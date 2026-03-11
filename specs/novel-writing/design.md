# AI 长篇小说写作模块 - 技术设计文档

## 1. 目录结构设计

### 1.1 新增文件列表

```
/Users/ty/self/AI_novel/
├── src/
│   ├── novel/                          # 小说模块独立目录（物理隔离）
│   │   ├── __init__.py
│   │   ├── agents/                     # 小说专用 Agent
│   │   │   ├── __init__.py
│   │   │   ├── novel_director.py       # Agent-1: 总导演
│   │   │   ├── world_builder.py        # Agent-2: 世界观构建师
│   │   │   ├── character_designer.py   # Agent-3: 角色设计师
│   │   │   ├── plot_planner.py         # Agent-4: 情节规划师
│   │   │   ├── writer.py               # Agent-5: 写手
│   │   │   ├── consistency_checker.py  # Agent-6: 一致性检查官
│   │   │   ├── style_keeper.py         # Agent-7: 风格守护者
│   │   │   ├── quality_reviewer.py     # Agent-8: 质量评审官
│   │   │   ├── feedback_analyzer.py   # Agent-9: 读者反馈分析师
│   │   │   ├── state.py                # NovelState 定义
│   │   │   └── graph.py                # LangGraph 图构建
│   │   ├── tools/                      # 小说专用 Tool
│   │   │   ├── __init__.py
│   │   │   ├── outline_tool.py         # 大纲生成/更新工具
│   │   │   ├── world_setting_tool.py   # 世界观管理工具
│   │   │   ├── character_tool.py       # 角色档案管理工具
│   │   │   ├── scene_decompose_tool.py # 场景分解工具
│   │   │   ├── scene_gen_tool.py       # 场景生成工具
│   │   │   ├── consistency_tool.py     # 一致性检查工具
│   │   │   ├── style_analysis_tool.py  # 风格分析工具
│   │   │   ├── quality_check_tool.py   # 质量检查工具
│   │   │   ├── import_tool.py          # 已有稿件导入工具
│   │   │   ├── foreshadowing_tool.py   # 伏笔管理工具（V2）
│   │   │   ├── bm25_retriever.py      # BM25 关键词检索工具
│   │   │   └── chapter_digest.py      # 章节摘要压缩工具
│   │   ├── services/                   # 业务逻辑层
│   │   │   ├── __init__.py
│   │   │   ├── outline_service.py      # 大纲服务
│   │   │   ├── world_service.py        # 世界观服务
│   │   │   ├── character_service.py    # 角色服务
│   │   │   ├── scene_service.py        # 场景服务
│   │   │   ├── memory_service.py       # 记忆管理服务
│   │   │   ├── style_service.py        # 风格服务
│   │   │   ├── consistency_service.py  # 一致性检查服务
│   │   │   └── import_service.py       # 导入服务
│   │   ├── storage/                    # 存储层
│   │   │   ├── __init__.py
│   │   │   ├── novel_memory.py         # 三层混合记忆系统
│   │   │   ├── structured_db.py        # SQLite 结构化数据库
│   │   │   ├── knowledge_graph.py      # NetworkX 知识图谱
│   │   │   ├── vector_store.py         # Chroma 向量存储
│   │   │   └── file_manager.py         # 文件系统管理
│   │   ├── models/                     # 数据模型（Pydantic）
│   │   │   ├── __init__.py
│   │   │   ├── novel.py                # Novel, Outline, Act, Volume
│   │   │   ├── chapter.py              # Chapter, Scene
│   │   │   ├── character.py            # CharacterProfile, Relationship
│   │   │   ├── world.py                # WorldSetting, PowerSystem
│   │   │   ├── memory.py               # Fact, ChapterSummary, VolumeSnapshot
│   │   │   ├── foreshadowing.py        # Foreshadowing, DetailEntry
│   │   │   ├── quality.py              # QualityMetrics, RuleCheckResult
│   │   │   └── feedback.py            # FeedbackAnalysis, RewriteInstruction
│   │   ├── templates/                  # 模板和预设
│   │   │   ├── __init__.py
│   │   │   ├── outline_templates.py    # 大纲模板（循环升级/多线交织/四幕）
│   │   │   ├── style_presets.py        # 风格预设（武侠/网文/文学/轻小说）
│   │   │   ├── rhythm_templates.py     # 节奏模板（按题材）
│   │   │   └── ai_flavor_blacklist.py  # AI味短语黑名单
│   │   ├── pipeline.py                 # 小说创作流水线
│   │   ├── config.py                   # 小说模块配置
│   │   └── utils.py                    # 小说模块工具函数
│   ├── llm/                            # 共享 LLM 层（现有）
│   ├── logger.py                       # 共享日志（现有）
│   ├── config_manager.py               # 共享配置管理（现有）
│   └── checkpoint.py                   # 共享断点管理（现有）
├── main.py                             # CLI 入口（扩展命令）
├── config.yaml                         # 全局配置（新增 novel 配置段）
└── tests/
    └── novel/                          # 小说模块测试
        ├── test_agents/
        ├── test_tools/
        ├── test_services/
        └── test_storage/
```

### 1.2 与现有代码的关系

**物理隔离**:
- 小说模块完全独立在 `src/novel/` 目录
- 视频模块保持在 `src/agents/`, `src/tools/` 等现有位置
- 互不干扰，可独立迭代

**共享基础设施**:
- `src/llm/` - LLM 统一抽象层（OpenAI/DeepSeek/Gemini/Ollama）
- `src/logger.py` - Rich 日志
- `src/config_manager.py` - YAML 配置加载
- `src/checkpoint.py` - 断点续传基础

**Workspace 隔离**:
```
workspace/
├── {video_project_id}/     # 视频项目
│   ├── segments.json
│   ├── images/
│   └── ...
└── novels/                 # 小说项目
    └── {novel_id}/
        ├── novel.json      # Novel 对象序列化
        ├── chapters/       # 章节正文
        ├── memory.db       # SQLite 数据库
        ├── graph.pkl       # NetworkX 图序列化
        ├── vectors/        # Chroma 向量索引
        └── checkpoint.json # 断点数据
```

---

## 2. 分层架构图

```
┌─────────────────────────────────────────────────────────────┐
│                         CLI 层                               │
│  main.py: write-novel / resume-novel / import-novel         │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│                    Pipeline 层                               │
│  NovelPipeline: 编排流程、断点续传、进度管理                 │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│                    Agent 层（LangGraph）                     │
│  8 个 Agent: Director / WorldBuilder / CharacterDesigner /  │
│  PlotPlanner / Writer / ConsistencyChecker / StyleKeeper /  │
│  QualityReviewer                                            │
└─────┬──────────────┬─────────────┬────────────────┬─────────┘
      │              │             │                │
┌─────▼─────┐  ┌────▼────┐  ┌─────▼─────┐  ┌──────▼──────┐
│ Tool 层   │  │Service层│  │ Storage层 │  │  LLM 层     │
│ 封装单一  │  │ 业务逻辑│  │ 三层混合  │  │  统一抽象   │
│ 原子操作  │  │ 协调多个│  │ 持久化    │  │  多后端     │
│           │  │ 组件    │  │           │  │             │
└───────────┘  └─────────┘  └───────────┘  └─────────────┘
      │              │             │                │
      └──────────────┴─────────────┴────────────────┘
                     │
            ┌────────▼────────┐
            │   数据模型层     │
            │  Pydantic Models │
            └─────────────────┘
```

**层次职责**:

1. **CLI 层**: 解析命令、加载配置、调用 Pipeline
2. **Pipeline 层**: 状态机管理、LangGraph 执行、断点续传
3. **Agent 层**: 决策制定、调用 Tool、记录决策日志
4. **Tool 层**: 原子操作封装（一个 Tool 一个职责）
5. **Service 层**: 业务逻辑协调（跨多个 Tool 的复杂操作）
6. **Storage 层**: 数据持久化（SQLite/NetworkX/Chroma/File）
7. **LLM 层**: 统一 LLM 调用接口（复用现有 `src/llm/`）
8. **数据模型层**: 类型定义、验证、序列化

---

## 3. 核心接口定义

### 3.1 Agent 接口

#### Agent-1: NovelDirector（总导演）

```python
# src/novel/agents/novel_director.py
from typing import Any
from src.novel.agents.state import NovelState
from src.novel.models.novel import Outline

class NovelDirector:
    """总导演 Agent - 负责大纲生成和流程协调"""

    def __init__(self, llm_client):
        self.llm = llm_client
        self.outline_tool = OutlineTool(llm_client)

    def analyze_user_input(
        self,
        genre: str,
        theme: str,
        target_words: int,
        custom_ideas: str | None = None
    ) -> dict[str, Any]:
        """分析用户输入，提取关键信息"""
        ...

    def generate_outline(
        self,
        genre: str,
        theme: str,
        target_words: int,
        template: str = "cyclic_upgrade"
    ) -> Outline:
        """生成三层大纲（总大纲/卷大纲/章大纲）"""
        ...

    def update_outline(
        self,
        outline: Outline,
        modifications: dict[str, Any]
    ) -> Outline:
        """响应用户中途修改，更新大纲"""
        ...

    def plan_workflow(self, outline: Outline) -> dict[str, Any]:
        """规划各 Agent 的调用顺序"""
        ...

def novel_director_node(state: NovelState) -> dict[str, Any]:
    """LangGraph 节点函数"""
    ...
```

