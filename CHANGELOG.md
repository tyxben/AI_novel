# 更新日志

## [2.0.0] - 2026-04-26

### 重大重构 — 架构重构 2026 Phase 0-5（2026-04-18 ~ 04-21）

- **5 Agent 替换旧 9 Agent** — `ProjectArchitect` / `VolumeDirector` / `ChapterPlanner` / `Writer` / `Reviewer`，规划文档见 `specs/architecture-rework-2026/`（README / AUDIT / DESIGN / MODULE_USAGE / PHASE4 / PHASE5）
  - 删除 `ConsistencyChecker` / `StyleKeeper` / `QualityReviewer` 三 Agent，合并到单一 `Reviewer` 节点（3 维联合报告：quality / consistency / style）
  - 删除 `DynamicOutlinePlanner` / `PlotPlanner` / `HookGenerator`，合并到 `ChapterPlanner`（brief + scenes + hook 一站式）
  - 删除 `WorldBuilder` / `CharacterDesigner` / `NovelDirector` 三 Agent 的初始化职责，合并到 `ProjectArchitect.propose_*`
  - 章节生成图从多节点并行简化为 4 节点串行：`chapter_planner → writer → reviewer → state_writeback`
  - **Reviewer 不再打分** — 只产 `CritiqueResult` 报告，零自动重写循环；定量打分迁移到 Phase 5 `src/novel/quality/`

- **Phase 4 三段式工具层** `NEW` — `propose / accept / regenerate` 统一到 MCP / CLI / agent_chat 三层
  - 9 个实体（project_setup / synopsis / main_outline / characters / world_setting / story_arcs / volume_breakdown / volume_outline / chapter_brief）× propose / accept / regenerate 矩阵
  - `NovelToolFacade` (`src/novel/services/tool_facade.py`) — 三层共享的唯一业务入口，MCP/CLI/agent_chat 只做参数适配
  - propose 不入库（仅 caller 会话内有效）；accept 幂等（`_meta.last_accepted_proposal_id`）；regenerate 删而不藏（不保留历史版本，characters/world_setting 走 `setting_version.py` 版本链）
  - **Deprecated**：`novel_create` MCP 工具 + `plan_chapters` agent_chat 工具，保留一个版本周期

- **Phase 5 质量评估** `NEW` — 7 维仪表盘 + LLM-as-judge 异源原则
  - 7 维度：叙事流畅 / 角色一致 / 伏笔兑现率（**唯一硬门禁 >= 60%**）/ AI 味指数 / 情节推进 / 对话自然 / 章节勾连
  - LLM Judge 异源：Writer 用 DeepSeek → Judge 用 Gemini，反之亦然，避免同模型自评 bias
  - **A/B 双向强制 de-bias** — 实证 gpt-4o-mini position bias 平均 76.5%，单向结果不作量化结论；`scripts/quality_ab_debias.py` 必跑双向
  - 跨体裁回归脚本 `scripts/quality_regression.py`（5 体裁 × 3 章 + 7 维评估 + Rich Table + markdown 报告）
  - pytest marker 体系：`signature` / `quality` / `llm_judge` / `real_run` / `regression`，本地默认跳真机 marker

- **LedgerStore 统一账本** `NEW` — `src/novel/services/ledger_store.py`
  - facade 包装 `ObligationTracker` / `ForeshadowingService` / `CharacterArcTracker` / `MilestoneTracker` / `EntityService`
  - `snapshot_for_chapter(N)` 返回当章 brief 需要的所有账本数据，`ChapterPlanner.propose_chapter_brief` 实时消费

- **BriefAssembler 替换 ContinuityService** — `src/novel/services/brief_assembler.py`
  - Ledger-first 的 continuity context 聚合器，`ContinuityService` 保留为兼容 shim
  - 由 `ChapterPlanner.propose_chapter_brief` 实时调用，新代码一律用 BriefAssembler

### 修复 — Writer 跨章 verbatim 复读 P0 + C3 同源

- **P0 修复（commit `ffffda2`，2026-04-25）** — Writer 切断上章原文通道
  - `writer_node` 删 41 行直接读 `chapters_text` / `FileManager.load_chapter_text` 逻辑
  - `ChapterPlanner` 加 `_summarize_previous_tail`（LLM 压缩 ≤200 字 + 15-char verbatim 后校验）+ `_lookup_previous_end_hook`
  - `ChapterBrief` 加 `previous_chapter_tail_summary` / `previous_chapter_end_hook` 字段（派生字段不落盘，运行时 state 流转）
  - `pipeline.polish_chapters` / `rewrite_chapter` 上章原文 2000 → 500 字（中间硬扛），Writer prompt 加"严禁照抄"
  - 测试 +51 例（`test_chapter_planner_prev_tail_summary.py` × 19 + `test_writer_no_raw_prev_chapter.py` × 9 + `test_p0_integration.py` × 14）

