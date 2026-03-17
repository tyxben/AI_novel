"""ContentCreator 单元测试"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.ppt.content_creator import (
    AI_BLACKLIST,
    ContentCreator,
    _AI_REPLACEMENTS,
    _LIMIT_BULLET,
    _LIMIT_TITLE,
)
from src.ppt.models import (
    ColumnItem,
    ContentBlock,
    ContentMap,
    DeckType,
    IconItem,
    ImageStrategy,
    LayoutType,
    PageRole,
    SlideContent,
    SlideOutline,
    TimelineStep,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_outline(
    page_number: int = 1,
    layout: LayoutType = LayoutType.TEXT_LEFT_IMAGE_RIGHT,
    title: str = "测试标题",
    key_points: list[str] | None = None,
) -> SlideOutline:
    return SlideOutline(
        page_number=page_number,
        slide_type=layout.value,
        layout=layout,
        title=title,
        key_points=key_points or ["要点A", "要点B"],
    )


def _mock_llm_response(data: dict) -> LLMResponse:
    return LLMResponse(content=json.dumps(data, ensure_ascii=False), model="test")


@pytest.fixture()
def creator():
    """Return a ContentCreator with a mocked LLM client."""
    with patch("src.ppt.content_creator.create_llm_client") as mock_factory:
        mock_llm = MagicMock()
        mock_factory.return_value = mock_llm
        cc = ContentCreator(config={"llm": {}})
        cc._mock_llm = mock_llm  # expose for per-test setup
        yield cc


# ---------------------------------------------------------------------------
# AI 味过滤测试
# ---------------------------------------------------------------------------


class TestFilterAITaste:
    def test_replaces_blacklisted_words(self):
        text = "我们需要赋能合作伙伴，形成闭环"
        result = ContentCreator._filter_ai_taste(text)
        assert "赋能" not in result
        assert "闭环" not in result
        assert "帮助" in result
        assert "完整流程" in result

    def test_handles_empty_string(self):
        assert ContentCreator._filter_ai_taste("") == ""

    def test_handles_none(self):
        assert ContentCreator._filter_ai_taste(None) is None

    def test_no_change_for_clean_text(self):
        text = "市场增长了30%，团队规模翻倍"
        assert ContentCreator._filter_ai_taste(text) == text

    def test_multiple_replacements(self):
        text = "底层逻辑决定了顶层设计的方法论"
        result = ContentCreator._filter_ai_taste(text)
        assert "底层逻辑" not in result
        assert "顶层设计" not in result
        assert "方法论" not in result
        assert "核心原理" in result
        assert "整体规划" in result

    def test_all_blacklist_words_have_replacements(self):
        for word in AI_BLACKLIST:
            assert word in _AI_REPLACEMENTS, (
                f"黑名单词 '{word}' 缺少替换映射"
            )


# ---------------------------------------------------------------------------
# 内容生成 - 不同布局类型
# ---------------------------------------------------------------------------


class TestCreateContentByLayout:
    def test_title_hero(self, creator):
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "AI驱动创新",
                "subtitle": "从数据到决策的全新路径",
                "speaker_notes": "欢迎来到今天的分享...",
            }
        )
        outlines = [_make_outline(layout=LayoutType.TITLE_HERO, title="封面")]
        results = creator.create("测试文档内容", outlines)
        assert len(results) == 1
        assert results[0].title == "AI驱动创新"
        assert results[0].subtitle == "从数据到决策的全新路径"
        assert results[0].speaker_notes

    def test_section_divider(self, creator):
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {"title": "市场分析", "speaker_notes": "接下来看看市场数据..."}
        )
        outlines = [_make_outline(layout=LayoutType.SECTION_DIVIDER)]
        results = creator.create("文档", outlines)
        assert results[0].title == "市场分析"

    def test_text_left_image_right(self, creator):
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "市场规模增长30%",
                "bullet_points": ["规模达500亿", "同比增长30%", "预计突破650亿"],
                "speaker_notes": "这张图展示了...",
            }
        )
        outlines = [_make_outline(layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT)]
        results = creator.create("文档", outlines)
        assert len(results[0].bullet_points) == 3
        assert "500亿" in results[0].bullet_points[0]

    def test_data_highlight(self, creator):
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "核心增长",
                "data_value": "30%",
                "data_label": "年增长率",
                "data_description": "超出行业平均水平2倍",
                "speaker_notes": "这个数字说明...",
            }
        )
        outlines = [_make_outline(layout=LayoutType.DATA_HIGHLIGHT)]
        results = creator.create("文档", outlines)
        assert results[0].data_value == "30%"
        assert results[0].data_label == "年增长率"
        assert results[0].data_description

    def test_quote_page(self, creator):
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "核心观点",
                "quote": "最好的产品是用户自己想要的",
                "quote_author": "张三",
                "speaker_notes": "这句话非常重要...",
            }
        )
        outlines = [_make_outline(layout=LayoutType.QUOTE_PAGE)]
        results = creator.create("文档", outlines)
        assert results[0].quote == "最好的产品是用户自己想要的"
        assert results[0].quote_author == "张三"

    def test_three_columns(self, creator):
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "三大优势",
                "columns": [
                    {"subtitle": "速度快", "description": "处理速度提升3倍"},
                    {"subtitle": "成本低", "description": "降低运营成本40%"},
                    {"subtitle": "质量高", "description": "错误率下降到0.1%"},
                ],
                "speaker_notes": "分别来看...",
            }
        )
        outlines = [_make_outline(layout=LayoutType.THREE_COLUMNS)]
        results = creator.create("文档", outlines)
        assert len(results[0].columns) == 3
        assert results[0].columns[0].subtitle == "速度快"

    def test_timeline(self, creator):
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "发展历程",
                "steps": [
                    {"label": "2022 Q1", "description": "项目启动"},
                    {"label": "2022 Q3", "description": "产品上线"},
                    {"label": "2023 Q1", "description": "用户突破100万"},
                ],
                "speaker_notes": "回顾这段历程...",
            }
        )
        outlines = [_make_outline(layout=LayoutType.TIMELINE)]
        results = creator.create("文档", outlines)
        assert len(results[0].steps) == 3
        assert results[0].steps[0].label == "2022 Q1"

    def test_bullet_with_icons(self, creator):
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "核心功能",
                "icon_items": [
                    {"icon_keyword": "chart", "text": "数据分析"},
                    {"icon_keyword": "shield", "text": "安全防护"},
                    {"icon_keyword": "rocket", "text": "快速部署"},
                ],
                "speaker_notes": "这些功能...",
            }
        )
        outlines = [_make_outline(layout=LayoutType.BULLET_WITH_ICONS)]
        results = creator.create("文档", outlines)
        assert len(results[0].icon_items) == 3
        assert results[0].icon_items[0].icon_keyword == "chart"

    def test_comparison(self, creator):
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "方案对比",
                "left_title": "方案A",
                "left_items": ["成本低", "速度快", "扩展性一般"],
                "right_title": "方案B",
                "right_items": ["成本较高", "速度适中", "扩展性强"],
                "speaker_notes": "两个方案各有优劣...",
            }
        )
        outlines = [_make_outline(layout=LayoutType.COMPARISON)]
        results = creator.create("文档", outlines)
        assert results[0].left_title == "方案A"
        assert len(results[0].left_items) == 3

    def test_closing(self, creator):
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "谢谢",
                "subtitle": "期待合作",
                "contact_info": "email@example.com",
                "speaker_notes": "感谢大家的时间...",
            }
        )
        outlines = [_make_outline(layout=LayoutType.CLOSING)]
        results = creator.create("文档", outlines)
        assert results[0].contact_info == "email@example.com"

    def test_full_image_overlay(self, creator):
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "改变未来",
                "body_text": "科技让一切成为可能",
                "speaker_notes": "这张图想传达...",
            }
        )
        outlines = [_make_outline(layout=LayoutType.FULL_IMAGE_OVERLAY)]
        results = creator.create("文档", outlines)
        assert results[0].body_text == "科技让一切成为可能"


# ---------------------------------------------------------------------------
# 边界条件
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_text(self, creator):
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "默认标题",
                "bullet_points": ["要点1"],
                "speaker_notes": "备注",
            }
        )
        outlines = [_make_outline()]
        results = creator.create("", outlines)
        assert len(results) == 1
        assert results[0].title == "默认标题"

    def test_very_long_text(self, creator):
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "长文档总结",
                "bullet_points": ["核心观点"],
                "speaker_notes": "备注",
            }
        )
        long_text = "这是一段很长的文字。\n\n" * 5000
        outlines = [_make_outline()]
        results = creator.create(long_text, outlines)
        assert len(results) == 1

    def test_llm_returns_invalid_json(self, creator):
        """LLM 返回非 JSON 时应兜底到大纲信息。"""
        creator._mock_llm.chat.return_value = LLMResponse(
            content="这不是JSON", model="test"
        )
        outlines = [
            _make_outline(title="兜底标题", key_points=["兜底要点"])
        ]
        results = creator.create("文档", outlines)
        assert results[0].title == "兜底标题"
        assert results[0].bullet_points == ["兜底要点"]

    def test_llm_raises_exception(self, creator):
        """LLM 调用抛异常时应兜底。"""
        creator._mock_llm.chat.side_effect = RuntimeError("API 挂了")
        outlines = [_make_outline(title="异常兜底")]
        results = creator.create("文档", outlines)
        assert results[0].title == "异常兜底"

    def test_multiple_slides(self, creator):
        """测试多页批量生成。"""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "批量页面",
                "bullet_points": ["要点"],
                "speaker_notes": "备注",
            }
        )
        outlines = [_make_outline(page_number=i) for i in range(1, 6)]
        results = creator.create("文档内容" * 100, outlines)
        assert len(results) == 5
        assert creator._mock_llm.chat.call_count == 5

    def test_long_bullet_condensed_not_truncated(self, creator):
        """超长要点应被智能精炼（而非硬截断），保持语义完整。"""
        # 多句话的长要点 -> 规则精炼会取前几句
        long_bullet = "市场规模达到500亿。同比增长30%。预计明年突破650亿。这是非常重要的里程碑。我们需要进一步扩展业务。"
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "标题",
                "bullet_points": [long_bullet],
                "speaker_notes": "备注",
            }
        )
        outlines = [_make_outline()]
        results = creator.create("文档", outlines)
        result_bp = results[0].bullet_points[0]
        assert len(result_bp) <= _LIMIT_BULLET
        # 规则精炼应以句号结尾（取完整句），不应有断字
        assert result_bp.endswith("。") or result_bp.endswith("...")

    def test_ai_taste_filtered_in_output(self, creator):
        """输出中的 AI 味词汇应被替换。"""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "赋能合作伙伴",
                "bullet_points": ["打通全链路", "形成闭环"],
                "speaker_notes": "底层逻辑是这样的...",
            }
        )
        outlines = [_make_outline()]
        results = creator.create("文档", outlines)
        assert "赋能" not in results[0].title
        assert "全链路" not in results[0].bullet_points[0]
        assert "闭环" not in results[0].bullet_points[1]
        assert "底层逻辑" not in results[0].speaker_notes

    def test_bullet_points_max_five(self, creator):
        """最多返回5条要点。"""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "标题",
                "bullet_points": [f"要点{i}" for i in range(10)],
                "speaker_notes": "备注",
            }
        )
        outlines = [_make_outline()]
        results = creator.create("文档", outlines)
        assert len(results[0].bullet_points) <= 5


# ---------------------------------------------------------------------------
# 文本精炼测试
# ---------------------------------------------------------------------------


class TestCondense:
    """Test _condense (rule-based condensing)."""

    def test_short_text_unchanged(self):
        result = ContentCreator._condense("短文本", 20)
        assert result == "短文本"

    def test_empty_text(self):
        assert ContentCreator._condense("", 10) == ""

    def test_none_text(self):
        assert ContentCreator._condense(None, 10) is None

    def test_multi_sentence_takes_first(self):
        text = "第一句话。第二句话很长很长。第三句话。"
        result = ContentCreator._condense(text, 15)
        assert result is not None
        assert len(result) <= 15
        assert "第一句话。" in result

    def test_comma_separated_takes_first_clauses(self):
        text = "这是一个很长的句子，有很多分句，还有更多的分句，以及最后的分句"
        result = ContentCreator._condense(text, 20)
        assert result is not None
        assert len(result) <= 20
        assert result.endswith("...")

    def test_single_long_sentence_returns_none(self):
        """无法用规则精炼的长句应返回 None。"""
        text = "这是一个没有任何标点的超级长句子不包含逗号句号等分隔符号啊啊啊啊啊啊啊啊"
        result = ContentCreator._condense(text, 10)
        assert result is None

    def test_exclamation_mark_splits(self):
        text = "太棒了！成绩非常优秀！继续努力！"
        result = ContentCreator._condense(text, 10)
        assert result is not None
        assert "太棒了！" in result


class TestSummarize:
    """Test _summarize (LLM-based condensing)."""

    def test_short_text_no_llm_call(self, creator):
        result = creator._summarize("短文本", 20)
        assert result == "短文本"
        creator._mock_llm.chat.assert_not_called()

    def test_calls_llm_for_long_text(self, creator):
        creator._mock_llm.chat.return_value = LLMResponse(
            content="精炼后的结果", model="test"
        )
        result = creator._summarize("这是一段超长文本" * 20, 15)
        assert result == "精炼后的结果"
        creator._mock_llm.chat.assert_called_once()

    def test_safety_net_truncation(self, creator):
        """LLM 输出仍然超长时，最终安全网截断。"""
        creator._mock_llm.chat.return_value = LLMResponse(
            content="这段LLM输出比预期长很多很多很多", model="test"
        )
        result = creator._summarize("原文很长" * 50, 10)
        assert len(result) <= 10


class TestSmartTrim:
    """Test _smart_trim (condense -> summarize fallback)."""

    def test_short_text_no_processing(self, creator):
        result = creator._smart_trim("OK", 50)
        assert result == "OK"
        creator._mock_llm.chat.assert_not_called()

    def test_rule_condensable_no_llm(self, creator):
        """多句文本可被规则精炼，不需要调用 LLM。"""
        text = "第一句。第二句很长很长。第三句。"
        result = creator._smart_trim(text, 10)
        assert len(result) <= 10
        creator._mock_llm.chat.assert_not_called()

    def test_falls_back_to_llm(self, creator):
        """规则处理不了的长文本应调用 LLM。"""
        creator._mock_llm.chat.return_value = LLMResponse(
            content="LLM精炼", model="test"
        )
        text = "这是一个没有任何标点的超级长句子不包含分隔符号啊啊啊啊啊啊"
        result = creator._smart_trim(text, 10)
        assert result == "LLM精炼"
        creator._mock_llm.chat.assert_called_once()


# ---------------------------------------------------------------------------
# 相关文本提取
# ---------------------------------------------------------------------------


class TestExtractRelevantChunk:
    def test_splits_by_double_newline(self):
        text = "段落一\n\n段落二\n\n段落三\n\n段落四"
        chunk = ContentCreator._extract_relevant_chunk(text, 1, 4)
        assert "段落一" in chunk

    def test_returns_truncated_for_long_text(self):
        text = ("长段落" * 1000 + "\n\n") * 10
        chunk = ContentCreator._extract_relevant_chunk(text, 1, 2)
        assert len(chunk) <= 2000

    def test_empty_text_returns_empty(self):
        assert ContentCreator._extract_relevant_chunk("", 1, 5) == ""


# ---------------------------------------------------------------------------
# ContentMap 辅助工厂
# ---------------------------------------------------------------------------


def _make_content_block(
    block_id: str = "b1",
    block_type: str = "argument",
    title: str = "测试块标题",
    summary: str = "这是摘要信息",
    source_text: str = "这是原文片段，包含具体事实和数据。",
    importance: int = 3,
) -> ContentBlock:
    return ContentBlock(
        block_id=block_id,
        block_type=block_type,
        title=title,
        summary=summary,
        source_text=source_text,
        importance=importance,
    )


def _make_content_map(
    blocks: list[ContentBlock] | None = None,
    thesis: str = "文档核心论点",
) -> ContentMap:
    if blocks is None:
        blocks = [
            _make_content_block("b1", "thesis", "核心论点", "摘要1", "原文1"),
            _make_content_block("b2", "data", "数据支撑", "摘要2", "原文2：市场规模500亿"),
            _make_content_block("b3", "example", "案例分析", "摘要3", "原文3：某公司增长30%"),
        ]
    return ContentMap(
        document_thesis=thesis,
        content_blocks=blocks,
        logical_flow=[b.block_id for b in blocks],
        key_data_points=["市场规模500亿"],
        key_quotes=["成功的关键在于执行力"],
    )


def _make_outline_with_blocks(
    page_number: int = 2,
    layout: LayoutType = LayoutType.TEXT_LEFT_IMAGE_RIGHT,
    title: str = "测试标题",
    key_points: list[str] | None = None,
    content_block_ids: list[str] | None = None,
) -> SlideOutline:
    """Create a SlideOutline, then monkey-patch content_block_ids onto it."""
    outline = SlideOutline(
        page_number=page_number,
        slide_type=layout.value,
        layout=layout,
        title=title,
        key_points=key_points or ["要点A", "要点B"],
    )
    # SlideOutline may not yet have content_block_ids as a field;
    # we attach it as an attribute so getattr() in the creator picks it up.
    if content_block_ids is not None:
        object.__setattr__(outline, "content_block_ids", content_block_ids)
    return outline


# ---------------------------------------------------------------------------
# _build_context_from_blocks 测试
# ---------------------------------------------------------------------------


class TestBuildContextFromBlocks:
    def test_basic_formatting(self):
        """Each block should be formatted with type, title, summary, source."""
        cmap = _make_content_map()
        result = ContentCreator._build_context_from_blocks(cmap, ["b1", "b2"])
        assert "[thesis]" in result
        assert "核心论点" in result
        assert "摘要1" in result
        assert "原文1" in result
        assert "[data]" in result
        assert "数据支撑" in result
        assert "原文2" in result

    def test_preserves_order(self):
        """Blocks should appear in the order of block_ids, not content_map order."""
        cmap = _make_content_map()
        result = ContentCreator._build_context_from_blocks(cmap, ["b3", "b1"])
        idx_b3 = result.index("[example]")
        idx_b1 = result.index("[thesis]")
        assert idx_b3 < idx_b1

    def test_missing_block_ids_skipped(self):
        """Non-existent block IDs are silently skipped."""
        cmap = _make_content_map()
        result = ContentCreator._build_context_from_blocks(
            cmap, ["b1", "nonexistent", "b3"]
        )
        assert "[thesis]" in result
        assert "[example]" in result
        assert "nonexistent" not in result

    def test_all_block_ids_missing_returns_thesis(self):
        """When every block_id is invalid, return document thesis as fallback."""
        cmap = _make_content_map(thesis="AI改变教育的未来")
        result = ContentCreator._build_context_from_blocks(
            cmap, ["no_such_id", "also_missing"]
        )
        assert "AI改变教育的未来" in result

    def test_empty_block_ids_returns_thesis(self):
        """Empty block_ids list returns thesis fallback."""
        cmap = _make_content_map(thesis="核心论点XYZ")
        result = ContentCreator._build_context_from_blocks(cmap, [])
        assert "核心论点XYZ" in result

    def test_single_block(self):
        """Single block should produce clean output."""
        cmap = _make_content_map()
        result = ContentCreator._build_context_from_blocks(cmap, ["b2"])
        assert "[data]" in result
        assert "数据支撑" in result
        # Should NOT contain other blocks
        assert "[thesis]" not in result
        assert "[example]" not in result


# ---------------------------------------------------------------------------
# ContentMap 集成到 create() / _create_single_slide 的测试
# ---------------------------------------------------------------------------


class TestContentMapIntegration:
    def test_create_with_content_map_uses_blocks(self, creator):
        """When content_map + content_block_ids are provided, the LLM prompt
        should receive block-based context instead of position-based chunks."""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "数据支撑",
                "bullet_points": ["市场规模500亿", "增长30%"],
                "speaker_notes": "来看数据...",
            }
        )
        cmap = _make_content_map()
        outline = _make_outline_with_blocks(
            content_block_ids=["b1", "b2"],
        )
        results = creator.create("原始长文本" * 100, [outline], content_map=cmap)
        assert len(results) == 1
        # Verify that the LLM prompt contains block content, not position-based
        call_args = creator._mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "精准提取的内容块" in user_msg
        assert "核心论点" in user_msg  # block b1 title
        assert "数据支撑" in user_msg  # block b2 title

    def test_create_without_content_map_uses_position(self, creator):
        """When content_map is None, fall back to position-based extraction."""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "标题",
                "bullet_points": ["要点"],
                "speaker_notes": "备注",
            }
        )
        outline = _make_outline(page_number=2)
        results = creator.create("原始文本\n\n第二段\n\n第三段", [outline])
        assert len(results) == 1
        call_args = creator._mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "原文相关片段" in user_msg

    def test_create_with_content_map_but_no_block_ids(self, creator):
        """When content_map is provided but outline has no content_block_ids,
        fall back to position-based extraction."""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "标题",
                "bullet_points": ["要点"],
                "speaker_notes": "备注",
            }
        )
        cmap = _make_content_map()
        outline = _make_outline(page_number=2)  # no content_block_ids
        results = creator.create("文本\n\n段落二", [outline], content_map=cmap)
        assert len(results) == 1
        call_args = creator._mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "原文相关片段" in user_msg

    def test_create_with_content_map_empty_block_ids(self, creator):
        """Empty content_block_ids list should also fall back to position-based."""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "标题",
                "bullet_points": ["要点"],
                "speaker_notes": "备注",
            }
        )
        cmap = _make_content_map()
        outline = _make_outline_with_blocks(content_block_ids=[])
        results = creator.create("文本", [outline], content_map=cmap)
        assert len(results) == 1
        call_args = creator._mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "原文相关片段" in user_msg

    def test_backward_compat_existing_tests_still_pass(self, creator):
        """Verify create() still works with the old 2-arg signature."""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "兼容测试",
                "bullet_points": ["OK"],
                "speaker_notes": "notes",
            }
        )
        outlines = [_make_outline()]
        # Old-style call: create(text, outlines) without content_map
        results = creator.create("文档内容", outlines)
        assert len(results) == 1
        assert results[0].title == "兼容测试"

    def test_mixed_slides_some_with_blocks(self, creator):
        """In a multi-slide deck, some slides may have content_block_ids
        and others may not. Each should use the appropriate context path."""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "标题",
                "bullet_points": ["要点"],
                "speaker_notes": "备注",
            }
        )
        cmap = _make_content_map()
        slide_with_blocks = _make_outline_with_blocks(
            page_number=2, content_block_ids=["b1"]
        )
        slide_without_blocks = _make_outline(page_number=3)
        results = creator.create(
            "文档正文" * 50,
            [slide_with_blocks, slide_without_blocks],
            content_map=cmap,
        )
        assert len(results) == 2
        # First call (slide with blocks): should use block context
        first_call_user_msg = creator._mock_llm.chat.call_args_list[0][0][0][1]["content"]
        assert "精准提取的内容块" in first_call_user_msg
        # Second call (slide without blocks): should use position-based
        second_call_user_msg = creator._mock_llm.chat.call_args_list[1][0][0][1]["content"]
        assert "原文相关片段" in second_call_user_msg

    def test_nonexistent_block_ids_graceful_fallback(self, creator):
        """When content_block_ids reference non-existent blocks,
        _build_context_from_blocks returns thesis as minimal context;
        the LLM still gets called and produces output."""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "兜底结果",
                "bullet_points": ["来自兜底"],
                "speaker_notes": "备注",
            }
        )
        cmap = _make_content_map(thesis="这是文档核心论点")
        outline = _make_outline_with_blocks(
            content_block_ids=["nonexistent_1", "nonexistent_2"]
        )
        results = creator.create("文本", [outline], content_map=cmap)
        assert len(results) == 1
        assert results[0].title == "兜底结果"
        # The prompt should contain the thesis as fallback context
        call_args = creator._mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "这是文档核心论点" in user_msg


# ---------------------------------------------------------------------------
# _build_system_prompt 测试
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    """Test mode-specific system prompt generation."""

    def test_business_report_style(self, creator):
        """BUSINESS_REPORT deck_type should produce management-oriented prompt."""
        outline = _make_outline()
        prompt = creator._build_system_prompt(DeckType.BUSINESS_REPORT, outline)
        assert "管理层" in prompt
        assert "结论优先" in prompt
        assert "用事实句" in prompt
        assert "少形容词" in prompt
        assert "行动导向" in prompt
        assert "完成率85%" in prompt  # positive example
        assert "进展顺利" in prompt  # negative example

    def test_course_lecture_style(self, creator):
        """COURSE_LECTURE deck_type should produce teaching-oriented prompt."""
        outline = _make_outline()
        prompt = creator._build_system_prompt(DeckType.COURSE_LECTURE, outline)
        assert "学员" in prompt
        assert "术语必须解释" in prompt
        assert "例子先行" in prompt
        assert "一页一个知识点" in prompt
        assert "递进关系" in prompt
        assert "缓存" in prompt  # positive example about caching analogy

    def test_product_intro_style(self, creator):
        """PRODUCT_INTRO deck_type should produce customer-facing prompt."""
        outline = _make_outline()
        prompt = creator._build_system_prompt(DeckType.PRODUCT_INTRO, outline)
        assert "潜在客户" in prompt
        assert "用户价值" in prompt
        assert "功能对应收益" in prompt
        assert "场景化表达" in prompt
        assert "数据说服" in prompt
        assert "节省60%时间" in prompt  # positive example

    def test_none_deck_type_uses_generic(self, creator):
        """deck_type=None should produce the generic style prompt."""
        outline = _make_outline()
        prompt = creator._build_system_prompt(None, outline)
        assert "简洁有力" in prompt
        assert "数据具体" in prompt
        assert "语言有温度" in prompt
        # Should NOT contain mode-specific content
        assert "管理层" not in prompt
        assert "学员" not in prompt
        assert "潜在客户" not in prompt

    def test_all_prompts_contain_blacklist(self, creator):
        """All deck types should include the AI blacklist."""
        outline = _make_outline()
        for deck_type in [None, DeckType.BUSINESS_REPORT, DeckType.COURSE_LECTURE, DeckType.PRODUCT_INTRO]:
            prompt = creator._build_system_prompt(deck_type, outline)
            assert "绝对不使用以下词汇" in prompt
            assert "赋能" in prompt  # first blacklist word

    def test_all_prompts_start_with_base(self, creator):
        """All deck types should start with the base role description."""
        outline = _make_outline()
        for deck_type in [None, DeckType.BUSINESS_REPORT, DeckType.COURSE_LECTURE, DeckType.PRODUCT_INTRO]:
            prompt = creator._build_system_prompt(deck_type, outline)
            assert prompt.startswith("你是一位顶尖的 PPT 文案撰写师。")

    def test_page_goal_appears_in_prompt(self, creator):
        """When outline has page_goal, it should appear in system prompt."""
        outline = SlideOutline(
            page_number=2,
            slide_type="text_left_image_right",
            layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            title="测试",
            page_goal="让读者理解市场现状",
        )
        prompt = creator._build_system_prompt(None, outline)
        assert "本页目标：让读者理解市场现状" in prompt

    def test_must_include_appears_in_prompt(self, creator):
        """When outline has must_include, items should appear in system prompt."""
        outline = SlideOutline(
            page_number=2,
            slide_type="text_left_image_right",
            layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            title="测试",
            must_include=["市场规模数据", "增长趋势"],
        )
        prompt = creator._build_system_prompt(None, outline)
        assert "本页必须包含" in prompt
        assert "市场规模数据" in prompt
        assert "增长趋势" in prompt

    def test_forbidden_content_appears_in_prompt(self, creator):
        """When outline has forbidden_content, items should appear in system prompt."""
        outline = SlideOutline(
            page_number=2,
            slide_type="text_left_image_right",
            layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            title="测试",
            forbidden_content=["竞品名称", "内部代号"],
        )
        prompt = creator._build_system_prompt(None, outline)
        assert "本页禁止出现" in prompt
        assert "竞品名称" in prompt
        assert "内部代号" in prompt

    def test_empty_page_goal_not_in_prompt(self, creator):
        """Empty page_goal should not produce a '本页目标' line."""
        outline = _make_outline()
        prompt = creator._build_system_prompt(None, outline)
        assert "本页目标" not in prompt

    def test_empty_must_include_not_in_prompt(self, creator):
        """Empty must_include should not produce a '本页必须包含' line."""
        outline = _make_outline()
        prompt = creator._build_system_prompt(None, outline)
        assert "本页必须包含" not in prompt

    def test_combined_constraints(self, creator):
        """page_goal + must_include + forbidden_content all present together."""
        outline = SlideOutline(
            page_number=3,
            slide_type="data_highlight",
            layout=LayoutType.DATA_HIGHLIGHT,
            title="数据页",
            page_goal="用一个数字震撼读者",
            must_include=["500亿市场规模"],
            forbidden_content=["竞品数据"],
        )
        prompt = creator._build_system_prompt(DeckType.BUSINESS_REPORT, outline)
        assert "管理层" in prompt  # business report style
        assert "本页目标：用一个数字震撼读者" in prompt
        assert "500亿市场规模" in prompt
        assert "竞品数据" in prompt


# ---------------------------------------------------------------------------
# _get_notes_instruction 测试
# ---------------------------------------------------------------------------


class TestGetNotesInstruction:
    """Test speaker notes instruction varies by deck_type."""

    def test_business_report_notes(self, creator):
        instruction = creator._get_notes_instruction(DeckType.BUSINESS_REPORT)
        assert "50-100字" in instruction
        assert "领导" in instruction

    def test_course_lecture_notes(self, creator):
        instruction = creator._get_notes_instruction(DeckType.COURSE_LECTURE)
        assert "200-300字" in instruction
        assert "怎么讲" in instruction
        assert "过渡语" in instruction

    def test_product_intro_notes(self, creator):
        instruction = creator._get_notes_instruction(DeckType.PRODUCT_INTRO)
        assert "100-200字" in instruction
        assert "感染力" in instruction
        assert "互动" in instruction

    def test_none_deck_type_notes(self, creator):
        instruction = creator._get_notes_instruction(None)
        assert "200-300字" in instruction
        assert "口语化" in instruction
        assert "听众" in instruction


# ---------------------------------------------------------------------------
# _get_page_role_hint 测试
# ---------------------------------------------------------------------------


class TestGetPageRoleHint:
    """Test page role hint generation."""

    def test_executive_summary_hint(self, creator):
        outline = SlideOutline(
            page_number=2,
            slide_type="text_left_image_right",
            layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            title="摘要",
            page_role=PageRole.EXECUTIVE_SUMMARY,
        )
        hint = creator._get_page_role_hint(outline)
        assert "摘要页" in hint
        assert "30秒" in hint

    def test_data_evidence_hint(self, creator):
        outline = SlideOutline(
            page_number=3,
            slide_type="data_highlight",
            layout=LayoutType.DATA_HIGHLIGHT,
            title="数据",
            page_role=PageRole.DATA_EVIDENCE,
        )
        hint = creator._get_page_role_hint(outline)
        assert "数据页" in hint

    def test_pain_point_hint(self, creator):
        outline = SlideOutline(
            page_number=4,
            slide_type="text_left_image_right",
            layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            title="痛点",
            page_role=PageRole.PAIN_POINT,
        )
        hint = creator._get_page_role_hint(outline)
        assert "痛点页" in hint
        assert "共鸣" in hint

    def test_knowledge_point_hint(self, creator):
        outline = SlideOutline(
            page_number=5,
            slide_type="text_left_image_right",
            layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            title="知识点",
            page_role=PageRole.KNOWLEDGE_POINT,
        )
        hint = creator._get_page_role_hint(outline)
        assert "知识点页" in hint
        assert "例子" in hint

    def test_no_page_role_returns_empty(self, creator):
        outline = _make_outline()
        hint = creator._get_page_role_hint(outline)
        assert hint == ""

    def test_all_page_roles_have_hints(self, creator):
        """Every PageRole enum value should have a corresponding hint."""
        for role in PageRole:
            outline = SlideOutline(
                page_number=1,
                slide_type="text_left_image_right",
                layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT,
                title="测试",
                page_role=role,
            )
            hint = creator._get_page_role_hint(outline)
            assert hint != "", f"PageRole.{role.name} has no hint"
            assert "页面角色提示" in hint


# ---------------------------------------------------------------------------
# DeckType 集成到 create() 的测试
# ---------------------------------------------------------------------------


class TestDeckTypeIntegration:
    """Test that deck_type is passed through create() to the LLM prompt."""

    def test_create_passes_deck_type_business_report(self, creator):
        """create() with deck_type=BUSINESS_REPORT should use business style."""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "月度报告",
                "bullet_points": ["完成3项交付"],
                "speaker_notes": "本月重点...",
            }
        )
        outlines = [_make_outline()]
        results = creator.create("文档", outlines, deck_type=DeckType.BUSINESS_REPORT)
        assert len(results) == 1
        # Verify system prompt contains business style
        call_args = creator._mock_llm.chat.call_args
        system_msg = call_args[0][0][0]["content"]
        assert "管理层" in system_msg
        assert "结论优先" in system_msg

    def test_create_passes_deck_type_course_lecture(self, creator):
        """create() with deck_type=COURSE_LECTURE should use teaching style."""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "缓存机制",
                "bullet_points": ["缓存原理"],
                "speaker_notes": "这一节我们来学...",
            }
        )
        outlines = [_make_outline()]
        results = creator.create("文档", outlines, deck_type=DeckType.COURSE_LECTURE)
        assert len(results) == 1
        call_args = creator._mock_llm.chat.call_args
        system_msg = call_args[0][0][0]["content"]
        assert "学员" in system_msg
        assert "术语必须解释" in system_msg

    def test_create_passes_deck_type_product_intro(self, creator):
        """create() with deck_type=PRODUCT_INTRO should use product style."""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "产品亮点",
                "bullet_points": ["节省60%时间"],
                "speaker_notes": "想象一下...",
            }
        )
        outlines = [_make_outline()]
        results = creator.create("文档", outlines, deck_type=DeckType.PRODUCT_INTRO)
        assert len(results) == 1
        call_args = creator._mock_llm.chat.call_args
        system_msg = call_args[0][0][0]["content"]
        assert "潜在客户" in system_msg
        assert "用户价值" in system_msg

    def test_create_without_deck_type_backward_compatible(self, creator):
        """create() without deck_type uses generic style (backward compat)."""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "标题",
                "bullet_points": ["要点"],
                "speaker_notes": "备注",
            }
        )
        outlines = [_make_outline()]
        # Old-style: no deck_type argument
        results = creator.create("文档", outlines)
        assert len(results) == 1
        call_args = creator._mock_llm.chat.call_args
        system_msg = call_args[0][0][0]["content"]
        assert "简洁有力" in system_msg
        assert "管理层" not in system_msg

    def test_notes_instruction_varies_by_deck_type(self, creator):
        """Speaker notes instruction in user_msg should change with deck_type."""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "标题",
                "bullet_points": ["要点"],
                "speaker_notes": "备注",
            }
        )
        outlines = [_make_outline()]

        # Business report: concise notes
        creator.create("文档", outlines, deck_type=DeckType.BUSINESS_REPORT)
        user_msg_biz = creator._mock_llm.chat.call_args[0][0][1]["content"]
        assert "50-100字" in user_msg_biz

        creator._mock_llm.chat.reset_mock()

        # Course lecture: detailed notes
        creator.create("文档", outlines, deck_type=DeckType.COURSE_LECTURE)
        user_msg_edu = creator._mock_llm.chat.call_args[0][0][1]["content"]
        assert "怎么讲" in user_msg_edu

        creator._mock_llm.chat.reset_mock()

        # Product intro: engaging notes
        creator.create("文档", outlines, deck_type=DeckType.PRODUCT_INTRO)
        user_msg_prod = creator._mock_llm.chat.call_args[0][0][1]["content"]
        assert "感染力" in user_msg_prod

    def test_page_role_hint_appears_in_user_msg(self, creator):
        """When outline has page_role, the hint should appear in user_msg."""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "摘要",
                "bullet_points": ["结论1"],
                "speaker_notes": "备注",
            }
        )
        outline = SlideOutline(
            page_number=2,
            slide_type="text_left_image_right",
            layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            title="执行摘要",
            page_role=PageRole.EXECUTIVE_SUMMARY,
        )
        creator.create("文档", [outline], deck_type=DeckType.BUSINESS_REPORT)
        user_msg = creator._mock_llm.chat.call_args[0][0][1]["content"]
        assert "页面角色提示" in user_msg
        assert "摘要页" in user_msg

    def test_deck_type_combined_with_content_map(self, creator):
        """deck_type should work alongside content_map."""
        creator._mock_llm.chat.return_value = _mock_llm_response(
            {
                "title": "标题",
                "bullet_points": ["要点"],
                "speaker_notes": "备注",
            }
        )
        cmap = _make_content_map()
        outline = _make_outline_with_blocks(content_block_ids=["b1"])
        results = creator.create(
            "文档", [outline], content_map=cmap, deck_type=DeckType.PRODUCT_INTRO
        )
        assert len(results) == 1
        call_args = creator._mock_llm.chat.call_args
        system_msg = call_args[0][0][0]["content"]
        user_msg = call_args[0][0][1]["content"]
        # Product intro style in system prompt
        assert "潜在客户" in system_msg
        # Content blocks used in user prompt
        assert "精准提取的内容块" in user_msg