#### Agent-2: WorldBuilder（世界观构建师）

```python
# src/novel/agents/world_builder.py
from src.novel.models.world import WorldSetting, PowerSystem

class WorldBuilder:
    """世界观构建师 Agent"""

    def __init__(self, llm_client):
        self.llm = llm_client
        self.world_tool = WorldSettingTool(llm_client)

    def create_world_setting(
        self,
        genre: str,
        outline: Outline
    ) -> WorldSetting:
        """根据题材和大纲创建世界观框架"""
        ...

    def define_power_system(
        self,
        genre: str,
        target_levels: int = 10
    ) -> PowerSystem | None:
        """定义力量体系（玄幻/武侠）"""
        ...

    def register_term(
        self,
        term: str,
        definition: str,
        chapter: int
    ) -> None:
        """注册专有名词"""
        ...

    def validate_setting_consistency(
        self,
        chapter_text: str,
        world_setting: WorldSetting
    ) -> tuple[bool, list[str]]:
        """检查章节内容是否违反世界观设定"""
        ...

def world_builder_node(state: NovelState) -> dict[str, Any]:
    """LangGraph 节点函数"""
    ...
```

#### Agent-3: CharacterDesigner（角色设计师）

```python
# src/novel/agents/character_designer.py
from src.novel.models.character import CharacterProfile, Relationship

class CharacterDesigner:
    """角色设计师 Agent"""

    def __init__(self, llm_client):
        self.llm = llm_client
        self.char_tool = CharacterTool(llm_client)

    def extract_characters(
        self,
        outline: Outline
    ) -> list[str]:
        """从大纲提取角色列表（姓名）"""
        ...

    def generate_character_profile(
        self,
        name: str,
        role: str,  # protagonist / antagonist / supporting
        genre: str,
        outline_context: str
    ) -> CharacterProfile:
        """生成完整角色档案"""
        ...

    def define_relationship(
        self,
        char1_id: str,
        char2_id: str,
        relationship_type: str,
        intensity: int,
        description: str
    ) -> Relationship:
        """定义角色关系"""
        ...

    def track_character_arc(
        self,
        character_id: str,
        chapter: int,
        event: str,
        change: str
    ) -> None:
        """追踪角色成长"""
        ...

    def validate_character_consistency(
        self,
        character_id: str,
        chapter_text: str,
        character_profile: CharacterProfile
    ) -> tuple[bool, list[str]]:
        """检查角色行为是否 OOC"""
        ...

def character_designer_node(state: NovelState) -> dict[str, Any]:
    """LangGraph 节点函数"""
    ...
```

#### Agent-4: PlotPlanner（情节规划师）

```python
# src/novel/agents/plot_planner.py
from src.novel.models.chapter import Scene
from src.novel.models.novel import ChapterOutline

class PlotPlanner:
    """情节规划师 Agent - 场景分解和节奏设计"""

    def __init__(self, llm_client):
        self.llm = llm_client
        self.scene_tool = SceneDecomposeTool(llm_client)

    def decompose_chapter(
        self,
        chapter_outline: ChapterOutline,
        target_scenes: int = 4
    ) -> list[Scene]:
        """将章大纲分解为场景序列（每个场景 500-1500 字）"""
        ...

    def design_chapter_rhythm(
        self,
        chapter_number: int,
        genre: str,
        total_chapters: int
    ) -> tuple[str, str]:
        """设计章节情绪节奏

        Returns:
            (chapter_mood, rhythm_instruction)
            chapter_mood: 蓄力/小爽/大爽/过渡/虐心/反转/日常
            rhythm_instruction: 传递给 Writer 的节奏指令
        """
        ...

    def check_rhythm_anomaly(
        self,
        recent_moods: list[str]
    ) -> tuple[bool, str | None]:
        """检测节奏异常（连续 3+ 章同一基调）

        Returns:
            (has_anomaly, warning_message)
        """
        ...

    def plan_foreshadowing(
        self,
        chapter: int,
        outline: Outline
    ) -> list[dict[str, Any]]:
        """规划伏笔埋设与回收（V2）"""
        ...

def plot_planner_node(state: NovelState) -> dict[str, Any]:
    """LangGraph 节点函数"""
    ...
```

#### Agent-5: Writer（写手）

```python
# src/novel/agents/writer.py
from src.novel.models.chapter import Chapter, Scene

class Writer:
    """写手 Agent - 正文生成"""

    def __init__(self, llm_client):
        self.llm = llm_client
        self.gen_tool = SceneGenTool(llm_client)

    def generate_scene(
        self,
        scene: Scene,
        context: dict[str, Any],
        style: str,
        rhythm_instruction: str
    ) -> str:
        """生成单个场景正文（500-1500 字）

        Args:
            scene: 场景大纲
            context: {
                "world_setting": WorldSetting,
                "characters": list[CharacterProfile],
                "recent_chapters": str,  # 最近 3 章正文
                "relevant_facts": str,   # 向量检索结果
            }
            style: 风格类型
            rhythm_instruction: 节奏指令（来自 PlotPlanner）
        """
        ...

    def apply_style(
        self,
        text: str,
        style: str
    ) -> str:
        """应用风格模板重写文本"""
        ...

    def add_cliffhanger(
        self,
        chapter_text: str,
        next_chapter_hint: str | None = None
    ) -> str:
        """在章末添加悬念钩子"""
        ...

    def polish_transitions(
        self,
        scenes: list[str]
    ) -> str:
        """平滑场景间过渡，拼接为完整章节"""
        ...

def writer_node(state: NovelState) -> dict[str, Any]:
    """LangGraph 节点函数"""
    ...
```

#### Agent-6: ConsistencyChecker（一致性检查官）

```python
# src/novel/agents/consistency_checker.py
from src.novel.models.memory import Fact

class ConsistencyChecker:
    """一致性检查官 Agent - 三层混合检测"""

    def __init__(self, llm_client, memory_service):
        self.llm = llm_client
        self.memory = memory_service  # NovelMemory 实例
        self.consistency_tool = ConsistencyTool(llm_client, memory_service)

    def extract_facts(
        self,
        chapter: Chapter
    ) -> list[Fact]:
        """从新章提取关键事实

        提取类型: time / character_state / location / event / relationship
        """
        ...

    def check_consistency(
        self,
        chapter: Chapter,
        facts: list[Fact]
    ) -> tuple[bool, list[dict[str, Any]], float]:
        """三层混合一致性检查

        Returns:
            (passed, contradictions, confidence)
            contradictions: [{"type": str, "layer": str, "detail": str}, ...]
            confidence: 0.0-1.0
        """
        ...

    def query_structured_db(
        self,
        fact: Fact
    ) -> list[dict[str, Any]]:
        """第一层: SQLite 精确查询"""
        ...

    def query_relationship_graph(
        self,
        character_ids: list[str]
    ) -> dict[str, Any]:
        """第二层: NetworkX 图查询"""
        ...

    def vector_search(
        self,
        query: str,
        n_results: int = 5
    ) -> list[dict[str, Any]]:
        """第三层: Chroma 向量检索"""
        ...

    def llm_judge_contradiction(
        self,
        new_fact: Fact,
        historical_facts: list[dict[str, Any]]
    ) -> tuple[bool, str]:
        """LLM 裁决是否构成实质矛盾

        Returns:
            (is_contradiction, reason)
        """
        ...

def consistency_checker_node(state: NovelState) -> dict[str, Any]:
    """LangGraph 节点函数"""
    ...
```

#### Agent-7: StyleKeeper（风格守护者）

```python
# src/novel/agents/style_keeper.py
from src.novel.models.quality import StyleMetrics

class StyleKeeper:
    """风格守护者 Agent"""

    def __init__(self, llm_client):
        self.llm = llm_client
        self.style_tool = StyleAnalysisTool()

    def analyze_style(
        self,
        text: str
    ) -> StyleMetrics:
        """分析文本风格特征

        返回指标: avg_sentence_length / dialogue_ratio /
                 exclamation_ratio / paragraph_length /
                 classical_word_ratio / description_ratio
        """
        ...

    def compare_style(
        self,
        text: str,
        reference_style: str | StyleMetrics
    ) -> tuple[float, list[str]]:
        """与参考风格对比

        Returns:
            (similarity_score, deviations)
            similarity_score: 0.0-1.0
            deviations: 偏离项列表
        """
        ...

    def rewrite_for_style(
        self,
        text: str,
        target_style: str
    ) -> str:
        """重写文本以匹配目标风格"""
        ...

    def extract_custom_style(
        self,
        reference_texts: list[str]
    ) -> StyleMetrics:
        """从用户提供的参考文本提取风格特征（自定义风格）"""
        ...

def style_keeper_node(state: NovelState) -> dict[str, Any]:
    """LangGraph 节点函数"""
    ...
```

#### Agent-8: QualityReviewer（质量评审官）

