# AI 长篇小说写作模块 - 需求分析文档

## 1. 产品定位与目标用户

### 1.1 产品定位

**核心价值主张**: 为内容创作者提供 AI 辅助的长篇小说创作工具，支持从大纲规划到章节生成的完整创作流程，兼顾质量与效率。

**差异化优势**:
- **结构化创作**: 不是简单的"续写"工具，而是基于大纲驱动的层次化生成系统
- **长文一致性**: 通过角色档案、世界观管理、伏笔追踪确保数万字内容的连贯性
- **风格可控**: 二级风格体系（4 大类 × 8-10 子类预设）+ 自定义风格（用户提供参考文本自动模仿）
- **与现有 Pipeline 集成**: 生成的小说可直接输入视频生成流程，实现"创作→传播"闭环

**产品边界**:
- **IN SCOPE**: 商业网文、类型小说（武侠、玄幻、都市、科幻、言情、悬疑）
- **OUT OF SCOPE**: 诗歌、剧本、非虚构写作（这些需要不同的生成逻辑）

### 1.2 目标用户

**主要用户群体**:

1. **网文作者（核心用户）**
   - 痛点: 日更压力大、灵感枯竭、情节重复
   - 需求: 快速生成大纲、辅助扩写情节、保持角色一致性
   - 使用场景: 日更 4000-8000 字，月产 10-20 万字

2. **短视频内容创作者（次要用户）**
   - 痛点: 缺少原创剧本，改编版权复杂
   - 需求: 生成适合短视频改编的短篇/中篇故事
   - 使用场景: 生成 3000-10000 字小说 → 转为 3-5 分钟视频

3. **兴趣创作者（长尾用户）**
   - 痛点: 有创意但缺乏写作技巧
   - 需求: 通过提示词引导 AI 完成创作
   - 使用场景: 创作同人、脑洞故事

**非目标用户**:
- 传统文学作家（对 AI 辅助抗拒，需求不匹配）
- 学术写作者（需求完全不同）

---

## 2. 核心功能清单（MVP / V2 / V3 分阶段）

### 2.1 MVP 阶段（最小可用产品）

**目标**: 验证核心价值 —— 能否生成连贯的长篇小说

#### FR-MVP-1: 大纲生成与管理
**优先级**: P0

**功能描述**:
- 用户输入: 题材、主题、核心冲突、字数目标（如"10 万字都市重生小说"）
- 系统输出: 三层大纲
  - **总大纲**: 支持多种结构模板（用户可选）
    - **循环升级模板**: 适合玄幻/都市/系统流，"升级→遇敌→苦战→突破"循环递进
    - **多线交织模板**: 适合群像/宫斗/悬疑，多条线索并行推进、交汇
    - **经典四幕模板**: 适合中篇/电影感故事，开端/发展/高潮/结局
    - **自由模板**: 用户自定义结构，支持开放式结尾
  - **卷大纲**: 每卷 3-5 章，明确卷内矛盾与解决
  - **章大纲**: 每章核心事件、涉及角色、推进主线/支线

**WHY（设计理由）**:
- 长篇小说的核心挑战是结构混乱。大纲驱动可确保生成过程有明确方向
- 层次化大纲便于断点续写（章节级粒度）和局部调整
- 参考网文行业经验：成熟作者都是"先大纲后写作"

**验收标准**:
- 生成的大纲包含至少 10 个章节
- 每章大纲明确"本章目标"和"关键事件"
- 章节间有逻辑递进关系

---

#### FR-MVP-2: 角色档案系统
**优先级**: P0

**功能描述**:
- 自动从大纲提取主要角色（3-10 人）
- 为每个角色建立档案:
  - **基础属性**: 姓名、性别、年龄、职业
  - **外貌特征**: 身高、发型、服装风格（可选配图）
  - **性格标签**: 3-5 个关键词（如"冷静、腹黑、护短"）
  - **关系网**: 与其他角色的关系（15 种类型: 敌对/友好/暧昧/师徒/竞争/利用/依赖/崇拜/畏惧/合作/背叛等），带时间维度的关系变化链
  - **成长弧线**: 角色在故事中的转变（如"懦弱→果敢"）

**WHY**:
- 长篇小说最大问题是角色 OOC（Out Of Character，行为不符合性格）
- 每次生成章节时，系统需引用档案确保角色行为一致
- 关系网防止"张三第 5 章和李四是仇人，第 20 章突然成兄弟"的矛盾

**验收标准**:
- 系统能从大纲自动提取至少 3 个主角
- 每个角色档案包含完整的基础信息和性格标签
- 生成章节时，涉及角色的描写符合其档案设定

---

#### FR-MVP-3: 世界观设定管理
**优先级**: P0

**功能描述**:
- 根据题材建立世界观框架:
  - **时空背景**: 年代、地域（如"现代上海"、"架空仙侠世界"）
  - **力量体系**: 武侠的内力等级、玄幻的修炼境界、科幻的科技树
  - **关键设定**: 特殊规则（如"灵气复苏后普通人也能修炼"）
  - **专有名词表**: 门派名、法宝名、地名等（确保全文统一）

**WHY**:
- 类型小说高度依赖设定。力量体系混乱会导致战力崩溃
- 专有名词不统一是 AI 生成的典型问题（前文"九霄门"后文变"九天宗"）
- 世界观是角色行为的约束条件（现代都市角色不能突然施展法术）

**验收标准**:
- 玄幻/武侠题材自动生成力量等级体系（至少 5 个层级）
- 系统维护专有名词表，生成时强制复用
- 章节内容不出现违反世界观设定的情节

---

#### FR-MVP-4: 章节生成引擎
**优先级**: P0

**功能描述**:
- **输入**: 章大纲 + 角色档案 + 世界观 + 前文摘要（最近 3 章）
- **输出**: 2000-5000 字章节正文
- **生成策略**:
  - 采用"场景分解"法: 1 章拆为 3-5 个场景，逐场景生成
  - 每个场景包含: 环境描写、对话、动作、心理描写
  - 自动在章末埋设悬念（钩子）用于下章

**WHY**:
- 直接生成 5000 字质量差。分场景生成可控性更强
- 场景是叙事基本单位，便于后续修改和重新生成
- 章末悬念是网文的核心技巧，提升阅读粘性

**验收标准**:
- 单章生成时间 < 5 分钟（使用快速模型）
- 生成内容包含对话、动作、环境描写三要素
- 章节与大纲匹配度 >= 80%（人工评审）

---

#### FR-MVP-5: 上下文一致性检查
**优先级**: P0

**功能描述**:
- **矛盾检测**:
  - 时间线矛盾（第 5 章是春天，第 6 章突然冬天）
  - 角色状态矛盾（上章受重伤，本章活蹦乱跳）
  - 设定矛盾（前文说主角不会武功，后文突然使出降龙十八掌）
  - 角色关系矛盾（关系变化缺乏铺垫，ConsistencyChecker 检查 RelationshipEvent 链）
- **三层混合检测机制**:
  - **第一层: 结构化数据库（SQLite）— 精确查询**:
    - 角色状态表: (character_id, chapter, health, location, power_level, emotional_state)
    - 时间线表: (chapter, scene, absolute_time, relative_time)
    - 力量等级追踪: 严格检查战力变化是否合理
    - 专有名词表: 强制一致性（零容忍）
  - **第二层: 轻量知识图谱（NetworkX）— 关系查询**:
    - 角色关系网: 节点=角色，边=关系类型+强度
    - 势力/阵营归属图: 检测阵营切换是否有逻辑
    - 地点连通图: 检测位移是否合理（A地到B地是否需要经过C地）
  - **第三层: 向量检索（Chroma）— 语义兜底**:
    - 存储已生成章节的关键信息
    - 用于检测前两层无法覆盖的隐性矛盾（如语义层面的性格不一致）
    - 每生成新章，提取关键事实与历史对比
  - 发现矛盾时暂停生成，提示用户修改

**WHY**:
- 长文一致性是 AI 写作的核心难题。LLM 上下文窗口有限（即使 128K 也无法完整记住 10 万字小说）
- 纯向量检索漏报率高（语义相似不等于事实矛盾），结构化查询更可靠
- 知识图谱天然适合关系类查询（"A和B什么关系"比向量检索精确得多）
- 三层互补: 结构化数据库查硬事实、知识图谱查关系、向量检索兜底软矛盾
- 主动检测比事后修改成本低
- 矛盾会严重破坏阅读体验

**验收标准**:
- 能检测出人工植入的明显矛盾（如角色死亡后复活）
- 误报率 < 20%（不能过于严格导致无法继续）
- **漏报率 < 15%**（对人工植入的 20 个矛盾，至少检测出 17 个）
- 检测延迟 < 30 秒

---

#### FR-MVP-6: 风格控制
**优先级**: P1

**功能描述**:
- **二级风格体系**:
  - **大类（4 种）**:
    - 武侠风: 文言韵味、武侠意境、慢节奏
    - 网文风: 短句、快节奏、对话多、金手指明显
    - 文学风: 意识流、细腻心理描写、隐喻
    - 轻小说风: 日系轻小说语感、大量对话、吐槽
  - **子类（8-10 种预设）**:
    - 网文-爽文: 极致打脸、装逼、金手指，节奏极快
    - 网文-种田流: 经营发展、细节描写，节奏舒缓
    - 网文-系统流: 系统面板、任务提示，游戏化叙事
    - 网文-黑暗流: 压抑氛围、残酷现实、反套路
    - 网文-无敌流: 碾压一切、极致爽感
    - 武侠-古言风: 半文言、诗词引用、古典美
    - 文学-现实主义: 白描手法、社会题材、人性刻画
    - 轻小说-后宫: 多女主互动、轻松搞笑
  - **自定义风格（P1）**: 用户提供 1-3 段参考文本（1000-3000 字），系统自动提取风格特征并模仿
    - 分析维度: 平均句长、对话占比、常用词频、叙事视角、描写密度
    - 生成风格配置文件，后续章节复用
- **风格实现**:
  - 通过 System Prompt 注入风格指令
  - Few-shot 示例（提供 2-3 段参考文本）
  - 关键词约束（如网文风要求"每段 < 150 字"）

**WHY**:
- 风格统一是专业作品的标志
- 不同用户群体偏好不同（网文读者接受不了文学风的拖沓）
- 风格是品牌识别要素
- 二级结构覆盖主流网文细分市场，自定义风格满足个性化需求

