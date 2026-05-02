# oMLX CLI 落地实施清单（面向 oi 全能力 Web 化）

本文档用于把“目标愿景”拆解为可实施任务，默认以 6 周为一期，优先保证可交付与可验证。

## 1) oi 能力对齐矩阵（第一版）

说明：
- `状态` 分为：`已实现` / `部分实现` / `未实现`
- `优先级` 分为：`P0`（必须）/ `P1`（重要）/ `P2`（增强）

| 能力域 | 子能力 | 当前状态 | 差距说明 | 优先级 | 落地建议 |
|---|---|---|---|---|---|
| 模型接入 | OpenAI-compatible 文本对话 | 已实现 | 已支持可配置 HTTP 超时/重试（`OMLXCLI_CHAT_TIMEOUT_SEC`、`OMLXCLI_CHAT_HTTP_RETRIES`、`OMLXCLI_CHAT_RETRY_BACKOFF_SEC`） | P0 | 可按上游 SLA 调参；熔断与配额治理仍可选 |
| 模型接入 | 多模型切换与会话级配置 | 已实现 | 已支持回退链 `OMLXCLI_MODEL_FALLBACKS`（首选模型失败如 404 时依次尝试） | P1 | 可扩展为「按任务类型绑定模型」 |
| 执行代理 | `run_shell` 多轮执行循环 | 已实现 | 模板 + 黑名单/高风险/越界；可选白名单 `OMLXCLI_EXEC_ALLOWLIST_RE` | P0 | 误杀解释与规则管理界面仍可选 |
| 执行代理 | 高风险命令确认 | 已实现 | 策略由 `OMLXCLI_EXEC_*` 与模板组合配置 | P0 | 策略热更新与 UI 仍可选 |
| 执行代理 | 命令审计与回放 | 已实现 | `executions` 落库；确认 API 路径写入 `metadata.approved_via` 等 | P1 | 可继续细化审批人身份（登录用户） |
| 工具能力 | `run_skill` 调用链 | 已实现 | manifest + AST 参数校验 | P0 | 可按技能补充 JSON schema 级校验 |
| 工具能力 | oi 工具全集映射 | 已实现 | **全集 = `.omlxcli/skills`**；`OI_TOOL_MAP.json` 的 `skills[]` 由 `scripts/gen_oi_tool_map.py` 生成；`tests/test_oi_tool_map_skills.py` 防漂移 | P0 | 新技能：manifest + `gen_oi_tool_map.py --write` + 可选 `agent_eval_scenarios` |
| 会话系统 | 会话 CRUD、标题管理 | 已实现 | `archived` 字段、列表 `include_archived`、设置内归档、`POST /api/sessions/batch-archive` | P0 | 标签、保留策略仍可选 |
| 上下文系统 | pinned/working/archived | 已实现 | `contexts.priority` 控制注入顺序（同层高优先、新记录优先） | P0 | 语义冲突消解仍可选 |
| 上下文系统 | checkpoint 恢复 | 已实现 | `POST .../resume` 支持 `mode=append\|replace` | P1 | 可扩展 pinned 层恢复策略 |
| 上下文系统 | 长会话压缩策略 | 已实现 | 估算上下文字符超 `OMLXCLI_CONTEXT_BUDGET_CHARS * OMLXCLI_SUMMARY_TRIGGER_RATIO` 时节流触发 checkpoint；`OMLXCLI_SUMMARY_MIN_MESSAGES_BETWEEN` 防抖 | P0 | 可接入真实 tokenizer 预算 |
| 前端体验 | SSE 流式、Markdown、附件 | 已实现 | UI 体验未形成设计体系 | P1 | 建立 design token 与组件规范 |
| 前端体验 | 执行流可视化 | 部分实现 | 流式消息内已支持可折叠「执行时间线」与 `agent_trace` 行；侧栏独立 timeline/抽屉与重试入口仍可选 | P1 | 增加侧栏任务视图与失败重试 |
| 可观测性 | 错误码、结构化日志 | 已实现 | 主链路 `request_id`/`error_code` 与 JSON 日志（详见 `OI_CAPABILITY_MATRIX` 第 8 节） | P0 | 细化业务错误码字典与脱敏策略 |
| 质量保障 | 自动化测试 | 部分实现 | CI：`requirements.txt`、`unittest`（含 Playwright `/ui/` 冒烟）、`gen_oi_tool_map --check`、`smoke_http`；发消息/确认流等深度 E2E 仍可选 | P0 | 按需扩展 Playwright 场景 |

