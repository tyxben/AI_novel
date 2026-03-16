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

9 个专职 Agent 协作完成长篇小说创作：

| Agent | 模块 | 职责 |
|-------|------|------|
| NovelDirector | `novel_director.py` | 三层大纲生成（幕→卷→章） |
| WorldBuilder | `world_builder.py` | 世界观构建（时代/地域/力量体系） |
| CharacterDesigner | `character_designer.py` | 角色档案 + 关系网 |
| PlotPlanner | `plot_planner.py` | 场景分解 + 节奏设计 |
| Writer | `writer.py` | 逐场景章节生成（2000-3000 字/章） |
| ConsistencyChecker | `consistency_checker.py` | BM25 + LLM 矛盾检测 |
| StyleKeeper | `style_keeper.py` | 风格指标量化分析 |
| QualityReviewer | `quality_reviewer.py` | 规则硬指标 + LLM 打分 |
| FeedbackAnalyzer | `feedback_analyzer.py` | 读者反馈处理 + 重写指令 |

**编排**:
- 初始化图: NovelDirector → WorldBuilder → CharacterDesigner → END
- 章节生成图: PlotPlanner → Writer → [ConsistencyChecker || StyleKeeper] → QualityReviewer → END/重写
- 反馈重写: FeedbackAnalyzer → Writer.rewrite_chapter()

**关键文件**:
- `src/novel/agents/graph.py` - LangGraph 图构建 + sequential fallback
- `src/novel/agents/state.py` - NovelState TypedDict
- `src/novel/tools/` - BM25Retriever, ChapterDigest, ConsistencyTool, QualityCheckTool, StyleAnalysisTool
- `src/novel/services/` - 角色/世界观/一致性业务逻辑

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
