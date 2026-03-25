"""Tests for ObligationTracker service.

Uses the in-memory fallback (db=None) for fast, isolated tests.
Also tests the DB-backed path using a real in-memory SQLite StructuredDB.
"""

from __future__ import annotations

import pytest

from src.novel.services.obligation_tracker import ObligationTracker


# ---------------------------------------------------------------
# Fixture: in-memory tracker (dict-based fallback)
# ---------------------------------------------------------------


@pytest.fixture()
def tracker() -> ObligationTracker:
    """Create a tracker with in-memory fallback (no DB)."""
    return ObligationTracker(db=None)


# ---------------------------------------------------------------
# Fixture: DB-backed tracker (real SQLite in-memory)
# ---------------------------------------------------------------


@pytest.fixture()
def db_tracker(tmp_path):
    """Create a tracker backed by a real in-memory StructuredDB."""
    from src.novel.storage.structured_db import StructuredDB

    db_path = tmp_path / "test_debts.db"
    db = StructuredDB(str(db_path))
    t = ObligationTracker(db=db)
    yield t
    db.close()


# ---------------------------------------------------------------
# Helper to add sample debts
# ---------------------------------------------------------------


def _add_sample_debts(tracker: ObligationTracker) -> None:
    """Add a standard set of debts for testing."""
    tracker.add_debt(
        debt_id="debt_must_1",
        source_chapter=3,
        debt_type="must_pay_next",
        description="主角答应师妹明天去密林",
        urgency_level="normal",
    )
    tracker.add_debt(
        debt_id="debt_pay3_1",
        source_chapter=2,
        debt_type="pay_within_3",
        description="门派比武悬念未揭晓",
        urgency_level="normal",
    )
    tracker.add_debt(
        debt_id="debt_long_1",
        source_chapter=1,
        debt_type="long_tail_payoff",
        description="神秘老者留下的谜团",
        urgency_level="normal",
    )


# ===================================================================
# Tests: in-memory fallback
# ===================================================================


class TestAddDebt:
    def test_add_debt_basic(self, tracker):
        tracker.add_debt(
            debt_id="d1",
            source_chapter=5,
            debt_type="must_pay_next",
            description="主角承诺报仇",
        )
        stats = tracker.get_debt_statistics()
        assert stats["pending_count"] == 1

    def test_add_debt_with_optional_fields(self, tracker):
        tracker.add_debt(
            debt_id="d2",
            source_chapter=3,
            debt_type="pay_within_3",
            description="一起去冒险",
            target_chapter=6,
            urgency_level="high",
            character_pending=["找到宝藏"],
            emotional_debt="对师父的愧疚",
        )
        debts = tracker.get_debts_for_chapter(10)
        assert len(debts) == 1
        assert debts[0]["urgency_level"] == "high"
        assert debts[0]["target_chapter"] == 6
        assert debts[0]["emotional_debt"] == "对师父的愧疚"

    def test_add_multiple_debts(self, tracker):
        for i in range(5):
            tracker.add_debt(
                debt_id=f"d{i}",
                source_chapter=i + 1,
                debt_type="pay_within_3",
                description=f"债务 {i}",
            )
        stats = tracker.get_debt_statistics()
        assert stats["pending_count"] == 5


