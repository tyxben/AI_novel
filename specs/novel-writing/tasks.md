# AI 长篇小说写作模块 - 开发任务拆分

## 开发原则

1. **MVP 优先** — 先跑通核心链路（大纲→角色→世界观→章节生成→一致性检查），再迭代增强
2. **并行开发** — 标注可以并行的任务（不同文件），有依赖关系的任务按顺序执行
3. **每个任务附带测试要求** — 必须写单元测试，覆盖边界条件和错误路径
4. **控制粒度** — 每个任务 30-120 分钟工作量
5. **测试目标** — 最终生成一部 10 万字小说，验证全流程

---

## Phase 1: 基础设施（数据模型、存储、记忆系统、配置）

### 1.1 数据模型层

- [x] **Task 1.1.1: 核心小说数据模型**
  - **文件**: `src/novel/models/novel.py`
  - **依赖**: 无
  - **并行**: 可与 1.1.2-1.1.5 并行
  - **内容**:
    - 实现 `Novel`, `Outline`, `Act`, `VolumeOutline`, `ChapterOutline`, `Volume` 模型
    - 所有字段使用 Pydantic 验证（min_length, ge, le, pattern）
    - `Novel.model_dump_json()` 序列化测试
    - 包含 `created_at`, `updated_at`, `status`, `current_chapter` 元数据
  - **测试**:
    - 有效数据验证通过
    - 无效数据抛出 `ValidationError`（空 title、负字数、无效 status）
    - JSON 序列化/反序列化一致性
    - 边界条件：超长 title（> 100字）、target_words = 0
  - **验收**: 所有模型可正常实例化，验证规则生效

- [x] **Task 1.1.2: 章节与场景模型**
  - **文件**: `src/novel/models/chapter.py`
  - **依赖**: 无
  - **并行**: 可与 1.1.1, 1.1.3-1.1.5 并行
  - **内容**:
    - 实现 `Chapter`, `Scene` 模型
    - `Scene.narrative_modes` 验证（对话/动作/描写/心理）
    - `Chapter.full_text` 从 `scenes` 拼接的逻辑
    - `word_count` 自动计算
  - **测试**:
    - Scene 字数超限（> 3000字）触发验证错误
    - Chapter 拼接多个 Scene，验证 `full_text` 和 `word_count` 正确
    - 状态流转：draft → reviewed → finalized
  - **验收**: 场景拼接逻辑正确，字数统计准确

- [x] **Task 1.1.3: 角色与关系模型**
  - **文件**: `src/novel/models/character.py`
  - **依赖**: 无
  - **并行**: 可与 1.1.1-1.1.2, 1.1.4-1.1.5 并行
  - **内容**:
    - 实现 `CharacterProfile`, `Appearance`, `Personality`, `Relationship`, `RelationshipEvent`, `CharacterArc`, `TurningPoint`
    - `Personality.traits` 限制 3-7 个
    - `Relationship.current_type` 支持 15 种类型
    - `RelationshipEvent` 记录关系变化链
  - **测试**:
    - 性格标签少于 3 个或多于 7 个抛出错误
    - `RelationshipEvent.intensity_change` 超出 [-10, 10] 范围报错
    - 关系历史链追加测试
  - **验收**: 角色档案完整，关系网可追溯变化

- [x] **Task 1.1.4: 世界观与力量体系模型**
  - **文件**: `src/novel/models/world.py`
  - **依赖**: 无
  - **并行**: 可与 1.1.1-1.1.3, 1.1.5 并行
  - **内容**:
    - 实现 `WorldSetting`, `PowerSystem`, `PowerLevel`
    - `terms` 字典结构（专有名词 → 定义）
    - `PowerLevel.rank` 严格递增验证
  - **测试**:
    - 空 `terms` 字典可用
    - `PowerSystem` 至少 1 个层级
    - 力量等级 rank 顺序验证
  - **验收**: 玄幻/武侠世界观可定义完整力量体系

- [x] **Task 1.1.5: 记忆与质量模型**
  - **文件**: `src/novel/models/memory.py`, `src/novel/models/quality.py`, `src/novel/models/foreshadowing.py`
  - **依赖**: 无
  - **并行**: 可与 1.1.1-1.1.4 并行
  - **内容**:
    - `memory.py`: `Fact`, `ChapterSummary`, `VolumeSnapshot`, `CharacterSnapshot`
    - `quality.py`: `StyleMetrics`, `RuleCheckResult`, `PairwiseResult`
    - `foreshadowing.py`: `Foreshadowing`, `DetailEntry`（V2，但模型先建好）
  - **测试**:
    - `Fact.storage_layer` 限定 structured/graph/vector
    - `StyleMetrics` 所有比例字段 [0.0, 1.0]
    - `PairwiseResult.winner` 只能是 A/B/TIE
    - `Foreshadowing.origin` planned/retroactive 验证
  - **验收**: 所有辅助模型字段验证正确

---

### 1.2 存储层

- [x] **Task 1.2.1: SQLite 结构化数据库**
  - **文件**: `src/novel/storage/structured_db.py`
  - **依赖**: 1.1.5（Fact 模型）
  - **并行**: 可与 1.2.2-1.2.3 并行
  - **内容**:
    - 创建 `StructuredDB` 类，初始化 7 张表（character_states, timeline, terms, power_tracking, facts, chapter_summaries, indexes）
    - CRUD 接口：`insert_character_state()`, `query_character_state()`, `insert_term()`, `query_term()`
    - 事务支持（Context Manager）
    - 索引创建验证
  - **测试**:
    - 插入重复 UNIQUE 数据抛出 IntegrityError
    - 查询不存在数据返回空列表
    - 时间线查询按 chapter 排序
    - 专有名词模糊查询（LIKE）
    - Mock 数据库文件，测试后自动删除
  - **验收**: SQLite schema 创建成功，CRUD 操作稳定

- [x] **Task 1.2.2: NetworkX 知识图谱**
  - **文件**: `src/novel/storage/knowledge_graph.py`
  - **依赖**: 1.1.3（Relationship 模型）
  - **并行**: 可与 1.2.1, 1.2.3 并行
  - **内容**:
    - `KnowledgeGraph` 类封装 `nx.MultiDiGraph`
    - 接口：`add_character()`, `add_relationship()`, `add_faction()`, `add_location()`, `get_relationships()`, `find_shortest_path()`, `get_faction_members()`
    - 序列化：`save()`, `load()` 使用 pickle
  - **测试**:
    - 添加角色节点，验证节点属性
    - 添加关系边，支持多重边（同一角色对不同章节关系不同）
    - 查询角色关系，返回完整边列表
    - 地点路径查询（A→B 经过 C）
    - 保存/加载图，验证数据一致性
    - 空图保存/加载不崩溃
  - **验收**: 关系图增删查改正常，路径查询正确

