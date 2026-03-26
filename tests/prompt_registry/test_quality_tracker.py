"""Comprehensive tests for QualityTracker."""

import json

import pytest

from src.prompt_registry.quality_tracker import QualityTracker
from src.prompt_registry.registry import PromptRegistry


@pytest.fixture
def registry(tmp_path):
    """Create a PromptRegistry with a temporary database."""
    db_path = str(tmp_path / "test_qt.db")
    reg = PromptRegistry(db_path=db_path)
    yield reg
    reg.close()


@pytest.fixture
def tracker(registry):
    """Create a QualityTracker backed by a fresh registry."""
    return QualityTracker(registry)


# ---------------------------------------------------------------------------
# Helper: seed usages with scores and weaknesses for a given block
# ---------------------------------------------------------------------------
def _seed_usages(
    registry: PromptRegistry,
    block_id: str,
    scores: list[float],
    weaknesses_per_usage: list[list[str]] | None = None,
) -> list[str]:
    """Record usages for *block_id* with given scores. Returns usage_ids."""
    usage_ids: list[str] = []
    for i, score in enumerate(scores):
        uid = registry.record_usage("tpl", [block_id], "writer", "default")
        ws = weaknesses_per_usage[i] if weaknesses_per_usage else []
        registry.update_usage_score(uid, score, weaknesses=ws)
        usage_ids.append(uid)
    return usage_ids


# =====================================================================
# get_block_statistics
# =====================================================================


class TestGetBlockStatistics:
    def test_returns_correct_fields(self, tracker, registry):
        registry.create_block("blk_a", "craft_technique", "Some content", agent="writer")
        block = registry.get_active_block("blk_a")
        _seed_usages(registry, block.block_id, [7.0, 8.0, 9.0, 8.0])

        stats = tracker.get_block_statistics("blk_a")
        assert stats["base_id"] == "blk_a"
        assert stats["avg_score"] is not None
        assert isinstance(stats["usage_count"], int)
        assert "needs_optimization" in stats
        assert "version" in stats
        assert "block_type" in stats
        assert stats["block_type"] == "craft_technique"
        assert stats["score_trend"] in ("improving", "declining", "stable", "unknown")

    def test_nonexistent_block_returns_defaults(self, tracker):
        stats = tracker.get_block_statistics("no_such_block")
        assert stats["base_id"] == "no_such_block"
        assert stats["avg_score"] is None
        assert stats["usage_count"] == 0
        assert stats["needs_optimization"] is False


# =====================================================================
# _calculate_trend
# =====================================================================


class TestCalculateTrend:
    def test_improving_scores(self, tracker, registry):
        """Recent scores higher than older scores -> 'improving'."""
        registry.create_block("trend_up", "anti_pattern", "x")
        block = registry.get_active_block("trend_up")
        # Older scores (inserted first, appear later in DESC order): low
        # Recent scores (inserted last, appear first in DESC order): high
        # We insert: [3, 3, 3, 3, 9, 9, 9, 9]
        # DESC query returns [9, 9, 9, 9, 3, 3, 3, 3]
        # recent_avg = 9, older_avg = 3 -> diff = 6 > 0.5 -> improving
        _seed_usages(registry, block.block_id, [3.0, 3.0, 3.0, 3.0, 9.0, 9.0, 9.0, 9.0])
        assert tracker._calculate_trend("trend_up") == "improving"

    def test_declining_scores(self, tracker, registry):
        """Recent scores lower than older scores -> 'declining'."""
        registry.create_block("trend_down", "anti_pattern", "x")
        block = registry.get_active_block("trend_down")
        # Insert: [9, 9, 9, 9, 3, 3, 3, 3]
        # DESC query returns [3, 3, 3, 3, 9, 9, 9, 9]
        # recent_avg = 3, older_avg = 9 -> diff = -6 < -0.5 -> declining
        _seed_usages(registry, block.block_id, [9.0, 9.0, 9.0, 9.0, 3.0, 3.0, 3.0, 3.0])
        assert tracker._calculate_trend("trend_down") == "declining"

    def test_stable_scores(self, tracker, registry):
        """Scores roughly equal -> 'stable'."""
        registry.create_block("trend_flat", "anti_pattern", "x")
        block = registry.get_active_block("trend_flat")
        _seed_usages(registry, block.block_id, [7.0, 7.0, 7.0, 7.0, 7.0, 7.0])
        assert tracker._calculate_trend("trend_flat") == "stable"

    def test_too_few_scores_returns_unknown(self, tracker, registry):
        """Fewer than 4 scored usages -> 'unknown'."""
        registry.create_block("trend_few", "anti_pattern", "x")
        block = registry.get_active_block("trend_few")
        _seed_usages(registry, block.block_id, [5.0, 6.0])
        assert tracker._calculate_trend("trend_few") == "unknown"

    def test_nonexistent_block_returns_unknown(self, tracker):
        assert tracker._calculate_trend("ghost") == "unknown"


