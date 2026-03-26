# ReAct Agent Framework + Prompt Registry - 任务拆分

## 任务优先级说明

- **P0**：核心功能，必须实现，阻塞后续开发
- **P1**：重要功能，显著提升用户价值
- **P2**：增强功能，改善用户体验但非必需

---

## Phase 1: Prompt Registry 基础设施（Week 1-2）

### P0-1: 数据模型和数据库表

**任务描述**：创建 Prompt Registry 的数据模型和数据库表结构。

**输入**：
- `src/novel/storage/structured_db.py`（现有存储层）
- `design.md` 中的表结构定义

**输出**：
- `src/prompt_registry/models.py`：Pydantic 数据模型（PromptBlock / PromptTemplate / PromptUsage / FeedbackRecord）
- `src/novel/storage/structured_db.py`：新增 `_ensure_prompt_tables()` 方法，创建 4 个表

**验收标准**：
- 运行 `StructuredDB(db_path)._ensure_prompt_tables()` 后，数据库中存在 4 个表
- 所有索引创建成功（`idx_prompt_blocks_base_id` 等）
- 运行 `pytest tests/prompt_registry/test_models.py` 通过（测试 Pydantic 模型序列化/反序列化）

**依赖**：无

**预计工时**：4 小时

---

### P0-2: PromptRegistry 核心类（CRUD 操作）

**任务描述**：实现 `PromptRegistry` 类的基础 CRUD 操作。

**输入**：
- `src/prompt_registry/models.py`（P0-1 输出）
- `design.md` 中的 `PromptRegistry` 类设计

**输出**：
- `src/prompt_registry/registry.py`：实现以下方法
  - `create_block()` / `get_block()` / `get_active_block()` / `get_block_versions()` / `rollback_block()`
  - `create_template()` / `get_template()` / `get_template_by_agent_scenario()`
  - `record_usage()` / `update_quality_score()`

**验收标准**：
- 创建 block 后，版本号自动递增（v1 → v2）
- 同一 base_id 只有一个 active=True 的 block
- 回滚 block 后，旧版本 active=True，当前版本 active=False
- 运行 `pytest tests/prompt_registry/test_registry.py` 通过（15+ 测试用例）

**依赖**：P0-1

**预计工时**：8 小时

---

### P0-3: Prompt 组装逻辑

**任务描述**：实现 `get_prompt()` 方法，根据 agent 和 scenario 组装完整 prompt。

**输入**：
- `src/prompt_registry/registry.py`（P0-2 输出）

**输出**：
- `PromptRegistry.get_prompt(agent_name, scenario, context)` 方法

**验收标准**：
- 调用 `get_prompt("Writer", "battle", {"last_weaknesses": ["重复"]})` 返回拼接后的 prompt
- Prompt 中包含所有 block（按 block_order 顺序）
- Context 变量正确替换（如 `{last_weaknesses}` → "- 重复"）
- 场景特化 block 优先级高于通用 block（如 `battle_craft` 优先于 `craft_technique`）
- 运行 `pytest tests/prompt_registry/test_get_prompt.py` 通过（10+ 测试用例）

**依赖**：P0-2

**预计工时**：4 小时

---

### P0-4: Prompt 迁移脚本

**任务描述**：将现有硬编码 prompt 迁移到数据库。

**输入**：
- `src/novel/agents/writer.py`（`_ANTI_AI_FLAVOR` 等常量）
- `src/novel/templates/style_presets.py`（风格预设）
- `design.md` 中的迁移方案

**输出**：
- `scripts/migrate_prompts.py`：迁移脚本

**验收标准**：
- 运行脚本后，数据库中存在以下 block：
  - `anti_ai_flavor_v1`（类型：anti_pattern）
  - `anti_repetition_v1`（类型：anti_pattern）
  - `narrative_logic_v1`（类型：anti_pattern）
  - `character_name_lock_v1`（类型：anti_pattern）
  - `wuxia_classical_system_v1`（类型：system_instruction，从 style_presets 迁移）
  - `webnovel_shuangwen_system_v1`（类型：system_instruction）
  - ...（至少 15 个 block）
- 为 Writer 创建默认 template：`writer_default_template`
- 为 QualityReviewer 创建默认 template：`quality_reviewer_default_template`
- 运行 `pytest tests/prompt_registry/test_migration.py` 通过（验证迁移数据完整性）

