# 更新日志

## [1.1.0] - 2026-04-01

### 新增
- **章节标题内联编辑** — 前端点击标题直接修改，无需进入编辑模式
- **OpenAI GPT-5+ 兼容** — max_completion_tokens 参数适配 + 超时增至 600s
- **存储重构** — rename_chapter 工具 + canonical state 架构，彻底解决内容覆盖问题
- **两步写作流程** — "规划大纲"审核后再"确认写作"，前端两段式交互
- **两段式章节编排** — dynamic_outline 写前修订 + state_writeback 写后回写
- **Agent Chat 对话型助手** — 从工具执行器升级为讨论型助手，支持步数配置 + 智能截断
- **大纲预检** — 生成章节前自动检查大纲完整性
- **编排闭环** — 重写反馈回流 + PlotPlanner 连续性 + 风格检查去重

### 修复
- Agent Chat 重写章节后同步更新 chapter JSON（title/word_count）
- Agent Chat 对话区溢出修复（Panel overflow-hidden + 高度缩小）
- 章节标题从正文智能提取，不再显示"第N章"
- 系统提示词加 JSON 关键词，修复 OpenAI json_mode 400 错误
- ReAct fallback 降级到 one-shot 时传递 feedback_prompt + continuity_brief
- Agent Chat 消息去重 + 角色快照真实抽取
- 占位符大纲回填不再用正文覆盖 goal/key_events
- 防御性修复：state.get("chapters") or [] 替代 state.get("chapters", [])，避免 None 值导致迭代异常

### 变更
- 版本号从 1.0.0 升级至 1.1.0
- .gitignore 增加 frontend 构建产物（test-results/playwright-report/tsconfig.tsbuildinfo）

---

## [1.0.0] - 2026-03-26

### 新增
- **ReAct Agent 框架** — Writer 支持 ReAct 推理模式，工具链路可视化（类 Claude Code 风格）
- **Prompt Registry** — DB 驱动的 Prompt 管理系统，支持版本控制 + 质量追踪 + 自动优化
- **Next.js Prompt 管理页面** — Block 编辑/版本/回滚/预览，独立前端
- **Agent Chat 会话持久化** — 自动恢复对话历史 + 工作记忆注入，多轮协作不再丢上下文
- **叙事控制层 P0** — ObligationTracker 叙事债务追踪 + VolumeSettlement 卷末收束 + 弧线推进
- **知识图谱可视化** — StoryUnit + 角色关系网络图谱
- **LLM 债务兑现判定** — LLM 自动识别章节中哪些叙事线索已兑现
- **Agent Chat 6 工具** — 章节生成/重写/大纲查看/角色查看/一致性检查/设定修改
- **叙事控制 REST API** — 7 个端点供前端调用
- **前端叙事 Tab** — 债务表格可视化 + 弧线时间线
- **LLM 按阶段分模型** — 不同创作阶段可配置不同 LLM（如大纲用 GPT-4、写作用 DeepSeek）
- **占位符大纲自动补全** — 缺失章节大纲自动回填

### 修复
- Tab 状态保持 + Agent 对话优化 + 任务并发支持
- 叙事债务表格加 max-height 滚动，不再撑开页面
- Writer 未接收 debt_summary 的关键 bug
- NovelMemory 初始化 + DB 连接泄漏修复
- 占位符大纲补全导致 ChapterOutline validation 失败
- SiliconFlow 429 重试逻辑修复
- AI 导演模式加载历史视频不显示的问题
- 小说精修报告修改前后对比展示

### 变更
- 项目版本从 0.9.0 升级至 1.0.0，标志小说创作系统全功能成熟

---

## [0.9.0] - 2026-03-16

### 新增
- **AI 短视频导演模式** (`src/director_pipeline.py` + `src/scriptplan/`)
  - 从一句灵感/主题出发，AI 自动生成完整短视频
  - IdeaPlanner: 灵感 → 概念（主题/情绪/风格/目标受众）
  - ScriptPlanner: 概念 → 分段脚本（镜头语言、画面描述、旁白）
  - AssetStrategy: 智能决策每段使用静态图 or AI 视频片段
  - CLI: `python main.py create-video "灵感文本"` / Web UI 导演 Tab
