"""音频分析工具（先转写、后回答）。

设计：Gemma 4 是 vision-language 模型，本身不能直接吃 audio；oMLX 的
`/v1/audio/transcriptions` 端点是占位（不实际处理）。所以这里走两段式：
  1. 用本地 `mlx-whisper` 转写音频成文字（`transcribe_audio`，纯本地推理）
  2. 把转写 + 用户 prompt 拼成纯文本喂回 chat 模型 (`call_omlx_multimodal`)

权重首次使用从 HuggingFace 自动拉取，缓存在 `~/.cache/huggingface/`。
默认仓库 `mlx-community/whisper-large-v3-mlx-4bit`，可用 env `_AICLI_STT_MODEL` 覆盖。
"""

from __future__ import annotations

from _media import call_omlx_multimodal, resolve_path, transcribe_audio
from _meta import skill


@skill(
    desc="音频转写 + 内容回答（先 mlx-whisper 本地转文字，再让 LLM 基于转写回答）。",
    examples=[
        "audio_transcribe('~/Downloads/meeting.m4a')",
        "audio_transcribe('/tmp/voice.mp3', '转写后用 3 个要点总结')",
        "audio_transcribe('voice.wav', language='zh')  # 显式指定语种",
    ],
)
def audio_transcribe(
    audio_path: str,
    prompt: str = "请基于上面这段音频转写内容，给出准确、简洁的中文回答。",
    language: str | None = None,
) -> str:
    """单段音频分析（≤30MB）。返回模型最终文字回答。

    - prompt 为空字符串时仅返回原始转写文本（不再二次调 LLM）。
    - language 可显式指定 ISO 639-1（如 'zh'/'en'），加速 STT 推理。
    """
    abs_path = resolve_path(audio_path)
    transcript = transcribe_audio(abs_path, language=language)

    if not prompt or not prompt.strip():
        return transcript

    composed = (
        f"以下是用户提供的音频转写内容（来源: {abs_path}）：\n"
        f'"""\n{transcript}\n"""\n\n'
        f"用户问题：{prompt}"
    )
    return call_omlx_multimodal([{"type": "text", "text": composed}], timeout=300)


@skill(
    desc="只做音频转写，返回纯文字，不再调 LLM 二次回答。",
    examples=["audio_transcribe_only('/tmp/voice.m4a')"],
)
def audio_transcribe_only(audio_path: str, language: str | None = None) -> str:
    """只调本地 mlx-whisper 转写，返回纯转写文本。"""
    abs_path = resolve_path(audio_path)
    return transcribe_audio(abs_path, language=language)
