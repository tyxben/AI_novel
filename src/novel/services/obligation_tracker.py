"""Runtime service for debt lifecycle management.

Manages the full lifecycle of narrative debts (obligations): creation,
escalation, fulfillment, querying, and prompt-ready summarization for
Writer injection.

Example::

    tracker = ObligationTracker(db)
    tracker.add_debt(
        debt_id="debt_5_0_abc123",
        source_chapter=5,
        debt_type="must_pay_next",
        description="主角答应师妹明天一起探索密林",
    )
    summary = tracker.get_summary_for_writer(chapter_num=6)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

log = logging.getLogger("novel.services")


class ObligationTracker:
    """Manages debt lifecycle: creation, escalation, fulfillment, query.

    Works with a StructuredDB instance that provides ``insert_debt``,
    ``query_debts``, and ``update_debt_status`` methods.  When *db* is
    ``None`` (e.g. during testing without a real database) the tracker
    falls back to an in-memory dict-based store.

    Args:
        db: A StructuredDB instance, or ``None`` for in-memory fallback.
    """

    def __init__(self, db=None) -> None:
        self.db = db
        # In-memory fallback when db is None
        self._mem_store: dict[str, dict] | None = None if db is not None else {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_debt(
        self,
        debt_id: str,
        source_chapter: int,
        debt_type: str,
        description: str,
        target_chapter: int | None = None,
        urgency_level: str = "normal",
        character_pending: list[str] | None = None,
        emotional_debt: str | None = None,
    ) -> None:
        """Add a new narrative debt.

        Args:
            debt_id: Unique identifier for the debt.
            source_chapter: Chapter number where the debt was created.
            debt_type: One of ``must_pay_next``, ``pay_within_3``,
                ``long_tail_payoff``.
            description: Human-readable description of the obligation.
            target_chapter: Optional chapter where the debt should be
                resolved.
            urgency_level: ``normal``, ``high``, or ``critical``.
            character_pending: Optional list of character-specific actions.
            emotional_debt: Optional description of unresolved emotional
                tension.
        """
        created_at = datetime.now(timezone.utc).isoformat()

        if self._mem_store is not None:
            self._mem_store[debt_id] = {
                "debt_id": debt_id,
                "source_chapter": source_chapter,
                "created_at": created_at,
                "type": debt_type,
                "description": description,
                "status": "pending",
                "urgency_level": urgency_level,
                "target_chapter": target_chapter,
                "fulfilled_at": None,
                "fulfillment_note": None,
                "character_pending": json.dumps(
                    character_pending or [], ensure_ascii=False
                ),
                "emotional_debt": emotional_debt,
                "escalation_history": json.dumps([]),
            }
        else:
            self.db.insert_debt(
                debt_id=debt_id,
                source_chapter=source_chapter,
                type=debt_type,
                description=description,
                status="pending",
                urgency_level=urgency_level,
                target_chapter=target_chapter,
                created_at=created_at,
                character_pending=character_pending or [],
                emotional_debt=emotional_debt,
                escalation_history=[],
            )

        log.info(
            "添加债务: %s (类型=%s, 来源章节=%d)",
            debt_id, debt_type, source_chapter,
        )

    def get_debts_for_chapter(self, chapter_num: int) -> list[dict]:
        """Get all pending/overdue debts relevant before *chapter_num*.

        Args:
            chapter_num: The upcoming chapter number.

        Returns:
            List of debt dicts with status ``pending`` or ``overdue``
            whose ``source_chapter`` is strictly less than *chapter_num*,
            ordered by urgency (critical first) then source_chapter.
        """
        if self._mem_store is not None:
            debts = [
                dict(d) for d in self._mem_store.values()
                if d["status"] in ("pending", "overdue")
                and d["source_chapter"] < chapter_num
            ]
            # Sort: critical > high > normal, then by source_chapter ASC
            urgency_order = {"critical": 0, "high": 1, "normal": 2}
            debts.sort(
                key=lambda d: (
                    urgency_order.get(d["urgency_level"], 9),
                    d["source_chapter"],
                )
            )
            return debts

        rows = self.db.query_debts(before_chapter=chapter_num)
        # Filter to pending/overdue only
        return [
            dict(r) for r in rows
            if r.get("status") in ("pending", "overdue")
        ]

    def mark_debt_fulfilled(
        self, debt_id: str, chapter_num: int, note: str | None = None
    ) -> None:
        """Mark a debt as fulfilled.

        Args:
            debt_id: The debt to mark as fulfilled.
            chapter_num: The chapter where the debt was resolved.
            note: Optional description of how the debt was resolved.
        """
        if self._mem_store is not None:
            if debt_id in self._mem_store:
                self._mem_store[debt_id]["status"] = "fulfilled"
                self._mem_store[debt_id]["fulfilled_at"] = str(chapter_num)
                self._mem_store[debt_id]["fulfillment_note"] = note
        else:
            self.db.update_debt_status(
                debt_id=debt_id,
                status="fulfilled",
                fulfilled_at=str(chapter_num),
                note=note,
            )

        log.info("债务 %s 已完成于第 %d 章", debt_id, chapter_num)

    def escalate_debts(self, current_chapter: int) -> int:
        """Check and escalate overdue debts.

        Escalation rules:

        - ``must_pay_next``: overdue if ``source_chapter + 1 < current_chapter``
        - ``pay_within_3``: overdue if ``source_chapter + 3 < current_chapter``
        - ``long_tail_payoff``: never auto-escalate

        Args:
            current_chapter: The chapter about to be generated.

        Returns:
            Number of debts that were escalated.
        """
        if self._mem_store is not None:
            return self._escalate_mem(current_chapter)
        return self._escalate_db(current_chapter)

    def get_summary_for_writer(
        self, chapter_num: int, max_tokens: int = 1000
    ) -> str:
        """Format debts into prompt-ready text for Writer injection.

        Debts are grouped by urgency (critical, high, normal) and
        truncated to fit within *max_tokens* (estimated at 1 Chinese
        character ~= 2 tokens).

        Args:
            chapter_num: The upcoming chapter number.
            max_tokens: Maximum estimated token budget.

        Returns:
            A formatted string ready for prompt injection, or ``""``
            when there are no relevant debts.
        """
        debts = self.get_debts_for_chapter(chapter_num)
        if not debts:
            return ""

        critical = [d for d in debts if d.get("urgency_level") == "critical"]
        high = [d for d in debts if d.get("urgency_level") == "high"]
        normal = [d for d in debts if d.get("urgency_level") == "normal"]

        lines: list[str] = ["## 待解决的叙事债务\n"]

        if critical:
            lines.append("### 必须在本章解决：")
            for debt in critical[:3]:
                lines.append(
                    f"- 第{debt['source_chapter']}章遗留："
                    f"{debt['description']}"
                )

        if high:
            lines.append("\n### 近期需要解决：")
            for debt in high[:2]:
                lines.append(
                    f"- 第{debt['source_chapter']}章遗留："
                    f"{debt['description']}"
                )

        if normal and len(lines) < 8:
            lines.append("\n### 长线伏笔：")
            for debt in normal[:2]:
                lines.append(
                    f"- 第{debt['source_chapter']}章遗留："
                    f"{debt['description']}"
                )

        summary = "\n".join(lines)

        # Token estimation: 1 Chinese char ≈ 2 tokens
        estimated_tokens = len(summary) * 2
        if estimated_tokens > max_tokens:
            truncate_at = max_tokens // 2
            summary = (
                summary[:truncate_at]
                + f"\n\n（已截断，完整债务列表共 {len(debts)} 项）"
            )

        return summary

    def get_debt_statistics(self) -> dict:
        """Return counts by status and type.

        Returns:
            Dict with keys like ``pending_count``, ``fulfilled_count``,
            ``overdue_count``, ``abandoned_count``, and
            ``avg_fulfillment_chapters``.
        """
        if self._mem_store is not None:
            return self._stats_mem()
        return self._stats_db()

    # ------------------------------------------------------------------
    # Internal: in-memory fallback
    # ------------------------------------------------------------------

    def _escalate_mem(self, current_chapter: int) -> int:
        assert self._mem_store is not None
        escalated = 0

        for debt in self._mem_store.values():
            if debt["status"] != "pending":
                continue

            debt_type = debt["type"]
            source = debt["source_chapter"]
            chapters_elapsed = current_chapter - source
            should_escalate = False
            new_urgency = debt["urgency_level"]

            if debt_type == "must_pay_next" and source + 1 < current_chapter:
                should_escalate = True
                new_urgency = "critical"
            elif debt_type == "pay_within_3" and source + 3 < current_chapter:
                should_escalate = True
                new_urgency = "high"
            # long_tail_payoff: never auto-escalate

            if should_escalate:
                history = json.loads(debt["escalation_history"])
                history.append({
                    "chapter": current_chapter,
                    "old_urgency": debt["urgency_level"],
                    "new_urgency": new_urgency,
                    "reason": (
                        f"{debt_type} 债务经过 {chapters_elapsed} 章未解决"
                    ),
                })
                debt["escalation_history"] = json.dumps(
                    history, ensure_ascii=False
                )
                debt["urgency_level"] = new_urgency
                debt["status"] = "overdue"
                escalated += 1
                log.warning(
                    "债务 %s 升级为 %s (来源: 第%d章, 当前: 第%d章)",
                    debt["debt_id"], new_urgency, source, current_chapter,
                )

        return escalated

    def _stats_mem(self) -> dict:
        assert self._mem_store is not None
        stats: dict = {}
        all_debts = list(self._mem_store.values())

        for status in ("pending", "fulfilled", "overdue", "abandoned"):
            stats[f"{status}_count"] = sum(
                1 for d in all_debts if d["status"] == status
            )

        # Average fulfillment time (in chapters)
        fulfilled = [
            d for d in all_debts if d["status"] == "fulfilled"
            and d.get("fulfilled_at") is not None
        ]
        if fulfilled:
            total_time = sum(
                int(d["fulfilled_at"]) - d["source_chapter"]
                for d in fulfilled
            )
            stats["avg_fulfillment_chapters"] = round(
                total_time / len(fulfilled), 2
            )
        else:
            stats["avg_fulfillment_chapters"] = 0

        return stats

    # ------------------------------------------------------------------
    # Internal: StructuredDB backend
    # ------------------------------------------------------------------

    def _escalate_db(self, current_chapter: int) -> int:
        # Get all pending debts
        rows = self.db.query_debts(status="pending")
        escalated = 0

        for row in rows:
            debt_type = row["type"]
            source = row["source_chapter"]
            chapters_elapsed = current_chapter - source
            should_escalate = False
            new_urgency = row["urgency_level"]

            if debt_type == "must_pay_next" and source + 1 < current_chapter:
                should_escalate = True
                new_urgency = "critical"
            elif debt_type == "pay_within_3" and source + 3 < current_chapter:
                should_escalate = True
                new_urgency = "high"
            # long_tail_payoff: never auto-escalate

            if should_escalate:
                history_raw = row.get("escalation_history")
                if history_raw and isinstance(history_raw, str):
                    try:
                        history = json.loads(history_raw)
                    except json.JSONDecodeError:
                        history = []
                else:
                    history = []

                history.append({
                    "chapter": current_chapter,
                    "old_urgency": row["urgency_level"],
                    "new_urgency": new_urgency,
                    "reason": (
                        f"{debt_type} 债务经过 {chapters_elapsed} 章未解决"
                    ),
                })

                # update_debt_status only updates status/fulfilled_at/note,
                # so we also need to update urgency_level + escalation_history
                # via a raw query if using real DB.
                # For now, update via the available interface:
                # Single transaction: update status + urgency + history atomically
                if hasattr(self.db, "transaction"):
                    with self.db.transaction() as cur:
                        cur.execute(
                            """UPDATE chapter_debts
                               SET status = 'overdue',
                                   urgency_level = ?,
                                   escalation_history = ?
                               WHERE debt_id = ?
                            """,
                            (
                                new_urgency,
                                json.dumps(history, ensure_ascii=False),
                                row["debt_id"],
                            ),
                        )
                else:
                    self.db.update_debt_status(
                        debt_id=row["debt_id"],
                        status="overdue",
                    )

                escalated += 1
                log.warning(
                    "债务 %s 升级为 %s (来源: 第%d章, 当前: 第%d章)",
                    row["debt_id"], new_urgency, source, current_chapter,
                )

        return escalated

    def _stats_db(self) -> dict:
        stats: dict = {}

        for status in ("pending", "fulfilled", "overdue", "abandoned"):
            rows = self.db.query_debts(status=status)
            stats[f"{status}_count"] = len(rows)

        # Average fulfillment time
        fulfilled_rows = self.db.query_debts(status="fulfilled")
        if fulfilled_rows:
            times = []
            for r in fulfilled_rows:
                fa = r.get("fulfilled_at")
                if fa is not None:
                    try:
                        times.append(int(fa) - r["source_chapter"])
                    except (ValueError, TypeError):
                        pass
            if times:
                stats["avg_fulfillment_chapters"] = round(
                    sum(times) / len(times), 2
                )
            else:
                stats["avg_fulfillment_chapters"] = 0
        else:
            stats["avg_fulfillment_chapters"] = 0

        return stats
