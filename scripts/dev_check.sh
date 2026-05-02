#!/usr/bin/env bash
# 本地一键对齐 CI 核心检查（不拉起长时间 uvicorn；需要完整 HTTP smoke 见 ci.yml 或手动跑 smoke_http.py）。
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

export OMLXCLI_EVAL_SKIP_HTTP="${OMLXCLI_EVAL_SKIP_HTTP:-1}"

echo "==> gen_oi_tool_map --check"
"${PY}" "${ROOT}/scripts/gen_oi_tool_map.py" --check

echo "==> unittest"
"${PY}" -m unittest discover -s tests -p "test_*.py" -v

echo "==> dev_check 完成（未含 uvicorn+smoke_http；与 CI 完全一致请见 .github/workflows/ci.yml）"
