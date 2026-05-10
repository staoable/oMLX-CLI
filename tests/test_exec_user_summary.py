# SPDX-License-Identifier: MIT
from __future__ import annotations

import unittest

from webapi.exec_user_summary import markdown_exec_digest, merge_answer_with_exec_digest, record_exec_digest


class ExecUserSummaryTest(unittest.TestCase):
    def test_markdown_shows_failure(self) -> None:
        d: list = []
        record_exec_digest(d, kind="shell", command="false", exit_code=1, stdout="", stderr="boom")
        md = markdown_exec_digest(d)
        self.assertIn("未全部成功", md)
        self.assertIn("boom", md)

    def test_merge_skips_duplicate(self) -> None:
        a = "hello\n\n---\n### 命令执行摘要\nx"
        m = "### 命令执行摘要\ny"
        self.assertEqual(merge_answer_with_exec_digest(a, m), a)