```python
# src/novel/agents/quality_reviewer.py
from src.novel.models.quality import RuleCheckResult, PairwiseResult

class QualityReviewer:
    """质量评审官 Agent - 三层评估体系"""

    def __init__(self, llm_client):
        self.llm = llm_client
        self.quality_tool = QualityCheckTool(llm_client)

    def rule_based_check(
        self,
        chapter: Chapter,
        characters: list[CharacterProfile]
    ) -> RuleCheckResult:
        """第一层: 规则硬指标检查（零成本）

        检查项:
        - 重复句检测（连续 3 句相似度 > 80%）
        - 对话标签一致性
        - 段落长度分布异常
        - AI 味短语黑名单（50+ 短语）
        - 对话区分度（不同角色对话相似度）
        """
        ...

    def pairwise_compare(
        self,
        version_a: str,
        version_b: str,
        criteria: str
    ) -> PairwiseResult:
        """第二层: 对比式评估（LLM 选优）

        Returns:
            PairwiseResult(winner="A"|"B"|"TIE", reason=str)
        """
        ...

    def evaluate_chapter(
        self,
        chapter: Chapter
    ) -> dict[str, float]:
        """第三层: LLM 绝对打分（仅作粗筛）

        Returns:
            {
                "plot_coherence": 0-10,
                "writing_quality": 0-10,
                "character_portrayal": 0-10,
                "ai_flavor_score": 0-10,  # 越低越好
            }
        """
        ...

    def suggest_improvement(
        self,
        chapter: Chapter,
        issues: list[str]
    ) -> list[str]:
        """生成改进建议"""
        ...

    def should_rewrite(
        self,
        rule_result: RuleCheckResult,
        scores: dict[str, float]
    ) -> tuple[bool, str]:
        """判断是否需要重写

        Returns:
            (need_rewrite, reason)
        """
        ...

def quality_reviewer_node(state: NovelState) -> dict[str, Any]:
    """LangGraph 节点函数"""
    ...
```

---

### 3.2 Tool 接口

#### OutlineTool

```python
# src/novel/tools/outline_tool.py

class OutlineTool:
    """大纲生成/更新工具"""

    def __init__(self, llm_client):
        self.llm = llm_client
        self.outline_service = OutlineService(llm_client)

    def generate_outline(
        self,
        genre: str,
        theme: str,
        target_words: int,
        template: str
    ) -> Outline:
        """生成三层大纲"""
        ...

    def update_chapter_outline(
        self,
        outline: Outline,
        chapter_number: int,
        modifications: dict[str, Any]
    ) -> Outline:
        """更新指定章节大纲"""
        ...
```

#### WorldSettingTool

```python
# src/novel/tools/world_setting_tool.py

class WorldSettingTool:
    """世界观管理工具"""

    def __init__(self, llm_client):
        self.llm = llm_client
        self.world_service = WorldService(llm_client)

    def create_world_setting(
        self,
        genre: str,
        outline: Outline
    ) -> WorldSetting:
        """创建世界观框架"""
        ...

    def define_power_system(
        self,
        genre: str,
        levels: int
    ) -> PowerSystem:
        """定义力量体系"""
        ...

    def add_term(
        self,
        term: str,
        definition: str
    ) -> None:
        """添加专有名词"""
        ...
```

#### CharacterTool

```python
# src/novel/tools/character_tool.py

class CharacterTool:
    """角色档案管理工具"""

    def __init__(self, llm_client):
        self.llm = llm_client
        self.char_service = CharacterService(llm_client)

    def create_character(
        self,
        name: str,
        role: str,
        genre: str,
        outline_context: str
    ) -> CharacterProfile:
        """创建角色档案"""
        ...

    def update_relationship(
        self,
        char1_id: str,
        char2_id: str,
        new_type: str,
        chapter: int,
        trigger_event: str
    ) -> None:
        """更新角色关系"""
        ...
```

#### SceneDecomposeTool

```python
# src/novel/tools/scene_decompose_tool.py

class SceneDecomposeTool:
    """场景分解工具"""

    def __init__(self, llm_client):
        self.llm = llm_client

    def decompose_chapter(
        self,
        chapter_outline: ChapterOutline,
        target_scenes: int
    ) -> list[Scene]:
        """将章大纲拆解为场景序列"""
        ...
```

#### SceneGenTool

```python
# src/novel/tools/scene_gen_tool.py

class SceneGenTool:
    """场景生成工具"""

    def __init__(self, llm_client):
        self.llm = llm_client
        self.scene_service = SceneService(llm_client)

    def generate_scene(
        self,
        scene: Scene,
        context: dict[str, Any],
        style: str,
        rhythm_instruction: str
    ) -> str:
        """生成场景正文"""
        ...
```

#### ConsistencyTool

```python
# src/novel/tools/consistency_tool.py

class ConsistencyTool:
    """一致性检查工具"""

    def __init__(self, llm_client, memory_service):
        self.llm = llm_client
        self.memory = memory_service
        self.consistency_service = ConsistencyService(llm_client, memory_service)

    def check_consistency(
        self,
        chapter: Chapter,
        facts: list[Fact]
    ) -> tuple[bool, list[dict], float]:
        """执行三层混合检测"""
        ...
```

#### QualityCheckTool

```python
# src/novel/tools/quality_check_tool.py

class QualityCheckTool:
    """质量检查工具"""

    def __init__(self, llm_client):
        self.llm = llm_client

    def rule_check(
        self,
        chapter: Chapter,
        characters: list[CharacterProfile]
    ) -> RuleCheckResult:
        """规则硬指标检查"""
        ...

    def pairwise_compare(
        self,
        version_a: str,
        version_b: str
    ) -> PairwiseResult:
        """对比式评估"""
        ...
```

#### ImportTool

```python
# src/novel/tools/import_tool.py

class ImportTool:
    """已有稿件导入工具"""

    def __init__(self, llm_client):
        self.llm = llm_client
        self.import_service = ImportService(llm_client)

    def import_existing_draft(
        self,
        file_path: str,
        auto_split: bool = True
    ) -> dict[str, Any]:
        """导入已有稿件

        Returns:
            {
                "chapters": list[Chapter],
                "characters": list[CharacterProfile],
                "world_setting": WorldSetting,
                "plot_threads": list[PlotThread],
            }
        """
        ...

    def auto_extract_metadata(
        self,
        chapters: list[Chapter]
    ) -> dict[str, Any]:
        """自动提取元数据（角色/世界观/情节线）"""
        ...
```

---

## 4. 数据模型（Pydantic）

### 4.1 核心数据结构

```python
# src/novel/models/novel.py
from pydantic import BaseModel, Field
from datetime import datetime

class Novel(BaseModel):
    """小说项目根对象"""
    novel_id: str = Field(..., description="UUID")
    title: str = Field(..., min_length=1, max_length=100)
    genre: str = Field(..., description="题材: 武侠/都市/玄幻/科幻/言情/悬疑")
    theme: str = Field(..., description="主题")
    target_words: int = Field(..., gt=0, description="目标字数")

    # 风格
    style_category: str = Field(..., description="武侠/网文/文学/轻小说")
    style_subcategory: str = Field(..., description="子类风格")
    custom_style_reference: str | None = Field(None, description="自定义风格参考文本")

    # 结构
    outline: "Outline"
    volumes: list["Volume"] = Field(default_factory=list)
    chapters: list["Chapter"] = Field(default_factory=list)

    # 设定
    world_setting: "WorldSetting"
    characters: list["CharacterProfile"] = Field(default_factory=list)

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    status: str = Field("draft", pattern="^(draft|writing|completed)$")
    current_chapter: int = Field(0, ge=0)


class Outline(BaseModel):
    """三层大纲结构"""
    template: str = Field(..., description="cyclic_upgrade|multi_thread|four_act|custom")
    acts: list["Act"] = Field(default_factory=list)
    volumes: list["VolumeOutline"] = Field(default_factory=list)
    chapters: list["ChapterOutline"] = Field(default_factory=list)


class Act(BaseModel):
    """幕（最顶层结构）"""
    name: str = Field(..., description="如'第一幕：平凡世界'")
    description: str
    start_chapter: int = Field(..., ge=1)
    end_chapter: int = Field(..., ge=1)


class VolumeOutline(BaseModel):
    """卷大纲"""
    volume_number: int = Field(..., ge=1)
    title: str
    core_conflict: str = Field(..., description="本卷核心矛盾")
    resolution: str = Field(..., description="本卷如何解决")
    chapters: list[int] = Field(..., description="包含的章节号")


class ChapterOutline(BaseModel):
    """章大纲"""
    chapter_number: int = Field(..., ge=1)
    title: str
    goal: str = Field(..., description="本章目标")
    key_events: list[str] = Field(..., min_items=1)
    involved_characters: list[str] = Field(default_factory=list, description="角色 ID 列表")
    plot_threads: list[str] = Field(default_factory=list, description="推进的情节线 ID")
    estimated_words: int = Field(3000, ge=1000, le=10000)
    mood: str = Field("蓄力", description="蓄力/小爽/大爽/过渡/虐心/反转/日常")


class Volume(BaseModel):
    """卷实体"""
    volume_number: int = Field(..., ge=1)
    title: str
    chapters: list[int] = Field(default_factory=list)
    status: str = Field("planning", pattern="^(planning|writing|completed)$")
    snapshot: "VolumeSnapshot | None" = None
```

