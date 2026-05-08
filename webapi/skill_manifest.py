# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import ast

from webapi.logging_utils import log_event


def load_skill_manifests(skills_dir: str) -> dict[str, Any]:
    """读取 `.omlxcli/skills/manifests/skills.json` 中的技能元数据。"""
    p = Path(skills_dir) / "manifests" / "skills.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log_event(
            "skill_manifest_load_error",
            skills_dir=skills_dir,
            file=str(p),
            error_type=type(exc).__name__,
            message=str(exc)[:300],
        )
        return {}
    skills = data.get("skills")
    return skills if isinstance(skills, dict) else {}


def validate_skill_ast_call(func_name: str, node: ast.Call, manifests: dict[str, Any]) -> tuple[bool, str]:
    """对 AST 调用做轻量校验（防 **kwargs、参数数量异常）。"""
    meta = manifests.get(func_name)
    if not meta or not isinstance(meta, dict):
        return True, ""

    if node.keywords and any(kw.arg is None for kw in node.keywords):
        return False, "技能调用不支持 **kwargs 展开"
    if any(isinstance(a, ast.Starred) for a in node.args):
        return False, "技能调用不支持 *args 展开"

    min_pos = int(meta.get("min_positional_args", 1))
    max_total = int(meta.get("max_total_args", 48))
    n_pos = len(node.args)
    n_kw = len(node.keywords)
    if n_pos + n_kw < min_pos:
        return False, f"{func_name} 至少需要 {min_pos} 个参数"
    if n_pos + n_kw > max_total:
        return False, f"{func_name} 参数过多（>{max_total}）"

    banned = (
        ast.Call,
        ast.Lambda,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
        ast.Await,
        ast.Yield,
        ast.YieldFrom,
        ast.NamedExpr,
    )
    for arg in list(node.args) + [kw.value for kw in node.keywords]:
        for child in ast.walk(arg):
            if isinstance(child, banned):
                return False, "技能参数中包含不允许的表达式节点（如调用/推导式/lambda）"
    return True, ""
