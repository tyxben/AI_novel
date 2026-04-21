# AI 创意工坊

## 项目概述
AI 驱动的一站式内容创作平台：短视频自动制作 + AI 长篇小说创作。
支持三种使用方式：CLI 命令行 / Next.js Web UI / MCP Server（AI 助手调用）。

## 技术栈
- Python 3.10+ / Click CLI / Next.js + FastAPI / FastMCP Server
- edge-tts (微软免费TTS)
- 多 LLM 后端: OpenAI / DeepSeek / Gemini(免费) / Ollama(本地) — 统一接口 `src/llm/`
- 图片生成: SiliconFlow(免费) / 阿里云万相 / Together.ai / diffusers(本地SD) — 统一接口 `src/imagegen/`
- AI视频片段: 可灵(Kling) / 即梦(Seedance) / MiniMax(海螺) / OpenAI Sora — 统一接口 `src/videogen/`
- FFmpeg (视频合成)
- FastAPI + SQLite (任务队列)

## 项目结构
- `main.py` - CLI 入口 (click)
- `frontend/` - Next.js Web UI (port 3000)
- `src/api/app.py` - FastAPI 后端 (port 8000)
- `mcp_server.py` - MCP Server (FastMCP streamable-http + stdio)
- `src/pipeline.py` - 经典流水线调度器，编排5个阶段
- `src/agent_pipeline.py` - Agent 模式入口，LangGraph StateGraph 编排
- `src/director_pipeline.py` - AI 导演模式流水线（灵感→视频）
- `src/config_manager.py` - YAML 配置加载/验证
- `src/checkpoint.py` - 断点续传 (JSON)
- `src/logger.py` - Rich 日志
- `src/llm/` - LLM 统一抽象层 (OpenAI/DeepSeek/Gemini/Ollama)
- `src/segmenter/` - 文本分段 (simple规则 / LLM智能)
- `src/promptgen/` - 小说文本→图片/视频prompt生成
- `src/imagegen/` - 图片生成 (SiliconFlow / 阿里云万相 / Together.ai / diffusers本地)
- `src/videogen/` - AI视频片段生成 (可灵Kling / 即梦Seedance / MiniMax海螺 / OpenAI Sora)
- `src/tts/` - edge-tts 配音 + SRT字幕
- `src/video/` - FFmpeg 视频合成 (静态图Ken Burns特效 / AI视频片段拼接)
- `src/scriptplan/` - AI 导演脚本规划 (灵感→概念→分段脚本→素材策略)
- `src/task_queue/` - 后台任务队列 (FastAPI + SQLite + Worker)
- `src/novel/quality/` - Phase 5 质量评估 (7 维度 / LLM-as-judge / A/B 对比 / Rich Table + markdown 报告)
- `scripts/quality_regression.py` - 跨体裁回归（5 体裁 × 3 章 + 7 维评估）
- `scripts/quality_ab_phase3_vs_phase4.py` - A/B 对比（git worktree 隔离老 commit 代码）
- `scripts/quality_ab_debias.py` - A/B 反向对照（消除 LLM judge position bias）

