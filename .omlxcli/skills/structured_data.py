"""JSON/YAML 本地文件安全读取与点路径取值。"""

from __future__ import annotations

import json
import os
from typing import Any

from _meta import skill

_MAX_FILE_BYTES = 16 * 1024 * 1024


def _abs_file(path: str) -> str:
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(p):
        raise FileNotFoundError(f"文件不存在: {p}")
    if os.path.getsize(p) > _MAX_FILE_BYTES:
        raise ValueError(f"文件过大（>{_MAX_FILE_BYTES // (1024 * 1024)}MB）。")
    return p


def _detect_format(path: str, fmt: str) -> str:
    f = (fmt or "auto").strip().lower()
    if f in ("json", "yaml", "yml"):
        return "json" if f == "json" else "yaml"
    low = path.lower()
    if low.endswith(".json"):
        return "json"
    if low.endswith((".yaml", ".yml")):
        return "yaml"
    raise ValueError("format=auto 时无法从扩展名判断，请指定 format='json' 或 'yaml'")


def _traverse(obj: Any, parts: list[str], max_depth: int) -> Any:
    cur: Any = obj
    depth = 0
    for raw in parts:
        if not raw:
            continue
        if depth >= max_depth:
            raise ValueError("pointer 路径过深")
        depth += 1
        if isinstance(cur, list):
            if not raw.isdigit():
                raise ValueError(f"在列表处需要数字下标，收到: {raw!r}")
            idx = int(raw)
            if idx < 0 or idx >= len(cur):
                raise IndexError(f"列表下标越界: {idx}, len={len(cur)}")
            cur = cur[idx]
        elif isinstance(cur, dict):
            if raw not in cur:
                raise KeyError(f"对象缺少键: {raw!r}")
            cur = cur[raw]
        else:
            raise TypeError(f"无法在 {type(cur).__name__} 上继续下钻: {raw!r}")
    return cur


def _preview(obj: Any, limit: int = 30) -> Any:
    if obj is None:
        return {"_type": "null"}
    if isinstance(obj, dict):
        keys = list(obj.keys())[:limit]
        return {"_type": "object", "keys": keys, "key_count": len(obj)}
    if isinstance(obj, list):
        return {"_type": "array", "length": len(obj), "first_types": [type(x).__name__ for x in obj[:5]]}
    return {"_type": type(obj).__name__, "repr": repr(obj)[:500]}


@skill(
    desc="读取本地 JSON/YAML，按点路径取值；pointer 为空则返回顶层键/类型预览。",
    examples=[
        "structured_pick('./package.json', pointer='dependencies')",
        "structured_pick('./cfg.yaml', pointer='server.port', format='yaml')",
    ],
)
def structured_pick(
    path: str,
    pointer: str = "",
    format: str = "auto",
    max_value_chars: int = 120_000,
    max_depth: int = 40,
) -> dict[str, Any]:
    """pointer 用 . 分隔；数组下标用数字段，如 items.0.name。"""
    abs_path = _abs_file(path)
    kind = _detect_format(abs_path, format)
    with open(abs_path, "r", encoding="utf-8-sig", errors="strict") as fh:
        text = fh.read()

    if kind == "json":
        data = json.loads(text)
    else:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("缺少依赖 PyYAML，请安装：pip install PyYAML") from exc
        data = yaml.safe_load(text)

    max_depth = max(1, min(int(max_depth), 80))
    max_value_chars = max(1000, min(int(max_value_chars), 2_000_000))

    ptr = (pointer or "").strip().strip(".")
    if not ptr:
        return {
            "path": abs_path,
            "format": kind,
            "preview": _preview(data),
        }

    parts = [p for p in ptr.split(".") if p != ""]
    picked = _traverse(data, parts, max_depth)

    serialized = json.dumps(picked, ensure_ascii=False, default=str)
    if len(serialized) > max_value_chars:
        return {
            "path": abs_path,
            "format": kind,
            "pointer": ptr,
            "preview": _preview(picked) if isinstance(picked, (dict, list)) else {"repr": serialized[:2000]},
            "truncated": True,
            "hint": f"序列化长度 {len(serialized)} 超过 max_value_chars={max_value_chars}，请收窄 pointer 或提高上限。",
        }

    return {
        "path": abs_path,
        "format": kind,
        "pointer": ptr,
        "value": picked,
        "truncated": False,
    }