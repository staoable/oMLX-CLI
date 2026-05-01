"""图像分析工具。

把本地图片直接喂给 Gemma 4 多模态推理（绕开 OI 主对话流程，单独发一次 multimodal
请求），返回模型的纯文字描述/回答，便于在脚本/笔记里把视觉理解结果拿来继续处理。

注意：用户在终端里直接 `%img <path> <prompt>` 已是首选交互；
本 skill 是给模型（或自动化脚本）"按需调用"用的——比如读完一段笔记里
存了截图路径，模型可以自己 `vision_describe(p)` 拿到内容继续推理。
"""

from __future__ import annotations

from _media import call_omlx_multimodal, image_to_data_url, resolve_path
from _meta import skill


@skill(
    desc="把本地图片送给多模态模型，返回它的描述/回答（纯字符串）。",
    examples=[
        "vision_describe('/tmp/screenshot.png')",
        "vision_describe('~/Desktop/cat.jpg', '这是什么品种？')",
    ],
)
def vision_describe(image_path: str, prompt: str = "请仔细描述这张图片，并回答用户可能关心的问题。") -> str:
    """单图分析。返回模型输出文本。"""
    abs_path = resolve_path(image_path)
    parts = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_to_data_url(abs_path)}},
    ]
    return call_omlx_multimodal(parts)


@skill(
    desc="把多张本地图片一次送给多模态模型对比/汇总。返回字符串。",
    examples=["vision_compare(['/tmp/a.png','/tmp/b.png'], '两张图最大差异是什么？')"],
)
def vision_compare(image_paths: list[str], prompt: str = "对比这些图片并回答。") -> str:
    """多图联合分析。"""
    if not image_paths:
        raise ValueError("image_paths 不能为空")
    parts: list[dict] = [{"type": "text", "text": prompt}]
    for p in image_paths:
        abs_path = resolve_path(p)
        parts.append({"type": "image_url", "image_url": {"url": image_to_data_url(abs_path)}})
    return call_omlx_multimodal(parts)