**验收标准**:
- 提供至少 8 种风格预设（大类 + 子类组合）
- 同一章节用不同风格生成，人工可明显区分
- 全文风格一致性 >= 85%（抽样检查）
- 自定义风格: 给定参考文本后，生成内容与参考文本的风格相似度人工评估 >= 7/10

---

#### FR-MVP-7: 导入已有稿件
**优先级**: P0

**功能描述**:
- 用户已有部分稿件（几千到几万字），系统自动解析并导入:
  - **自动提取**: 从已有文本中提取角色档案、世界观设定、情节线、时间线
  - **构建记忆**: 将已有内容向量化存储，建立一致性检查基线
  - **生成摘要**: 为每个已有章节生成摘要，填充分层记忆
- **三种使用场景**:
  - **续写**: 用户写了开头 N 章，系统接续后面的章节（最常见场景）
  - **改写**: 用户对某些章节不满意，系统基于上下文重写指定章节
  - **扩写**: 用户有简短大纲或梗概，系统扩展为完整章节
- **导入流程**:
  1. 用户上传 TXT 文件（支持自动章节分割或手动标记）
  2. 系统调用 LLM 提取角色、设定、情节线
  3. 展示提取结果，用户确认/修正
  4. 建立向量索引和分层记忆
  5. 根据选择的场景（续写/改写/扩写）开始创作

**WHY**:
- 大部分用户不是从零开始，而是"写了一半写不下去"
- 续写是最真实的使用场景，缺少此功能会丢失核心用户
- 已有稿件是最好的风格参考来源（自定义风格的天然输入）

**验收标准**:
- 支持导入 1000-100000 字的已有稿件
- 自动提取角色准确率 >= 80%（主要角色不遗漏）
- 续写内容与已有稿件风格一致性 >= 7/10（人工评估）
- 不出现与已有稿件矛盾的内容

---

### 2.2 V2 阶段（增强版）

**目标**: 提升创作质量与效率

#### FR-V2-1: 伏笔与线索追踪（含后置伏笔）
**优先级**: P1

**功能描述**:

**A. 正向伏笔（传统模式）**:
- 系统维护"伏笔表":
  - 埋设章节、伏笔内容、计划回收章节
  - 状态: 待回收、已回收、已废弃
- 生成时:
  - 在合适位置自动埋伏笔（由 Planner Agent 决定）
  - 接近回收章节时提示回收，生成时强制包含
- 用户可手动标记伏笔

**B. 后置伏笔（反向利用历史闲笔）**:

真实创作中，很多伏笔不是预先设计的，而是写到后面需要线索时，回头发现前文某个随手写的细节恰好可以利用。读者看来是"70 章前就埋好的伏笔"，实际是后置回收。

实现机制:
- **闲笔收集**: 每章生成后，除提取关键事实外，额外提取"潜在可利用细节"（道具、环境描写、角色小动作、未解释的异常等），标记为 `detail` 类型存入向量库
- **反向检索**: 当 PlotPlanner 需要一个线索/转折但大纲中没有预设时，检索历史闲笔：
  ```
  查询: "与{当前需要的线索类型}相关的历史细节"
  → 命中第 10 章: "书架上一本无字旧书"
  → 升级为伏笔: "旧书是师父用隐墨写的修炼笔记"
  ```
- **升级为伏笔**: 一旦闲笔被利用，状态从 `detail` → `foreshadowing`，记录原始章节和回收章节
- **回写一致性**: 确保回收内容与原文不矛盾（原文说"无字旧书"，可以变成"隐墨"，但不能变成"一把剑"）

```python
class DetailEntry(TypedDict):
    """历史闲笔条目"""
    detail_id: str
    chapter: int                   # 出现章节
    content: str                   # "书架上一本无字旧书"
    context: str                   # 原文上下文（前后 2 句）
    category: str                  # 道具/环境/角色动作/异常现象
    status: str                    # detail | promoted_to_foreshadowing | used
    promoted_as: str | None        # 被利用时的新解释
```

**WHY 需要后置伏笔**:
- 这是职业作者最常用的技巧之一（"挖旧坑"），读者满意度极高
- 让 AI 创作更接近真人的灵活创作方式，而非死板执行预设大纲
- 避免"大纲里没写的就永远不能变成伏笔"的僵化问题
- 让前期的随机细节有了价值，增强全文的紧密感

**实现难点**:
- 判断哪些闲笔可以被合理利用（需要 LLM 判断逻辑自洽性）
- 回收时不能与原文产生矛盾（需要一致性检查配合）
- 正向伏笔和后置伏笔的混合管理

---

#### FR-V2-2: 多结局分支
**优先级**: P2

**功能描述**:
- 在关键章节（如第 50 章）生成 2-3 个不同的剧情走向
- 用户选择后，后续章节基于选定分支继续
- 用于探索"如果主角做了另一个选择会怎样"

**WHY**:
- 提升创作趣味性
- 互动小说的需求（V3 可能做互动阅读 App）

---

#### FR-V2-3: 质量自评与重写
**优先级**: P1

**功能描述**:
- **三层质量评估体系**:
  - **第一层: 规则硬指标（自动，零成本）**:
    - 重复句检测: 连续 3 句以上相似度 > 80% 视为重复
    - 对话标签一致性: 检查说话人标记是否前后匹配
    - 段落长度分布: 检测异常段落（过长 > 500 字或过短 < 10 字）
    - AI 味短语黑名单: 检测"内心翻涌"、"莫名的力量"、"不由得"、"竟然"过度使用等 AI 常见套话（维护 50+ 黑名单短语）
    - 对话区分度: 检测不同角色的对话是否过于相似（结合 CharacterProfile.speech_style）
  - **第二层: 对比式评估（pairwise comparison）**:
    - 对质量存疑的章节（硬指标不通过或边界情况），生成同一场景的 2 个版本
    - LLM 对比两个版本，选出更优版本并说明理由
    - 比绝对打分更稳定可靠，避免 LLM 自评的分数膨胀问题
  - **第三层: LLM 绝对打分（仅作为粗筛辅助）**:
    - 情节合理性、文笔流畅度、人物塑造、AI 味浓度（0-10 分）
    - 仅用于快速过滤明显低质量内容（< 4 分触发重写）
    - 不作为最终质量判断依据
- **重写触发条件**:
  - 硬指标不通过（如重复句 > 3 处）→ 自动重写
  - 对比评估连续选择"两版都差" → 暂停，提示用户介入
  - 最多重写 2 次

**WHY**:
- 复用视频 Agent 的质量控制经验
- AI 生成质量波动大，自检可过滤低质量内容
- LLM 绝对打分不可靠（倾向给高分），对比式评估更稳定
- 规则硬指标零成本、零延迟，可快速拦截明显问题

---

#### FR-V2-4: 人工介入点
**优先级**: P1

**功能描述**:
- 按可配置间隔暂停（默认每 5 章），展示摘要给用户
- **介入间隔配置**:
  - `review_interval`: 每 N 章暂停审核（默认 5，范围 1-50）
  - `silent_mode`: 静默模式（bool，默认 false）— 开启后仅在质量不达标时暂停，其余全自动
  - `auto_approve_threshold`: 自动通过阈值 — 质量评估全部通过时自动继续，无需人工确认
- 用户可以:
  - 修改大纲（调整后续剧情）
  - 修改角色设定（如"主角性格改为更冷酷"）
  - 标记需要重写的章节
- Human-in-the-Loop 确保方向可控

**WHY**:
- 完全自动生成 10 万字风险极高，中途失控无法挽回
- 用户需要保留创作主导权
- 网文作者习惯"写一段、看读者反馈、调整大纲"
- 不同用户对介入频率需求不同：新手需要频繁审核，熟练用户希望全自动

---

### 2.3 V3 阶段（未来展望）

- **多线程叙事**: 支持多主角、多视角并行推进
- **数据驱动优化**: 分析成功网文的情节模式，反哺生成
- **协作创作**: 多个用户共同创作一部小说
- **自动配图**: 为每章生成插图（复用 imagegen 模块）
- **语音朗读**: 自动生成有声书（复用 tts 模块）

---

## 3. Agent 架构设计

### 3.1 核心理念

**WHY 需要 Multi-Agent 而非单一 LLM**:

1. **职责分离**: 大纲规划、角色塑造、情节生成、质量把关需要不同的思维模式
2. **专业化**: 每个 Agent 专注一个领域，提示词更精准，质量更高
3. **可维护**: 出问题时易定位（如角色崩坏 → 检查 Character Agent）
4. **复用现有架构**: 视频 Agent 已验证 LangGraph 可行性

### 3.2 Agent 角色定义

```
┌─────────────────────────────────────────────────────────┐
│                   NovelDirector (总导演)                 │
│  职责: 接收用户需求 → 生成初始大纲 → 编排创作流程        │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│ World    │  │Character │  │ Plot     │
│ Builder  │  │ Designer │  │ Planner  │
│ 世界观   │  │ 角色设计 │  │ 情节规划 │
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │             │             │
     └─────────────┼─────────────┘
                   ▼
           ┌──────────────┐
           │  Writer      │
           │  正文生成    │
           └───────┬──────┘
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│Consistency│ │ Style   │ │ Quality  │
│Checker   │ │ Keeper  │ │ Reviewer │
│一致性检查│ │风格控制 │ │质量评审  │
└──────────┘ └──────────┘ └──────────┘
```

---

#### Agent-1: NovelDirector（总导演）

**职责**:
1. 解析用户输入（题材、字数、风格、核心创意）
2. 生成初始大纲（调用 LLM 生成 3 层大纲）
3. 协调其他 Agent 的工作顺序
4. 管理创作进度（当前写到第几章）
5. 处理用户的中途修改指令

**Tools**:
- `AnalyzeUserInputTool`: 提取关键信息（题材、主题、冲突）
- `GenerateOutlineTool`: 调用 LLM 生成大纲
- `UpdateOutlineTool`: 响应用户修改

**决策输出**:
- `outline`: 完整的 3 层大纲（dict 结构）
- `total_chapters`: 总章节数
- `current_chapter`: 当前进度
- `workflow_plan`: 各 Agent 的调用顺序

**WHY 需要这个 Agent**:
- 大纲是整个创作的"宪法"，必须由顶层 Agent 掌控
- 避免各 Agent 各自为政导致方向偏离

---

#### Agent-2: WorldBuilder（世界观构建师）

**职责**:
1. 根据题材建立世界观框架
2. 定义力量体系（武侠/玄幻）或科技树（科幻）
3. 维护专有名词表（地名、门派、法宝）
4. 检测设定矛盾

