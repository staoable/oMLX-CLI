# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
"""从仓库根目录加载 `.env`、`.env.local` 到 `os.environ`。

约定：
- 先读 `.env`，再读 `.env.local`；**同一键以后者为准**（合并后再写入）。
- **不覆盖**在调用本函数之前进程环境里**已经存在**的键（CI/容器注入优先生效）。
- 支持 `KEY=value`、`export KEY=value`；值可用成对单引号或双引号包裹。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")


def _parse_env_value(raw: str) -> str:
    val = raw.strip()
    if not val:
        return ""
    if len(val) >= 2 and val[0] == val[-1] == '"':
        inner = val[1:-1]
        return inner.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
    if len(val) >= 2 and val[0] == val[-1] == "'":
        return val[1:-1]
    if " #" in val:
        val = val.split(" #", 1)[0].rstrip()
    return val


def _parse_dotenv_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        if not key or not _ENV_KEY_RE.match(key):
            continue
        out[key] = _parse_env_value(rest)
    return out


def load_dotenv_files(repo_root: Path) -> None:
    """将 `repo_root/.env` 与 `repo_root/.env.local` 合并进环境变量。"""
    frozen = set(os.environ.keys())
    override_allow_prefixes = (
        "OMLXCLI_CLAUDE_CODE_",
        "ANTHROPIC_",
    )
    merged: dict[str, str] = {}
    for fname in (".env", ".env.local"):
        path = repo_root / fname
        if not path.is_file():
            continue
        merged.update(_parse_dotenv_file(path))
    for key, val in merged.items():
        if key in frozen and not key.startswith(override_allow_prefixes):
            continue
        os.environ[key] = val
