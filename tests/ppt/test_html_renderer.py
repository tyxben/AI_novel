"""Tests for HTMLRenderer — covers rendering, CSS/JS, all layouts, and edge cases."""

from __future__ import annotations

import pytest

from src.ppt.html_renderer import HTMLRenderer
from src.ppt.models import (
    ColorScheme,
    ColumnItem,
    DecorationSpec,
    FontSpec,
    IconItem,
    LayoutType,
    SlideContent,
    SlideDesign,
    SlideSpec,
    ThemeConfig,
    TimelineStep,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_color_scheme(**overrides) -> ColorScheme:
    defaults = dict(
        primary="#1A237E",
        secondary="#00BCD4",
        accent="#FDD835",
        text="#424242",
        background="#FFFFFF",
    )
    defaults.update(overrides)
    return ColorScheme(**defaults)


def _make_font(size: int = 20, bold: bool = False, color: str = "#424242") -> FontSpec:
    return FontSpec(size=size, bold=bold, color=color, family="Arial")


def _make_theme(**overrides) -> ThemeConfig:
    defaults = dict(
        name="test_modern",
        display_name="Test Modern",
        colors=_make_color_scheme(),
        title_font=_make_font(32, True, "#1A237E"),
        body_font=_make_font(18, False, "#424242"),
        note_font=_make_font(12, False, "#757575"),
    )
    defaults.update(overrides)
    return ThemeConfig(**defaults)


def _make_design(layout: LayoutType, **overrides) -> SlideDesign:
    defaults = dict(
        layout=layout,
        colors=_make_color_scheme(),
        title_font=_make_font(32, True, "#1A237E"),
        body_font=_make_font(18, False, "#424242"),
        note_font=_make_font(12, False, "#757575"),
        decoration=DecorationSpec(),
    )
    defaults.update(overrides)
    return SlideDesign(**defaults)


def _make_slide(
    layout: LayoutType,
    page: int = 1,
    title: str = "Test Title",
    subtitle: str | None = None,
    bullets: list[str] | None = None,
    body_text: str | None = None,
    data_value: str | None = None,
    data_label: str | None = None,
    data_description: str | None = None,
    speaker_notes: str = "",
    image_path: str | None = None,
    quote: str | None = None,
    quote_author: str | None = None,
    columns: list[ColumnItem] | None = None,
    steps: list[TimelineStep] | None = None,
    icon_items: list[IconItem] | None = None,
    left_title: str | None = None,
    left_items: list[str] | None = None,
    right_title: str | None = None,
    right_items: list[str] | None = None,
    contact_info: str | None = None,
) -> SlideSpec:
    return SlideSpec(
        page_number=page,
        content=SlideContent(
            title=title,
            subtitle=subtitle,
            bullet_points=bullets or [],
            body_text=body_text,
            speaker_notes=speaker_notes,
            data_value=data_value,
            data_label=data_label,
            data_description=data_description,
            quote=quote,
            quote_author=quote_author,
            columns=columns or [],
            steps=steps or [],
            icon_items=icon_items or [],
            left_title=left_title,
            left_items=left_items or [],
            right_title=right_title,
            right_items=right_items or [],
            contact_info=contact_info,
        ),
        design=_make_design(layout),
        image_path=image_path,
    )


@pytest.fixture
def theme() -> ThemeConfig:
    return _make_theme()


@pytest.fixture
def renderer(theme) -> HTMLRenderer:
    return HTMLRenderer(theme)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInitRenderer:
    """Test HTMLRenderer initialization."""

    def test_init_renderer(self, theme):
        renderer = HTMLRenderer(theme)
        assert renderer.theme is theme
        assert renderer.env is not None

    def test_init_sets_up_jinja_env(self, renderer):
        """Jinja2 environment should have FileSystemLoader."""
        assert renderer.env.loader is not None

    def test_init_with_custom_theme(self):
        custom_theme = _make_theme(
            name="custom",
            colors=_make_color_scheme(primary="#FF0000", secondary="#00FF00"),
        )
        renderer = HTMLRenderer(custom_theme)
        assert renderer.theme.name == "custom"
        assert renderer.theme.colors.primary == "#FF0000"


class TestRenderSingleSlide:
    """Test rendering individual slide layouts."""

    def test_render_single_slide_title_hero(self, renderer, tmp_path):
        slide = _make_slide(
            LayoutType.TITLE_HERO,
            title="Welcome Presentation",
            subtitle="An Amazing Subtitle",
        )
        output = renderer.render([slide], tmp_path / "test.html")
        html = (tmp_path / "test.html").read_text(encoding="utf-8")

        assert "Welcome Presentation" in html
        assert "An Amazing Subtitle" in html
        assert 'data-page="1"' in html

    def test_render_single_slide_with_bullets(self, renderer, tmp_path):
        slide = _make_slide(
            LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            title="Key Points",
            bullets=["First point", "Second point", "Third point"],
        )
        output = renderer.render([slide], tmp_path / "test.html")
        html = (tmp_path / "test.html").read_text(encoding="utf-8")

        assert "Key Points" in html
        assert "First point" in html
        assert "Second point" in html
        assert "Third point" in html

    def test_render_section_divider(self, renderer, tmp_path):
        slide = _make_slide(
            LayoutType.SECTION_DIVIDER,
            title="Part Two",
            subtitle="Advanced Topics",
        )
        output = renderer.render([slide], tmp_path / "test.html")
        html = (tmp_path / "test.html").read_text(encoding="utf-8")

        assert "Part Two" in html
        assert "Advanced Topics" in html

    def test_render_image_left_text_right(self, renderer, tmp_path):
        slide = _make_slide(
            LayoutType.IMAGE_LEFT_TEXT_RIGHT,
            title="Image Layout",
            bullets=["Point A", "Point B"],
            image_path="/img/test.png",
        )
        output = renderer.render([slide], tmp_path / "test.html")
        html = (tmp_path / "test.html").read_text(encoding="utf-8")

        assert "Image Layout" in html
        assert "/img/test.png" in html
        assert "Point A" in html

    def test_render_full_image_overlay(self, renderer, tmp_path):
        slide = _make_slide(
            LayoutType.FULL_IMAGE_OVERLAY,
            title="Overlay Title",
            subtitle="Overlay Sub",
            body_text="Some descriptive text",
            image_path="/img/bg.jpg",
        )
        output = renderer.render([slide], tmp_path / "test.html")
        html = (tmp_path / "test.html").read_text(encoding="utf-8")

        assert "Overlay Title" in html
        assert "/img/bg.jpg" in html

    def test_render_three_columns(self, renderer, tmp_path):
        cols = [
            ColumnItem(subtitle="Col 1", description="Description 1"),
            ColumnItem(subtitle="Col 2", description="Description 2"),
            ColumnItem(subtitle="Col 3", description="Description 3"),
        ]
        slide = _make_slide(
            LayoutType.THREE_COLUMNS,
            title="Three Pillars",
            columns=cols,
        )
        output = renderer.render([slide], tmp_path / "test.html")
        html = (tmp_path / "test.html").read_text(encoding="utf-8")

        assert "Three Pillars" in html
        assert "Col 1" in html
        assert "Description 2" in html
        assert "Col 3" in html

    def test_render_quote_page(self, renderer, tmp_path):
        slide = _make_slide(
            LayoutType.QUOTE_PAGE,
            title="Inspiration",
            quote="The only way to do great work is to love what you do.",
            quote_author="Steve Jobs",
        )
        output = renderer.render([slide], tmp_path / "test.html")
        html = (tmp_path / "test.html").read_text(encoding="utf-8")

        assert "The only way to do great work" in html
        assert "Steve Jobs" in html

    def test_render_data_highlight(self, renderer, tmp_path):
        slide = _make_slide(
            LayoutType.DATA_HIGHLIGHT,
            title="Revenue Growth",
            data_value="42%",
            data_label="Year-over-Year Growth",
            data_description="Driven by international expansion.",
        )
        output = renderer.render([slide], tmp_path / "test.html")
        html = (tmp_path / "test.html").read_text(encoding="utf-8")

        assert "42%" in html
        assert "Year-over-Year Growth" in html
        assert "Driven by international expansion" in html

    def test_render_timeline(self, renderer, tmp_path):
        steps = [
            TimelineStep(label="Q1", description="Research phase"),
            TimelineStep(label="Q2", description="Development"),
            TimelineStep(label="Q3", description="Launch"),
        ]
        slide = _make_slide(
            LayoutType.TIMELINE,
            title="Project Roadmap",
            steps=steps,
        )
        output = renderer.render([slide], tmp_path / "test.html")
        html = (tmp_path / "test.html").read_text(encoding="utf-8")

        assert "Project Roadmap" in html
        assert "Q1" in html
        assert "Research phase" in html
        assert "Launch" in html

    def test_render_bullet_with_icons(self, renderer, tmp_path):
        items = [
            IconItem(icon_keyword="rocket", text="Fast delivery"),
            IconItem(icon_keyword="shield", text="Secure platform"),
            IconItem(icon_keyword="chart", text="Analytics built-in"),
        ]
        slide = _make_slide(
            LayoutType.BULLET_WITH_ICONS,
            title="Our Features",
            icon_items=items,
        )
        output = renderer.render([slide], tmp_path / "test.html")
        html = (tmp_path / "test.html").read_text(encoding="utf-8")

        assert "Our Features" in html
        assert "Fast delivery" in html
        assert "Secure platform" in html

    def test_render_comparison(self, renderer, tmp_path):
        slide = _make_slide(
            LayoutType.COMPARISON,
            title="Before vs After",
            left_title="Before",
            left_items=["Manual process", "Slow feedback"],
            right_title="After",
            right_items=["Automated workflow", "Real-time insights"],
        )
        output = renderer.render([slide], tmp_path / "test.html")
        html = (tmp_path / "test.html").read_text(encoding="utf-8")

        assert "Before vs After" in html
        assert "Before" in html
        assert "Manual process" in html
        assert "After" in html
        assert "Automated workflow" in html

    def test_render_closing(self, renderer, tmp_path):
        slide = _make_slide(
            LayoutType.CLOSING,
            title="Thank You",
            subtitle="Questions?",
            contact_info="email@example.com",
        )
        output = renderer.render([slide], tmp_path / "test.html")
        html = (tmp_path / "test.html").read_text(encoding="utf-8")

        assert "Thank You" in html
        assert "Questions?" in html
        assert "email@example.com" in html


class TestRenderMultipleSlides:
    """Test rendering multiple slides together."""

    def test_render_multiple_slides(self, renderer, tmp_path):
        slides = [
            _make_slide(LayoutType.TITLE_HERO, page=1, title="Slide One"),
            _make_slide(
                LayoutType.TEXT_LEFT_IMAGE_RIGHT,
                page=2,
                title="Slide Two",
                bullets=["A", "B"],
            ),
            _make_slide(LayoutType.CLOSING, page=3, title="Slide Three"),
        ]
        output = renderer.render(slides, tmp_path / "multi.html")
        html = (tmp_path / "multi.html").read_text(encoding="utf-8")

        assert "Slide One" in html
        assert "Slide Two" in html
        assert "Slide Three" in html
        assert 'data-page="1"' in html
        assert 'data-page="2"' in html
        assert 'data-page="3"' in html

    def test_render_empty_slides(self, renderer, tmp_path):
        """Rendering zero slides should produce a valid HTML doc."""
        output = renderer.render([], tmp_path / "empty.html")
        html = (tmp_path / "empty.html").read_text(encoding="utf-8")

        assert "<!DOCTYPE html>" in html
        assert "showSlide(0)" in html


class TestCSSGeneration:
    """Test CSS generation from theme."""

    def test_generate_css_has_theme_colors(self, renderer):
        css = renderer._generate_css()
        assert "--color-primary: #1A237E" in css
        assert "--color-secondary: #00BCD4" in css
        assert "--color-accent: #FDD835" in css
        assert "--color-text: #424242" in css
        assert "--color-background: #FFFFFF" in css

    def test_generate_css_has_font_families(self, renderer):
        css = renderer._generate_css()
        assert "'Arial'" in css
        assert "'PingFang SC'" in css
        assert "'Microsoft YaHei'" in css

    def test_generate_css_has_slide_dimensions(self, renderer):
        css = renderer._generate_css()
        assert "1280px" in css
        assert "720px" in css

    def test_generate_css_has_navigation_styles(self, renderer):
        css = renderer._generate_css()
        assert ".nav-btn" in css
        assert ".page-info" in css
        assert ".navigation" in css


class TestJSGeneration:
    """Test JavaScript generation."""

    def test_generate_js_has_navigation(self, renderer):
        js = renderer._generate_js()
        assert "function showSlide(n)" in js
        assert "function nextSlide()" in js
        assert "function prevSlide()" in js

    def test_generate_js_has_keyboard_nav(self, renderer):
        js = renderer._generate_js()
        assert "ArrowRight" in js
        assert "ArrowLeft" in js
        assert "keydown" in js

    def test_generate_js_has_initial_call(self, renderer):
        js = renderer._generate_js()
        assert "showSlide(0)" in js

    def test_generate_js_has_page_info_update(self, renderer):
        js = renderer._generate_js()
        assert "pageInfo" in js


class TestMissingTemplate:
    """Test error handling for missing templates."""

    def test_missing_template_raises(self, renderer):
        """Requesting a layout with a deleted template should raise FileNotFoundError."""
        # Temporarily corrupt the map to simulate missing template
        from src.ppt.html_renderer import _LAYOUT_TEMPLATE_MAP

        original = _LAYOUT_TEMPLATE_MAP.get(LayoutType.TITLE_HERO)
        _LAYOUT_TEMPLATE_MAP[LayoutType.TITLE_HERO] = "nonexistent_layout.html"
        try:
            slide = _make_slide(LayoutType.TITLE_HERO, title="Test")
            with pytest.raises(FileNotFoundError, match="nonexistent_layout.html"):
                renderer._render_slide(slide)
        finally:
            # Restore original
            _LAYOUT_TEMPLATE_MAP[LayoutType.TITLE_HERO] = original


class TestImageHandling:
    """Test image rendering and placeholder behavior."""

    def test_missing_image_shows_placeholder(self, renderer, tmp_path):
        """Slides expecting images but without image_path show a placeholder block."""
        slide = _make_slide(
            LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            title="No Image Here",
            image_path=None,
        )
        output = renderer.render([slide], tmp_path / "no_img.html")
        html = (tmp_path / "no_img.html").read_text(encoding="utf-8")

        # Should have gradient placeholder, not an <img> tag
        assert "linear-gradient" in html
        assert "No Image Here" in html

    def test_image_path_rendered(self, renderer, tmp_path):
        slide = _make_slide(
            LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            title="With Image",
            image_path="/images/slide_1.png",
        )
        output = renderer.render([slide], tmp_path / "with_img.html")
        html = (tmp_path / "with_img.html").read_text(encoding="utf-8")

        assert "/images/slide_1.png" in html

    def test_full_image_overlay_no_image(self, renderer, tmp_path):
        """Full image overlay without image should still render with gradient bg."""
        slide = _make_slide(
            LayoutType.FULL_IMAGE_OVERLAY,
            title="No Background",
            image_path=None,
        )
        output = renderer.render([slide], tmp_path / "overlay_noimg.html")
        html = (tmp_path / "overlay_noimg.html").read_text(encoding="utf-8")

        assert "No Background" in html
        assert "linear-gradient" in html


class TestThemeApplication:
    """Test that theme colors and fonts are applied in output."""

    def test_theme_colors_applied(self, tmp_path):
        custom_theme = _make_theme(
            colors=_make_color_scheme(
                primary="#FF5722",
                secondary="#009688",
                accent="#FFEB3B",
            ),
        )
        renderer = HTMLRenderer(custom_theme)
        slide = _make_slide(LayoutType.TITLE_HERO, title="Custom Theme Slide")
        renderer.render([slide], tmp_path / "themed.html")
        html = (tmp_path / "themed.html").read_text(encoding="utf-8")

        # CSS variables should contain custom colors
        assert "#FF5722" in html
        assert "#009688" in html
        assert "#FFEB3B" in html

    def test_theme_font_family_in_css(self, tmp_path):
        custom_theme = _make_theme(
            title_font=_make_font(36, True, "#000000"),
        )
        custom_theme.title_font.family = "Helvetica"
        renderer = HTMLRenderer(custom_theme)
        css = renderer._generate_css()
        assert "'Helvetica'" in css

    def test_footer_text_in_closing(self, tmp_path):
        theme_with_footer = _make_theme(footer_text="Company Inc. 2025")
        renderer = HTMLRenderer(theme_with_footer)
        slide = _make_slide(LayoutType.CLOSING, title="End")
        renderer.render([slide], tmp_path / "footer.html")
        html = (tmp_path / "footer.html").read_text(encoding="utf-8")

        assert "Company Inc. 2025" in html


class TestHTMLOutput:
    """Test output file creation and HTML structure."""

    def test_html_output_file_created(self, renderer, tmp_path):
        slide = _make_slide(LayoutType.TITLE_HERO, title="Output Test")
        output_path = tmp_path / "output" / "slides.html"
        result = renderer.render([slide], output_path)

        assert output_path.exists()
        assert output_path.stat().st_size > 0
        assert str(output_path.resolve()) == result

    def test_html_structure_valid(self, renderer, tmp_path):
        slide = _make_slide(LayoutType.TITLE_HERO, title="Structure Test")
        renderer.render([slide], tmp_path / "valid.html")
        html = (tmp_path / "valid.html").read_text(encoding="utf-8")

        assert "<!DOCTYPE html>" in html
        assert '<html lang="zh-CN">' in html
        assert "<head>" in html
        assert "<body>" in html
        assert "</html>" in html

    def test_output_creates_parent_dirs(self, renderer, tmp_path):
        """If the output directory doesn't exist, it should be created."""
        deep_path = tmp_path / "a" / "b" / "c" / "preview.html"
        slide = _make_slide(LayoutType.TITLE_HERO, title="Deep Path Test")
        renderer.render([slide], deep_path)
        assert deep_path.exists()

    def test_render_returns_absolute_path(self, renderer, tmp_path):
        slide = _make_slide(LayoutType.TITLE_HERO, title="Path Test")
        result = renderer.render([slide], tmp_path / "abs.html")
        assert result.startswith("/")


class TestAllLayoutTypes:
    """Ensure every LayoutType enum value can be rendered without error."""

    def test_all_layout_types_render(self, renderer, tmp_path):
        """Every layout type in the enum should render without errors."""
        layout_slides = {
            LayoutType.TITLE_HERO: _make_slide(
                LayoutType.TITLE_HERO, page=1, title="Title Hero",
            ),
            LayoutType.SECTION_DIVIDER: _make_slide(
                LayoutType.SECTION_DIVIDER, page=2, title="Section",
            ),
            LayoutType.TEXT_LEFT_IMAGE_RIGHT: _make_slide(
                LayoutType.TEXT_LEFT_IMAGE_RIGHT, page=3, title="Text Left",
                bullets=["A"],
            ),
            LayoutType.IMAGE_LEFT_TEXT_RIGHT: _make_slide(
                LayoutType.IMAGE_LEFT_TEXT_RIGHT, page=4, title="Image Left",
                bullets=["B"],
            ),
            LayoutType.FULL_IMAGE_OVERLAY: _make_slide(
                LayoutType.FULL_IMAGE_OVERLAY, page=5, title="Full Image",
            ),
            LayoutType.THREE_COLUMNS: _make_slide(
                LayoutType.THREE_COLUMNS, page=6, title="Columns",
                columns=[
                    ColumnItem(subtitle="A", description="Desc A"),
                    ColumnItem(subtitle="B", description="Desc B"),
                    ColumnItem(subtitle="C", description="Desc C"),
                ],
            ),
            LayoutType.QUOTE_PAGE: _make_slide(
                LayoutType.QUOTE_PAGE, page=7, title="Quote",
                quote="Hello World", quote_author="Author",
            ),
            LayoutType.DATA_HIGHLIGHT: _make_slide(
                LayoutType.DATA_HIGHLIGHT, page=8, title="Data",
                data_value="99%", data_label="Uptime",
            ),
            LayoutType.TIMELINE: _make_slide(
                LayoutType.TIMELINE, page=9, title="Timeline",
                steps=[
                    TimelineStep(label="Step 1", description="First"),
                    TimelineStep(label="Step 2", description="Second"),
                ],
            ),
            LayoutType.BULLET_WITH_ICONS: _make_slide(
                LayoutType.BULLET_WITH_ICONS, page=10, title="Icons",
                icon_items=[
                    IconItem(icon_keyword="star", text="Stars"),
                    IconItem(icon_keyword="rocket", text="Rockets"),
                ],
            ),
            LayoutType.COMPARISON: _make_slide(
                LayoutType.COMPARISON, page=11, title="Compare",
                left_title="Old", left_items=["X"],
                right_title="New", right_items=["Y"],
            ),
            LayoutType.CLOSING: _make_slide(
                LayoutType.CLOSING, page=12, title="Closing",
                contact_info="hello@test.com",
            ),
        }

        # Verify every LayoutType enum member is covered
        for lt in LayoutType:
            assert lt in layout_slides, f"Missing test case for layout: {lt.value}"

        slides = list(layout_slides.values())
        output = renderer.render(slides, tmp_path / "all_layouts.html")
        html = (tmp_path / "all_layouts.html").read_text(encoding="utf-8")

        # All 12 slides should be present
        for i in range(1, 13):
            assert f'data-page="{i}"' in html

        # Spot check some content
        assert "Title Hero" in html
        assert "99%" in html
        assert "hello@test.com" in html


class TestEdgeCases:
    """Test edge cases and optional field handling."""

    def test_slide_without_subtitle(self, renderer, tmp_path):
        slide = _make_slide(LayoutType.TITLE_HERO, title="No Sub", subtitle=None)
        renderer.render([slide], tmp_path / "nosub.html")
        html = (tmp_path / "nosub.html").read_text(encoding="utf-8")
        assert "No Sub" in html

    def test_slide_without_bullets(self, renderer, tmp_path):
        slide = _make_slide(
            LayoutType.TEXT_LEFT_IMAGE_RIGHT, title="No Bullets", bullets=[],
        )
        renderer.render([slide], tmp_path / "nobullets.html")
        html = (tmp_path / "nobullets.html").read_text(encoding="utf-8")
        assert "No Bullets" in html

    def test_empty_columns(self, renderer, tmp_path):
        slide = _make_slide(
            LayoutType.THREE_COLUMNS, title="Empty Cols", columns=[],
        )
        renderer.render([slide], tmp_path / "emptycols.html")
        html = (tmp_path / "emptycols.html").read_text(encoding="utf-8")
        assert "Empty Cols" in html

    def test_chinese_content(self, renderer, tmp_path):
        slide = _make_slide(
            LayoutType.TITLE_HERO,
            title="AI 创意工坊",
            subtitle="让创作更简单",
        )
        renderer.render([slide], tmp_path / "chinese.html")
        html = (tmp_path / "chinese.html").read_text(encoding="utf-8")
        assert "AI 创意工坊" in html
        assert "让创作更简单" in html

    def test_icon_unknown_keyword_uses_default(self, renderer, tmp_path):
        items = [IconItem(icon_keyword="unknown_thing", text="Unknown icon")]
        slide = _make_slide(
            LayoutType.BULLET_WITH_ICONS,
            title="Unknown Icons",
            icon_items=items,
        )
        renderer.render([slide], tmp_path / "unknown_icon.html")
        html = (tmp_path / "unknown_icon.html").read_text(encoding="utf-8")
        # Should still render without error; default emoji used
        assert "Unknown icon" in html

    def test_decoration_with_divider(self, renderer, tmp_path):
        design = _make_design(
            LayoutType.TITLE_HERO,
            decoration=DecorationSpec(
                has_divider=True,
                divider_color="#FF0000",
                divider_width=3,
            ),
        )
        slide = SlideSpec(
            page_number=1,
            content=SlideContent(title="Divider Test"),
            design=design,
        )
        renderer.render([slide], tmp_path / "divider.html")
        html = (tmp_path / "divider.html").read_text(encoding="utf-8")
        assert "Divider Test" in html
        assert "#FF0000" in html