**依赖**：P0-3

**预计工时**：6 小时

---

### P0-5: Writer 集成 Prompt Registry

**任务描述**：修改 `Writer` 类，支持从 Prompt Registry 读取 prompt（可选功能，默认仍用硬编码）。

**输入**：
- `src/novel/agents/writer.py`（现有代码）
- `src/prompt_registry/registry.py`（P0-3 输出）

**输出**：
- `Writer.enable_prompt_registry(registry, feedback_injector)` 方法
- 修改 `Writer._build_scene_prompt()`，如果启用了 Prompt Registry，则从数据库读取 prompt

**验收标准**：
- 默认情况下，Writer 行为不变（仍用硬编码 prompt）
- 调用 `writer.enable_prompt_registry(registry, feedback_injector)` 后，prompt 从数据库读取
- 生成的 prompt 与硬编码版本一致（对比文本内容）
- 运行 `pytest tests/novel/test_writer_prompt_registry.py` 通过（5+ 测试用例）

**依赖**：P0-4

**预计工时**：4 小时

---

### P1-6: QualityReviewer 集成 Prompt Registry

**任务描述**：修改 `QualityReviewer` 类，支持从 Prompt Registry 读取 prompt。

**输入**：
- `src/novel/agents/quality_reviewer.py`（现有代码）
- `src/prompt_registry/registry.py`（P0-3 输出）

**输出**：
- `QualityReviewer.enable_prompt_registry(registry)` 方法
- 修改评分 prompt 读取逻辑

**验收标准**：
- 默认情况下，QualityReviewer 行为不变
- 启用 Prompt Registry 后，评分 prompt 从数据库读取
- 运行 `pytest tests/novel/test_reviewer_prompt_registry.py` 通过

**依赖**：P0-5

**预计工时**：3 小时

---

### P2-7: PlotPlanner 集成 Prompt Registry

**任务描述**：修改 `PlotPlanner` 类，支持从 Prompt Registry 读取 prompt。

**输入**：
- `src/novel/agents/plot_planner.py`（现有代码）

**输出**：
- `PlotPlanner.enable_prompt_registry(registry)` 方法

**验收标准**：
- 大纲生成 prompt 从数据库读取
- 运行 `pytest tests/novel/test_planner_prompt_registry.py` 通过

**依赖**：P1-6

**预计工时**：3 小时

---

## Phase 2: ReAct Agent Framework（Week 3-4）

### P0-8: ReactAgent 基类实现

**任务描述**：实现通用的 ReAct 循环引擎。

**输入**：
- `design.md` 中的 `ReactAgent` 类设计
- `src/novel/services/agent_chat.py`（参考现有 tool-calling 循环）

**输出**：
- `src/react/__init__.py`
- `src/react/agent.py`：实现以下方法
  - `register_tool(name, func, description, parameters)`
  - `_format_tools_for_prompt()`
  - `_execute_action(action)`
  - `run(initial_prompt, max_iterations, budget_mode)`

**验收标准**：
- 注册 3 个工具后，`_format_tools_for_prompt()` 返回格式正确的工具描述
- 调用 `_execute_action({"tool": "test_tool", "args": {}})` 正确执行工具
- 运行 `run()` 进入循环，LLM 依次调用工具，最终调用 `submit` 结束
- 达到 max_iterations 后强制结束
- budget_mode=True 时，跳过 check 类工具
- 运行 `pytest tests/react/test_agent.py` 通过（20+ 测试用例）

**依赖**：无

**预计工时**：10 小时

---

### P0-9: WriterTools 工具集实现

**任务描述**：为 Writer 提供 ReAct 模式的工具集。

**输入**：
- `src/novel/agents/writer.py`（现有逻辑）
- `design.md` 中的 `WriterTools` 设计

**输出**：
- `src/novel/tools/react_tools/__init__.py`
- `src/novel/tools/react_tools/writer_tools.py`：实现以下工具
  - `generate_scene(outline, characters, world, context) -> str`
  - `check_repetition(text, previous_texts) -> dict`
  - `check_logic(text, context) -> dict`
  - `check_character_names(text, character_list) -> dict`
  - `revise_scene(text, issues) -> str`
  - `submit(text) -> str`

