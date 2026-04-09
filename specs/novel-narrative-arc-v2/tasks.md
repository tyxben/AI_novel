# AI 长篇小说写作模块 - 叙事节奏控制 v2 任务拆分

## 任务组织原则

1. **分阶段实施**：Phase 0（基础设施）→ Phase 1-3（三机制核心功能）→ Phase 4（集成测试）→ Phase 5（优化与迁移）
2. **并行开发**：标注可并行的任务（不同机制、不同文件）
3. **测试先行**：每个功能任务必须附带测试任务
4. **增量验证**：每个 Phase 结束后跑一次集成测试，确保不破坏现有功能

---

## Phase 0: 基础设施（数据模型、模板、工具）

### Task 0.1: 数据模型定义

**任务标题**：实现 `src/novel/models/narrative_control.py` 数据模型

**依赖**：无

**并行**：可与 Task 0.2 并行

**涉及文件**：
- `src/novel/models/narrative_control.py`（新建）

**内容**：
- 实现 6 个 Pydantic 模型：`NarrativeMilestone`, `SystemFailureEvent`, `SystemCapabilityState`, `StrategyElement`, `StrategyTier`, `VolumeProgressReport`
- 所有字段使用 Pydantic 验证（min_length, ge, le, Literal 枚举）
- 支持 `model_dump()` / `model_dump_json()` 序列化

**验收条件**：
- 所有模型可正常实例化
- 字段验证规则生效（如 `priority` 只能是 `critical/high/normal`）
- 无效数据抛出 `ValidationError`
- JSON 序列化/反序列化一致性

**预估复杂度**：S

---

### Task 0.2: 策略分级模板定义

**任务标题**：编写 `src/novel/templates/strategy_tiers.yaml` 策略分级定义

**依赖**：无

**并行**：可与 Task 0.1, 0.3 并行

**涉及文件**：
- `src/novel/templates/strategy_tiers.yaml`（新建）

**内容**：
- 手工编写 7 个 Tier 的定义（Tier 1-7）
- 每个 Tier 包含：`tier_number`, `tier_name`, `description`, `applicable_scales`, `example_elements`（至少 20 个）
- 确保 Tier 1-7 的 `example_elements` 无重复（或重复率 < 10%）
- YAML 格式正确，可被 Python `yaml.safe_load()` 加载

**验收条件**：
- YAML 文件语法正确，加载为 dict
- 7 个 Tier 定义完整，每个 Tier 至少 20 个 `example_elements`
- Tier 1-7 总元素数 >= 150

**预估复杂度**：M

---

### Task 0.3: 策略元素注册表生成脚本

**任务标题**：实现 `src/novel/scripts/generate_strategy_registry.py` 生成策略注册表

**依赖**：Task 0.1（需要 `StrategyElement` 模型）

**并行**：可与 Task 0.2 并行

**涉及文件**：
- `src/novel/scripts/generate_strategy_registry.py`（新建）
- `src/novel/templates/strategy_registry.yaml`（生成）

**内容**：
- 使用 LLM 生成 3 类策略元素：36 计、兵法术语、帝王心术
- 每类使用独立 prompt，temperature=0.5
- 合并所有元素，写入 YAML
- 支持人工审核后再次运行（追加模式）

**验收条件**：
- 脚本可正常运行，生成 `strategy_registry.yaml`
- 注册表包含至少 150 个元素
- 36 计全部录入（36 个）
- 每个元素包含完整字段（element_id, name, tier, description, usage_constraints, keywords）
- 元素按 Tier 分布合理（Tier 1-2 占 30%，Tier 3-5 占 50%，Tier 6-7 占 20%）

**预估复杂度**：M

---

### Task 0.4: 扩展 novel.json Schema

**任务标题**：为 `novel.json` 增加新字段支持

**依赖**：Task 0.1（需要数据模型）

**并行**：可与 Task 0.2, 0.3 并行

**涉及文件**：
- `src/novel/models/novel.py`（修改 `VolumeOutline` 模型）
- `src/novel/pipeline.py`（修改保存逻辑）

**内容**：
- `VolumeOutline` 增加字段：`narrative_milestones: list[NarrativeMilestone]`, `strategy_tier_range: tuple[int, int]`, `settlement_report: VolumeProgressReport | None`
- `Novel` 增加顶层字段：`enable_strategy_ladder: bool`, `system_failure_schedule: list[SystemFailureEvent]`, `system_state: SystemCapabilityState`
- 修改 `NovelPipeline._save_novel()` 确保新字段正确序列化

**验收条件**：
- `VolumeOutline` / `Novel` 模型可正常实例化，包含新字段
- 新字段可序列化到 `novel.json`
- 从 `novel.json` 加载后，新字段值正确恢复
- 向后兼容：旧的 `novel.json`（无新字段）仍可正常加载（新字段取默认值）

