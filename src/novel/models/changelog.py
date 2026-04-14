"""变更历史数据模型"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class ChangeLogEntry(BaseModel):
    """单条变更记录。"""

    change_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    novel_id: str
    change_type: str  # "add_character" | "modify_character" | "delete_character" | "modify_outline" | "modify_world"
    entity_type: str  # "character" | "outline" | "world"
    entity_id: Optional[str] = None
    description: str  # 变更描述（如"添加角色李明"）
    old_value: Optional[dict[str, Any]] = None  # 变更前的 JSON 快照
    new_value: Optional[dict[str, Any]] = None  # 变更后的 JSON 快照
    effective_from_chapter: int = 1
    author: str = "ai"  # "ai" | "user"