class TestGetDebtsForChapter:
    def test_returns_only_pending_and_overdue(self, tracker):
        _add_sample_debts(tracker)
        # Fulfill one debt
        tracker.mark_debt_fulfilled("debt_long_1", chapter_num=5)

        debts = tracker.get_debts_for_chapter(10)
        debt_ids = [d["debt_id"] for d in debts]
        assert "debt_must_1" in debt_ids
        assert "debt_pay3_1" in debt_ids
        assert "debt_long_1" not in debt_ids  # fulfilled, excluded

    def test_respects_chapter_boundary(self, tracker):
        _add_sample_debts(tracker)
        # Chapter 2: only debts from chapter 1 should be visible
        debts = tracker.get_debts_for_chapter(2)
        assert len(debts) == 1
        assert debts[0]["source_chapter"] == 1

    def test_sorted_by_urgency(self, tracker):
        tracker.add_debt(
            debt_id="d_normal",
            source_chapter=1,
            debt_type="pay_within_3",
            description="普通债务",
            urgency_level="normal",
        )
        tracker.add_debt(
            debt_id="d_critical",
            source_chapter=2,
            debt_type="must_pay_next",
            description="紧急债务",
            urgency_level="critical",
        )
        tracker.add_debt(
            debt_id="d_high",
            source_chapter=3,
            debt_type="pay_within_3",
            description="较急债务",
            urgency_level="high",
        )
        debts = tracker.get_debts_for_chapter(10)
        urgencies = [d["urgency_level"] for d in debts]
        assert urgencies == ["critical", "high", "normal"]

    def test_empty_when_no_debts(self, tracker):
        debts = tracker.get_debts_for_chapter(5)
        assert debts == []

    def test_empty_when_all_debts_from_same_chapter(self, tracker):
        tracker.add_debt(
            debt_id="d1",
            source_chapter=5,
            debt_type="must_pay_next",
            description="同章债务",
        )
        debts = tracker.get_debts_for_chapter(5)
        assert len(debts) == 0


class TestMarkDebtFulfilled:
    def test_marks_fulfilled(self, tracker):
        tracker.add_debt(
            debt_id="d1",
            source_chapter=3,
            debt_type="must_pay_next",
            description="要报仇",
        )
        tracker.mark_debt_fulfilled("d1", chapter_num=4, note="已复仇")
        stats = tracker.get_debt_statistics()
        assert stats["pending_count"] == 0
        assert stats["fulfilled_count"] == 1

    def test_fulfilled_debt_not_in_chapter_query(self, tracker):
        tracker.add_debt(
            debt_id="d1",
            source_chapter=3,
            debt_type="must_pay_next",
            description="要报仇",
        )
        tracker.mark_debt_fulfilled("d1", chapter_num=4)
        debts = tracker.get_debts_for_chapter(10)
        assert len(debts) == 0

    def test_mark_nonexistent_debt(self, tracker):
        # Should not raise
        tracker.mark_debt_fulfilled("nonexistent", chapter_num=1)