## 常用命令
```bash
# 安装
pip install -e '.[web,cloud-image,gemini]'  # 推荐：Web UI + 云端生图 + Gemini
pip install -e '.[all]'                      # 全部安装

# Web UI 启动
cd frontend && npm run dev    # Next.js 前端 (port 3000)
python -m src.api.app         # FastAPI 后端 (port 8000)

# 视频制作 - 经典模式
python main.py run input/novel.txt
python main.py run input/novel.txt --resume  # 断点续传

# 视频制作 - Agent 模式
python main.py run input/novel.txt --mode agent
python main.py run input/novel.txt --mode agent --budget-mode

# 视频制作 - 导演模式
python main.py create-video "一句灵感"

# 小说创作 - 一步到位（快速模式，内部走 propose + auto-accept）
python main.py novel write --genre 玄幻 --theme "少年修炼逆天改命" --target-words 100000
python main.py novel resume workspace/novels/novel_xxx
python main.py novel export workspace/novels/novel_xxx
python main.py novel status workspace/novels/novel_xxx

# 小说创作 - Phase 4 三段式（propose / accept / regenerate）
python main.py novel propose project-setup "一句灵感"
python main.py novel propose synopsis <project_path>
python main.py novel propose main-outline <project_path>
python main.py novel propose characters <project_path>
python main.py novel propose world-setting <project_path>
python main.py novel propose story-arcs <project_path>
python main.py novel propose volume-breakdown <project_path>
python main.py novel propose volume-outline <project_path> --volume 1
python main.py novel propose chapter-brief <project_path> --chapter 5
python main.py novel accept <project_path> --proposal-file proposal.json
python main.py novel regenerate <project_path> --section synopsis --hints "主角换成女性"

# Phase 5 质量评估
python scripts/quality_regression.py                     # 全量 5 体裁 × 3 章
python scripts/quality_regression.py --genres xuanhuan --chapters 2
python scripts/quality_ab_phase3_vs_phase4.py            # A/B 对比
python scripts/quality_ab_debias.py                      # A/B 反向对照（必跑）

# 仅分段 / 查看进度
python main.py segment input/novel.txt
python main.py status workspace/novel/
```

## 配置
全局配置在 `config.yaml`，可通过 `--config` 指定自定义配置。
- `llm.provider` 默认 `auto`，按优先级检测: GEMINI_API_KEY → DEEPSEEK_API_KEY → OPENAI_API_KEY → Ollama
- `imagegen.backend` 支持 `siliconflow`(免费) / `dashscope` / `together` / `diffusers`(本地)
- `imagegen.device` 默认 `auto`，自动检测: CUDA > MPS > CPU
- `videogen.backend` 支持 `kling` / `seedance` / `minimax` / `sora`（可选，不配置则用静态图模式）

## Agent 模式 (LangGraph)
- `src/agents/` - 5个 Agent: Director / ContentAnalyzer / ArtDirector / VoiceDirector / Editor
- `src/tools/` - Tool 层封装现有模块（SegmentTool, PromptGenTool, ImageGenTool, TTSTool, VideoAssembleTool, EvaluateQualityTool）
- `src/agent_pipeline.py` - Agent 模式入口，LangGraph StateGraph 编排
- `src/agents/graph.py` - 图构建 + 断点续传 wrapper
- `src/agents/state.py` - AgentState TypedDict，decisions/errors/completed_nodes 用 `Annotated[list, operator.add]` reducer
- `src/agents/utils.py` - `make_decision()` 创建决策记录，`extract_json_obj/array` 稳健 JSON 提取
- 规划文档在 `specs/langgraph-multi-agent/`（requirements.md / design.md / tasks.md）

```bash
# Agent 模式
python main.py run input/novel.txt --mode agent

# Agent + 省钱模式
python main.py run input/novel.txt --mode agent --budget-mode

# Agent + 自定义质量阈值
python main.py run input/novel.txt --mode agent --quality-threshold 7.0

# Agent + 断点续传
python main.py run input/novel.txt --mode agent --resume
```

## AI 长篇小说写作模块 (src/novel/)

架构重构 2026（Phase 0-5 完工）后的状态。旧 9 Agent 架构已废弃，方案文档在
`specs/architecture-rework-2026/`（README / AUDIT / DESIGN / MODULE_USAGE /
PHASE4 / PHASE5）。

- `src/novel/agents/` - 5 个 Agent（见下）
- `src/novel/tools/` - Tool 层: ConsistencyTool / QualityCheckTool / StyleAnalysisTool / BM25Retriever(fallback) / ChapterDigest
- `src/novel/services/` - 服务层: BriefAssembler(brief 聚合) / LedgerStore(账本 facade) / ObligationTracker / ForeshadowingService / CharacterArcTracker / MilestoneTracker / EntityService / StyleProfileService / VolumeSettlement / AgentChat / NovelToolFacade(三段式入口)
- `src/novel/quality/` - Phase 5 质量评估: dimensions / judge / ab_compare / report
- `src/novel/models/` - Pydantic 数据模型: Novel / Volume / Chapter / Character / World / Feedback 等
- `src/novel/storage/` - 存储层: NovelMemory(SQLite+NetworkX+Chroma) / FileManager
- `src/novel/templates/` - 模板预设: 大纲模板 / 风格预设 / 节奏模板 / AI 味观察清单（分体裁，不做全局黑名单）
- `src/novel/pipeline.py` - 小说创作流水线（创建项目 / 生成章节 / 应用反馈）
- `src/novel/config.py` - 小说模块配置 (NovelConfig)
- `src/novel/agents/graph.py` - LangGraph chapter graph + sequential fallback
- `src/novel/agents/state.py` - NovelState TypedDict
- 旧规划文档 `specs/novel-writing/`（requirements.md / design.md / tasks.md）作为历史参考

