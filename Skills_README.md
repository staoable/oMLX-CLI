# Skills_README：Skills 管理与开发部署说明

> 本文档为仓库内 **Skills 工程** 的权威说明（文件名 **`Skills_README.md`**）。与 **`README.md`**、**`README_cn.md` / `README_en.md`**、**`OI_CAPABILITY_MATRIX.md`**、**`OI_TOOL_MAP.json`**、**`docs/API.md`**（HTTP 契约）互补：首页与双语 README 偏整体产品与上手，本文偏 **开发、注册、生成映射与部署**。

---

## 1. 概念与范围

- **技能全集**：本仓库约定 **全集 = `.omlxcli/skills`**（以 **`manifests/skills.json`** 的 **`skills`** 键为权威清单）。
- **调用路径**：Web 会话引擎通过 `<run_skill>函数调用表达式</run_skill>` 调用；服务端由 **`webapi/skill_runner.py`** 加载注册表并执行。
- **与上游 oi CLI**：不保证与 oi 二进制工具逐项同名同行为；对齐范围以本目录 + manifest 为准。

---

## 2. 当前技能一览（manifest 权威）

以下路径相对于仓库根目录下的 **`.omlxcli/skills/`**（若使用 `OMLXCLI_SKILLS_DIR`，则为该目录下同名相对路径）。**功能简述**来自各模块 `@skill(desc=…)`。

| 技能名（函数名） | 功能简述 | 源码路径 |
|------------------|----------|----------|
| `audio_transcribe` | 音频转写 + 基于转写由 LLM 回答 | `.omlxcli/skills/audio.py` |
| `audio_transcribe_only` | 仅音频转写为文字，不调 LLM | `.omlxcli/skills/audio.py` |
| `claude_job_start` | 启动 Claude Code 后台任务（同会话串行队列，支持 `queued`） | `.omlxcli/skills/claude_job_skill.py` |
| `claude_job_status` | 查询 Claude Job 状态（`queued/running/completed/failed/cancelled`） | `.omlxcli/skills/claude_job_skill.py` |
| `claude_job_logs` | 读取 Claude Job 日志 tail（最多 5000 行） | `.omlxcli/skills/claude_job_skill.py` |
| `claude_job_cancel` | 取消 Claude Job（支持取消 `running` 与 `queued`） | `.omlxcli/skills/claude_job_skill.py` |
| `date_now` | 返回本机当前日期、时间、星期、时区等 | `.omlxcli/skills/clock.py` |
| `csv_tsv_summary` | CSV/TSV 列名、行数、抽样行与数值列 min/max/mean | `.omlxcli/skills/spreadsheet.py` |
| `xlsx_sample` | xlsx/xlsm 只读抽样（openpyxl read_only） | `.omlxcli/skills/spreadsheet.py` |
| `structured_pick` | 本地 JSON/YAML 点路径取值（`yaml.safe_load`） | `.omlxcli/skills/structured_data.py` |
| `git_snapshot` | 仓库内只读 `git log` / `diff` / `show` | `.omlxcli/skills/git_readonly.py` |
| `docx_to_text` | .docx 段落与表格抽纯文本 | `.omlxcli/skills/docx_read.py` |
| `files_read_chunk` | 按行范围读取文件分块（大文件友好） | `.omlxcli/skills/files.py` |
| `files_search` | 按文件名或内容搜索，返回绝对路径列表 | `.omlxcli/skills/files.py` |
| `note_list` | 列出笔记目录下文件名 | `.omlxcli/skills/notes.py` |
| `note_load` | 读取指定笔记全文 | `.omlxcli/skills/notes.py` |
| `note_save` | 保存笔记（同名覆盖） | `.omlxcli/skills/notes.py` |
| `pdf_meta` | 读取 PDF 元信息（页数、标题、作者等） | `.omlxcli/skills/pdf.py` |
| `pdf_ocr` | 对 PDF 强制 OCR | `.omlxcli/skills/pdf.py` |
| `pdf_read` | 一站式读 PDF（文字层 / 自动或强制 OCR） | `.omlxcli/skills/pdf.py` |
| `pdf_search` | 在 PDF 文字层中搜索关键词并返回页码与上下文 | `.omlxcli/skills/pdf.py` |
| `pdf_to_text` | 仅提取 PDF 文字层、不 OCR | `.omlxcli/skills/pdf.py` |
| `repo_grep` | 目录内 ripgrep/回退扫描，返回匹配文件路径列表 | `.omlxcli/skills/repo_search.py` |
| `stock_quote` | A 股多只股票实时行情（最新价/涨跌幅/开盘价） | `.omlxcli/skills/stock_market.py` |
| `stock_hot_list` | A 股热股榜/飙升榜（东方财富） | `.omlxcli/skills/stock_market.py` |
| `stock_unusual` | A 股盘口异动（东方财富） | `.omlxcli/skills/stock_market.py` |
| `stock_search` | A 股代码/名称检索（东方财富） | `.omlxcli/skills/stock_market.py` |
| `stock_brief` | A 股单票聚合视图（行情+热榜+异动） | `.omlxcli/skills/stock_market.py` |
| `stock_kline` | 股票/指数/基金历史 K 线（分钟/日周月） | `.omlxcli/skills/stock_market.py` |
| `stock_history_trades` | 当日分时成交明细（最近 N 笔） | `.omlxcli/skills/stock_market.py` |
| `stock_kline_summary` | 历史 K 线统计摘要（涨跌/振幅/均线趋势） | `.omlxcli/skills/stock_market.py` |
| `video_summarize` | 抽关键帧与音轨转写后送 LLM 做视频摘要 | `.omlxcli/skills/video.py` |
| `vision_compare` | 多图对比/汇总（多模态模型） | `.omlxcli/skills/vision.py` |
| `vision_describe` | 单图描述或问答（多模态模型） | `.omlxcli/skills/vision.py` |
| `weather_forecast` | 未来若干天天气预报 | `.omlxcli/skills/weather.py` |
| `weather_now` | 当前天气查询 | `.omlxcli/skills/weather.py` |
| `web_read` | 读取单个网页正文（轻清洗） | `.omlxcli/skills/web_search.py` |
| `web_search` | 联网搜索（网关 / SearXNG 等，带白名单与排序） | `.omlxcli/skills/web_search.py` |