class TestEscalateDebts:
    def test_must_pay_next_escalates_after_1_chapter(self, tracker):
        tracker.add_debt(
            debt_id="d1",
            source_chapter=3,
            debt_type="must_pay_next",
            description="必须下一章解决",
        )
        # source=3, current=5 -> 3+1=4 < 5 -> should escalate
        count = tracker.escalate_debts(current_chapter=5)
        assert count == 1
        debts = tracker.get_debts_for_chapter(10)
        assert debts[0]["urgency_level"] == "critical"
        assert debts[0]["status"] == "overdue"

    def test_must_pay_next_no_escalation_at_boundary(self, tracker):
        tracker.add_debt(
            debt_id="d1",
            source_chapter=3,
            debt_type="must_pay_next",
            description="下一章解决",
        )
        # source=3, current=4 -> 3+1=4 is NOT < 4 -> no escalation
        count = tracker.escalate_debts(current_chapter=4)
        assert count == 0

    def test_pay_within_3_escalates_after_3_chapters(self, tracker):
        tracker.add_debt(
            debt_id="d1",
            source_chapter=2,
            debt_type="pay_within_3",
            description="三章内解决",
        )
        # source=2, current=6 -> 2+3=5 < 6 -> should escalate
        count = tracker.escalate_debts(current_chapter=6)
        assert count == 1
        debts = tracker.get_debts_for_chapter(10)
        assert debts[0]["urgency_level"] == "high"
        assert debts[0]["status"] == "overdue"

    def test_pay_within_3_no_escalation_within_window(self, tracker):
        tracker.add_debt(
            debt_id="d1",
            source_chapter=2,
            debt_type="pay_within_3",
            description="三章内解决",
        )
        # source=2, current=5 -> 2+3=5 is NOT < 5 -> no escalation
        count = tracker.escalate_debts(current_chapter=5)
        assert count == 0

    def test_long_tail_never_escalates(self, tracker):
        tracker.add_debt(
            debt_id="d1",
            source_chapter=1,
            debt_type="long_tail_payoff",
            description="长线伏笔",
        )
        count = tracker.escalate_debts(current_chapter=100)
        assert count == 0

    def test_already_fulfilled_not_escalated(self, tracker):
        tracker.add_debt(
            debt_id="d1",
            source_chapter=3,
            debt_type="must_pay_next",
            description="已解决",
        )
        tracker.mark_debt_fulfilled("d1", chapter_num=4)
        count = tracker.escalate_debts(current_chapter=10)
        assert count == 0

    def test_escalation_records_history(self, tracker):
        tracker.add_debt(
            debt_id="d1",
            source_chapter=3,
            debt_type="must_pay_next",
            description="有历史记录",
        )
        tracker.escalate_debts(current_chapter=5)

        # Check that escalation_history is updated
        import json
        debts = tracker.get_debts_for_chapter(10)
        history = json.loads(debts[0]["escalation_history"])
        assert len(history) == 1
        assert history[0]["new_urgency"] == "critical"
        assert history[0]["chapter"] == 5

    def test_multiple_debts_mixed_escalation(self, tracker):
        _add_sample_debts(tracker)
        # At chapter 10: must_pay_next(source=3) and pay_within_3(source=2)
        # should escalate, long_tail(source=1) should NOT
        count = tracker.escalate_debts(current_chapter=10)
        assert count == 2  # must_pay_next + pay_within_3


class TestGetSummaryForWriter:
    def test_empty_when_no_debts(self, tracker):
        summary = tracker.get_summary_for_writer(chapter_num=5)
        assert summary == ""

    def test_contains_header(self, tracker):
        _add_sample_debts(tracker)
        summary = tracker.get_summary_for_writer(chapter_num=10)
        assert "待解决的叙事债务" in summary

    def test_groups_by_urgency(self, tracker):
        tracker.add_debt(
            debt_id="d_critical",
            source_chapter=1,
            debt_type="must_pay_next",
            description="紧急事项",
            urgency_level="critical",
        )
        tracker.add_debt(
            debt_id="d_normal",
            source_chapter=2,
            debt_type="long_tail_payoff",
            description="普通事项",
            urgency_level="normal",
        )
        summary = tracker.get_summary_for_writer(chapter_num=10)
        assert "必须在本章解决" in summary
        assert "长线伏笔" in summary
        assert "紧急事项" in summary
        assert "普通事项" in summary

    def test_truncation(self, tracker):
        # Add many debts with long descriptions to force truncation
        for i in range(20):
            tracker.add_debt(
                debt_id=f"d{i}",
                source_chapter=i + 1,
                debt_type="must_pay_next",
                description="这是一个非常长的债务描述" * 10,
                urgency_level="critical",
            )
        summary = tracker.get_summary_for_writer(chapter_num=50, max_tokens=100)
        assert "已截断" in summary

    def test_max_tokens_respected(self, tracker):
        tracker.add_debt(
            debt_id="d1",
            source_chapter=1,
            debt_type="must_pay_next",
            description="简短描述",
            urgency_level="critical",
        )
        summary = tracker.get_summary_for_writer(
            chapter_num=10, max_tokens=5000
        )
        # Estimate: summary should be well under max_tokens
        assert len(summary) * 2 <= 5000


