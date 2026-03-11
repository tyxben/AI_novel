"""Tests for FeedbackAnalyzer agent and feedback_analyzer_node."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tests.novel.conftest import FakeLLMResponse, make_llm_client, make_outline_dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _outline_chapters(n: int = 5) -> list[dict]:
    """Return a list of outline chapter dicts."""
    return make_outline_dict(total_chapters=n)["chapters"]


def _characters() -> list[dict]:
    return [{"name": "张三"}, {"name": "李四"}]


def _valid_analysis_json() -> dict:
    """Return a valid analysis JSON that the LLM would return."""
    return {
        "feedback_type": "character",
        "severity": "high",
        "target_chapters": [2, 3],
        "propagation_chapters": [4, 5],
        "rewrite_instructions": {
            "2": "加强主角性格描写",
            "3": "补充角色互动细节",
        },
        "character_changes": [{"name": "张三", "change": "性格更沉稳"}],
        "summary": "主角性格不够鲜明，需加强刻画",
    }


# =========================================================================
# FeedbackAnalyzer.analyze() tests
# =========================================================================


class TestFeedbackAnalyzerAnalyze:
    """Tests for FeedbackAnalyzer.analyze()."""

    def test_analyze_valid_json(self):
        """LLM returns valid JSON analysis -- happy path."""
        from src.novel.agents.feedback_analyzer import FeedbackAnalyzer

        analysis_json = _valid_analysis_json()
        llm = make_llm_client(response_json=analysis_json)
        analyzer = FeedbackAnalyzer(llm)

        result = analyzer.analyze(
            feedback_text="主角性格太平淡",
            chapter_number=2,
            outline_chapters=_outline_chapters(5),
            characters=_characters(),
        )

        assert result["feedback_type"] == "character"
        assert result["severity"] == "high"
        assert 2 in result["target_chapters"]
        assert 3 in result["target_chapters"]
        assert 4 in result["propagation_chapters"]
        assert result["rewrite_instructions"]["2"] == "加强主角性格描写"
        assert result["summary"] == "主角性格不够鲜明，需加强刻画"
        llm.chat.assert_called_once()

    def test_analyze_garbage_fallback(self):
        """LLM returns garbage text -- fallback to direct rewrite."""
        from src.novel.agents.feedback_analyzer import FeedbackAnalyzer

        llm = make_llm_client(response_text="这不是JSON，只是乱码!!!")
        analyzer = FeedbackAnalyzer(llm)

        result = analyzer.analyze(
            feedback_text="节奏太慢了",
            chapter_number=3,
            outline_chapters=_outline_chapters(5),
            characters=_characters(),
        )

        assert result["feedback_type"] == "other"
        assert result["severity"] == "medium"
        assert result["target_chapters"] == [3]
        assert result["propagation_chapters"] == []
        assert result["rewrite_instructions"] == {"3": "节奏太慢了"}
        assert "LLM 分析失败" in result["summary"]

    def test_analyze_chapter_number_none_global_feedback(self):
        """chapter_number=None means global feedback -- fallback path."""
        from src.novel.agents.feedback_analyzer import FeedbackAnalyzer

        # LLM returns garbage to trigger fallback
        llm = make_llm_client(response_text="not json at all")
        analyzer = FeedbackAnalyzer(llm)

        result = analyzer.analyze(
            feedback_text="整体节奏偏慢",
            chapter_number=None,
            outline_chapters=_outline_chapters(5),
            characters=_characters(),
        )

        assert result["target_chapters"] == []
        assert result["rewrite_instructions"] == {}
        assert result["feedback_type"] == "other"

    def test_analyze_chapter_number_none_valid_json(self):
        """chapter_number=None with valid LLM JSON -- global hint in prompt."""
        from src.novel.agents.feedback_analyzer import FeedbackAnalyzer

        analysis_json = {
            "feedback_type": "pacing",
            "severity": "low",
            "target_chapters": [1, 3],
            "propagation_chapters": [],
            "rewrite_instructions": {"1": "加快开头节奏", "3": "删减过渡段落"},
            "character_changes": None,
            "summary": "节奏偏慢",
        }
        llm = make_llm_client(response_json=analysis_json)
        analyzer = FeedbackAnalyzer(llm)

        result = analyzer.analyze(
            feedback_text="前几章太拖了",
            chapter_number=None,
            outline_chapters=_outline_chapters(5),
            characters=_characters(),
        )

        # Verify global hint appeared in prompt (no chapter number)
        call_args = llm.chat.call_args
        user_msg = call_args[1]["messages"][1]["content"] if "messages" in (call_args[1] or {}) else call_args[0][0][1]["content"]
        assert "全局反馈" in user_msg
        assert result["feedback_type"] == "pacing"

    def test_analyze_sanitizes_invalid_feedback_type(self):
        """Invalid feedback_type is replaced with 'other'."""
        from src.novel.agents.feedback_analyzer import FeedbackAnalyzer

        analysis_json = _valid_analysis_json()
        analysis_json["feedback_type"] = "INVALID_TYPE"

        llm = make_llm_client(response_json=analysis_json)
        analyzer = FeedbackAnalyzer(llm)

        result = analyzer.analyze(
            feedback_text="test",
            chapter_number=1,
            outline_chapters=_outline_chapters(5),
            characters=_characters(),
        )

        assert result["feedback_type"] == "other"

    def test_analyze_sanitizes_invalid_severity(self):
        """Invalid severity is replaced with 'medium'."""
        from src.novel.agents.feedback_analyzer import FeedbackAnalyzer

        analysis_json = _valid_analysis_json()
        analysis_json["severity"] = "critical"  # not in {low, medium, high}

        llm = make_llm_client(response_json=analysis_json)
        analyzer = FeedbackAnalyzer(llm)

        result = analyzer.analyze(
            feedback_text="test",
            chapter_number=1,
            outline_chapters=_outline_chapters(5),
            characters=_characters(),
        )

        assert result["severity"] == "medium"

    def test_analyze_caps_propagation_chapters(self):
        """propagation_chapters is capped to max_propagation."""
        from src.novel.agents.feedback_analyzer import FeedbackAnalyzer

        analysis_json = _valid_analysis_json()
        # Create outline with 20 chapters and propagation that exceeds limit
        outline_chapters = _outline_chapters(20)
        analysis_json["propagation_chapters"] = list(range(3, 18))  # 15 chapters

        llm = make_llm_client(response_json=analysis_json)
        analyzer = FeedbackAnalyzer(llm)

        result = analyzer.analyze(
            feedback_text="test",
            chapter_number=1,
            outline_chapters=outline_chapters,
            characters=_characters(),
            max_propagation=5,
        )

        assert len(result["propagation_chapters"]) <= 5

    def test_analyze_filters_out_of_range_chapter_numbers(self):
        """Chapter numbers outside [1, total] are filtered out."""
        from src.novel.agents.feedback_analyzer import FeedbackAnalyzer

        analysis_json = _valid_analysis_json()
        analysis_json["target_chapters"] = [0, 1, 3, 99, -1]
        analysis_json["propagation_chapters"] = [2, 100, 5]

        llm = make_llm_client(response_json=analysis_json)
        analyzer = FeedbackAnalyzer(llm)

        # 5 chapters total
        result = analyzer.analyze(
            feedback_text="test",
            chapter_number=1,
            outline_chapters=_outline_chapters(5),
            characters=_characters(),
        )

        # Only chapters 1-5 should be kept
        for ch in result["target_chapters"]:
            assert 1 <= ch <= 5, f"Out-of-range chapter {ch} not filtered"
        for ch in result["propagation_chapters"]:
            assert 1 <= ch <= 5, f"Out-of-range chapter {ch} not filtered"
        assert 99 not in result["target_chapters"]
        assert 0 not in result["target_chapters"]

    def test_analyze_filters_non_numeric_instruction_keys(self):
        """rewrite_instructions keys that are not digit strings are dropped."""
        from src.novel.agents.feedback_analyzer import FeedbackAnalyzer

        analysis_json = _valid_analysis_json()
        analysis_json["rewrite_instructions"] = {
            "2": "有效指令",
            "abc": "无效key",
            "3": "另一个有效指令",
        }

        llm = make_llm_client(response_json=analysis_json)
        analyzer = FeedbackAnalyzer(llm)

        result = analyzer.analyze(
            feedback_text="test",
            chapter_number=1,
            outline_chapters=_outline_chapters(5),
            characters=_characters(),
        )

        assert "2" in result["rewrite_instructions"]
        assert "3" in result["rewrite_instructions"]
        assert "abc" not in result["rewrite_instructions"]


# =========================================================================
# feedback_analyzer_node() tests
# =========================================================================


class TestFeedbackAnalyzerNode:
    """Tests for the feedback_analyzer_node LangGraph node function."""

    def test_node_happy_path(self):
        """Node processes first pending feedback and returns analysis."""
        from src.novel.agents.feedback_analyzer import feedback_analyzer_node

        analysis_json = _valid_analysis_json()
        mock_llm = make_llm_client(response_json=analysis_json)

        state = {
            "feedback_entries": [
                {
                    "content": "主角太弱了",
                    "chapter_number": 2,
                    "status": "pending",
                },
            ],
            "config": {"llm": {"provider": "fake"}},
            "outline": {"chapters": _outline_chapters(5)},
            "characters": _characters(),
        }

        with patch(
            "src.llm.llm_client.create_llm_client",
            return_value=mock_llm,
        ):
            result = feedback_analyzer_node(state)

        assert "feedback_analyzer" in result["completed_nodes"]
        assert result["feedback_analysis"]["feedback_type"] == "character"
        assert isinstance(result["rewrite_queue"], list)
        assert len(result["rewrite_queue"]) > 0
        assert isinstance(result["rewrite_instructions"], dict)
        assert len(result["decisions"]) == 1
        assert result["decisions"][0]["agent"] == "FeedbackAnalyzer"
        # Entry status should be updated
        assert state["feedback_entries"][0]["status"] == "analyzed"

    def test_node_no_pending_feedback(self):
        """Node returns error when no pending feedback entries exist."""
        from src.novel.agents.feedback_analyzer import feedback_analyzer_node

        state = {
            "feedback_entries": [
                {"content": "已处理", "status": "analyzed"},
            ],
        }

        result = feedback_analyzer_node(state)

        assert "feedback_analyzer" in result["completed_nodes"]
        assert len(result["errors"]) == 1
        assert "没有待处理的反馈" in result["errors"][0]["message"]

    def test_node_empty_feedback_entries(self):
        """Node returns error when feedback_entries is empty."""
        from src.novel.agents.feedback_analyzer import feedback_analyzer_node

        result = feedback_analyzer_node({"feedback_entries": []})

        assert "feedback_analyzer" in result["completed_nodes"]
        assert len(result["errors"]) == 1

    def test_node_llm_init_failure(self):
        """Node returns error when LLM client creation fails."""
        from src.novel.agents.feedback_analyzer import feedback_analyzer_node

        state = {
            "feedback_entries": [
                {"content": "test", "status": "pending"},
            ],
            "config": {"llm": {}},
        }

        with patch(
            "src.llm.llm_client.create_llm_client",
            side_effect=RuntimeError("No API key"),
        ):
            result = feedback_analyzer_node(state)

        assert "feedback_analyzer" in result["completed_nodes"]
        assert len(result["errors"]) == 1
        assert "LLM 初始化失败" in result["errors"][0]["message"]
        assert "No API key" in result["errors"][0]["message"]

    def test_node_rewrite_queue_sorted_and_deduped(self):
        """rewrite_queue contains sorted unique union of target + propagation."""
        from src.novel.agents.feedback_analyzer import feedback_analyzer_node

        analysis_json = {
            "feedback_type": "plot_hole",
            "severity": "high",
            "target_chapters": [3, 1],
            "propagation_chapters": [3, 4, 5],  # 3 overlaps with target
            "rewrite_instructions": {"1": "fix", "3": "fix", "4": "fix", "5": "fix"},
            "character_changes": None,
            "summary": "情节漏洞",
        }
        mock_llm = make_llm_client(response_json=analysis_json)

        state = {
            "feedback_entries": [
                {"content": "情节矛盾", "chapter_number": 3, "status": "pending"},
            ],
            "config": {"llm": {}},
            "outline": {"chapters": _outline_chapters(5)},
            "characters": [],
        }

        with patch(
            "src.llm.llm_client.create_llm_client",
            return_value=mock_llm,
        ):
            result = feedback_analyzer_node(state)

        queue = result["rewrite_queue"]
        assert queue == sorted(set(queue)), "Queue should be sorted and deduplicated"
        assert 3 in queue
        assert 1 in queue
