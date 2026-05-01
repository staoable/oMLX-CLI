"""持久工具链 - 注册装饰器。

被 `_registry.register_all()` 扫描到的 skill 文件 import 此模块，使用
`@skill(...)` 装饰函数即可：

  - 函数被 setattr 到 builtins，IPython 内核里直接当函数调用，无需 import。
  - 函数元信息被收集到 `_REGISTRY`，由 `render_tools_md()` 生成工具菜单
    并写入 OI 的 system_message，让模型每次启动就能"看见"已注册的工具。

注意：本模块**故意**写得很薄，没有任何强约束。skill 函数返回什么、抛什么异常
都由作者自定。我们只承诺"被持久化、被注入、被列表化"。
"""

from __future__ import annotations

import builtins
import inspect
from typing import Callable, Iterable, Optional

_REGISTRY: list[dict] = []


def skill(
    name: Optional[str] = None,
    desc: str = "",
    examples: Optional[Iterable[str]] = None,
) -> Callable:
    """装饰器：把函数注册为持久工具。

    参数：
        name: 工具的展示名（默认 = 函数名）。
        desc: 一句话描述；省略时取 docstring 第一行非空字符串。
        examples: 调用示例列表，会显示在工具菜单里供模型参考。
    """

    examples_list = list(examples or [])

    def decorator(fn: Callable) -> Callable:
        try:
            sig = str(inspect.signature(fn))
        except (TypeError, ValueError):
            sig = "(...)"

        final_desc = (desc or "").strip()
        if not final_desc and fn.__doc__:
            for line in fn.__doc__.splitlines():
                line = line.strip()
                if line:
                    final_desc = line
                    break

        _REGISTRY.append(
            {
                "name": name or fn.__name__,
                "func_name": fn.__name__,
                "desc": final_desc,
                "signature": sig,
                "examples": list(examples_list),
                "module": fn.__module__,
            }
        )

        # 注入 builtins：模型在 IPython 内核里 `func()` 直接可用
        try:
            setattr(builtins, fn.__name__, fn)
        except Exception:  # noqa: BLE001
            pass
        return fn

    return decorator
