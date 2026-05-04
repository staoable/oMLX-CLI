# oMLX CLI — English documentation

<p align="center">
  <a href="README.md"><b>← Repository home</b></a>
  &nbsp;·&nbsp;
  <a href="README_cn.md"><b>中文版</b></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+" />
  <img src="https://img.shields.io/badge/FastAPI-0.109+-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/version-0.2.1-555555" alt="version 0.2.1" />
</p>

A **deliverable, self-hostable web workspace** for **OpenAI-compatible** local or remote LLMs: multi-session chat, agent-style **shell / skill execution**, multimodal attachments, and an extensible **skills** layer (PDF, weather, web, vision, audio on supported platforms).

This is a **day-to-day web application** (session engine, SQLite persistence, execution policy, structured logging, **CI**: unit tests + Playwright E2E + HTTP smoke)—meant to be more than a throwaway MVP; **whether it meets your production bar** still depends on how you deploy it, on upstreams, and on compliance. The narrative matches the repository home **`README.md`** (including the bilingual sections on problems solved, fit scenarios, and Claude Code).

---

## Table of contents

1. [Positioning](#positioning)
2. [Problems we help solve](#problems-we-help-solve)
3. [When it shines](#when-it-shines)
4. [Relationship to Claude Code](#relationship-to-claude-code)
5. [Highlights](#highlights)
6. [Quick start](#quick-start)
7. [Configuration](#configuration)
8. [Features](#features)
9. [Repository layout](#repository-layout)
10. [Testing & quality](#testing--quality)
11. [Related documentation](#related-documentation)
12. [Roadmap](#roadmap)
13. [Contributing](#contributing)
14. [License](#license)

---

## Positioning

- **Goal**: a reliable **browser-based** command center around **your** OpenAI-compatible API (e.g. oMLX, vLLM, LM Studio HTTP gateway)—**not** a pixel-perfect clone of any particular desktop CLI.
- **Skills** live under `.omlxcli/skills` (manifest-driven). See **`Skills_README.md`** for layout, `gen_oi_tool_map`, and smoke tests.

---

## Problems we help solve

- **Fragmented tools** — You already have an OpenAI-compatible endpoint, but juggling ad-hoc scripts, loose API keys in env files, and a separate browser chat is brittle. Here, **model settings live in SQLite**, sessions bind a **vendor**, and the same UI drives **chat + shell + skills** with **execution audit** and **`x-request-id`** tracing.
- **Repeatable “agent” work** — Turn long threads into something you can **resume**: layered context, checkpoints, and a bounded **`run_shell` / `run_skill`** loop instead of one-off copy-paste into a terminal.
- **Local / team guardrails** — **`OMLXCLI_CORS_ORIGINS`**, **rate limits**, **payload / attachment caps**, workspace path checks, and optional **multimodal cache TTL** are first-class knobs for self-hosting—not afterthoughts.

---

## When it shines

Best fit when you want:

- A **browser-first** assistant over **your own** (or team) **OpenAI-compatible** API — including local gateways (LM Studio, vLLM, custom stacks, etc.).
- **Multimodal chat** in the UI plus **skills** (PDF, repo grep, spreadsheets, web read/search where configured, optional **Apple Silicon** STT) in the same session model.
- **Optional** offload of **long-running Claude Code jobs** (`claude_job_*`) while keeping day-to-day chat on whatever vendor you configured — see **`docs/CLAUDE_CODE_JOB_SPEC.md`**.

---

## Relationship to Claude Code

**Claude Code** excels as an **interactive terminal coding agent** for developers who live in the shell. **oMLX CLI is not a replacement** for that workflow; it is a **different layer**:

| Dimension | Claude Code (typical) | oMLX CLI |
|-----------|------------------------|----------|
| **Primary chat model** | Anthropic / Claude Code product assumptions | **Any OpenAI-compatible** HTTP API you configure per **vendor** in the Web UI |
| **Surface** | Terminal-centric | **Web UI + REST** (`docs/API.md`), shareable in a LAN / small-team sense |
| **Persistence & ops** | Session/product dependent | **SQLite** sessions, vendors, execution records; structured logs, **CORS / limits** you control |
| **Tooling breadth** | Strong for repo editing & codegen | **Manifest skills** (PDF, weather, notes, `repo_grep`, read-only git snapshots, xlsx/csv, docx, …) **plus** optional **`claude_job_*`** that **delegates** to the official **`claude`** CLI for a **subset** of long jobs |

**Honest takeaway** · If your only need is **daily IDE-style coding inside a terminal**, Claude Code alone may be simpler. Choose oMLX when you want a **self-hosted web control plane**, **mixed-model / mixed-vendor** chat, **integrated skills + audits**, and **optional** background **Claude Code** jobs—not when you need a 1:1 clone of the Claude Code UX.

---

## Highlights

| Area | What you get |
|------|----------------|
| **Chat** | SSE streaming; discover models from upstream `/v1/models`; persist messages and basic latency/token estimates. |
| **Agent loop** | `<run_shell>` / `<run_skill>` protocol until `<final_answer>`; toggle between normal chat and agent mode. |
| **Safety** | Command blacklist, high-risk confirmation UI, workspace write-boundary checks. |
| **Context** | Layers: `pinned` / `working` / `archived`; checkpoints (append/replace); budget trim; auto-summary; injection audit rows. |
| **Observability** | JSON logs (`LOGGING_SPEC.md`), `x-request-id`, REST APIs for executions and context injections. |
| **Skills** | PDF, weather, web, notes, repo grep, vision, audio/video; **CSV/TSV summary**, **xlsx sample**, **read-only git**, **JSON/YAML pick**, **docx to text** (see **openpyxl / PyYAML / python-docx** in `requirements.txt`); **Apple Silicon**: optional **mlx-whisper** for local STT. |

---

## Quick start

**Prerequisites**

- macOS or Linux (Windows not exercised in CI).
- Python **3.12+** (matches GitHub Actions).
- A running **OpenAI-compatible** base URL and model id.

**Steps**

```bash
git clone https://github.com/staoable/oMLX-CLI.git
cd oMLX-CLI

./bootstrap.sh
cp .env.example .env.local
# Edit .env.local: data dir, search gateway, etc. Web upstream is only in SQLite via UI “Vendor (Model settings)” (see Configuration)

./start_web.sh
```

`bootstrap.sh` defaults to auto-installing macOS system deps (`ripgrep`, `fd`, `ffmpeg`, `poppler`, `tesseract`) and Playwright Chromium.
If you need to skip these in CI or constrained environments:

```bash
AUTO_INSTALL_SYSTEM_DEPS=0 AUTO_INSTALL_PLAYWRIGHT_CHROMIUM=0 ./bootstrap.sh
```

- Default UI: [http://127.0.0.1:8788/ui/](http://127.0.0.1:8788/ui/)
- Another port: `OMLXCLI_PORT=8790 ./start_web.sh`

Use **`.venv/bin/python`** for scripts so dependencies (PyMuPDF, conditional mlx-whisper, etc.) match the web process.

---

## Configuration

- **Template**: **`.env.example`** — copy to **`.env.local`** (gitignored).
- **Load order**: `webapi/dotenv_loader.py` loads `.env` then **`.env.local`**; values already present in the environment are not overwritten. `start_web.sh` also `source`s these files.
- **Vendor (Model settings, Web)**: Add at least one row; **`api_base` / `api_key` / default model** live in **`sessions.db`** (`vendors`); bind a row per session in Settings before chat or LLM-using Skills. **Do not** use `OI_API_BASE` / `OI_API_KEY` in `.env.local` for the web UI (removed from **`.env.example`**; delete stale keys locally if present).
- **Typical `.env.local` keys**: `OMLXCLI_DATA_DIR`, `OMLXCLI_DEFAULT_WORKSPACE`, `OMLXCLI_RUN_SKILL_TIMEOUT_SEC`, `OMLXCLI_CHAT_*`, `OMLXCLI_SEARCH_*` / `OMLXCLI_SEARXNG_URL`, etc. Default model id for new sessions and legacy placeholder resolution use **`DEFAULT_SESSION_MODEL_ID`** in code plus the bound vendor’s **`default_model`**—no **`OI_MODEL`** env. See **`.env.example`**.
- **Do not miss these production guards**:
  - CORS: `OMLXCLI_CORS_ORIGINS` (defaults to local `8788`; list every browser origin if you access the UI cross-origin)
  - rate limit: `OMLXCLI_MSG_RATE_LIMIT_COUNT`, `OMLXCLI_MSG_RATE_LIMIT_WINDOW_SEC`
  - payload limits: `OMLXCLI_MSG_MAX_BODY_BYTES`, `OMLXCLI_MSG_MAX_ATTACHMENTS_BYTES`
  - media cache cleanup: `OMLXCLI_MEDIA_CACHE_TTL_SEC`, `OMLXCLI_MEDIA_CACHE_CLEANUP_INTERVAL_SEC`
  - Claude job stale-running reaper: `OMLXCLI_CLAUDE_JOB_REAPER_INTERVAL_SEC`

---

## Features

**Sessions**

- Create, switch, delete sessions; auto-generated titles, manual edit, title lock.
- Per-session model and **bound vendor (model settings)** (`vendors` row), workspace path, and execution policy.

**Model & streaming**

- After configuring **`vendors`** in the Web UI, the session’s bound **`vendor_id`** drives **`GET /api/models?vendor_id=…`**; stream deltas over SSE; store assistant messages and coarse performance fields.

**Execution**

- Agent mode runs shell and/or Python skill calls in a loop with user-visible steps and optional confirmations.
- Executions persisted and queryable via API.

**Context & memory**

- SQLite tables: `sessions`, `messages`, `contexts`, `checkpoints`, `executions`, `context_injections`, …
- Working-directory injection to reduce stale-path issues in long threads.

**Web UI**

- Markdown + code highlighting; drag/drop and paste attachments (data URLs); collapsible sidebar; observability panel (filter executions, expand stdout/stderr).

**Errors**

- Structured JSON errors: `error_code`, `message`, `request_id`.

---

## Repository layout

```text
oMLX-CLI/
├── webapi/                 # FastAPI app, session engine, policies, skill runner
├── webui/                  # Static SPA (HTML/CSS/JS)
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

## Testing & quality

| Command | Purpose |
|---------|---------|
| `./scripts/dev_check.sh` | `gen_oi_tool_map.py --check` + full `unittest` suite (aligns with most of CI). |
| `python3 scripts/smoke_all_skills.py` | Optional full skills smoke; vars in **`.env.example`** (comment block **「九·1」**) and **`Skills_README.md`** §8.1. |
| `./.venv/bin/python -m playwright install chromium` | First-time browser install for E2E tests. |

CI (`.github/workflows/ci.yml`): `pip install -r requirements.txt`, Playwright Chromium, `gen_oi_tool_map --check`, unittest **including** Playwright, then `uvicorn` + `scripts/smoke_http.py`. Tests set `OMLXCLI_EVAL_SKIP_HTTP=1` by default for outbound-sensitive cases.

---

## Related documentation

The repository home **`README.md`** includes the **maintainer reference environment**, the bilingual sections on **problems solved / fit scenarios / Claude Code comparison**, and **UI / skills smoke illustrations** (`docs/readme/`) to help visitors trust local runs.

| File | Description |
|------|-------------|
| `Skills_README.md` | Skills catalog, manifest, OI_TOOL_MAP workflow, smoke variables. |
| `.env.example` | All environment variables with comments. |
| `IMPLEMENTATION_PLAN.md` | Status, code pointers, optional evolution; keep in sync with matrix/API docs. |
| `OI_CAPABILITY_MATRIX.md` | Capability list (implemented / partial / missing). |
| `docs/API.md` | **HTTP API** (custom frontends, SSE, errors); complements **`/docs`** OpenAPI. |
| `docs/UPSTREAM_VENDOR_IMPLEMENTATION.md` | Vendor (model settings): credentials, binding, DB ops (REST details in **`docs/API.md`**). |
| `CHANGELOG.md` | Release notes (tracks `webapi` FastAPI `version`). |

---

## Roadmap

Roadmap and gaps: **`OI_CAPABILITY_MATRIX.md`** and **`IMPLEMENTATION_PLAN.md`** §5.

---

## Contributing

Issues and pull requests are welcome. Do **not** commit secrets—use **`.env.local`**. Run **`./scripts/dev_check.sh`** before opening a PR when possible, and describe user-visible changes clearly in the PR body.

---

## License

This repository ships a root **`LICENSE`** file (MIT).

---

<p align="center">
  <a href="README.md"><b>← Repository home</b></a>
  &nbsp;·&nbsp;
  <a href="README_cn.md"><b>中文版</b></a>
</p>