- **C3 同源真修（commit `15095b3`，2026-04-26）** `NEW` — pipeline 三处通道走 summarizer
  - 新增 `src/novel/services/prev_tail_summarizer.py` — `summarize_previous_tail()` + `has_long_verbatim_overlap()` 模块函数
  - `ChapterPlanner._summarize_previous_tail` / `_has_long_verbatim_overlap` 改为 thin wrapper 委托给 service（19 个旧测试不破）
  - `pipeline.polish_chapters` / `apply_feedback` / `rewrite_affected_chapters` 三处通道：先 `summarize_previous_tail()` 拿摘要再喂 `Writer.polish_chapter` / `Writer.rewrite_chapter`；摘要返空时 context 也置空，**绝不 fallback 塞生原文**
  - **信息边界规则落地** — `polish_chapters` 的 Reviewer 拿原文末 500 字（评估侧需要原始字面量做 typo / 衔接 / 跨章伏笔判断），Writer 拿摘要（生成侧防 verbatim 复读）
  - Writer 提示词文案：`【前文回顾 — 严禁照抄】` → `【前章状态摘要 — 仅供衔接参考，严禁照抄】`，propagation 分支 `【修改后的前文】` → `【修改后的前章状态摘要 — 严禁照抄】`
  - `apply_feedback` 路径修 `truncate_text(..., 500)` (从开头切句子边界 friendly) → `[-500:]` (取末尾)
  - 测试 +15 例 `test_pipeline_c3_prev_tail.py`（含端到端 backstop：不 patch summarizer 只 patch llm.chat，验证 Writer prompt 不含上章 15-char 子串）

### 变更

- 版本号从 1.2.0 升级至 2.0.0（标志 9 → 5 Agent 架构 break change）
- pytest 总数从 3692 → **4630**（Phase 5 完工 4564 → P0 4615 → C3 4630）
- 旧规划文档 `specs/novel-writing/`（requirements.md / design.md / tasks.md）转为历史参考

### 沉淀的判读规则

来自 P0 / C3 期间被 code-review 抓出的 CRITICAL（C1 死代码 / C2 持久化断链 / C3 同类路径漏修 + H1 信息边界违反）后总结的 4 条规则：

1. **信息边界（生成侧 / 评估侧分流）** — Writer 用摘要避免 verbatim 复读；Reviewer 用原文做 typo / 衔接判断；不能混用
2. **同类路径全 grep** — 修一处时 grep 整库找同模式（如 `chapter_texts[ch-1][-N:]` / `prev_text[-N:]`），避免漏改
3. **生产 key 名集成测试** — 端到端测试不 mock 内部函数，只 mock 外部边界（LLM I/O），避免 import 路径迁移导致 spy 失效
4. **架构修复优先于 prompt 警告** — 直接喂生原文 + "严禁照抄" prompt 警告 是反模式；正确做法是切断生原文通道，让 Writer 物理上看不到原文

---

## [1.2.0] - 2026-04-08

### 新增 — 小说生成质量三层增强

- **GlobalDirector 全书状态监控** `NEW` — 新服务 `services/global_director.py`
  - 计算每章在卷内的位置与推进百分比
  - 自动判断故事阶段：起势 / 上升 / 高潮 / 收束 / 过渡
  - 提取活跃故事弧线，卷末倒数自动预警
  - 检测最近 5 章标题字符重复，强制场景切换
  - 注入到 Writer 系统提示 + 大纲规划 prompt 双通道

- **CharacterArcTracker 角色弧线追踪** `NEW` — 新服务 `services/character_arc_tracker.py`
  - 从每章 actual_summary 自动识别成长阶段（觉醒/试炼/结盟/冲突/蜕变/失落/胜利）
  - 记录每个角色的里程碑链（from_stage → to_stage + 触发事件）
  - 长期未出场角色自动预警（>5 章未出现提示重新介绍）
  - 状态持久化到 `novel.json` 的 `character_arc_states` 字段
  - 注入到 Writer system prompt，约束角色行为与成长阶段一致

- **HookGenerator 章末钩子生成** `NEW` — 新服务 `services/hook_generator.py`
  - 自动评分章末钩子质量（0-10）
  - 检测弱结尾（休息/总结/平淡）并用 LLM 重写
  - 保留强钩子类型：问句 / 突发事件 / 省略悬念 / 被打断的关键动作
  - 段落级智能拼接，不破坏正文主体

- **自动补全 actual_summary** `NEW`
  - `generate_chapters` 启动时扫描已写但缺摘要的章节
  - 自动调 LLM 生成 2-3 句实际摘要（含死亡/转折等关键事件）
  - 后续章节规划和死亡检测自动受益