class TestGetDebtStatistics:
    def test_all_zeros_when_empty(self, tracker):
        stats = tracker.get_debt_statistics()
        assert stats["pending_count"] == 0
        assert stats["fulfilled_count"] == 0
        assert stats["overdue_count"] == 0
        assert stats["abandoned_count"] == 0
        assert stats["avg_fulfillment_chapters"] == 0

    def test_counts_correct(self, tracker):
        _add_sample_debts(tracker)
        stats = tracker.get_debt_statistics()
        assert stats["pending_count"] == 3
        assert stats["fulfilled_count"] == 0

    def test_counts_after_fulfillment(self, tracker):
        _add_sample_debts(tracker)
        tracker.mark_debt_fulfilled("debt_must_1", chapter_num=5)
        stats = tracker.get_debt_statistics()
        assert stats["pending_count"] == 2
        assert stats["fulfilled_count"] == 1

    def test_avg_fulfillment_chapters(self, tracker):
        tracker.add_debt(
            debt_id="d1",
            source_chapter=3,
            debt_type="must_pay_next",
            description="债务1",
        )
        tracker.add_debt(
            debt_id="d2",
            source_chapter=5,
            debt_type="pay_within_3",
            description="债务2",
        )
        tracker.mark_debt_fulfilled("d1", chapter_num=5)  # 5-3 = 2
        tracker.mark_debt_fulfilled("d2", chapter_num=9)  # 9-5 = 4
        stats = tracker.get_debt_statistics()
        assert stats["avg_fulfillment_chapters"] == 3.0  # (2+4)/2

    def test_counts_after_escalation(self, tracker):
        tracker.add_debt(
            debt_id="d1",
            source_chapter=3,
            debt_type="must_pay_next",
            description="紧急",
        )
        tracker.escalate_debts(current_chapter=10)
        stats = tracker.get_debt_statistics()
        assert stats["pending_count"] == 0
        assert stats["overdue_count"] == 1


# ===================================================================
# Tests: DB-backed tracker (real SQLite)
# ===================================================================


class TestDBBacked:
    def test_add_and_query(self, db_tracker):
        db_tracker.add_debt(
            debt_id="db_d1",
            source_chapter=3,
            debt_type="must_pay_next",
            description="DB测试债务",
        )
        debts = db_tracker.get_debts_for_chapter(10)
        assert len(debts) == 1
        assert debts[0]["description"] == "DB测试债务"

    def test_fulfill_in_db(self, db_tracker):
        db_tracker.add_debt(
            debt_id="db_d2",
            source_chapter=2,
            debt_type="pay_within_3",
            description="DB测试",
        )
        db_tracker.mark_debt_fulfilled("db_d2", chapter_num=4, note="完成了")
        stats = db_tracker.get_debt_statistics()
        assert stats["fulfilled_count"] == 1
        assert stats["pending_count"] == 0

    def test_escalate_in_db(self, db_tracker):
        db_tracker.add_debt(
            debt_id="db_d3",
            source_chapter=1,
            debt_type="must_pay_next",
            description="DB升级测试",
        )
        count = db_tracker.escalate_debts(current_chapter=5)
        assert count == 1
        stats = db_tracker.get_debt_statistics()
        assert stats["overdue_count"] == 1

    def test_summary_from_db(self, db_tracker):
        db_tracker.add_debt(
            debt_id="db_d4",
            source_chapter=1,
            debt_type="must_pay_next",
            description="紧急债务描述",
            urgency_level="critical",
        )
        summary = db_tracker.get_summary_for_writer(chapter_num=5)
        assert "紧急债务描述" in summary

    def test_statistics_from_db(self, db_tracker):
        db_tracker.add_debt(
            debt_id="db_d5",
            source_chapter=1,
            debt_type="pay_within_3",
            description="统计测试",
        )
        db_tracker.add_debt(
            debt_id="db_d6",
            source_chapter=2,
            debt_type="must_pay_next",
            description="统计测试2",
        )
        db_tracker.mark_debt_fulfilled("db_d5", chapter_num=3)
        stats = db_tracker.get_debt_statistics()
        assert stats["pending_count"] == 1
        assert stats["fulfilled_count"] == 1
        assert stats["avg_fulfillment_chapters"] == 2.0  # 3-1=2
