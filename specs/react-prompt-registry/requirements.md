# ReAct Agent Framework + Prompt Registry - 需求文档

## 1. 项目背景

### 1.1 当前痛点

AI 创意工坊是一个多产品线的内容创作平台（小说/视频/PPT），所有 agent 基于 LLM 生成内容。目前存在以下核心问题：

1. **Prompt 硬编码**：所有 agent 的 prompt 直接写死在 Python 代码中（如 `writer.py` 的 `_ANTI_AI_FLAVOR`、`style_presets.py` 的预设文本），无法动态调整
2. **One-Shot 模式**：Agent 只是"拼 prompt → 调 LLM → 拿结果"，没有推理和自检能力，质量依赖单次生成
3. **质量不回流**：QualityReviewer 评审结果不会注入下次生成的 prompt，prompt 无法从历史问题中学习
4. **缺乏场景特化**：战斗场景、对话场景、策略场景用同一套 prompt，没有针对性优化
5. **手动交互效果远超自动化**：用户反馈同样的小说用 ChatGPT 手动交互写出的质量远超自动生成，说明 ReAct 循环（思考-行动-观察）对创作质量有显著提升

### 1.2 设计目标

本项目旨在构建两大核心模块：

**A. Prompt Registry（动态 Prompt 管理系统）**
- 数据库管理所有 prompt，支持模块化组装、版本控制、质量追踪
- 自动关联 prompt 版本和生成质量，低分版本自动标记
- 支持按类型（genre/scene_type）特化 prompt
- 提供前端管理界面（查看/编辑/回滚）

**B. ReAct Agent Framework（通用推理循环引擎）**
- 统一的 Thought → Action → Observe → 循环，Agent 可以多次调用工具自检和修改
- 每个 Agent 注册自己的工具集，框架负责循环调度
- 成本控制：budget_mode 可跳过自检/修改，退化为 one-shot
- 最大迭代次数限制，防止无限循环

**C. 反馈进化闭环（质量驱动的 Prompt 优化）**
- **即时层**：上一章/上一段的 strengths/weaknesses 注入下次生成的 prompt
- **统计层**：累计 N 次后算均分，低分 prompt block 标记待优化
- **重写层**：用 LLM 分析低分 block + weaknesses，自动生成改进版 prompt，人工审核后上线

---

## 2. 功能需求

### 2.1 Prompt Registry（P0 核心）

#### 2.1.1 Prompt Block（最小管理单元）

**功能描述**：Prompt 不再是整块文本，而是由多个可复用的 block 组装而成。

**需求**：
- FR-PR-001：系统应支持创建 prompt block，每个 block 包含：
  - `block_id`（唯一标识符，如 `anti_ai_flavor_v2`）
  - `block_type`（类型：`system_instruction` / `craft_technique` / `anti_pattern` / `scene_specific` / `feedback_injection` / `few_shot_example`）
  - `content`（block 文本内容）
  - `metadata`（元数据：作者、创建时间、描述）
  - `active`（是否启用，支持软删除）

- FR-PR-002：同一个 block 可以被多个 agent 和多个场景复用（如 `anti_ai_flavor` 可用于 Writer、QualityReviewer）

- FR-PR-003：系统应支持 block 版本控制：
  - 每次修改 block 内容时自动创建新版本（`block_id_v1` → `block_id_v2`）
  - 保留历史版本，支持回滚
  - 新版本默认 `active=True`，旧版本自动 `active=False`

**验收标准**：
- 可以创建一个名为 `anti_ai_flavor` 的 block，内容为"禁止使用：内心翻涌、莫名的力量..."
- 修改该 block 后生成 `anti_ai_flavor_v2`，旧版本仍可查询但不再被使用
- 可以回滚到 `anti_ai_flavor_v1`（将其 `active` 改回 `True`，v2 改为 `False`）

---

#### 2.1.2 Prompt Template（组装规则）

**功能描述**：定义如何从多个 block 组装成完整的 prompt。