**Tools**:
- `CreateWorldSettingTool`: 生成世界观文档
- `DefinePowerSystemTool`: 定义力量等级
- `RegisterTermTool`: 注册专有名词
- `ValidateSettingTool`: 检查设定一致性

**决策输出**:
- `world_setting`: 世界观文档（JSON）
- `power_system`: 力量体系（如修炼境界表）
- `term_dict`: 专有名词表（如 {"九霄门": "主角所属门派"}）

**WHY 需要这个 Agent**:
- 世界观是类型小说的骨架。需要专门 Agent 维护
- 力量体系设计是专业技能，需要专用 Prompt 模板

---

#### Agent-3: CharacterDesigner（角色设计师）

**职责**:
1. 从大纲提取角色列表
2. 为每个角色生成详细档案
3. 定义角色关系网
4. 规划角色成长弧线
5. 监控角色一致性（防止 OOC）

**Tools**:
- `ExtractCharactersTool`: 从大纲提取角色
- `GenerateCharacterProfileTool`: 生成角色档案
- `DefineRelationshipTool`: 定义角色关系
- `TrackCharacterArcTool`: 追踪角色成长

**决策输出**:
- `characters`: 角色列表（list[CharacterProfile]）
- `relationships`: 关系网（graph 结构）
- `character_arcs`: 成长弧线（各角色在各章的状态）

**WHY 需要这个 Agent**:
- 角色是小说的灵魂。复杂的角色设定需要专门管理
- 关系网可防止逻辑错误（如仇人突然和解无铺垫）

---

#### Agent-4: PlotPlanner（情节规划师）

**职责**:
1. 将章大纲细化为场景序列
2. 规划伏笔埋设与回收（V2）
3. **设计章节情绪节奏（核心能力）**: 为每章标注情绪基调，确保张弛有度
4. 确保主线推进

**Tools**:
- `DecomposeChapterTool`: 章大纲 → 场景序列
- `PlanForeshadowingTool`: 规划伏笔（V2）
- `BalanceRhythmTool`（**核心工具**）: 节奏设计与调整
  - 为每章标注情绪基调: 蓄力 / 小爽 / 大爽 / 过渡 / 虐心 / 反转 / 日常
  - 检测节奏异常: 连续 3+ 章同一基调触发警告
  - 提供默认节奏模板（按题材）:
    - 玄幻: 蓄力→蓄力→小爽→蓄力→大爽→过渡（循环）
    - 都市: 日常→蓄力→小爽→虐心→反转→大爽
    - 悬疑: 蓄力→蓄力→蓄力→反转→大爽→过渡
  - 输出节奏指令传递给 Writer Agent

**决策输出**:
- `scenes`: 场景列表（每个场景包含目标、涉及角色、关键事件）
- `chapter_mood`: 本章情绪基调（str）
- `rhythm_instruction`: 传递给 Writer 的节奏指令（如"本章为蓄力章，节奏放缓，重点铺垫角色内心"）
- `foreshadowing_plan`: 伏笔计划（V2）

**WHY 需要这个 Agent**:
- 场景是生成的基本单位。需要专门 Agent 拆解
- 伏笔规划需要全局视角
- 节奏设计是网文的核心竞争力，连续平淡或连续高潮都会导致读者流失

---

#### Agent-5: Writer（写手）

**职责**:
1. 根据场景描述生成正文（2000-5000 字）
2. 调用风格模板（金庸风/网文风）
3. 埋设悬念钩子
4. 生成对话、动作、心理描写

**Tools**:
- `GenerateSceneTool`: 生成单个场景正文
- `ApplyStyleTool`: 应用风格模板
- `AddCliffhangerTool`: 在章末添加悬念

**输入**:
- 场景大纲
- 角色档案（涉及角色，含 speech_style 和 catchphrases）
- 世界观设定
- 前文摘要（最近 5000 字）
- 风格指令
- **节奏指令**（来自 PlotPlanner 的 rhythm_instruction，如"蓄力章，节奏放缓"）
- **反 AI 味指令**: 显式要求避免黑名单短语，注入个性化细节

**输出**:
- `chapter_text`: 完整章节正文

**WHY 需要这个 Agent**:
- 生成正文是核心任务，需要独立 Agent 专注
- 与其他 Agent 解耦，便于替换模型（如用本地 70B 模型）

---

#### Agent-6: ConsistencyChecker（一致性检查官）

**职责**:
1. 检测时间线矛盾
2. 检测角色状态矛盾
3. 检测设定矛盾
4. 检测专有名词不统一
5. 检测角色关系变化是否有足够铺垫

**Tools**:
- `ExtractFactsTool`: 从新章提取关键事实（时间、地点、角色状态），写入 SQLite
- `QueryStructuredDBTool`: 查询 SQLite 中的角色状态、时间线、力量等级等硬事实
- `QueryRelationshipGraphTool`: 查询 NetworkX 知识图谱中的角色关系、阵营归属
- `VectorSearchTool`: 向量检索相似内容（Chroma，语义层兜底）
- `CompareHistoryTool`: 综合三层检测结果，用 LLM 判断是否构成实质矛盾

**实现机制（三层混合）**:
- **SQLite**: 存储角色状态、时间线、力量等级、专有名词等结构化数据，精确查询
- **NetworkX**: 维护角色关系图、势力阵营图、地点连通图，支持图遍历查询
- **Chroma**: 向量化存储章节关键信息，语义检索隐性矛盾
- 每生成新章，三层同步更新；检索时三层并行查询，汇总后 LLM 裁决

**决策输出**:
- `contradictions`: 矛盾列表（如有），标注来源层（structured/graph/vector）
- `passed`: bool（是否通过检查）
- `confidence`: float（检测置信度，三层一致时高，仅单层命中时低）

**WHY 需要这个 Agent**:
- 一致性是长文的生死线。必须有专门 Agent 把关
- 纯向量检索漏报率高，结构化查询 + 图查询 + 向量检索三层互补更可靠

---

#### Agent-7: StyleKeeper（风格守护者）

**职责**:
1. 确保全文风格统一
2. 检测风格偏离（如突然从网文风变文学风）
3. 调整语句长度、词汇风格

**Tools**:
- `AnalyzeStyleTool`: 分析文本风格特征（平均句长、对话占比、描写比例）
- `CompareStyleTool`: 与参考风格对比
- `RewriteForStyleTool`: 重写偏离的段落

**WHY 需要这个 Agent**:
- 风格一致性是阅读体验的关键
- LLM 容易"人格分裂"，需要主动监控

---

#### Agent-8: QualityReviewer（质量评审官）

**职责**:
1. 运行规则硬指标检查（重复句、对话标签、段落长度、AI 味短语、对话区分度）
2. 对存疑章节执行对比式评估（pairwise comparison）
3. LLM 绝对打分作为粗筛辅助
4. 触发重写机制
5. 生成改进建议

**Tools**:
- `RuleBasedCheckTool`: 规则硬指标检查（零成本，自动执行）
  - 重复句检测、对话标签一致性、段落长度分布、AI 味短语黑名单、对话区分度
- `PairwiseCompareTool`: 对比式评估 — 生成 2 版本，LLM 选优并说明理由
- `EvaluateChapterTool`: LLM 绝对打分（仅作为粗筛）
- `SuggestImprovementTool`: 生成修改建议

**决策输出**:
- `rule_check_result`: 规则检查结果（通过/不通过 + 具体违规项）
- `pairwise_winner`: 对比评估胜出版本（如执行了对比）
- `quality_score`: 综合评分（0-10，仅供参考）
- `ai_flavor_score`: AI 味浓度评分（0-10，越低越好）
- `dialogue_distinction_score`: 对话区分度评分（0-10）
- `need_rewrite`: bool
- `suggestions`: 改进建议

**WHY 需要这个 Agent**:
- 复用视频 Agent 的质量控制经验
- 自动过滤低质量内容
- 三层评估互补: 规则零成本快筛、对比式评估稳定可靠、LLM 打分兜底

---

### 3.3 Agent 间数据流

```
用户输入
   ↓
NovelDirector → 生成大纲
   ↓
并行调用 ────┬─→ WorldBuilder → 世界观
             ├─→ CharacterDesigner → 角色档案
             └─→ PlotPlanner → 场景序列
   ↓
Writer → 生成章节正文
   ↓
并行检查 ────┬─→ ConsistencyChecker → 一致性检查
             ├─→ StyleKeeper → 风格检查
             └─→ QualityReviewer → 质量评分
   ↓
通过 → 保存章节
不通过 → 重写（最多 2 次）
   ↓
继续下一章 或 暂停等待人工介入
```

---

### 3.4 与现有视频 Agent 共存方案

**物理隔离策略**:

1. **独立目录结构**:
```
src/
  agents/           # 现有视频 Agent
  novel_agents/     # 新增小说 Agent（独立目录）
  tools/            # 共享 Tool 层
```

2. **独立 State 定义**:
```python
# src/novel_agents/state.py
class NovelState(TypedDict):
    # 小说专用 State
    outline: dict
    characters: list[CharacterProfile]
    world_setting: dict
    chapters: list[Chapter]
    current_chapter_index: int
    ...
```

3. **独立 Pipeline**:
```python
# src/novel_pipeline.py
class NovelPipeline:
    """小说创作流水线（独立于视频 Pipeline）"""
    def run(self) -> Path:
        # 返回生成的小说文件路径
```

4. **CLI 命令分离**:
```bash
# 现有命令（不变）
python main.py run input.txt --mode agent

# 新增命令
python main.py write-novel --genre 都市 --words 100000 --style 网文

# 混合使用（V3）
python main.py write-novel --genre 武侠 --words 50000 | \
python main.py run - --mode agent  # 管道符传递
```

**数据共享**:
- 小说生成后可作为视频 Pipeline 的输入
- 共享 LLM 配置（`src/llm/`）
- 共享 Logger、Checkpoint 等基础设施

**WHY 选择物理隔离而非共用 Agent**:
- 两个领域的 Agent 职责完全不同（视频 vs 文本）
- 避免 State 膨胀（混在一起会有几十个字段）
- 降低耦合，便于独立迭代

---

## 4. 数据模型设计

> **实现建议**: 以下数据结构在需求文档中使用 TypedDict 描述以便阅读，但实际实现应使用 **Pydantic BaseModel** 替代 TypedDict。优势:
> - 自动验证字段类型和取值范围（如 `intensity: int = Field(ge=1, le=10)`）
> - 内置 JSON 序列化/反序列化（`.model_dump()` / `.model_validate()`）
> - 支持可选字段默认值、嵌套模型、自定义验证器
> - 更好的 IDE 提示和错误信息
> - 与 LLM 返回的 JSON 解析天然配合（`model_validate_json()`）