**预估复杂度**：S

---

### Task 0.5: 扩展 SQLite Schema

**任务标题**：为 `structured_db.py` 增加 `strategy_usage` 表

**依赖**：无

**并行**：可与 Task 0.1-0.4 并行

**涉及文件**：
- `src/novel/storage/structured_db.py`（修改）

**内容**：
- 在 `StructuredDB.__init__()` 中增加表创建 SQL：
  ```sql
  CREATE TABLE IF NOT EXISTS strategy_usage (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      chapter_number INTEGER NOT NULL,
      element_id TEXT NOT NULL,
      element_name TEXT NOT NULL,
      tier INTEGER NOT NULL,
      matched_keywords TEXT,
      usage_timestamp TEXT NOT NULL
  );
  ```
- 增加索引：`CREATE INDEX IF NOT EXISTS idx_strategy_chapter ON strategy_usage(chapter_number);`

**验收条件**：
- 表创建成功，schema 正确
- 索引创建成功
- 插入测试数据无报错
- 查询测试数据返回正确结果

**预估复杂度**：S

---

## Phase 1: 机制 A — 卷进度预算

### Task 1.1: 里程碑生成逻辑

**任务标题**：实现 `NovelDirector._generate_milestones_for_volume()` 方法

**依赖**：Task 0.1, 0.4

**并行**：可与 Task 1.2, 1.3 并行（不同文件）

**涉及文件**：
- `src/novel/agents/novel_director.py`（修改）

**内容**：
- 实现 `_generate_milestones_for_volume()` 方法
- LLM prompt 设计：根据卷的 `theme/climax/end_hook` 生成 3-5 个里程碑
- 返回 `list[NarrativeMilestone]`
- 在 `generate_outline()` 中调用，为每个卷分配里程碑
- 里程碑存储到 `volume.narrative_milestones`

**验收条件**：
- 为 6 卷小说生成 18-30 个里程碑
- 每个里程碑的 `target_chapter_range` 不重叠度 > 70%
- 80% 的里程碑 `verification_type` 为 `auto_keyword`
- 里程碑存储在 `novel.json` 的 `volumes[].narrative_milestones`
- LLM 调用失败时有 fallback（返回空列表但不崩溃）

**预估复杂度**：M

---

### Task 1.2: 里程碑追踪服务

**任务标题**：实现 `src/novel/services/milestone_tracker.py`

**依赖**：Task 0.1, 0.4

**并行**：可与 Task 1.1, 1.3 并行

**涉及文件**：
- `src/novel/services/milestone_tracker.py`（新建）

**内容**：
- 实现 `MilestoneTracker` 类
- 方法：
  - `get_milestones_for_chapter()`: 获取待办里程碑
  - `check_milestone_completion()`: 检查关键词 / LLM 判定里程碑完成
  - `mark_overdue_milestones()`: 标记逾期里程碑
  - `_mark_milestone_completed()` / `_mark_milestone_overdue()`: 更新状态
- 关键词检查优先（省 token），LLM 判定为备选

**验收条件**：
- 对包含关键词的章节文本，`check_milestone_completion()` 返回正确的里程碑 ID
- 对不包含关键词的章节，返回空列表
- LLM 判定模式正常工作（mock LLM 测试）
- 逾期里程碑正确标记为 `status: "overdue"`
- 已完成里程碑标记为 `status: "completed"`，记录 `completed_at_chapter`

**预估复杂度**：M

---

### Task 1.3: 进度注入到 continuity_brief

**任务标题**：扩展 `ContinuityService` 增加卷进度提取

**依赖**：Task 0.1, 0.4

**并行**：可与 Task 1.1, 1.2 并行

**涉及文件**：
- `src/novel/services/continuity_service.py`（修改）

**内容**：
- `generate_brief()` 增加参数：`novel_data: dict | None`
- 增加方法 `_extract_volume_progress()`：
  - 提取当前卷、已用章节、剩余章节
  - 提取已完成 / 待完成 / 逾期里程碑
  - 计算 `progress_health`（on_track / behind_schedule / critical）
- `format_for_prompt()` 增加卷进度格式化为中文提示块
- 提示块长度控制在 < 500 字

**验收条件**：
- `continuity_brief` 包含完整 `volume_progress` 字段
- `progress_health` 计算正确：
  - 无逾期且完成率 >= 50% → `on_track`
  - 无逾期但完成率 < 50% → `behind_schedule`
  - 有逾期 → `critical`
- 格式化的提示块长度 < 500 字
- 提示块包含：当前卷、章节消耗、剩余章节、已完成 / 待完成 / 逾期里程碑、进度状态

**预估复杂度**：M

---

