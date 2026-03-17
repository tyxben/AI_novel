"""DesignOrchestrator 单元测试"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.ppt.design_orchestrator import (
    DesignOrchestrator,
    _THEME_IMAGE_STYLE,
    _decoration_for_layout,
)
from src.ppt.models import (
    ColorScheme,
    DecorationSpec,
    FontSpec,
    ImageOrientation,
    ImageRequest,
    LayoutType,
    SlideContent,
    SlideDesign,
    SlideOutline,
    ThemeConfig,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_theme(name: str = "modern") -> ThemeConfig:
    return ThemeConfig(
        name=name,
        display_name="测试主题",
        colors=ColorScheme(
            primary="#1A237E",
            secondary="#00BCD4",
            accent="#FDD835",
            text="#424242",
            background="#FFFFFF",
        ),
        title_font=FontSpec(size=44, bold=True, color="#1A237E", family="Arial"),
        body_font=FontSpec(size=20, bold=False, color="#424242", family="Arial"),
        note_font=FontSpec(size=14, bold=False, color="#757575", family="Arial"),
        decoration_defaults=DecorationSpec(),
    )


def _make_outline(
    page_number: int = 1,
    layout: LayoutType = LayoutType.TEXT_LEFT_IMAGE_RIGHT,
    needs_image: bool = False,
    title: str = "测试标题",
) -> SlideOutline:
    return SlideOutline(
        page_number=page_number,
        slide_type=layout.value,
        layout=layout,
        title=title,
        needs_image=needs_image,
    )


def _make_content(title: str = "测试标题") -> SlideContent:
    return SlideContent(
        title=title,
        bullet_points=["要点1", "要点2"],
        speaker_notes="演讲备注",
    )


@pytest.fixture()
def orchestrator():
    theme = _make_theme()
    with patch("src.ppt.design_orchestrator.create_llm_client") as mock_factory:
        mock_llm = MagicMock()
        mock_factory.return_value = mock_llm
        orch = DesignOrchestrator(config={"llm": {}}, theme_config=theme)
        orch._mock_llm = mock_llm
        yield orch


# ---------------------------------------------------------------------------
# 装饰元素分配测试
# ---------------------------------------------------------------------------


class TestDecorationAssignment:
    def test_title_hero_gets_gradient(self):
        theme = _make_theme()
        deco = _decoration_for_layout(LayoutType.TITLE_HERO, theme)
        assert deco.has_background_shape is True
        assert deco.shape_type == "gradient"

    def test_section_divider_gets_divider_and_gradient(self):
        theme = _make_theme()
        deco = _decoration_for_layout(LayoutType.SECTION_DIVIDER, theme)
        assert deco.has_divider is True
        assert deco.has_background_shape is True
        assert deco.divider_color == theme.colors.accent

    def test_content_pages_get_accent_divider(self):
        theme = _make_theme()
        for layout in (
            LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            LayoutType.IMAGE_LEFT_TEXT_RIGHT,
            LayoutType.BULLET_WITH_ICONS,
        ):
            deco = _decoration_for_layout(layout, theme)
            assert deco.has_divider is True
            assert deco.divider_color == theme.colors.accent

    def test_quote_page_gets_rectangle(self):
        theme = _make_theme()
        deco = _decoration_for_layout(LayoutType.QUOTE_PAGE, theme)
        assert deco.has_background_shape is True
        assert deco.shape_type == "rectangle"

    def test_data_highlight_gets_circle(self):
        theme = _make_theme()
        deco = _decoration_for_layout(LayoutType.DATA_HIGHLIGHT, theme)
        assert deco.has_background_shape is True
        assert deco.shape_type == "circle"

    def test_closing_gets_gradient(self):
        theme = _make_theme()
        deco = _decoration_for_layout(LayoutType.CLOSING, theme)
        assert deco.has_background_shape is True
        assert deco.shape_type == "gradient"

    def test_full_image_overlay_uses_default(self):
        theme = _make_theme()
        deco = _decoration_for_layout(LayoutType.FULL_IMAGE_OVERLAY, theme)
        assert deco.has_divider == theme.decoration_defaults.has_divider

    def test_max_two_decoration_elements(self):
        """每个布局最多2个装饰元素。"""
        theme = _make_theme()
        for layout in LayoutType:
            deco = _decoration_for_layout(layout, theme)
            count = int(deco.has_divider) + int(deco.has_background_shape)
            assert count <= 2, f"{layout.value} 有 {count} 个装饰元素"


# ---------------------------------------------------------------------------
# 图片 prompt 生成测试
# ---------------------------------------------------------------------------


class TestImagePromptGeneration:
    def test_generates_english_prompt(self, orchestrator):
        orchestrator._mock_llm.chat.return_value = LLMResponse(
            content="Minimalist illustration of upward growth chart with blue gradient background, clean white space, modern flat design",
            model="test",
        )
        content = _make_content(title="市场增长30%")
        outline = _make_outline(needs_image=True)
        result = orchestrator._generate_image_prompt(
            content, outline, orchestrator.theme
        )
        assert result is not None
        assert isinstance(result, ImageRequest)
        assert result.page_number == 1
        assert len(result.prompt) > 10
        # prompt 应该是英文（LLM 返回）
        assert "illustration" in result.prompt.lower()

    def test_prompt_includes_style_from_theme(self, orchestrator):
        orchestrator._mock_llm.chat.return_value = LLMResponse(
            content="Tech-themed abstract visualization, minimalist, clean background",
            model="test",
        )
        content = _make_content()
        outline = _make_outline(needs_image=True)
        # 检查 LLM 调用时传入了风格信息
        orchestrator._generate_image_prompt(content, outline, orchestrator.theme)
        call_args = orchestrator._mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "modern" in user_msg.lower() or "style" in user_msg.lower()

    def test_fallback_on_llm_failure(self, orchestrator):
        orchestrator._mock_llm.chat.side_effect = RuntimeError("API error")
        content = _make_content(title="测试失败回退")
        outline = _make_outline(needs_image=True)
        result = orchestrator._generate_image_prompt(
            content, outline, orchestrator.theme
        )
        assert result is not None
        assert "测试失败回退" in result.prompt

    def test_orientation_based_on_layout(self, orchestrator):
        orchestrator._mock_llm.chat.return_value = LLMResponse(
            content="Portrait illustration", model="test"
        )
        # text_left_image_right -> portrait
        content = _make_content()
        outline = _make_outline(
            layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT, needs_image=True
        )
        result = orchestrator._generate_image_prompt(
            content, outline, orchestrator.theme
        )
        assert result.size == ImageOrientation.PORTRAIT

        # title_hero -> landscape
        outline2 = _make_outline(
            layout=LayoutType.TITLE_HERO, needs_image=True
        )
        result2 = orchestrator._generate_image_prompt(
            content, outline2, orchestrator.theme
        )
        assert result2.size == ImageOrientation.LANDSCAPE


# ---------------------------------------------------------------------------
# 完整编排测试
# ---------------------------------------------------------------------------


class TestOrchestrate:
    def test_returns_correct_count(self, orchestrator):
        contents = [_make_content() for _ in range(5)]
        outlines = [
            _make_outline(page_number=i + 1) for i in range(5)
        ]
        designs = orchestrator.orchestrate(contents, outlines)
        assert len(designs) == 5

    def test_all_designs_use_theme_colors(self, orchestrator):
        contents = [_make_content() for _ in range(3)]
        outlines = [
            _make_outline(page_number=1, layout=LayoutType.TITLE_HERO),
            _make_outline(page_number=2, layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT),
            _make_outline(page_number=3, layout=LayoutType.CLOSING),
        ]
        designs = orchestrator.orchestrate(contents, outlines)
        for design in designs:
            assert design.colors.primary == "#1A237E"
            assert design.colors.secondary == "#00BCD4"

    def test_all_designs_use_consistent_fonts(self, orchestrator):
        contents = [_make_content() for _ in range(3)]
        outlines = [_make_outline(page_number=i + 1) for i in range(3)]
        designs = orchestrator.orchestrate(contents, outlines)
        for design in designs:
            assert design.title_font.family == "Arial"
            assert design.body_font.family == "Arial"

    def test_image_requests_collected(self, orchestrator):
        orchestrator._mock_llm.chat.return_value = LLMResponse(
            content="Test image prompt", model="test"
        )
        contents = [_make_content(), _make_content()]
        outlines = [
            _make_outline(page_number=1, needs_image=True),
            _make_outline(page_number=2, needs_image=False),
        ]
        orchestrator.orchestrate(contents, outlines)
        requests = orchestrator.get_image_requests()
        assert len(requests) == 1
        assert requests[0].page_number == 1


# ---------------------------------------------------------------------------
# 视觉一致性测试
# ---------------------------------------------------------------------------


class TestVisualConsistency:
    def test_decoration_colors_within_palette(self, orchestrator):
        contents = [_make_content() for _ in range(3)]
        outlines = [
            _make_outline(page_number=1, layout=LayoutType.SECTION_DIVIDER),
            _make_outline(page_number=2, layout=LayoutType.DATA_HIGHLIGHT),
            _make_outline(page_number=3, layout=LayoutType.QUOTE_PAGE),
        ]
        designs = orchestrator.orchestrate(contents, outlines)

        valid_colors = {
            "#1A237E", "#00BCD4", "#FDD835", "#424242", "#FFFFFF"
        }
        for design in designs:
            deco = design.decoration
            if deco.divider_color:
                assert deco.divider_color in valid_colors, (
                    f"divider_color {deco.divider_color} not in palette"
                )
            if deco.shape_color:
                assert deco.shape_color in valid_colors, (
                    f"shape_color {deco.shape_color} not in palette"
                )

    def test_padding_always_set(self, orchestrator):
        contents = [_make_content()]
        outlines = [_make_outline()]
        designs = orchestrator.orchestrate(contents, outlines)
        assert designs[0].padding == {
            "left": 80, "right": 80, "top": 60, "bottom": 60
        }


# ---------------------------------------------------------------------------
# 不同主题的设计方案
# ---------------------------------------------------------------------------


class TestDifferentThemes:
    def test_tech_theme(self):
        theme = ThemeConfig(
            name="tech",
            colors=ColorScheme(
                primary="#0D1117",
                secondary="#161B22",
                accent="#00D4FF",
                text="#E6EDF3",
                background="#0D1117",
            ),
            title_font=FontSpec(size=36, bold=True, color="#E6EDF3", family="Consolas"),
            body_font=FontSpec(size=16, bold=False, color="#E6EDF3", family="Arial"),
            note_font=FontSpec(size=12, bold=False, color="#8B949E", family="Arial"),
        )
        with patch("src.ppt.design_orchestrator.create_llm_client") as mock_factory:
            mock_llm = MagicMock()
            mock_factory.return_value = mock_llm
            orch = DesignOrchestrator(config={"llm": {}}, theme_config=theme)
            contents = [_make_content()]
            outlines = [_make_outline(layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT)]
            designs = orch.orchestrate(contents, outlines)
            assert designs[0].colors.primary == "#0D1117"
            assert designs[0].title_font.family == "Consolas"

    def test_creative_theme_colors_preserved(self):
        theme = ThemeConfig(
            name="creative",
            colors=ColorScheme(
                primary="#FF6B6B",
                secondary="#FFA502",
                accent="#4ECDC4",
                text="#2D3436",
                background="#FFFFFF",
            ),
            title_font=FontSpec(size=38, bold=True, color="#FF6B6B", family="Helvetica"),
            body_font=FontSpec(size=16, bold=False, color="#2D3436", family="Helvetica"),
            note_font=FontSpec(size=12, bold=False, color="#636E72", family="Helvetica"),
        )
        with patch("src.ppt.design_orchestrator.create_llm_client") as mock_factory:
            mock_llm = MagicMock()
            mock_factory.return_value = mock_llm
            orch = DesignOrchestrator(config={"llm": {}}, theme_config=theme)
            contents = [_make_content()]
            outlines = [_make_outline()]
            designs = orch.orchestrate(contents, outlines)
            assert designs[0].colors.accent == "#4ECDC4"
