# oMLX CLI Web 后端 HTTP API 说明

本文档面向**自建前端、脚本或第三方客户端**：说明当前 `webapi.app:app`（FastAPI）暴露的 REST 与流式接口。字段与状态码以仓库内实现为准；若与运行中的服务不一致，以 **`/openapi.json`** 为准。

**相关文档**：模型设置（凭据、绑定、运维）见 **[UPSTREAM_VENDOR_IMPLEMENTATION.md](./UPSTREAM_VENDOR_IMPLEMENTATION.md)**；能力全景见仓库根 **`OI_CAPABILITY_MATRIX.md`**。

---

## 1. 约定

### 1.1 基址与路径

- 默认在单进程内同时提供 **`/api/*`** API 与 **`/ui/*`** 内置前端（见 `webapi/app.py`）。
- 请求 URL 建议使用**与页面同源**的绝对路径（例如 `https://host/api/sessions`），或按部署前缀解析（内置 Web 使用相对 `../api/...` 以支持子路径反代）。
- 根路径 **`GET /`** 会 **302** 到 **`/ui/`**。

### 1.2 内容类型与编码

- 凡带 JSON 体的请求：头 **`Content-Type: application/json`**，UTF-8。
- 响应 JSON 亦为 UTF-8（`application/json`），SSE 见下文。

### 1.3 CORS

- 已配置 **`Access-Control-Allow-Origin: *`**（见 `CORSMiddleware`），浏览器跨域调用一般可行；若你自行限制 Cookie，注意与 `allow_credentials` 的组合策略。

### 1.4 请求 ID

- 中间件为每个请求生成或透传 **`X-Request-Id`**（响应头与部分错误体中的 `request_id` 一致），便于排查。

### 1.5 与 OpenAPI 对齐

服务启动后可直接打开：

| 资源 | 路径 | 说明 |
|------|------|------|
| Swagger UI | **`/docs`** | 可试请求、看 Schema |
| OpenAPI JSON | **`/openapi.json`** | 机器可读，可生成客户端 |

本文件侧重**集成流程与 SSE**；字段级细节以 OpenAPI 为准。

---

## 2. 错误格式

多数业务错误返回 JSON，HTTP 状态码与 `4xx/5xx` 一致，常见结构：

```json
{
  "error_code": "HTTP_ERROR",
  "message": "人类可读说明",
  "request_id": "uuid"
}
```

部分路由（如管理员导出）在 `HTTPException` 的 `detail` 中直接携带上述对象。简单字符串 `detail` 时，`error_code` 多为 **`HTTP_ERROR`**。

---

## 3. 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| **GET** | `/healthz` | 存活探测。响应示例：`{"ok":"true"}` |

---

## 4. 模型设置（`vendors`）与上游模型列表

上游 **OpenAI 兼容** 服务的 Base URL 与 API Key 存于 SQLite **`vendors`** 表；会话通过 **`vendor_id`** 绑定一行。

### 4.1 列出模型设置（不含密钥）

**GET** `/api/vendors`

响应：`VendorRecord[]` 的 JSON 数组，**不含** `api_key` 字段。单条对象字段包括：`id`, `name`, `slug`, `api_base`, `default_model`, `created_at`, `updated_at`（与 `webapi/session_store.VendorRecord` 一致，列表响应已剔除 `api_key`）。

### 4.2 单条模型设置（含密钥）

**GET** `/api/vendors/{vendor_id}`

- 成功：返回完整对象，**含 `api_key`**（供管理端编辑回显；勿记录到不可信日志）。
- 404：不存在。

### 4.3 创建

**POST** `/api/vendors`

请求体（JSON）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 显示名 |
| `api_base` | string | 是 | 上游根 URL，如 `https://api.openai.com/v1` |
| `default_model` | string | 否 | 默认模型 id，可为空串 |
| `api_key` | string \| null | 否 | 非空则写入库；省略或空可表示暂无密钥 |

- **`slug` 由服务端生成**，请求体**不接受**客户端 `slug`。
- 成功：HTTP **200** + 新建对象 JSON（**响应中剔除** `api_key`）。

### 4.4 更新

**PATCH** `/api/vendors/{vendor_id}`

