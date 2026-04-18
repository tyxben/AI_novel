"""伏笔管理服务测试 - ForeshadowingService

NOTE: ``ForeshadowingTool`` 已随 architecture-rework-2026 Phase 0 删除，
对应的 ``TestForeshadowingTool`` 用例集体下线。本文件只保留
``ForeshadowingService`` + ``_extract_json_array`` + 集成用例。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.novel.models.foreshadowing import DetailEntry, Foreshadowing
from src.novel.services.foreshadowing_service import (
    ForeshadowingService,
    _extract_json_array,
)
from src.novel.storage.knowledge_graph import KnowledgeGraph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def knowledge_graph():
    """Create a fresh KnowledgeGraph."""
    return KnowledgeGraph()


@pytest.fixture
def mock_llm():
    """Create a mock LLM client."""
    return MagicMock()


@pytest.fixture
def mock_memory():
    """Create a mock NovelMemory with vector store."""
    memory = MagicMock()
    memory.add_detail = MagicMock()
    memory.search_details = MagicMock(return_value={
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
    })
    # mock vector_store._collection for _find_detail_by_id
    memory.vector_store = MagicMock()
    memory.vector_store._collection = MagicMock()
    return memory


@pytest.fixture
def service(knowledge_graph, mock_llm, mock_memory):
    """Create ForeshadowingService with all dependencies."""
    return ForeshadowingService(
        knowledge_graph=knowledge_graph,
        llm_client=mock_llm,
        novel_memory=mock_memory,
    )


@pytest.fixture
def sample_chapter_text():
    return (
        "林远走进破旧的祠堂，墙角有一把生锈的铁剑，剑柄上刻着奇怪的符文。"
        "他没有在意，径直走向供桌。供桌上放着一盏油灯，灯焰呈现诡异的蓝色。"
        "老者咳嗽了一声，意味深长地看了他一眼，说道：'有些东西，错过了就再也找不回来了。'"
        "说完便转身消失在暗处。林远回头看了看那把铁剑，心中隐隐觉得不安。"
    )


# ---------------------------------------------------------------------------
# _extract_json_array helper tests
# ---------------------------------------------------------------------------


class TestExtractJsonArray:
    def test_direct_array(self):
        result = _extract_json_array('[{"a": 1}]')
        assert result == [{"a": 1}]

    def test_wrapped_in_details_key(self):
        result = _extract_json_array('{"details": [{"a": 1}]}')
        assert result == [{"a": 1}]

    def test_wrapped_in_items_key(self):
        result = _extract_json_array('{"items": [{"x": 2}]}')
        assert result == [{"x": 2}]

    def test_array_embedded_in_text(self):
        result = _extract_json_array('Here are details:\n[{"a": 1}]\nDone.')
        assert result == [{"a": 1}]

    def test_none_input(self):
        assert _extract_json_array(None) is None

    def test_empty_string(self):
        assert _extract_json_array("") is None

    def test_invalid_json(self):
        assert _extract_json_array("not json at all") is None

    def test_dict_without_known_key(self):
        assert _extract_json_array('{"unknown_key": [1, 2]}') is None


# ---------------------------------------------------------------------------
# extract_details tests
# ---------------------------------------------------------------------------


class TestExtractDetails:
    def test_basic_extraction(self, service, mock_llm, sample_chapter_text):
        """Test extracting details from chapter text via LLM."""
        llm_response = MagicMock()
        llm_response.content = json.dumps([
            {
                "content": "生锈的铁剑，剑柄上刻着奇怪的符文",
                "context": "墙角有一把生锈的铁剑，剑柄上刻着奇怪的符文。他没有在意，径直走向供桌。",
                "category": "道具",
            },
            {
                "content": "油灯灯焰呈现诡异的蓝色",
                "context": "供桌上放着一盏油灯，灯焰呈现诡异的蓝色。",
                "category": "异常现象",
            },
            {
                "content": "老者说'有些东西，错过了就再也找不回来了'",
                "context": "老者咳嗽了一声，意味深长地看了他一眼，说道：'有些东西，错过了就再也找不回来了。'",
                "category": "对话暗示",
            },
        ])
        mock_llm.chat.return_value = llm_response

        details = service.extract_details(sample_chapter_text, chapter_number=3)

        assert len(details) == 3
        assert all(isinstance(d, DetailEntry) for d in details)
        assert details[0].category == "道具"
        assert details[0].chapter == 3
        assert "铁剑" in details[0].content
        assert details[1].category == "异常现象"
        assert details[2].category == "对话暗示"

        # Verify LLM was called
        mock_llm.chat.assert_called_once()
        call_kwargs = mock_llm.chat.call_args
        assert call_kwargs[1]["json_mode"] is True

    def test_details_stored_in_vector(self, service, mock_llm, mock_memory, sample_chapter_text):
        """Extracted details should be stored in vector memory."""
        llm_response = MagicMock()
        llm_response.content = json.dumps([{
            "content": "神秘戒指",
            "context": "桌上有一枚神秘戒指。",
            "category": "道具",
        }])
        mock_llm.chat.return_value = llm_response

        details = service.extract_details(sample_chapter_text, chapter_number=1)

        assert len(details) == 1
        mock_memory.add_detail.assert_called_once()
        stored_detail = mock_memory.add_detail.call_args[0][0]
        assert isinstance(stored_detail, DetailEntry)
        assert stored_detail.content == "神秘戒指"

    def test_empty_text(self, service, mock_llm):
        """Empty text should return empty list without calling LLM."""
        details = service.extract_details("", chapter_number=1)
        assert details == []
        mock_llm.chat.assert_not_called()

    def test_whitespace_only_text(self, service, mock_llm):
        """Whitespace-only text should return empty list."""
        details = service.extract_details("   \n\t  ", chapter_number=1)
        assert details == []
        mock_llm.chat.assert_not_called()

    def test_no_extractable_details(self, service, mock_llm):
        """LLM returns empty array when no details found."""
        llm_response = MagicMock()
        llm_response.content = "[]"
        mock_llm.chat.return_value = llm_response

        details = service.extract_details("平淡无奇的一段文字。", chapter_number=5)
        assert details == []

    def test_no_llm_configured(self, knowledge_graph, mock_memory):
        """Without LLM, extract_details returns empty list."""
        svc = ForeshadowingService(
            knowledge_graph=knowledge_graph,
            llm_client=None,
            novel_memory=mock_memory,
        )
        details = svc.extract_details("有内容的文本", chapter_number=1)
        assert details == []

    def test_llm_exception_returns_empty(self, service, mock_llm):
        """LLM exception should be caught, return empty list."""
        mock_llm.chat.side_effect = RuntimeError("API error")
        details = service.extract_details("有内容的文本", chapter_number=1)
        assert details == []

    def test_llm_returns_garbage(self, service, mock_llm):
        """LLM returns unparseable content."""
        llm_response = MagicMock()
        llm_response.content = "I cannot help with that."
        mock_llm.chat.return_value = llm_response

        details = service.extract_details("有内容的文本", chapter_number=1)
        assert details == []

    def test_invalid_category_defaults_to_prop(self, service, mock_llm):
        """Unknown category should default to '道具'."""
        llm_response = MagicMock()
        llm_response.content = json.dumps([{
            "content": "一块石头",
            "context": "地上有一块石头。",
            "category": "未知类别",
        }])
        mock_llm.chat.return_value = llm_response

        details = service.extract_details("有内容的文本", chapter_number=1)
        assert len(details) == 1
        assert details[0].category == "道具"

    def test_items_missing_required_fields_skipped(self, service, mock_llm):
        """Items missing content or context should be skipped."""
        llm_response = MagicMock()
        llm_response.content = json.dumps([
            {"content": "", "context": "有上下文", "category": "道具"},
            {"content": "有内容", "context": "", "category": "道具"},
            {"content": "有效", "context": "有效上下文", "category": "道具"},
            "not_a_dict",
        ])
        mock_llm.chat.return_value = llm_response

        details = service.extract_details("有内容的文本", chapter_number=1)
        assert len(details) == 1
        assert details[0].content == "有效"

    def test_vector_store_failure_does_not_block(self, service, mock_llm, mock_memory):
        """Vector store failure should not block detail extraction."""
        mock_memory.add_detail.side_effect = RuntimeError("Chroma down")
        llm_response = MagicMock()
        llm_response.content = json.dumps([{
            "content": "一把刀",
            "context": "桌上有一把刀。",
            "category": "道具",
        }])
        mock_llm.chat.return_value = llm_response

        details = service.extract_details("有内容的文本", chapter_number=1)
        assert len(details) == 1  # Still returns the detail


# ---------------------------------------------------------------------------
# search_reusable_details tests
# ---------------------------------------------------------------------------


class TestSearchReusableDetails:
    def test_basic_search(self, service, mock_memory):
        """Test searching for reusable details via vector store."""
        mock_memory.search_details.return_value = {
            "ids": [["detail_1", "detail_2", "detail_3"]],
            "documents": [["生锈的铁剑", "蓝色灯焰", "神秘符文"]],
            "metadatas": [[
                {"chapter": 3, "category": "道具", "detail_id": "detail_1", "type": "detail"},
                {"chapter": 5, "category": "异常现象", "detail_id": "detail_2", "type": "detail"},
                {"chapter": 7, "category": "道具", "detail_id": "detail_3", "type": "detail"},
            ]],
        }

        results = service.search_reusable_details(
            query="需要一把武器",
            current_chapter=10,
            top_k=5,
        )

        assert len(results) == 3
        assert all(isinstance(d, DetailEntry) for d in results)
        assert results[0].content == "生锈的铁剑"
        assert results[0].chapter == 3
        mock_memory.search_details.assert_called_once()

    def test_filters_future_chapters(self, service, mock_memory):
        """Details from current or future chapters should be filtered out."""
        mock_memory.search_details.return_value = {
            "ids": [["d1", "d2", "d3"]],
            "documents": [["过去的剑", "当前的灯", "未来的书"]],
            "metadatas": [[
                {"chapter": 3, "category": "道具", "detail_id": "d1", "type": "detail"},
                {"chapter": 10, "category": "道具", "detail_id": "d2", "type": "detail"},
                {"chapter": 15, "category": "道具", "detail_id": "d3", "type": "detail"},
            ]],
        }

        results = service.search_reusable_details(
            query="需要武器",
            current_chapter=10,
            top_k=5,
        )

        assert len(results) == 1
        assert results[0].content == "过去的剑"
        assert results[0].chapter == 3

    def test_respects_top_k(self, service, mock_memory):
        """Should limit results to top_k."""
        mock_memory.search_details.return_value = {
            "ids": [["d1", "d2", "d3", "d4", "d5"]],
            "documents": [["a", "b", "c", "d", "e"]],
            "metadatas": [[
                {"chapter": 1, "category": "道具", "detail_id": f"d{i}", "type": "detail"}
                for i in range(1, 6)
            ]],
        }

        results = service.search_reusable_details(
            query="查询",
            current_chapter=10,
            top_k=2,
        )

        assert len(results) == 2

    def test_empty_query(self, service, mock_memory):
        """Empty query should return empty list."""
        results = service.search_reusable_details(
            query="",
            current_chapter=10,
        )
        assert results == []
        mock_memory.search_details.assert_not_called()

    def test_no_memory_configured(self, knowledge_graph, mock_llm):
        """Without novel_memory, search returns empty list."""
        svc = ForeshadowingService(
            knowledge_graph=knowledge_graph,
            llm_client=mock_llm,
            novel_memory=None,
        )
        results = svc.search_reusable_details(
            query="需要武器",
            current_chapter=10,
        )
        assert results == []

    def test_vector_store_failure(self, service, mock_memory):
        """Vector store exception should return empty list."""
        mock_memory.search_details.side_effect = RuntimeError("Chroma error")

        results = service.search_reusable_details(
            query="查询",
            current_chapter=10,
        )
        assert results == []

    def test_empty_search_results(self, service, mock_memory):
        """Empty search results from vector store."""
        mock_memory.search_details.return_value = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
        }

        results = service.search_reusable_details(
            query="不存在的内容",
            current_chapter=10,
        )
        assert results == []


# ---------------------------------------------------------------------------
# promote_to_foreshadowing tests
# ---------------------------------------------------------------------------


class TestPromoteToForeshadowing:
    def test_basic_promotion(self, service, knowledge_graph):
        """Test promoting a detail to foreshadowing."""
        detail = DetailEntry(
            detail_id="test_detail_001",
            chapter=3,
            content="生锈的铁剑",
            context="墙角有一把生锈的铁剑。",
            category="道具",
            status="available",
        )

        foreshadowing = service.promote_to_foreshadowing(
            detail_id="test_detail_001",
            resolution_plan="主角在第15章用铁剑打败敌人",
            target_chapter=15,
            detail=detail,
        )

        assert isinstance(foreshadowing, Foreshadowing)
        assert foreshadowing.planted_chapter == 3
        assert foreshadowing.content == "生锈的铁剑"
        assert foreshadowing.target_chapter == 15
        assert foreshadowing.resolution == "主角在第15章用铁剑打败敌人"
        assert foreshadowing.origin == "retroactive"
        assert foreshadowing.original_detail_id == "test_detail_001"
        assert foreshadowing.original_context == "墙角有一把生锈的铁剑。"
        assert foreshadowing.status == "pending"

        # Verify detail status updated
        assert detail.status == "promoted"
        assert detail.promoted_foreshadowing_id == foreshadowing.foreshadowing_id

        # Verify knowledge graph node created
        node = knowledge_graph.get_node(foreshadowing.foreshadowing_id)
        assert node is not None
        assert node["type"] == "foreshadowing"
        assert node["status"] == "pending"
        assert node["planted_chapter"] == 3
        assert node["target_chapter"] == 15

    def test_already_promoted_raises(self, service):
        """Promoting an already promoted detail should raise ValueError."""
        detail = DetailEntry(
            detail_id="test_detail_002",
            chapter=5,
            content="蓝色灯焰",
            context="灯焰呈现诡异的蓝色。",
            category="异常现象",
            status="promoted",
        )

        with pytest.raises(ValueError, match="已升级"):
            service.promote_to_foreshadowing(
                detail_id="test_detail_002",
                resolution_plan="灯焰是封印的信号",
                target_chapter=20,
                detail=detail,
            )

    def test_empty_detail_id_raises(self, service):
        """Empty detail_id should raise ValueError."""
        with pytest.raises(ValueError, match="不能为空"):
            service.promote_to_foreshadowing(
                detail_id="",
                resolution_plan="plan",
                target_chapter=10,
            )

    def test_nonexistent_detail_id_raises(self, service, mock_memory):
        """Non-existent detail_id (no detail passed, not in vector store) should raise."""
        mock_memory.vector_store._collection.get.return_value = {
            "ids": [],
            "documents": [],
            "metadatas": [],
        }

        with pytest.raises(ValueError, match="不存在"):
            service.promote_to_foreshadowing(
                detail_id="nonexistent_id",
                resolution_plan="plan",
                target_chapter=10,
            )

    def test_promote_finds_detail_from_vector_store(self, service, mock_memory, knowledge_graph):
        """When detail is not passed, should look it up from vector store."""
        mock_memory.vector_store.get_by_id.return_value = {
            "id": "vs_detail_001",
            "document": "古老的玉佩",
            "metadata": {"chapter": 2, "category": "道具", "type": "detail"},
        }

        foreshadowing = service.promote_to_foreshadowing(
            detail_id="vs_detail_001",
            resolution_plan="玉佩是传送门钥匙",
            target_chapter=12,
        )

        assert foreshadowing.content == "古老的玉佩"
        assert foreshadowing.planted_chapter == 2
        assert foreshadowing.origin == "retroactive"

    def test_promote_without_memory(self, knowledge_graph, mock_llm):
        """Without novel_memory and no detail passed, should raise."""
        svc = ForeshadowingService(
            knowledge_graph=knowledge_graph,
            llm_client=mock_llm,
            novel_memory=None,
        )

        with pytest.raises(ValueError, match="不存在"):
            svc.promote_to_foreshadowing(
                detail_id="some_id",
                resolution_plan="plan",
                target_chapter=10,
            )


# ---------------------------------------------------------------------------
# Integration-style tests (service + real KnowledgeGraph)
# ---------------------------------------------------------------------------


class TestServiceIntegration:
    def test_extract_and_promote_workflow(self, service, mock_llm, knowledge_graph):
        """End-to-end: extract detail -> promote to foreshadowing -> verify in graph."""
        # Step 1: Extract details
        llm_response = MagicMock()
        llm_response.content = json.dumps([{
            "content": "墙上的古画",
            "context": "祠堂墙上挂着一幅古画，画中人似在微笑。",
            "category": "道具",
        }])
        mock_llm.chat.return_value = llm_response

        details = service.extract_details("祠堂墙上挂着一幅古画，画中人似在微笑。", chapter_number=2)
        assert len(details) == 1
        detail = details[0]

        # Step 2: Promote to foreshadowing
        foreshadowing = service.promote_to_foreshadowing(
            detail_id=detail.detail_id,
            resolution_plan="古画是通往异世界的入口",
            target_chapter=20,
            detail=detail,
        )

        # Step 3: Verify in knowledge graph
        assert detail.status == "promoted"
        node = knowledge_graph.get_node(foreshadowing.foreshadowing_id)
        assert node is not None
        assert node["origin"] == "retroactive"
        assert node["original_detail_id"] == detail.detail_id

        # Step 4: Check pending foreshadowings
        pending = knowledge_graph.get_pending_foreshadowings(current_chapter=5)
        assert any(
            f["foreshadowing_id"] == foreshadowing.foreshadowing_id
            for f in pending
        )

    def test_register_and_get_forgotten(self, service, knowledge_graph):
        """Register foreshadowings and check forgotten ones."""
        # Register a few
        chapter_brief = {
            "foreshadowing_plant": ["主角的玉佩发光", "密室中的暗道"],
            "foreshadowing_collect": [],
        }
        count = service.register_planned_foreshadowings(chapter_brief, chapter_number=1)
        assert count == 2

        # Not forgotten at chapter 5
        forgotten = service.get_forgotten_foreshadowings(current_chapter=5, threshold=10)
        assert len(forgotten) == 0

        # Forgotten at chapter 15
        forgotten = service.get_forgotten_foreshadowings(current_chapter=15, threshold=10)
        assert len(forgotten) == 2
