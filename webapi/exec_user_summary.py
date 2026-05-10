# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
"""将本轮 shell/skill 执行结果整理为面向普通用户的中文 Markdown 摘要。"""

from __future__ import annotations

from typing import Any


def record_exec_digest(
    digest: list[dict[str, Any]],
    *,
    kind: str,
    command: str,
    exit_code: Any,
    stdout: str = "",
    stderr: str = "",
    blocked: bool = False,
    pending_confirm: bool = False,
) -> None:
    digest.append(
        {
            "kind": kind,
            "command": (command or "").strip(),
            "exit_code": exit_code,
            "stdout": str(stdout or ""),
            "stderr": str(stderr or ""),
            "blocked": blocked,
            "pending_confirm": pending_confirm,
        }
    )


def _clip(s: str, n: int = 420) -> str:
    t = " ".join((s or "").split())
    if len(t) <= n:
        return t
    return t[:n] + "…"


def _exit_label(ec: Any, it: dict[str, Any]) -> str:
    if it.get("pending_confirm"):
        return "等待确认（尚未在服务器上执行）"
    if it.get("blocked"):
        return "被安全策略拦截（未执行）"
    try:
        n = int(ec)
    except (TypeError, ValueError):
        return f"退出码 {ec}"
    if n == 0:
        return "成功（exit_code=0）"
    if n == 124:
        return "超时（exit_code=124，常见：程序持续输出或等待交互）"
    if n == 125:
        return "未执行（exit_code=125，如全屏 TUI 被服务端拒绝）"
    return f"未成功（exit_code={n}）"


def markdown_exec_digest(digest: list[dict[str, Any]]) -> str:
    if not digest:
        return ""
    lines: list[str] = ["### 命令执行摘要", ""]
    failed = False
    for it in digest:
        ec = it.get("exit_code")
        if it.get("blocked") or it.get("pending_confirm"):
            failed = True
            continue
        try:
            if int(ec) != 0:
                failed = True
        except (TypeError, ValueError):
            failed = True
    if failed:
        lines.append("**任务状态**：**未全部成功**——下列至少一步失败、被拦截或仍在等待你确认。")
    else:
        lines.append("**任务状态**：**命令层面已成功**（进程退出码为 0）。若你仍觉得「没结果」，多半是命令输出里没有你要的数据，需要换命令或补充上下文。")
    lines.append("")
    for i, it in enumerate(digest, 1):
        kind = str(it.get("kind") or "shell")
        cmd = str(it.get("command") or "")[:220]
        label = _exit_label(it.get("exit_code"), it)
        lines.append(f"{i}. **{kind}** `{cmd}` → **{label}**")
        err = (it.get("stderr") or "").strip()
        out = (it.get("stdout") or "").strip()
        if err:
            lines.append(f"   - **错误/提示**：{_clip(err)}")
        if out:
            show_out = bool(err) or bool(it.get("pending_confirm")) or bool(it.get("blocked"))
            if not show_out:
                try:
                    show_out = int(it.get("exit_code") or 0) != 0
                except (TypeError, ValueError):
                    show_out = True
            if show_out or len(out) < 500:
                lines.append(f"   - **输出摘录**：{_clip(out)}")
        lines.append("")
    lines.append("如需我继续（换命令、解读输出、写脚本），请直接说你的目标。")
    return "\n".join(lines)


def merge_answer_with_exec_digest(answer: str, digest_md: str) -> str:
    """把摘要接在模型答复后；避免重复插入。"""
    if not digest_md.strip():
        return answer or ""
    if "### 命令执行摘要" in (answer or ""):
        return answer or ""
    base = (answer or "").rstrip()
    if base:
        return f"{base}\n\n---\n{digest_md}"
    return digest_md
