# oMLX CLI — English documentation

<p align="center">
  <a href="README.md"><b>← Repository home</b></a>
  &nbsp;·&nbsp;
  <a href="README_cn.md"><b>中文版</b></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+" />
  <img src="https://img.shields.io/badge/FastAPI-0.109+-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/version-0.2.0-555555" alt="version 0.2.0" />
</p>

A **production-ready, self-hostable web workspace** for **OpenAI-compatible** local or remote LLMs: multi-session chat, agent-style **shell / skill execution**, multimodal attachments, and an extensible **skills** layer (PDF, weather, web, vision, audio on supported platforms).

This is a **deliverable web application** (session engine, SQLite persistence, execution policy, structured logging, **CI**: unit tests + Playwright E2E + HTTP smoke)—not a throwaway MVP.

---

## Table of contents

1. [Positioning](#positioning)
2. [Highlights](#highlights)
3. [Quick start](#quick-start)
4. [Configuration](#configuration)
5. [Features](#features)
6. [Repository layout](#repository-layout)
7. [Testing & quality](#testing--quality)
8. [Related documentation](#related-documentation)
9. [Roadmap](#roadmap)
10. [Contributing](#contributing)
11. [License](#license)

---

## Positioning

- **Goal**: a reliable **browser-based** command center around **your** OpenAI-compatible API (e.g. oMLX, vLLM, LM Studio HTTP gateway)—**not** a pixel-perfect clone of any particular desktop CLI.
- **Skills** live under `.omlxcli/skills` (manifest-driven). See **`Skills_README.md`** for layout, `gen_oi_tool_map`, and smoke tests.

---

## Highlights

| Area | What you get |
|------|----------------|
| **Chat** | SSE streaming; discover models from upstream `/v1/models`; persist messages and basic latency/token estimates. |
| **Agent loop** | `<run_shell>` / `<run_skill>` protocol until `<final_answer>`; toggle between normal chat and agent mode. |
| **Safety** | Command blacklist, high-risk confirmation UI, workspace write-boundary checks. |
| **Context** | Layers: `pinned` / `working` / `archived`; checkpoints (append/replace); budget trim; auto-summary; injection audit rows. |
| **Observability** | JSON logs (`LOGGING_SPEC.md`), `x-request-id`, REST APIs for executions and context injections. |
| **Skills** | PDF (PyMuPDF + fallbacks), weather, web read/search, notes, repo grep, vision, video; **Apple Silicon**: optional **mlx-whisper** for local STT (see `requirements.txt` markers). |

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
# Edit .env.local: data dir, search gateway, etc. Web upstream is only in SQLite via UI “Model settings” (see Configuration)

./start_web.sh
```

- Default UI: [http://127.0.0.1:8788/ui/](http://127.0.0.1:8788/ui/)
- Another port: `OMLXCLI_PORT=8790 ./start_web.sh`

Use **`.venv/bin/python`** for scripts so dependencies (PyMuPDF, conditional mlx-whisper, etc.) match the web process.

---

## Configuration

- **Template**: **`.env.example`** — copy to **`.env.local`** (gitignored).
- **Load order**: `webapi/dotenv_loader.py` loads `.env` then **`.env.local`**; values already present in the environment are not overwritten. `start_web.sh` also `source`s these files.
- **Model settings (Web)**: Add at least one row; **`api_base` / `api_key` / default model** live in **`sessions.db`** (`vendors`); bind a row per session in Settings before chat or LLM-using Skills. **Do not** use `OI_API_BASE` / `OI_API_KEY` in `.env.local` for the web UI (removed from **`.env.example`**; delete stale keys locally if present).
- **Typical `.env.local` keys**: `OMLXCLI_DATA_DIR`, `OMLXCLI_DEFAULT_WORKSPACE`, `OMLXCLI_RUN_SKILL_TIMEOUT_SEC`, `OMLXCLI_CHAT_*`, `OMLXCLI_SEARCH_*` / `OMLXCLI_SEARXNG_URL`, etc. Default model id for new sessions and legacy placeholder resolution use **`DEFAULT_SESSION_MODEL_ID`** in code plus the bound vendor’s **`default_model`**—no **`OI_MODEL`** env. See **`.env.example`**.

---

## Features

**Sessions**

- Create, switch, delete sessions; auto-generated titles, manual edit, title lock.
- Per-session model and **bound model settings** (`vendors` row), workspace path, and execution policy.

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
| `python3 scripts/smoke_all_skills.py` | Optional full skills smoke; env vars in `Skills_README.md` §8.1. |
| `./.venv/bin/python -m playwright install chromium` | First-time browser install for E2E tests. |

CI (`.github/workflows/ci.yml`): `pip install -r requirements.txt`, Playwright Chromium, `gen_oi_tool_map --check`, unittest **including** Playwright, then `uvicorn` + `scripts/smoke_http.py`. Tests set `OMLXCLI_EVAL_SKIP_HTTP=1` by default for outbound-sensitive cases.

---

## Related documentation

The repository home **`README.md`** includes the **maintainer reference environment** and **UI / skills smoke illustrations** (`docs/readme/`) to help visitors trust local runs.

| File | Description |
|------|-------------|
| `Skills_README.md` | Skills catalog, manifest, OI_TOOL_MAP workflow, smoke variables. |
| `.env.example` | All environment variables with comments. |
| `IMPLEMENTATION_PLAN.md` | Status, code pointers, optional evolution; keep in sync with matrix/API docs. |
| `OI_CAPABILITY_MATRIX.md` | Capability list (implemented / partial / missing). |
| `docs/API.md` | **HTTP API** (custom frontends, SSE, errors); complements **`/docs`** OpenAPI. |
| `docs/UPSTREAM_VENDOR_IMPLEMENTATION.md` | Model settings: credentials, binding, DB ops (REST details in **`docs/API.md`**). |
| `CHANGELOG.md` | Release notes (tracks `webapi` FastAPI `version`). |

---

## Roadmap

Roadmap and gaps: **`OI_CAPABILITY_MATRIX.md`** and **`IMPLEMENTATION_PLAN.md`** §5.

---

## Contributing

Issues and pull requests are welcome. Do **not** commit secrets—use **`.env.local`**. Run **`./scripts/dev_check.sh`** before opening a PR when possible, and describe user-visible changes clearly in the PR body.

---

## License

Add a root **`LICENSE`** file (e.g. MIT, Apache-2.0) when you publish under explicit terms; downstream users and packagers expect it.

---

<p align="center">
  <a href="README.md"><b>← Repository home</b></a>
  &nbsp;·&nbsp;
  <a href="README_cn.md"><b>中文版</b></a>
</p>
