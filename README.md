# oMLX CLI

<p align="center">
  <b>Self-hostable web workbench</b> for <b>OpenAI-compatible</b> LLMs — sessions, agent-style tools, multimodal chat, and a built-in skills toolkit.
</p>

<p align="center">
  <a href="README_en.md"><b>English documentation →</b></a>
  &nbsp;·&nbsp;
  <a href="README_cn.md"><b>← 中文文档</b></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+" />
  <img src="https://img.shields.io/badge/FastAPI-0.109+-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/version-0.2.1-555555" alt="version 0.2.1" />
</p>

<p align="center"><sub><b>README.md</b> / <b>README_cn.md</b> / <b>README_en.md</b> 对「能解决哪些问题 → 适合哪些场景 → 与 Claude Code 关系」叙述<strong>口径一致</strong>；首页为中英对照摘要，长文档为单语展开。</sub></p>

---

## At a glance

| | |
|--|--|
| **What** | Browser UI + **FastAPI** backend: stream chat, **run_shell** / **run_skill**, SQLite persistence, execution audit, layered context & checkpoints. |
| **Who** | Teams or individuals who already expose a **/v1/chat/completions**-style API and want a **polished local web** control plane—not a disposable demo. |
| **Docs** | Full install, configuration, features, testing, and contribution guide: **[README_en.md](README_en.md)** · **[README_cn.md](README_cn.md)** · HTTP API for custom UIs: **[docs/API.md](docs/API.md)** |

---

## 一览

| | |
|--|--|
| **是什么** | 浏览器工作台 + **FastAPI**：流式对话、**run_shell / run_skill**、SQLite 持久化、执行审计、分层上下文与 checkpoint。 |
| **适合谁** | 已有 **OpenAI 兼容推理服务**、希望用 **成熟 Web 界面** 完成日常助手与工具调用的个人或小团队。 |
| **详细说明** | 安装、环境变量、功能清单、测试与贡献流程请见：**[README_cn.md](README_cn.md)** · **[README_en.md](README_en.md)** · 自建前端 API：**[docs/API.md](docs/API.md)** |

---

## Problems we help solve · 能帮人解决哪些问题

**EN**

- **Fragmented tools** — You already have an OpenAI-compatible endpoint, but juggling ad-hoc scripts, loose API keys in env files, and a separate browser chat is brittle. Here, **model settings live in SQLite**, sessions bind a **vendor**, and the same UI drives **chat + shell + skills** with **execution audit** and **request tracing**.
- **Repeatable “agent” work** — Turn long threads into something you can **resume**: layered context, checkpoints, and a bounded **`run_shell` / `run_skill`** loop instead of one-off copy-paste into a terminal.
- **Local / team guardrails** — **CORS**, **rate limits**, **payload / attachment caps**, workspace path checks, and optional **multimodal cache TTL** are first-class knobs for self-hosting—not afterthoughts.

**中文**

- **工具链分散** — 已有 OpenAI 兼容推理端点，但密钥散落在 `.env`、脚本与网页之间、难以审计。此处 **供应商（Base/Key/默认模型）在 Web 写入 SQLite**，会话 **`vendor_id` 绑定**，同一界面串联 **对话 + 终端命令 + Skills**，并带 **执行记录** 与 **`x-request-id`**。
- **可延续的「代理式」工作** — 长对话可配合 **分层上下文与 checkpoint**，在受控的 **`run_shell` / `run_skill`** 循环里推进，而不是反复手工粘贴命令。
- **自托管时的边界与防护** — **CORS**、**消息限流**、**请求体/附件上限**、工作区路径约束、多模态 **缓存 TTL** 等可配置，适合局域网或小团队部署时收紧暴露面。

---

## When it shines · 适合哪些场景

**EN** · Best fit when you want:

- A **browser-first** assistant over **your own** (or team) **OpenAI-compatible** API — including local gateways (LM Studio, vLLM, custom oMLX stacks, etc.).
- **Multimodal chat** in the UI plus **skills** (PDF, repo grep, spreadsheets, web read/search where configured, optional **Apple Silicon** STT) in the same session model.
- **Optional** offload of **long-running Claude Code jobs** (`claude_job_*`) while keeping day-to-day chat on whatever vendor you configured — see **`docs/CLAUDE_CODE_JOB_SPEC.md`**.