**验收标准**：
- `check_repetition()` 能检测出文本中与前文重复的句子（Jaccard 相似度）
- `check_logic()` 能检测出叙事逻辑问题（事件闭环、角色去向）
- `check_character_names()` 能检测出角色名称不一致（如 "小玲" vs "李小玲"）
- `revise_scene()` 能根据 issues 列表调用 LLM 修改文本
- 运行 `pytest tests/novel/tools/test_writer_tools.py` 通过（15+ 测试用例）

**依赖**：P0-8

**预计工时**：12 小时

---

### P0-10: WriterReactAgent 实现

**任务描述**：创建基于 ReAct 框架的 Writer Agent。

**输入**：
- `src/react/agent.py`（P0-8 输出）
- `src/novel/tools/react_tools/writer_tools.py`（P0-9 输出）
- `design.md` 中的 `WriterReactAgent` 设计

**输出**：
- `src/novel/agents/writer_react.py`：实现 `WriterReactAgent` 类
  - 继承 `ReactAgent`
  - 注册 6 个工具（generate_scene / check_repetition / check_logic / check_character_names / revise_scene / submit）
  - 实现 `generate_chapter()` 方法

**验收标准**：
- 调用 `agent.generate_chapter(react_mode=True)` 后，LLM 依次调用：
  1. `generate_scene` 生成初稿
  2. `check_repetition` 检查重复
  3. `revise_scene` 修改（如有问题）
  4. `check_logic` 检查逻辑
  5. `check_character_names` 检查名称
  6. `submit` 提交最终结果
- Loop log 记录每一步的 thinking、action、observation
- 运行 `pytest tests/novel/agents/test_writer_react.py` 通过（10+ 测试用例）

**依赖**：P0-9

**预计工时**：8 小时

---

### P0-11: Writer 集成 ReAct 模式

**任务描述**：修改 `Writer` 类，支持 react_mode 参数。

**输入**：
- `src/novel/agents/writer.py`（现有代码）
- `src/novel/agents/writer_react.py`（P0-10 输出）

**输出**：
- 修改 `Writer.generate_scene()`，增加 `react_mode` 和 `budget_mode` 参数
- 如果 `react_mode=True`，创建 `WriterReactAgent` 并调用
- 如果 `react_mode=False`，保持原有 one-shot 逻辑

**验收标准**：
- 默认 `react_mode=False`，行为与现在完全一致
- `react_mode=True` 时，使用 ReAct 循环生成
- `budget_mode=True` 时，跳过所有 check 工具，LLM 调用次数与 one-shot 相同
- 运行 `pytest tests/novel/test_writer_integration.py` 通过（覆盖 one-shot 和 react 两种模式）

**依赖**：P0-10

**预计工时**：4 小时

---

### P1-12: QualityReviewerTools 工具集实现

**任务描述**：为 QualityReviewer 提供 ReAct 模式的工具集。

**输入**：
- `src/novel/agents/quality_reviewer.py`（现有逻辑）

**输出**：
- `src/novel/tools/react_tools/reviewer_tools.py`：实现以下工具
  - `check_rules(text) -> dict`
  - `check_style(text, target_style) -> dict`
  - `llm_score(text, criteria) -> float`
  - `submit(decision, reason) -> dict`

**验收标准**：
- `check_rules()` 能检测规则硬指标（无需 LLM，零成本）
- `check_style()` 能检测风格一致性（如句子长度、对话占比）
- `llm_score()` 能调用 LLM 打分（0-10 分）
- 运行 `pytest tests/novel/tools/test_reviewer_tools.py` 通过

**依赖**：P0-8

**预计工时**：6 小时

---

### P2-13: QualityReviewerReactAgent 实现

**任务描述**：创建基于 ReAct 框架的 QualityReviewer Agent。

**输入**：
- `src/react/agent.py`（P0-8 输出）
- `src/novel/tools/react_tools/reviewer_tools.py`（P1-12 输出）

**输出**：
- `src/novel/agents/quality_reviewer_react.py`：实现 `QualityReviewerReactAgent` 类

**验收标准**：
- 调用 `agent.review_chapter(react_mode=True)` 后，LLM 依次调用：
  1. `check_rules` 规则检查
  2. `check_style` 风格检查
  3. `llm_score` 打分（如果不是 budget_mode）
  4. `submit` 提交评审结果
- 运行 `pytest tests/novel/agents/test_reviewer_react.py` 通过

**依赖**：P1-12

**预计工时**：6 小时

---

## Phase 3: 质量闭环（Week 5-6）

