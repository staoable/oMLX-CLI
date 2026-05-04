#!/usr/bin/env zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "${ROOT}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
AUTO_INSTALL_SYSTEM_DEPS="${AUTO_INSTALL_SYSTEM_DEPS:-1}"
AUTO_INSTALL_PLAYWRIGHT_CHROMIUM="${AUTO_INSTALL_PLAYWRIGHT_CHROMIUM:-1}"
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

OS_NAME="$(uname -s)"
ARCH_NAME="$(uname -m)"

if [[ "${OS_NAME}" == "Darwin" && "${AUTO_INSTALL_SYSTEM_DEPS}" == "1" ]]; then
  if command -v brew >/dev/null 2>&1; then
    echo "检测到 Homebrew，检查并安装系统依赖（ripgrep/fd/ffmpeg/poppler/tesseract）..."
    missing_pkgs=()
    command -v rg >/dev/null 2>&1 || missing_pkgs+=("ripgrep")
    command -v fd >/dev/null 2>&1 || missing_pkgs+=("fd")
    command -v ffmpeg >/dev/null 2>&1 || missing_pkgs+=("ffmpeg")
    command -v pdftoppm >/dev/null 2>&1 || missing_pkgs+=("poppler")
    command -v tesseract >/dev/null 2>&1 || missing_pkgs+=("tesseract")
    if (( ${#missing_pkgs[@]} )); then
      echo "将安装: ${missing_pkgs[*]}"
      brew install "${missing_pkgs[@]}"
    else
      echo "系统依赖已齐全。"
    fi
  else
    echo "未检测到 Homebrew，跳过系统依赖自动安装。"
    echo "建议手动安装: ripgrep fd ffmpeg poppler tesseract"
  fi
fi

if [[ "${OS_NAME}" == "Darwin" && "${ARCH_NAME}" == "arm64" ]]; then
  echo "（Apple Silicon）已按 requirements.txt 条件安装 mlx-whisper；音频/视频音轨 STT 可用。"
else
  echo "（非 Apple Silicon）未自动安装 mlx-whisper；音频转写类技能需 Apple Silicon macOS 或自行查阅 MLX 支持矩阵。"
fi

if [[ "${AUTO_INSTALL_PLAYWRIGHT_CHROMIUM}" == "1" ]]; then
  echo "安装 Playwright Chromium（首次需要，供本地 E2E）..."
  "${VENV_PY}" -m playwright install chromium
else
  echo "已跳过 Playwright Chromium 自动安装（AUTO_INSTALL_PLAYWRIGHT_CHROMIUM=${AUTO_INSTALL_PLAYWRIGHT_CHROMIUM}）。"
fi

if command -v claude >/dev/null 2>&1; then
  echo "已检测到 claude（Claude Code CLI）。"
else
  echo "（可选）Claude Code 长任务：安装 npm 包后应出现 claude 命令，例如："
  echo "  npm i -g @anthropic-ai/claude-code"
  echo "  并配置 .env.local 中 OMLXCLI_ENABLE_CLAUDE_CODE 与 OMLXCLI_CLAUDE_CODE_API_KEY（见 .env.example 第十一节）。"
fi

echo "环境初始化完成。可执行："
echo "  ./start_web.sh"
echo "  ./scripts/dev_check.sh"
echo "  （如需手动重装浏览器）${VENV_PY} -m playwright install chromium"