### 4.1 核心数据结构

#### Novel（小说项目）

```python
class Novel(TypedDict):
    """小说项目根对象"""
    novel_id: str                      # UUID
    title: str                         # 书名
    genre: str                         # 题材（武侠/都市/玄幻...）
    theme: str                         # 主题（如"复仇与救赎"）
    target_words: int                  # 目标字数
    style_category: str                # 风格大类（武侠/网文/文学/轻小说）
    style_subcategory: str             # 风格子类（爽文/种田流/系统流/...）
    custom_style_reference: str | None # 自定义风格参考文本（用户提供）

    # 结构
    outline: Outline                   # 大纲
    volumes: list[Volume]              # 卷列表
    chapters: list[Chapter]            # 章节列表

    # 设定
    world_setting: WorldSetting        # 世界观
    characters: list[CharacterProfile] # 角色

    # 元数据
    created_at: str                    # ISO 时间戳
    updated_at: str
    status: str                        # draft | writing | completed
    current_chapter: int               # 当前进度
```

---

#### Outline（大纲）

```python
class Outline(TypedDict):
    """三层大纲结构"""

    # 结构模板类型
    template: str  # "cyclic_upgrade" | "multi_thread" | "four_act" | "custom"

    # 总大纲（根据模板不同，acts 数量和含义不同）
    acts: list[Act]  # 四幕模板通常 4 个；循环升级模板为多个循环弧；多线交织模板为多条线索

    # 卷大纲
    volumes: list[VolumeOutline]

    # 章大纲
    chapters: list[ChapterOutline]

class Act(TypedDict):
    """幕（最顶层）"""
    name: str                  # "第一幕：平凡世界"
    description: str           # 简述
    target_chapters: range     # 包含的章节范围（如 1-20）

class VolumeOutline(TypedDict):
    """卷大纲"""
    volume_number: int
    title: str                 # "第一卷：崛起"
    core_conflict: str         # 本卷核心矛盾
    resolution: str            # 本卷如何解决
    chapters: list[int]        # 包含的章节号

class ChapterOutline(TypedDict):
    """章大纲"""
    chapter_number: int
    title: str                 # 章节标题
    goal: str                  # 本章目标（如"主角学会第一招武功"）
    key_events: list[str]      # 关键事件列表
    involved_characters: list[str]  # 涉及角色（引用 character_id）
    plot_threads: list[str]    # 推进的主线/支线（引用 thread_id）
    estimated_words: int       # 预计字数
    mood: str                  # 情绪基调: 蓄力/小爽/大爽/过渡/虐心/反转/日常
```

**WHY 三层结构**:
- Act（幕）: 确保整体节奏（起承转合）
- Volume（卷）: 网文标准结构，便于连载和断点
- Chapter（章）: 生成的基本单位

---

#### WorldSetting（世界观）

```python
class WorldSetting(TypedDict):
    """世界观设定"""
    era: str                   # 时代（古代/现代/未来/架空）
    location: str              # 地域背景

    # 力量体系（玄幻/武侠特有）
    power_system: PowerSystem | None

    # 专有名词表
    terms: dict[str, str]      # {"九霄门": "主角所属门派"}

    # 关键设定
    rules: list[str]           # 世界规则（如"灵气复苏"）

class PowerSystem(TypedDict):
    """力量体系"""
    name: str                  # 如"修炼境界"
    levels: list[PowerLevel]   # 等级列表

class PowerLevel(TypedDict):
    """单个力量等级"""
    rank: int                  # 1, 2, 3...
    name: str                  # "筑基期"
    description: str           # 简述
    typical_abilities: list[str]  # 该等级的典型能力
```

**WHY 需要 PowerSystem**:
- 玄幻/武侠的核心。战斗场景必须参考
- 防止战力崩坏（主角打败炼气期高手，下章输给凡人）

---

#### CharacterProfile（角色档案）

```python
class CharacterProfile(TypedDict):
    """角色档案"""
    character_id: str          # UUID
    name: str                  # 姓名
    alias: list[str]           # 别名/外号

    # 基础属性
    gender: str                # 男/女/其他
    age: int
    occupation: str            # 职业
    status: str                # 角色状态: active(活跃) / retired(退场) / deceased(死亡) / absent(暂离)

    # 外貌
    appearance: Appearance

    # 性格
    personality: Personality

    # 关系网
    relationships: list[Relationship]

    # 成长弧线
    character_arc: CharacterArc

    # 引用图片（可选，V2）
    portrait_image: str | None  # 角色立绘路径

class Appearance(TypedDict):
    """外貌特征"""
    height: str                # "175cm"
    build: str                 # 体型（瘦削/魁梧/匀称）
    hair: str                  # 发型颜色
    eyes: str                  # 眼睛
    clothing_style: str        # 服装风格
    distinctive_features: list[str]  # 特征（如"左脸刀疤"）

class Personality(TypedDict):
    """性格"""
    traits: list[str]          # 标签（冷静、腹黑、护短）
    core_belief: str           # 核心信念（如"力量即正义"）
    motivation: str            # 动机（如"复仇"）
    flaw: str                  # 缺陷（如"过度自信"）
    speech_style: str          # 语言风格（如"文绉绉书生腔"、"江湖豪爽"、"冷淡简短"）
    catchphrases: list[str]    # 口头禅/标志性用语（用于对话区分度）

class Relationship(TypedDict):
    """角色关系（带时间维度）"""
    target_character_id: str   # 对方
    current_type: str          # 当前关系类型（见下方扩展列表）
    description: str           # 关系描述
    intensity: int             # 关系强度（1-10）
    history: list[RelationshipEvent]  # 关系变化历史链

# 关系类型扩展（15 种）:
# 敌对 / 友好 / 暧昧 / 师徒 / 亲属 / 竞争 / 利用 /
# 依赖 / 崇拜 / 畏惧 / 合作 / 背叛 / 暗恋 / 仇杀 / 陌生

class RelationshipEvent(TypedDict):
    """关系变化事件"""
    chapter: int               # 发生章节
    from_type: str             # 变化前关系类型
    to_type: str               # 变化后关系类型
    trigger_event: str         # 触发事件（如"主角救了对方"）
    intensity_change: int      # 强度变化（+/- 值）

class CharacterArc(TypedDict):
    """角色成长弧线"""
    initial_state: str         # 初始状态（如"懦弱自卑"）
    turning_points: list[TurningPoint]  # 转折点
    final_state: str           # 最终状态（如"自信坚毅"）

class TurningPoint(TypedDict):
    """角色转折点"""
    chapter: int               # 发生章节
    event: str                 # 事件描述
    change: str                # 变化（如"学会坚持"）
```

**WHY 如此详细的角色设定**:
- 角色是小说的灵魂。设定越详细，生成越一致
- 外貌特征用于生成插图时保持一致（V3）
- 关系网防止逻辑错误（仇人不能无理由和解）
- 成长弧线确保角色不是"纸片人"

---

#### Chapter（章节）

```python
class Chapter(TypedDict):
    """章节"""
    chapter_id: str
    chapter_number: int
    title: str

    # 内容
    scenes: list[Scene]        # 场景列表
    full_text: str             # 完整正文（拼接 scenes）
    word_count: int            # 字数

    # 元数据
    outline: ChapterOutline    # 引用大纲
    generated_at: str          # 生成时间
    quality_score: float       # 质量评分（0-10）

    # 状态
    status: str                # draft | reviewed | finalized
    revision_count: int        # 修改次数

class Scene(TypedDict):
    """场景（章节的组成单元）"""
    scene_id: str
    scene_number: int          # 章内序号（1, 2, 3...）

    # 场景要素
    location: str              # 地点
    time: str                  # 时间（相对时间，如"同日午后"）
    characters: list[str]      # 出场角色 ID
    goal: str                  # 场景目标

    # 内容
    text: str                  # 正文（500-1500 字）
    word_count: int

    # 叙事元素
    narrative_modes: list[str] # 叙事手法（对话/动作/描写/心理）
```

**WHY 分 Scene**:
- 直接生成 5000 字质量不可控
- 场景是叙事基本单位，便于修改和重组
- 可并行生成多个场景（提速）

---

### 4.2 辅助数据结构

#### PlotThread（情节线）

```python
class PlotThread(TypedDict):
    """情节线（主线/支线）"""
    thread_id: str
    name: str                  # "主线：复仇之路"
    type: str                  # main | sub | foreshadowing

    # 时间跨度
    start_chapter: int
    end_chapter: int

    # 节点
    nodes: list[PlotNode]      # 情节节点

    status: str                # active | completed | abandoned

class PlotNode(TypedDict):
    """情节节点"""
    chapter: int
    event: str                 # 事件描述
    impact: str                # 对主线的影响
```

**WHY 需要 PlotThread**:
- 长篇小说通常有 1 条主线 + 3-5 条支线
- 显式管理可避免支线被遗忘或虎头蛇尾

---

#### Foreshadowing（伏笔）

```python
class Foreshadowing(TypedDict):
    """伏笔"""
    foreshadowing_id: str
    planted_chapter: int       # 埋设章节（正向伏笔）或原始出现章节（后置伏笔）
    content: str               # 伏笔内容

    # 回收计划
    target_chapter: int        # 计划回收章节（正向伏笔有值，后置伏笔初始为 -1）
    resolution: str            # 如何回收

    # 伏笔类型
    origin: str                # "planned" = 正向伏笔, "retroactive" = 后置伏笔
    original_detail_id: str | None  # 后置伏笔关联的原始闲笔 ID
    original_context: str | None    # 原文上下文（后置伏笔用，确保回收不矛盾）

    status: str                # pending | collected | abandoned
    collected_chapter: int | None  # 实际回收章节

class DetailEntry(TypedDict):
    """历史闲笔（潜在可利用的细节）"""
    detail_id: str
    chapter: int               # 出现章节
    content: str               # "书架上一本无字旧书"
    context: str               # 原文上下文（前后 2 句）
    category: str              # 道具/环境/角色动作/异常现象/对话暗示
    status: str                # available | promoted | used
    promoted_foreshadowing_id: str | None  # 升级后关联的伏笔 ID
```

**WHY V2 才加入伏笔**:
- MVP 先保证基本功能
- 伏笔管理（尤其是后置伏笔）需要全局理解能力，对 LLM 要求高
- 后置伏笔需要向量检索成熟后才能实现

