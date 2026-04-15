"""角色相关数据模型"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class TurningPoint(BaseModel):
    """角色转折点"""

    chapter: int = Field(..., ge=1)
    event: str = Field(..., min_length=1)
    change: str = Field(..., min_length=1, description="如'学会坚持'")


class CharacterArc(BaseModel):
    """角色成长弧线"""

    initial_state: str = Field(..., min_length=1, description="如'懦弱自卑'")
    turning_points: list[TurningPoint] = Field(default_factory=list)
    final_state: str = Field(..., min_length=1, description="如'自信坚毅'")


class RelationshipEvent(BaseModel):
    """关系变化事件"""

    chapter: int = Field(..., ge=1)
    from_type: str = Field(..., min_length=1)
    to_type: str = Field(..., min_length=1)
    trigger_event: str = Field(..., min_length=1, description="触发事件")
    intensity_change: int = Field(..., ge=-10, le=10)


class Relationship(BaseModel):
    """角色关系（带时间维度）"""

    target_character_id: str = Field(..., min_length=1)
    current_type: str = Field(
        ...,
        min_length=1,
        description="敌对/友好/暧昧/师徒/亲属/竞争/利用/依赖/崇拜/畏惧/合作/背叛/暗恋/仇杀/陌生",
    )
    description: str = Field(..., min_length=1)
    intensity: int = Field(..., ge=1, le=10, description="关系强度")
    history: list[RelationshipEvent] = Field(default_factory=list)


class Appearance(BaseModel):
    """外貌特征"""

    height: str = Field(..., min_length=1, description="如'175cm'")
    build: str = Field(..., min_length=1, description="体型: 瘦削/魁梧/匀称")
    hair: str = Field(..., min_length=1, description="发型颜色")
    eyes: str = Field(..., min_length=1)
    clothing_style: str = Field(..., min_length=1)
    distinctive_features: list[str] = Field(
        default_factory=list, description="如'左脸刀疤'"
    )


class Personality(BaseModel):
    """性格"""

    traits: list[str] = Field(
        ..., min_length=3, max_length=7, description="性格标签"
    )
    core_belief: str = Field(..., min_length=1, description="核心信念")
    motivation: str = Field(..., min_length=1, description="动机")
    flaw: str = Field(..., min_length=1, description="缺陷")
    speech_style: str = Field(
        ..., min_length=1, description="语言风格: 文绉绉/江湖豪爽/冷淡简短"
    )
    catchphrases: list[str] = Field(default_factory=list, description="口头禅")


class CharacterSnapshot(BaseModel):
    """角色状态快照"""

    character_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    current_power_level: str | None = None
    location: str = Field(..., min_length=1)
    health: str = Field(..., min_length=1)
    emotional_state: str = Field(..., min_length=1)
    key_relationships_changed: list[str] = Field(default_factory=list)


class CharacterProfile(BaseModel):
    """角色档案"""

    character_id: str = Field(
        default_factory=lambda: str(uuid4()), description="UUID"
    )
    name: str = Field(..., min_length=1)
    alias: list[str] = Field(default_factory=list)

    # 基础属性
    gender: Literal["男", "女", "其他"] = Field(..., description="性别")
    age: int = Field(..., ge=0, le=200)
    occupation: str = Field(..., min_length=1)
    role: str = Field(
        "配角", description="角色类型：主角/反派/配角/导师/爱情线等"
    )
    status: Literal["active", "retired", "deceased", "absent"] = Field(
        "active", description="角色状态"
    )

    # 外貌
    appearance: Appearance

    # 性格
    personality: Personality

    # 关系网
    relationships: list[Relationship] = Field(default_factory=list)

    # 成长弧线
    character_arc: CharacterArc | None = None

    # 立绘（V2）
    portrait_image: str | None = None

    # 版本控制（智能编辑系统）
    effective_from_chapter: int | None = Field(
        None, description="生效起始章节（None=从头生效）"
    )
    deprecated_at_chapter: int | None = Field(
        None, description="废弃章节（None=一直生效）"
    )
    version: int = Field(1, ge=1, description="版本号")
