"""Tests for P1 Foreshadowing Graph and P2 Health Dashboard.

Covers:
- ForeshadowingEdge / ForeshadowingStatus Pydantic models
- KnowledgeGraph foreshadowing operations (add, query, mark, stats)
- ForeshadowingService (register, verify, forgotten detection)
- HealthMetrics Pydantic model
- HealthService (compute metrics, overall score, format report)
"""
from __future__ import annotations

import importlib
from typing import Any

import networkx as nx
import pytest


# =========================================================================
# Conditional imports — skip gracefully if modules not yet implemented
# =========================================================================


def _try_import(module_path: str, names: list[str]) -> dict[str, Any]:
    """Import *names* from *module_path*, return dict or raise Skipped."""
    try:
        mod = importlib.import_module(module_path)
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.skip(f"{module_path} not available: {exc}")
    result = {}
    for name in names:
        if not hasattr(mod, name):
            pytest.skip(f"{module_path}.{name} not found")
        result[name] = getattr(mod, name)
    return result


# =========================================================================
# TestForeshadowingModels (3 tests)
# =========================================================================


class TestForeshadowingModels:
    """ForeshadowingEdge / ForeshadowingStatus Pydantic models."""

    def test_foreshadowing_edge_creation(self) -> None:
        ns = _try_import(
            "src.novel.models.foreshadowing",
            ["ForeshadowingEdge"],
        )
        ForeshadowingEdge = ns["ForeshadowingEdge"]

        edge = ForeshadowingEdge(
            from_foreshadowing_id="f_001",
            to_foreshadowing_id="f_002",
            relation_type="collect",
            description="主角解开封印",
        )
        assert edge.from_foreshadowing_id == "f_001"
        assert edge.to_foreshadowing_id == "f_002"
        assert edge.relation_type == "collect"
        assert edge.description == "主角解开封印"
        # edge_id auto-generated
        assert edge.edge_id is not None
        assert len(edge.edge_id) > 0

    def test_foreshadowing_status_creation(self) -> None:
        ns = _try_import(
            "src.novel.models.foreshadowing",
            ["ForeshadowingStatus"],
        )
        ForeshadowingStatus = ns["ForeshadowingStatus"]

        status = ForeshadowingStatus(
            foreshadowing_id="f_001",
            planted_chapter=3,
            target_chapter=15,
            status="pending",
            content="一把神秘的钥匙",
            chapters_since_plant=5,
            last_mentioned_chapter=6,
            is_forgotten=False,
        )
        assert status.foreshadowing_id == "f_001"
        assert status.planted_chapter == 3
        assert status.target_chapter == 15
        assert status.status == "pending"
        assert status.content == "一把神秘的钥匙"
        assert status.chapters_since_plant == 5
        assert status.last_mentioned_chapter == 6
        assert status.is_forgotten is False

    def test_foreshadowing_status_forgotten(self) -> None:
        ns = _try_import(
            "src.novel.models.foreshadowing",
            ["ForeshadowingStatus"],
        )
        ForeshadowingStatus = ns["ForeshadowingStatus"]

        status = ForeshadowingStatus(
            foreshadowing_id="f_002",
            planted_chapter=1,
            target_chapter=20,
            status="pending",
            content="被遗忘的预言",
            chapters_since_plant=18,
            last_mentioned_chapter=2,
            is_forgotten=True,
        )
        assert status.is_forgotten is True
        assert status.chapters_since_plant == 18


# =========================================================================
# TestKnowledgeGraphForeshadowing (6 tests)
# =========================================================================


