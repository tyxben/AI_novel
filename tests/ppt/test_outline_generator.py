"""大纲生成器测试"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.ppt.models import (
    Audience,
    ContentBlock,
    ContentMap,
    DeckType,
    DocumentAnalysis,
    DocumentType,
    ImageStrategy,
    LayoutType,
    PageRole,
    PresentationPlan,
    SlideOutline,
    SlideTask,
    Tone,
)
from src.ppt.outline_generator import OutlineGenerator


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_analysis(**overrides) -> DocumentAnalysis:
    """构造一个 DocumentAnalysis 对象。"""
    defaults = dict(
        theme="AI技术发展趋势",
        doc_type=DocumentType.TECH_SHARE,
        audience=Audience.TECHNICAL,
        tone=Tone.PROFESSIONAL,
        key_points=["大模型", "多模态", "开源社区"],
        has_sections=True,
        has_data=True,
        has_quotes=False,
        estimated_pages=15,
    )
    defaults.update(overrides)
    return DocumentAnalysis(**defaults)


def _make_content_map(**overrides) -> ContentMap:
    """构造一个 ContentMap 对象。"""
    defaults = dict(
        document_thesis="AI正在重塑各行各业，2024年将是大模型落地元年",
        content_blocks=[
            ContentBlock(
                block_id="b1",
                block_type="thesis",
                title="AI重塑行业",
                summary="人工智能正在深刻改变各行各业的运作方式",
                source_text="人工智能正在深刻改变各行各业",
                importance=5,
            ),
            ContentBlock(
                block_id="b2",
                block_type="data",
                title="市场规模",
                summary="全球AI市场规模预计达5.2万亿美元",
                source_text="据预测，2024年全球AI市场规模将达5.2万亿美元",
                importance=4,
            ),
            ContentBlock(
                block_id="b3",
                block_type="argument",
                title="大模型突破",
                summary="GPT-4等大模型在多项任务上超越人类水平",
                source_text="GPT-4等大模型在多项任务上超越人类水平",
                importance=4,
            ),
            ContentBlock(
                block_id="b4",
                block_type="quote",
                title="Gartner预言",
                summary="AI不是未来，AI就是现在",
                source_text="Gartner在2024年报告中指出：AI不是未来，AI就是现在",
                importance=3,
            ),
            ContentBlock(
                block_id="b5",
                block_type="example",
                title="医疗AI案例",
                summary="AI辅助诊断在皮肤癌检测中准确率达95%",
                source_text="在皮肤癌检测领域，AI辅助诊断准确率达95%",
                importance=2,
            ),
            ContentBlock(
                block_id="b6",
                block_type="conclusion",
                title="未来展望",
                summary="2025年AI将进一步渗透到日常生活的方方面面",
                source_text="展望未来，2025年AI将进一步渗透到日常生活的方方面面",
                importance=4,
            ),
        ],
        logical_flow=["b1", "b2", "b3", "b4", "b5", "b6"],
        key_data_points=["全球AI市场规模5.2万亿", "皮肤癌检测准确率95%"],
        key_quotes=["AI不是未来，AI就是现在 — Gartner 2024"],
    )
    defaults.update(overrides)
    return ContentMap(**defaults)


def _make_slides_json(n: int) -> list[dict]:
    """生成 n 页的合法大纲 JSON。"""
    layouts = [
        "text_left_image_right",
        "bullet_with_icons",
        "three_columns",
        "image_left_text_right",
        "data_highlight",
        "timeline",
    ]
    slides = []

    # 封面
    slides.append({
        "page_number": 1,
        "slide_type": "title_hero",
        "layout": "title_hero",
        "title": "AI技术发展趋势",
        "subtitle": "2024年度报告",
        "key_points": [],
        "needs_image": True,
        "image_prompt": "futuristic AI technology background, blue gradient, minimalist",
        "speaker_notes_hint": "欢迎各位",
    })

    # 中间页
    for i in range(1, n - 1):
        layout = layouts[i % len(layouts)]
        slides.append({
            "page_number": i + 1,
            "slide_type": layout,
            "layout": layout,
            "title": f"内容页 {i}",
            "subtitle": None,
            "key_points": [f"要点{j}" for j in range(1, 4)],
            "needs_image": layout in ("text_left_image_right", "image_left_text_right"),
            "image_prompt": "professional illustration" if layout in ("text_left_image_right", "image_left_text_right") else None,
            "speaker_notes_hint": f"第{i}页要传递的信息",
        })

    # 结尾
    slides.append({
        "page_number": n,
        "slide_type": "closing",
        "layout": "closing",
        "title": "谢谢",
        "subtitle": "欢迎提问",
        "key_points": [],
        "needs_image": False,
        "image_prompt": None,
        "speaker_notes_hint": "感谢大家",
    })

    return slides


def _make_slides_json_with_block_ids(n: int) -> list[dict]:
    """生成 n 页带 content_block_ids 的大纲 JSON。"""
    block_ids = ["b1", "b2", "b3", "b4", "b5", "b6"]
    layouts = [
        "text_left_image_right",
        "data_highlight",
        "bullet_with_icons",
        "quote_page",
        "image_left_text_right",
        "timeline",
    ]
    slides = []

    # 封面
    slides.append({
        "page_number": 1,
        "slide_type": "title_hero",
        "layout": "title_hero",
        "title": "AI 重塑一切",
        "subtitle": "2024年人工智能趋势",
        "key_points": ["AI正在重塑各行各业"],
        "content_block_ids": ["b1"],
        "needs_image": True,
        "image_prompt": "futuristic AI background",
        "speaker_notes_hint": "开场",
    })

    # 中间页
    for i in range(1, n - 1):
        layout = layouts[i % len(layouts)]
        bid_idx = i % len(block_ids)
        slides.append({
            "page_number": i + 1,
            "slide_type": layout,
            "layout": layout,
            "title": f"内容页 {i}",
            "subtitle": None,
            "key_points": [f"来自内容块的要点{j}" for j in range(1, 4)],
            "content_block_ids": [block_ids[bid_idx]],
            "needs_image": layout in ("text_left_image_right", "image_left_text_right"),
            "image_prompt": "professional illustration" if layout in ("text_left_image_right", "image_left_text_right") else None,
            "speaker_notes_hint": f"第{i}页信息",
        })

    # 结尾
    slides.append({
        "page_number": n,
        "slide_type": "closing",
        "layout": "closing",
        "title": "谢谢",
        "subtitle": "欢迎提问",
        "key_points": [],
        "content_block_ids": [],
        "needs_image": False,
        "image_prompt": None,
        "speaker_notes_hint": "结束",
    })

    return slides


def _make_llm_response(data) -> LLMResponse:
    return LLMResponse(content=json.dumps(data, ensure_ascii=False), model="test")


@pytest.fixture()
def generator():
    """创建 mock LLM 的 OutlineGenerator。"""
    with patch("src.ppt.outline_generator.create_llm_client") as mock_create:
        mock_llm = MagicMock()
        mock_create.return_value = mock_llm
        og = OutlineGenerator({"llm": {}})
        og._mock_llm = mock_llm
        yield og


# ---------------------------------------------------------------------------
# 正常流程
# ---------------------------------------------------------------------------


class TestGenerateHappyPath:
    """测试正常大纲生成。"""

    def test_basic_15_pages(self, generator: OutlineGenerator):
        """生成 15 页大纲。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json(15)
        )
        analysis = _make_analysis(estimated_pages=15)
        slides = generator.generate("测试文本" * 100, analysis)

        assert len(slides) == 15
        assert all(isinstance(s, SlideOutline) for s in slides)
        # 页码连续
        assert [s.page_number for s in slides] == list(range(1, 16))

    def test_8_pages(self, generator: OutlineGenerator):
        """生成 8 页大纲。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json(8)
        )
        analysis = _make_analysis(estimated_pages=8)
        slides = generator.generate("测试文本" * 50, analysis)
        assert len(slides) == 8

    def test_30_pages(self, generator: OutlineGenerator):
        """生成 30 页大纲。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json(30)
        )
        analysis = _make_analysis(estimated_pages=30)
        slides = generator.generate("测试文本" * 500, analysis)
        assert len(slides) == 30

    def test_max_pages_limits_output(self, generator: OutlineGenerator):
        """max_pages 限制实际页数。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json(10)
        )
        analysis = _make_analysis(estimated_pages=20)
        slides = generator.generate("测试文本" * 100, analysis, max_pages=10)
        # LLM 被请求生成 10 页（min(20, 10)）
        call_args = generator._mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "10 页" in user_msg

    def test_cover_is_title_hero(self, generator: OutlineGenerator):
        """第一页必须是 title_hero。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json(10)
        )
        slides = generator.generate("测试" * 100, _make_analysis(estimated_pages=10))
        assert slides[0].layout == LayoutType.TITLE_HERO

    def test_last_page_is_closing(self, generator: OutlineGenerator):
        """最后一页必须是 closing。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json(10)
        )
        slides = generator.generate("测试" * 100, _make_analysis(estimated_pages=10))
        assert slides[-1].layout == LayoutType.CLOSING


# ---------------------------------------------------------------------------
# _ensure_layout_diversity
# ---------------------------------------------------------------------------


class TestLayoutDiversity:
    """测试布局多样性保证。"""

    def test_no_three_consecutive_same_layout(self, generator: OutlineGenerator):
        """不连续 3 页使用相同布局。"""
        # 构造连续相同布局的数据
        slides_json = _make_slides_json(10)
        for i in range(1, 7):
            slides_json[i]["layout"] = "bullet_with_icons"
        generator._mock_llm.chat.return_value = _make_llm_response(slides_json)

        slides = generator.generate("测试" * 100, _make_analysis(estimated_pages=10))

        # 检查不连续 3 个相同布局
        for i in range(2, len(slides)):
            if slides[i].layout == slides[i - 1].layout:
                assert slides[i].layout != slides[i - 2].layout, (
                    f"页 {i - 1}, {i}, {i + 1} 连续使用 {slides[i].layout}"
                )

    def test_cover_forced_to_title_hero(self, generator: OutlineGenerator):
        """即使 LLM 返回错误封面类型，也强制为 title_hero。"""
        slides_json = _make_slides_json(8)
        slides_json[0]["layout"] = "bullet_with_icons"  # 错误的封面类型
        generator._mock_llm.chat.return_value = _make_llm_response(slides_json)

        slides = generator.generate("测试" * 100, _make_analysis(estimated_pages=8))
        assert slides[0].layout == LayoutType.TITLE_HERO
        assert slides[0].slide_type == "title_hero"

    def test_closing_forced_for_last_page(self, generator: OutlineGenerator):
        """即使 LLM 返回错误结尾类型，也强制为 closing。"""
        slides_json = _make_slides_json(8)
        slides_json[-1]["layout"] = "bullet_with_icons"
        generator._mock_llm.chat.return_value = _make_llm_response(slides_json)

        slides = generator.generate("测试" * 100, _make_analysis(estimated_pages=8))
        assert slides[-1].layout == LayoutType.CLOSING
        assert slides[-1].slide_type == "closing"

    def test_no_consecutive_section_dividers(self, generator: OutlineGenerator):
        """不连续出现两个 section_divider。"""
        slides_json = _make_slides_json(10)
        slides_json[2]["layout"] = "section_divider"
        slides_json[3]["layout"] = "section_divider"
        generator._mock_llm.chat.return_value = _make_llm_response(slides_json)

        slides = generator.generate("测试" * 100, _make_analysis(estimated_pages=10))

        for i in range(1, len(slides)):
            if slides[i].layout == LayoutType.SECTION_DIVIDER:
                assert slides[i - 1].layout != LayoutType.SECTION_DIVIDER

    def test_direct_call_ensure_layout_diversity(self, generator: OutlineGenerator):
        """直接调用 _ensure_layout_diversity 测试。"""
        slides = [
            SlideOutline(
                page_number=i + 1,
                slide_type="bullet_with_icons",
                layout=LayoutType.BULLET_WITH_ICONS,
                title=f"页 {i + 1}",
            )
            for i in range(8)
        ]

        result = generator._ensure_layout_diversity(slides)

        # 封面被强制为 title_hero
        assert result[0].layout == LayoutType.TITLE_HERO
        # 结尾被强制为 closing
        assert result[-1].layout == LayoutType.CLOSING
        # 中间不连续 3 个相同
        for i in range(2, len(result)):
            if result[i].layout == result[i - 1].layout:
                assert result[i].layout != result[i - 2].layout


# ---------------------------------------------------------------------------
# _ensure_rhythm
# ---------------------------------------------------------------------------


class TestRhythm:
    """测试节奏感保证。"""

    def test_no_three_consecutive_text_only(self, generator: OutlineGenerator):
        """不连续 3 个纯文字页。"""
        # 构造全是纯文字布局的页面
        text_layouts = [
            LayoutType.TITLE_HERO,
            LayoutType.BULLET_WITH_ICONS,
            LayoutType.THREE_COLUMNS,
            LayoutType.BULLET_WITH_ICONS,
            LayoutType.THREE_COLUMNS,
            LayoutType.BULLET_WITH_ICONS,
            LayoutType.THREE_COLUMNS,
            LayoutType.CLOSING,
        ]
        slides = [
            SlideOutline(
                page_number=i + 1,
                slide_type=lay.value,
                layout=lay,
                title=f"页 {i + 1}",
                needs_image=False,
            )
            for i, lay in enumerate(text_layouts)
        ]

        result = generator._ensure_rhythm(slides)

        # 检查不连续 3 个纯文字页
        consecutive_text = 0
        for slide in result[1:-1]:  # 跳过封面和结尾
            if generator._is_text_only(slide):
                consecutive_text += 1
            else:
                consecutive_text = 0
            assert consecutive_text < 3, (
                f"连续 {consecutive_text} 个纯文字页出现在第 {slide.page_number} 页"
            )

    def test_quote_pages_limited(self, generator: OutlineGenerator):
        """quote_page 不超过总页数的 10%。"""
        n = 20
        slides = [
            SlideOutline(
                page_number=1,
                slide_type="title_hero",
                layout=LayoutType.TITLE_HERO,
                title="封面",
                needs_image=True,
            )
        ]
        # 中间全是 quote_page
        for i in range(1, n - 1):
            slides.append(
                SlideOutline(
                    page_number=i + 1,
                    slide_type="quote_page",
                    layout=LayoutType.QUOTE_PAGE,
                    title=f"引用 {i}",
                )
            )
        slides.append(
            SlideOutline(
                page_number=n,
                slide_type="closing",
                layout=LayoutType.CLOSING,
                title="结束",
            )
        )

        result = generator._ensure_rhythm(slides)

        quote_count = sum(
            1 for s in result if s.layout == LayoutType.QUOTE_PAGE
        )
        max_allowed = max(1, n // 10)
        assert quote_count <= max_allowed, (
            f"quote_page 数量 {quote_count} 超过上限 {max_allowed}"
        )

    def test_data_highlight_not_consecutive(self, generator: OutlineGenerator):
        """data_highlight 不连续出现。"""
        slides = [
            SlideOutline(
                page_number=1,
                slide_type="title_hero",
                layout=LayoutType.TITLE_HERO,
                title="封面",
            ),
            SlideOutline(
                page_number=2,
                slide_type="data_highlight",
                layout=LayoutType.DATA_HIGHLIGHT,
                title="数据 1",
            ),
            SlideOutline(
                page_number=3,
                slide_type="data_highlight",
                layout=LayoutType.DATA_HIGHLIGHT,
                title="数据 2",
            ),
            SlideOutline(
                page_number=4,
                slide_type="data_highlight",
                layout=LayoutType.DATA_HIGHLIGHT,
                title="数据 3",
            ),
            SlideOutline(
                page_number=5,
                slide_type="closing",
                layout=LayoutType.CLOSING,
                title="结束",
            ),
        ]

        result = generator._ensure_rhythm(slides)

        for i in range(1, len(result)):
            if result[i].layout == LayoutType.DATA_HIGHLIGHT:
                assert result[i - 1].layout != LayoutType.DATA_HIGHLIGHT


# ---------------------------------------------------------------------------
# LLM 失败降级
# ---------------------------------------------------------------------------


class TestFallback:
    """测试 LLM 返回垃圾时的降级。"""

    def test_garbage_response_fallback(self, generator: OutlineGenerator):
        """LLM 返回非 JSON 时使用 fallback。"""
        generator._mock_llm.chat.return_value = LLMResponse(
            content="这不是有效的JSON", model="test"
        )

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(estimated_pages=10),
        )

        assert len(slides) == 10
        assert slides[0].layout == LayoutType.TITLE_HERO
        assert slides[-1].layout == LayoutType.CLOSING

    def test_empty_array_fallback(self, generator: OutlineGenerator):
        """LLM 返回空数组时使用 fallback。"""
        generator._mock_llm.chat.return_value = _make_llm_response([])

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(estimated_pages=12),
        )

        assert len(slides) == 12
        assert slides[0].layout == LayoutType.TITLE_HERO
        assert slides[-1].layout == LayoutType.CLOSING

    def test_partial_valid_slides(self, generator: OutlineGenerator):
        """部分页面解析失败时仍返回有效结果。"""
        slides_json = _make_slides_json(10)
        # 损坏几页
        slides_json[3] = {"invalid": True}
        slides_json[5] = "not a dict"
        generator._mock_llm.chat.return_value = _make_llm_response(slides_json)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(estimated_pages=10),
        )

        # 应该仍有大部分页面（丢弃2页，剩8页 >= 3 → 不触发 fallback）
        assert len(slides) >= 3
        assert slides[0].layout == LayoutType.TITLE_HERO
        assert slides[-1].layout == LayoutType.CLOSING

    def test_too_few_valid_slides_triggers_fallback(self, generator: OutlineGenerator):
        """有效页面不足 3 页时触发完整 fallback。"""
        slides_json = [{"invalid": True}, {"also_invalid": True}]
        generator._mock_llm.chat.return_value = _make_llm_response(slides_json)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(estimated_pages=8),
        )

        assert len(slides) == 8
        assert slides[0].layout == LayoutType.TITLE_HERO
        assert slides[-1].layout == LayoutType.CLOSING

    def test_invalid_layout_uses_default(self, generator: OutlineGenerator):
        """无效布局值时使用默认布局。"""
        slides_json = _make_slides_json(8)
        slides_json[2]["layout"] = "nonexistent_layout"
        generator._mock_llm.chat.return_value = _make_llm_response(slides_json)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(estimated_pages=8),
        )

        # 不应崩溃
        assert len(slides) == 8
        # 无效布局应被替换为 bullet_with_icons
        assert slides[2].layout == LayoutType.BULLET_WITH_ICONS


# ---------------------------------------------------------------------------
# 页码
# ---------------------------------------------------------------------------


class TestPageNumbering:
    """测试页码正确性。"""

    def test_page_numbers_sequential(self, generator: OutlineGenerator):
        """页码从1开始连续。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json(12)
        )
        slides = generator.generate(
            "测试" * 100,
            _make_analysis(estimated_pages=12),
        )
        assert [s.page_number for s in slides] == list(range(1, 13))

    def test_page_numbers_after_diversity_fix(self, generator: OutlineGenerator):
        """布局修正后页码仍然连续。"""
        # 全部用相同布局
        slides_json = _make_slides_json(10)
        for s in slides_json[1:-1]:
            s["layout"] = "bullet_with_icons"
        generator._mock_llm.chat.return_value = _make_llm_response(slides_json)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(estimated_pages=10),
        )
        assert [s.page_number for s in slides] == list(range(1, 11))


