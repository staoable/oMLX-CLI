# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
"""run_shell 前置启发式：拦截典型全屏 TUI，避免在无头 subprocess 中挂死至超时。"""

from __future__ import annotations

import os
import re

# 首段命令名为下列之一时拒绝（捕获常见 Bubble Tea / ncurses 全屏工具）。
# 不含 `top`：避免误判；用户可用 `top -l 1` 等自行承担。
_TUI_PRIMARY_BINS: frozenset[str] = frozenset(
    {
        "mactop",
        "htop",
        "btop",
        "vim",
        "nvim",
        "vi",
        "nano",
        "emacs",
        "tmux",
        "screen",
    }
)


def _segment_lead_executable(segment: str) -> str | None:
    s = (segment or "").strip()
    if not s:
        return None
    while True:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\S+\s+", s)
        if m:
            s = s[m.end() :].lstrip()
            continue
        m2 = re.match(r"^sudo\s+", s, re.IGNORECASE)
        if m2:
            s = s[m2.end() :].lstrip()
            continue
        break
    m3 = re.match(r'^["\']?([^\s"\']+)["\']?', s)
    if not m3:
        return None
    tok = m3.group(1)
    return os.path.basename(tok).lower()


def list_shell_lead_bins(cmd: str) -> list[str]:
    """按 ``|`` / ``&&`` / ``||`` 粗分条，取每条的首个可执行文件名（小写 basename）。"""
    raw = (cmd or "").strip()
    if not raw:
        return []
    parts = re.split(r"\s*(?:&&|\|\|)\s*|\s*\|\s*", raw)
    out: list[str] = []
    for part in parts:
        b = _segment_lead_executable(part)
        if b:
            out.append(b)
    return out


def blocked_interactive_tui_message(cmd: str) -> str | None:
    """若应拒执行，返回 stderr 文案；否则 None。"""
    for b in list_shell_lead_bins(cmd):
        if b in _TUI_PRIMARY_BINS:
            return (
                f"已跳过交互式全屏程序 `{b}`：oMLXCli 的 run_shell 为无头 subprocess（无真实终端尺寸与键盘），"
                f"此类 TUI 极易挂起直至超时。\n"
                f"建议：改用该工具的**非 TUI** 模式（若存在，如部分版本支持 --headless/--count，请先 `{b} --help` 核实）；"
                "或在 macOS 上用 `powermetrics`（注意带采样次数如 `-n 1`）、`pmset -g therm` 快照等；在本地真终端手动运行 TUI。"
            )
    return None


_STREAMING_PMSET_THERMLOG = re.compile(r"\bpmset\s+-g\s+thermlog\b", re.IGNORECASE)


def wrap_known_streaming_shell_commands(cmd: str) -> str:
    """`pmset -g thermlog` 会持续输出不退出，无头执行会直至超时；包一层 ``head`` 取前几屏。"""
    s = (cmd or "").strip()
    if not s:
        return s
    if re.search(r"\|\s*head\b", s, re.IGNORECASE):
        return s
    if not _STREAMING_PMSET_THERMLOG.search(s):
        return s
    return f"( {s} ) 2>&1 | head -n 80"