```python
# src/novel/models/chapter.py
from pydantic import BaseModel, Field
from datetime import datetime

class Chapter(BaseModel):
    """章节"""
    chapter_id: str = Field(..., description="UUID")
    chapter_number: int = Field(..., ge=1)
    title: str

    # 内容
    scenes: list["Scene"] = Field(default_factory=list)
    full_text: str = Field("", description="完整正文，拼接 scenes")
    word_count: int = Field(0, ge=0)

    # 元数据
    outline: "ChapterOutline"
    generated_at: datetime = Field(default_factory=datetime.now)
    quality_score: float = Field(0.0, ge=0.0, le=10.0)

    # 状态
    status: str = Field("draft", pattern="^(draft|reviewed|finalized)$")
    revision_count: int = Field(0, ge=0)


class Scene(BaseModel):
    """场景（章节组成单元）"""
    scene_id: str = Field(..., description="UUID")
    scene_number: int = Field(..., ge=1, description="章内序号")

    # 场景要素
    location: str = Field(..., description="地点")
    time: str = Field(..., description="时间（相对时间）")
    characters: list[str] = Field(..., description="出场角色 ID")
    goal: str = Field(..., description="场景目标")

    # 内容
    text: str = Field("", min_length=0, max_length=3000)
    word_count: int = Field(0, ge=0)

    # 叙事元素
    narrative_modes: list[str] = Field(
        default_factory=list,
        description="对话/动作/描写/心理"
    )
```

```python
# src/novel/models/character.py
from pydantic import BaseModel, Field

class CharacterProfile(BaseModel):
    """角色档案"""
    character_id: str = Field(..., description="UUID")
    name: str = Field(..., min_length=1)
    alias: list[str] = Field(default_factory=list)

    # 基础属性
    gender: str = Field(..., pattern="^(男|女|其他)$")
    age: int = Field(..., ge=0, le=200)
    occupation: str
    status: str = Field("active", pattern="^(active|retired|deceased|absent)$")

    # 外貌
    appearance: "Appearance"

    # 性格
    personality: "Personality"

    # 关系网
    relationships: list["Relationship"] = Field(default_factory=list)

    # 成长弧线
    character_arc: "CharacterArc | None" = None

    # 立绘（V2）
    portrait_image: str | None = None


class Appearance(BaseModel):
    """外貌特征"""
    height: str = Field(..., description="如'175cm'")
    build: str = Field(..., description="体型: 瘦削/魁梧/匀称")
    hair: str = Field(..., description="发型颜色")
    eyes: str
    clothing_style: str
    distinctive_features: list[str] = Field(default_factory=list, description="如'左脸刀疤'")


class Personality(BaseModel):
    """性格"""
    traits: list[str] = Field(..., min_items=3, max_items=7, description="性格标签")
    core_belief: str = Field(..., description="核心信念")
    motivation: str = Field(..., description="动机")
    flaw: str = Field(..., description="缺陷")
    speech_style: str = Field(..., description="语言风格: 文绉绉/江湖豪爽/冷淡简短")
    catchphrases: list[str] = Field(default_factory=list, description="口头禅")


class Relationship(BaseModel):
    """角色关系（带时间维度）"""
    target_character_id: str
    current_type: str = Field(
        ...,
        description="敌对/友好/暧昧/师徒/亲属/竞争/利用/依赖/崇拜/畏惧/合作/背叛/暗恋/仇杀/陌生"
    )
    description: str
    intensity: int = Field(..., ge=1, le=10, description="关系强度")
    history: list["RelationshipEvent"] = Field(default_factory=list)


class RelationshipEvent(BaseModel):
    """关系变化事件"""
    chapter: int = Field(..., ge=1)
    from_type: str
    to_type: str
    trigger_event: str = Field(..., description="触发事件")
    intensity_change: int = Field(..., ge=-10, le=10)


class CharacterArc(BaseModel):
    """角色成长弧线"""
    initial_state: str = Field(..., description="如'懦弱自卑'")
    turning_points: list["TurningPoint"] = Field(default_factory=list)
    final_state: str = Field(..., description="如'自信坚毅'")


class TurningPoint(BaseModel):
    """角色转折点"""
    chapter: int = Field(..., ge=1)
    event: str
    change: str = Field(..., description="如'学会坚持'")
```

```python
# src/novel/models/world.py
from pydantic import BaseModel, Field

class WorldSetting(BaseModel):
    """世界观设定"""
    era: str = Field(..., description="古代/现代/未来/架空")
    location: str = Field(..., description="地域背景")

    # 力量体系（玄幻/武侠特有）
    power_system: "PowerSystem | None" = None

    # 专有名词表
    terms: dict[str, str] = Field(default_factory=dict, description="专有名词→定义")

    # 关键设定
    rules: list[str] = Field(default_factory=list, description="世界规则")


class PowerSystem(BaseModel):
    """力量体系"""
    name: str = Field(..., description="如'修炼境界'")
    levels: list["PowerLevel"] = Field(..., min_items=1)


class PowerLevel(BaseModel):
    """单个力量等级"""
    rank: int = Field(..., ge=1)
    name: str = Field(..., description="如'筑基期'")
    description: str
    typical_abilities: list[str] = Field(default_factory=list)
```

```python
# src/novel/models/memory.py
from pydantic import BaseModel, Field

class Fact(BaseModel):
    """关键事实"""
    fact_id: str = Field(..., description="UUID")
    chapter: int = Field(..., ge=1)
    type: str = Field(
        ...,
        description="time/character_state/location/event/relationship"
    )
    content: str = Field(..., min_length=1)
    storage_layer: str = Field(..., pattern="^(structured|graph|vector)$")
    embedding: list[float] | None = None


class ChapterSummary(BaseModel):
    """章节摘要"""
    chapter: int = Field(..., ge=1)
    summary: str = Field(..., min_length=50, max_length=1000)
    key_events: list[str] = Field(..., min_items=1)


class VolumeSnapshot(BaseModel):
    """卷间过渡快照"""
    volume_number: int = Field(..., ge=1)

    # 主线进度
    main_plot_progress: str
    main_plot_completion: float = Field(..., ge=0.0, le=1.0)

    # 角色状态快照
    character_states: list["CharacterSnapshot"] = Field(default_factory=list)

    # 伏笔管理
    unresolved_foreshadowing: list["Foreshadowing"] = Field(default_factory=list)
    resolved_this_volume: list[str] = Field(default_factory=list)

    # 上卷结尾
    ending_summary: str = Field(..., min_length=100, max_length=1000)
    cliffhanger: str | None = None

    # 世界观增量
    new_terms: dict[str, str] = Field(default_factory=dict)
    power_changes: list[str] = Field(default_factory=list)


class CharacterSnapshot(BaseModel):
    """角色状态快照"""
    character_id: str
    name: str
    current_power_level: str | None = None
    location: str
    health: str
    emotional_state: str
    key_relationships_changed: list[str] = Field(default_factory=list)
```

```python
# src/novel/models/foreshadowing.py
from pydantic import BaseModel, Field

class Foreshadowing(BaseModel):
    """伏笔（V2）"""
    foreshadowing_id: str = Field(..., description="UUID")
    planted_chapter: int = Field(..., ge=1, description="埋设章节（正向）或原始章节（后置）")
    content: str = Field(..., min_length=1)

    # 回收计划
    target_chapter: int = Field(..., ge=-1, description="-1 表示后置伏笔初始状态")
    resolution: str | None = None

    # 伏笔类型
    origin: str = Field(..., pattern="^(planned|retroactive)$")
    original_detail_id: str | None = None
    original_context: str | None = None

    status: str = Field("pending", pattern="^(pending|collected|abandoned)$")
    collected_chapter: int | None = None


class DetailEntry(BaseModel):
    """历史闲笔（潜在可利用的细节）"""
    detail_id: str = Field(..., description="UUID")
    chapter: int = Field(..., ge=1)
    content: str = Field(..., min_length=1)
    context: str = Field(..., description="原文上下文，前后 2 句")
    category: str = Field(
        ...,
        description="道具/环境/角色动作/异常现象/对话暗示"
    )
    status: str = Field("available", pattern="^(available|promoted|used)$")
    promoted_foreshadowing_id: str | None = None
```

```python
# src/novel/models/quality.py
from pydantic import BaseModel, Field

class StyleMetrics(BaseModel):
    """风格特征指标"""
    avg_sentence_length: float = Field(..., ge=0)
    dialogue_ratio: float = Field(..., ge=0.0, le=1.0)
    exclamation_ratio: float = Field(..., ge=0.0, le=1.0)
    paragraph_length: float = Field(..., ge=0)
    classical_word_ratio: float | None = Field(None, ge=0.0, le=1.0)
    description_ratio: float | None = Field(None, ge=0.0, le=1.0)
    first_person_ratio: float | None = Field(None, ge=0.0, le=1.0)


class RuleCheckResult(BaseModel):
    """规则硬指标检查结果"""
    passed: bool
    repetition_issues: list[str] = Field(default_factory=list)
    dialogue_tag_issues: list[str] = Field(default_factory=list)
    paragraph_length_issues: list[str] = Field(default_factory=list)
    ai_flavor_issues: list[str] = Field(default_factory=list)
    dialogue_distinction_issues: list[str] = Field(default_factory=list)


class PairwiseResult(BaseModel):
    """对比式评估结果"""
    winner: str = Field(..., pattern="^(A|B|TIE)$")
    reason: str = Field(..., min_length=1)
```