**需求**：
- FR-PR-004：系统应支持创建 prompt template，每个 template 包含：
  - `template_id`（唯一标识符，如 `writer_scene_prompt`）
  - `agent_name`（所属 agent：`Writer` / `QualityReviewer` / `PlotPlanner`）
  - `scenario`（适用场景：`default` / `battle` / `dialogue` / `emotional` / `strategy`）
  - `block_order`（block 组装顺序，JSON 列表：`["system_instruction", "craft_technique", "anti_pattern", "scene_specific", "feedback_injection"]`）
  - `active`（是否启用）

- FR-PR-005：每个 template 可以按 scenario 特化（如 `Writer` 的 `battle` 场景用 `battle_craft_technique` 替换默认的 `craft_technique`）

- FR-PR-006：系统应提供 API `get_prompt(agent_name, scenario, context) -> str`：
  - 根据 agent 和 scenario 查找对应 template
  - 按 `block_order` 查找所有 `active=True` 的 block
  - 将 context 参数注入 `feedback_injection` block（如上一章的 weaknesses）
  - 拼接所有 block 返回完整 prompt 文本

**验收标准**：
- 创建一个 `writer_battle_template`，指定 block_order 为 `["system_instruction", "battle_craft", "anti_pattern", "feedback_injection"]`
- 调用 `get_prompt("Writer", "battle", {"last_weaknesses": ["重复使用比喻"]})` 返回拼接后的完整 prompt
- prompt 中包含 feedback_injection block 插入的 "上一章问题：重复使用比喻"

---

#### 2.1.3 质量追踪（关联 prompt 与生成质量）

**功能描述**：每次内容生成后，记录使用的 prompt 版本和质量评分，用于统计 prompt 效果。

**需求**：
- FR-PR-007：系统应在每次内容生成后记录 `prompt_usage`：
  - `usage_id`（唯一标识符）
  - `template_id`（使用的 template）
  - `block_ids`（实际使用的 block 列表，JSON）
  - `agent_name`（生成内容的 agent）
  - `scenario`（场景类型）
  - `generated_at`（生成时间）
  - `quality_score`（质量评分，0-10，初始为 null，后续由 QualityReviewer 回填）
  - `feedback_summary`（简短反馈摘要，如 "重复使用比喻"）

- FR-PR-008：系统应支持按 block_id 查询所有使用记录的平均质量分（用于标记低分 block）

- FR-PR-009：系统应提供 API `mark_low_quality_blocks(threshold=6.0)`：
  - 计算每个 block 的平均质量分
  - 将平均分 < threshold 的 block 标记为 `needs_optimization=True`
  - 返回低分 block 列表

**验收标准**：
- Writer 生成一章内容后，记录使用的 template 和 block 列表
- QualityReviewer 评分 5.5 后，回填 `quality_score=5.5` 和 `feedback_summary="对话缺乏人物个性"`
- 累计 20 次使用后，查询发现 `dialogue_craft` block 平均分 5.2，被标记为 `needs_optimization=True`

---

### 2.2 ReAct Agent Framework（P0 核心）

#### 2.2.1 统一 ReAct 循环引擎

**功能描述**：提供通用的 Thought → Action(tool call) → Observe → 循环框架，Agent 不再是 one-shot。

**需求**：
- FR-RA-001：系统应提供 `ReactAgent` 基类，包含核心循环逻辑：
  ```python
  def run(self, initial_prompt: str, max_iterations: int = 5) -> dict:
      # 1. 初始化：将任务转换为 LLM 可理解的消息
      # 2. 进入循环（最多 max_iterations 次）：
      #    a. LLM 生成 {"thinking": "...", "action": {"tool": "...", "args": {...}}}
      #    b. 执行 action 对应的工具
      #    c. 将工具结果注入下一轮消息
      #    d. 如果 action 是 "submit"，结束循环
      # 3. 返回最终结果和循环日志
  ```