### 5 Agent 架构（替代旧 9 Agent）
- **ProjectArchitect** (`project_architect.py`) - 项目骨架：`propose_project_setup` / `propose_synopsis` / `propose_main_outline` / `propose_main_characters` / `propose_world_setting` / `propose_story_arcs` / `propose_volume_breakdown` / `regenerate_section`
- **VolumeDirector** (`volume_director.py`) - 单卷细纲：`propose_volume_outline(hints=...)` / `settle_volume`
- **ChapterPlanner** (`chapter_planner.py`) - 单章 brief：`propose_chapter_brief`，消费 `LedgerStore.snapshot_for_chapter()` 实时快照
- **Writer** (`writer.py`) - 正文生成：one-shot + ReAct 双模式；**不再自 critique**
- **Reviewer** (`reviewer.py`) - 审稿单一入口：3 维度（quality / consistency / style）联合报告。**不再拆 QualityReviewer + ConsistencyChecker + StyleKeeper 三 Agent**；消费 `LedgerStore + StyleProfile`，**只标问题不打分**

### Agent 编排
- **初始化阶段**：`NovelPipeline.create_novel()` 直接调 `ProjectArchitect` 的一组 propose_* 方法（synopsis → main_outline → main_characters → world_setting → story_arcs），不走 LangGraph
- **章节生成图** (4 节点)：`chapter_planner → writer → reviewer → state_writeback → END`
  - `chapter_planner` 是 Phase 2-δ 合并产物（取代 dynamic_outline + plot_planner + hook_generator）
  - `reviewer` 是 Phase 2-β 合并产物（取代 ConsistencyChecker + StyleKeeper + QualityReviewer 三 Agent），**零打分、零自动重写**，只写 `state["current_chapter_quality"]`
  - 并行执行已取消，Reviewer 串行产单一 `CritiqueResult`
- **反馈重写**：作者读 Reviewer 报告后主动调 `apply_feedback` / `rewrite_chapter` 工具。无自动重写循环
- Writer 的 feedback_prompt 在 one-shot 和 ReAct 两条路径都注入
- LangGraph 为可选依赖，未安装时 fallback 为顺序执行（单 pass 无重写循环）

### 省 Token 策略
- 每章执行轻量级向量一致性检查（Chroma 语义检索 + 规则矛盾检测），BM25 作为 fallback
- 深度一致性交给 Reviewer 单节点消费 `LedgerStore + StyleProfile`（Phase 2-β 合并后不再每 9 章独立 LLM 裁决）
- Reviewer **只产报告不打分**；定量打分统一放到 Phase 5 `src/novel/quality/`（详见下文）
- 章节摘要（`ChapterDigest`）仅用于向量索引和 brief 压缩；不再作为 LLM 打分输入
- 每章目标 2000-3000 字，Writer 用 max_tokens + 硬截断控制。DeepSeek 实测 1.5-1.6x 超目标

### 叙事状态管理
- **BriefAssembler** (`src/novel/services/brief_assembler.py`): Ledger-first 的 continuity context 聚合器，是 `ContinuityService` 的继承替代（ContinuityService 保留为兼容 shim，新代码一律用 BriefAssembler）。由 `ChapterPlanner.propose_chapter_brief` 实时调用
- **LedgerStore** (`src/novel/services/ledger_store.py`): 统一包装 ObligationTracker / ForeshadowingService / CharacterArcTracker / MilestoneTracker / EntityService 的 facade；`snapshot_for_chapter(N)` 返回当章 brief 需要的所有账本数据
- **角色状态快照**：每章生成后自动提取角色位置/状态/情感到 StructuredDB，供后续 brief 查询
- **向量索引**：每章生成后 ChapterDigest 摘要自动索引到 Chroma，供一致性检查语义检索
- **Agent Chat 会话记忆**：`run_agent_chat()` 支持 `session_id` + `db` 参数，自动从 DB 恢复历史对话 + 工作记忆注入系统提示

