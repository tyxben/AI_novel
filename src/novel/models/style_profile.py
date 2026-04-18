"""StyleProfile 数据模型 — 本书用词/句长/节奏统计指纹。

由 :class:`StyleProfileService` 构建，取代硬编码的 AI 味黑名单
(``ai_flavor_blacklist``)。核心理念：**本书自己的口头禅**，而非全局词表。

字段设计参考架构重构方案 ``specs/architecture-rework-2026/DESIGN.md`` Part 3 B2：

- ``overused_phrases``：出现在 >= 30% 章节的短语（自动检测，供 Reviewer watchlist）
- ``avg_sentence_len`` / ``sentence_len_std``：句长统计
- ``pacing_curve``：按章节的"动作密度"点（动作动词/描写词比值）
- ``sample_size``：构建统计用了多少章

Phase 1-A：仅落数据模型 + 服务 + 存储，不 wire 进 Verifier/Reviewer
（集成留给 Phase 2 合并 Reviewer 时统一处理）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class OverusedPhrase(BaseModel):
    """高频短语条目。

    ``chapter_coverage`` 表示这个 phrase 在多少比例的章节里出现；
    本项目的判定阈值默认 >= 0.3（30%），由 service 层决定。
    """

    phrase: str = Field(..., min_length=1, description="短语文本")
    chapter_coverage: float = Field(
        ..., ge=0.0, le=1.0, description="出现在多少比例的章节（0-1）"
    )
    total_occurrences: int = Field(
        ..., ge=1, description="全书总出现次数"
    )


class PacingPoint(BaseModel):
    """单章节奏点。

    ``action_density`` 是"动作动词数 / (动作动词数 + 描写词数)"，范围 0-1：

    - 接近 1：章节偏动作/打斗/推进
    - 接近 0：章节偏描写/日常/铺垫
    - 0.5 附近：平衡
    """

    chapter_number: int = Field(..., ge=1)
    action_density: float = Field(
        ..., ge=0.0, le=1.0, description="动作密度，0-1"
    )


class StyleProfile(BaseModel):
    """本书的风格指纹。

    由 :class:`StyleProfileService.build` 从已有章节文本统计得出，
    用于：

    1. Reviewer 检查新章节是否过度复用本书自己的口头禅
    2. Verifier 对照 overused phrases 提示潜在的"自我抄袭"
    3. 风格/节奏可视化（前端展示）
    """

    novel_id: str = Field(..., min_length=1, description="小说 ID")
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="最近一次统计的 ISO 时间戳",
    )

    overused_phrases: list[OverusedPhrase] = Field(
        default_factory=list,
        description=">= 阈值章节覆盖率的短语（默认阈值 30%）",
    )
    avg_sentence_len: float = Field(
        0.0, ge=0.0, description="全书平均句长（字符数）"
    )
    sentence_len_std: float = Field(
        0.0, ge=0.0, description="句长标准差"
    )
    pacing_curve: list[PacingPoint] = Field(
        default_factory=list, description="每章节奏点"
    )
    sample_size: int = Field(
        0, ge=0, description="构建统计用了多少章（<=0 代表空 profile）"
    )
