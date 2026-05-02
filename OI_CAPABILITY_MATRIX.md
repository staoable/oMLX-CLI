# OI Capability Matrix（oMLX CLI Web 对齐清单）

本清单用于 Week 1 的能力盘点与排期依据，目标是把 “oi CLI 能力” 映射为 “当前 Web 端状态 + 改造任务”。

状态定义：
- `已实现`：主链路可用，可在当前仓库直接验证。
- `部分实现`：有基础能力，但缺关键治理/一致性/可观测能力。
- `未实现`：当前仓库无对应实现或仅有设计意图。

优先级定义：
- `P0`：必须优先完成，影响主流程可用性或安全性。
- `P1`：重要能力，影响产品体验与工程效率。
- `P2`：增强项，可在主流程稳定后推进。

---

## 1. 协议与代理执行能力

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 差距 / 任务 |
|---|---|---|---|---|---|
| 代理协议解析（`run_shell`/`run_skill`/`final_answer`） | 已支持标签协议解析与循环 | 已实现 | P0 | `webapi/engine_protocol.py`, `webapi/session_engine.py` | 增加协议版本号与 schema 校验 |
| 多轮执行收敛 | 支持执行后继续决策，最终收敛答复 | 已实现 | P0 | `webapi/session_engine.py` | 增加“最大执行成本”阈值（轮次/时长/命令数） |
| 命令确认协议（文本确认/弹窗确认） | 已支持确认后执行与取消 | 已实现 | P0 | `webapi/app.py`, `webui/app.js` | 补统一确认事件模型与审计记录 |
| 工作目录查询一致性 | 对“当前工作目录”有强一致兜底回答 | 已实现 | P1 | `webapi/session_engine.py`, `webapi/context_manager.py` | 增加路径变更历史与可视化 |

---

## 2. 安全策略与执行治理

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 差距 / 任务 |
|---|---|---|---|---|---|
| 高风险命令识别与确认 | 已支持环境变量配置策略正则与模式 | 已实现 | P0 | `webapi/execution_policy.py`, `webapi/config.py` | 下一步补策略热更新与管理界面 |
| 系统级危险命令阻断 | 已有黑名单阻断 | 已实现 | P0 | `webapi/execution_policy.py` | 增加规则解释与误杀白名单机制 |
| 写操作路径越界保护 | 已限制 mutating 命令越界路径；绝对路径经 `realpath` 解析防符号链接逃逸 | 已实现 | P0 | `webapi/execution_policy.py`、`tests/test_agent_maturity.py` | 复杂路径拼接与更多逃逸变体仍可加单测 |
| 执行审计（结构化） | 已落库命令/技能执行记录，并提供按 session 查询接口 | 已实现 | P0 | `webapi/session_store.py`, `webapi/session_engine.py`, `webapi/app.py` | 下一步补充审批人和更细粒度追踪字段 |
| 可配置权限模型 | 已支持 `strict/readonly` 模式与正则配置入口 | 部分实现 | P1 | `webapi/config.py`, `webapi/execution_policy.py` | 补全开发/自定义模板与会话级覆盖 |

---

## 3. 会话系统（Session）

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 差距 / 任务 |
|---|---|---|---|---|---|
| Session CRUD | 新建/查询/更新/删除齐全；支持归档与批量归档 API | 已实现 | P0 | `webapi/app.py`, `webapi/session_store.py` | 增加标签与保留策略 |
| 会话配置隔离 | 每会话独立保存模型/API/工作目录/执行开关 | 已实现 | P0 | `webapi/session_store.py` | 增加配置变更历史 |
| 标题管理 | 自动命名 + 手工编辑 + 锁定 | 已实现 | P1 | `webapi/session_engine.py`, `webui/app.js` | 增加摘要型自动标题可选策略 |
| 生命周期治理 | 已支持 `archived`、列表筛选、批量归档 API；保留策略与自动清理仍可选 | 部分实现 | P1 | `webapi/session_store.py`, `webapi/app.py` | 增加标签、按策略清理旧会话、保留天数配置 |

---

## 4. 上下文系统（Context / Memory）

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 差距 / 任务 |
|---|---|---|---|---|---|
| 分层上下文（Pinned/Working/Archived） | 已支持落库与注入；`contexts.priority` 控制排序 | 已实现 | P0 | `webapi/context_manager.py`, `webapi/session_store.py` | 语义冲突消解仍可选 |
| Checkpoint 创建与恢复 | 已支持创建与恢复；`resume` 支持 append/replace | 已实现 | P0 | `webapi/context_manager.py`, `webapi/app.py` | 可扩展 pinned 恢复策略 |
| 自动摘要归档 | 预算比例 + 消息节流触发 checkpoint（环境变量可配） | 已实现 | P0 | `webapi/session_engine.py` | 可接入 tokenizer 级预算 |
| 上下文预算与裁剪解释 | 已记录每轮上下文注入来源、体积与裁剪事件 | 已实现 | P0 | `webapi/context_manager.py`, `webapi/session_store.py`, `webapi/app.py` | 下一步增加前端可视化面板 |
| 语义检索召回 | 当前无专门检索层 | 未实现 | P1 | - | 引入检索召回和打分排序 |

---

## 5. 模型接入与推理层

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 差距 / 任务 |
|---|---|---|---|---|---|
| OpenAI-compatible 对话接口 | 已支持 stream/non-stream；可配置重试/超时与模型回退链 | 已实现 | P0 | `oi_runtime_core.py` | 熔断与配额治理仍可选 |
| 模型列表发现 | 已代理 `/models` | 已实现 | P0 | `webapi/app.py`, `webui/app.js` | 增加缓存与异常降级文案 |
| 上游连通性探测 | 已有 API base 候选探测函数 | 部分实现 | P1 | `oi_runtime_core.py` | 在 Web 启动/会话保存阶段接入探测结果 |
| 上下文窗口自动估算 | 已按内存估算 context window | 部分实现 | P2 | `oi_runtime_core.py` | 改为模型级动态配置 |