## Phase 4 三段式工具层 — propose / accept / regenerate

Phase 4 把 propose / accept / regenerate 统一到 MCP / CLI / agent_chat 三层。
设计文档 `specs/architecture-rework-2026/PHASE4.md`。核心原则：propose 不入库、
accept 幂等、三层同底、facade 不持有 LLM。

### 9 个实体 × 三操作

| 实体 | propose | accept | regenerate | 负责 Agent |
|---|:---:|:---:|:---:|---|
| project_setup | Y | Y | N | ProjectArchitect |
| synopsis | Y | Y | Y | ProjectArchitect |
| main_outline | Y | Y | Y | ProjectArchitect |
| characters | Y | Y | Y | ProjectArchitect |
| world_setting | Y | Y | Y | ProjectArchitect |
| story_arcs | Y | Y | Y | ProjectArchitect |
| volume_breakdown | Y | Y | Y | ProjectArchitect |
| volume_outline | Y | Y | Y | VolumeDirector |
| chapter_brief | Y | Y | N | ChapterPlanner |

`accept` / `regenerate` 在 MCP/CLI 各为单一通用入口（通过 `proposal_type` / `section` dispatch）。

### 三层入口（Web UI 不支持三段式）

- **MCP** (`mcp_server.py`)：`novel_propose_<entity>` × 9 + `novel_accept_proposal` + `novel_regenerate_section`
- **CLI** (`main.py`)：`novel propose <sub>` 子命令组 × 9 + `novel accept` + `novel regenerate`
- **agent_chat** (`src/novel/services/agent_chat.py`)：工具 `propose_<entity>` / `accept_proposal` / `regenerate_section`
- **Web UI**：设计决策不支持三段式，继续用 `NovelPipeline.create_novel()` 传统一步到位入口

### NovelToolFacade
- `src/novel/services/tool_facade.py` 是三层共享的**唯一业务入口**
- 职责：加载 novel.json → 构造 meta → 创建 LLM → 调 Agent → 包 `ProposalEnvelope` / `AcceptResult`
- MCP / CLI / agent_chat 只做参数适配和结果格式化，不得持有业务逻辑

### Deprecated 入口
- `novel_create` MCP 工具：**[DEPRECATED]** 被 `novel_propose_project_setup` + `novel_propose_main_outline` + `novel_accept_proposal` 组合替代，保留一个版本周期
- `plan_chapters` agent_chat 工具：**[DEPRECATED]** 被 `propose_chapter_brief` 替代

### 幂等保障
- 每个 proposal 带 UUID `proposal_id`，仅在 caller 会话内有效（proposal 不落盘）
- accept 记录 `_meta.last_accepted_proposal_id`；同 ID 重复 accept 返回 `status: "already_accepted"` 不写盘
- regenerate 不保留历史版本（原则 7 "删而不藏"）。characters / world_setting 走 `setting_version.py` 的 `effective_from_chapter` / `deprecated_at_chapter` 版本链

## Phase 5 质量评估

Phase 5 补的是"读着像不像人写的"层面。设计文档
`specs/architecture-rework-2026/PHASE5.md`。交付：7 维仪表盘 + A/B 对比工具，
不追求单一数字。

### 7 维度

| # | 维度 | key | 方法 | 尺度 | CI 门禁 |
|---|------|-----|------|------|:-:|
| D1 | 叙事流畅度 | `narrative_flow` | LLM-as-judge | 1-5 | 否 |
| D2 | 角色一致性 | `character_consistency` | 混合（Ledger + LLM） | 1-5 | 否 |
| D3 | 伏笔兑现率 | `foreshadow_payoff` | **纯规则**（LedgerStore 查询） | 百分比 | **是 >= 60%** |
| D4 | AI 味指数 | `ai_flavor_index` | **纯规则**（StyleProfile + 正则） | 0-100 | 否 |
| D5 | 情节推进度 | `plot_advancement` | LLM-as-judge | 1-5 | 否 |
| D6 | 对话自然度 | `dialogue_quality` | 混合 | 1-5 | 否 |
| D7 | 章节勾连 | `chapter_hook` | 混合 | 1-5 | 否 |