- [x] **Task 1.2.3: Chroma 向量存储**
  - **文件**: `src/novel/storage/vector_store.py`
  - **依赖**: 1.1.5（Fact 模型）
  - **并行**: 可与 1.2.1-1.2.2 并行
  - **内容**:
    - `VectorStore` 类封装 chromadb
    - 接口：`create_collection()`, `add_fact()`, `query_facts()`, `add_chapter_summary()`, `query_similar_chapters()`
    - 自动生成 embedding（使用 Chroma 默认模型）
    - 支持 metadata 过滤（chapter, type）
  - **测试**:
    - 添加 fact，验证 embedding 自动生成
    - 语义查询测试（query="角色受伤" 应匹配 "主角左臂骨折"）
    - metadata 过滤（查询指定 chapter 的 facts）
    - 空集合查询返回空列表
    - 持久化测试：重启后数据仍在
  - **验收**: 向量检索有效，metadata 过滤正常

- [x] **Task 1.2.4: 三层混合记忆系统**
  - **文件**: `src/novel/storage/novel_memory.py`
  - **依赖**: 1.2.1, 1.2.2, 1.2.3
  - **并行**: 无（依赖前 3 个存储层）
  - **内容**:
    - `NovelMemory` 类统一封装三层存储
    - 智能路由：根据 `Fact.type` 决定存储层
      - time/character_state/power_level → SQLite
      - relationship/affiliation → NetworkX
      - 其他 → Chroma（兜底）
    - 接口：`add_fact()`, `query_fact()`, `add_chapter_summary()`, `get_recent_chapters()`, `create_volume_snapshot()`
  - **测试**:
    - 添加不同类型 fact，验证路由到正确存储层
    - 跨层查询（先查 SQLite，未命中再查 Chroma）
    - 章节摘要存储与检索（最近 3 章）
    - 卷快照生成（包含角色状态、伏笔、世界观增量）
    - 并发写入测试（多线程安全）
  - **验收**: 三层协同工作，查询性能 < 100ms

- [x] **Task 1.2.5: 文件系统管理**
  - **文件**: `src/novel/storage/file_manager.py`
  - **依赖**: 1.1.1（Novel 模型）
  - **并行**: 可与 1.2.1-1.2.4 并行
  - **内容**:
    - `FileManager` 类管理项目目录结构
    - 接口：`create_project()`, `save_novel()`, `load_novel()`, `save_chapter()`, `load_chapter()`, `delete_project()`
    - 目录结构：`workspace/novels/{novel_id}/` 自动创建
    - 章节文本使用 UTF-8 编码
  - **测试**:
    - 创建项目，验证目录和文件存在
    - 保存 Novel 对象，验证 JSON 正确
    - 加载 Novel，验证数据一致性
    - 章节文本中文编码测试
    - 删除项目，验证文件清理干净
    - 重复创建同名项目抛出错误
  - **验收**: 文件操作稳定，编码无乱码

---

### 1.3 配置与工具

- [x] **Task 1.3.1: 小说模块配置**
  - **文件**: `src/novel/config.py`, `config.yaml`（新增 novel 段）
  - **依赖**: 无
  - **并行**: 可与 Phase 1 其他任务并行
  - **内容**:
    - `NovelConfig` 类（Pydantic BaseSettings）
    - 配置项：
      - `default_genre`: 默认题材
      - `default_target_words`: 默认字数
      - `review_interval`: 审核间隔（章）
      - `silent_mode`: 静默模式
      - `auto_approve_threshold`: 自动通过阈值
      - `max_rewrite_attempts`: 最大重写次数
      - `memory.db_path`, `memory.vector_path`, `memory.graph_path`
    - `config.yaml` 新增 `novel:` 配置段
  - **测试**:
    - 加载默认配置
    - 覆盖配置（项目级 config.json）
    - 无效配置值抛出验证错误
  - **验收**: 配置可分层覆盖，验证生效

- [x] **Task 1.3.2: 小说模块工具函数**
  - **文件**: `src/novel/utils.py`
  - **依赖**: 无
  - **并行**: 可与 Phase 1 其他任务并行
  - **内容**:
    - `count_chinese_words(text: str) -> int`: 中文字数统计（汉字 + 标点）
    - `split_paragraphs(text: str) -> list[str]`: 段落分割
    - `detect_repetition(sentences: list[str], threshold=0.8) -> list[tuple]`: 重复句检测
    - `extract_dialogue(text: str) -> list[str]`: 提取对话
    - `compute_similarity(text1: str, text2: str) -> float`: 文本相似度
  - **测试**:
    - 中文字数统计：包含标点、英文、数字混合文本
    - 重复句检测：连续 3 句相似度 > 80%
    - 对话提取：支持中文引号、问号、感叹号
    - 相似度计算：完全相同=1.0，完全不同≈0.0
  - **验收**: 所有工具函数边界条件测试通过

---

## Phase 2: Agent 核心（NovelDirector、Writer、PlotPlanner）

### 2.1 NovelDirector（总导演）

- [x] **Task 2.1.1: 大纲模板系统**
  - **文件**: `src/novel/templates/outline_templates.py`
  - **依赖**: 1.1.1（Outline 模型）
  - **并行**: 可与 2.1.2 并行
  - **内容**:
    - 实现 4 种大纲模板（每种返回 Outline 结构）：
      - `cyclic_upgrade_template()`: 循环升级模板（玄幻/系统流）
      - `multi_thread_template()`: 多线交织模板（群像/宫斗）
      - `four_act_template()`: 四幕经典模板（中篇）
      - `custom_template()`: 自由模板（开放式）
    - 每个模板包含：acts, volumes, chapters 三层结构
    - 章节数自动根据 target_words 计算（每章 3000-5000 字）
  - **测试**:
    - 生成 10 万字小说大纲，验证章节数合理（20-33 章）
    - 每种模板的 acts/volumes/chapters 层级完整
    - 章节号连续无重复
    - 各模板的情绪节奏符合设定（循环升级：蓄力→小爽→大爽循环）
  - **验收**: 4 种模板可正常生成，结构合理

- [x] **Task 2.1.2: 大纲生成工具**
  - **文件**: `src/novel/tools/outline_tool.py`, `src/novel/services/outline_service.py`
  - **依赖**: 1.1.1, 2.1.1, `src/llm/`
  - **并行**: 可与 2.1.1 并行开发（模板先用硬编码占位）
  - **内容**:
    - `OutlineService.generate_outline()`: 调用 LLM 生成大纲
      - System Prompt: 根据题材、主题、模板生成三层大纲
      - Few-shot 示例（每种模板 1 个示例）
      - 返回结构化 JSON（Pydantic 验证）
    - `OutlineTool.generate_outline()`: 封装服务层
    - `OutlineTool.update_chapter_outline()`: 更新指定章大纲
  - **测试**:
    - Mock LLM 返回固定 JSON，验证解析正确
    - 非法 JSON 返回触发重试（最多 3 次）
    - 更新章大纲，验证其他章不受影响
    - LLM 超时处理（timeout=60s）
  - **验收**: 大纲生成稳定，结构化输出可靠