- FR-RA-002：Agent 应注册自己的工具集，每个工具是一个可调用函数：
  ```python
  class WriterReactAgent(ReactAgent):
      def __init__(self):
          super().__init__()
          self.register_tool("generate_scene", self._generate_scene)
          self.register_tool("check_repetition", self._check_repetition)
          self.register_tool("check_logic", self._check_logic)
          self.register_tool("revise_scene", self._revise_scene)
          self.register_tool("submit", self._submit)
  ```

- FR-RA-003：LLM 每轮输出必须是 JSON 格式：
  ```json
  {
    "thinking": "当前思考过程",
    "action": {
      "tool": "工具名",
      "args": { "参数": "值" }
    }
  }
  ```

- FR-RA-004：系统应提供工具描述生成函数 `_format_tools_for_prompt()`，将注册的工具转换为 LLM 可理解的工具列表（参考 `agent_chat.py` 的 `_tools_description()`）

**验收标准**：
- 创建一个 `WriterReactAgent`，注册 5 个工具
- 调用 `agent.run("生成战斗场景")`，LLM 依次调用：
  1. `generate_scene` 生成初稿
  2. `check_repetition` 检查重复
  3. `revise_scene` 修改问题
  4. `check_logic` 检查逻辑
  5. `submit` 提交最终结果
- 循环日志中记录每一步的 thinking、action、observation

---

#### 2.2.2 预置工具集

**功能描述**：为 Writer、QualityReviewer 等 agent 提供常用工具实现。

**需求**：
- FR-RA-005：系统应提供 `WriterTools` 工具集，包含：
  - `generate_scene(outline, characters, world, context) -> str`：生成场景初稿
  - `check_repetition(text, previous_texts) -> dict`：检查与前文的重复度
  - `check_logic(text, context) -> dict`：检查叙事逻辑（事件闭环、角色去向等）
  - `check_character_names(text, character_list) -> dict`：检查角色名称一致性
  - `revise_scene(text, issues) -> str`：根据问题列表修改文本
  - `submit(text) -> str`：提交最终结果（特殊工具，会终止循环）

- FR-RA-006：系统应提供 `QualityReviewerTools` 工具集，包含：
  - `check_rules(text) -> dict`：规则硬指标检查（零成本）
  - `check_style(text, target_style) -> dict`：风格一致性检查
  - `llm_score(text, criteria) -> float`：LLM 打分评估
  - `submit(decision, reason) -> dict`：提交评审结果

**验收标准**：
- `check_repetition` 能检测出 "导弹攻击" 场景在前 3 章出现过，返回 `{"has_repetition": true, "details": "..."}`
- `check_logic` 能检测出 "角色A去执行任务后没有结果交代"，返回 `{"has_issue": true, "issues": [...]}`
- `revise_scene` 能根据 issues 列表调用 LLM 修改文本

---

#### 2.2.3 成本控制

**功能描述**：支持 budget_mode，跳过自检和修改步骤，退化为 one-shot。

**需求**：
- FR-RA-007：`ReactAgent.run()` 应支持 `budget_mode=True` 参数：
  - 此模式下只执行 `generate_scene` 和 `submit`，跳过所有 `check_*` 和 `revise_*` 工具
  - 等价于当前的 one-shot 模式，LLM 调用次数与现在相同

- FR-RA-008：系统应提供 `max_iterations` 参数控制最大循环次数（默认 5 次）

**验收标准**：
- `budget_mode=True` 时，Writer 只调用 1 次 LLM 生成场景，不调用任何检查工具
- `max_iterations=3` 时，即使 LLM 想继续调用工具，第 3 次后强制提交当前结果

---

### 2.3 反馈进化闭环（P1 核心）

#### 2.3.1 即时层：Feedback Injection

**功能描述**：上一章/上一段的 strengths/weaknesses 注入下次生成的 prompt。

**需求**：
- FR-FE-001：QualityReviewer 评审完成后，应提取 strengths 和 weaknesses，存储到数据库：
  - `feedback_record` 表：`chapter_number` / `strengths` (JSON) / `weaknesses` (JSON) / `overall_score`