### Task 1.4: PlotPlanner 响应进度信号

**任务标题**：修改 `PlotPlanner` 读取卷进度并注入约束 prompt

**依赖**：Task 1.3

**并行**：可与 Task 1.5 并行（不同文件）

**涉及文件**：
- `src/novel/agents/plot_planner.py`（修改）

**内容**：
- `decompose_chapter()` 增加参数：`continuity_brief: dict | None`
- 读取 `continuity_brief.volume_progress`
- 根据 `progress_health` 生成约束 prompt：
  - `on_track`: "当前卷进度正常，本章可正常推进主线或适度展开支线"
  - `behind_schedule`: "卷进度落后，本章必须优先推进待完成里程碑"
  - `critical`: "严重警告：逾期里程碑必须在本章推进"
- 注入到 `_DECOMPOSE_USER` prompt 的 `{volume_progress_constraint}` 占位符
- 修改 `_DECOMPOSE_USER` 模板增加占位符

**验收条件**：
- 当 `progress_health = "critical"` 时，PlotPlanner 生成的场景中至少 1 个场景的 `summary` 明确提及逾期里程碑（人工审查 5 个案例，符合率 >= 80%）
- 当 `progress_health = "on_track"` 时，PlotPlanner 可自由分配场景内容（无额外约束）
- Prompt 注入正确，LLM 收到约束信息

**预估复杂度**：S

---

### Task 1.5: 卷边界强制收束

**任务标题**：扩展 `VolumeSettlement` 增加里程碑收束逻辑

**依赖**：Task 1.2

**并行**：可与 Task 1.4 并行

**涉及文件**：
- `src/novel/services/volume_settlement.py`（修改）

**内容**：
- 扩展 `get_settlement_brief()` 增加里程碑完成度检查
- 新增方法 `settle_volume()`：
  - 生成卷完成度报告（`VolumeProgressReport`）
  - 处理未完成的 `critical` 里程碑：继承到下一卷 或 标记为 `abandoned`
  - 存储报告到 `volume.settlement_report`
- 在 `NovelPipeline.generate_chapters()` 中检测卷结束时调用 `settle_volume()`

**验收条件**：
- 卷末生成的 `settlement_report` 包含里程碑完成度统计（百分比）
- 若卷末有 2 个 `critical` 里程碑未完成，下一卷的 `milestones_pending` 中可见继承的里程碑
- 继承的里程碑标记 `inherited_from_volume`
- 最后一卷的未完成里程碑标记为 `abandoned`

**预估复杂度**：M

---

### Task 1.6: 测试 — 里程碑追踪

**任务标题**：编写 `tests/novel/services/test_milestone_tracker.py` 单元测试

**依赖**：Task 1.2

**涉及文件**：
- `tests/novel/services/test_milestone_tracker.py`（新建）

**内容**：
- `test_keyword_milestone_completion()`: 关键词匹配里程碑检查
- `test_llm_milestone_completion()`: LLM 判定里程碑检查（mock LLM）
- `test_overdue_milestone()`: 逾期里程碑标记
- `test_get_milestones_for_chapter()`: 获取待办里程碑
- 边界条件：空里程碑列表、所有里程碑已完成、chapter_num 超出卷范围

**验收条件**：
- 所有测试通过
- 覆盖正常路径 + 边界条件 + 错误路径
- Mock LLM 返回 `{"completed": true}` 时，里程碑正确标记为完成

**预估复杂度**：S

---

## Phase 2: 机制 B — 系统能力状态机

### Task 2.1: 系统失效排程生成

**任务标题**：实现 `NovelDirector._schedule_system_failures()` 方法

**依赖**：Task 0.1, 0.4

**并行**：可与 Task 2.2 并行

**涉及文件**：
- `src/novel/agents/novel_director.py`（修改）

**内容**：
- 实现 `_schedule_system_failures()` 方法
- 排程策略：
  - 密度：每 20 章 1 次（可配置）
  - 优先高潮前 2-5 章（60% 分布）
  - 避让：第 1-5 章、卷末倒数 2 章、连续 3 章
- 失效模式分布：60% degraded, 20% wrong_data, 15% offline, 5% limited
- 失效原因生成（简单随机 或 LLM 生成）
- 受影响能力选择、恢复条件生成
- 返回 `list[SystemFailureEvent]`
- 在 `generate_outline()` 中调用，存储到 `novel.json` 的 `system_failure_schedule`

**验收条件**：
- 为 200 章小说生成 8-13 个失效窗口
- 失效窗口中 70% 分布在各卷高潮前 2-5 章
- 无连续 3 章都失效的情况
- 第 1-5 章和每卷倒数 2 章无失效
- 失效模式分布符合比例（60/20/15/5）

**预估复杂度**：M