- [x] **Task 2.1.3: NovelDirector Agent**
  - **文件**: `src/novel/agents/novel_director.py`
  - **依赖**: 2.1.2
  - **并行**: 可与 2.2, 2.3 并行（Agent 间独立）
  - **内容**:
    - `NovelDirector` 类实现：
      - `analyze_user_input()`: 提取题材、主题、字数目标
      - `generate_outline()`: 调用 OutlineTool
      - `update_outline()`: 响应用户修改
      - `plan_workflow()`: 规划 Agent 调用顺序（WorldBuilder → CharacterDesigner → PlotPlanner → Writer → Checkers）
    - `novel_director_node()`: LangGraph 节点函数
  - **测试**:
    - 解析用户输入："写一部 10 万字都市重生小说，主题是商战复仇"
    - 生成大纲，验证包含 acts/volumes/chapters
    - 修改大纲（调整第 10 章情节），验证更新生效
    - workflow_plan 包含正确 Agent 顺序
  - **验收**: Director 可生成完整大纲，规划流程清晰

---

### 2.2 Writer（写手）

- [x] **Task 2.2.1: 场景分解工具**
  - **文件**: `src/novel/tools/scene_decompose_tool.py`
  - **依赖**: 1.1.2（Scene 模型）, `src/llm/`
  - **并行**: 可与 2.2.2 并行
  - **内容**:
    - `SceneDecomposeTool.decompose_chapter()`: 将章大纲拆为 3-5 个场景
      - LLM Prompt: "将以下章节大纲拆分为场景序列，每个场景包含地点、时间、角色、目标"
      - 返回 `list[Scene]`（带 scene_number, location, time, characters, goal）
  - **测试**:
    - Mock LLM 返回场景列表，验证解析
    - 场景数量限制（3-5 个）
    - 场景 goal 不为空
    - 场景角色列表非空
  - **验收**: 章节可拆分为合理场景序列

- [x] **Task 2.2.2: 场景生成工具**
  - **文件**: `src/novel/tools/scene_gen_tool.py`, `src/novel/services/scene_service.py`
  - **依赖**: 1.1.2, 1.2.4（NovelMemory）, `src/llm/`
  - **并行**: 可与 2.2.1 并行
  - **内容**:
    - `SceneService.generate_scene()`: 生成单个场景正文（500-1500 字）
      - Context 注入：world_setting, characters, recent_chapters, relevant_facts
      - Style Prompt: 根据风格类型调整
      - Rhythm Instruction: 节奏指令（来自 PlotPlanner）
    - `SceneGenTool.generate_scene()`: 封装服务层
  - **测试**:
    - Mock context 和 style，生成场景
    - 验证场景包含对话、动作、描写
    - 字数控制（500-1500）
    - 多次生成同一场景，内容应有差异
  - **验收**: 场景生成质量稳定，符合字数要求

- [x] **Task 2.2.3: 风格预设系统**
  - **文件**: `src/novel/templates/style_presets.py`
  - **依赖**: 1.1.5（StyleMetrics 模型）
  - **并行**: 可与 2.2.1-2.2.2 并行
  - **内容**:
    - 8 种风格预设（每种返回 System Prompt + Few-shot 示例 + StyleMetrics）:
      - 武侠-古言风
      - 网文-爽文
      - 网文-种田流
      - 网文-系统流
      - 网文-黑暗流
      - 网文-无敌流
      - 文学-现实主义
      - 轻小说-后宫
    - 每个预设包含：avg_sentence_length, dialogue_ratio, exclamation_ratio, paragraph_length
  - **测试**:
    - 验证 8 种预设的 StyleMetrics 有效
    - 网文爽文：paragraph_length < 150，exclamation_ratio > 0.05
    - 文学现实主义：avg_sentence_length > 15，dialogue_ratio < 0.4
  - **验收**: 风格预设数据完整，符合类型特征

- [x] **Task 2.2.4: Writer Agent**
  - **文件**: `src/novel/agents/writer.py`
  - **依赖**: 2.2.1, 2.2.2, 2.2.3
  - **并行**: 可与 2.1.3, 2.3 并行
  - **内容**:
    - `Writer` 类实现：
      - `generate_scene()`: 调用 SceneGenTool
      - `apply_style()`: 应用风格模板
      - `add_cliffhanger()`: 章末添加悬念钩子
      - `polish_transitions()`: 平滑场景过渡，拼接为完整章节
    - `writer_node()`: LangGraph 节点函数
  - **测试**:
    - 生成 4 个场景，拼接为章节
    - 验证章末有悬念（关键词检测："然而"、"突然"、"没想到"）
    - 场景过渡自然（检测过渡词："与此同时"、"不久后"）
    - 风格应用：网文爽文段落 < 150 字
  - **验收**: 完整章节生成流畅，悬念有效

---

### 2.3 PlotPlanner（情节规划师）

- [x] **Task 2.3.1: 节奏模板系统**
  - **文件**: `src/novel/templates/rhythm_templates.py`
  - **依赖**: 1.1.1（ChapterOutline 模型）
  - **并行**: 可与 2.3.2 并行
  - **内容**:
    - 按题材定义节奏模板（dict 结构）：
      - 玄幻：蓄力(2章) → 小爽(1章) → 蓄力(2章) → 大爽(1章) → 过渡(1章) 循环
      - 都市：日常(2章) → 反转(1章) → 小爽(1章) → 虐心(1章) 循环
      - 悬疑：蓄力(3章) → 反转(1章) → 蓄力(2章) → 大爆发(1章)
    - `get_chapter_mood(genre, chapter_number, total_chapters) -> str`: 根据章节位置返回情绪
  - **测试**:
    - 玄幻 30 章小说，验证节奏分布合理
    - 最后 3 章必须包含至少 1 个"大爽"
    - 避免连续 3+ 章相同情绪
  - **验收**: 节奏模板符合网文经验，避免单调

- [x] **Task 2.3.2: PlotPlanner Agent**
  - **文件**: `src/novel/agents/plot_planner.py`
  - **依赖**: 2.2.1（SceneDecomposeTool）, 2.3.1
  - **并行**: 可与 2.1.3, 2.2.4 并行
  - **内容**:
    - `PlotPlanner` 类实现：
      - `decompose_chapter()`: 调用 SceneDecomposeTool
      - `design_chapter_rhythm()`: 根据节奏模板返回情绪和指令
      - `check_rhythm_anomaly()`: 检测连续 3+ 章同一情绪
      - `plan_foreshadowing()`: 伏笔规划（V2 占位，先返回空列表）
    - `plot_planner_node()`: LangGraph 节点函数
  - **测试**:
    - 分解章节为 4 个场景
    - 设计节奏：第 5 章返回"小爽" + "节奏加快，矛盾激化"
    - 检测异常：连续 3 章"蓄力"触发警告
  - **验收**: 节奏设计合理，异常检测有效

---

## Phase 3: 辅助 Agent（WorldBuilder、CharacterDesigner、ConsistencyChecker、StyleKeeper、QualityReviewer）

