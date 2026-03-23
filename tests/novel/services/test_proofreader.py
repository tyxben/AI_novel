"""Tests for src.novel.services.proofreader."""
import json
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from src.novel.models.refinement import ProofreadingIssue, ProofreadingIssueType
from src.novel.services.proofreader import Proofreader


@dataclass
class _LLMResponse:
    """Minimal LLMResponse stub."""
    content: str
    model: str = "test"
    usage: dict | None = None


def _make_llm(content: str) -> MagicMock:
    """Create a mock LLM client that returns *content*."""
    llm = MagicMock()
    llm.chat.return_value = _LLMResponse(content=content)
    return llm


class TestProofread:
    """Proofreader.proofread() tests."""

    def test_proofread_normal(self):
        """Normal case: LLM returns valid JSON array with matching issues."""
        source = "他走的很快，心里很高兴。"
        issues_json = json.dumps([
            {
                "issue_type": "typo",
                "original": "走的很快",
                "correction": "走得很快",
                "explanation": "的/得 用法错误",
            }
        ], ensure_ascii=False)

        llm = _make_llm(issues_json)
        proofreader = Proofreader(llm)
        result = proofreader.proofread(source)

        assert len(result) == 1
        assert result[0].issue_type == ProofreadingIssueType.TYPO
        assert result[0].original == "走的很快"
        assert result[0].correction == "走得很快"
        assert result[0].explanation == "的/得 用法错误"

        # Verify LLM was called with expected params
        llm.chat.assert_called_once()
        call_kwargs = llm.chat.call_args
        assert call_kwargs[1]["temperature"] == 0.3
        assert call_kwargs[1]["json_mode"] is True

    def test_proofread_empty_text(self):
        """Empty/whitespace text returns empty list without calling LLM."""
        llm = MagicMock()
        proofreader = Proofreader(llm)

        assert proofreader.proofread("") == []
        assert proofreader.proofread("   ") == []
        assert proofreader.proofread(None) == []
        llm.chat.assert_not_called()

    def test_proofread_llm_error(self):
        """LLM exception returns empty list."""
        llm = MagicMock()
        llm.chat.side_effect = RuntimeError("API timeout")
        proofreader = Proofreader(llm)

        result = proofreader.proofread("一段正常文本")
        assert result == []

    def test_proofread_invalid_json(self):
        """LLM returns non-JSON text."""
        llm = _make_llm("这段文本没有问题。")
        proofreader = Proofreader(llm)

        result = proofreader.proofread("一段正常文本")
        assert result == []

    def test_proofread_json_in_markdown(self):
        """LLM wraps JSON in markdown code block."""
        source = "他走的很快"
        raw = '一些前缀文本\n[{"issue_type":"typo","original":"走的很快","correction":"走得很快","explanation":"err"}]\n后缀'
        llm = _make_llm(raw)
        proofreader = Proofreader(llm)

        result = proofreader.proofread(source)
        assert len(result) == 1
        assert result[0].original == "走的很快"

    def test_proofread_filters_unmatched(self):
        """Issues whose 'original' is not in source text are filtered out."""
        source = "天空很蓝。"
        issues_json = json.dumps([
            {
                "issue_type": "typo",
                "original": "天空很兰",  # not in source
                "correction": "天空很蓝",
                "explanation": "错别字",
            },
            {
                "issue_type": "punctuation",
                "original": "很蓝。",
                "correction": "很蓝！",
                "explanation": "感叹号更合适",
            },
        ], ensure_ascii=False)

        llm = _make_llm(issues_json)
        proofreader = Proofreader(llm)
        result = proofreader.proofread(source)

        assert len(result) == 1
        assert result[0].original == "很蓝。"

    def test_proofread_same_original_correction(self):
        """Issues where original == correction are filtered out."""
        source = "一段文本"
        issues_json = json.dumps([
            {
                "issue_type": "grammar",
                "original": "一段文本",
                "correction": "一段文本",  # same
                "explanation": "no actual fix",
            }
        ], ensure_ascii=False)

        llm = _make_llm(issues_json)
        proofreader = Proofreader(llm)
        result = proofreader.proofread(source)

        assert result == []

    def test_proofread_invalid_issue_type_fallback(self):
        """Unknown issue_type falls back to 'grammar'."""
        source = "他走的很快"
        issues_json = json.dumps([
            {
                "issue_type": "unknown_type",
                "original": "走的很快",
                "correction": "走得很快",
                "explanation": "",
            }
        ], ensure_ascii=False)

        llm = _make_llm(issues_json)
        proofreader = Proofreader(llm)
        result = proofreader.proofread(source)

        assert len(result) == 1
        assert result[0].issue_type == ProofreadingIssueType.GRAMMAR

    def test_proofread_max_30_issues(self):
        """At most 30 issues returned."""
        source = "a" * 100
        items = [
            {
                "issue_type": "grammar",
                "original": "a",
                "correction": "b",
                "explanation": "",
            }
            for _ in range(50)
        ]
        llm = _make_llm(json.dumps(items))
        proofreader = Proofreader(llm)
        result = proofreader.proofread(source)

        assert len(result) <= 30

    def test_proofread_non_dict_items_skipped(self):
        """Non-dict entries in the array are skipped."""
        source = "测试文本"
        items = ["not a dict", 42, None]
        llm = _make_llm(json.dumps(items))
        proofreader = Proofreader(llm)
        result = proofreader.proofread(source)
        assert result == []

    def test_proofread_result_not_array(self):
        """LLM returns a JSON object instead of array."""
        source = "测试文本"
        llm = _make_llm(json.dumps({"issues": []}))
        proofreader = Proofreader(llm)
        result = proofreader.proofread(source)
        assert result == []

    def test_proofread_missing_fields_skipped(self):
        """Items missing original or correction are skipped."""
        source = "测试文本"
        items = [
            {"issue_type": "grammar", "correction": "fixed"},  # no original
            {"issue_type": "grammar", "original": "测试"},     # no correction
            {"issue_type": "grammar", "original": "", "correction": "x"},  # empty original
        ]
        llm = _make_llm(json.dumps(items, ensure_ascii=False))
        proofreader = Proofreader(llm)
        result = proofreader.proofread(source)
        assert result == []