请求体字段均为可选：`name`, `api_base`, `default_model`, `api_key`。若包含 **`api_key`**：按字符串写入（**空字符串可清空**库内密钥，具体见 `session_store.update_vendor`）。

响应：更新后的对象（**剔除** `api_key`）。

### 4.5 删除

**DELETE** `/api/vendors/{vendor_id}`

- 成功：`{"status":"ok"}`。
- **409**：仍有会话引用该 `vendor_id`，不可删。

### 4.6 下载模型列表 / 探测（不写库）

**POST** `/api/vendors/probe`

请求体：

```json
{ "api_base": "https://...", "api_key": "sk-..." }
```

- `api_key` 不能为空（会 **400**）。
- 成功：`{"ok": true, "api_base": "<规范化后的 base>", "models": ["id1", "..."]}`（与上游 `GET {base}/models` 解析一致）。

### 4.7 代理上游模型列表

**GET** `/api/models?vendor_id=<vendors.id>`

- **必填**查询参数 **`vendor_id`**；历史参数 `api_base` 已废弃，应忽略。
- 从对应 `vendors` 行读取 **`api_key`** 调上游；若该行无密钥则 **400**。
- 成功：`{"api_base": "...", "models": ["..."], "vendor_id": "..."}`。

---

## 5. 会话

### 5.1 创建会话

**POST** `/api/sessions`

请求体（节选，`CreateSessionReq`）：

| 字段 | 说明 |
|------|------|
| `title` | 默认 `"新会话"` |
| `workspace_path` | 工作目录；会规范化、展开 `~` |
| `model` | 默认取代码常量 **`DEFAULT_SESSION_MODEL_ID`**（见 `webapi/session_engine.py`） |
| `api_base` | 未绑 `vendor_id` 时可空；绑定时由服务端同步为 vendor 的 base |
| `vendor_id` | 可选；若提供则从该 vendor 同步 **`api_base`**，且若 vendor 有 **`default_model`** 则覆盖 `model` |
| `auto_run` | 默认 `true` |
| `execution_enabled` | 是否走「代理执行」多轮 shell/skill 流程，默认 `false` |
| `confirm_each` | 高危 shell 前是否要求确认，默认 `true` |

响应：完整 **`SessionRecord`** 的 JSON 对象（`asdict`），字段包括：

`id`, `title`, `title_locked`, `workspace_path`, `model`, `api_base`, `vendor_id`, `auto_run`, `execution_enabled`, `confirm_each`, `pending_command`, `summary`, `archived`, `created_at`, `updated_at`, `last_active_at`。

### 5.2 列出会话

**GET** `/api/sessions?include_archived=0|1`

- `include_archived=1` 时包含已归档会话。

响应：`SessionRecord[]`。

### 5.3 获取单个会话（含嵌套数据）

**GET** `/api/sessions/{session_id}`

响应在会话对象上附加：

- `messages`：消息列表；元素常见字段：`id`, `session_id`, `role`, `content`, `kind`, `attachments`（数组）, `token_estimate`, `metrics`, `created_at`。
- `contexts`：上下文层记录。
- `checkpoints`：检查点列表。
- `executions`：最近执行记录（最多 100 条）。
- `context_injections`：最近注入调试记录（最多 120 条）。

### 5.4 更新会话

**PATCH** `/api/sessions/{session_id}`

请求体字段均为可选：`title`, `workspace_path`, `model`, `api_base`, `vendor_id`, `auto_run`, `execution_enabled`, `confirm_each`, `archived`。

- 若 PATCH **`title`**，服务端会将 **`title_locked`** 置为真。
- 若 PATCH **`vendor_id`** 为非空字符串：校验 vendor 存在，并同步 **`api_base`**；若 PATCH 中未带 `model` 且 vendor 有 **`default_model`**，会一并更新 **`model`**。
- 将 **`vendor_id`** 置为 **`null`**：表示**解绑**模型设置（JSON 中传 `null`）。

### 5.5 删除会话

**DELETE** `/api/sessions/{session_id}`

成功：`{"status":"ok"}`（级联删除关联数据）。

### 5.6 批量归档

**POST** `/api/sessions/batch-archive`

请求体：

```json
{
  "session_ids": ["uuid", "..."],
  "archived": true
}
```