---

#### ContextMemory（上下文记忆）

```python
class ContextMemory(TypedDict):
    """上下文记忆（三层混合存储，用于一致性检查）"""

    # 第一层: 结构化数据库（SQLite）
    structured_db_path: str    # SQLite 数据库路径
    # 表: character_states(character_id, chapter, health, location, power_level, emotional_state)
    # 表: timeline(chapter, scene, absolute_time, relative_time)
    # 表: terms(term, definition, first_chapter)
    # 表: power_tracking(character_id, chapter, level, change_reason)

    # 第二层: 知识图谱（NetworkX）
    relationship_graph_path: str  # 序列化的关系图路径
    # 节点: 角色、势力、地点
    # 边: 关系类型+强度+变化历史

    # 第三层: 向量检索（Chroma）
    vector_index_path: str     # Chroma 向量索引路径

    # 关键事实库（三层共享）
    facts: list[Fact]

    # 最近章节摘要
    recent_summaries: list[ChapterSummary]  # 保留最近 5 章

class Fact(TypedDict):
    """关键事实"""
    fact_id: str
    chapter: int               # 来源章节
    type: str                  # 类型（time/character_state/location/setting/relationship）
    content: str               # 事实内容
    storage_layer: str         # 存储层: "structured" | "graph" | "vector"
    embedding: list[float] | None  # 向量（仅 vector 层有值）

class ChapterSummary(TypedDict):
    """章节摘要"""
    chapter: int
    summary: str               # 300-500 字摘要
    key_events: list[str]      # 关键事件列表
```

**WHY 三层混合存储**:
- LLM 上下文窗口有限。10 万字小说无法全部塞入 prompt
- **结构化数据库**: 角色状态、时间线等硬事实需要精确查询（"第 10 章主角在哪"），向量检索不可靠
- **知识图谱**: 关系查询天然适合图结构（"主角的敌人有哪些"），SQL 查询笨拙
- **向量检索**: 语义层面的隐性矛盾（"描写风格突然变化"）只能靠语义匹配兜底
- 三层互补，综合漏报率远低于单一方案

---

## 5. 记忆与上下文管理方案

### 5.0 百万字级长篇的核心架构

**现实**: 网络小说动辄百万字甚至更多（200-500 万字），远超任何 LLM 的上下文窗口。关键是如何在极长的创作过程中保持前后串联、不脱节。

#### 5.0.1 分层记忆架构（类比操作系统内存管理）

```
┌─────────────────────────────────────────────────────┐
│ 全局层 (Global Context) — 始终在内存中               │
│  • 主线进度（当前到哪一步了）                         │
│  • 角色终极目标 & 核心关系                           │
│  • 力量体系 / 世界观基本规则                         │
│  • 未回收伏笔清单（关键！防烂尾）                    │
│  • 专有名词表                                       │
│  ~1500 tokens，永不淘汰                              │
├─────────────────────────────────────────────────────┤
│ 卷层 (Volume Context) — 每卷加载                     │
│  • 本卷大纲（反派、矛盾、高潮点）                    │
│  • 本卷新增角色                                      │
│  • 上卷结尾快照（过渡衔接）                          │
│  • 本卷内已发生事件摘要                              │
│  ~3000 tokens，换卷时切换                             │
├─────────────────────────────────────────────────────┤
│ 章层 (Chapter Context) — 每章加载                    │
│  • 最近 3 章完整正文                                  │
│  • 最近 10 章摘要                                    │
│  • 向量检索相关历史片段                              │
│  • 当前章大纲 + 场景描述                             │
│  ~8000 tokens，滚动更新                               │
└─────────────────────────────────────────────────────┘
总计 ~12500 tokens，远低于 128K 上限
```

#### 5.0.2 卷快照机制（Volume Snapshot）

每一卷是一个相对独立的故事弧（有自己的反派、冲突、高潮），卷与卷之间通过**卷快照**衔接：

```python
class VolumeSnapshot(TypedDict):
    """卷间过渡快照 — 百万字串联的关键"""
    volume_number: int

    # 主线进度
    main_plot_progress: str        # "主角已突破金丹，正在南疆寻找师父下落"
    main_plot_completion: float    # 0.3 = 主线完成 30%

    # 角色状态快照（只保留活跃角色）
    character_states: list[CharacterSnapshot]

    # 伏笔管理
    unresolved_foreshadowing: list[Foreshadowing]  # 未回收的伏笔
    resolved_this_volume: list[str]                 # 本卷回收的伏笔

    # 上卷结尾
    ending_summary: str            # 上卷最后 3 章的摘要（~500字）
    cliffhanger: str               # 悬念（如"门外传来一个不该出现的声音"）

    # 世界观增量
    new_terms: dict[str, str]      # 本卷新增的专有名词
    power_changes: list[str]       # 力量体系的新增/变化

class CharacterSnapshot(TypedDict):
    """角色状态快照"""
    character_id: str
    name: str
    current_power_level: str       # "金丹中期"
    location: str                  # "南疆荒漠"
    health: str                    # "轻伤，左臂未愈"
    emotional_state: str           # "决心复仇"
    key_relationships_changed: list[str]  # 本卷关系变化
```

#### 5.0.3 为什么这样能防止脱节

| 脱节类型 | 原因 | 解法 |
|----------|------|------|
| 角色行为突变 | 第 300 章忘了第 50 章的性格设定 | 全局层始终携带角色核心性格 |
| 伏笔烂尾 | 埋了坑忘了填 | `unresolved_foreshadowing` 清单强制追踪 |
| 力量崩坏 | 战力忽高忽低 | 力量体系在全局层 + 角色快照记录当前等级 |
| 关系混乱 | 仇人无理由和好 | 卷快照记录关系变化，新卷开始时加载 |
| 主线迷失 | 写着写着忘了主线是什么 | `main_plot_progress` + `completion%` 始终可见 |
| 前后矛盾 | 地名/人名前后不一 | 专有名词表在全局层，向量检索兜底 |

#### 5.0.4 百万字成本估算

```
200 万字 ≈ 400 章 ≈ 40 卷

每章成本 ≈ $0.0068（GPT-4o-mini，含正文+事实提取+摘要+质量评估+去AI味）
400 章 = $2.72（乐观）~ $4.80（悲观，含重写+对比评估）
+ 卷间快照生成 40 × $0.01 = $0.40
+ 一致性检查 400 × 免费（SQLite/NetworkX 本地 + Gemini LLM 裁决）

总计 ≈ $3.1（乐观）~ $5.2（悲观）
详细分项见 §8.4 成本估算
```

#### 5.0.5 类比：网文作者的真实创作方式

这个架构模拟了职业网文作者的实际做法：
- **全局层** = 作者脑中的"大设定"（随时能想起来的）
- **卷快照** = 作者在每卷结束时写的"卷末总结"
- **章层** = 作者翻看最近几章找灵感
- **向量检索** = 作者翻回前文查"这个角色上次出现是什么时候"

没有人写到第 500 章还记得第 3 章每句话，但好的作者知道"主线走到哪了"和"哪些坑还没填"——我们的系统做的就是这个。

---

### 5.1 核心挑战（中篇/长篇通用）

**问题**: 即使是 128K 上下文的模型（如 GPT-4 Turbo），也无法完整记住 10 万字（约 25K tokens）小说的所有细节。

**后果**:
- 前文的角色设定、情节被遗忘
- 出现矛盾（时间线错乱、角色状态错乱）
- 专有名词不统一

### 5.2 方案对比

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **全文塞入 Prompt** | 简单，100% 信息保留 | 超长上下文成本高（$0.01/1K tokens），慢 | < 2 万字短篇 |
| **滑动窗口** | 成本可控，最近内容完整 | 遗忘早期内容，适合流水账 | 日记、对话生成 |
| **层次化摘要** | 压缩比高，保留关键信息 | 细节丢失，摘要质量依赖 LLM | 中篇（3-10 万字） |
| **向量检索 RAG** | 可精准找回相关内容 | 检索质量依赖 embedding，可能漏检 | 长篇（>10 万字） |
| **混合方案** | 结合各方法优点 | 实现复杂 | **推荐用于本项目** |

### 5.3 推荐方案：混合记忆架构

```
生成第 N 章时的上下文组成：

1. 固定上下文（始终在 Prompt 中）
   ├─ 世界观设定（500 tokens）
   ├─ 主要角色档案（1000 tokens）
   └─ 总大纲（800 tokens）

2. 动态上下文（根据相关性选择）
   ├─ 最近 3 章完整正文（6000 tokens）
   ├─ 最近 10 章摘要（2000 tokens）
   └─ 向量检索到的相关历史片段（2000 tokens）

3. 当前任务上下文
   ├─ 当前章大纲（300 tokens）
   ├─ 当前场景描述（200 tokens）
   └─ 风格指令（200 tokens）

总计：~13000 tokens（远低于 128K 上限）
```

**实现细节**:

#### 步骤 1: 初始化时建立知识库

```python
# 使用 Chroma 向量数据库
from chromadb import Client

class NovelMemory:
    def __init__(self, novel_id: str):
        self.db = Client()
        self.collection = self.db.create_collection(
            name=f"novel_{novel_id}",
            metadata={"hnsw:space": "cosine"}
        )

    def add_chapter(self, chapter: Chapter):
        """章节生成后，提取关键事实并向量化"""
        facts = self._extract_facts(chapter)

        for fact in facts:
            self.collection.add(
                documents=[fact.content],
                metadatas=[{"chapter": fact.chapter, "type": fact.type}],
                ids=[fact.fact_id]
            )

    def _extract_facts(self, chapter: Chapter) -> list[Fact]:
        """调用 LLM 从章节提取关键事实"""
        prompt = f"""从以下章节中提取关键事实（时间、地点、角色状态变化、重要事件）

章节内容：
{chapter.full_text}

输出 JSON 数组，每条事实包含：
{{"type": "time/character_state/location/event", "content": "事实描述"}}
"""
        result = llm.invoke(prompt)
        # 解析 JSON 并生成 Fact 对象
        ...
```

#### 步骤 2: 生成新章时检索相关内容

