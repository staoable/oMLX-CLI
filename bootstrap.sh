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
    echo "检测到 Homebrew，检查并安装系统依赖（ripgrep/fd/ffmpeg/poppler/tesseract/node）..."
    echo "（run_shell）全屏 TUI（如 mactop/htop/vim）不适合 Web 无头执行，服务端会快速拒绝；pmset -g thermlog 会持续输出，已自动截断；也可用 pmset -g therm / powermetrics -n 1 等。"
    missing_pkgs=()
    command -v rg >/dev/null 2>&1 || missing_pkgs+=("ripgrep")
    command -v fd >/dev/null 2>&1 || missing_pkgs+=("fd")
    command -v ffmpeg >/dev/null 2>&1 || missing_pkgs+=("ffmpeg")
    command -v pdftoppm >/dev/null 2>&1 || missing_pkgs+=("poppler")
    command -v tesseract >/dev/null 2>&1 || missing_pkgs+=("tesseract")
    command -v node >/dev/null 2>&1 || missing_pkgs+=("node")
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

install_claude_cli() {
  if command -v claude >/dev/null 2>&1; then
    echo "已检测到 claude（Claude Code CLI）。"
    return 0
  fi
  if ! command -v npm >/dev/null 2>&1; then
    echo "未检测到 npm，暂无法自动安装 Claude Code CLI。"
    echo "请先安装 Node.js（建议用 brew install node），再重跑 ./bootstrap.sh。"
    return 1
  fi
  echo "安装 Claude Code CLI（npm i -g @anthropic-ai/claude-code）..."
  if npm i -g @anthropic-ai/claude-code; then
    if command -v claude >/dev/null 2>&1; then
      echo "Claude Code CLI 安装成功。"
      return 0
    fi
    echo "npm 安装已完成，但当前 shell 尚未识别 claude；可重开终端后重试。"
    return 1
  fi
  echo "Claude Code CLI 自动安装失败，请手动执行：npm i -g @anthropic-ai/claude-code"
  return 1
}

install_claude_cli || true

echo "环境初始化完成。可执行："
echo "  ./start_web.sh"
echo "  ./scripts/dev_check.sh"
echo "  （如需手动重装浏览器）${VENV_PY} -m playwright install chromium"