- 最多处理约 **500** 个 id（实现为切片上限）。
- 响应：`{"status":"ok","updated": <成功更新的条数>}`（不存在的 id 会跳过）。

---

## 6. 发送消息（SSE）

**POST** `/api/sessions/{session_id}/messages`

请求体：

| 字段 | 类型 | 说明 |
|------|------|------|
| `content` | string | 用户正文 |
| `system_prompt` | string | 可选，默认内置中文系统提示 |
| `attachments` | array | 可选；元素形如 `{"name","mime","size","data_url"}`，与内置 Web 一致（图片等多模态见 `context_manager`） |

响应：**`text/event-stream`**（Server-Sent Events），**非** JSON 单响应。

### 6.1 SSE 帧格式

每事件若干行，以**空行**结束：

```
event: <类型>
data: <JSON 对象>

```

- `data` 为**单行** JSON（UTF-8）。解析时可按 `\n\n` 分帧，再读 `event:` / `data:`。

### 6.2 事件类型一览

| `event` | `data` 主要字段 | 说明 |
|---------|-----------------|------|
| `delta` | `type`, `content` | 助手增量文本（流式拼接） |
| `metrics` | `type`, `ttft_ms`, `gen_duration_ms`, `tps`, `input_tokens_est`, `output_tokens_est`, `total_tokens_est` | 粗粒度性能（一次回复末尾常见一条） |
| `exec_step` | `type`, `command`, `status` | 开始执行 shell 或 `skill: ...` |
| `exec_result` | `type`, `command`, `exit_code`, `stdout`, `stderr`, `duration_ms?` | shell 含 `duration_ms`；skill 分支可能省略 `duration_ms`，以实际 payload 为准 |
| `require_confirm` | `type`, `command`, `reason` | 需用户调用 **§7 确认接口** 或按助手提示操作 |
| `agent_trace` | `type`, `turn_id`, `step_index`, `action`, `detail` | 代理执行轨迹，与 **§8** `agent-trace` 列表结构对应 |
| `error` | 常见含 `type` 与 `content`；会话不存在时 data 可能仅为 **`{"message":"session not found"}`**（无 `type`） |
| `done` | `{}` | 流结束标记 |

说明：

- 每条 `data` JSON 内通常仍带 **`"type"`** 字段，与 `event:` 行一致，便于单一路由解析。
- **`execution_enabled=false`** 时走纯对话流，一般只有 `delta` / `metrics` / `error` / `done`。
- 上游或凭据错误时，可能在写入助手 `error` 类消息后以 **`event: error`** 结束；请以 `GET /api/sessions/{id}` 再拉库为准。

### 6.3 客户端最小流程

1. `POST /api/sessions` 创建会话，并（推荐）`PATCH` 绑定 **`vendor_id`**、选好 **`model`**。
2. `POST .../messages`，`body` 为 JSON；用 **`ReadableStream`** 或 `fetch().body.getReader()` 读 SSE。
3. 收到 **`require_confirm`** 后，由用户决定调用 **`POST .../confirm-command`**（§7）。
4. 流结束后 **`GET /api/sessions/{id}`** 同步消息列表与 `pending_command` 等。

---

## 7. 命令确认（高危 shell）

**POST** `/api/sessions/{session_id}/confirm-command`

请求体：

```json
{ "command": "与 pending 或 SSE 中一致的命令", "approve": true }
```

- **`approve": false`**：取消待确认命令，写入一条 `cancelled` 执行记录及助手提示；返回 `{"status":"cancelled","message":"..."}`。
- **`approve": true`**：执行该命令（须与当前会话 **`pending_command`** 一致，否则 **400**）。成功时返回包含 **`command`, `exit_code`, `stdout`, `stderr`, `answer`, `metrics`, `pending_command`** 等字段的对象（见 `session_engine.run_confirmed_command`）。

---

## 8. 观测与调试数据（GET）

以下接口在会话不存在时返回 **404**。