---

### Task 2.2: 系统状态追踪服务

**任务标题**：实现 `src/novel/services/system_state_tracker.py`

**依赖**：Task 0.1, 0.4

**并行**：可与 Task 2.1 并行

**涉及文件**：
- `src/novel/services/system_state_tracker.py`（新建）

**内容**：
- 实现 `SystemStateTracker` 类
- 方法：
  - `get_state_for_chapter()`: 获取指定章节的系统状态（检查是否触发新失效 / 是否恢复）
  - `advance_state()`: 推进系统状态（每章生成后调用）
  - `_activate_failure()`: 激活失效事件
  - `_recover_system()`: 系统恢复
- 状态转移逻辑：读取 `system_failure_schedule`，根据当前章节号触发/恢复
- 记录 `failure_history`

**验收条件**：
- 当 `chapter_num` 匹配排程中的失效章节时，`current_state.current_mode` 变为对应模式
- 当 `chapter_num >= recovery_chapter` 时，`current_state.current_mode` 恢复为 `full`
- `failure_history` 正确记录历史失效
- 状态更新写入 `novel.json` 的 `system_state`

**预估复杂度**：M

---

### Task 2.3: PlotPlanner 读取失效排程

**任务标题**：修改 `PlotPlanner` 读取系统状态并注入约束 prompt

**依赖**：Task 2.2

**并行**：可与 Task 2.4 并行

**涉及文件**：
- `src/novel/agents/plot_planner.py`（修改）

**内容**：
- `decompose_chapter()` 增加参数：`system_state: SystemCapabilityState | None`
- 读取 `system_state.current_mode` 和 `affected_capabilities`
- 若系统失效（`mode != "full"`），生成系统状态约束 prompt
- 注入到 `_DECOMPOSE_USER` prompt 的 `{system_constraint}` 占位符
- 约束要求：至少 1 个场景体现系统失效困境

**验收条件**：
- 当系统失效时，PlotPlanner 生成的场景中至少 1 个场景的 `summary` 明确提及系统失效或功能受限（人工审查 5 个案例，符合率 >= 80%）
- `wrong_data` 模式下，场景包含"数据误导→后果"因果链
- Prompt 注入正确

**预估复杂度**：S

---

### Task 2.4: Writer 禁止使用失效功能

**任务标题**：修改 `Writer` 注入系统状态约束到 prompt

**依赖**：Task 2.2

**并行**：可与 Task 2.3 并行

**涉及文件**：
- `src/novel/agents/writer.py`（修改）

**内容**：
- `write_scene()` 增加参数：`system_state: SystemCapabilityState | None`
- 若系统失效，生成禁用功能列表
- 注入到 Writer 系统 prompt 的约束部分
- 约束明确：不允许使用禁用功能，不允许出现"系统扫描显示"等描述（针对禁用功能）

**验收条件**：
- 系统失效章节中，Writer 生成的文本不包含禁用功能关键词（如失效"地图扫描"时，文本不包含"系统扫描显示敌军位置"）
- 人工审查 5 个案例，符合率 >= 90%

**预估复杂度**：S

---

### Task 2.5: ConsistencyChecker 验证系统约束

**任务标题**：扩展 `ConsistencyChecker` 增加系统约束检查

**依赖**：Task 2.2

**并行**：可与 Task 2.3, 2.4 并行

**涉及文件**：
- `src/novel/agents/consistency_checker.py`（修改）

**内容**：
- `check_chapter()` 增加参数：`system_state: SystemCapabilityState | None`
- 若系统失效，检查章节文本是否包含禁用功能关键词
- 检查上下文是否是"系统失效"相关描述（允许提及失效本身）
- 违规时标记为 `system_constraint_violation`，严重度 `high`

**验收条件**：
- 对人工植入的违规使用（如失效期间写"系统扫描成功"），检测准确率 >= 90%（5 个案例中检出 >= 4.5 个）
- 允许"系统失效""无法使用"等描述失效本身的文本（不误报）

**预估复杂度**：S

---

### Task 2.6: 测试 — 系统状态追踪

**任务标题**：编写 `tests/novel/services/test_system_state_tracker.py` 单元测试

**依赖**：Task 2.2

**涉及文件**：
- `tests/novel/services/test_system_state_tracker.py`（新建）

**内容**：
- `test_activate_failure()`: 失效事件激活
- `test_recover_system()`: 系统恢复
- `test_failure_history()`: 历史记录
- `test_get_state_for_chapter()`: 获取章节状态
- 边界条件：空排程、连续失效、恢复条件为 `None`

**验收条件**：
- 所有测试通过
- 覆盖正常路径 + 边界条件

**预估复杂度**：S

---

## Phase 3: 机制 C — 策略复杂度阶梯