```python
def get_context_for_chapter(self, chapter_num: int) -> str:
    """构建第 N 章的上下文"""

    # 1. 固定上下文
    fixed = f"""
世界观：{self.world_setting}
角色：{self.characters}
大纲：{self.outline}
"""

    # 2. 最近 3 章完整正文
    recent_chapters = self.chapters[max(0, chapter_num-3):chapter_num]
    recent_text = "\n\n".join(c.full_text for c in recent_chapters)

    # 3. 最近 10 章摘要
    recent_summaries = self.summaries[max(0, chapter_num-10):chapter_num]
    summary_text = "\n".join(s.summary for s in recent_summaries)

    # 4. 向量检索相关历史
    current_outline = self.outline.chapters[chapter_num]
    query = f"{current_outline.goal} {' '.join(current_outline.key_events)}"

    results = self.memory.collection.query(
        query_texts=[query],
        n_results=5  # 取最相关的 5 条事实
    )
    relevant_facts = "\n".join(results['documents'][0])

    # 组合
    return f"""
{fixed}

【最近章节摘要】
{summary_text}

【最近 3 章正文】
{recent_text}

【相关历史内容】
{relevant_facts}
"""
```

#### 步骤 3: 生成后更新记忆

```python
def after_chapter_generated(chapter: Chapter):
    """章节生成后的处理"""

    # 1. 提取事实并向量化
    memory.add_chapter(chapter)

    # 2. 生成摘要
    summary = generate_summary(chapter)
    summaries.append(summary)

    # 3. 如果章节数 > 20，删除最旧的完整正文（仅保留摘要）
    if len(chapters) > 20:
        chapters[0].full_text = None  # 释放内存
```

**WHY 选择混合方案**:
- **固定上下文**: 世界观和角色是不变的"宪法"，必须始终可见
- **最近正文**: 保证叙事连贯，避免断层感
- **摘要**: 压缩早期章节，节省 tokens
- **向量检索**: 按需召回相关内容（如第 50 章提到第 3 章埋的伏笔，向量检索可找回）

---

### 5.4 上下文窗口优化技巧

#### 技巧 1: 角色档案懒加载

```python
# 不要把所有角色都塞入 Prompt，只加载本章涉及的角色
relevant_characters = [
    char for char in characters
    if char.character_id in current_chapter.outline.involved_characters
]
```

#### 技巧 2: 分层摘要

```python
# 对于超长小说（>50 万字），采用两层摘要
# 第一层：每章摘要（500 字 → 100 字）
# 第二层：每卷摘要（每 10 章 → 300 字）

def get_hierarchical_summary(chapter_num: int):
    # 当前卷的详细摘要
    current_volume_summary = ...

    # 之前各卷的简要摘要
    previous_volumes_summary = ...

    return f"{previous_volumes_summary}\n\n{current_volume_summary}"
```

#### 技巧 3: 关键情节强化记忆

```python
# 某些关键章节（转折点、高潮）需要更频繁被召回
# 给这些章节的事实加权

fact = Fact(
    content="主角突破至金丹期",
    weight=2.0  # 权重加倍，检索时优先召回
)
```

---

## 6. 风格控制方案

### 6.1 风格的定义

**风格 = 词汇 + 句式 + 节奏 + 叙事视角**

**二级风格体系**: 大类（4 种）× 子类（8-10 种预设）+ 自定义风格

| 维度 | 武侠风 | 网文风 | 文学风 | 轻小说风 |
|------|--------|--------|--------|----------|
| **词汇** | 文言韵味（"须臾"、"倏忽"） | 现代白话（"瞬间"、"马上"） | 书面语 + 隐喻 | 日系口语化、吐槽 |
| **句式** | 长短结合，多排比 | 短句为主（< 20 字） | 长句，复杂从句 | 短句+大量对话 |
| **节奏** | 慢，大量环境描写 | 快，对话推进情节 | 极慢，意识流 | 中等，轻松明快 |
| **视角** | 全知全能第三人称 | 主角第一人称/有限第三人称 | 多视角，时空跳跃 | 第一人称为主 |
| **示例** | "他缓缓抬手，内力运至掌心，一股浩然之气油然而生" | "他一掌拍出，轰！对手倒飞十米！" | "他的手颤抖着，不知是因为寒冷还是恐惧，或许两者皆是" | "等一下，这展开也太离谱了吧？我明明只是去买个便当而已啊！" |

**子类示例**（同为网文风大类，子类差异显著）:
| 子类 | 关键特征 | 节奏 |
|------|---------|------|
| 网文-爽文 | 极致打脸、装逼、碾压 | 极快，每章有爽点 |
| 网文-种田流 | 经营发展、细节丰富 | 舒缓，日常感 |
| 网文-系统流 | 系统面板、任务、奖励 | 游戏化节奏 |
| 网文-黑暗流 | 压抑、残酷、反套路 | 缓慢积累 + 爆发 |

### 6.2 实现方法

#### 方法 1: System Prompt 注入

```python
STYLE_PROMPTS = {
    "金庸风": """
你是金庸武侠小说的专业作者。请遵循以下风格：
1. 使用文言韵味词汇（如"须臾"、"顷刻"、"黯然"）
2. 句式长短结合，多用排比和对偶
3. 大量环境描写，营造意境
4. 武功描写注重招式名称和内力运行
5. 人物对话简洁有力，点到即止
6. 节奏舒缓，张弛有度

示例：
"他缓缓抬手，内力运至掌心，一股浩然之气油然而生。掌风过处，竹叶纷飞，却无一片触及身旁的少女。这一掌看似平淡无奇，实则暗含玄机，正是当年恩师传授的'太极绵掌'第三式。"
""",

    "网文风": """
你是网络爽文作者。请遵循以下风格：
1. 短句为主（每句 < 20 字），节奏极快
2. 多用动作和对话推进情节，少环境描写
3. 频繁使用感叹号和省略号
4. 强调"爽点"：打脸、装逼、收美女、获宝物
5. 主角必须强大且果断
6. 每章必须有钩子（悬念）

示例：
"一掌！\n\n轰！\n\n对手倒飞十米，狂吐鲜血！\n\n众人惊呆了。\n\n'这...这怎么可能？他竟然是...传说中的金丹期高手？！'\n\n林凡冷笑一声：'垃圾。'"
""",

    "文学风": """
你是严肃文学作者。请遵循以下风格：
1. 词汇书面化，多用意象和隐喻
2. 长句，复杂从句，注重节奏美
3. 大量心理描写，意识流
4. 环境与情绪融合（借景抒情）
5. 避免直白，留白让读者思考
6. 慢节奏，关注人性和哲思

示例：
"他的手微微颤抖——不知是因为寒冷，还是那无以名状的恐惧，抑或两者皆是。窗外的雨声愈发急促，仿佛天地也在为即将发生之事而焦躁不安。他想起了多年前的那个午后，同样的雨，同样的沉默，只是彼时的她还未离开。"
""",

    "轻小说风": """
你是日系轻小说作者。请遵循以下风格：
1. 大量对话驱动情节，对话占比 > 50%
2. 第一人称为主，主角内心吐槽频繁
3. 轻松幽默的基调，即使严肃场景也保留吐槽
4. 角色称呼日系化（"那家伙"、"前辈"、"学姐"）
5. 夸张的情绪反应和动作描写
6. 短句为主，节奏明快

示例：
"等一下，这展开也太离谱了吧？我明明只是去买个便当而已啊！\n\n'你就是被选中的勇者。'银发少女一脸认真地说。\n\n不不不，我只是个普通高中生！而且你能不能先从我的课桌上下来？全班都在看了！"
"""
}

def generate_with_style(scene: Scene, style: str) -> str:
    system_prompt = STYLE_PROMPTS[style]
    user_prompt = f"根据以下场景大纲生成正文：\n{scene.goal}\n{scene.key_events}"

    result = llm.invoke(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )
    return result.content
```

**优点**: 简单，无需额外训练
**缺点**: LLM 不一定严格遵守（尤其是小模型）

---

#### 方法 2: Few-Shot 示例

```python
def generate_with_few_shot(scene: Scene, style: str) -> str:
    # 准备 2-3 段该风格的示例
    examples = STYLE_EXAMPLES[style]  # 预先准备的范文

    prompt = f"""
参考以下风格示例，生成新的场景：

【示例 1】
{examples[0]}

【示例 2】
{examples[1]}

【待生成场景】
{scene.goal}

请严格模仿上述示例的风格（词汇、句式、节奏）生成 800-1000 字正文。
"""
    result = llm.invoke(prompt)
    return result.content
```

**优点**: 比 System Prompt 更可控
**缺点**: 需要准备高质量示例（可人工撰写或从经典小说提取）

---

#### 方法 3: 风格特征约束

```python
STYLE_CONSTRAINTS = {
    "网文风": {
        "avg_sentence_length": (10, 20),  # 平均句长 10-20 字
        "dialogue_ratio": (0.4, 0.6),     # 对话占比 40-60%
        "exclamation_ratio": (0.1, 0.2),  # 感叹号占比 10-20%
        "paragraph_length": (50, 150),    # 段落长度 50-150 字
    },
    "武侠风": {
        "avg_sentence_length": (20, 40),
        "dialogue_ratio": (0.2, 0.3),
        "classical_word_ratio": (0.15, 0.25),  # 文言词汇占比
        "description_ratio": (0.4, 0.5),       # 描写占比
    },
    "轻小说风": {
        "avg_sentence_length": (8, 18),
        "dialogue_ratio": (0.5, 0.7),          # 对话占比极高
        "first_person_ratio": (0.8, 1.0),      # 第一人称为主
        "exclamation_ratio": (0.15, 0.25),     # 感叹号多
    }
}

def validate_style(text: str, style: str) -> bool:
    """检查生成的文本是否符合风格约束"""
    constraints = STYLE_CONSTRAINTS[style]

    # 计算实际指标
    sentences = split_sentences(text)
    avg_len = sum(len(s) for s in sentences) / len(sentences)

    dialogue_ratio = count_dialogue(text) / len(text)
    # ...

    # 检查是否在范围内
    if not (constraints["avg_sentence_length"][0] <= avg_len <= constraints["avg_sentence_length"][1]):
        return False
    # ...

    return True

# 使用
text = generate_scene(scene, style="网文风")
if not validate_style(text, "网文风"):
    # 重新生成或调用 StyleKeeper Agent 重写
    text = rewrite_for_style(text, "网文风")
```

**优点**: 可量化检验，客观
**缺点**: 某些风格特征难以量化（如"意境"）

---

#### 方法 4: 风格迁移模型（V3 高级）

```python
# 使用专门的风格迁移模型（如 ControlNet for Text）
# 先生成"无风格"内容，再迁移为目标风格

def generate_with_style_transfer(scene: Scene, style: str) -> str:
    # 1. 生成中性内容
    neutral_text = llm.invoke(f"客观叙述以下场景：{scene.goal}")

    # 2. 风格迁移
    styled_text = style_transfer_model.transfer(neutral_text, target_style=style)

    return styled_text
```

