# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from oi_runtime_core import chat_completion_once, completion_prompt_from_messages
from webapi.engine_protocol import extract_assistant_text


class UpstreamProtocolTests(unittest.TestCase):
    def test_completion_prompt_from_messages_multipart(self) -> None:
        p = completion_prompt_from_messages(
            [
                {"role": "system", "content": "S"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "hi"},
                        {"type": "image_url", "image_url": {"url": "http://x"}},
                    ],
                },
            ]
        )
        self.assertIn("SYSTEM:\nS", p)
        self.assertIn("USER:\nhi", p)

    def test_extract_assistant_text_completions_shape(self) -> None:
        self.assertEqual(
            extract_assistant_text({"choices": [{"text": "legacy out"}]}),
            "legacy out",
        )

    @mock.patch("oi_runtime_core.urllib.request.urlopen")
    def test_chat_completion_once_completions_protocol(self, m_url: mock.MagicMock) -> None:
        body = json.dumps({"choices": [{"text": "done"}]}).encode("utf-8")

        class _Ok:
            def __enter__(self) -> "_Ok":
                return self

            def __exit__(self, *_a: object) -> None:
                return None

            def read(self) -> bytes:
                return body

        m_url.return_value = _Ok()
        old = os.environ.get("OMLXCLI_UPSTREAM_PROTOCOL")
        os.environ["OMLXCLI_UPSTREAM_PROTOCOL"] = "completions"
        try:
            out = chat_completion_once(
                "http://127.0.0.1:9/v1",
                "k",
                "m",
                [{"role": "user", "content": "hello"}],
                timeout=5,
            )
            self.assertEqual(extract_assistant_text(out), "done")
            called = m_url.call_args[0][0]
            self.assertTrue(called.full_url.endswith("/completions"))
            payload = json.loads(called.data.decode("utf-8"))
            self.assertIn("prompt", payload)
            self.assertNotIn("messages", payload)
        finally:
            if old is None:
                os.environ.pop("OMLXCLI_UPSTREAM_PROTOCOL", None)
            else:
                os.environ["OMLXCLI_UPSTREAM_PROTOCOL"] = old

    @mock.patch("oi_runtime_core.urllib.request.urlopen")
    def test_auto_falls_back_after_404(self, m_url: mock.MagicMock) -> None:
        ok_body = json.dumps({"choices": [{"message": {"content": "from completions"}}]}).encode(
            "utf-8"
        )

        class _Err404:
            def __enter__(self) -> "_Err404":
                return self

            def __exit__(self, *_a: object) -> None:
                return None

            def read(self) -> bytes:
                return b"{}"

        class _Ok:
            def __enter__(self) -> "_Ok":
                return self

            def __exit__(self, *_a: object) -> None:
                return None

            def read(self) -> bytes:
                return ok_body

        m_url.side_effect = [
            urllib.error.HTTPError("http://u", 404, "nope", {}, io.BytesIO(b"{}")),
            _Ok(),
        ]
        old = os.environ.get("OMLXCLI_UPSTREAM_PROTOCOL")
        old_retries = os.environ.get("OMLXCLI_CHAT_HTTP_RETRIES")
        os.environ["OMLXCLI_UPSTREAM_PROTOCOL"] = "auto"
        os.environ["OMLXCLI_CHAT_HTTP_RETRIES"] = "0"
        try:
            out = chat_completion_once(
                "http://127.0.0.1:9/v1",
                "k",
                "m",
                [{"role": "user", "content": "hi"}],
                timeout=5,
            )
            self.assertEqual(extract_assistant_text(out), "from completions")
            self.assertEqual(m_url.call_count, 2)
        finally:
            if old is None:
                os.environ.pop("OMLXCLI_UPSTREAM_PROTOCOL", None)
            else:
                os.environ["OMLXCLI_UPSTREAM_PROTOCOL"] = old
            if old_retries is None:
                os.environ.pop("OMLXCLI_CHAT_HTTP_RETRIES", None)
            else:
                os.environ["OMLXCLI_CHAT_HTTP_RETRIES"] = old_retries


if __name__ == "__main__":
    unittest.main()
