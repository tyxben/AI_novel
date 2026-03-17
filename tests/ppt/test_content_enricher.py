"""Tests for ContentEnricher -- web research enrichment for PPT pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.ppt.content_enricher import (
    ContentEnricher,
    EnrichLevel,
    _gap_type_to_block_type,
)
from src.ppt.models import ContentBlock, ContentMap


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_content_map(
    *,
    thesis: str = "AI 正在改变各行各业",
    num_blocks: int = 3,
    data_points: list[str] | None = None,
    quotes: list[str] | None = None,
) -> ContentMap:
    """Helper to build a ContentMap for tests."""
    blocks = [
        ContentBlock(
            block_id=f"b{i+1}",
            block_type="argument",
            title=f"论点{i+1}",
            summary=f"这是第{i+1}个论点的摘要内容",
            source_text=f"第{i+1}段原文",
            importance=4,
        )
        for i in range(num_blocks)
    ]
    return ContentMap(
        document_thesis=thesis,
        content_blocks=blocks,
        logical_flow=[b.block_id for b in blocks],
        key_data_points=data_points or [],
        key_quotes=quotes or [],
    )


def _mock_llm_response(content: str) -> LLMResponse:
    """Create a LLMResponse with given content."""
    return LLMResponse(content=content, model="test-model", usage=None)


@pytest.fixture()
def enricher_llm():
    """ContentEnricher with level=llm and mocked LLM."""
    with patch("src.ppt.content_enricher.create_llm_client") as mock_create:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        config = {"llm": {}, "ppt": {"enrich_level": "llm"}}
        enricher = ContentEnricher(config)
        yield enricher, mock_client


@pytest.fixture()
def enricher_web():
    """ContentEnricher with level=web and mocked LLM."""
    with patch("src.ppt.content_enricher.create_llm_client") as mock_create:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        config = {"llm": {}, "ppt": {"enrich_level": "web"}}
        enricher = ContentEnricher(config)
        yield enricher, mock_client


@pytest.fixture()
def enricher_none():
    """ContentEnricher with level=none and mocked LLM."""
    with patch("src.ppt.content_enricher.create_llm_client") as mock_create:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        config = {"llm": {}, "ppt": {"enrich_level": "none"}}
        enricher = ContentEnricher(config)
        yield enricher, mock_client


# ---------------------------------------------------------------------------
# Test EnrichLevel enum
# ---------------------------------------------------------------------------


class TestEnrichLevel:
    def test_enum_values(self):
        assert EnrichLevel.NONE == "none"
        assert EnrichLevel.LLM == "llm"
        assert EnrichLevel.WEB == "web"

    def test_enum_from_string(self):
        assert EnrichLevel("none") is EnrichLevel.NONE
        assert EnrichLevel("llm") is EnrichLevel.LLM
        assert EnrichLevel("web") is EnrichLevel.WEB


# ---------------------------------------------------------------------------
# Test _gap_type_to_block_type
# ---------------------------------------------------------------------------


class TestGapTypeMapping:
    def test_missing_data(self):
        assert _gap_type_to_block_type("missing_data") == "data"

    def test_missing_context(self):
        assert _gap_type_to_block_type("missing_context") == "argument"

    def test_missing_evidence(self):
        assert _gap_type_to_block_type("missing_evidence") == "example"

    def test_unknown_type_defaults_to_argument(self):
        assert _gap_type_to_block_type("unknown") == "argument"
        assert _gap_type_to_block_type("") == "argument"


# ---------------------------------------------------------------------------
# Test __init__
# ---------------------------------------------------------------------------


class TestContentEnricherInit:
    def test_default_level_is_llm(self):
        """When ppt.enrich_level is missing, default to 'llm'."""
        with patch("src.ppt.content_enricher.create_llm_client") as mock_create:
            mock_create.return_value = MagicMock()
            enricher = ContentEnricher({"llm": {}})
            assert enricher.level == EnrichLevel.LLM

    def test_explicit_level_none(self, enricher_none):
        enricher, _ = enricher_none
        assert enricher.level == EnrichLevel.NONE

    def test_explicit_level_web(self, enricher_web):
        enricher, _ = enricher_web
        assert enricher.level == EnrichLevel.WEB


# ---------------------------------------------------------------------------
# Test _identify_gaps
# ---------------------------------------------------------------------------


class TestIdentifyGaps:
    def test_returns_valid_gaps(self, enricher_llm):
        """LLM returns valid gap analysis."""
        enricher, mock_client = enricher_llm
        cm = _make_content_map()

        gaps_json = json.dumps([
            {
                "topic": "市场规模数据",
                "gap_type": "missing_data",
                "search_query": "AI市场规模2024",
                "description": "缺少具体市场数据",
            },
            {
                "topic": "竞品分析",
                "gap_type": "missing_context",
                "search_query": "AI竞争格局",
                "description": "缺少竞品对比",
            },
        ])
        mock_client.chat.return_value = _mock_llm_response(gaps_json)

        gaps = enricher._identify_gaps(cm)
        assert len(gaps) == 2
        assert gaps[0]["topic"] == "市场规模数据"
        assert gaps[1]["search_query"] == "AI竞争格局"

    def test_returns_empty_for_complete_content(self, enricher_llm):
        """LLM indicates no gaps needed."""
        enricher, mock_client = enricher_llm
        cm = _make_content_map()

        mock_client.chat.return_value = _mock_llm_response("[]")
        gaps = enricher._identify_gaps(cm)
        assert gaps == []

    def test_returns_empty_for_garbage_response(self, enricher_llm):
        """LLM returns garbage text."""
        enricher, mock_client = enricher_llm
        cm = _make_content_map()

        mock_client.chat.return_value = _mock_llm_response(
            "这不是JSON，只是随意的文本回复"
        )
        gaps = enricher._identify_gaps(cm)
        assert gaps == []

    def test_limits_to_5_gaps(self, enricher_llm):
        """Even if LLM returns more than 5 gaps, only 5 are kept."""
        enricher, mock_client = enricher_llm
        cm = _make_content_map()

        many_gaps = [
            {
                "topic": f"Gap {i}",
                "gap_type": "missing_data",
                "search_query": f"query {i}",
                "description": f"desc {i}",
            }
            for i in range(8)
        ]
        mock_client.chat.return_value = _mock_llm_response(
            json.dumps(many_gaps)
        )
        gaps = enricher._identify_gaps(cm)
        assert len(gaps) == 5

    def test_filters_gaps_without_search_query(self, enricher_llm):
        """Gaps without search_query are filtered out."""
        enricher, mock_client = enricher_llm
        cm = _make_content_map()

        gaps_json = json.dumps([
            {
                "topic": "有效缺口",
                "gap_type": "missing_data",
                "search_query": "有效查询",
                "description": "有效描述",
            },
            {
                "topic": "无效缺口",
                "gap_type": "missing_data",
                "search_query": "",
                "description": "没有搜索词",
            },
            {
                "topic": "也无效",
                "gap_type": "missing_data",
                "description": "完全没有search_query字段",
            },
        ])
        mock_client.chat.return_value = _mock_llm_response(gaps_json)
        gaps = enricher._identify_gaps(cm)
        assert len(gaps) == 1
        assert gaps[0]["topic"] == "有效缺口"

    def test_handles_json_wrapped_in_object(self, enricher_llm):
        """LLM returns gaps inside a wrapper object (json_mode behavior)."""
        enricher, mock_client = enricher_llm
        cm = _make_content_map()

        wrapped = json.dumps({
            "gaps": [
                {
                    "topic": "数据缺口",
                    "gap_type": "missing_data",
                    "search_query": "query",
                    "description": "desc",
                }
            ]
        })
        mock_client.chat.return_value = _mock_llm_response(wrapped)
        gaps = enricher._identify_gaps(cm)
        assert len(gaps) == 1


# ---------------------------------------------------------------------------
# Test _llm_research
# ---------------------------------------------------------------------------


class TestLLMResearch:
    def test_produces_valid_content_blocks(self, enricher_llm):
        """_llm_research returns ContentBlocks with is_external=True."""
        enricher, mock_client = enricher_llm
        cm = _make_content_map(num_blocks=3)

        gaps = [
            {
                "topic": "市场规模",
                "gap_type": "missing_data",
                "search_query": "AI市场规模",
                "description": "缺数据",
            },
            {
                "topic": "行业趋势",
                "gap_type": "missing_context",
                "search_query": "AI趋势",
                "description": "缺背景",
            },
        ]

        mock_client.chat.return_value = _mock_llm_response(
            json.dumps({
                "title": "AI市场规模报告",
                "summary": "全球AI市场预计2025年达到5000亿美元",
                "source_text": "基于公开行业数据",
            })
        )

        blocks = enricher._llm_research(gaps, cm)
        assert len(blocks) == 2

        for block in blocks:
            assert block.is_external is True
            assert block.importance == 3
            assert block.block_id.startswith("ext_")

        # First block should be ext_4 (3 existing + 1)
        assert blocks[0].block_id == "ext_4"
        assert blocks[1].block_id == "ext_5"

    def test_skips_gap_when_llm_returns_null(self, enricher_llm):
        """If LLM returns null for a gap, skip it."""
        enricher, mock_client = enricher_llm
        cm = _make_content_map(num_blocks=2)

        gaps = [
            {
                "topic": "不确定的内容",
                "gap_type": "missing_data",
                "search_query": "query",
                "description": "desc",
            },
        ]

        mock_client.chat.return_value = _mock_llm_response("null")
        blocks = enricher._llm_research(gaps, cm)
        assert blocks == []


# ---------------------------------------------------------------------------
# Test _llm_fill_gap
# ---------------------------------------------------------------------------


class TestLLMFillGap:
    def test_returns_content_block(self, enricher_llm):
        enricher, mock_client = enricher_llm
        cm = _make_content_map()

        gap = {
            "topic": "市场规模",
            "gap_type": "missing_data",
            "search_query": "AI市场2024",
            "description": "需要市场数据",
        }

        mock_client.chat.return_value = _mock_llm_response(
            json.dumps({
                "title": "全球AI市场数据",
                "summary": "2024年全球AI市场规模约4000亿美元，预计2030年超万亿",
                "source_text": "基于公开行业报告数据（IDC, Gartner）",
            })
        )

        block = enricher._llm_fill_gap(gap, cm, 5)
        assert block is not None
        assert block.block_id == "ext_5"
        assert block.block_type == "data"  # missing_data -> data
        assert block.is_external is True
        assert block.importance == 3
        assert "4000亿" in block.summary

    def test_returns_none_for_null_response(self, enricher_llm):
        """LLM returns null -> None."""
        enricher, mock_client = enricher_llm
        cm = _make_content_map()

        gap = {
            "topic": "不确定",
            "gap_type": "missing_data",
            "search_query": "q",
            "description": "d",
        }

        mock_client.chat.return_value = _mock_llm_response("null")
        block = enricher._llm_fill_gap(gap, cm, 1)
        assert block is None

    def test_returns_none_for_empty_title(self, enricher_llm):
        """If LLM returns obj without title, return None."""
        enricher, mock_client = enricher_llm
        cm = _make_content_map()

        gap = {
            "topic": "x",
            "gap_type": "missing_data",
            "search_query": "q",
            "description": "d",
        }

        mock_client.chat.return_value = _mock_llm_response(
            json.dumps({"title": "", "summary": "some", "source_text": "src"})
        )
        block = enricher._llm_fill_gap(gap, cm, 1)
        assert block is None

    def test_gap_type_maps_correctly(self, enricher_llm):
        """Different gap_types produce different block_types."""
        enricher, mock_client = enricher_llm
        cm = _make_content_map()

        response = _mock_llm_response(
            json.dumps({
                "title": "标题",
                "summary": "内容",
                "source_text": "来源",
            })
        )
        mock_client.chat.return_value = response

        # missing_context -> argument
        gap_ctx = {
            "topic": "t",
            "gap_type": "missing_context",
            "search_query": "q",
            "description": "d",
        }
        block = enricher._llm_fill_gap(gap_ctx, cm, 1)
        assert block is not None
        assert block.block_type == "argument"

        # missing_evidence -> example
        gap_evi = {
            "topic": "t",
            "gap_type": "missing_evidence",
            "search_query": "q",
            "description": "d",
        }
        block = enricher._llm_fill_gap(gap_evi, cm, 2)
        assert block is not None
        assert block.block_type == "example"


# ---------------------------------------------------------------------------
# Test _web_research
# ---------------------------------------------------------------------------


class TestWebResearch:
    def test_with_mocked_duckduckgo(self, enricher_web):
        """Web research with mocked duckduckgo_search."""
        enricher, mock_client = enricher_web
        cm = _make_content_map(num_blocks=2)

        gaps = [
            {
                "topic": "市场数据",
                "gap_type": "missing_data",
                "search_query": "AI市场2024",
                "description": "需要数据",
            }
        ]

        # Mock _search_web to return results
        mock_search_results = [
            {
                "title": "AI Market Report 2024",
                "snippet": "Global AI market reached $400B in 2024",
                "url": "https://example.com/ai-report",
            },
        ]

        # Mock LLM extraction from search results
        mock_client.chat.return_value = _mock_llm_response(
            json.dumps({
                "title": "AI市场规模",
                "summary": "全球AI市场2024年达4000亿美元",
                "source_text": "Global AI market reached $400B - example.com",
            })
        )

        with patch.object(
            enricher, "_search_web", return_value=mock_search_results
        ):
            blocks = enricher._web_research(gaps, cm)

        assert len(blocks) == 1
        assert blocks[0].is_external is True
        assert blocks[0].block_id == "ext_3"  # 2 existing + 1

    def test_fallback_to_llm_when_search_empty(self, enricher_web):
        """When web search returns nothing, fall back to LLM knowledge."""
        enricher, mock_client = enricher_web
        cm = _make_content_map(num_blocks=2)

        gaps = [
            {
                "topic": "obscure topic",
                "gap_type": "missing_data",
                "search_query": "very obscure query",
                "description": "need data",
            }
        ]

        mock_client.chat.return_value = _mock_llm_response(
            json.dumps({
                "title": "LLM补充数据",
                "summary": "根据已知信息补充",
                "source_text": "基于公开数据",
            })
        )

        with patch.object(enricher, "_search_web", return_value=[]):
            blocks = enricher._web_research(gaps, cm)

        assert len(blocks) == 1
        assert blocks[0].title == "LLM补充数据"

    def test_skips_gap_without_search_query(self, enricher_web):
        """Gaps with empty search_query are skipped."""
        enricher, mock_client = enricher_web
        cm = _make_content_map()

        gaps = [
            {
                "topic": "no query",
                "gap_type": "missing_data",
                "search_query": "",
                "description": "no query",
            }
        ]

        blocks = enricher._web_research(gaps, cm)
        assert blocks == []


# ---------------------------------------------------------------------------
# Test _search_web
# ---------------------------------------------------------------------------


class TestSearchWeb:
    def test_import_error_returns_empty(self, enricher_web):
        """When duckduckgo_search is not installed, return empty list."""
        enricher, _ = enricher_web

        with patch.dict("sys.modules", {"duckduckgo_search": None}):
            # Force reimport to trigger ImportError
            with patch(
                "builtins.__import__",
                side_effect=lambda name, *a, **kw: (
                    (_ for _ in ()).throw(ImportError("no module"))
                    if name == "duckduckgo_search"
                    else __import__(name, *a, **kw)
                ),
            ):
                results = enricher._search_web("test query")
                assert results == []

    def test_generic_exception_returns_empty(self, enricher_web):
        """When search raises an exception, return empty list."""
        enricher, _ = enricher_web

        mock_ddgs = MagicMock()
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.__enter__ = MagicMock(
            side_effect=RuntimeError("network error")
        )
        mock_ddgs.return_value = mock_ddgs_instance

        with patch.dict(
            "sys.modules",
            {"duckduckgo_search": MagicMock(DDGS=mock_ddgs)},
        ):
            results = enricher._search_web("test query")
            assert results == []


# ---------------------------------------------------------------------------
# Test _extract_from_search
# ---------------------------------------------------------------------------


class TestExtractFromSearch:
    def test_extracts_info_successfully(self, enricher_web):
        """LLM extracts useful info from search results."""
        enricher, mock_client = enricher_web

        gap = {
            "topic": "市场数据",
            "gap_type": "missing_data",
            "search_query": "AI市场",
            "description": "需要数据",
        }
        search_results = [
            {
                "title": "AI Report",
                "snippet": "AI market is $400B",
                "url": "https://example.com",
            }
        ]

        mock_client.chat.return_value = _mock_llm_response(
            json.dumps({
                "title": "AI市场报告",
                "summary": "全球AI市场规模达4000亿美元",
                "source_text": "AI Report - example.com",
            })
        )

        block = enricher._extract_from_search(gap, search_results, 10)
        assert block is not None
        assert block.block_id == "ext_10"
        assert block.block_type == "data"
        assert block.is_external is True
        assert "4000亿" in block.summary

    def test_returns_none_for_null_llm_response(self, enricher_web):
        """LLM says no useful info in search results."""
        enricher, mock_client = enricher_web

        gap = {
            "topic": "x",
            "gap_type": "missing_data",
            "search_query": "q",
            "description": "d",
        }
        search_results = [
            {"title": "Irrelevant", "snippet": "unrelated", "url": "x.com"}
        ]

        mock_client.chat.return_value = _mock_llm_response("null")
        block = enricher._extract_from_search(gap, search_results, 1)
        assert block is None

    def test_returns_none_for_empty_title(self, enricher_web):
        """LLM returns object without title."""
        enricher, mock_client = enricher_web

        gap = {"topic": "x", "gap_type": "missing_data"}
        search_results = [
            {"title": "R", "snippet": "s", "url": "u"}
        ]

        mock_client.chat.return_value = _mock_llm_response(
            json.dumps({"title": "", "summary": "some data"})
        )
        block = enricher._extract_from_search(gap, search_results, 1)
        assert block is None


# ---------------------------------------------------------------------------
# Test _merge
# ---------------------------------------------------------------------------


class TestMerge:
    def test_merges_blocks_correctly(self):
        """Original blocks + supplementary blocks are combined."""
        cm = _make_content_map(
            num_blocks=2,
            data_points=["原有数据点"],
            quotes=["原有引用"],
        )

        supplementary = [
            ContentBlock(
                block_id="ext_3",
                block_type="data",
                title="补充数据",
                summary="市场规模5000亿",
                source_text="来源标注",
                importance=3,
                is_external=True,
            ),
            ContentBlock(
                block_id="ext_4",
                block_type="argument",
                title="补充论据",
                summary="行业趋势分析",
                source_text="来源标注",
                importance=3,
                is_external=True,
            ),
        ]

        merged = ContentEnricher._merge(cm, supplementary)

        # Total blocks = 2 original + 2 supplementary
        assert len(merged.content_blocks) == 4
        assert merged.content_blocks[0].block_id == "b1"
        assert merged.content_blocks[2].block_id == "ext_3"
        assert merged.content_blocks[3].block_id == "ext_4"

        # Logical flow extended
        assert merged.logical_flow == ["b1", "b2", "ext_3", "ext_4"]

        # Data points extended (data block summary added)
        assert "原有数据点" in merged.key_data_points
        assert "市场规模5000亿" in merged.key_data_points
        # argument block summary NOT added to data_points
        assert "行业趋势分析" not in merged.key_data_points

        # Quotes preserved
        assert merged.key_quotes == ["原有引用"]

        # Thesis preserved
        assert merged.document_thesis == cm.document_thesis

    def test_preserves_original_when_no_supplementary(self):
        """Empty supplementary list just copies the original."""
        cm = _make_content_map(num_blocks=3)
        merged = ContentEnricher._merge(cm, [])

        assert len(merged.content_blocks) == 3
        assert merged.logical_flow == ["b1", "b2", "b3"]

    def test_external_blocks_marked_correctly(self):
        """is_external flag distinguishes origin."""
        cm = _make_content_map(num_blocks=1)
        supplementary = [
            ContentBlock(
                block_id="ext_2",
                block_type="example",
                title="案例",
                summary="外部案例",
                source_text="src",
                importance=3,
                is_external=True,
            ),
        ]

        merged = ContentEnricher._merge(cm, supplementary)

        # Original block has is_external=False (default)
        assert merged.content_blocks[0].is_external is False
        # Supplementary block has is_external=True
        assert merged.content_blocks[1].is_external is True


# ---------------------------------------------------------------------------
# Test enrich() end-to-end
# ---------------------------------------------------------------------------


class TestEnrich:
    def test_level_none_returns_unchanged(self, enricher_none):
        """Level NONE returns ContentMap as-is, no LLM calls."""
        enricher, mock_client = enricher_none
        cm = _make_content_map()

        result = enricher.enrich(cm, document_text="some text")

        assert result is cm  # Same object, not copied
        mock_client.chat.assert_not_called()

    def test_level_llm_calls_llm_research(self, enricher_llm):
        """Level LLM calls _identify_gaps then _llm_research."""
        enricher, mock_client = enricher_llm
        cm = _make_content_map(num_blocks=2)

        # First call: _identify_gaps
        # Second call: _llm_fill_gap
        mock_client.chat.side_effect = [
            # _identify_gaps response
            _mock_llm_response(
                json.dumps([
                    {
                        "topic": "gap1",
                        "gap_type": "missing_data",
                        "search_query": "query1",
                        "description": "desc1",
                    }
                ])
            ),
            # _llm_fill_gap response
            _mock_llm_response(
                json.dumps({
                    "title": "补充标题",
                    "summary": "补充内容50字以上的摘要信息",
                    "source_text": "基于公开数据",
                })
            ),
        ]

        result = enricher.enrich(cm)

        assert len(result.content_blocks) == 3  # 2 original + 1 enriched
        assert result.content_blocks[2].is_external is True
        assert mock_client.chat.call_count == 2

    def test_level_web_calls_web_research(self, enricher_web):
        """Level WEB calls _identify_gaps then _web_research."""
        enricher, mock_client = enricher_web
        cm = _make_content_map(num_blocks=2)

        # First call: _identify_gaps
        # Second call: _extract_from_search (or _llm_fill_gap)
        mock_client.chat.side_effect = [
            # _identify_gaps response
            _mock_llm_response(
                json.dumps([
                    {
                        "topic": "gap1",
                        "gap_type": "missing_data",
                        "search_query": "query1",
                        "description": "desc1",
                    }
                ])
            ),
            # _llm_fill_gap fallback (since _search_web returns [])
            _mock_llm_response(
                json.dumps({
                    "title": "补充",
                    "summary": "来自LLM知识",
                    "source_text": "基于公开数据",
                })
            ),
        ]

        # Mock _search_web to return empty (trigger LLM fallback)
        with patch.object(enricher, "_search_web", return_value=[]):
            result = enricher.enrich(cm)

        assert len(result.content_blocks) == 3
        assert result.content_blocks[2].is_external is True

    def test_no_gaps_returns_original(self, enricher_llm):
        """When no gaps are found, return original ContentMap."""
        enricher, mock_client = enricher_llm
        cm = _make_content_map()

        mock_client.chat.return_value = _mock_llm_response("[]")
        result = enricher.enrich(cm)

        # Should be the same content (no modifications)
        assert len(result.content_blocks) == len(cm.content_blocks)
        # Only one LLM call (identify_gaps)
        assert mock_client.chat.call_count == 1

    def test_empty_supplementary_returns_original(self, enricher_llm):
        """When gaps are found but LLM cannot fill them, return original."""
        enricher, mock_client = enricher_llm
        cm = _make_content_map()

        mock_client.chat.side_effect = [
            # _identify_gaps returns 1 gap
            _mock_llm_response(
                json.dumps([
                    {
                        "topic": "gap",
                        "gap_type": "missing_data",
                        "search_query": "q",
                        "description": "d",
                    }
                ])
            ),
            # _llm_fill_gap returns null (cannot fill)
            _mock_llm_response("null"),
        ]

        result = enricher.enrich(cm)
        assert len(result.content_blocks) == len(cm.content_blocks)


# ---------------------------------------------------------------------------
# Test backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_content_block_without_is_external(self):
        """ContentBlock created without is_external defaults to False."""
        block = ContentBlock(
            block_id="b1",
            block_type="argument",
            title="标题",
            summary="摘要",
            source_text="原文",
            importance=3,
        )
        assert block.is_external is False

    def test_content_block_with_is_external(self):
        """ContentBlock with explicit is_external=True."""
        block = ContentBlock(
            block_id="ext_1",
            block_type="data",
            title="外部数据",
            summary="外部摘要",
            source_text="来源",
            importance=3,
            is_external=True,
        )
        assert block.is_external is True

    def test_content_map_with_mixed_blocks(self):
        """ContentMap works with both internal and external blocks."""
        blocks = [
            ContentBlock(
                block_id="b1",
                block_type="thesis",
                title="论点",
                summary="核心观点",
                source_text="原文",
                importance=5,
            ),
            ContentBlock(
                block_id="ext_2",
                block_type="data",
                title="补充数据",
                summary="外部数据",
                source_text="搜索结果",
                importance=3,
                is_external=True,
            ),
        ]

        cm = ContentMap(
            document_thesis="主论点",
            content_blocks=blocks,
            logical_flow=["b1", "ext_2"],
        )

        assert len(cm.content_blocks) == 2
        assert cm.content_blocks[0].is_external is False
        assert cm.content_blocks[1].is_external is True

    def test_content_block_json_serialization(self):
        """is_external field survives JSON round-trip."""
        block = ContentBlock(
            block_id="ext_1",
            block_type="data",
            title="外部",
            summary="数据",
            source_text="来源",
            importance=3,
            is_external=True,
        )

        data = block.model_dump()
        assert data["is_external"] is True

        restored = ContentBlock.model_validate(data)
        assert restored.is_external is True

    def test_existing_content_extractor_not_affected(self):
        """ContentBlock from content_extractor (no is_external) still works."""
        # Simulates what ContentExtractor produces
        block = ContentBlock(
            block_id="b1",
            block_type="argument",
            title="提取内容",
            summary="提取的摘要信息",
            source_text="原文片段",
            importance=4,
        )
        assert block.is_external is False

        data = block.model_dump()
        assert "is_external" in data
        assert data["is_external"] is False
