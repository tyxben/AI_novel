"""小说模块配置

使用 Pydantic 模型定义配置结构，支持从 YAML 加载。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class StyleConfig(BaseModel):
    """风格配置"""

    default_category: str = Field("网文", description="默认风格大类")
    default_subcategory: str = Field("爽文", description="默认风格子类")
    constraints: dict[str, dict[str, list[float]]] = Field(
        default_factory=lambda: {
            "网文": {
                "avg_sentence_length": [10, 20],
                "dialogue_ratio": [0.4, 0.6],
                "exclamation_ratio": [0.1, 0.2],
            },
            "武侠": {
                "avg_sentence_length": [20, 40],
                "dialogue_ratio": [0.2, 0.3],
                "classical_word_ratio": [0.15, 0.25],
            },
            "轻小说": {
                "avg_sentence_length": [8, 18],
                "dialogue_ratio": [0.5, 0.7],
                "first_person_ratio": [0.8, 1.0],
            },
        },
        description="各风格的量化约束阈值",
    )


class LLMConfig(BaseModel):
    """LLM 模型分工配置"""

    outline_generation: str = Field("deepseek-chat", description="大纲生成模型")
    character_design: str = Field("deepseek-chat", description="角色设计模型")
    scene_writing: str = Field("deepseek-chat", description="场景写作模型")
    quality_review: str = Field("deepseek-chat", description="质量评审模型")
    consistency_check: str = Field(
        "deepseek-chat", description="一致性检查模型"
    )
    style_rewrite: str = Field("deepseek-chat", description="风格改写模型")


class GenerationConfig(BaseModel):
    """生成策略配置"""

    scene_per_chapter: int = Field(3, ge=1, le=10, description="每章场景数")
    words_per_scene: list[int] = Field(
        default_factory=lambda: [400, 800], description="场景字数范围 [min, max]"
    )
    words_per_chapter: list[int] = Field(
        default_factory=lambda: [2000, 3000], description="章节字数范围 [min, max]"
    )
    use_parallel_scenes: bool = Field(False, description="是否并行生成场景")


class QualityConfig(BaseModel):
    """质量控制配置"""

    max_retries: int = Field(2, ge=0, le=10, description="最大重写次数")
    auto_approve_threshold: float = Field(
        6.0, ge=0.0, le=10.0, description="自动通过阈值"
    )
    enable_rule_check: bool = Field(True, description="启用规则硬指标检查")
    enable_pairwise_compare: bool = Field(True, description="启用对比式评估")
    enable_llm_scoring: bool = Field(True, description="启用 LLM 打分")
    ai_flavor_hard_ban: list[str] = Field(
        default_factory=lambda: [
            "内心翻涌",       # 抽象抒情，永远不具象
            "莫名的力量",     # 写不清楚就用这个糊弄
            "嘴角勾起一抹",   # 公式化网文表情
            "深邃的眸子",     # 同上
            "不可名状的",     # 廉价玄秘感
        ],
        description=(
            "硬禁短语：无论场景都属于空洞抒情/抽象偷懒。出现即判失败。"
            "仅放真正没有合适使用场景的短语。"
        ),
    )

    ai_flavor_watchlist: dict[str, int] = Field(
        default_factory=lambda: {
            # 短语 → 单章软上限。超过即提示"可能滥用"，由 LLM critic 判断是否合理
            "瞳孔骤缩": 2,
            "黑眸": 2,
            "目光一凝": 2,
            "眼神一凛": 2,
            "不由得": 3,
            "竟然": 5,
        },
        description=(
            "软观察名单：这些短语在合适场景里能用，但单章超出阈值"
            "就交给 LLM critic 按场景判断是否滥用。Verifier 不直接据此判失败。"
        ),
    )

    # Phase 2-β 合并 Reviewer 后，旧字段 ``ai_flavor_blacklist`` 彻底移除。
    # 新代码统一用 ``ai_flavor_hard_ban``（verifier）+ ``ai_flavor_watchlist``
    # （Reviewer / critic 软观察）。StyleProfile 接管按项目学习的口头禅检查。


class ConsistencyConfig(BaseModel):
    """一致性检查配置"""

    enable_structured_db: bool = Field(True, description="启用 SQLite 检查")
    enable_knowledge_graph: bool = Field(True, description="启用 NetworkX 检查")
    enable_vector_search: bool = Field(True, description="启用 Chroma 检查")
    contradiction_threshold: float = Field(
        0.7, ge=0.0, le=1.0, description="矛盾判定阈值"
    )


class MemoryConfig(BaseModel):
    """记忆管理配置"""

    recent_chapters_full: int = Field(
        3, ge=1, le=20, description="保留最近 N 章完整正文"
    )
    recent_summaries: int = Field(
        10, ge=1, le=50, description="保留最近 N 章摘要"
    )
    vector_search_results: int = Field(
        5, ge=1, le=20, description="向量检索返回数量"
    )
    enable_volume_snapshot: bool = Field(True, description="启用卷快照")
    snapshot_interval: int = Field(10, ge=1, le=50, description="每 N 章生成卷快照")


class HumanInLoopConfig(BaseModel):
    """人工介入配置"""

    review_interval: int = Field(5, ge=1, le=50, description="每 N 章暂停审核")
    silent_mode: bool = Field(
        False, description="静默模式（仅质量不达标时暂停）"
    )
    pause_on_contradiction: bool = Field(True, description="发现矛盾时暂停")


class ForeshadowingConfig(BaseModel):
    """伏笔管理配置"""

    enable_planned: bool = Field(True, description="启用正向伏笔")
    enable_retroactive: bool = Field(False, description="启用后置伏笔（V2）")
    detail_extraction_threshold: float = Field(
        0.6, ge=0.0, le=1.0, description="闲笔提取阈值"
    )


class FeedbackConfig(BaseModel):
    """反馈处理配置"""

    max_propagation_chapters: int = Field(
        10, ge=1, le=40, description="最大传播章节数"
    )
    propagation_mode: Literal["full_rewrite", "minimal_adjust"] = Field(
        "minimal_adjust", description="传播模式"
    )
    keep_revisions: int = Field(
        3, ge=1, le=10, description="保留的历史版本数"
    )


class ImportConfig(BaseModel):
    """导入配置"""

    auto_split_chapters: bool = Field(True, description="自动章节分割")
    chapter_markers: list[str] = Field(
        default_factory=lambda: ["第", "章"], description="章节标记关键词"
    )
    extract_characters: bool = Field(True, description="自动提取角色")
    extract_world_setting: bool = Field(True, description="自动提取世界观")


class NovelConfig(BaseModel):
    """小说模块完整配置"""

    # 默认配置
    default_genre: str = Field("都市", description="默认题材")
    default_target_words: int = Field(
        100000, gt=0, description="默认目标字数"
    )
    default_template: str = Field(
        "cyclic_upgrade", description="默认大纲模板"
    )

    # 子配置
    style: StyleConfig = Field(default_factory=StyleConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    consistency: ConsistencyConfig = Field(default_factory=ConsistencyConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    human_in_loop: HumanInLoopConfig = Field(default_factory=HumanInLoopConfig)
    foreshadowing: ForeshadowingConfig = Field(
        default_factory=ForeshadowingConfig
    )
    feedback: FeedbackConfig = Field(default_factory=FeedbackConfig)
    import_settings: ImportConfig = Field(
        default_factory=ImportConfig, alias="import"
    )

    model_config = {"populate_by_name": True}


def load_novel_config(
    config_path: Path | str | None = None,
    config_dict: dict[str, Any] | None = None,
) -> NovelConfig:
    """加载小说模块配置。

    优先使用 config_dict，其次从 YAML 文件加载。
    如果都未提供，返回全部默认值。

    Args:
        config_path: YAML 配置文件路径
        config_dict: 已解析的配置字典（novel 段）

    Returns:
        NovelConfig 实例
    """
    if config_dict is not None:
        return NovelConfig.model_validate(config_dict)

    if config_path is not None:
        import yaml

        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")
        with open(path, encoding="utf-8") as f:
            full_cfg = yaml.safe_load(f) or {}
        novel_section = full_cfg.get("novel", {})
        return NovelConfig.model_validate(novel_section)

    return NovelConfig()
