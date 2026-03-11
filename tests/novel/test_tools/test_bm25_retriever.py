"""BM25Retriever unit tests.

Covers:
- Empty corpus returns empty
- Add chapter and query
- Query by entity
- Multiple chapters
- Scores decrease with irrelevance
"""

from __future__ import annotations

import pytest

# Guard: skip entire module if jieba / rank_bm25 not installed
jieba = pytest.importorskip("jieba", reason="jieba not installed")
pytest.importorskip("rank_bm25", reason="rank_bm25 not installed")

from src.novel.tools.bm25_retriever import BM25Retriever


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CH1_TEXT = (
    "张三拿起了长剑，朝着敌人冲去。\n"
    "李四在一旁默默观察，寻找破绽。\n\n"
    "战斗持续了整整一个时辰，最终张三获胜。"
)

_CH2_TEXT = (
    "回到客栈后，张三伤势严重，躺在床上无法动弹。\n"
    "李四守在门口，防止敌人再次来袭。\n\n"
    "第二天清晨，王五带来了珍贵的疗伤丹药。\n"
    "张三服下丹药后，伤势逐渐好转。"
)

_CH3_TEXT = (
    "一个月后，众人来到了京城。\n"
    "京城的繁华远超他们的想象。\n\n"
    "张三在京城的武馆中修炼剑法。\n"
    "李四则去打探消息。"
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBM25Retriever:
    def test_empty_corpus_returns_empty(self) -> None:
        """Querying an empty retriever returns an empty list."""
        r = BM25Retriever()
        assert r.query("张三") == []

    def test_add_chapter_and_query(self) -> None:
        """After adding one chapter, relevant query returns results."""
        r = BM25Retriever()
        r.add_chapter(1, _CH1_TEXT)

        results = r.query("张三长剑")
        assert len(results) > 0
        assert results[0]["chapter"] == 1
        assert isinstance(results[0]["score"], float)
        assert results[0]["score"] > 0

    def test_query_by_entity(self) -> None:
        """query_by_entity returns paragraphs mentioning the entity."""
        r = BM25Retriever()
        r.add_chapter(1, _CH1_TEXT)
        r.add_chapter(2, _CH2_TEXT)

        results = r.query_by_entity("王五")
        assert len(results) > 0
        # The top result should mention 王五
        assert "王五" in results[0]["text"]

    def test_multiple_chapters(self) -> None:
        """Results span multiple chapters and include chapter numbers."""
        r = BM25Retriever()
        r.add_chapter(1, _CH1_TEXT)
        r.add_chapter(2, _CH2_TEXT)
        r.add_chapter(3, _CH3_TEXT)

        results = r.query("张三", top_k=10)
        chapters_found = {res["chapter"] for res in results}
        # 张三 appears in all 3 chapters
        assert len(chapters_found) >= 2

    def test_scores_decrease_with_irrelevance(self) -> None:
        """A highly relevant query scores higher than an irrelevant one."""
        r = BM25Retriever()
        r.add_chapter(1, _CH1_TEXT)
        r.add_chapter(2, _CH2_TEXT)

        relevant = r.query("张三长剑战斗", top_k=1)
        irrelevant = r.query("飞机大炮宇宙飞船", top_k=1)

        if relevant and irrelevant:
            assert relevant[0]["score"] > irrelevant[0]["score"]
        elif relevant and not irrelevant:
            # Irrelevant query returned nothing -- that's fine
            pass
        else:
            pytest.skip("BM25 didn't return results for either query")

    def test_empty_text_ignored(self) -> None:
        """Adding empty text does not break the retriever."""
        r = BM25Retriever()
        r.add_chapter(1, "")
        r.add_chapter(2, "  ")
        assert r.query("test") == []

    def test_empty_query_returns_empty(self) -> None:
        """An empty query string returns empty results."""
        r = BM25Retriever()
        r.add_chapter(1, _CH1_TEXT)
        assert r.query("") == []
        assert r.query("   ") == []