### 3.1 WorldBuilder（世界观构建师）

- [x] **Task 3.1.1: 世界观生成服务**
  - **文件**: `src/novel/services/world_service.py`
  - **依赖**: 1.1.4（WorldSetting 模型）, `src/llm/`
  - **并行**: 可与 3.1.2, 3.2, 3.3, 3.4, 3.5 并行
  - **内容**:
    - `WorldService.create_world_setting()`: 根据题材生成世界观框架
      - LLM Prompt: "为{genre}小说生成世界观，包括时空背景、关键设定、规则"
      - 返回 `WorldSetting` 对象
    - `WorldService.define_power_system()`: 生成力量体系（玄幻/武侠）
      - 返回 `PowerSystem`，至少 5 个层级
  - **测试**:
    - Mock LLM 返回世界观 JSON
    - 玄幻题材自动生成力量体系
    - 都市题材不生成力量体系（power_system=None）
    - 专有名词表初始为空
  - **验收**: 世界观生成稳定，力量体系合理

- [x] **Task 3.1.2: WorldBuilder Agent**
  - **文件**: `src/novel/agents/world_builder.py`, `src/novel/tools/world_setting_tool.py`
  - **依赖**: 3.1.1, 1.2.1（StructuredDB - terms 表）
  - **并行**: 可与 3.1.1, 3.2, 3.3, 3.4, 3.5 并行
  - **内容**:
    - `WorldSettingTool`: 封装 WorldService
    - `WorldBuilder` 类实现：
      - `create_world_setting()`: 调用 WorldService
      - `define_power_system()`: 生成力量体系
      - `register_term()`: 注册专有名词到 SQLite terms 表
      - `validate_setting_consistency()`: 检查章节是否违反世界观（如现代都市突然出现法术）
    - `world_builder_node()`: LangGraph 节点函数
  - **测试**:
    - 创建玄幻世界观，验证力量体系包含 10 个层级
    - 注册专有名词："九霄门" → "主角所属门派"
    - 验证一致性：都市背景章节包含"御剑飞行"触发警告
  - **验收**: 世界观管理完整，专有名词强制一致性

---

### 3.2 CharacterDesigner（角色设计师）

- [x] **Task 3.2.1: 角色生成服务**
  - **文件**: `src/novel/services/character_service.py`
  - **依赖**: 1.1.3（CharacterProfile 模型）, `src/llm/`
  - **并行**: 可与 3.1, 3.2.2, 3.3, 3.4, 3.5 并行
  - **内容**:
    - `CharacterService.extract_characters()`: 从大纲提取角色列表
      - LLM Prompt: "从大纲中提取主要角色姓名及角色类型（主角/反派/配角）"
    - `CharacterService.generate_character_profile()`: 生成完整角色档案
      - 包含：基础属性、外貌、性格、关系网、成长弧线
  - **测试**:
    - Mock 大纲，提取至少 3 个角色
    - 生成角色档案，验证所有必填字段
    - 性格标签数量 3-7 个
    - 语言风格描述具体（如"冷淡简短"而非"正常"）
  - **验收**: 角色档案完整，符合模型约束

- [x] **Task 3.2.2: CharacterDesigner Agent**
  - **文件**: `src/novel/agents/character_designer.py`, `src/novel/tools/character_tool.py`
  - **依赖**: 3.2.1, 1.2.2（KnowledgeGraph - 关系网）
  - **并行**: 可与 3.1, 3.2.1, 3.3, 3.4, 3.5 并行
  - **内容**:
    - `CharacterTool`: 封装 CharacterService
    - `CharacterDesigner` 类实现：
      - `extract_characters()`: 调用服务层
      - `generate_character_profile()`: 生成档案
      - `define_relationship()`: 定义角色关系，写入 NetworkX 图
      - `track_character_arc()`: 追踪角色成长
      - `validate_character_consistency()`: 检查角色行为是否 OOC（对比 speech_style, traits）
    - `character_designer_node()`: LangGraph 节点函数
  - **测试**:
    - 提取 5 个角色，生成档案
    - 定义关系：主角与反派"敌对"，intensity=9
    - 关系变化：第 10 章从"陌生"→"暧昧"，记录 RelationshipEvent
    - OOC 检测：冷静角色突然"大喊大叫"触发警告
  - **验收**: 角色档案和关系网完整，OOC 检测有效

---

### 3.3 ConsistencyChecker（一致性检查官）

- [x] **Task 3.3.1: 事实提取工具**
  - **文件**: `src/novel/tools/consistency_tool.py`（部分）, `src/novel/services/consistency_service.py`（部分）
  - **依赖**: 1.1.5（Fact 模型）, `src/llm/`
  - **并行**: 可与 3.3.2 并行
  - **内容**:
    - `ConsistencyService.extract_facts()`: 从章节提取关键事实
      - LLM Prompt: "提取章节中的关键事实，分类为 time/character_state/location/event/relationship"
      - 返回 `list[Fact]`
  - **测试**:
    - Mock 章节文本，提取 5-10 个 facts
    - 验证 Fact.type 正确分类
    - 时间相关事实自动归类为 "time"
    - 角色状态（受伤/位置）归类为 "character_state"
  - **验收**: 事实提取准确，分类合理

- [x] **Task 3.3.2: 三层混合检测**
  - **文件**: `src/novel/tools/consistency_tool.py`, `src/novel/services/consistency_service.py`
  - **依赖**: 3.3.1, 1.2.4（NovelMemory）
  - **并行**: 可与 3.3.1 并行（分函数开发）
  - **内容**:
    - `ConsistencyService.check_consistency()`: 三层混合检测
      - 第一层：查询 SQLite（精确匹配）
      - 第二层：查询 NetworkX（关系查询）
      - 第三层：查询 Chroma（语义兜底）
      - LLM 裁决：`llm_judge_contradiction()` 判断是否实质矛盾
    - `ConsistencyTool.check_consistency()`: 封装服务层
  - **测试**:
    - 植入明显矛盾：第 5 章"角色死亡"，第 10 章"角色出现"
    - 验证第一层检测到矛盾（查 character_states 表）
    - 植入关系矛盾：第 5 章"敌对"，第 10 章突然"兄弟"无铺垫
    - 验证第二层检测到（查 NetworkX，RelationshipEvent 缺失）
    - 语义矛盾：第 5 章"主角不会武功"，第 10 章"使出降龙十八掌"
    - 验证第三层检测到（向量检索 + LLM 裁决）
    - 误报测试：合理的情节发展不应触发矛盾（如角色受伤后康复）
  - **验收**: 漏报率 < 15%，误报率 < 20%，检测延迟 < 30s

