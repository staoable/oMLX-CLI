from __future__ import annotations

import os
import re

from webapi.config import load_execution_policy_config

_ABS_PATH_RE = re.compile(r"(/Users/[^\s`\"'<>]+|/[^\s`\"'<>]+)")


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

    abs_paths = [m.group(0) for m in _ABS_PATH_RE.finditer(s)]
    if cfg.enforce_workspace_boundary and mutating_re.search(s):
        for p in abs_paths:
            p_abs = os.path.abspath(p)
            if not p_abs.startswith(cwd.rstrip("/") + "/") and p_abs != cwd:
                return False, f"写操作路径越界：{p}", False

    if confirm_each and high_risk_re.search(s):
        return True, "检测到高风险命令，需要人工确认", True
    return True, "", False