- FR-FE-002：Writer 生成下一章时，系统应自动从数据库读取上一章的 weaknesses，注入到 `feedback_injection` block：
  ```
  【上一章反馈】
  需要注意的问题：
  - 重复使用"如同"这个比喻
  - 角色B的对话缺乏个性

  本章请避免以上问题。
  ```

- FR-FE-003：strengths 也应注入，强化好的写作模式：
  ```
  【上一章亮点】
  - 战斗场景节奏紧凑，没有拖沓
  - 主角心理描写细腻，没有说教感

  请继续保持这些优点。
  ```

**验收标准**：
- Writer 生成第 5 章时，prompt 中自动包含第 4 章的 weaknesses
- 第 5 章评审发现 "重复使用比喻" 问题消失

---

#### 2.3.2 统计层：低分 Block 标记

**功能描述**：累计 N 次使用后计算 prompt block 的平均质量分，低分 block 自动标记待优化。

**需求**：
- FR-FE-004：系统应提供定时任务或手动触发的 `analyze_prompt_performance()` 函数：
  - 查询所有 prompt_usage 记录，按 block_id 分组计算平均分
  - 将平均分 < 6.0 的 block 标记为 `needs_optimization=True`
  - 将平均分 >= 7.0 的 block 标记为 `needs_optimization=False`（重置标记）

- FR-FE-005：系统应在 Prompt Registry 管理界面显示每个 block 的统计数据：
  - 使用次数
  - 平均质量分
  - 优化状态（正常 / 待优化）

**验收标准**：
- 运行 20 章生成后，查询发现 `dialogue_craft` block 平均分 5.2，被标记 `needs_optimization=True`
- 管理界面显示该 block 需要优化，并提示 "平均分 5.2，低于阈值 6.0"

---

#### 2.3.3 重写层：LLM 自动生成改进版

**功能描述**：对标记为待优化的 block，用 LLM 分析历史 weaknesses 并生成改进版 prompt。

**需求**：
- FR-FE-006：系统应提供 `generate_improved_block(block_id)` 函数：
  - 查询该 block 所有关联的 prompt_usage 记录
  - 提取所有 `feedback_summary`（历史 weaknesses）
  - 调用 LLM 分析：
    - 当前 block 内容
    - 历史 weaknesses 汇总
    - 平均质量分
  - LLM 生成改进版 block 内容
  - 创建新版本（如 `dialogue_craft_v3`），状态为 `pending_review`

- FR-FE-007：改进版 block 必须经过人工审核才能上线：
  - 管理界面显示改进版和原版的对比
  - 提供 "批准上线" 和 "拒绝" 按钮
  - 批准后将新版本 `active=True`，旧版本 `active=False`

**验收标准**：
- `dialogue_craft` block 被标记待优化后，运行 `generate_improved_block("dialogue_craft")`
- LLM 生成新版本，内容增加了 "每个角色必须有独特的语言习惯和口头禅"
- 管理界面显示对比，人工审核后点击 "批准上线"，Writer 下次生成使用新版本

---

### 2.4 前端管理界面（P2 扩展）

#### 2.4.1 Prompt Block 管理

**需求**：
- FR-UI-001：页面应展示所有 prompt block，支持筛选（按 agent / scenario / active 状态）
- FR-UI-002：支持查看 block 详情（内容、版本历史、使用统计、质量分）
- FR-UI-003：支持在线编辑 block 内容，保存时自动创建新版本
- FR-UI-004：支持回滚到历史版本（将旧版本 active=True，当前版本 active=False）

#### 2.4.2 Prompt Template 管理

**需求**：
- FR-UI-005：页面应展示所有 prompt template，支持筛选（按 agent / scenario）
- FR-UI-006：支持拖拽调整 block_order（可视化编排）
- FR-UI-007：支持为不同 scenario 创建特化版本（如复制 `writer_default` 创建 `writer_battle`）

#### 2.4.3 质量分析看板