**唯一硬门禁**是 D3（工程指标：pipeline 是否正确消费 Ledger），其余 6 维软观测。
AI 味观察清单分体裁维护，不做全局黑名单。

### LLM Judge 异源原则
- Writer 用 DeepSeek → Judge 用 Gemini
- Writer 用 Gemini → Judge 用 DeepSeek
- Writer 用 OpenAI → Judge 用 Gemini
- `src/novel/quality/judge.py::auto_select_judge(writer_provider)` 自动切换 + 检查 API key 可用性
- `--judge-model` 手动覆盖一切
- 默认 Gemini 2.5 Flash（免费 tier 覆盖日常需求）

### 关键脚本

```bash
# 全量回归（5 体裁 × 3 章 + 7 维评估 + Rich Table + markdown 报告）
python scripts/quality_regression.py
python scripts/quality_regression.py --genres xuanhuan,suspense --chapters 2
python scripts/quality_regression.py --eval-only --input-dir workspace/quality_baselines/phase4

# A/B pairwise 对比（git worktree 隔离老 commit 的代码，确保两版生成同步比较）
python scripts/quality_ab_phase3_vs_phase4.py

# A/B 反向对照（消除 LLM judge position bias）
python scripts/quality_ab_debias.py
```

### A/B 双向强制规范（实证）

2026-04-21 首次 Phase 3 vs Phase 4 对比实证 **gpt-4o-mini 存在强 position bias**：

| 方向 | Phase 3 | Phase 4 | 判读 |
|------|:-:|:-:|---|
| Run 1: a=P3, b=P4 | 9 (60%) | 6 (40%) | 表面 P3 胜 |
| Run 2: a=P4, b=P3 | 1 (7%) | 14 (93%) | 反过来 P4 胜 |
| Position a 胜率 | 60% | 93% | **平均 76.5%** |

**强制**：所有 A/B 对比**必须跑双向** + **只报告双向一致决策**。单向结果仅
快速 sanity check，不作量化结论。工具：`scripts/quality_ab_debias.py`。

### pytest marker 体系

`pyproject.toml` 已注册 markers：

- `signature` - Agent 签名兼容（秒级、零 LLM）
- `quality` - 质量评估测试（mock judge，可慢）
- `llm_judge` - 需真实 LLM judge call
- `real_run` - 需真实 LLM 生成章节
- `regression` - 跨体裁回归（慢，需 API key）

本地默认跳过 `llm_judge` / `real_run` / `regression`，通过 `--run-real` 开启。
pytest 基线（Phase 5 完工）：**4564 passed / 21 skipped**。

### 基线与报告持久化

```
workspace/quality_reports/
├── single/       # ChapterQualityReport JSON
├── ab_compare/   # ABComparisonResult JSON
└── summary/      # markdown 汇总

workspace/quality_baselines/phase4/   # Phase 4 基线（章节文本 + 评估报告）
workspace/quality_baselines/phase5/   # Phase 5 基线
```

```bash
# 创建小说项目（大纲+世界观+角色）
python -c "
from src.novel.pipeline import NovelPipeline
pipe = NovelPipeline(workspace='workspace')
result = pipe.create_novel(genre='玄幻', theme='少年修炼逆天改命', target_words=100000)
"

# 生成章节
python -c "
pipe.generate_chapters('workspace/novels/novel_xxx', start_chapter=1, end_chapter=40)
"

# 应用读者反馈
python -c "
result = pipe.apply_feedback(
    project_path='workspace/novels/novel_xxx',
    feedback_text='第5章主角性格突然变了',
    chapter_number=5,
    dry_run=True,  # 先分析不修改
)
"
```

## 小说智能编辑（smart-editor）
规划文档 `specs/novel-smart-editor/`，详细文档见 `docs/edit_examples.md`、
`docs/mcp_edit_guide.md`、`docs/adr/0001-versioned-settings.md`。

