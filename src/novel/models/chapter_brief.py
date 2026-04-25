"""ChapterBrief — chapter-level writing brief produced by ChapterPlanner.

Architecture rework 2026-04 Phase 2-δ: this model is the canonical structured
output of :class:`~src.novel.agents.chapter_planner.ChapterPlanner`.  Unlike
the legacy ``chapter_brief`` dict embedded inside ``ChapterOutline`` which
was authored at outline time and never refreshed, ``ChapterBrief`` is
regenerated *right before* each chapter is written so that the Ledger
snapshot (foreshadowings, debts, active characters) is current.

See ``specs/architecture-rework-2026/DESIGN.md`` Part 2 A3 for the full
specification.  The dict returned by
``ChapterPlanner.propose_chapter_brief`` is a ``ChapterBriefProposal`` —
a ``ChapterBrief`` plus diagnostics.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SceneSummary(BaseModel):
    """Scene-level summary embedded inside a ChapterBrief."""

    summary: str = Field(..., description="Scene goal / one-line summary")
    characters: list[str] = Field(default_factory=list)

    # Optional hints the Writer can use; kept flexible so legacy
    # scene_plans dicts deserialize cleanly.
    title: str | None = None
    target_words: int | None = None
    mood: str | None = None
    tension_level: float | None = None
    narrative_focus: str | None = None


class ChapterBrief(BaseModel):
    """Canonical per-chapter brief, assembled just before Writer runs.

    Fields marked "from Ledger" are re-fetched from
    :class:`~src.novel.services.ledger_store.LedgerStore` on every
    assembly so they reflect the latest narrative state rather than the
    stale copy stored on ``ChapterOutline.chapter_brief``.
    """

    chapter_number: int
    goal: str = ""
    scenes: list[SceneSummary] = Field(default_factory=list)

    # --- from Ledger --------------------------------------------------
    must_collect_foreshadowings: list[str] = Field(default_factory=list)
    must_fulfill_debts: list[str] = Field(default_factory=list)
    active_characters: list[str] = Field(default_factory=list)
    world_facts_to_respect: list[str] = Field(default_factory=list)

    # --- chapter-type driven -----------------------------------------
    target_words: int = 2500
    chapter_type: str = "buildup"   # setup / buildup / climax / resolution / interlude
    tone_notes: str = ""

    # --- end-hook section (absorbed from HookGenerator) ---------------
    end_hook: str = ""
    end_hook_type: str = ""

    # --- previous chapter continuity (no verbatim carry-over) ---------
    previous_chapter_tail_summary: str = Field(
        default="",
        description=(
            "上章结尾的结构化摘要（≤200 字，非原文）。由 ChapterPlanner 通过 LLM 压缩产出。"
        ),
    )
    previous_chapter_end_hook: str = Field(
        default="",
        description="上章 brief 的 end_hook（若可得），用于本章开头承接。",
    )

    # --- legacy compatibility ----------------------------------------
    # Some call sites (Writer prompts, pipeline) still expect the
    # unstructured ``chapter_brief`` dict keys.  We expose them back
    # through :meth:`to_legacy_chapter_brief` instead of duplicating.

    def to_legacy_chapter_brief(self) -> dict[str, Any]:
        """Return the dict shape expected by ``Writer.set_chapter_brief``.

        Writer reads ``main_conflict / payoff / foreshadowing_plant /
        foreshadowing_collect / end_hook / end_hook_type /
        character_arc_step`` from the dict embedded on
        ``ChapterOutline.chapter_brief``.  We map our first-class fields
        into that shape so the Writer stays unchanged during Phase 2-δ.

        NOTE: ``previous_chapter_tail_summary`` and
        ``previous_chapter_end_hook`` are **intentionally omitted** —
        they are per-run derived summaries of the *prior* chapter and
        must not be persisted into ``novel.json`` (would stale within
        one regeneration).  The runtime path keeps them on
        ``state["current_chapter_brief"]`` via the Pydantic dump
        instead.
        """
        return {
            "main_conflict": self.goal,
            "payoff": self.tone_notes,
            "character_arc_step": "",
            "foreshadowing_plant": [],
            "foreshadowing_collect": list(self.must_collect_foreshadowings),
            "end_hook": self.end_hook,
            "end_hook_type": self.end_hook_type,
        }


class ChapterBriefProposal(BaseModel):
    """Envelope returned by :meth:`ChapterPlanner.propose_chapter_brief`.

    Wraps the ``ChapterBrief`` with optional diagnostics so callers can
    tell why a Ledger section ended up empty (e.g. LedgerStore missing)
    without inspecting logs.
    """

    brief: ChapterBrief
    source: str = "chapter_planner"
    warnings: list[str] = Field(default_factory=list)

    # Raw scene plan list in legacy dict shape — kept because the Writer
    # currently reads ``state["current_scenes"]`` directly as a list of
    # dicts rather than Pydantic models.
    scene_plans: list[dict[str, Any]] = Field(default_factory=list)
