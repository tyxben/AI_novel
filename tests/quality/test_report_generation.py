"""Phase 5 / E2 — 质量评估数据结构单元测试。

覆盖 :class:`DimensionScore` / :class:`ChapterQualityReport` /
:class:`ABComparisonResult` 三个 dataclass 的 ``to_dict`` 序列化、
``avg_llm_score`` 聚合、``save_json`` 落盘往返。
"""

from __future__ import annotations

import json

import pytest

from src.novel.quality.report import (
    ABComparisonResult,
    ChapterQualityReport,
    DimensionScore,
)

pytestmark = pytest.mark.quality


# ---------------------------------------------------------------------------
# DimensionScore
# ---------------------------------------------------------------------------


class TestDimensionScore:
    def test_to_dict_contains_all_fields(self):
        """to_dict 返回五个字段均存在、值一致。"""
        ds = DimensionScore(
            key="narrative_flow",
            score=4.2,
            scale="1-5",
            method="llm_judge",
            details={"reasoning": "段落衔接自然"},
        )
        d = ds.to_dict()
        assert set(d.keys()) == {"key", "score", "scale", "method", "details"}
        assert d["key"] == "narrative_flow"
        assert d["score"] == 4.2
        assert d["scale"] == "1-5"
        assert d["method"] == "llm_judge"
        assert d["details"] == {"reasoning": "段落衔接自然"}

    def test_to_dict_defaults(self):
        """使用默认参数构造后 to_dict 字段合理。"""
        ds = DimensionScore(key="x", score=1.0)
        d = ds.to_dict()
        assert d["scale"] == "1-5"
        assert d["method"] == "llm_judge"
        assert d["details"] == {}

    def test_details_is_copied_not_shared(self):
        """to_dict 返回的 details 应与原始对象解耦，修改不影响原始对象。"""
        ds = DimensionScore(key="x", score=1.0, details={"a": 1})
        d = ds.to_dict()
        d["details"]["b"] = 2
        assert "b" not in ds.details


# ---------------------------------------------------------------------------
# ChapterQualityReport
# ---------------------------------------------------------------------------


class TestChapterQualityReport:
    def test_to_dict_contains_all_fields_and_nested_scores(self):
        """to_dict 八个顶层字段齐全，且 scores 嵌套 DimensionScore 正确序列化。"""
        report = ChapterQualityReport(
            chapter_number=7,
            genre="xuanhuan",
            commit_hash="abcd123",
            scores=[
                DimensionScore(key="narrative_flow", score=4.0, scale="1-5"),
                DimensionScore(
                    key="ai_flavor_index",
                    score=35,
                    scale="0-100",
                    method="rule",
                    details={"cliche_count": 2},
                ),
            ],
            overall_summary="整体尚可",
            generated_at="2026-04-21T10:00:00+00:00",
            judge_model="gemini-2.5-flash",
            judge_token_usage=1234,
        )
        d = report.to_dict()
        assert set(d.keys()) == {
            "chapter_number",
            "genre",
            "commit_hash",
            "scores",
            "overall_summary",
            "generated_at",
            "judge_model",
            "judge_token_usage",
        }
        assert d["chapter_number"] == 7
        assert d["genre"] == "xuanhuan"
        assert d["commit_hash"] == "abcd123"
        assert d["overall_summary"] == "整体尚可"
        assert d["generated_at"] == "2026-04-21T10:00:00+00:00"
        assert d["judge_model"] == "gemini-2.5-flash"
        assert d["judge_token_usage"] == 1234
        assert isinstance(d["scores"], list) and len(d["scores"]) == 2
        # 嵌套 DimensionScore 序列化
        assert d["scores"][0] == {
            "key": "narrative_flow",
            "score": 4.0,
            "scale": "1-5",
            "method": "llm_judge",
            "details": {},
        }
        assert d["scores"][1]["key"] == "ai_flavor_index"
        assert d["scores"][1]["details"] == {"cliche_count": 2}

    def test_avg_llm_score_only_counts_1_to_5_scale(self):
        """avg_llm_score 只算 scale=='1-5' 的维度。"""
        report = ChapterQualityReport(
            chapter_number=1,
            genre="xuanhuan",
            scores=[
                DimensionScore(key="narrative_flow", score=4.0, scale="1-5"),
                DimensionScore(key="plot_advancement", score=3.0, scale="1-5"),
                # 下面两条不应参与平均
                DimensionScore(key="foreshadow_payoff", score=80, scale="percent"),
                DimensionScore(
                    key="ai_flavor_index", score=40, scale="0-100", method="rule"
                ),
            ],
        )
        assert report.avg_llm_score() == 3.5

    def test_avg_llm_score_returns_zero_when_no_llm_dimensions(self):
        """没有 1-5 维度时返回 0.0（防除零）。"""
        report = ChapterQualityReport(
            chapter_number=1,
            genre="xuanhuan",
            scores=[
                DimensionScore(key="foreshadow_payoff", score=100, scale="percent"),
                DimensionScore(
                    key="ai_flavor_index", score=50, scale="0-100", method="rule"
                ),
            ],
        )
        assert report.avg_llm_score() == 0.0

    def test_avg_llm_score_empty_scores_returns_zero(self):
        """空 scores 列表也返回 0.0。"""
        report = ChapterQualityReport(chapter_number=1, genre="xuanhuan")
        assert report.avg_llm_score() == 0.0

    def test_save_json_round_trip(self, tmp_path):
        """save_json 落盘后能被 json.load 回来，数据不丢失。"""
        report = ChapterQualityReport(
            chapter_number=3,
            genre="suspense",
            commit_hash="deadbeef",
            scores=[
                DimensionScore(key="narrative_flow", score=3.5),
                DimensionScore(
                    key="foreshadow_payoff",
                    score=75.0,
                    scale="percent",
                    method="rule",
                    details={"collected": 3, "total": 4},
                ),
            ],
            overall_summary="留白合理",
        )
        target = tmp_path / "nested" / "report.json"
        report.save_json(str(target))

        assert target.exists()
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded["chapter_number"] == 3
        assert loaded["genre"] == "suspense"
        assert loaded["commit_hash"] == "deadbeef"
        assert loaded["overall_summary"] == "留白合理"
        assert len(loaded["scores"]) == 2
        assert loaded["scores"][1]["details"]["collected"] == 3

    def test_save_json_uses_utf8(self, tmp_path):
        """中文内容不应被 ascii-escape。"""
        report = ChapterQualityReport(
            chapter_number=1,
            genre="武侠",
            overall_summary="剑意纵横，山河失色。",
        )
        target = tmp_path / "r.json"
        report.save_json(str(target))
        raw = target.read_text(encoding="utf-8")
        assert "武侠" in raw
        assert "剑意纵横" in raw


