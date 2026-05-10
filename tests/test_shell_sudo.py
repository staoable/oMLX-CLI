# SPDX-License-Identifier: MIT
from __future__ import annotations

from webapi.shell_sudo import command_uses_sudo, inject_sudo_stdin_mode


def test_command_uses_sudo() -> None:
    assert command_uses_sudo("sudo ls /tmp")
    assert command_uses_sudo("  sudo -n true")
    assert not command_uses_sudo("ls /tmp")


def test_inject_once() -> None:
    assert inject_sudo_stdin_mode("sudo apt update") == "sudo -S -p '' apt update"


def test_inject_idempotent() -> None:
    s = "sudo -S -p '' apt update"
    assert inject_sudo_stdin_mode(s) == s


def test_inject_second_sudo_unchanged() -> None:
    """仅替换首处 sudo。"""
    out = inject_sudo_stdin_mode("sudo env A=1 sudo -n true")
    assert out.startswith("sudo -S -p '' env A=1 sudo -n true")
