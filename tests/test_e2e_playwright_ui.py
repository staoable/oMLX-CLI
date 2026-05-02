"""浏览器 E2E：拉起 uvicorn 后由 Playwright 访问 /ui/（CI 必跑）。

本地未安装 playwright 时整类跳过，不影响 `unittest discover` 其它用例。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None  # type: ignore[misc, assignment]

_ROOT = Path(__file__).resolve().parents[1]


def _pick_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    _host, port = s.getsockname()
    s.close()
    return int(port)


def _wait_healthz(port: int, *, timeout_sec: float = 60.0) -> None:
    url = f"http://127.0.0.1:{port}/healthz"
    deadline = time.time() + timeout_sec
    last_err: str | None = None
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if int(resp.status) == 200:
                    return
        except (urllib.error.URLError, OSError) as exc:
            last_err = str(exc)
        time.sleep(0.35)
    raise RuntimeError(f"healthz 未就绪: {url} 最后错误: {last_err}")


@unittest.skipUnless(sync_playwright is not None, "未安装 playwright，跳过 E2E（CI 已安装）")
class PlaywrightUiSmokeTest(unittest.TestCase):
    _proc: subprocess.Popen | None = None
    _tmpdir: tempfile.TemporaryDirectory | None = None
    _port: int = 0

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._port = _pick_free_port()
        data_dir = cls._tmpdir.name
        env = os.environ.copy()
        env["OMLXCLI_DATA_DIR"] = data_dir
        env["OMLXCLI_DEFAULT_WORKSPACE"] = data_dir
        cls._proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "webapi.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(cls._port),
            ],
            cwd=str(_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_healthz(cls._port)
        except Exception:
            if cls._proc.poll() is not None:
                print(f"[e2e] uvicorn 已退出 code={cls._proc.returncode}", file=sys.stderr)
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._proc is not None:
            cls._proc.terminate()
            try:
                cls._proc.wait(timeout=12)
            except subprocess.TimeoutExpired:
                cls._proc.kill()
            cls._proc = None
        if cls._tmpdir is not None:
            cls._tmpdir.cleanup()
            cls._tmpdir = None

    def test_ui_loads_title_and_new_session_button(self) -> None:
        assert sync_playwright is not None
        base = f"http://127.0.0.1:{self._port}"
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as exc:  # noqa: BLE001
                raise unittest.SkipTest(
                    "Chromium 未安装。请执行: python -m playwright install chromium"
                ) from exc
            try:
                page = browser.new_page()
                page.goto(f"{base}/ui/", wait_until="domcontentloaded", timeout=60000)
                self.assertEqual(page.title(), "oMLX CLI")
                self.assertIn("新建会话", page.content())
                btn = page.get_by_role("button", name="新建会话")
                btn.wait_for(state="visible", timeout=15000)
            finally:
                browser.close()
