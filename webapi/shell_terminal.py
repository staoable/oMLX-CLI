# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
"""run_shell 伪终端包装：POSIX 且 PATH 中存在 ``script(1)`` 时自动使用，无需环境变量。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any


def _posix_script_bin() -> str | None:
    if os.name == "nt":
        return None
    return shutil.which("script")


def build_shell_argv(exec_cmd: str) -> list[str]:
    """构造 ``subprocess.run`` 的 argv：Windows 为 ``cmd /c``；POSIX 在可用时自动 ``script`` 包装。"""
    if os.name == "nt":
        return [os.environ.get("ComSpec", "cmd.exe"), "/c", exec_cmd]
    shell = os.environ.get("SHELL") or "/bin/sh"
    script_bin = _posix_script_bin()
    if not script_bin:
        return [shell, "-c", exec_cmd]
    if sys.platform == "darwin":
        return [script_bin, "-q", "/dev/null", shell, "-c", exec_cmd]
    return [script_bin, "-q", "-e", "-c", exec_cmd, "/dev/null"]


def subprocess_run_kwargs_for_shell() -> dict[str, Any]:
    """与 ``build_shell_argv`` 搭配：在 PTY 包装下将 stdin 置为 DEVNULL，避免挂住。"""
    if os.name == "nt":
        return {}
    if _posix_script_bin():
        return {"stdin": subprocess.DEVNULL}
    return {}
