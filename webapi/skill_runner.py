from __future__ import annotations

import ast
import builtins
import json
import os
import sys
from pathlib import Path
from typing import Any


def load_skills_registry() -> tuple[dict[str, Any], str]:
    root = Path(__file__).resolve().parent.parent
    skills_dir = Path(os.getenv("OMLXCLI_SKILLS_DIR", str(root / ".omlxcli" / "skills")))
    if not skills_dir.is_dir():
        # 兼容老目录，便于平滑迁移。
        skills_dir = root / ".aicli" / "skills"
    if not skills_dir.is_dir():
        return {}, ""

    skills_dir_s = str(skills_dir)
    try:
        if skills_dir_s not in sys.path:
            sys.path.insert(0, skills_dir_s)
        from _registry import register_all, render_tools_md  # type: ignore

        reg = register_all(skills_dir_s) or []
        tools_md = render_tools_md(reg) or ""
        funcs: dict[str, Any] = {}
        for item in reg:
            name = str(item.get("func_name") or "").strip()
            fn = getattr(builtins, name, None)
            if name and callable(fn):
                funcs[name] = fn
        return funcs, tools_md
    except Exception:
        return {}, ""


def run_skill_call(expr: str, funcs: dict[str, Any]) -> dict[str, Any]:
    s = (expr or "").strip()
    if not funcs:
        return {"exit_code": 1, "stdout": "", "stderr": "skills 未加载，无法执行 run_skill。"}
    try:
        node = ast.parse(s, mode="eval")
        if not isinstance(node.body, ast.Call):
            return {"exit_code": 1, "stdout": "", "stderr": "run_skill 只允许函数调用表达式。"}
        fn = node.body.func
        if not isinstance(fn, ast.Name):
            return {"exit_code": 1, "stdout": "", "stderr": "run_skill 仅支持直接函数名调用。"}
        if fn.id not in funcs:
            return {"exit_code": 1, "stdout": "", "stderr": f"未找到技能函数：{fn.id}"}

        res = eval(  # noqa: S307
            compile(node, "<run_skill>", "eval"),
            {"__builtins__": {}},
            funcs,
        )
        if isinstance(res, (dict, list)):
            out = json.dumps(res, ensure_ascii=False, indent=2)
        else:
            out = str(res)
        return {"exit_code": 0, "stdout": out, "stderr": ""}
    except Exception as exc:  # noqa: BLE001
        return {"exit_code": 1, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}"}
