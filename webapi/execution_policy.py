# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
from __future__ import annotations

import os
import re

from webapi.config import load_execution_policy_config

_ABS_PATH_RE = re.compile(r"(/Users/[^\s`\"'<>]+|/[^\s`\"'<>]+)")


def _abs_paths_for_workspace_boundary(cmd: str) -> list[str]:
    """从命令串中提取「看起来像绝对路径」的片段，供工作区边界检查。

    需排除 ``~/.foo`` 中第二个 ``/`` 被误匹配成 ``/.foo``，以及 ``BAR/.foo`` 等相对后缀。
    """
    out: list[str] = []
    for m in _ABS_PATH_RE.finditer(cmd):
        p = m.group(0)
        i = m.start()
        if i > 0:
            prev = cmd[i - 1]
            if prev == "~":
                continue
            if prev.isalnum() or prev == "_":
                continue
        out.append(p)
    return out


def check_command_policy(cmd: str, cwd: str, confirm_each: bool) -> tuple[bool, str, bool]:
    cfg = load_execution_policy_config()
    blocklist_re = re.compile(cfg.blocklist_pattern, re.IGNORECASE)
    high_risk_re = re.compile(cfg.high_risk_pattern, re.IGNORECASE)
    mutating_re = re.compile(cfg.mutating_pattern, re.IGNORECASE)
    s = (cmd or "").strip()
    if not s:
        return False, "空命令", False
    if blocklist_re.search(s):
        return False, "命中系统级黑名单命令", False

    allow_raw = (cfg.allowlist_pattern or "").strip()
    if allow_raw:
        allow_re = re.compile(allow_raw, re.IGNORECASE)
        if not allow_re.search(s):
            return False, "未命中允许执行的命令白名单（OMLXCLI_EXEC_ALLOWLIST_RE）", False

    abs_paths = _abs_paths_for_workspace_boundary(s)
    if cfg.enforce_workspace_boundary and mutating_re.search(s):
        cwd_bound = os.path.realpath(os.path.abspath(cwd))
        sep = os.sep
        prefix = cwd_bound.rstrip(sep) + sep
        for p in abs_paths:
            p_abs = os.path.realpath(os.path.abspath(p))
            if not (p_abs == cwd_bound or p_abs.startswith(prefix)):
                return False, f"写操作路径越界：{p}", False

    if confirm_each and high_risk_re.search(s):
        return True, "检测到高风险命令，需要人工确认", True
    return True, "", False
