# 变更日志

本文档遵循简要条目风格；版本号与 `webapi/app:app` 的 FastAPI `version` 字段对齐。

## [0.2.0] — 2026-05-02

### 变更

- 文档：根目录 **`README.md`** 作为仓库首页（宣传 + 快速入口），完整说明拆至 **`README_cn.md`** / **`README_en.md`** 双语维护；`Skills_README.md` 互补说明已更新。
- 文档：`skill-readme.md` 重命名为 **`Skills_README.md`**，并增加 **manifest 技能一览表**（名称、功能、路径）。

### 新增

- **Playwright 浏览器 E2E**：`tests/test_e2e_playwright_ui.py`（启动 uvicorn 后访问 `/ui/`，断言标题与「新建会话」按钮）；GitHub Actions 安装 Chromium 后与单测一并执行。
- **本地开发脚本**：`scripts/dev_check.sh`（`gen_oi_tool_map --check` + 全量 `unittest`，默认跳过外网评测类场景）。
- **run_skill 超时**：`OMLXCLI_RUN_SKILL_TIMEOUT_SEC`（见 `.env.example`）。
- **环境加载**：`webapi/dotenv_loader.py` 在 `import webapi.app` 时加载 `.env` / `.env.local`。

### 工程

- CI：`pip install -r requirements.txt` + `playwright install --with-deps chromium`。
- 仓库根 `requirements.txt` 便于与 CI/bootstrap 统一依赖。
- **本地 STT**：`requirements.txt` 增加 **Apple Silicon macOS** 条件依赖 **`mlx-whisper`**（Linux CI 不安装）；`bootstrap.sh`、`_media.py` 缺包提示与 `README` / `Skills_README` 冒烟说明对齐「用 `.venv` 解释器」。
- **PDF**：`requirements.txt` 增加 **`pymupdf`**，使 `pdf_meta` 等与 CI/bootstrap 一致有 PyMuPDF 后端。
- **天气**：`weather_forecast` 增加 **wttr.in 兜底**；`_http_get_json` 对 **502/503/504** 短时重试，减轻 Open-Meteo 网关抖动。

## [0.1.0] — 更早

- MVP：会话、流式对话、run_shell/run_skill、上下文与 checkpoint、执行审计、skills 与 `OI_TOOL_MAP` 生成链等（见 `README.md` / `IMPLEMENTATION_PLAN.md`）。