### Task 3.1: 策略元素选择服务

**任务标题**：实现 `src/novel/services/strategy_selector.py`

**依赖**：Task 0.1, 0.2, 0.3

**并行**：可与 Task 3.2 并行

**涉及文件**：
- `src/novel/services/strategy_selector.py`（新建）

**内容**：
- 实现 `StrategySelector` 类
- 加载 `strategy_registry.yaml`，解析为 `list[StrategyElement]`
- 方法 `select_elements_for_chapter()`：
  - 输入：`tier_range`, `recent_chapters_usage`, `current_context`, `count`
  - 筛选符合 Tier 的元素
  - 排除近期使用的元素（近 5 章）
  - 过滤不满足 `usage_constraints` 的元素
  - 加权随机选择（中位 Tier 概率更高）
  - 返回 `list[StrategyElement]`

**验收条件**：
- 对 `tier_range = [3, 5]`，选出的元素 Tier 在 3-5 之间
- 近期使用的元素不被选中（排除正确）
- `usage_constraints` 过滤正确（简单示例：需要 3 个区域但只有 1 个，元素被排除）
- 选中元素数量 <= `count`

**预估复杂度**：M

---

### Task 3.2: Tier 范围映射

**任务标题**：修改 `NovelDirector` 为每个卷分配 Tier 范围

**依赖**：Task 0.4

**并行**：可与 Task 3.1 并行

**涉及文件**：
- `src/novel/agents/novel_director.py`（修改）

**内容**：
- 在 `generate_outline()` 中，为每个卷分配 `strategy_tier_range`
- 映射规则：前 1/3 卷 [1, 3]，中 1/3 卷 [3, 5]，后 1/3 卷 [5, 7]
- 存储到 `volume.strategy_tier_range`

**验收条件**：
- 为 6 卷小说分配的 Tier 范围呈递增趋势
- 相邻卷的 Tier 范围有 1-2 级重叠
- 第 1 卷的 `min_tier` = 1，最后一卷的 `max_tier` = 7

**预估复杂度**：S

---

### Task 3.3: PlotPlanner 章节级策略元素分配

**任务标题**：修改 `PlotPlanner` 抽取策略元素并注入 prompt

**依赖**：Task 3.1

**并行**：可与 Task 3.4 并行

**涉及文件**：
- `src/novel/agents/plot_planner.py`（修改）

**内容**：
- `decompose_chapter()` 增加参数：`enable_strategy_ladder: bool`, `recent_strategy_usage: list[str]`
- 若 `enable_strategy_ladder = True`：
  - 调用 `StrategySelector.select_elements_for_chapter()`
  - 抽取 1-2 个策略元素
  - 注入到 `_DECOMPOSE_USER` prompt 的 `{strategy_section}` 占位符
- 返回结果附带 `required_strategy_elements`

**验收条件**：
- PlotPlanner 生成的场景中，至少 1 个场景的 `summary` 包含 `required_strategy_elements` 中的关键词（人工审查 5 个案例，符合率 >= 80%）
- 近 5 章内不出现重复的策略元素（检查 10 章样本，重复率 < 10%）
- 策略元素的 Tier 与卷的 `strategy_tier_range` 匹配

**预估复杂度**：M

---

### Task 3.4: Writer 强制使用策略元素

**任务标题**：修改 `Writer` 注入策略元素约束到 prompt

**依赖**：Task 3.1

**并行**：可与 Task 3.3 并行

**涉及文件**：
- `src/novel/agents/writer.py`（修改）

**内容**：
- `write_scene()` 增加参数：`required_strategy_elements: list[dict] | None`
- 若有策略元素，生成策略约束 prompt
- 注入到 Writer 系统 prompt
- 约束要求：至少 1 个场景明确使用策略，不生硬说教，有因果逻辑

**验收条件**：
- 章节文本中至少包含 `required_strategy_elements` 的 1 个关键词（关键词检查，覆盖 10 章样本，命中率 >= 90%）

**预估复杂度**：S

---

### Task 3.5: 策略使用追踪服务

**任务标题**：实现 `src/novel/services/strategy_usage_tracker.py`

**依赖**：Task 0.5

**并行**：可与 Task 3.1-3.4 并行

**涉及文件**：
- `src/novel/services/strategy_usage_tracker.py`（新建）

**内容**：
- 实现 `StrategyUsageTracker` 类
- 方法：
  - `record_usage()`: 记录本章策略使用（基于关键词匹配）
  - `get_recent_usage()`: 获取近 N 章使用的策略元素 ID
  - `generate_report()`: 生成策略使用统计报告（Tier 分布、36 计覆盖率、重复率）
- 数据存储到 `strategy_usage` 表