未列入上表且以下划线开头的文件（如 `_meta.py`、`_registry.py`、`_media.py` 等）为**内部模块**，不单独作为对外技能名。

---

## 3. 目录与环境变量

| 项目 | 说明 |
|------|------|
| 默认目录 | `<repo>/.omlxcli/skills/` |
| 自定义目录 | 环境变量 **`OMLXCLI_SKILLS_DIR`**（目录须存在且含 **`manifests/skills.json`**） |
| 技能目录 | 固定使用 **`.omlxcli/skills`**（见 `webapi/skill_runner.resolve_skills_dir`） |
| run_skill 超时 | **`OMLXCLI_RUN_SKILL_TIMEOUT_SEC`**（秒，`0` 表示不限制；默认 `120`），见 `webapi/skill_runner.py` |
| 全量环境变量说明 | 仓库根 **`.env.example`**（逐项中文注释；Web 模型上游在 SQLite，不在此配 Base/Key）；可复制为 **`.env.local`**，`webapi/app.py` 启动时自动加载 |
| 表格与 Office skills | **`requirements.txt`** 含 **openpyxl**、**python-docx**、**PyYAML**（CI/bootstrap 安装）；缺包时对应 skill 会抛出可读的 `RuntimeError` |
| Web 下需 LLM 的技能 | **`webapi/session_engine._skill_llm_env`** 在 `run_skill` 前注入 **`_AICLI_API_BASE`**、**`_AICLI_API_KEY`**、**`_AICLI_LLM_MODEL`**（与会话当前供应商（模型设置）一致）；技能内应读 `_AICLI_*`，勿依赖进程级 `OI_API_*` |

部署时在 `.env` / `.env.local` / systemd / K8s 等环境中设置变量；本地推荐维护 **`.env.local`**（已 `.gitignore`）。

CI 与本地全量测试包含 **Playwright** 对 `/ui/` 的静态冒烟（见 `tests/test_e2e_playwright_ui.py`）；首次本地跑前需执行 `python -m playwright install chromium`（`bootstrap.sh` 结束时会提示）。

---

## 4. 文件与命名约定

1. **可扫描文件**：`skills_dir` 下所有 **非 `_` 开头** 的 `*.py` 由 **`_registry.register_all()`** 加载；**`_meta.py`、`_registry.py`** 等以下划线开头的文件 **会被跳过**。
2. **模块内**：`from _meta import skill`，用 **`@skill(desc=..., examples=[...])`** 装饰要暴露给模型的 **顶层函数**。
3. **函数名 = 工具名**：模型写 `date_now()` 等形式；注册使用 **`func_name`**，并挂到 **`builtins`**。

加载失败时打印 **`[skills] 加载 <模块名> 失败: ...`**，不导致整个 Web 进程退出。

---

## 5. `run_skill` 调用约束（必须遵守）

`webapi/skill_manifest.validate_skill_ast_call` 规则摘要：