---

## 5. 存储方案

### 5.1 项目文件结构

```
workspace/novels/{novel_id}/
├── novel.json              # Novel 对象序列化（Pydantic .model_dump_json()）
├── config.json             # 项目专属配置（覆盖全局配置）
├── checkpoint.json         # 断点数据
├── chapters/               # 章节正文
│   ├── chapter_001.txt
│   ├── chapter_002.txt
│   └── ...
├── memory.db               # SQLite 结构化数据库
├── graph.pkl               # NetworkX 知识图谱序列化
└── vectors/                # Chroma 向量索引目录
    ├── chroma.sqlite3
    └── ...
```

### 5.2 SQLite Schema

```sql
-- memory.db

-- 角色状态追踪表
CREATE TABLE character_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id TEXT NOT NULL,
    chapter INTEGER NOT NULL,
    health TEXT,                -- "健康" / "轻伤" / "重伤"
    location TEXT,              -- "南疆荒漠"
    power_level TEXT,           -- "金丹中期"
    emotional_state TEXT,       -- "愤怒" / "冷静"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(character_id, chapter)
);

-- 时间线表
CREATE TABLE timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter INTEGER NOT NULL,
    scene INTEGER NOT NULL,
    absolute_time TEXT,         -- "1024年春天" / NULL
    relative_time TEXT,         -- "三天后" / "同日午后"
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chapter, scene)
);

-- 专有名词表
CREATE TABLE terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL UNIQUE,
    definition TEXT NOT NULL,
    first_chapter INTEGER NOT NULL,
    category TEXT,              -- "门派" / "法宝" / "地名"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 力量等级追踪表
CREATE TABLE power_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id TEXT NOT NULL,
    chapter INTEGER NOT NULL,
    level TEXT NOT NULL,        -- "筑基期"
    change_reason TEXT,         -- "突破" / "受伤降级"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(character_id, chapter)
);

-- 事实表（三层共享）
CREATE TABLE facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id TEXT NOT NULL UNIQUE,
    chapter INTEGER NOT NULL,
    type TEXT NOT NULL,         -- time/character_state/location/event/relationship
    content TEXT NOT NULL,
    storage_layer TEXT NOT NULL, -- structured / graph / vector
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 章节摘要表
CREATE TABLE chapter_summaries (
    chapter INTEGER PRIMARY KEY,
    summary TEXT NOT NULL,
    key_events TEXT NOT NULL,   -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_character_states_chapter ON character_states(chapter);
CREATE INDEX idx_timeline_chapter ON timeline(chapter);
CREATE INDEX idx_facts_chapter ON facts(chapter);
CREATE INDEX idx_facts_type ON facts(type);
```

### 5.3 NetworkX 知识图谱结构

```python
# src/novel/storage/knowledge_graph.py
import networkx as nx

class KnowledgeGraph:
    """NetworkX 知识图谱管理"""

    def __init__(self):
        self.graph = nx.MultiDiGraph()  # 多重有向图（支持多条边）

    # 节点类型:
    # - character: 角色
    # - faction: 势力/阵营
    # - location: 地点

    # 边类型 + 属性:
    # - relationship: (char1, char2, type="敌对", intensity=8, chapter=10)
    # - affiliation: (char, faction, type="member", chapter=5)
    # - transition: (loc1, loc2, distance="远", chapter=12)

    def add_character(self, character_id: str, name: str) -> None:
        """添加角色节点"""
        self.graph.add_node(character_id, type="character", name=name)

    def add_relationship(
        self,
        char1_id: str,
        char2_id: str,
        rel_type: str,
        intensity: int,
        chapter: int
    ) -> None:
        """添加/更新角色关系边"""
        self.graph.add_edge(
            char1_id,
            char2_id,
            key=f"{rel_type}_{chapter}",
            type=rel_type,
            intensity=intensity,
            chapter=chapter
        )

    def get_relationships(self, character_id: str) -> list[dict]:
        """查询角色的所有关系"""
        ...

    def find_shortest_path(
        self,
        loc1: str,
        loc2: str
    ) -> list[str] | None:
        """查找地点间最短路径（检测位移合理性）"""
        ...

    def get_faction_members(self, faction_id: str) -> list[str]:
        """查询阵营成员"""
        ...

    def save(self, path: str) -> None:
        """序列化保存为 .pkl"""
        nx.write_gpickle(self.graph, path)

    @classmethod
    def load(cls, path: str) -> "KnowledgeGraph":
        """从 .pkl 加载"""
        kg = cls()
        kg.graph = nx.read_gpickle(path)
        return kg
```

### 5.4 Chroma 向量存储结构

```python
# src/novel/storage/vector_store.py
import chromadb
from chromadb.config import Settings

class VectorStore:
    """Chroma 向量存储管理"""

    def __init__(self, persist_directory: str):
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = None

    def create_collection(self, novel_id: str) -> None:
        """创建集合"""
        self.collection = self.client.get_or_create_collection(
            name=f"novel_{novel_id}",
            metadata={"hnsw:space": "cosine"}
        )

    def add_fact(self, fact: Fact) -> None:
        """添加事实向量"""
        self.collection.add(
            documents=[fact.content],
            metadatas=[{
                "chapter": fact.chapter,
                "type": fact.type,
                "fact_id": fact.fact_id
            }],
            ids=[fact.fact_id]
        )

    def add_detail(self, detail: DetailEntry) -> None:
        """添加闲笔条目（后置伏笔）"""
        self.collection.add(
            documents=[detail.content],
            metadatas=[{
                "chapter": detail.chapter,
                "category": detail.category,
                "detail_id": detail.detail_id,
                "type": "detail"  # 标记为闲笔
            }],
            ids=[detail.detail_id]
        )

    def search_similar_facts(
        self,
        query: str,
        n_results: int = 5,
        filter_type: str | None = None
    ) -> list[dict]:
        """向量检索相似事实"""
        where = {"type": filter_type} if filter_type else None
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where
        )
        return results

    def search_potential_details(
        self,
        query: str,
        category: str | None = None,
        n_results: int = 5
    ) -> list[dict]:
        """检索潜在可利用的闲笔（后置伏笔）"""
        where = {"type": "detail"}
        if category:
            where["category"] = category

        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where
        )
        return results
```

---

## 6. 记忆系统设计

### 6.1 NovelMemory 类接口