**验收条件**：
- `record_usage()` 正确写入数据库
- `get_recent_usage()` 返回近 5 章使用的元素 ID
- `generate_report()` 包含：Tier 分布、36 计覆盖率、重复率、总使用次数
- 对生成 50 章的小说，36 计覆盖率 >= 60%（至少用了 21 计）

**预估复杂度**：M

---

### Task 3.6: QualityReviewer 检查策略元素使用

**任务标题**：扩展 `QualityReviewer` 增加策略元素检查

**依赖**：Task 3.1

**并行**：可与 Task 3.5 并行

**涉及文件**：
- `src/novel/agents/quality_reviewer.py`（修改）

**内容**：
- `review_chapter()` 增加参数：`required_strategy_elements: list[dict] | None`
- 若有策略元素，检查章节文本是否包含关键词
- 若无关键词，扣分并标记"策略要求未满足"

**验收条件**：
- QualityReviewer 对人工植入的"缺失策略"章节（有 `required_strategy_elements` 但文本无关键词），检测准确率 >= 85%（5 个案例中检出 >= 4.25 个）

**预估复杂度**：S

---

### Task 3.7: 主题门控

**任务标题**：实现主题检测逻辑，自动启用/禁用策略阶梯

**依赖**：Task 0.4

**并行**：可与 Task 3.1-3.6 并行

**涉及文件**：
- `src/novel/agents/novel_director.py`（修改）

**内容**：
- 在 `analyze_input()` 中增加 `_detect_strategy_theme()` 方法
- 检测逻辑：关键词匹配 + 题材白名单
- 返回 `enable_strategy_ladder: bool`
- 存储到 `novel.json` 的 `enable_strategy_ladder`

**验收条件**：
- 对战争题材小说（主题包含"战争""兵法"等关键词），`enable_strategy_ladder` = True
- 对言情题材小说（主题"都市霸总爱上我"），`enable_strategy_ladder` = False
- 检测准确率 >= 90%（10 个不同题材样本）

**预估复杂度**：S

---

### Task 3.8: 测试 — 策略选择器

**任务标题**：编写 `tests/novel/services/test_strategy_selector.py` 单元测试

**依赖**：Task 3.1

**涉及文件**：
- `tests/novel/services/test_strategy_selector.py`（新建）

**内容**：
- `test_select_elements_tier_filter()`: Tier 范围过滤
- `test_select_elements_exclude_recent()`: 排除近期使用
- `test_select_elements_constraints()`: usage_constraints 过滤
- `test_select_elements_weighted_random()`: 加权随机（中位 Tier 概率更高）
- 边界条件：空注册表、tier_range 无可用元素

**验收条件**：
- 所有测试通过
- 覆盖正常路径 + 边界条件

**预估复杂度**：S

---

## Phase 4: 集成与测试

### Task 4.1: Pipeline 集成三机制

**任务标题**：在 `NovelPipeline` 中集成三机制的调用

**依赖**：Task 1.1-1.5, 2.1-2.5, 3.1-3.6

**涉及文件**：
- `src/novel/pipeline.py`（修改）

**内容**：
- 在 `generate_chapters()` 每章生成前：
  - 调用 `SystemStateTracker.get_state_for_chapter()`
  - 调用 `StrategyUsageTracker.get_recent_usage()`
  - 将 `novel_data`, `system_state`, `recent_strategy_usage` 传递给 PlotPlanner / Writer
- 每章生成后：
  - 调用 `MilestoneTracker.check_milestone_completion()`
  - 调用 `MilestoneTracker.mark_overdue_milestones()`
  - 调用 `SystemStateTracker.advance_state()`
  - 调用 `StrategyUsageTracker.record_usage()`
- 卷结束时：
  - 调用 `VolumeSettlement.settle_volume()`

**验收条件**：
- Pipeline 正常运行，三机制无报错
- 生成 10 章后，检查 `novel.json`：
  - 里程碑状态正确更新
  - 系统状态正确更新
  - 策略使用记录写入数据库
- 卷结束后，`settlement_report` 正确生成

**预估复杂度**：M

---

### Task 4.2: 端到端集成测试（新建项目）

**任务标题**：编写 `tests/novel/integration/test_narrative_arc.py` 集成测试

**依赖**：Task 4.1

**涉及文件**：
- `tests/novel/integration/test_narrative_arc.py`（新建）

**内容**：
- `test_full_pipeline_with_narrative_arc()`: 创建项目 → 生成 10 章 → 验证三机制
- 验证点：
  - 大纲阶段：里程碑、失效排程、Tier 范围生成
  - 生成阶段：里程碑完成检查、系统状态转移、策略使用记录
  - 卷结束：settlement_report 生成
- Mock LLM 返回固定响应，确保测试稳定

