"""里程碑追踪服务 — 卷进度预算核心 (Intervention A)

Tracks narrative milestones for each volume, checks completion via keyword
matching (free) or LLM review (budget-friendly fallback), and computes
volume progress health status.

Example::

    tracker = MilestoneTracker(novel_data=novel_dict)
    completed = tracker.check_milestone_completion(
        chapter_num=28,
        chapter_text="...全文...",
    )
    progress = tracker.compute_volume_progress(chapter_num=28)
"""
from __future__ import annotations

import logging
import re
from typing import Any

from src.novel.models.narrative_control import NarrativeMilestone
from src.novel.utils import extract_json_from_llm

log = logging.getLogger("novel.services.milestone")


class MilestoneTracker:
    """负责里程碑完成度检查和状态更新。

    Operates directly on the ``novel_data`` dict (volumes are dicts loaded
    from ``novel.json``).  Mutations (mark completed / overdue) are applied
    in-place so that the caller can persist them back to disk.
    """

    def __init__(self, novel_data: dict) -> None:
        self.novel_data = novel_data
        self.volumes = novel_data.get("outline", {}).get("volumes", [])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_milestones_for_chapter(
        self, chapter_num: int
    ) -> list[NarrativeMilestone]:
        """获取当前章节应完成的待办里程碑。"""
        current_volume = self._get_volume_by_chapter(chapter_num)
        if not current_volume:
            return []

        milestones = current_volume.get("narrative_milestones", [])
        pending: list[NarrativeMilestone] = []
        for m_data in milestones:
            try:
                milestone = NarrativeMilestone(**m_data)
            except Exception:
                continue
            if milestone.status == "pending":
                min_ch, max_ch = milestone.target_chapter_range
                if min_ch <= chapter_num <= max_ch:
                    pending.append(milestone)
        return pending

    def check_milestone_completion(
        self,
        chapter_num: int,
        chapter_text: str,
        chapter_summary: str | None = None,
        llm_client: Any | None = None,
    ) -> list[str]:
        """检查本章是否完成了某个待办里程碑。

        Uses keyword matching first (free).  For ``llm_review`` type
        milestones, falls back to an LLM call if *llm_client* is provided.

        Returns:
            List of completed milestone IDs.
        """
        current_volume = self._get_volume_by_chapter(chapter_num)
        if not current_volume:
            return []

        milestones = current_volume.get("narrative_milestones", [])
        completed_ids: list[str] = []

        for m_data in milestones:
            try:
                milestone = NarrativeMilestone(**m_data)
            except Exception:
                continue

            if milestone.status != "pending":
                continue

            # Only check milestones whose range includes this chapter
            min_ch, max_ch = milestone.target_chapter_range
            if chapter_num < min_ch:
                continue

            is_completed = False

            if milestone.verification_type == "auto_keyword":
                keywords = milestone.verification_criteria
                if isinstance(keywords, str):
                    keywords = [keywords]
                is_completed = all(
                    self._contains_keyword(chapter_text, kw) for kw in keywords
                )

            elif milestone.verification_type == "llm_review":
                if llm_client is None:
                    log.warning(
                        "Milestone %s needs LLM but no client provided",
                        milestone.milestone_id,
                    )
                    continue

                try:
                    prompt = (
                        f"判断以下章节是否完成了里程碑：\n\n"
                        f"里程碑描述：{milestone.description}\n\n"
                        f"章节摘要：\n{chapter_summary or chapter_text[:1000]}\n\n"
                        f'返回 JSON：{{"completed": true/false, "reason": "简要理由"}}'
                    )
                    response = llm_client.chat(
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.3,
                        json_mode=True,
                        max_tokens=512,
                    )
                    result = extract_json_from_llm(response.content)
                    is_completed = (
                        result.get("completed", False) if result else False
                    )
                except Exception as exc:
                    log.warning(
                        "LLM milestone check failed for %s: %s",
                        milestone.milestone_id,
                        exc,
                    )
                    continue

            if is_completed:
                self._mark_milestone_completed(
                    milestone.milestone_id, chapter_num
                )
                completed_ids.append(milestone.milestone_id)
                log.info(
                    "Milestone %s completed at chapter %d",
                    milestone.milestone_id,
                    chapter_num,
                )

        return completed_ids

    def mark_overdue_milestones(self, current_chapter: int) -> list[str]:
        """标记已逾期的里程碑。

        Returns:
            List of newly-overdue milestone IDs.
        """
        overdue_ids: list[str] = []
        for volume in self.volumes:
            milestones = volume.get("narrative_milestones", [])
            for m_data in milestones:
                try:
                    milestone = NarrativeMilestone(**m_data)
                except Exception:
                    continue
                if milestone.status == "pending":
                    _, max_ch = milestone.target_chapter_range
                    if current_chapter > max_ch:
                        self._mark_milestone_overdue(milestone.milestone_id)
                        overdue_ids.append(milestone.milestone_id)
        return overdue_ids

    def compute_volume_progress(
        self, chapter_num: int
    ) -> dict[str, Any]:
        """计算当前卷的进度状态。

        Returns:
            Dict with keys: ``current_volume``, ``chapters_consumed``,
            ``chapters_remaining``, ``milestones_completed``,
            ``milestones_pending``, ``milestones_overdue``,
            ``progress_health`` (``on_track`` / ``behind_schedule`` /
            ``critical``).
        """
        current_volume = self._get_volume_by_chapter(chapter_num)
        if not current_volume:
            return {}

        start = current_volume["start_chapter"]
        end = current_volume["end_chapter"]
        consumed = chapter_num - start
        remaining = end - chapter_num + 1
        total_span = end - start + 1

        milestones = current_volume.get("narrative_milestones", [])
        completed = [m for m in milestones if m.get("status") == "completed"]
        pending = [m for m in milestones if m.get("status") == "pending"]
        overdue = [m for m in milestones if m.get("status") == "overdue"]

        total_milestones = len(milestones)
        if total_milestones == 0:
            progress_health = "on_track"
        else:
            completion_rate = len(completed) / total_milestones
            chapter_usage_rate = consumed / max(total_span, 1)
            if overdue:
                progress_health = "critical"
            elif chapter_usage_rate > 0.5 and completion_rate < 0.5:
                progress_health = "behind_schedule"
            else:
                progress_health = "on_track"

        return {
            "current_volume": {
                "number": current_volume.get("volume_number"),
                "title": current_volume.get("title", ""),
            },
            "chapters_consumed": consumed,
            "chapters_remaining": remaining,
            "milestones_completed": [
                m.get("description", "") for m in completed
            ],
            "milestones_pending": [
                m.get("description", "") for m in pending
            ],
            "milestones_overdue": [
                m.get("description", "") for m in overdue
            ],
            "progress_health": progress_health,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _mark_milestone_completed(
        self, milestone_id: str, chapter_num: int
    ) -> None:
        """Update milestone status to *completed* in-place."""
        for volume in self.volumes:
            for m in volume.get("narrative_milestones", []):
                if m.get("milestone_id") == milestone_id:
                    m["status"] = "completed"
                    m["completed_at_chapter"] = chapter_num
                    return

    def _mark_milestone_overdue(self, milestone_id: str) -> None:
        """Update milestone status to *overdue* in-place."""
        for volume in self.volumes:
            for m in volume.get("narrative_milestones", []):
                if m.get("milestone_id") == milestone_id:
                    m["status"] = "overdue"
                    return

    @staticmethod
    def _contains_keyword(text: str, keyword: str) -> bool:
        """Check whether *text* contains *keyword* (ignoring punctuation)."""
        clean_text = re.sub(r"[^\w\s]", "", text)
        clean_keyword = re.sub(r"[^\w\s]", "", keyword)
        return clean_keyword in clean_text

    def _get_volume_by_chapter(self, chapter_num: int) -> dict | None:
        """Return the volume dict that contains *chapter_num*."""
        for vol in self.volumes:
            start = vol.get("start_chapter", 0)
            end = vol.get("end_chapter", 0)
            if start <= chapter_num <= end:
                return vol
        return None