- `src/novel/services/edit_service.py` — `NovelEditService` 统一编辑入口
- `src/novel/services/intent_parser.py` — 自然语言 → 结构化变更（opt-in LRU 缓存）
- `src/novel/services/impact_analyzer.py` — 纯规则影响分析（无 LLM）
- `src/novel/services/changelog_manager.py` — 变更历史
- `src/novel/editors/` — Character / Outline / WorldSetting 编辑器
- `src/novel/utils/setting_version.py` — 按章查询实体版本
- `src/novel/storage/file_manager.py::_novel_lock` — fcntl 文件锁（Unix）

实体版本字段：`effective_from_chapter`（闭）/ `deprecated_at_chapter`（开）/
`version`（>=1）。旧项目自动补默认值；可跑迁移脚本标准化。

```bash
# 自然语言编辑（CLI）
python main.py novel edit workspace/novels/novel_xxx \
  -i "添加角色柳青鸾，第10章出场" --dry-run
python main.py novel edit workspace/novels/novel_xxx \
  -i "删除角色张三"

# 变更历史
python main.py novel history workspace/novels/novel_xxx --limit 20

# 回滚（--force 绕过后续依赖检查）
python main.py novel rollback workspace/novels/novel_xxx <change_id>

# 老项目迁移（加版本字段；幂等，首次迁移落 novel.v1.json 备份）
python scripts/migrate_novel_v1_to_v2.py --workspace workspace
python scripts/migrate_novel_v1_to_v2.py --dry-run
```

MCP 工具（详见 `docs/mcp_edit_guide.md`）：`novel_edit_setting` /
`novel_analyze_change_impact` / `novel_get_change_history`。

批量编辑服务层 API（尚未暴露 CLI）：
```python
service.batch_edit(project_path, changes=[...], stop_on_failure=False)
```
每条独立 change_id + changelog 条目，保持回滚粒度。

## 开发注意事项
- 重依赖 (torch, diffusers, edge_tts) 使用懒加载，避免import时报错
- 图片尺寸 1024x1792 (竖屏9:16)
- 所有文件使用 UTF-8 编码
- FFmpeg 命令通过 subprocess.run 执行
- 字体检测跨平台: macOS PingFang / Linux Noto Sans CJK / Windows YaHei
- **A/B 对比必须双向**：LLM judge (实证 gpt-4o-mini) 有强 position bias，单向结果不可量化；跑 `quality_ab_debias.py` 只采纳双向一致决策
- **新测试必须打 pytest marker**：按 `signature` / `quality` / `llm_judge` / `real_run` / `regression` 分类，本地默认跳过真机 marker，通过 `--run-real` 启用

## 开发流程规范（必须遵守）

### 测试要求
- **每次代码变更必须编写测试**，不允许跳过
- **禁止乐观测试**（只测 happy path）。必须覆盖：
  - 边界条件（空值、None、超长输入、缺失字段）
  - 错误路径（异常、API 失败、垃圾返回值、文件不存在）
  - 状态一致性（跨模块数据传递是否正确）
  - 回归测试（修改不能破坏现有功能）
- 所有外部依赖必须 Mock（LLM、图片生成、TTS、FFmpeg）
- 断言要具体：不能只 `assert result`，必须检查具体字段和值
- 测试完成后运行 `python -m pytest tests/ -v` 确认全部通过

### 代码审查
- 每次实现完成后必须启动 `code-reviewer` Agent 审查代码
- 审查重点：接口兼容性、安全风险、错误处理、状态管理
- CRITICAL/HIGH 级别问题必须修复后才能提交

### Agent Team 协作模式
- 大型任务拆分为多个并行 Agent 执行，最大化效率
- 典型分工模式：
  - **task-executor Agent × N**：并行实现不同模块（注意文件不冲突）
  - **code-reviewer Agent**：实现完成后审查代码质量
  - **task-executor Agent**：根据审查结果修复问题 + 编写测试
- Agent 间通过文件系统协调，避免修改同一文件
- 所有 Agent 完成后，主线程运行完整测试确认无冲突
