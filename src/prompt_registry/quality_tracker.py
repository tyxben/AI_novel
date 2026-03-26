"""Quality Tracker -- block performance statistics and optimization marking."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.prompt_registry.registry import PromptRegistry

log = logging.getLogger("prompt_registry.quality")


class QualityTracker:
    """Tracks prompt block quality and identifies blocks needing optimization."""

    def __init__(self, registry: PromptRegistry):
        self.registry = registry

    def get_block_statistics(self, base_id: str) -> dict[str, Any]:
        """Get detailed statistics for a block.

        Returns: {
            "base_id": str,
            "avg_score": float | None,
            "usage_count": int,
            "needs_optimization": bool,
            "version": int,
            "block_type": str,
            "score_trend": "improving" | "declining" | "stable" | "unknown",
        }
        """
        block = self.registry.get_active_block(base_id)
        if block is None:
            return {
                "base_id": base_id,
                "avg_score": None,
                "usage_count": 0,
                "needs_optimization": False,
            }

        # Calculate trend from recent usages
        trend = self._calculate_trend(base_id)

        return {
            "base_id": base_id,
            "avg_score": block.avg_score,
            "usage_count": block.usage_count,
            "needs_optimization": block.needs_optimization,
            "version": block.version,
            "block_type": block.block_type,
            "score_trend": trend,
        }

    def _calculate_trend(self, base_id: str) -> str:
        """Calculate score trend for a block based on recent usages."""
        block = self.registry.get_active_block(base_id)
        if block is None:
            return "unknown"

        with self.registry._lock:
            assert self.registry._conn is not None
            cur = self.registry._conn.cursor()
            cur.execute(
                """SELECT quality_score FROM prompt_usages
                   WHERE quality_score IS NOT NULL AND block_ids LIKE ?
                   ORDER BY created_at DESC LIMIT 20""",
                (f"%{block.block_id}%",),
            )
            scores = [row["quality_score"] for row in cur.fetchall()]

        if len(scores) < 4:
            return "unknown"

        # Compare first half vs second half (recent vs older)
        mid = len(scores) // 2
        recent_avg = sum(scores[:mid]) / mid
        older_avg = sum(scores[mid:]) / (len(scores) - mid)

        diff = recent_avg - older_avg
        if diff > 0.5:
            return "improving"
        elif diff < -0.5:
            return "declining"
        return "stable"

    def get_block_weaknesses(self, base_id: str, limit: int = 10) -> list[str]:
        """Get aggregated weaknesses from usages that included this block."""
        block = self.registry.get_active_block(base_id)
        if block is None:
            return []

        with self.registry._lock:
            assert self.registry._conn is not None
            cur = self.registry._conn.cursor()
            cur.execute(
                """SELECT weaknesses FROM prompt_usages
                   WHERE block_ids LIKE ? AND weaknesses != '[]'
                   ORDER BY created_at DESC LIMIT ?""",
                (f"%{block.block_id}%", limit * 2),
            )
            rows = cur.fetchall()

        all_weaknesses: list[str] = []
        seen: set[str] = set()
        for row in rows:
            try:
                items = json.loads(row["weaknesses"])
                for w in items:
                    if w not in seen:
                        seen.add(w)
                        all_weaknesses.append(w)
            except (json.JSONDecodeError, TypeError):
                continue

        return all_weaknesses[:limit]

    def get_optimization_candidates(
        self, threshold: float = 6.0, min_usage: int = 10
    ) -> list[dict[str, Any]]:
        """Find blocks that need optimization, with their weaknesses.

        Returns list of dicts with block info + weaknesses for each candidate.
        """
        low_blocks = self.registry.analyze_performance(threshold, min_usage)
        candidates = []
        for block in low_blocks:
            weaknesses = self.get_block_weaknesses(block.base_id)
            stats = self.get_block_statistics(block.base_id)
            candidates.append(
                {
                    **stats,
                    "weaknesses": weaknesses,
                    "content_preview": (
                        block.content[:200] + "..."
                        if len(block.content) > 200
                        else block.content
                    ),
                }
            )
        return candidates
