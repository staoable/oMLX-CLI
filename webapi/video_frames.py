# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
"""将 data URL 视频转为 chat/completions 可用的多帧 image_url。

多数 OpenAI 兼容上游不识别 ``input_video``，会导致模型只看到纯文本。
此处用 ffmpeg 均匀抽帧为 JPEG，与仓库内 ``.omlxcli/skills/video.py`` 策略一致。
"""

from __future__ import annotations

import base64
import glob
import os
import shutil
import subprocess
import tempfile
from typing import Any


def parse_data_url(data_url: str) -> tuple[bytes, str]:
    """解析 ``data:<mime>;base64,<payload>``，返回 (解码字节, 声明的 MIME 小写前缀)。"""
    s = (data_url or "").strip()
    if not s.startswith("data:"):
        raise ValueError("附件不是合法的 data URL")
    comma = s.find(",")
    if comma < 0:
        raise ValueError("data URL 缺少逗号后的载荷")
    meta = s[5:comma]
    payload = s[comma + 1 :]
    if "base64" not in meta:
        raise ValueError("仅支持 base64 编码的 data URL")
    mime = "application/octet-stream"
    if ";" in meta:
        mime = meta.split(";", 1)[0].strip().lower() or mime
    else:
        mime = meta.strip().lower() or mime
    raw = base64.b64decode(payload, validate=False)
    return raw, mime


def _video_attach_max_bytes() -> int:
    raw = (os.getenv("OMLXCLI_VIDEO_ATTACH_MAX_BYTES") or str(256 * 1024 * 1024)).strip()
    try:
        n = int(raw)
    except ValueError:
        return 256 * 1024 * 1024
    return max(16 * 1024 * 1024, min(n, 1024 * 1024 * 1024))


def _video_attach_frames() -> int:
    raw = (os.getenv("OMLXCLI_VIDEO_ATTACH_FRAMES") or "12").strip()
    try:
        n = int(raw)
    except ValueError:
        return 12
    return max(1, min(n, 32))


def _suffix_for_mime(mime: str) -> str:
    m = (mime or "").lower()
    if m == "video/quicktime":
        return ".mov"
    if m == "video/webm":
        return ".webm"
    if m == "video/x-matroska":
        return ".mkv"
    if m == "video/mp4" or m.endswith("mp4"):
        return ".mp4"
    return ".mp4"


def _ffprobe_duration(path: str) -> float:
    if not shutil.which("ffprobe"):
        raise RuntimeError("未找到 ffprobe（通常随 ffmpeg 安装）。请先安装 ffmpeg。")
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            path,
        ],
        timeout=30,
    )
    return float(out.decode().strip() or "0")


def video_data_url_to_chat_parts(
    *,
    data_url: str,
    name: str,
    mime: str,
) -> list[dict[str, Any]]:
    """返回若干条 content part：说明文字 + 多帧 ``image_url``。"""
    raw, declared = parse_data_url(data_url)
    cap = _video_attach_max_bytes()
    if len(raw) > cap:
        mb = cap / (1024 * 1024)
        raise ValueError(f"视频过大（>{mb:.0f} MB），已拒绝抽帧。可在环境变量 OMLXCLI_VIDEO_ATTACH_MAX_BYTES 中调大上限。")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("未找到 ffmpeg。视频附件需抽帧后才能送给模型，请先安装 ffmpeg（例如 brew install ffmpeg）。")

    frames_n = _video_attach_frames()
    parts: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="omlxcli_webui_vid_") as tmp:
        vpath = os.path.join(tmp, f"in{_suffix_for_mime(mime or declared)}")
        with open(vpath, "wb") as fh:
            fh.write(raw)
        duration = _ffprobe_duration(vpath)
        frames_n = max(1, min(frames_n, 32))
        fps = max(0.05, frames_n / max(duration, 0.1))
        out_pat = os.path.join(tmp, "frame_%03d.jpg")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                vpath,
                "-vf",
                f"fps={fps:.6f}",
                "-frames:v",
                str(frames_n),
                "-q:v",
                "3",
                out_pat,
            ],
            check=True,
            timeout=300,
        )
        paths = sorted(glob.glob(os.path.join(tmp, "frame_*.jpg")))
        if not paths:
            raise RuntimeError("ffmpeg 未生成任何帧图，请确认视频编码是否受支持。")

        label = (name or "video").strip() or "video"
        parts.append(
            {
                "type": "text",
                "text": (
                    f"\n\n（以下为视频附件「{label}」按时间均匀抽取的 {len(paths)} 张关键帧（JPEG），"
                    f"时长约 {duration:.1f} 秒；请结合这些画面回答上文问题。）\n"
                ),
            }
        )
        for fp in paths:
            with open(fp, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode("ascii")
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    return parts