- **死亡角色检测** `NEW` — `ContinuityService._extract_dead_characters`
  - 从 actual_summary 用正则识别"处决/斩杀/身亡"等关键词
  - 死亡角色自动加入 `forbidden_breaks`，要求 Writer 用"余部/残部"指代
  - 主角名自动从角色列表 role 字段提取（`_extract_protagonist_names`），不硬编码

- **章节衔接验证器** `NEW`
  - 章节保存后自动比对开头与上章结尾的关键词
  - 无共同关键词时记 warning + decision，帮助发现断裂问题

- **Writer 内容过滤器** `NEW` — `_sanitize_chapter_text`
  - 自动过滤 `【系统】`、`【检测到...】` 等游戏 UI 泄漏
  - 过滤 `忠诚度：71→79`、`【兵煞值+8】` 等数值变化
  - 保留故事性标记如 `【叮！】`

- **章节衔接硬约束**
  - Writer 第一场景强制注入 5 条衔接规则（禁止跳时间/空间/事件）
  - 首场景上下文标签从"前文回顾"改为"上章结尾 — 必须从这里接续"
  - 首场景上下文窗口从 4000 字扩大到 6000 字
  - PlotPlanner 要求第一场景 title/summary 必须体现"承接上章"

- **201 条防御性测试**
  - `test_taskqueue_defensive.py` 线程安全 + key 白名单 + limit 边界
  - `test_pipeline_defensive.py` 空 YAML + 音频/字幕不匹配 + 资源泄漏
  - `test_llm_tts_defensive.py` Ollama SDK + 事件循环 TTS + LLM 错误
  - `test_novel_pipeline_defensive.py` state 保持 + 章节去重 + 重写上限
  - `test_novel_services_defensive.py` DB 缓存 + 搜索 .txt + 异常清理
  - `test_media_defensive.py` Sora 重试 + 嵌套 JSON + 资源清理

### 修复 — 全局 Bug 审查（30+ 处）

- **线程安全** — `workers.py` `_env_lock` 保护环境变量，防止多任务并发时 API key 互相污染
- **Worker env var 恢复** — 清理时恢复原值而非删除，防止启动时 export 的 key 被删
- **LLM provider fallback** — `create_llm_client` 指定 provider 失败时自动回退到 auto-detect
- **API key 白名单** — `helpers.py` 补齐 Kling/Seedance/MiniMax/Jimeng/Together 5 个视频 key
- **TTS 事件循环** — FastAPI 内调用 `asyncio.run()` 改用 ThreadPoolExecutor 规避
- **Ollama SDK 兼容** — 新版 `ChatResponse` 对象和旧版 dict 响应都支持
- **Sora 下载重试** — 恢复 3 次指数退避重试逻辑
- **JSON 解析** — `idea_planner` 支持嵌套 JSON + 捕获贪婪正则异常
- **Pipeline 资源泄漏** — videogen 连接用 try/finally 关闭
- **audio/srt 校验** — 断点续传时数量不匹配报错而非静默截断
- **API limit 边界** — `list_tasks` 上限 200 防 DoS
- **checkpoint O(n²) I/O** — TTS 阶段 `save=False` 减少完整 JSON 写入
- **章节生成每章重复第 19 章开头** — `writer_node` 按 `chapter_number` 找前一章，不再用 `chapters_done[-1]`
- **chapters 列表去重** — 新生成的章节替换旧条目（含 full_text），而非跳过
- **ReAct 工具调用泄漏** — 截断的 tool-call JSON 请求重试而非当成最终输出
- **章节标题垃圾** — `_sanitize_title` 过滤 `\n`、引号、prompt 指令片段
- **规划任务"已提交"卡住** — `planMut.reset()` 清除成功状态 + 查询失效刷新
- **Agent 对话错误不显示** — 修复 optimistic 合并逻辑，错误消息保留
- **novel_memory close 丢失图谱** — `close()` 前自动 `save()`
- **obligation_tracker 两次 DB 调用** — 合并为单事务
- **continuity regex 跨句** — 限制在单句内匹配（`[^。！？\n]`）
- **video_assembler SRT 路径特殊字符** — 复制到 tmp_dir 规避
- **video_assembler drawtext 过度转义** — 从 4 层降为正确的 1 层
- **plot_planner rhythm 越界** — 加保护 `rhythm[i] if i < len(rhythm) else rhythm[-1]`
- **character_tracker 多角色同描述** — 用 `pop(0)` 按序分配

### 通用化 — 移除所有硬编码的小说特定内容

- `continuity_service` 死亡检测移除硬编码主角名，改为从角色列表自动提取
- `state_writeback` 示例和地点词移除小说专属内容
- `consistency_checker` / `character_service` / `agent_chat` 示例改为通用占位符
- `pipeline` 大纲约束 prompt 不再引用特定小说角色名

### 变更

- 版本号从 1.1.0 升级至 1.2.0
- 测试总数从 3420 → **3692**（+272 个新测试）

---

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
