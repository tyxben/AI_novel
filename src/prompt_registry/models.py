"""Prompt Registry data models.

Pydantic models for prompt blocks, templates, usage records, and feedback.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PromptBlock(BaseModel):
    """Prompt 的最小管理单元，可复用的文本片段。"""

    block_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    base_id: str  # 不含版本号的 ID，如 "anti_ai_flavor"
    version: int = 1
    block_type: str  # system_instruction / craft_technique / anti_pattern / scene_specific / feedback_injection / few_shot_example
    agent: str = "universal"  # 所属 agent 或 "universal" 表示通用
    genre: str | None = None  # 适用题材（wuxia/scifi/...），None=通用
    scene_type: str | None = None  # 适用场景类型（battle/dialogue/...），None=通用
    content: str  # block 文本内容
    active: bool = True  # 是否启用
    needs_optimization: bool = False  # 是否需要优化（低分标记）
    avg_score: float | None = None  # 平均质量分
    usage_count: int = 0
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    updated_at: datetime = Field(default_factory=lambda: datetime.now())


class PromptTemplate(BaseModel):
    """定义如何从多个 block 组装成完整 prompt 的规则。"""

    template_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    agent_name: str  # 所属 agent
    scenario: str = "default"  # 适用场景
    genre: str | None = None
    block_refs: list[str]  # block base_id 列表（按顺序组装）
    active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now())


class PromptUsage(BaseModel):
    """记录每次使用的 prompt 版本和质量评分。"""

    usage_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    template_id: str
    block_ids: list[str]  # 实际使用的 block_id 列表
    agent_name: str
    scenario: str
    novel_id: str | None = None
    chapter_number: int | None = None
    quality_score: float | None = None
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now())


class FeedbackRecord(BaseModel):
    """章节质量反馈记录，用于即时层注入。"""

    record_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    novel_id: str
    chapter_number: int
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    overall_score: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now())