# ---------------------------------------------------------------------------
# LLM 调用参数
# ---------------------------------------------------------------------------


class TestLLMCallParams:
    """测试 LLM 调用参数。"""

    def test_system_prompt_has_ted(self, generator: OutlineGenerator):
        """system prompt 包含 TED 关键词。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json(10)
        )
        generator.generate("测试" * 100, _make_analysis(estimated_pages=10))

        messages = generator._mock_llm.chat.call_args[0][0]
        assert messages[0]["role"] == "system"
        assert "TED" in messages[0]["content"]

    def test_analysis_info_in_user_prompt(self, generator: OutlineGenerator):
        """用户 prompt 包含分析结果。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json(10)
        )
        analysis = _make_analysis(theme="量子计算前沿", estimated_pages=10)
        generator.generate("测试" * 100, analysis)

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        assert "量子计算前沿" in user_msg
        assert "10 页" in user_msg


# ---------------------------------------------------------------------------
# 内容地图模式（ContentMap-aware generation）
# ---------------------------------------------------------------------------


class TestContentMapGeneration:
    """测试基于 ContentMap 的内容感知大纲生成。"""

    def test_content_map_basic_generation(self, generator: OutlineGenerator):
        """使用 content_map 生成大纲，基本流程正常。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json_with_block_ids(10)
        )
        analysis = _make_analysis(estimated_pages=10)
        content_map = _make_content_map()

        slides = generator.generate(
            "测试" * 100, analysis, content_map=content_map
        )

        assert len(slides) == 10
        assert all(isinstance(s, SlideOutline) for s in slides)
        assert slides[0].layout == LayoutType.TITLE_HERO
        assert slides[-1].layout == LayoutType.CLOSING

    def test_content_map_uses_different_system_prompt(self, generator: OutlineGenerator):
        """content_map 模式使用不同的 system prompt（含内容块编排指令）。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json_with_block_ids(10)
        )
        analysis = _make_analysis(estimated_pages=10)
        content_map = _make_content_map()

        generator.generate("测试" * 100, analysis, content_map=content_map)

        messages = generator._mock_llm.chat.call_args[0][0]
        system_msg = messages[0]["content"]
        # 内容地图模式的 system prompt 应包含内容块编排相关关键词
        assert "content_block_id" in system_msg
        assert "importance" in system_msg

    def test_content_map_user_prompt_contains_thesis(self, generator: OutlineGenerator):
        """content_map 模式的用户 prompt 包含文档核心论点。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json_with_block_ids(10)
        )
        analysis = _make_analysis(estimated_pages=10)
        content_map = _make_content_map()

        generator.generate("测试" * 100, analysis, content_map=content_map)

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        assert content_map.document_thesis in user_msg

    def test_content_map_user_prompt_contains_blocks(self, generator: OutlineGenerator):
        """content_map 模式的用户 prompt 包含所有内容块信息。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json_with_block_ids(10)
        )
        analysis = _make_analysis(estimated_pages=10)
        content_map = _make_content_map()

        generator.generate("测试" * 100, analysis, content_map=content_map)

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        # 每个内容块的 block_id 和标题应出现在 prompt 中
        for block in content_map.content_blocks:
            assert block.block_id in user_msg
            assert block.title in user_msg

    def test_content_map_user_prompt_contains_data_points(self, generator: OutlineGenerator):
        """content_map 模式的用户 prompt 包含关键数据。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json_with_block_ids(10)
        )
        analysis = _make_analysis(estimated_pages=10)
        content_map = _make_content_map()

        generator.generate("测试" * 100, analysis, content_map=content_map)

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        for dp in content_map.key_data_points:
            assert dp in user_msg

    def test_content_map_user_prompt_contains_quotes(self, generator: OutlineGenerator):
        """content_map 模式的用户 prompt 包含金句引用。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json_with_block_ids(10)
        )
        analysis = _make_analysis(estimated_pages=10)
        content_map = _make_content_map()

        generator.generate("测试" * 100, analysis, content_map=content_map)

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        for q in content_map.key_quotes:
            assert q in user_msg

    def test_content_map_user_prompt_contains_logical_flow(
        self, generator: OutlineGenerator
    ):
        """content_map 模式的用户 prompt 包含逻辑顺序。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json_with_block_ids(10)
        )
        analysis = _make_analysis(estimated_pages=10)
        content_map = _make_content_map()

        generator.generate("测试" * 100, analysis, content_map=content_map)

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        # 逻辑顺序应以 "→" 分隔展示
        assert "b1" in user_msg
        assert "→" in user_msg

    def test_content_map_user_prompt_contains_importance(
        self, generator: OutlineGenerator
    ):
        """content_map 模式的用户 prompt 包含重要性标识。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json_with_block_ids(10)
        )
        analysis = _make_analysis(estimated_pages=10)
        content_map = _make_content_map()

        generator.generate("测试" * 100, analysis, content_map=content_map)

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        # importance=5 的块应有 5 个星号
        assert "★★★★★" in user_msg


