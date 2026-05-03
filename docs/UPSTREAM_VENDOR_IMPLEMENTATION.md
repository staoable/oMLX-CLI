# 模型设置（Upstream）— 设计与运维说明

与当前代码对齐：**`vendors` 表**（含 **`api_key`** 明文列）、会话可选 **`vendor_id`**、无内置默认上游行、Skills 经 **`_AICLI_*`** 与会话同一解析路径。HTTP 路径、请求体、SSE 见 **`docs/API.md`** 与运行时的 **`/openapi.json`**。

---

## 1. 当前行为（摘要）

- **凭据**：仅 **`vendors.api_key`** + **`api_base`**；`webapi/upstream_credentials.resolve_upstream_credentials(session, store)` 读取；**不**用 `.env` 中的 `OI_API_*` 作为 Web 对话上游。
- **会话**：`sessions.vendor_id` 可空；未绑定或密钥为空时，**发消息**会得到明确中文错误，引导先配置并保存模型设置。
- **拉模型**：**`GET /api/models?vendor_id=<vendors.id>`**（`vendor_id` 必填）；**`POST /api/vendors/probe`** 用请求体中的 base+key 拉取列表（界面「下载模型列表」），不写库。
- **对话**：`POST {api_base}/chat/completions`（`oi_runtime_core`），流式字段 `choices[0].delta.content`。
- **Skills**：`run_skill` 前 **`_skill_llm_env`** 写入 **`_AICLI_API_BASE`**、**`_AICLI_API_KEY`**、**`_AICLI_LLM_MODEL`**；`_media._llm_endpoint` **不**回退 `OI_API_*`。
- **默认 model**：新会话默认 id 见代码 **`DEFAULT_SESSION_MODEL_ID`**；占位名 `local`/`default`/空时优先已绑定 **`vendors.default_model`**（见 `session_engine._resolve_effective_model`）。

**非目标（本仓库范围外）**：OpenAI 全量 API（embeddings、assistants 等）；多租户计费；各厂商专有扩展字段的通用适配（可在 `oi_runtime_core` 按需加）。

---

## 2. 概念

| 概念 | 说明 |
|------|------|
| **模型设置（一行 `vendors`）** | 显示名、`api_base`、**`default_model`**、**`api_key`**；**`slug`** 创建时由服务端生成，REST 列表/写响应默认不暴露敏感字段。 |
| **Probe** | 仅验证连通性并返回模型 id 列表，不落库。 |
| **会话绑定** | `vendor_id` 指向 `vendors.id`；`PATCH` 中 **`vendor_id: null`** 解绑。 |

**运维**：`sessions.db` 含密钥，注意文件权限与备份范围。

---

## 3. 存储（SQLite，`session_store`）

### 3.1 `vendors`

| 字段 | 说明 |
|------|------|
| `id` | UUID |
| `name` | 展示名 |
| `slug` | UNIQUE，服务端生成 |
| `api_base` | 上游根 URL |
| `default_model` | 默认模型 id |
| `api_key` | Bearer 密钥，服务端使用 |
| `created_at` / `updated_at` | ISO8601 |

### 3.2 `sessions.vendor_id`

可空；绑定后 **`api_base`** 等与所选行同步（见 `app.py` 中 `create_session` / `update_session`）。

迁移由 **`session_store._init_db`** 内 `CREATE TABLE` / `ALTER TABLE` 完成（无独立 Alembic 工程）。

---

## 4. 解析规则（发消息 / 拉模型）

逻辑入口：**`webapi/upstream_credentials.py`**（无可用 vendor/绑定/key 时抛 **`RuntimeError`**，消息已本地化）。

**Skills**：环境注入见 **`webapi/session_engine.py`** 中 **`_skill_llm_env`**。

---

## 5. 密钥与传输

- **列表 `GET /api/vendors`**：响应**无** `api_key`。
- **单条 `GET /api/vendors/{id}`**：**含** `api_key`，供可信管理端编辑回显；勿打日志、勿缓存到不可信存储。
- **`POST`/`PATCH`**：请求体可选 **`api_key`**；`PATCH` 传入字段则更新（**空字符串可清空**库内密钥，与 `session_store.update_vendor` 一致）；写响应默认剔除 `api_key`。
- 日志与异常：**禁止**打印明文 `api_key`。

---

## 6. Web UI 要点

- **模型设置**弹窗：列表、新建/编辑、「下载模型列表」（`POST /api/vendors/probe`）、保存；新建/更新成功后**清空表单**以免误 `PATCH`（与内置 `webui/app.js` 行为一致）。
- **会话设置**：下拉绑定 `vendor_id`；「刷新模型」必须带已保存行的 **`vendor_id`** 调 **`GET /api/models`**。

---

## 7. 涉及文件（索引）

| 文件 | 职责 |
|------|------|
| `webapi/session_store.py` | `vendors` CRUD；`sessions` 含 `vendor_id` |
| `webapi/upstream_credentials.py` | 从 DB 解析上游 |
| `webapi/app.py` | `/api/vendors*`、`/api/models`、`/api/sessions*` |
| `webapi/session_engine.py` | `stream_reply`、`_resolve_effective_model`、`_skill_llm_env` |
| `webui/app.js` / `index.html` | 模型设置与会话绑定 UI |
| `.env.example` | 进程级 `OMLXCLI_CHAT_*` 等；**第十节** `_AICLI_*` 供脱离 Web 调试 skills |

---

## 8. OpenAI 兼容范围

依赖上游提供 **`GET {api_base}/models`** 与 **`POST {api_base}/chat/completions`**（`model`、`messages`、`temperature`、可选 `max_tokens`、`stream`）。tools / `response_format` 等不在本方案保证范围内。

---

## 9. 可选加固（未排期）

- `api_base` 主机校验、对用户更友好的错误码分层。
- 管理鉴权（谁改写了 vendor）、审计与导出（已有 **`GET /api/admin/sessions/{id}/audit-export`** + `OMLXCLI_ADMIN_TOKEN` 可选能力）。
- 密钥加密或外部密钥服务；子进程更强隔离。

---

## 10. 风险

| 风险 | 缓解 |
|------|------|
| SQLite 明文存 key | 文件权限、备份策略、单机信任边界 |
| XSS / 窃取管理请求 | 自托管场景下的鉴权、CSP、Cookie 策略（按部署栈选型） |
