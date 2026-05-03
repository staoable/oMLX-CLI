# oMLX CLI 实施计划与能力对照

与 **`OI_CAPABILITY_MATRIX.md`**（能力全景）、**`CHANGELOG.md`**（按版本的事实变更）、**`docs/API.md`**（HTTP 与 SSE 契约）、**`docs/UPSTREAM_VENDOR_IMPLEMENTATION.md`**（模型设置与凭据边界）一起维护；避免在本文件重复长表格或已完成的「周里程碑」排期。

---

## 1) 能力域与状态（摘要表）

说明：`状态` = 已实现 / 部分实现 / 未实现。`备注` 仅保留与排期相关的补充；细节以代码与 OpenAPI（`/docs`）为准。

| 能力域 | 子能力 | 状态 | 备注 |
|--------|--------|------|------|
| 模型接入 | OpenAI-compatible 对话 + 流式 | 已实现 | 超时/重试/回退链：`OMLXCLI_CHAT_*`、`OMLXCLI_MODEL_FALLBACKS`（`oi_runtime_core.py`） |
| 模型接入 | 模型设置 `vendors` + 会话 `vendor_id` + `resolve_upstream_credentials` | 已实现 | 见 **`docs/UPSTREAM_VENDOR_IMPLEMENTATION.md`** |
| 执行代理 | `run_shell` 多轮、`require_confirm`、`confirm-command` | 已实现 | 策略：`OMLXCLI_EXEC_*`、模板 `webapi/config.py` |
| 执行代理 | 审计 `executions` + 按会话查询 API | 已实现 | 见 **`docs/API.md`** |
| 工具 | `run_skill` + manifest + AST 校验 + `OI_TOOL_MAP.json` 生成链 | 已实现 | **`Skills_README.md`** |
| 会话 | CRUD、归档、`batch-archive` | 已实现 | `webapi/app.py`、`session_store.py` |
| 上下文 | pinned / working / archived、priority、checkpoint、`resume` | 已实现 | `context_manager.py` |
| 上下文 | 长会话预算裁剪与注入记录 | 已实现 | `OMLXCLI_CONTEXT_BUDGET_CHARS` 等；`context_injections` |
| 上下文 | **语义检索**独立召回层 | 未实现 | — |
| 前端 | SSE、Markdown、附件、执行时间线、`agent_trace` | 已实现 / 部分 | 观测数据：`GET .../executions` 等 |
| 可观测 | `request_id`、`error_code` JSON 日志 | 已实现 | **`LOGGING_SPEC.md`** |
| 质量 | `unittest`、Playwright `/ui/` 冒烟、`smoke_http`、`gen_oi_tool_map --check` | 已实现 / 部分 | CI：`.github/workflows/ci.yml` |

---

## 2) Session / Context：当前实现与边界

**已实现（`context_manager.build_prompt_messages_debug`）**：在 system 与用户输入之间注入 Pinned / Working / Archived 文本块、近期对话、工作目录权威说明、当前用户多模态 `content`；超预算时在消息级裁剪并写入 `context_injections`。

**未实现（本仓库无对应代码路径）**：独立「语义检索」服务层；**`summaries` / `artifacts` 独立表**及与主 `messages` 分离的摘要版本链——**不在**当前 SQLite schema，亦非交付承诺。

---

## 3) 代码与测试落点（速查）

| 主题 | 位置 |
|------|------|
| HTTP 全路由、请求体 | `webapi/app.py`；说明 **`docs/API.md`** + **`/openapi.json`** |
| 会话 / 消息 / vendors / 执行 / trace | `webapi/session_store.py` |
| 流式对话与执行循环 | `webapi/session_engine.py`；凭据 `webapi/upstream_credentials.py` |
| 执行策略 | `webapi/execution_policy.py`、`webapi/config.py` |
| 协议解析 | `webapi/engine_protocol.py` |
| 上游 HTTP | `oi_runtime_core.py` |
| Agent 评测 JSON | `tests/fixtures/agent_eval_scenarios.json`（**35** 条）、`tests/test_agent_maturity.py` |
| 策略评测 JSON | `tests/fixtures/policy_eval_scenarios.json`（**13** 条） |
| Skills 映射校验 | `scripts/gen_oi_tool_map.py`、`tests/test_oi_tool_map_skills.py` |
| 管理员审计导出 | `GET /api/admin/sessions/{id}/audit-export` + `OMLXCLI_ADMIN_TOKEN` |

---

## 4) 任务拆分模板（执行用）

- **目标** / **范围** / **契约**（输入输出、错误语义）/ **验收** / **回滚**

---

## 5) 可选演进（未排期、非承诺）

以下不与当前里程碑绑定；需要时另开议题与评测基线。

- 语义检索与召回打分；tokenizer 级预算（替代纯字符估算）。
- 业务错误码字典、日志脱敏、SSE 细粒度结构化日志。
- `run_skill` JSON Schema 级入参校验加强；E2E 覆盖发消息全链路。
- 多 Agent / 企业 RBAC / 密钥 OS 级托管等——属平台化方向，见历史讨论与 `OI_CAPABILITY_MATRIX` 中「未实现」行。
