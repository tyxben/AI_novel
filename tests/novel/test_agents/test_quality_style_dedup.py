"""Tests for style-check deduplication in QualityReviewer.

Verifies that:
1. When existing_style_check is provided, StyleKeeper is NOT instantiated
2. Deviations from existing_style_check are included in suggestions
3. Fallback: when existing_style_check is None but style_name is set, StyleKeeper IS used
4. quality_reviewer_node passes existing style_check from state
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.novel.agents.quality_reviewer import QualityReviewer, quality_reviewer_node


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


_CLEAN_TEXT = (
    "清晨的阳光透过窗帘洒进房间。\n"
    "李明揉了揉眼睛，从床上坐起来。\n"
    "今天是他入职新公司的第一天，他有些紧张。\n"
    "洗漱完毕，他穿上那套新买的西装，对着镜子整了整领带。\n"
    "出门时，楼下的早餐铺飘来阵阵包子的香气。\n"
    "他买了两个肉包子和一杯豆浆，边走边吃。\n"
    "地铁站里人头攒动，他挤上了早高峰的列车。\n"
)


# ---------------------------------------------------------------------------
# 1. existing_style_check provided -> StyleKeeper NOT instantiated
# ---------------------------------------------------------------------------


class TestExistingStyleCheckSkipsStyleKeeper:
    def test_existing_style_check_prevents_stylekeeper_creation(self) -> None:
        """When existing_style_check is provided, StyleKeeper should NOT be imported/created."""
        llm = _make_fake_llm()
        reviewer = QualityReviewer(llm)

        existing = {
            "similarity": 0.85,
            "deviations": ["对话比例偏低"],
            "suggestions": ["增加角色对话比例"],
        }

        with patch(
            "src.novel.agents.style_keeper.StyleKeeper", autospec=True
        ) as mock_sk_cls:
            report = reviewer.review_chapter(
                _CLEAN_TEXT,
                style_name="webnovel.shuangwen",
                budget_mode=True,
                existing_style_check=existing,
            )
            # StyleKeeper should never be instantiated
            mock_sk_cls.assert_not_called()

        # style_check should be populated from existing
        assert report["style_check"]["similarity"] == 0.85
        assert report["style_check"]["deviations"] == ["对话比例偏低"]

    def test_existing_style_check_without_style_name(self) -> None:
        """existing_style_check should work even when style_name is None."""
        reviewer = QualityReviewer(None)

        existing = {
            "similarity": 0.9,
            "deviations": [],
            "suggestions": [],
        }
        report = reviewer.review_chapter(
            _CLEAN_TEXT,
            style_name=None,
            budget_mode=True,
            existing_style_check=existing,
        )
        assert report["style_check"]["similarity"] == 0.9
        assert report["style_check"]["deviations"] == []


# ---------------------------------------------------------------------------
# 2. Deviations from existing_style_check included in suggestions
# ---------------------------------------------------------------------------


class TestExistingStyleCheckSuggestions:
    def test_suggestions_from_existing_style_check(self) -> None:
        """Suggestions from existing_style_check should be added to report."""
        reviewer = QualityReviewer(None)

        existing = {
            "similarity": 0.65,
            "deviations": ["对话比例偏低", "叙述节奏太快"],
            "suggestions": ["增加角色对话比例", "放慢叙述节奏"],
        }
        report = reviewer.review_chapter(
            _CLEAN_TEXT,
            budget_mode=True,
            existing_style_check=existing,
        )
        assert "增加角色对话比例" in report["suggestions"]
        assert "放慢叙述节奏" in report["suggestions"]

    def test_fallback_suggestions_from_deviations_when_no_suggestions_key(self) -> None:
        """When existing_style_check has deviations but no suggestions, generate from deviations."""
        reviewer = QualityReviewer(None)

        existing = {
            "similarity": 0.5,
            "deviations": ["对话比例偏低", "段落过长"],
            # No "suggestions" key
        }
        report = reviewer.review_chapter(
            _CLEAN_TEXT,
            budget_mode=True,
            existing_style_check=existing,
        )
        # Should generate suggestions from deviations
        assert any("对话比例偏低" in s for s in report["suggestions"])
        assert any("段落过长" in s for s in report["suggestions"])

    def test_fallback_suggestions_from_dict_deviations(self) -> None:
        """When deviations are dicts with 'description' key, extract description."""
        reviewer = QualityReviewer(None)

        existing = {
            "similarity": 0.5,
            "deviations": [
                {"description": "对话太少", "severity": "high"},
                {"description": "节奏失控", "severity": "medium"},
            ],
        }
        report = reviewer.review_chapter(
            _CLEAN_TEXT,
            budget_mode=True,
            existing_style_check=existing,
        )
        assert any("对话太少" in s for s in report["suggestions"])
        assert any("节奏失控" in s for s in report["suggestions"])

    def test_empty_deviations_no_suggestions_added(self) -> None:
        """Empty deviations should not add any suggestions."""
        reviewer = QualityReviewer(None)

        existing = {
            "similarity": 0.95,
            "deviations": [],
            "suggestions": [],
        }
        report = reviewer.review_chapter(
            _CLEAN_TEXT,
            budget_mode=True,
            existing_style_check=existing,
        )
        # No style-related suggestions
        assert all("风格偏差" not in s for s in report["suggestions"])

    def test_deviations_capped_at_three(self) -> None:
        """When generating suggestions from deviations (no suggestions key), cap at 3."""
        reviewer = QualityReviewer(None)

        existing = {
            "similarity": 0.3,
            "deviations": ["a", "b", "c", "d", "e"],
            # No suggestions key -> fallback generates from deviations[:3]
        }
        report = reviewer.review_chapter(
            _CLEAN_TEXT,
            budget_mode=True,
            existing_style_check=existing,
        )
        style_suggestions = [s for s in report["suggestions"] if "风格偏差" in s]
        assert len(style_suggestions) == 3


# ---------------------------------------------------------------------------
# 3. Fallback: existing_style_check=None + style_name -> StyleKeeper IS used
# ---------------------------------------------------------------------------


class TestFallbackUsesStyleKeeper:
    def test_fallback_creates_stylekeeper_when_no_existing(self) -> None:
        """Without existing_style_check, style_name should trigger StyleKeeper."""
        llm = _make_fake_llm()
        reviewer = QualityReviewer(llm)

        mock_keeper = MagicMock()
        mock_keeper.check_style.return_value = (0.75, ["偏差1"])
        mock_keeper.suggest_improvements.return_value = ["建议1"]

        # StyleKeeper is lazily imported inside the method, so patch at its source module
        with patch(
            "src.novel.agents.style_keeper.StyleKeeper", return_value=mock_keeper
        ) as mock_sk_cls:
            report = reviewer.review_chapter(
                _CLEAN_TEXT,
                style_name="webnovel.shuangwen",
                budget_mode=True,
                existing_style_check=None,
            )

            mock_sk_cls.assert_called_once_with(llm)
            mock_keeper.check_style.assert_called_once()
            mock_keeper.suggest_improvements.assert_called_once()

        assert report["style_check"]["similarity"] == 0.75
        assert report["style_check"]["deviations"] == ["偏差1"]
        assert "建议1" in report["suggestions"]

    def test_no_style_check_when_neither_existing_nor_style_name(self) -> None:
        """Without existing_style_check and without style_name, no style check at all."""
        reviewer = QualityReviewer(None)

        report = reviewer.review_chapter(
            _CLEAN_TEXT,
            style_name=None,
            budget_mode=True,
            existing_style_check=None,
        )
        assert "style_check" not in report


# ---------------------------------------------------------------------------
# 4. quality_reviewer_node passes existing style_check from state
# ---------------------------------------------------------------------------


class TestQualityReviewerNodeStyleDedup:
    @patch("src.novel.agents.quality_reviewer.create_llm_client")
    def test_node_passes_existing_style_check(self, mock_create_llm: MagicMock) -> None:
        """Node should extract style_keeper results from state and pass to review_chapter."""
        mock_create_llm.return_value = _make_fake_llm({
            "plot_coherence": 8.0,
            "writing_quality": 8.0,
            "character_portrayal": 8.0,
            "ai_flavor_score": 9.0,
        })

        state: dict[str, Any] = {
            "current_chapter_text": _CLEAN_TEXT,
            "config": {"llm": {}},
            "current_chapter": 5,
            "total_chapters": 20,
            "auto_approve_threshold": 6.0,
            "style_name": "webnovel.shuangwen",
            # style_keeper node already populated these:
            "current_chapter_quality": {
                "style_metrics": {"avg_sentence_length": 15.0},
                "style_similarity": 0.82,
                "style_deviations": ["对话偏少"],
                "style_suggestions": ["增加对话"],
            },
        }

        with patch.object(
            QualityReviewer, "review_chapter", wraps=QualityReviewer(mock_create_llm.return_value).review_chapter
        ) as mock_review:
            result = quality_reviewer_node(state)

            # Verify existing_style_check was passed
            call_kwargs = mock_review.call_args
            passed_style_check = call_kwargs.kwargs.get("existing_style_check") or call_kwargs[1].get("existing_style_check")
            assert passed_style_check is not None
            assert passed_style_check["similarity"] == 0.82
            assert passed_style_check["deviations"] == ["对话偏少"]
            assert passed_style_check["suggestions"] == ["增加对话"]

    @patch("src.novel.agents.quality_reviewer.create_llm_client")
    def test_node_no_style_check_when_no_style_keeper_output(self, mock_create_llm: MagicMock) -> None:
        """Node should pass None when style_keeper did not produce results."""
        mock_create_llm.return_value = _make_fake_llm({
            "plot_coherence": 8.0,
            "writing_quality": 8.0,
            "character_portrayal": 8.0,
            "ai_flavor_score": 9.0,
        })

        state: dict[str, Any] = {
            "current_chapter_text": _CLEAN_TEXT,
            "config": {"llm": {}},
            "current_chapter": 5,
            "total_chapters": 20,
            "auto_approve_threshold": 6.0,
            "style_name": "webnovel.shuangwen",
            # No style_keeper output in current_chapter_quality
            "current_chapter_quality": {},
        }

        with patch.object(
            QualityReviewer, "review_chapter", wraps=QualityReviewer(mock_create_llm.return_value).review_chapter
        ) as mock_review:
            result = quality_reviewer_node(state)

            call_kwargs = mock_review.call_args
            passed_style_check = call_kwargs.kwargs.get("existing_style_check") or call_kwargs[1].get("existing_style_check")
            assert passed_style_check is None

    @patch("src.novel.agents.quality_reviewer.create_llm_client")
    def test_node_no_style_check_when_quality_is_none(self, mock_create_llm: MagicMock) -> None:
        """Node should handle current_chapter_quality being None."""
        mock_create_llm.return_value = _make_fake_llm({
            "plot_coherence": 8.0,
            "writing_quality": 8.0,
            "character_portrayal": 8.0,
            "ai_flavor_score": 9.0,
        })

        state: dict[str, Any] = {
            "current_chapter_text": _CLEAN_TEXT,
            "config": {"llm": {}},
            "current_chapter": 5,
            "total_chapters": 20,
            "auto_approve_threshold": 6.0,
            "style_name": "webnovel.shuangwen",
            "current_chapter_quality": None,
        }

        with patch.object(
            QualityReviewer, "review_chapter", wraps=QualityReviewer(mock_create_llm.return_value).review_chapter
        ) as mock_review:
            result = quality_reviewer_node(state)

            call_kwargs = mock_review.call_args
            passed_style_check = call_kwargs.kwargs.get("existing_style_check") or call_kwargs[1].get("existing_style_check")
            assert passed_style_check is None