class TestKnowledgeGraphForeshadowing:
    """KnowledgeGraph foreshadowing node/edge operations."""

    def _make_graph(self):
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        return KnowledgeGraph()

    def test_add_foreshadowing_node(self) -> None:
        graph = self._make_graph()
        graph.add_foreshadowing_node(
            foreshadowing_id="fs_001",
            planted_chapter=3,
            content="门前古树暗藏玄机",
            target_chapter=10,
            status="pending",
        )
        node = graph.get_node("fs_001")
        assert node is not None
        assert node["type"] == "foreshadowing"
        assert node["planted_chapter"] == 3
        assert node["content"] == "门前古树暗藏玄机"
        assert node["target_chapter"] == 10
        assert node["status"] == "pending"
        assert node["last_mentioned_chapter"] == 3  # defaults to planted_chapter

    def test_get_pending_foreshadowings(self) -> None:
        graph = self._make_graph()
        # 1 pending
        graph.add_foreshadowing_node(
            foreshadowing_id="fs_a",
            planted_chapter=1,
            content="伏笔A",
            status="pending",
        )
        # 1 collected (should NOT appear)
        graph.add_foreshadowing_node(
            foreshadowing_id="fs_b",
            planted_chapter=2,
            content="伏笔B",
            status="collected",
        )
        # 1 pending
        graph.add_foreshadowing_node(
            foreshadowing_id="fs_c",
            planted_chapter=4,
            content="伏笔C",
            status="pending",
        )

        pending = graph.get_pending_foreshadowings(current_chapter=5)
        assert len(pending) == 2
        ids = {p["foreshadowing_id"] for p in pending}
        assert ids == {"fs_a", "fs_c"}

    def test_mark_collected(self) -> None:
        graph = self._make_graph()
        graph.add_foreshadowing_node(
            foreshadowing_id="fs_x",
            planted_chapter=2,
            content="伏笔X",
            status="pending",
        )
        graph.mark_foreshadowing_collected("fs_x", collected_chapter=8)

        node = graph.get_node("fs_x")
        assert node["status"] == "collected"
        assert node["collected_chapter"] == 8

        # Should no longer appear in pending
        pending = graph.get_pending_foreshadowings(current_chapter=10)
        assert all(p["foreshadowing_id"] != "fs_x" for p in pending)

    def test_update_mention(self) -> None:
        graph = self._make_graph()
        graph.add_foreshadowing_node(
            foreshadowing_id="fs_m",
            planted_chapter=1,
            content="伏笔M",
            status="pending",
        )
        assert graph.get_node("fs_m")["last_mentioned_chapter"] == 1

        graph.update_foreshadowing_mention("fs_m", chapter=5)
        assert graph.get_node("fs_m")["last_mentioned_chapter"] == 5

    def test_forgotten_detection(self) -> None:
        graph = self._make_graph()
        graph.add_foreshadowing_node(
            foreshadowing_id="fs_old",
            planted_chapter=1,
            content="古老伏笔",
            status="pending",
        )
        # last_mentioned_chapter defaults to planted_chapter=1
        # current_chapter=15, chapters_since = 15-1 = 14 >= 10 => forgotten
        pending = graph.get_pending_foreshadowings(current_chapter=15)
        assert len(pending) == 1
        assert pending[0]["is_forgotten"] is True
        assert pending[0]["chapters_since_plant"] == 14

    def test_get_stats(self) -> None:
        graph = self._make_graph()
        # 2 pending
        graph.add_foreshadowing_node("fs_1", planted_chapter=1, content="A", status="pending")
        graph.add_foreshadowing_node("fs_2", planted_chapter=2, content="B", status="pending")
        # 1 collected
        graph.add_foreshadowing_node("fs_3", planted_chapter=3, content="C", status="collected")
        # 1 abandoned
        graph.add_foreshadowing_node("fs_4", planted_chapter=4, content="D", status="abandoned")
        # 1 non-foreshadowing node (should be ignored)
        graph.add_character("char_1", name="张三")

        stats = graph.get_foreshadowing_stats()
        assert stats["total"] == 4
        assert stats["pending"] == 2
        assert stats["collected"] == 1
        assert stats["abandoned"] == 1


# =========================================================================
# TestForeshadowingService (5 tests)
# =========================================================================