**中文** · 更适合：

- 希望 **浏览器优先**、对接 **自管或团队自建的 OpenAI 兼容** 推理（含本机网关、远端统一网关等），而不是被某一闭源网页产品绑死。
- 同一会话里既要 **多模态附件对话**，又要 **可审计的技能调用**（PDF、仓库检索、表格与结构化数据、按环境配置的联网搜索等；**Apple Silicon** 上还可选本地转写相关能力）。
- 在 **主对话仍走你配置的供应商** 的前提下，**可选**把少数「长耗时、可多步」的任务交给 **Claude Code CLI** 后台队列（`claude_job_*`），见 **`docs/CLAUDE_CODE_JOB_SPEC.md`**。

---

## vs using Claude Code alone · 与 Claude Code 的关系

**EN** · **Claude Code** excels as an **interactive terminal coding agent** for developers who live in the shell. **oMLX CLI is not a replacement** for that workflow; it is a **different layer**:

| Dimension | Claude Code (typical) | oMLX CLI |
|-----------|------------------------|----------|
| **Primary chat model** | Anthropic / Claude Code product assumptions | **Any OpenAI-compatible** HTTP API you configure per **vendor** in the Web UI |
| **Surface** | Terminal-centric | **Web UI + REST** (`docs/API.md`), shareable in a LAN/small-team sense |
| **Persistence & ops** | Session/product dependent | **SQLite** sessions, vendors, execution records; structured logs, **CORS / limits** you control |
| **Tooling breadth** | Strong for repo editing & codegen | **Manifest skills** (PDF, weather, notes, `repo_grep`, read-only git snapshots, xlsx/csv, docx, …) **plus** optional **`claude_job_*`** that **delegates** to the official **`claude`** CLI for a **subset** of long jobs |

**Honest takeaway** · If your only need is **daily IDE-style coding inside a terminal**, Claude Code alone may be simpler. Choose oMLX when you want a **self-hosted web control plane**, **mixed-model / mixed-vendor** chat, **integrated skills + audits**, and **optional** background **Claude Code** jobs—not when you need a 1:1 clone of the Claude Code UX.

**中文** · 与「只用 Claude Code」相比，本仓库的定位如下。**Claude Code** 在 **终端里写代码、改仓库** 的场景非常强。**oMLX CLI 不是要替代它**，而是另一层：

| 维度 | 典型「只用 Claude Code」 | oMLX CLI |
|------|--------------------------|----------|
| **主对话模型** | 与 Anthropic / Claude Code 产品路径强相关 | 在界面配置 **任意 OpenAI 兼容** 上游，按 **供应商** 存 SQLite |
| **交互形态** | 以终端为中心 | **浏览器 + REST**（见 `docs/API.md`），便于局域网或小团队统一入口 |
| **持久化与运维** | 随产品形态变化 | **SQLite** 会话、供应商、执行记录；结构化日志、**CORS / 限流 / 体积上限** 等可自管 |
| **工具广度** | 强在代码与仓库操作 | **内置 Skills 生态**（PDF、天气、笔记、检索、只读 git、表格与 Office 等）**外加** 可选 **`claude_job_*`**，在少数长任务上 **委托** 本机官方 **`claude`** CLI |

**实话实说** · 若你 **只在终端里日常写代码**，继续用 **Claude Code** 往往更直接。若你需要 **自托管 Web 工作台**、**主对话可换任意兼容端点**、**技能与审计一体化**，并 **偶尔**把长任务交给 **Claude Code CLI** 跑在后台，再考虑本仓库。

---

## Reference environment · 维护者自测环境

**EN** · The table below is the **maintainer’s reference rig** used for day-to-day development and `smoke_all_skills.py` runs—it is **not** a minimum requirement. Your hardware and inference stack can differ as long as the API is **OpenAI-compatible**.

**中文** · 下表为 **维护者日常开发与技能冒烟** 所用参考配置，**不是**运行本项目的最低门槛；只要上游为 **OpenAI 兼容** API，硬件与推理栈可与下表不同。

