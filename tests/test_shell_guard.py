# SPDX-License-Identifier: MIT
from __future__ import annotations

import unittest

from webapi.shell_guard import (
    blocked_interactive_tui_message,
    list_shell_lead_bins,
    wrap_known_streaming_shell_commands,
)


class ShellGuardTest(unittest.TestCase):
    def test_tilde_path_not_listed_as_lead_bins(self) -> None:
        cmd = "mkdir -p ~/.myapp && touch ~/.myapp/x"
        self.assertEqual(list_shell_lead_bins(cmd), ["mkdir", "touch"])

    def test_mactop_blocked(self) -> None:
        msg = blocked_interactive_tui_message("sudo mactop -o gpu -n 1")
        self.assertIsNotNone(msg)
        self.assertIn("mactop", msg or "")

    def test_plain_echo_not_blocked(self) -> None:
        self.assertIsNone(blocked_interactive_tui_message("echo ok"))

    def test_pipeline_mactop_in_second_segment(self) -> None:
        self.assertIsNotNone(blocked_interactive_tui_message("echo 1 | mactop"))

    def test_pmset_thermlog_wrapped(self) -> None:
        out = wrap_known_streaming_shell_commands("sudo pmset -g thermlog")
        self.assertIn("| head", out)
        self.assertIn("pmset -g thermlog", out)

    def test_pmset_thermlog_not_double_wrapped(self) -> None:
        raw = "pmset -g thermlog 2>&1 | head -n 5"
        self.assertEqual(wrap_known_streaming_shell_commands(raw), raw)