### P0-14: FeedbackInjector 实现

**任务描述**：实现即时反馈注入（上一章问题注入下次生成）。

**输入**：
- `design.md` 中的 `FeedbackInjector` 设计

**输出**：
- `src/prompt_registry/feedback_injector.py`：实现以下方法
  - `save_feedback(novel_id, chapter_number, strengths, weaknesses, overall_score)`
  - `get_last_feedback(novel_id, chapter_number)`
  - `format_feedback_for_prompt(feedback)`

**验收标准**：
- 保存第 5 章反馈后，查询数据库 `feedback_records` 表有记录
- 生成第 6 章时，调用 `get_last_feedback(novel_id, 6)` 返回第 5 章反馈
- `format_feedback_for_prompt()` 返回格式化文本（包含亮点和问题）
- 运行 `pytest tests/prompt_registry/test_feedback_injector.py` 通过（10+ 测试用例）

**依赖**：P0-3

**预计工时**：4 小时

---

### P0-15: QualityReviewer 集成反馈闭环

**任务描述**：修改 `QualityReviewer`，评审完成后保存反馈并回填质量评分。

**输入**：
- `src/novel/agents/quality_reviewer.py`（现有代码）
- `src/prompt_registry/feedback_injector.py`（P0-14 输出）

**输出**：
- `QualityReviewer.enable_feedback_loop(feedback_injector, prompt_registry)` 方法
- 修改 `review_chapter()`，评审完成后调用 `feedback_injector.save_feedback()`
- 如果有 `usage_id`，调用 `prompt_registry.update_quality_score()` 回填评分

**验收标准**：
- 评审第 5 章后，`feedback_records` 表有记录
- `prompt_usage` 表的 `quality_score` 字段被回填
- 运行 `pytest tests/novel/test_reviewer_feedback.py` 通过

**依赖**：P0-14

**预计工时**：3 小时

---

### P0-16: Writer 集成反馈注入

**任务描述**：修改 `Writer`，生成前读取上一章反馈并注入 prompt。

**输入**：
- `src/novel/agents/writer.py`（现有代码）
- `src/prompt_registry/feedback_injector.py`（P0-14 输出）

**输出**：
- 修改 `Writer.generate_scene()`，调用 `feedback_injector.get_last_feedback()` 获取上一章反馈
- 将反馈注入到 `get_prompt()` 的 context 参数

**验收标准**：
- 生成第 6 章时，prompt 中包含第 5 章的 weaknesses
- 验证 `feedback_injection` block 的变量替换正确（`{last_weaknesses}` → 实际问题列表）
- 运行 `pytest tests/novel/test_writer_feedback_injection.py` 通过

**依赖**：P0-15

**预计工时**：3 小时

---

### P1-17: QualityTracker 实现

**任务描述**：实现质量追踪和低分 block 标记。

**输入**：
- `design.md` 中的 `QualityTracker` 设计

**输出**：
- `src/prompt_registry/quality_tracker.py`：实现以下方法
  - `get_block_statistics(base_id)`
  - `analyze_prompt_performance(threshold, min_usage_count)`
  - `get_block_weaknesses(base_id, limit)`

**验收标准**：
- 累计 20 次使用后，`get_block_statistics("dialogue_craft")` 返回平均分
- `analyze_prompt_performance()` 将平均分 < 6.0 的 block 标记 `needs_optimization=True`
- `get_block_weaknesses()` 返回历史 feedback_summary 列表（去重）
- 运行 `pytest tests/prompt_registry/test_quality_tracker.py` 通过（10+ 测试用例）

**依赖**：P0-15

**预计工时**：6 小时

---

### P1-18: 定时任务：分析 Prompt 性能

**任务描述**：创建定时任务脚本，每周分析 prompt 性能。

**输入**：
- `src/prompt_registry/quality_tracker.py`（P1-17 输出）

**输出**：
- `scripts/analyze_prompt_performance.py`：定时任务脚本

**验收标准**：
- 运行脚本后，输出低分 block 列表
- 数据库中低分 block 被标记 `needs_optimization=True`
- 可配置阈值（默认 6.0）和最小样本量（默认 20）

**依赖**：P1-17

**预计工时**：2 小时

---

## Phase 4: 自动优化（Week 7-8）

### P1-19: PromptOptimizer 实现

**任务描述**：实现 LLM 自动生成改进版 prompt。

