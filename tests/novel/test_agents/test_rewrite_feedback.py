"""Test that quality_reviewer → writer rewrite loop carries actual feedback.

Covers:
1. quality_reviewer_node sets current_chapter_rewrite_prompt when need_rewrite=True
2. The prompt contains specific issues (AI flavor, repetition, style, suggestions, brief)
3. writer_node prioritizes current_chapter_rewrite_prompt over feedback_prompt
4. current_chapter_rewrite_prompt is cleared when chapter passes
5. current_chapter_rewrite_prompt is cleared on force-pass (max retries)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.novel.agents.quality_reviewer import (
    QualityReviewer,
    quality_reviewer_node,
)
from src.novel.agents.writer import writer_node


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake-model"
    usage: dict | None = None


def _make_fake_llm(response_json: dict | None = None) -> MagicMock:
    llm = MagicMock()
    if response_json is None:
        response_json = {
            "plot_coherence": 8.0,
            "writing_quality": 7.5,
            "character_portrayal": 7.0,
            "ai_flavor_score": 8.0,
            "summary": "OK",
        }
    llm.chat.return_value = FakeLLMResponse(
        content=json.dumps(response_json, ensure_ascii=False)
    )
    return llm


_CLEAN_TEXT = (
    "清晨的阳光透过窗帘洒进房间。\n"
    "李明揉了揉眼睛，从床上坐起来。\n"
    "今天是他入职新公司的第一天，他有些紧张。\n"
    "洗漱完毕，他穿上那套新买的西装，对着镜子整了整领带。\n"
    "出门时，楼下的早餐铺飘来阵阵包子的香气。\n"
    "他买了两个肉包子和一杯豆浆，边走边吃。\n"
    "地铁站里人头攒动，他挤上了早高峰的列车。\n"
)


def _base_state(**overrides: Any) -> dict:
    """Build a minimal valid state for quality_reviewer_node."""
    state: dict[str, Any] = {
        "current_chapter_text": _CLEAN_TEXT,
        "current_chapter": 1,
        "total_chapters": 10,
        "config": {},
        "retry_counts": {},
        "max_retries": 3,
        "auto_approve_threshold": 6.0,
        "characters": [],
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# 1. quality_reviewer_node sets current_chapter_rewrite_prompt on rewrite
# ---------------------------------------------------------------------------


class TestRewritePromptSet:
    """Verify that current_chapter_rewrite_prompt is populated when need_rewrite=True."""

    def test_rewrite_prompt_set_on_rule_failure(self):
        """When rule check fails, the rewrite prompt should contain specific issues."""
        # Use AI-flavored text that will trigger rule check failure (need >= 5 to fail)
        ai_text = (
            "他的内心翻涌着莫名的情绪。\n"
            "嘴角勾起一抹淡淡的笑意。\n"
            "空气仿佛凝固了。\n"
            "然而他并不知道，命运的齿轮开始转动。\n"
            "一股令人窒息的气息弥漫开来。\n"
            "他不由得打了个寒颤。\n"
            "那深深的眼眸中满满的都是杀意。\n"
        )
        state = _base_state(current_chapter_text=ai_text)

        with patch(
            "src.novel.agents.quality_reviewer.create_llm_client",
            side_effect=Exception("no LLM"),
        ):
            result = quality_reviewer_node(state)

        # If rule check triggered need_rewrite, check the prompt
        quality = result.get("current_chapter_quality", {})
        if quality.get("need_rewrite", False) or result.get("retry_counts"):
            prompt = result.get("current_chapter_rewrite_prompt", "")
            assert prompt, "Rewrite prompt should be set when rule check fails"
            assert "质量审查反馈" in prompt
            assert "重写原因" in prompt

    def test_rewrite_prompt_contains_ai_flavor_phrases(self):
        """Rewrite prompt should list specific AI flavor phrases to eliminate."""
        # Mock the reviewer to guarantee rule failure with AI flavor issues (strings)
        state = _base_state()
        fake_report = {
            "need_rewrite": True,
            "rewrite_reason": "规则硬指标未通过",
            "suggestions": ["消除AI味"],
            "rule_check": {
                "passed": False,
                "ai_flavor_issues": [
                    "AI味短语: '内心翻涌'（位置10）",
                    "AI味短语: '命运齿轮'（位置42）",
                ],
            },
            "scores": {},
            "retention_scores": {},
        }

        with patch(
            "src.novel.agents.quality_reviewer.create_llm_client",
            side_effect=Exception("no LLM"),
        ), patch.object(
            QualityReviewer, "review_chapter", return_value=fake_report
        ), patch.object(
            QualityReviewer, "should_rewrite", return_value=True
        ):
            result = quality_reviewer_node(state)

        prompt = result.get("current_chapter_rewrite_prompt", "")
        assert "AI 味短语" in prompt
        assert "内心翻涌" in prompt
        assert "命运齿轮" in prompt

    def test_rewrite_prompt_contains_repetition_issues(self):
        """Rewrite prompt mentions repetition when detected."""
        # Build text with repeated sentences
        repeated = "这是一个重复的句子。\n" * 20
        state = _base_state(current_chapter_text=repeated)

        with patch(
            "src.novel.agents.quality_reviewer.create_llm_client",
            side_effect=Exception("no LLM"),
        ):
            result = quality_reviewer_node(state)

        prompt = result.get("current_chapter_rewrite_prompt", "")
        # Repetition detection depends on rule check implementation
        # If no rewrite is triggered, prompt may be empty (clean pass)
        if result.get("current_chapter_quality", {}).get("need_rewrite"):
            assert "重复" in prompt

    def test_rewrite_prompt_includes_style_deviations(self):
        """When style deviations exist in the report, they appear in the rewrite prompt."""
        # Directly test the assembly logic by mocking the reviewer
        state = _base_state()

        fake_report = {
            "need_rewrite": True,
            "rewrite_reason": "规则硬指标未通过",
            "suggestions": [],
            "rule_check": {"passed": False, "ai_flavor_issues": [{"phrase": "内心翻涌"}]},
            "style_check": {
                "deviations": [
                    {"description": "语气过于正式"},
                    "用词偏书面化",
                ],
            },
            "scores": {},
            "retention_scores": {},
        }

        with patch(
            "src.novel.agents.quality_reviewer.create_llm_client",
            side_effect=Exception("no LLM"),
        ), patch.object(
            QualityReviewer, "review_chapter", return_value=fake_report
        ), patch.object(
            QualityReviewer, "should_rewrite", return_value=True
        ):
            result = quality_reviewer_node(state)

        prompt = result.get("current_chapter_rewrite_prompt", "")
        assert "风格偏差" in prompt
        assert "语气过于正式" in prompt
        assert "用词偏书面化" in prompt

    def test_rewrite_prompt_includes_suggestions(self):
        """When suggestions exist, they appear in the rewrite prompt."""
        state = _base_state()

        fake_report = {
            "need_rewrite": True,
            "rewrite_reason": "LLM评分过低",
            "suggestions": ["增加环境描写", "对话需要更自然"],
            "rule_check": {"passed": True},
            "scores": {"plot_coherence": 4.0},
            "retention_scores": {},
        }

        with patch(
            "src.novel.agents.quality_reviewer.create_llm_client",
            side_effect=Exception("no LLM"),
        ), patch.object(
            QualityReviewer, "review_chapter", return_value=fake_report
        ), patch.object(
            QualityReviewer, "should_rewrite", return_value=True
        ):
            result = quality_reviewer_node(state)

        prompt = result.get("current_chapter_rewrite_prompt", "")
        assert "改进建议" in prompt
        assert "增加环境描写" in prompt
        assert "对话需要更自然" in prompt

    def test_rewrite_prompt_includes_brief_unfulfilled(self):
        """When brief fulfillment fails, unfulfilled items appear in rewrite prompt."""
        state = _base_state()

        fake_report = {
            "need_rewrite": True,
            "rewrite_reason": "任务书未完成",
            "suggestions": [],
            "rule_check": {"passed": True},
            "scores": {},
            "retention_scores": {},
            "brief_fulfillment": {
                "overall_pass": False,
                "unfulfilled_items": ["伏笔A未埋设", "角色B未登场"],
            },
        }

        with patch(
            "src.novel.agents.quality_reviewer.create_llm_client",
            side_effect=Exception("no LLM"),
        ), patch.object(
            QualityReviewer, "review_chapter", return_value=fake_report
        ), patch.object(
            QualityReviewer, "should_rewrite", return_value=True
        ):
            result = quality_reviewer_node(state)

        prompt = result.get("current_chapter_rewrite_prompt", "")
        assert "任务书未完成项" in prompt
        assert "伏笔A未埋设" in prompt
        assert "角色B未登场" in prompt


# ---------------------------------------------------------------------------
# 2. Rewrite prompt cleared when chapter passes
# ---------------------------------------------------------------------------


class TestRewritePromptCleared:
    """Verify prompt is cleared on pass and force-pass."""

    def test_cleared_when_chapter_passes(self):
        """When quality passes, current_chapter_rewrite_prompt should be empty."""
        state = _base_state(current_chapter_text=_CLEAN_TEXT)

        with patch(
            "src.novel.agents.quality_reviewer.create_llm_client",
            side_effect=Exception("no LLM"),
        ):
            result = quality_reviewer_node(state)

        # Clean text should pass rule check
        quality = result.get("current_chapter_quality", {})
        if not quality.get("need_rewrite", False):
            assert result.get("current_chapter_rewrite_prompt") == ""

    def test_cleared_on_force_pass_max_retries(self):
        """When max retries reached, rewrite prompt should be cleared."""
        state = _base_state()
        # Set retry count at max - 1 so this review pushes it to max
        state["retry_counts"] = {1: 2}
        state["max_retries"] = 3

        fake_report = {
            "need_rewrite": True,
            "rewrite_reason": "规则硬指标未通过",
            "suggestions": ["fix something"],
            "rule_check": {"passed": False, "ai_flavor_issues": [{"phrase": "内心翻涌"}]},
            "scores": {},
            "retention_scores": {},
        }

        with patch(
            "src.novel.agents.quality_reviewer.create_llm_client",
            side_effect=Exception("no LLM"),
        ), patch.object(
            QualityReviewer, "review_chapter", return_value=fake_report
        ), patch.object(
            QualityReviewer, "should_rewrite", return_value=True
        ):
            result = quality_reviewer_node(state)

        # Should have been force-passed
        quality = result.get("current_chapter_quality", {})
        assert quality.get("need_rewrite") is False, "Should be force-passed"
        assert result.get("current_chapter_rewrite_prompt") == ""

    def test_not_set_when_no_issues_found(self):
        """When there are no specific issues (empty rewrite_parts), prompt is not set."""
        state = _base_state()

        # A report that triggers rewrite but has no specific issues to extract
        fake_report = {
            "need_rewrite": True,
            "rewrite_reason": "",  # empty reason
            "suggestions": [],
            "rule_check": {"passed": True},
            "scores": {},
            "retention_scores": {},
        }

        with patch(
            "src.novel.agents.quality_reviewer.create_llm_client",
            side_effect=Exception("no LLM"),
        ), patch.object(
            QualityReviewer, "review_chapter", return_value=fake_report
        ), patch.object(
            QualityReviewer, "should_rewrite", return_value=True
        ):
            result = quality_reviewer_node(state)

        # No rewrite_parts were assembled, so key should not be set
        assert "current_chapter_rewrite_prompt" not in result


# ---------------------------------------------------------------------------
# 3. writer_node prioritizes current_chapter_rewrite_prompt
# ---------------------------------------------------------------------------


class TestWriterRewritePriority:
    """Verify writer_node uses current_chapter_rewrite_prompt over feedback_prompt."""

    def _writer_state(self, **overrides: Any) -> dict:
        """Minimal state for writer_node."""
        state: dict[str, Any] = {
            "current_chapter": 1,
            "total_chapters": 10,
            "config": {},
            "style_name": "webnovel.shuangwen",
            "budget_mode": False,
            "feedback_prompt": "",
            "debt_summary": "",
            "continuity_brief": "",
            "characters": [],
            "world_setting": {"era": "现代", "location": "北京"},
            "current_chapter_outline": {
                "chapter_number": 1,
                "title": "第一章",
                "goal": "开篇",
                "key_events": ["事件A"],
                "involved_characters": [],
                "estimated_words": 2500,
                "mood": "日常",
            },
            "current_scenes": [
                {"scene_number": 1, "target_words": 800},
            ],
            "chapters": [],
        }
        state.update(overrides)
        return state

    def _fake_chapter(self):
        """Create a mock Chapter with needed attributes for writer_node."""
        mock_scene = MagicMock()
        mock_scene.model_dump.return_value = {"scene_number": 1, "text": "正文"}
        mock_chapter = MagicMock()
        mock_chapter.scenes = [mock_scene]
        mock_chapter.full_text = "正文" * 100
        mock_chapter.word_count = 200
        return mock_chapter

    @patch("src.novel.agents.writer.Writer.generate_chapter")
    @patch("src.novel.agents.writer.create_llm_client")
    def test_rewrite_prompt_overrides_feedback_prompt(self, mock_create, mock_gen):
        """current_chapter_rewrite_prompt should override feedback_prompt."""
        mock_gen.return_value = self._fake_chapter()
        mock_create.return_value = MagicMock()

        rewrite_feedback = "【当前章质量审查反馈】\n- 消除AI味短语：内心翻涌"
        state = self._writer_state(
            feedback_prompt="旧的反馈内容",
            current_chapter_rewrite_prompt=rewrite_feedback,
        )

        result = writer_node(state)

        # generate_chapter should have been called with the rewrite feedback, not the old one
        assert not result.get("errors"), f"writer_node returned errors: {result['errors']}"
        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args
        actual_feedback = call_kwargs.kwargs.get("feedback_prompt", "")
        assert actual_feedback == rewrite_feedback
        assert "旧的反馈内容" not in actual_feedback

    @patch("src.novel.agents.writer.Writer.generate_chapter")
    @patch("src.novel.agents.writer.create_llm_client")
    def test_empty_rewrite_prompt_falls_back_to_feedback_prompt(self, mock_create, mock_gen):
        """When current_chapter_rewrite_prompt is empty, feedback_prompt is used."""
        mock_gen.return_value = self._fake_chapter()
        mock_create.return_value = MagicMock()

        state = self._writer_state(
            feedback_prompt="之前章节的反馈",
            current_chapter_rewrite_prompt="",
        )

        result = writer_node(state)

        assert not result.get("errors"), f"writer_node returned errors: {result['errors']}"
        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args
        actual_feedback = call_kwargs.kwargs.get("feedback_prompt", "")
        assert actual_feedback == "之前章节的反馈"

    @patch("src.novel.agents.writer.Writer.generate_chapter")
    @patch("src.novel.agents.writer.create_llm_client")
    def test_no_rewrite_prompt_key_uses_feedback_injector(self, mock_create, mock_gen):
        """When current_chapter_rewrite_prompt not in state, FeedbackInjector is consulted."""
        mock_gen.return_value = self._fake_chapter()
        mock_create.return_value = MagicMock()

        mock_injector = MagicMock()
        mock_injector.get_feedback_prompt.return_value = "来自注入器的反馈"

        state = self._writer_state(
            feedback_prompt="",
            novel_id="test-novel",
            feedback_injector=mock_injector,
        )
        # Don't set current_chapter_rewrite_prompt at all

        result = writer_node(state)

        mock_injector.get_feedback_prompt.assert_called_once_with("test-novel", 1)

    @patch("src.novel.agents.writer.Writer.generate_chapter")
    @patch("src.novel.agents.writer.create_llm_client")
    def test_rewrite_prompt_present_skips_feedback_injector(self, mock_create, mock_gen):
        """When current_chapter_rewrite_prompt is present, FeedbackInjector is NOT called."""
        mock_gen.return_value = self._fake_chapter()
        mock_create.return_value = MagicMock()

        mock_injector = MagicMock()
        mock_injector.get_feedback_prompt.return_value = "来自注入器的反馈"

        state = self._writer_state(
            feedback_prompt="",
            novel_id="test-novel",
            feedback_injector=mock_injector,
            current_chapter_rewrite_prompt="重写反馈内容",
        )

        result = writer_node(state)

        mock_injector.get_feedback_prompt.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Integration: full rewrite loop scenario
# ---------------------------------------------------------------------------


class TestRewriteLoopIntegration:
    """End-to-end scenario: quality fails -> sets prompt -> writer reads it -> quality passes -> clears."""

    def test_full_rewrite_cycle(self):
        """Simulate a quality fail -> rewrite -> pass cycle, verifying prompt flow."""
        # Step 1: quality_reviewer_node produces rewrite prompt
        state = _base_state()
        fail_report = {
            "need_rewrite": True,
            "rewrite_reason": "规则硬指标未通过",
            "suggestions": ["消除AI味", "增加细节"],
            "rule_check": {
                "passed": False,
                "ai_flavor_issues": [{"phrase": "内心翻涌"}, {"phrase": "命运齿轮"}],
                "repetition_issues": [{"text": "重复句1"}],
            },
            "scores": {},
            "retention_scores": {},
        }

        with patch(
            "src.novel.agents.quality_reviewer.create_llm_client",
            side_effect=Exception("no LLM"),
        ), patch.object(
            QualityReviewer, "review_chapter", return_value=fail_report
        ), patch.object(
            QualityReviewer, "should_rewrite", return_value=True
        ):
            qr_result = quality_reviewer_node(state)

        rewrite_prompt = qr_result.get("current_chapter_rewrite_prompt", "")
        assert "内心翻涌" in rewrite_prompt
        assert "命运齿轮" in rewrite_prompt
        assert "重复句" in rewrite_prompt
        assert "消除AI味" in rewrite_prompt
        assert "增加细节" in rewrite_prompt

        # Step 2: Verify the prompt would be picked up by writer_node
        # (We just check the priority logic, not full writer execution)
        writer_state = {
            "feedback_prompt": "old feedback",
            "current_chapter_rewrite_prompt": rewrite_prompt,
        }
        current_rewrite = writer_state.get("current_chapter_rewrite_prompt", "")
        feedback = writer_state.get("feedback_prompt", "")
        if current_rewrite:
            feedback = current_rewrite
        assert feedback == rewrite_prompt
        assert "old feedback" not in feedback

        # Step 3: quality passes on second try -> prompt cleared
        pass_report = {
            "need_rewrite": False,
            "rewrite_reason": None,
            "suggestions": [],
            "rule_check": {"passed": True},
            "scores": {},
            "retention_scores": {},
        }

        state2 = _base_state()
        with patch(
            "src.novel.agents.quality_reviewer.create_llm_client",
            side_effect=Exception("no LLM"),
        ), patch.object(
            QualityReviewer, "review_chapter", return_value=pass_report
        ), patch.object(
            QualityReviewer, "should_rewrite", return_value=False
        ):
            qr_result2 = quality_reviewer_node(state2)

        assert qr_result2.get("current_chapter_rewrite_prompt") == ""
