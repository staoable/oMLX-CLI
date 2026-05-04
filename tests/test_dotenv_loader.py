from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from webapi.dotenv_loader import load_dotenv_files


class DotenvLoaderTest(unittest.TestCase):
    def test_local_overrides_env_file_and_preserves_existing_os(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / ".env").write_text(
            "OMLXCLI_DOTENV_TEST_A=from_env\nOMLXCLI_DOTENV_TEST_B=1\n",
            encoding="utf-8",
        )
        (root / ".env.local").write_text(
            'OMLXCLI_DOTENV_TEST_A=from_local\nOMLXCLI_DOTENV_TEST_C="quoted"\n',
            encoding="utf-8",
        )
        keys = (
            "OMLXCLI_DOTENV_TEST_A",
            "OMLXCLI_DOTENV_TEST_B",
            "OMLXCLI_DOTENV_TEST_C",
            "OMLXCLI_DOTENV_TEST_PRESET",
        )
        saved = {k: os.environ.get(k) for k in keys}
        try:
            for k in keys:
                os.environ.pop(k, None)
            os.environ["OMLXCLI_DOTENV_TEST_PRESET"] = "keep"
            load_dotenv_files(root)
            self.assertEqual(os.environ.get("OMLXCLI_DOTENV_TEST_A"), "from_local")
            self.assertEqual(os.environ.get("OMLXCLI_DOTENV_TEST_B"), "1")
            self.assertEqual(os.environ.get("OMLXCLI_DOTENV_TEST_C"), "quoted")
            self.assertEqual(os.environ.get("OMLXCLI_DOTENV_TEST_PRESET"), "keep")
        finally:
            for k in keys:
                os.environ.pop(k, None)
                if saved.get(k) is not None:
                    os.environ[k] = saved[k]  # type: ignore[index]

    def test_claude_env_can_override_existing_process_env(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / ".env.local").write_text(
            (
                "OMLXCLI_CLAUDE_CODE_API_KEY=from_local_key\n"
                "ANTHROPIC_BASE_URL=https://local.example\n"
                "OMLXCLI_DOTENV_TEST_X=from_local_x\n"
            ),
            encoding="utf-8",
        )
        keys = (
            "OMLXCLI_CLAUDE_CODE_API_KEY",
            "ANTHROPIC_BASE_URL",
            "OMLXCLI_DOTENV_TEST_X",
        )
        saved = {k: os.environ.get(k) for k in keys}
        try:
            os.environ["OMLXCLI_CLAUDE_CODE_API_KEY"] = "from_process_old_key"
            os.environ["ANTHROPIC_BASE_URL"] = "https://process.example"
            os.environ["OMLXCLI_DOTENV_TEST_X"] = "from_process_x"
            load_dotenv_files(root)
            self.assertEqual(os.environ.get("OMLXCLI_CLAUDE_CODE_API_KEY"), "from_local_key")
            self.assertEqual(os.environ.get("ANTHROPIC_BASE_URL"), "https://local.example")
            self.assertEqual(os.environ.get("OMLXCLI_DOTENV_TEST_X"), "from_process_x")
        finally:
            for k in keys:
                os.environ.pop(k, None)
                if saved.get(k) is not None:
                    os.environ[k] = saved[k]  # type: ignore[index]