---

## 6. Skills / 工具能力映射

开发与部署约定见仓库根目录 **`Skills_README.md`**。

当前已加载的本地 skills 能力（来自 `.omlxcli/skills`）：

- 文本与文件：`files_search`, `files_read_chunk`, `note_save`, `note_load`, `note_list`
- 多模态：`vision_describe`, `vision_compare`, `video_summarize`, `audio_transcribe`, `audio_transcribe_only`, `pdf_read`, `pdf_ocr`, `pdf_to_text`, `pdf_search`
- 生活工具：`weather_now`, `weather_forecast`, `date_now`

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 差距 / 任务 |
|---|---|---|---|---|---|
| Skills 自动注册与注入 | 已支持目录扫描、注册、调用 | 已实现 | P0 | `.omlxcli/skills/_registry.py`, `webapi/skill_runner.py` | 增加加载失败报告与健康检查 |
| `run_skill` 执行沙箱 | 仅 AST 基础限制 | 部分实现 | P0 | `webapi/skill_runner.py` | 增加参数 schema 校验与执行超时隔离 |
| 技能元数据治理 | 仅描述 + 示例 | 部分实现 | P1 | `.omlxcli/skills/_meta.py` | 增加 manifest（权限、输入输出、版本） |
| 与 oi 工具全集对齐 | **全集定义**：`.omlxcli/skills`（以 `manifests/skills.json` 为准）；`OI_TOOL_MAP.json` 的 `skills[]` 由 `scripts/gen_oi_tool_map.py` 生成并由单测校验 | 已实现 | P0 | `scripts/gen_oi_tool_map.py`, `tests/test_oi_tool_map_skills.py` | 新增技能：manifest → `--write` 生成映射 → 评测/文档按需 |

---

## 7. Web 交互与设计体验

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 差距 / 任务 |
|---|---|---|---|---|---|
| 基础聊天体验 | 会话侧栏、流式消息、Markdown | 已实现 | P0 | `webui/index.html`, `webui/app.js` | 增加长消息性能优化 |
| 执行过程可视化 | 已展示执行步骤、观测面板；流式区内可折叠「执行时间线」与 `agent_trace` | 部分实现 | P1 | `webui/app.js`, `webui/index.html` | 侧栏 timeline、失败重试入口 |
| 附件交互 | 支持拖拽/粘贴/选择上传 | 已实现 | P1 | `webui/app.js` | 增加附件预览与失败重传 |
| 视觉设计体系 | 工程样式为主；`:root` 已含间距/圆角等变量及 timeline 专用 token | 部分实现 | P1 | `webui/styles.css` | 统一组件级 tokens 与主题切换 |
| 可访问性与易用性 | 基础 ARIA 有覆盖 | 部分实现 | P2 | `webui/index.html` | 增加键盘导航与焦点管理规范 |

---

## 8. 可观测性、测试与发布

| 能力 | 现状 | 状态 | 优先级 | 证据模块 | 差距 / 任务 |
|---|---|---|---|---|---|
| 结构化日志 | 已实现 JSON 事件日志（含 `event_type/request_id/session_id` 主链路） | 已实现 | P0 | `webapi/app.py`, `webapi/session_engine.py`, `webapi/logging_utils.py` | 下一步补 SSE 细粒度事件和脱敏策略 |
| 错误码体系 | 已统一异常响应结构（`error_code/message/request_id`） | 已实现 | P0 | `webapi/app.py` | 下一步细化业务错误码字典 |
| 自动化测试 | 后端单测 + `policy_eval`/`agent_eval`；CI 含 Playwright `/ui/` 冒烟、`smoke_http`；`requirements.txt` 统一依赖 | 部分实现 | P0 | `tests/test_e2e_playwright_ui.py`、`.github/workflows/ci.yml` | 扩展 E2E 覆盖（发消息、确认流）仍可选 |
| 发布规范 | 暂无版本与变更流程文档 | 未实现 | P1 | - | 增加 release checklist 与迁移说明 |

---

## 9. P0 执行清单（滚动维护）

1. 建立能力映射跟踪表（本文件作为基线，后续逐项标注 owner/截止时间）。
2. （已完成）执行审计 `executions` 与按 session 查询 API。
3. （已完成）执行策略配置化（黑名单、高风险、工作区约束、模板与白名单）。
4. （已完成）上下文注入明细（来源、体积、裁剪原因）。
5. （已完成）统一错误响应（`error_code`, `message`, `request_id`）。
6. （已完成）后端单测骨架 + **CI**（`unittest`、`gen_oi_tool_map --check`、`scripts/smoke_http.py`）+ **评测 JSON**（`agent_eval_scenarios`、`policy_eval_scenarios`，含 `__CWD__` 占位）。
7. （已完成）工作区写路径 **`realpath`** 与符号链接逃逸单测。
8. （进行中）Playwright/前端 E2E、错误码字典与脱敏、CHANGELOG。

## 10. 维护方式

- 每完成一项能力，将对应行 `状态` 更新为最新值，并附 PR/提交链接。
- 每周评审一次：新增能力、风险、延期项、优先级调整。
- 与 `IMPLEMENTATION_PLAN.md` 联动维护：矩阵负责“能力全景”，计划负责“节奏和验收”。