## 2) Session / Context 目标方案（参考主流 Web 助理）

## 2.1 目标原则

- 会话可追溯：每轮输入、注入上下文、工具调用、输出可回放。
- 上下文可控：用户可显式 pin；系统可自动压缩、检索、淘汰。
- 预算可解释：每轮明确 token 预算占用与裁剪原因。
- 策略可切换：支持“精确模式”（少压缩）与“经济模式”（强压缩）。

## 2.2 上下文分层模型

每轮组装建议按以下顺序：

1. `SystemPolicy`（系统策略、执行安全约束、工作目录权威信息）
2. `PinnedMemory`（用户长期偏好、关键事实，强保留）
3. `WorkingSet`（当前任务近轮关键上下文）
4. `RetrievedArchive`（历史归档中检索召回片段）
5. `RecentTurns`（最近对话窗口）
6. `CurrentUserInput`（当前输入与附件）

## 2.3 上下文预算策略（建议）

- 设定会话级预算：`context_budget_tokens`
- 预留输出预算：`response_reserve_tokens`
- 动态压缩触发条件：
  - 输入后预计总量超过预算的 80%
  - 或最近 6 轮累计增长过快
- 压缩优先级（先删后压）：
  - 先裁剪低分归档召回
  - 再压缩 WorkingSet
  - 最后才影响 RecentTurns
- 永不自动移除：
  - 用户 pin 的高优先级事实
  - 当前任务约束（如目标、验收标准）

## 2.4 Session 数据结构增强（建议）

建议在现有 SQLite 基础上新增：

- `executions`：命令审计（command/exit_code/duration/approval/status）
- `context_injections`：每轮实际注入项（source/type/size/score）
- `summaries`：摘要版本（summary_type/version/source_range）
- `artifacts`：执行产物索引（文件、报告、链接）

## 2.5 检索与排序（建议）

- 先规则后语义：
  - 规则召回：同会话、同主题、最近窗口
  - 语义召回：按 query 与历史摘要相似度
- 排序特征：
  - recency（最近度）
  - relevance（语义相关度）
  - authority（是否 pinned / 是否用户确认）
- 去重与冲突：
  - 相同事实取最新版本
  - 冲突事实同时展示并标记“待确认”

## 3) 六周实施里程碑（建议排期）

## Week 1：能力盘点与基础治理（P0）

- 建立 `oi -> web` 能力映射清单（功能名、协议、入参、出参、错误语义）
- 抽离配置中心（新增 `config.py` + 环境变量校验）
- 增加统一错误结构：`error_code`, `message`, `request_id`
- 验收标准：
  - 能力清单可追踪到具体文件和接口
  - 启动时配置缺失可给出清晰报错

## Week 2：执行代理安全与审计（P0）

- 执行策略升级为“策略集”（黑名单/白名单/工作区约束）
- 新增 `executions` 审计落库与查询接口
- 完成确认流统一（弹窗确认、文本确认、API 确认行为一致）
- 验收标准：
  - 每次执行可完整追踪
  - 越界写与高风险命令可稳定阻断或确认

## Week 3：Session/Context 核心升级（P0）

- 实现上下文预算器（预算计算 + 裁剪日志）
- 加入检索召回层（规则召回先行）
- Checkpoint 恢复模式扩展：`append` / `replace`
- 验收标准：
  - 长会话下回复质量稳定，无明显“忘记核心约束”
  - 可查看每轮上下文注入明细

## Week 4：Web 交互体验与设计系统（P1）

- 建立 design tokens（颜色、字号、间距、圆角、阴影）
- 重构关键组件：消息卡、执行时间线、设置面板、会话列表
- 增加空态、错误态、加载态统一规范
- 验收标准：
  - 主流程视觉一致、交互反馈清晰
  - 新组件可复用、可主题化

## Week 5：oi 能力对齐扩展（P0/P1）

