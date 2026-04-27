"""Reviewer 跨章 verbatim 兜底维度（C 阶段 P2）。

P0 (commit ffffda2) + C3 (commit 15095b3) 物理切断 Writer 直读上章原文的所有
路径。本兜底网在 Reviewer 内做 char-5gram Jaccard 对比，>=0.6 报 high severity
issue。万一未来新加的 pipeline 入口忘走 summarizer，本规则立刻报警。

覆盖：
* 模块级 helper：_char_ngrams / _ngram_jaccard 边界
* Reviewer._check_cross_chapter_verbatim 阈值边界 / 空输入
* Reviewer.review() 集成：高 Jaccard → issues 出现一条 type=cross_chapter_verbatim
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.reviewer import (
    Reviewer,
    _char_ngrams,
    _CROSS_CHAPTER_JACCARD_THRESHOLD,
    _CROSS_CHAPTER_NGRAM,
    _ngram_jaccard,
)
from src.novel.models.critique_result import CritiqueIssue


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


class TestCharNgrams:
    def test_empty_input(self) -> None:
        assert _char_ngrams("") == set()

    def test_short_input_below_n(self) -> None:
        # 短于 n 字 → 空 set
        assert _char_ngrams("abc", n=5) == set()

    def test_normalizes_whitespace(self) -> None:
        # 空白被压扁，"a b c d e" 等价 "abcde"
        assert _char_ngrams("a b c d e", n=5) == {"abcde"}

    def test_chinese_5gram(self) -> None:
        text = "他走进了房间"  # 6 字 → 2 个 5-gram
        ngrams = _char_ngrams(text, n=5)
        assert "他走进了房" in ngrams
        assert "走进了房间" in ngrams
        assert len(ngrams) == 2

    def test_n_param_default(self) -> None:
        assert _CROSS_CHAPTER_NGRAM == 5
        # 默认 n=5
        ngrams = _char_ngrams("一二三四五六")
        assert all(len(g) == 5 for g in ngrams)


class TestNgramJaccard:
    def test_identical_text_score_1(self) -> None:
        a = "同样的文字内容做出来比较"
        assert _ngram_jaccard(a, a) == 1.0

    def test_no_overlap_score_0(self) -> None:
        # 完全不同字符
        assert _ngram_jaccard("abcdefghijk", "12345678901") == 0.0

    def test_partial_overlap(self) -> None:
        a = "他走进了昏暗的房间她坐在窗边的桌子前"
        b = "他走进了昏暗的房间然后转身走开了"
        score = _ngram_jaccard(a, b)
        # 共同前缀产生明显 overlap
        assert 0.0 < score < 1.0

    def test_either_empty_returns_0(self) -> None:
        assert _ngram_jaccard("", "abcdefghij") == 0.0
        assert _ngram_jaccard("abcdefghij", "") == 0.0
        assert _ngram_jaccard("", "") == 0.0

    def test_below_n_returns_0(self) -> None:
        # 任一边 < n 字 → 0
        assert _ngram_jaccard("abc", "abcdefghij", n=5) == 0.0


# ---------------------------------------------------------------------------
# Reviewer._check_cross_chapter_verbatim
# ---------------------------------------------------------------------------


class TestCheckCrossChapterVerbatim:
    def test_returns_none_for_empty_inputs(self) -> None:
        assert Reviewer._check_cross_chapter_verbatim("", "前章末段。") is None
        assert Reviewer._check_cross_chapter_verbatim("当前章节。", "") is None
        assert Reviewer._check_cross_chapter_verbatim("", "") is None

    def test_returns_none_below_threshold(self) -> None:
        chapter = (
            "他踏入了从未涉足过的境地。空气里弥漫着不属于人间的气息。"
            "脚下的石板被某种古老的符文刻满，每一步都像是踩在历史里。"
        )
        prev_tail = (
            "苏醒过来。她缓缓睁开眼，发现自己躺在一片陌生的床榻上。"
        )
        result = Reviewer._check_cross_chapter_verbatim(chapter, prev_tail)
        assert result is None

    def test_returns_high_issue_when_verbatim(self) -> None:
        """当前章直接抄了上一章末段（典型 P0 失守 case）→ high issue。"""
        prev_tail = (
            "他缓缓睁开眼睛，发现自己躺在一座荒废的古庙里。"
            "庙顶的瓦片掉了大半，月光从破洞中倾泻进来。"
            "他下意识摸向腰间，却发现佩剑已然不见。"
        )
        # 当前章节 80% 复用上章末段 + 加几句新词
        chapter = (
            prev_tail
            + "他猛地坐起，咳嗽声划破了寂静。远处传来狼嚎。"
        )

        result = Reviewer._check_cross_chapter_verbatim(chapter, prev_tail)
        assert result is not None
        assert isinstance(result, CritiqueIssue)
        assert result.type == "cross_chapter_verbatim"
        assert result.severity == "high"
        assert "Jaccard" in result.reason
        assert "summarize_previous_tail" in result.reason  # 提示排查方向

    def test_threshold_param_override(self) -> None:
        """阈值参数可调，便于回归测试不同 case。"""
        a = "abcdefghijabcdefghij"  # 10 个 5-gram (有重复)
        b = "abcdefghij"  # 6 个 5-gram
        # 实际相似度
        score = _ngram_jaccard(a, b)
        # 阈值高于实际值 → None
        result = Reviewer._check_cross_chapter_verbatim(
            a, b, threshold=score + 0.1
        )
        assert result is None
        # 阈值低于实际值 → issue
        result = Reviewer._check_cross_chapter_verbatim(
            a, b, threshold=max(0.0, score - 0.1)
        )
        assert result is not None

    def test_default_threshold_is_06(self) -> None:
        assert _CROSS_CHAPTER_JACCARD_THRESHOLD == 0.6


# ---------------------------------------------------------------------------
# Reviewer.review() integration
# ---------------------------------------------------------------------------


def _llm_returns(payload: str) -> MagicMock:
    """Mock LLM that returns a clean critique JSON."""
    client = MagicMock()
    client.chat.return_value = LLMResponse(content=payload, model="m")
    return client


_CLEAN_CRITIQUE_JSON = (
    '{"strengths": ["节奏紧凑"], '
    '"issues": [], '
    '"specific_revisions": [], '
    '"overall_assessment": "整体过关。"}'
)


class TestReviewerReviewIntegration:
    def test_no_issue_when_unrelated_prev_tail(self) -> None:
        chapter = "他踏入了从未涉足过的境地。空气里弥漫着古老气息。" * 10
        prev_tail = "苏醒过来。她睁开眼，看见陌生的天花板。" * 5
        reviewer = Reviewer(_llm_returns(_CLEAN_CRITIQUE_JSON))
        result = reviewer.review(chapter, previous_tail=prev_tail)
        types = {i.type for i in result.issues}
        assert "cross_chapter_verbatim" not in types

    def test_issue_added_when_verbatim_overlap(self) -> None:
        prev_tail = (
            "他缓缓睁开眼睛，发现自己躺在一座荒废的古庙里。"
            "庙顶的瓦片掉了大半，月光从破洞中倾泻进来。"
            "他下意识摸向腰间，却发现佩剑已然不见。"
        )
        chapter = prev_tail + "他猛地坐起，咳嗽声划破了寂静。远处传来狼嚎。"
        reviewer = Reviewer(_llm_returns(_CLEAN_CRITIQUE_JSON))

        result = reviewer.review(chapter, previous_tail=prev_tail)

        cross_issues = [
            i for i in result.issues if i.type == "cross_chapter_verbatim"
        ]
        assert len(cross_issues) == 1
        issue = cross_issues[0]
        assert issue.severity == "high"
        assert "Jaccard" in issue.reason

    def test_no_issue_when_prev_tail_empty(self) -> None:
        """首章场景：previous_tail 为空 → 不报 cross-chapter issue。"""
        chapter = "第一章正文。" * 50
        reviewer = Reviewer(_llm_returns(_CLEAN_CRITIQUE_JSON))
        result = reviewer.review(chapter, previous_tail="")
        types = {i.type for i in result.issues}
        assert "cross_chapter_verbatim" not in types

    def test_need_rewrite_set_by_high_severity_cross_chapter(self) -> None:
        """跨章 verbatim 是 high → CritiqueResult.need_rewrite=True。"""
        prev_tail = (
            "他缓缓睁开眼睛，发现自己躺在一座荒废的古庙里。"
            "庙顶的瓦片掉了大半，月光从破洞中倾泻进来。"
        )
        chapter = prev_tail + "他猛地坐起。"
        reviewer = Reviewer(_llm_returns(_CLEAN_CRITIQUE_JSON))
        result = reviewer.review(chapter, previous_tail=prev_tail)
        # high_severity_count >= 1 → need_rewrite True
        assert result.high_severity_count >= 1
        assert result.need_rewrite is True


# ---------------------------------------------------------------------------
# P0 ch32 复读事故案例的回归断言（review L1）
# ---------------------------------------------------------------------------


class TestP0Ch32CaseRegression:
    """把 reviewer.py:117 注释里"5-gram Jaccard ≈ 0.85+"从推测变回归。

    P0 (commit ffffda2) 修复前 ch32 直接复读 ch31 末段 6000 字。本测试
    重现该 case 的简化版：当前章节末段含上章末段约 80% verbatim → Jaccard
    应明显高于 0.6 阈值，确保兜底网能 catch 它。
    """

    def test_full_overlap_jaccard_above_threshold(self) -> None:
        """80% verbatim 复读 → Jaccard 远超 0.6 阈值。

        实测当前 case score≈0.84；reviewer.py:117 注释里"≈0.85+"是不同
        长度组合的估计上限。本测试锁的是"远超阈值"这个语义而不是具体数字，
        阈值 0.80 给抗噪空间但仍说明兜底网能稳定 catch 这类事故。
        """
        prev_tail = (
            "他缓缓睁开眼睛，发现自己躺在一座荒废的古庙里。"
            "庙顶的瓦片掉了大半，月光从破洞中倾泻进来。"
            "他下意识摸向腰间，却发现佩剑已然不见。"
            "远处隐约传来狼嚎，让他不寒而栗。"
        )
        # 当前章 80% 复读 + 加 20% 新词
        chapter = prev_tail + "他咬牙挣扎起身，向庙门走去。"

        score = _ngram_jaccard(chapter, prev_tail)
        assert score >= 0.80, (
            f"P0 ch32 case 回归：5-gram Jaccard={score:.3f}，"
            f"应 >= 0.80 （远超 0.6 阈值，确保兜底网稳定 catch）"
        )

    def test_natural_continuation_jaccard_well_below_threshold(self) -> None:
        """正常承接（轻量回顾 + 新内容）→ Jaccard 远低于 0.6。"""
        prev_tail = (
            "他缓缓睁开眼睛，发现自己躺在一座荒废的古庙里。"
            "庙顶的瓦片掉了大半，月光从破洞中倾泻进来。"
        )
        chapter = (
            "天蒙蒙亮，他终于撑着站了起来。古庙外是一片杂草丛生的荒野，"
            "几只乌鸦栖在枯枝上叫得凄厉。他摸了摸空荡荡的腰间，"
            "苦笑一声，朝着山路走去。"
        )
        score = _ngram_jaccard(chapter, prev_tail)
        # 自然承接重叠应远低于阈值（即使有"古庙"等共现词）
        assert score < 0.3, (
            f"自然承接误判：5-gram Jaccard={score:.3f}，应 < 0.3 远低 0.6 阈值"
        )


# ---------------------------------------------------------------------------
# reviewer_node 端到端集成（review M2）
# ---------------------------------------------------------------------------


class TestReviewerNodeEndToEnd:
    """reviewer_node 是生产路径，state["chapters"][-1].full_text → prev_tail。

    review M2 抓的盲区：单测只走 Reviewer.review() 直调，未覆盖 reviewer_node
    把 state 拉成 prev_tail 再喂的拼装环节。如果以后有人改 state 字段名
    （如 chapters → chapters_done），单测全绿但生产兜底失效。
    """

    def test_reviewer_node_attaches_cross_chapter_issue(self) -> None:
        from unittest.mock import patch

        from src.novel.agents.reviewer import reviewer_node

        # 上一章 full_text 末 500 字将作为 prev_tail
        prev_full_text = "前情铺垫开头若干字。" * 20 + (
            "他缓缓睁开眼睛，发现自己躺在一座荒废的古庙里。"
            "庙顶的瓦片掉了大半，月光从破洞中倾泻进来。"
            "他下意识摸向腰间，却发现佩剑已然不见。"
        )
        # 当前章 verbatim 复读上章末段
        current_chapter_text = (
            "他缓缓睁开眼睛，发现自己躺在一座荒废的古庙里。"
            "庙顶的瓦片掉了大半，月光从破洞中倾泻进来。"
            "他下意识摸向腰间，却发现佩剑已然不见。"
            "他猛地坐起，咳嗽声划破了寂静。"
        )

        state: dict = {
            "current_chapter_text": current_chapter_text,
            "current_chapter": 32,
            "current_chapter_outline": {
                "chapter_number": 32,
                "title": "醒来",
                "goal": "主角苏醒",
            },
            "chapters": [{"full_text": prev_full_text, "chapter_number": 31}],
            "characters": [],
            "config": {},
        }

        # 让 LLM 客户端不可用 → reviewer_node 走纯规则路径
        # （和真实生产一致：LLM 失败时仍跑规则维度）
        with patch(
            "src.llm.llm_client.create_llm_client",
            side_effect=RuntimeError("no llm"),
        ):
            result_state = reviewer_node(state)

        # current_chapter_quality 是 dict（model_dump'd），issues 是 list[dict]
        critique = result_state["current_chapter_quality"]
        issues = critique["issues"]
        cross_issues = [i for i in issues if i["type"] == "cross_chapter_verbatim"]
        assert len(cross_issues) == 1, (
            f"reviewer_node 端到端：应报 1 条 cross_chapter_verbatim issue，"
            f"实际 issues={[i['type'] for i in issues]}"
        )
        assert cross_issues[0]["severity"] == "high"
        # need_rewrite 应被 high severity 拉起来
        assert critique["need_rewrite"] is True

    def test_reviewer_node_first_chapter_no_prev_tail(self) -> None:
        """首章场景：state["chapters"] 为空 → prev_tail 为空 → 不报。"""
        from unittest.mock import patch

        from src.novel.agents.reviewer import reviewer_node

        state: dict = {
            "current_chapter_text": "第一章正文内容。" * 30,
            "current_chapter": 1,
            "current_chapter_outline": {"chapter_number": 1, "title": "起源"},
            "chapters": [],
            "characters": [],
            "config": {},
        }

        with patch(
            "src.llm.llm_client.create_llm_client",
            side_effect=RuntimeError("no llm"),
        ):
            result_state = reviewer_node(state)

        critique = result_state["current_chapter_quality"]
        types = {i["type"] for i in critique["issues"]}
        assert "cross_chapter_verbatim" not in types
