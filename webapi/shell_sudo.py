# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
"""检测 shell 命令中的 sudo，并在需要时注入 ``sudo -S`` 以便从 stdin 读取密码。"""

from __future__ import annotations

import os
import re

_SUDO_TOKEN = re.compile(r"\bsudo\b")


def command_uses_sudo(cmd: str) -> bool:
    """命令是否包含 sudo（Windows 上恒为 False）。"""
    if os.name == "nt":
        return False
    return bool(_SUDO_TOKEN.search(cmd or ""))


def inject_sudo_stdin_mode(cmd: str) -> str:
    """将首处 ``sudo`` 改为 ``sudo -S -p ''``，从标准输入读密码、不打印提示。

    若已含 ``sudo -S`` 则原样返回。适用于 ``subprocess.run(..., input=password + '\\n')``。
    """
    s = cmd or ""
    if re.search(r"\bsudo\s+-S\b", s):
        return s
    return _SUDO_TOKEN.sub("sudo -S -p ''", s, count=1)