**需求**：
- FR-UI-008：页面应展示所有 block 的质量统计（使用次数、平均分、趋势图）
- FR-UI-009：支持查看待优化 block 列表，点击可查看历史 weaknesses
- FR-UI-010：支持查看 LLM 生成的改进版建议，对比原版和改进版，批准或拒绝

---

## 3. 非功能需求

### 3.1 性能要求

- NFR-001：`get_prompt()` 调用延迟 < 100ms（频繁调用场景）
- NFR-002：`ReactAgent.run()` 的循环开销（工具调用 + 日志记录）< 50ms/次（相对 LLM 调用可忽略）
- NFR-003：prompt_usage 记录插入应异步执行，不阻塞生成流程

### 3.2 可靠性要求

- NFR-004：所有数据库操作必须支持事务，block 版本创建失败应回滚
- NFR-005：`ReactAgent.run()` 必须有最大迭代次数限制，防止无限循环（LLM 生成错误导致）
- NFR-006：工具执行失败不应导致整个循环崩溃，应记录错误并返回 observation

### 3.3 可扩展性要求

- NFR-007：ReAct 框架应与具体 agent 解耦，新 agent 只需继承 `ReactAgent` 并注册工具
- NFR-008：Prompt Registry 应支持自定义 block_type（未来可能增加新类型）
- NFR-009：质量追踪应支持多维度评分（未来可能不只是 0-10 分，还有多个子维度）

### 3.4 可维护性要求

- NFR-010：所有数据库表必须有明确的索引（按 block_id、template_id、agent_name 查询频繁）
- NFR-011：ReAct 循环日志必须完整记录每一步（thinking、action、observation），便于调试
- NFR-012：Prompt Registry 管理界面应提供导出/导入功能（备份和跨环境迁移）

---

## 4. 约束条件

### 4.1 技术约束

- CONST-001：LLM 客户端是同步的（`client.chat(messages, temperature, json_mode, max_tokens) -> LLMResponse`），所有代码必须是同步的，不使用 async
- CONST-002：必须复用现有 `StructuredDB`（SQLite wrapper），不引入新的数据库系统
- CONST-003：必须复用现有 `create_llm_client(config)` 工厂函数，不重新实现 LLM 调用逻辑
- CONST-004：ReAct 框架必须通用，不绑定任何特定产品线（小说/视频/PPT 都能用）

### 4.2 兼容性约束

- CONST-005：现有 agent（Writer、QualityReviewer 等）可以逐步接入，不需要一次性改完
- CONST-006：在 ReAct 模式未启用时，agent 应保持当前 one-shot 行为（向后兼容）
- CONST-007：Prompt Registry 上线后，现有硬编码 prompt 应逐步迁移，但不强制删除代码（允许回退）

### 4.3 成本约束

- CONST-008：budget_mode 必须支持，跳过所有额外的 LLM 调用（自检、修改）
- CONST-009：质量追踪不应产生额外 LLM 调用（只是记录，评分由现有 QualityReviewer 回填）
- CONST-010：LLM 自动生成改进版 prompt 应控制调用频率（如每周一次批量处理）

---

## 5. 用例场景

### 5.1 Writer 使用 ReAct 模式生成章节

**前置条件**：
- Prompt Registry 已配置好 `writer_battle_template`
- 包含 block：`system_instruction`, `battle_craft`, `anti_pattern`, `feedback_injection`

**正常流程**：
1. 用户调用 `Writer.generate_chapter(chapter_outline, react_mode=True)`
2. Writer 创建 `WriterReactAgent`，注册工具集
3. 调用 `get_prompt("Writer", "battle", {"last_weaknesses": [...]})` 获取 prompt
4. ReactAgent 进入循环：
   - 第 1 轮：LLM 调用 `generate_scene` 生成初稿
   - 第 2 轮：LLM 调用 `check_repetition` 检测重复
   - 第 3 轮：LLM 发现重复问题，调用 `revise_scene` 修改
   - 第 4 轮：LLM 调用 `check_logic` 检查逻辑
   - 第 5 轮：LLM 调用 `submit` 提交最终结果
