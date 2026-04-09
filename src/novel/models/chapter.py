"""章节和场景数据模型"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.novel.models.novel import ChapterOutline


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
