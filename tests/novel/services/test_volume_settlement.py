"""Tests for VolumeSettlement service."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.novel.services.volume_settlement import VolumeSettlement
from src.novel.storage.structured_db import StructuredDB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path):
    """Create a real StructuredDB in a temp directory."""
    db_path = tmp_path / "memory.db"
    db = StructuredDB(db_path)
    yield db
    db.close()


@pytest.fixture()
def outline_with_volumes():
    """Outline dict with explicit volumes."""
    return {
        "volumes": [
            {"volume_number": 1, "title": "初入江湖", "start_chapter": 1, "end_chapter": 30},
            {"volume_number": 2, "title": "门派风云", "start_chapter": 31, "end_chapter": 60},
        ],
        "chapters": [{"chapter_number": i} for i in range(1, 61)],
    }


@pytest.fixture()
def outline_no_volumes():
    """Outline dict without explicit volumes (infer from chapters)."""
    return {
        "chapters": [{"chapter_number": i} for i in range(1, 46)],
    }


def _insert_debts(db, debts_data):
    """Helper to insert test debts into the DB."""
    for d in debts_data:
        db.insert_debt(
            debt_id=d["debt_id"],
            source_chapter=d["source_chapter"],
            type=d["type"],
            description=d["description"],
            status=d.get("status", "pending"),
            urgency_level=d.get("urgency_level", "normal"),
            target_chapter=d.get("target_chapter"),
        )


def _insert_arcs(db, arcs_data):
    """Helper to insert test arcs into the DB."""
    for a in arcs_data:
        db.insert_story_unit(
            arc_id=a["arc_id"],
            volume_id=a.get("volume_id", "1"),
            name=a["name"],
            chapters_json=json.dumps(a.get("chapters", [])),
            phase=a.get("phase", "setup"),
            status=a.get("status", "active"),
            completion_rate=a.get("completion_rate", 0.0),
            turning_point=a.get("turning_point"),
        )


# ===========================================================================
# TestVolumeDetection
# ===========================================================================


class TestVolumeDetection:
    def test_get_current_volume(self, tmp_db, outline_with_volumes):
        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        vol = vs.get_current_volume(15)
        assert vol is not None
        assert vol["volume_number"] == 1
        assert vol["title"] == "初入江湖"

    def test_get_current_volume_second(self, tmp_db, outline_with_volumes):
        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        vol = vs.get_current_volume(45)
        assert vol is not None
        assert vol["volume_number"] == 2
        assert vol["title"] == "门派风云"

    def test_get_current_volume_not_found(self, tmp_db, outline_with_volumes):
        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        vol = vs.get_current_volume(100)
        assert vol is None

    def test_is_volume_ending_within_threshold(self, tmp_db, outline_with_volumes):
        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        # Chapter 28 is 2 chapters from end of volume 1 (end=30), 30-28=2 < 3
        assert vs.is_volume_ending(28) is True
        # Chapter 29 is 1 chapter from end, 30-29=1 < 3
        assert vs.is_volume_ending(29) is True
        # Chapter 30 is 0 chapters from end, 30-30=0 < 3
        assert vs.is_volume_ending(30) is True

    def test_is_volume_ending_not_near_end(self, tmp_db, outline_with_volumes):
        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        # Chapter 20 is 10 chapters from end, 30-20=10 >= 3
        assert vs.is_volume_ending(20) is False
        # Chapter 27 is 3 chapters from end, 30-27=3 >= 3 (NOT < 3)
        assert vs.is_volume_ending(27) is False

    def test_is_volume_ending_invalid_chapter(self, tmp_db, outline_with_volumes):
        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        assert vs.is_volume_ending(999) is False

    def test_infer_volumes_from_chapter_count(self, tmp_db, outline_no_volumes):
        vs = VolumeSettlement(db=tmp_db, outline=outline_no_volumes)
        assert len(vs.volumes) == 2  # 45 chapters = 2 volumes (30 + 15)
        assert vs.volumes[0]["start_chapter"] == 1
        assert vs.volumes[0]["end_chapter"] == 30
        assert vs.volumes[1]["start_chapter"] == 31
        assert vs.volumes[1]["end_chapter"] == 45

    def test_infer_volumes_empty_outline(self, tmp_db):
        vs = VolumeSettlement(db=tmp_db, outline={})
        assert vs.volumes == []

    def test_parse_explicit_volumes_takes_priority(self, tmp_db):
        outline = {
            "volumes": [
                {"volume_number": 1, "title": "V1", "start_chapter": 1, "end_chapter": 10},
            ],
            "chapters": [{"chapter_number": i} for i in range(1, 100)],
        }
        vs = VolumeSettlement(db=tmp_db, outline=outline)
        assert len(vs.volumes) == 1
        assert vs.volumes[0]["end_chapter"] == 10


# ===========================================================================
# TestSettlementBrief
# ===========================================================================


class TestSettlementBrief:
    def test_settlement_in_ending_zone(self, tmp_db, outline_with_volumes):
        # Insert debts that should trigger settlement
        _insert_debts(tmp_db, [
            {
                "debt_id": "d1",
                "source_chapter": 5,
                "type": "must_pay_next",
                "description": "主角承诺明天帮忙",
                "urgency_level": "critical",
            },
            {
                "debt_id": "d2",
                "source_chapter": 10,
                "type": "pay_within_3",
                "description": "暗线伏笔需展开",
            },
            {
                "debt_id": "d3",
                "source_chapter": 15,
                "type": "long_tail_payoff",
                "description": "远期悬念",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        brief = vs.get_settlement_brief(29)  # 30 - 29 = 1 < 3

        assert brief["is_settlement_zone"] is True
        assert brief["volume"]["volume_number"] == 1
        assert brief["chapters_remaining"] == 1
        assert len(brief["must_resolve"]) >= 1  # d1 (critical)
        assert len(brief["should_resolve"]) >= 1  # d2 (pay_within_3)
        assert len(brief["can_carry_over"]) >= 1  # d3 (long_tail)

    def test_no_settlement_when_not_ending(self, tmp_db, outline_with_volumes):
        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        brief = vs.get_settlement_brief(15)  # 30 - 15 = 15 >= 3

        assert brief["is_settlement_zone"] is False
        assert brief["volume"]["volume_number"] == 1
        assert brief["chapters_remaining"] == 15

    def test_no_settlement_invalid_chapter(self, tmp_db, outline_with_volumes):
        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        brief = vs.get_settlement_brief(999)

        assert brief["is_settlement_zone"] is False
        assert brief["settlement_prompt"] == ""

    def test_categorize_debts(self, tmp_db, outline_with_volumes):
        _insert_debts(tmp_db, [
            {
                "debt_id": "must1",
                "source_chapter": 3,
                "type": "must_pay_next",
                "description": "紧急债务",
            },
            {
                "debt_id": "high1",
                "source_chapter": 5,
                "type": "pay_within_3",
                "description": "高优先级",
                "urgency_level": "high",
            },
            {
                "debt_id": "within3",
                "source_chapter": 8,
                "type": "pay_within_3",
                "description": "三章内解决",
            },
            {
                "debt_id": "long1",
                "source_chapter": 2,
                "type": "long_tail_payoff",
                "description": "长线伏笔",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        brief = vs.get_settlement_brief(29)

        # must_pay_next goes to must_resolve
        must_ids = [d["debt_id"] for d in brief["must_resolve"]]
        assert "must1" in must_ids
        # high urgency pay_within_3 also goes to must_resolve
        assert "high1" in must_ids

        # Normal pay_within_3 goes to should_resolve
        should_ids = [d["debt_id"] for d in brief["should_resolve"]]
        assert "within3" in should_ids

        # long_tail_payoff goes to can_carry_over
        carry_ids = [d["debt_id"] for d in brief["can_carry_over"]]
        assert "long1" in carry_ids

    def test_settlement_prompt_format(self, tmp_db, outline_with_volumes):
        _insert_debts(tmp_db, [
            {
                "debt_id": "d1",
                "source_chapter": 5,
                "type": "must_pay_next",
                "description": "必须解决的事",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        brief = vs.get_settlement_brief(29)

        prompt = brief["settlement_prompt"]
        assert "卷末收束指令" in prompt
        assert "初入江湖" in prompt
        assert "必须在本卷解决" in prompt
        assert "必须解决的事" in prompt
        assert "推进以上债务的解决" in prompt

    def test_settlement_with_no_debts(self, tmp_db, outline_with_volumes):
        """Settlement zone with no pending debts should still report zone status."""
        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        brief = vs.get_settlement_brief(29)

        assert brief["is_settlement_zone"] is True
        assert brief["must_resolve"] == []
        assert brief["should_resolve"] == []
        assert brief["can_carry_over"] == []

    def test_fulfilled_debts_excluded(self, tmp_db, outline_with_volumes):
        """Fulfilled debts should not appear in settlement brief."""
        _insert_debts(tmp_db, [
            {
                "debt_id": "fulfilled1",
                "source_chapter": 5,
                "type": "must_pay_next",
                "description": "已完成债务",
                "status": "fulfilled",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        brief = vs.get_settlement_brief(29)

        # get_debts_for_chapter only returns pending/overdue
        assert brief["must_resolve"] == []
        assert brief["should_resolve"] == []
        assert brief["can_carry_over"] == []


# ===========================================================================
# TestArcProgression
# ===========================================================================


class TestArcProgression:
    def test_advance_phase_setup_to_escalation(self, tmp_db, outline_with_volumes):
        _insert_arcs(tmp_db, [
            {
                "arc_id": "arc1",
                "name": "主角修炼",
                "chapters": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
                "phase": "setup",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        # Chapter 6: (6-1)/(20-1) = 5/19 = 0.263 >= 0.25 -> escalation
        changed = vs.advance_arc_phases(6)

        assert len(changed) == 1
        assert changed[0]["arc_id"] == "arc1"
        assert changed[0]["old_phase"] == "setup"
        assert changed[0]["new_phase"] == "escalation"

    def test_advance_phase_to_climax(self, tmp_db, outline_with_volumes):
        _insert_arcs(tmp_db, [
            {
                "arc_id": "arc1",
                "name": "主角修炼",
                "chapters": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
                "phase": "escalation",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        # Chapter 11: (11-1)/(20-1) = 10/19 = 0.526 >= 0.5 -> climax
        changed = vs.advance_arc_phases(11)

        assert len(changed) == 1
        assert changed[0]["new_phase"] == "climax"

    def test_advance_phase_to_resolution(self, tmp_db, outline_with_volumes):
        _insert_arcs(tmp_db, [
            {
                "arc_id": "arc1",
                "name": "主角修炼",
                "chapters": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
                "phase": "climax",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        # Chapter 16: (16-1)/(20-1) = 15/19 = 0.789 >= 0.75 -> resolution
        changed = vs.advance_arc_phases(16)

        assert len(changed) == 1
        assert changed[0]["new_phase"] == "resolution"

    def test_mark_completed_past_end(self, tmp_db, outline_with_volumes):
        _insert_arcs(tmp_db, [
            {
                "arc_id": "arc1",
                "name": "短弧线",
                "chapters": [1, 2, 3, 4, 5],
                "phase": "resolution",
                "status": "active",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        changed = vs.advance_arc_phases(10)  # Well past end chapter 5

        assert len(changed) == 1
        assert changed[0]["new_phase"] == "completed"
        assert changed[0]["progress"] == 1.0

        # Verify DB was updated
        units = tmp_db.query_story_units()
        assert units[0]["status"] == "completed"
        assert units[0]["completion_rate"] == 1.0

    def test_no_change_same_phase(self, tmp_db, outline_with_volumes):
        _insert_arcs(tmp_db, [
            {
                "arc_id": "arc1",
                "name": "弧线",
                "chapters": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
                "phase": "setup",
                "completion_rate": 0.0,
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        # Chapter 2: (2-1)/(20-1) = 1/19 = 0.052 -> still setup
        changed = vs.advance_arc_phases(2)

        # No phase change, only completion_rate update (0.05 > 0.05 threshold is close)
        assert len(changed) == 0

    def test_arc_not_started_yet(self, tmp_db, outline_with_volumes):
        _insert_arcs(tmp_db, [
            {
                "arc_id": "arc_future",
                "name": "未来弧线",
                "chapters": [31, 32, 33, 34, 35],
                "phase": "setup",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        changed = vs.advance_arc_phases(5)  # Before arc starts

        assert len(changed) == 0

    def test_arc_with_empty_chapters(self, tmp_db, outline_with_volumes):
        _insert_arcs(tmp_db, [
            {
                "arc_id": "arc_empty",
                "name": "空弧线",
                "chapters": [],
                "phase": "setup",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        changed = vs.advance_arc_phases(10)

        assert len(changed) == 0

    def test_multiple_arcs_some_change(self, tmp_db, outline_with_volumes):
        _insert_arcs(tmp_db, [
            {
                "arc_id": "arc1",
                "name": "弧线A",
                "chapters": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
                "phase": "setup",
            },
            {
                "arc_id": "arc2",
                "name": "弧线B",
                "chapters": [5, 6, 7, 8, 9, 10],
                "phase": "setup",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        # Chapter 8: arc1 -> (8-1)/19=0.368 -> escalation; arc2 -> (8-5)/5=0.6 -> climax
        changed = vs.advance_arc_phases(8)

        assert len(changed) == 2
        arc1_change = next(c for c in changed if c["arc_id"] == "arc1")
        arc2_change = next(c for c in changed if c["arc_id"] == "arc2")
        assert arc1_change["new_phase"] == "escalation"
        assert arc2_change["new_phase"] == "climax"


# ===========================================================================
# TestArcPrompt
# ===========================================================================


class TestArcPrompt:
    def test_arc_prompt_with_active_arcs(self, tmp_db, outline_with_volumes):
        _insert_arcs(tmp_db, [
            {
                "arc_id": "arc1",
                "name": "主角修炼",
                "chapters": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                "phase": "escalation",
            },
            {
                "arc_id": "arc2",
                "name": "门派斗争",
                "chapters": [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
                "phase": "climax",
                "turning_point": "掌门叛变",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        prompt = vs.get_arc_prompt(7)

        assert "故事弧线推进指引" in prompt
        assert "主角修炼" in prompt
        assert "escalation" in prompt
        assert "门派斗争" in prompt
        assert "climax" in prompt
        assert "掌门叛变" in prompt

    def test_arc_prompt_empty_when_no_arcs(self, tmp_db, outline_with_volumes):
        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        prompt = vs.get_arc_prompt(5)
        assert prompt == ""

    def test_arc_prompt_filters_out_of_range_arcs(self, tmp_db, outline_with_volumes):
        _insert_arcs(tmp_db, [
            {
                "arc_id": "arc_far",
                "name": "远期弧线",
                "chapters": [40, 41, 42, 43, 44, 45],
                "phase": "setup",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        prompt = vs.get_arc_prompt(5)  # Chapter 5 is outside arc range

        assert prompt == ""

    def test_arc_prompt_no_turning_point_in_setup(self, tmp_db, outline_with_volumes):
        _insert_arcs(tmp_db, [
            {
                "arc_id": "arc1",
                "name": "弧线",
                "chapters": [1, 2, 3, 4, 5],
                "phase": "setup",
                "turning_point": "不应显示",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        prompt = vs.get_arc_prompt(3)

        assert "故事弧线推进指引" in prompt
        assert "弧线" in prompt
        assert "不应显示" not in prompt  # turning_point only shows in climax/resolution


# ===========================================================================
# TestVolumeSummary
# ===========================================================================


class TestVolumeSummary:
    def test_volume_summary_with_debts(self, tmp_db, outline_with_volumes):
        # Insert debts in volume 1
        _insert_debts(tmp_db, [
            {
                "debt_id": "v1d1",
                "source_chapter": 5,
                "type": "must_pay_next",
                "description": "债务1",
            },
            {
                "debt_id": "v1d2",
                "source_chapter": 10,
                "type": "pay_within_3",
                "description": "债务2",
                "status": "fulfilled",
            },
        ])
        # Insert debts in volume 2
        _insert_debts(tmp_db, [
            {
                "debt_id": "v2d1",
                "source_chapter": 35,
                "type": "long_tail_payoff",
                "description": "债务3",
            },
        ])

        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        summary = vs.get_volume_summary()

        assert len(summary) == 2

        vol1 = summary[0]
        assert vol1["volume_number"] == 1
        # v1d1 is pending, v1d2 is fulfilled but get_debts_for_chapter
        # only returns pending/overdue so fulfilled won't show
        assert vol1["debts_total"] >= 1

        vol2 = summary[1]
        assert vol2["volume_number"] == 2

    def test_volume_summary_empty_volumes(self, tmp_db):
        vs = VolumeSettlement(db=tmp_db, outline={})
        summary = vs.get_volume_summary()
        assert summary == []

    def test_volume_summary_no_debts(self, tmp_db, outline_with_volumes):
        vs = VolumeSettlement(db=tmp_db, outline=outline_with_volumes)
        summary = vs.get_volume_summary()

        assert len(summary) == 2
        for vol in summary:
            assert vol["debts_total"] == 0
            assert vol["debts_pending"] == 0
            assert vol["debts_fulfilled"] == 0
            assert vol["settlement_rate"] == 0


# ===========================================================================
# TestNullDb
# ===========================================================================


class TestNullDb:
    """Test behavior when db is None."""

    def test_get_active_arcs_none_db(self, outline_with_volumes):
        vs = VolumeSettlement(db=None, outline=outline_with_volumes)
        arcs = vs._get_active_arcs()
        assert arcs == []

    def test_arc_prompt_none_db(self, outline_with_volumes):
        vs = VolumeSettlement(db=None, outline=outline_with_volumes)
        prompt = vs.get_arc_prompt(5)
        assert prompt == ""

    def test_advance_arc_phases_none_db(self, outline_with_volumes):
        vs = VolumeSettlement(db=None, outline=outline_with_volumes)
        changed = vs.advance_arc_phases(10)
        assert changed == []
