#!/usr/bin/env bash
# 环境与数据目录一键诊断（与 GET /api/diagnostics 同源逻辑，无需启动 uvicorn）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PY="${ROOT}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "未找到 Python。请先执行: ./bootstrap.sh"
  exit 1
fi

export PYTHONPATH="${ROOT}"
"${PY}" -m webapi.diagnostics