**输入**：
- `design.md` 中的 `PromptOptimizer` 设计
- `src/prompt_registry/quality_tracker.py`（P1-17 输出）

**输出**：
- `src/prompt_registry/optimizer.py`：实现以下方法
  - `generate_improved_block(base_id)`
  - `approve_improved_block(block_id)`
  - `reject_improved_block(block_id)`
  - `_create_pending_block()`

**验收标准**：
- 调用 `generate_improved_block("dialogue_craft")` 后，LLM 生成改进版
- 改进版 block 状态为 `pending_review`（active=False）
- 批准后，新版本 active=True，旧版本 active=False
- 拒绝后，block 标记 `rejected`
- 运行 `pytest tests/prompt_registry/test_optimizer.py` 通过（10+ 测试用例）

**依赖**：P1-17

**预计工时**：8 小时

---

### P2-20: Gradio 管理界面 - Prompt Block 管理

**任务描述**：创建 Prompt Block 管理页面（查看/编辑/回滚）。

**输入**：
- `src/prompt_registry/registry.py`（P0-2 输出）
- Gradio 现有 UI 代码

**输出**：
- `src/prompt_registry/ui/block_manager.py`：Gradio 页面

**验收标准**：
- 页面展示所有 block，支持按 agent / scenario / active 状态筛选
- 点击 block 可查看详情（内容、版本历史、使用统计）
- 支持在线编辑 block 内容，保存时自动创建新版本
- 支持回滚到历史版本
- 运行 Web UI 验证功能正常

**依赖**：P0-2

**预计工时**：10 小时

---

### P2-21: Gradio 管理界面 - Prompt Template 管理

**任务描述**：创建 Prompt Template 管理页面（查看/编辑/组装）。

**输入**：
- `src/prompt_registry/registry.py`（P0-2 输出）

**输出**：
- `src/prompt_registry/ui/template_manager.py`：Gradio 页面

**验收标准**：
- 页面展示所有 template，支持筛选
- 支持拖拽调整 block_order（可视化编排）
- 支持为不同 scenario 创建特化版本
- 运行 Web UI 验证功能正常

**依赖**：P2-20

**预计工时**：8 小时

---

### P2-22: Gradio 管理界面 - 质量分析看板

**任务描述**：创建质量分析看板（查看 block 统计、待优化列表、改进建议）。

**输入**：
- `src/prompt_registry/quality_tracker.py`（P1-17 输出）
- `src/prompt_registry/optimizer.py`（P1-19 输出）

**输出**：
- `src/prompt_registry/ui/quality_dashboard.py`：Gradio 页面

**验收标准**：
- 页面展示所有 block 的质量统计（使用次数、平均分、趋势图）
- 展示待优化 block 列表，点击可查看历史 weaknesses
- 支持生成改进建议，对比原版和改进版，批准或拒绝
- 运行 Web UI 验证功能正常

**依赖**：P1-19

**预计工时**：12 小时

---

## Phase 5: 集成测试和优化（Week 9）

### P0-23: 端到端集成测试

**任务描述**：完整流程测试（创建小说 → 生成章节 → 评审 → 反馈闭环 → 自动优化）。

**输入**：
- 所有前置模块

**输出**：
- `tests/novel/test_pipeline_react_e2e.py`：端到端测试

**验收标准**：
- 测试流程：
  1. 创建小说项目
  2. 生成 5 章（ReAct 模式）
  3. 每章评审，保存反馈
  4. 第 2-5 章生成时，prompt 中包含上一章反馈
  5. 查询 `prompt_usage` 表，验证有 5 条记录
  6. 运行 `analyze_prompt_performance()`，验证低分 block 被标记
  7. 生成改进版 prompt，批准上线
  8. 生成第 6 章，使用新版本 prompt
  9. 验证第 6 章质量分 > 前 5 章平均分
- 运行 `pytest tests/novel/test_pipeline_react_e2e.py` 通过

**依赖**：P0-16, P1-19

**预计工时**：8 小时

---

### P1-24: 性能优化和监控

**任务描述**：优化数据库查询、增加缓存、添加监控指标。

**输入**：
- 所有前置模块

**输出**：
- 数据库索引优化
- `get_prompt()` 增加 LRU 缓存
- 异步 `record_usage()` 队列
- 日志记录关键指标（prompt 使用量、质量评分趋势、ReAct 循环效率）

