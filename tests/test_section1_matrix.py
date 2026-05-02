"""IMPLEMENTATION_PLAN 第 1 节矩阵相关回归用例。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
import io
import urllib.error
from unittest import mock

from oi_runtime_core import chat_completion_once
from webapi.context_manager import ContextManager
from webapi.execution_policy import check_command_policy
from webapi.session_store import SessionStore


class Section1MatrixTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "s1.db")
        self.store = SessionStore(self.db_path)

    def tearDown(self) -> None:
        del self.store
        self.tmpdir.cleanup()

    def test_exec_allowlist_blocks_non_matching(self) -> None:
        old = os.environ.get("OMLXCLI_EXEC_ALLOWLIST_RE")
        os.environ["OMLXCLI_EXEC_ALLOWLIST_RE"] = r"\b(git)\b"
        try:
            ok, reason, _ = check_command_policy("ls", self.tmpdir.name, False)
            self.assertFalse(ok)
            self.assertIn("白名单", reason)
            ok2, _, _ = check_command_policy("git status", self.tmpdir.name, False)
            self.assertTrue(ok2)
        finally:
            if old is None:
                os.environ.pop("OMLXCLI_EXEC_ALLOWLIST_RE", None)
            else:
                os.environ["OMLXCLI_EXEC_ALLOWLIST_RE"] = old

    def test_list_sessions_respects_archived(self) -> None:
        a = self.store.create_session(
            title="active",
            workspace_path=self.tmpdir.name,
            model="m",
            api_base="http://127.0.0.1:8000/v1",
            auto_run=True,
        )
        b = self.store.create_session(
            title="gone",
            workspace_path=self.tmpdir.name,
            model="m",
            api_base="http://127.0.0.1:8000/v1",
            auto_run=True,
        )
        self.store.update_session(b.id, archived=True)
        visible = self.store.list_sessions(include_archived=False)
        self.assertEqual({r.id for r in visible}, {a.id})
        all_rows = self.store.list_sessions(include_archived=True)
        self.assertGreaterEqual(len(all_rows), 2)
        self.assertIn(b.id, {r.id for r in all_rows})

    def test_context_priority_order_in_list(self) -> None:
        s = self.store.create_session(
            title="c",
            workspace_path=self.tmpdir.name,
            model="m",
            api_base="http://127.0.0.1:8000/v1",
            auto_run=True,
        )
        self.store.add_context(session_id=s.id, layer="working", content="low", priority=0)
        self.store.add_context(session_id=s.id, layer="working", content="high", priority=10)
        rows = self.store.list_contexts(s.id, layer="working")
        self.assertEqual(rows[0]["content"], "high")
        self.assertEqual(rows[0]["priority"], 10)

    def test_restore_checkpoint_replace_clears_working(self) -> None:
        s = self.store.create_session(
            title="r",
            workspace_path=self.tmpdir.name,
            model="m",
            api_base="http://127.0.0.1:8000/v1",
            auto_run=True,
        )
        ctx = ContextManager(self.store)
        self.store.add_context(session_id=s.id, layer="working", content="from_ckpt", priority=0)
        cp = ctx.create_checkpoint(
            s.id,
            "sum",
            [{"role": "user", "content": "x"}],
        )
        self.store.add_context(session_id=s.id, layer="working", content="stale_after_ckpt", priority=0)
        ctx.restore_from_checkpoint(s.id, cp["id"], mode="replace")
        rows = self.store.list_contexts(s.id, layer="working")
        contents = [r["content"] for r in rows]
        self.assertNotIn("stale_after_ckpt", contents)
        self.assertIn("from_ckpt", contents)

    def test_measure_messages_chars(self) -> None:
        n = ContextManager.measure_messages_chars(
            [{"role": "user", "content": "abcd"}],
        )
        self.assertEqual(n, 4)

    def test_oi_tool_map_json_has_skills_scope(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = root / "OI_TOOL_MAP.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(data.get("scope"), "omlxcli_skills_only")
        self.assertIsInstance(data.get("skills"), list)
        self.assertGreater(len(data["skills"]), 0)

    @mock.patch("oi_runtime_core.urllib.request.urlopen")
    def test_chat_completion_retries_on_502(self, m_url: mock.MagicMock) -> None:
        body = b'{"choices":[{"message":{"content":"ok"}}]}'

        class _Ok:
            def __enter__(self) -> "_Ok":
                return self

            def __exit__(self, *_a: object) -> None:
                return None

            def read(self) -> bytes:
                return body

        m_url.side_effect = [
            urllib.error.HTTPError("http://u", 502, "bad", {}, io.BytesIO(b"{}")),
            _Ok(),
        ]
        old_retries = os.environ.get("OMLXCLI_CHAT_HTTP_RETRIES")
        os.environ["OMLXCLI_CHAT_HTTP_RETRIES"] = "2"
        try:
            out = chat_completion_once(
                "http://127.0.0.1:9/v1",
                "k",
                "m",
                [{"role": "user", "content": "hi"}],
                timeout=5,
            )
            self.assertEqual(out["choices"][0]["message"]["content"], "ok")
            self.assertEqual(m_url.call_count, 2)
        finally:
            if old_retries is None:
                os.environ.pop("OMLXCLI_CHAT_HTTP_RETRIES", None)
            else:
                os.environ["OMLXCLI_CHAT_HTTP_RETRIES"] = old_retries


if __name__ == "__main__":
    unittest.main()
