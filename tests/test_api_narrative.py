"""Tests for the narrative control REST endpoints (src/api/narrative_routes.py).

Uses FastAPI TestClient for synchronous endpoint testing.
Creates temporary novel project structures with test data on disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.helpers import set_workspace, configure_task_queue


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _workspace(tmp_path):
    """Set workspace to a temp dir for every test."""
    set_workspace(str(tmp_path))
    yield tmp_path
    set_workspace("workspace")


@pytest.fixture()
def mock_db():
    """Mock TaskDB."""
    db = MagicMock()
    db.create_task = MagicMock()
    db.get_task = MagicMock(return_value=None)
    db.list_tasks = MagicMock(return_value=[])
    db.delete_task = MagicMock(return_value=False)
    db.update_status = MagicMock()
    return db


@pytest.fixture()
def mock_executor():
    """Mock executor."""
    ex = MagicMock()
    ex.submit = MagicMock()
    return ex


@pytest.fixture()
def client(mock_db, mock_executor):
    """Create a TestClient with mocked task queue."""
    configure_task_queue(mock_db, mock_executor)
    from src.api.app import create_app

    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_novel(
    workspace: Path,
    novel_id: str = "novel_test001",
    outline_chapters: int = 5,
    with_debts_json: bool = False,
    with_arcs_json: bool = False,
    with_graph_json: bool = False,
    with_memory_db: bool = False,
) -> Path:
    """Create a minimal novel project directory structure for testing."""
    novel_dir = workspace / "novels" / novel_id
    novel_dir.mkdir(parents=True, exist_ok=True)

    outline_chs = []
    for i in range(1, outline_chapters + 1):
        ch = {
            "chapter_number": i,
            "title": f"Chapter {i}",
            "summary": f"Summary for chapter {i}",
        }
        if i <= 3:
            ch["chapter_brief"] = {
                "main_conflict": f"Conflict in chapter {i}",
                "payoff": f"Payoff for chapter {i}",
                "character_arc_step": f"Arc step {i}",
                "end_hook_type": "cliffhanger",
            }
        outline_chs.append(ch)

    novel_data = {
        "title": "Test Novel",
        "genre": "fantasy",
        "status": "generating",
        "current_chapter": 3,
        "target_words": 100000,
        "outline": {
            "main_storyline": {"premise": "A hero's journey"},
            "chapters": outline_chs,
        },
        "characters": [
            {"name": "Hero", "role": "protagonist"},
            {"name": "Villain", "role": "antagonist"},
        ],
        "world_setting": {"name": "Fantasy World"},
    }
    (novel_dir / "novel.json").write_text(
        json.dumps(novel_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if with_debts_json:
        debts = [
            {
                "debt_id": "debt_1_0_abc",
                "source_chapter": 1,
                "type": "must_pay_next",
                "description": "Hero promised to return the sword",
                "status": "pending",
                "urgency_level": "high",
                "target_chapter": 2,
                "created_at": "2025-01-01T00:00:00",
                "fulfilled_at": None,
                "fulfillment_note": None,
                "character_pending": "[]",
                "emotional_debt": None,
                "escalation_history": "[]",
            },
            {
                "debt_id": "debt_2_0_def",
                "source_chapter": 2,
                "type": "pay_within_3",
                "description": "Villain's secret identity hinted",
                "status": "fulfilled",
                "urgency_level": "normal",
                "target_chapter": 5,
                "created_at": "2025-01-02T00:00:00",
                "fulfilled_at": "3",
                "fulfillment_note": "Revealed in chapter 3",
                "character_pending": "[]",
                "emotional_debt": None,
                "escalation_history": "[]",
            },
            {
                "debt_id": "debt_3_0_ghi",
                "source_chapter": 3,
                "type": "long_tail_payoff",
                "description": "Ancient prophecy mentioned",
                "status": "overdue",
                "urgency_level": "critical",
                "target_chapter": None,
                "created_at": "2025-01-03T00:00:00",
                "fulfilled_at": None,
                "fulfillment_note": None,
                "character_pending": "[]",
                "emotional_debt": None,
                "escalation_history": "[]",
            },
        ]
        (novel_dir / "debts.json").write_text(
            json.dumps(debts, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if with_arcs_json:
        arcs = [
            {
                "arc_id": "arc_001",
                "volume_id": "1",
                "name": "Trial Arc",
                "chapters": [1, 2, 3],
                "phase": "climax",
                "status": "in_progress",
                "completion_rate": 0.6,
                "hook": "Hero enters trial",
                "escalation_point": "2",
                "turning_point": "3",
                "closure_method": "Hero defeats guardian",
                "residual_question": "Who sent the guardian?",
            },
            {
                "arc_id": "arc_002",
                "volume_id": "1",
                "name": "Revenge Arc",
                "chapters": [4, 5],
                "phase": "setup",
                "status": "planning",
                "completion_rate": 0.0,
                "hook": "Villain attacks",
                "escalation_point": "4",
                "turning_point": "5",
                "closure_method": "Temporary truce",
                "residual_question": "Will the truce hold?",
            },
        ]
        (novel_dir / "arcs.json").write_text(
            json.dumps(arcs, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if with_graph_json:
        # NetworkX node_link_data format
        graph_data = {
            "directed": True,
            "multigraph": True,
            "graph": {},
            "nodes": [
                {"id": "char_hero", "type": "character", "name": "Hero"},
                {"id": "char_villain", "type": "character", "name": "Villain"},
                {"id": "faction_guild", "type": "faction", "name": "Guild"},
            ],
            "links": [
                {
                    "source": "char_hero",
                    "target": "char_villain",
                    "key": "rivalry_1",
                    "edge_type": "relationship",
                    "type": "rivalry",
                    "intensity": 8,
                    "chapter": 1,
                },
                {
                    "source": "char_hero",
                    "target": "faction_guild",
                    "key": "affiliation_1",
                    "edge_type": "affiliation",
                    "role": "member",
                    "chapter": 1,
                },
            ],
        }
        (novel_dir / "graph.json").write_text(
            json.dumps(graph_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return novel_dir


# ---------------------------------------------------------------------------
# Tests: GET /overview
# ---------------------------------------------------------------------------


class TestNarrativeOverview:
    def test_overview_with_data(self, client, _workspace):
        _create_novel(
            _workspace,
            with_debts_json=True,
            with_arcs_json=True,
            with_graph_json=True,
        )
        resp = client.get("/api/novels/novel_test001/narrative/overview")
        assert resp.status_code == 200
        data = resp.json()

        assert data["novel_id"] == "novel_test001"
        assert data["title"] == "Test Novel"
        assert data["current_chapter"] == 3
        assert data["total_chapters"] == 5

        # Debts
        assert data["debts"]["total"] == 3
        assert data["debts"]["pending"] == 1
        assert data["debts"]["fulfilled"] == 1
        assert data["debts"]["overdue"] == 1
        assert data["debts"]["abandoned"] == 0

        # Arcs
        assert data["arcs"]["total"] == 2
        assert data["arcs"]["active"] == 2  # in_progress + planning
        assert data["arcs"]["completed"] == 0

        # Graph
        assert data["graph"]["node_count"] == 3
        assert data["graph"]["edge_count"] == 2

    def test_overview_empty_novel(self, client, _workspace):
        _create_novel(_workspace)
        resp = client.get("/api/novels/novel_test001/narrative/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["debts"]["total"] == 0
        assert data["arcs"]["total"] == 0
        assert data["graph"]["node_count"] == 0

    def test_overview_novel_not_found(self, client, _workspace):
        resp = client.get("/api/novels/nonexistent/narrative/overview")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: GET /debts & POST /debts
# ---------------------------------------------------------------------------


class TestNarrativeDebts:
    def test_list_debts(self, client, _workspace):
        _create_novel(_workspace, with_debts_json=True)
        resp = client.get("/api/novels/novel_test001/narrative/debts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3
        assert len(data["debts"]) == 3

    def test_list_debts_with_status_filter(self, client, _workspace):
        _create_novel(_workspace, with_debts_json=True)
        resp = client.get(
            "/api/novels/novel_test001/narrative/debts?status=pending"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["debts"][0]["status"] == "pending"

    def test_list_debts_with_status_filter_no_match(self, client, _workspace):
        _create_novel(_workspace, with_debts_json=True)
        resp = client.get(
            "/api/novels/novel_test001/narrative/debts?status=abandoned"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_list_debts_empty(self, client, _workspace):
        _create_novel(_workspace)
        resp = client.get("/api/novels/novel_test001/narrative/debts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["debts"] == []

    def test_list_debts_novel_not_found(self, client, _workspace):
        resp = client.get("/api/novels/nonexistent/narrative/debts")
        assert resp.status_code == 404

    def test_add_debt(self, client, _workspace):
        _create_novel(_workspace)
        resp = client.post(
            "/api/novels/novel_test001/narrative/debts",
            json={
                "source_chapter": 2,
                "debt_type": "must_pay_next",
                "description": "Hero must face the dragon",
                "urgency_level": "high",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "created"
        assert "debt_id" in data
        assert data["debt_id"].startswith("debt_2_manual_")

        # Verify it was persisted to debts.json
        debts_path = _workspace / "novels" / "novel_test001" / "debts.json"
        assert debts_path.exists()
        debts = json.loads(debts_path.read_text(encoding="utf-8"))
        assert len(debts) == 1
        assert debts[0]["description"] == "Hero must face the dragon"
        assert debts[0]["status"] == "pending"

    def test_add_debt_invalid_type(self, client, _workspace):
        _create_novel(_workspace)
        resp = client.post(
            "/api/novels/novel_test001/narrative/debts",
            json={
                "source_chapter": 1,
                "debt_type": "invalid_type",
                "description": "Something",
            },
        )
        assert resp.status_code == 400

    def test_add_debt_invalid_urgency(self, client, _workspace):
        _create_novel(_workspace)
        resp = client.post(
            "/api/novels/novel_test001/narrative/debts",
            json={
                "source_chapter": 1,
                "debt_type": "must_pay_next",
                "description": "Something",
                "urgency_level": "mega_urgent",
            },
        )
        assert resp.status_code == 400

    def test_add_debt_missing_description(self, client, _workspace):
        _create_novel(_workspace)
        resp = client.post(
            "/api/novels/novel_test001/narrative/debts",
            json={
                "source_chapter": 1,
                "debt_type": "must_pay_next",
                "description": "",
            },
        )
        assert resp.status_code == 422  # Pydantic validation


# ---------------------------------------------------------------------------
# Tests: POST /debts/{debt_id}/fulfill
# ---------------------------------------------------------------------------


class TestFulfillDebt:
    def test_fulfill_debt_via_json(self, client, _workspace):
        _create_novel(_workspace, with_debts_json=True)
        resp = client.post(
            "/api/novels/novel_test001/narrative/debts/debt_1_0_abc/fulfill",
            json={"chapter_number": 5, "note": "Sword returned in chapter 5"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["debt_id"] == "debt_1_0_abc"
        assert data["status"] == "fulfilled"

        # Verify debts.json updated
        debts = json.loads(
            (_workspace / "novels" / "novel_test001" / "debts.json").read_text(
                encoding="utf-8"
            )
        )
        debt = next(d for d in debts if d["debt_id"] == "debt_1_0_abc")
        assert debt["status"] == "fulfilled"
        assert debt["fulfilled_at"] == "5"
        assert debt["fulfillment_note"] == "Sword returned in chapter 5"

    def test_fulfill_debt_not_found(self, client, _workspace):
        _create_novel(_workspace, with_debts_json=True)
        resp = client.post(
            "/api/novels/novel_test001/narrative/debts/nonexistent_debt/fulfill",
            json={"chapter_number": 5},
        )
        assert resp.status_code == 404

    def test_fulfill_debt_novel_not_found(self, client, _workspace):
        resp = client.post(
            "/api/novels/nonexistent/narrative/debts/some_debt/fulfill",
            json={"chapter_number": 5},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: GET /arcs
# ---------------------------------------------------------------------------


class TestNarrativeArcs:
    def test_list_arcs(self, client, _workspace):
        _create_novel(_workspace, with_arcs_json=True)
        resp = client.get("/api/novels/novel_test001/narrative/arcs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["arcs"]) == 2
        assert data["arcs"][0]["name"] == "Trial Arc"
        assert data["arcs"][1]["name"] == "Revenge Arc"

    def test_list_arcs_empty(self, client, _workspace):
        _create_novel(_workspace)
        resp = client.get("/api/novels/novel_test001/narrative/arcs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["arcs"] == []

    def test_list_arcs_novel_not_found(self, client, _workspace):
        resp = client.get("/api/novels/nonexistent/narrative/arcs")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: GET /briefs/{chapter_number}
# ---------------------------------------------------------------------------


class TestChapterBrief:
    def test_get_brief_with_data(self, client, _workspace):
        _create_novel(_workspace)
        resp = client.get(
            "/api/novels/novel_test001/narrative/briefs/1"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["chapter_number"] == 1
        assert data["title"] == "Chapter 1"
        assert data["brief"]["main_conflict"] == "Conflict in chapter 1"
        assert data["brief"]["payoff"] == "Payoff for chapter 1"

    def test_get_brief_chapter_without_brief(self, client, _workspace):
        _create_novel(_workspace, outline_chapters=5)
        # Chapters 4 and 5 have no brief in our test data
        resp = client.get(
            "/api/novels/novel_test001/narrative/briefs/4"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["chapter_number"] == 4
        assert data["brief"] == {}

    def test_get_brief_chapter_not_in_outline(self, client, _workspace):
        _create_novel(_workspace, outline_chapters=5)
        resp = client.get(
            "/api/novels/novel_test001/narrative/briefs/99"
        )
        assert resp.status_code == 404

    def test_get_brief_novel_not_found(self, client, _workspace):
        resp = client.get(
            "/api/novels/nonexistent/narrative/briefs/1"
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: GET /graph
# ---------------------------------------------------------------------------


class TestKnowledgeGraph:
    def test_get_graph_with_data(self, client, _workspace):
        _create_novel(_workspace, with_graph_json=True)
        resp = client.get("/api/novels/novel_test001/narrative/graph")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["nodes"]) == 3
        assert len(data["edges"]) == 2

        # Check node types
        node_types = {n["type"] for n in data["nodes"]}
        assert "character" in node_types
        assert "faction" in node_types

        # Check specific nodes
        node_ids = {n["id"] for n in data["nodes"]}
        assert "char_hero" in node_ids
        assert "char_villain" in node_ids
        assert "faction_guild" in node_ids

        # Check edges
        edge_types = {e.get("edge_type") for e in data["edges"]}
        assert "relationship" in edge_types
        assert "affiliation" in edge_types

    def test_get_graph_empty(self, client, _workspace):
        _create_novel(_workspace)
        resp = client.get("/api/novels/novel_test001/narrative/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []
        assert data["edges"] == []

    def test_get_graph_novel_not_found(self, client, _workspace):
        resp = client.get("/api/novels/nonexistent/narrative/graph")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: Invalid novel ID (path traversal)
# ---------------------------------------------------------------------------


class TestInvalidIds:
    def test_invalid_id_overview(self, client, _workspace):
        # IDs with dots/slashes should be rejected by validate_id
        resp = client.get("/api/novels/novel..test/narrative/overview")
        assert resp.status_code == 400

    def test_invalid_id_debts(self, client, _workspace):
        resp = client.get("/api/novels/novel..evil/narrative/debts")
        assert resp.status_code == 400
