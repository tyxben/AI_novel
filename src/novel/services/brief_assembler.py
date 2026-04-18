"""BriefAssembler — Ledger-first continuity context for ChapterPlanner.

Architecture rework 2026-04 Phase 2-δ (Part 3 B2): this class is the
renamed successor of :class:`ContinuityService`.  The legacy
implementation (rule-based hook scanning, dead-character detection,
volume milestones, etc.) remains available via the parent class so
existing callers keep working; ``BriefAssembler`` adds a single new
entry point that pulls fresh data from :class:`LedgerStore`:

    >>> la = BriefAssembler(db=..., ledger=ledger)
    >>> ctx = la.assemble_for_chapter(novel, volume_number=1, chapter_number=12)
    >>> ctx["must_collect_foreshadowings"]  # from Ledger snapshot
    ['...']

The old ``generate_brief`` + ``format_for_prompt`` methods are inherited
unchanged so ``pipeline.generate_chapters`` can migrate incrementally.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.novel.services.continuity_service import ContinuityService

if TYPE_CHECKING:  # pragma: no cover
    from src.novel.models.novel import Novel
    from src.novel.services.ledger_store import LedgerStore

log = logging.getLogger("novel.services.brief_assembler")


class BriefAssembler(ContinuityService):
    """ChapterPlanner's context assembler.

    Wraps :class:`ContinuityService` with a Ledger-first ``assemble_for_chapter``
    method.  When ``ledger`` is provided we query
    :meth:`LedgerStore.snapshot_for_chapter` and normalize the result
    into a flat dict suitable for ChapterPlanner prompts; falling back
    to the legacy rule-based aggregation when it is absent.

    Args:
        db: structured DB (inherited).
        obligation_tracker: legacy debt tracker (inherited).
        knowledge_graph: legacy foreshadowing KG (inherited).
        ledger: ``LedgerStore`` instance.  When supplied,
            :meth:`assemble_for_chapter` uses it exclusively; when
            ``None`` we fall back to the inherited rule-based path.
    """

    def __init__(
        self,
        db: Any = None,
        obligation_tracker: Any = None,
        knowledge_graph: Any = None,
        ledger: "LedgerStore | None" = None,
    ) -> None:
        super().__init__(
            db=db,
            obligation_tracker=obligation_tracker,
            knowledge_graph=knowledge_graph,
        )
        self.ledger = ledger

    # ------------------------------------------------------------------
    # New Ledger-first assembly
    # ------------------------------------------------------------------

    def assemble_for_chapter(
        self,
        novel: Any,
        volume_number: int,
        chapter_number: int,
    ) -> dict[str, Any]:
        """Build a flat context dict for :class:`ChapterPlanner`.

        Args:
            novel: a ``Novel`` model or dict; only used for active-character
                defaulting. Pass ``None`` when you only want the Ledger section.
            volume_number: current volume (kept for forward compatibility —
                the Ledger is volume-agnostic right now but callers pass it).
            chapter_number: the chapter being planned.

        Returns:
            Dict with keys::

                must_collect_foreshadowings: list[str]
                must_fulfill_debts:          list[str]
                active_characters:           list[str]
                world_facts_to_respect:      list[str]
                pending_milestones:          list[str]
                warnings:                    list[str]   (diagnostics)

            All lists default to empty when the backing Ledger is
            missing; never raises.
        """
        ctx: dict[str, Any] = {
            "must_collect_foreshadowings": [],
            "must_fulfill_debts": [],
            "active_characters": [],
            "world_facts_to_respect": [],
            "pending_milestones": [],
            "warnings": [],
        }

        if self.ledger is None:
            ctx["warnings"].append("ledger_unavailable")
            # Best-effort fallback: derive active characters from novel.
            ctx["active_characters"] = self._default_active_characters(novel)
            return ctx

        try:
            snap = self.ledger.snapshot_for_chapter(chapter_number)
        except Exception as exc:  # noqa: BLE001 — degrade gracefully
            log.warning("LedgerStore snapshot failed: %s", exc)
            ctx["warnings"].append(f"ledger_error:{exc}")
            ctx["active_characters"] = self._default_active_characters(novel)
            return ctx

        # --- foreshadowings -------------------------------------------
        for item in snap.get("collectable_foreshadowings") or []:
            content = (item or {}).get("content")
            if content:
                ctx["must_collect_foreshadowings"].append(str(content))

        # --- debts ----------------------------------------------------
        for debt in snap.get("pending_debts") or []:
            desc = (debt or {}).get("description")
            if desc:
                ctx["must_fulfill_debts"].append(str(desc))

        # --- active characters ----------------------------------------
        ac = [
            (c or {}).get("name", "")
            for c in snap.get("active_characters") or []
            if (c or {}).get("name")
        ]
        if not ac:
            ac = self._default_active_characters(novel)
        ctx["active_characters"] = ac

        # --- world facts ----------------------------------------------
        for term in snap.get("world_facts") or []:
            if not isinstance(term, dict):
                continue
            name = term.get("name") or term.get("term") or term.get("canonical_name")
            if name:
                ctx["world_facts_to_respect"].append(str(name))

        # --- milestones -----------------------------------------------
        for ms in snap.get("pending_milestones") or []:
            desc = (ms or {}).get("description")
            if desc:
                ctx["pending_milestones"].append(str(desc))

        return ctx

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_active_characters(novel: Any) -> list[str]:
        """Extract active character names from a ``Novel`` or novel dict."""
        if novel is None:
            return []

        if hasattr(novel, "characters"):
            chars = getattr(novel, "characters", []) or []
        elif isinstance(novel, dict):
            chars = novel.get("characters", []) or []
        else:
            return []

        names: list[str] = []
        for c in chars:
            if hasattr(c, "name"):
                name = getattr(c, "name", "")
            elif isinstance(c, dict):
                name = c.get("name", "")
            else:
                name = ""
            if name:
                names.append(name)
        return names
