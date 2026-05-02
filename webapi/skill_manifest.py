from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import ast


def load_skill_manifests(skills_dir: str) -> dict[str, Any]:
    """读取 `.omlxcli/skills/manifests/skills.json` 中的技能元数据。"""
    p = Path(skills_dir) / "manifests" / "skills.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
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
    if n_pos < min_pos:
        return False, f"{func_name} 至少需要 {min_pos} 个位置参数"
    if n_pos + n_kw > max_total:
        return False, f"{func_name} 参数过多（>{max_total}）"
    return True, ""
