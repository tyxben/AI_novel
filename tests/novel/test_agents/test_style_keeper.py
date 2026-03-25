"""StyleKeeper Agent + StyleAnalysisTool 单元测试

覆盖：
- StyleAnalysisTool.analyze: 正常文本、空文本、各种风格
- StyleAnalysisTool.compare: 相同/不同指标
- StyleKeeper.check_style: 已知风格预设
- StyleKeeper.suggest_improvements: 规则建议
- style_keeper_node: 状态更新
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.novel.models.quality import StyleMetrics
from src.novel.tools.style_analysis_tool import StyleAnalysisTool
from src.novel.agents.style_keeper import StyleKeeper, style_keeper_node, _constraints_to_metrics


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake-model"
    usage: dict | None = None


def _make_fake_llm() -> MagicMock:
    llm = MagicMock()
    llm.chat.return_value = FakeLLMResponse(content='{"result": "ok"}')
    return llm


# 网文爽文风格样本：短句、多对话、多感叹
_SHUANGWEN_SAMPLE = (
    "\u201c废物？\u201d\n"
    "林凡嘴角微扬。\n"
    "轰！\n"
    "一股恐怖的气浪横扫全场。\n"
    "那几个弟子被震飞出去！\n"
    "全场寂静。\n"
    "所有人都傻了。\n"
    "\u201c你说谁是废物？\u201d林凡冷笑。\n"
    "\u201c不……不可能！\u201d张三满脸惊恐。\n"
    "\u201c滚！\u201d\n"
)

# 文学现实主义风格样本：长句、少对话
_LITERARY_SAMPLE = (
    "父亲把最后一口馒头塞进嘴里，用手背擦了擦嘴，站起身来往外走。"
    "走到门口又停下，从裤兜里摸出两张皱巴巴的十块钱，放在桌上。"
    "他没说话，门在身后关上了。\n"
    "桌上的钱被穿堂风吹得微微颤动。"
    "屋里很安静，只有墙上的挂钟在嘀嗒作响。"
    "母亲坐在灶台边，手里捏着一把韭菜，眼睛望着窗外发呆。"
    "院子里的老槐树落了一地黄叶，秋风卷着叶子在地上打转。"
)


# ---------------------------------------------------------------------------
# StyleAnalysisTool.analyze 测试
# ---------------------------------------------------------------------------


class TestStyleAnalysisToolAnalyze:
    def setup_method(self) -> None:
        self.tool = StyleAnalysisTool()

    def test_analyze_normal_text(self) -> None:
        metrics = self.tool.analyze(_SHUANGWEN_SAMPLE)
        assert isinstance(metrics, StyleMetrics)
        assert metrics.avg_sentence_length > 0
        assert 0.0 <= metrics.dialogue_ratio <= 1.0
        assert 0.0 <= metrics.exclamation_ratio <= 1.0
        assert metrics.paragraph_length > 0

    def test_analyze_empty_text(self) -> None:
        metrics = self.tool.analyze("")
        assert metrics.avg_sentence_length == 0.0
        assert metrics.dialogue_ratio == 0.0
        assert metrics.exclamation_ratio == 0.0
        assert metrics.paragraph_length == 0.0

    def test_analyze_whitespace_text(self) -> None:
        metrics = self.tool.analyze("   \n\n  ")
        assert metrics.avg_sentence_length == 0.0

    def test_shuangwen_has_high_dialogue_ratio(self) -> None:
        """网文爽文应有较高对话占比。"""
        metrics = self.tool.analyze(_SHUANGWEN_SAMPLE)
        assert metrics.dialogue_ratio > 0.1  # 包含多段对话

    def test_shuangwen_has_exclamations(self) -> None:
        """网文爽文应有感叹句。"""
        metrics = self.tool.analyze(_SHUANGWEN_SAMPLE)
        assert metrics.exclamation_ratio > 0.0

    def test_literary_has_longer_sentences(self) -> None:
        """文学现实主义应有较长句子。"""
        lit_metrics = self.tool.analyze(_LITERARY_SAMPLE)
        shuang_metrics = self.tool.analyze(_SHUANGWEN_SAMPLE)
        assert lit_metrics.avg_sentence_length > shuang_metrics.avg_sentence_length

    def test_analyze_classical_text(self) -> None:
        """包含古典词汇的文本应有非零 classical_word_ratio。"""
        text = "然则此事须知端的，莫非他兀自不肯罢了。遂拱手道：且慢，皆非小事。"
        metrics = self.tool.analyze(text)
        assert metrics.classical_word_ratio is not None
        assert metrics.classical_word_ratio > 0.0

    def test_analyze_first_person(self) -> None:
        """第一人称叙述应有较高 first_person_ratio。"""
        text = "我走在路上，看到远处有一座山。我停下脚步。我心想这到底怎么回事。"
        metrics = self.tool.analyze(text)
        assert metrics.first_person_ratio is not None
        assert metrics.first_person_ratio > 0.5


# ---------------------------------------------------------------------------
# StyleAnalysisTool.compare 测试
# ---------------------------------------------------------------------------


class TestStyleAnalysisToolCompare:
    def setup_method(self) -> None:
        self.tool = StyleAnalysisTool()

    def test_identical_metrics_high_similarity(self) -> None:
        """完全相同的指标相似度应接近 1.0。"""
        m = StyleMetrics(
            avg_sentence_length=15.0,
            dialogue_ratio=0.3,
            exclamation_ratio=0.05,
            paragraph_length=100.0,
        )
        similarity, deviations = self.tool.compare(m, m)
        assert similarity >= 0.99
        assert len(deviations) == 0

    def test_very_different_metrics_low_similarity(self) -> None:
        """差异很大的指标相似度应低于 0.5。"""
        m1 = StyleMetrics(
            avg_sentence_length=5.0,
            dialogue_ratio=0.8,
            exclamation_ratio=0.3,
            paragraph_length=30.0,
        )
        m2 = StyleMetrics(
            avg_sentence_length=40.0,
            dialogue_ratio=0.1,
            exclamation_ratio=0.0,
            paragraph_length=300.0,
        )
        similarity, deviations = self.tool.compare(m1, m2)
        assert similarity < 0.5
        assert len(deviations) > 0

    def test_compare_with_custom_tolerances(self) -> None:
        """自定义容差应影响相似度计算。"""
        m1 = StyleMetrics(
            avg_sentence_length=15.0,
            dialogue_ratio=0.3,
            exclamation_ratio=0.05,
            paragraph_length=100.0,
        )
        m2 = StyleMetrics(
            avg_sentence_length=20.0,
            dialogue_ratio=0.3,
            exclamation_ratio=0.05,
            paragraph_length=100.0,
        )
        # 宽松容差
        sim_loose, _ = self.tool.compare(m1, m2, tolerances={"avg_sentence_length": 50.0})
        # 严格容差
        sim_strict, _ = self.tool.compare(m1, m2, tolerances={"avg_sentence_length": 2.0})
        assert sim_loose > sim_strict

    def test_compare_reports_deviations(self) -> None:
        """偏差大的字段应出现在 deviations 中。"""
        m1 = StyleMetrics(
            avg_sentence_length=5.0,
            dialogue_ratio=0.3,
            exclamation_ratio=0.05,
            paragraph_length=100.0,
        )
        m2 = StyleMetrics(
            avg_sentence_length=35.0,
            dialogue_ratio=0.3,
            exclamation_ratio=0.05,
            paragraph_length=100.0,
        )
        _, deviations = self.tool.compare(m1, m2)
        assert any("平均句长" in d for d in deviations)


# ---------------------------------------------------------------------------
# StyleKeeper 测试
# ---------------------------------------------------------------------------


class TestStyleKeeper:
    def setup_method(self) -> None:
        self.llm = _make_fake_llm()
        self.keeper = StyleKeeper(self.llm)

    def test_analyze_style_returns_metrics(self) -> None:
        metrics = self.keeper.analyze_style(_SHUANGWEN_SAMPLE)
        assert isinstance(metrics, StyleMetrics)

    def test_check_style_with_known_preset(self) -> None:
        """检查文本与已知风格预设的匹配度。"""
        similarity, deviations = self.keeper.check_style(
            _SHUANGWEN_SAMPLE, "webnovel.shuangwen"
        )
        assert 0.0 <= similarity <= 1.0
        assert isinstance(deviations, list)

    def test_check_style_unknown_preset_raises(self) -> None:
        """未知风格预设应抛出 KeyError。"""
        with pytest.raises(KeyError):
            self.keeper.check_style(_SHUANGWEN_SAMPLE, "nonexistent.style")

    def test_suggest_improvements_for_deviations(self) -> None:
        """应针对偏差生成建议。"""
        deviations = [
            "平均句长偏高（当前=35.00，参考=15.00）",
            "对话占比偏低（当前=0.10，参考=0.40）",
        ]
        suggestions = self.keeper.suggest_improvements(_SHUANGWEN_SAMPLE, deviations)
        assert len(suggestions) == 2
        assert any("短句" in s for s in suggestions)
        assert any("对话" in s for s in suggestions)

    def test_suggest_improvements_empty_deviations(self) -> None:
        """无偏差时建议列表为空。"""
        suggestions = self.keeper.suggest_improvements(_SHUANGWEN_SAMPLE, [])
        assert suggestions == []


# ---------------------------------------------------------------------------
# _constraints_to_metrics 测试
# ---------------------------------------------------------------------------


class TestConstraintsToMetrics:
    def test_basic_constraints(self) -> None:
        constraints = {
            "avg_sentence_length": [10, 20],
            "dialogue_ratio": [0.3, 0.5],
            "max_paragraph_sentences": 5,
        }
        metrics = _constraints_to_metrics(constraints)
        assert metrics.avg_sentence_length == 15.0
        assert metrics.dialogue_ratio == 0.4

    def test_missing_constraints_use_defaults(self) -> None:
        metrics = _constraints_to_metrics({})
        assert metrics.avg_sentence_length == 15.0
        assert metrics.dialogue_ratio == 0.3


# ---------------------------------------------------------------------------
# style_keeper_node 测试
# ---------------------------------------------------------------------------


class TestStyleKeeperNode:
    def test_node_with_empty_text(self) -> None:
        """空文本应返回错误。"""
        state: dict[str, Any] = {"current_chapter_text": None}
        result = style_keeper_node(state)
        assert "style_keeper" in result["completed_nodes"]
        assert len(result["errors"]) > 0

    @patch("src.novel.agents.style_keeper.create_llm_client")
    def test_node_with_text_and_style(self, mock_create_llm: MagicMock) -> None:
        """有文本和风格名称时应执行完整检查。"""
        mock_create_llm.return_value = _make_fake_llm()
        state: dict[str, Any] = {
            "current_chapter_text": _SHUANGWEN_SAMPLE,
            "style_name": "webnovel.shuangwen",
            "config": {"llm": {}},
            "current_chapter_quality": None,
        }
        result = style_keeper_node(state)
        assert "style_keeper" in result["completed_nodes"]
        assert "current_chapter_quality" in result
        quality = result["current_chapter_quality"]
        assert "style_metrics" in quality

    @patch("src.novel.agents.style_keeper.create_llm_client")
    def test_node_without_style(self, mock_create_llm: MagicMock) -> None:
        """无风格名称时只做基础分析。"""
        mock_create_llm.return_value = _make_fake_llm()
        state: dict[str, Any] = {
            "current_chapter_text": _LITERARY_SAMPLE,
            "config": {"llm": {}},
            "current_chapter_quality": None,
        }
        result = style_keeper_node(state)
        assert "style_keeper" in result["completed_nodes"]
        quality = result["current_chapter_quality"]
        assert "style_metrics" in quality
        # 没有 style_name，不应有 style_similarity
        assert "style_similarity" not in quality
