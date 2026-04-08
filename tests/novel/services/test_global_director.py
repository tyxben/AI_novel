"""Tests for GlobalDirector service."""
import pytest
from src.novel.services.global_director import GlobalDirector


@pytest.fixture
def sample_novel():
    return {
        "title": "测试小说",
    }


@pytest.fixture
def sample_outline():
    return {
        "volumes": [
            {
                "volume_number": 1,
                "title": "卷一",
                "theme": "建立基地",
                "chapters": list(range(1, 36)),  # chapters 1-35
            },
            {
                "volume_number": 2,
                "title": "卷二",
                "theme": "对外扩张",
                "chapters": list(range(36, 71)),
            },
        ],
        "story_arcs": [
            {"arc_id": "main", "name": "主角崛起", "chapters": list(range(1, 100)), "phase": "active"},
            {"arc_id": "love", "name": "情感线", "chapters": list(range(15, 50)), "phase": "starting"},
        ],
        "chapters": [{"chapter_number": i} for i in range(1, 100)],
    }


class TestGlobalDirectorPosition:
    def test_calculate_position_volume_1(self, sample_novel, sample_outline):
        d = GlobalDirector(sample_novel, sample_outline)
        brief = d.analyze(20, [])
        pos = brief["position"]
        assert pos["volume_number"] == 1
        assert pos["volume_title"] == "卷一"
        assert pos["chapter_in_volume"] == 20
        assert pos["volume_total"] == 35
        assert pos["chapters_remaining_in_volume"] == 15

    def test_calculate_position_volume_2(self, sample_novel, sample_outline):
        d = GlobalDirector(sample_novel, sample_outline)
        brief = d.analyze(40, [])
        pos = brief["position"]
        assert pos["volume_number"] == 2

    def test_position_unknown_volume(self, sample_novel, sample_outline):
        d = GlobalDirector(sample_novel, sample_outline)
        brief = d.analyze(500, [])
        # Should not crash, fallback used
        assert "position" in brief


class TestGlobalDirectorPhase:
    def test_phase_setup_early_chapter(self, sample_novel, sample_outline):
        d = GlobalDirector(sample_novel, sample_outline)
        # Chapter 5 of 35 = 14% → setup
        brief = d.analyze(5, [])
        assert brief["phase"] == "setup"

    def test_phase_rising(self, sample_novel, sample_outline):
        d = GlobalDirector(sample_novel, sample_outline)
        # Chapter 15 of 35 = 43% → rising
        brief = d.analyze(15, [])
        assert brief["phase"] == "rising"

    def test_phase_climax(self, sample_novel, sample_outline):
        d = GlobalDirector(sample_novel, sample_outline)
        # Chapter 25 of 35 = 71% → climax
        brief = d.analyze(25, [])
        assert brief["phase"] == "climax"

    def test_phase_resolution(self, sample_novel, sample_outline):
        d = GlobalDirector(sample_novel, sample_outline)
        # Chapter 32 of 35 = 91% → resolution
        brief = d.analyze(32, [])
        assert brief["phase"] == "resolution"


class TestGlobalDirectorArcs:
    def test_active_arcs_chapter_5(self, sample_novel, sample_outline):
        d = GlobalDirector(sample_novel, sample_outline)
        brief = d.analyze(5, [])
        arcs = brief["active_arcs"]
        # Only main arc active at ch5 (love starts at 15)
        assert len(arcs) == 1
        assert arcs[0]["arc_id"] == "main"

    def test_active_arcs_chapter_20(self, sample_novel, sample_outline):
        d = GlobalDirector(sample_novel, sample_outline)
        brief = d.analyze(20, [])
        arcs = brief["active_arcs"]
        # Both main and love active at ch20
        assert len(arcs) == 2


class TestGlobalDirectorNotes:
    def test_notes_for_climax(self, sample_novel, sample_outline):
        d = GlobalDirector(sample_novel, sample_outline)
        brief = d.analyze(25, [])
        notes = brief["directorial_notes"]
        assert any("高潮" in n for n in notes)

    def test_notes_warning_at_volume_end(self, sample_novel, sample_outline):
        d = GlobalDirector(sample_novel, sample_outline)
        brief = d.analyze(33, [])  # 2 chapters from end
        notes = brief["directorial_notes"]
        assert any("收束" in n or "收线" in n for n in notes)

    def test_repetition_warning(self, sample_novel, sample_outline):
        d = GlobalDirector(sample_novel, sample_outline)
        recent = [
            {"chapter_number": 17, "title": "矿场整顿"},
            {"chapter_number": 18, "title": "矿道收网"},
            {"chapter_number": 19, "title": "矿洞异兆"},
        ]
        brief = d.analyze(20, recent)
        notes = brief["directorial_notes"]
        assert any("矿" in n and "重复" not in n for n in notes if "场景集中" in n) or any("矿" in n for n in notes)


class TestGlobalDirectorPromptFormat:
    def test_format_for_prompt_includes_position(self, sample_novel, sample_outline):
        d = GlobalDirector(sample_novel, sample_outline)
        brief = d.analyze(20, [])
        prompt = d.format_for_prompt(brief)
        assert "卷一" in prompt
        assert "导演" in prompt

    def test_format_for_prompt_empty_brief(self, sample_novel, sample_outline):
        d = GlobalDirector(sample_novel, sample_outline)
        brief = {"chapter_number": 1}
        prompt = d.format_for_prompt(brief)
        # Should handle missing fields gracefully
        assert isinstance(prompt, str)
