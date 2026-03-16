# AI 创意工坊

## 项目概述
AI 驱动的一站式内容创作平台：短视频自动制作 + AI 长篇小说创作。
支持三种使用方式：CLI 命令行 / Gradio Web UI / MCP Server（AI 助手调用）。

## 技术栈
- Python 3.10+ / Click CLI / Gradio Web UI / FastMCP Server
- edge-tts (微软免费TTS)
- 多 LLM 后端: OpenAI / DeepSeek / Gemini(免费) / Ollama(本地) — 统一接口 `src/llm/`
- 图片生成: SiliconFlow(免费) / 阿里云万相 / Together.ai / diffusers(本地SD) — 统一接口 `src/imagegen/`
- AI视频片段: 可灵(Kling) / 即梦(Seedance) / MiniMax(海螺) / OpenAI Sora — 统一接口 `src/videogen/`
- FFmpeg (视频合成)
- FastAPI + SQLite (任务队列)

## 项目结构
- `main.py` - CLI 入口 (click)
- `web.py` - Web UI 入口 (Gradio 三合一创作平台)
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

## 常用命令
```bash
# 安装
pip install -e '.[web,cloud-image,gemini]'  # 推荐：Web UI + 云端生图 + Gemini
pip install -e '.[all]'                      # 全部安装

# Web UI 启动
./start.sh                    # 或 python web.py

# 视频制作 - 经典模式
python main.py run input/novel.txt
python main.py run input/novel.txt --resume  # 断点续传

# 视频制作 - Agent 模式
python main.py run input/novel.txt --mode agent
python main.py run input/novel.txt --mode agent --budget-mode

# 视频制作 - 导演模式
python main.py create-video "一句灵感"

# 小说创作
python main.py novel write --genre 玄幻 --theme "少年修炼逆天改命" --target-words 100000
python main.py novel resume workspace/novels/novel_xxx
python main.py novel export workspace/novels/novel_xxx
python main.py novel status workspace/novels/novel_xxx

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
- `src/novel/agents/` - 9个 Agent: NovelDirector / WorldBuilder / CharacterDesigner / PlotPlanner / Writer / ConsistencyChecker / StyleKeeper / QualityReviewer / FeedbackAnalyzer
- `src/novel/tools/` - Tool 层: ConsistencyTool / QualityCheckTool / StyleAnalysisTool / BM25Retriever / ChapterDigest
- `src/novel/models/` - Pydantic 数据模型: Novel / Chapter / Character / World / Feedback 等
- `src/novel/storage/` - 存储层: NovelMemory(SQLite+NetworkX+Chroma) / FileManager
- `src/novel/templates/` - 模板预设: 大纲模板 / 风格预设 / 节奏模板 / AI味黑名单
- `src/novel/pipeline.py` - 小说创作流水线（创建项目 / 生成章节 / 应用反馈）
- `src/novel/config.py` - 小说模块配置 (NovelConfig)
- `src/novel/agents/graph.py` - LangGraph 图构建 (init graph + chapter graph) + sequential fallback
- `src/novel/agents/state.py` - NovelState TypedDict
- 规划文档在 `specs/novel-writing/`（requirements.md / design.md / tasks.md）

### Agent 编排
- **初始化图**: NovelDirector → WorldBuilder → CharacterDesigner → END
- **章节生成图**: PlotPlanner → Writer → [ConsistencyChecker ∥ StyleKeeper] → QualityReviewer → END/Writer(重写)
- **反馈重写**: FeedbackAnalyzer → Writer.rewrite_chapter() (直接修改 + 传播调整)
- ConsistencyChecker 和 StyleKeeper 并行执行 (ThreadPoolExecutor)
- LangGraph 为可选依赖，未安装时 fallback 为顺序执行

### 省 Token 策略
- 前3章跳过一致性检查，非9倍数章用 BM25 轻量检查
- LLM 打分仅每5章一次 + 末章（budget_mode）
- 章节摘要替代全文送 LLM 打分（ChapterDigest）
- 每章目标 2000-3000 字，Writer 用 max_tokens + 硬截断控制

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

## 开发注意事项
- 重依赖 (torch, diffusers, edge_tts) 使用懒加载，避免import时报错
- 图片尺寸 1024x1792 (竖屏9:16)
- 所有文件使用 UTF-8 编码
- FFmpeg 命令通过 subprocess.run 执行
- 字体检测跨平台: macOS PingFang / Linux Noto Sans CJK / Windows YaHei

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