| 方法 | 路径 | 查询参数 | 说明 |
|------|------|----------|------|
| **GET** | `/api/sessions/{session_id}/executions` | `limit` 默认 100，范围 1–500 | shell/skill 执行审计列表 |
| **GET** | `/api/sessions/{session_id}/context-injections` | `limit` 默认 120，1–500 | 构造提示时的上下文注入调试行 |
| **GET** | `/api/sessions/{session_id}/agent-trace` | `turn_id` 可选；`limit` 默认 200，1–500 | 代理轨迹；不带 `turn_id` 时为最近若干条按时间倒序再反转，适合时间线展示 |

**`executions`** 元素字段示例：`id`, `session_id`, `exec_type`, `command`, `status`, `reason`, `exit_code`, `stdout`, `stderr`, `duration_ms`, `metadata`, `created_at`。

**`context_injections`**：`id`, `session_id`, `source`, `role`, `char_count`, `dropped`, `reason`, `created_at`。

**`agent_trace`**：`id`, `session_id`, `turn_id`, `step_index`, `action_type`, `detail`, `created_at`（列表中与 SSE 的 `action` / `detail` 对应）。

---

## 9. 上下文与 Checkpoint

### 9.1 固定上下文（pinned）

**POST** `/api/sessions/{session_id}/context/pin`

请求体：`{"content":"...", "priority": 0}`，`priority` 范围 **-1000～1000**（默认 0）。

响应：新建的 context 行（`id`, `session_id`, `layer`=`pinned`, `content`, `priority`, `created_at`）。

### 9.2 工作上下文（working）

**POST** `/api/sessions/{session_id}/context/working`

请求体同 pin。`layer` 为 **`working`**。

### 9.3 创建 checkpoint

**POST** `/api/sessions/{session_id}/context/checkpoint`

请求体：`{"summary":"本次摘要"}`。

行为：归档当前 bundle、更新会话 `summary`、写入 **`checkpoints`** 表。响应为 checkpoint 对象：`id`, `session_id`, `summary`, `payload`, `created_at`；其中 **`payload`** 内含 `pinned` / `working` / `archived` / `recent_messages` 等快照。

### 9.4 从 checkpoint 恢复

**POST** `/api/sessions/{session_id}/resume`

请求体：

```json
{ "checkpoint_id": "uuid", "mode": "append" }
```

- **`mode`**：`append`（默认）在现有 working 上追加；**`replace`** 先清空 **working** 层再写入快照中的 working 行。
- 成功：返回对应 checkpoint 对象（同列表中的结构）。

---

## 10. 管理员审计导出

**GET** `/api/admin/sessions/{session_id}/audit-export`

- 请求头：**`X-Admin-Token: <与进程环境变量 OMLXCLI_ADMIN_TOKEN 一致>`**。
- 若未配置 **`OMLXCLI_ADMIN_TOKEN`**：**501**，`error_code` 多为 **`ADMIN_NOT_CONFIGURED`**。
- 令牌不匹配：**403**，**`FORBIDDEN`**。

成功响应为 JSON 大对象，包含：`session`, `messages`（至多 400 条）, `executions`（至多 500）, `context_injections`（至多 300）, `agent_trace`（至多 500）。

---

## 11. 自建前端注意事项

1. **凭据**：对话与依赖 LLM 的 skill 使用会话绑定的 **`vendor_id`** 及库内 **`api_key`**；不要在浏览器长期存放用户密钥 unless 你明确承担风险（内置 UI 仅通过单条 GET 回显编辑）。
2. **发消息前**：确保 **`vendor_id`**、**`api_key`**、**`model`** 可用，否则 `POST .../messages` 会在流内返回可读中文错误（见 `resolve_upstream_credentials`）。
3. **子路径部署**：API 与 UI 应同前缀；可参考内置 **`webui/core/api.js`** 的 **`resolveApiUrl`** 思路。
4. **附件**：大 **`data_url`** 会增加请求体积与延迟；生产环境可考虑改为对象存储 + URL 引用（需同步改服务端解析逻辑方可通用）。
5. **执行安全**：`execution_enabled=true` 时模型可提议 shell；务必实现 **`require_confirm`** 的用户确认 UI，并理解 **`confirm-command`** 的幂等与校验规则。

---

## 12. 版本

本文档编写时应用内 **`FastAPI` `version`** 字段为 **`0.2.0`**（见 `webapi/app.py`）。升级后请以 **`/openapi.json`** 与 **`CHANGELOG.md`** 为准。