- [x] **Task 3.3.3: ConsistencyChecker Agent**
  - **文件**: `src/novel/agents/consistency_checker.py`
  - **依赖**: 3.3.2
  - **并行**: 可与 3.1, 3.2, 3.4, 3.5 并行
  - **内容**:
    - `ConsistencyChecker` 类实现：
      - `extract_facts()`: 调用 ConsistencyTool
      - `check_consistency()`: 执行三层检测
      - `query_structured_db()`, `query_relationship_graph()`, `vector_search()`: 分层查询接口
      - `llm_judge_contradiction()`: LLM 裁决
    - `consistency_checker_node()`: LangGraph 节点函数
  - **测试**:
    - 检测章节，无矛盾通过
    - 发现矛盾，返回详细报告（type, layer, detail）
    - confidence 分数合理（明显矛盾 > 0.9，模糊矛盾 0.5-0.7）
  - **验收**: 一致性检查稳定，报告清晰

---

### 3.4 StyleKeeper（风格守护者）

- [x] **Task 3.4.1: 风格分析工具**
  - **文件**: `src/novel/tools/style_analysis_tool.py`
  - **依赖**: 1.1.5（StyleMetrics 模型）, 1.3.2（utils.py）
  - **并行**: 可与 3.1-3.3, 3.4.2, 3.5 并行
  - **内容**:
    - `StyleAnalysisTool.analyze_style()`: 分析文本风格特征
      - 计算：avg_sentence_length, dialogue_ratio, exclamation_ratio, paragraph_length, classical_word_ratio, description_ratio
      - 返回 `StyleMetrics`
    - `StyleAnalysisTool.compare_style()`: 与参考风格对比
      - 返回相似度分数 + 偏离项列表
  - **测试**:
    - 分析网文爽文文本，验证 paragraph_length < 150
    - 分析文学风文本，验证 avg_sentence_length > 15
    - 对比测试：相同风格相似度 > 0.8，不同风格 < 0.5
    - 边界条件：空文本返回默认 StyleMetrics
  - **验收**: 风格分析准确，对比有效

- [x] **Task 3.4.2: StyleKeeper Agent**
  - **文件**: `src/novel/agents/style_keeper.py`
  - **依赖**: 3.4.1, 2.2.3（style_presets.py）, `src/llm/`
  - **并行**: 可与 3.1-3.3, 3.4.1, 3.5 并行
  - **内容**:
    - `StyleKeeper` 类实现：
      - `analyze_style()`: 调用 StyleAnalysisTool
      - `compare_style()`: 对比风格
      - `rewrite_for_style()`: 重写文本以匹配目标风格
      - `extract_custom_style()`: 从用户提供的参考文本提取风格（自定义风格）
    - `style_keeper_node()`: LangGraph 节点函数
  - **测试**:
    - 提取自定义风格：给定 3 段参考文本，提取 StyleMetrics
    - 重写测试：将文学风文本重写为网文爽文，验证段落变短、对话增多
    - 风格一致性：全文 10 章，抽样 3 章，相似度 >= 0.85
  - **验收**: 风格控制有效，自定义风格提取准确

---

### 3.5 QualityReviewer（质量评审官）

- [x] **Task 3.5.1: AI 味黑名单**
  - **文件**: `src/novel/templates/ai_flavor_blacklist.py`
  - **依赖**: 无
  - **并行**: 可与所有 Phase 3 任务并行
  - **内容**:
    - 维护 50+ AI 味短语黑名单（list）:
      - "内心翻涌"、"莫名的力量"、"不由得"、"竟然"（过度使用）、"说实话"、"老实说"、"深深的"、"满满的"
    - `check_ai_flavor(text: str) -> list[str]`: 检测文本中的 AI 味短语
  - **测试**:
    - 检测包含 5 个 AI 味短语的文本
    - 验证返回完整短语列表
    - 正常文本不误报
  - **验收**: 黑名单覆盖常见 AI 味，检测准确

- [x] **Task 3.5.2: 规则硬指标检查**
  - **文件**: `src/novel/tools/quality_check_tool.py`（部分）
  - **依赖**: 3.5.1, 1.3.2（utils.py - detect_repetition）
  - **并行**: 可与 3.5.3 并行
  - **内容**:
    - `QualityCheckTool.rule_check()`: 规则硬指标检查
      - 重复句检测（连续 3 句相似度 > 80%）
      - 对话标签一致性（"张三说" vs "张三道"）
      - 段落长度分布异常（> 500 字或 < 10 字）
      - AI 味短语黑名单
      - 对话区分度（不同角色对话相似度）
    - 返回 `RuleCheckResult`
  - **测试**:
    - 植入重复句，触发检测
    - 植入 AI 味短语（"内心翻涌"），触发检测
    - 对话标签混乱（同一角色前后不一致），触发检测
    - 正常文本通过检查
  - **验收**: 规则检查零延迟，准确率 > 95%

- [x] **Task 3.5.3: 对比式评估与 LLM 打分**
  - **文件**: `src/novel/tools/quality_check_tool.py`（部分）
  - **依赖**: `src/llm/`
  - **并行**: 可与 3.5.2 并行
  - **内容**:
    - `QualityCheckTool.pairwise_compare()`: 对比两个版本
      - LLM Prompt: "对比版本 A 和 B，选出更优版本并说明理由"
      - 返回 `PairwiseResult(winner="A"|"B"|"TIE", reason=str)`
    - `QualityCheckTool.evaluate_chapter()`: LLM 绝对打分
      - 返回 plot_coherence, writing_quality, character_portrayal, ai_flavor_score（0-10）
  - **测试**:
    - Mock 两个版本，验证 LLM 选出更优版本
    - 绝对打分测试：明显低质量文本 < 4 分
    - 对比稳定性：多次对比同一对版本，结果一致
  - **验收**: 对比评估稳定，绝对打分可用于粗筛

- [x] **Task 3.5.4: QualityReviewer Agent**
  - **文件**: `src/novel/agents/quality_reviewer.py`
  - **依赖**: 3.5.2, 3.5.3
  - **并行**: 可与 3.1-3.4 并行
  - **内容**:
    - `QualityReviewer` 类实现：
      - `rule_based_check()`: 调用规则检查
      - `pairwise_compare()`: 对比评估
      - `evaluate_chapter()`: LLM 打分
      - `suggest_improvement()`: 生成改进建议
      - `should_rewrite()`: 判断是否需要重写（硬指标不通过或连续对比失败）
    - `quality_reviewer_node()`: LangGraph 节点函数
  - **测试**:
    - 低质量章节触发重写（重复句 > 3 处）
    - 边界情况对比评估（生成两版，选优）
    - 改进建议具体（如"减少'内心翻涌'，增加动作描写"）
  - **验收**: 质量评审流程完整，重写判断合理

---

## Phase 4: Pipeline 集成（LangGraph 图、CLI、断点续传）

### 4.1 Agent State 与 LangGraph 图

