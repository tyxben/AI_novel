"""Tests for narrative control storage layer: chapter_debts + story_units tables + FileManager exports"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.novel.storage.structured_db import StructuredDB
from src.novel.storage.file_manager import FileManager


# ========== Fixtures ==========


@pytest.fixture
def db(tmp_path: Path) -> StructuredDB:
    """Create StructuredDB with temporary SQLite file."""
    db_path = tmp_path / "test.db"
    return StructuredDB(db_path)


@pytest.fixture
def file_manager(tmp_path: Path) -> FileManager:
    """Create FileManager with temporary workspace."""
    return FileManager(str(tmp_path))


# ========== chapter_debts tests ==========


class TestChapterDebtsTable:
    """Tests for chapter_debts table CRUD operations."""

    def test_insert_debt_minimal(self, db: StructuredDB) -> None:
        """Insert a debt with only required fields."""
        db.insert_debt(
            debt_id="d001",
            source_chapter=3,
            type="must_pay_next",
            description="Hero promised to return the sword",
        )
        results = db.query_debts()
        assert len(results) == 1
        row = results[0]
        assert row["debt_id"] == "d001"
        assert row["source_chapter"] == 3
        assert row["type"] == "must_pay_next"
        assert row["description"] == "Hero promised to return the sword"
        assert row["status"] == "pending"
        assert row["urgency_level"] == "normal"
        assert row["target_chapter"] is None
        assert row["fulfilled_at"] is None
        assert row["fulfillment_note"] is None

    def test_insert_debt_full_fields(self, db: StructuredDB) -> None:
        """Insert a debt with all optional fields."""
        db.insert_debt(
            debt_id="d002",
            source_chapter=5,
            type="pay_within_3",
            description="Villain escaped, must be caught",
            status="overdue",
            urgency_level="high",
            target_chapter=8,
            fulfilled_at="2025-01-01T00:00:00",
            fulfillment_note="Caught in chapter 8",
            character_pending=json.dumps(["chase villain", "gather allies"]),
            emotional_debt="Betrayal unresolved",
            escalation_history=json.dumps([{"chapter": 7, "old": "normal", "new": "high"}]),
        )
        results = db.query_debts()
        assert len(results) == 1
        row = results[0]
        assert row["status"] == "overdue"
        assert row["urgency_level"] == "high"
        assert row["target_chapter"] == 8
        assert row["fulfilled_at"] == "2025-01-01T00:00:00"
        assert row["fulfillment_note"] == "Caught in chapter 8"
        assert row["emotional_debt"] == "Betrayal unresolved"
        # Verify JSON-serialized list fields
        assert json.loads(row["character_pending"]) == ["chase villain", "gather allies"]
        assert json.loads(row["escalation_history"]) == [
            {"chapter": 7, "old": "normal", "new": "high"}
        ]

    def test_insert_debt_list_auto_serialization(self, db: StructuredDB) -> None:
        """Verify that list/dict kwargs are auto-serialized to JSON strings."""
        db.insert_debt(
            debt_id="d003",
            source_chapter=1,
            type="long_tail_payoff",
            description="Mystery seed planted",
            character_pending=["investigate clue"],
            escalation_history=[{"chapter": 2, "reason": "auto"}],
        )
        results = db.query_debts()
        assert len(results) == 1
        row = results[0]
        assert json.loads(row["character_pending"]) == ["investigate clue"]
        assert json.loads(row["escalation_history"]) == [{"chapter": 2, "reason": "auto"}]

    def test_insert_debt_duplicate_ignored(self, db: StructuredDB) -> None:
        """Duplicate debt_id should be silently ignored (ON CONFLICT DO NOTHING)."""
        db.insert_debt(debt_id="dup", source_chapter=1, type="must_pay_next", description="v1")
        db.insert_debt(debt_id="dup", source_chapter=2, type="pay_within_3", description="v2")
        results = db.query_debts()
        assert len(results) == 1
        assert results[0]["description"] == "v1"  # original kept

    def test_query_debts_no_filter(self, db: StructuredDB) -> None:
        """Query all debts without filters."""
        for i in range(5):
            db.insert_debt(
                debt_id=f"d{i}",
                source_chapter=i + 1,
                type="must_pay_next",
                description=f"Debt {i}",
            )
        results = db.query_debts()
        assert len(results) == 5

    def test_query_debts_filter_status(self, db: StructuredDB) -> None:
        """Filter debts by status."""
        db.insert_debt(debt_id="d1", source_chapter=1, type="must_pay_next", description="A", status="pending")
        db.insert_debt(debt_id="d2", source_chapter=2, type="must_pay_next", description="B", status="fulfilled")
        db.insert_debt(debt_id="d3", source_chapter=3, type="must_pay_next", description="C", status="pending")

        pending = db.query_debts(status="pending")
        assert len(pending) == 2
        assert all(r["status"] == "pending" for r in pending)

        fulfilled = db.query_debts(status="fulfilled")
        assert len(fulfilled) == 1
        assert fulfilled[0]["debt_id"] == "d2"

    def test_query_debts_filter_source_chapter(self, db: StructuredDB) -> None:
        """Filter debts by exact source_chapter."""
        db.insert_debt(debt_id="d1", source_chapter=3, type="must_pay_next", description="A")
        db.insert_debt(debt_id="d2", source_chapter=5, type="must_pay_next", description="B")
        db.insert_debt(debt_id="d3", source_chapter=3, type="pay_within_3", description="C")

        results = db.query_debts(source_chapter=3)
        assert len(results) == 2
        assert all(r["source_chapter"] == 3 for r in results)

    def test_query_debts_filter_before_chapter(self, db: StructuredDB) -> None:
        """Filter debts by before_chapter (source_chapter < N)."""
        db.insert_debt(debt_id="d1", source_chapter=1, type="must_pay_next", description="A")
        db.insert_debt(debt_id="d2", source_chapter=3, type="must_pay_next", description="B")
        db.insert_debt(debt_id="d3", source_chapter=5, type="must_pay_next", description="C")
        db.insert_debt(debt_id="d4", source_chapter=7, type="must_pay_next", description="D")

        results = db.query_debts(before_chapter=5)
        assert len(results) == 2
        assert {r["debt_id"] for r in results} == {"d1", "d2"}

    def test_query_debts_combined_filters(self, db: StructuredDB) -> None:
        """Combine status + before_chapter filters."""
        db.insert_debt(debt_id="d1", source_chapter=1, type="must_pay_next", description="A", status="pending")
        db.insert_debt(debt_id="d2", source_chapter=2, type="must_pay_next", description="B", status="fulfilled")
        db.insert_debt(debt_id="d3", source_chapter=3, type="must_pay_next", description="C", status="pending")
        db.insert_debt(debt_id="d4", source_chapter=10, type="must_pay_next", description="D", status="pending")

        results = db.query_debts(status="pending", before_chapter=5)
        assert len(results) == 2
        assert {r["debt_id"] for r in results} == {"d1", "d3"}

    def test_query_debts_empty(self, db: StructuredDB) -> None:
        """Query returns empty list when no debts exist."""
        results = db.query_debts()
        assert results == []

    def test_update_debt_status_basic(self, db: StructuredDB) -> None:
        """Update debt status to fulfilled."""
        db.insert_debt(debt_id="d1", source_chapter=1, type="must_pay_next", description="A")
        db.update_debt_status("d1", "fulfilled", fulfilled_at="2025-06-01T12:00:00", note="Resolved in ch3")

        results = db.query_debts()
        assert len(results) == 1
        assert results[0]["status"] == "fulfilled"
        assert results[0]["fulfilled_at"] == "2025-06-01T12:00:00"
        assert results[0]["fulfillment_note"] == "Resolved in ch3"

    def test_update_debt_status_partial(self, db: StructuredDB) -> None:
        """Update status without note preserves existing fields."""
        db.insert_debt(
            debt_id="d1", source_chapter=1, type="must_pay_next",
            description="A", fulfillment_note="original note",
        )
        db.update_debt_status("d1", "overdue")

        results = db.query_debts()
        assert results[0]["status"] == "overdue"
        assert results[0]["fulfillment_note"] == "original note"  # preserved

    def test_update_debt_status_nonexistent(self, db: StructuredDB) -> None:
        """Updating nonexistent debt_id is a no-op (no error)."""
        db.update_debt_status("nonexistent", "fulfilled")
        results = db.query_debts()
        assert results == []

    def test_query_debts_ordered_by_source_chapter(self, db: StructuredDB) -> None:
        """Results are ordered by source_chapter ASC."""
        db.insert_debt(debt_id="d3", source_chapter=10, type="must_pay_next", description="C")
        db.insert_debt(debt_id="d1", source_chapter=1, type="must_pay_next", description="A")
        db.insert_debt(debt_id="d2", source_chapter=5, type="must_pay_next", description="B")

        results = db.query_debts()
        chapters = [r["source_chapter"] for r in results]
        assert chapters == [1, 5, 10]


# ========== story_units tests ==========


class TestStoryUnitsTable:
    """Tests for story_units table CRUD operations."""

    def test_insert_story_unit_minimal(self, db: StructuredDB) -> None:
        """Insert a story unit with only required fields."""
        db.insert_story_unit(
            arc_id="arc001",
            volume_id="vol1",
            name="Opening Arc",
            chapters_json=json.dumps([1, 2, 3, 4]),
        )
        results = db.query_story_units()
        assert len(results) == 1
        row = results[0]
        assert row["arc_id"] == "arc001"
        assert row["volume_id"] == "vol1"
        assert row["name"] == "Opening Arc"
        assert json.loads(row["chapters"]) == [1, 2, 3, 4]
        assert row["phase"] == "setup"
        assert row["status"] == "active"
        assert row["completion_rate"] == 0.0

    def test_insert_story_unit_full_fields(self, db: StructuredDB) -> None:
        """Insert a story unit with all optional fields."""
        db.insert_story_unit(
            arc_id="arc002",
            volume_id="vol1",
            name="Climax Arc",
            chapters_json=json.dumps([5, 6, 7]),
            phase="climax",
            status="in_progress",
            completion_rate=0.67,
            hook="The enemy attacks at dawn",
            escalation_point="Chapter 6",
            turning_point="Chapter 7",
            closure_method="Final battle victory",
            residual_question="What happened to the missing artifact?",
        )
        results = db.query_story_units()
        assert len(results) == 1
        row = results[0]
        assert row["phase"] == "climax"
        assert row["status"] == "in_progress"
        assert abs(row["completion_rate"] - 0.67) < 0.001
        assert row["hook"] == "The enemy attacks at dawn"
        assert row["escalation_point"] == "Chapter 6"
        assert row["turning_point"] == "Chapter 7"
        assert row["closure_method"] == "Final battle victory"
        assert row["residual_question"] == "What happened to the missing artifact?"

    def test_insert_story_unit_duplicate_ignored(self, db: StructuredDB) -> None:
        """Duplicate arc_id should be silently ignored."""
        db.insert_story_unit(arc_id="dup", volume_id="v1", name="First", chapters_json="[1,2,3]")
        db.insert_story_unit(arc_id="dup", volume_id="v2", name="Second", chapters_json="[4,5,6]")
        results = db.query_story_units()
        assert len(results) == 1
        assert results[0]["name"] == "First"

    def test_query_story_units_all(self, db: StructuredDB) -> None:
        """Query all story units without filter."""
        for i in range(3):
            db.insert_story_unit(
                arc_id=f"arc{i}",
                volume_id="vol1",
                name=f"Arc {i}",
                chapters_json=json.dumps([i * 3 + 1, i * 3 + 2, i * 3 + 3]),
            )
        results = db.query_story_units()
        assert len(results) == 3

    def test_query_story_units_filter_volume(self, db: StructuredDB) -> None:
        """Filter story units by volume_id."""
        db.insert_story_unit(arc_id="a1", volume_id="vol1", name="A1", chapters_json="[1,2,3]")
        db.insert_story_unit(arc_id="a2", volume_id="vol2", name="A2", chapters_json="[4,5,6]")
        db.insert_story_unit(arc_id="a3", volume_id="vol1", name="A3", chapters_json="[7,8,9]")

        vol1 = db.query_story_units(volume_id="vol1")
        assert len(vol1) == 2
        assert all(r["volume_id"] == "vol1" for r in vol1)

        vol2 = db.query_story_units(volume_id="vol2")
        assert len(vol2) == 1
        assert vol2[0]["arc_id"] == "a2"

    def test_query_story_units_empty(self, db: StructuredDB) -> None:
        """Query returns empty list when no story units exist."""
        results = db.query_story_units()
        assert results == []

    def test_update_story_unit_progress(self, db: StructuredDB) -> None:
        """Update completion_rate and phase."""
        db.insert_story_unit(
            arc_id="arc001", volume_id="vol1", name="Test",
            chapters_json="[1,2,3,4,5]",
        )
        db.update_story_unit_progress("arc001", completion_rate=0.6, phase="escalation")

        results = db.query_story_units()
        assert len(results) == 1
        assert abs(results[0]["completion_rate"] - 0.6) < 0.001
        assert results[0]["phase"] == "escalation"

    def test_update_story_unit_progress_to_complete(self, db: StructuredDB) -> None:
        """Update to 100% completion with resolution phase."""
        db.insert_story_unit(
            arc_id="arc001", volume_id="vol1", name="Test",
            chapters_json="[1,2,3]",
        )
        db.update_story_unit_progress("arc001", completion_rate=1.0, phase="resolution")

        results = db.query_story_units()
        assert results[0]["completion_rate"] == 1.0
        assert results[0]["phase"] == "resolution"

    def test_update_story_unit_progress_nonexistent(self, db: StructuredDB) -> None:
        """Updating nonexistent arc_id is a no-op."""
        db.update_story_unit_progress("nonexistent", completion_rate=0.5, phase="climax")
        results = db.query_story_units()
        assert results == []


# ========== FileManager export tests ==========


class TestFileManagerExports:
    """Tests for FileManager narrative control export methods."""

    def test_export_debts_json(self, file_manager: FileManager) -> None:
        """Export debts list to JSON file."""
        debts = [
            {"debt_id": "d1", "source_chapter": 1, "description": "Promise A", "status": "pending"},
            {"debt_id": "d2", "source_chapter": 3, "description": "Promise B", "status": "fulfilled"},
        ]
        path = file_manager.export_debts_json("novel_001", debts)

        assert path.exists()
        assert path.name == "debts.json"
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == debts

    def test_export_debts_json_empty(self, file_manager: FileManager) -> None:
        """Export empty debts list."""
        path = file_manager.export_debts_json("novel_001", [])
        assert path.exists()
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == []

    def test_export_debts_json_unicode(self, file_manager: FileManager) -> None:
        """Export debts with Chinese characters."""
        debts = [{"debt_id": "d1", "description": "主角承诺归还神剑", "status": "pending"}]
        path = file_manager.export_debts_json("novel_001", debts)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "主角承诺归还神剑" in content  # Not escaped
        loaded = json.loads(content)
        assert loaded[0]["description"] == "主角承诺归还神剑"

    def test_export_arcs_json(self, file_manager: FileManager) -> None:
        """Export arcs list to JSON file."""
        arcs = [
            {
                "arc_id": "arc1",
                "volume_id": "vol1",
                "name": "Opening Arc",
                "chapters": [1, 2, 3, 4],
                "phase": "setup",
                "completion_rate": 0.0,
            },
            {
                "arc_id": "arc2",
                "volume_id": "vol1",
                "name": "Rising Action",
                "chapters": [5, 6, 7],
                "phase": "escalation",
                "completion_rate": 0.33,
            },
        ]
        path = file_manager.export_arcs_json("novel_001", arcs)

        assert path.exists()
        assert path.name == "arcs.json"
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == arcs
        assert loaded[0]["chapters"] == [1, 2, 3, 4]

    def test_export_arcs_json_empty(self, file_manager: FileManager) -> None:
        """Export empty arcs list."""
        path = file_manager.export_arcs_json("novel_001", [])
        assert path.exists()
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == []

    def test_export_arcs_json_unicode(self, file_manager: FileManager) -> None:
        """Export arcs with Chinese characters."""
        arcs = [{"arc_id": "a1", "name": "新生试炼篇", "hook": "少年踏入宗门"}]
        path = file_manager.export_arcs_json("novel_001", arcs)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "新生试炼篇" in content
        assert "少年踏入宗门" in content

    def test_export_creates_novel_directory(self, file_manager: FileManager) -> None:
        """Export methods create novel directory if it does not exist."""
        path = file_manager.export_debts_json("brand_new_novel", [{"test": True}])
        assert path.parent.exists()
        assert path.parent.name == "brand_new_novel"

    def test_export_overwrites_existing(self, file_manager: FileManager) -> None:
        """Export overwrites existing file."""
        file_manager.export_debts_json("novel_001", [{"v": 1}])
        path = file_manager.export_debts_json("novel_001", [{"v": 2}])
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == [{"v": 2}]

    def test_export_both_files_coexist(self, file_manager: FileManager) -> None:
        """Both debts.json and arcs.json can coexist in same novel directory."""
        debts_path = file_manager.export_debts_json("novel_001", [{"type": "debt"}])
        arcs_path = file_manager.export_arcs_json("novel_001", [{"type": "arc"}])

        assert debts_path.parent == arcs_path.parent
        assert debts_path.exists()
        assert arcs_path.exists()

        with open(debts_path, encoding="utf-8") as f:
            assert json.load(f) == [{"type": "debt"}]
        with open(arcs_path, encoding="utf-8") as f:
            assert json.load(f) == [{"type": "arc"}]


# ========== Integration: StructuredDB table initialization ==========


class TestTableCreation:
    """Verify both tables are created during StructuredDB initialization."""

    def test_chapter_debts_table_exists(self, db: StructuredDB) -> None:
        """chapter_debts table exists after init."""
        with db._lock:
            assert db._conn is not None
            cur = db._conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='chapter_debts'"
            )
            assert cur.fetchone() is not None

    def test_story_units_table_exists(self, db: StructuredDB) -> None:
        """story_units table exists after init."""
        with db._lock:
            assert db._conn is not None
            cur = db._conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='story_units'"
            )
            assert cur.fetchone() is not None

    def test_chapter_debts_indexes_exist(self, db: StructuredDB) -> None:
        """Verify indexes on chapter_debts table."""
        with db._lock:
            assert db._conn is not None
            cur = db._conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='chapter_debts'"
            )
            index_names = {row["name"] for row in cur.fetchall()}
            assert "idx_chapter_debts_status" in index_names
            assert "idx_chapter_debts_source_chapter" in index_names
            assert "idx_chapter_debts_urgency_level" in index_names

    def test_story_units_indexes_exist(self, db: StructuredDB) -> None:
        """Verify indexes on story_units table."""
        with db._lock:
            assert db._conn is not None
            cur = db._conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='story_units'"
            )
            index_names = {row["name"] for row in cur.fetchall()}
            assert "idx_story_units_volume_id" in index_names
            assert "idx_story_units_status" in index_names

    def test_reinit_idempotent(self, tmp_path: Path) -> None:
        """Creating StructuredDB twice on same file is safe (IF NOT EXISTS)."""
        db_path = tmp_path / "test.db"
        db1 = StructuredDB(db_path)
        db1.insert_debt(debt_id="d1", source_chapter=1, type="must_pay_next", description="test")
        db1.close()

        db2 = StructuredDB(db_path)
        results = db2.query_debts()
        assert len(results) == 1
        assert results[0]["debt_id"] == "d1"
        db2.close()
