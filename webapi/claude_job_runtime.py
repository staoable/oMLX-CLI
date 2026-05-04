"""由 app 启动时注入，供 skills 模块解析 Claude Job 服务（避免 skills 直接 import app）。"""

from __future__ import annotations

from pathlib import Path

from webapi.claude_job_service import ClaudeJobService
from webapi.session_store import SessionStore

_store: SessionStore | None = None
_jobs_root: Path | None = None
_service: ClaudeJobService | None = None


def configure_claude_job_runtime(*, store: SessionStore, jobs_root: Path) -> None:
    global _store, _jobs_root, _service
    _store = store
    _jobs_root = jobs_root
    _service = ClaudeJobService(store, jobs_root)


def get_claude_job_service() -> ClaudeJobService:
    if _service is None:
        raise RuntimeError("Claude Job 未初始化：请先启动 Web（configure_claude_job_runtime）。")
    return _service
