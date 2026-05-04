# Claude Code Job 规格（草案）

面向 **官方 `claude` CLI**、**macOS 本机优先**、**Job + 轮询**；与 Web 对话模型 **vendor** 分离，专用环境变量见 **`.env.example`**（实现阶段补齐）。

---

## 1. 已拍板的产品决策

| 项 | 结论 |
|----|------|
| **发起方式** | **仅**通过会话内模型输出 `<run_skill>…</run_skill>` 调用 `claude_job_*` skill；**首版 UI 不提供**「手动填 prompt 启动任务」。 |
| **日志** | **HTTP 轮询 + tail**；首版 **不**做 WebSocket / SSE 实时流。 |
| **CLI** | 官方 **Claude Code CLI**（`claude`）；安装路径见 README / bootstrap 提示（npm）。 |
| **平台** | **优先 macOS 本地**；其他平台文档级说明，首版不强保证。 |

---

## 2. 后端要点（与实现对齐用）

- **Job 服务**：`start`（spawn 子进程，`cwd` = 当前 **session `workspace_path`**）、`status`、`logs`（tail）、`cancel`；与 **REST 共用**同一套逻辑，skill 为薄封装。
- **会话上下文**：`run_skill` 调用链注入 **ContextVar**（`session_id`、`workdir`）；`job` 与 **session 绑定**，仅该会话可查询/取消。
- **环境**：`.env.local` 专用键（如 `OMLXCLI_CLAUDE_CODE_*`）；**未配置则 skill 返回明确错误**，REST 返回 `disabled` 或 403/404 策略待实现时统一。
- **日志落盘**：数据目录下按 `job_id` 隔离；**单 job 大小上限**；DB 存元数据 + 日志路径。
- **部署**：功能 **默认关闭**（如 `OMLXCLI_ENABLE_CLAUDE_CODE`）；Docker 默认不承诺带 `claude`。

---

## 3. REST（只读监控 + 取消）

首版建议（具体路径以实现为准）：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/sessions/{id}/claude-jobs` | 该会话最近 N 条 job 列表。 |
| `GET` | `/api/sessions/{id}/claude-jobs/{job_id}` | 状态与元数据。 |
| `GET` | `/api/sessions/{id}/claude-jobs/{job_id}/logs?tail=200` | **tail** 文本（轮询用）。 |
| `POST` | `/api/sessions/{id}/claude-jobs/{job_id}/cancel` | 取消运行中 job（可选；若策略只允许 skill 取消可二期再开放）。 |

**鉴权**：与现有会话 API 一致；**仅** `session_id` 匹配者可访问。

---

## 4. 前端（只读监控）

- **入口**：会话级 **「Claude 任务」**侧栏或面板；列表展示状态、时间、摘要（prompt 截断）。
- **行为**：对 **运行中** job **HTTP 轮询** `status`（退避策略：如 2s → 5s → 10s cap）；日志区轮询 **`logs?tail=…`**。
- **空状态 / 错误**：未安装 `claude`、未配置 env、功能关闭 → **说明 + 文档锚点 / 复制安装命令**；**不在 UI 收集密钥**。
- **与对话**：模型 `run_skill` 创建 job 后，用户靠侧栏查看；**可选二期**：解析 trace 自动展开某 `job_id`（非首版必做）。

---

## 5. Skills 表面（由模型调用）

| 函数 | 作用 |
|------|------|
| `claude_job_start(prompt, …)` | 创建 job、后台跑 `claude`，**快速返回** `job_id`。 |
| `claude_job_status(job_id)` | `running` / `completed` / `failed` / `cancelled` 等。 |
| `claude_job_logs(job_id, tail_lines=…)` | 与 REST tail 语义一致（或仅 REST 提供 tail，skill 返回占位——实现时二选一避免重复大块日志）。 |
| `claude_job_cancel(job_id)` | 终止子进程树。 |

单次 `run_skill` **须在现有超时内返回**；长耗时仅在子进程内。

---

## 6. 文档与运维

- **`.env.example`**：新增「Claude Code Job（可选）」节。  
- **`README` / `bootstrap`**：macOS 下检测 `claude`；缺失时打印安装指引。  
- **健康/设置**：可暴露 `claude_cli: ok | missing | disabled` 供本机排查。

---

## 7. 修订记录

- 2026-05-04：首版草案；确认 **仅 run_skill 发起**、**UI 只读**、**HTTP 轮询 + tail**。
