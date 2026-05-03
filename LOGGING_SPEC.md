# 结构化日志规范（v1）

本文档定义 `oMLX CLI` 后端的最小结构化日志规范，用于排障、审计与链路追踪。

## 1. 输出格式

- 日志为单行 JSON（UTF-8）。
- 字段要求：
  - `ts`: UTC ISO 时间戳
  - `event_type`: 事件类型
- 建议字段：
  - `request_id`: 请求追踪 ID
  - `session_id`: 会话 ID
  - `path`: HTTP 路径
  - `status_code`: HTTP 状态码
  - `duration_ms`: 耗时（毫秒）

## 2. 当前已落地事件

- `http_request`
  - 字段：`request_id`, `method`, `path`, `status_code`, `duration_ms`
- `http_exception`
  - 字段：`request_id`, `path`, `status_code`, `error_code`, `detail`
- `internal_exception`
  - 字段：`request_id`, `path`, `error_code`, `detail`
- `session_created`
  - 字段：`session_id`, `workspace_path`, `model`
- `session_message_received`
  - 字段：`session_id`, `content_chars`
- `command_confirm_rejected`
  - 字段：`session_id`, `command`
- `command_confirm_approved`
  - 字段：`session_id`, `command`, `exit_code`
- `exec_blocked`
  - 字段：`session_id`, `exec_type`, `command`, `reason`
- `exec_need_confirm`
  - 字段：`session_id`, `exec_type`, `command`, `reason`
- `exec_finished`
  - 字段：`session_id`, `exec_type`, `command`, `exit_code`, `duration_ms?`
- `context_injection_recorded`
  - 字段：`session_id`, `total_rows`, `dropped_rows`, `input_chars`
- `vendor_created`
  - 字段：`vendor_id`, `slug`（不含 `api_key`）
- `vendor_updated`
  - 字段：`vendor_id`
- `vendor_deleted`
  - 字段：`vendor_id`

## 3. 关联关系

- `request_id`：串联同一 HTTP 请求的入口/异常日志。
- `session_id`：串联同一会话中的消息、执行、确认等行为。
- 若同时存在 `request_id` 与 `session_id`，优先用于跨层排障。

## 4. 可选扩展（未实现）

若后续要加强可观测性，可考虑：`event_version` / `component` / `env` 字段；SSE 细粒度事件入库；错误 `detail` 脱敏策略统一化。
