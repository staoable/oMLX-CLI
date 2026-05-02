from __future__ import annotations

import os
import tempfile
import unittest

from webapi.context_manager import ContextManager
from webapi.execution_policy import check_command_policy
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


if __name__ == "__main__":
    unittest.main()
