# Agent 系统概览

本项目包含两套 LangGraph Multi-Agent 系统，分别用于视频制作和小说创作。

## 视频 Agent 系统 (src/agents/)

5 个专职 Agent 协作完成短视频制作：

| Agent | 模块 | 职责 |
|-------|------|------|
| Director | `director.py` | 任务分析、成本估算、流程调度 |
| ContentAnalyzer | `content_analyzer.py` | 题材分类、角色提取、风格推荐 |
| ArtDirector | `art_director.py` | 图片/视频生成 + GPT-4V/Gemini 质量评估 |
| VoiceDirector | `voice_director.py` | 情感分析 + TTS 参数调优 |
| Editor | `editor.py` | FFmpeg 视频合成、最终输出 |

**编排**: Director → ContentAnalyzer → ArtDirector → VoiceDirector → Editor

**关键文件**:
- `src/agents/graph.py` - LangGraph StateGraph 构建 + 断点续传
- `src/agents/state.py` - AgentState TypedDict
- `src/agents/utils.py` - 决策记录、JSON 提取
- `src/agents/cost_tracker.py` - 费用追踪
- `src/tools/` - Tool 层（SegmentTool, PromptGenTool, ImageGenTool, VideoGenTool, TTSTool, VideoAssembleTool, EvaluateQualityTool）

## 小说 Agent 系统 (src/novel/agents/)

**2026-04 架构重构 Phase 0-5 完工**：9 Agent 合并为 **5 个专职 Agent**。

| Agent | 模块 | 职责 | 替代 |
|-------|------|------|------|
| ProjectArchitect | `project_architect.py` | 项目骨架（synopsis / main_outline / characters / world / arcs / volume_breakdown），全部 propose/accept/regenerate 三段式 | NovelDirector / WorldBuilder / CharacterDesigner |
| VolumeDirector | `volume_director.py` | 单卷细纲 + 卷结算（propose_volume_outline + settle_volume + plan_volume_breakdown） | — |
| ChapterPlanner | `chapter_planner.py` | 单章 brief 组装（消费 LedgerStore snapshot），吸收 hook_generator + dynamic_outline | PlotPlanner |
| Writer | `writer.py` | 逐场景章节生成（2000-3000 字/章，one-shot + ReAct 双模式） | — |
| Reviewer | `reviewer.py` | 单入口审稿（quality + consistency + style 三维度联合报告，**不打分只标问题**），吃 LedgerStore + StyleProfile | ConsistencyChecker + StyleKeeper + QualityReviewer + ChapterCritic |

> FeedbackAnalyzer 逻辑下放到 `pipeline.apply_feedback` 直接 LLM 调用，不再作为独立 Agent。
> NovelDirector 仅保留 `plan_next_chapter` / `generate_volume_outline` / `generate_volume_milestones` 三个卷级工具方法。

**编排**:
- 初始化图（5 Agent 前）→ **简化为 ProjectArchitect 多方法 propose/accept 链**（MCP / CLI / agent_chat 各自驱动）
- 章节生成图：`chapter_planner → writer → reviewer → state_writeback`（**5 节点精简为 4 节点**，零自动重写）
- 反馈重写：`pipeline.apply_feedback` → `Writer.rewrite_chapter()`

**关键文件**:
- `src/novel/agents/graph.py` - LangGraph 图构建 + sequential fallback
- `src/novel/agents/state.py` - NovelState TypedDict
- `src/novel/services/tool_facade.py` - **NovelToolFacade**：MCP / CLI / agent_chat 三层共享的唯一业务入口（Phase 4）
- `src/novel/services/ledger_store.py` - **LedgerStore** facade：统一包装 ObligationTracker + ForeshadowingService + CharacterArcTracker + MilestoneTracker + EntityService
- `src/novel/services/brief_assembler.py` - BriefAssembler（继承 ContinuityService shim，逐步替代）
- `src/novel/services/prev_tail_summarizer.py` - **PrevTailSummarizer**（C3 真修，commit `15095b3`）：上章末 500 字 → ≤200 字结构化摘要 + 15-char verbatim 后校验。pipeline 所有 Writer 通道（generate / polish / apply_feedback / rewrite_affected）共用；ChapterPlanner 内部 wrapper 委托
- `src/novel/quality/` - **Phase 5** 质量评估（7 维度 + LLM-as-judge + A/B pairwise）
- `src/novel/tools/` - ChapterDigest（BM25/ConsistencyTool/QualityCheckTool/StyleAnalysisTool 已删）
- 规划文档 `specs/architecture-rework-2026/`（AUDIT / DESIGN / PHASE4 / PHASE5 / README）

## AI 导演系统 (src/scriptplan/)

从灵感出发自动生成短视频的规划系统：

| 模块 | 职责 |
|------|------|
| `idea_planner.py` | 灵感 → 概念（主题/情绪/风格/受众） |
| `script_planner.py` | 概念 → 分段脚本（镜头/画面/旁白） |
| `asset_strategy.py` | 素材策略（静态图 vs AI 视频） |
| `models.py` | Pydantic 数据模型 |

入口: `src/director_pipeline.py`

## 共同特性

- LangGraph 为可选依赖，未安装时自动 fallback 为顺序执行
- 省钱模式 (`--budget-mode`): 规则替代 LLM，降低成本约 40%
- 断点续传: 中断后从上次进度继续
- 决策日志: 全流程审计追踪