**优点**: 风格控制最精准
**缺点**: 需要训练/微调模型，成本高

---

### 6.3 推荐方案

**MVP**: 方法 1（System Prompt）+ 方法 3（风格约束）— 覆盖 4 大类 + 8-10 子类预设
**V2**: 增加方法 2（Few-Shot）+ 自定义风格（用户贴参考文本，自动提取风格特征）
**V3**: 探索方法 4（风格迁移）

---

## 7. 质量保障

### 7.1 一致性检查

#### 检查维度 1: 时间线一致性

```python
def check_timeline_consistency(new_chapter: Chapter) -> list[str]:
    """检查时间线矛盾"""

    # 提取新章的时间信息
    new_timeline = extract_timeline(new_chapter)  # 如"三天后"、"春天"

    # 与历史时间线对比
    contradictions = []
    for past_chapter in chapters:
        past_timeline = extract_timeline(past_chapter)

        if is_contradictory(new_timeline, past_timeline):
            contradictions.append(
                f"矛盾：第{new_chapter.number}章时间为{new_timeline}，"
                f"但第{past_chapter.number}章时间为{past_timeline}"
            )

    return contradictions
```

#### 检查维度 2: 角色状态一致性

```python
def check_character_state(new_chapter: Chapter) -> list[str]:
    """检查角色状态矛盾"""

    contradictions = []

    for char_id in new_chapter.outline.involved_characters:
        # 查询角色在上一章的状态
        last_state = get_character_last_state(char_id)

        # 提取本章的角色状态
        current_state = extract_character_state(new_chapter, char_id)

        # 检查是否有不合理变化
        if last_state.health == "重伤" and current_state.health == "完好":
            if not has_healing_event(new_chapter):
                contradictions.append(
                    f"{char_id} 上章重伤，本章突然痊愈但无治疗情节"
                )

        if last_state.location != current_state.location:
            if not has_travel_event(new_chapter):
                contradictions.append(
                    f"{char_id} 从{last_state.location}到{current_state.location}，但无移动描写"
                )

    return contradictions
```

#### 检查维度 3: 设定一致性

```python
def check_world_setting_consistency(new_chapter: Chapter) -> list[str]:
    """检查违反世界观设定"""

    contradictions = []

    # 检查力量体系
    if world_setting.power_system:
        for battle in extract_battles(new_chapter):
            if violates_power_system(battle, world_setting.power_system):
                contradictions.append(
                    f"战斗描写违反力量体系：{battle.description}"
                )

    # 检查专有名词
    terms_in_chapter = extract_terms(new_chapter)
    for term, usage in terms_in_chapter.items():
        if term in world_setting.terms:
            official = world_setting.terms[term]
            if usage != official:
                contradictions.append(
                    f"专有名词不一致：'{term}' 应为 '{official}'，实际为 '{usage}'"
                )

    return contradictions
```

---

### 7.2 去 AI 味机制

**问题**: LLM 生成的文本存在明显的"AI 味"——过度使用特定短语、描写模式化、缺乏个性化细节，导致读者一眼辨认出 AI 生成。

**四层去 AI 味策略**:

#### 策略 1: AI 常用短语黑名单（规则层）

维护 50+ 条 AI 常见套话黑名单（持续更新）:
- 情绪类: "内心翻涌"、"莫名的力量"、"不由得"、"心中涌起一股"
- 转折类: "竟然"（过度使用）、"没想到"、"居然"
- 描写类: "宛如"、"恍若"、"仿佛置身于"
- 结尾类: "嘴角微微上扬"、"眼中闪过一丝"

生成后自动扫描，命中 3 处以上触发重写。

#### 策略 2: Writer Prompt 反 AI 味指令（生成层）

在 Writer Agent 的 System Prompt 中显式添加:
- 禁止使用黑名单短语
- 要求使用具体细节替代抽象描写（"他攥紧了左手的铜币" vs "他内心翻涌"）
- 要求对话符合角色 speech_style，避免所有角色说同样的话

#### 策略 3: 个性化细节注入（后处理层）

生成后增加一次"细节注入" pass:
- LLM 审查文本，将模式化描写替换为具体、独特的细节
- 注入感官细节（气味、温度、质感）替代抽象情绪描写
- 为不同角色的对话添加语言特征（口头禅、语气词、句式习惯）

#### 策略 4: QualityReviewer AI 味评分（评估层）

- 新增"AI 味浓度"评分维度（0-10，越低越好）
- 评估标准: 黑名单命中数、描写独特性、对话区分度
- AI 味浓度 > 6 分触发重写

---

### 7.3 文笔评估

**评估流程（三层递进）**:

```python
def evaluate_writing_quality(chapter: Chapter) -> dict:
    """文笔质量评估 — 三层递进"""

    result = {}

    # === 第一层: 规则硬指标（零成本，自动执行） ===
    rule_check = run_rule_based_checks(chapter)
    # - 重复句检测（连续 3 句相似度 > 80%）
    # - 对话标签一致性（说话人标记前后匹配）
    # - 段落长度分布（异常段落检测）
    # - AI 味短语黑名单命中数
    # - 对话区分度（不同角色对话相似度）
    result["rule_check"] = rule_check

    if not rule_check["passed"]:
        result["need_rewrite"] = True
        result["rewrite_reason"] = rule_check["violations"]
        return result  # 硬指标不过，直接重写

    # === 第二层: 对比式评估（存疑时执行） ===
    if rule_check["borderline"]:  # 边界情况
        # 生成同一场景的第二个版本
        version_b = regenerate_scene(chapter)
        comparison = pairwise_compare(chapter.full_text, version_b)
        # LLM 选优并说明理由
        result["pairwise_result"] = comparison
        if comparison["winner"] == "B":
            result["better_version"] = version_b

    # === 第三层: LLM 绝对打分（仅作粗筛辅助） ===
    llm_scores = llm_evaluate(chapter)
    # 维度: 流畅度、生动性、对话自然度、节奏、用词、AI味浓度
    result["llm_scores"] = llm_scores

    # 综合判断
    result["need_rewrite"] = (
        llm_scores["overall_score"] < 4  # 极低分才触发
        or llm_scores["ai_flavor_score"] > 6  # AI 味过重
    )

    return result
```

**注意**: LLM 绝对打分仅作为粗筛辅助（< 4 分触发），不作为最终质量判断。对比式评估的结论优先级更高。

---

### 7.4 人工介入点

#### 介入点 1: 大纲审核

```
用户输入需求 → NovelDirector 生成大纲 → 【暂停，展示大纲】
                                           ↓
                                   用户确认/修改 → 继续
```

#### 介入点 2: 定期审核（间隔可配置，默认每 5 章）

```
生成第 N/2N/3N... 章 → 【暂停，展示摘要和质量报告】
（N = review_interval，默认 5）    ↓
                        用户选择：继续/修改大纲/重写某章
                        （静默模式下：质量达标则自动继续）
```

#### 介入点 3: 质量不达标

```
QualityReviewer 评分 < 6 → 自动重写 1 次
                          ↓
                   仍 < 6 → 【暂停，提示用户人工修改】
```

---

### 7.5 质量基准

**验收标准**（人工评审抽样）:

| 指标 | 目标 |
|------|------|
| 时间线一致性 | 无明显矛盾（允许 < 5% 微小瑕疵） |
| 角色 OOC 率 | < 10%（即 10 次角色出场，不超过 1 次 OOC） |
| 专有名词一致性 | 100%（强约束） |
| 文笔流畅度（人工打分） | >= 7/10 |
| 情节合理性（人工打分） | >= 7/10 |
| AI 味浓度 | 黑名单命中 < 2 处/章，人工盲评"像人写的"比例 >= 60% |
| 对话区分度 | 遮盖角色名后，人工能正确归属 >= 70% 的对话 |
| 一致性检查漏报率 | < 15%（植入 20 个矛盾至少检出 17 个） |
| 关系变化合理性 | 角色关系每次变化都有至少 1 章铺垫 |

---

## 8. 技术实现要点

### 8.1 LLM 选型考量

#### 长上下文需求

| 模型 | 上下文窗口 | 成本（$/1M tokens） | 推荐场景 |
|------|-----------|---------------------|----------|
| GPT-4 Turbo | 128K | input: $10, output: $30 | V2/V3 高质量生成 |
| GPT-4o-mini | 128K | input: $0.15, output: $0.60 | **MVP 推荐** |
| Claude 3 Opus | 200K | input: $15, output: $75 | 最长上下文，成本高 |
| Gemini 1.5 Pro | 1M | 免费（有限额） | **预算有限首选** |
| DeepSeek Chat | 64K | input: $0.14, output: $0.28 | 省钱模式 |
| Qwen2.5:72B (本地) | 128K | 免费（需显卡） | 隐私敏感用户 |

**推荐配置**:
- **MVP**: Gemini 1.5 Pro（免费额度）+ GPT-4o-mini（质量评估）
- **生产环境**: GPT-4o-mini（主力）+ Claude 3 Opus（超长上下文场景）
- **省钱模式**: DeepSeek Chat + 本地 Qwen2.5

---

#### 模型分工

```python
MODEL_ROLES = {
    "outline_generation": "gpt-4o-mini",      # 大纲生成
    "character_design": "claude-3-haiku",     # 角色设计（Claude 擅长人物）
    "scene_writing": "gpt-4o-mini",           # 正文生成
    "quality_review": "gpt-4o",               # 质量评估（用最强模型）
    "consistency_check": "gemini-1.5-pro",    # 一致性检查（长上下文）
    "style_rewrite": "deepseek-chat",         # 风格重写（省钱）
}
```

---

### 8.2 生成策略

#### 策略 1: 逐场景生成（推荐）

```python
def generate_chapter(chapter_outline: ChapterOutline) -> Chapter:
    """逐场景生成章节"""

    # 1. PlotPlanner 将章大纲拆解为 3-5 个场景
    scenes = plot_planner.decompose_chapter(chapter_outline)

    # 2. 逐场景生成
    scene_texts = []
    for scene in scenes:
        context = build_context_for_scene(scene)  # 包含世界观、角色、前文摘要
        text = writer.generate_scene(scene, context)
        scene_texts.append(text)

    # 3. 拼接 + 润色
    full_text = "\n\n".join(scene_texts)
    polished = polish_transitions(full_text)  # 平滑场景过渡

    return Chapter(
        chapter_number=chapter_outline.chapter_number,
        title=chapter_outline.title,
        scenes=[Scene(text=t) for t in scene_texts],
        full_text=polished
    )
```