| Item · 项目 | Reference · 参考配置 |
|---------------|----------------------|
| **Hardware · 硬件** | Apple MacBook Pro（M4 Max 12性能和4能效），统一内存 **128GB**（更大上下文与本地 STT 更从容） |
| **OS · 系统** | **macOS** Tahoe 26.4.1 (25E253) |
| **Python** | **3.12**，项目虚拟环境 **`.venv`**（`./bootstrap.sh`） |
| **Inference · 推理** | 本机或远端 **OpenAI 兼容** HTTP API；在 Web **Model settings** 写入 Base/Key/模型并存 SQLite；默认 model id 见代码 **`DEFAULT_SESSION_MODEL_ID`**（见 **`.env.example`** 第三节说明） |
| **Optional · 可选** | **PyMuPDF**（PDF）、**mlx-whisper**（Apple Silicon 本地转写）、**SearXNG / 网关**（`web_search`）、样例 PDF/图/音视频路径用于冒烟 |

### Screenshots · 技能与界面示意

**EN** · PNGs in `docs/readme/` are **resampled to ~900px width** (~160–210 KB each) for faster GitHub README loads. Replace the files when you update captures—keep the same names.


<p align="center">
  <b>Web UI · 会话与执行流</b><br/>
  <img src="docs/readme/screenshot-web-ui.png" alt="Web UI screenshot" width="720" loading="lazy" decoding="async" />
</p>

<p align="center">
  <b>Claude skills · Claude 任务管理</b><br/>
  <img src="docs/readme/screenshot-claude-skills.png" alt="Claude skills task management screenshot" width="720" loading="lazy" decoding="async" />
</p>

<p align="center">
  <b>Debug · 调试观测面板</b><br/>
  <img src="docs/readme/screenshot-web-debug.png" alt="Debug panel screenshot" width="720" loading="lazy" decoding="async" />
</p>


---

## Claude Skills · 让专业工具做专业的事

- **定位**：`claude_job_*` 把“长耗时、跨步骤、可恢复”的任务交给 **Claude Code CLI** 后台队列执行，避免阻塞主对话。
- **方式**：在会话里由模型通过 `run_skill` 发起，返回 `job_id`；Web「Claude」面板只读监控（排队、运行、完成、失败、取消）。
- **共享上下文**：同一会话采用 `queued -> running` 串行调度，前序完成后自动续接（`--resume` 语义），减少重复启动与上下文丢失。
- **运维友好**：支持日志大小上限与保留清理（见 `.env.example` 第十一节），并可通过 `claude_job_status / claude_job_logs` 拉取过程与结果。
- **上线加固配置**：**CORS**（`OMLXCLI_CORS_ORIGINS`）、消息限流与体积限制（`OMLXCLI_MSG_RATE_LIMIT_*` / `OMLXCLI_MSG_MAX_*`）、多模态缓存 TTL 清理（`OMLXCLI_MEDIA_CACHE_*`）。

## Try in 30 seconds · 快速体验

```bash
git clone https://github.com/staoable/oMLX-CLI.git && cd oMLX-CLI
./bootstrap.sh && cp .env.example .env.local   # data dir, search, etc.; add Web “Model settings” in UI for chat keys
./start_web.sh
```

`bootstrap.sh` 默认会在 macOS 自动补齐系统依赖（`ripgrep`、`fd`、`ffmpeg`、`poppler`、`tesseract`）并安装 Playwright Chromium。若需跳过：
`AUTO_INSTALL_SYSTEM_DEPS=0 AUTO_INSTALL_PLAYWRIGHT_CHROMIUM=0 ./bootstrap.sh`

Then open **[http://127.0.0.1:8788/ui/](http://127.0.0.1:8788/ui/)** — or read **[README_en.md](README_en.md)** / **[README_cn.md](README_cn.md)** for ports, optional skills (PDF, search, Apple Silicon STT), and CI.

---

<p align="center">
  <a href="README_en.md">English →</a>
  &nbsp;·&nbsp;
  <a href="README_cn.md">中文 →</a>
</p>
