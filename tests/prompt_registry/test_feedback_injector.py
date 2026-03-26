"""Tests for FeedbackInjector -- QualityReviewer-to-Writer feedback bridge."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.prompt_registry.feedback_injector import FeedbackInjector
from src.prompt_registry.registry import PromptRegistry


@pytest.fixture()
def registry(tmp_path: Path) -> PromptRegistry:
    """Create a PromptRegistry backed by a temporary SQLite DB."""
    db_path = str(tmp_path / "test_feedback.db")
    return PromptRegistry(db_path=db_path)


@pytest.fixture()
def injector(registry: PromptRegistry) -> FeedbackInjector:
    return FeedbackInjector(registry)


# ---------------------------------------------------------------------------
# save_chapter_feedback
# ---------------------------------------------------------------------------


class TestSaveChapterFeedback:
    """Tests for FeedbackInjector.save_chapter_feedback()."""

    def test_full_quality_report(self, injector: FeedbackInjector, registry: PromptRegistry) -> None:
        """Full report with rule_check, scores, and suggestions is saved correctly."""
        report = {
            "rule_check": {
                "passed": False,
                "ai_flavor_issues": ["issue1", "issue2"],
                "repetition_issues": ["rep1"],
            },
            "scores": {
                "plot": 8.5,
                "character": 5.0,
                "prose": 7.0,
            },
            "suggestions": ["改进角色刻画", "增加冲突"],
        }

        injector.save_chapter_feedback("novel_001", 3, report)

        feedback = registry.get_last_feedback("novel_001", 4)
        assert feedback is not None
        assert feedback.novel_id == "novel_001"
        assert feedback.chapter_number == 3

        # Weaknesses: AI味(2处) + 重复(1处) + character低分 + 2 suggestions
        assert any("AI味问题" in w for w in feedback.weaknesses)
        assert any("重复问题" in w for w in feedback.weaknesses)
        assert any("character" in w and "需改进" in w for w in feedback.weaknesses)
        assert "改进角色刻画" in feedback.weaknesses
        assert "增加冲突" in feedback.weaknesses

        # Strengths: rule_check NOT passed (so no "规则检查全部通过") + plot high score
        assert "规则检查全部通过" not in feedback.strengths
        assert any("plot" in s and "表现优秀" in s for s in feedback.strengths)

        # Overall score: average of 8.5, 5.0, 7.0 = 6.833...
        assert feedback.overall_score is not None
        assert abs(feedback.overall_score - 6.833) < 0.01

    def test_empty_report(self, injector: FeedbackInjector, registry: PromptRegistry) -> None:
        """Empty report produces no strengths/weaknesses but still saves."""
        report: dict = {}

        injector.save_chapter_feedback("novel_001", 1, report)

        feedback = registry.get_last_feedback("novel_001", 2)
        assert feedback is not None
        assert feedback.strengths == []
        assert feedback.weaknesses == []
        assert feedback.overall_score is None

    def test_extracts_strengths_from_high_scores(self, injector: FeedbackInjector, registry: PromptRegistry) -> None:
        """Scores >= 8.0 become strengths."""
        report = {
            "rule_check": {"passed": True},
            "scores": {
                "plot": 9.0,
                "prose": 8.0,
                "dialogue": 8.5,
            },
        }

        injector.save_chapter_feedback("novel_002", 5, report)

        feedback = registry.get_last_feedback("novel_002", 6)
        assert feedback is not None
        # "规则检查全部通过" + 3 high-score metrics
        assert "规则检查全部通过" in feedback.strengths
        assert any("plot" in s and "9.0" in s for s in feedback.strengths)
        assert any("prose" in s and "8.0" in s for s in feedback.strengths)
        assert any("dialogue" in s and "8.5" in s for s in feedback.strengths)
        assert len(feedback.weaknesses) == 0

    def test_extracts_weaknesses_from_low_scores_and_suggestions(
        self, injector: FeedbackInjector, registry: PromptRegistry
    ) -> None:
        """Scores < 6.0 become weaknesses; suggestions are appended."""
        report = {
            "rule_check": {"passed": True},
            "scores": {
                "plot": 4.0,
                "prose": 5.5,
            },
            "suggestions": ["s1", "s2", "s3", "s4", "s5", "s6_ignored"],
        }

        injector.save_chapter_feedback("novel_003", 2, report)

        feedback = registry.get_last_feedback("novel_003", 3)
        assert feedback is not None
        # Both scores < 6.0 should be weaknesses
        assert any("plot" in w and "需改进" in w for w in feedback.weaknesses)
        assert any("prose" in w and "需改进" in w for w in feedback.weaknesses)
        # Suggestions capped at 5
        assert "s1" in feedback.weaknesses
        assert "s5" in feedback.weaknesses
        assert "s6_ignored" not in feedback.weaknesses

    def test_rule_check_passed_adds_strength(self, injector: FeedbackInjector, registry: PromptRegistry) -> None:
        """When rule_check passes, a strength is added."""
        report = {
            "rule_check": {"passed": True},
            "scores": {},
        }

        injector.save_chapter_feedback("novel_004", 1, report)

        feedback = registry.get_last_feedback("novel_004", 2)
        assert feedback is not None
        assert "规则检查全部通过" in feedback.strengths


# ---------------------------------------------------------------------------
# get_feedback_prompt
# ---------------------------------------------------------------------------


class TestGetFeedbackPrompt:
    """Tests for FeedbackInjector.get_feedback_prompt()."""

    def test_returns_formatted_string(self, injector: FeedbackInjector, registry: PromptRegistry) -> None:
        """Feedback for a chapter produces a non-empty formatted string."""
        registry.save_feedback(
            novel_id="novel_010",
            chapter_number=5,
            strengths=["节奏紧凑"],
            weaknesses=["对话区分度不够"],
            overall_score=7.2,
        )

        prompt = injector.get_feedback_prompt("novel_010", 6)
        assert prompt != ""
        assert "上一章质量反馈" in prompt
        assert "对话区分度不够" in prompt
        assert "节奏紧凑" in prompt
        assert "7.2" in prompt

    def test_returns_empty_when_no_feedback(self, injector: FeedbackInjector) -> None:
        """No prior feedback returns empty string."""
        prompt = injector.get_feedback_prompt("nonexistent_novel", 1)
        assert prompt == ""

    def test_includes_weaknesses_and_strengths(self, injector: FeedbackInjector, registry: PromptRegistry) -> None:
        """Both weaknesses and strengths appear in the prompt with correct markers."""
        registry.save_feedback(
            novel_id="novel_011",
            chapter_number=3,
            strengths=["文笔流畅", "角色鲜明"],
            weaknesses=["情节拖沓", "节奏失衡"],
            overall_score=6.5,
        )

        prompt = injector.get_feedback_prompt("novel_011", 4)
        # Weaknesses come with "  - " prefix
        assert "  - 情节拖沓" in prompt
        assert "  - 节奏失衡" in prompt
        # Strengths come with "  + " prefix
        assert "  + 文笔流畅" in prompt
        assert "  + 角色鲜明" in prompt
        # Score
        assert "6.5/10" in prompt

    def test_no_score_omits_score_line(self, injector: FeedbackInjector, registry: PromptRegistry) -> None:
        """When overall_score is None, score line is not included."""
        registry.save_feedback(
            novel_id="novel_012",
            chapter_number=1,
            strengths=["good"],
            weaknesses=[],
            overall_score=None,
        )

        prompt = injector.get_feedback_prompt("novel_012", 2)
        assert "综合评分" not in prompt
        assert "  + good" in prompt

    def test_only_weaknesses_no_strengths(self, injector: FeedbackInjector, registry: PromptRegistry) -> None:
        """When only weaknesses exist, strengths section is absent."""
        registry.save_feedback(
            novel_id="novel_013",
            chapter_number=2,
            strengths=[],
            weaknesses=["bad pacing"],
            overall_score=4.0,
        )

        prompt = injector.get_feedback_prompt("novel_013", 3)
        assert "需要改进的问题" in prompt
        assert "  - bad pacing" in prompt
        assert "继续保持的优点" not in prompt


# ---------------------------------------------------------------------------
# End-to-end feedback loop
# ---------------------------------------------------------------------------


class TestFeedbackLoopE2E:
    """End-to-end test: QualityReviewer saves feedback, Writer reads it."""

    def test_save_then_get_feedback_loop(self, injector: FeedbackInjector) -> None:
        """Save chapter 5 feedback via save_chapter_feedback, then retrieve for chapter 6."""
        quality_report = {
            "rule_check": {
                "passed": False,
                "ai_flavor_issues": ["内心翻涌"],
                "repetition_issues": [],
            },
            "scores": {
                "plot": 7.5,
                "prose": 9.0,
                "character": 5.0,
            },
            "suggestions": ["加强角色弧线"],
        }

        # QualityReviewer saves feedback for chapter 5
        injector.save_chapter_feedback("novel_e2e", 5, quality_report)

        # Writer reads feedback before writing chapter 6
        prompt = injector.get_feedback_prompt("novel_e2e", 6)

        assert prompt != ""
        assert "上一章质量反馈" in prompt
        # Weaknesses from AI flavor issues + character low score + suggestion
        assert "AI味问题" in prompt
        assert "character" in prompt and "需改进" in prompt
        assert "加强角色弧线" in prompt
        # Strengths from prose high score (rule_check did NOT pass, so no rule strength)
        assert "prose" in prompt and "表现优秀" in prompt
        assert "规则检查全部通过" not in prompt
        # Overall score: avg(7.5, 9.0, 5.0) = 7.167
        assert "7.2" in prompt  # formatted as .1f

    def test_multiple_chapters_gets_latest(self, injector: FeedbackInjector) -> None:
        """When multiple chapters have feedback, get_feedback_prompt returns the most recent before current."""
        injector.save_chapter_feedback(
            "novel_multi", 1, {"rule_check": {"passed": True}, "scores": {"plot": 6.0}}
        )
        injector.save_chapter_feedback(
            "novel_multi", 3, {"rule_check": {"passed": True}, "scores": {"plot": 9.0}}
        )

        # Chapter 4 should get chapter 3's feedback
        prompt = injector.get_feedback_prompt("novel_multi", 4)
        assert "plot" in prompt and "表现优秀" in prompt and "9.0" in prompt

        # Chapter 2 should get chapter 1's feedback
        prompt2 = injector.get_feedback_prompt("novel_multi", 2)
        # plot=6.0 is in the 6.0-7.99 range (not >= 8.0 and not < 6.0), so no strength or weakness for it
        assert "规则检查全部通过" in prompt2

    def test_no_feedback_for_chapter_1(self, injector: FeedbackInjector) -> None:
        """Chapter 1 has no previous chapter, so no feedback."""
        prompt = injector.get_feedback_prompt("novel_first", 1)
        assert prompt == ""
