from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class ExecutionPolicyConfig:
    mode: str
    blocklist_pattern: str
    high_risk_pattern: str
    mutating_pattern: str
    enforce_workspace_boundary: bool


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_execution_policy_config() -> ExecutionPolicyConfig:
    mode = os.getenv("OMLXCLI_EXEC_POLICY_MODE", "strict").strip().lower() or "strict"
    default_blocklist = r"\b(mkfs|fdisk|diskutil\s+erase|shutdown|reboot|halt|poweroff|launchctl\s+bootout)\b"
    default_high_risk = r"\b(rm\s+-rf|sudo\b|mkfs|dd\s+if=|chmod\s+777|shutdown|reboot|launchctl|diskutil\s+erase)\b"
    default_mutating = r"^\s*(rm|mv|cp|mkdir|touch|tee|sed\s+-i|python\s+.*-c|node\s+.*-e|cat\s+>|\>\s*\/)"
    if mode == "readonly":
        default_mutating = r".+"
    return ExecutionPolicyConfig(
        mode=mode,
        blocklist_pattern=os.getenv("OMLXCLI_EXEC_BLOCKLIST_RE", default_blocklist),
        high_risk_pattern=os.getenv("OMLXCLI_EXEC_HIGH_RISK_RE", default_high_risk),
        mutating_pattern=os.getenv("OMLXCLI_EXEC_MUTATING_RE", default_mutating),
        enforce_workspace_boundary=_env_bool("OMLXCLI_EXEC_ENFORCE_WORKSPACE_BOUNDARY", True),
    )
