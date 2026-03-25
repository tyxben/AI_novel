"""Chapter debt tracking - narrative obligations across chapters

Debts represent promises or expectations created in one chapter that must be
fulfilled in a subsequent chapter.  The three urgency types control how quickly
a debt must be resolved:

- ``must_pay_next``: Must be addressed in the very next chapter.
- ``pay_within_3``: Should be addressed within 3 chapters.
- ``long_tail_payoff``: Can be resolved over a longer horizon.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ChapterDebt(BaseModel):
    """Narrative obligation requiring future payoff

    Example::

        debt = ChapterDebt(
            source_chapter=5,
            type="must_pay_next",
            description="主角答应师妹明天一起探索密林",
        )
    """

    debt_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="UUID",
    )
    source_chapter: int = Field(
        ..., ge=1, description="Chapter where promise was made"
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Creation timestamp ISO format",
    )

    # Debt classification
    type: Literal["must_pay_next", "pay_within_3", "long_tail_payoff"] = Field(
        ..., description="Urgency classification"
    )
    description: str = Field(
        ..., min_length=1, description="What needs to be resolved"
    )

    # Specific obligations
    character_pending_actions: list[str] = Field(
        default_factory=list, description="Character-specific obligations"
    )
    emotional_debt: str | None = Field(
        None, description="Unresolved emotional tension"
    )

    # Resolution tracking
    target_chapter: int | None = Field(
        None, ge=1, description="When it should be paid (if specified)"
    )
    status: Literal["pending", "fulfilled", "overdue", "abandoned"] = Field(
        "pending", description="Current debt status"
    )
    fulfilled_at: int | None = Field(
        None, ge=1, description="Chapter where debt was paid"
    )
    fulfillment_note: str | None = Field(
        None, description="How the debt was resolved"
    )

    # Escalation
    urgency_level: Literal["normal", "high", "critical"] = Field(
        "normal", description="Escalation level"
    )
    escalation_history: list[dict] = Field(
        default_factory=list, description="Log of urgency changes"
    )


class DebtExtractionResult(BaseModel):
    """Result of extracting debts from a chapter

    Example::

        result = DebtExtractionResult(
            chapter_number=5,
            debts=[debt1, debt2],
            extraction_method="hybrid",
            confidence=0.85,
        )
    """

    chapter_number: int = Field(..., ge=1)
    debts: list[ChapterDebt] = Field(default_factory=list)
    extraction_method: Literal["llm", "rule_based", "hybrid"] = Field(
        "llm", description="Method used for extraction"
    )
    confidence: float = Field(
        1.0, ge=0.0, le=1.0, description="Confidence in extraction quality"
    )


class DebtContext(BaseModel):
    """Formatted debt context for Writer prompt injection

    Groups debts by severity and provides a pre-formatted summary string
    suitable for inclusion in LLM prompts.

    Example::

        ctx = DebtContext(
            chapter_number=10,
            pending_debts=[debt1],
            overdue_debts=[debt2],
            critical_debts=[],
            formatted_summary="...",
            token_count=150,
        )
    """

    chapter_number: int = Field(..., ge=1, description="Target chapter")
    pending_debts: list[ChapterDebt] = Field(default_factory=list)
    overdue_debts: list[ChapterDebt] = Field(default_factory=list)
    critical_debts: list[ChapterDebt] = Field(default_factory=list)

    formatted_summary: str = Field(
        "", description="Human-readable summary for LLM prompt"
    )
    token_count: int = Field(
        0, ge=0, description="Estimated token count of summary"
    )