**验收条件**：
- 测试通过
- 覆盖完整流程：大纲 → 生成 10 章 → 验证三机制数据正确

**预估复杂度**：L

---

### Task 4.3: 端到端集成测试（非战争题材）

**任务标题**：测试主题门控，验证非战争题材禁用策略阶梯

**依赖**：Task 3.7, 4.1

**涉及文件**：
- `tests/novel/integration/test_narrative_arc.py`（扩展）

**内容**：
- `test_non_strategy_theme()`: 创建言情题材项目 → 验证 `enable_strategy_ladder = False`
- 验证点：
  - `novel.json` 的 `enable_strategy_ladder` = False
  - 生成章节时，PlotPlanner 无策略元素约束
  - 策略使用记录表为空
  - 卷进度和系统失效仍然正常工作

**验收条件**：
- 测试通过
- 言情题材项目无策略阶梯污染

**预估复杂度**：M

---

### Task 4.4: 三机制协同触发验证

**任务标题**：验证高潮章节三机制协同触发

**依赖**：Task 4.1

**涉及文件**：
- `tests/novel/integration/test_narrative_arc.py`（扩展）

**内容**：
- `test_synergy_at_climax()`: 创建项目 → 生成到卷高潮章节 → 验证三机制协同
- 验证点：
  - 高潮前 2-5 章有系统失效
  - 高潮章节有最高 Tier 策略元素
  - 高潮前有待完成的 `critical` 里程碑
- 人工审查生成的高潮章节，张力评分

**验收条件**：
- 高潮章节满足"系统失效 + 高 Tier 策略 + 里程碑待完成"三条件
- 人工阅读高潮章节，张力评分 >= 7/10

**预估复杂度**：M

---

## Phase 5: 优化与迁移

### Task 5.1: Token 消耗优化

**任务标题**：优化三机制的 token 消耗

**依赖**：Task 4.1

**并行**：可与 Task 5.2, 5.3 并行

**涉及文件**：
- `src/novel/services/milestone_tracker.py`（优化）
- `src/novel/services/continuity_service.py`（优化）

**内容**：
- 里程碑验证优先用关键词，LLM 判定比例控制在 < 25%
- `continuity_brief` 的 `volume_progress` 提示块长度 < 500 字
- 系统失效排程在大纲阶段一次性生成，后续章节只读取
- 策略元素抽取无 LLM 调用（纯随机 + 过滤）

**验收条件**：
- 生成 10 章样本，对比启用/未启用三机制的 token 消耗，增量 < 2500 tokens/章
- 里程碑验证中，关键词匹配覆盖率 >= 75%

**预估复杂度**：M

---

### Task 5.2: 策略使用统计报告

**任务标题**：生成项目级策略使用统计报告

**依赖**：Task 3.5

**并行**：可与 Task 5.1, 5.3 并行

**涉及文件**：
- `src/novel/services/strategy_usage_tracker.py`（扩展）
- `src/novel/pipeline.py`（调用报告生成）

**内容**：
- 扩展 `StrategyUsageTracker.generate_report()` 生成详细报告
- 报告包含：Tier 分布、36 计覆盖率、策略重复率、平均 Tier 曲线（每 10 章）
- 报告存储到 `workspace/novels/{novel_id}/strategy_report.json`
- 在项目完成时自动生成报告

**验收条件**：
- 报告包含 Tier 分布、36 计覆盖率、平均 Tier 曲线
- 对生成 50 章的小说，36 计覆盖率 >= 60%
- 策略重复率 < 15%

**预估复杂度**：S

---

### Task 5.3: 迁移现有项目

**任务标题**：实现 `novel migrate-narrative-arc` 命令，支持现有项目迁移

**依赖**：Task 4.1

**并行**：可与 Task 5.1, 5.2 并行

**涉及文件**：
- `main.py`（新增 CLI 命令）
- `src/novel/scripts/migrate_narrative_arc.py`（新建）

**内容**：
- 新增 CLI 命令：`python main.py novel migrate-narrative-arc workspace/novels/novel_xxx`
- 迁移逻辑：
  1. 加载现有 `novel.json`
  2. 为现有卷生成里程碑（LLM 根据 `theme/climax` 生成）
  3. 对已生成章节批量检查里程碑完成情况（LLM 回顾 + 关键词检查）
  4. 为剩余章节重新排程系统失效（避开已生成章节）
  5. 为剩余章节分配策略 Tier 范围
  6. 保存到 `novel.json`
- 输出迁移报告（已完成 / 未完成里程碑、剩余章节排程）

**验收条件**：
- 对 `novel_12e1c974`（已生成 27 章）运行迁移命令，成功生成：
  - 6 个卷的里程碑（前 1 卷的已完成里程碑标记为 `completed`）
  - 剩余 173 章的系统失效排程
  - 剩余 173 章的策略 Tier 范围
