# OI Capability Matrix（oMLX CLI Web 能力清单）

与 **`IMPLEMENTATION_PLAN.md`**、**`docs/API.md`**、**`CHANGELOG.md`** 同步更新。状态定义：**已实现**（主链路可验）、**部分实现**（可用但缺治理/体验项）、**未实现**。优先级 **P0/P1/P2** 仅表示相对重要性，不代表未排期的承诺。

---

## 1. 协议与代理执行

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 备注 |
|------|------|------|--------|------------|------|
| 协议解析（`run_shell` / `run_skill` / `final_answer`） | 标签解析与多轮循环 | 已实现 | P0 | `engine_protocol.py`, `session_engine.py` | 可选：协议版本号 |
| 多轮收敛与轮次上限 | `OMLXCLI_MAX_EXEC_ROUNDS` 等 | 已实现 | P0 | `session_engine.py` | 可选：总时长/总成本阈值 |
| 命令确认（弹窗 / API / 文本） | 与 `pending_command` 一致 | 已实现 | P0 | `app.py`, `webui/app.js` | — |
| 工作目录查询兜底 | 不走模型直接答当前目录 | 已实现 | P1 | `session_engine.py`, `context_manager.py` | — |

---

## 2. 安全与执行治理

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 备注 |
|------|------|------|--------|------------|------|
| 高风险识别与确认 | `OMLXCLI_EXEC_*` + 模板 | 已实现 | P0 | `execution_policy.py`, `config.py` | — |
| 黑名单阻断 | 有 | 已实现 | P0 | `execution_policy.py` | — |
| 写路径越界与 `realpath` | 有 + 单测 | 已实现 | P0 | `execution_policy.py`, `tests/test_agent_maturity.py` | — |
| 执行审计与按会话查询 | `executions` + API | 已实现 | P0 | `session_store.py`, `app.py` | 见 **`docs/API.md`** |
| 策略模板 `strict/readonly/...` | 环境变量切换 | 部分实现 | P1 | `config.py`, `execution_policy.py` | 会话级覆盖等可选 |

---

## 3. 会话（Session）

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 备注 |
|------|------|------|--------|------------|------|
| CRUD + 归档 + `batch-archive` | 有 | 已实现 | P0 | `app.py`, `session_store.py` | — |
| 配置隔离 | `model`、`vendor_id`、`api_base`（随 vendor 同步）、工作目录、执行开关；**密钥仅在 `vendors`** | 已实现 | P0 | `session_store.py` | 见 **`docs/UPSTREAM_VENDOR_IMPLEMENTATION.md`** |
| 标题 | 自动命名 + 编辑 + 锁定 | 已实现 | P1 | `session_engine.py`, `webui/app.js` | — |

---

## 4. 上下文（Context / Memory）

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 备注 |
|------|------|------|--------|------------|------|
| Pinned / Working / Archived + `priority` | 落库与注入 | 已实现 | P0 | `context_manager.py`, `session_store.py` | — |
| Checkpoint + `resume`（append/replace） | 有 | 已实现 | P0 | `context_manager.py`, `app.py` | — |
| 预算裁剪与 `context_injections` 记录 | 有 | 已实现 | P0 | 同上 + `app.py` | Web 观测面板可读 API |
| **语义检索召回** | 无独立层 | 未实现 | P1 | — | — |

---

## 5. 模型接入

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 备注 |
|------|------|------|--------|------------|------|
| 对话与凭据 | SQLite `vendors` + `resolve_upstream_credentials` | 已实现 | P0 | `upstream_credentials.py`, `session_engine.py`, `oi_runtime_core.py` | — |
| `GET /api/models` | **必填** `vendor_id` | 已实现 | P0 | `app.py` | — |
| 模型设置 CRUD + 拉取模型列表（probe） | 有 | 已实现 | P1 | `app.py`, `session_store.py`, `webui` | **`docs/API.md`** |
| 默认 / 占位 model | `DEFAULT_SESSION_MODEL_ID` + `vendors.default_model` | 已实现 | P1 | `session_engine.py` | — |
| 上下文窗口估算 | 内存启发式 | 部分实现 | P2 | `oi_runtime_core.py` | 可选：按模型配置 |

---

## 6. Skills / 工具

**技能名与文件路径以 `.omlxcli/skills/manifests/skills.json` 与 `Skills_README.md` §2 为准**（勿依赖下列历史枚举）。

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 备注 |
|------|------|------|--------|------------|------|
| 扫描注册与 `run_skill` | 有 | 已实现 | P0 | `_registry.py`, `skill_runner.py` | — |
| manifest + AST 校验 | 有 | 已实现 | P0 | `skill_manifest.py`, `manifests/skills.json` | — |
| Web 下 `_AICLI_*` 注入 | `_skill_llm_env` | 已实现 | P0 | `session_engine.py` | 与会话上游一致 |
| `OI_TOOL_MAP.json` 生成链 | `gen_oi_tool_map.py` + 单测 | 已实现 | P0 | `scripts/`, `tests/test_oi_tool_map_skills.py` | — |
| 表格 / Git / JSON·YAML / Word | **`csv_tsv_summary`**、**`xlsx_sample`**、**`git_snapshot`**、**`structured_pick`**、**`docx_to_text`** | 已实现 | P0 | `.omlxcli/skills/spreadsheet.py` 等、`tests/test_workspace_skills.py` | 依赖 **openpyxl**、**python-docx**、**PyYAML**（`requirements.txt`） |
| 沙箱 | AST 限制 + 超时 `OMLXCLI_RUN_SKILL_TIMEOUT_SEC` | 部分实现 | P0 | `skill_runner.py` | 可选：更强隔离 |

---

## 7. Web 与可观测性

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 备注 |
|------|------|------|--------|------------|------|
| 聊天流式、Markdown、附件 | 有 | 已实现 | P0 | `webui/` | — |
| 执行步骤 / 观测 API | 有 | 部分实现 | P1 | `webui/app.js`, `app.py` | 侧栏任务视图等可选 |
| JSON 日志 + `request_id` | 有 | 已实现 | P0 | `logging_utils.py`, `app.py` | **`LOGGING_SPEC.md`** |
| 统一错误 JSON | 有 | 已实现 | P0 | `app.py` | — |
| 自动化测试 | 单测 + Playwright 冒烟 + CI | 部分实现 | P0 | `tests/`, `.github/workflows/ci.yml` | 深度 E2E 可选 |

---

## 8. 维护

- 能力或路由变更时：更新本表、`docs/API.md` 或 OpenAPI 注释、`CHANGELOG.md`（用户可见行为）。
- 不必在本文件保留「已完成」的勾选清单；版本事实以 **`CHANGELOG.md`** 为准。
