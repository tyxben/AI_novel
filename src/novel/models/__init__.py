"""小说模块数据模型 - 统一导出"""

from src.novel.models.chapter import Chapter, MoodTag, Scene
from src.novel.models.character import (
    Appearance,
    CharacterArc,
    CharacterProfile,
    CharacterSnapshot,
    Personality,
    Relationship,
    RelationshipEvent,
    TurningPoint,
)
from src.novel.models.feedback import FeedbackAnalysis, FeedbackEntry, FeedbackType
from src.novel.models.health import HealthMetrics
from src.novel.models.foreshadowing import DetailEntry, Foreshadowing
from src.novel.models.memory import (
    ChapterSummary,
    ContextWindow,
    Fact,
    VolumeSnapshot,
)
from src.novel.models.novel import (
    Act,
    ChapterOutline,
    Novel,
    Outline,
    OutlineTemplate,
    Volume,
    VolumeOutline,
)
from src.novel.models.quality import (
    PairwiseResult,
    QualityReport,
    RuleCheckResult,
    StyleMetrics,
)
from src.novel.models.refinement import (
    ProofreadingIssue,
    ProofreadingIssueType,
    SettingConflict,
    SettingImpact,
)
from src.novel.models.story_unit import ArcBrief, StoryUnit
from src.novel.models.debt import ChapterDebt, DebtContext, DebtExtractionResult
from src.novel.models.entity import Entity, EntityMention, EntityType
from src.novel.models.validation import BriefFulfillmentReport, BriefItemResult
from src.novel.models.world import PowerLevel, PowerSystem, WorldSetting

# 解析 Novel 和 Volume 中的前向引用（Chapter, CharacterProfile, WorldSetting, VolumeSnapshot）
Novel.model_rebuild()
Volume.model_rebuild()

__all__ = [
    # novel.py
    "Novel",
    "Outline",
    "OutlineTemplate",
    "Act",
    "VolumeOutline",
    "ChapterOutline",
    "Volume",
    # chapter.py
    "Chapter",
    "Scene",
    "MoodTag",
    # character.py
    "CharacterProfile",
    "Appearance",
    "Personality",
    "Relationship",
    "RelationshipEvent",
    "CharacterArc",
    "TurningPoint",
    "CharacterSnapshot",
    # world.py
    "WorldSetting",
    "PowerSystem",
    "PowerLevel",
    # memory.py
    "Fact",
    "ChapterSummary",
    "VolumeSnapshot",
    "ContextWindow",
    # quality.py
    "StyleMetrics",
    "RuleCheckResult",
    "PairwiseResult",
    "QualityReport",
    # foreshadowing.py
    "Foreshadowing",
    "DetailEntry",
    # health.py
    "HealthMetrics",
    # feedback.py
    "FeedbackType",
    "FeedbackEntry",
    "FeedbackAnalysis",
    # refinement.py
    "ProofreadingIssue",
    "ProofreadingIssueType",
    "SettingConflict",
    "SettingImpact",
    # story_unit.py
    "StoryUnit",
    "ArcBrief",
    # debt.py
    "ChapterDebt",
    "DebtExtractionResult",
    "DebtContext",
    # entity.py
    "Entity",
    "EntityMention",
    "EntityType",
    # validation.py
    "BriefItemResult",
    "BriefFulfillmentReport",
]
