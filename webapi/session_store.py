from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SessionRecord:
    id: str
    title: str
    title_locked: bool
    workspace_path: str
    model: str
    api_base: str
    auto_run: bool
    execution_enabled: bool
    confirm_each: bool
    pending_command: str
    summary: str
    archived: bool
    created_at: str
    updated_at: str
    last_active_at: str


class SessionStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    title_locked INTEGER NOT NULL DEFAULT 0,
                    workspace_path TEXT NOT NULL,
                    model TEXT NOT NULL,
                    api_base TEXT NOT NULL,
                    auto_run INTEGER NOT NULL DEFAULT 1,
                    execution_enabled INTEGER NOT NULL DEFAULT 0,
                    confirm_each INTEGER NOT NULL DEFAULT 1,
                    pending_command TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_active_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'message',
                    attachments TEXT NOT NULL DEFAULT '[]',
                    token_estimate INTEGER NOT NULL DEFAULT 0,
                    metrics_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS contexts (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    layer TEXT NOT NULL,
                    content TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS executions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    exec_type TEXT NOT NULL,
                    command TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    exit_code INTEGER,
                    stdout TEXT NOT NULL DEFAULT '',
                    stderr TEXT NOT NULL DEFAULT '',
                    duration_ms REAL,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS context_injections (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    role TEXT NOT NULL,
                    char_count INTEGER NOT NULL DEFAULT 0,
                    dropped INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS agent_trace (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                """
            )
            self._migrate_sessions(conn)
            self._migrate_messages(conn)
            self._migrate_executions(conn)
            self._migrate_contexts(conn)

    def _migrate_sessions(self, conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if "title_locked" not in cols:
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN title_locked INTEGER NOT NULL DEFAULT 0"
            )
        if "execution_enabled" not in cols:
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN execution_enabled INTEGER NOT NULL DEFAULT 0"
            )
        if "confirm_each" not in cols:
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN confirm_each INTEGER NOT NULL DEFAULT 1"
            )
        if "pending_command" not in cols:
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN pending_command TEXT NOT NULL DEFAULT ''"
            )
        if "archived" not in cols:
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
            )

    def _migrate_contexts(self, conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(contexts)").fetchall()}
        if not cols:
            return
        if "priority" not in cols:
            conn.execute(
                "ALTER TABLE contexts ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
            )

    def _migrate_messages(self, conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
        if "metrics_json" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN metrics_json TEXT")

    def _migrate_executions(self, conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(executions)").fetchall()}
        if not cols:
            return
        if "reason" not in cols:
            conn.execute("ALTER TABLE executions ADD COLUMN reason TEXT NOT NULL DEFAULT ''")
        if "metadata_json" not in cols:
            conn.execute("ALTER TABLE executions ADD COLUMN metadata_json TEXT")

    def add_context_injection(
        self,
        *,
        session_id: str,
        source: str,
        role: str,
        char_count: int,
        dropped: bool = False,
        reason: str = "",
    ) -> dict[str, Any]:
        row_id = str(uuid.uuid4())
        now = _now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO context_injections (
                    id, session_id, source, role, char_count, dropped, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row_id, session_id, source, role, int(char_count), int(bool(dropped)), reason, now),
            )
        return {
            "id": row_id,
            "session_id": session_id,
            "source": source,
            "role": role,
            "char_count": int(char_count),
            "dropped": bool(dropped),
            "reason": reason,
            "created_at": now,
        }

    def list_context_injections(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM context_injections
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "source": r["source"],
                "role": r["role"],
                "char_count": int(r["char_count"]),
                "dropped": bool(r["dropped"]),
                "reason": r["reason"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def create_session(
        self,
        *,
        title: str,
        workspace_path: str,
        model: str,
        api_base: str,
        auto_run: bool,
    ) -> SessionRecord:
        now = _now_iso()
        session_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    id, title, title_locked, workspace_path, model, api_base, auto_run, execution_enabled, confirm_each, pending_command, summary, archived, created_at, updated_at, last_active_at
                ) VALUES (?, ?, 0, ?, ?, ?, ?, 0, 1, '', '', 0, ?, ?, ?)
                """,
                (session_id, title, workspace_path, model, api_base, int(auto_run), now, now, now),
            )
        return self.get_session(session_id)

    def list_sessions(self, *, include_archived: bool = False) -> list[SessionRecord]:
        with self._conn() as conn:
            if include_archived:
                rows = conn.execute(
                    "SELECT * FROM sessions ORDER BY last_active_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM sessions
                    WHERE COALESCE(archived, 0) = 0
                    ORDER BY last_active_at DESC
                    """
                ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def get_session(self, session_id: str) -> SessionRecord:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(f"Session not found: {session_id}")
        return self._row_to_session(row)

    def update_session(self, session_id: str, **updates: Any) -> SessionRecord:
        allowed = {
            "title",
            "title_locked",
            "workspace_path",
            "model",
            "api_base",
            "auto_run",
            "execution_enabled",
            "confirm_each",
            "pending_command",
            "summary",
            "archived",
        }
        fields = {k: v for k, v in updates.items() if k in allowed and v is not None}
        if "title_locked" in fields:
            fields["title_locked"] = int(bool(fields["title_locked"]))
        if "execution_enabled" in fields:
            fields["execution_enabled"] = int(bool(fields["execution_enabled"]))
        if "confirm_each" in fields:
            fields["confirm_each"] = int(bool(fields["confirm_each"]))
        if "archived" in fields:
            fields["archived"] = int(bool(fields["archived"]))
        if not fields:
            return self.get_session(session_id)
        fields["updated_at"] = _now_iso()
        fields["last_active_at"] = fields["updated_at"]
        keys = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [session_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE sessions SET {keys} WHERE id = ?", values)
        return self.get_session(session_id)

    def delete_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        kind: str = "message",
        attachments: list[dict[str, Any]] | None = None,
        token_estimate: int = 0,
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now_iso()
        message_id = str(uuid.uuid4())
        metrics_blob = json.dumps(metrics, ensure_ascii=False) if metrics else None
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO messages (
                    id, session_id, role, content, kind, attachments, token_estimate, metrics_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    session_id,
                    role,
                    content,
                    kind,
                    json.dumps(attachments or [], ensure_ascii=False),
                    token_estimate,
                    metrics_blob,
                    now,
                ),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ?, last_active_at = ? WHERE id = ?",
                (now, now, session_id),
            )
        return {
            "id": message_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "kind": kind,
            "attachments": attachments or [],
            "token_estimate": token_estimate,
            "metrics": metrics,
            "created_at": now,
        }

    def list_messages(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE session_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        out = []
        for r in rows:
            keys = r.keys()
            raw_metrics = r["metrics_json"] if "metrics_json" in keys else None
            metrics = json.loads(raw_metrics) if raw_metrics else None
            out.append(
                {
                    "id": r["id"],
                    "session_id": r["session_id"],
                    "role": r["role"],
                    "content": r["content"],
                    "kind": r["kind"],
                    "attachments": json.loads(r["attachments"] or "[]"),
                    "token_estimate": r["token_estimate"],
                    "metrics": metrics,
                    "created_at": r["created_at"],
                }
            )
        return out

    def add_context(
        self,
        *,
        session_id: str,
        layer: str,
        content: str,
        priority: int = 0,
    ) -> dict[str, Any]:
        context_id = str(uuid.uuid4())
        now = _now_iso()
        pri = int(priority)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO contexts (id, session_id, layer, content, priority, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (context_id, session_id, layer, content, pri, now),
            )
        return {
            "id": context_id,
            "session_id": session_id,
            "layer": layer,
            "content": content,
            "priority": pri,
            "created_at": now,
        }

    def delete_contexts_by_layer(self, session_id: str, layer: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM contexts WHERE session_id = ? AND layer = ?",
                (session_id, layer),
            )
            return int(cur.rowcount or 0)

    def list_contexts(self, session_id: str, layer: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if layer:
                rows = conn.execute(
                    """
                    SELECT * FROM contexts
                    WHERE session_id = ? AND layer = ?
                    ORDER BY priority DESC, created_at DESC
                    """,
                    (session_id, layer),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM contexts
                    WHERE session_id = ?
                    ORDER BY priority DESC, created_at DESC
                    """,
                    (session_id,),
                ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            keys = r.keys()
            pri = int(r["priority"]) if "priority" in keys else 0
            out.append(
                {
                    "id": r["id"],
                    "session_id": r["session_id"],
                    "layer": r["layer"],
                    "content": r["content"],
                    "priority": pri,
                    "created_at": r["created_at"],
                }
            )
        return out

    def add_checkpoint(
        self,
        *,
        session_id: str,
        summary: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        checkpoint_id = str(uuid.uuid4())
        now = _now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO checkpoints (id, session_id, summary, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (checkpoint_id, session_id, summary, json.dumps(payload, ensure_ascii=False), now),
            )
        return {
            "id": checkpoint_id,
            "session_id": session_id,
            "summary": summary,
            "payload": payload,
            "created_at": now,
        }

    def list_checkpoints(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM checkpoints
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "summary": r["summary"],
                "payload": json.loads(r["payload_json"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def add_execution(
        self,
        *,
        session_id: str,
        exec_type: str,
        command: str,
        status: str,
        reason: str = "",
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
        duration_ms: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        execution_id = str(uuid.uuid4())
        now = _now_iso()
        metadata_blob = json.dumps(metadata, ensure_ascii=False) if metadata else None
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO executions (
                    id, session_id, exec_type, command, status, reason, exit_code, stdout, stderr, duration_ms, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    session_id,
                    exec_type,
                    command,
                    status,
                    reason,
                    exit_code,
                    stdout,
                    stderr,
                    duration_ms,
                    metadata_blob,
                    now,
                ),
            )
        return {
            "id": execution_id,
            "session_id": session_id,
            "exec_type": exec_type,
            "command": command,
            "status": status,
            "reason": reason,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": duration_ms,
            "metadata": metadata,
            "created_at": now,
        }

    def list_executions(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM executions
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            raw_meta = r["metadata_json"] if "metadata_json" in r.keys() else None
            meta = json.loads(raw_meta) if raw_meta else None
            out.append(
                {
                    "id": r["id"],
                    "session_id": r["session_id"],
                    "exec_type": r["exec_type"],
                    "command": r["command"],
                    "status": r["status"],
                    "reason": r["reason"],
                    "exit_code": r["exit_code"],
                    "stdout": r["stdout"],
                    "stderr": r["stderr"],
                    "duration_ms": r["duration_ms"],
                    "metadata": meta,
                    "created_at": r["created_at"],
                }
            )
        return out

    def add_agent_trace(
        self,
        *,
        session_id: str,
        turn_id: str,
        step_index: int,
        action_type: str,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row_id = str(uuid.uuid4())
        now = _now_iso()
        blob = json.dumps(detail or {}, ensure_ascii=False)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO agent_trace (
                    id, session_id, turn_id, step_index, action_type, detail_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (row_id, session_id, turn_id, int(step_index), action_type, blob, now),
            )
        return {
            "id": row_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "step_index": int(step_index),
            "action_type": action_type,
            "detail": detail or {},
            "created_at": now,
        }

    def list_agent_trace(
        self,
        session_id: str,
        *,
        turn_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._conn() as conn:
            if turn_id:
                rows = conn.execute(
                    """
                    SELECT * FROM agent_trace
                    WHERE session_id = ? AND turn_id = ?
                    ORDER BY step_index ASC, created_at ASC
                    LIMIT ?
                    """,
                    (session_id, turn_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM agent_trace
                    WHERE session_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (session_id, limit),
                ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "session_id": r["session_id"],
                    "turn_id": r["turn_id"],
                    "step_index": int(r["step_index"]),
                    "action_type": r["action_type"],
                    "detail": json.loads(r["detail_json"] or "{}"),
                    "created_at": r["created_at"],
                }
            )
        if not turn_id:
            out.reverse()
        return out

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> SessionRecord:
        keys = row.keys()
        title_locked = bool(row["title_locked"]) if "title_locked" in keys else False
        execution_enabled = bool(row["execution_enabled"]) if "execution_enabled" in keys else False
        confirm_each = bool(row["confirm_each"]) if "confirm_each" in keys else True
        pending_command = str(row["pending_command"]) if "pending_command" in keys else ""
        archived = bool(row["archived"]) if "archived" in keys else False
        return SessionRecord(
            id=row["id"],
            title=row["title"],
            title_locked=title_locked,
            workspace_path=row["workspace_path"],
            model=row["model"],
            api_base=row["api_base"],
            auto_run=bool(row["auto_run"]),
            execution_enabled=execution_enabled,
            confirm_each=confirm_each,
            pending_command=pending_command,
            summary=row["summary"],
            archived=archived,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_active_at=row["last_active_at"],
        )