- **AI 长篇小说写作模块** (`src/novel/`)
  - 9 Agent LangGraph 编排: NovelDirector / WorldBuilder / CharacterDesigner / PlotPlanner / Writer / ConsistencyChecker / StyleKeeper / QualityReviewer / FeedbackAnalyzer
  - 三层大纲生成（幕→卷→章），支持循环升级/多线交织/四幕等模板
  - 角色档案系统: 性格标签、说话风格、口头禅、成长弧线、关系网
  - 世界观构建: 时代/地域/力量体系/专有名词
  - 逐场景章节生成，每章 2000-3000 字，反 AI 味指令
  - 三层一致性检查: SQLite / NetworkX / Chroma 向量搜索
  - 风格预设系统: 6 大类风格（网文/武侠/文学/轻小说），量化指标约束
  - 质量评审: 规则硬指标（零成本）+ LLM 打分，不达标自动重写（最多 2 次）
  - ConsistencyChecker 和 StyleKeeper 并行执行 (ThreadPoolExecutor)
  - LangGraph 为可选依赖，未安装时自动 fallback 为顺序执行
  - 章节任务书 (ChapterBrief)、追更价值评估 (RetentionQuality)、反馈诊断链
  - Writer 去重/锁定机制防止重复生成
- **MCP Server** (`mcp_server.py`)
  - FastMCP (streamable-http + stdio) 协议，供 Claude Code 等 AI 助手调用
  - 小说工具: 创建项目 / 生成章节 / 查看状态 / 读取章节 / 应用反馈 / 导出
  - 视频工具: 生成视频 / 文本分段 / 查看状态 / 列出项目
- **任务队列系统** (`src/task_queue/`)
  - FastAPI 后台任务服务，前后端分离架构
  - SQLite 持久化，支持任务提交/轮询/取消
  - Worker 异步执行视频生成和小说创作任务
  - Web UI 全面异步化，不再阻塞前端
- **Web UI 三合一创作平台** (`web.py`)
  - 短视频制作 Tab: 经典/Agent/导演三种模式 + 快捷键场景 + 历史记录加载/回放
  - AI 小说 Tab: 创建/续写/反馈/导出/七猫自动发布
  - 设置 Tab: 统一 API Key 管理 + LLM/图片/TTS 后端选择
- **Token 优化策略**
  - BM25 关键词检索 (jieba + rank_bm25) 替代 LLM 全文比对
  - ChapterDigest 章节摘要压缩（~500 字）替代全文 LLM 打分
  - 前 3 章跳过一致性检查，非 9 倍数章用 BM25 轻量检查
  - LLM 打分仅每 5 章一次 + 末章（budget_mode）
  - Writer 使用 max_tokens + 硬截断控制章节长度
- **读者反馈系统**
  - FeedbackAnalyzer Agent: LLM 分析反馈类型、影响范围、重写指令
  - Writer.rewrite_chapter(): 直接修改 + 传播调整两种模式
  - 章节版本备份: 重写前自动保存旧版本，支持回滚
  - dry_run 模式: 先分析影响范围，确认后再执行
  - pipeline.apply_feedback() API
- **LLM 接口增强**
  - 所有后端 (OpenAI/Gemini/Ollama) 新增 `max_tokens` 参数支持
  - 大纲生成使用 max_tokens=8192 避免长输出截断
- **Sora 视频生成后端** (`src/videogen/sora_backend.py`)
  - OpenAI Sora 2 原生竖屏 720x1280
  - 支持 sora-2 ($0.10/s) 和 sora-2-pro ($0.30~0.50/s)

### 修复
- Pipeline 完成时回调 progress(1.0)，进度条正确显示 100%
- 视频图片角色性别混乱问题
- DirectorPipeline 合成阶段 crash
- 修复 code review 发现的 3 个安全/可靠性问题

### 变更
- 项目定位升级为「AI 创意工坊」，涵盖短视频制作 + AI 小说创作
- 章节默认长度从 4000 字调整为 2000-3000 字
- 每章场景数从 4 个调整为 3 个
- ChapterOutline.estimated_words 默认值从 3000 改为 2500，最小值从 1000 改为 500

## [0.8.0] - 2026-03-11

### 新增
- **Sora 2 视频生成支持**
  - Agent 模式完整支持 AI 动态视频生成 (ArtDirector → VideoGenTool)
  - Sora 2 原生竖屏 720x1280，无需横转竖裁剪
  - 自动生成同步音频（对话、音效、环境音）
  - 支持 sora-2 ($0.10/s) 和 sora-2-pro ($0.30~0.50/s)
  - 分辨率自动验证 + 时长对齐到支持的档位
- **VideoGenTool** - 新增视频生成工具，封装 videogen 模块供 Agent 调用
- **drawtext 字幕备选方案** - FFmpeg 缺少 libass 时自动使用 drawtext 滤镜渲染字幕

