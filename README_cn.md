# oMLX CLI — 中文文档

<p align="center">
  <a href="README.md"><b>← 仓库首页</b></a>
  &nbsp;·&nbsp;
  <a href="README_en.md"><b>English</b></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+" />
  <img src="https://img.shields.io/badge/FastAPI-0.109+-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/version-0.2.0-555555" alt="version 0.2.0" />
</p>

**可自托管、可交付使用的 Web 助手工作台**：对接 **OpenAI 兼容**的本地或远端大模型，提供多会话流式对话、**类代理执行**（`run_shell` / `run_skill`）、多模态附件，以及可扩展的 **Skills**（PDF、天气、网页、笔记、视觉与音视频等）。

本仓库定位为 **可日常使用的 Web 应用**（完整会话编排、SQLite 持久化、执行策略与审计、结构化日志、**CI：单测 + Playwright E2E + HTTP smoke**），而非一次性概念验证。

---

## 目录

1. [定位与范围](#定位与范围)
2. [核心亮点](#核心亮点)
3. [快速开始](#快速开始)
4. [配置说明](#配置说明)
5. [功能一览](#功能一览)
6. [仓库结构](#仓库结构)
7. [测试与质量](#测试与质量)
8. [相关文档](#相关文档)
9. [路线图](#路线图)
10. [参与贡献](#参与贡献)
11. [许可证](#许可证)

---

## 定位与范围

- **目标**：围绕你自有的 **OpenAI 兼容 API**（如 oMLX、vLLM、LM Studio 网关等）提供稳定的 **浏览器工作台**，**不是**某一桌面 CLI 的 1:1 复刻。
- **技能**：默认位于 `.omlxcli/skills`，由 manifest 驱动；详见 **`Skills_README.md`**（目录约定、`gen_oi_tool_map`、冒烟环境变量等）。

---

## 核心亮点

| 方面 | 能力 |
|------|------|
| **对话** | SSE 流式；从上游 `/v1/models` 拉取模型列表；消息与基础性能指标持久化。 |
| **执行循环** | `<run_shell>` / `<run_skill>` 协议直至 `<final_answer>`；普通对话与代理模式可切换。 |
| **安全** | 命令黑名单、高危操作确认弹窗、工作区写路径边界检查。 |
| **上下文** | 分层：`pinned` / `working` / `archived`；checkpoint（追加/替换）；预算裁剪与自动摘要；上下文注入审计。 |
| **可观测** | 结构化 JSON 日志（见 `LOGGING_SPEC.md`）、`x-request-id`、执行与注入相关 REST 接口。 |
| **Skills** | PDF、天气、网页、笔记、`repo_grep`、视觉、音视频；**CSV/TSV 摘要**、**xlsx 抽样**、**只读 git**、**JSON/YAML 点路径**、**docx 抽文本**（依赖见 `requirements.txt` 中 **openpyxl / PyYAML / python-docx**）；**Apple Silicon** 上可选 **mlx-whisper** 本地转写。 |

---

## 快速开始

**环境要求**

- macOS 或 Linux（Windows 未在 CI 中验证）。
- 建议 **Python 3.12+**（与 GitHub Actions 一致）。
- 已可用的 **OpenAI 兼容** `base_url` 与模型名。

**命令**

```bash
git clone https://github.com/staoable/oMLX-CLI.git
cd oMLX-CLI

./bootstrap.sh
cp .env.example .env.local
# 编辑 .env.local：数据目录、搜索网关等；Web 对话上游仅在界面「模型设置」→ SQLite（见下节）

./start_web.sh
```

- 默认界面：[http://127.0.0.1:8788/ui/](http://127.0.0.1:8788/ui/)
- 更换端口：`OMLXCLI_PORT=8790 ./start_web.sh`

脚本与技能冒烟请尽量使用 **`.venv/bin/python`**，与 Web 进程依赖一致（含 PyMuPDF、Apple Silicon 上的 mlx-whisper 等）。

---

## 配置说明

- **模板**：根目录 **`.env.example`**，推荐复制为 **`.env.local`**（已在 `.gitignore`，勿提交密钥）。
- **加载**：`import webapi.app` 时由 `webapi/dotenv_loader.py` 读取 `.env` 与 **`.env.local`**；**已在进程环境中的变量不会被文件覆盖**。`./start_web.sh` 也会 `source` 上述文件。
- **模型设置（Web）**：在界面至少添加一条；**`api_base` / `api_key` / 默认模型** 在 **`sessions.db` 的 `vendors` 表**；会话在设置中绑定后才能对话与使用依赖 LLM 的 Skills。**不要**再在 `.env.local` 里配 `OI_API_BASE` / `OI_API_KEY` 作为 Web 上游（模板已移除；若本地仍有旧键可删掉以免混淆）。
- **`.env.local` 常用项**：`OMLXCLI_DATA_DIR`、`OMLXCLI_DEFAULT_WORKSPACE`、`OMLXCLI_RUN_SKILL_TIMEOUT_SEC`、`OMLXCLI_CHAT_*`、`OMLXCLI_SEARCH_*` / `OMLXCLI_SEARXNG_URL` 等。新建会话默认 model、旧占位名回退由代码 **`DEFAULT_SESSION_MODEL_ID`** 与已绑定模型设置的 **`default_model`** 决定，**无需** `OI_MODEL`。逐项说明见 **`.env.example`**。

---

## 功能一览

**会话**

- 新建、切换、删除会话；标题自动生成、手动编辑、标题锁定。
- 每会话独立配置：模型、**绑定的模型设置**、工作目录、执行策略等。

**模型与流式**

- 在 Web「模型设置」中配置 **`vendors`** 后，按会话绑定的 **`vendor_id`** 调用 **`GET /api/models?vendor_id=…`** 拉取上游列表；SSE 流式输出；完成后写入助手消息与粗粒度性能字段。

**执行代理**

- 可开关代理模式；shell 与 skill 循环执行；执行步骤可视化；高风险确认。
- 执行记录落库并提供查询 API。

**上下文与记忆**

- SQLite：`sessions` / `messages` / `contexts` / `checkpoints` / `executions` / `context_injections` 等。
- 工作目录权威注入，减轻长会话路径污染。

**前端**

- Markdown 与代码高亮；附件拖拽/粘贴（data_url）；侧栏折叠；执行与上下文注入观测面板（筛选、展开 stdout/stderr）。

**错误**

- 统一 JSON：`error_code`、`message`、`request_id`。

---

## 仓库结构

```text
oMLX-CLI/
├── webapi/                 # FastAPI、会话引擎、策略、skill 执行
├── webui/                  # 静态单页（HTML/CSS/JS）
├── bootstrap.sh
├── start_web.sh
├── scripts/
│   ├── dev_check.sh
│   ├── gen_oi_tool_map.py
│   ├── smoke_http.py
│   └── smoke_all_skills.py
├── tests/
├── .omlxcli/skills/
├── requirements.txt
├── .env.example
├── Skills_README.md
├── CHANGELOG.md
├── IMPLEMENTATION_PLAN.md
├── OI_CAPABILITY_MATRIX.md
└── .github/workflows/ci.yml
```

---

## 测试与质量

| 命令 | 作用 |
|------|------|
| `./scripts/dev_check.sh` | `gen_oi_tool_map.py --check` + 全量 `unittest`（与 CI 主体对齐）。 |
| `python3 scripts/smoke_all_skills.py` | 可选：对 manifest 全技能冒烟；变量见 **`.env.example`「九·1」** 与 **`Skills_README.md`** §8.1。 |
| `./.venv/bin/python -m playwright install chromium` | 首次跑 E2E 前安装 Chromium。 |

GitHub Actions（`.github/workflows/ci.yml`）：安装依赖与 Playwright Chromium，执行 `gen_oi_tool_map --check`、含 Playwright 的 `unittest`、以及拉起 `uvicorn` 后的 `scripts/smoke_http.py`。单测默认 `OMLXCLI_EVAL_SKIP_HTTP=1`，跳过依赖外网的评测场景。

---

## 相关文档

仓库首页 **`README.md`** 含 **维护者自测环境** 与 **界面 / 技能冒烟示意图**（`docs/readme/`），便于访客建立信心。

| 文件 | 说明 |
|------|------|
| `Skills_README.md` | 技能目录、manifest、`OI_TOOL_MAP`、冒烟变量等。 |
| `.env.example` | 环境变量逐项中文注释。 |
| `IMPLEMENTATION_PLAN.md` | 能力状态速查、代码落点、可选演进；与矩阵/API 文档联动。 |
| `OI_CAPABILITY_MATRIX.md` | 能力清单（已实现 / 部分 / 未实现）。 |
| `docs/API.md` | **HTTP API**（自建前端、SSE、错误格式）；与 **`/docs`** OpenAPI 互补。 |
| `docs/UPSTREAM_VENDOR_IMPLEMENTATION.md` | 模型设置：凭据、绑定、SQLite 运维（REST 细节见 **`docs/API.md`**）。 |
| `CHANGELOG.md` | 变更记录（与 `webapi` 中 FastAPI `version` 字段同步）。 |

---

## 路线图

路线图与未实现项以 **`OI_CAPABILITY_MATRIX.md`**、**`IMPLEMENTATION_PLAN.md`** §5 为准。

---

## 参与贡献

欢迎 Issue 与 Pull Request。请勿将密钥写入仓库，请使用 **`.env.local`**。提交前尽量运行 **`./scripts/dev_check.sh`**，并在 PR 中清晰说明对用户可见行为的变更。

---

## 许可证

正式对外发布时，请在仓库根目录添加 **`LICENSE`**（如 MIT、Apache-2.0），便于贡献者与下游引用。

---

<p align="center">
  <a href="README.md"><b>← 仓库首页</b></a>
  &nbsp;·&nbsp;
  <a href="README_en.md"><b>English</b></a>
</p>
