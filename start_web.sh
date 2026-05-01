#!/usr/bin/env zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "${ROOT}"

# 自动加载项目环境变量（若存在）
# 支持 .env 与 .env.local；后者可覆盖前者。
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

if ! "${PY_CMD}" -c "import fastapi,uvicorn,pydantic" >/dev/null 2>&1; then
  echo "Python 环境缺少依赖（fastapi/uvicorn/pydantic）。"
  echo "请先执行: ./bootstrap.sh"
  exit 1
fi

exec "${PY_CMD}" -m uvicorn webapi.app:app --app-dir "${ROOT}" --host "${WEB_HOST}" --port "${WEB_PORT}" --reload
