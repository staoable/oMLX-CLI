# SPDX-License-Identifier: MIT
from __future__ import annotations

import unittest
from unittest import mock

from webapi.shell_terminal import build_shell_argv


class ShellTerminalTest(unittest.TestCase):
    def test_plain_shell_when_no_script(self) -> None:
        with mock.patch("webapi.shell_terminal.shutil.which", return_value=None):
            argv = build_shell_argv("echo x")
        self.assertEqual(len(argv), 3)
        self.assertEqual(argv[1], "-c")
        self.assertEqual(argv[2], "echo x")

    def test_pty_wrap_darwin_when_script_present(self) -> None:
        with mock.patch("webapi.shell_terminal.shutil.which", return_value="/usr/bin/script"):
            with mock.patch("webapi.shell_terminal.sys.platform", "darwin"):
                argv = build_shell_argv("true")
                self.assertEqual(argv[0], "/usr/bin/script")
                self.assertEqual(argv[1], "-q")
                self.assertEqual(argv[2], "/dev/null")