```python
# src/novel/storage/novel_memory.py
from src.novel.storage.structured_db import StructuredDB
from src.novel.storage.knowledge_graph import KnowledgeGraph
from src.novel.storage.vector_store import VectorStore

class NovelMemory:
    """三层混合记忆系统"""

    def __init__(self, novel_id: str, workspace_dir: str):
        self.novel_id = novel_id
        self.workspace = Path(workspace_dir) / "novels" / novel_id
        self.workspace.mkdir(parents=True, exist_ok=True)

        # 三层存储
        self.structured_db = StructuredDB(self.workspace / "memory.db")
        self.knowledge_graph = KnowledgeGraph()
        self.vector_store = VectorStore(str(self.workspace / "vectors"))

        # 加载现有数据
        self._load()

    def _load(self) -> None:
        """加载现有记忆数据"""
        graph_path = self.workspace / "graph.pkl"
        if graph_path.exists():
            self.knowledge_graph = KnowledgeGraph.load(str(graph_path))

        self.vector_store.create_collection(self.novel_id)

    def save(self) -> None:
        """保存所有层"""
        self.knowledge_graph.save(str(self.workspace / "graph.pkl"))
        # SQLite 自动持久化
        # Chroma 自动持久化

    # === 全局层（始终在内存中） ===

    def get_global_context(self) -> dict[str, Any]:
        """获取全局层上下文（~1500 tokens）

        Returns:
            {
                "main_plot_progress": str,
                "character_core_info": list[dict],
                "power_system": PowerSystem | None,
                "unresolved_foreshadowing": list[Foreshadowing],
                "terms": dict[str, str]
            }
        """
        ...

    # === 卷层（每卷加载） ===

    def get_volume_context(self, volume_number: int) -> dict[str, Any]:
        """获取卷层上下文（~3000 tokens）

        Returns:
            {
                "volume_outline": VolumeOutline,
                "volume_characters": list[CharacterProfile],
                "previous_volume_summary": str | None,
                "volume_events": list[str]
            }
        """
        ...

    def create_volume_snapshot(
        self,
        volume_number: int,
        novel: Novel
    ) -> VolumeSnapshot:
        """创建卷快照（卷结束时调用）"""
        ...

    # === 章层（每章加载） ===

    def get_chapter_context(self, chapter_number: int) -> dict[str, Any]:
        """获取章层上下文（~8000 tokens）

        Returns:
            {
                "recent_chapters_text": str,      # 最近 3 章完整正文
                "recent_summaries": list[str],    # 最近 10 章摘要
                "relevant_history": list[dict],   # 向量检索结果
                "current_chapter_outline": ChapterOutline
            }
        """
        ...

    # === 三层数据更新 ===

    def add_chapter(self, chapter: Chapter) -> None:
        """新章生成后，同步更新三层"""
        # 1. 提取事实
        facts = self._extract_facts(chapter)

        # 2. 更新结构化数据库
        for fact in facts:
            if fact.type == "character_state":
                self.structured_db.insert_character_state(fact)
            elif fact.type == "time":
                self.structured_db.insert_timeline(fact)
            # ...

        # 3. 更新知识图谱
        for fact in facts:
            if fact.type == "relationship":
                self._update_relationship_graph(fact)

        # 4. 更新向量存储
        for fact in facts:
            self.vector_store.add_fact(fact)

        # 5. 生成摘要
        summary = self._generate_summary(chapter)
        self.structured_db.insert_summary(summary)

        # 6. 提取闲笔（V2 后置伏笔）
        details = self._extract_details(chapter)
        for detail in details:
            self.vector_store.add_detail(detail)

    # === 一致性检查（三层并行查询） ===

    def check_consistency(
        self,
        chapter: Chapter,
        facts: list[Fact]
    ) -> tuple[bool, list[dict], float]:
        """三层混合一致性检查

        Returns:
            (passed, contradictions, confidence)
        """
        contradictions = []

        # 第一层: SQLite 精确查询
        structured_results = self._check_structured_layer(facts)
        contradictions.extend(structured_results)

        # 第二层: NetworkX 图查询
        graph_results = self._check_graph_layer(facts)
        contradictions.extend(graph_results)

        # 第三层: Chroma 向量检索
        vector_results = self._check_vector_layer(chapter, facts)
        contradictions.extend(vector_results)

        # 计算置信度（三层一致时高）
        confidence = self._calculate_confidence(
            structured_results,
            graph_results,
            vector_results
        )

        passed = len(contradictions) == 0
        return passed, contradictions, confidence

    def _check_structured_layer(self, facts: list[Fact]) -> list[dict]:
        """第一层检查: SQLite"""
        ...

    def _check_graph_layer(self, facts: list[Fact]) -> list[dict]:
        """第二层检查: NetworkX"""
        ...

    def _check_vector_layer(
        self,
        chapter: Chapter,
        facts: list[Fact]
    ) -> list[dict]:
        """第三层检查: Chroma"""
        ...

    # === 辅助方法 ===

    def _extract_facts(self, chapter: Chapter) -> list[Fact]:
        """从章节提取关键事实（调用 LLM）"""
        ...

    def _extract_details(self, chapter: Chapter) -> list[DetailEntry]:
        """提取潜在可利用的闲笔（V2）"""
        ...

    def _generate_summary(self, chapter: Chapter) -> ChapterSummary:
        """生成章节摘要"""
        ...

    def _update_relationship_graph(self, fact: Fact) -> None:
        """根据事实更新关系图"""
        ...

    def _calculate_confidence(self, *layer_results) -> float:
        """计算检测置信度"""
        ...
```

### 6.2 三层记忆加载策略

**全局层（始终加载）**:
- 数据源: Novel 对象的核心字段 + SQLite terms 表
- 加载时机: Pipeline 初始化时一次性加载
- 更新时机: 用户修改大纲/角色/世界观时

**卷层（换卷时切换）**:
- 数据源: VolumeSnapshot + 本卷相关角色
- 加载时机: 开始新卷的第一章时
- 更新时机: 卷结束时生成快照

**章层（每章滚动更新）**:
- 数据源: SQLite + Chroma
- 加载时机: 生成新章前
- 更新时机: 新章生成后

**内存占用估算**:
```
全局层:  ~1500 tokens  (~6KB)
卷层:    ~3000 tokens  (~12KB)
章层:    ~8000 tokens  (~32KB)
---------------------------------
总计:    ~12500 tokens (~50KB)
```

---

## 7. LangGraph 图定义

### 7.1 NovelState 定义

```python
# src/novel/agents/state.py
from typing import Annotated, TypedDict
import operator

class Decision(TypedDict, total=False):
    agent: str
    step: str
    decision: str
    reason: str
    data: dict | None
    timestamp: str

class NovelState(TypedDict, total=False):
    # === 输入 ===
    genre: str                          # 题材
    theme: str                          # 主题
    target_words: int                   # 目标字数
    style_category: str                 # 风格大类
    style_subcategory: str              # 风格子类
    custom_style_reference: str | None  # 自定义风格参考
    template: str                       # 大纲模板

    # === 导入模式 ===
    import_mode: bool                   # 是否导入已有稿件
    import_file_path: str | None

    # === 项目状态 ===
    novel_id: str
    workspace: str
    config: dict

    # === 创作流程控制 ===
    current_chapter: int                # 当前进度
    total_chapters: int
    review_interval: int                # 审核间隔（每 N 章暂停）
    silent_mode: bool                   # 静默模式（仅质量不达标时暂停）
    auto_approve_threshold: float       # 自动通过阈值

    # === 核心数据 ===
    outline: dict | None                # Outline.model_dump()
    world_setting: dict | None          # WorldSetting.model_dump()
    characters: list[dict]              # list[CharacterProfile.model_dump()]
    chapters: list[dict]                # list[Chapter.model_dump()]
    volume_snapshots: list[dict]        # list[VolumeSnapshot.model_dump()]

    # === 当前章节工作区 ===
    current_chapter_outline: dict | None
    current_scenes: list[dict] | None
    current_chapter_mood: str | None
    current_rhythm_instruction: str | None
    current_chapter_text: str | None
    current_chapter_quality: dict | None

    # === 质量控制 ===
    retry_counts: dict[int, int]        # {chapter_number: retry_count}
    max_retries: int                    # 最大重试次数

    # === 决策日志（累积） ===
    decisions: Annotated[list[Decision], operator.add]

    # === 错误日志（累积） ===
    errors: Annotated[list[dict], operator.add]

    # === 断点续传 ===
    completed_nodes: Annotated[list[str], operator.add]
    resume: bool
```

### 7.2 StateGraph 节点和边

```python
# src/novel/agents/graph.py
from langgraph.graph import StateGraph, END
from src.novel.agents.state import NovelState

def create_novel_graph(config: dict) -> StateGraph:
    """构建小说创作 LangGraph"""

    graph = StateGraph(NovelState)

    # === 节点定义 ===

    # 1. 初始化节点
    graph.add_node("initialize", initialize_node)

    # 2. 导入模式分支
    graph.add_node("import_draft", import_draft_node)

    # 3. 设定构建节点（并行）
    graph.add_node("build_world", world_builder_node)
    graph.add_node("design_characters", character_designer_node)

    # 4. 章节生成循环
    graph.add_node("plan_chapter", plot_planner_node)
    graph.add_node("write_chapter", writer_node)
    graph.add_node("check_consistency", consistency_checker_node)
    graph.add_node("check_style", style_keeper_node)
    graph.add_node("review_quality", quality_reviewer_node)

    # 5. 人工审核节点
    graph.add_node("human_review", human_review_node)

    # 6. 卷快照节点
    graph.add_node("create_volume_snapshot", volume_snapshot_node)

    # 7. 完成节点
    graph.add_node("finalize", finalize_node)

    # === 边定义 ===

    # 入口
    graph.set_entry_point("initialize")

    # 初始化 → 导入分支
    graph.add_conditional_edges(
        "initialize",
        lambda state: "import_draft" if state.get("import_mode") else "generate_outline"
    )

    # 导入 → 设定构建
    graph.add_edge("import_draft", "build_world")

    # 生成大纲 → 设定构建（并行）
    graph.add_node("generate_outline", novel_director_node)
    graph.add_edge("generate_outline", "build_world")
    graph.add_edge("generate_outline", "design_characters")

    # 设定构建完成 → 章节循环
    graph.add_edge("build_world", "plan_chapter")
    graph.add_edge("design_characters", "plan_chapter")

    # 章节生成流程
    graph.add_edge("plan_chapter", "write_chapter")
    graph.add_edge("write_chapter", "check_consistency")

    # 一致性检查分支
    graph.add_conditional_edges(
        "check_consistency",
        lambda state: "check_style" if state.get("consistency_passed") else "write_chapter",
        {
            "check_style": "check_style",
            "write_chapter": "write_chapter"  # 重写
        }
    )

    graph.add_edge("check_style", "review_quality")

    # 质量评审分支
    graph.add_conditional_edges(
        "review_quality",
        decide_after_quality_review,
        {
            "continue": "save_chapter",
            "rewrite": "write_chapter",
            "human_review": "human_review"
        }
    )

    # 保存章节
    graph.add_node("save_chapter", save_chapter_node)

    # 章节完成 → 下一章或结束
    graph.add_conditional_edges(
        "save_chapter",
        decide_next_step,
        {
            "next_chapter": "plan_chapter",
            "volume_snapshot": "create_volume_snapshot",
            "human_review": "human_review",
            "finalize": "finalize"
        }
    )

    # 卷快照 → 继续
    graph.add_edge("create_volume_snapshot", "plan_chapter")

    # 人工审核 → 继续或修改
    graph.add_conditional_edges(
        "human_review",
        lambda state: "plan_chapter" if state.get("human_approved") else END
    )

    # 完成 → END
    graph.add_edge("finalize", END)

    return graph.compile()


def decide_after_quality_review(state: NovelState) -> str:
    """质量评审后决策"""
    quality = state.get("current_chapter_quality", {})
    chapter_num = state.get("current_chapter", 0)
    retry_count = state.get("retry_counts", {}).get(chapter_num, 0)
    max_retries = state.get("max_retries", 2)

    # 规则不通过 → 重写
    if not quality.get("rule_check_passed"):
        if retry_count < max_retries:
            return "rewrite"
        else:
            return "human_review"  # 重试次数用尽

    # 评分过低 → 重写
    if quality.get("overall_score", 0) < 4.0:
        if retry_count < max_retries:
            return "rewrite"
        else:
            return "human_review"

    # 通过
    return "continue"


def decide_next_step(state: NovelState) -> str:
    """章节保存后决策下一步"""
    current = state.get("current_chapter", 0)
    total = state.get("total_chapters", 0)
    review_interval = state.get("review_interval", 5)
    silent_mode = state.get("silent_mode", False)

    # 检查是否完成
    if current >= total:
        return "finalize"

    # 检查是否需要卷快照（每 10 章）
    if current % 10 == 0 and current > 0:
        return "volume_snapshot"

    # 检查是否需要人工审核
    if not silent_mode and current % review_interval == 0:
        return "human_review"

    # 继续下一章
    return "next_chapter"
```

