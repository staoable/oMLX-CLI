# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
"""运行环境与本地数据目录诊断（不含密钥与上游连通性）。"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from oi_runtime_core import upstream_llm_protocol

from webapi.claude_job_service import claude_code_public_status


def _default_paths(root: Path) -> tuple[Path, Path, Path, str]:
    data_dir = Path(os.getenv("OMLXCLI_DATA_DIR", str(root / ".omlxcli" / "web")))
    db_path = data_dir / "sessions.db"
    webui_dir = root / "webui"
    default_workspace = os.path.abspath(
        os.path.expanduser(os.getenv("OMLXCLI_DEFAULT_WORKSPACE", str(root)))
    )
    return data_dir, db_path, webui_dir, default_workspace


def _sqlite_meta(db_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "reachable": False,
        "sqlite_version": None,
        "sessions_count": None,
        "vendors_count": None,
    }
    if not db_path.is_file():
        return out
    try:
        conn = sqlite3.connect(str(db_path), timeout=1.0)
        try:
            row = conn.execute("SELECT sqlite_version()").fetchone()
            out["sqlite_version"] = row[0] if row else None
            out["reachable"] = True
            try:
                out["sessions_count"] = int(
                    conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                )
            except sqlite3.OperationalError:
                out["sessions_count"] = None
            try:
                out["vendors_count"] = int(
                    conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
                )
            except sqlite3.OperationalError:
                out["vendors_count"] = None
        finally:
            conn.close()
    except OSError:
        pass
    return out


def _node_version() -> tuple[bool, str | None]:
    node = shutil.which("node")
    if not node:
        return False, None
    try:
        proc = subprocess.run(
            [node, "-v"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if proc.returncode == 0:
            v = (proc.stdout or "").strip()
            return True, v or None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return True, None


def _playwright_import() -> dict[str, Any]:
    try:
        import importlib.metadata

        import playwright  # noqa: F401

        try:
            ver = importlib.metadata.version("playwright")
        except importlib.metadata.PackageNotFoundError:
            ver = ""
        return {"import_ok": True, "version": ver or None}
    except ImportError:
        return {"import_ok": False, "version": None}


def build_diagnostics_payload(
    *,
    root: Path,
    data_dir: Path,
    db_path: Path,
    webui_dir: Path,
    default_workspace: str,
) -> dict[str, Any]:
    meta = _sqlite_meta(db_path)
    node_on_path, node_ver = _node_version()
    vendors_n = meta.get("vendors_count")
    sessions_n = meta.get("sessions_count")
    return {
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "platform": sys.platform,
        "paths": {
            "project_root": str(root),
            "data_dir": str(data_dir),
            "db_path": str(db_path),
            "db_exists": db_path.is_file(),
            "webui_dir": str(webui_dir),
            "webui_exists": webui_dir.is_dir(),
            "default_workspace": default_workspace,
        },
        "sqlite": {
            "reachable": bool(meta.get("reachable")),
            "version": meta.get("sqlite_version"),
        },
        "store": {
            "vendors_count": 0 if vendors_n is None else int(vendors_n),
            "sessions_count": 0 if sessions_n is None else int(sessions_n),
        },
        "node": {"on_path": node_on_path, "version": node_ver},
        "npm": {"on_path": bool(shutil.which("npm"))},
        "uv": {"on_path": bool(shutil.which("uv"))},
        "playwright": _playwright_import(),
        "claude_code": claude_code_public_status(),
        "llm_transport": {
            "protocol": upstream_llm_protocol(),
        },
    }


def main() -> None:
    from webapi.dotenv_loader import load_dotenv_files

    root = Path(__file__).resolve().parent.parent
    load_dotenv_files(root)
    data_dir, db_path, webui_dir, default_workspace = _default_paths(root)
    payload = build_diagnostics_payload(
        root=root,
        data_dir=data_dir,
        db_path=db_path,
        webui_dir=webui_dir,
        default_workspace=default_workspace,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
