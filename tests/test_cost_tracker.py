"""CostTracker 单元测试。"""
from __future__ import annotations

import json
import logging

import pytest

from src.agents.cost_tracker import CostTracker


# ---------------------------------------------------------------------------
# 基本功能
# ---------------------------------------------------------------------------

class TestCostTrackerBasic:
    def test_empty_tracker_returns_zero(self):
        tracker = CostTracker()
        assert tracker.total_cost() == 0.0
        assert tracker.get_breakdown() == {}
        assert tracker.get_summary()["total_cost"] == 0.0

    def test_add_token_call_and_total(self):
        tracker = CostTracker()
        # gpt-4o: input $2.50/1M, output $10.00/1M
        tracker.add_call("gpt-4o", input_tokens=1000, output_tokens=500)
        expected = (1000 * 2.50 + 500 * 10.00) / 1_000_000
        assert tracker.total_cost() == pytest.approx(expected)

    def test_add_per_call_model(self):
        tracker = CostTracker()
        tracker.add_call("together-flux", count=3)
        assert tracker.total_cost() == pytest.approx(0.003 * 3)

    def test_free_models_zero_cost(self):
        tracker = CostTracker()
        tracker.add_call("gemini-2.0-flash", input_tokens=10000, output_tokens=5000)
        tracker.add_call("edge-tts", count=10)
        assert tracker.total_cost() == 0.0


# ---------------------------------------------------------------------------
# 分模型汇总
# ---------------------------------------------------------------------------

class TestBreakdown:
    def test_breakdown_by_model(self):
        tracker = CostTracker()
        tracker.add_call("gpt-4o-mini", input_tokens=2000, output_tokens=1000)
        tracker.add_call("deepseek-chat", input_tokens=5000, output_tokens=3000)
        breakdown = tracker.get_breakdown()
        assert "gpt-4o-mini" in breakdown
        assert "deepseek-chat" in breakdown
        assert len(breakdown) == 2

    def test_multiple_calls_accumulate(self):
        tracker = CostTracker()
        tracker.add_call("gpt-4o", input_tokens=1000, output_tokens=0)
        tracker.add_call("gpt-4o", input_tokens=1000, output_tokens=0)
        expected = 2 * (1000 * 2.50) / 1_000_000
        assert tracker.get_breakdown()["gpt-4o"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 未知模型
# ---------------------------------------------------------------------------

class TestUnknownModel:
    def test_unknown_model_zero_cost_with_warning(self, caplog):
        tracker = CostTracker()
        with caplog.at_level(logging.WARNING):
            tracker.add_call("some-unknown-model", input_tokens=9999, output_tokens=9999)
        assert tracker.total_cost() == 0.0
        assert "未知模型" in caplog.text


# ---------------------------------------------------------------------------
# 边界条件
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_tokens(self):
        tracker = CostTracker()
        tracker.add_call("gpt-4o", input_tokens=0, output_tokens=0)
        assert tracker.total_cost() == 0.0

    def test_negative_tokens_treated_as_zero(self):
        tracker = CostTracker()
        tracker.add_call("gpt-4o", input_tokens=-100, output_tokens=-50)
        assert tracker.total_cost() == 0.0

    def test_negative_count_treated_as_zero(self):
        tracker = CostTracker()
        tracker.add_call("together-flux", count=-5)
        assert tracker.total_cost() == 0.0

    def test_gpt4_vision_same_as_gpt4o(self):
        tracker = CostTracker()
        tracker.add_call("gpt-4-vision", input_tokens=1000, output_tokens=500)
        expected = (1000 * 2.50 + 500 * 10.00) / 1_000_000
        assert tracker.total_cost() == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_dict_is_json_serializable(self):
        tracker = CostTracker()
        tracker.add_call("gpt-4o", input_tokens=100, output_tokens=50)
        tracker.add_call("together-flux", count=2)
        d = tracker.to_dict()
        # 应可正常序列化
        serialized = json.dumps(d)
        loaded = json.loads(serialized)
        assert loaded["total_cost"] == pytest.approx(d["total_cost"])
        assert len(loaded["records"]) == 2

    def test_to_dict_structure(self):
        tracker = CostTracker()
        tracker.add_call("deepseek-chat", input_tokens=500, output_tokens=200)
        d = tracker.to_dict()
        assert "total_cost" in d
        assert "breakdown" in d
        assert "records" in d
        assert d["records"][0]["model"] == "deepseek-chat"


# ---------------------------------------------------------------------------
# get_summary
# ---------------------------------------------------------------------------

class TestGetSummary:
    def test_summary_includes_call_counts(self):
        tracker = CostTracker()
        tracker.add_call("gpt-4o", input_tokens=100, output_tokens=50, count=1)
        tracker.add_call("gpt-4o", input_tokens=200, output_tokens=100, count=1)
        tracker.add_call("together-flux", count=5)
        summary = tracker.get_summary()
        assert summary["call_counts"]["gpt-4o"] == 2
        assert summary["call_counts"]["together-flux"] == 5
        assert "total_cost" in summary
        assert "breakdown" in summary
