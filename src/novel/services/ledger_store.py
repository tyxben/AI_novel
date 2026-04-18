"""LedgerStore — unified facade over narrative ledger services.

This module is part of the 2026-04 architecture rework (Phase 1-C).

Background
----------
The narrative state of a novel project is currently fragmented across at
least six services:

* :class:`~src.novel.services.obligation_tracker.ObligationTracker` —
  narrative debts lifecycle.
* :class:`~src.novel.services.debt_extractor.DebtExtractor` — extracts
  debts from chapter text.
* :class:`~src.novel.services.foreshadowing_service.ForeshadowingService`
  — foreshadowing graph, detail promotion, forgotten-foreshadow warnings.
* :class:`~src.novel.services.character_arc_tracker.CharacterArcTracker`
  — character growth stages and arcs.
* :class:`~src.novel.services.milestone_tracker.MilestoneTracker` —
  per-volume narrative milestones and progress health.
* :class:`~src.novel.services.entity_service.EntityService` — entity
  registry, alias merging, name-conflict detection.

Each service speaks to a different combination of underlying stores
(``StructuredDB`` / ``KnowledgeGraph`` / ``VectorStore``) and has its own
ad-hoc query shape. Callers such as ``ContinuityService`` / ``BriefAssembler``
/ consistency checks currently know about all of them.

LedgerStore
-----------
``LedgerStore`` is the Phase 2+ single entry point for ledger reads and
writes. It wraps the services above without modifying them. This Phase 1-C
commit only introduces the facade and tests — the migration of existing
callers (ConsistencyChecker / BriefAssembler / Agent tools) to go
through ``LedgerStore`` happens in Phase 2.

Design principles
~~~~~~~~~~~~~~~~~
* **No behaviour change** in underlying services. Inner stores keep their
  APIs; this is strictly a facade.
* **Lazy instantiation**: wrapped services are created on first access so
  projects that never touch milestones / entities pay no import cost.
* **Graceful degradation**: if a store (e.g. ``vector_store``) is missing
  the corresponding queries return empty results rather than raising.
* **Read-heavy**: writes are passed through unchanged; no new business
  logic is introduced here.
* **Plain dicts out**: returns untyped ``dict`` / ``list[dict]`` so
  callers stay loosely coupled to the models inside each service.

Future work (Phase 2)
~~~~~~~~~~~~~~~~~~~~~
* Migrate ``ConsistencyChecker`` to read via ``LedgerStore``.
* Migrate ``BriefAssembler`` / ``ContinuityService`` snapshot assembly
  to ``LedgerStore.snapshot_for_chapter``.
* Expose ``LedgerStore`` on the Agent tool layer.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — import cost only at type-check time
    from src.novel.services.character_arc_tracker import CharacterArcTracker
    from src.novel.services.entity_service import EntityService
    from src.novel.services.foreshadowing_service import ForeshadowingService
    from src.novel.services.milestone_tracker import MilestoneTracker
    from src.novel.services.obligation_tracker import ObligationTracker
    from src.novel.storage.knowledge_graph import KnowledgeGraph
    from src.novel.storage.structured_db import StructuredDB

log = logging.getLogger("novel.services.ledger_store")


class LedgerStore:
    """Unified facade over narrative ledger services.

    Provides a single entry point for reading (and forwarding writes to)
    the narrative ledger: foreshadowings, debts, character states,
    character arcs, world facts, and milestones.

    The underlying services/stores are not replaced — this class just
    wraps them. Phase 2 will migrate Agent / service callers to use
    ``LedgerStore`` instead of instantiating the individual trackers.

    Args:
        project_path: Root of the novel project workspace (used only as
            an identity tag and for future extensions; current queries do
            not touch the filesystem directly).
        db: A ``StructuredDB`` instance, or ``None`` for in-memory
            degraded mode (debts/character-state queries will return
            empty results when ``db`` is ``None``).
        kg: A ``KnowledgeGraph`` instance, or ``None`` for degraded mode
            (foreshadowing queries will return empty results).
        vector_store: Optional ``VectorStore`` (Chroma) — used by the
            foreshadowing service for detail search. ``None`` is fine;
            detail-based methods degrade silently.
        novel_data: Optional novel JSON dict (``outline.volumes`` must be
            present for milestone queries). If ``None``, milestone
            queries return empty results.
    """

    def __init__(
        self,
        project_path: str | Path,
        db: "StructuredDB | None" = None,
        kg: "KnowledgeGraph | None" = None,
        vector_store: Any | None = None,
        novel_data: dict | None = None,
    ) -> None:
        self.project_path = Path(project_path)
        self.db = db
        self.kg = kg
        self.vector_store = vector_store
        self.novel_data = novel_data or {}

        # Lazy-built service wrappers
        self._obligation_tracker: ObligationTracker | None = None
        self._foreshadowing_service: ForeshadowingService | None = None
        self._character_arc_tracker: CharacterArcTracker | None = None
        self._milestone_tracker: MilestoneTracker | None = None
        self._entity_service: EntityService | None = None

    # ------------------------------------------------------------------
    # Lazy service accessors
    # ------------------------------------------------------------------

    @property
    def obligation_tracker(self) -> "ObligationTracker":
        if self._obligation_tracker is None:
            from src.novel.services.obligation_tracker import ObligationTracker

            self._obligation_tracker = ObligationTracker(db=self.db)
        return self._obligation_tracker

    @property
    def foreshadowing_service(self) -> "ForeshadowingService | None":
        """Return the wrapped ForeshadowingService, or ``None`` if ``kg`` missing."""
        if self.kg is None:
            return None
        if self._foreshadowing_service is None:
            from src.novel.services.foreshadowing_service import ForeshadowingService

            self._foreshadowing_service = ForeshadowingService(
                knowledge_graph=self.kg,
                llm_client=None,
                novel_memory=None,
            )
        return self._foreshadowing_service

    @property
    def character_arc_tracker(self) -> "CharacterArcTracker":
        if self._character_arc_tracker is None:
            from src.novel.services.character_arc_tracker import CharacterArcTracker

            self._character_arc_tracker = CharacterArcTracker()
        return self._character_arc_tracker

    @property
    def milestone_tracker(self) -> "MilestoneTracker | None":
        """Return the wrapped MilestoneTracker, or ``None`` if no novel_data."""
        if not self.novel_data:
            return None
        if self._milestone_tracker is None:
            from src.novel.services.milestone_tracker import MilestoneTracker

            self._milestone_tracker = MilestoneTracker(self.novel_data)
        return self._milestone_tracker

    @property
    def entity_service(self) -> "EntityService | None":
        """Return the wrapped EntityService, or ``None`` if ``db`` missing."""
        if self.db is None:
            return None
        if self._entity_service is None:
            from src.novel.services.entity_service import EntityService

            self._entity_service = EntityService(db=self.db, llm_client=None)
        return self._entity_service

    # ==================================================================
    # Read API
    # ==================================================================

    # -- Foreshadowings -------------------------------------------------

    def list_foreshadowings(
        self,
        status: str | None = None,
        chapter_range: tuple[int, int] | None = None,
    ) -> list[dict]:
        """List foreshadowing nodes from the knowledge graph.

        Args:
            status: Optional status filter (``pending`` / ``collected``).
                When ``None``, pending foreshadowings are returned.
            chapter_range: Optional ``(min_chapter, max_chapter)`` inclusive
                filter applied to ``planted_chapter``.

        Returns:
            List of foreshadowing dicts. Empty list when the knowledge
            graph is unavailable.
        """
        if self.kg is None:
            return []

        # get_pending_foreshadowings needs a "current_chapter"; use a
        # very large horizon to return everything still pending, then
        # filter.
        try:
            horizon = 10**9
            raw = self.kg.get_pending_foreshadowings(current_chapter=horizon)
        except Exception as exc:
            log.debug("list_foreshadowings failed: %s", exc)
            return []

        results: list[dict] = list(raw)

        # Status filter: the underlying method already returns only
        # ``pending``. If caller asks for non-pending, return [] (the
        # current graph API exposes no bulk query; extending it is a
        # Phase 2 task).
        if status is not None and status != "pending":
            return []

        if chapter_range is not None:
            lo, hi = chapter_range
            results = [
                f for f in results
                if lo <= int(f.get("planted_chapter", 0)) <= hi
            ]

        return results

    # -- Debts ----------------------------------------------------------

    def list_debts(
        self,
        status: str | None = None,
        overdue_only: bool = False,
    ) -> list[dict]:
        """List debts from the obligation tracker / structured DB.

        Args:
            status: Optional status filter. When ``None``, all statuses
                returned.
            overdue_only: When ``True``, only debts with status
                ``overdue`` are returned (overrides ``status``).

        Returns:
            List of debt dicts. Empty list when ``db`` is ``None``.
        """
        if self.db is None:
            return []

        try:
            if overdue_only:
                return list(self.db.query_debts(status="overdue"))
            if status is not None:
                return list(self.db.query_debts(status=status))
            return list(self.db.query_debts())
        except Exception as exc:
            log.debug("list_debts failed: %s", exc)
            return []

    # -- Character state ------------------------------------------------

    def get_character_state(
        self,
        character_name: str,
        chapter_number: int,
    ) -> dict | None:
        """Look up the latest character state at / before *chapter_number*.

        Resolves ``character_name`` to a ``character_id`` via ``novel_data``
        when possible; otherwise falls back to treating the name as the id
        (older projects stored states keyed on name).

        Returns:
            The state dict (fields like ``health`` / ``location`` /
            ``emotional_state``), or ``None`` when not found / unavailable.
        """
        if self.db is None or not character_name:
            return None

        char_id = self._resolve_character_id(character_name) or character_name

        try:
            return self.db.get_character_state(char_id, chapter=chapter_number)
        except Exception as exc:
            log.debug("get_character_state failed: %s", exc)
            return None

    def list_character_arcs(
        self,
        character_name: str | None = None,
    ) -> list[dict]:
        """List tracked character-arc states.

        Args:
            character_name: Optional name filter. When ``None``, all
                tracked characters are returned.

        Returns:
            List of ``{"name": str, ...arc_state}`` dicts.
        """
        try:
            all_states = self.character_arc_tracker.get_all_states()
        except Exception as exc:
            log.debug("list_character_arcs failed: %s", exc)
            return []

        if character_name is not None:
            state = all_states.get(character_name)
            if not state:
                return []
            return [{"name": character_name, **state}]

        return [{"name": name, **state} for name, state in all_states.items()]

    # -- World facts / terms --------------------------------------------

    def get_world_facts(self, category: str | None = None) -> list[dict]:
        """List world-building facts (``terms`` table) from ``StructuredDB``.

        Args:
            category: Optional category filter.

        Returns:
            List of term dicts. Empty list when ``db`` is ``None``.
        """
        if self.db is None:
            return []

        try:
            terms = list(self.db.get_all_terms())
        except Exception as exc:
            log.debug("get_world_facts failed: %s", exc)
            return []

        if category is not None:
            terms = [t for t in terms if t.get("category") == category]
        return terms

    # -- Milestones -----------------------------------------------------

    def list_milestones(
        self,
        chapter_range: tuple[int, int] | None = None,
    ) -> list[dict]:
        """List narrative milestones across volumes.

        Args:
            chapter_range: Optional ``(min_chapter, max_chapter)`` filter.
                A milestone is included when its ``target_chapter_range``
                intersects the requested range.

        Returns:
            List of milestone dicts (``milestone_id`` / ``description`` /
            ``status`` / ``target_chapter_range`` etc.). Empty when
            ``novel_data`` is missing.
        """
        tracker = self.milestone_tracker
        if tracker is None:
            return []

        out: list[dict] = []
        for volume in tracker.volumes:
            for m in volume.get("narrative_milestones", []) or []:
                if not isinstance(m, dict):
                    continue
                if chapter_range is not None:
                    lo, hi = chapter_range
                    target = m.get("target_chapter_range") or [0, 10**9]
                    if len(target) != 2:
                        continue
                    m_lo, m_hi = target[0], target[1]
                    # intersection non-empty?
                    if m_hi < lo or m_lo > hi:
                        continue
                out.append(dict(m))
        return out

    # ==================================================================
    # Write API (thin forwarding)
    # ==================================================================

    def record_debt(
        self,
        debt_id: str,
        source_chapter: int,
        debt_type: str,
        description: str,
        **kwargs: Any,
    ) -> None:
        """Forward to :meth:`ObligationTracker.add_debt`."""
        self.obligation_tracker.add_debt(
            debt_id=debt_id,
            source_chapter=source_chapter,
            debt_type=debt_type,
            description=description,
            **kwargs,
        )

    def record_foreshadowing(
        self,
        chapter_brief: dict,
        chapter_number: int,
    ) -> int:
        """Forward to :meth:`ForeshadowingService.register_planned_foreshadowings`.

        Returns the count registered, or ``0`` when the knowledge graph
        is unavailable.
        """
        svc = self.foreshadowing_service
        if svc is None:
            return 0
        return svc.register_planned_foreshadowings(
            chapter_brief=chapter_brief,
            chapter_number=chapter_number,
        )

    def record_character_state(
        self,
        character_name: str,
        chapter: int,
        **fields: Any,
    ) -> None:
        """Forward to :meth:`StructuredDB.insert_character_state`.

        No-op when ``db`` is ``None``.
        """
        if self.db is None:
            return
        char_id = self._resolve_character_id(character_name) or character_name
        try:
            self.db.insert_character_state(
                character_id=char_id,
                chapter=chapter,
                **fields,
            )
        except Exception as exc:
            log.debug("record_character_state failed: %s", exc)

    # ==================================================================
    # Snapshot
    # ==================================================================

    def snapshot_for_chapter(self, chapter_number: int) -> dict:
        """Aggregate a ledger snapshot for upcoming chapter *chapter_number*.

        Intended for :class:`BriefAssembler` / :class:`ChapterPlanner` so
        they can fetch everything they need in one call. Each field is
        safe to inspect even when the corresponding backend is missing
        — it will simply be an empty list.

        Returns:
            Dict with keys:

            * ``pending_debts``: debts with ``status`` in ``pending``/
              ``overdue`` (from ``ObligationTracker``, urgency-sorted).
            * ``plantable_foreshadowings``: pending foreshadowings not
              yet collected (still plantable / referenceable).
            * ``collectable_foreshadowings``: pending foreshadowings
              whose ``target_chapter`` is ``<= chapter_number`` (ready
              to be collected).
            * ``active_characters``: character-arc states with
              ``last_appearance`` within 5 chapters of *chapter_number*.
            * ``world_facts``: all terms (world facts) registered.
            * ``pending_milestones``: milestones whose target range
              includes *chapter_number* and status is ``pending``.
        """
        # Debts
        pending_debts: list[dict] = []
        try:
            pending_debts = list(
                self.obligation_tracker.get_debts_for_chapter(chapter_number)
            )
        except Exception as exc:
            log.debug("snapshot pending_debts failed: %s", exc)

        # Foreshadowings
        plantable: list[dict] = []
        collectable: list[dict] = []
        if self.kg is not None:
            try:
                raw = list(
                    self.kg.get_pending_foreshadowings(current_chapter=chapter_number)
                )
            except Exception as exc:
                log.debug("snapshot foreshadowings failed: %s", exc)
                raw = []

            for item in raw:
                target = int(item.get("target_chapter", -1) or -1)
                if 0 < target <= chapter_number:
                    collectable.append(item)
                else:
                    plantable.append(item)

        # Active characters (arc tracker)
        active_chars: list[dict] = []
        try:
            for name, state in self.character_arc_tracker.get_all_states().items():
                last_seen = state.get("last_appearance", 0) or 0
                if chapter_number - last_seen <= 5:
                    active_chars.append({"name": name, **state})
        except Exception as exc:
            log.debug("snapshot active_chars failed: %s", exc)

        # World facts
        world_facts = self.get_world_facts()

        # Pending milestones
        pending_milestones: list[dict] = []
        tracker = self.milestone_tracker
        if tracker is not None:
            try:
                pending_milestones = [
                    {
                        "milestone_id": m.milestone_id,
                        "description": m.description,
                        "target_chapter_range": list(m.target_chapter_range),
                        "verification_type": m.verification_type,
                    }
                    for m in tracker.get_milestones_for_chapter(chapter_number)
                ]
            except Exception as exc:
                log.debug("snapshot pending_milestones failed: %s", exc)

        return {
            "pending_debts": pending_debts,
            "plantable_foreshadowings": plantable,
            "collectable_foreshadowings": collectable,
            "active_characters": active_chars,
            "world_facts": world_facts,
            "pending_milestones": pending_milestones,
        }

    # ==================================================================
    # Internal helpers
    # ==================================================================

    def _resolve_character_id(self, character_name: str) -> str | None:
        """Map *character_name* to ``character_id`` via ``novel_data``.

        Novel JSON stores characters under ``characters`` (list of dicts
        with ``name`` + ``character_id``). Returns ``None`` when no match
        is found.
        """
        if not character_name or not self.novel_data:
            return None

        characters = self.novel_data.get("characters")
        if not characters:
            return None

        for char in characters:
            if not isinstance(char, dict):
                continue
            if char.get("name") == character_name:
                cid = char.get("character_id")
                if cid:
                    return str(cid)
        return None