# ---------------------------------------------------------------------------
# content_block_ids 解析
# ---------------------------------------------------------------------------


class TestContentBlockIdsParsing:
    """测试 content_block_ids 从 LLM 输出中解析。"""

    def test_block_ids_parsed_from_llm_output(self, generator: OutlineGenerator):
        """content_block_ids 被正确解析。"""
        slides_json = _make_slides_json_with_block_ids(8)
        generator._mock_llm.chat.return_value = _make_llm_response(slides_json)

        analysis = _make_analysis(estimated_pages=8)
        content_map = _make_content_map()
        slides = generator.generate(
            "测试" * 100, analysis, content_map=content_map
        )

        # 封面应有 content_block_ids
        assert slides[0].content_block_ids == ["b1"]

        # 中间页也应有 content_block_ids
        for slide in slides[1:-1]:
            assert isinstance(slide.content_block_ids, list)
            assert len(slide.content_block_ids) >= 1

    def test_empty_block_ids_for_closing(self, generator: OutlineGenerator):
        """结束页的 content_block_ids 为空。"""
        slides_json = _make_slides_json_with_block_ids(8)
        generator._mock_llm.chat.return_value = _make_llm_response(slides_json)

        analysis = _make_analysis(estimated_pages=8)
        slides = generator.generate(
            "测试" * 100, analysis, content_map=_make_content_map()
        )

        assert slides[-1].content_block_ids == []

    def test_missing_block_ids_defaults_to_empty_list(self, generator: OutlineGenerator):
        """LLM 输出缺少 content_block_ids 时默认为空列表。"""
        # 使用不含 content_block_ids 的 JSON
        slides_json = _make_slides_json(8)
        generator._mock_llm.chat.return_value = _make_llm_response(slides_json)

        analysis = _make_analysis(estimated_pages=8)
        slides = generator.generate("测试" * 100, analysis)

        for slide in slides:
            assert slide.content_block_ids == []

    def test_invalid_block_ids_filtered(self, generator: OutlineGenerator):
        """content_block_ids 中的无效值（None、空字符串）被过滤。"""
        slides_json = _make_slides_json_with_block_ids(8)
        slides_json[1]["content_block_ids"] = ["b1", None, "", "b2", 0]
        generator._mock_llm.chat.return_value = _make_llm_response(slides_json)

        analysis = _make_analysis(estimated_pages=8)
        slides = generator.generate(
            "测试" * 100, analysis, content_map=_make_content_map()
        )

        # None 和 "" 被过滤，0 是 falsy 也被过滤
        # 只保留 "b1" 和 "b2"
        assert slides[1].content_block_ids == ["b1", "b2"]

    def test_non_list_block_ids_becomes_empty_list(self, generator: OutlineGenerator):
        """content_block_ids 为非列表类型时变为空列表。"""
        slides_json = _make_slides_json_with_block_ids(8)
        slides_json[2]["content_block_ids"] = "b1"  # 字符串，不是列表
        generator._mock_llm.chat.return_value = _make_llm_response(slides_json)

        analysis = _make_analysis(estimated_pages=8)
        slides = generator.generate(
            "测试" * 100, analysis, content_map=_make_content_map()
        )

        assert slides[2].content_block_ids == []


