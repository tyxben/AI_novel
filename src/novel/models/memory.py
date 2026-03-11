"""记忆系统数据模型：Fact, ChapterSummary, VolumeSnapshot, ContextWindow"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from src.novel.models.character import CharacterSnapshot
from src.novel.models.foreshadowing import Foreshadowing


class Fact(BaseModel):
    """关键事实"""

    fact_id: str = Field(
        default_factory=lambda: str(uuid4()), description="UUID"
    )
    chapter: int = Field(..., ge=1)
    type: Literal[
        "time", "character_state", "location", "event", "relationship"
    ] = Field(..., description="事实类型")
    content: str = Field(..., min_length=1)
    storage_layer: Literal["structured", "graph", "vector"] = Field(
        ..., description="存储层"
    )
    embedding: list[float] | None = None


class ChapterSummary(BaseModel):
    """章节摘要"""

    chapter: int = Field(..., ge=1)
    summary: str = Field(..., min_length=50, max_length=1000)
    key_events: list[str] = Field(..., min_length=1)


class VolumeSnapshot(BaseModel):
    """卷间过渡快照"""

    volume_number: int = Field(..., ge=1)

    # 主线进度
    main_plot_progress: str = Field(..., min_length=1)
    main_plot_completion: float = Field(..., ge=0.0, le=1.0)

    # 角色状态快照
    character_states: list[CharacterSnapshot] = Field(default_factory=list)

    # 伏笔管理
    unresolved_foreshadowing: list[Foreshadowing] = Field(default_factory=list)
    resolved_this_volume: list[str] = Field(default_factory=list)

    # 上卷结尾
    ending_summary: str = Field(..., min_length=100, max_length=1000)
    cliffhanger: str | None = None

    # 世界观增量
    new_terms: dict[str, str] = Field(default_factory=dict)
    power_changes: list[str] = Field(default_factory=list)


class ContextWindow(BaseModel):
    """上下文窗口 - 组装给 LLM 的写作上下文"""

    recent_chapters_text: str = Field(
        "", description="最近 N 章正文（滑动窗口）"
    )
    chapter_summaries: list[ChapterSummary] = Field(
        default_factory=list, description="相关章节摘要"
    )
    relevant_facts: list[Fact] = Field(
        default_factory=list, description="向量检索到的相关事实"
    )
    volume_snapshot: VolumeSnapshot | None = Field(
        None, description="当前卷快照"
    )
    max_tokens: int = Field(8000, ge=1000, le=128000, description="上下文窗口大小限制")