5. 系统记录 `prompt_usage`，关联使用的 template 和 block 列表
6. QualityReviewer 评审，回填 `quality_score` 和 `feedback_summary`

**后置条件**：
- 生成的章节质量高于 one-shot 模式（因为经过自检和修改）
- 数据库记录本次生成的 prompt 版本和质量分

### 5.2 低分 Prompt Block 自动优化

**前置条件**：
- `dialogue_craft` block 累计使用 20 次，平均分 5.2

**正常流程**：
1. 系统运行 `analyze_prompt_performance()`，标记 `dialogue_craft` 为 `needs_optimization=True`
2. 管理员在界面看到提示，点击 "生成改进建议"
3. 系统调用 `generate_improved_block("dialogue_craft")`：
   - 查询历史 weaknesses：["对话缺乏人物个性", "不同角色说话雷同", "过度使用书面语"]
   - LLM 分析当前 block + weaknesses，生成改进版
   - 改进版增加："每个角色必须有独特的语言习惯。指挥官用短句命令式，科学家用术语+情绪，工程师用数字+实际操作"
4. 管理员对比原版和改进版，点击 "批准上线"
5. 新版本 `dialogue_craft_v2` 生效，Writer 下次生成使用新版本
6. 后续 10 章平均分提升到 7.5，优化标记自动清除

**后置条件**：
- Prompt 质量持续提升，形成正向反馈循环

---

## 6. 数据字典

### 6.1 prompt_blocks 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| block_id | TEXT | Block 唯一标识符（含版本号，如 `anti_ai_flavor_v2`） | PRIMARY KEY |
| base_id | TEXT | Block 基础 ID（不含版本号，如 `anti_ai_flavor`） | NOT NULL, INDEX |
| version | INTEGER | 版本号 | NOT NULL |
| block_type | TEXT | Block 类型 | NOT NULL, CHECK IN (...) |
| content | TEXT | Block 文本内容 | NOT NULL |
| active | BOOLEAN | 是否启用（同一 base_id 只有一个 active=True） | NOT NULL, DEFAULT TRUE |
| needs_optimization | BOOLEAN | 是否需要优化（低分标记） | NOT NULL, DEFAULT FALSE |
| metadata | TEXT | 元数据 JSON（作者、描述等） | NULL |
| created_at | TIMESTAMP | 创建时间 | NOT NULL |

### 6.2 prompt_templates 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| template_id | TEXT | Template 唯一标识符 | PRIMARY KEY |
| agent_name | TEXT | 所属 agent | NOT NULL, INDEX |
| scenario | TEXT | 适用场景 | NOT NULL, DEFAULT 'default' |
| block_order | TEXT | Block 组装顺序 JSON 列表 | NOT NULL |
| active | BOOLEAN | 是否启用 | NOT NULL, DEFAULT TRUE |
| created_at | TIMESTAMP | 创建时间 | NOT NULL |

### 6.3 prompt_usage 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| usage_id | TEXT | 使用记录唯一标识符 | PRIMARY KEY |
| template_id | TEXT | 使用的 template | NOT NULL, INDEX |
| block_ids | TEXT | 实际使用的 block 列表 JSON | NOT NULL |
| agent_name | TEXT | 生成内容的 agent | NOT NULL, INDEX |
| scenario | TEXT | 场景类型 | NOT NULL |
| generated_at | TIMESTAMP | 生成时间 | NOT NULL |
| quality_score | REAL | 质量评分（0-10，初始为 null） | NULL |
| feedback_summary | TEXT | 简短反馈摘要 | NULL |

### 6.4 feedback_records 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| record_id | TEXT | 反馈记录唯一标识符 | PRIMARY KEY |
| novel_id | TEXT | 小说 ID | NOT NULL, INDEX |
| chapter_number | INTEGER | 章节号 | NOT NULL, INDEX |
| strengths | TEXT | 优点列表 JSON | NULL |
| weaknesses | TEXT | 问题列表 JSON | NULL |
| overall_score | REAL | 总体评分 | NULL |
| created_at | TIMESTAMP | 创建时间 | NOT NULL |