# =====================================================================
# get_block_weaknesses
# =====================================================================


class TestGetBlockWeaknesses:
    def test_extracts_from_usages(self, tracker, registry):
        registry.create_block("weak_blk", "anti_pattern", "content")
        block = registry.get_active_block("weak_blk")
        _seed_usages(
            registry,
            block.block_id,
            [5.0, 4.0],
            weaknesses_per_usage=[["dialogue weak"], ["pacing slow"]],
        )
        weaknesses = tracker.get_block_weaknesses("weak_blk")
        assert "dialogue weak" in weaknesses
        assert "pacing slow" in weaknesses

    def test_deduplicates(self, tracker, registry):
        registry.create_block("dedup_blk", "anti_pattern", "content")
        block = registry.get_active_block("dedup_blk")
        _seed_usages(
            registry,
            block.block_id,
            [5.0, 4.0, 3.0],
            weaknesses_per_usage=[
                ["dialogue weak", "pacing slow"],
                ["dialogue weak"],  # duplicate
                ["pacing slow", "new issue"],  # one duplicate, one new
            ],
        )
        weaknesses = tracker.get_block_weaknesses("dedup_blk")
        assert weaknesses.count("dialogue weak") == 1
        assert weaknesses.count("pacing slow") == 1
        assert "new issue" in weaknesses

    def test_respects_limit(self, tracker, registry):
        registry.create_block("limit_blk", "anti_pattern", "content")
        block = registry.get_active_block("limit_blk")
        many_weaknesses = [[f"issue_{i}"] for i in range(20)]
        _seed_usages(
            registry,
            block.block_id,
            [5.0] * 20,
            weaknesses_per_usage=many_weaknesses,
        )
        result = tracker.get_block_weaknesses("limit_blk", limit=3)
        assert len(result) <= 3

    def test_nonexistent_block_returns_empty(self, tracker):
        assert tracker.get_block_weaknesses("ghost_block") == []


# =====================================================================
# get_optimization_candidates
# =====================================================================


class TestGetOptimizationCandidates:
    def test_finds_low_scoring_blocks(self, tracker, registry):
        registry.create_block("low_cand", "anti_pattern", "low quality prompt")
        block = registry.get_active_block("low_cand")
        _seed_usages(
            registry,
            block.block_id,
            [4.0] * 12,
            weaknesses_per_usage=[["bad writing"]] * 12,
        )

        candidates = tracker.get_optimization_candidates(threshold=6.0, min_usage=10)
        assert len(candidates) >= 1
        found = [c for c in candidates if c["base_id"] == "low_cand"]
        assert len(found) == 1
        assert "weaknesses" in found[0]
        assert "content_preview" in found[0]

    def test_returns_empty_when_all_high(self, tracker, registry):
        registry.create_block("high_cand", "anti_pattern", "great prompt")
        block = registry.get_active_block("high_cand")
        _seed_usages(registry, block.block_id, [9.0] * 12)

        candidates = tracker.get_optimization_candidates(threshold=6.0, min_usage=10)
        assert not any(c["base_id"] == "high_cand" for c in candidates)

    def test_content_preview_truncated_for_long_content(self, tracker, registry):
        long_content = "A" * 300
        registry.create_block("long_cand", "anti_pattern", long_content)
        block = registry.get_active_block("long_cand")
        _seed_usages(registry, block.block_id, [3.0] * 12)

        candidates = tracker.get_optimization_candidates(threshold=6.0, min_usage=10)
        found = [c for c in candidates if c["base_id"] == "long_cand"]
        assert len(found) == 1
        assert found[0]["content_preview"].endswith("...")
        assert len(found[0]["content_preview"]) == 203  # 200 + "..."
