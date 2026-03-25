"""Tests for BriefItemResult and BriefFulfillmentReport models"""

import pytest
from pydantic import ValidationError

from src.novel.models.validation import BriefFulfillmentReport, BriefItemResult


# ---------------------------------------------------------------------------
# BriefItemResult tests
# ---------------------------------------------------------------------------


class TestBriefItemResult:
    def test_brief_item_result_fulfilled(self):
        """Create fulfilled BriefItemResult."""
        item = BriefItemResult(
            item_name="main_conflict",
            expected="主角与反派首次正面冲突",
            fulfilled=True,
            evidence="第三段描写了主角与反派的对峙",
            reason="冲突场景完整呈现",
        )

        assert item.item_name == "main_conflict"
        assert item.expected == "主角与反派首次正面冲突"
        assert item.fulfilled is True
        assert item.evidence == "第三段描写了主角与反派的对峙"
        assert item.reason == "冲突场景完整呈现"

    def test_brief_item_result_unfulfilled(self):
        """Create unfulfilled BriefItemResult."""
        item = BriefItemResult(
            item_name="payoff",
            expected="伏笔回收",
            fulfilled=False,
            evidence=None,
            reason="章节中未找到相关伏笔回收",
        )

        assert item.fulfilled is False
        assert item.evidence is None

    def test_brief_item_result_minimal(self):
        """Create BriefItemResult with only required fields."""
        item = BriefItemResult(
            item_name="end_hook",
            expected="章末悬念",
            fulfilled=True,
        )

        assert item.evidence is None
        assert item.reason is None

    def test_brief_item_result_serialization(self):
        """JSON round-trip preserves all fields."""
        item = BriefItemResult(
            item_name="character_arc",
            expected="角色成长",
            fulfilled=False,
            evidence="未发现相关描写",
            reason="角色无明显变化",
        )

        json_str = item.model_dump_json()
        restored = BriefItemResult.model_validate_json(json_str)

        assert restored.item_name == "character_arc"
        assert restored.fulfilled is False
        assert restored.evidence == "未发现相关描写"
        assert restored.reason == "角色无明显变化"


# ---------------------------------------------------------------------------
# BriefFulfillmentReport tests
# ---------------------------------------------------------------------------


