"""A/B 对比单元测试 (Phase 5 E3).

覆盖 ``src/novel/quality/ab_compare.py``:
- pairwise_judge happy path / tie 分支 / parse_error
- load_baseline 存在 / 不存在
- prompt 包含两段文本的定界符
- H4 fix: max_chars 参数透传给 sanitize
- H6 fix: MULTI_JUDGE_DIMENSIONS / SINGLE_JUDGE_DIMENSIONS / AB_DIMENSIONS 常量关系
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.quality.ab_compare import (
    _AB_DIMENSIONS,
    _normalize_verdict,
    load_baseline,
    pairwise_judge,
)
from src.novel.quality.judge import JudgeConfig, _CHAPTER_END, _CHAPTER_START
from src.novel.quality.report import ABComparisonResult

pytestmark = pytest.mark.quality


# ---------------------------------------------------------------------------
# _normalize_verdict
# ---------------------------------------------------------------------------


class TestNormalizeVerdict:
    @pytest.mark.parametrize("raw,expected", [
        ("a", "a"),
        ("A", "a"),
        ("b", "b"),
        ("B", "b"),
        ("tie", "tie"),
        ("TIE", "tie"),
        ("相同", "tie"),
        ("平手", "tie"),
        ("", "tie"),
        (None, "tie"),
        ("version_a", "a"),
        ("version_b", "b"),
        ("whatever", "tie"),
    ])
    def test_cases(self, raw, expected) -> None:
        assert _normalize_verdict(raw) == expected


# ---------------------------------------------------------------------------
# pairwise_judge
# ---------------------------------------------------------------------------


def _client_with_response(content: str, usage: int = 300) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = LLMResponse(
        content=content,
        model="gemini-2.5-flash",
        usage={"total_tokens": usage},
    )
    return client


class TestPairwiseJudge:
    def test_winner_a(self) -> None:
        payload = {
            "winner": "a",
            "reasoning": "A 版更紧凑",
            "dimension_preferences": {
                "narrative_flow": "a",
                "character_consistency": "a",
                "plot_advancement": "a",
                "dialogue_quality": "tie",
                "chapter_hook": "b",
            },
        }
        client = _client_with_response(json.dumps(payload), usage=300)
        with patch("src.novel.quality.ab_compare.create_llm_client", return_value=client):
            result = pairwise_judge(
                text_a="版本 A 文本",
                text_b="版本 B 文本",
                genre="玄幻",
                chapter_number=3,
                commit_a="aaa111",
                commit_b="bbb222",
                config=JudgeConfig(),
            )
        assert isinstance(result, ABComparisonResult)
        assert result.winner == "a"
        assert result.genre == "玄幻"
        assert result.chapter_number == 3
        assert result.commit_a == "aaa111"
        assert result.commit_b == "bbb222"
        assert result.judge_reasoning == "A 版更紧凑"
        assert result.judge_token_usage == 300
        # 所有 5 个维度都填了
        assert set(result.dimension_preferences.keys()) == set(_AB_DIMENSIONS)
        assert result.dimension_preferences["narrative_flow"] == "a"
        assert result.dimension_preferences["dialogue_quality"] == "tie"
        assert result.dimension_preferences["chapter_hook"] == "b"
        assert result.judge_model == "gemini-2.5-flash"

    def test_winner_tie(self) -> None:
        payload = {
            "winner": "tie",
            "reasoning": "质量接近",
            "dimension_preferences": {
                "narrative_flow": "tie",
                "character_consistency": "tie",
                "plot_advancement": "tie",
                "dialogue_quality": "tie",
                "chapter_hook": "tie",
            },
        }
        client = _client_with_response(json.dumps(payload))
        with patch("src.novel.quality.ab_compare.create_llm_client", return_value=client):
            result = pairwise_judge(
                text_a="a",
                text_b="b",
                genre="武侠",
                chapter_number=1,
                commit_a="x",
                commit_b="y",
                config=JudgeConfig(),
            )
        assert result.winner == "tie"
        assert all(v == "tie" for v in result.dimension_preferences.values())

    def test_winner_b(self) -> None:
        payload = {
            "winner": "b",
            "reasoning": "B 版对话更好",
            "dimension_preferences": {d: "b" for d in _AB_DIMENSIONS},
        }
        client = _client_with_response(json.dumps(payload))
        with patch("src.novel.quality.ab_compare.create_llm_client", return_value=client):
            result = pairwise_judge(
                text_a="a",
                text_b="b",
                genre="悬疑",
                chapter_number=2,
                commit_a="x",
                commit_b="y",
                config=JudgeConfig(),
            )
        assert result.winner == "b"
        assert all(v == "b" for v in result.dimension_preferences.values())

    def test_non_json_twice_returns_parse_error(self) -> None:
        client = MagicMock()
        client.chat.return_value = LLMResponse(
            content="not json at all",
            model="x",
            usage={"total_tokens": 50},
        )
        with patch("src.novel.quality.ab_compare.create_llm_client", return_value=client):
            result = pairwise_judge(
                text_a="a",
                text_b="b",
                genre="g",
                chapter_number=1,
                commit_a="x",
                commit_b="y",
                config=JudgeConfig(),
            )
        assert result.winner == "tie"
        assert "parse_error" in result.judge_reasoning
        # 两次尝试都调了 LLM
        assert client.chat.call_count == 2
        # token usage 累加两次
        assert result.judge_token_usage == 100
        # 所有维度都是 tie 兜底
        assert set(result.dimension_preferences.keys()) == set(_AB_DIMENSIONS)
        assert all(v == "tie" for v in result.dimension_preferences.values())

    def test_missing_dimension_preferences_defaults_to_tie(self) -> None:
        # 只给了 winner, 没给 dimension_preferences
        payload = {"winner": "a", "reasoning": "ok"}
        client = _client_with_response(json.dumps(payload))
        with patch("src.novel.quality.ab_compare.create_llm_client", return_value=client):
            result = pairwise_judge(
                text_a="a",
                text_b="b",
                genre="g",
                chapter_number=1,
                commit_a="x",
                commit_b="y",
                config=JudgeConfig(),
            )
        assert result.winner == "a"
        # 所有 5 个维度仍然存在, 都 tie
        assert len(result.dimension_preferences) == 5
        assert all(v == "tie" for v in result.dimension_preferences.values())

    def test_max_chars_param_propagates_to_sanitize(self) -> None:
        """H4 fix: ``max_chars`` 参数需透传给 ``_sanitize_chapter_text``。

        传入两段 8000 字文本 + ``max_chars=500`` → user prompt 中每段 <= 500 字
        + 截断提示。传 ``max_chars=8000`` → 不截断。
        """
        payload = {
            "winner": "tie",
            "reasoning": "",
            "dimension_preferences": {d: "tie" for d in _AB_DIMENSIONS},
        }
        big_a = "甲" * 8000
        big_b = "乙" * 8000

        # --- max_chars=500 ---
        client_small = _client_with_response(json.dumps(payload))
        with patch("src.novel.quality.ab_compare.create_llm_client", return_value=client_small):
            pairwise_judge(
                text_a=big_a,
                text_b=big_b,
                genre="g",
                chapter_number=1,
                commit_a="x",
                commit_b="y",
                config=JudgeConfig(),
                max_chars=500,
            )
        call_args = client_small.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        user_msg = next(m["content"] for m in messages if m["role"] == "user")
        # 两段均被截断
        assert user_msg.count("[...文本已被截断以控制成本...]") == 2
        # 每段 "甲"/"乙" 出现次数不超过 500
        assert user_msg.count("甲") <= 500
        assert user_msg.count("乙") <= 500

        # --- max_chars=8000 不截断 ---
        client_big = _client_with_response(json.dumps(payload))
        with patch("src.novel.quality.ab_compare.create_llm_client", return_value=client_big):
            pairwise_judge(
                text_a=big_a,
                text_b=big_b,
                genre="g",
                chapter_number=1,
                commit_a="x",
                commit_b="y",
                config=JudgeConfig(),
                max_chars=8000,
            )
        call_args = client_big.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        user_msg = next(m["content"] for m in messages if m["role"] == "user")
        # 不应出现截断提示
        assert "[...文本已被截断以控制成本...]" not in user_msg
        assert user_msg.count("甲") == 8000
        assert user_msg.count("乙") == 8000

    def test_default_max_chars_is_6000(self) -> None:
        """H4 fix: A/B 默认 max_chars=6000（比 single/multi 的 4000 宽松）。

        传入一段 5500 字文本（小于 6000）→ 不应被截断。
        """
        payload = {
            "winner": "tie",
            "reasoning": "",
            "dimension_preferences": {d: "tie" for d in _AB_DIMENSIONS},
        }
        text_5500 = "丙" * 5500
        client = _client_with_response(json.dumps(payload))
        with patch("src.novel.quality.ab_compare.create_llm_client", return_value=client):
            pairwise_judge(
                text_a=text_5500,
                text_b="短文本",
                genre="g",
                chapter_number=1,
                commit_a="x",
                commit_b="y",
                config=JudgeConfig(),
            )
        call_args = client.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        user_msg = next(m["content"] for m in messages if m["role"] == "user")
        # 5500 字未超默认 6000 → 全部保留
        assert user_msg.count("丙") == 5500
        # 5500 字场景无截断提示
        # （若默认仍是 4000 则会出现两次截断提示；6000 则零次）
        assert user_msg.count("[...文本已被截断以控制成本...]") == 0

    def test_prompt_contains_both_texts_in_delimiters(self) -> None:
        """验证两段文本都被 sanitize 包裹进 prompt."""
        payload = {
            "winner": "tie",
            "reasoning": "",
            "dimension_preferences": {d: "tie" for d in _AB_DIMENSIONS},
        }
        client = _client_with_response(json.dumps(payload))
        with patch("src.novel.quality.ab_compare.create_llm_client", return_value=client):
            pairwise_judge(
                text_a="AAA章节特征文字",
                text_b="BBB章节特征文字",
                genre="g",
                chapter_number=1,
                commit_a="x",
                commit_b="y",
                config=JudgeConfig(),
            )
        # 读取 user message
        call_args = client.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        user_msg = next(m["content"] for m in messages if m["role"] == "user")
        # 定界符出现两次（A/B 各一对）
        assert user_msg.count(_CHAPTER_START) == 2
        assert user_msg.count(_CHAPTER_END) == 2
        # 两段特征文字都在
        assert "AAA章节特征文字" in user_msg
        assert "BBB章节特征文字" in user_msg
        # 5 个维度 key 都出现
        for dim in _AB_DIMENSIONS:
            assert dim in user_msg


# ---------------------------------------------------------------------------
# load_baseline
# ---------------------------------------------------------------------------


class TestLoadBaseline:
    def test_loads_multiple_chapters(self, tmp_path: Path) -> None:
        root = tmp_path / "phase4" / "xuanhuan"
        root.mkdir(parents=True)
        (root / "chapter_001.txt").write_text("第一章内容", encoding="utf-8")
        (root / "chapter_002.txt").write_text("第二章内容", encoding="utf-8")
        (root / "chapter_003.txt").write_text("第三章内容", encoding="utf-8")
        out = load_baseline(str(tmp_path / "phase4"), "xuanhuan")
        assert set(out.keys()) == {1, 2, 3}
        assert out[1] == "第一章内容"
        assert out[2] == "第二章内容"
        assert out[3] == "第三章内容"

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        out = load_baseline(str(tmp_path / "nope"), "xuanhuan")
        assert out == {}

    def test_existing_dir_but_no_genre(self, tmp_path: Path) -> None:
        (tmp_path / "phase4").mkdir()
        out = load_baseline(str(tmp_path / "phase4"), "missing_genre")
        assert out == {}

    def test_empty_genre_dir(self, tmp_path: Path) -> None:
        root = tmp_path / "phase4" / "xuanhuan"
        root.mkdir(parents=True)
        out = load_baseline(str(tmp_path / "phase4"), "xuanhuan")
        assert out == {}

    def test_alternate_filename_chapter_1(self, tmp_path: Path) -> None:
        # 支持 chapter_1.txt 不带 0 padding
        root = tmp_path / "base" / "wuxia"
        root.mkdir(parents=True)
        (root / "chapter_1.txt").write_text("ch1", encoding="utf-8")
        (root / "chapter_15.txt").write_text("ch15", encoding="utf-8")
        out = load_baseline(str(tmp_path / "base"), "wuxia")
        assert out == {1: "ch1", 15: "ch15"}

    def test_ignores_non_chapter_files(self, tmp_path: Path) -> None:
        root = tmp_path / "base" / "g"
        root.mkdir(parents=True)
        (root / "chapter_001.txt").write_text("ok", encoding="utf-8")
        (root / "readme.md").write_text("ignore", encoding="utf-8")
        (root / "chapter.txt").write_text("no number", encoding="utf-8")
        out = load_baseline(str(tmp_path / "base"), "g")
        assert out == {1: "ok"}


# ---------------------------------------------------------------------------
# H6 fix: MULTI / SINGLE / AB 维度常量关系
# ---------------------------------------------------------------------------


class TestDimensionConstants:
    """H6 fix: A/B 5 项 vs multi judge 3 项命名歧义——锁定模块常量关系。"""

    def test_constants_exposed_from_module(self) -> None:
        """从 src.novel.quality 可直接导入 3 组常量。"""
        from src.novel.quality import (
            AB_DIMENSIONS,
            MULTI_JUDGE_DIMENSIONS,
            SINGLE_JUDGE_DIMENSIONS,
        )
        # 各自非空 + 是 tuple
        assert isinstance(MULTI_JUDGE_DIMENSIONS, tuple)
        assert isinstance(SINGLE_JUDGE_DIMENSIONS, tuple)
        assert isinstance(AB_DIMENSIONS, tuple)
        assert len(MULTI_JUDGE_DIMENSIONS) == 3
        assert len(SINGLE_JUDGE_DIMENSIONS) == 2
        assert len(AB_DIMENSIONS) == 5

    def test_multi_and_single_are_disjoint(self) -> None:
        """MULTI 与 SINGLE 不重叠。"""
        from src.novel.quality import MULTI_JUDGE_DIMENSIONS, SINGLE_JUDGE_DIMENSIONS
        assert set(MULTI_JUDGE_DIMENSIONS).isdisjoint(set(SINGLE_JUDGE_DIMENSIONS))

    def test_ab_equals_multi_union_single(self) -> None:
        """AB_DIMENSIONS == MULTI ∪ SINGLE（set 比较，不在意顺序）。"""
        from src.novel.quality import (
            AB_DIMENSIONS,
            MULTI_JUDGE_DIMENSIONS,
            SINGLE_JUDGE_DIMENSIONS,
        )
        assert set(AB_DIMENSIONS) == (
            set(MULTI_JUDGE_DIMENSIONS) | set(SINGLE_JUDGE_DIMENSIONS)
        )

    def test_expected_keys(self) -> None:
        """锁定每组具体成员，防未来无意改动。"""
        from src.novel.quality import (
            AB_DIMENSIONS,
            MULTI_JUDGE_DIMENSIONS,
            SINGLE_JUDGE_DIMENSIONS,
        )
        assert set(MULTI_JUDGE_DIMENSIONS) == {
            "character_consistency",
            "dialogue_quality",
            "chapter_hook",
        }
        assert set(SINGLE_JUDGE_DIMENSIONS) == {
            "narrative_flow",
            "plot_advancement",
        }
        assert set(AB_DIMENSIONS) == {
            "narrative_flow",
            "character_consistency",
            "plot_advancement",
            "dialogue_quality",
            "chapter_hook",
        }

    def test_ab_compare_uses_module_constant(self) -> None:
        """ab_compare._AB_DIMENSIONS 必须引用模块级 AB_DIMENSIONS（不再字符串硬编码）。"""
        from src.novel.quality import AB_DIMENSIONS as mod_ab
        from src.novel.quality.ab_compare import _AB_DIMENSIONS as local_ab
        assert local_ab == mod_ab