### 7.3 断点续传 Wrapper

```python
# src/novel/agents/graph.py

def _make_skip_or_run(node_name: str, node_fn):
    """包装节点函数，支持断点续传"""

    def wrapped(state: NovelState, config=None):
        completed = state.get("completed_nodes", [])

        # 已完成则跳过
        if node_name in completed:
            log.info(f"[Resume] 跳过已完成节点: {node_name}")
            return {
                "decisions": [make_decision(node_name, "skip", "断点续传跳过", "已完成")],
                "completed_nodes": [node_name]
            }

        # 执行节点
        result = node_fn(state)
        result["completed_nodes"] = [node_name]

        # 保存中间状态
        if config and "configurable" in config:
            pipeline = config["configurable"].get("pipeline")
            if pipeline:
                merged = {**state, **result}
                pipeline._save_state(merged)

        return result

    return wrapped
```

---

## 8. 配置项设计

### 8.1 config.yaml 扩展

```yaml
# config.yaml

# ... 现有视频配置 ...

# === 小说模块配置 ===
novel:
  # 默认配置
  default_genre: "都市"
  default_target_words: 100000
  default_template: "cyclic_upgrade"  # cyclic_upgrade | multi_thread | four_act | custom

  # 风格
  style:
    default_category: "网文"          # 武侠 | 网文 | 文学 | 轻小说
    default_subcategory: "爽文"       # 子类风格

    # 风格约束阈值（用于 StyleKeeper 检查）
    constraints:
      网文:
        avg_sentence_length: [10, 20]
        dialogue_ratio: [0.4, 0.6]
        exclamation_ratio: [0.1, 0.2]
      武侠:
        avg_sentence_length: [20, 40]
        dialogue_ratio: [0.2, 0.3]
        classical_word_ratio: [0.15, 0.25]
      轻小说:
        avg_sentence_length: [8, 18]
        dialogue_ratio: [0.5, 0.7]
        first_person_ratio: [0.8, 1.0]

  # LLM 模型分工
  llm:
    outline_generation: "gpt-4o-mini"
    character_design: "gpt-4o-mini"
    scene_writing: "gpt-4o-mini"
    quality_review: "gpt-4o-mini"
    consistency_check: "gemini-1.5-pro"  # 长上下文
    style_rewrite: "deepseek-chat"       # 省钱

  # 生成策略
  generation:
    scene_per_chapter: 4                 # 每章场景数
    words_per_scene: [500, 1500]         # 场景字数范围
    words_per_chapter: [2000, 5000]      # 章节字数范围
    use_parallel_scenes: false           # 是否并行生成场景（V2）

  # 质量控制
  quality:
    max_retries: 2                       # 最大重写次数
    auto_approve_threshold: 6.0          # 自动通过阈值（0-10）
    enable_rule_check: true              # 启用规则硬指标检查
    enable_pairwise_compare: true        # 启用对比式评估
    enable_llm_scoring: true             # 启用 LLM 打分

    # AI 味短语黑名单（检测阈值：单章出现次数）
    ai_flavor_blacklist:
      "内心翻涌": 2
      "莫名的力量": 2
      "不由得": 3
      "竟然": 5
      "眼神一凛": 2
      "嘴角勾起一抹": 2

  # 一致性检查
  consistency:
    enable_structured_db: true           # 启用 SQLite 检查
    enable_knowledge_graph: true         # 启用 NetworkX 检查
    enable_vector_search: true           # 启用 Chroma 检查
    contradiction_threshold: 0.7         # 矛盾判定阈值

  # 记忆管理
  memory:
    recent_chapters_full: 3              # 保留最近 N 章完整正文
    recent_summaries: 10                 # 保留最近 N 章摘要
    vector_search_results: 5             # 向量检索返回数量
    enable_volume_snapshot: true         # 启用卷快照
    snapshot_interval: 10                # 每 N 章生成卷快照

  # 人工介入
  human_in_loop:
    review_interval: 5                   # 每 N 章暂停审核
    silent_mode: false                   # 静默模式（仅质量不达标时暂停）
    pause_on_contradiction: true         # 发现矛盾时暂停

  # 伏笔管理（V2）
  foreshadowing:
    enable_planned: true                 # 启用正向伏笔
    enable_retroactive: false            # 启用后置伏笔（V2）
    detail_extraction_threshold: 0.6     # 闲笔提取阈值

  # 导入已有稿件
  import:
    auto_split_chapters: true            # 自动章节分割
    chapter_markers: ["第", "章"]        # 章节标记关键词
    extract_characters: true             # 自动提取角色
    extract_world_setting: true          # 自动提取世界观
```

---

## 9. CLI 命令设计

### 9.1 Click 命令接口

```python
# main.py 扩展

import click
from pathlib import Path

@click.group()
def cli():
    """AI 小说推文自动化"""
    pass

# === 小说创作命令 ===

@cli.command("write-novel")
@click.option("--genre", required=True, help="题材: 武侠/都市/玄幻/科幻/言情/悬疑")
@click.option("--theme", required=True, help="主题（如'复仇与救赎'）")
@click.option("--words", type=int, default=100000, help="目标字数")
@click.option("--style", default="网文-爽文", help="风格: 武侠/网文/文学/轻小说 + 子类")
@click.option("--template", default="cyclic_upgrade", help="大纲模板: cyclic_upgrade/multi_thread/four_act/custom")
@click.option("--config", type=click.Path(exists=True), help="自定义配置文件")
@click.option("--workspace", type=click.Path(), help="工作目录")
@click.option("--custom-style-ref", type=click.Path(exists=True), help="自定义风格参考文本文件")
@click.option("--silent", is_flag=True, help="静默模式（仅质量不达标时暂停）")
@click.option("--review-interval", type=int, default=5, help="审核间隔（每 N 章暂停）")
def write_novel(genre, theme, words, style, template, config, workspace, custom_style_ref, silent, review_interval):
    """创作新小说"""
    from src.novel.pipeline import NovelPipeline

    # 解析风格
    style_parts = style.split("-")
    style_category = style_parts[0]
    style_subcategory = style_parts[1] if len(style_parts) > 1 else style_parts[0]

    # 加载自定义风格参考
    custom_ref = None
    if custom_style_ref:
        custom_ref = Path(custom_style_ref).read_text(encoding="utf-8")

    # 创建 Pipeline
    pipeline = NovelPipeline(
        genre=genre,
        theme=theme,
        target_words=words,
        style_category=style_category,
        style_subcategory=style_subcategory,
        custom_style_reference=custom_ref,
        template=template,
        config_path=config,
        workspace=workspace,
        silent_mode=silent,
        review_interval=review_interval
    )

    # 执行创作
    result = pipeline.run()
    click.echo(f"✓ 小说创作完成: {result['novel_path']}")


@cli.command("resume-novel")
@click.argument("novel_id")
@click.option("--workspace", type=click.Path(), help="工作目录")
def resume_novel(novel_id, workspace):
    """断点续写小说"""
    from src.novel.pipeline import NovelPipeline

    pipeline = NovelPipeline.from_checkpoint(
        novel_id=novel_id,
        workspace=workspace
    )

    result = pipeline.run()
    click.echo(f"✓ 续写完成: {result['novel_path']}")


@cli.command("import-novel")
@click.argument("draft_file", type=click.Path(exists=True))
@click.option("--genre", required=True, help="题材")
@click.option("--mode", type=click.Choice(["continue", "rewrite", "expand"]), default="continue", help="续写/改写/扩写")
@click.option("--style", default="网文-爽文", help="风格")
@click.option("--target-words", type=int, help="目标总字数（续写模式）")
@click.option("--config", type=click.Path(exists=True), help="自定义配置文件")
@click.option("--workspace", type=click.Path(), help="工作目录")
def import_novel(draft_file, genre, mode, style, target_words, config, workspace):
    """导入已有稿件"""
    from src.novel.pipeline import NovelPipeline

    style_parts = style.split("-")
    style_category = style_parts[0]
    style_subcategory = style_parts[1] if len(style_parts) > 1 else style_parts[0]

    pipeline = NovelPipeline(
        genre=genre,
        style_category=style_category,
        style_subcategory=style_subcategory,
        import_mode=True,
        import_file_path=draft_file,
        import_operation=mode,
        target_words=target_words,
        config_path=config,
        workspace=workspace
    )

    result = pipeline.run()
    click.echo(f"✓ 导入并{'续写' if mode == 'continue' else mode}完成: {result['novel_path']}")


@cli.command("novel-status")
@click.argument("novel_id")
@click.option("--workspace", type=click.Path(), help="工作目录")
def novel_status(novel_id, workspace):
    """查看小说创作进度"""
    from src.novel.storage.file_manager import FileManager

    fm = FileManager(workspace or "workspace")
    status = fm.load_status(novel_id)

    click.echo(f"项目: {status['title']}")
    click.echo(f"进度: {status['current_chapter']}/{status['total_chapters']} 章")
    click.echo(f"状态: {status['status']}")
    click.echo(f"字数: {status['total_words']}/{status['target_words']}")


# === 现有视频命令保持不变 ===
# ...
```

