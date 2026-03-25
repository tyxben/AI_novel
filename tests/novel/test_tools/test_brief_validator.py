"""Tests for BriefValidator tool.

Covers:
- All items fulfilled
- Partial fulfillment
- Empty brief (no LLM call)
- Missing brief fields
- Suggested debt generation
- Pass rate calculation
- Long chapter text truncation
- LLM error handling / permissive fallback
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.tools.brief_validator import BriefValidator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_llm(content: str) -> MagicMock:
    """Create a mock LLM client returning the given JSON string."""
    mock = MagicMock()
    mock.chat.return_value = LLMResponse(
        content=content,
        model="test-model",
        usage=None,
    )
    return mock


_FULL_BRIEF = {
    "main_conflict": "主角与反派首次正面冲突",
    "payoff": "获得秘籍",
    "character_arc_step": "主角从怯懦变得勇敢",
    "foreshadowing_plant": ["神秘老人的身份"],
    "foreshadowing_collect": ["第一章提到的宝剑"],
    "end_hook_type": "cliffhanger",
}

_SAMPLE_CHAPTER = "主角站在擂台上，面对强大的反派，他心中涌起一股从未有过的勇气。" * 30


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestValidateAllFulfilled:
    """Mock LLM returns all items fulfilled."""

    def test_validate_all_fulfilled(self):
        llm_response = json.dumps({
            "main_conflict_fulfilled": True,
            "payoff_delivered": True,
            "character_arc_step_taken": True,
            "foreshadowing_planted": [True],
            "foreshadowing_collected": [True],
            "end_hook_present": True,
            "item_results": [
                {
                    "item_name": "main_conflict",
                    "expected": "主角与反派首次正面冲突",
                    "fulfilled": True,
                    "evidence": "擂台对决场景",
                    "reason": "冲突场景完整呈现",
                },
                {
                    "item_name": "payoff",
                    "expected": "获得秘籍",
                    "fulfilled": True,
                    "evidence": "战胜后获得奖励",
                    "reason": "爽点兑现",
                },
                {
                    "item_name": "character_arc_step",
                    "expected": "主角从怯懦变得勇敢",
                    "fulfilled": True,
                    "evidence": "心中涌起勇气",
                    "reason": "角色成长明显",
                },
            ],
            "unfulfilled_items": [],
            "overall_pass": True,
        })

        mock_llm = _make_llm(llm_response)
        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(_SAMPLE_CHAPTER, _FULL_BRIEF, chapter_number=5)

        assert result["overall_pass"] is True
        assert result["pass_rate"] == 1.0
        assert result["chapter_number"] == 5
        assert len(result["unfulfilled_items"]) == 0
        assert len(result["suggested_debts"]) == 0
        assert len(result["item_results"]) == 3
        mock_llm.chat.assert_called_once()


class TestValidatePartialFulfilled:
    """Some items pass, some fail."""

    def test_validate_partial_fulfilled(self):
        llm_response = json.dumps({
            "main_conflict_fulfilled": True,
            "payoff_delivered": False,
            "character_arc_step_taken": True,
            "foreshadowing_planted": [True],
            "foreshadowing_collected": [False],
            "end_hook_present": True,
            "item_results": [
                {
                    "item_name": "main_conflict",
                    "expected": "主角与反派首次正面冲突",
                    "fulfilled": True,
                    "evidence": "擂台对决",
                    "reason": "已完成",
                },
                {
                    "item_name": "payoff",
                    "expected": "获得秘籍",
                    "fulfilled": False,
                    "evidence": None,
                    "reason": "章节中未提及获得秘籍",
                },
                {
                    "item_name": "foreshadowing_collect",
                    "expected": "第一章提到的宝剑",
                    "fulfilled": False,
                    "evidence": None,
                    "reason": "宝剑未出现",
                },
            ],
            "unfulfilled_items": ["payoff", "foreshadowing_collect"],
            "overall_pass": False,
        })

        mock_llm = _make_llm(llm_response)
        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(_SAMPLE_CHAPTER, _FULL_BRIEF, chapter_number=3)

        assert result["overall_pass"] is False
        assert result["chapter_number"] == 3
        assert len(result["unfulfilled_items"]) == 2
        assert "payoff" in result["unfulfilled_items"]

        # pass_rate: 1 out of 3 fulfilled
        assert abs(result["pass_rate"] - 1.0 / 3.0) < 0.01

        # Should generate suggested debts for payoff and foreshadowing_collect
        assert len(result["suggested_debts"]) >= 2
        debt_descriptions = [d["description"] for d in result["suggested_debts"]]
        assert any("payoff" in desc for desc in debt_descriptions)
        assert any("foreshadowing_collect" in desc for desc in debt_descriptions)


class TestValidateEmptyBrief:
    """Empty brief returns pass=True without LLM call."""

    def test_empty_dict(self):
        mock_llm = MagicMock()
        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(_SAMPLE_CHAPTER, {}, chapter_number=1)

        assert result["overall_pass"] is True
        assert result["pass_rate"] == 1.0
        assert result["item_results"] == []
        assert result["unfulfilled_items"] == []
        assert result["suggested_debts"] == []
        mock_llm.chat.assert_not_called()

    def test_none_brief(self):
        mock_llm = MagicMock()
        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(_SAMPLE_CHAPTER, None, chapter_number=1)

        assert result["overall_pass"] is True
        mock_llm.chat.assert_not_called()

    def test_all_empty_values(self):
        mock_llm = MagicMock()
        validator = BriefValidator(mock_llm)
        brief = {
            "main_conflict": "",
            "payoff": "",
            "character_arc_step": "",
            "foreshadowing_plant": [],
            "foreshadowing_collect": [],
            "end_hook_type": "",
        }
        result = validator.validate_chapter(_SAMPLE_CHAPTER, brief, chapter_number=1)

        assert result["overall_pass"] is True
        mock_llm.chat.assert_not_called()


class TestValidateMissingFields:
    """Brief with only some fields."""

    def test_brief_with_only_main_conflict(self):
        llm_response = json.dumps({
            "main_conflict_fulfilled": True,
            "payoff_delivered": True,
            "character_arc_step_taken": True,
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "end_hook_present": True,
            "item_results": [
                {
                    "item_name": "main_conflict",
                    "expected": "主角觉醒力量",
                    "fulfilled": True,
                    "evidence": "力量觉醒描写",
                    "reason": "已完成",
                },
            ],
            "unfulfilled_items": [],
            "overall_pass": True,
        })

        mock_llm = _make_llm(llm_response)
        validator = BriefValidator(mock_llm)

        brief = {"main_conflict": "主角觉醒力量"}
        result = validator.validate_chapter(_SAMPLE_CHAPTER, brief, chapter_number=2)

        assert result["overall_pass"] is True
        assert result["chapter_number"] == 2
        mock_llm.chat.assert_called_once()

    def test_brief_with_only_foreshadowing(self):
        llm_response = json.dumps({
            "main_conflict_fulfilled": True,
            "payoff_delivered": True,
            "character_arc_step_taken": True,
            "foreshadowing_planted": [True, False],
            "foreshadowing_collected": [],
            "end_hook_present": True,
            "item_results": [
                {
                    "item_name": "foreshadowing_plant_1",
                    "expected": "神秘符文",
                    "fulfilled": True,
                    "evidence": "符文出现",
                    "reason": "已埋设",
                },
                {
                    "item_name": "foreshadowing_plant_2",
                    "expected": "暗影势力",
                    "fulfilled": False,
                    "evidence": None,
                    "reason": "未提及",
                },
            ],
            "unfulfilled_items": ["foreshadowing_plant_2"],
            "overall_pass": False,
        })

        mock_llm = _make_llm(llm_response)
        validator = BriefValidator(mock_llm)

        brief = {"foreshadowing_plant": ["神秘符文", "暗影势力"]}
        result = validator.validate_chapter(_SAMPLE_CHAPTER, brief, chapter_number=4)

        assert result["overall_pass"] is False
        assert abs(result["pass_rate"] - 0.5) < 0.01


class TestSuggestedDebts:
    """Unfulfilled items generate debt suggestions."""

    def test_suggested_debts_for_unfulfilled_mandatory(self):
        llm_response = json.dumps({
            "main_conflict_fulfilled": False,
            "payoff_delivered": False,
            "character_arc_step_taken": False,
            "foreshadowing_planted": [False],
            "foreshadowing_collected": [False],
            "end_hook_present": False,
            "item_results": [],
            "unfulfilled_items": [
                "main_conflict", "payoff", "character_arc_step",
                "foreshadowing_plant", "foreshadowing_collect", "end_hook_type",
            ],
            "overall_pass": False,
        })

        mock_llm = _make_llm(llm_response)
        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(_SAMPLE_CHAPTER, _FULL_BRIEF, chapter_number=7)

        debts = result["suggested_debts"]
        # Expect debts for: main_conflict, payoff, character_arc_step,
        # end_hook_type, foreshadowing_plant[0], foreshadowing_collect[0]
        assert len(debts) >= 4

        # Check debt structure
        for debt in debts:
            assert "type" in debt
            assert debt["type"] in ("must_pay_next", "pay_within_3")
            assert "description" in debt
            assert "urgency_level" in debt
            assert "第7章未完成" in debt["description"]

        # main_conflict and payoff should be must_pay_next / high
        mc_debts = [d for d in debts if "main_conflict" in d["description"]]
        assert len(mc_debts) == 1
        assert mc_debts[0]["type"] == "must_pay_next"
        assert mc_debts[0]["urgency_level"] == "high"

    def test_no_debts_when_all_fulfilled(self):
        llm_response = json.dumps({
            "main_conflict_fulfilled": True,
            "payoff_delivered": True,
            "character_arc_step_taken": True,
            "foreshadowing_planted": [True],
            "foreshadowing_collected": [True],
            "end_hook_present": True,
            "item_results": [
                {
                    "item_name": "main_conflict",
                    "expected": "test",
                    "fulfilled": True,
                    "evidence": "found",
                    "reason": "ok",
                },
            ],
            "unfulfilled_items": [],
            "overall_pass": True,
        })

        mock_llm = _make_llm(llm_response)
        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(_SAMPLE_CHAPTER, _FULL_BRIEF, chapter_number=2)

        assert result["suggested_debts"] == []


class TestPassRateCalculation:
    """Verify pass_rate math."""

    def test_pass_rate_all_pass(self):
        items = [
            {"item_name": f"item_{i}", "expected": "x", "fulfilled": True, "evidence": "y", "reason": "z"}
            for i in range(5)
        ]
        llm_response = json.dumps({
            "main_conflict_fulfilled": True,
            "payoff_delivered": True,
            "character_arc_step_taken": True,
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "end_hook_present": True,
            "item_results": items,
            "unfulfilled_items": [],
            "overall_pass": True,
        })

        mock_llm = _make_llm(llm_response)
        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(_SAMPLE_CHAPTER, _FULL_BRIEF, chapter_number=1)

        assert result["pass_rate"] == 1.0

    def test_pass_rate_none_pass(self):
        items = [
            {"item_name": f"item_{i}", "expected": "x", "fulfilled": False, "evidence": None, "reason": "fail"}
            for i in range(4)
        ]
        llm_response = json.dumps({
            "main_conflict_fulfilled": False,
            "payoff_delivered": False,
            "character_arc_step_taken": False,
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "end_hook_present": False,
            "item_results": items,
            "unfulfilled_items": ["item_0", "item_1", "item_2", "item_3"],
            "overall_pass": False,
        })

        mock_llm = _make_llm(llm_response)
        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(_SAMPLE_CHAPTER, _FULL_BRIEF, chapter_number=1)

        assert result["pass_rate"] == 0.0

    def test_pass_rate_two_of_five(self):
        items = [
            {"item_name": f"item_{i}", "expected": "x", "fulfilled": i < 2, "evidence": "y", "reason": "z"}
            for i in range(5)
        ]
        llm_response = json.dumps({
            "main_conflict_fulfilled": True,
            "payoff_delivered": True,
            "character_arc_step_taken": True,
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "end_hook_present": True,
            "item_results": items,
            "unfulfilled_items": ["item_2", "item_3", "item_4"],
            "overall_pass": False,
        })

        mock_llm = _make_llm(llm_response)
        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(_SAMPLE_CHAPTER, _FULL_BRIEF, chapter_number=1)

        assert abs(result["pass_rate"] - 0.4) < 0.01

    def test_pass_rate_empty_items_defaults_to_one(self):
        """When LLM returns no item_results, pass_rate should be 1.0."""
        llm_response = json.dumps({
            "main_conflict_fulfilled": True,
            "payoff_delivered": True,
            "character_arc_step_taken": True,
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "end_hook_present": True,
            "item_results": [],
            "unfulfilled_items": [],
            "overall_pass": True,
        })

        mock_llm = _make_llm(llm_response)
        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(_SAMPLE_CHAPTER, _FULL_BRIEF, chapter_number=1)

        assert result["pass_rate"] == 1.0


class TestTruncateLongChapter:
    """Long text gets truncated to 3000 chars."""

    def test_truncate_long_chapter(self):
        long_chapter = "这是一段很长的章节内容。" * 500  # ~3500 chars
        assert len(long_chapter) > 3000

        llm_response = json.dumps({
            "main_conflict_fulfilled": True,
            "payoff_delivered": True,
            "character_arc_step_taken": True,
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "end_hook_present": True,
            "item_results": [],
            "unfulfilled_items": [],
            "overall_pass": True,
        })

        mock_llm = _make_llm(llm_response)
        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(long_chapter, _FULL_BRIEF, chapter_number=1)

        # Verify LLM was called
        mock_llm.chat.assert_called_once()
        # Verify the chapter text in the prompt was truncated
        call_args = mock_llm.chat.call_args
        messages = call_args[0][0]
        user_content = messages[1]["content"]
        assert "已截取前 3000 字符" in user_content
        assert result["overall_pass"] is True

    def test_short_chapter_not_truncated(self):
        short_chapter = "短章节内容" * 10  # ~50 chars
        assert len(short_chapter) < 3000

        llm_response = json.dumps({
            "main_conflict_fulfilled": True,
            "item_results": [],
            "unfulfilled_items": [],
            "overall_pass": True,
        })

        mock_llm = _make_llm(llm_response)
        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(short_chapter, _FULL_BRIEF, chapter_number=1)

        call_args = mock_llm.chat.call_args
        messages = call_args[0][0]
        user_content = messages[1]["content"]
        assert "已截取前 3000 字符" not in user_content


class TestLLMErrorHandling:
    """Verify permissive default on LLM errors."""

    def test_llm_exception_returns_permissive_default(self):
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("LLM unavailable")

        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(_SAMPLE_CHAPTER, _FULL_BRIEF, chapter_number=5)

        assert result["overall_pass"] is True
        assert result["pass_rate"] == 1.0
        assert result["chapter_number"] == 5
        assert result["suggested_debts"] == []
        assert any("验证失败" in item for item in result["unfulfilled_items"])

    def test_llm_returns_garbage(self):
        mock_llm = _make_llm("This is not JSON at all, just random text")

        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(_SAMPLE_CHAPTER, _FULL_BRIEF, chapter_number=3)

        # Should still return a valid result (permissive defaults from empty parsed dict)
        assert result["chapter_number"] == 3
        assert isinstance(result["overall_pass"], bool)
        assert isinstance(result["pass_rate"], float)
        assert isinstance(result["item_results"], list)

    def test_llm_returns_partial_json(self):
        """LLM returns JSON missing some fields — should handle gracefully."""
        partial = json.dumps({
            "main_conflict_fulfilled": True,
            "overall_pass": True,
            # Missing all other fields
        })
        mock_llm = _make_llm(partial)

        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(_SAMPLE_CHAPTER, _FULL_BRIEF, chapter_number=1)

        assert result["overall_pass"] is True
        assert result["item_results"] == []
        assert result["suggested_debts"] == []


class TestFormatBrief:
    """Test the _format_brief helper."""

    def test_format_full_brief(self):
        validator = BriefValidator(MagicMock())
        lines = validator._format_brief(_FULL_BRIEF)

        assert len(lines) == 6
        assert any("主冲突" in line for line in lines)
        assert any("爽点" in line for line in lines)
        assert any("角色弧线" in line for line in lines)
        assert any("伏笔" in line for line in lines)
        assert any("钩子" in line for line in lines)

    def test_format_empty_brief(self):
        validator = BriefValidator(MagicMock())
        lines = validator._format_brief({})
        assert lines == []

    def test_format_string_foreshadowing(self):
        """Foreshadowing as a string (not list) should be handled."""
        validator = BriefValidator(MagicMock())
        brief = {"foreshadowing_plant": "单个伏笔"}
        lines = validator._format_brief(brief)
        assert len(lines) == 1
        assert "单个伏笔" in lines[0]


class TestDefaultChapterNumber:
    """chapter_number defaults to 1 when not provided."""

    def test_default_chapter_number(self):
        llm_response = json.dumps({
            "main_conflict_fulfilled": True,
            "item_results": [],
            "unfulfilled_items": [],
            "overall_pass": True,
        })
        mock_llm = _make_llm(llm_response)
        validator = BriefValidator(mock_llm)
        result = validator.validate_chapter(_SAMPLE_CHAPTER, _FULL_BRIEF)

        assert result["chapter_number"] == 1