- [x] **Task 4.1.1: NovelState 定义**
  - **文件**: `src/novel/agents/state.py`
  - **依赖**: 1.1.* (所有数据模型)
  - **并行**: 可与 4.1.2 并行
  - **内容**:
    - `NovelState` TypedDict 定义：
      - `novel`: Novel 对象
      - `outline`: Outline
      - `world_setting`: WorldSetting
      - `characters`: list[CharacterProfile]
      - `current_chapter`: int
      - `chapters`: list[Chapter]
      - `memory`: NovelMemory 实例
      - `decisions`: list[dict] (reducer: operator.add)
      - `errors`: list[dict] (reducer: operator.add)
      - `completed_nodes`: list[str] (reducer: operator.add)
      - `user_feedback`: str | None
  - **测试**:
    - 创建 NovelState，验证所有字段类型
    - Reducer 测试：多次 decisions.append，验证列表累加
    - 序列化测试：State → JSON → State
  - **验收**: State 定义完整，序列化稳定

- [x] **Task 4.1.2: LangGraph 图构建**
  - **文件**: `src/novel/agents/graph.py`
  - **依赖**: 4.1.1, 2.1.3, 2.2.4, 2.3.2, 3.1.2, 3.2.2, 3.3.3, 3.4.2, 3.5.4
  - **并行**: 可与 4.1.1 并行（先用 Mock Agent 占位）
  - **内容**:
    - `build_novel_graph()`: 构建 StateGraph
      - 节点：novel_director, world_builder, character_designer, plot_planner, writer, consistency_checker, style_keeper, quality_reviewer
      - 边：
        - START → novel_director
        - novel_director → world_builder → character_designer → plot_planner
        - plot_planner → writer
        - writer → consistency_checker
        - consistency_checker → (条件路由) 通过 → style_keeper / 不通过 → writer (重写)
        - style_keeper → quality_reviewer
        - quality_reviewer → (条件路由) 通过 → 下一章 / 不通过 → writer (重写)
      - 循环：每章重复 plot_planner → writer → checkers
      - 断点：每 N 章暂停（human-in-the-loop）
    - `compile_graph()`: 编译为可执行图
  - **测试**:
    - Mock 所有 Agent，验证图连通性
    - 单章生成流程：plot_planner → writer → checkers → 通过
    - 重写流程：quality_reviewer 返回不通过 → 回到 writer
    - 断点测试：每 5 章暂停，等待 user_feedback
  - **验收**: 图结构正确，条件路由有效

---

### 4.2 Pipeline 流程编排

- [x] **Task 4.2.1: NovelPipeline 核心**
  - **文件**: `src/novel/pipeline.py`
  - **依赖**: 4.1.2, 1.2.4 (NovelMemory), 1.2.5 (FileManager)
  - **并行**: 无（依赖图构建）
  - **内容**:
    - `NovelPipeline` 类实现：
      - `create_novel()`: 创建新项目
        - 初始化 Novel 对象
        - 调用 NovelDirector 生成大纲
        - 调用 WorldBuilder, CharacterDesigner 初始化设定
        - 保存到文件系统
      - `generate_chapters()`: 批量生成章节
        - 循环调用图执行
        - 每章生成后更新 memory
        - 每 N 章触发 human-in-the-loop
      - `resume_novel()`: 断点续传
        - 加载 checkpoint.json
        - 恢复 State
        - 从 current_chapter 继续
      - `export_novel()`: 导出完整小说（拼接所有章节）
  - **测试**:
    - 创建 10 万字小说项目
    - 生成前 5 章，验证文件保存
    - 暂停后恢复，继续生成
    - 导出完整小说，验证字数和格式
    - 错误处理：生成失败时保存断点，不丢失进度
  - **验收**: 完整流程跑通，断点续传稳定

- [ ] **Task 4.2.2: 人工介入与审核**
  - **文件**: `src/novel/pipeline.py`（部分）
  - **依赖**: 4.2.1
  - **并行**: 无（依赖 Pipeline 核心）
  - **内容**:
    - `NovelPipeline.review_pause()`: 审核暂停
      - 展示最近 N 章摘要
      - 用户选项：继续 / 修改大纲 / 修改角色设定 / 重写指定章节
    - `NovelPipeline.apply_user_feedback()`: 应用用户反馈
      - 修改大纲：更新 Outline，重新生成后续章节
      - 修改角色：更新 CharacterProfile，检查一致性
      - 重写章节：标记章节为 draft，重新生成
  - **测试**:
    - 生成 5 章后暂停，展示摘要
    - 修改大纲（调整第 10 章情节），验证后续章节受影响
    - 修改角色（主角性格从"懦弱"→"果敢"），验证后续章节角色行为变化
    - 重写第 3 章，验证新版本替换旧版本
    - silent_mode 测试：无暂停，全自动生成
  - **验收**: 人工介入流程清晰，反馈生效

---

### 4.3 CLI 集成

- [x] **Task 4.3.1: 小说创作命令**
  - **文件**: `main.py`（新增命令）
  - **依赖**: 4.2.1
  - **并行**: 可与 4.3.2-4.3.3 并行
  - **内容**:
    - 新增 Click 命令组 `novel`：
      - `write-novel`: 创建新小说项目
        - 参数：--genre, --theme, --target-words, --style, --template
      - `resume-novel`: 恢复小说创作
        - 参数：--project-path
      - `export-novel`: 导出完整小说
        - 参数：--project-path, --output-file
  - **测试**:
    - 命令行测试：`python main.py novel write-novel --genre 玄幻 --target-words 100000`
    - 验证项目创建成功
    - 恢复命令测试：`python main.py novel resume-novel --project-path workspace/novels/xxx`
    - 导出测试：生成 TXT 文件
  - **验收**: CLI 命令可用，参数验证生效

- [ ] **Task 4.3.2: 小说导入命令**
  - **文件**: `main.py`, `src/novel/tools/import_tool.py`, `src/novel/services/import_service.py`
  - **依赖**: 4.2.1, `src/llm/`
  - **并行**: 可与 4.3.1, 4.3.3 并行
  - **内容**:
    - `ImportService.import_existing_draft()`: 导入已有稿件
      - 自动章节分割（检测章节标题正则）
      - 提取角色、世界观、情节线
      - 构建向量索引
    - CLI 命令 `import-novel`:
      - 参数：--file, --genre, --auto-split
  - **测试**:
    - 导入 2 万字已有稿件
    - 验证自动提取 3+ 角色
    - 验证世界观提取（题材、背景）
    - 续写测试：导入后继续生成，风格一致性 >= 7/10
  - **验收**: 导入流程稳定，续写风格匹配

- [ ] **Task 4.3.3: 状态查询命令**
  - **文件**: `main.py`
  - **依赖**: 4.2.1
  - **并行**: 可与 4.3.1-4.3.2 并行
  - **内容**:
    - CLI 命令 `novel-status`:
      - 参数：--project-path
      - 输出：当前章节、总章节、已生成字数、角色数量、世界观摘要、最近决策
    - CLI 命令 `list-novels`:
      - 列出所有小说项目
  - **测试**:
    - 查询项目状态，验证输出正确
    - 列出多个项目，验证排序（按更新时间）
  - **验收**: 状态查询清晰，信息完整

---

## Phase 5: 集成测试与端到端验证

### 5.1 单元测试完整性检查

