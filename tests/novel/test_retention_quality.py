"""追更价值评估系统测试。

测试 retention_scores 字段、evaluate_retention 方法、
evaluate_chapter 集成、should_rewrite 联动。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.models.quality import QualityReport, RuleCheckResult
from src.novel.tools.quality_check_tool import QualityCheckTool
from src.novel.agents.quality_reviewer import QualityReviewer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CHAPTER = (
    "叶凡猛然睁开双眼,发现自己躺在一片荒芜的山谷中。\n\n"
    "他低声自语,心中涌起一股莫名的激动。\n\n"
    "远处传来一声巨响,一头浑身漆黑的巨兽从山谷尽头冲来。\n\n"
    "叶凡冷喝一声,右手猛然握拳,一道金色光芒从拳头上爆发而出。\n\n"
    "金光与黑兽碰撞,爆发出惊天动地的轰鸣。黑兽惨叫一声,被轰飞百丈之外。\n\n"
    "叶凡看着自己的拳头,嘴角微微上扬。\n\n"
    "就在这时,一道冰冷的声音从身后传来。\n\n"
    "叶凡转过身,只见三道身影从天而降,每一个都散发着远超黑兽的强大气息。"
)


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, model="test", usage=None)


def _make_retention_response(
    ig: float = 7.0,
    ce: float = 8.0,
    mm: float = 7.5,
    cs: float = 8.5,
    pa: float = 7.0,
) -> LLMResponse:
    data = {
        "information_gain": ig,
        "conflict_effectiveness": ce,
        "memorable_moment": mm,
        "cliffhanger_strength": cs,
        "protagonist_appeal": pa,
    }
    return _make_llm_response(json.dumps(data))


def _make_scores_response(
    pc: float = 7.0, wq: float = 7.0, cp: float = 7.0, af: float = 7.0
) -> LLMResponse:
    data = {
        "plot_coherence": pc,
        "writing_quality": wq,
        "character_portrayal": cp,
        "ai_flavor_score": af,
        "summary": "测试摘要",
    }
    return _make_llm_response(json.dumps(data))


# ---------------------------------------------------------------------------
# QualityReport 模型测试
# ---------------------------------------------------------------------------


class TestQualityReportRetentionField:
    """QualityReport retention_scores 字段测试。"""

    def test_default_empty_dict(self):
        report = QualityReport(
            chapter_number=1,
            rule_check=RuleCheckResult(passed=True),
        )
        assert report.retention_scores == {}

    def test_accepts_retention_scores(self):
        scores = {
            "information_gain": 8.0,
            "conflict_effectiveness": 7.5,
            "memorable_moment": 6.0,
            "cliffhanger_strength": 9.0,
            "protagonist_appeal": 7.0,
        }
        report = QualityReport(
            chapter_number=1,
            rule_check=RuleCheckResult(passed=True),
            retention_scores=scores,
        )
        assert report.retention_scores == scores
        assert len(report.retention_scores) == 5

    def test_serialization_roundtrip(self):
        scores = {"information_gain": 8.0, "cliffhanger_strength": 9.0}
        report = QualityReport(
            chapter_number=1,
            rule_check=RuleCheckResult(passed=True),
            retention_scores=scores,
        )
        data = report.model_dump()
        assert data["retention_scores"] == scores
        restored = QualityReport(**data)
        assert restored.retention_scores == scores


# ---------------------------------------------------------------------------
# evaluate_retention 方法测试
# ---------------------------------------------------------------------------


class TestEvaluateRetention:
    """QualityCheckTool.evaluate_retention 测试。"""

    def test_no_llm_returns_empty(self):
        tool = QualityCheckTool(llm_client=None)
        result = tool.evaluate_retention(SAMPLE_CHAPTER)
        assert result == {}

    def test_normal_response(self):
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_retention_response()
        tool = QualityCheckTool(llm_client=mock_llm)

        result = tool.evaluate_retention(SAMPLE_CHAPTER)

        assert len(result) == 5
        assert result["information_gain"] == 7.0
        assert result["conflict_effectiveness"] == 8.0
        assert result["memorable_moment"] == 7.5
        assert result["cliffhanger_strength"] == 8.5
        assert result["protagonist_appeal"] == 7.0

    def test_with_chapter_outline(self):
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_retention_response()
        tool = QualityCheckTool(llm_client=mock_llm)

        result = tool.evaluate_retention(
            SAMPLE_CHAPTER, chapter_outline={"title": "第一章", "scenes": []}
        )
        assert len(result) == 5
        # Verify outline was passed to prompt
        call_args = mock_llm.chat.call_args
        user_msg = call_args[1]["messages"][1]["content"] if "messages" in call_args[1] else call_args[0][0][1]["content"]
        assert "章节大纲" in user_msg

    def test_with_chapter_brief(self):
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_retention_response()
        tool = QualityCheckTool(llm_client=mock_llm)

        brief = {"main_conflict": "对抗炎狼帮", "hook_type": "悬念"}
        result = tool.evaluate_retention(
            SAMPLE_CHAPTER, chapter_brief=brief
        )
        assert len(result) == 5
        call_args = mock_llm.chat.call_args
        user_msg = call_args[1]["messages"][1]["content"] if "messages" in call_args[1] else call_args[0][0][1]["content"]
        assert "章节任务书" in user_msg

    def test_empty_response(self):
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response("")
        tool = QualityCheckTool(llm_client=mock_llm)

        result = tool.evaluate_retention(SAMPLE_CHAPTER)
        assert result == {}

    def test_non_json_response(self):
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(
            "这章写得不错，追更价值很高！"
        )
        tool = QualityCheckTool(llm_client=mock_llm)

        result = tool.evaluate_retention(SAMPLE_CHAPTER)
        assert result == {}

    def test_partial_fields(self):
        """LLM 只返回部分字段。"""
        mock_llm = MagicMock()
        partial_data = {
            "information_gain": 7.0,
            "cliffhanger_strength": 8.0,
        }
        mock_llm.chat.return_value = _make_llm_response(json.dumps(partial_data))
        tool = QualityCheckTool(llm_client=mock_llm)

        result = tool.evaluate_retention(SAMPLE_CHAPTER)
        assert len(result) == 2
        assert result["information_gain"] == 7.0
        assert result["cliffhanger_strength"] == 8.0

    def test_scores_clamped_to_range(self):
        """分数超出 0-10 范围时被截断。"""
        mock_llm = MagicMock()
        data = {
            "information_gain": 15.0,
            "conflict_effectiveness": -3.0,
            "memorable_moment": 7.0,
            "cliffhanger_strength": 8.0,
            "protagonist_appeal": 7.0,
        }
        mock_llm.chat.return_value = _make_llm_response(json.dumps(data))
        tool = QualityCheckTool(llm_client=mock_llm)

        result = tool.evaluate_retention(SAMPLE_CHAPTER)
        assert result["information_gain"] == 10.0
        assert result["conflict_effectiveness"] == 0.0

    def test_llm_exception(self):
        """LLM 调用抛异常时返回空 dict。"""
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("API 超时")
        tool = QualityCheckTool(llm_client=mock_llm)

        result = tool.evaluate_retention(SAMPLE_CHAPTER)
        assert result == {}

    def test_non_numeric_values_skipped(self):
        """非数值字段被跳过。"""
        mock_llm = MagicMock()
        data = {
            "information_gain": "high",
            "conflict_effectiveness": 8.0,
            "memorable_moment": None,
            "cliffhanger_strength": 7.0,
            "protagonist_appeal": True,
        }
        mock_llm.chat.return_value = _make_llm_response(json.dumps(data))
        tool = QualityCheckTool(llm_client=mock_llm)

        result = tool.evaluate_retention(SAMPLE_CHAPTER)
        assert "information_gain" not in result
        assert "memorable_moment" not in result
        assert result["conflict_effectiveness"] == 8.0
        assert result["cliffhanger_strength"] == 7.0


# ---------------------------------------------------------------------------
# evaluate_chapter 集成测试
# ---------------------------------------------------------------------------


class TestEvaluateChapterIntegration:
    """evaluate_chapter 集成 retention_scores 测试。"""

    def test_no_llm_empty_retention(self):
        tool = QualityCheckTool(llm_client=None)
        report = tool.evaluate_chapter(SAMPLE_CHAPTER)
        assert report.retention_scores == {}

    def test_with_llm_has_retention(self):
        mock_llm = MagicMock()
        # First call: evaluate_chapter scores, second call: evaluate_retention
        mock_llm.chat.side_effect = [
            _make_scores_response(),
            _make_retention_response(),
        ]
        tool = QualityCheckTool(llm_client=mock_llm)

        report = tool.evaluate_chapter(SAMPLE_CHAPTER)
        assert report.scores  # has regular scores
        assert report.retention_scores  # has retention scores
        assert "information_gain" in report.retention_scores

    def test_retention_failure_does_not_break_report(self):
        """evaluate_retention 失败不影响整体报告。"""
        mock_llm = MagicMock()
        # First call succeeds (scores), second call fails (retention)
        mock_llm.chat.side_effect = [
            _make_scores_response(),
            RuntimeError("Retention API failed"),
        ]
        tool = QualityCheckTool(llm_client=mock_llm)

        report = tool.evaluate_chapter(SAMPLE_CHAPTER)
        assert report.scores  # regular scores still work
        assert report.retention_scores == {}  # retention gracefully empty


# ---------------------------------------------------------------------------
# should_rewrite 追更分数联动测试
# ---------------------------------------------------------------------------


class TestShouldRewriteRetention:
    """QualityReviewer.should_rewrite 追更分数联动测试。"""

    def test_low_retention_triggers_rewrite(self):
        reviewer = QualityReviewer(llm_client=None)
        report = {
            "rule_check": {"passed": True},
            "scores": {"plot_coherence": 8.0, "writing_quality": 8.0},
            "retention_scores": {
                "information_gain": 2.0,
                "conflict_effectiveness": 3.0,
                "memorable_moment": 3.0,
                "cliffhanger_strength": 2.5,
                "protagonist_appeal": 3.0,
            },
            "need_rewrite": False,
        }
        # avg retention = 2.7 < 4.0
        assert reviewer.should_rewrite(report) is True

    def test_moderate_retention_no_rewrite(self):
        reviewer = QualityReviewer(llm_client=None)
        report = {
            "rule_check": {"passed": True},
            "scores": {"plot_coherence": 7.0},
            "retention_scores": {
                "information_gain": 6.0,
                "conflict_effectiveness": 5.0,
                "memorable_moment": 5.0,
                "cliffhanger_strength": 5.5,
                "protagonist_appeal": 5.0,
            },
            "need_rewrite": False,
        }
        # avg retention = 5.3 >= 4.0
        assert reviewer.should_rewrite(report) is False

    def test_empty_retention_no_effect(self):
        reviewer = QualityReviewer(llm_client=None)
        report = {
            "rule_check": {"passed": True},
            "scores": {"plot_coherence": 7.0},
            "retention_scores": {},
            "need_rewrite": False,
        }
        assert reviewer.should_rewrite(report) is False

    def test_no_retention_key_no_effect(self):
        reviewer = QualityReviewer(llm_client=None)
        report = {
            "rule_check": {"passed": True},
            "scores": {"plot_coherence": 7.0},
            "need_rewrite": False,
        }
        assert reviewer.should_rewrite(report) is False

    def test_borderline_retention_exactly_4(self):
        """avg == 4.0 should NOT trigger rewrite (only < 4.0 triggers)."""
        reviewer = QualityReviewer(llm_client=None)
        report = {
            "rule_check": {"passed": True},
            "scores": {},
            "retention_scores": {
                "information_gain": 4.0,
                "conflict_effectiveness": 4.0,
                "memorable_moment": 4.0,
                "cliffhanger_strength": 4.0,
                "protagonist_appeal": 4.0,
            },
            "need_rewrite": False,
        }
        assert reviewer.should_rewrite(report) is False


# ---------------------------------------------------------------------------
# review_chapter 集成测试
# ---------------------------------------------------------------------------


class TestReviewChapterRetention:
    """review_chapter 报告中包含 retention_scores。"""

    def test_full_review_includes_retention(self):
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            _make_scores_response(),
            _make_retention_response(),
        ]
        reviewer = QualityReviewer(llm_client=mock_llm)

        report = reviewer.review_chapter(SAMPLE_CHAPTER, budget_mode=False)
        assert "retention_scores" in report
        assert len(report["retention_scores"]) == 5

    def test_budget_mode_skips_retention(self):
        """省钱模式跳过 LLM 打分和追更评估。"""
        mock_llm = MagicMock()
        reviewer = QualityReviewer(llm_client=mock_llm)

        report = reviewer.review_chapter(SAMPLE_CHAPTER, budget_mode=True)
        assert report["scores"] == {}
        assert report["retention_scores"] == {}
        mock_llm.chat.assert_not_called()

    def test_no_llm_empty_retention_in_report(self):
        reviewer = QualityReviewer(llm_client=None)
        report = reviewer.review_chapter(SAMPLE_CHAPTER, budget_mode=False)
        assert report["retention_scores"] == {}

    def test_no_llm_budget_mode_empty_retention(self):
        reviewer = QualityReviewer(llm_client=None)
        report = reviewer.review_chapter(SAMPLE_CHAPTER, budget_mode=True)
        assert report["retention_scores"] == {}
