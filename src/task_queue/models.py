"""Task queue data models."""

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TaskType(str, enum.Enum):
    novel_create = "novel_create"
    novel_generate = "novel_generate"
    novel_polish = "novel_polish"
    novel_feedback = "novel_feedback"
    video_generate = "video_generate"
    director_generate = "director_generate"
    ppt_generate = "ppt_generate"
    ppt_outline = "ppt_outline"
    ppt_continue = "ppt_continue"
    ppt_render_html = "ppt_render_html"
    ppt_export = "ppt_export"
    novel_rewrite_affected = "novel_rewrite_affected"
    novel_resize = "novel_resize"
    novel_agent_chat = "novel_agent_chat"
    novel_narrative_rebuild = "novel_narrative_rebuild"


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TaskRecord(BaseModel):
    task_id: str
    task_type: TaskType
    status: TaskStatus = TaskStatus.pending
    progress: float = 0.0  # 0.0 ~ 1.0
    progress_msg: str = ""
    params: dict = Field(default_factory=dict)
    result: Optional[str] = None  # JSON string when completed
    error: Optional[str] = None  # error message + traceback
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