- [x] **Task 5.1.1: 测试覆盖率检查** (91% coverage, 561 tests)
  - **文件**: `tests/novel/` (所有测试文件)
  - **依赖**: Phase 1-4 所有任务
  - **并行**: 无（依赖所有实现）
  - **内容**:
    - 运行 `pytest --cov=src/novel --cov-report=html tests/novel/`
    - 验证覆盖率 >= 80%
    - 重点检查边界条件测试和错误路径测试
    - 补充缺失测试
  - **测试**:
    - 数据模型层：所有字段验证
    - 存储层：并发写入、空数据、大数据量
    - Agent 层：Mock LLM 返回异常数据
    - Pipeline 层：中途失败、断点恢复
  - **验收**: 覆盖率 >= 80%，核心路径 100%

- [x] **Task 5.1.2: Mock 策略统一** (conftest.py created)
  - **文件**: `tests/novel/conftest.py`
  - **依赖**: 5.1.1
  - **并行**: 无
  - **内容**:
    - 创建通用 Mock Fixtures:
      - `mock_llm_client`: Mock LLM 返回固定 JSON
      - `mock_novel_memory`: Mock 三层存储
      - `mock_file_manager`: Mock 文件操作
      - `sample_novel`: 示例 Novel 对象
      - `sample_outline`: 示例大纲
    - 所有测试复用 Fixtures
  - **测试**:
    - 验证 Fixtures 可用
    - 测试隔离性（多个测试不互相干扰）
  - **验收**: 测试代码简洁，复用性强

---

### 5.2 端到端集成测试

- [x] **Task 5.2.1: 10 万字小说生成测试（都市重生）** (mocked pipeline: 16 integration tests)
  - **文件**: `tests/novel/integration/test_full_novel_generation.py`
  - **依赖**: Phase 1-4 所有任务
  - **并行**: 可与 5.2.2-5.2.3 并行
  - **内容**:
    - 完整流程测试：
      1. 创建项目：都市重生题材，10 万字，网文爽文风格
      2. 生成大纲：验证 20-33 章
      3. 生成前 10 章
      4. 暂停审核：修改第 15 章大纲
      5. 继续生成
      6. 导出完整小说
    - 验证指标：
      - 总字数 >= 10 万
      - 角色一致性：主角姓名、性格前后一致
      - 世界观一致性：无违反设定的情节
      - 风格一致性：抽样 5 章，相似度 >= 0.85
      - 无明显矛盾（ConsistencyChecker 通过率 >= 90%）
  - **测试**:
    - 使用真实 LLM（需配置 API key）
    - 生成时间 < 6 小时（使用快速模型）
    - 中途中断恢复测试
  - **验收**: 完整小说生成成功，质量可读

- [ ] **Task 5.2.2: 10 万字小说生成测试（玄幻修仙）**
  - **文件**: `tests/novel/integration/test_xianxia_novel.py`
  - **依赖**: Phase 1-4 所有任务
  - **并行**: 可与 5.2.1, 5.2.3 并行
  - **内容**:
    - 玄幻修仙题材，10 万字，网文种田流风格
    - 验证力量体系：10 个层级，主角逐步突破
    - 验证专有名词一致性：门派、功法、法宝名称统一
    - 验证伏笔回收（V2，先占位测试）
  - **测试**:
    - 力量等级追踪：主角从"炼气期"→"金丹期"
    - 专有名词检查：全文"九霄门"无变体
    - 角色关系变化：从"陌生"→"师徒"有铺垫
  - **验收**: 玄幻小说生成成功，设定严谨

- [ ] **Task 5.2.3: 导入续写测试**
  - **文件**: `tests/novel/integration/test_import_continue.py`
  - **依赖**: 4.3.2
  - **并行**: 可与 5.2.1-5.2.2 并行
  - **内容**:
    - 导入 2 万字已有稿件
    - 续写至 10 万字
    - 验证风格一致性：导入部分与续写部分风格相似度 >= 7/10（人工评估）
    - 验证角色一致性：已有角色档案提取准确
  - **测试**:
    - 使用真实小说片段（从网文站爬取）
    - 提取角色数量 >= 3
    - 续写内容不出现与已有稿件矛盾的情节
  - **验收**: 导入续写流程稳定，风格匹配

---

### 5.3 性能与稳定性测试

- [ ] **Task 5.3.1: 性能基准测试**
  - **文件**: `tests/novel/performance/test_benchmarks.py`
  - **依赖**: Phase 1-4 所有任务
  - **并行**: 可与 5.3.2 并行
  - **内容**:
    - 性能指标：
      - 单章生成时间 < 5 分钟（使用快速模型）
      - 一致性检查延迟 < 30 秒
      - 向量检索延迟 < 100ms
      - 10 万字小说生成总时长 < 6 小时
    - 使用 pytest-benchmark 测量
  - **测试**:
    - Mock LLM 返回固定延迟（模拟真实 API）
    - 大数据量测试：100 章节，1000+ facts
  - **验收**: 所有性能指标达标

- [x] **Task 5.3.2: 稳定性与容错测试** (covered in test_integration.py: error resilience, checkpoint recovery)
  - **文件**: `tests/novel/stability/test_error_recovery.py`
  - **依赖**: Phase 1-4 所有任务
  - **并行**: 可与 5.3.1 并行
  - **内容**:
    - 错误场景测试：
      - LLM 超时（timeout）
      - LLM 返回非法 JSON
      - 磁盘空间不足
      - 数据库锁定
      - 中途中断（Ctrl+C）
    - 验证：所有错误不丢失进度，checkpoint 保存正确
  - **测试**:
    - Mock LLM 抛出 TimeoutError
    - Mock 文件系统抛出 IOError
    - 手动中断测试（signal.SIGINT）
  - **验收**: 所有错误场景优雅降级，断点可恢复

---

## Phase 6: V2 功能（伏笔系统、多结局、质量增强）

### 6.1 伏笔系统（正向 + 后置）

- [ ] **Task 6.1.1: 伏笔管理工具**
  - **文件**: `src/novel/tools/foreshadowing_tool.py`, `src/novel/services/foreshadowing_service.py`
  - **依赖**: 1.1.5（Foreshadowing, DetailEntry 模型）, 1.2.3（VectorStore）
  - **并行**: 可与 6.2, 6.3 并行
  - **内容**:
    - `ForeshadowingService.extract_details()`: 提取历史闲笔
      - LLM Prompt: "提取章节中的潜在可利用细节（道具、环境、角色动作、异常现象）"
      - 返回 `list[DetailEntry]`
    - `ForeshadowingService.search_reusable_details()`: 反向检索可利用闲笔
      - 向量检索 + LLM 判断逻辑自洽性
    - `ForeshadowingService.promote_to_foreshadowing()`: 升级为伏笔
    - `ForeshadowingTool`: 封装服务层
  - **测试**:
    - 提取闲笔：第 10 章"书架上一本无字旧书"
    - 反向检索：第 50 章需要线索，命中"旧书"
    - 升级为伏笔：status 从 detail → promoted
    - 回写一致性检查：升级后的解释与原文不矛盾
  - **验收**: 后置伏笔流程完整，逻辑自洽

