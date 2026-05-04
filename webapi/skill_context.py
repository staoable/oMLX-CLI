# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
"""run_skill 调用链上的会话上下文（供需要 session / 工作区的技能读取）。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

session_id_var: ContextVar[str | None] = ContextVar("skill_session_id", default=None)
workdir_var: ContextVar[str | None] = ContextVar("skill_workdir", default=None)


@contextmanager
def skill_run_context(*, session_id: str, workdir: str) -> Iterator[None]:
    t_sid = session_id_var.set(session_id)
    t_wd = workdir_var.set(workdir)
    try:
        yield
    finally:
        session_id_var.reset(t_sid)
        workdir_var.reset(t_wd)


def get_skill_session_id() -> str | None:
    return session_id_var.get()


def get_skill_workdir() -> str | None:
    return workdir_var.get()