- 迁移后继续生成 ch28-30，三机制正常工作

**预估复杂度**：L

---

### Task 5.4: 测试 — 迁移功能

**任务标题**：编写迁移功能测试

**依赖**：Task 5.3

**涉及文件**：
- `tests/novel/scripts/test_migrate_narrative_arc.py`（新建）

**内容**：
- `test_migrate_existing_project()`: 测试迁移现有项目
- `test_migrate_resume_generation()`: 迁移后继续生成章节
- 边界条件：空项目、所有章节已生成、部分卷已完成

**验收条件**：
- 所有测试通过
- 迁移后数据正确，无数据丢失

**预估复杂度**：M

---

## Phase 6: 文档与验收

### Task 6.1: 更新用户文档

**任务标题**：更新 `CLAUDE.md` 和 `README.md` 描述三机制

**依赖**：Task 4.1

**涉及文件**：
- `CLAUDE.md`（修改）
- `README.md`（修改）

**内容**：
- 在 `CLAUDE.md` 的"小说模块"章节增加三机制简介
- 在 `README.md` 增加迁移命令说明
- 增加三机制的使用示例

**验收条件**：
- 文档清晰描述三机制功能
- 包含迁移命令示例

**预估复杂度**：S

---

### Task 6.2: 最终验收测试

**任务标题**：运行完整验收测试，验证所有验收标准

**依赖**：所有 Task 完成

**内容**：
- 运行 `specs/novel-narrative-arc-v2/requirements.md` 中的所有验收标准
- 端到端测试场景 1：新建战争题材小说，生成 20 章
- 端到端测试场景 2：迁移 `novel_12e1c974`，继续生成 10 章
- 端到端测试场景 3：非战争题材小说，验证主题门控
- 人工阅读生成章节，评分（张力、策略自然度、卷切换流畅性）

**验收条件**：
- 所有定量指标达标（卷进度完成率 >= 80%，系统失效执行率 100%，策略升级斜率正确，36 计覆盖率 >= 75%）
- 所有定性指标达标（人工评分 >= 7/10）
- 无关键 bug，无性能退化

**预估复杂度**：L

---

## 任务总结

**总任务数**：34

**预估复杂度分布**：
- S（简单）：16 个
- M（中等）：14 个
- L（复杂）：4 个

**并行度**：
- Phase 0: 5 个任务可完全并行
- Phase 1: Task 1.1-1.3 可并行，Task 1.4-1.5 可并行
- Phase 2: Task 2.1-2.2 可并行，Task 2.3-2.5 可并行
- Phase 3: Task 3.1-3.7 大部分可并行
- Phase 4: 顺序执行（集成测试）
- Phase 5: Task 5.1-5.3 可并行

**关键路径**：
Task 0.1 → Task 1.1 → Task 1.2 → Task 1.3 → Task 4.1 → Task 6.2

**总预估工时**（假设 1 人顺序开发）：
- Phase 0: 2 天
- Phase 1: 3 天
- Phase 2: 3 天
- Phase 3: 4 天
- Phase 4: 3 天
- Phase 5: 3 天
- Phase 6: 1 天
- **总计**：约 19 天（1 人）

**并行开发预估**（3 人团队，1 人负责 1 个机制）：
- Phase 0: 1 天（共享基础设施）
- Phase 1-3: 5 天（并行开发三机制）
- Phase 4: 3 天（集成测试，顺序执行）
- Phase 5: 2 天（并行优化）
- Phase 6: 1 天
- **总计**：约 12 天（3 人团队）

---

## 里程碑检查点

**Milestone 1**：Phase 0 完成
- 所有数据模型可用
- 模板文件生成
- SQLite schema 扩展完成

**Milestone 2**：Phase 1 完成（机制 A）
- 里程碑追踪正常工作
- 卷进度注入 continuity_brief
- PlotPlanner 响应进度信号
- 卷边界收束正常

**Milestone 3**：Phase 2 完成（机制 B）
- 系统失效排程生成
- 系统状态追踪正常
- PlotPlanner / Writer 响应系统约束
- ConsistencyChecker 检查系统约束

**Milestone 4**：Phase 3 完成（机制 C）
- 策略元素选择器正常
- PlotPlanner / Writer 使用策略元素
- 策略使用追踪正常
- 主题门控正常

**Milestone 5**：Phase 4 完成（集成）
- Pipeline 集成三机制
- 端到端测试通过
- 三机制协同触发验证通过

**Milestone 6**：Phase 5 完成（优化）
- Token 消耗优化完成
- 策略统计报告生成
- 迁移功能正常

**Milestone 7**：Phase 6 完成（发布）
- 文档更新
- 最终验收测试通过
- 准备发布