### 修复
- 视频合成横转竖使用 crop 填充替代 pad 黑边
- Sora API 参数修正: `input_reference`(非 image)、JSON 格式纯文本请求
- `pipeline_plan` 为 None 时的 AttributeError
- FFmpeg subtitles filter 检测 + 优雅降级

### 变更
- 默认 Sora 分辨率从 1280x720 改为 720x1280 (原生竖屏)
- 升级 FFmpeg 依赖建议: homebrew-ffmpeg/ffmpeg (含 libass + drawtext)

## [0.7.0] - 2026-03-10

### 新增
- **LangGraph Multi-Agent 架构** (Phase 1-3 完成)
  - 5 Agent 系统: Director, ContentAnalyzer, ArtDirector, VoiceDirector, Editor
  - LangGraph StateGraph 编排，线性流程
  - `--mode agent` CLI 参数启用 Agent 模式（经典模式不受影响）
  - `--budget-mode` 省钱模式（基于规则，跳过质量检查）
  - `--quality-threshold` 可配置图片质量阈值
- **图片质量控制**
  - GPT-4V / Gemini Vision 质量评估 (EvaluateQualityTool)
  - 低分自动重试 + prompt 优化
  - 多维度评分（清晰度、构图、色彩、文本匹配度、一致性）
- **Agent 决策日志**
  - 完整决策审计追踪，保存至 `agent_decisions.json`
  - `status --decisions` CLI 可视化，Rich 表格展示
  - 每个 Agent 的决策计数、质量汇总、重试统计
- **费用追踪**
  - CostTracker 类，支持按模型计费
  - 决策日志中按模型展示费用明细
- **Agent 模式断点续传**
  - `completed_nodes` 累加器，使用 `operator.add` reducer
  - `_make_skip_or_run` 包装器跳过已完成节点
  - 每个节点执行后通过 RunnableConfig 保存中间状态
- **内容分析**
  - 题材分类（6 种规则匹配 + LLM 兜底）
  - 角色提取（正则 + LLM 兜底）
  - 风格建议映射
  - 情感分析用于 TTS 参数调优
- **Tool 层**
  - SegmentTool, PromptGenTool, ImageGenTool, TTSTool, VideoAssembleTool
  - `create_tools()` 工厂函数
  - 轻量包装器，懒加载初始化
- **Gradio 前端 Agent 模式**
  - 新增 Agent/经典模式切换
  - Agent 分析 Tab（内容分析 + 图片画廊）
  - 决策日志 Tab（JSON 审计追踪）
  - 质量报告 Tab（Markdown 汇总）
  - 省钱模式 + 质量阈值前端控件
- **Playwright E2E 测试**
  - 6 个端到端浏览器测试：页面加载、模式切换、经典生成、Agent 全流程
  - Gradio server fixture + headless Chromium
- **真实 API 集成测试**
  - 10 个 `@pytest.mark.integration` 测试（LLM/TTS/图片/Agent Pipeline）
- **Agent 架构设计文档**
  - `specs/langgraph-multi-agent/architecture.md`

### 修复
- `extract_json_array` 处理 OpenAI json_mode 返回的对象包装数组
- `load_decisions_from_file` 对损坏 JSON 文件的容错处理
- Ruff lint：修复 31 个未使用 import

### 变更
- 版本号从 0.4.0 升级至 0.7.0
- `pyproject.toml` 新增 `agent` 和 `agent-gemini` 可选依赖组
- `config.yaml` 新增 `agent:` 配置段（quality_check, decisions, budget_mode）
- PyInstaller spec 更新：添加 agents/tools 模块，版本号同步 0.7.0

## [0.4.0] - 2026-03-08

### 新增
- AI 视频生成模块（可灵 Kling / 即梦 Seedance / MiniMax 海螺）
- H.265 编码支持，视频文件体积更小
- 改进启动脚本

## [0.3.0] - 2026-03-07

### 新增
- PyInstaller 打包优化（1.4G -> 192M）
- CI artifact 名称改为 ASCII，修复下载失败问题

## [0.2.0] - 2026-03-06

### 新增
- 多 LLM 后端支持（OpenAI / DeepSeek / Gemini / Ollama）
- 多图片生成后端（diffusers / Together.ai / SiliconFlow / DashScope）
- Edge-TTS 语音合成 + SRT 字幕生成
- FFmpeg 视频合成 + Ken Burns 特效

## [0.1.0] - 2026-03-05

### 新增
- 首次发布：小说文本转短视频流水线
- Click CLI 命令行界面
- 简单文本分段
- 基础 prompt 生成