- 仅 **直接函数名调用**：`foo(1, b=2)`；不支持 `pkg.foo()`、非调用表达式。
- **禁止 `*args` / `**kwargs` 展开**。
- manifest 中若配置了 **`min_positional_args`**、**`max_total_args`**，则校验位置参数个数与参数总数。

**设计建议**：显式参数 + 默认值；可选配置用多个具名参数或小 `dict` 参数（勿用 `**kwargs`）。

---

## 6. 返回值与副作用

- 返回值为 **`dict` / `list`** 时经 **`json.dumps`** 进入输出；否则 **`str()`**。避免不可 JSON 序列化对象。
- **`permissions`**（如 `filesystem_read`、`network`）写在 manifest 中，用于文档与后续策略；**不自动**替代代码内访问控制。

---

## 7. 配置进系统（Checklist）

| 步骤 | 动作 |
|------|------|
| 1 | 在 **`.omlxcli/skills/`** 增加或修改 **`*.py`**（非 `_` 前缀），实现带 **`@skill`** 的顶层函数。 |
| 2 | 在 **`manifests/skills.json`** 的 **`skills`** 中增加与 **函数同名** 的条目（`version`、`permissions`、`min_positional_args`、`max_total_args` 等）。 |
| 3 | 在仓库根执行 **`python3 scripts/gen_oi_tool_map.py --write`**，自动生成 **`OI_TOOL_MAP.json`** 的 **`skills[]`**（含 **`source_file`**）。**请勿手改 `skills` 数组**。 |
| 4 | 校验： **`python3 scripts/gen_oi_tool_map.py --check`** 或 **`python3 -m unittest tests.test_oi_tool_map_skills -v`**。 |
| 5 | （可选）在 **`tests/fixtures/agent_eval_scenarios.json`** 增加评测用例；合并前 **`python3 -m unittest discover -s tests -p "test_*.py"`**。 |
| 6 | 更新本节 **§2 技能一览表**（名称、简述、路径与 manifest 一致）。 |

无需为「注册进工具表」改 **`webapi/session_engine.py`** 白名单：模块加载成功即可进入注册表。若技能需 Web 会话中的上游 LLM，由 **`_skill_llm_env`** 统一注入 **`_AICLI_*`**，一般也不用手改白名单。

---

## 8. `scripts/gen_oi_tool_map.py`（映射生成）

根据 **manifest 键名** + 源码 AST（各 `*.py` 中带 `@skill` 的顶层函数）生成 **`OI_TOOL_MAP.json`** 中的 **`skills[]`**；若同一技能名出现在两个源文件中，脚本 **报错退出**。

| 命令 | 作用 |
|------|------|
| **`python3 scripts/gen_oi_tool_map.py --write`** | 写回仓库根 **`OI_TOOL_MAP.json`**（含 `runtime_protocol` 固定块） |
| **`python3 scripts/gen_oi_tool_map.py --check`** | 仅校验磁盘上的 **`skills[]`** 与生成结果一致（适合 CI） |

单测 **`tests/test_oi_tool_map_skills.OiToolMapSkillsTest.test_gen_oi_tool_map_script_check_mode`** 会子进程执行 **`--check`**，防止漏跑脚本。

### 8.1 一次性跑全技能（冒烟）

仓库根执行 **`python3 scripts/smoke_all_skills.py`**（或 **`.venv/bin/python scripts/smoke_all_skills.py`**）：按 manifest 对每个技能尝试最小 `run_skill` 调用，输出 **OK / SKIP / FAIL**。仅有 **FAIL** 时进程退出码为 **1**；**SKIP** 表示缺样例/缺依赖/未开外网等（**不算失败**）。

**建议在 `.env` / `.env.local` 配置的变量（完整说明见仓库根 `.env.example`「九·1」）：**

| 变量 | 作用 |
|------|------|
| **`OMLXCLI_SMOKE_NETWORK=1`** | 打开 **weather_***、**web_read** 等外网冒烟分支。 |
| **`OMLXCLI_SMOKE_STOCK=1`** | 打开 **stock_*** 冒烟分支（默认关闭，避免东财风控导致误报）。 |
| **`OMLXCLI_SMOKE_PDF_PATH`** 等 | **`OMLXCLI_SMOKE_IMAGE_PATH`**、**`OMLXCLI_SMOKE_AUDIO_PATH`**、**`OMLXCLI_SMOKE_VIDEO_PATH`**：本机样例**绝对路径**；不设则对应技能 **SKIP**。 |
| **`OMLXCLI_SEARCH_GATEWAY_*` / `OMLXCLI_SEARXNG_URL`** | **web_search** 需要（见 **`.env.example` 第五节**）；与 **`OMLXCLI_SMOKE_NETWORK=1`** 同开。 |
| **`OMLXCLI_EVAL_SKIP_HTTP`** | 测 **web_read** 时请**勿**设为 `1/true`（否则脚本 **SKIP**）；与 CI 单测跳过外网语义一致。 |
| **`_AICLI_API_BASE`**（及 **`_AICLI_API_KEY`**、**`_AICLI_LLM_MODEL`**） | **vision_***、**audio_transcribe**（非 `audio_transcribe_only`）、**video_summarize** 依赖 LLM；与 Web 会话注入同名，见 **`.env.example`「十」**。不设时冒烟 **SKIP**。 |

