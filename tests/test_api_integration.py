from __future__ import annotations

import importlib
import os
import tempfile
import unittest

try:
    from fastapi.testclient import TestClient
except Exception:  # noqa: BLE001
    TestClient = None  # type: ignore[assignment]


class ApiIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if TestClient is None:
            raise unittest.SkipTest("fastapi/testclient 不可用，跳过 API 集成测试")
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._old_data_dir = os.environ.get("OMLXCLI_DATA_DIR")
        cls._old_workspace = os.environ.get("OMLXCLI_DEFAULT_WORKSPACE")
        os.environ["OMLXCLI_DATA_DIR"] = cls._tmpdir.name
        os.environ["OMLXCLI_DEFAULT_WORKSPACE"] = cls._tmpdir.name
        import webapi.app as app_module  # noqa: WPS433

        cls.app_module = importlib.reload(app_module)
        cls.client = TestClient(cls.app_module.app)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._old_data_dir is None:
            os.environ.pop("OMLXCLI_DATA_DIR", None)
        else:
            os.environ["OMLXCLI_DATA_DIR"] = cls._old_data_dir
        if cls._old_workspace is None:
            os.environ.pop("OMLXCLI_DEFAULT_WORKSPACE", None)
        else:
            os.environ["OMLXCLI_DEFAULT_WORKSPACE"] = cls._old_workspace
        cls._tmpdir.cleanup()

    def test_session_crud_and_observability_endpoints(self) -> None:
        created = self.client.post("/api/sessions", json={"title": "集成测试会话"})
        self.assertEqual(created.status_code, 200)
        payload = created.json()
        sid = payload["id"]

        got = self.client.get(f"/api/sessions/{sid}")
        self.assertEqual(got.status_code, 200)
        full = got.json()
        self.assertIn("executions", full)
        self.assertIn("context_injections", full)

        execs = self.client.get(f"/api/sessions/{sid}/executions?limit=5")
        self.assertEqual(execs.status_code, 200)
        self.assertIsInstance(execs.json(), list)

        ctx_rows = self.client.get(f"/api/sessions/{sid}/context-injections?limit=5")
        self.assertEqual(ctx_rows.status_code, 200)
        self.assertIsInstance(ctx_rows.json(), list)

        deleted = self.client.delete(f"/api/sessions/{sid}")
        self.assertEqual(deleted.status_code, 200)

    def test_confirm_command_reject_records_execution(self) -> None:
        created = self.client.post("/api/sessions", json={"title": "命令拒绝测试"})
        sid = created.json()["id"]

        # 直接走拒绝确认分支，应写入 cancelled 审计记录
        rejected = self.client.post(
            f"/api/sessions/{sid}/confirm-command",
            json={"command": "rm -rf /tmp/foo", "approve": False},
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["status"], "cancelled")

        execs = self.client.get(f"/api/sessions/{sid}/executions?limit=20").json()
        self.assertTrue(any(item.get("status") == "cancelled" for item in execs))

    def test_send_message_sse_and_request_id_header(self) -> None:
        created = self.client.post("/api/sessions", json={"title": "SSE测试"})
        sid = created.json()["id"]

        def fake_stream_reply(**_kwargs):
            yield {"type": "delta", "content": "hello"}
            yield {"type": "metrics", "ttft_ms": 1.0, "gen_duration_ms": 2.0, "tps": 3.0}

        self.app_module.engine.stream_reply = fake_stream_reply
        with self.client.stream(
            "POST",
            f"/api/sessions/{sid}/messages",
            json={"content": "你好"},
            headers={"x-request-id": "test-rid-1"},
        ) as resp:
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("x-request-id"), "test-rid-1")
            raw = "".join(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk for chunk in resp.iter_raw())
        self.assertIn("event: delta", raw)
        self.assertIn("event: done", raw)

    def test_error_shape_contains_error_code_and_request_id(self) -> None:
        bad = self.client.get("/api/sessions/not-exist")
        self.assertEqual(bad.status_code, 404)
        body = bad.json()
        self.assertIn("error_code", body)
        self.assertIn("request_id", body)
        self.assertIn("message", body)

    def test_execution_policy_configurable_via_env(self) -> None:
        sid = self.client.post("/api/sessions", json={"title": "策略测试"}).json()["id"]
        old = os.environ.get("OMLXCLI_EXEC_BLOCKLIST_RE")
        os.environ["OMLXCLI_EXEC_BLOCKLIST_RE"] = r"\b(echo)\b"
        try:
            self.app_module.store.update_session(sid, execution_enabled=True, confirm_each=False)
            res = self.client.post(
                f"/api/sessions/{sid}/messages",
                json={"content": "确认执行: echo hi"},
            )
            self.assertEqual(res.status_code, 200)
            # SSE 文本中应包含“命令被安全策略阻止”
            text = res.text
            self.assertIn("命令被安全策略阻止", text)
        finally:
            if old is None:
                os.environ.pop("OMLXCLI_EXEC_BLOCKLIST_RE", None)
            else:
                os.environ["OMLXCLI_EXEC_BLOCKLIST_RE"] = old


if __name__ == "__main__":
    unittest.main()
