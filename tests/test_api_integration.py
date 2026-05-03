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
        vr = cls.client.post(
            "/api/vendors",
            json={
                "name": "IntegrationTestUpstream",
                "api_base": "http://127.0.0.1:59999/v1",
                "default_model": "",
                "api_key": "dummy-key-for-tests",
            },
        )
        assert vr.status_code == 200, vr.text
        cls._integration_vendor_id = vr.json()["id"]

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
        self.assertIsNone(payload.get("vendor_id"))

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

    def test_session_archived_list_and_batch_archive(self) -> None:
        a = self.client.post("/api/sessions", json={"title": "可见"}).json()["id"]
        b = self.client.post("/api/sessions", json={"title": "归档"}).json()["id"]
        self.client.patch(f"/api/sessions/{b}", json={"archived": True})
        listed = self.client.get("/api/sessions").json()
        self.assertTrue(all(not row.get("archived") for row in listed))
        self.assertIn(a, {row["id"] for row in listed})
        self.assertNotIn(b, {row["id"] for row in listed})
        with_arch = self.client.get("/api/sessions?include_archived=1").json()
        self.assertIn(b, {row["id"] for row in with_arch})
        batch = self.client.post(
            "/api/sessions/batch-archive",
            json={"session_ids": [b], "archived": False},
        )
        self.assertEqual(batch.status_code, 200)
        self.assertGreaterEqual(batch.json().get("updated", 0), 1)
        listed2 = self.client.get("/api/sessions").json()
        self.assertIn(b, {row["id"] for row in listed2})

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
        sid = self.client.post(
            "/api/sessions",
            json={"title": "策略测试", "vendor_id": self.__class__._integration_vendor_id},
        ).json()["id"]
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

    def test_agent_trace_list_endpoint(self) -> None:
        created = self.client.post("/api/sessions", json={"title": "trace 列表"})
        sid = created.json()["id"]
        self.app_module.store.add_agent_trace(
            session_id=sid,
            turn_id="turn-it",
            step_index=0,
            action_type="eval",
            detail={"x": 1},
        )
        r = self.client.get(f"/api/sessions/{sid}/agent-trace?turn_id=turn-it&limit=10")
        self.assertEqual(r.status_code, 200)
        rows = r.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action_type"], "eval")
        self.assertEqual(rows[0]["detail"]["x"], 1)

    def test_admin_audit_export_status_codes(self) -> None:
        created = self.client.post("/api/sessions", json={"title": "审计导出"})
        sid = created.json()["id"]
        old_admin = os.environ.pop("OMLXCLI_ADMIN_TOKEN", None)
        try:
            r501 = self.client.get(f"/api/admin/sessions/{sid}/audit-export")
            self.assertEqual(r501.status_code, 501)
        finally:
            if old_admin is not None:
                os.environ["OMLXCLI_ADMIN_TOKEN"] = old_admin

        os.environ["OMLXCLI_ADMIN_TOKEN"] = "integration-admin-token-xyz"
        try:
            r403 = self.client.get(
                f"/api/admin/sessions/{sid}/audit-export",
                headers={"x-admin-token": "wrong"},
            )
            self.assertEqual(r403.status_code, 403)
            r200 = self.client.get(
                f"/api/admin/sessions/{sid}/audit-export",
                headers={"x-admin-token": "integration-admin-token-xyz"},
            )
            self.assertEqual(r200.status_code, 200)
            body = r200.json()
            self.assertIn("session", body)
            self.assertIn("agent_trace", body)
            self.assertIsInstance(body["agent_trace"], list)
        finally:
            os.environ.pop("OMLXCLI_ADMIN_TOKEN", None)
            if old_admin is not None:
                os.environ["OMLXCLI_ADMIN_TOKEN"] = old_admin

    def test_get_vendor_by_id_includes_api_key(self) -> None:
        vid = self.__class__._integration_vendor_id
        r = self.client.get(f"/api/vendors/{vid}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("api_key"), "dummy-key-for-tests")

    def test_list_vendors_omits_api_key(self) -> None:
        r = self.client.get("/api/vendors")
        self.assertEqual(r.status_code, 200)
        for row in r.json():
            self.assertNotIn("api_key", row)

    def test_patch_clear_vendor_unbinds(self) -> None:
        v = self.client.post(
            "/api/vendors",
            json={
                "name": "Tmp",
                "api_base": "https://upstream.vendor.test/v1",
                "default_model": "",
                "api_key": "k",
            },
        )
        self.assertEqual(v.status_code, 200)
        vid = v.json()["id"]
        sess = self.client.post("/api/sessions", json={"title": "bind", "vendor_id": vid}).json()
        self.assertEqual(sess.get("vendor_id"), vid)
        out = self.client.patch(f"/api/sessions/{sess['id']}", json={"vendor_id": None}).json()
        self.assertIsNone(out.get("vendor_id"))


if __name__ == "__main__":
    unittest.main()