class TestBriefFulfillmentReport:
    def test_brief_fulfillment_report_all_pass(self):
        """Report with all items fulfilled."""
        items = [
            BriefItemResult(
                item_name="main_conflict", expected="冲突", fulfilled=True
            ),
            BriefItemResult(
                item_name="payoff", expected="回报", fulfilled=True
            ),
            BriefItemResult(
                item_name="end_hook", expected="悬念", fulfilled=True
            ),
        ]

        report = BriefFulfillmentReport(
            chapter_number=5,
            overall_pass=True,
            item_results=items,
        )

        assert report.chapter_number == 5
        assert report.overall_pass is True
        assert report.pass_rate == 1.0
        assert report.unfulfilled_items == []
        assert report.suggested_debts == []

    def test_brief_fulfillment_report_partial_pass(self):
        """Report with some items unfulfilled."""
        items = [
            BriefItemResult(
                item_name="main_conflict", expected="冲突", fulfilled=True
            ),
            BriefItemResult(
                item_name="payoff", expected="回报", fulfilled=False
            ),
            BriefItemResult(
                item_name="end_hook", expected="悬念", fulfilled=True
            ),
        ]

        report = BriefFulfillmentReport(
            chapter_number=5,
            overall_pass=False,
            item_results=items,
            unfulfilled_items=["payoff"],
            suggested_debts=["payoff should become a debt"],
        )

        assert report.overall_pass is False
        assert report.unfulfilled_items == ["payoff"]
        assert report.suggested_debts == ["payoff should become a debt"]

    def test_brief_fulfillment_report_pass_rate_auto_calculated(self):
        """pass_rate auto-computed from item_results when not explicitly set."""
        items = [
            BriefItemResult(
                item_name="a", expected="x", fulfilled=True
            ),
            BriefItemResult(
                item_name="b", expected="y", fulfilled=False
            ),
            BriefItemResult(
                item_name="c", expected="z", fulfilled=True
            ),
            BriefItemResult(
                item_name="d", expected="w", fulfilled=False
            ),
        ]

        report = BriefFulfillmentReport(
            chapter_number=3,
            overall_pass=False,
            item_results=items,
        )

        # 2 fulfilled out of 4 = 0.5
        assert report.pass_rate == pytest.approx(0.5)

    def test_brief_fulfillment_report_pass_rate_explicit_overrides(self):
        """Explicitly provided non-default pass_rate should be preserved."""
        items = [
            BriefItemResult(
                item_name="a", expected="x", fulfilled=True
            ),
            BriefItemResult(
                item_name="b", expected="y", fulfilled=False
            ),
        ]

        report = BriefFulfillmentReport(
            chapter_number=3,
            overall_pass=False,
            item_results=items,
            pass_rate=0.75,  # explicit override
        )

        # Explicit value preserved (not 1.0 so validator won't recompute)
        assert report.pass_rate == 0.75

    def test_brief_fulfillment_report_no_items_default_pass_rate(self):
        """Empty item_results keeps default pass_rate of 1.0."""
        report = BriefFulfillmentReport(
            chapter_number=1,
            overall_pass=True,
        )

        assert report.pass_rate == 1.0
        assert report.item_results == []

    def test_brief_fulfillment_report_all_false_pass_rate(self):
        """All items unfulfilled -> pass_rate = 0.0."""
        items = [
            BriefItemResult(
                item_name="a", expected="x", fulfilled=False
            ),
            BriefItemResult(
                item_name="b", expected="y", fulfilled=False
            ),
        ]

        report = BriefFulfillmentReport(
            chapter_number=1,
            overall_pass=False,
            item_results=items,
        )

        assert report.pass_rate == pytest.approx(0.0)

    def test_brief_fulfillment_report_defaults(self):
        """Verify all default values."""
        report = BriefFulfillmentReport(
            chapter_number=1,
            overall_pass=True,
        )

        assert report.main_conflict_fulfilled is True
        assert report.payoff_delivered is True
        assert report.character_arc_step_taken is True
        assert report.foreshadowing_planted == []
        assert report.foreshadowing_collected == []
        assert report.end_hook_present is True
        assert report.item_results == []
        assert report.unfulfilled_items == []
        assert report.suggested_debts == []

    def test_brief_fulfillment_report_foreshadowing_lists(self):
        """Foreshadowing planted/collected lists work correctly."""
        report = BriefFulfillmentReport(
            chapter_number=3,
            overall_pass=True,
            foreshadowing_planted=[True, False, True],
            foreshadowing_collected=[True],
        )

        assert report.foreshadowing_planted == [True, False, True]
        assert report.foreshadowing_collected == [True]

    def test_brief_fulfillment_report_chapter_number_must_be_positive(self):
        """chapter_number must be >= 1."""
        with pytest.raises(ValidationError):
            BriefFulfillmentReport(chapter_number=0, overall_pass=True)

    def test_brief_fulfillment_report_pass_rate_bounds(self):
        """pass_rate must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            BriefFulfillmentReport(
                chapter_number=1, overall_pass=True, pass_rate=-0.1
            )

        with pytest.raises(ValidationError):
            BriefFulfillmentReport(
                chapter_number=1, overall_pass=True, pass_rate=1.5
            )

    def test_brief_fulfillment_report_serialization_json_roundtrip(self):
        """JSON serialize/deserialize preserves all fields."""
        items = [
            BriefItemResult(
                item_name="main_conflict",
                expected="冲突",
                fulfilled=True,
                evidence="证据",
                reason="原因",
            ),
        ]
        report = BriefFulfillmentReport(
            chapter_number=5,
            main_conflict_fulfilled=True,
            payoff_delivered=False,
            character_arc_step_taken=True,
            foreshadowing_planted=[True],
            foreshadowing_collected=[False],
            end_hook_present=True,
            item_results=items,
            unfulfilled_items=["payoff"],
            overall_pass=False,
            pass_rate=0.8,
            suggested_debts=["补充payoff"],
        )

        json_str = report.model_dump_json()
        restored = BriefFulfillmentReport.model_validate_json(json_str)

        assert restored.chapter_number == 5
        assert restored.payoff_delivered is False
        assert restored.overall_pass is False
        assert restored.pass_rate == 0.8
        assert restored.unfulfilled_items == ["payoff"]
        assert restored.suggested_debts == ["补充payoff"]
        assert len(restored.item_results) == 1
        assert restored.item_results[0].item_name == "main_conflict"
        assert restored.item_results[0].evidence == "证据"

    def test_brief_fulfillment_report_serialization_dict_roundtrip(self):
        """Dict serialize/deserialize preserves all fields."""
        report = BriefFulfillmentReport(
            chapter_number=3,
            overall_pass=True,
            suggested_debts=["item1", "item2"],
        )

        dumped = report.model_dump()
        restored = BriefFulfillmentReport.model_validate(dumped)

        assert restored.chapter_number == 3
        assert restored.overall_pass is True
        assert restored.suggested_debts == ["item1", "item2"]
