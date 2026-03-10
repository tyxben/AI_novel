# Changelog

## [0.7.0] - 2026-03-10

### Added
- **LangGraph Multi-Agent Architecture** (Phase 1-3 complete)
  - 5 Agent system: Director, ContentAnalyzer, ArtDirector, VoiceDirector, Editor
  - LangGraph StateGraph orchestration with linear flow
  - `--mode agent` CLI flag for Agent mode (classic mode unchanged)
  - `--budget-mode` for cost-effective processing (rules-based, skip quality checks)
  - `--quality-threshold` for configurable image quality gates
- **Image Quality Control**
  - GPT-4V / Gemini Vision quality evaluation (EvaluateQualityTool)
  - Auto-retry with prompt optimization on low scores
  - Per-dimension scoring (clarity, composition, color, text_match, consistency)
- **Agent Decision Logging**
  - Full decision audit trail saved to `agent_decisions.json`
  - `status --decisions` CLI visualization with Rich tables
  - Per-agent decision counts, quality summaries, retry statistics
- **Cost Tracking**
  - CostTracker class with per-model API pricing
  - Cost breakdown by model in decision logs
- **Checkpoint Resume for Agent Mode**
  - `completed_nodes` accumulator with `operator.add` reducer
  - `_make_skip_or_run` wrapper skips already-completed nodes
  - Intermediate state saved after each node via RunnableConfig
- **Content Analysis**
  - Genre classification (6 rule patterns + LLM fallback)
  - Character extraction (regex + LLM fallback)
  - Style suggestion mapping
  - Emotion analysis for TTS parameter tuning
- **Tool Layer**
  - SegmentTool, PromptGenTool, ImageGenTool, TTSTool, VideoAssembleTool
  - `create_tools()` factory function
  - Lightweight wrappers with lazy initialization
- **Gradio 前端 Agent 模式**
  - 新增 Agent/经典模式切换
  - Agent 分析 Tab (内容分析 + 图片画廊)
  - 决策日志 Tab (JSON 审计追踪)
  - 质量报告 Tab (Markdown 汇总)
  - 省钱模式 + 质量阈值前端控件
- **Playwright E2E 测试**
  - 6 个端到端浏览器测试: 页面加载、模式切换、经典生成、Agent 全流程
  - Gradio server fixture + headless Chromium
- **真实 API 集成测试**
  - 10 个 `@pytest.mark.integration` 测试 (LLM/TTS/图片/Agent Pipeline)
- **Agent 架构设计文档**
  - `specs/langgraph-multi-agent/architecture.md`

### Fixed
- `extract_json_array` 处理 OpenAI json_mode 返回的对象包装数组
- `load_decisions_from_file` 对损坏 JSON 文件的容错处理
- Ruff lint: 修复 31 个未使用 import

### Changed
- Version bump from 0.4.0 to 0.7.0
- `pyproject.toml` adds `agent` and `agent-gemini` optional dependency groups
- `config.yaml` adds `agent:` section (quality_check, decisions, budget_mode)
- PyInstaller spec 更新: 添加 agents/tools 模块, 版本号同步 0.7.0

## [0.4.0] - 2026-03-08

### Added
- AI video generation module (Kling/Seedance/MiniMax)
- H.265 codec support for smaller video files
- Improved startup scripts

## [0.3.0] - 2026-03-07

### Added
- PyInstaller build optimization (1.4G -> 192M)
- CI artifact ASCII naming fix

## [0.2.0] - 2026-03-06

### Added
- Multi-LLM backend support (OpenAI/DeepSeek/Gemini/Ollama)
- Multi image generation backend (diffusers/Together.ai/SiliconFlow/DashScope)
- Edge-TTS voice synthesis with SRT subtitles
- FFmpeg video assembly with Ken Burns effect

## [0.1.0] - 2026-03-05

### Added
- Initial release: novel text to short video pipeline
- Click CLI interface
- Simple text segmentation
- Basic prompt generation
