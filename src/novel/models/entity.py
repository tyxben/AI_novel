"""实体模型 - 实体分类索引（知识图谱 P0）"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class EntityType:
    """实体类型常量（适配网文场景）"""

    CHARACTER = "character"       # 人名
    LOCATION = "location"         # 地名
    FACTION = "faction"           # 势力/宗门/组织
    SKILL = "skill"               # 功法/技能/绝招
    ARTIFACT = "artifact"         # 器物/宝物/法宝
    RACE = "race"                 # 种族
    TITLE = "title"               # 称号/外号
    FORMATION = "formation"       # 阵法/禁制
    EVENT = "event"               # 历史事件
    POSITION = "position"         # 职位/官衔
    TERM = "term"                 # 专有名词
    OTHER = "other"               # 其他


class Entity(BaseModel):
    """实体条目"""

    entity_id: str = Field(default_factory=lambda: str(uuid4()))
    canonical_name: str = Field(..., min_length=1, description="规范名称（主名）")
    aliases: list[str] = Field(default_factory=list, description="别名列表")
    entity_type: str = Field(..., description="实体类型，见 EntityType")
    first_mention_chapter: int = Field(..., ge=1, description="首次出现章节")
    definition: str = Field("", description="实体定义/描述")
    metadata: dict = Field(default_factory=dict, description="扩展元数据")

    # 内部统计字段
    mention_count: int = Field(0, ge=0, description="总提及次数")
    last_mention_chapter: int = Field(0, ge=0, description="最后提及章节")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class EntityMention(BaseModel):
    """实体提及记录（用于追踪上下文）"""

    mention_id: str = Field(default_factory=lambda: str(uuid4()))
    entity_id: str = Field(..., description="关联的实体 ID")
    chapter: int = Field(..., ge=1)
    mentioned_name: str = Field(..., description="实际提及的名称（可能是别名）")
    context: str = Field("", max_length=200, description="前后文摘录")
