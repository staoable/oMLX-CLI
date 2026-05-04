# 变更日志

版本号与 `webapi/app:app` 的 FastAPI **`version`** 对齐。

## [未发布]

### 新增

- **Claude Code Job**：官方 **`claude -p`** 后台任务（**`claude_job_start` / `status` / `logs` / `cancel`**，**`.omlxcli/skills/claude_job_skill.py`**）；SQLite **`claude_jobs`**；REST **`/api/claude-code/status`**、**`/api/sessions/{id}/claude-jobs`** 等；Web **「Claude」**只读轮询；**`skill_context` + `run_skill` 线程内 ContextVar 传播**；配置见 **`.env.example` 第十一节**；规格 **`docs/CLAUDE_CODE_JOB_SPEC.md`**；单测 **`tests/test_claude_job_store.py`**；冒烟脚本 **SKIP** **`claude_job_*`**。
- **Skills**：**`csv_tsv_summary`**（CSV/TSV 摘要）、**`xlsx_sample`**（xlsx 只读抽样）、**`git_snapshot`**（`git log` / `diff` / `show` 只读）、**`structured_pick`**（JSON/YAML 点路径取值）、**`docx_to_text`**（.docx 抽文本）；源码见 **`.omlxcli/skills/spreadsheet.py`**、**`structured_data.py`**、**`git_readonly.py`**、**`docx_read.py`**；单测 **`tests/test_workspace_skills.py`**。
- **依赖**：根 **`requirements.txt`** 增加 **openpyxl**、**python-docx**、**PyYAML**（与 CI / `bootstrap` 一致安装）。
- **可靠性与安全加固（2026-05-04）**：
  - `claude_job_start` 返回主聊天固定提示模板（稳定输出 `job_id`、状态、下一步查询命令）。
  - Claude Job 默认注入结构化报告模板（`OMLXCLI_CLAUDE_JOB_STRICT_REPORT`）并新增后台回收线程（`OMLXCLI_CLAUDE_JOB_REAPER_INTERVAL_SEC`）自动纠正僵尸 `running`。
  - 会话消息接口新增速率限制（`429 RATE_LIMITED`）与请求体/附件体积限制（`413 PAYLOAD_TOO_LARGE` / `ATTACHMENTS_TOO_LARGE`）。
  - SessionStore 启用 SQLite `WAL`、`busy_timeout`、`foreign_keys`（并发稳定性提升）。
  - 多模态缓存新增 TTL 与定期清理（`OMLXCLI_MEDIA_CACHE_TTL_SEC`、`OMLXCLI_MEDIA_CACHE_CLEANUP_INTERVAL_SEC`）。
  - 根目录新增 `LICENSE`（MIT）；修复 `run_skill` / `git_readonly` / `repo_search` / `files_search` 的若干安全与鲁棒性问题。

### 文档

- **`Skills_README.md`** §8.1、**`.env.example`「九·1」**、**`scripts/smoke_all_skills.py`** 头注释、**`README_cn.md` / `README_en.md`** 命令表：全技能冒烟变量与 **`OMLXCLI_EVAL_SKIP_HTTP`** / **`web_read`** 关系；**vision_*** / **audio_transcribe** / **video_summarize** 在无 **`_AICLI_API_BASE`** 时 **SKIP**（非 FAIL）；**`OI_CAPABILITY_MATRIX.md`**、**`IMPLEMENTATION_PLAN.md`** 与 skills 条目已对齐。
- **`docs/CLAUDE_CODE_JOB_SPEC.md`**：Claude Code Job（官方 CLI、macOS 优先）草案——**仅 `run_skill` 发起**、**UI 只读监控**、日志 **HTTP 轮询 + tail**。
- 版本与术语收口：`README.md` / `README_en.md` / `README_cn.md` 版本徽章统一为 `0.2.1`；补充生产配置项（限流、体积限制、缓存 TTL、Claude reaper）；`docs/API.md` 修复重复章节编号并补充 `429/413` 约定。

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
