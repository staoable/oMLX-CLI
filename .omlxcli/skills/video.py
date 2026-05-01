"""视频分析工具。

策略：
  - ffmpeg 抽 N 帧（默认 16）→ 多 image_url content part（chat/completions 可处理）
  - ffmpeg 抽音轨 → 本地 mlx-whisper 转写为文本，与画面 prompt 一起拼

Gemma 4 是 vision-language 模型，本身不能直接吃 audio；oMLX 的
`/v1/audio/transcriptions` 端点是占位（不实际处理）。所以音轨走本地
mlx-whisper 转写，转写失败则跳过并附上原因，画面分析仍然进行。

依赖外部命令：ffmpeg / ffprobe（`brew install ffmpeg`）。
"""

from __future__ import annotations

from _media import (
    call_omlx_multimodal,
    image_to_data_url,
    resolve_path,
    transcribe_audio,
    video_split,
)
from _meta import skill


@skill(
    desc="拆视频为 N 帧关键画面 + 音轨（音轨走 STT 转写），合并送给 LLM 分析。返回字符串。",
    examples=[
        "video_summarize('/tmp/clip.mp4')",
        "video_summarize('~/Movies/demo.mov', frames=8, prompt='这段在演示什么？')",
    ],
)
def video_summarize(
    video_path: str,
    frames: int = 16,
    prompt: str = "结合关键画面与音轨转写，先 1 句话概述这段视频，再用 3 条要点说明内容。",
    language: str | None = None,
) -> str:
    """单段视频综合分析。frames 默认 16；language 用于 STT 加速。"""
    abs_path = resolve_path(video_path)
    frame_paths, audio_path, duration = video_split(abs_path, frames=frames)

    transcript = ""
    transcript_note = ""
    if audio_path:
        try:
            transcript = transcribe_audio(audio_path, language=language)
        except Exception as exc:  # noqa: BLE001
            transcript_note = f"（音轨转写失败、已跳过：{exc}）"

    intro_lines = [
        f"以下附件来自一段视频（时长约 {duration:.1f} 秒）：",
        f"- 前 {len(frame_paths)} 张图片是按时间均匀抽样的关键画面。",
    ]
    if transcript:
        intro_lines.append(
            f"- 音轨转写文本如下：\n\"\"\"\n{transcript}\n\"\"\""
        )
    elif transcript_note:
        intro_lines.append(transcript_note)
    else:
        intro_lines.append("- 无音轨。")
    intro_lines.append(f"\n用户问题：{prompt}")

    parts: list[dict] = [{"type": "text", "text": "\n".join(intro_lines)}]
    for fp in frame_paths:
        parts.append({"type": "image_url", "image_url": {"url": image_to_data_url(fp)}})
    return call_omlx_multimodal(parts, timeout=600)
