"""Tests for ``LedgerStore`` facade.

Scope
-----
Only the facade behaviour is tested here. The underlying services
(ObligationTracker / ForeshadowingService / CharacterArcTracker /
MilestoneTracker / EntityService / StructuredDB / KnowledgeGraph) have
their own test suites and we do not duplicate them.

Coverage
--------
* Empty project: missing ``db`` / ``kg`` / ``vector_store`` / ``novel_data``
  must not crash; every ``list_*`` / ``get_*`` returns an empty result.
* Read happy-path: mocked stores return data, facade forwards correctly.
* Graceful degradation when underlying calls raise.
* ``snapshot_for_chapter`` assembles all expected keys and splits
  foreshadowings into plantable / collectable.
* Write forwarding: ``record_debt`` / ``record_character_state`` /
  ``record_foreshadowing`` hit the right backend.
* Lazy instantiation: wrapped services are only built on first access.
* Character-id resolution through ``novel_data``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.novel.services.ledger_store import LedgerStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_db() -> MagicMock:
    db = MagicMock(name="StructuredDB")
    db.query_debts.return_value = []
    db.get_character_state.return_value = None
    db.get_all_terms.return_value = []
    return db


@pytest.fixture
def fake_kg() -> MagicMock:
    kg = MagicMock(name="KnowledgeGraph")
    kg.get_pending_foreshadowings.return_value = []
    return kg


@pytest.fixture
def novel_data_with_milestones() -> dict:
    return {
        "characters": [
            {"character_id": "char_001", "name": "林渊"},
            {"character_id": "char_002", "name": "苏雪"},
        ],
        "outline": {
            "volumes": [
                {
                    "volume_number": 1,
                    "title": "启程卷",
                    "start_chapter": 1,
                    "end_chapter": 30,
                    "narrative_milestones": [
                        {
                            "milestone_id": "m_001",
                            "description": "主角觉醒异能",
                            "target_chapter_range": [5, 10],
                            "status": "pending",
                            "verification_type": "auto_keyword",
                            "verification_criteria": ["觉醒"],
                        },
                        {
                            "milestone_id": "m_002",
                            "description": "苏雪加入队伍",
                            "target_chapter_range": [12, 18],
                            "status": "pending",
                            "verification_type": "auto_keyword",
                            "verification_criteria": ["加入"],
                        },
                    ],
                }
            ]
        },
    }


# ---------------------------------------------------------------------------
# Empty / degraded mode
# ---------------------------------------------------------------------------


def test_empty_project_does_not_crash(tmp_path):
    """All list_* / get_* APIs return empty / None on a bare LedgerStore."""
    store = LedgerStore(project_path=tmp_path)

    assert store.list_foreshadowings() == []
    assert store.list_foreshadowings(status="collected") == []
    assert store.list_debts() == []
    assert store.list_debts(status="pending") == []
    assert store.list_debts(overdue_only=True) == []
    assert store.get_character_state("林渊", chapter_number=5) is None
    assert store.list_character_arcs() == []
    assert store.get_world_facts() == []
    assert store.list_milestones() == []


def test_snapshot_for_empty_project(tmp_path):
    """snapshot_for_chapter must always return all keys even when empty."""
    store = LedgerStore(project_path=tmp_path)
    snap = store.snapshot_for_chapter(chapter_number=1)

    expected_keys = {
        "pending_debts",
        "plantable_foreshadowings",
        "collectable_foreshadowings",
        "active_characters",
        "world_facts",
        "pending_milestones",
    }
    assert set(snap.keys()) == expected_keys
    for key in expected_keys:
        assert snap[key] == [], f"{key} should be empty, got {snap[key]!r}"


def test_vector_store_none_degrades_silently(tmp_path, fake_db, fake_kg):
    """Missing vector_store is fine — facade still usable."""
    store = LedgerStore(
        project_path=tmp_path,
        db=fake_db,
        kg=fake_kg,
        vector_store=None,
    )
    # Should not raise
    assert store.list_foreshadowings() == []
    assert store.list_debts() == []


# ---------------------------------------------------------------------------
# Read happy-path
# ---------------------------------------------------------------------------


def test_list_foreshadowings_forwards_and_filters(tmp_path, fake_kg):
    fake_kg.get_pending_foreshadowings.return_value = [
        {
            "foreshadowing_id": "fs1",
            "content": "神秘戒指",
            "planted_chapter": 3,
            "target_chapter": 15,
            "chapters_since_plant": 2,
            "last_mentioned_chapter": 3,
            "is_forgotten": False,
        },
        {
            "foreshadowing_id": "fs2",
            "content": "黑衣人",
            "planted_chapter": 20,
            "target_chapter": -1,
            "chapters_since_plant": 1,
            "last_mentioned_chapter": 20,
            "is_forgotten": False,
        },
    ]
    store = LedgerStore(project_path=tmp_path, kg=fake_kg)

    # No filter
    all_fs = store.list_foreshadowings()
    assert len(all_fs) == 2
    fake_kg.get_pending_foreshadowings.assert_called_once()

    # Chapter-range filter keeps only fs1
    filtered = store.list_foreshadowings(chapter_range=(1, 10))
    assert len(filtered) == 1
    assert filtered[0]["foreshadowing_id"] == "fs1"

    # Status != pending currently returns [] (Phase 2 to extend)
    assert store.list_foreshadowings(status="collected") == []


def test_list_debts_status_and_overdue(tmp_path, fake_db):
    def _query_debts(status=None, **_kw):
        if status == "overdue":
            return [{"debt_id": "d_over", "status": "overdue"}]
        if status == "pending":
            return [{"debt_id": "d_pend", "status": "pending"}]
        return [
            {"debt_id": "d_pend", "status": "pending"},
            {"debt_id": "d_over", "status": "overdue"},
        ]

    fake_db.query_debts.side_effect = _query_debts
    store = LedgerStore(project_path=tmp_path, db=fake_db)

    assert len(store.list_debts()) == 2
    overdue = store.list_debts(overdue_only=True)
    assert len(overdue) == 1 and overdue[0]["debt_id"] == "d_over"
    pending = store.list_debts(status="pending")
    assert len(pending) == 1 and pending[0]["debt_id"] == "d_pend"


def test_get_character_state_resolves_name(
    tmp_path, fake_db, novel_data_with_milestones
):
    fake_db.get_character_state.return_value = {
        "character_id": "char_001",
        "chapter": 5,
        "health": "healthy",
        "location": "青云峰",
    }
    store = LedgerStore(
        project_path=tmp_path,
        db=fake_db,
        novel_data=novel_data_with_milestones,
    )

    state = store.get_character_state("林渊", chapter_number=5)
    assert state is not None and state["location"] == "青云峰"
    # Ensure the resolved id was char_001
    call = fake_db.get_character_state.call_args
    assert call.args[0] == "char_001"
    assert call.kwargs["chapter"] == 5


def test_get_character_state_unknown_name_falls_back_to_raw(
    tmp_path, fake_db, novel_data_with_milestones
):
    fake_db.get_character_state.return_value = None
    store = LedgerStore(
        project_path=tmp_path,
        db=fake_db,
        novel_data=novel_data_with_milestones,
    )
    assert store.get_character_state("未知角色", chapter_number=3) is None
    # When the name is not in novel_data, we pass the raw name through.
    fake_db.get_character_state.assert_called_once_with(
        "未知角色", chapter=3
    )


def test_get_character_state_empty_name_returns_none(tmp_path, fake_db):
    store = LedgerStore(project_path=tmp_path, db=fake_db)
    assert store.get_character_state("", chapter_number=1) is None
    fake_db.get_character_state.assert_not_called()


def test_list_character_arcs_with_and_without_filter(tmp_path):
    store = LedgerStore(project_path=tmp_path)
    tracker = store.character_arc_tracker
    tracker._states = {
        "林渊": {
            "current_stage": "trial",
            "milestones": [],
            "growth_summary": "",
            "last_appearance": 5,
        },
        "苏雪": {
            "current_stage": "bonding",
            "milestones": [],
            "growth_summary": "",
            "last_appearance": 6,
        },
    }

    all_arcs = store.list_character_arcs()
    names = {a["name"] for a in all_arcs}
    assert names == {"林渊", "苏雪"}

    only = store.list_character_arcs(character_name="苏雪")
    assert len(only) == 1 and only[0]["current_stage"] == "bonding"

    missing = store.list_character_arcs(character_name="不存在")
    assert missing == []


def test_get_world_facts_filters_by_category(tmp_path, fake_db):
    fake_db.get_all_terms.return_value = [
        {"term": "灵气", "definition": "...", "category": "修炼"},
        {"term": "青云宗", "definition": "...", "category": "门派"},
    ]
    store = LedgerStore(project_path=tmp_path, db=fake_db)

    assert len(store.get_world_facts()) == 2
    filtered = store.get_world_facts(category="门派")
    assert len(filtered) == 1 and filtered[0]["term"] == "青云宗"


def test_list_milestones_chapter_range(
    tmp_path, novel_data_with_milestones
):
    store = LedgerStore(
        project_path=tmp_path,
        novel_data=novel_data_with_milestones,
    )

    all_ms = store.list_milestones()
    assert len(all_ms) == 2

    early = store.list_milestones(chapter_range=(1, 10))
    assert len(early) == 1 and early[0]["milestone_id"] == "m_001"

    late = store.list_milestones(chapter_range=(15, 20))
    assert len(late) == 1 and late[0]["milestone_id"] == "m_002"

    none = store.list_milestones(chapter_range=(100, 200))
    assert none == []


# ---------------------------------------------------------------------------
# Graceful degradation on exception
# ---------------------------------------------------------------------------


def test_list_foreshadowings_swallows_exceptions(tmp_path, fake_kg):
    fake_kg.get_pending_foreshadowings.side_effect = RuntimeError("boom")
    store = LedgerStore(project_path=tmp_path, kg=fake_kg)
    assert store.list_foreshadowings() == []


def test_list_debts_swallows_exceptions(tmp_path, fake_db):
    fake_db.query_debts.side_effect = RuntimeError("boom")
    store = LedgerStore(project_path=tmp_path, db=fake_db)
    assert store.list_debts() == []


def test_get_character_state_swallows_exceptions(tmp_path, fake_db):
    fake_db.get_character_state.side_effect = RuntimeError("boom")
    store = LedgerStore(project_path=tmp_path, db=fake_db)
    assert store.get_character_state("some_id", chapter_number=1) is None


def test_get_world_facts_swallows_exceptions(tmp_path, fake_db):
    fake_db.get_all_terms.side_effect = RuntimeError("boom")
    store = LedgerStore(project_path=tmp_path, db=fake_db)
    assert store.get_world_facts() == []


# ---------------------------------------------------------------------------
# snapshot_for_chapter
# ---------------------------------------------------------------------------


def test_snapshot_splits_plantable_and_collectable(
    tmp_path, fake_db, fake_kg, novel_data_with_milestones
):
    # Foreshadowings: fs1 target=4 <= 10 (collectable), fs2 target=-1 (plantable)
    fake_kg.get_pending_foreshadowings.return_value = [
        {
            "foreshadowing_id": "fs1",
            "content": "x",
            "planted_chapter": 2,
            "target_chapter": 4,
            "chapters_since_plant": 8,
            "last_mentioned_chapter": 2,
            "is_forgotten": False,
        },
        {
            "foreshadowing_id": "fs2",
            "content": "y",
            "planted_chapter": 3,
            "target_chapter": -1,
            "chapters_since_plant": 7,
            "last_mentioned_chapter": 3,
            "is_forgotten": False,
        },
    ]
    fake_db.query_debts.return_value = [
        {
            "debt_id": "d1",
            "status": "pending",
            "source_chapter": 5,
            "type": "must_pay_next",
            "description": "...",
            "urgency_level": "normal",
        }
    ]
    fake_db.get_all_terms.return_value = [{"term": "灵气", "category": "修炼"}]

    store = LedgerStore(
        project_path=tmp_path,
        db=fake_db,
        kg=fake_kg,
        novel_data=novel_data_with_milestones,
    )

    # Populate arc tracker so active_characters has something
    store.character_arc_tracker._states = {
        "林渊": {
            "current_stage": "trial",
            "milestones": [],
            "growth_summary": "",
            "last_appearance": 9,  # within 5 of chapter 10
        },
        "老者": {
            "current_stage": "introduction",
            "milestones": [],
            "growth_summary": "",
            "last_appearance": 2,  # >5 away from 10 → excluded
        },
    }

    snap = store.snapshot_for_chapter(chapter_number=10)

    assert len(snap["pending_debts"]) == 1
    assert snap["pending_debts"][0]["debt_id"] == "d1"

    fs_ids_collectable = {f["foreshadowing_id"] for f in snap["collectable_foreshadowings"]}
    fs_ids_plantable = {f["foreshadowing_id"] for f in snap["plantable_foreshadowings"]}
    assert fs_ids_collectable == {"fs1"}
    assert fs_ids_plantable == {"fs2"}

    active_names = {c["name"] for c in snap["active_characters"]}
    assert active_names == {"林渊"}

    assert snap["world_facts"] == [{"term": "灵气", "category": "修炼"}]

    pending_ms_ids = {m["milestone_id"] for m in snap["pending_milestones"]}
    # chapter 10 falls in m_001 range (5-10) but not m_002 (12-18)
    assert pending_ms_ids == {"m_001"}


# ---------------------------------------------------------------------------
# Write forwarding
# ---------------------------------------------------------------------------


def test_record_debt_forwards_to_obligation_tracker(tmp_path, fake_db):
    store = LedgerStore(project_path=tmp_path, db=fake_db)
    store.record_debt(
        debt_id="d1",
        source_chapter=3,
        debt_type="must_pay_next",
        description="主角答应师妹明天一起探索",
        urgency_level="high",
    )
    fake_db.insert_debt.assert_called_once()
    kwargs = fake_db.insert_debt.call_args.kwargs
    assert kwargs["debt_id"] == "d1"
    assert kwargs["source_chapter"] == 3
    assert kwargs["type"] == "must_pay_next"
    assert kwargs["urgency_level"] == "high"


def test_record_character_state_forwards(
    tmp_path, fake_db, novel_data_with_milestones
):
    store = LedgerStore(
        project_path=tmp_path,
        db=fake_db,
        novel_data=novel_data_with_milestones,
    )
    store.record_character_state(
        "林渊",
        chapter=5,
        health="injured",
        location="青云峰",
        emotional_state="anxious",
    )
    fake_db.insert_character_state.assert_called_once()
    kwargs = fake_db.insert_character_state.call_args.kwargs
    assert kwargs["character_id"] == "char_001"
    assert kwargs["chapter"] == 5
    assert kwargs["health"] == "injured"
    assert kwargs["location"] == "青云峰"
    assert kwargs["emotional_state"] == "anxious"


def test_record_character_state_no_db_is_noop(tmp_path):
    store = LedgerStore(project_path=tmp_path)
    # Must not raise even without db
    store.record_character_state("X", chapter=1, health="ok")


def test_record_foreshadowing_forwards(tmp_path, fake_kg):
    fake_kg.add_foreshadowing_node = MagicMock()
    fake_kg.get_pending_foreshadowings.return_value = []
    store = LedgerStore(project_path=tmp_path, kg=fake_kg)

    brief = {
        "foreshadowing_plant": ["主角发现神秘戒指"],
        "foreshadowing_collect": [],
    }
    count = store.record_foreshadowing(brief, chapter_number=3)
    assert count == 1
    fake_kg.add_foreshadowing_node.assert_called_once()


def test_record_foreshadowing_without_kg_returns_zero(tmp_path):
    store = LedgerStore(project_path=tmp_path)
    count = store.record_foreshadowing(
        {"foreshadowing_plant": ["x"]}, chapter_number=1
    )
    assert count == 0


# ---------------------------------------------------------------------------
# Lazy instantiation
# ---------------------------------------------------------------------------


def test_services_are_lazily_built(tmp_path, fake_db, fake_kg):
    store = LedgerStore(project_path=tmp_path, db=fake_db, kg=fake_kg)

    # Nothing built yet
    assert store._obligation_tracker is None
    assert store._foreshadowing_service is None
    assert store._character_arc_tracker is None
    assert store._entity_service is None

    # Touching each accessor builds exactly what is needed
    _ = store.obligation_tracker
    assert store._obligation_tracker is not None

    _ = store.foreshadowing_service
    assert store._foreshadowing_service is not None

    _ = store.character_arc_tracker
    assert store._character_arc_tracker is not None

    _ = store.entity_service
    assert store._entity_service is not None


def test_foreshadowing_service_none_without_kg(tmp_path, fake_db):
    store = LedgerStore(project_path=tmp_path, db=fake_db)
    assert store.foreshadowing_service is None


def test_entity_service_none_without_db(tmp_path, fake_kg):
    store = LedgerStore(project_path=tmp_path, kg=fake_kg)
    assert store.entity_service is None


def test_milestone_tracker_none_without_novel_data(tmp_path, fake_db):
    store = LedgerStore(project_path=tmp_path, db=fake_db)
    assert store.milestone_tracker is None


# ---------------------------------------------------------------------------
# Character-id resolution
# ---------------------------------------------------------------------------


def test_resolve_character_id_from_novel_data(
    tmp_path, novel_data_with_milestones
):
    store = LedgerStore(
        project_path=tmp_path, novel_data=novel_data_with_milestones
    )
    assert store._resolve_character_id("林渊") == "char_001"
    assert store._resolve_character_id("苏雪") == "char_002"
    assert store._resolve_character_id("未知") is None
    assert store._resolve_character_id("") is None


def test_resolve_character_id_handles_malformed_entries(tmp_path):
    # characters list contains non-dict entries
    novel_data = {
        "characters": [
            "not_a_dict",
            None,
            {"name": "主角"},  # missing character_id
            {"character_id": "cid_9", "name": "小师妹"},
        ]
    }
    store = LedgerStore(project_path=tmp_path, novel_data=novel_data)
    assert store._resolve_character_id("主角") is None
    assert store._resolve_character_id("小师妹") == "cid_9"
