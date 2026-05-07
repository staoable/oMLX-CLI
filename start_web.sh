#!/usr/bin/env zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "${ROOT}"

# 自动加载项目环境变量（若存在）
# 支持 .env 与 .env.local；后者覆盖前者中同名键（与 webapi/dotenv_loader 语义一致）。
# 直接 uvicorn 未走本脚本时，import webapi.app 也会加载上述文件。
for env_file in "${ROOT}/.env" "${ROOT}/.env.local"; do
  if [[ -f "${env_file}" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "${env_file}"
    set +a
  fi
done

WEB_HOST="${OMLXCLI_HOST:-127.0.0.1}"
WEB_PORT="${OMLXCLI_PORT:-8788}"

export OMLXCLI_DATA_DIR="${OMLXCLI_DATA_DIR:-${ROOT}/.omlxcli/web}"
export OMLXCLI_SKILLS_DIR="${OMLXCLI_SKILLS_DIR:-${ROOT}/.omlxcli/skills}"
export OMLXCLI_DEFAULT_WORKSPACE="${OMLXCLI_DEFAULT_WORKSPACE:-${ROOT}}"

if lsof -nP -iTCP:"${WEB_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  if curl -fsS "http://${WEB_HOST}:${WEB_PORT}/healthz" >/dev/null 2>&1; then
    echo "检测到服务已在运行: http://${WEB_HOST}:${WEB_PORT}/ui/"
    exit 0
  fi
  echo "端口 ${WEB_PORT} 已被占用，请先释放端口或改用其它端口："
  echo "  OMLXCLI_PORT=8790 ./start_web.sh"
  lsof -nP -iTCP:"${WEB_PORT}" -sTCP:LISTEN || true
  exit 1
fi

PY_CMD=""
if [[ -x "${ROOT}/../.venv/bin/python" ]]; then
  PY_CMD="${ROOT}/../.venv/bin/python"
elif [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PY_CMD="${ROOT}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY_CMD="$(command -v python3)"
fi

if [[ -z "${PY_CMD}" ]]; then
  echo "未找到可用 Python。请先执行 ./bootstrap.sh 初始化环境。"
  exit 1
fi

ensure_python_deps() {
  local missing_core=0
  local missing_unblock=0
  if ! "${PY_CMD}" -c "import fastapi,uvicorn,pydantic" >/dev/null 2>&1; then
    missing_core=1
  fi
  if ! "${PY_CMD}" -c "import cv2,numpy,requests,PIL" >/dev/null 2>&1; then
    missing_unblock=1
  fi
  if [[ "${missing_core}" -eq 0 && "${missing_unblock}" -eq 0 ]]; then
    return 0
  fi

  echo "检测到 Python 依赖缺失，尝试自动安装..."
  if ! "${PY_CMD}" -m pip --version >/dev/null 2>&1; then
    echo "当前 Python 无可用 pip，请先执行 ./bootstrap.sh"
    exit 1
  fi
  "${PY_CMD}" -m pip install --upgrade pip >/dev/null 2>&1 || true
  if [[ -f "${ROOT}/requirements.txt" ]]; then
    "${PY_CMD}" -m pip install -r "${ROOT}/requirements.txt"
  fi
  if [[ "${missing_unblock}" -eq 1 ]]; then
    "${PY_CMD}" -m pip install numpy requests Pillow opencv-python
  fi

  if ! "${PY_CMD}" -c "import fastapi,uvicorn,pydantic,cv2,numpy,requests,PIL" >/dev/null 2>&1; then
    echo "自动安装后仍有缺失依赖，请执行 ./bootstrap.sh 后重试。"
    exit 1
  fi
}

ensure_python_deps

exec "${PY_CMD}" -m uvicorn webapi.app:app --app-dir "${ROOT}" --host "${WEB_HOST}" --port "${WEB_PORT}" --reload