**WHY 逐场景**:
- 单次生成 5000 字质量不可控
- 场景是叙事基本单位，便于修改
- 可并行生成多个场景（提速）

---

#### 策略 2: 逐章生成（备选）

```python
def generate_chapter_directly(chapter_outline: ChapterOutline) -> Chapter:
    """一次性生成整章"""

    context = build_full_context(chapter_outline)

    full_text = llm.invoke(f"""
{context}

请根据以下大纲生成 3000-5000 字的完整章节：
{chapter_outline.goal}
{chapter_outline.key_events}
""")

    return Chapter(full_text=full_text)
```

**优点**: 章节整体连贯性更好
**缺点**: 生成时间长（2-5 分钟），出错率高

---

### 8.3 断点续写

```python
class NovelPipeline:
    """小说创作流水线"""

    def __init__(self, novel_id: str, resume: bool = False):
        self.checkpoint_file = f"workspace/{novel_id}/checkpoint.json"

        if resume and Path(self.checkpoint_file).exists():
            self.state = self.load_checkpoint()
        else:
            self.state = self.init_state()

    def run(self):
        """执行创作流程"""

        while self.state.current_chapter < self.state.total_chapters:
            chapter_num = self.state.current_chapter

            # 生成章节
            chapter = self.generate_chapter(chapter_num)

            # 一致性检查
            if not self.check_consistency(chapter):
                # 提示用户修改
                self.pause_for_review(chapter)
                continue

            # 保存章节
            self.save_chapter(chapter)

            # 更新进度
            self.state.current_chapter += 1
            self.save_checkpoint()

            # 按配置间隔暂停让用户审核（默认每 5 章）
            if chapter_num % self.state.review_interval == 0 and not self.state.silent_mode:
                self.pause_for_review()

        return self.finalize()
```

---

### 8.4 成本估算

**假设**: 10 万字都市小说，20 章，每章 5000 字

#### 每章 LLM 调用明细

| 调用类型 | Input Tokens | Output Tokens | 模型 | 单次成本 |
|----------|-------------|--------------|------|---------|
| 正文生成（3-5 场景） | 15K | 2K | GPT-4o-mini | $0.0035 |
| 事实提取 | 3K | 0.5K | GPT-4o-mini | $0.0008 |
| 章节摘要 | 3K | 0.3K | GPT-4o-mini | $0.0006 |
| 一致性检查（SQLite+Graph查询免费，LLM裁决） | 8K | 0.5K | Gemini 1.5 Pro | 免费 |
| 质量评估（规则检查免费，LLM打分） | 3K | 0.5K | GPT-4o-mini | $0.0008 |
| 去AI味后处理 | 3K | 1K | GPT-4o-mini | $0.0011 |
| **每章小计** | | | | **$0.0068** |

#### 三档估算（10 万字 / 20 章）

| 阶段 | 乐观（0%重写） | 中性（20%重写1次） | 悲观（40%重写+对比评估） |
|------|---------------|-------------------|------------------------|
| 初始化（大纲+角色+世界观） | $0.01 | $0.01 | $0.01 |
| 章节生成 × 20 | $0.070 | $0.070 | $0.070 |
| 事实提取+摘要 × 20 | $0.028 | $0.028 | $0.028 |
| 一致性检查 × 20 | 免费 | 免费 | 免费 |
| 质量评估 × 20 | $0.016 | $0.016 | $0.016 |
| 去AI味后处理 × 20 | $0.022 | $0.022 | $0.022 |
| 重写（正文+后处理） | $0 | 4章 × $0.0046 = $0.018 | 8章 × $0.0046 = $0.037 |
| 对比式评估 | $0 | $0 | 8章 × $0.007 = $0.056 |
| **总计** | **~$0.15** | **~$0.16** | **~$0.24** |

#### 百万字成本（200 万字 ≈ 400 章 ≈ 40 卷）

| 场景 | 乐观 | 中性 | 悲观 |
|------|------|------|------|
| 章节生成+检查+评估 | $2.72 | $3.28 | $4.80 |
| 卷间快照 × 40 | $0.40 | $0.40 | $0.40 |
| **总计** | **~$3.1** | **~$3.7** | **~$5.2** |

**结论**: 即使悲观估算，10 万字成本 < $0.25，百万字 < $6。主要瓶颈是时间（生成 10 万字约 1-2 小时）

---

## 9. 风险与挑战

### 9.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| **LLM 生成质量不稳定** | 高 | 高 | 质量自检 + 多次重试 + 人工介入 |
| **长文一致性失控** | 中 | 高 | 三层混合检测（SQLite+NetworkX+Chroma）+ 显式检查 + 可配置审核间隔 |
| **角色 OOC 严重** | 中 | 中 | 强化角色档案 + 生成时强制引用 |
| **生成速度慢（10 万字需 2 小时）** | 低 | 中 | 并行生成场景 + 使用快速模型 |
| **成本超预期** | 低 | 低 | 已验证成本极低（$0.1/10 万字） |

---

### 9.2 产品风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| **用户不信任 AI 生成内容** | 中 | 高 | 强调"AI 辅助"而非"AI 代笔"，Human-in-the-Loop |
| **生成内容同质化** | 高 | 中 | 多样化风格预设 + 用户可自定义参考文本 |
| **法律问题（版权、伦理）** | 低 | 高 | 明确用户协议：生成内容归用户所有，用户承担法律责任 |
| **与传统作者竞争关系** | 中 | 中 | 定位为"工具"而非"替代品" |

---

### 9.3 工程风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| **代码复杂度高，维护困难** | 中 | 中 | 模块化设计 + 完善文档 + 单元测试 |
| **与视频 Agent 冲突** | 低 | 中 | 物理隔离（独立目录、State、Pipeline） |
| **向量数据库性能瓶颈** | 低 | 低 | Chroma 支持百万级向量，10 万字小说远未达瓶颈 |

---

## 10. 和现有视频 Pipeline 的衔接点

### 10.1 数据流向

```
小说创作 Pipeline → 生成小说.txt
                    ↓
                 【用户选择】
                    ↓
        ┌───────────┴───────────┐
        ▼                       ▼
   完整小说                  章节拆分
转为单个长视频              每章一个短视频
        ↓                       ↓
  视频 Pipeline           视频 Pipeline × N
   (Agent 模式)            (并行生成)
```

### 10.2 衔接方式

#### 方式 1: 文件传递

```bash
# 1. 生成小说
python main.py write-novel --genre 武侠 --words 50000 --output novel.txt

# 2. 转为视频（使用现有 Pipeline）
python main.py run novel.txt --mode agent
```

#### 方式 2: 管道传递（V3）

```bash
# 一键完成：创作 → 视频
python main.py create-and-publish --genre 都市 --words 10000
```

### 10.3 共享模块

- **LLM 层**: `src/llm/` 复用现有的多后端支持
- **配置管理**: `src/config_manager.py` 扩展支持小说配置
- **日志**: `src/logger.py` 统一日志
- **Checkpoint**: `src/checkpoint.py` 复用断点逻辑

### 10.4 差异点

| 维度 | 视频 Pipeline | 小说 Pipeline |
|------|--------------|--------------|
| **输入** | 现有小说文本 | 用户创意（题材、主题） |
| **输出** | MP4 视频 | TXT 小说文件 |
| **核心 Agent** | Director, ArtDirector, VoiceDirector | NovelDirector, Writer, ConsistencyChecker |
| **时间尺度** | 分钟级（3-5 分钟视频） | 小时级（2 小时生成 10 万字） |
| **交互性** | 全自动 | 可配置（默认每 5 章审核，支持静默模式全自动） |

---

## 11. 总结：为什么这个设计可行

### 11.1 技术可行性

✅ **LLM 能力已验证**: GPT-4/Claude/Gemini 已能生成高质量长文（见 AI Dungeon、NovelAI 等产品）
✅ **长上下文方案成熟**: 三层混合存储（结构化DB + 知识图谱 + 向量检索）+ 分层摘要
✅ **Multi-Agent 架构可复用**: 视频 Agent 已验证 LangGraph 可行性
✅ **成本可控**: $0.15-$0.24/10 万字（三档估算），商业可行

### 11.2 产品可行性

✅ **市场需求真实**: 网文日更压力大，AI 辅助需求强烈
✅ **差异化明显**: 市场上缺少"结构化创作"工具（现有产品多为简单续写）
✅ **与现有产品互补**: 小说生成 + 视频生成 = 完整内容链

### 11.3 工程可行性

✅ **渐进式开发**: MVP 可在 4-6 周完成（复用现有基础设施）
✅ **风险可控**: 物理隔离避免影响现有视频功能
✅ **可测试**: 每个 Agent 可独立测试

---

**下一步**: 进入设计阶段（design.md），详细定义各 Agent 的 Prompt 模板、Tool 接口、数据库 Schema 等。

---

**文档版本**: v1.1
**创建日期**: 2026-03-11
**最后修改**: 2026-03-11
**作者**: AI Product Architect
**审阅状态**: 已完成审查修订（v1.1 变更摘要见下）

**v1.1 变更摘要**:
- [C1] 质量评分改为三层体系: 规则硬指标 + 对比式评估 + LLM 打分辅助
- [C2] 一致性检查改为三层混合: SQLite + NetworkX 知识图谱 + Chroma 向量检索
- [C3] 成本估算拆细每章调用，提供乐观/中性/悲观三档
- [H1] 风格体系改为二级结构（4 大类 × 8-10 子类）+ 自定义风格
- [H2] 新增节奏设计模块，BalanceRhythmTool 提升为核心能力
- [H3] 大纲结构改为多模板可选（循环升级/多线交织/经典四幕/自由）
- [H4] 角色关系改为带时间维度的变化链，关系类型扩展到 15 种
- [H5] 新增去 AI 味机制（黑名单 + 反指令 + 细节注入 + AI 味评分）
- [M7] 新增 FR-MVP-7 导入已有稿件（续写/改写/扩写）
- [M3] CharacterProfile 增加 status 字段（active/retired/deceased/absent）
- [M4] CharacterProfile 增加 speech_style/catchphrases 字段，QualityReviewer 增加对话区分度
- [M6] 人工介入间隔可配置，新增静默模式
- [L1] 修正拼写 DefinePoerSystemTool → DefinePowerSystemTool
- [L3] 新增数据模型实现建议: TypedDict → Pydantic BaseModel
