"""跨 session 笔记。

笔记落到仓库根目录下的 `.aicli/notes/`，便于 git 控制粒度。
本 skill 是为了让模型/用户能在退出 OI 后下次进来还能看到上次留下的上下文。
"""

from __future__ import annotations

import os

from _meta import skill


def _notes_dir() -> str:
    """定位 .aicli/notes/，自动创建。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target = os.path.join(here, "notes")
    os.makedirs(target, exist_ok=True)
    return target


def _safe_path(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    if not safe:
        raise ValueError("笔记名为空")
    if "." not in safe:
        safe += ".md"
    return os.path.join(_notes_dir(), safe)


@skill(
    desc="保存一段笔记到 .aicli/notes/<name>.md（同名覆盖）。",
    examples=["note_save('todo', '- 检查 oMLX 配置\\n- 跑 bench')"],
)
def note_save(name: str, content: str) -> str:
    """返回写入的绝对路径。"""
    path = _safe_path(name)
    with open(path, "w") as fh:
        fh.write(content)
    return path


@skill(
    desc="读取 .aicli/notes/<name>.md 全部内容。不存在时返回空字符串。",
    examples=["note_load('todo')"],
)
def note_load(name: str) -> str:
    path = _safe_path(name)
    if not os.path.isfile(path):
        return ""
    with open(path, "r", errors="replace") as fh:
        return fh.read()


@skill(
    desc="列出 .aicli/notes/ 下所有笔记的文件名。",
    examples=["note_list()"],
)
def note_list() -> list[str]:
    return sorted(os.listdir(_notes_dir()))
