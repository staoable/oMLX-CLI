from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from webapi.claude_job_service import ClaudeJobService
from webapi.session_store import SessionStore


class ClaudeJobServiceRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp_db.close()
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.store = SessionStore(self._tmp_db.name)
        self.jobs_root = Path(self._tmp_dir.name)
        self.svc = ClaudeJobService(self.store, self.jobs_root)
        self.session = self.store.create_session(
            title="s",
            workspace_path="/tmp/ws",
            model="m",
            api_base="http://x",
            auto_run=True,
        )

    def tearDown(self) -> None:
        os.environ.pop("OMLXCLI_CLAUDE_JOB_LOG_RETENTION_SEC", None)
        os.environ.pop("OMLXCLI_CLAUDE_JOB_MAX_LOG_BYTES", None)
        self._tmp_dir.cleanup()
        try:
            os.unlink(self._tmp_db.name)
        except OSError:
            pass

    def test_recover_stale_running_to_completed_from_log(self) -> None:
        jid = uuid.uuid4().hex
        (self.jobs_root / jid).mkdir(parents=True, exist_ok=True)
        (self.jobs_root / jid / "run.log").write_text("审计完成，未做任何修改。", encoding="utf-8")
        self.store.create_claude_job(
            job_id=jid,
            session_id=self.session.id,
            workspace_path=self.session.workspace_path,
            prompt="p",
            status="running",
            pid=999999,  # 不存在的 pid
            log_relpath=f"{jid}/run.log",
        )
        row = self.svc.get_job(self.session.id, jid)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["exit_code"], 0)
        self.assertIn("审计完成", row["result_summary"])

    def test_recover_stale_running_to_failed_from_error_log(self) -> None:
        jid = uuid.uuid4().hex
        (self.jobs_root / jid).mkdir(parents=True, exist_ok=True)
        (self.jobs_root / jid / "run.log").write_text(
            'API Error: 401 {"error":"bad key"}',
            encoding="utf-8",
        )
        self.store.create_claude_job(
            job_id=jid,
            session_id=self.session.id,
            workspace_path=self.session.workspace_path,
            prompt="p",
            status="running",
            pid=999999,
            log_relpath=f"{jid}/run.log",
        )
        row = self.svc.get_job(self.session.id, jid)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["exit_code"], 1)

    def test_recover_stale_running_telemetry_export_warning_to_completed(self) -> None:
        jid = uuid.uuid4().hex
        (self.jobs_root / jid).mkdir(parents=True, exist_ok=True)
        (self.jobs_root / jid / "run.log").write_text(
            "Error: 1P event logging: 3 events failed to export\n"
            "Error: Failed to export 3 events\n",
            encoding="utf-8",
        )
        self.store.create_claude_job(
            job_id=jid,
            session_id=self.session.id,
            workspace_path=self.session.workspace_path,
            prompt="p",
            status="running",
            pid=999999,
            log_relpath=f"{jid}/run.log",
        )
        row = self.svc.get_job(self.session.id, jid)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["exit_code"], 0)
        self.assertEqual(row["error_summary"], "stale_running_telemetry_export_warning")

    def test_start_next_queued_is_serialized(self) -> None:
        j1 = uuid.uuid4().hex
        j2 = uuid.uuid4().hex
        for jid in (j1, j2):
            (self.jobs_root / jid).mkdir(parents=True, exist_ok=True)
            self.store.create_claude_job(
                job_id=jid,
                session_id=self.session.id,
                workspace_path=self.session.workspace_path,
                prompt=f"p-{jid}",
                context_mode="continue",
                max_turns=12,
                status="queued",
                pid=None,
                log_relpath=f"{jid}/run.log",
            )
        calls: list[str] = []
        gate = threading.Event()

        def fake_spawn(*, job_id: str, **_: object) -> dict[str, object]:
            calls.append(job_id)
            self.store.update_claude_job(job_id, status="running", pid=os.getpid(), error_summary="")
            gate.wait(0.15)
            return {"ok": True, "job_id": job_id, "status": "running"}

        self.svc._spawn_job_process = fake_spawn  # type: ignore[method-assign]
        t1 = threading.Thread(target=self.svc._start_next_queued, args=(self.session.id,))
        t2 = threading.Thread(target=self.svc._start_next_queued, args=(self.session.id,))
        t1.start()
        t2.start()
        time.sleep(0.05)
        gate.set()
        t1.join()
        t2.join()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], j1)

    def test_cleanup_old_logs_removes_terminal_artifacts(self) -> None:
        os.environ["OMLXCLI_CLAUDE_JOB_LOG_RETENTION_SEC"] = "3600"
        jid = uuid.uuid4().hex
        job_dir = self.jobs_root / jid
        job_dir.mkdir(parents=True, exist_ok=True)
        log_path = job_dir / "run.log"
        log_path.write_text("old", encoding="utf-8")
        old_ts = time.time() - 7200
        os.utime(log_path, (old_ts, old_ts))
        self.store.create_claude_job(
            job_id=jid,
            session_id=self.session.id,
            workspace_path=self.session.workspace_path,
            prompt="p",
            context_mode="continue",
            max_turns=8,
            status="completed",
            pid=None,
            log_relpath=f"{jid}/run.log",
        )
        self.svc.list_jobs(self.session.id, limit=10)
        self.assertFalse(log_path.exists())

    def test_trim_oversize_log_keeps_tail(self) -> None:
        os.environ["OMLXCLI_CLAUDE_JOB_MAX_LOG_BYTES"] = "300000"
        jid = uuid.uuid4().hex
        job_dir = self.jobs_root / jid
        job_dir.mkdir(parents=True, exist_ok=True)
        log_path = job_dir / "run.log"
        big = ("x" * 400000 + "TAIL_MARKER").encode("utf-8")
        log_path.write_bytes(big)
        self.store.create_claude_job(
            job_id=jid,
            session_id=self.session.id,
            workspace_path=self.session.workspace_path,
            prompt="p",
            context_mode="continue",
            max_turns=8,
            status="completed",
            pid=None,
            log_relpath=f"{jid}/run.log",
        )
        text = self.svc.tail_logs(self.session.id, jid, tail_lines=20)
        self.assertIn("TAIL_MARKER", text)
        self.assertLessEqual(log_path.stat().st_size, 300000)

    def test_spawn_exception_persists_terminal_message(self) -> None:
        jid = uuid.uuid4().hex
        (self.jobs_root / jid).mkdir(parents=True, exist_ok=True)
        self.store.create_claude_job(
            job_id=jid,
            session_id=self.session.id,
            workspace_path=self.session.workspace_path,
            prompt="p",
            context_mode="continue",
            max_turns=12,
            status="queued",
            pid=None,
            log_relpath=f"{jid}/run.log",
        )
        with mock.patch.object(subprocess, "Popen", side_effect=RuntimeError("boom")):
            out = self.svc._spawn_job_process(
                job_id=jid,
                session_id=self.session.id,
                workspace_path=self.session.workspace_path,
                prompt="p",
                max_turns=12,
                context_mode="continue",
            )
        self.assertFalse(out["ok"])
        row = self.store.get_claude_job(jid)
        self.assertEqual(row["status"], "failed")
        msgs = self.store.list_messages(self.session.id, limit=200)
        self.assertTrue(any("Claude 任务" in str(m.get("content") or "") for m in msgs))
        self.assertTrue(any(f"claude_job_event:{jid}:failed" in str(m.get("content") or "") for m in msgs))

    def test_wait_exception_persists_terminal_message(self) -> None:
        jid = uuid.uuid4().hex
        (self.jobs_root / jid).mkdir(parents=True, exist_ok=True)
        self.store.create_claude_job(
            job_id=jid,
            session_id=self.session.id,
            workspace_path=self.session.workspace_path,
            prompt="p",
            context_mode="continue",
            max_turns=12,
            status="running",
            pid=12345,
            log_relpath=f"{jid}/run.log",
        )

        class _BadProc:
            def wait(self) -> int:
                raise RuntimeError("wait failed")

        self.svc._wait_and_finalize(jid, _BadProc())  # type: ignore[arg-type]
        row = self.store.get_claude_job(jid)
        self.assertEqual(row["status"], "failed")
        self.assertIn("wait_error", row["error_summary"])
        msgs = self.store.list_messages(self.session.id, limit=200)
        self.assertTrue(any("Claude 任务" in str(m.get("content") or "") for m in msgs))
        self.assertTrue(any(f"claude_job_event:{jid}:failed" in str(m.get("content") or "") for m in msgs))

    def test_conditional_transition_does_not_overwrite_non_running(self) -> None:
        jid = uuid.uuid4().hex
        (self.jobs_root / jid).mkdir(parents=True, exist_ok=True)
        self.store.create_claude_job(
            job_id=jid,
            session_id=self.session.id,
            workspace_path=self.session.workspace_path,
            prompt="p",
            context_mode="continue",
            max_turns=8,
            status="completed",
            pid=None,
            log_relpath=f"{jid}/run.log",
        )
        changed = self.svc._transition_terminal_from_status(  # type: ignore[attr-defined]
            job_id=jid,
            expect_status="running",
            status="failed",
            exit_code=1,
            error_summary="should_not_apply",
            report_text="",
        )
        self.assertFalse(changed)
        row = self.store.get_claude_job(jid)
        self.assertEqual(row["status"], "completed")


if __name__ == "__main__":
    unittest.main()