class TestForeshadowingService:
    """ForeshadowingService: register, verify, forgotten detection."""

    def _make_service(self):
        ns = _try_import(
            "src.novel.services.foreshadowing_service",
            ["ForeshadowingService"],
        )
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        ForeshadowingService = ns["ForeshadowingService"]
        kg = KnowledgeGraph()
        return ForeshadowingService(knowledge_graph=kg, llm_client=None), kg

    def test_register_plant(self) -> None:
        svc, kg = self._make_service()
        chapter_brief = {
            "foreshadowing_plant": ["古井中传来的低语"],
        }
        count = svc.register_planned_foreshadowings(chapter_brief, chapter_number=5)
        assert count >= 1

        pending = kg.get_pending_foreshadowings(current_chapter=6)
        assert len(pending) == 1
        assert "古井" in pending[0]["content"] or "低语" in pending[0]["content"]

    def test_register_collect(self) -> None:
        svc, kg = self._make_service()
        # First plant a foreshadowing
        kg.add_foreshadowing_node(
            foreshadowing_id="fs_planted",
            planted_chapter=1,
            content="门前古树暗藏传送阵",
            status="pending",
        )

        # Now register a collect that matches the planted one
        chapter_brief = {
            "foreshadowing_collect": ["古树传送阵被激活"],
        }
        svc.register_planned_foreshadowings(chapter_brief, chapter_number=8)

        # Check the planted foreshadowing is now collected
        node = kg.get_node("fs_planted")
        assert node["status"] == "collected"

    def test_verify_plants_in_text(self) -> None:
        svc, _kg = self._make_service()
        # The keyword extractor splits on punctuation and takes segments >= 2 chars.
        # "神秘，钥匙" => keywords ["神秘", "钥匙"].
        # The text must contain at least one of those keywords as a substring.
        chapter_text = "张三在地下室发现了一把神秘的钥匙，上面刻着奇怪的符文。"
        result = svc.verify_foreshadowings_in_text(
            chapter_text=chapter_text,
            chapter_number=5,
            planned_plants=["神秘，钥匙"],
            planned_collects=[],
        )
        assert len(result["plants_confirmed"]) >= 1
        assert len(result["plants_missing"]) == 0

    def test_verify_plants_missing(self) -> None:
        svc, _kg = self._make_service()
        # Text about cultivation -- nothing about wells or whispers
        chapter_text = "张三在山顶修炼了一整天，突破到了第三层。"
        result = svc.verify_foreshadowings_in_text(
            chapter_text=chapter_text,
            chapter_number=5,
            planned_plants=["神秘，钥匙"],
            planned_collects=[],
        )
        assert len(result["plants_missing"]) >= 1
        assert len(result["plants_confirmed"]) == 0

    def test_forgotten_foreshadowings(self) -> None:
        svc, kg = self._make_service()
        # Plant a foreshadowing at chapter 1
        kg.add_foreshadowing_node(
            foreshadowing_id="fs_forgotten",
            planted_chapter=1,
            content="被遗忘的线索",
            status="pending",
        )
        # Query at chapter 15 — should be forgotten (14 chapters since last mention)
        pending = kg.get_pending_foreshadowings(current_chapter=15)
        forgotten = [p for p in pending if p["is_forgotten"]]
        assert len(forgotten) == 1
        assert forgotten[0]["foreshadowing_id"] == "fs_forgotten"


# =========================================================================
# TestHealthMetrics (2 tests)
# =========================================================================


class TestHealthMetrics:
    """HealthMetrics Pydantic model."""

    def test_health_metrics_defaults(self) -> None:
        ns = _try_import("src.novel.models.health", ["HealthMetrics"])
        HealthMetrics = ns["HealthMetrics"]

        metrics = HealthMetrics()
        assert metrics.foreshadowing_total == 0
        assert metrics.foreshadowing_collected == 0
        assert metrics.foreshadowing_abandoned == 0
        assert metrics.foreshadowing_forgotten == 0
        assert metrics.foreshadowing_collection_rate == 0.0
        assert metrics.milestone_total == 0
        assert metrics.milestone_completed == 0
        assert metrics.milestone_overdue == 0
        assert metrics.milestone_completion_rate == 0.0
        assert metrics.character_total == 0
        assert metrics.character_active == 0
        assert metrics.character_coverage == 0.0
        assert metrics.entity_total == 0
        assert metrics.entity_conflict_count == 0
        assert metrics.entity_consistency_score == 1.0
        assert metrics.debt_total == 0
        assert metrics.debt_overdue == 0
        assert metrics.debt_health == "healthy"
        assert metrics.overall_health_score == 0.0

    def test_health_metrics_full(self) -> None:
        ns = _try_import("src.novel.models.health", ["HealthMetrics"])
        HealthMetrics = ns["HealthMetrics"]

        metrics = HealthMetrics(
            foreshadowing_total=10,
            foreshadowing_collected=7,
            foreshadowing_abandoned=1,
            foreshadowing_forgotten=0,
            foreshadowing_collection_rate=0.7,
            milestone_total=5,
            milestone_completed=4,
            milestone_overdue=0,
            milestone_completion_rate=0.8,
            character_total=20,
            character_active=15,
            character_coverage=0.75,
            character_top_10_appearance_ratio=0.6,
            entity_total=50,
            entity_conflict_count=2,
            entity_consistency_score=0.96,
            debt_total=3,
            debt_overdue=0,
            debt_health="healthy",
            overall_health_score=85.0,
        )
        assert 0 <= metrics.overall_health_score <= 100
        assert metrics.foreshadowing_total == 10
        assert metrics.character_coverage == 0.75


# =========================================================================
# Mock helpers for HealthService
# =========================================================================


