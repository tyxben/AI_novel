"""健康度计算服务 — 纯本地计算，零 LLM 成本。

每个 _compute_* 方法独立运行，单个维度失败不影响其他。
所有外部依赖 (structured_db / knowledge_graph / obligation_tracker /
milestone_tracker) 均可为 None，优雅降级。
"""

from __future__ import annotations

import logging
from typing import Any

from src.novel.models.health import HealthMetrics

log = logging.getLogger("novel")

# ---------------------------------------------------------------------------
# 进度条工具（纯 Unicode，不依赖 Rich）
# ---------------------------------------------------------------------------

_BAR_FILLED = "\u2588"   # █
_BAR_EMPTY = "\u2591"    # ░
_BAR_LENGTH = 10


def _progress_bar(ratio: float) -> str:
    """Return a 10-char Unicode bar like ``████████░░``."""
    filled = round(ratio * _BAR_LENGTH)
    filled = max(0, min(_BAR_LENGTH, filled))
    return _BAR_FILLED * filled + _BAR_EMPTY * (_BAR_LENGTH - filled)


# ---------------------------------------------------------------------------
# HealthService
# ---------------------------------------------------------------------------


class HealthService:
    """小说项目健康度计算服务"""

    # 综合得分权重
    _WEIGHT_FORESHADOWING = 0.25
    _WEIGHT_MILESTONE = 0.25
    _WEIGHT_CHARACTER = 0.20
    _WEIGHT_ENTITY = 0.15
    _WEIGHT_DEBT = 0.15

    # 缺失维度使用中性值
    _NEUTRAL = 0.5

    def __init__(
        self,
        structured_db: Any | None = None,
        knowledge_graph: Any | None = None,
        obligation_tracker: Any | None = None,
        milestone_tracker: Any | None = None,
    ) -> None:
        self.db = structured_db
        self.graph = knowledge_graph
        self.obligation_tracker = obligation_tracker
        self.milestone_tracker = milestone_tracker

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_health_metrics(
        self, current_chapter: int, novel_data: dict
    ) -> HealthMetrics:
        """计算完整健康度指标"""
        metrics = HealthMetrics()

        self._compute_foreshadowing_metrics(metrics, current_chapter)
        self._compute_milestone_metrics(metrics, current_chapter, novel_data)
        self._compute_character_metrics(metrics, current_chapter, novel_data)
        self._compute_entity_metrics(metrics)
        self._compute_debt_metrics(metrics, current_chapter)

        metrics.overall_health_score = self._compute_overall_score(metrics)
        return metrics

    def format_report(self, metrics: HealthMetrics) -> str:
        """格式化为可读文本报告（CLI 输出用）。

        Uses plain Unicode characters — no Rich dependency.
        """
        lines: list[str] = []
        lines.append("")
        lines.append("  小说健康度报告")
        lines.append("  " + "\u2501" * 36)  # ━

        score = metrics.overall_health_score
        lines.append(f"  总分: {score:.0f}/100")
        lines.append("")

        # -- 伏笔 --
        rate = metrics.foreshadowing_collection_rate
        bar = _progress_bar(rate)
        detail = (
            f"{metrics.foreshadowing_collected}/{metrics.foreshadowing_total} 已回收"
        )
        if metrics.foreshadowing_forgotten > 0:
            detail += f", {metrics.foreshadowing_forgotten} 即将遗忘"
        lines.append(
            f"  伏笔回收    {bar} {rate * 100:3.0f}%  ({detail})"
        )

        # -- 里程碑 --
        mrate = metrics.milestone_completion_rate
        mbar = _progress_bar(mrate)
        mdetail = f"{metrics.milestone_completed}/{metrics.milestone_total} 完成"
        if metrics.milestone_overdue > 0:
            mdetail += f", {metrics.milestone_overdue} 逾期"
        lines.append(
            f"  里程碑完成  {mbar} {mrate * 100:3.0f}%  ({mdetail})"
        )

        # -- 角色 --
        crate = metrics.character_coverage
        cbar = _progress_bar(crate)
        cdetail = f"{metrics.character_active}/{metrics.character_total} 活跃"
        lines.append(
            f"  角色覆盖    {cbar} {crate * 100:3.0f}%  ({cdetail})"
        )

        # -- 实体 --
        erate = metrics.entity_consistency_score
        ebar = _progress_bar(erate)
        edetail = f"{metrics.entity_conflict_count} 冲突"
        lines.append(
            f"  实体一致性  {ebar} {erate * 100:3.0f}%  ({edetail})"
        )

        # -- 债务 --
        debt_score_map = {"healthy": 1.0, "warning": 0.5, "critical": 0.0}
        drate = debt_score_map.get(metrics.debt_health, 0.5)
        dbar = _progress_bar(drate)
        ddetail = f"{metrics.debt_total} 待解决, {metrics.debt_overdue} 逾期"
        lines.append(
            f"  叙事债务    {dbar} {drate * 100:3.0f}%  ({ddetail})"
        )

        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Dimension: foreshadowing
    # ------------------------------------------------------------------

    def _compute_foreshadowing_metrics(
        self, metrics: HealthMetrics, current_chapter: int
    ) -> None:
        """从 knowledge_graph 计算伏笔指标"""
        if self.graph is None:
            return
        try:
            all_nodes = self.graph.graph.nodes(data=True)
            foreshadowings = [
                (nid, attrs)
                for nid, attrs in all_nodes
                if attrs.get("type") == "foreshadowing"
            ]

            metrics.foreshadowing_total = len(foreshadowings)
            metrics.foreshadowing_collected = sum(
                1
                for _, attrs in foreshadowings
                if attrs.get("status") == "collected"
            )
            metrics.foreshadowing_abandoned = sum(
                1
                for _, attrs in foreshadowings
                if attrs.get("status") == "abandoned"
            )

            # 即将遗忘（10 章未提及的 pending 伏笔）
            forgotten = 0
            for _nid, attrs in foreshadowings:
                if attrs.get("status") != "pending":
                    continue
                last_mention = attrs.get(
                    "last_mentioned_chapter",
                    attrs.get("planted_chapter", 0),
                )
                if current_chapter - last_mention >= 10:
                    forgotten += 1
            metrics.foreshadowing_forgotten = forgotten

            if metrics.foreshadowing_total > 0:
                metrics.foreshadowing_collection_rate = (
                    metrics.foreshadowing_collected / metrics.foreshadowing_total
                )
        except Exception:
            log.warning("伏笔指标计算失败", exc_info=True)

    # ------------------------------------------------------------------
    # Dimension: milestones
    # ------------------------------------------------------------------

    def _compute_milestone_metrics(
        self,
        metrics: HealthMetrics,
        current_chapter: int,
        novel_data: dict,
    ) -> None:
        """从 novel_data 的 volumes 计算里程碑指标

        Reads ``novel_data["outline"]["volumes"]`` directly — does NOT rely
        on MilestoneTracker. If ``milestone_tracker`` is available, use its
        ``compute_volume_progress`` instead for richer data.
        """
        try:
            if self.milestone_tracker is not None:
                progress = self.milestone_tracker.compute_volume_progress(
                    current_chapter
                )
                if progress:
                    completed_list = progress.get("milestones_completed", [])
                    pending_list = progress.get("milestones_pending", [])
                    overdue_list = progress.get("milestones_overdue", [])
                    metrics.milestone_total = (
                        len(completed_list) + len(pending_list) + len(overdue_list)
                    )
                    metrics.milestone_completed = len(completed_list)
                    metrics.milestone_overdue = len(overdue_list)
                    if metrics.milestone_total > 0:
                        metrics.milestone_completion_rate = (
                            metrics.milestone_completed / metrics.milestone_total
                        )
                    return

            # Fallback: read directly from novel_data
            volumes = (
                novel_data.get("outline", {}).get("volumes", [])
            )
            total = 0
            completed = 0
            overdue = 0
            for vol in volumes:
                milestones = vol.get("narrative_milestones", [])
                for m in milestones:
                    total += 1
                    status = m.get("status", "pending")
                    if status == "completed":
                        completed += 1
                    elif status == "overdue":
                        overdue += 1
                    elif status == "pending":
                        # Check if overdue based on chapter range
                        target_range = m.get("target_chapter_range")
                        if target_range and len(target_range) >= 2:
                            _, max_ch = target_range[0], target_range[1]
                            if current_chapter > max_ch:
                                overdue += 1

            metrics.milestone_total = total
            metrics.milestone_completed = completed
            metrics.milestone_overdue = overdue
            if total > 0:
                metrics.milestone_completion_rate = completed / total
        except Exception:
            log.warning("里程碑指标计算失败", exc_info=True)

    # ------------------------------------------------------------------
    # Dimension: character coverage
    # ------------------------------------------------------------------

    def _compute_character_metrics(
        self,
        metrics: HealthMetrics,
        current_chapter: int,
        novel_data: dict,
    ) -> None:
        """从 novel_data 的 characters + structured_db 的 character_states 计算角色覆盖"""
        try:
            characters = novel_data.get("characters", [])
            metrics.character_total = len(characters)
            if not characters:
                return

            if self.db is None:
                # Without DB, cannot determine active characters
                return

            # Query characters active in the last 10 chapters
            min_chapter = max(1, current_chapter - 9)
            active_ids: set[str] = set()

            with self.db.transaction() as cur:
                cur.execute(
                    "SELECT DISTINCT character_id FROM character_states "
                    "WHERE chapter >= ? AND chapter <= ?",
                    (min_chapter, current_chapter),
                )
                for row in cur.fetchall():
                    active_ids.add(row[0] if isinstance(row, (tuple, list)) else row["character_id"])

            metrics.character_active = len(active_ids)
            if metrics.character_total > 0:
                metrics.character_coverage = (
                    metrics.character_active / metrics.character_total
                )
        except Exception:
            log.warning("角色指标计算失败", exc_info=True)

    # ------------------------------------------------------------------
    # Dimension: entity consistency
    # ------------------------------------------------------------------

    def _compute_entity_metrics(self, metrics: HealthMetrics) -> None:
        """从 structured_db 计算实体一致性

        Conflict detection is intentionally lightweight: ``conflict_count``
        stays at 0 to avoid an expensive O(n^2) scan.  A full scan could be
        added later as a separate command.
        """
        if self.db is None:
            return
        try:
            entities = self.db.get_all_entities()
            metrics.entity_total = len(entities)
            # Conflict count intentionally 0 — full-scan too expensive for
            # a dashboard.  entity_consistency_score stays at 1.0 when there
            # are no detected conflicts.
            metrics.entity_conflict_count = 0
            if metrics.entity_total > 0:
                metrics.entity_consistency_score = 1.0 - (
                    metrics.entity_conflict_count / max(metrics.entity_total, 1)
                )
        except Exception:
            log.warning("实体指标计算失败", exc_info=True)

    # ------------------------------------------------------------------
    # Dimension: narrative debt
    # ------------------------------------------------------------------

    def _compute_debt_metrics(
        self, metrics: HealthMetrics, current_chapter: int
    ) -> None:
        """从 obligation_tracker 计算债务健康度"""
        if self.obligation_tracker is None:
            return
        try:
            if hasattr(self.obligation_tracker, "get_debt_statistics"):
                stats = self.obligation_tracker.get_debt_statistics()
                metrics.debt_total = stats.get("pending_count", 0) + stats.get(
                    "overdue_count", 0
                )
                metrics.debt_overdue = stats.get("overdue_count", 0)
            elif hasattr(self.obligation_tracker, "get_summary_for_writer"):
                summary = self.obligation_tracker.get_summary_for_writer(
                    chapter_num=current_chapter
                )
                # Best-effort parse: count items in the summary
                metrics.debt_total = len(summary) if isinstance(summary, list) else 0
            else:
                return

            # Determine health status
            if metrics.debt_overdue == 0:
                metrics.debt_health = "healthy"
            elif metrics.debt_overdue <= 2:
                metrics.debt_health = "warning"
            else:
                metrics.debt_health = "critical"
        except Exception:
            log.warning("债务指标计算失败", exc_info=True)

    # ------------------------------------------------------------------
    # Overall score
    # ------------------------------------------------------------------

    def _compute_overall_score(self, metrics: HealthMetrics) -> float:
        """加权综合得分 (0-100)。

        权重分配：
        - 伏笔回收率: 25%
        - 里程碑完成率: 25%
        - 角色覆盖率: 20%
        - 实体一致性: 15%
        - 债务健康度: 15%

        缺失维度（依赖不存在导致值为默认 0）使用中性值 0.5。
        """
        # Foreshadowing: use neutral if no data; floor at 0.2 so having
        # data (even imperfect) never scores worse than having none
        if self.graph is None or metrics.foreshadowing_total == 0:
            fs_score = self._NEUTRAL
        else:
            fs_score = max(0.2, metrics.foreshadowing_collection_rate)

        # Milestone
        if metrics.milestone_total == 0:
            ms_score = self._NEUTRAL
        else:
            ms_score = metrics.milestone_completion_rate

        # Character
        if metrics.character_total == 0:
            ch_score = self._NEUTRAL
        else:
            ch_score = metrics.character_coverage

        # Entity
        if self.db is None or metrics.entity_total == 0:
            en_score = self._NEUTRAL
        else:
            en_score = metrics.entity_consistency_score

        # Debt
        debt_score_map = {"healthy": 1.0, "warning": 0.5, "critical": 0.0}
        if self.obligation_tracker is None:
            dt_score = self._NEUTRAL
        else:
            dt_score = debt_score_map.get(metrics.debt_health, self._NEUTRAL)

        score = (
            fs_score * self._WEIGHT_FORESHADOWING
            + ms_score * self._WEIGHT_MILESTONE
            + ch_score * self._WEIGHT_CHARACTER
            + en_score * self._WEIGHT_ENTITY
            + dt_score * self._WEIGHT_DEBT
        ) * 100

        # Penalty: each forgotten foreshadowing -0.5 points (max -10)
        penalty = min(10, metrics.foreshadowing_forgotten * 0.5)
        score = max(0.0, score - penalty)

        return round(score, 1)
