"""Tests for CharacterArcTracker."""
import pytest
from src.novel.services.character_arc_tracker import CharacterArcTracker


@pytest.fixture
def tracker():
    return CharacterArcTracker()


@pytest.fixture
def characters():
    return [
        {"name": "林辰"},
        {"name": "苏晚照"},
        {"name": "黑风煞"},
    ]


class TestArcTrackerUpdate:
    def test_detects_awakening(self, tracker, characters):
        summary = "林辰在战斗中突然觉醒了体内的兵煞之力，明白了真正的战斗之道。"
        tracker.update_from_chapter(16, summary, characters)
        state = tracker.get_state("林辰")
        assert state["current_stage"] == "awakening"
        assert state["last_appearance"] == 16

    def test_detects_conflict(self, tracker, characters):
        summary = "林辰与苏晚照因为玉牌的事情爆发了争执，两人决裂。"
        tracker.update_from_chapter(20, summary, characters)
        # Both characters should be tracked
        assert tracker.get_state("林辰")["current_stage"] == "conflict"
        assert tracker.get_state("苏晚照")["current_stage"] == "conflict"

    def test_milestone_recorded_on_stage_change(self, tracker, characters):
        # First: intro
        tracker.update_from_chapter(1, "林辰登场，在矿场中挣扎求生。", characters)
        # Then: awakening
        tracker.update_from_chapter(16, "林辰突然觉醒了体内的力量。", characters)
        state = tracker.get_state("林辰")
        milestones = state["milestones"]
        assert len(milestones) >= 1
        assert milestones[-1]["to_stage"] == "awakening"
        assert milestones[-1]["chapter"] == 16

    def test_ignores_unmentioned_character(self, tracker, characters):
        summary = "林辰带着李四前往矿场。"
        tracker.update_from_chapter(5, summary, characters)
        # 苏晚照 not mentioned, should not be tracked
        assert tracker.get_state("苏晚照") == {}


class TestArcTrackerPromptFormat:
    def test_format_includes_active_chars(self, tracker, characters):
        tracker.update_from_chapter(16, "林辰觉醒了。", characters)
        prompt = tracker.format_for_prompt(["林辰"], 17)
        assert "林辰" in prompt
        assert "觉醒" in prompt or "突破" in prompt
        assert "弧线" in prompt

    def test_format_warns_long_absence(self, tracker, characters):
        tracker.update_from_chapter(1, "林辰登场。", characters)
        prompt = tracker.format_for_prompt(["林辰"], 10)
        assert "9" in prompt or "未出场" in prompt or "重新介绍" in prompt

    def test_format_empty_for_unknown_char(self, tracker, characters):
        prompt = tracker.format_for_prompt(["未知角色"], 1)
        assert prompt == ""


class TestArcTrackerPersistence:
    def test_to_dict_and_from_dict(self, tracker, characters):
        tracker.update_from_chapter(5, "林辰试炼受挫，反思自己。", characters)
        data = tracker.to_dict()

        new_tracker = CharacterArcTracker()
        new_tracker.from_dict(data)

        original = tracker.get_state("林辰")
        restored = new_tracker.get_state("林辰")
        assert original == restored

    def test_empty_summary_no_crash(self, tracker, characters):
        tracker.update_from_chapter(1, "", characters)
        # Should not crash, no states added
        assert tracker.get_all_states() == {}
