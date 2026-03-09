# Changelog

## [0.7.0] - 2026-03-09

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

### Changed
- Version bump from 0.4.0 to 0.7.0
- `pyproject.toml` adds `agent` and `agent-gemini` optional dependency groups
- `config.yaml` adds `agent:` section (quality_check, decisions, budget_mode)

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
