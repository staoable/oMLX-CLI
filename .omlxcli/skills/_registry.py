"""持久工具链 - 启动注册 + 文档生成。

`register_all(skills_dir)` 扫描 `skills_dir` 下所有非下划线开头的 `.py`，
通过 importlib 重新加载它们；每个文件里的 `@skill` 装饰器会把函数追加到
`_meta._REGISTRY`，并 setattr 到 builtins。

`render_tools_md()` 把 `_REGISTRY` 渲染成 markdown，由调用方拼接进
OI 的 system_message。
"""

from __future__ import annotations

import glob
import importlib
import importlib.util
import os
import sys


def register_all(skills_dir: str) -> list[dict]:
    """扫描并加载 skills_dir 下的所有 skill 文件，返回当前注册表的副本。"""
    skills_dir = os.path.abspath(skills_dir)
    if not os.path.isdir(skills_dir):
        return []

    if skills_dir not in sys.path:
        sys.path.insert(0, skills_dir)

    if "_meta" in sys.modules:
        importlib.reload(sys.modules["_meta"])
    import _meta  # type: ignore  # noqa: WPS433

    _meta._REGISTRY.clear()

    for path in sorted(glob.glob(os.path.join(skills_dir, "*.py"))):
        name = os.path.basename(path)[:-3]
        if name.startswith("_"):
            continue
        if name in sys.modules:
            del sys.modules[name]

        spec = importlib.util.spec_from_file_location(name, path)
        if not spec or not spec.loader:
            continue

        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:  # noqa: BLE001
            print(f"[skills] 加载 {name} 失败: {type(exc).__name__}: {exc}")

    return list(_meta._REGISTRY)


def render_tools_md(registry: list[dict] | None = None) -> str:
    """把注册表渲染成 markdown，用于注入 system_message。"""
    if registry is None:
        if "_meta" in sys.modules:
            registry = list(sys.modules["_meta"]._REGISTRY)  # type: ignore[attr-defined]
        else:
            return ""
    if not registry:
        return ""

    by_module: dict[str, list[dict]] = {}
    for item in registry:
        by_module.setdefault(item["module"], []).append(item)

    lines = [
        "## 已加载的本地工具（持久工具链）",
        "",
        "下面这些函数已注入到当前 IPython 内核的 builtins：**直接当函数调用即可，不要 `import`**。",
        "需要新工具时，写到 `.aicli/skills/<your_module>.py`，重启会话即可生效。",
        "",
    ]
    for module in sorted(by_module):
        lines.append(f"### `{module}`")
        for item in by_module[module]:
            lines.append(f"- **`{item['func_name']}{item['signature']}`**")
            if item["desc"]:
                lines.append(f"  - {item['desc']}")
            for ex in item["examples"]:
                lines.append(f"  - 例：`{ex}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