**验收标准**：
- `get_prompt()` 调用延迟 < 100ms（测量 100 次平均值）
- `record_usage()` 不阻塞生成流程（异步插入）
- 运行 10 章生成后，查看日志有完整的指标记录
- 运行 `pytest tests/prompt_registry/test_performance.py` 通过（性能基准测试）

**依赖**：P0-23

**预计工时**：6 小时

---

### P2-25: 文档和示例代码

**任务描述**：编写用户文档和示例代码。

**输入**：
- 所有前置模块

**输出**：
- `docs/prompt_registry_guide.md`：用户指南
- `docs/react_agent_guide.md`：ReAct Agent 开发指南
- `examples/writer_react_example.py`：示例代码

**验收标准**：
- 文档覆盖所有核心功能（Prompt Registry / ReAct Agent / 反馈闭环 / 自动优化）
- 示例代码可直接运行，输出符合预期

**依赖**：P0-23

**预计工时**：6 小时

---

## 任务总览

| 阶段 | 任务数 | 总工时 | 关键里程碑 |
|------|--------|--------|-----------|
| Phase 1 | P0-1 ~ P2-7 (7个) | 32h | Prompt Registry 上线，Writer/QualityReviewer 可选启用 |
| Phase 2 | P0-8 ~ P2-13 (6个) | 52h | ReAct 框架上线，Writer 支持 react_mode |
| Phase 3 | P0-14 ~ P1-18 (5个) | 18h | 质量闭环上线，反馈注入生效 |
| Phase 4 | P1-19 ~ P2-22 (4个) | 38h | 自动优化上线，管理界面完成 |
| Phase 5 | P0-23 ~ P2-25 (3个) | 20h | 集成测试通过，性能优化完成 |
| **总计** | **25个任务** | **160h** | **约 4 周（4 人并行）** |

---

## 并行开发建议

### Week 1-2（Phase 1）

**并行路径 1（基础设施）**：
- Task P0-1 → P0-2 → P0-3 → P0-4
- 开发者 A：数据库和 CRUD 操作

**并行路径 2（集成）**：
- Task P0-5 → P1-6 → P2-7
- 开发者 B：Writer/QualityReviewer/PlotPlanner 集成

### Week 3-4（Phase 2）

**并行路径 1（框架）**：
- Task P0-8 → P0-10 → P0-11
- 开发者 A：ReactAgent 基类 + WriterReactAgent

**并行路径 2（工具集）**：
- Task P0-9 → P1-12 → P2-13
- 开发者 B：WriterTools + QualityReviewerTools

### Week 5-6（Phase 3）

**并行路径 1（反馈闭环）**：
- Task P0-14 → P0-15 → P0-16
- 开发者 A：FeedbackInjector + 集成

**并行路径 2（质量追踪）**：
- Task P1-17 → P1-18
- 开发者 B：QualityTracker + 定时任务

### Week 7-8（Phase 4）

**并行路径 1（自动优化）**：
- Task P1-19
- 开发者 A：PromptOptimizer

**并行路径 2（管理界面）**：
- Task P2-20 → P2-21 → P2-22
- 开发者 B：Gradio UI（3 个页面）

### Week 9（Phase 5）

**所有开发者协作**：
- Task P0-23：端到端测试（开发者 A + B）
- Task P1-24：性能优化（开发者 A）
- Task P2-25：文档和示例（开发者 B）

---

## 风险缓解计划

### 高风险任务

**P0-9: WriterTools 工具集实现（12h）**
- **风险**：`check_repetition` 和 `check_logic` 实现复杂度高，可能超时
- **缓解**：
  - 先实现简单版本（规则检查），后续迭代优化为 LLM 检查
  - 如果超时，将 `check_logic` 降级为 P1 任务

**P1-19: PromptOptimizer 实现（8h）**
- **风险**：LLM 生成的改进版质量不稳定
- **缓解**：
  - 增加 prompt 示例（few-shot）提升生成质量
  - 人工审核机制（必须批准才能上线）
  - 如果效果差，暂时关闭自动生成功能

**P2-22: Gradio 管理界面 - 质量分析看板（12h）**
- **风险**：前端开发工作量大，可能超时
- **缓解**：
  - 先实现核心功能（block 列表、统计数据），图表和高级筛选放到 P2
  - 如果时间不足，使用 FastAPI + 简单 HTML 替代 Gradio