**无需为冒烟单独配置路径变量**（没有 `OMLXCLI_SMOKE_XLSX_PATH` 之类）：**`csv_tsv_summary`** 与 **`xlsx_sample`** 由脚本在 **`.omlxcli/`** 下写入 **`_smoke_sample.csv`** / **`_smoke_sample.xlsx`**（xlsx 依赖 **openpyxl**）；**`docx_to_text`** 写入 **`_smoke_sample.docx`**（依赖 **python-docx**）；**`structured_pick`** 读仓库根 **`OI_TOOL_MAP.json`**（可先 **`python3 scripts/gen_oi_tool_map.py --write`**）；**`git_snapshot`** 对当前仓库根做只读 **`git log`**。缺 **openpyxl / python-docx** 或缺 **`OI_TOOL_MAP.json`** 时对应行为 **SKIP**（非 FAIL）。

**音频 / 视频转写**依赖 **`mlx-whisper`**：Apple Silicon 上 **`./bootstrap.sh`** 后用 **`.venv/bin/python`** 跑本脚本；否则 **audio_*** / **video_summarize** 可能 **SKIP** 或缺包报错。

**传入环境变量的两种方式（二选一即可）：**

1. **写入 `.env.local`**（推荐）：脚本会调用与 Web 相同的 **`load_dotenv_files`** 加载 `.env` / `.env.local`。
2. **在终端里 `export`**：仅写 `VAR=value` **不会**传给 `python3` 子进程，必须 **`export VAR=value`**。

**zsh 注意**：`unset` 与行内 `#` 注释偶发解析问题，请把注释单独成行，例如：

```bash
unset OMLXCLI_EVAL_SKIP_HTTP
export OMLXCLI_SMOKE_NETWORK=1
python3 scripts/smoke_all_skills.py
```

---

## 9. 本地开发与热加载

- **Web**：`load_skills_registry()` 会再次执行 `register_all`；一般 **保存 `.py` 后下一轮对话** 即加载新版本；异常时 **重启 Web 进程**。
- **本地调试**：`from webapi.skill_runner import load_skills_registry, run_skill_call`，构造 `funcs` 后调用 `run_skill_call("your_skill(...)", funcs)`。

---

## 10. 部署注意事项

1. **系统依赖**：`rg`、`ffmpeg`、PDF 库等需在运行环境预装。
2. **路径与安全**：shell 仍受 **`execution_policy`** 与会话 **workspace** 约束；skill 内路径建议基于 **`workspace_path`** 或绝对路径。
3. **只读挂载**：`OMLXCLI_SKILLS_DIR` 只读时不要向该目录写缓存；缓存用 **`TMPDIR`** 或会话目录。

---

## 11. 相关文件索引

| 路径 | 作用 |
|------|------|
| **`Skills_README.md`** | 本文（Skills 规范 + 技能一览） |
| `.omlxcli/skills/_meta.py` | `@skill` 与 `_REGISTRY` |
| `.omlxcli/skills/_registry.py` | 扫描加载、`render_tools_md` |
| `.omlxcli/skills/manifests/skills.json` | 权威技能清单与参数边界 |
| **`OI_TOOL_MAP.json`** | v2 映射；**`skills[]` 仅由脚本生成** |
| **`scripts/gen_oi_tool_map.py`** | `--write` / `--check` |
| `webapi/skill_runner.py` | 目录解析、注册表、`run_skill_call` |
| `webapi/skill_manifest.py` | manifest 加载、AST 校验 |
| **`tests/test_oi_tool_map_skills.py`** | manifest ↔ 映射 ↔ 源码一致性 + `--check` |

---

## 12. 维护约定

- 与 **`OI_CAPABILITY_MATRIX.md`**、**`docs/API.md`**（若技能影响对外行为）联动更新。
- **新增技能**：**源码 + manifest** → **`gen_oi_tool_map.py --write`**；否则单测 / **`--check`** 失败。

变更本规范时，在本节追加 **日期与摘要** 即可。
