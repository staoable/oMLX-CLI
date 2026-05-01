#!/usr/bin/env zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "${ROOT}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "未找到 ${PYTHON_BIN}，请先安装 Python 3。"
  exit 1
fi

if [[ ! -x "${ROOT}/.venv/bin/python" ]]; then
  echo "创建虚拟环境: ${ROOT}/.venv"
  "${PYTHON_BIN}" -m venv "${ROOT}/.venv"
fi

VENV_PY="${ROOT}/.venv/bin/python"

echo "升级 pip..."
"${VENV_PY}" -m pip install --upgrade pip

echo "安装运行与测试依赖..."
"${VENV_PY}" -m pip install fastapi uvicorn pydantic httpx

echo "环境初始化完成。可执行："
echo "  ./start_web.sh"
echo "  ./.venv/bin/python -m unittest discover -s tests -p \"test_*.py\""
