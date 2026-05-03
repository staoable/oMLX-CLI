"""多模态共享工具（不被 skill 注册扫描，仅供 vision/audio/video 与 cli_input patch 共用）。

设计要点：
- 路径解析、扩展名归类、ffmpeg 调用、oMLX multimodal 直连。
- 不依赖 OI 内部实现：cli_input patch 直接 push LMC 消息时只需路径校验；
  skill 模块直接发 HTTP 请求时复用 _call_oMLX_multimodal。
"""

from __future__ import annotations

import base64
import glob
import hashlib
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif"}
_AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".flac", ".ogg", ".aac", ".aiff", ".opus"}
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg"}

_MAX_AUDIO_BYTES = 30 * 1024 * 1024
_MAX_VIDEO_BYTES = 500 * 1024 * 1024
_DEFAULT_VIDEO_FRAMES = 16

# 本地 STT：oMLX 0.3.x 的 /v1/audio/transcriptions 端点是占位，实际不能加载/执行
# whisper（参考 oMLX 主页能力清单 + GitHub issue #958）。所以转写走 Apple MLX 官方
# 维护的 `mlx-whisper`（pip 包），权重从 HuggingFace 拉取，纯本地推理。
# 默认仓库：4bit 量化的 large-v3，约 1.5GB，中文识别质量好且速度快。
_DEFAULT_STT_REPO = "mlx-community/whisper-large-v3-mlx-4bit"


def media_kind(path: str) -> str | None:
    """根据扩展名归类：'image' / 'audio' / 'video' / None。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext in _VIDEO_EXTS:
        return "video"
    return None


def resolve_path(path: str) -> str:
    """展开 ~、转绝对路径；不存在时抛 FileNotFoundError。"""
    abs_path = os.path.abspath(os.path.expanduser(path.strip().strip('"').strip("'")))
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"文件不存在: {abs_path}")
    return abs_path


def cache_dir() -> str:
    """`.aicli/cache/` —— 视频抽帧/音轨临时存放目录。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(here, "cache")
    os.makedirs(d, exist_ok=True)
    return d


def _ext_to_format(ext: str, kind: str) -> str:
    """oMLX/Gemma 期望的 format 字段（image/audio）。"""
    e = ext.lstrip(".").lower()
    if kind == "image":
        return "jpeg" if e in ("jpg", "jpeg") else e
    if kind == "audio":
        if e == "m4a":
            return "m4a"
        if e == "aiff":
            return "wav"
        return e
    return e


def _heic_to_jpeg_bytes(abs_path: str) -> bytes:
    """把 HEIC/HEIF 解码为 JPEG 字节流。

    Gemma 4 / 多数 CLIP-style 视觉塔不识别 HEIC bitstream，必须转 JPEG。
    优先用 macOS 原生 `sips`（开箱即用，无需 pip）；
    没有 sips 时退回 pillow-heif（需自己 pip install）。
    """
    if shutil.which("sips"):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run(
                ["sips", "-s", "format", "jpeg", abs_path, "--out", tmp_path],
                check=True,
                capture_output=True,
                timeout=30,
            )
            with open(tmp_path, "rb") as fh:
                return fh.read()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    try:
        import pillow_heif  # type: ignore  # noqa: WPS433

        pillow_heif.register_heif_opener()
        from PIL import Image as _Img  # type: ignore
        import io as _io

        img = _Img.open(abs_path).convert("RGB")
        buf = _io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        return buf.getvalue()
    except ImportError as exc:
        raise RuntimeError(
            "HEIC/HEIF 图片解码失败：未找到 `sips`（macOS 原生工具）也未安装 "
            "`pillow-heif`。请运行 `pip install pillow-heif`，或先用 `sips -s "
            "format jpeg in.heic --out out.jpg` 手动转换。"
        ) from exc


def image_to_data_url(path: str) -> str:
    """读图 → 'data:image/<ext>;base64,<...>'.

    HEIC/HEIF 自动转 JPEG（Gemma 视觉塔通常不识别 HEIC bitstream）。
    """
    abs_path = resolve_path(path)
    raw_ext = os.path.splitext(abs_path)[1].lower().lstrip(".")

    if raw_ext in ("heic", "heif"):
        data = _heic_to_jpeg_bytes(abs_path)
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"

    fmt = _ext_to_format(raw_ext, "image")
    with open(abs_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return f"data:image/{fmt};base64,{b64}"


def _ffprobe_duration(path: str) -> float:
    """ffprobe 拿视频时长（秒）。失败抛 RuntimeError。"""
    if not shutil.which("ffprobe"):
        raise RuntimeError("缺 ffprobe（与 ffmpeg 同包）。请先 `brew install ffmpeg`。")
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
        timeout=20,
    )
    return float(out.decode().strip())


