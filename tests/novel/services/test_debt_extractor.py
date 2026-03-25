"""Tests for DebtExtractor service.

LLM is mocked using ``MagicMock`` returning ``LLMResponse``.
Rule-based extraction tests use real Chinese text snippets.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.services.debt_extractor import DebtExtractor


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------


@pytest.fixture()
def extractor_no_llm() -> DebtExtractor:
    """Extractor with no LLM (rule-based only)."""
    return DebtExtractor(llm_client=None)


@pytest.fixture()
def mock_llm():
    """Create a mock LLM client."""
    llm = MagicMock()
    return llm


@pytest.fixture()
def extractor_with_llm(mock_llm) -> DebtExtractor:
    """Extractor with a mock LLM client."""
    return DebtExtractor(llm_client=mock_llm)


# ---------------------------------------------------------------
# Sample chapter texts
# ---------------------------------------------------------------

_TEXT_WITH_PROMISES = """
陈凡握紧拳头，目光坚定地看向远方。"我一定要找到那颗灵珠，替师父报仇！"
他心中暗暗发誓，必须在三天内赶到南山。
师妹拉住他的衣袖，"你答应过我，不会一个人去冒险的。"
"""

_TEXT_WITH_TENSION = """
这个洞穴的秘密究竟是什么？陈凡百思不得其解。
而他还不知道的是，一双冰冷的眼睛正从暗处注视着他的一举一动。
这背后的真相，远比他想象的更加可怕。
"""

_TEXT_WITH_ACTIONS = """
陈凡转身离开了酒楼，准备去找那位神秘的炼丹师。
师妹也起身前往东城门，赶往凤凰谷的路途遥远。
"""

_TEXT_WITH_EMOTIONS = """
看到师父倒下的那一刻，陈凡心中一痛，泪水夺眶而出。
这份仇恨如同烈火般灼烧着他的内心。
"""

_TEXT_MIXED = """
陈凡发誓一定要在三天内抵达南山，替师父报仇。
他心中的疑惑更深了——那个黑衣人究竟是谁？
他转身离开了村庄，准备去找药材救治伤员。
"""

_TEXT_NO_DEBTS = """
阳光洒在庭院中，花朵在微风中轻轻摇曳。
陈凡坐在石凳上，安静地喝着茶，享受着这难得的宁静时光。
远处传来鸟鸣声，一切都是那么平和。
"""


# ===================================================================
# Tests: Rule-based extraction
# ===================================================================


class TestExtractRuleBased:
    def test_extract_promises(self, extractor_no_llm):
        result = extractor_no_llm.extract_from_chapter(
            _TEXT_WITH_PROMISES, chapter_number=5, method="rule_based"
        )
        assert result["method"] == "rule_based"
        assert result["confidence"] == 0.6
        debts = result["debts"]
        assert len(debts) > 0
        # Should find at least one promise pattern
        descriptions = [d["description"] for d in debts]
        found_promise = any("一定要" in d or "必须" in d or "答应" in d for d in descriptions)
        assert found_promise, f"Expected promise pattern, got: {descriptions}"

    def test_extract_tension(self, extractor_no_llm):
        result = extractor_no_llm.extract_from_chapter(
            _TEXT_WITH_TENSION, chapter_number=3, method="rule_based"
        )
        debts = result["debts"]
        assert len(debts) > 0
        descriptions = [d["description"] for d in debts]
        found_tension = any("究竟" in d or "秘密" in d or "真相" in d for d in descriptions)
        assert found_tension, f"Expected tension pattern, got: {descriptions}"

    def test_extract_actions(self, extractor_no_llm):
        result = extractor_no_llm.extract_from_chapter(
            _TEXT_WITH_ACTIONS, chapter_number=7, method="rule_based"
        )
        debts = result["debts"]
        assert len(debts) > 0
        # Action debts should be must_pay_next with high urgency
        action_debts = [d for d in debts if d["type"] == "must_pay_next"]
        assert len(action_debts) > 0
        for ad in action_debts:
            assert ad["urgency_level"] == "high"

    def test_extract_emotions(self, extractor_no_llm):
        result = extractor_no_llm.extract_from_chapter(
            _TEXT_WITH_EMOTIONS, chapter_number=2, method="rule_based"
        )
        debts = result["debts"]
        assert len(debts) > 0
        emotional_debts = [d for d in debts if d.get("emotional_debt")]
        assert len(emotional_debts) > 0

    def test_no_debts_in_peaceful_text(self, extractor_no_llm):
        result = extractor_no_llm.extract_from_chapter(
            _TEXT_NO_DEBTS, chapter_number=1, method="rule_based"
        )
        debts = result["debts"]
        assert len(debts) == 0

    def test_mixed_text_multiple_types(self, extractor_no_llm):
        result = extractor_no_llm.extract_from_chapter(
            _TEXT_MIXED, chapter_number=4, method="rule_based"
        )
        debts = result["debts"]
        assert len(debts) >= 2  # At least promises + actions
        types = {d["type"] for d in debts}
        assert len(types) >= 2, f"Expected multiple debt types, got: {types}"

    def test_debt_id_format(self, extractor_no_llm):
        result = extractor_no_llm.extract_from_chapter(
            _TEXT_WITH_PROMISES, chapter_number=5, method="rule_based"
        )
        for debt in result["debts"]:
            assert debt["debt_id"].startswith("debt_5_")
            assert debt["source_chapter"] == 5

    def test_empty_text(self, extractor_no_llm):
        result = extractor_no_llm.extract_from_chapter(
            "", chapter_number=1, method="rule_based"
        )
        assert len(result["debts"]) == 0


# ===================================================================
# Tests: LLM-based extraction
# ===================================================================


class TestExtractLLM:
    def test_llm_extraction_parses_json(self, extractor_with_llm, mock_llm):
        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps({
                "debts": [
                    {
                        "type": "must_pay_next",
                        "description": "主角需要赶到南山",
                        "character_pending_actions": ["赶到南山"],
                        "emotional_debt": None,
                        "target_chapter": None,
                        "urgency_level": "high",
                    },
                    {
                        "type": "long_tail_payoff",
                        "description": "黑衣人的身份之谜",
                        "character_pending_actions": [],
                        "emotional_debt": "对师父的愧疚",
                        "target_chapter": None,
                        "urgency_level": "normal",
                    },
                ]
            }),
            model="test",
            usage=None,
        )

        result = extractor_with_llm.extract_from_chapter(
            _TEXT_MIXED, chapter_number=4, method="llm"
        )
        assert result["method"] == "llm"
        assert result["confidence"] == 0.9
        debts = result["debts"]
        assert len(debts) == 2
        assert debts[0]["type"] == "must_pay_next"
        assert debts[0]["description"] == "主角需要赶到南山"
        assert debts[1]["emotional_debt"] == "对师父的愧疚"

    def test_llm_fallback_on_error(self, extractor_with_llm, mock_llm):
        mock_llm.chat.side_effect = Exception("API 超时")

        result = extractor_with_llm.extract_from_chapter(
            _TEXT_MIXED, chapter_number=4, method="llm"
        )
        # Should return empty debts but not crash
        assert result["method"] == "llm"
        assert result["confidence"] == 0.0
        assert len(result["debts"]) == 0

    def test_llm_called_with_correct_params(self, extractor_with_llm, mock_llm):
        mock_llm.chat.return_value = LLMResponse(
            content='{"debts": []}',
            model="test",
            usage=None,
        )

        extractor_with_llm.extract_from_chapter(
            _TEXT_MIXED, chapter_number=4, method="llm"
        )

        mock_llm.chat.assert_called_once()
        call_args = mock_llm.chat.call_args
        assert call_args[1]["temperature"] == 0.3
        assert call_args[1]["json_mode"] is True
        assert call_args[1]["max_tokens"] == 2048

    def test_llm_truncates_long_text(self, extractor_with_llm, mock_llm):
        mock_llm.chat.return_value = LLMResponse(
            content='{"debts": []}',
            model="test",
            usage=None,
        )
        long_text = "这是一段很长的文字。" * 1000  # ~10000 chars

        extractor_with_llm.extract_from_chapter(
            long_text, chapter_number=1, method="llm"
        )

        call_args = mock_llm.chat.call_args
        messages = call_args[0][0]
        user_msg = messages[1]["content"]
        # Should contain truncation notice
        assert "已截取前 3000 字符" in user_msg

    def test_llm_not_available_falls_back(self, extractor_no_llm):
        result = extractor_no_llm.extract_from_chapter(
            _TEXT_WITH_PROMISES, chapter_number=5, method="llm"
        )
        # Falls back to rule_based
        assert result["method"] == "rule_based"

    def test_llm_invalid_type_normalized(self, extractor_with_llm, mock_llm):
        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps({
                "debts": [{
                    "type": "invalid_type",
                    "description": "某个债务",
                    "urgency_level": "unknown",
                }]
            }),
            model="test",
            usage=None,
        )

        result = extractor_with_llm.extract_from_chapter(
            _TEXT_MIXED, chapter_number=1, method="llm"
        )
        debts = result["debts"]
        assert len(debts) == 1
        assert debts[0]["type"] == "pay_within_3"  # normalized
        assert debts[0]["urgency_level"] == "normal"  # normalized

    def test_llm_empty_debts_response(self, extractor_with_llm, mock_llm):
        mock_llm.chat.return_value = LLMResponse(
            content='{"debts": []}',
            model="test",
            usage=None,
        )

        result = extractor_with_llm.extract_from_chapter(
            _TEXT_NO_DEBTS, chapter_number=1, method="llm"
        )
        assert len(result["debts"]) == 0
        assert result["confidence"] == 0.0  # no debts -> 0 confidence

    def test_llm_markdown_code_block_response(
        self, extractor_with_llm, mock_llm
    ):
        mock_llm.chat.return_value = LLMResponse(
            content='```json\n{"debts": [{"type": "must_pay_next", "description": "测试"}]}\n```',
            model="test",
            usage=None,
        )

        result = extractor_with_llm.extract_from_chapter(
            _TEXT_MIXED, chapter_number=1, method="llm"
        )
        assert len(result["debts"]) == 1


# ===================================================================
# Tests: Hybrid extraction
# ===================================================================


class TestExtractHybrid:
    def test_hybrid_combines_results(self, extractor_with_llm, mock_llm):
        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps({
                "debts": [{
                    "type": "long_tail_payoff",
                    "description": "LLM发现的暗线伏笔",
                    "urgency_level": "normal",
                }]
            }),
            model="test",
            usage=None,
        )

        result = extractor_with_llm.extract_from_chapter(
            _TEXT_MIXED, chapter_number=4, method="hybrid"
        )
        assert result["method"] == "hybrid"
        assert result["confidence"] == 0.85
        # Should have LLM debt + some rule-based debts
        debts = result["debts"]
        assert len(debts) >= 2
        descriptions = [d["description"] for d in debts]
        assert any("LLM发现" in d for d in descriptions)

    def test_hybrid_without_llm_falls_back(self, extractor_no_llm):
        result = extractor_no_llm.extract_from_chapter(
            _TEXT_MIXED, chapter_number=4, method="hybrid"
        )
        # Falls back to rule_based only
        assert result["method"] == "rule_based"
        assert result["confidence"] == 0.6

    def test_hybrid_deduplicates(self, extractor_with_llm, mock_llm):
        # LLM returns a debt similar to what rule-based would find
        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps({
                "debts": [{
                    "type": "pay_within_3",
                    "description": "发誓一定要在三天内抵达南山",
                    "urgency_level": "normal",
                }]
            }),
            model="test",
            usage=None,
        )

        result = extractor_with_llm.extract_from_chapter(
            _TEXT_MIXED, chapter_number=4, method="hybrid"
        )
        # Should not have duplicates of the same promise
        debts = result["debts"]
        descriptions = [d["description"] for d in debts]
        # Check no exact duplicates
        assert len(descriptions) == len(set(descriptions))


# ===================================================================
# Tests: Deduplication and similarity
# ===================================================================


class TestDeduplication:
    def test_is_similar_same_type_overlapping_desc(self):
        d1 = {
            "type": "must_pay_next",
            "description": "主角前往南山寻找灵珠",
        }
        d2 = {
            "type": "must_pay_next",
            "description": "主角前往南山寻找灵珠报仇",
        }
        assert DebtExtractor._is_similar(d1, d2) is True

    def test_is_similar_different_types(self):
        d1 = {
            "type": "must_pay_next",
            "description": "主角前往南山",
        }
        d2 = {
            "type": "long_tail_payoff",
            "description": "主角前往南山",
        }
        assert DebtExtractor._is_similar(d1, d2) is False

    def test_is_similar_completely_different(self):
        d1 = {
            "type": "must_pay_next",
            "description": "赶到南山",
        }
        d2 = {
            "type": "must_pay_next",
            "description": "黑衣人身份之谜",
        }
        assert DebtExtractor._is_similar(d1, d2) is False

    def test_is_similar_empty_description(self):
        d1 = {"type": "must_pay_next", "description": ""}
        d2 = {"type": "must_pay_next", "description": "有内容"}
        assert DebtExtractor._is_similar(d1, d2) is False

    def test_deduplicate_removes_duplicates(self):
        debts = [
            {
                "debt_id": "d1",
                "type": "must_pay_next",
                "description": "主角前往南山寻找灵珠",
            },
            {
                "debt_id": "d2",
                "type": "must_pay_next",
                "description": "主角前往南山寻找灵珠报仇",
            },
            {
                "debt_id": "d3",
                "type": "long_tail_payoff",
                "description": "完全不同的债务内容描述",
            },
        ]
        result = DebtExtractor._deduplicate_debts(debts)
        assert len(result) == 2
        ids = [d["debt_id"] for d in result]
        assert "d1" in ids  # first one kept
        assert "d3" in ids  # different type, kept

    def test_deduplicate_no_duplicates(self):
        debts = [
            {"debt_id": "d1", "type": "must_pay_next", "description": "债务A的具体描述"},
            {"debt_id": "d2", "type": "pay_within_3", "description": "债务B的具体描述"},
            {"debt_id": "d3", "type": "long_tail_payoff", "description": "债务C的具体描述"},
        ]
        result = DebtExtractor._deduplicate_debts(debts)
        assert len(result) == 3

    def test_deduplicate_empty_list(self):
        result = DebtExtractor._deduplicate_debts([])
        assert result == []