- 按能力映射表补齐高优先级工具能力
- 技能系统引入 manifest（描述、参数 schema、权限声明）
- 增加工具调用失败的可恢复策略（重试/降级/提示）
- 验收标准：
  - P0 能力覆盖达到目标比例（建议 >= 90%）
  - 工具调用链稳定，失败可解释

## Week 6：质量与发布（P0）

- 自动化测试：
  - 后端单测（store/context/policy）
  - API 集成测试（session/message/confirm）
  - 前端 smoke（发送、流式、附件、确认）
- 发布治理：
  - 版本号、变更日志、迁移说明
  - 性能与稳定性基线报告
- 验收标准：
  - 关键路径自动化通过
  - 可进行内部试运行

## 4) 任务拆分模板（执行用）

每个任务建议固定字段：

- `目标`：要解决什么问题
- `范围`：涉及模块与接口
- `输入/输出`：数据契约与错误语义
- `验收`：可量化标准
- `回滚`：失败时如何安全回退

## 5) 当前推进（2～4 周可交付切片）

1. **文档与矩阵**：`README`、`OI_CAPABILITY_MATRIX.md`、本节 §1 与 CI 现状保持同步。
2. **评测**：`agent_eval_scenarios.json`（skills，**35** 条）与 `policy_eval_scenarios.json`（执行策略，**13** 条）持续扩展；下一批优先「多步 shell / 会话内确认」类场景。
3. **安全**：工作区写路径校验已用 `os.path.realpath` 缓解 **符号链接逃逸**（`webapi/execution_policy.py` + 单测）。
4. **质量**：安装 `fastapi`+`httpx` 后本地可跑 `tests/test_api_integration.py`；CI 已装依赖故默认执行。
5. **后续队列**：`run_skill` 超时与 JSON schema、语义检索、CHANGELOG、Playwright 最小 E2E（仍按 **第 6 节** P0→P1 排序）。

## 6) 对标成熟 CLI Agent 的差距补齐路线图（P0 / P1 / P2）

说明：本节与第 3 节六周里程碑互补——第 3 节偏「oi 对齐与工程化」，本节偏「与成熟 CLI Agent 产品形态对齐」。优先级含义同第 1 节。

### P0（必须：可度量、可控制、可排障）

| 方向 | 目标 | 落地建议 | 验收标准 |
|---|---|---|---|
| Agent 评测基线 | 有固定回归集，改代码不怕回退 | 建立 30～50 条真实任务集（含：纯对话、单步 shell、多步 shell、run_skill、联网搜索、失败重试）；每条标注期望行为（成功/拒绝/需确认） | CI 或本地一键跑完；通过率可统计；失败用例有稳定复现步骤 |
| 工具调用卫生 | 少误调用、少参数幻觉 | run_skill 入参 schema 校验；明显非法路径/空 query 前置拒绝；失败返回可解析错误码 | 随机破坏性输入不导致进程崩溃；错误信息含 request_id / 技能名 |
| 执行策略模板 | dev / readonly / prod-safe 可切换 | 将现有 policy 抽象为命名模板（环境变量或会话字段）；文档写明各模板允许的操作边界 | 同一任务在 readonly 下写盘被拦；在 dev 下可工作；切换无需改代码 |
| 最小可观测 trace | 一轮内「决策→工具→结果」可回看 | 每轮落库或日志：用户输入摘要、选用的工具/命令、stdout/stderr 摘要、耗时、是否走确认 | 任意一轮可从 UI 或 API 拉出时间序列表；与现有 executions 不冲突 |

### P1（重要：体验与鲁棒性接近「能日常干活」）

| 方向 | 目标 | 落地建议 | 验收标准 |
|---|---|---|---|
| 任务鲁棒性 | 长任务可恢复、可重试 | 对多轮执行循环增加「步骤 id」、失败重试上限、幂等写检测；可选：会话级「任务检查点」 | 模拟中途网络错误后，用户可继续同一会话完成目标且不重复破坏写 |
| 代码库理解 | 跨文件改动更靠谱 | 轻量索引：符号表 / ripgrep 封装 skill；或接入 LSP 只读查询（视投入） | 给定符号可列出定义与引用路径；大仓库下响应时间有上限（如 P95 < 3s） |
| 联网与证据 | 回答可引用、可核对 | web_search 结果与最终回答的引用格式约定；敏感查询默认走网关 + 白名单 | 用户可见「来源链接列表」；无链接时模型明确说「未检索」而非编造 |
| UI 任务视图 | 对齐「Agent 产品」心智 | 单会话内「当前任务」折叠面板：步骤条、每步状态、可展开日志 | 主对话区不被调试信息挤占；移动端可用 |

