"""小说项目核心数据模型：Novel, Outline, Act, Volume 等"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class OutlineTemplate(BaseModel):
    """大纲模板定义"""

    name: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="模板名称，如 cyclic_upgrade",
    )
    description: str = Field("", max_length=500, description="模板描述")
    act_count: int = Field(..., ge=1, le=10, description="幕数量")
    default_chapters_per_volume: int = Field(
        30, ge=5, le=100, description="每卷默认章节数"
    )


class Act(BaseModel):
    """幕（最顶层结构）"""

    name: str = Field(..., min_length=1, description="如'第一幕：平凡世界'")
    description: str = Field(..., min_length=1)
    start_chapter: int = Field(..., ge=1)
    end_chapter: int = Field(..., ge=1)


class VolumeOutline(BaseModel):
    """卷大纲"""

    volume_number: int = Field(..., ge=1)
    title: str = Field(..., min_length=1)
    core_conflict: str = Field(..., min_length=1, description="本卷核心矛盾")
    resolution: str = Field(..., min_length=1, description="本卷如何解决")
    chapters: list[int] = Field(..., min_length=1, description="包含的章节号")


class ChapterOutline(BaseModel):
    """章大纲"""

    chapter_number: int = Field(..., ge=1)
    title: str = Field(..., min_length=1)
    goal: str = Field(..., min_length=1, description="本章目标")
    key_events: list[str] = Field(..., min_length=1)
    involved_characters: list[str] = Field(
        default_factory=list, description="角色 ID 列表"
    )
    plot_threads: list[str] = Field(
        default_factory=list, description="推进的情节线 ID"
    )
    estimated_words: int = Field(2500, ge=500, le=10000)
    mood: Literal["蓄力", "小爽", "大爽", "过渡", "虐心", "反转", "日常"] = Field(
        "蓄力", description="章节情绪基调"
    )
    storyline_progress: str = Field(
        "", description="本章如何推进主线（例：主角发现关键线索）"
    )
    chapter_summary: str = Field(
        "", description="本章内容摘要（2-3句话）"
    )


class Outline(BaseModel):
    """三层大纲结构"""

    template: Literal[
        "cyclic_upgrade", "multi_thread", "four_act", "scifi_crisis", "custom"
    ] = Field(..., description="大纲模板类型")
    main_storyline: dict = Field(
        default_factory=dict,
        description="主线定义，包含 protagonist_goal, core_conflict, character_arc, stakes 等",
    )
    acts: list[Act] = Field(default_factory=list)
    volumes: list[VolumeOutline] = Field(default_factory=list)
    chapters: list[ChapterOutline] = Field(default_factory=list)


class Volume(BaseModel):
    """卷实体"""

    volume_number: int = Field(..., ge=1)
    title: str = Field(..., min_length=1)
    chapters: list[int] = Field(default_factory=list)
    status: Literal["planning", "writing", "completed"] = Field(
        "planning", description="卷状态"
    )
    snapshot: VolumeSnapshot | None = None


class Novel(BaseModel):
    """小说项目根对象"""

    novel_id: str = Field(
        default_factory=lambda: str(uuid4()), description="UUID"
    )
    title: str = Field(..., min_length=1, max_length=100)
    genre: str = Field(
        ..., min_length=1, description="题材: 武侠/都市/玄幻/科幻/言情/悬疑"
    )
    theme: str = Field(..., min_length=1, description="主题")
    target_words: int = Field(..., gt=0, description="目标字数")

    # 风格
    style_category: str = Field(
        ..., min_length=1, description="武侠/网文/文学/轻小说"
    )
    style_subcategory: str = Field(..., min_length=1, description="子类风格")
    custom_style_reference: str | None = Field(
        None, description="自定义风格参考文本"
    )

    # 结构
    outline: Outline
    volumes: list[Volume] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)

    # 设定
    world_setting: WorldSetting
    characters: list[CharacterProfile] = Field(default_factory=list)

    # 元数据
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="创建时间 ISO 格式",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="更新时间 ISO 格式",
    )
    status: Literal["draft", "writing", "completed"] = Field(
        "draft", description="项目状态"
    )
    current_chapter: int = Field(0, ge=0)
