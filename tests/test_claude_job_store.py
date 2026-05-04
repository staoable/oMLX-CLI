"""claude_jobs 表 CRUD（不启动子进程）。"""

from __future__ import annotations

import os
import tempfile
import unittest
import uuid

from webapi.session_store import SessionStore


class ClaudeJobStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.store = SessionStore(self._tmp.name)

    def tearDown(self) -> None:
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_create_list_get_update(self) -> None:
        rec = self.store.create_session(
            title="t",
            workspace_path="/tmp/ws",
            model="m",
            api_base="https://x",
            auto_run=True,
        )
        sid = rec.id

        jid = uuid.uuid4().hex
        self.store.create_claude_job(
            job_id=jid,
            session_id=sid,
            workspace_path="/tmp/ws",
            prompt="hello",
            status="running",
            pid=12345,
            log_relpath=f"{jid}/run.log",
        )
        rows = self.store.list_claude_jobs(sid, limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "running")

        self.store.update_claude_job(jid, status="completed", exit_code=0, result_summary="ok")
        row = self.store.get_claude_job(jid)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["exit_code"], 0)

    def test_latest_claude_session_id(self) -> None:
        rec = self.store.create_session(
            title="t",
            workspace_path="/tmp/ws",
            model="m",
            api_base="https://x",
            auto_run=True,
        )
        sid = rec.id
        j1 = uuid.uuid4().hex
        self.store.create_claude_job(
            job_id=j1,
            session_id=sid,
            workspace_path="/tmp/ws",
            prompt="p1",
            status="completed",
            pid=None,
            log_relpath=f"{j1}/run.log",
            claude_session_id="claude-sid-1",
        )
        j2 = uuid.uuid4().hex
        self.store.create_claude_job(
            job_id=j2,
            session_id=sid,
            workspace_path="/tmp/ws",
            prompt="p2",
            status="completed",
            pid=None,
            log_relpath=f"{j2}/run.log",
            claude_session_id="claude-sid-2",
        )
        self.assertEqual(self.store.latest_claude_session_id(sid), "claude-sid-2")


if __name__ == "__main__":
    unittest.main()