### P2（增强：平台化与多 Agent）

| 方向 | 目标 | 落地建议 | 验收标准 |
|---|---|---|---|
| 多 Agent 编排 | 规划 / 执行 / 审查分工 | 同一 session 内多角色 system 片段或子会话；审查 agent 只读工具 | 复杂任务（如「改代码 + 写测试 + 自检」）成功率高于单 Agent 基线（用本节 P0 评测集对比） |
| 权限与审计企业级 | 多人、多环境、可追责 | RBAC、审批流、导出审计包；与 executions 对齐 | 非管理员无法关闭审计；导出包含 request_id 链路与策略版本号 |
| 插件生态 | skills 可治理、可版本化 | manifest：版本、依赖、权限声明、changelog；可选签名或可信目录 | 新技能安装/升级不破坏旧会话；缺失依赖启动时明确报错 |

### 与现有文档的关系

- 能力逐项对照仍以 `OI_CAPABILITY_MATRIX.md` 为主。
- 联网检索部署与对接细节以 `SearXNG.md` 与 `web_search` skill 为准。
- 建议每完成一个 P0 子项，在评测集上跑一次并记录通过率变化，避免「感觉变强但不可测」。

### 7) 本节已在仓库内落地的实现（持续扩展）

| 路线图项 | 实现位置 |
|---|---|
| P0 评测基线（可扩展 JSON） | `tests/fixtures/agent_eval_scenarios.json`、`tests/fixtures/policy_eval_scenarios.json`、`tests/test_agent_maturity.py` |
| P0 工具调用卫生 + P2 manifest | `.omlxcli/skills/manifests/skills.json`、`webapi/skill_manifest.py`、`webapi/skill_runner.py` |
| P0 执行策略模板 | `webapi/config.py`（`OMLXCLI_EXEC_POLICY_TEMPLATE`） |
| P0 最小 trace | `session_store` 表 `agent_trace`、`GET /api/sessions/{id}/agent-trace`、SSE 事件 `agent_trace`、`webui/app.js` |
| P1 任务鲁棒（轮次上限） | `webapi/session_engine.py`（`OMLXCLI_MAX_EXEC_ROUNDS`） |
| P1 代码库理解 | `.omlxcli/skills/repo_search.py`（`repo_grep`） |
| P1 UI 任务轨迹（轻量） | 对话区执行步骤旁展示 `agent_trace` 事件（同上） |
| P2 多 Agent（轻量自检提示） | `OMLXCLI_MULTI_AGENT` 扩展 `session_engine` 控制协议 |
| P2 审计导出 | `GET /api/admin/sessions/{id}/audit-export` + `X-Admin-Token` / `OMLXCLI_ADMIN_TOKEN` |
| 第 1 节：模型 HTTP 重试/超时/回退 | `oi_runtime_core.py`（`OMLXCLI_CHAT_*`、`OMLXCLI_MODEL_FALLBACKS`） |
| 第 1 节：可选命令白名单 + workspace `realpath` | `OMLXCLI_EXEC_ALLOWLIST_RE` → `webapi/config.py`、`webapi/execution_policy.py` |
| 第 1 节：会话归档与批量 | `sessions.archived`、`GET /api/sessions?include_archived=`、`POST /api/sessions/batch-archive` |
| 第 1 节：上下文 priority / checkpoint mode | `contexts.priority`、`ResumeReq.mode` |
| 技能全集映射（.omlxcli/skills） | `OI_TOOL_MAP.json` v2 + `scripts/gen_oi_tool_map.py` + `tests/test_oi_tool_map_skills.py`；规范见 **`Skills_README.md`** |

后续可将 `agent_eval_scenarios.json` 扩至 **40～50+** 条，并增加「多步 shell / 需确认命令」等用例而不改运行器接口；`policy_eval_scenarios.json` 同理扩展边界与模板组合。