def video_split(
    video_path: str,
    frames: int = _DEFAULT_VIDEO_FRAMES,
) -> tuple[list[str], str | None, float]:
    """ffmpeg 抽 N 帧 + 抽音轨；返回 (帧路径列表, 音轨路径|None, 时长秒)。

    缓存到 `.aicli/cache/vid_<hash>/` 以加速重复分析同一文件。
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("缺 ffmpeg。请先 `brew install ffmpeg`。")

    abs_path = resolve_path(video_path)
    size = os.path.getsize(abs_path)
    if size > _MAX_VIDEO_BYTES:
        raise ValueError(
            f"视频文件过大 ({size / 1024 / 1024:.1f} MB > "
            f"{_MAX_VIDEO_BYTES / 1024 / 1024:.0f} MB)"
        )

    duration = _ffprobe_duration(abs_path)
    frames = max(1, min(64, int(frames)))

    sig = f"{abs_path}|{os.path.getmtime(abs_path)}|{frames}"
    h = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
    out_dir = os.path.join(cache_dir(), f"vid_{h}")

    frame_glob = os.path.join(out_dir, "frame_*.jpg")
    audio_path = os.path.join(out_dir, "audio.m4a")

    if os.path.isdir(out_dir) and glob.glob(frame_glob):
        existing = sorted(glob.glob(frame_glob))
        return existing, (audio_path if os.path.exists(audio_path) else None), duration

    os.makedirs(out_dir, exist_ok=True)

    fps = max(0.05, frames / max(duration, 0.1))
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            abs_path,
            "-vf",
            f"fps={fps:.6f}",
            "-frames:v",
            str(frames),
            "-q:v",
            "3",
            os.path.join(out_dir, "frame_%03d.jpg"),
        ],
        check=True,
        timeout=300,
    )

    audio_proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            abs_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            audio_path,
        ],
        capture_output=True,
        timeout=300,
    )
    if audio_proc.returncode != 0 or not os.path.exists(audio_path):
        audio_path_final: str | None = None
    else:
        audio_path_final = audio_path

    return sorted(glob.glob(frame_glob)), audio_path_final, duration


def _llm_endpoint() -> tuple[str, str, str]:
    """读取当前推理端点 (api_base, api_key, model)。

    Web 会话执行 `run_skill` 时，由 `webapi.session_engine` 在调用前注入
    `_AICLI_API_BASE` / `_AICLI_API_KEY` / `_AICLI_LLM_MODEL`，与当前会话所选
    模型设置一致。未注入时视为配置缺失。
    """
    api_base = (os.getenv("_AICLI_API_BASE") or "").strip().rstrip("/")
    api_key = (os.getenv("_AICLI_API_KEY") or "").strip() or "EMPTY"
    model = (os.getenv("_AICLI_LLM_MODEL") or "").strip() or "default_model"
    if not api_base:
        raise RuntimeError(
            "缺少推理端点：请在 Web 中为会话选择模型设置并保存后再调用依赖模型的技能。"
        )
    # OI 的 LiteLLM 习惯前缀是 openai/，去掉
    if model.startswith("openai/"):
        model = model[len("openai/"):]
    return api_base, api_key, model


def _resolve_stt_model() -> str:
    """决定 mlx-whisper 用哪个权重仓库 / 本地路径。

    优先级：env `_AICLI_STT_MODEL` > env `OI_STT_MODEL` > 默认 `large-v3-mlx-4bit`。
    取值可以是 HuggingFace repo（如 `mlx-community/whisper-large-v3-mlx-4bit`）
    或本地权重目录路径——`mlx_whisper.transcribe` 的 `path_or_hf_repo` 接受两者。
    """
    env_pick = os.getenv("_AICLI_STT_MODEL") or os.getenv("OI_STT_MODEL")
    if env_pick:
        return env_pick.removeprefix("openai/")
    return _DEFAULT_STT_REPO


def _import_mlx_whisper():
    """懒加载 mlx_whisper：首次调用时才 import（numba/mlx 启动重，~2s）。

    没装时抛 RuntimeError，里头给出明确的修复指令。
    """
    try:
        import mlx_whisper  # type: ignore  # noqa: WPS433
    except ImportError as exc:
        raise RuntimeError(
            "本地 STT 缺包：未安装 `mlx-whisper`。\n"
            "原因：oMLX 0.3.x 的 /v1/audio/transcriptions 端点是占位（不实际处理音频），\n"
            "本仓库改为用 Apple MLX 官方维护的本地 mlx-whisper（仅 Apple Silicon macOS 官方支持）。\n"
            "修复（本仓库虚拟环境，推荐）：\n"
            "    ./bootstrap.sh\n"
            "    # 或：.venv/bin/python -m pip install -r requirements.txt\n"
            "请确认运行 Web / run_skill 的 Python 与安装依赖的解释器一致（勿混用 conda base 与 .venv）。\n"
            "若使用独立 conda 环境：conda run -n <env> pip install mlx-whisper"
        ) from exc
    return mlx_whisper


def transcribe_audio(
    audio_path: str,
    *,
    model: str | None = None,
    language: str | None = None,
) -> str:
    """本地 mlx-whisper 转写音频，返回纯文本。

    - `model`：HuggingFace repo 或本地权重目录；不传则按 `_resolve_stt_model()`。
    - `language`：传 `"zh"` / `"en"` 等强制语言；不传时 whisper 自动检测。
    - 接受任意 ffmpeg 能解码的音频（m4a/mp3/wav/flac/...）；mlx-whisper 内部会调 ffmpeg。
    - 首次调用某个 repo 时会从 HuggingFace 自动拉权重，缓存到 `~/.cache/huggingface/`。
    """
    abs_path = resolve_path(audio_path)
    size = os.path.getsize(abs_path)
    if size > _MAX_AUDIO_BYTES:
        raise ValueError(
            f"音频文件过大 ({size / 1024 / 1024:.1f} MB > "
            f"{_MAX_AUDIO_BYTES / 1024 / 1024:.0f} MB)"
        )

    repo = (model or _resolve_stt_model()).removeprefix("openai/")
    mlx_whisper = _import_mlx_whisper()

    kwargs: dict[str, Any] = {"path_or_hf_repo": repo}
    if language:
        kwargs["language"] = language

    try:
        result = mlx_whisper.transcribe(abs_path, **kwargs)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"mlx-whisper 转写失败 (model={repo}): {type(exc).__name__}: {exc}\n"
            "排查：\n"
            "  - 首次使用需联网从 HuggingFace 拉权重 (~1.5GB)；网络受限时可手动 "
            "`huggingface-cli download {repo}` 预下载。\n"
            "  - 想换更小/更快的模型：`export _AICLI_STT_MODEL=mlx-community/whisper-large-v3-turbo-q4`"
        ) from exc

    text = result.get("text") if isinstance(result, dict) else None
    if not text:
        raise RuntimeError(f"mlx-whisper 返回为空: {result}")
    return text.strip()


# 向后兼容别名：早期实现走 oMLX HTTP（已废弃，因为 oMLX 不实际支持 STT），
# 但 audio.py / video.py / open_interpreter_cli.py 已 import 了这个名字。
# 保留别名避免广撒网式改 import。
def call_omlx_transcriptions(
    audio_path: str,
    *,
    model: str | None = None,
    language: str | None = None,
    timeout: int = 600,  # noqa: ARG001 — 本地推理无需 HTTP timeout，留参数兼容旧调用
) -> str:
    return transcribe_audio(audio_path, model=model, language=language)


def call_omlx_multimodal(
    parts: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
    timeout: int = 180,
) -> str:
    """单轮 multimodal 请求，stream=False。返回模型输出文本。

    `parts` 必须是 OpenAI/Gemma multimodal 的 user content 数组：
    [{type:"text"...}, {type:"image_url"...}, {type:"input_audio"...}, ...]
    """
    api_base, api_key, model = _llm_endpoint()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": parts}],
        "stream": False,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        url=api_base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        raise RuntimeError(
            f"oMLX HTTP {exc.code}: {exc.reason}. 多模态可能不被当前后端支持。响应: {body[:500]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"oMLX 不可达 ({exc.reason})。请确认服务在线。") from exc

    try:
        return obj["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"oMLX 响应格式异常: {obj}") from exc
