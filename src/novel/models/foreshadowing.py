"""伏笔管理数据模型"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class Foreshadowing(BaseModel):
    """伏笔（V2）"""

    foreshadowing_id: str = Field(
        default_factory=lambda: str(uuid4()), description="UUID"
    )
    planted_chapter: int = Field(
        ..., ge=1, description="埋设章节（正向）或原始章节（后置）"
    )
    content: str = Field(..., min_length=1)

    # 回收计划
    target_chapter: int = Field(
        ..., ge=-1, description="-1 表示后置伏笔初始状态"
    )
    resolution: str | None = None

    # 伏笔类型
    origin: Literal["planned", "retroactive"] = Field(
        ..., description="正向埋设 / 后置追认"
    )
    original_detail_id: str | None = None
    original_context: str | None = None

    status: Literal["pending", "collected", "abandoned"] = Field(
        "pending", description="伏笔状态"
    )
    collected_chapter: int | None = None


class DetailEntry(BaseModel):
    """历史闲笔（潜在可利用的细节）"""

    detail_id: str = Field(
        default_factory=lambda: str(uuid4()), description="UUID"
    )
    chapter: int = Field(..., ge=1)
    content: str = Field(..., min_length=1)
    context: str = Field(..., min_length=1, description="原文上下文，前后 2 句")
    category: str = Field(
        ...,
        min_length=1,
        description="道具/环境/角色动作/异常现象/对话暗示",
    )
    status: Literal["available", "promoted", "used"] = Field(
        "available", description="细节状态"
    )
    promoted_foreshadowing_id: str | None = None


class ForeshadowingEdge(BaseModel):
    """伏笔关系边"""

    edge_id: str = Field(default_factory=lambda: str(uuid4()))
    from_foreshadowing_id: str = Field(..., description="源伏笔ID")
    to_foreshadowing_id: str = Field(..., description="目标伏笔ID")
    relation_type: Literal["trigger", "collect", "parallel", "conflict"] = Field(
        ..., description="触发/回收/并行/冲突"
    )
    description: str = Field("", description="关系描述")


class ForeshadowingStatus(BaseModel):
    """伏笔状态摘要（用于检查遗忘）"""

    foreshadowing_id: str
    planted_chapter: int
    target_chapter: int
    status: Literal["pending", "collected", "abandoned"]
    content: str = Field("", description="伏笔内容")
    chapters_since_plant: int = Field(..., description="距埋设已过多少章")
    last_mentioned_chapter: int | None = Field(
        None, description="最后被提及的章节"
    )
    is_forgotten: bool = Field(
        False, description="是否即将遗忘（超过阈值未提及）"
    )
