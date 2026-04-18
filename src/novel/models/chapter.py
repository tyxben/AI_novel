"""章节和场景数据模型"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.novel.models.novel import (
    BASE_CHAPTER_WORDS,
    CHAPTER_TYPE_WORD_MULTIPLIER,
    ChapterOutline,
    ChapterType,
)


class MoodTag(str, Enum):
    """章节情绪标签"""

    BUILDUP = "蓄力"
    SMALL_WIN = "小爽"
    BIG_WIN = "大爽"
    TRANSITION = "过渡"
    HEARTBREAK = "虐心"
    TWIST = "反转"
    DAILY = "日常"


class Scene(BaseModel):
    """场景（章节组成单元）"""

    scene_id: str = Field(
        default_factory=lambda: str(uuid4()), description="UUID"
    )
    scene_number: int = Field(..., ge=1, description="章内序号")

    # 场景要素
    location: str = Field(..., min_length=1, description="地点")
    time: str = Field(..., min_length=1, description="时间（相对时间）")
    characters: list[str] = Field(..., min_length=1, description="出场角色 ID")
    goal: str = Field(..., min_length=1, description="场景目标")

    # 内容
    text: str = Field("", max_length=15000)
    word_count: int = Field(0, ge=0)

    # 叙事元素
    narrative_modes: list[str] = Field(
        default_factory=list, description="对话/动作/描写/心理"
    )


class Chapter(BaseModel):
    """章节"""

    chapter_id: str = Field(
        default_factory=lambda: str(uuid4()), description="UUID"
    )
    chapter_number: int = Field(..., ge=1)
    title: str = Field(..., min_length=1)

    # 内容
    scenes: list[Scene] = Field(default_factory=list)
    full_text: str = Field("", description="完整正文，拼接 scenes")
    word_count: int = Field(0, ge=0)

    # --- Phase 1-B：章节级字数与类型（与 ChapterOutline 对齐）---
    chapter_type: ChapterType = Field(
        "buildup",
        description="章节类型，决定字数基数与节奏 (setup/buildup/climax/resolution/interlude)",
    )
    target_words: int | None = Field(
        None,
        ge=500,
        le=10000,
        description=(
            "本章目标字数。为 None 时由 chapter_type × BASE_CHAPTER_WORDS 推算，"
            "见 resolved_target_words。"
        ),
    )

    # 元数据
    outline: ChapterOutline
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="生成时间 ISO 格式",
    )
    quality_score: Optional[float] = Field(None, ge=0.0, le=10.0)

    # 状态
    status: Literal["draft", "reviewed", "finalized"] = Field(
        "draft", description="章节状态"
    )
    revision_count: int = Field(0, ge=0)

    @property
    def resolved_target_words(self) -> int:
        """返回本章目标字数。

        解析顺序：
        1. ``self.target_words`` (显式指定)
        2. ``self.outline.resolved_target_words`` (大纲层级)
        3. ``self.chapter_type × BASE_CHAPTER_WORDS`` 推算
        """
        if self.target_words is not None and self.target_words > 0:
            return int(self.target_words)
        try:
            if self.outline is not None:
                return int(self.outline.resolved_target_words)
        except Exception:  # pragma: no cover - outline malformed
            pass
        multiplier = CHAPTER_TYPE_WORD_MULTIPLIER.get(self.chapter_type, 1.0)
        return int(round(BASE_CHAPTER_WORDS * multiplier))