# ---------------------------------------------------------------------------
# ABComparisonResult
# ---------------------------------------------------------------------------


class TestABComparisonResult:
    def test_to_dict_contains_all_fields(self):
        """to_dict 九个字段齐全，dimension_preferences 被 copy。"""
        prefs = {
            "narrative_flow": "b",
            "dialogue_quality": "tie",
            "plot_advancement": "a",
        }
        ab = ABComparisonResult(
            genre="wuxia",
            chapter_number=2,
            commit_a="abc123",
            commit_b="def456",
            winner="b",
            judge_reasoning="B 版本对话更自然",
            dimension_preferences=prefs,
            judge_model="gemini-2.5-flash",
            judge_token_usage=2048,
        )
        d = ab.to_dict()
        assert set(d.keys()) == {
            "genre",
            "chapter_number",
            "commit_a",
            "commit_b",
            "winner",
            "judge_reasoning",
            "dimension_preferences",
            "judge_model",
            "judge_token_usage",
        }
        assert d["genre"] == "wuxia"
        assert d["chapter_number"] == 2
        assert d["commit_a"] == "abc123"
        assert d["commit_b"] == "def456"
        assert d["winner"] == "b"
        assert d["judge_reasoning"] == "B 版本对话更自然"
        assert d["dimension_preferences"] == prefs
        assert d["judge_model"] == "gemini-2.5-flash"
        assert d["judge_token_usage"] == 2048

    def test_dimension_preferences_is_copied(self):
        """to_dict 返回的 dimension_preferences 应与原对象解耦。"""
        prefs = {"x": "a"}
        ab = ABComparisonResult(
            genre="g",
            chapter_number=1,
            commit_a="a",
            commit_b="b",
            winner="tie",
            judge_reasoning="",
            dimension_preferences=prefs,
        )
        d = ab.to_dict()
        d["dimension_preferences"]["y"] = "b"
        assert "y" not in ab.dimension_preferences

    def test_default_token_usage_zero(self):
        """judge_token_usage 默认 0，不传也不崩。"""
        ab = ABComparisonResult(
            genre="g",
            chapter_number=1,
            commit_a="a",
            commit_b="b",
            winner="tie",
            judge_reasoning="平手",
        )
        assert ab.judge_token_usage == 0
        assert ab.judge_model == ""
        assert ab.dimension_preferences == {}