class TestApplyFixes:
    """Proofreader.apply_fixes() static method tests."""

    def _issue(self, original: str, correction: str) -> ProofreadingIssue:
        return ProofreadingIssue(
            issue_type=ProofreadingIssueType.TYPO,
            original=original,
            correction=correction,
        )

    def test_apply_fixes_single(self):
        text = "他走的很快，跑的很慢。"
        issues = [self._issue("走的很快", "走得很快")]
        result, failures = Proofreader.apply_fixes(text, issues, [0])

        assert result == "他走得很快，跑的很慢。"
        assert failures == []

    def test_apply_fixes_multiple(self):
        """Multiple fixes applied correctly (back-to-front avoids offset issues)."""
        text = "他走的很快，跑的很慢。"
        issues = [
            self._issue("走的很快", "走得很快"),
            self._issue("跑的很慢", "跑得很慢"),
        ]
        result, failures = Proofreader.apply_fixes(text, issues, [0, 1])

        assert result == "他走得很快，跑得很慢。"
        assert failures == []

    def test_apply_fixes_partial_failure(self):
        """Some fixes match, others don't."""
        text = "天空很蓝。"
        issues = [
            self._issue("天空很蓝", "天空湛蓝"),
            self._issue("不存在的文本", "替换"),
        ]
        result, failures = Proofreader.apply_fixes(text, issues, [0, 1])

        assert result == "天空湛蓝。"
        assert len(failures) == 1
        assert "[1]" in failures[0]

    def test_apply_fixes_empty_selection(self):
        """Empty selection returns original text."""
        text = "原始文本"
        issues = [self._issue("原始", "新的")]
        result, failures = Proofreader.apply_fixes(text, issues, [])

        assert result == "原始文本"
        assert failures == []

    def test_apply_fixes_out_of_range_index(self):
        """Out-of-range indices are silently ignored."""
        text = "一段文本"
        issues = [self._issue("一段", "一些")]
        result, failures = Proofreader.apply_fixes(text, issues, [5, -2])

        assert result == "一段文本"
        assert failures == []

    def test_apply_fixes_adjacent_replacements(self):
        """Adjacent replacements of different lengths work correctly."""
        text = "AABB"
        issues = [
            self._issue("AA", "X"),
            self._issue("BB", "YYY"),
        ]
        result, failures = Proofreader.apply_fixes(text, issues, [0, 1])

        assert result == "XYYY"
        assert failures == []