# ---------------------------------------------------------------------------
# 后向兼容性
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """测试后向兼容：不传 content_map 时行为不变。"""

    def test_no_content_map_uses_traditional_prompt(self, generator: OutlineGenerator):
        """不传 content_map 时使用传统的原文模式。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json(10)
        )
        analysis = _make_analysis(estimated_pages=10)

        generator.generate("测试文本" * 100, analysis)

        # 传统模式的 user prompt 应包含 "原文内容"
        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        assert "原文内容" in user_msg

    def test_no_content_map_no_block_related_in_prompt(
        self, generator: OutlineGenerator
    ):
        """不传 content_map 时 prompt 中不含 content_block 相关内容。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json(10)
        )
        analysis = _make_analysis(estimated_pages=10)

        generator.generate("测试文本" * 100, analysis)

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        assert "content_block_ids" not in user_msg
        assert "内容块列表" not in user_msg

    def test_content_map_none_same_as_omitted(self, generator: OutlineGenerator):
        """content_map=None 与不传 content_map 行为一致。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json(10)
        )
        analysis = _make_analysis(estimated_pages=10)

        # 显式传 None
        generator.generate("测试" * 100, analysis, content_map=None)

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        assert "原文内容" in user_msg

    def test_old_slides_still_have_empty_block_ids(self, generator: OutlineGenerator):
        """传统模式生成的 slides 的 content_block_ids 为空列表。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json(8)
        )
        analysis = _make_analysis(estimated_pages=8)

        slides = generator.generate("测试" * 100, analysis)

        for slide in slides:
            assert slide.content_block_ids == []

    def test_fallback_slides_have_empty_block_ids(self, generator: OutlineGenerator):
        """fallback 大纲的 content_block_ids 为空列表。"""
        generator._mock_llm.chat.return_value = LLMResponse(
            content="garbage", model="test"
        )
        slides = generator.generate(
            "测试" * 100, _make_analysis(estimated_pages=10)
        )

        for slide in slides:
            assert slide.content_block_ids == []


