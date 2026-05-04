# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class ExecutionPolicyConfig:
    """执行策略配置（可由模板 + 环境变量叠加）。"""

    mode: str
    template: str
    blocklist_pattern: str
    high_risk_pattern: str
    mutating_pattern: str
    enforce_workspace_boundary: bool
    # 非空时：命令行须匹配该正则（OMLXCLI_EXEC_ALLOWLIST_RE），否则拒绝。
    allowlist_pattern: str


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_execution_policy_config() -> ExecutionPolicyConfig:
    """加载执行策略。

    - `OMLXCLI_EXEC_POLICY_TEMPLATE`：`strict` / `readonly` / `dev`（预设组合）
    - `OMLXCLI_EXEC_POLICY_MODE`：若设置则作为最终 **mode**（覆盖模板推断的 mode）
    - `OMLXCLI_EXEC_*_RE` / `OMLXCLI_EXEC_ENFORCE_WORKSPACE_BOUNDARY`：逐项覆盖模板默认值
    - `OMLXCLI_EXEC_ALLOWLIST_RE`：可选白名单；设置后仅允许匹配该正则的命令
    """
    template = (os.getenv("OMLXCLI_EXEC_POLICY_TEMPLATE") or "").strip().lower()
    explicit_mode = (os.getenv("OMLXCLI_EXEC_POLICY_MODE") or "").strip().lower()

    blocklist = r"\b(mkfs|fdisk|diskutil\s+erase|shutdown|reboot|halt|poweroff|launchctl\s+bootout)\b"
    high_risk = r"\b(rm\s+-rf|sudo\b|mkfs|dd\s+if=|chmod\s+777|shutdown|reboot|launchctl|diskutil\s+erase)\b"
    mutating = r"^\s*(rm|mv|cp|mkdir|touch|tee|sed\s+-i|python\s+.*-c|node\s+.*-e|cat\s+>|\>\s*\/)"
    enforce_default = True

    inferred_mode = "strict"
    if template == "readonly":
        inferred_mode = "readonly"
    elif template == "dev":
        inferred_mode = "strict"
        blocklist = r"\b(mkfs|diskutil\s+erase|shutdown|reboot|halt|poweroff)\b"
        high_risk = r"\b(rm\s+-rf|sudo\b|mkfs|dd\s+if=|diskutil\s+erase)\b"
        enforce_default = False

    mode = explicit_mode or inferred_mode
    if mode == "readonly":
        mutating = r".+"

    tpl_label = template if template else "none"

    allowlist_raw = (os.getenv("OMLXCLI_EXEC_ALLOWLIST_RE") or "").strip()

    return ExecutionPolicyConfig(
        mode=mode,
        template=tpl_label,
        blocklist_pattern=os.getenv("OMLXCLI_EXEC_BLOCKLIST_RE", blocklist),
        high_risk_pattern=os.getenv("OMLXCLI_EXEC_HIGH_RISK_RE", high_risk),
        mutating_pattern=os.getenv("OMLXCLI_EXEC_MUTATING_RE", mutating),
        enforce_workspace_boundary=_env_bool(
            "OMLXCLI_EXEC_ENFORCE_WORKSPACE_BOUNDARY", enforce_default
        ),
        allowlist_pattern=allowlist_raw,
    )