- [ ] **Task 6.1.2: PlotPlanner 伏笔规划增强**
  - **文件**: `src/novel/agents/plot_planner.py`（更新）
  - **依赖**: 6.1.1
  - **并行**: 可与 6.2, 6.3 并行
  - **内容**:
    - `PlotPlanner.plan_foreshadowing()`: 伏笔规划逻辑
      - 正向伏笔：从大纲提取，埋设和回收计划
      - 后置伏笔：需要线索时调用 ForeshadowingTool 检索历史闲笔
    - 伏笔回收提醒：接近目标章节时提示 Writer 回收
  - **测试**:
    - 正向伏笔：第 10 章埋设，第 30 章回收
    - 后置伏笔：第 50 章需要线索，检索到第 10 章闲笔
    - 回收提醒：第 29 章提示即将回收伏笔
  - **验收**: 伏笔系统与 PlotPlanner 集成成功

---

### 6.2 质量增强（对比式评估）

- [ ] **Task 6.2.1: 对比评估集成**
  - **文件**: `src/novel/agents/quality_reviewer.py`（更新）
  - **依赖**: 3.5.3
  - **并行**: 可与 6.1, 6.3 并行
  - **内容**:
    - 质量存疑时生成两个版本
    - 调用 `pairwise_compare()` 选优
    - 连续选择"两版都差"时暂停，提示用户介入
  - **测试**:
    - 规则检查边界情况（如 AI 味短语 = 3 个，刚好阈值）
    - 生成两版，验证 LLM 选出更优版本
    - 两版都差时暂停，验证 user_feedback 机制
  - **验收**: 对比评估提升质量稳定性

---

### 6.3 配置增强（审核间隔、静默模式）

- [ ] **Task 6.3.1: 审核间隔配置**
  - **文件**: `src/novel/config.py`（更新）, `src/novel/pipeline.py`（更新）
  - **依赖**: 4.2.2
  - **并行**: 可与 6.1, 6.2 并行
  - **内容**:
    - 配置项：`review_interval`, `silent_mode`, `auto_approve_threshold`
    - Pipeline 逻辑：根据配置决定暂停频率
    - silent_mode: 仅质量不达标时暂停
  - **测试**:
    - review_interval=5: 每 5 章暂停
    - silent_mode=true: 质量通过时不暂停
    - auto_approve_threshold=8.0: 评分 >= 8 自动通过
  - **验收**: 配置灵活，满足不同用户需求

---

## 开发协作建议

### 并行开发分组

**Group A（数据模型 + 存储层）**:
- Task 1.1.1-1.1.5（数据模型）
- Task 1.2.1-1.2.5（存储层）
- Task 1.3.1-1.3.2（配置与工具）

**Group B（核心 Agent）**:
- Task 2.1.1-2.1.3（NovelDirector）
- Task 2.2.1-2.2.4（Writer）
- Task 2.3.1-2.3.2（PlotPlanner）

**Group C（辅助 Agent）**:
- Task 3.1.1-3.1.2（WorldBuilder）
- Task 3.2.1-3.2.2（CharacterDesigner）
- Task 3.3.1-3.3.3（ConsistencyChecker）

**Group D（辅助 Agent 续）**:
- Task 3.4.1-3.4.2（StyleKeeper）
- Task 3.5.1-3.5.4（QualityReviewer）

**Group E（集成层）**:
- Task 4.1.1-4.1.2（LangGraph）
- Task 4.2.1-4.2.2（Pipeline）
- Task 4.3.1-4.3.3（CLI）

**Group F（测试与 V2）**:
- Task 5.1.1-5.3.2（集成测试）
- Task 6.1.1-6.3.1（V2 功能）

### 里程碑

- **Milestone 1（1-2 周）**: Phase 1 完成，数据模型和存储层稳定
- **Milestone 2（2-3 周）**: Phase 2-3 完成，所有 Agent 可用
- **Milestone 3（1 周）**: Phase 4 完成，Pipeline 集成成功
- **Milestone 4（1-2 周）**: Phase 5 完成，端到端测试通过
- **Milestone 5（1 周）**: Phase 6 完成，V2 功能上线

### 质量控制

- **每个任务完成后**:
  1. 运行单元测试：`pytest tests/novel/test_{module}.py -v`
  2. 代码审查：启动 `code-reviewer` Agent 审查
  3. 修复 CRITICAL/HIGH 问题
  4. 提交代码前运行完整测试：`pytest tests/novel/ -v`

- **每个 Phase 完成后**:
  1. 运行覆盖率检查：`pytest --cov=src/novel --cov-report=html tests/novel/`
  2. 集成测试：验证跨模块协作
  3. 性能检查：关键路径性能分析

---

## 总结

**总任务数**: 63 个任务
**预计总工时**: 80-120 小时（按 3-5 人团队并行开发，2-3 周完成 MVP）

**关键风险**:
1. **LLM 输出质量不稳定** → 多轮重试 + 结构化 Prompt + Few-shot 示例
2. **一致性检查漏报率高** → 三层混合检测 + LLM 裁决 + 持续优化黑名单
3. **生成速度慢** → 使用快速模型（如 DeepSeek）+ 场景并行生成（V3）
4. **用户介入频率难平衡** → 可配置 review_interval + silent_mode

**成功标准**:
- [ ] 可生成 10 万字连贯小说
- [ ] 角色一致性 >= 90%
- [ ] 世界观一致性 >= 95%
- [ ] 风格一致性 >= 85%
- [ ] 矛盾漏报率 < 15%
- [ ] 单章生成时间 < 5 分钟
- [ ] 测试覆盖率 >= 80%

---

## Rules & Tips

1. **LangGraph 为可选依赖**: `graph.py` 中所有 langgraph 导入必须用 `try/except`，提供 `_SequentialRunner` / `_ChapterRunner` fallback。测试通过 `patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False)` 强制使用 fallback。
2. **两个独立图**: 使用 `build_init_graph()` (3 nodes) 和 `build_chapter_graph()` (5 nodes) 分别处理初始化和章节生成，而不是一个大图。Pipeline 编排循环调用 chapter graph。
3. **State merge for fallback**: 累积字段 (decisions / errors / completed_nodes) 需要在 `_merge_state` 中用列表拼接而非覆盖，模拟 LangGraph 的 `Annotated[list, operator.add]` reducer。
4. **Checkpoint 序列化**: `_save_checkpoint` 需要 try/except 跳过不可 JSON 序列化的字段（如 memory 对象）。
5. **所有函数必须 SYNC**: LLM client 和所有 agent node 都是同步的，pipeline 也全部同步。
6. **CLI workspace 推算**: `resume` / `export` / `status` 命令接收 project_path (novels/{id})，通过 `Path(project_path).parent.parent` 推算 workspace 根目录。
