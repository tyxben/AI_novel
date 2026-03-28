"""Vector-based consistency check tests

Covers:
- _vector_check: character resurrection detection via vector retrieval
- _vector_check: character disappearance detection
- _vector_check: event duplication via semantic similarity
- _vector_check: graceful fallback to BM25 when vector store unavailable
- _vector_check: graceful fallback when vector store is empty
- consistency_checker_node: new frequency logic (every chapter gets checked)
- consistency_checker_node: chapter 1 now gets lightweight check (not skipped)
- consistency_checker_node: non-9th chapters get lightweight vector check
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.novel.agents.consistency_checker import (
    _bm25_check_fallback,
    _vector_check,
    consistency_checker_node,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    chapter_number: int = 5,
    chapter_text: str = "张三说道，我们出发吧。",
    characters: list[dict] | None = None,
    novel_id: str = "test_novel",
    workspace: str = "/tmp/test_ws",
    **extra: Any,
) -> dict[str, Any]:
    """Build a minimal NovelState dict for testing."""
    state: dict[str, Any] = {
        "current_chapter_text": chapter_text,
        "current_chapter": chapter_number,
        "config": {"llm": {"provider": "auto"}},
        "novel_id": novel_id,
        "workspace": workspace,
        "characters": characters or [{"name": "张三"}, {"name": "李四"}],
        "current_chapter_quality": {},
    }
    state.update(extra)
    return state


def _make_mock_vector_store(
    facts_results: dict | None = None,
    count: int = 10,
    search_side_effect: Exception | None = None,
) -> MagicMock:
    """Create a mock VectorStore with configurable search results."""
    vs = MagicMock()
    vs.count.return_value = count

    if search_side_effect:
        vs.search_similar_facts.side_effect = search_side_effect
    elif facts_results is not None:
        vs.search_similar_facts.return_value = facts_results
    else:
        vs.search_similar_facts.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
    return vs


def _make_mock_memory(
    vector_store: MagicMock | None = None,
    count: int = 10,
) -> MagicMock:
    """Create a mock NovelMemory with an embedded mock VectorStore."""
    memory = MagicMock()
    if vector_store is None:
        vector_store = _make_mock_vector_store(count=count)
    memory.vector_store = vector_store
    memory.close = MagicMock()
    return memory


# ---------------------------------------------------------------------------
# _vector_check: Character resurrection
# ---------------------------------------------------------------------------


class TestVectorCheckResurrection:
    """Dead character reappearing in a later chapter."""

    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_detects_death_then_alive(self, MockMemoryCls):
        """Character dies in ch3, appears alive in ch10 -> contradiction."""
        vs = _make_mock_vector_store(
            facts_results={
                "documents": [[
                    "张三身亡，众人悲痛不已",
                    "张三说道：我们继续前进",
                ]],
                "metadatas": [[
                    {"chapter": 3, "type": "character_state"},
                    {"chapter": 10, "type": "event"},
                ]],
                "distances": [[0.2, 0.3]],
            },
        )
        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        state = _make_state(
            chapter_number=10,
            chapter_text="张三说道：我已恢复。",
            characters=[{"name": "张三"}],
        )
        result = _vector_check(state, state["current_chapter_text"], 10)

        assert result["method"] == "vector"
        resurrections = [
            c for c in result["contradictions"]
            if c["type"] == "character_resurrection"
        ]
        assert len(resurrections) >= 1
        assert resurrections[0]["character"] == "张三"
        assert resurrections[0]["confidence"] == 0.6
        assert result["passed"] is False

    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_no_resurrection_when_death_after_alive(self, MockMemoryCls):
        """Alive ref is BEFORE death ref -> no resurrection flag."""
        vs = _make_mock_vector_store(
            facts_results={
                "documents": [[
                    "张三说道：出发",
                    "张三身亡",
                ]],
                "metadatas": [[
                    {"chapter": 2, "type": "event"},
                    {"chapter": 5, "type": "character_state"},
                ]],
                "distances": [[0.3, 0.3]],
            },
        )
        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        state = _make_state(
            chapter_number=5,
            chapter_text="战斗结束了。",
            characters=[{"name": "张三"}],
        )
        result = _vector_check(state, state["current_chapter_text"], 5)

        resurrections = [
            c for c in result["contradictions"]
            if c["type"] == "character_resurrection"
        ]
        assert len(resurrections) == 0


# ---------------------------------------------------------------------------
# _vector_check: Character disappearance
# ---------------------------------------------------------------------------


class TestVectorCheckDisappearance:
    """Character departs but is never mentioned again."""

    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_detects_departure_no_followup(self, MockMemoryCls):
        """Character departs in ch3, no mention by ch10 -> flag."""
        vs = _make_mock_vector_store(
            facts_results={
                "documents": [[
                    "李四前去铁剑门谈判",
                ]],
                "metadatas": [[
                    {"chapter": 3, "type": "event"},
                ]],
                "distances": [[0.25]],
            },
        )
        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        state = _make_state(
            chapter_number=10,
            chapter_text="张三独自修炼。",
            characters=[{"name": "李四"}],
        )
        result = _vector_check(state, state["current_chapter_text"], 10)

        disappearances = [
            c for c in result["contradictions"]
            if c["type"] == "character_disappeared"
        ]
        assert len(disappearances) >= 1
        assert disappearances[0]["character"] == "李四"
        assert disappearances[0]["confidence"] == 0.4

    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_no_disappearance_with_followup(self, MockMemoryCls):
        """Character departs in ch3 but reappears in ch7 -> no flag."""
        vs = _make_mock_vector_store(
            facts_results={
                "documents": [[
                    "李四前去铁剑门谈判",
                    "李四说道：谈判成功了",
                ]],
                "metadatas": [[
                    {"chapter": 3, "type": "event"},
                    {"chapter": 7, "type": "event"},
                ]],
                "distances": [[0.25, 0.3]],
            },
        )
        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        state = _make_state(
            chapter_number=10,
            chapter_text="众人聚集。",
            characters=[{"name": "李四"}],
        )
        result = _vector_check(state, state["current_chapter_text"], 10)

        disappearances = [
            c for c in result["contradictions"]
            if c["type"] == "character_disappeared"
        ]
        assert len(disappearances) == 0


# ---------------------------------------------------------------------------
# _vector_check: Event duplication
# ---------------------------------------------------------------------------


class TestVectorCheckEventDuplication:
    """Detect highly similar paragraphs across chapters."""

    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_detects_duplicate_paragraph(self, MockMemoryCls):
        """Very low distance (<0.15) between paragraphs in different chapters."""
        # The character search returns nothing (no char issues)
        char_results = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        # The paragraph search returns a very similar passage from ch3
        para_results = {
            "documents": [["主角挥剑斩向敌人，剑光闪烁"]],
            "metadatas": [[{"chapter": 3, "type": "event"}]],
            "distances": [[0.08]],  # Very similar
        }

        call_count = {"n": 0}

        def side_effect(query, n_results=5, **kw):
            call_count["n"] += 1
            # First calls are for characters, later ones for paragraphs
            if "状态 行动 位置" in query:
                return char_results
            return para_results

        vs = MagicMock()
        vs.count.return_value = 10
        vs.search_similar_facts.side_effect = side_effect

        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        long_para = ("主角挥剑斩向敌人，剑光闪烁，敌人应声倒地。这一招凌厉无比，"
                    "众人纷纷惊叹。远处的山峰在夕阳下泛起金光，战场上的硝烟渐渐散去。")
        text = f"一些开头文字，为了凑够字数需要更多的文字内容来确保段落足够长。\n\n{long_para}\n\n结尾。"
        state = _make_state(
            chapter_number=10,
            chapter_text=text,
            characters=[],  # No characters to check
        )
        result = _vector_check(state, text, 10)

        dupes = [
            c for c in result["contradictions"]
            if c["type"] == "event_duplication"
        ]
        assert len(dupes) >= 1
        assert dupes[0]["confidence"] == 0.45
        assert dupes[0]["conflicting_fact"]["chapter"] == 3

    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_no_duplication_when_distance_high(self, MockMemoryCls):
        """Distance >= 0.15 should not flag duplication."""
        vs = _make_mock_vector_store(
            facts_results={
                "documents": [["一些不太相关的文本"]],
                "metadatas": [[{"chapter": 3, "type": "event"}]],
                "distances": [[0.5]],  # Not similar enough
            },
        )
        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        long_para = "完全不同的段落，讲述了另一个故事情节，与之前的内容毫无关系。"
        text = f"开头。\n\n{long_para}\n\n结尾。"
        state = _make_state(
            chapter_number=10,
            chapter_text=text,
            characters=[],
        )
        result = _vector_check(state, text, 10)

        dupes = [
            c for c in result["contradictions"]
            if c["type"] == "event_duplication"
        ]
        assert len(dupes) == 0

    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_no_duplication_for_same_chapter(self, MockMemoryCls):
        """Same chapter number in duplication match should be ignored."""
        vs = _make_mock_vector_store(
            facts_results={
                "documents": [["主角修炼突破"]],
                "metadatas": [[{"chapter": 10, "type": "event"}]],  # Same chapter
                "distances": [[0.05]],
            },
        )
        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        text = "开头。\n\n主角修炼突破，实力大增，震惊四座。\n\n结尾。"
        state = _make_state(
            chapter_number=10,
            chapter_text=text,
            characters=[],
        )
        result = _vector_check(state, text, 10)

        dupes = [
            c for c in result["contradictions"]
            if c["type"] == "event_duplication"
        ]
        assert len(dupes) == 0


# ---------------------------------------------------------------------------
# _vector_check: Fallback behavior
# ---------------------------------------------------------------------------


class TestVectorCheckFallback:
    """Test graceful fallback when vector store is unavailable."""

    @patch("src.novel.agents.consistency_checker._bm25_check_fallback")
    @patch(
        "src.novel.storage.novel_memory.NovelMemory",
        side_effect=ImportError("chromadb not installed"),
    )
    def test_fallback_to_bm25_on_memory_init_failure(
        self, _mock_memory, mock_bm25
    ):
        """When NovelMemory init fails, fall back to BM25."""
        mock_bm25.return_value = {
            "passed": True,
            "contradictions": [],
            "method": "bm25",
        }
        state = _make_state(chapter_number=5)
        result = _vector_check(state, "some text", 5)

        mock_bm25.assert_called_once_with(state, "some text", 5)
        assert result["method"] == "bm25"

    @patch("src.novel.agents.consistency_checker._bm25_check_fallback")
    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_fallback_to_bm25_on_empty_vector_store(
        self, MockMemoryCls, mock_bm25
    ):
        """When vector store is empty (count==0), fall back to BM25."""
        mock_bm25.return_value = {
            "passed": True,
            "contradictions": [],
            "method": "bm25",
        }
        vs = _make_mock_vector_store(count=0)
        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        state = _make_state(chapter_number=5)
        result = _vector_check(state, "some text", 5)

        mock_bm25.assert_called_once()
        assert result["method"] == "bm25"

    @patch("src.novel.agents.consistency_checker._bm25_check_fallback")
    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_fallback_to_bm25_on_vector_exception(
        self, MockMemoryCls, mock_bm25
    ):
        """When vector store raises during search, fall back to BM25."""
        mock_bm25.return_value = {
            "passed": True,
            "contradictions": [],
            "method": "bm25",
        }
        vs = MagicMock()
        vs.count.side_effect = RuntimeError("Chroma crashed")
        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        state = _make_state(chapter_number=5)
        result = _vector_check(state, "some text", 5)

        mock_bm25.assert_called_once()

    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_passes_when_no_characters(self, MockMemoryCls):
        """No characters in state -> no character checks, still passes."""
        vs = _make_mock_vector_store()
        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        state = _make_state(
            chapter_number=5,
            chapter_text="短文本。",
            characters=[],
        )
        result = _vector_check(state, "短文本。", 5)

        assert result["passed"] is True
        assert result["method"] == "vector"
        assert result["contradictions"] == []

    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_memory_close_called_even_on_success(self, MockMemoryCls):
        """NovelMemory.close() is called in the finally block."""
        vs = _make_mock_vector_store()
        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        state = _make_state(chapter_number=5, characters=[])
        _vector_check(state, "text", 5)

        mock_memory.close.assert_called_once()


# ---------------------------------------------------------------------------
# consistency_checker_node: Frequency logic
# ---------------------------------------------------------------------------


class TestNodeFrequencyLogic:
    """Verify every chapter gets at least a lightweight check."""

    @patch("src.novel.agents.consistency_checker._vector_check")
    @patch("src.novel.agents.consistency_checker._run_narrative_logic_check")
    def test_chapter_1_gets_vector_check(
        self, mock_narrative, mock_vector
    ):
        """Chapter 1 should get lightweight vector check, not be skipped."""
        mock_vector.return_value = {
            "passed": True,
            "contradictions": [],
            "method": "vector",
        }
        mock_narrative.return_value = []

        state = _make_state(chapter_number=1)
        result = consistency_checker_node(state)

        mock_vector.assert_called_once()
        assert "consistency_checker" in result["completed_nodes"]
        quality = result["current_chapter_quality"]
        assert quality["consistency_check"]["passed"] is True
        assert quality["consistency_check"]["method"] == "vector"

    @patch("src.novel.agents.consistency_checker._vector_check")
    @patch("src.novel.agents.consistency_checker._run_narrative_logic_check")
    def test_chapter_2_gets_vector_check(
        self, mock_narrative, mock_vector
    ):
        """Chapter 2 (previously skipped) now gets lightweight check."""
        mock_vector.return_value = {
            "passed": True,
            "contradictions": [],
            "method": "vector",
        }
        mock_narrative.return_value = []

        state = _make_state(chapter_number=2)
        result = consistency_checker_node(state)

        mock_vector.assert_called_once()
        assert "consistency_checker" in result["completed_nodes"]

    @patch("src.novel.agents.consistency_checker._vector_check")
    @patch("src.novel.agents.consistency_checker._run_narrative_logic_check")
    def test_chapter_3_gets_vector_check(
        self, mock_narrative, mock_vector
    ):
        """Chapter 3 (previously skipped) now gets lightweight check."""
        mock_vector.return_value = {
            "passed": True,
            "contradictions": [],
            "method": "vector",
        }
        mock_narrative.return_value = []

        state = _make_state(chapter_number=3)
        result = consistency_checker_node(state)

        mock_vector.assert_called_once()

    @patch("src.novel.agents.consistency_checker._vector_check")
    @patch("src.novel.agents.consistency_checker._run_narrative_logic_check")
    def test_chapter_5_gets_vector_check(
        self, mock_narrative, mock_vector
    ):
        """Chapter 5 (non-9th, previously only every-3rd) gets checked."""
        mock_vector.return_value = {
            "passed": True,
            "contradictions": [],
            "method": "vector",
        }
        mock_narrative.return_value = []

        state = _make_state(chapter_number=5)
        result = consistency_checker_node(state)

        mock_vector.assert_called_once()

    @patch("src.novel.agents.consistency_checker._vector_check")
    @patch("src.novel.agents.consistency_checker._run_narrative_logic_check")
    def test_non_9th_chapters_all_use_lightweight(
        self, mock_narrative, mock_vector
    ):
        """All non-9th chapters (1-8, 10-17, etc.) get lightweight vector check."""
        mock_vector.return_value = {
            "passed": True,
            "contradictions": [],
            "method": "vector",
        }
        mock_narrative.return_value = []

        for ch in [1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 17, 20, 35]:
            mock_vector.reset_mock()
            state = _make_state(chapter_number=ch)
            result = consistency_checker_node(state)
            mock_vector.assert_called_once(), f"Chapter {ch} should use vector check"

    @patch("src.novel.storage.novel_memory.NovelMemory")
    @patch("src.llm.llm_client.create_llm_client")
    def test_9th_chapter_gets_full_llm_check(
        self, mock_create_llm, MockMemory
    ):
        """Chapter 9 (and 18, 27, ...) gets full LLM check, not lightweight."""
        from dataclasses import dataclass

        @dataclass
        class FakeLLMResponse:
            content: str = "[]"
            model: str = "fake"
            usage: dict | None = None

        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(content="[]")
        mock_create_llm.return_value = mock_llm

        mock_mem = _make_mock_memory()
        MockMemory.return_value = mock_mem

        state = _make_state(chapter_number=9)
        result = consistency_checker_node(state)

        assert "consistency_checker" in result["completed_nodes"]
        # Full LLM check produces "facts_count" key
        quality = result.get("current_chapter_quality", {})
        if "consistency_check" in quality:
            assert "facts_count" in quality["consistency_check"]

    @patch("src.novel.agents.consistency_checker._vector_check")
    @patch("src.novel.agents.consistency_checker._run_narrative_logic_check")
    def test_vector_contradictions_surface_in_node_result(
        self, mock_narrative, mock_vector
    ):
        """Contradictions from vector check appear in node output."""
        mock_vector.return_value = {
            "passed": False,
            "contradictions": [{
                "layer": "vector",
                "type": "character_resurrection",
                "character": "张三",
                "fact": {"chapter": 10, "content": "张三出现"},
                "conflicting_fact": {"chapter": 3, "content": "张三身亡"},
                "confidence": 0.6,
                "reason": "张三在第3章疑似死亡，但在第10章再次出现",
            }],
            "method": "vector",
        }
        mock_narrative.return_value = []

        state = _make_state(chapter_number=10)
        result = consistency_checker_node(state)

        quality = result["current_chapter_quality"]
        assert quality["consistency_check"]["passed"] is False
        assert len(quality["consistency_check"]["contradictions"]) == 1
        assert quality["consistency_check"]["contradictions"][0]["type"] == "character_resurrection"

    @patch("src.novel.agents.consistency_checker._vector_check")
    @patch("src.novel.agents.consistency_checker._run_narrative_logic_check")
    def test_decision_records_vector_method(
        self, mock_narrative, mock_vector
    ):
        """Decision record should mention vector check, not bm25."""
        mock_vector.return_value = {
            "passed": True,
            "contradictions": [],
            "method": "vector",
        }
        mock_narrative.return_value = []

        state = _make_state(chapter_number=5)
        result = consistency_checker_node(state)

        decisions = result["decisions"]
        assert len(decisions) >= 1
        assert decisions[0]["step"] == "vector_check"
        assert "向量" in decisions[0]["reason"]


# ---------------------------------------------------------------------------
# _vector_check: Edge cases
# ---------------------------------------------------------------------------


class TestVectorCheckEdgeCases:
    """Edge cases and boundary conditions."""

    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_character_name_not_in_document(self, MockMemoryCls):
        """Documents returned by vector search that don't contain the
        character name should be ignored."""
        vs = _make_mock_vector_store(
            facts_results={
                "documents": [["一些不包含角色名的文档"]],
                "metadatas": [[{"chapter": 3, "type": "event"}]],
                "distances": [[0.2]],
            },
        )
        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        state = _make_state(
            chapter_number=5,
            chapter_text="无关文本",
            characters=[{"name": "王五"}],
        )
        result = _vector_check(state, "无关文本", 5)

        assert result["passed"] is True
        assert result["contradictions"] == []

    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_empty_search_results(self, MockMemoryCls):
        """search_similar_facts returns empty documents list."""
        vs = _make_mock_vector_store(
            facts_results={
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            },
        )
        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        state = _make_state(
            chapter_number=5,
            characters=[{"name": "张三"}],
        )
        result = _vector_check(state, "张三走了", 5)

        assert result["passed"] is True

    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_search_per_character_fails_gracefully(self, MockMemoryCls):
        """If search fails for one character, other characters still checked."""
        call_count = {"n": 0}

        def side_effect(query, n_results=5, **kw):
            call_count["n"] += 1
            if "张三" in query:
                raise RuntimeError("Search failed for 张三")
            return {
                "documents": [["李四说道：好的"]],
                "metadatas": [[{"chapter": 5, "type": "event"}]],
                "distances": [[0.3]],
            }

        vs = MagicMock()
        vs.count.return_value = 10
        vs.search_similar_facts.side_effect = side_effect

        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        state = _make_state(
            chapter_number=5,
            chapter_text="短文本。",
            characters=[{"name": "张三"}, {"name": "李四"}],
        )
        result = _vector_check(state, "短文本。", 5)

        # Should complete without error (张三 search failed but 李四 succeeded)
        assert result["method"] == "vector"
        # Should have been called at least twice (once per character)
        assert call_count["n"] >= 2

    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_current_chapter_text_contributes_alive_ref(self, MockMemoryCls):
        """Current chapter text with alive keywords adds an alive_ref
        for the current chapter number."""
        vs = _make_mock_vector_store(
            facts_results={
                "documents": [["张三身亡，众人悲痛"]],
                "metadatas": [[{"chapter": 3, "type": "character_state"}]],
                "distances": [[0.2]],
            },
        )
        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        # Current chapter has 张三 + alive keyword
        state = _make_state(
            chapter_number=10,
            chapter_text="张三走到门前，推开了大门。",
            characters=[{"name": "张三"}],
        )
        result = _vector_check(state, state["current_chapter_text"], 10)

        resurrections = [
            c for c in result["contradictions"]
            if c["type"] == "character_resurrection"
        ]
        # Death in ch3, alive in ch10 (current chapter) -> resurrection
        assert len(resurrections) >= 1
        assert resurrections[0]["fact"]["chapter"] == 10

    @patch("src.novel.storage.novel_memory.NovelMemory")
    def test_empty_chapter_text(self, MockMemoryCls):
        """Empty chapter text should still work without errors."""
        vs = _make_mock_vector_store()
        mock_memory = _make_mock_memory(vector_store=vs)
        MockMemoryCls.return_value = mock_memory

        state = _make_state(chapter_number=5, chapter_text="", characters=[])
        result = _vector_check(state, "", 5)

        assert result["method"] == "vector"
        assert result["passed"] is True


# ---------------------------------------------------------------------------
# _bm25_check_fallback: Ensure it still works
# ---------------------------------------------------------------------------


class TestBM25Fallback:
    """Verify the renamed BM25 fallback function still works."""

    def test_bm25_fallback_returns_correct_method(self):
        """The fallback should report method='bm25'."""
        state = _make_state(
            chapter_number=5,
            chapter_text="一些文本",
            characters=[],
        )
        result = _bm25_check_fallback(state, "一些文本", 5)

        assert result["method"] == "bm25"
        assert isinstance(result["passed"], bool)
        assert isinstance(result["contradictions"], list)

    def test_bm25_fallback_with_empty_chapters_text(self):
        """BM25 fallback handles missing chapters_text gracefully."""
        state = _make_state(
            chapter_number=5,
            chapter_text="当前章节内容",
            characters=[{"name": "张三"}],
        )
        # No chapters_text in state
        result = _bm25_check_fallback(state, "当前章节内容", 5)

        assert result["method"] == "bm25"
        assert isinstance(result["contradictions"], list)


# ---------------------------------------------------------------------------
# Node: empty text handling
# ---------------------------------------------------------------------------


class TestNodeEmptyText:
    """Node-level handling of empty/missing text."""

    def test_empty_text_returns_error_immediately(self):
        """Empty text -> error, no vector/bm25 check attempted."""
        state = _make_state(chapter_number=5, chapter_text="")
        result = consistency_checker_node(state)

        assert "consistency_checker" in result["completed_nodes"]
        assert len(result["errors"]) >= 1
        assert "为空" in result["errors"][0]["message"]

    def test_missing_text_returns_error(self):
        """No current_chapter_text key -> error."""
        state: dict[str, Any] = {
            "current_chapter": 5,
            "config": {"llm": {}},
        }
        result = consistency_checker_node(state)

        assert "consistency_checker" in result["completed_nodes"]
        assert len(result["errors"]) >= 1