---

## 验收清单

### Phase 1 验收（Week 2 结束）

- [ ] 数据库表创建成功（4 个表 + 索引）
- [ ] 迁移脚本运行成功（15+ block + 2 template）
- [ ] Writer 可从 Prompt Registry 读取 prompt（对比硬编码版本一致）
- [ ] 运行 `pytest tests/prompt_registry/` 全部通过（30+ 测试）

### Phase 2 验收（Week 4 结束）

- [ ] ReAct 循环正常工作（LLM 依次调用工具 → submit）
- [ ] Writer ReAct 模式生成章节（包含 thinking/action/observation 日志）
- [ ] Budget mode 跳过 check 工具（LLM 调用次数与 one-shot 相同）
- [ ] 运行 `pytest tests/react/` 和 `pytest tests/novel/agents/` 全部通过（40+ 测试）

### Phase 3 验收（Week 6 结束）

- [ ] 评审完成后，`feedback_records` 表有记录
- [ ] 生成下一章时，prompt 中包含上一章反馈
- [ ] `prompt_usage` 表的 `quality_score` 字段被回填
- [ ] 低分 block 被标记 `needs_optimization=True`
- [ ] 运行 `pytest tests/prompt_registry/test_feedback*.py` 全部通过（20+ 测试）

### Phase 4 验收（Week 8 结束）

- [ ] LLM 生成改进版 prompt（状态为 pending_review）
- [ ] 批准后，新版本 active=True
- [ ] Gradio 管理界面可访问（3 个页面功能正常）
- [ ] 运行 `pytest tests/prompt_registry/test_optimizer.py` 全部通过（10+ 测试）

### Phase 5 验收（Week 9 结束）

- [ ] 端到端测试通过（5 章生成 → 反馈闭环 → 自动优化 → 新版本生效）
- [ ] 性能指标达标（`get_prompt()` < 100ms，异步 `record_usage()` 不阻塞）
- [ ] 文档完成，示例代码可运行
- [ ] **生产环境灰度发布**（10% 流量用 ReAct 模式，监控成本和质量）

---

## 成功指标

### 核心指标（Week 9 结束时测量）

| 指标 | 目标值 | 测量方法 |
|------|--------|---------|
| **质量提升** | ReAct 模式章节质量评分 >= one-shot + 1.0 分 | 生成 20 章（10 章 one-shot + 10 章 ReAct），对比平均分 |
| **成本控制** | Budget mode 成本与 one-shot 持平，react_mode 成本 < 3x | 统计 LLM token 消耗 |
| **迁移进度** | 50% Writer 生成使用 ReAct 模式 | 查询 `prompt_usage` 表 react_mode 使用率 |
| **反馈闭环有效性** | 低分 block 优化后，平均分提升 >= 1.5 分 | 对比优化前后 20 次使用的平均分 |
| **人工审核效率** | 自动生成改进版批准率 >= 60% | 统计批准/拒绝次数 |

### 性能指标（Week 9 结束时测量）

| 指标 | 目标值 | 测量方法 |
|------|--------|---------|
| **Prompt 组装延迟** | < 100ms | 测量 `get_prompt()` 100 次平均值 |
| **ReAct 循环开销** | < 50ms/次 | 测量工具调用 + 日志记录耗时 |
| **异步插入延迟** | 不阻塞生成流程 | 验证 `record_usage()` 立即返回 |

---

## 术语表

| 术语 | 定义 |
|------|------|
| **P0/P1/P2** | 任务优先级：P0=核心功能，P1=重要功能，P2=增强功能 |
| **ReAct 模式** | Reasoning + Acting，LLM 通过"思考-行动-观察"循环解决问题 |
| **One-Shot 模式** | 传统模式，LLM 一次性生成结果，没有自检和修改 |
| **Budget Mode** | 省钱模式，跳过自检和修改步骤，退化为 one-shot |
| **Feedback Injection** | 将上一章的问题注入下次生成的 prompt，即时反馈 |
| **Block 版本控制** | 每次修改 block 内容时自动创建新版本（v1 → v2） |
| **低分 Block** | 平均质量分 < 6.0 的 block，需要优化 |
| **改进版 Prompt** | LLM 根据历史 weaknesses 自动生成的优化版 block |
| **Pending Review** | 改进版 block 状态，需要人工审核才能上线 |
