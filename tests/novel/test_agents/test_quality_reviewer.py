"""QualityReviewer Agent + QualityCheckTool 单元测试

覆盖：
- QualityCheckTool.rule_check: 重复句、AI味、段落长度、正常文本
- QualityCheckTool.pairwise_compare: Mock LLM
- QualityCheckTool.evaluate_chapter: Mock LLM
- QualityReviewer.review_chapter: 完整流程
- QualityReviewer.should_rewrite: 阈值判断
- quality_reviewer_node: 状态更新、省钱模式
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.novel.models.quality import (
    PairwiseResult,
    QualityReport,
    RuleCheckResult,
)
from src.novel.tools.quality_check_tool import QualityCheckTool
from src.novel.agents.quality_reviewer import (
    QualityReviewer,
    quality_reviewer_node,
)


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
            "summary": "质量不错",
        }
    llm.chat.return_value = FakeLLMResponse(
        content=json.dumps(response_json, ensure_ascii=False)
    )
    return llm


# 正常文本（无问题）
_CLEAN_TEXT = (
    "清晨的阳光透过窗帘洒进房间。\n"
    "李明揉了揉眼睛，从床上坐起来。\n"
    "今天是他入职新公司的第一天，他有些紧张。\n"
    "洗漱完毕，他穿上那套新买的西装，对着镜子整了整领带。\n"
    "出门时，楼下的早餐铺飘来阵阵包子的香气。\n"
    "他买了两个肉包子和一杯豆浆，边走边吃。\n"
    "地铁站里人头攒动，他挤上了早高峰的列车。\n"
)

# 有 AI 味的文本
_AI_FLAVOR_TEXT = (
    "他的内心翻涌着莫名的情绪。\n"
    "嘴角勾起一抹淡淡的笑意。\n"
    "空气仿佛凝固了。\n"
    "然而他并不知道，命运的齿轮开始转动。\n"
    "一股令人窒息的气息弥漫开来。\n"
)

# 有重复句的文本
_REPETITIVE_TEXT = (
    "他站在那里一动不动。\n"
    "他站在那里一动不动。\n"
    "他站在那里一动不动。\n"
    "远处传来一声巨响。\n"
)

# 段落长度异常的文本
_ABNORMAL_PARA_TEXT = (
    "好。\n\n"
    + "这是一段非常非常长的文字，" * 50
    + "终于写完了。"
)


# ---------------------------------------------------------------------------
# QualityCheckTool.rule_check 测试
# ---------------------------------------------------------------------------


class TestRuleCheck:
    def setup_method(self) -> None:
        self.tool = QualityCheckTool()

    def test_clean_text_passes(self) -> None:
        """正常文本应通过检查。"""
        result = self.tool.rule_check(_CLEAN_TEXT)
        assert isinstance(result, RuleCheckResult)
        assert result.passed is True
        assert result.repetition_issues == []
        assert result.ai_flavor_issues == []

    def test_detects_ai_flavor(self) -> None:
        """Phase 0 架构重构：AI 味黑名单已废弃，rule_check 不再返回 AI 味命中。

        TODO(phase-1): StyleProfile 接管后改写此测试覆盖新的检测路径。
        """
        result = self.tool.rule_check(_AI_FLAVOR_TEXT)
        # Stubbed blacklist returns no hits — field guaranteed empty now.
        assert result.ai_flavor_issues == []

    def test_detects_repetition(self) -> None:
        """应检测到重复句。"""
        result = self.tool.rule_check(_REPETITIVE_TEXT)
        assert len(result.repetition_issues) > 0

    def test_detects_abnormal_paragraph_length(self) -> None:
        """应检测到段落长度异常。"""
        result = self.tool.rule_check(_ABNORMAL_PARA_TEXT)
        assert len(result.paragraph_length_issues) > 0

    def test_empty_text_passes(self) -> None:
        """空文本应直接通过（无内容可检查）。"""
        result = self.tool.rule_check("")
        assert result.passed is True

    def test_detects_similar_dialogues(self) -> None:
        """应检测到相邻对话相似度过高。"""
        text = (
            "\u201c你到底想要什么东西？\u201d\n"
            "\u201c你到底想要什么东西呢？\u201d\n"
        )
        result = self.tool.rule_check(text)
        # 可能检测到对话区分度问题
        # （取决于 Jaccard 阈值，这里两句很相似）
        assert isinstance(result, RuleCheckResult)

    def test_short_paragraphs_detected(self) -> None:
        """过短段落应被检测。"""
        text = "好。\n嗯。\n行。\n这是一段正常长度的文字，用来确保不只有短段落存在。"
        result = self.tool.rule_check(text)
        assert len(result.paragraph_length_issues) > 0


# ---------------------------------------------------------------------------
# QualityCheckTool.pairwise_compare 测试
# ---------------------------------------------------------------------------


class TestPairwiseCompare:
    def test_pairwise_with_mocked_llm(self) -> None:
        """Mock LLM 应返回有效的 PairwiseResult。"""
        llm = _make_fake_llm({"winner": "A", "reason": "版本A情节更连贯"})
        tool = QualityCheckTool(llm)
        result = tool.pairwise_compare("版本A正文...", "版本B正文...")
        assert isinstance(result, PairwiseResult)
        assert result.winner == "A"
        assert "连贯" in result.reason

    def test_pairwise_returns_tie_on_bad_json(self) -> None:
        """LLM 返回无法解析时应返回 TIE。"""
        llm = MagicMock()
        llm.chat.return_value = FakeLLMResponse(content="这不是JSON")
        tool = QualityCheckTool(llm)
        result = tool.pairwise_compare("A", "B")
        assert result.winner == "TIE"

    def test_pairwise_without_llm_raises(self) -> None:
        """无 LLM 时应抛出 RuntimeError。"""
        tool = QualityCheckTool(None)
        with pytest.raises(RuntimeError, match="LLM 客户端不可用"):
            tool.pairwise_compare("A", "B")

    def test_pairwise_normalizes_invalid_winner(self) -> None:
        """无效 winner 值应归一化为 TIE。"""
        llm = _make_fake_llm({"winner": "C", "reason": "无效选择"})
        tool = QualityCheckTool(llm)
        result = tool.pairwise_compare("A", "B")
        assert result.winner == "TIE"


# ---------------------------------------------------------------------------
# QualityCheckTool.evaluate_chapter 测试
# ---------------------------------------------------------------------------


class TestEvaluateChapter:
    def test_evaluate_with_mocked_llm(self) -> None:
        """Mock LLM 应返回有效的 QualityReport。"""
        llm = _make_fake_llm({
            "plot_coherence": 8.0,
            "writing_quality": 7.5,
            "character_portrayal": 7.0,
            "ai_flavor_score": 9.0,
            "summary": "质量良好",
        })
        tool = QualityCheckTool(llm)
        report = tool.evaluate_chapter(_CLEAN_TEXT)
        assert isinstance(report, QualityReport)
        assert "plot_coherence" in report.scores
        assert report.scores["plot_coherence"] == 8.0
        assert report.scores["writing_quality"] == 7.5

    def test_evaluate_without_llm(self) -> None:
        """无 LLM 时应返回仅规则检查结果。"""
        tool = QualityCheckTool(None)
        report = tool.evaluate_chapter(_CLEAN_TEXT)
        assert isinstance(report, QualityReport)
        assert report.scores == {}
        assert report.rule_check.passed is True

    def test_evaluate_clamps_scores(self) -> None:
        """超范围分数应被截断到 [0, 10]。"""
        llm = _make_fake_llm({
            "plot_coherence": 15.0,
            "writing_quality": -5.0,
            "character_portrayal": 7.0,
            "ai_flavor_score": 8.0,
        })
        tool = QualityCheckTool(llm)
        report = tool.evaluate_chapter(_CLEAN_TEXT)
        assert report.scores["plot_coherence"] == 10.0
        assert report.scores["writing_quality"] == 0.0

    def test_evaluate_ai_flavor_text_has_rule_issues(self) -> None:
        """Phase 0 架构重构：AI 味黑名单废弃，rule_check 不再抓 AI 味短语。

        TODO(phase-1): StyleProfile 接管后重写这个场景。
        """
        llm = _make_fake_llm()
        tool = QualityCheckTool(llm)
        report = tool.evaluate_chapter(_AI_FLAVOR_TEXT)
        # Stubbed blacklist — AI flavor issues always empty.
        assert report.rule_check.ai_flavor_issues == []


# ---------------------------------------------------------------------------
# QualityReviewer.review_chapter 测试
# ---------------------------------------------------------------------------


class TestReviewChapter:
    def test_full_pipeline_clean_text(self) -> None:
        """正常文本应通过审查。"""
        llm = _make_fake_llm({
            "plot_coherence": 8.0,
            "writing_quality": 7.5,
            "character_portrayal": 7.0,
            "ai_flavor_score": 9.0,
        })
        reviewer = QualityReviewer(llm)
        report = reviewer.review_chapter(_CLEAN_TEXT)
        assert report["rule_check"]["passed"] is True
        assert "scores" in report

    def test_full_pipeline_ai_flavor_text(self) -> None:
        """Phase 0 架构重构：AI 味黑名单废弃；此文本现在走 rule_check 会通过。

        TODO(phase-1): StyleProfile 接管后让该类文本重新触发重写。
        """
        import pytest
        pytest.skip("AI flavor blacklist deprecated in Phase 0; rewrite trigger待 StyleProfile 接管")

    def test_budget_mode_skips_llm(self) -> None:
        """省钱模式应跳过 LLM 评分。"""
        llm = _make_fake_llm()
        reviewer = QualityReviewer(llm)
        report = reviewer.review_chapter(_CLEAN_TEXT, budget_mode=True)
        assert report["scores"] == {}
        # LLM 不应被调用
        llm.chat.assert_not_called()

    def test_review_with_style_name(self) -> None:
        """指定风格名称时应包含风格检查结果。"""
        llm = _make_fake_llm()
        reviewer = QualityReviewer(llm)
        report = reviewer.review_chapter(
            _CLEAN_TEXT,
            style_name="webnovel.shuangwen",
        )
        assert "style_check" in report
        assert "similarity" in report["style_check"]

    def test_review_with_invalid_style_name_skips(self) -> None:
        """无效风格名称应跳过风格检查而不崩溃。"""
        llm = _make_fake_llm()
        reviewer = QualityReviewer(llm)
        report = reviewer.review_chapter(
            _CLEAN_TEXT,
            style_name="nonexistent.style",
        )
        # 应正常返回，只是没有 style_check
        assert "rule_check" in report

    def test_review_without_llm(self) -> None:
        """无 LLM 时应仅执行规则检查。"""
        reviewer = QualityReviewer(None)
        report = reviewer.review_chapter(_CLEAN_TEXT)
        assert report["scores"] == {}
        assert report["rule_check"]["passed"] is True


# ---------------------------------------------------------------------------
# QualityReviewer.should_rewrite 测试
# ---------------------------------------------------------------------------


class TestShouldRewrite:
    def setup_method(self) -> None:
        self.reviewer = QualityReviewer(None)

    def test_rule_check_failed_triggers_rewrite(self) -> None:
        report = {"rule_check": {"passed": False}, "scores": {}, "need_rewrite": True}
        assert self.reviewer.should_rewrite(report) is True

    def test_low_scores_triggers_rewrite(self) -> None:
        report = {
            "rule_check": {"passed": True},
            "scores": {"plot_coherence": 3.0, "writing_quality": 4.0},
            "need_rewrite": False,
        }
        assert self.reviewer.should_rewrite(report, threshold=6.0) is True

    def test_high_scores_no_rewrite(self) -> None:
        report = {
            "rule_check": {"passed": True},
            "scores": {"plot_coherence": 8.0, "writing_quality": 8.0},
            "need_rewrite": False,
        }
        assert self.reviewer.should_rewrite(report, threshold=6.0) is False

    def test_empty_scores_no_rewrite(self) -> None:
        """无评分时只看规则检查。"""
        report = {
            "rule_check": {"passed": True},
            "scores": {},
            "need_rewrite": False,
        }
        assert self.reviewer.should_rewrite(report) is False

    def test_custom_threshold(self) -> None:
        """自定义阈值应生效。"""
        report = {
            "rule_check": {"passed": True},
            "scores": {"plot_coherence": 7.0, "writing_quality": 7.0},
            "need_rewrite": False,
        }
        assert self.reviewer.should_rewrite(report, threshold=8.0) is True
        assert self.reviewer.should_rewrite(report, threshold=6.0) is False


# ---------------------------------------------------------------------------
# quality_reviewer_node 测试
# ---------------------------------------------------------------------------


class TestQualityReviewerNode:
    def test_node_with_empty_text(self) -> None:
        """空文本应返回错误。"""
        state: dict[str, Any] = {"current_chapter_text": None}
        result = quality_reviewer_node(state)
        assert "quality_reviewer" in result["completed_nodes"]
        assert len(result["errors"]) > 0

    @patch("src.novel.agents.quality_reviewer.create_llm_client")
    def test_node_with_clean_text(self, mock_create_llm: MagicMock) -> None:
        """正常文本应通过审查。"""
        mock_create_llm.return_value = _make_fake_llm({
            "plot_coherence": 8.0,
            "writing_quality": 8.0,
            "character_portrayal": 8.0,
            "ai_flavor_score": 9.0,
        })
        state: dict[str, Any] = {
            "current_chapter_text": _CLEAN_TEXT,
            "config": {"llm": {}},
            "current_chapter_quality": None,
            "current_chapter": 1,
            "auto_approve_threshold": 6.0,
        }
        result = quality_reviewer_node(state)
        assert "quality_reviewer" in result["completed_nodes"]
        assert "current_chapter_quality" in result

    @patch("src.novel.agents.quality_reviewer.create_llm_client")
    def test_node_with_ai_flavor_text(self, mock_create_llm: MagicMock) -> None:
        """Phase 0 架构重构：AI 味黑名单废弃后 rule_check 会通过。

        TODO(phase-1): StyleProfile 接管后重写这个节点级断言。
        """
        mock_create_llm.return_value = _make_fake_llm()
        state: dict[str, Any] = {
            "current_chapter_text": _AI_FLAVOR_TEXT,
            "config": {"llm": {}},
            "current_chapter_quality": None,
            "current_chapter": 1,
            "auto_approve_threshold": 6.0,
            "retry_counts": {},
            "max_retries": 3,
        }
        result = quality_reviewer_node(state)
        assert "quality_reviewer" in result["completed_nodes"]
        quality = result["current_chapter_quality"]
        # Stub returns empty ai_flavor_issues — rule_check no longer fails on flavor text.
        assert quality["rule_check"]["ai_flavor_issues"] == []

    @patch("src.novel.agents.quality_reviewer.create_llm_client")
    def test_node_llm_unavailable(self, mock_create_llm: MagicMock) -> None:
        """LLM 不可用时应仅做规则检查。"""
        mock_create_llm.side_effect = RuntimeError("No LLM")
        state: dict[str, Any] = {
            "current_chapter_text": _CLEAN_TEXT,
            "config": {"llm": {}},
            "current_chapter_quality": None,
            "current_chapter": 1,
            "auto_approve_threshold": 6.0,
        }
        result = quality_reviewer_node(state)
        assert "quality_reviewer" in result["completed_nodes"]
