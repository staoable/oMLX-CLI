from __future__ import annotations

import os
import tempfile
import unittest

from webapi.context_manager import ContextManager
from webapi.execution_policy import _abs_paths_for_workspace_boundary, check_command_policy
from webapi.session_store import SessionStore


class P0BasicsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "sessions.db")
        self.store = SessionStore(self.db_path)
        self.session = self.store.create_session(
            title="t",
            workspace_path=self.tmpdir.name,
            model="m",
            api_base="http://127.0.0.1:8000/v1",
            auto_run=True,
        )

    def tearDown(self) -> None:
        del self.store
        self.tmpdir.cleanup()

    def test_execution_and_context_injection_persistence(self) -> None:
        saved = self.store.add_execution(
            session_id=self.session.id,
            exec_type="shell",
            command="ls",
            status="success",
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_ms=12.3,
        )
        self.assertEqual(saved["status"], "success")
        rows = self.store.list_executions(self.session.id, limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["command"], "ls")

        self.store.add_context_injection(
            session_id=self.session.id,
            source="history",
            role="assistant",
            char_count=321,
            dropped=False,
            reason="",
        )
        crows = self.store.list_context_injections(self.session.id, limit=10)
        self.assertEqual(len(crows), 1)
        self.assertEqual(crows[0]["char_count"], 321)

    def test_context_manager_debug_rows(self) -> None:
        ctx = ContextManager(self.store)
        messages, debug_rows = ctx.build_prompt_messages_debug(
            session_id=self.session.id,
            system_prompt="sys",
            recent_messages=[{"role": "user", "content": "hello"}],
            user_input="new question",
            attachments=[],
            token_budget_chars=1024,
        )
        self.assertTrue(messages)
        self.assertTrue(debug_rows)
        self.assertTrue(any(r["source"] == "current_user" for r in debug_rows))

    def test_tilde_paths_not_misread_as_root_dotpath(self) -> None:
        """~/.foo 中的 / 不应被当成 /.foo（曾误触发写路径越界）。"""
        cmd = "mkdir -p ~/.myapp && touch ~/.myapp/run.log && echo ok 2>&1"
        paths = _abs_paths_for_workspace_boundary(cmd)
        self.assertNotIn("/.myapp", paths)
        self.assertEqual(paths, [])

    def test_absolute_paths_after_space_still_detected(self) -> None:
        paths = _abs_paths_for_workspace_boundary("ls -la /etc/hosts")
        self.assertIn("/etc/hosts", paths)

    def test_execution_policy_configurable(self) -> None:
        old = os.environ.get("OMLXCLI_EXEC_BLOCKLIST_RE")
        os.environ["OMLXCLI_EXEC_BLOCKLIST_RE"] = r"\b(echo)\b"
        try:
            ok, reason, _ = check_command_policy("echo hi", self.tmpdir.name, confirm_each=False)
            self.assertFalse(ok)
            self.assertIn("黑名单", reason)
        finally:
            if old is None:
                os.environ.pop("OMLXCLI_EXEC_BLOCKLIST_RE", None)
            else:
                os.environ["OMLXCLI_EXEC_BLOCKLIST_RE"] = old

    def test_trim_to_budget_caps_system_messages(self) -> None:
        old_ratio = os.environ.get("OMLXCLI_SYSTEM_BUDGET_RATIO")
        os.environ["OMLXCLI_SYSTEM_BUDGET_RATIO"] = "0.5"
        try:
            msgs = [
                {"role": "system", "content": "S" * 90},
                {"role": "user", "content": "U" * 30},
                {"role": "assistant", "content": "A" * 30},
            ]
            out = ContextManager._trim_to_budget(msgs, budget_chars=100)
            total = sum(len(str(m["content"])) for m in out)
            sys_total = sum(len(str(m["content"])) for m in out if m.get("role") == "system")
            self.assertLessEqual(total, 100)
            self.assertLessEqual(sys_total, 50)
        finally:
            if old_ratio is None:
                os.environ.pop("OMLXCLI_SYSTEM_BUDGET_RATIO", None)
            else:
                os.environ["OMLXCLI_SYSTEM_BUDGET_RATIO"] = old_ratio


if __name__ == "__main__":
    unittest.main()
