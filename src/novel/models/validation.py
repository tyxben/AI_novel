"""Validation models for chapter brief fulfillment

After a chapter is generated, the BriefValidator checks whether the chapter
fulfills the obligations defined in its chapter_brief.  Results are captured
in a ``BriefFulfillmentReport``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class BriefItemResult(BaseModel):
    """Result for a single brief item

    Example::

        item = BriefItemResult(
            item_name="main_conflict",
            expected="主角与反派首次正面冲突",
            fulfilled=True,
            evidence="第三段描写了主角与反派的对峙",
            reason="冲突场景完整呈现",
        )
    """

    item_name: str = Field(
        ..., description="Brief item key (e.g., 'main_conflict')"
    )
    expected: str = Field(..., description="What was expected from brief")
    fulfilled: bool = Field(..., description="Whether it was fulfilled")
    evidence: str | None = Field(
        None, description="Text evidence of fulfillment"
    )
    reason: str | None = Field(None, description="Why it passed/failed")


class BriefFulfillmentReport(BaseModel):
    """Complete validation report for chapter brief

    Example::

        report = BriefFulfillmentReport(
            chapter_number=5,
            overall_pass=True,
            item_results=[item1, item2],
        )
    """

    chapter_number: int = Field(..., ge=1)

    # Per-item results
    main_conflict_fulfilled: bool = Field(
        True, description="Main conflict addressed"
    )
    payoff_delivered: bool = Field(True, description="Payoff present")
    character_arc_step_taken: bool = Field(
        True, description="Character arc progressed"
    )
    foreshadowing_planted: list[bool] = Field(
        default_factory=list, description="Per-item plant status"
    )
    foreshadowing_collected: list[bool] = Field(
        default_factory=list, description="Per-item collection status"
    )
    end_hook_present: bool = Field(
        True, description="Chapter end hook exists"
    )

    # Detailed breakdown
    item_results: list[BriefItemResult] = Field(
        default_factory=list, description="Detailed per-item results"
    )

    # Summary
    unfulfilled_items: list[str] = Field(
        default_factory=list, description="List of failed items"
    )
    overall_pass: bool = Field(..., description="All mandatory items passed")
    pass_rate: float = Field(
        1.0, ge=0.0, le=1.0, description="Proportion of items fulfilled"
    )

    # Recommendations
    suggested_debts: list[str] = Field(
        default_factory=list, description="Items that should become debts"
    )

    @model_validator(mode="after")
    def _compute_pass_rate(self) -> BriefFulfillmentReport:
        """Compute pass_rate from item_results when items exist and rate is default."""
        if self.item_results and self.pass_rate == 1.0:
            fulfilled_count = sum(
                1 for item in self.item_results if item.fulfilled
            )
            self.pass_rate = fulfilled_count / len(self.item_results)
        return self