---

## 7. 迁移路径

### 7.1 Phase 1: 基础设施（Week 1-2）

- 实现 Prompt Registry 数据库表和 CRUD API
- 迁移现有硬编码 prompt 到数据库（如 `_ANTI_AI_FLAVOR` → `anti_ai_flavor` block）
- 现有 agent 保持 one-shot 模式，但 prompt 从数据库读取

### 7.2 Phase 2: ReAct 框架（Week 3-4）

- 实现 `ReactAgent` 基类和工具注册机制
- 实现 `WriterTools` 预置工具集
- Writer agent 支持 `react_mode=True` 参数，默认仍为 one-shot

### 7.3 Phase 3: 质量闭环（Week 5-6）

- 实现 prompt_usage 记录和质量追踪
- 实现即时层 feedback injection
- 实现统计层低分 block 标记

### 7.4 Phase 4: 自动优化（Week 7-8）

- 实现 LLM 自动生成改进版 prompt
- 实现管理界面（Gradio 或 FastAPI + 前端）
- 生产环境灰度发布（10% 流量用 ReAct 模式）

### 7.5 Phase 5: 推广（Week 9+）

- 其他 agent（QualityReviewer、PlotPlanner 等）逐步接入 ReAct 模式
- 视频和 PPT 产品线接入 Prompt Registry
- 全量切换 ReAct 模式（budget_mode 作为降级开关）

---

## 8. 风险评估

| 风险 | 等级 | 影响 | 缓解措施 |
|------|------|------|---------|
| LLM 在 ReAct 循环中生成错误格式 JSON | 高 | 工具调用失败，循环崩溃 | 严格 JSON schema 验证 + fallback 机制（解析失败时提示 LLM 重试 1 次） |
| ReAct 模式 LLM 调用次数过多（5x one-shot） | 高 | 成本大幅增加 | 严格强制 budget_mode 可用，灰度发布时监控成本 |
| 低分 block 标记不准确（样本量不足） | 中 | 误杀好的 prompt | 设置最小样本量阈值（如 >= 20 次使用才统计） |
| LLM 自动生成的改进版 prompt 质量差 | 中 | 人工审核负担 | 必须经过人工审核才能上线，拒绝率高时停用自动生成功能 |
| 多 agent 并发写入 prompt_usage 表 | 低 | 数据库锁竞争 | SQLite WAL 模式 + 异步插入队列 |

---

## 9. 成功指标

- **质量提升**：ReAct 模式生成的章节质量评分 >= one-shot 模式 +1.0 分（10 分制）
- **成本可控**：budget_mode 下成本与现在持平，react_mode 下成本 < 3x one-shot
- **迁移进度**：Phase 1-2 完成后，50% 的 Writer 生成使用 ReAct 模式
- **反馈闭环有效性**：低分 block 经过优化后，平均质量分提升 >= 1.5 分
- **人工审核效率**：每周自动生成的改进版 prompt 批准率 >= 60%

---

## 10. 术语表

| 术语 | 定义 |
|------|------|
| Prompt Block | Prompt 的最小管理单元，可复用的文本片段 |
| Prompt Template | 定义如何从多个 block 组装成完整 prompt 的规则 |
| ReAct | Reasoning + Acting，LLM 通过"思考-行动-观察"循环解决问题的模式 |
| One-Shot | 传统模式，LLM 一次性生成结果，没有自检和修改 |
| Budget Mode | 省钱模式，跳过自检和修改步骤，退化为 one-shot |
| Feedback Injection | 将上一章的问题注入下次生成的 prompt，即时反馈 |
| Block 版本控制 | 每次修改 block 内容时自动创建新版本（v1 → v2） |
| 低分 Block | 平均质量分 < 6.0 的 block，需要优化 |
| 改进版 Prompt | LLM 根据历史 weaknesses 自动生成的优化版 block |
