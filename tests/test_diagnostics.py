# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from webapi.diagnostics import build_diagnostics_payload


class DiagnosticsTests(unittest.TestCase):
    def test_payload_shape_and_sqlite_counts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"
            data = root / "data"
            data.mkdir(parents=True)
            db = data / "sessions.db"
            conn = sqlite3.connect(str(db))
            try:
                conn.execute(
                    "CREATE TABLE sessions (id TEXT PRIMARY KEY);"
                )
                conn.execute("INSERT INTO sessions (id) VALUES ('a');")
                conn.execute("CREATE TABLE vendors (id TEXT PRIMARY KEY);")
                conn.execute("INSERT INTO vendors (id) VALUES ('v1');")
                conn.commit()
            finally:
                conn.close()
            webui = root / "webui"
            webui.mkdir()
            payload = build_diagnostics_payload(
                root=root,
                data_dir=data,
                db_path=db,
                webui_dir=webui,
                default_workspace=str(root),
            )
            self.assertIn("python", payload)
            self.assertIn("claude_code", payload)
            self.assertIn("llm_transport", payload)
            self.assertIn(payload["llm_transport"]["protocol"], ("chat", "completions", "auto"))
            self.assertTrue(payload["paths"]["db_exists"])
            self.assertTrue(payload["sqlite"]["reachable"])
            self.assertEqual(payload["store"]["sessions_count"], 1)
            self.assertEqual(payload["store"]["vendors_count"], 1)
            # 确保可 JSON 序列化且无异常嵌套
            json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
