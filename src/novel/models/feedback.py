"""读者反馈数据模型"""

from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class FeedbackType(str, Enum):
    CHARACTER = "character"  # 角色问题（性格不连贯、刻画单薄）
    PACING = "pacing"  # 节奏问题
    FORESHADOWING = "foreshadowing"  # 伏笔未回收
    DIALOGUE = "dialogue"  # 对话生硬
    PLOT_HOLE = "plot_hole"  # 情节漏洞
    STYLE = "style"  # 风格问题
    OTHER = "other"


class FeedbackEntry(BaseModel):
    feedback_id: str = Field(default_factory=lambda: str(uuid4())[:8])
    chapter_number: int | None = None  # None = 全局反馈
    content: str = Field(..., min_length=1)
    feedback_type: FeedbackType | None = None
    status: Literal["pending", "analyzed", "applied", "rejected"] = "pending"


class FeedbackAnalysis(BaseModel):
    feedback_id: str
    feedback_type: FeedbackType
    severity: Literal["low", "medium", "high"] = "medium"
    target_chapters: list[int] = Field(
        default_factory=list, description="直接修改的章节"
    )
    propagation_chapters: list[int] = Field(
        default_factory=list, description="下游受影响章节"
    )
    rewrite_instructions: dict[int, str] = Field(
        default_factory=dict, description="{章节号: 重写指令}"
    )
    character_changes: list[dict] | None = None
    summary: str = ""
