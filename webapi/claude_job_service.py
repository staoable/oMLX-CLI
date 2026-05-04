# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
"""Claude Code CLI 长任务：子进程 + SQLite 元数据 + 日志文件 tail。"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from webapi.session_store import SessionStore


def claude_code_feature_enabled() -> bool:
    return os.getenv("OMLXCLI_ENABLE_CLAUDE_CODE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def claude_code_api_key() -> str:
    return (os.getenv("OMLXCLI_CLAUDE_CODE_API_KEY") or "").strip()


def claude_code_unavailable_reason() -> str | None:
    if not claude_code_feature_enabled():
        return "功能未启用：设置 OMLXCLI_ENABLE_CLAUDE_CODE=1（见 .env.example）。"
    if not claude_code_api_key():
        return "未配置 OMLXCLI_CLAUDE_CODE_API_KEY（见 .env.example Claude Code Job 节）。"
    if not shutil.which("claude"):
        return "未找到 claude 可执行文件：请安装 npm 包 @anthropic-ai/claude-code（例：npm i -g @anthropic-ai/claude-code）。"
    return None


def claude_code_public_status() -> dict[str, Any]:
    """供 UI / 健康说明用。"""
    reason = claude_code_unavailable_reason()
    return {
        "enabled": reason is None,
        "claude_on_path": bool(shutil.which("claude")),
        "feature_flag_on": claude_code_feature_enabled(),
        "api_key_configured": bool(claude_code_api_key()),
        "reason": reason or "",
    }


def _normalize_path(p: str) -> str:
    return os.path.abspath(os.path.expanduser(p or "."))


def _tail_bytes(path: Path, max_bytes: int = 256_000) -> str:
    if not path.is_file():
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    return data.decode("utf-8", errors="replace")


def _extract_session_id(text: str) -> str:
    m = re.search(r'"session_id"\s*:\s*"([a-zA-Z0-9\-]+)"', text or "")
    if not m:
        return ""
    return m.group(1).strip()


def _strict_report_template_enabled() -> bool:
    raw = (os.getenv("OMLXCLI_CLAUDE_JOB_STRICT_REPORT") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _compose_strict_report_prompt(user_prompt: str) -> str:
    p = (user_prompt or "").strip()
    if not p:
        return p
    if not _strict_report_template_enabled():
        return p
    if "[OMLXCLI_REPORT_TEMPLATE_V1]" in p:
        return p
    template = (
        "\n\n[OMLXCLI_REPORT_TEMPLATE_V1]\n"
        "请按以下固定结构输出，避免只给一句总结：\n"
        "1) 执行范围：列出你实际检查过的目录/文件（至少 6 条，使用项目内路径）。\n"
        "2) 关键发现：按严重级别分组（高/中/低），每条都需包含【证据文件路径 + 现象 + 风险】。\n"
        "3) 测试与验证：说明你实际执行了哪些检查；未执行的项明确写“未验证”。\n"
        "4) 上线结论：仅可三选一（✅ 可上线 / ⚠️ 有条件上线 / ❌ 不可上线），并给出前置条件。\n"
        "5) 下一步行动：给出 3-8 条可落地改进建议（按优先级排序）。\n"
        "要求：\n"
        "- 不要输出“以上为完整报告”这类空洞结语。\n"
        "- 结论必须引用前文证据，不得与证据矛盾。\n"
        "- 若信息不足，明确写出缺失信息与影响。\n"
    )
    return p + template


def _reaper_interval_sec() -> int:
    raw = (os.getenv("OMLXCLI_CLAUDE_JOB_REAPER_INTERVAL_SEC") or "15").strip()
    try:
        n = int(raw)
    except ValueError:
        return 15
    return max(5, min(n, 300))


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, PermissionError, OSError, ValueError):
        return False


class ClaudeJobService:
    def __init__(self, store: SessionStore, jobs_root: Path) -> None:
        self._store = store
        self._jobs_root = Path(jobs_root)
        self._lock = threading.Lock()
        self._queue_lock = threading.Lock()
        self._procs: dict[str, subprocess.Popen[Any]] = {}
        self._reaper_interval = _reaper_interval_sec()
        threading.Thread(
            target=self._running_job_reaper_loop,
            daemon=True,
            name="claude-job-reaper",
        ).start()

    def _job_dir(self, job_id: str) -> Path:
        return self._jobs_root / job_id

    def _log_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "run.log"

    def _max_log_bytes(self) -> int:
        raw = os.getenv("OMLXCLI_CLAUDE_JOB_MAX_LOG_BYTES", "5242880")
        try:
            return max(256_000, int(raw))
        except ValueError:
            return 5 * 1024 * 1024

    def _cleanup_retention_sec(self) -> int:
        raw = os.getenv("OMLXCLI_CLAUDE_JOB_LOG_RETENTION_SEC", "1209600")
        try:
            return max(3600, int(raw))
        except ValueError:
            return 14 * 24 * 3600

    def _trim_log_if_oversize(self, job_id: str) -> None:
        path = self._log_path(job_id)
        if not path.is_file():
            return
        max_bytes = self._max_log_bytes()
        try:
            size = path.stat().st_size
            if size <= max_bytes:
                return
            keep = max(256_000, min(max_bytes, 1_048_576))
            with path.open("rb") as f:
                f.seek(max(0, size - keep))
                data = f.read()
            with path.open("wb") as f:
                f.write(data)
        except OSError:
            return

    def _cleanup_old_logs(self, session_id: str) -> None:
        now = time.time()
        retention = self._cleanup_retention_sec()
        rows = self._store.list_claude_jobs(session_id, limit=500)
        for row in rows:
            if row.get("status") not in ("completed", "failed", "cancelled"):
                continue
            path = self._jobs_root / str(row.get("log_relpath") or "")
            if not path.exists():
                continue
            try:
                age = now - path.stat().st_mtime
            except OSError:
                continue
            if age < retention:
                continue
            try:
                path.unlink(missing_ok=True)
                parent = path.parent
                if parent != self._jobs_root:
                    parent.rmdir()
            except OSError:
                continue

    def _spawn_env(self) -> dict[str, str]:
        env = dict(os.environ)
        key = claude_code_api_key()
        if key:
            # DeepSeek 文档推荐 Claude Code 使用 ANTHROPIC_AUTH_TOKEN。
            env["ANTHROPIC_AUTH_TOKEN"] = key
            # 兼容部分上游/SDK仍读取 ANTHROPIC_API_KEY 的场景。
            env["ANTHROPIC_API_KEY"] = key
        base = (os.getenv("OMLXCLI_CLAUDE_CODE_ANTHROPIC_BASE_URL") or "").strip().rstrip("/")
        if base:
            env["ANTHROPIC_BASE_URL"] = base
        model = (os.getenv("OMLXCLI_CLAUDE_CODE_MODEL") or "").strip()
        if model:
            env["ANTHROPIC_MODEL"] = model
            env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = model
            env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = model
        haiku = (os.getenv("OMLXCLI_CLAUDE_CODE_DEFAULT_HAIKU_MODEL") or "").strip()
        if haiku:
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = haiku
        subagent = (os.getenv("OMLXCLI_CLAUDE_CODE_SUBAGENT_MODEL") or "").strip()
        if subagent:
            env["CLAUDE_CODE_SUBAGENT_MODEL"] = subagent
        effort = (os.getenv("OMLXCLI_CLAUDE_CODE_EFFORT_LEVEL") or "").strip()
        if effort:
            env["CLAUDE_CODE_EFFORT_LEVEL"] = effort
        return env

    def _build_cmd(
        self,
        prompt: str,
        max_turns: int | None,
        *,
        context_mode: str,
        resume_session_id: str = "",
    ) -> list[str]:
        run_prompt = _compose_strict_report_prompt(prompt)
        cmd: list[str] = ["claude", "-p", run_prompt]
        if resume_session_id:
            cmd.extend(["--resume", resume_session_id])
        if max_turns is not None:
            cmd.extend(["--max-turns", str(max_turns)])
        allowed = (os.getenv("OMLXCLI_CLAUDE_CODE_ALLOWED_TOOLS") or "").strip()
        if allowed:
            cmd.extend(["--allowed-tools", allowed])
        return cmd

    def _spawn_job_process(
        self,
        *,
        job_id: str,
        session_id: str,
        workspace_path: str,
        prompt: str,
        max_turns: int | None,
        context_mode: str,
    ) -> dict[str, Any]:
        log_path = self._log_path(job_id)
        resume_sid = self._store.latest_claude_session_id(session_id) if context_mode == "continue" else ""
        cmd = self._build_cmd(
            prompt,
            max_turns,
            context_mode=context_mode,
            resume_session_id=resume_sid,
        )
        env = self._spawn_env()
        log_f = None
        try:
            log_f = open(log_path, "ab", buffering=0)  # noqa: SIM115
            proc = subprocess.Popen(
                cmd,
                cwd=workspace_path,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=False,
            )
        except Exception as exc:  # noqa: BLE001
            if log_f is not None:
                try:
                    log_f.close()
                except OSError:
                    pass
            self._store.update_claude_job(
                job_id,
                status="failed",
                exit_code=1,
                error_summary=f"spawn:{type(exc).__name__}:{exc}",
            )
            return {"ok": False, "error": "spawn_failed", "message": str(exc), "job_id": job_id}

        self._store.update_claude_job(
            job_id,
            status="running",
            pid=proc.pid,
            error_summary="",
            claude_session_id=resume_sid,
        )
        with self._lock:
            self._procs[job_id] = proc
        threading.Thread(
            target=self._wait_and_finalize,
            args=(job_id, proc),
            daemon=True,
            name=f"claude-job-{job_id[:8]}",
        ).start()
        return {
            "ok": True,
            "job_id": job_id,
            "status": "running",
            "workspace_path": workspace_path,
            "context_mode": context_mode,
            "claude_session_id": resume_sid,
            "hint": "可在「Claude」面板轮询状态与日志，或使用 claude_job_status / claude_job_logs skill。",
        }

    def _start_next_queued(self, session_id: str) -> None:
        with self._queue_lock:
            rows = self._store.list_claude_jobs(session_id, limit=200)
            for r in rows:
                self._refresh_running(r["id"], r)
            rows = self._store.list_claude_jobs(session_id, limit=200)
            if any(r.get("status") == "running" for r in rows):
                return
            queued = [r for r in rows if r.get("status") == "queued"]
            if not queued:
                return
            queued.sort(key=lambda x: str(x.get("created_at") or ""))
            row = queued[0]
            self._spawn_job_process(
                job_id=row["id"],
                session_id=row["session_id"],
                workspace_path=row["workspace_path"],
                prompt=row["prompt"],
                max_turns=row.get("max_turns"),
                context_mode=row.get("context_mode") or "continue",
            )

    def _wait_and_finalize(self, job_id: str, proc: subprocess.Popen[Any]) -> None:
        code = 1
        session_id = ""
        try:
            try:
                job_row = self._store.get_claude_job(job_id)
                session_id = str(job_row.get("session_id") or "")
            except KeyError:
                session_id = ""
            code = int(proc.wait())
        except Exception as exc:  # noqa: BLE001
            self._store.update_claude_job(
                job_id,
                status="failed",
                exit_code=1,
                error_summary=f"wait_error:{type(exc).__name__}:{exc}",
            )
            with self._lock:
                self._procs.pop(job_id, None)
            if session_id:
                self._start_next_queued(session_id)
            return

        log_path = self._log_path(job_id)
        tail = _tail_bytes(log_path, 120_000)
        summary = tail.strip()[-4000:] if tail else ""
        claude_sid = _extract_session_id(tail)
        try:
            row = self._store.get_claude_job(job_id)
            if row.get("status") == "cancelled":
                with self._lock:
                    self._procs.pop(job_id, None)
                if session_id:
                    self._start_next_queued(session_id)
                return
        except KeyError:
            with self._lock:
                self._procs.pop(job_id, None)
            return

        self._store.update_claude_job(
            job_id,
            status="completed" if code == 0 else "failed",
            exit_code=code,
            result_summary=summary,
            claude_session_id=claude_sid,
        )
        self._trim_log_if_oversize(job_id)
        with self._lock:
            self._procs.pop(job_id, None)
        if session_id:
            self._start_next_queued(session_id)

    def _reap_running_once(self) -> None:
        sessions = self._store.list_sessions(include_archived=True)
        for s in sessions:
            sid = str(s.id or "")
            if not sid:
                continue
            rows = self._store.list_claude_jobs(sid, limit=200)
            had_running = False
            for r in rows:
                if r.get("status") != "running":
                    continue
                had_running = True
                self._refresh_running(str(r.get("id") or ""), r)
            if had_running:
                self._start_next_queued(sid)

    def _running_job_reaper_loop(self) -> None:
        while True:
            try:
                self._reap_running_once()
            except Exception:
                pass
            time.sleep(self._reaper_interval)

    def start_job(
        self,
        *,
        session_id: str,
        workdir: str,
        prompt: str,
        max_turns: int | None = None,
        context_mode: str = "continue",
    ) -> dict[str, Any]:
        reason = claude_code_unavailable_reason()
        if reason:
            return {"ok": False, "error": "unavailable", "message": reason}

        p = (prompt or "").strip()
        if not p:
            return {"ok": False, "error": "empty_prompt", "message": "prompt 不能为空。"}

        try:
            session = self._store.get_session(session_id)
        except KeyError:
            return {"ok": False, "error": "session_not_found", "message": "会话不存在。"}

        expected = _normalize_path(session.workspace_path or ".")
        actual = _normalize_path(workdir)
        if actual != expected:
            return {
                "ok": False,
                "error": "workspace_mismatch",
                "message": f"工作目录必须与当前会话一致：期望 {expected}，实际 {actual}。",
            }

        os.makedirs(actual, exist_ok=True)
        job_id = uuid.uuid4().hex
        self._jobs_root.mkdir(parents=True, exist_ok=True)
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        log_relpath = f"{job_id}/run.log"
        self._store.create_claude_job(
            job_id=job_id,
            session_id=session_id,
            workspace_path=actual,
            prompt=p[:50_000],
            context_mode=context_mode,
            max_turns=max_turns,
            status="queued",
            pid=None,
            log_relpath=log_relpath,
            error_summary="queued_waiting_previous_job",
        )
        self._start_next_queued(session_id)
        row = self._store.get_claude_job(job_id)
        if row.get("status") == "queued":
            running_id = ""
            rows = self._store.list_claude_jobs(session_id, limit=50)
            for r in rows:
                if r.get("status") == "running":
                    running_id = str(r.get("id") or "")
                    break
            return {
                "ok": True,
                "job_id": job_id,
                "status": "queued",
                "workspace_path": actual,
                "context_mode": context_mode,
                "queued_after_job_id": running_id,
                "hint": "当前会话已有运行中任务；本任务已入队，前序完成后将自动续接共享上下文执行。",
            }
        return {
            "ok": True,
            "job_id": job_id,
            "status": "running",
            "workspace_path": actual,
            "context_mode": context_mode,
            "claude_session_id": row.get("claude_session_id") or "",
            "hint": "任务已启动；可在「Claude」面板轮询状态与日志。",
        }

    def _refresh_running(self, job_id: str, row: dict[str, Any]) -> None:
        if row.get("status") != "running":
            return
        with self._lock:
            proc = self._procs.get(job_id)
        if proc is None:
            # 可能是服务重启后内存句柄丢失：用 PID 兜底探活。
            if _pid_alive(row.get("pid")):
                return
            self._finalize_stale_running(job_id)
            return
        poll = proc.poll()
        if poll is None:
            return
        # 进程已结束而守护线程尚未写库：同步收尾
        self._wait_and_finalize(job_id, proc)

    def _finalize_stale_running(self, job_id: str) -> None:
        """兜底回收：running 但进程已不存在（常见于服务重启后）。"""
        try:
            row = self._store.get_claude_job(job_id)
        except KeyError:
            return
        if row.get("status") != "running":
            return
        log_path = self._jobs_root / str(row.get("log_relpath") or "")
        tail = _tail_bytes(log_path, 120_000)
        summary = tail.strip()[-4000:] if tail else ""
        low = (tail or "").lower()
        looks_error = ("api error" in low) or ("traceback" in low) or ("error:" in low)
        if not tail:
            self._store.update_claude_job(
                job_id,
                status="failed",
                exit_code=1,
                error_summary="stale_running_no_process_no_log",
            )
            return
        self._store.update_claude_job(
            job_id,
            status="failed" if looks_error else "completed",
            exit_code=1 if looks_error else 0,
            error_summary="stale_running_log_indicates_error" if looks_error else "stale_running_recovered",
            result_summary=summary,
            claude_session_id=_extract_session_id(tail),
        )

    def get_job(self, session_id: str, job_id: str) -> dict[str, Any]:
        row = self._store.get_claude_job(job_id)
        if row["session_id"] != session_id:
            raise PermissionError("job 不属于该会话")
        self._refresh_running(job_id, row)
        self._start_next_queued(session_id)
        return self._store.get_claude_job(job_id)

    def list_jobs(self, session_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._store.list_claude_jobs(session_id, limit=limit)
        for r in rows:
            self._refresh_running(r["id"], r)
        self._start_next_queued(session_id)
        self._cleanup_old_logs(session_id)
        return self._store.list_claude_jobs(session_id, limit=limit)

    def tail_logs(self, session_id: str, job_id: str, *, tail_lines: int = 200) -> str:
        row = self.get_job(session_id, job_id)
        path = self._jobs_root / row["log_relpath"]
        self._trim_log_if_oversize(job_id)
        text = _tail_bytes(path, 512_000)
        if not text:
            return ""
        lines = text.splitlines()
        n = max(1, min(int(tail_lines), 5000))
        return "\n".join(lines[-n:])

    def cancel_job(self, session_id: str, job_id: str) -> dict[str, Any]:
        row = self._store.get_claude_job(job_id)
        if row["session_id"] != session_id:
            raise PermissionError("job 不属于该会话")
        if row["status"] not in ("running", "queued"):
            return {"ok": True, "status": row["status"], "message": "任务已结束，无需取消。"}
        if row["status"] == "queued":
            self._store.update_claude_job(
                job_id,
                status="cancelled",
                exit_code=-1,
                error_summary="user_cancelled_while_queued",
            )
            return {"ok": True, "status": "cancelled"}
        pid = row.get("pid")
        if not pid:
            self._store.update_claude_job(job_id, status="cancelled", exit_code=-1, error_summary="no_pid")
            return {"ok": True, "status": "cancelled"}

        with self._lock:
            proc = self._procs.get(job_id)
        try:
            try:
                os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
            except AttributeError:
                os.kill(int(pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                if proc:
                    proc.terminate()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}

        self._store.update_claude_job(
            job_id,
            status="cancelled",
            exit_code=-15,
            error_summary="user_cancelled",
        )
        with self._lock:
            self._procs.pop(job_id, None)
        self._start_next_queued(session_id)
        return {"ok": True, "status": "cancelled"}
