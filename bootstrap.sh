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

echo "安装运行与测试依赖（见 requirements.txt，含 Playwright 供本地 E2E）..."
"${VENV_PY}" -m pip install -r "${ROOT}/requirements.txt"

if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
  echo "（Apple Silicon）已按 requirements.txt 条件安装 mlx-whisper；音频/视频音轨 STT 可用。"
else
  echo "（非 Apple Silicon）未自动安装 mlx-whisper；音频转写类技能需 Apple Silicon macOS 或自行查阅 MLX 支持矩阵。"
fi

echo "环境初始化完成。可执行："
echo "  ./start_web.sh"
echo "  ./scripts/dev_check.sh"
echo "  （首次跑 Playwright E2E 前）${VENV_PY} -m playwright install chromium"