---

## 10. 错误处理与断点续写

### 10.1 Checkpoint 方案

```python
# src/novel/pipeline.py

class NovelPipeline:
    """小说创作流水线"""

    def __init__(
        self,
        genre: str,
        theme: str | None = None,
        target_words: int = 100000,
        style_category: str = "网文",
        style_subcategory: str = "爽文",
        custom_style_reference: str | None = None,
        template: str = "cyclic_upgrade",
        import_mode: bool = False,
        import_file_path: str | None = None,
        import_operation: str = "continue",
        config_path: str | None = None,
        workspace: str | None = None,
        silent_mode: bool = False,
        review_interval: int = 5,
        novel_id: str | None = None
    ):
        self.config = self._load_config(config_path)
        self.workspace_root = Path(workspace or self.config["project"]["default_workspace"])

        # 生成或加载 novel_id
        self.novel_id = novel_id or str(uuid.uuid4())
        self.workspace = self.workspace_root / "novels" / self.novel_id
        self.workspace.mkdir(parents=True, exist_ok=True)

        # 初始化组件
        self.llm_client = self._init_llm()
        self.memory = NovelMemory(self.novel_id, str(self.workspace_root))
        self.graph = create_novel_graph(self.config)

        # 初始化状态
        self.state: NovelState = {
            "novel_id": self.novel_id,
            "workspace": str(self.workspace),
            "config": self.config,
            "genre": genre,
            "theme": theme,
            "target_words": target_words,
            "style_category": style_category,
            "style_subcategory": style_subcategory,
            "custom_style_reference": custom_style_reference,
            "template": template,
            "import_mode": import_mode,
            "import_file_path": import_file_path,
            "current_chapter": 0,
            "total_chapters": 0,
            "review_interval": review_interval,
            "silent_mode": silent_mode,
            "auto_approve_threshold": self.config["novel"]["quality"]["auto_approve_threshold"],
            "max_retries": self.config["novel"]["quality"]["max_retries"],
            "characters": [],
            "chapters": [],
            "volume_snapshots": [],
            "retry_counts": {},
            "decisions": [],
            "errors": [],
            "completed_nodes": [],
            "resume": False
        }

        self.checkpoint_file = self.workspace / "checkpoint.json"

    @classmethod
    def from_checkpoint(cls, novel_id: str, workspace: str | None = None) -> "NovelPipeline":
        """从断点恢复"""
        workspace_root = Path(workspace or "workspace")
        checkpoint_file = workspace_root / "novels" / novel_id / "checkpoint.json"

        if not checkpoint_file.exists():
            raise FileNotFoundError(f"未找到断点文件: {checkpoint_file}")

        # 加载 checkpoint
        with open(checkpoint_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        # 创建 pipeline 实例
        pipeline = cls(
            genre=state["genre"],
            theme=state.get("theme"),
            target_words=state["target_words"],
            style_category=state["style_category"],
            style_subcategory=state["style_subcategory"],
            custom_style_reference=state.get("custom_style_reference"),
            template=state.get("template", "cyclic_upgrade"),
            workspace=workspace,
            silent_mode=state.get("silent_mode", False),
            review_interval=state.get("review_interval", 5),
            novel_id=novel_id
        )

        # 恢复状态
        pipeline.state = state
        pipeline.state["resume"] = True

        log.info(f"从断点恢复: 当前进度 {state['current_chapter']}/{state['total_chapters']} 章")
        return pipeline

    def run(self) -> dict[str, Any]:
        """执行创作流程"""
        try:
            # 执行 LangGraph
            final_state = self.graph.invoke(
                self.state,
                config={"configurable": {"pipeline": self}}
            )

            # 保存最终小说
            novel_path = self._save_novel(final_state)

            return {
                "novel_id": self.novel_id,
                "novel_path": str(novel_path),
                "total_chapters": final_state["total_chapters"],
                "total_words": self._calculate_total_words(final_state),
                "status": "completed"
            }

        except KeyboardInterrupt:
            log.warning("用户中断，保存断点...")
            self._save_checkpoint(self.state)
            raise

        except Exception as e:
            log.error(f"创作流程出错: {e}")
            self._save_checkpoint(self.state)
            raise

    def _save_checkpoint(self, state: NovelState) -> None:
        """保存断点"""
        with open(self.checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        log.info(f"断点已保存: {self.checkpoint_file}")

    def _save_state(self, state: NovelState) -> None:
        """保存中间状态（每个节点完成后调用）"""
        self._save_checkpoint(state)

    def _save_novel(self, state: NovelState) -> Path:
        """保存最终小说文件"""
        novel_path = self.workspace / f"{state['novel_id']}.txt"

        # 拼接所有章节
        chapters = state.get("chapters", [])
        full_text = "\n\n".join(
            f"第{ch['chapter_number']}章 {ch['title']}\n\n{ch['full_text']}"
            for ch in chapters
        )

        novel_path.write_text(full_text, encoding="utf-8")

        # 保存 JSON
        novel_json = self.workspace / "novel.json"
        with open(novel_json, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        return novel_path

    def _calculate_total_words(self, state: NovelState) -> int:
        """计算总字数"""
        return sum(ch["word_count"] for ch in state.get("chapters", []))

    def _load_config(self, config_path: str | None) -> dict:
        """加载配置"""
        from src.config_manager import load_config
        return load_config(config_path)

    def _init_llm(self) -> Any:
        """初始化 LLM 客户端"""
        from src.llm.llm_client import get_llm_client
        return get_llm_client(self.config)
```

### 10.2 错误处理策略

```python
# 各 Agent 节点内的错误处理模式

def writer_node(state: NovelState) -> dict[str, Any]:
    """Writer Agent 节点"""
    try:
        writer = Writer(llm_client)

        # 生成场景
        scenes_text = []
        for scene in state["current_scenes"]:
            try:
                text = writer.generate_scene(
                    scene,
                    context=...,
                    style=state["style_category"],
                    rhythm_instruction=state["current_rhythm_instruction"]
                )
                scenes_text.append(text)

            except Exception as e:
                log.error(f"场景生成失败: {e}")
                # 记录错误但继续（使用空文本）
                scenes_text.append(f"[场景生成失败: {e}]")
                state["errors"].append({
                    "node": "writer",
                    "scene": scene["scene_id"],
                    "error": str(e)
                })

        # 拼接章节
        full_text = writer.polish_transitions(scenes_text)

        return {
            "current_chapter_text": full_text,
            "decisions": [make_decision("writer", "generate", "章节生成完成", f"{len(full_text)} 字")]
        }

    except Exception as e:
        log.error(f"Writer 节点失败: {e}")
        return {
            "errors": [{
                "node": "writer",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }],
            "decisions": [make_decision("writer", "error", f"节点执行失败: {e}", "")]
        }
```

---

**设计文档完成。**

关键设计亮点：
1. **物理隔离**: `src/novel/` 独立目录，不污染视频模块
2. **分层架构**: Pipeline → Agent → Tool → Service → Storage，职责清晰
3. **三层混合记忆**: SQLite + NetworkX + Chroma，覆盖所有一致性检查场景
4. **Pydantic 数据模型**: 类型安全、自动验证、易序列化
5. **LangGraph 状态机**: 复用现有架构，支持断点续传
6. **渐进式开发**: MVP 核心功能先行，V2/V3 扩展点明确

下一步可直接进入 tasks.md 生成。
