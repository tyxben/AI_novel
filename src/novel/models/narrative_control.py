"""Narrative control data models.

Houses Pydantic models for the v2 narrative arc control mechanisms:
- NarrativeMilestone / VolumeProgressReport (Intervention A): volume progress budget
- StyleBible (Intervention D): per-project style anchoring document
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Intervention A: Volume Progress Budget
# ---------------------------------------------------------------------------


class NarrativeMilestone(BaseModel):
    """卷级叙事里程碑"""

    milestone_id: str = Field(..., description="唯一标识，如 vol1_m1")
    description: str = Field(
        ..., min_length=5, max_length=200, description="中文描述"
    )
    target_chapter_range: list[int] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="目标完成章节范围 [min, max]",
    )
    verification_type: Literal["auto_keyword", "llm_review"] = Field(
        default="auto_keyword", description="验证方式"
    )
    verification_criteria: list[str] | str = Field(
        ...,
        description="关键词列表（auto_keyword）或 LLM prompt（llm_review）",
    )
    priority: Literal["critical", "high", "normal"] = Field(
        default="normal", description="优先级"
    )
    status: Literal["pending", "completed", "overdue", "abandoned"] = Field(
        default="pending", description="完成状态"
    )
    completed_at_chapter: int | None = Field(
        default=None, description="实际完成章节号"
    )
    inherited_from_volume: int | None = Field(
        default=None, description="若继承自上一卷，记录来源卷号"
    )


class VolumeProgressReport(BaseModel):
    """卷完成度报告"""

    volume_number: int = Field(..., ge=1)
    milestones_total: int = Field(..., ge=0)
    milestones_completed: int = Field(..., ge=0)
    milestones_overdue: int = Field(..., ge=0)
    milestones_abandoned: int = Field(default=0, ge=0)
    milestones_inherited_to_next: int = Field(default=0, ge=0)
    completion_rate: float = Field(..., ge=0.0, le=1.0, description="完成率")
    settlement_timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="收束时间戳",
    )


# ---------------------------------------------------------------------------
# Intervention D: Writer Style Anchoring
# ---------------------------------------------------------------------------


class StyleBible(BaseModel):
    """风格圣经 - 项目专属风格锚定文档。

    Quantitative targets lock in the novel's writing voice. Generated once
    at project creation and consulted every chapter by Writer (via brief).
    Phase 2-β: 旧 StyleKeeper gate-check 已废弃；对 style bible 的日常复核
    由 Reviewer 在 CritiqueResult 里以 issues 形式回报。
    """

    quantitative_targets: dict[str, Any] = Field(
        ...,
        description=(
            "Metric name -> [min, max] target ranges. Expected keys: "
            "avg_sentence_length, dialogue_ratio, paragraph_length, "
            "sensory_density, exclamation_ratio.  Values are lists of "
            "two numbers."
        ),
    )
    voice_description: str = Field(
        ...,
        min_length=5,
        max_length=300,
        description="~50 word description of the target voice",
    )
    exemplar_paragraphs: list[str] = Field(
        ...,
        min_length=2,
        max_length=5,
        description="2-3 paragraphs (~200 chars each) of ideal prose",
    )
    anti_patterns: list[str] = Field(
        default_factory=list,
        description="AI-flavor phrases / patterns to ban",
    )
    volume_overrides: dict[int, dict] | None = Field(
        default=None,
        description="Optional per-volume metric overrides, keyed by volume number",
    )
    generated_at: str | None = Field(
        default=None,
        description="ISO timestamp of generation",
    )
    based_on_chapters: list[int] | None = Field(
        default=None,
        description="Chapter numbers used as baseline (migration case)",
    )

    @field_validator("quantitative_targets")
    @classmethod
    def _validate_targets(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Ensure target values are [min, max] pairs where min <= max."""
        for key, val in v.items():
            if isinstance(val, (list, tuple)) and len(val) == 2:
                lo, hi = val
                if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))):
                    raise ValueError(
                        f"quantitative_targets['{key}'] values must be numbers, got {val}"
                    )
                if lo > hi:
                    raise ValueError(
                        f"quantitative_targets['{key}'] min ({lo}) > max ({hi})"
                    )
        return v

    @field_validator("exemplar_paragraphs")
    @classmethod
    def _validate_exemplars(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("exemplar_paragraphs must contain at least 2 paragraphs")
        return v
