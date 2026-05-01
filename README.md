# oMLX CLI

一个基于本地推理引擎（OpenAI-compatible API）的 Web 版 CLI 助手工作台。  
当前仓库定位为 **MVP 基线**：已具备会话、上下文、流式回复、命令执行与 skills 调用的主链路能力，可作为后续“对齐 oi CLI 全能力 Web 化”的基础工程。

## 当前定位（已校对）

- 这是一个可运行、可扩展的 Web 端原型，不是 oi CLI 的 1:1 完整镜像实现。
- 后端核心是 `webapi`（FastAPI + SQLite + session engine），前端是原生 JS/CSS 的单页应用。
- 已有“会话 + 执行 + skills + 多模态附件”的基本闭环，可承接下一阶段产品化改造（交互体验和视觉设计）。

## 已实现能力（基于代码核对）

- **会话管理**
  - 新建、切换、删除会话。
  - 标题自动生成、手动编辑与标题锁定。
  - 每会话保存独立模型/API/workspace/执行策略配置。
- **模型与流式对话**
  - 从上游 `/models` 动态拉取模型列表。
  - SSE 流式输出（delta/events）。
  - 响应完成后持久化消息与基础性能指标（ttft/tps/token estimate）。
- **执行代理能力（run_shell / run_skill）**
  - 支持执行模式开关（普通对话 vs 可执行代理）。
  - 支持 `<run_shell>` 与 `<run_skill>` 协议循环，直到 `<final_answer>`。
  - 高风险命令确认弹窗、黑名单拦截、写路径越界保护。
  - 执行审计落库（`executions`）与查询接口。
- **上下文与记忆**
  - SQLite 持久化：`sessions/messages/contexts/checkpoints/executions/context_injections`。
  - 上下文分层：`pinned` / `working` / `archived`。
  - Checkpoint 创建与恢复；长会话按轮次自动摘要存档。
  - 工作目录权威注入，降低历史路径污染风险。
  - 每轮上下文注入明细记录（来源、字符数、是否被裁剪、原因）。
- **前端交互**
  - Enter 发送 / Shift+Enter 换行。
  - Markdown 渲染 + 代码块增强。
  - 执行步骤可视化（执行中/结果）+ 执行审计/上下文注入观测面板。
  - 侧栏折叠、会话列表、附件拖拽/粘贴/选择上传（以 data_url 透传后端）。
  - 观测面板支持执行状态筛选与 stdout/stderr 展开查看。
- **可观测与错误治理**
  - 统一错误响应结构：`error_code/message/request_id`。
  - `x-request-id` 请求链路透传。
  - 后端结构化 JSON 日志（见 `LOGGING_SPEC.md`）。

## 与“oi 全能力 Web 化”目标的差距

以下能力目前尚未完整落地，建议在 README 中明确为“规划中”而非“已实现”：

1. **能力等价性**
   - 尚未声明与 oi CLI 的命令集、工具集、策略行为完全对齐（仅具备 run_shell/run_skill 主流程）。
2. **Web 助理产品化体验**
   - 视觉体系和组件规范仍处于工程样式阶段，尚未形成完整美术设计系统（Design Tokens/主题/组件标准）。
3. **Session 与上下文治理深度**
   - 当前已实现基础分层与 checkpoint，但缺少更高级策略：摘要压缩策略版本化、上下文检索排序、冲突消解、可观测分析面板等。
4. **工程化与质量保障**
   - 自动化测试、错误可观测性、发布与迁移规范尚未完备。

## 目录结构

```text
oMLXCli/
├── webapi/
│   ├── app.py
│   ├── context_manager.py
│   ├── session_store.py
│   ├── session_engine.py
│   ├── execution_policy.py
│   ├── skill_runner.py
│   └── engine_protocol.py
├── webui/
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   └── core/
│       ├── state.js
│       ├── api.js
│       ├── markdown.js
│       └── stream.js
├── oi_runtime_core.py
├── start_web.sh
└── .omlxcli/
    └── skills/
```

## 快速启动

在 `oMLXCli` 目录执行：

```bash
./bootstrap.sh
./start_web.sh
```

`start_web.sh` 会自动加载项目根目录下的 `.env` 与 `.env.local`（后者优先级更高）。

默认地址：

