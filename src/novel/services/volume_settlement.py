"""Volume settlement — detect and enforce debt resolution at volume boundaries.

Also provides arc phase auto-progression: as chapters advance, story arcs
automatically transition through setup → escalation → climax → resolution.

Intervention A adds milestone settlement logic: at the end of each volume,
incomplete milestones are either inherited to the next volume or abandoned.

Example::

    vs = VolumeSettlement(db=structured_db, outline=outline_dict)
    brief = vs.get_settlement_brief(chapter_num=28)
    if brief["is_settlement_zone"]:
        # Inject brief["settlement_prompt"] into Writer
        ...

    changed = vs.advance_arc_phases(current_chapter=15)
    arc_prompt = vs.get_arc_prompt(current_chapter=15)

    # Milestone settlement at volume boundary
    report = vs.settle_volume_milestones(volume_number=1, novel_data=novel_dict)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

log = logging.getLogger("novel.services")


class VolumeSettlement:
    """Manages debt settlement at volume boundaries.

    Args:
        db: StructuredDB instance
        outline: Novel outline dict (from novel.json)
    """

    def __init__(self, db: Any, outline: dict) -> None:
        self.db = db
        self.outline = outline
        self.volumes = self._parse_volumes()

    def _parse_volumes(self) -> list[dict]:
        """Parse volume info from outline.

        Returns list of {volume_number, start_chapter, end_chapter, title}.
        If no explicit volumes, treat every 30 chapters as a volume.
        """
        volumes = self.outline.get("volumes", [])
        if volumes:
            return volumes

        # Fallback: infer from chapter count
        chapters = self.outline.get("chapters", [])
        total = len(chapters)
        if total == 0:
            return []

        per_volume = 30
        result = []
        for i in range(0, total, per_volume):
            result.append({
                "volume_number": i // per_volume + 1,
                "start_chapter": i + 1,
                "end_chapter": min(i + per_volume, total),
                "title": f"第{i // per_volume + 1}卷",
            })
        return result

    def get_current_volume(self, chapter_num: int) -> dict | None:
        """Get the volume that contains the given chapter."""
        for v in self.volumes:
            start = v.get("start_chapter", 0)
            end = v.get("end_chapter", 0)
            if start <= chapter_num <= end:
                return v
        return None

    def is_volume_ending(self, chapter_num: int, threshold: int = 3) -> bool:
        """Check if we're within *threshold* chapters of a volume end."""
        vol = self.get_current_volume(chapter_num)
        if not vol:
            return False
        end = vol.get("end_chapter", 0)
        return end - chapter_num < threshold

    def get_settlement_brief(self, chapter_num: int) -> dict:
        """Generate a settlement brief for the current chapter.

        Returns:
            {
                "is_settlement_zone": bool,
                "volume": {volume info} or None,
                "chapters_remaining": int,
                "must_resolve": [list of critical debts],
                "should_resolve": [list of important debts],
                "can_carry_over": [list of long-tail debts],
                "settlement_prompt": str  # Ready to inject into Writer
            }
        """
        vol = self.get_current_volume(chapter_num)
        if not vol:
            return {"is_settlement_zone": False, "settlement_prompt": ""}

        end = vol.get("end_chapter", 0)
        remaining = end - chapter_num
        is_ending = remaining < 3

        if not is_ending:
            return {
                "is_settlement_zone": False,
                "volume": vol,
                "chapters_remaining": remaining,
                "settlement_prompt": "",
            }

        # Query all pending debts from ObligationTracker
        from src.novel.services.obligation_tracker import ObligationTracker

        tracker = ObligationTracker(db=self.db)

        # Get debts up to current chapter
        pending_debts = tracker.get_debts_for_chapter(chapter_num)

        # Categorize debts
        must_resolve: list[dict] = []  # must_pay_next + overdue + high/critical urgency
        should_resolve: list[dict] = []  # pay_within_3
        can_carry_over: list[dict] = []  # long_tail_payoff

        for debt in pending_debts:
            dtype = debt.get("type", "")
            urgency = debt.get("urgency_level", "normal")
            status = debt.get("status", "pending")

            if status == "fulfilled":
                continue

            if dtype == "must_pay_next" or urgency in ("high", "critical") or status == "overdue":
                must_resolve.append(debt)
            elif dtype == "pay_within_3":
                should_resolve.append(debt)
            else:
                can_carry_over.append(debt)

        # Generate settlement prompt for Writer
        lines = [f"【卷末收束指令 — {vol.get('title', '')} 剩余{remaining}章】"]

        if must_resolve:
            lines.append(f"\n必须在本卷解决的债务 ({len(must_resolve)}个):")
            for d in must_resolve:
                lines.append(f"  - {d.get('description', '?')}")

        if should_resolve:
            lines.append(f"\n建议在本卷解决 ({len(should_resolve)}个):")
            for d in should_resolve[:5]:  # Limit to 5
                lines.append(f"  - {d.get('description', '?')}")

        if can_carry_over:
            lines.append(f"\n可延续到下卷 ({len(can_carry_over)}个，保留悬念)")

        lines.append("\n请在本章中推进以上债务的解决，确保本卷结束时主要矛盾得到阶段性解决。")

        # Milestone settlement warning (Intervention A)
        milestones = vol.get("narrative_milestones", [])
        critical_incomplete = [
            m
            for m in milestones
            if m.get("priority") == "critical"
            and m.get("status") != "completed"
        ]
        if critical_incomplete:
            lines.append("\n【卷级里程碑警告】")
            for m in critical_incomplete:
                lines.append(
                    f"  - 未完成关键里程碑：{m.get('description', '?')}"
                )
            lines.append(
                "请在本卷结束前确保以上里程碑得到解决或明确标记为继承。"
            )

        return {
            "is_settlement_zone": True,
            "volume": vol,
            "chapters_remaining": remaining,
            "must_resolve": must_resolve,
            "should_resolve": should_resolve,
            "can_carry_over": can_carry_over,
            "settlement_prompt": "\n".join(lines),
        }

    def get_volume_summary(self) -> list[dict]:
        """Get settlement status for all volumes.

        Returns list of volume dicts with debt counts.
        """
        from src.novel.services.obligation_tracker import ObligationTracker

        tracker = ObligationTracker(db=self.db)

        result = []
        for vol in self.volumes:
            start = vol.get("start_chapter", 0)
            end = vol.get("end_chapter", 0)

            # Count debts originating from this volume
            # get_debts_for_chapter returns debts with source_chapter < arg
            all_debts = tracker.get_debts_for_chapter(end + 1)
            vol_debts = [d for d in all_debts if start <= d.get("source_chapter", 0) <= end]

            pending = sum(1 for d in vol_debts if d.get("status") != "fulfilled")
            fulfilled = sum(1 for d in vol_debts if d.get("status") == "fulfilled")

            result.append({
                **vol,
                "debts_pending": pending,
                "debts_fulfilled": fulfilled,
                "debts_total": len(vol_debts),
                "settlement_rate": round(fulfilled / max(len(vol_debts), 1), 2),
            })

        return result

    # ------------------------------------------------------------------
    # Milestone settlement (Intervention A)
    # ------------------------------------------------------------------

    def settle_volume_milestones(
        self,
        volume_number: int,
        novel_data: dict,
    ) -> dict:
        """Generate a milestone completion report and handle incomplete milestones.

        At the end of each volume, this method:
        1. Counts completed / overdue / pending milestones.
        2. Inherits ``critical`` incomplete milestones to the next volume.
        3. Marks the rest as ``abandoned`` if this is the last volume.
        4. Stores a ``settlement_report`` dict on the volume.

        Mutations are applied in-place to *novel_data* so the caller can
        persist them back to ``novel.json``.

        Returns:
            A :class:`VolumeProgressReport`-shaped dict.
        """
        volumes = novel_data.get("outline", {}).get("volumes", [])
        current_volume = next(
            (v for v in volumes if v.get("volume_number") == volume_number),
            None,
        )
        if not current_volume:
            return {}

        milestones = current_volume.get("narrative_milestones", [])
        completed = [m for m in milestones if m.get("status") == "completed"]
        overdue = [m for m in milestones if m.get("status") == "overdue"]
        pending = [m for m in milestones if m.get("status") == "pending"]

        # Treat both pending and overdue as incomplete for settlement
        critical_incomplete = [
            m
            for m in (pending + overdue)
            if m.get("priority") == "critical"
        ]

        inherited_count = 0
        abandoned_count = 0

        # Find the next volume (by volume_number, not list index)
        next_volume = next(
            (v for v in volumes if v.get("volume_number") == volume_number + 1),
            None,
        )

        for m in critical_incomplete:
            if next_volume is not None:
                # Inherit to next volume
                if "narrative_milestones" not in next_volume:
                    next_volume["narrative_milestones"] = []
                inherited_m = dict(m)
                inherited_m["inherited_from_volume"] = volume_number
                inherited_m["status"] = "pending"
                next_volume["narrative_milestones"].insert(0, inherited_m)
                inherited_count += 1
                log.info(
                    "Inherited milestone %s to volume %d",
                    m.get("milestone_id", "?"),
                    volume_number + 1,
                )
            else:
                # Last volume -- mark as abandoned
                m["status"] = "abandoned"
                abandoned_count += 1
                log.warning(
                    "Abandoned milestone %s at last volume",
                    m.get("milestone_id", "?"),
                )

        total = len(milestones)
        report = {
            "volume_number": volume_number,
            "milestones_total": total,
            "milestones_completed": len(completed),
            "milestones_overdue": len(overdue),
            "milestones_abandoned": abandoned_count,
            "milestones_inherited_to_next": inherited_count,
            "completion_rate": len(completed) / max(total, 1),
            "settlement_timestamp": datetime.now().isoformat(),
        }

        current_volume["settlement_report"] = report
        return report

    # ------------------------------------------------------------------
    # Arc phase progression
    # ------------------------------------------------------------------

    def advance_arc_phases(self, current_chapter: int) -> list[dict]:
        """Auto-advance story arc phases based on chapter position.

        Phase rules:
        - 0-25% of arc chapters: setup
        - 25-50%: escalation
        - 50-75%: climax
        - 75-100%: resolution

        Returns list of arcs that changed phase.
        """
        arcs = self._get_active_arcs()
        changed: list[dict] = []

        for arc in arcs:
            chapters = arc.get("chapters", [])
            if isinstance(chapters, str):
                try:
                    chapters = json.loads(chapters)
                except (json.JSONDecodeError, TypeError):
                    chapters = []
            if not chapters:
                continue

            start_ch = min(chapters)
            end_ch = max(chapters)
            total_span = max(end_ch - start_ch, 1)

            if current_chapter < start_ch:
                continue  # Arc hasn't started yet

            progress = min((current_chapter - start_ch) / total_span, 1.0)

            # Determine target phase
            if progress >= 0.75:
                target_phase = "resolution"
            elif progress >= 0.5:
                target_phase = "climax"
            elif progress >= 0.25:
                target_phase = "escalation"
            else:
                target_phase = "setup"

            old_phase = arc.get("phase", "setup")

            # Mark completed if past the end
            if current_chapter > end_ch and arc.get("status") != "completed":
                with self.db.transaction() as cur:
                    cur.execute(
                        "UPDATE story_units SET status = 'completed', completion_rate = 1.0 WHERE arc_id = ?",
                        (arc["arc_id"],),
                    )
                changed.append({
                    "arc_id": arc["arc_id"],
                    "name": arc.get("name", "?"),
                    "old_phase": old_phase,
                    "new_phase": "completed",
                    "progress": 1.0,
                })
                continue

            # Update if phase changed
            if target_phase != old_phase:
                self.db.update_story_unit_progress(
                    arc_id=arc["arc_id"],
                    completion_rate=round(progress, 2),
                    phase=target_phase,
                )
                changed.append({
                    "arc_id": arc["arc_id"],
                    "name": arc.get("name", "?"),
                    "old_phase": old_phase,
                    "new_phase": target_phase,
                    "progress": round(progress, 2),
                })
            elif abs(progress - arc.get("completion_rate", 0)) > 0.05:
                # Just update completion_rate
                self.db.update_story_unit_progress(
                    arc_id=arc["arc_id"],
                    completion_rate=round(progress, 2),
                    phase=old_phase,
                )

        return changed

    def get_arc_prompt(self, current_chapter: int) -> str:
        """Generate arc-aware prompt for Writer.

        Tells the Writer what phase each arc is in and what's expected.
        """
        arcs = self._get_active_arcs()
        if not arcs:
            return ""

        phase_guidance = {
            "setup": "铺垫阶段 — 建立情境，引入冲突种子",
            "escalation": "升级阶段 — 加剧矛盾，提高stakes",
            "climax": "高潮阶段 — 主要冲突爆发，转折点",
            "resolution": "收束阶段 — 解决冲突，揭示后果",
        }

        lines: list[str] = ["【故事弧线推进指引】"]

        for arc in arcs:
            chapters = arc.get("chapters", [])
            if isinstance(chapters, str):
                try:
                    chapters = json.loads(chapters)
                except (json.JSONDecodeError, TypeError):
                    chapters = []
            if not chapters or current_chapter < min(chapters) or current_chapter > max(chapters):
                continue

            phase = arc.get("phase", "setup")
            guidance = phase_guidance.get(phase, "")
            lines.append(f"  {arc.get('name', '?')} [{phase}]: {guidance}")

            if arc.get("turning_point") and phase in ("climax", "resolution"):
                lines.append(f"    转折点: {arc['turning_point']}")

        return "\n".join(lines) if len(lines) > 1 else ""

    def _get_active_arcs(self) -> list[dict]:
        """Query active arcs from story_units table."""
        if self.db is None:
            return []
        try:
            with self.db.transaction() as cur:
                cur.execute(
                    "SELECT * FROM story_units WHERE status = 'active'"
                )
                rows = cur.fetchall()
                return [dict(row) for row in rows] if rows else []
        except Exception as exc:
            log.warning("Failed to query active arcs: %s", exc)
            return []
