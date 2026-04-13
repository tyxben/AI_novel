"""Tests for HealthService and HealthMetrics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.novel.models.health import HealthMetrics
from src.novel.services.health_service import HealthService, _progress_bar


# ---------------------------------------------------------------------------
# HealthMetrics model tests
# ---------------------------------------------------------------------------


class TestHealthMetrics:
    def test_defaults(self):
        m = HealthMetrics()
        assert m.foreshadowing_total == 0
        assert m.foreshadowing_collection_rate == 0.0
        assert m.milestone_total == 0
        assert m.character_total == 0
        assert m.entity_total == 0
        assert m.entity_consistency_score == 1.0
        assert m.debt_health == "healthy"
        assert m.overall_health_score == 0.0

    def test_model_dump_round_trip(self):
        m = HealthMetrics(
            foreshadowing_total=10,
            foreshadowing_collected=8,
            foreshadowing_collection_rate=0.8,
            overall_health_score=72.0,
        )
        d = m.model_dump()
        m2 = HealthMetrics(**d)
        assert m2.foreshadowing_total == 10
        assert m2.overall_health_score == 72.0

    def test_validation_bounds(self):
        with pytest.raises(Exception):
            HealthMetrics(foreshadowing_collection_rate=1.5)
        with pytest.raises(Exception):
            HealthMetrics(overall_health_score=-1)


# ---------------------------------------------------------------------------
# _progress_bar helper
# ---------------------------------------------------------------------------


class TestProgressBar:
    def test_zero(self):
        bar = _progress_bar(0.0)
        assert len(bar) == 10
        assert "\u2588" not in bar  # no filled blocks

    def test_full(self):
        bar = _progress_bar(1.0)
        assert len(bar) == 10
        assert "\u2591" not in bar  # no empty blocks

    def test_half(self):
        bar = _progress_bar(0.5)
        assert len(bar) == 10
        assert bar.count("\u2588") == 5

    def test_clamps_above_one(self):
        bar = _progress_bar(2.0)
        assert bar.count("\u2588") == 10

    def test_clamps_below_zero(self):
        bar = _progress_bar(-0.5)
        assert bar.count("\u2588") == 0


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_graph_with_foreshadowings(nodes: list[tuple[str, dict]]) -> MagicMock:
    """Create a mock knowledge graph with given node tuples."""
    import networkx as nx

    g = nx.MultiDiGraph()
    for nid, attrs in nodes:
        g.add_node(nid, **attrs)
    mock_kg = MagicMock()
    mock_kg.graph = g
    return mock_kg


def _make_structured_db(
    entities: list[dict] | None = None,
    character_state_rows: list[dict] | None = None,
) -> MagicMock:
    """Create a mock StructuredDB."""
    db = MagicMock()

    if entities is not None:
        db.get_all_entities.return_value = entities
    else:
        db.get_all_entities.return_value = []

    # Mock transaction context manager for character_states query
    import sqlite3
    from contextlib import contextmanager
    from unittest.mock import PropertyMock

    rows = character_state_rows or []

    @contextmanager
    def fake_transaction():
        cur = MagicMock()
        # Make fetchall return the rows filtered by the query params
        def execute_side_effect(query, params=None):
            cur._last_query = query
            cur._last_params = params

        cur.execute = MagicMock(side_effect=execute_side_effect)

        # Return rows as dicts with character_id key
        def fetchall_side_effect():
            return [{"character_id": r["character_id"]} for r in rows]

        cur.fetchall = MagicMock(side_effect=fetchall_side_effect)
        yield cur

    db.transaction = fake_transaction
    return db


# ---------------------------------------------------------------------------
# HealthService tests — foreshadowing
# ---------------------------------------------------------------------------


class TestForeshadowingMetrics:
    def test_no_graph(self):
        svc = HealthService(knowledge_graph=None)
        m = HealthMetrics()
        svc._compute_foreshadowing_metrics(m, current_chapter=10)
        assert m.foreshadowing_total == 0

    def test_empty_graph(self):
        kg = _make_graph_with_foreshadowings([])
        svc = HealthService(knowledge_graph=kg)
        m = HealthMetrics()
        svc._compute_foreshadowing_metrics(m, current_chapter=10)
        assert m.foreshadowing_total == 0

    def test_mixed_statuses(self):
        nodes = [
            ("fs1", {"type": "foreshadowing", "status": "collected"}),
            ("fs2", {"type": "foreshadowing", "status": "collected"}),
            ("fs3", {"type": "foreshadowing", "status": "abandoned"}),
            ("fs4", {"type": "foreshadowing", "status": "pending", "planted_chapter": 1}),
            ("fs5", {"type": "foreshadowing", "status": "pending", "planted_chapter": 8}),
            ("char1", {"type": "character", "name": "test"}),  # not a foreshadowing
        ]
        kg = _make_graph_with_foreshadowings(nodes)
        svc = HealthService(knowledge_graph=kg)
        m = HealthMetrics()
        svc._compute_foreshadowing_metrics(m, current_chapter=15)

        assert m.foreshadowing_total == 5
        assert m.foreshadowing_collected == 2
        assert m.foreshadowing_abandoned == 1
        # fs4 planted at ch1, current=15, gap=14 >= 10 -> forgotten
        # fs5 planted at ch8, current=15, gap=7 < 10 -> not forgotten
        assert m.foreshadowing_forgotten == 1
        assert m.foreshadowing_collection_rate == pytest.approx(0.4)

    def test_last_mentioned_chapter_used(self):
        nodes = [
            (
                "fs1",
                {
                    "type": "foreshadowing",
                    "status": "pending",
                    "planted_chapter": 1,
                    "last_mentioned_chapter": 18,
                },
            ),
        ]
        kg = _make_graph_with_foreshadowings(nodes)
        svc = HealthService(knowledge_graph=kg)
        m = HealthMetrics()
        svc._compute_foreshadowing_metrics(m, current_chapter=20)
        # gap = 20-18 = 2 < 10
        assert m.foreshadowing_forgotten == 0

    def test_graph_error_graceful(self):
        kg = MagicMock()
        kg.graph.nodes.side_effect = RuntimeError("boom")
        svc = HealthService(knowledge_graph=kg)
        m = HealthMetrics()
        svc._compute_foreshadowing_metrics(m, current_chapter=5)
        # Should not raise; metrics stay at defaults
        assert m.foreshadowing_total == 0


# ---------------------------------------------------------------------------
# HealthService tests — milestones
# ---------------------------------------------------------------------------


class TestMilestoneMetrics:
    def test_with_milestone_tracker(self):
        tracker = MagicMock()
        tracker.compute_volume_progress.return_value = {
            "milestones_completed": ["a", "b"],
            "milestones_pending": ["c"],
            "milestones_overdue": ["d"],
        }
        svc = HealthService(milestone_tracker=tracker)
        m = HealthMetrics()
        svc._compute_milestone_metrics(m, current_chapter=10, novel_data={})
        assert m.milestone_total == 4
        assert m.milestone_completed == 2
        assert m.milestone_overdue == 1
        assert m.milestone_completion_rate == pytest.approx(0.5)

    def test_tracker_returns_empty(self):
        tracker = MagicMock()
        tracker.compute_volume_progress.return_value = {}
        svc = HealthService(milestone_tracker=tracker)
        m = HealthMetrics()
        # Falls through to novel_data fallback
        svc._compute_milestone_metrics(m, current_chapter=10, novel_data={})
        assert m.milestone_total == 0

    def test_fallback_to_novel_data(self):
        novel_data = {
            "outline": {
                "volumes": [
                    {
                        "narrative_milestones": [
                            {"status": "completed"},
                            {"status": "pending", "target_chapter_range": [1, 5]},
                            {"status": "overdue"},
                        ]
                    },
                    {
                        "narrative_milestones": [
                            {"status": "pending", "target_chapter_range": [10, 20]},
                        ]
                    },
                ]
            }
        }
        svc = HealthService()  # no milestone_tracker
        m = HealthMetrics()
        svc._compute_milestone_metrics(m, current_chapter=8, novel_data=novel_data)
        # completed=1, overdue=1 (explicit), + ch8 > 5 so pending[0] also overdue
        assert m.milestone_total == 4
        assert m.milestone_completed == 1
        assert m.milestone_overdue == 2  # explicit overdue + pending past range

    def test_no_data_no_tracker(self):
        svc = HealthService()
        m = HealthMetrics()
        svc._compute_milestone_metrics(m, current_chapter=5, novel_data={})
        assert m.milestone_total == 0


# ---------------------------------------------------------------------------
# HealthService tests — character
# ---------------------------------------------------------------------------


class TestCharacterMetrics:
    def test_no_characters(self):
        svc = HealthService()
        m = HealthMetrics()
        svc._compute_character_metrics(m, current_chapter=10, novel_data={})
        assert m.character_total == 0
        assert m.character_active == 0

    def test_no_db(self):
        novel_data = {"characters": [{"name": "Alice"}, {"name": "Bob"}]}
        svc = HealthService(structured_db=None)
        m = HealthMetrics()
        svc._compute_character_metrics(m, current_chapter=10, novel_data=novel_data)
        assert m.character_total == 2
        assert m.character_active == 0  # can't determine without DB

    def test_with_db(self):
        novel_data = {
            "characters": [
                {"name": "Alice"},
                {"name": "Bob"},
                {"name": "Charlie"},
            ]
        }
        db = _make_structured_db(
            character_state_rows=[
                {"character_id": "alice_id"},
                {"character_id": "bob_id"},
            ]
        )
        svc = HealthService(structured_db=db)
        m = HealthMetrics()
        svc._compute_character_metrics(m, current_chapter=10, novel_data=novel_data)
        assert m.character_total == 3
        assert m.character_active == 2
        assert m.character_coverage == pytest.approx(2.0 / 3.0)

    def test_db_error_graceful(self):
        novel_data = {"characters": [{"name": "Alice"}]}
        db = MagicMock()
        db.transaction.side_effect = RuntimeError("db boom")
        svc = HealthService(structured_db=db)
        m = HealthMetrics()
        svc._compute_character_metrics(m, current_chapter=10, novel_data=novel_data)
        # Should not raise
        assert m.character_total == 1


# ---------------------------------------------------------------------------
# HealthService tests — entity
# ---------------------------------------------------------------------------


class TestEntityMetrics:
    def test_no_db(self):
        svc = HealthService(structured_db=None)
        m = HealthMetrics()
        svc._compute_entity_metrics(m)
        assert m.entity_total == 0
        assert m.entity_consistency_score == 1.0

    def test_with_entities(self):
        db = _make_structured_db(
            entities=[
                {"canonical_name": "李明", "entity_type": "character"},
                {"canonical_name": "王强", "entity_type": "character"},
                {"canonical_name": "九州", "entity_type": "location"},
            ]
        )
        svc = HealthService(structured_db=db)
        m = HealthMetrics()
        svc._compute_entity_metrics(m)
        assert m.entity_total == 3
        assert m.entity_conflict_count == 0
        assert m.entity_consistency_score == 1.0

    def test_db_error_graceful(self):
        db = MagicMock()
        db.get_all_entities.side_effect = RuntimeError("entity boom")
        svc = HealthService(structured_db=db)
        m = HealthMetrics()
        svc._compute_entity_metrics(m)
        assert m.entity_total == 0


# ---------------------------------------------------------------------------
# HealthService tests — debt
# ---------------------------------------------------------------------------


class TestDebtMetrics:
    def test_no_tracker(self):
        svc = HealthService(obligation_tracker=None)
        m = HealthMetrics()
        svc._compute_debt_metrics(m, current_chapter=10)
        assert m.debt_total == 0
        assert m.debt_health == "healthy"

    def test_healthy(self):
        tracker = MagicMock()
        tracker.get_debt_statistics.return_value = {
            "pending_count": 3,
            "overdue_count": 0,
        }
        svc = HealthService(obligation_tracker=tracker)
        m = HealthMetrics()
        svc._compute_debt_metrics(m, current_chapter=10)
        assert m.debt_total == 3
        assert m.debt_overdue == 0
        assert m.debt_health == "healthy"

    def test_warning(self):
        tracker = MagicMock()
        tracker.get_debt_statistics.return_value = {
            "pending_count": 5,
            "overdue_count": 2,
        }
        svc = HealthService(obligation_tracker=tracker)
        m = HealthMetrics()
        svc._compute_debt_metrics(m, current_chapter=10)
        assert m.debt_total == 7
        assert m.debt_overdue == 2
        assert m.debt_health == "warning"

    def test_critical(self):
        tracker = MagicMock()
        tracker.get_debt_statistics.return_value = {
            "pending_count": 2,
            "overdue_count": 5,
        }
        svc = HealthService(obligation_tracker=tracker)
        m = HealthMetrics()
        svc._compute_debt_metrics(m, current_chapter=10)
        assert m.debt_total == 7
        assert m.debt_overdue == 5
        assert m.debt_health == "critical"

    def test_fallback_to_get_summary(self):
        """When get_debt_statistics is absent, try get_summary_for_writer."""
        tracker = MagicMock(spec=[])  # empty spec = no methods
        tracker.get_summary_for_writer = MagicMock(return_value=["a", "b"])
        svc = HealthService(obligation_tracker=tracker)
        m = HealthMetrics()
        svc._compute_debt_metrics(m, current_chapter=10)
        assert m.debt_total == 2

    def test_tracker_error_graceful(self):
        tracker = MagicMock()
        tracker.get_debt_statistics.side_effect = RuntimeError("boom")
        svc = HealthService(obligation_tracker=tracker)
        m = HealthMetrics()
        svc._compute_debt_metrics(m, current_chapter=10)
        assert m.debt_total == 0


# ---------------------------------------------------------------------------
# HealthService tests — overall score
# ---------------------------------------------------------------------------


class TestOverallScore:
    def test_all_neutral_when_no_deps(self):
        """With no dependencies, all dimensions use neutral value 0.5 -> 50."""
        svc = HealthService()
        m = HealthMetrics()
        score = svc._compute_overall_score(m)
        assert score == pytest.approx(50.0)

    def test_perfect_score(self):
        """All dimensions at 100% with real data."""
        kg = _make_graph_with_foreshadowings([
            ("fs1", {"type": "foreshadowing", "status": "collected"}),
        ])
        db = _make_structured_db(entities=[{"canonical_name": "A", "entity_type": "char"}])
        tracker = MagicMock()
        tracker.get_debt_statistics.return_value = {
            "pending_count": 0, "overdue_count": 0,
        }

        svc = HealthService(
            structured_db=db,
            knowledge_graph=kg,
            obligation_tracker=tracker,
        )
        m = HealthMetrics(
            foreshadowing_total=1,
            foreshadowing_collected=1,
            foreshadowing_collection_rate=1.0,
            milestone_total=3,
            milestone_completed=3,
            milestone_completion_rate=1.0,
            character_total=5,
            character_active=5,
            character_coverage=1.0,
            entity_total=10,
            entity_conflict_count=0,
            entity_consistency_score=1.0,
            debt_total=0,
            debt_overdue=0,
            debt_health="healthy",
        )
        score = svc._compute_overall_score(m)
        assert score == pytest.approx(100.0)

    def test_forgotten_penalty(self):
        kg = _make_graph_with_foreshadowings([
            ("fs1", {"type": "foreshadowing", "status": "collected"}),
        ])
        svc = HealthService(knowledge_graph=kg)
        m = HealthMetrics(
            foreshadowing_total=1,
            foreshadowing_collected=1,
            foreshadowing_collection_rate=1.0,
            foreshadowing_forgotten=3,
        )
        score = svc._compute_overall_score(m)
        # Without forgotten: 0.25*1.0 + 0.25*0.5 + 0.20*0.5 + 0.15*0.5 + 0.15*0.5 = 0.625 -> 62.5
        # Penalty: min(10, 3*0.5) = 1.5
        assert score == pytest.approx(61.0)

    def test_penalty_capped_at_10(self):
        kg = _make_graph_with_foreshadowings([
            ("fs1", {"type": "foreshadowing", "status": "pending", "planted_chapter": 1}),
        ])
        svc = HealthService(knowledge_graph=kg)
        m = HealthMetrics(foreshadowing_forgotten=25)  # 25*0.5=12.5, capped at 10
        score = svc._compute_overall_score(m)
        # fs_score = NEUTRAL (0.5) since total==0
        # All neutral -> base 50. penalty = min(10, 25*0.5) = 10. score = 40.
        assert score == pytest.approx(40.0)

    def test_score_floor_at_zero(self):
        kg = _make_graph_with_foreshadowings([
            ("fs1", {"type": "foreshadowing", "status": "pending", "planted_chapter": 1}),
        ])
        svc = HealthService(knowledge_graph=kg)
        m = HealthMetrics(
            foreshadowing_forgotten=15,
            debt_health="critical",
            foreshadowing_total=10,
            foreshadowing_collected=0,
            foreshadowing_collection_rate=0.0,
            milestone_total=5,
            milestone_completed=0,
            milestone_completion_rate=0.0,
            character_total=5,
            character_active=0,
            character_coverage=0.0,
            entity_total=5,
            entity_consistency_score=0.0,
        )
        score = svc._compute_overall_score(m)
        assert score >= 0.0


# ---------------------------------------------------------------------------
# HealthService tests — compute_health_metrics integration
# ---------------------------------------------------------------------------


class TestComputeHealthMetrics:
    def test_full_computation_no_deps(self):
        """Full run with zero dependencies should produce sane defaults."""
        svc = HealthService()
        m = svc.compute_health_metrics(current_chapter=10, novel_data={})
        assert isinstance(m, HealthMetrics)
        assert m.overall_health_score == pytest.approx(50.0)

    def test_full_computation_with_novel_data(self):
        novel_data = {
            "characters": [{"name": "A"}, {"name": "B"}],
            "outline": {
                "volumes": [
                    {
                        "narrative_milestones": [
                            {"status": "completed"},
                            {"status": "pending", "target_chapter_range": [5, 10]},
                        ]
                    }
                ]
            },
        }
        svc = HealthService()
        m = svc.compute_health_metrics(current_chapter=8, novel_data=novel_data)
        assert m.milestone_total == 2
        assert m.milestone_completed == 1
        assert m.character_total == 2


# ---------------------------------------------------------------------------
# format_report tests
# ---------------------------------------------------------------------------


class TestFormatReport:
    def test_report_contains_sections(self):
        svc = HealthService()
        m = HealthMetrics(
            foreshadowing_total=10,
            foreshadowing_collected=8,
            foreshadowing_collection_rate=0.8,
            foreshadowing_forgotten=1,
            milestone_total=5,
            milestone_completed=3,
            milestone_completion_rate=0.6,
            milestone_overdue=1,
            character_total=10,
            character_active=9,
            character_coverage=0.9,
            entity_total=20,
            entity_conflict_count=0,
            entity_consistency_score=1.0,
            debt_total=3,
            debt_overdue=0,
            debt_health="healthy",
            overall_health_score=72.0,
        )
        report = svc.format_report(m)

        assert "72/100" in report
        assert "伏笔回收" in report
        assert "里程碑完成" in report
        assert "角色覆盖" in report
        assert "实体一致性" in report
        assert "叙事债务" in report
        assert "8/10 已回收" in report
        assert "1 即将遗忘" in report
        assert "3/5 完成" in report
        assert "1 逾期" in report
        assert "9/10 活跃" in report
        assert "0 冲突" in report
        assert "3 待解决" in report

    def test_report_no_forgotten_no_overdue(self):
        svc = HealthService()
        m = HealthMetrics(overall_health_score=50.0)
        report = svc.format_report(m)
        assert "即将遗忘" not in report
        assert "50/100" in report

    def test_report_is_string(self):
        svc = HealthService()
        m = HealthMetrics()
        report = svc.format_report(m)
        assert isinstance(report, str)
        # Should contain Unicode progress bar chars
        assert "\u2588" in report or "\u2591" in report
