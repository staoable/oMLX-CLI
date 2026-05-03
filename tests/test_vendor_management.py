"""模型设置（vendors）表与会话 vendor_id 的回归测试。"""

from __future__ import annotations

import os
import tempfile
import unittest

from webapi.session_store import SessionStore
from webapi.upstream_credentials import resolve_upstream_credentials


class VendorManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        path = os.path.join(self._td.name, "sessions.db")
        self.store = SessionStore(path)

    def test_count_vendors_zero_resolve_raises(self) -> None:
        s = self.store.create_session(
            title="s",
            workspace_path="/tmp",
            model="m",
            api_base="",
            auto_run=True,
            vendor_id=None,
        )
        loaded = self.store.get_session(s.id)
        with self.assertRaises(RuntimeError) as ctx:
            resolve_upstream_credentials(loaded, self.store)
        self.assertIn("尚未配置", str(ctx.exception))

    def test_create_vendor_and_session_binding(self) -> None:
        v = self.store.create_vendor(
            name="Test Upstream",
            slug="testup",
            api_base="https://example.com",
            default_model="m1",
            api_key="secret-x",
        )
        self.assertEqual(v.slug, "testup")
        s = self.store.create_session(
            title="s",
            workspace_path="/tmp",
            model="m0",
            api_base="http://ignored",
            auto_run=True,
            vendor_id=v.id,
        )
        self.assertEqual(s.vendor_id, v.id)
        loaded = self.store.get_session(s.id)
        base, key = resolve_upstream_credentials(loaded, self.store)
        self.assertEqual(base, "https://example.com")
        self.assertEqual(key, "secret-x")

    def test_invalid_slug(self) -> None:
        with self.assertRaises(ValueError):
            self.store.create_vendor(name="a", slug="9bad", api_base="https://x.com")

    def test_slug_from_display_name_ascii(self) -> None:
        self.assertEqual(SessionStore.slug_from_display_name("DeepSeek 工作"), "deepseek")
        self.assertEqual(SessionStore.slug_from_display_name("My-Vendor"), "my_vendor")
        self.assertEqual(SessionStore.slug_from_display_name("123abc"), "v123abc")

    def test_slug_from_display_name_cjk_fallback(self) -> None:
        self.assertEqual(SessionStore.slug_from_display_name("深度求索"), "vendor")

    def test_allocate_unique_vendor_slug_suffix(self) -> None:
        self.store.create_vendor(name="A", slug="a", api_base="https://a.com")
        s = self.store.allocate_unique_vendor_slug("A")
        self.assertEqual(s, "a_2")

    def test_delete_vendor_blocked_when_session_references(self) -> None:
        v = self.store.create_vendor(name="v", slug="vref", api_base="https://x.com")
        self.store.create_session(
            title="s",
            workspace_path="/tmp",
            model="m",
            api_base="https://x.com",
            auto_run=True,
            vendor_id=v.id,
        )
        with self.assertRaises(ValueError):
            self.store.delete_vendor(v.id)


if __name__ == "__main__":
    unittest.main()