- [http://127.0.0.1:8788/ui/](http://127.0.0.1:8788/ui/)

## 环境变量

- `OI_MODEL`：默认模型名（例如 `Qwen3.5-35B-A3B-8bit`）
- `OI_API_BASE`：上游 OpenAI-compatible API（例如 `http://127.0.0.1:8000/v1`）
- `OI_API_KEY`：上游 API Key
- `OMLXCLI_HOST`：Web 服务监听地址（默认 `127.0.0.1`）
- `OMLXCLI_PORT`：Web 服务端口（默认 `8788`）
- `OMLXCLI_DATA_DIR`：数据目录（默认 `./.omlxcli/web`）
- `OMLXCLI_SKILLS_DIR`：skills 目录（默认 `./.omlxcli/skills`）
- `OMLXCLI_DEFAULT_WORKSPACE`：新会话默认工作目录（默认项目根目录）
- `OMLXCLI_EXEC_POLICY_MODE`：执行策略模式（`strict` / `readonly`）
- `OMLXCLI_EXEC_BLOCKLIST_RE`：黑名单命令正则（可覆盖默认）
- `OMLXCLI_EXEC_HIGH_RISK_RE`：高风险命令正则（可覆盖默认）
- `OMLXCLI_EXEC_MUTATING_RE`：写操作命令正则（可覆盖默认）
- `OMLXCLI_EXEC_ENFORCE_WORKSPACE_BOUNDARY`：是否开启写路径边界保护（默认开启）
- `OMLXCLI_SEARCH_GATEWAY_URL`：SearXNG v2 检索网关地址（如 `https://dog.lqai.cn`）
- `OMLXCLI_SEARCH_GATEWAY_USER`：网关 Basic Auth 用户名
- `OMLXCLI_SEARCH_GATEWAY_PASSWORD`：网关 Basic Auth 密码
- `OMLXCLI_SEARXNG_URL`：直连 SearXNG 基地址（gateway 不可用时的回退入口）

## 常见启动问题

- 若提示依赖缺失：先执行 `./bootstrap.sh`
- 若提示端口占用：
  - 使用新端口启动：`OMLXCLI_PORT=8790 ./start_web.sh`
  - 或先结束占用进程后重启

## Git 推送前过滤无关文件

为避免把本地临时文件、凭据或无关改动推送到远程仓库，建议按下面流程操作：

```bash
# 1) 先看工作区改动
git status

# 2) 只添加要提交的文件（不要直接 git add .）
git add README.md webapi/ webui/

# 3) 再次确认暂存区内容
git diff --cached --name-only
```

补充建议：

- 把本地敏感配置放在 `.env.local`（本项目已在 `.gitignore` 忽略）。
- 若有临时测试文件（日志、导出数据、截图），先加入 `.gitignore` 再提交。
- 推送前至少检查一次 `git status`，确保只包含本次需要的改动。

## 观测接口（新增）

- `GET /api/sessions/{session_id}/executions?limit=100`
- `GET /api/sessions/{session_id}/context-injections?limit=120`
- `GET /api/sessions/{session_id}` 返回中包含：
  - `executions`
  - `context_injections`

## 测试

运行后端测试：

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

当前已包含：
- 核心单测：`tests/test_p0_basics.py`
- API 集成测试：`tests/test_api_integration.py`

## 架构概览

- **后端**
  - `session_engine.py`：会话主编排、执行循环、协议收敛。
  - `execution_policy.py`：命令安全策略（黑名单、高风险确认、越界写保护）。
  - `context_manager.py`：上下文分层构建、预算裁剪、checkpoint 管理。
  - `session_store.py`：SQLite 持久化与迁移。
  - `skill_runner.py`：skills 注册加载与函数调用执行。
- **前端**
  - `app.js`：会话、发送、流式事件、确认弹窗、附件交互。
  - `core/*`：状态管理、HTTP API、SSE 解析、Markdown 渲染与安全处理。

## 兼容与迁移

- 兼容环境变量：`OI_MODEL` / `OI_API_BASE` / `OI_API_KEY`。
- 若 `OMLXCLI_SKILLS_DIR` 不存在，会回退读取 `.aicli/skills`（兼容旧目录）。

## 下一阶段建议（面向你的目标）

1. **能力对齐 oi CLI**
   - 梳理 oi 现有能力矩阵，建立 Web 端能力对齐清单（协议、工具、策略、错误语义）。
2. **Session/上下文体系升级**
   - 引入主流助理策略：短期窗口 + 分层记忆 + 自动摘要 + 检索召回 + 显式 pin。
   - 增加上下文调试视图（每轮实际注入内容、预算占用、裁剪原因）。
3. **交互与视觉设计**
   - 建立设计规范（颜色/间距/排版/token），统一消息、执行流、附件、设置面板体验。
4. **质量与可运维**
   - 增加测试（后端单测/API 集成/前端 smoke）。
   - 增加结构化日志、错误码与诊断面板。
5. **发布与治理**
   - 增加 `config.py` 与配置校验、版本化变更日志、迁移指南。