# ---------------------------------------------------------------------------
# 高重要性内容块覆盖
# ---------------------------------------------------------------------------


class TestHighImportanceCoverage:
    """测试高重要性内容块在 prompt 中的呈现。"""

    def test_high_importance_blocks_in_prompt(self, generator: OutlineGenerator):
        """importance >= 4 的内容块信息出现在 prompt 中。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json_with_block_ids(10)
        )
        analysis = _make_analysis(estimated_pages=10)
        content_map = _make_content_map()

        generator.generate("测试" * 100, analysis, content_map=content_map)

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        # 所有 importance >= 4 的块必须出现
        high_importance_blocks = [
            b for b in content_map.content_blocks if b.importance >= 4
        ]
        assert len(high_importance_blocks) >= 1  # 确保测试有意义
        for block in high_importance_blocks:
            assert block.block_id in user_msg
            assert block.summary in user_msg

    def test_system_prompt_mentions_importance_rule(self, generator: OutlineGenerator):
        """content_map 模式的 system prompt 包含高重要性必须出现的规则。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json_with_block_ids(10)
        )
        analysis = _make_analysis(estimated_pages=10)
        content_map = _make_content_map()

        generator.generate("测试" * 100, analysis, content_map=content_map)

        system_msg = generator._mock_llm.chat.call_args[0][0][0]["content"]
        assert "importance >= 4" in system_msg

    def test_content_map_with_empty_data_and_quotes(self, generator: OutlineGenerator):
        """content_map 中无关键数据和金句时不崩溃。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json_with_block_ids(8)
        )
        analysis = _make_analysis(estimated_pages=8)
        content_map = _make_content_map(
            key_data_points=[],
            key_quotes=[],
        )

        slides = generator.generate(
            "测试" * 100, analysis, content_map=content_map
        )

        assert len(slides) == 8

        # prompt 中应显示"（无）"
        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        assert "（无）" in user_msg

    def test_all_block_types_in_prompt(self, generator: OutlineGenerator):
        """所有内容块类型（thesis, data, quote 等）都出现在 prompt 中。"""
        generator._mock_llm.chat.return_value = _make_llm_response(
            _make_slides_json_with_block_ids(10)
        )
        analysis = _make_analysis(estimated_pages=10)
        content_map = _make_content_map()

        generator.generate("测试" * 100, analysis, content_map=content_map)

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        block_types = {b.block_type for b in content_map.content_blocks}
        for bt in block_types:
            assert bt in user_msg


# ---------------------------------------------------------------------------
# Helpers: PresentationPlan 构造
# ---------------------------------------------------------------------------


def _make_presentation_plan(
    deck_type: DeckType = DeckType.COURSE_LECTURE,
    num_slides: int = 5,
) -> PresentationPlan:
    """构造一个简单的 PresentationPlan。"""
    slides = [
        SlideTask(
            page_role=PageRole.COVER,
            page_goal="建立课程主题",
            must_include=["课程名称"],
            image_strategy=ImageStrategy.ILLUSTRATION,
            layout_preference="title_hero",
        ),
        SlideTask(
            page_role=PageRole.LEARNING_OBJECTIVES,
            page_goal="让学员知道今天学什么",
            must_include=["3个学习目标"],
            forbidden_content=["空泛描述"],
            image_strategy=ImageStrategy.NONE,
            layout_preference="bullet_with_icons",
        ),
        SlideTask(
            page_role=PageRole.KNOWLEDGE_POINT,
            page_goal="讲清楚核心概念",
            must_include=["定义", "关键特征"],
            image_strategy=ImageStrategy.DIAGRAM,
        ),
    ]
    # 填充到 num_slides 页
    while len(slides) < num_slides - 1:
        slides.append(
            SlideTask(
                page_role=PageRole.KNOWLEDGE_POINT,
                page_goal=f"知识点 {len(slides)}",
                must_include=[f"要点 {len(slides)}"],
                image_strategy=ImageStrategy.NONE,
            )
        )
    slides.append(
        SlideTask(
            page_role=PageRole.CLOSING,
            page_goal="收尾",
            must_include=["联系方式"],
            image_strategy=ImageStrategy.NONE,
            layout_preference="closing",
        ),
    )
    return PresentationPlan(
        deck_type=deck_type,
        audience="学员/学生",
        core_message="AI正在重塑各行各业",
        presentation_goal="让学员理解AI核心概念",
        narrative_arc=["引入", "概念", "深入", "总结"],
        slides=slides,
    )


def _make_plan_driven_llm_response(num_slides: int) -> list[dict]:
    """生成 plan-driven 模式的 LLM 返回 JSON。"""
    result = []
    for i in range(num_slides):
        result.append({
            "title": f"中文标题 {i + 1}",
            "subtitle": f"副标题 {i + 1}" if i == 0 else None,
            "key_points": [f"要点{j}" for j in range(1, 4)],
            "content_block_ids": [f"b{i + 1}"] if i < 6 else [],
            "image_prompt": f"illustration for slide {i + 1}" if i == 0 else None,
            "speaker_notes_hint": f"第{i + 1}页说明",
        })
    return result


# ---------------------------------------------------------------------------
# Plan-Driven 大纲生成
# ---------------------------------------------------------------------------


class TestPlanDrivenGeneration:
    """测试 PresentationPlan → SlideOutline 的 plan-driven 模式。"""

    def test_plan_driven_basic(self, generator: OutlineGenerator):
        """有 presentation_plan 时，使用 plan-driven 模式。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(estimated_pages=15),  # analysis 建议 15 页
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        # plan 有 5 页，应该生成 5 页（忽略 analysis 的 15 页建议）
        assert len(slides) == 5

    def test_plan_driven_preserves_page_role(self, generator: OutlineGenerator):
        """plan-driven 模式保留每页的 page_role。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        assert slides[0].page_role == PageRole.COVER
        assert slides[1].page_role == PageRole.LEARNING_OBJECTIVES
        assert slides[-1].page_role == PageRole.CLOSING

    def test_plan_driven_preserves_page_goal(self, generator: OutlineGenerator):
        """plan-driven 模式保留每页的 page_goal。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        assert slides[0].page_goal == "建立课程主题"
        assert slides[1].page_goal == "让学员知道今天学什么"

    def test_plan_driven_preserves_must_include(self, generator: OutlineGenerator):
        """plan-driven 模式保留每页的 must_include。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        assert "课程名称" in slides[0].must_include
        assert "3个学习目标" in slides[1].must_include

    def test_plan_driven_preserves_forbidden_content(self, generator: OutlineGenerator):
        """plan-driven 模式保留每页的 forbidden_content。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        assert "空泛描述" in slides[1].forbidden_content

    def test_plan_driven_preserves_image_strategy(self, generator: OutlineGenerator):
        """plan-driven 模式保留每页的 image_strategy。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        assert slides[0].image_strategy == ImageStrategy.ILLUSTRATION
        assert slides[0].needs_image is True
        assert slides[1].image_strategy == ImageStrategy.NONE
        assert slides[1].needs_image is False

    def test_plan_driven_uses_layout_preference(self, generator: OutlineGenerator):
        """plan-driven 模式使用 layout_preference。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        # cover has layout_preference="title_hero"
        assert slides[0].layout == LayoutType.TITLE_HERO
        # learning_objectives has layout_preference="bullet_with_icons"
        assert slides[1].layout == LayoutType.BULLET_WITH_ICONS
        # closing has layout_preference="closing"
        assert slides[-1].layout == LayoutType.CLOSING

    def test_plan_driven_layout_fallback_to_page_role(self, generator: OutlineGenerator):
        """当 layout_preference 为 None 时，从 page_role 推断布局。"""
        plan = _make_presentation_plan(num_slides=5)
        # knowledge_point (index 2) has no layout_preference
        assert plan.slides[2].layout_preference is None

        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        # knowledge_point -> text_left_image_right (from _PAGE_ROLE_TO_LAYOUT)
        assert slides[2].layout == LayoutType.TEXT_LEFT_IMAGE_RIGHT

    def test_plan_driven_fills_title_from_llm(self, generator: OutlineGenerator):
        """plan-driven 模式从 LLM 填充标题。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        assert slides[0].title == "中文标题 1"
        assert slides[1].title == "中文标题 2"

    def test_plan_driven_fills_key_points_from_llm(self, generator: OutlineGenerator):
        """plan-driven 模式从 LLM 填充 key_points。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        assert len(slides[0].key_points) == 3
        assert slides[0].key_points[0] == "要点1"

    def test_plan_driven_fills_content_block_ids(self, generator: OutlineGenerator):
        """plan-driven 模式从 LLM 填充 content_block_ids。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        assert slides[0].content_block_ids == ["b1"]

    def test_plan_driven_page_numbers_sequential(self, generator: OutlineGenerator):
        """plan-driven 模式页码连续。"""
        plan = _make_presentation_plan(num_slides=8)
        llm_data = _make_plan_driven_llm_response(8)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        assert [s.page_number for s in slides] == list(range(1, 9))


class TestPlanDrivenPrompt:
    """测试 plan-driven 模式的 LLM prompt 内容。"""

    def test_prompt_contains_core_message(self, generator: OutlineGenerator):
        """prompt 包含核心信息。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        assert plan.core_message in user_msg

    def test_prompt_contains_page_roles(self, generator: OutlineGenerator):
        """prompt 包含每页的 page_role。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        assert "cover" in user_msg
        assert "learning_objectives" in user_msg
        assert "closing" in user_msg

    def test_prompt_contains_must_include(self, generator: OutlineGenerator):
        """prompt 包含每页的 must_include 信息。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        assert "课程名称" in user_msg
        assert "3个学习目标" in user_msg

    def test_prompt_contains_content_blocks(self, generator: OutlineGenerator):
        """prompt 包含 content_map 中的内容块信息。"""
        plan = _make_presentation_plan(num_slides=5)
        content_map = _make_content_map()
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=content_map,
            presentation_plan=plan,
        )

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        for block in content_map.content_blocks:
            assert block.block_id in user_msg

    def test_prompt_uses_plan_driven_system_prompt(self, generator: OutlineGenerator):
        """plan-driven 模式使用专用 system prompt。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        system_msg = generator._mock_llm.chat.call_args[0][0][0]["content"]
        # plan-driven prompt should mention "标题必须是中文"
        assert "中文" in system_msg

    def test_prompt_without_content_map_uses_raw_text(self, generator: OutlineGenerator):
        """无 content_map 时 prompt 使用原文摘要。"""
        plan = _make_presentation_plan(num_slides=5)
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        text = "这是一段很长的测试文本" * 100
        generator.generate(
            text,
            _make_analysis(),
            content_map=None,
            presentation_plan=plan,
        )

        user_msg = generator._mock_llm.chat.call_args[0][0][1]["content"]
        assert "原文内容" in user_msg


class TestPlanDrivenFallback:
    """测试 plan-driven 模式的 LLM 失败降级。"""

    def test_llm_failure_uses_rules_fallback(self, generator: OutlineGenerator):
        """LLM 调用失败时使用规则 fallback。"""
        plan = _make_presentation_plan(num_slides=5)
        generator._mock_llm.chat.side_effect = RuntimeError("LLM down")

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        # 仍应生成 5 页
        assert len(slides) == 5
        # 结构应保留
        assert slides[0].page_role == PageRole.COVER
        assert slides[-1].page_role == PageRole.CLOSING
        # title 应用 page_goal 作为 fallback
        assert slides[0].title == "建立课程主题"

    def test_llm_returns_garbage_uses_rules_fallback(self, generator: OutlineGenerator):
        """LLM 返回垃圾时使用规则 fallback。"""
        plan = _make_presentation_plan(num_slides=5)
        generator._mock_llm.chat.return_value = LLMResponse(
            content="这不是JSON", model="test"
        )

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        assert len(slides) == 5
        assert slides[0].page_role == PageRole.COVER

    def test_rules_fallback_assigns_content_blocks(self, generator: OutlineGenerator):
        """规则 fallback 为每页分配 content_block_ids。"""
        plan = _make_presentation_plan(num_slides=5)
        generator._mock_llm.chat.side_effect = RuntimeError("LLM down")
        content_map = _make_content_map()

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=content_map,
            presentation_plan=plan,
        )

        # 至少有些页应分配到 content_block_ids
        all_ids = []
        for s in slides:
            all_ids.extend(s.content_block_ids)
        assert len(all_ids) > 0

    def test_llm_returns_fewer_pages(self, generator: OutlineGenerator):
        """LLM 返回的页数少于 plan 时，不足的页用 page_goal 作标题。"""
        plan = _make_presentation_plan(num_slides=5)
        # LLM 只返回 3 页
        llm_data = _make_plan_driven_llm_response(3)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        # 仍然 5 页（来自 plan）
        assert len(slides) == 5
        # 前 3 页有 LLM 填充的标题
        assert slides[0].title == "中文标题 1"
        # 后 2 页使用 page_goal 作为标题
        assert slides[3].title == plan.slides[3].page_goal


class TestPlanDrivenBusinessReport:
    """测试 business_report 类型的 plan-driven 生成。"""

    def test_business_report_plan(self, generator: OutlineGenerator):
        """business_report 类型生成正确的布局。"""
        plan = PresentationPlan(
            deck_type=DeckType.BUSINESS_REPORT,
            audience="管理层",
            core_message="Q1业绩超预期完成",
            presentation_goal="汇报进展",
            narrative_arc=["结论先行", "展示进展", "核心数据", "下一步"],
            slides=[
                SlideTask(
                    page_role=PageRole.COVER,
                    page_goal="建立主题",
                    layout_preference="title_hero",
                    image_strategy=ImageStrategy.NONE,
                ),
                SlideTask(
                    page_role=PageRole.EXECUTIVE_SUMMARY,
                    page_goal="30秒讲清结论",
                    layout_preference="bullet_with_icons",
                    image_strategy=ImageStrategy.NONE,
                ),
                SlideTask(
                    page_role=PageRole.DATA_EVIDENCE,
                    page_goal="核心数据",
                    layout_preference="data_highlight",
                    image_strategy=ImageStrategy.CHART,
                ),
                SlideTask(
                    page_role=PageRole.CLOSING,
                    page_goal="收尾",
                    layout_preference="closing",
                    image_strategy=ImageStrategy.NONE,
                ),
            ],
        )

        llm_data = _make_plan_driven_llm_response(4)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        assert len(slides) == 4
        assert slides[0].layout == LayoutType.TITLE_HERO
        assert slides[1].layout == LayoutType.BULLET_WITH_ICONS
        assert slides[2].layout == LayoutType.DATA_HIGHLIGHT
        assert slides[2].needs_image is True  # chart strategy
        assert slides[-1].layout == LayoutType.CLOSING


class TestPlanDrivenIgnoresAnalysisSuggestion:
    """确保 plan-driven 模式忽略 analysis 的页数建议。"""

    def test_plan_page_count_overrides_analysis(self, generator: OutlineGenerator):
        """plan 页数优先于 analysis 建议。"""
        plan = _make_presentation_plan(num_slides=7)
        analysis = _make_analysis(estimated_pages=30)  # analysis 建议 30 页
        llm_data = _make_plan_driven_llm_response(7)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            analysis,
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        assert len(slides) == 7  # 用 plan 的 7 页，不是 analysis 的 30 页

    def test_plan_page_count_overrides_max_pages(self, generator: OutlineGenerator):
        """plan 页数不受 max_pages 限制（plan 已经过 planner 裁剪）。"""
        plan = _make_presentation_plan(num_slides=12)
        llm_data = _make_plan_driven_llm_response(12)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            max_pages=5,  # max_pages=5 不应影响 plan-driven
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        assert len(slides) == 12


class TestPlanDrivenNoLayoutOverride:
    """确保 plan-driven 模式不被 _ensure_layout_diversity 覆盖。"""

    def test_plan_driven_preserves_closing_needs_image(self, generator: OutlineGenerator):
        """plan-driven 模式不会强制 closing 页 needs_image=False。"""
        plan = PresentationPlan(
            deck_type=DeckType.PRODUCT_INTRO,
            audience="客户",
            core_message="test",
            presentation_goal="test",
            narrative_arc=["开头", "结尾"],
            slides=[
                SlideTask(
                    page_role=PageRole.COVER,
                    page_goal="封面",
                    layout_preference="title_hero",
                    image_strategy=ImageStrategy.ILLUSTRATION,
                ),
                SlideTask(
                    page_role=PageRole.CTA,
                    page_goal="行动号召",
                    layout_preference="closing",
                    image_strategy=ImageStrategy.ILLUSTRATION,  # 有图片
                ),
            ],
        )
        llm_data = _make_plan_driven_llm_response(2)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        # CTA 页 image_strategy=ILLUSTRATION → needs_image 应为 True
        assert slides[-1].needs_image is True

    def test_plan_driven_preserves_three_consecutive_same_layout(
        self, generator: OutlineGenerator
    ):
        """plan-driven 模式允许 3 个连续相同布局（planner 的设计决定）。"""
        plan = PresentationPlan(
            deck_type=DeckType.COURSE_LECTURE,
            audience="学员",
            core_message="test",
            presentation_goal="test",
            narrative_arc=["学习"],
            slides=[
                SlideTask(
                    page_role=PageRole.COVER,
                    page_goal="封面",
                    layout_preference="title_hero",
                    image_strategy=ImageStrategy.NONE,
                ),
                SlideTask(
                    page_role=PageRole.KNOWLEDGE_POINT,
                    page_goal="知识点1",
                    layout_preference="text_left_image_right",
                    image_strategy=ImageStrategy.DIAGRAM,
                ),
                SlideTask(
                    page_role=PageRole.KNOWLEDGE_POINT,
                    page_goal="知识点2",
                    layout_preference="text_left_image_right",
                    image_strategy=ImageStrategy.DIAGRAM,
                ),
                SlideTask(
                    page_role=PageRole.KNOWLEDGE_POINT,
                    page_goal="知识点3",
                    layout_preference="text_left_image_right",
                    image_strategy=ImageStrategy.DIAGRAM,
                ),
                SlideTask(
                    page_role=PageRole.CLOSING,
                    page_goal="收尾",
                    layout_preference="closing",
                    image_strategy=ImageStrategy.NONE,
                ),
            ],
        )
        llm_data = _make_plan_driven_llm_response(5)
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        # 3 个连续 text_left_image_right 应被保留
        assert slides[1].layout == LayoutType.TEXT_LEFT_IMAGE_RIGHT
        assert slides[2].layout == LayoutType.TEXT_LEFT_IMAGE_RIGHT
        assert slides[3].layout == LayoutType.TEXT_LEFT_IMAGE_RIGHT


class TestPlanDrivenEdgeCases:
    """Plan-driven 模式边界情况。"""

    def test_invalid_layout_preference_falls_through(self, generator: OutlineGenerator):
        """无效的 layout_preference 回退到 page_role 映射。"""
        from src.ppt.outline_generator import OutlineGenerator as OG

        task = SlideTask(
            page_role=PageRole.DATA_EVIDENCE,
            page_goal="test",
            layout_preference="nonexistent_layout",
            image_strategy=ImageStrategy.NONE,
        )
        layout = OG._resolve_layout(task)
        assert layout == LayoutType.DATA_HIGHLIGHT  # from _PAGE_ROLE_TO_LAYOUT

    def test_plan_driven_no_content_map_and_llm_failure(self, generator: OutlineGenerator):
        """content_map=None + LLM 失败时，规则 fallback 使用原文。"""
        plan = _make_presentation_plan(num_slides=5)
        generator._mock_llm.chat.side_effect = RuntimeError("LLM down")

        text = "这是一段关于AI技术的文档内容" * 20
        slides = generator.generate(
            text,
            _make_analysis(),
            content_map=None,
            presentation_plan=plan,
        )

        assert len(slides) == 5
        # 至少第一页应从原文获取 key_points
        assert len(slides[0].key_points) >= 1
        assert slides[0].key_points[0]  # 非空

    def test_key_points_rejects_nested_objects(self, generator: OutlineGenerator):
        """LLM 返回嵌套对象时，key_points 过滤掉非标量值。"""
        plan = _make_presentation_plan(num_slides=3)
        llm_data = [
            {
                "title": "标题",
                "key_points": [
                    "正常文本",
                    {"nested": "object"},
                    ["nested", "list"],
                    42,
                    "",
                    None,
                ],
                "content_block_ids": [],
            },
            {"title": "标题2", "key_points": ["ok"]},
            {"title": "标题3", "key_points": []},
        ]
        generator._mock_llm.chat.return_value = _make_llm_response(llm_data)

        slides = generator.generate(
            "测试" * 100,
            _make_analysis(),
            content_map=_make_content_map(),
            presentation_plan=plan,
        )

        # 只保留 "正常文本" 和 42（int 是标量），过滤 dict/list/None/""
        assert slides[0].key_points == ["正常文本", "42"]
