# 变更日志

版本号与 `webapi/app:app` 的 FastAPI **`version`** 对齐。

## [未发布]

### 新增

- **Skills**：**`csv_tsv_summary`**（CSV/TSV 摘要）、**`xlsx_sample`**（xlsx 只读抽样）、**`git_snapshot`**（`git log` / `diff` / `show` 只读）、**`structured_pick`**（JSON/YAML 点路径取值）、**`docx_to_text`**（.docx 抽文本）；源码见 **`.omlxcli/skills/spreadsheet.py`**、**`structured_data.py`**、**`git_readonly.py`**、**`docx_read.py`**；单测 **`tests/test_workspace_skills.py`**。
- **依赖**：根 **`requirements.txt`** 增加 **openpyxl**、**python-docx**、**PyYAML**（与 CI / `bootstrap` 一致安装）。

### 文档

- **`Skills_README.md`** §8.1、**`.env.example`「九·1」**、**`scripts/smoke_all_skills.py`** 头注释、**`README_cn.md` / `README_en.md`** 命令表：全技能冒烟变量与 **`OMLXCLI_EVAL_SKIP_HTTP`** / **`web_read`** 关系；**vision_*** / **audio_transcribe** / **video_summarize** 在无 **`_AICLI_API_BASE`** 时 **SKIP**（非 FAIL）；**`OI_CAPABILITY_MATRIX.md`**、**`IMPLEMENTATION_PLAN.md`** 与 skills 条目已对齐。

## [0.2.0] — 2026-05-02

### 变更

- **模型设置**：上游 Base / Key / 默认模型存 **`vendors`**（SQLite）；会话 **`vendor_id`** 可选，解绑为 **`null`**；无可用配置时对话返回明确错误。Web 不再依赖 `.env` 中的 `OI_API_BASE` / `OI_API_KEY` / `OI_MODEL`；默认与占位 model 由 **`DEFAULT_SESSION_MODEL_ID`** 与已绑定 **`vendors.default_model`** 决定（见 `.env.example`）。
- **API**：**`GET /api/models`** 必须 **`vendor_id`**；**`GET /api/vendors/{id}`** 单条含 `api_key` 供编辑回显；列表与写响应默认不含 key；**`POST`/`PATCH /api/vendors`** 可选 **`api_key`**；移除独立 secret 路由；**`slug`** 仅服务端生成。
- **Skills**：`run_skill` 使用 **`_AICLI_API_BASE`** / **`_AICLI_API_KEY`** / **`_AICLI_LLM_MODEL`**（`_media._llm_endpoint` 不再回退 `OI_API_*`）。
- **Web**：「模型设置」文案与弹窗；新建/更新保存后清空表单防误 `PATCH`；设置中移除会话级自填 API Base（由绑定行决定）。

### 新增

- **`webapi/upstream_credentials.py`**；**`webapi/dotenv_loader.py`**（加载 `.env` / `.env.local`，不含把模型密钥写入 `.env`）。
- **Playwright**：`tests/test_e2e_playwright_ui.py`；CI 安装 Chromium。
- **`OMLXCLI_RUN_SKILL_TIMEOUT_SEC`**；**`scripts/dev_check.sh`**。
- 文档：**`README.md`** 首页；**`README_cn.md` / `README_en.md`**；**`Skills_README.md`**；**`docs/readme/`** 截图；**`docs/API.md`**；本 **`CHANGELOG`**。

### 工程

- 根 **`requirements.txt`**（含条件 **`mlx-whisper`**、**`pymupdf`**）；CI `pip install -r` + `playwright install`。
- 天气 **`wttr.in` 兜底**；HTTP 502/503/504 短重试。

## [0.1.0] — 更早

- 初版：会话、流式对话、`run_shell` / `run_skill`、上下文与 checkpoint、执行审计、skills 与 `OI_TOOL_MAP` 生成链等。