class MockStructuredDB:
    """In-memory mock for StructuredDB entity-related methods."""

    def __init__(self, entities: list[dict] | None = None) -> None:
        self._entities = entities or []

    def get_all_entities(self) -> list[dict]:
        return self._entities

    def get_entity_count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._entities:
            t = e.get("entity_type", "other")
            counts[t] = counts.get(t, 0) + 1
        return counts

    def transaction(self):  # noqa: D102
        """Return a no-op context manager with a mock cursor."""
        import contextlib

        class _MockCursor:
            def execute(self, *a, **kw):  # noqa: D102
                pass

            def fetchone(self):  # noqa: D102
                return None

        @contextlib.contextmanager
        def _txn():
            yield _MockCursor()

        return _txn()


class MockMilestoneTracker:
    """Returns pre-set milestone progress."""

    def __init__(self, completed: int = 0, pending: int = 0, overdue: int = 0) -> None:
        self._completed = completed
        self._pending = pending
        self._overdue = overdue

    def compute_volume_progress(self, current_chapter: int) -> dict:
        return {
            "milestones_completed": [f"ms_{i}" for i in range(self._completed)],
            "milestones_pending": [f"ms_{i}" for i in range(self._pending)],
            "milestones_overdue": [f"ms_{i}" for i in range(self._overdue)],
        }


class MockObligationTracker:
    """Returns pre-set debt statistics."""

    def __init__(self, total: int = 0, overdue: int = 0) -> None:
        self._total = total
        self._overdue = overdue

    def get_debt_statistics(self) -> dict:
        return {"total_count": self._total, "overdue_count": self._overdue}


# =========================================================================
# TestHealthService (6 tests)
# =========================================================================


class TestHealthService:
    """HealthService: compute metrics from various data sources."""

    def _import_service(self):
        ns = _try_import(
            "src.novel.services.health_service",
            ["HealthService"],
        )
        return ns["HealthService"]

    def test_compute_empty(self) -> None:
        """All dependencies None/empty -- returns default HealthMetrics, no crash."""
        HealthService = self._import_service()
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        svc = HealthService(
            structured_db=MockStructuredDB(),
            knowledge_graph=KnowledgeGraph(),
            obligation_tracker=None,
            milestone_tracker=None,
        )
        metrics = svc.compute_health_metrics(current_chapter=0, novel_data={})
        assert metrics.foreshadowing_total == 0
        assert metrics.entity_total == 0
        assert metrics.overall_health_score >= 0

    def test_compute_milestone_metrics(self) -> None:
        HealthService = self._import_service()
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        svc = HealthService(
            structured_db=MockStructuredDB(),
            knowledge_graph=KnowledgeGraph(),
            obligation_tracker=None,
            milestone_tracker=MockMilestoneTracker(completed=3, pending=2, overdue=1),
        )
        metrics = svc.compute_health_metrics(current_chapter=10, novel_data={})
        assert metrics.milestone_total == 6  # 3+2+1
        assert metrics.milestone_completed == 3
        assert metrics.milestone_overdue == 1
        assert abs(metrics.milestone_completion_rate - 0.5) < 0.01  # 3/6

    def test_compute_entity_metrics(self) -> None:
        HealthService = self._import_service()
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        entities = [
            {"canonical_name": "张三", "entity_type": "character"},
            {"canonical_name": "李四", "entity_type": "character"},
            {"canonical_name": "青云山", "entity_type": "location"},
        ]
        svc = HealthService(
            structured_db=MockStructuredDB(entities=entities),
            knowledge_graph=KnowledgeGraph(),
            obligation_tracker=None,
            milestone_tracker=None,
        )
        metrics = svc.compute_health_metrics(current_chapter=5, novel_data={})
        assert metrics.entity_total == 3
        # No conflicts among these distinctly-named entities
        assert metrics.entity_conflict_count == 0
        assert metrics.entity_consistency_score == 1.0

    def test_compute_overall_score(self) -> None:
        """All dimensions at max => overall_health_score near 100."""
        HealthService = self._import_service()
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        # All foreshadowings collected
        kg.add_foreshadowing_node("fs_1", planted_chapter=1, content="A", status="collected")
        kg.add_foreshadowing_node("fs_2", planted_chapter=2, content="B", status="collected")

        svc = HealthService(
            structured_db=MockStructuredDB(),
            knowledge_graph=kg,
            obligation_tracker=MockObligationTracker(total=2, overdue=0),
            milestone_tracker=MockMilestoneTracker(completed=5, pending=0, overdue=0),
        )
        # novel_data with characters that match the character_coverage path
        # (character_coverage needs DB queries; with MockDB it stays 0 unless we
        # populate characters. For this test we focus on the overall formula.)
        metrics = svc.compute_health_metrics(current_chapter=10, novel_data={})

        # foreshadowing: 2/2 = 1.0 * 20 = 20
        # milestone: 5/5 = 1.0 * 25 = 25
        # character: 0 * 15 = 0 (no characters in novel_data)
        # entity: 1.0 * 20 = 20 (no entities = default 1.0 consistency)
        # debt: healthy * 20 = 20
        # total = 85, no penalty
        assert metrics.overall_health_score >= 80
        assert metrics.overall_health_score <= 100

    def test_compute_overall_degraded(self) -> None:
        """Some dimensions missing => uses neutral/zero values."""
        HealthService = self._import_service()
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        svc = HealthService(
            structured_db=MockStructuredDB(),
            knowledge_graph=KnowledgeGraph(),
            obligation_tracker=None,  # no debt tracker
            milestone_tracker=None,   # no milestone tracker
        )
        metrics = svc.compute_health_metrics(current_chapter=5, novel_data={})

        # No foreshadowings => rate=0 => 0 points
        # No milestones => rate=0 => 0 points
        # No characters => coverage=0 => 0 points
        # Entity consistency defaults to 1.0 => 20 points
        # Debt health defaults to "healthy" => 20 points (no tracker = no modification)
        # But debt_health only gets set if obligation_tracker exists, so it stays
        # at default "healthy" => 20 points
        # Total = 0+0+0+20+20 = 40 (approximately)
        assert metrics.overall_health_score >= 0
        assert metrics.overall_health_score < 100

    def test_format_report(self) -> None:
        """format_report output includes key display elements."""
        ns = _try_import(
            "src.novel.services.health_service",
            ["HealthService"],
        )
        HealthService = ns["HealthService"]

        # Check if format_report exists; skip if not yet implemented
        if not hasattr(HealthService, "format_report"):
            pytest.skip("HealthService.format_report not yet implemented")

        from src.novel.storage.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        kg.add_foreshadowing_node("fs_1", planted_chapter=1, content="A", status="collected")
        kg.add_foreshadowing_node("fs_2", planted_chapter=2, content="B", status="pending")

        svc = HealthService(
            structured_db=MockStructuredDB(),
            knowledge_graph=kg,
            obligation_tracker=MockObligationTracker(total=1, overdue=0),
            milestone_tracker=MockMilestoneTracker(completed=2, pending=1, overdue=0),
        )
        metrics = svc.compute_health_metrics(current_chapter=5, novel_data={})
        report = svc.format_report(metrics)

        assert isinstance(report, str)
        assert "健康度" in report
        # Should contain percentage numbers
        assert "%" in report
        # Should contain some kind of visual progress indicator
        has_bar = any(ch in report for ch in ["█", "▓", "▒", "░", "■", "□", "|", "#"])
        assert has_bar, f"Expected progress bar characters in report, got:\n{report}"


