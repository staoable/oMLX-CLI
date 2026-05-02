from __future__ import annotations

import ast
import builtins
import concurrent.futures
import json
import os
import sys
from pathlib import Path
from types import CodeType
from typing import Any

from webapi.skill_manifest import load_skill_manifests, validate_skill_ast_call


def resolve_skills_dir() -> Path:
    root = Path(__file__).resolve().parent.parent
    primary = Path(os.getenv("OMLXCLI_SKILLS_DIR", str(root / ".omlxcli" / "skills")))
    if primary.is_dir():
        return primary
    alt = root / ".aicli" / "skills"
    return alt if alt.is_dir() else primary


def load_skills_registry() -> tuple[dict[str, Any], str]:
    skills_dir = resolve_skills_dir()
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


def _eval_skill(compiled: CodeType, funcs: dict[str, Any]) -> Any:
    return eval(compiled, {"__builtins__": {}}, funcs)  # noqa: S307


def _run_skill_timeout_sec() -> int:
    raw = (os.getenv("OMLXCLI_RUN_SKILL_TIMEOUT_SEC") or "120").strip()
    try:
        n = int(raw)
    except ValueError:
        return 120
    if n <= 0:
        return 0
    return max(1, min(n, 7200))


def run_skill_call(expr: str, funcs: dict[str, Any]) -> dict[str, Any]:
    s = (expr or "").strip()
    if not funcs:
        return {"exit_code": 1, "stdout": "", "stderr": "skills 未加载，无法执行 run_skill。"}
    manifests = load_skill_manifests(str(resolve_skills_dir()))
    try:
        node = ast.parse(s, mode="eval")
        if not isinstance(node.body, ast.Call):
            return {"exit_code": 1, "stdout": "", "stderr": "run_skill 只允许函数调用表达式。"}
        fn = node.body.func
        if not isinstance(fn, ast.Name):
            return {"exit_code": 1, "stdout": "", "stderr": "run_skill 仅支持直接函数名调用。"}
        if fn.id not in funcs:
            return {"exit_code": 1, "stdout": "", "stderr": f"未找到技能函数：{fn.id}"}

        ok, err = validate_skill_ast_call(fn.id, node.body, manifests)
        if not ok:
            return {"exit_code": 1, "stdout": "", "stderr": err}

        compiled = compile(node, "<run_skill>", "eval")
        timeout_sec = _run_skill_timeout_sec()
        if timeout_sec <= 0:
            res = _eval_skill(compiled, funcs)
        else:
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                fut = pool.submit(_eval_skill, compiled, funcs)
                try:
                    res = fut.result(timeout=timeout_sec)
                except concurrent.futures.TimeoutError:
                    return {
                        "exit_code": 1,
                        "stdout": "",
                        "stderr": f"run_skill 超时（>{timeout_sec} 秒），已中断。",
                    }
            finally:
                # 避免 with 默认 wait=True：超时后仍阻塞至子线程结束
                pool.shutdown(wait=False, cancel_futures=False)
        if isinstance(res, (dict, list)):
            out = json.dumps(res, ensure_ascii=False, indent=2)
        else:
            out = str(res)
        return {"exit_code": 0, "stdout": out, "stderr": ""}
    except Exception as exc:  # noqa: BLE001
        return {"exit_code": 1, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}"}