# =========================================================================
# TestHealthServiceForeshadowing (2 tests)
# =========================================================================


class TestHealthServiceForeshadowing:
    """HealthService foreshadowing metrics with real KnowledgeGraph."""

    def _import_service(self):
        ns = _try_import(
            "src.novel.services.health_service",
            ["HealthService"],
        )
        return ns["HealthService"]

    def test_foreshadowing_metrics_with_graph(self) -> None:
        HealthService = self._import_service()
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        # 3 foreshadowings: 2 collected, 1 pending
        kg.add_foreshadowing_node("fs_1", planted_chapter=1, content="A", status="collected")
        kg.add_foreshadowing_node("fs_2", planted_chapter=2, content="B", status="collected")
        kg.add_foreshadowing_node("fs_3", planted_chapter=3, content="C", status="pending")

        svc = HealthService(
            structured_db=MockStructuredDB(),
            knowledge_graph=kg,
            obligation_tracker=None,
            milestone_tracker=None,
        )
        metrics = svc.compute_health_metrics(current_chapter=5, novel_data={})

        assert metrics.foreshadowing_total == 3
        assert metrics.foreshadowing_collected == 2
        # collection_rate = 2/3 ~ 0.6667
        assert abs(metrics.foreshadowing_collection_rate - 2.0 / 3.0) < 0.01

    def test_foreshadowing_metrics_empty_graph(self) -> None:
        HealthService = self._import_service()
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()  # empty graph, no foreshadowing nodes

        svc = HealthService(
            structured_db=MockStructuredDB(),
            knowledge_graph=kg,
            obligation_tracker=None,
            milestone_tracker=None,
        )
        metrics = svc.compute_health_metrics(current_chapter=1, novel_data={})

        assert metrics.foreshadowing_total == 0
        assert metrics.foreshadowing_collected == 0
        assert metrics.foreshadowing_collection_rate == 0.0
        assert metrics.foreshadowing_forgotten == 0
