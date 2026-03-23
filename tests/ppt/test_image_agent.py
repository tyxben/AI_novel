"""Tests for PPT Image Agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ppt.image_agent import (
    ImageAgent,
    _BACKGROUND_LAYOUTS,
    _IMAGE_LAYOUTS,
    _ORIENTATION_SIZES,
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
    SlideSpec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_colors() -> ColorScheme:
    return ColorScheme(
        primary="#1A73E8",
        secondary="#34A853",
        accent="#EA4335",
        text="#333333",
        background="#FFFFFF",
    )


def _make_font(size: int = 24, color: str = "#333333") -> FontSpec:
    return FontSpec(size=size, color=color)


def _make_design(layout: LayoutType = LayoutType.BULLET_WITH_ICONS) -> SlideDesign:
    return SlideDesign(
        layout=layout,
        colors=_make_colors(),
        title_font=_make_font(36),
        body_font=_make_font(20),
        note_font=_make_font(14),
        decoration=DecorationSpec(),
    )


def _make_content(title: str = "Test Slide") -> SlideContent:
    return SlideContent(
        title=title,
        bullet_points=["Point A", "Point B"],
        speaker_notes="Notes here",
    )


def _make_slide(
    page: int = 1,
    layout: LayoutType = LayoutType.BULLET_WITH_ICONS,
    needs_image: bool = False,
    image_request: ImageRequest | None = None,
) -> SlideSpec:
    return SlideSpec(
        page_number=page,
        content=_make_content(),
        design=_make_design(layout),
        needs_image=needs_image,
        image_request=image_request,
    )


def _make_image_request(
    page: int = 1,
    prompt: str = "A futuristic city skyline at sunset",
    size: ImageOrientation = ImageOrientation.LANDSCAPE,
    style: str = "photorealistic",
) -> ImageRequest:
    return ImageRequest(page_number=page, prompt=prompt, size=size, style=style)


def _make_mock_generator():
    """Return a mock image generator whose .generate() returns a mock PIL Image."""
    mock_gen = MagicMock()
    mock_image = MagicMock()
    mock_gen.generate.return_value = mock_image
    return mock_gen, mock_image


# ---------------------------------------------------------------------------
# Tests: init
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_defaults(self):
        agent = ImageAgent(config={"backend": "siliconflow"})
        assert agent.config == {"backend": "siliconflow"}
        assert agent.workspace == Path("workspace")
        assert agent.mode == "auto"

    def test_init_custom_params(self, tmp_path):
        agent = ImageAgent(
            config={"backend": "together"},
            workspace=str(tmp_path),
            mode="generate",
        )
        assert agent.workspace == tmp_path
        assert agent.mode == "generate"

    def test_init_search_mode(self):
        agent = ImageAgent(config={}, mode="search")
        assert agent.mode == "search"


# ---------------------------------------------------------------------------
# Tests: _needs_image
# ---------------------------------------------------------------------------


class TestNeedsImage:
    def test_needs_image_with_request(self):
        agent = ImageAgent(config={})
        slide = _make_slide(image_request=_make_image_request())
        assert agent._needs_image(slide) is True

    def test_needs_image_with_image_layout_full_overlay(self):
        agent = ImageAgent(config={})
        slide = _make_slide(layout=LayoutType.FULL_IMAGE_OVERLAY)
        assert agent._needs_image(slide) is True

    def test_needs_image_with_image_layout_text_left(self):
        agent = ImageAgent(config={})
        slide = _make_slide(layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT)
        assert agent._needs_image(slide) is True

    def test_needs_image_with_image_layout_image_left(self):
        agent = ImageAgent(config={})
        slide = _make_slide(layout=LayoutType.IMAGE_LEFT_TEXT_RIGHT)
        assert agent._needs_image(slide) is True

    def test_needs_image_with_needs_image_flag(self):
        agent = ImageAgent(config={})
        slide = _make_slide(needs_image=True)
        assert agent._needs_image(slide) is True

    def test_needs_image_with_background_layout_title_hero(self):
        agent = ImageAgent(config={})
        slide = _make_slide(layout=LayoutType.TITLE_HERO)
        assert agent._needs_image(slide) is True

    def test_needs_image_with_background_layout_closing(self):
        agent = ImageAgent(config={})
        slide = _make_slide(layout=LayoutType.CLOSING)
        assert agent._needs_image(slide) is True

    def test_needs_image_with_background_layout_data_highlight(self):
        agent = ImageAgent(config={})
        slide = _make_slide(layout=LayoutType.DATA_HIGHLIGHT)
        assert agent._needs_image(slide) is True

    def test_needs_image_text_only(self):
        """Plain text slide with no image indicators -> False."""
        agent = ImageAgent(config={})
        slide = _make_slide(layout=LayoutType.BULLET_WITH_ICONS, needs_image=False)
        assert agent._needs_image(slide) is False

    def test_needs_image_text_only_quote(self):
        agent = ImageAgent(config={})
        slide = _make_slide(layout=LayoutType.QUOTE_PAGE)
        assert agent._needs_image(slide) is False

    def test_needs_image_text_only_timeline(self):
        agent = ImageAgent(config={})
        slide = _make_slide(layout=LayoutType.TIMELINE)
        assert agent._needs_image(slide) is False


# ---------------------------------------------------------------------------
# Tests: _decide_strategy
# ---------------------------------------------------------------------------


class TestDecideStrategy:
    def test_strategy_title_hero(self):
        agent = ImageAgent(config={})
        slide = _make_slide(layout=LayoutType.TITLE_HERO)
        assert agent._decide_strategy(slide) == "background"

    def test_strategy_closing(self):
        agent = ImageAgent(config={})
        slide = _make_slide(layout=LayoutType.CLOSING)
        assert agent._decide_strategy(slide) == "background"

    def test_strategy_data_highlight(self):
        agent = ImageAgent(config={})
        slide = _make_slide(layout=LayoutType.DATA_HIGHLIGHT)
        assert agent._decide_strategy(slide) == "background"

    def test_strategy_content_page_auto(self):
        """auto mode on content page defaults to generate."""
        agent = ImageAgent(config={}, mode="auto")
        slide = _make_slide(
            layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            image_request=_make_image_request(),
        )
        assert agent._decide_strategy(slide) == "generate"

    def test_strategy_generate_mode(self):
        agent = ImageAgent(config={}, mode="generate")
        slide = _make_slide(
            layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            image_request=_make_image_request(),
        )
        assert agent._decide_strategy(slide) == "generate"

    def test_strategy_search_mode(self):
        agent = ImageAgent(config={}, mode="search")
        slide = _make_slide(
            layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            image_request=_make_image_request(),
        )
        assert agent._decide_strategy(slide) == "search"

    def test_strategy_background_overrides_mode(self):
        """Background layouts should always return 'background' regardless of mode."""
        for mode in ("search", "generate", "auto"):
            agent = ImageAgent(config={}, mode=mode)
            slide = _make_slide(layout=LayoutType.TITLE_HERO)
            assert agent._decide_strategy(slide) == "background"


# ---------------------------------------------------------------------------
# Tests: _generate_image
# ---------------------------------------------------------------------------


class TestGenerateImage:
    @patch("src.ppt.image_agent.create_image_generator")
    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_generate_image_success(self, mock_factory, tmp_path):
        mock_gen, mock_image = _make_mock_generator()
        mock_factory.return_value = mock_gen

        agent = ImageAgent(
            config={"backend": "siliconflow"},
            workspace=str(tmp_path),
        )
        slide = _make_slide(
            page=5,
            layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            image_request=_make_image_request(
                page=5,
                size=ImageOrientation.LANDSCAPE,
            ),
        )

        result = agent._generate_image(slide, "proj_001")

        assert result is not None
        assert "slide_005.png" in result
        assert "proj_001" in result

        # Verify generator was created with correct width/height
        call_config = mock_factory.call_args[0][0]
        assert call_config["width"] == 1024
        assert call_config["height"] == 576

        # Verify generate was called with the prompt
        mock_gen.generate.assert_called_once_with(
            prompt="A futuristic city skyline at sunset"
        )

        # Verify image.save was called
        mock_image.save.assert_called_once()

    @patch("src.ppt.image_agent.create_image_generator")
    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_generate_image_portrait(self, mock_factory, tmp_path):
        mock_gen, mock_image = _make_mock_generator()
        mock_factory.return_value = mock_gen

        agent = ImageAgent(config={}, workspace=str(tmp_path))
        slide = _make_slide(
            page=2,
            image_request=_make_image_request(
                page=2, size=ImageOrientation.PORTRAIT
            ),
        )

        result = agent._generate_image(slide, "proj_002")
        assert result is not None

        call_config = mock_factory.call_args[0][0]
        assert call_config["width"] == 576
        assert call_config["height"] == 1024

    @patch("src.ppt.image_agent.create_image_generator")
    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_generate_image_square(self, mock_factory, tmp_path):
        mock_gen, mock_image = _make_mock_generator()
        mock_factory.return_value = mock_gen

        agent = ImageAgent(config={}, workspace=str(tmp_path))
        slide = _make_slide(
            page=3,
            image_request=_make_image_request(
                page=3, size=ImageOrientation.SQUARE
            ),
        )

        result = agent._generate_image(slide, "proj_003")
        assert result is not None

        call_config = mock_factory.call_args[0][0]
        assert call_config["width"] == 768
        assert call_config["height"] == 768

    @patch("src.ppt.image_agent.create_image_generator")
    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_generate_image_failure_on_generate(self, mock_factory, tmp_path):
        mock_gen = MagicMock()
        mock_gen.generate.side_effect = RuntimeError("API Error")
        mock_factory.return_value = mock_gen

        agent = ImageAgent(config={}, workspace=str(tmp_path))
        slide = _make_slide(
            page=1,
            image_request=_make_image_request(),
        )

        result = agent._generate_image(slide, "proj_err")
        assert result is None

    @patch("src.ppt.image_agent.create_image_generator")
    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_generate_image_failure_on_save(self, mock_factory, tmp_path):
        mock_gen, mock_image = _make_mock_generator()
        mock_image.save.side_effect = OSError("Disk full")
        mock_factory.return_value = mock_gen

        agent = ImageAgent(config={}, workspace=str(tmp_path))
        slide = _make_slide(
            page=1,
            image_request=_make_image_request(),
        )

        result = agent._generate_image(slide, "proj_save_err")
        assert result is None

    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_generate_image_no_request(self, tmp_path):
        """Slide without image_request should return None."""
        agent = ImageAgent(config={}, workspace=str(tmp_path))
        slide = _make_slide(page=1, needs_image=True)
        # No image_request set

        result = agent._generate_image(slide, "proj_no_req")
        assert result is None

    @patch("src.ppt.image_agent._HAS_IMAGEGEN", False)
    def test_generate_image_no_imagegen_module(self, tmp_path):
        agent = ImageAgent(config={}, workspace=str(tmp_path))
        slide = _make_slide(
            page=1,
            image_request=_make_image_request(),
        )

        result = agent._generate_image(slide, "proj_no_mod")
        assert result is None

    @patch("src.ppt.image_agent.create_image_generator")
    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_generate_image_factory_error(self, mock_factory, tmp_path):
        mock_factory.side_effect = ValueError("Unknown backend")

        agent = ImageAgent(config={"backend": "bad"}, workspace=str(tmp_path))
        slide = _make_slide(
            page=1,
            image_request=_make_image_request(),
        )

        result = agent._generate_image(slide, "proj_factory_err")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: _generate_background
# ---------------------------------------------------------------------------


class TestGenerateBackground:
    @patch("src.ppt.image_agent.create_image_generator")
    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_generate_background_success(self, mock_factory, tmp_path):
        mock_gen, mock_image = _make_mock_generator()
        mock_factory.return_value = mock_gen

        agent = ImageAgent(config={}, workspace=str(tmp_path))
        slide = _make_slide(page=1, layout=LayoutType.TITLE_HERO)

        result = agent._generate_background(slide, "proj_bg")

        assert result is not None
        assert "bg_slide_001.png" in result
        assert "proj_bg" in result

        # Check dimensions
        call_config = mock_factory.call_args[0][0]
        assert call_config["width"] == 768
        assert call_config["height"] == 432

        # Check prompt includes colors
        prompt_arg = mock_gen.generate.call_args[1]["prompt"]
        assert "#1A73E8" in prompt_arg  # primary
        assert "#34A853" in prompt_arg  # secondary
        assert "Abstract background" in prompt_arg

        mock_image.save.assert_called_once()

    @patch("src.ppt.image_agent.create_image_generator")
    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_generate_background_failure(self, mock_factory, tmp_path):
        mock_gen = MagicMock()
        mock_gen.generate.side_effect = RuntimeError("GPU OOM")
        mock_factory.return_value = mock_gen

        agent = ImageAgent(config={}, workspace=str(tmp_path))
        slide = _make_slide(page=1, layout=LayoutType.CLOSING)

        result = agent._generate_background(slide, "proj_bg_err")
        assert result is None

    @patch("src.ppt.image_agent._HAS_IMAGEGEN", False)
    def test_generate_background_no_module(self, tmp_path):
        agent = ImageAgent(config={}, workspace=str(tmp_path))
        slide = _make_slide(page=1, layout=LayoutType.TITLE_HERO)

        result = agent._generate_background(slide, "proj_bg_no_mod")
        assert result is None

    @patch("src.ppt.image_agent.create_image_generator")
    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_generate_background_save_failure(self, mock_factory, tmp_path):
        mock_gen, mock_image = _make_mock_generator()
        mock_image.save.side_effect = OSError("Permission denied")
        mock_factory.return_value = mock_gen

        agent = ImageAgent(config={}, workspace=str(tmp_path))
        slide = _make_slide(page=1, layout=LayoutType.TITLE_HERO)

        result = agent._generate_background(slide, "proj_bg_save_err")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: _search_image (placeholder)
# ---------------------------------------------------------------------------


class TestSearchImage:
    @patch("src.ppt.image_agent.create_image_generator")
    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_search_fallback_to_generate(self, mock_factory, tmp_path):
        """Search mode should fall back to generate."""
        mock_gen, mock_image = _make_mock_generator()
        mock_factory.return_value = mock_gen

        agent = ImageAgent(
            config={}, workspace=str(tmp_path), mode="search"
        )
        slide = _make_slide(
            page=7,
            layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            image_request=_make_image_request(page=7),
        )

        result = agent._search_image(slide, "proj_search")

        assert result is not None
        assert "slide_007.png" in result
        mock_gen.generate.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: get_image (integration of all parts)
# ---------------------------------------------------------------------------


class TestGetImage:
    def test_get_image_no_need(self):
        """Slide that doesn't need image returns None."""
        agent = ImageAgent(config={})
        slide = _make_slide(layout=LayoutType.BULLET_WITH_ICONS)
        result = agent.get_image(slide, "proj_no_need")
        assert result is None

    @patch("src.ppt.image_agent.create_image_generator")
    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_get_image_generate_path(self, mock_factory, tmp_path):
        """Content slide with image_request -> generate strategy."""
        mock_gen, mock_image = _make_mock_generator()
        mock_factory.return_value = mock_gen

        agent = ImageAgent(config={}, workspace=str(tmp_path))
        slide = _make_slide(
            page=3,
            layout=LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            image_request=_make_image_request(page=3),
        )

        result = agent.get_image(slide, "proj_gen")
        assert result is not None
        assert "slide_003.png" in result

    @patch("src.ppt.image_agent.create_image_generator")
    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_get_image_background_path(self, mock_factory, tmp_path):
        """Title hero slide -> background strategy."""
        mock_gen, mock_image = _make_mock_generator()
        mock_factory.return_value = mock_gen

        agent = ImageAgent(config={}, workspace=str(tmp_path))
        slide = _make_slide(page=1, layout=LayoutType.TITLE_HERO)

        result = agent.get_image(slide, "proj_bg_path")
        assert result is not None
        assert "bg_slide_001.png" in result

    @patch("src.ppt.image_agent.create_image_generator")
    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_get_image_search_mode_fallback(self, mock_factory, tmp_path):
        """Search mode on content page falls back to generate."""
        mock_gen, mock_image = _make_mock_generator()
        mock_factory.return_value = mock_gen

        agent = ImageAgent(
            config={}, workspace=str(tmp_path), mode="search"
        )
        slide = _make_slide(
            page=4,
            layout=LayoutType.IMAGE_LEFT_TEXT_RIGHT,
            image_request=_make_image_request(page=4),
        )

        result = agent.get_image(slide, "proj_search_fb")
        assert result is not None
        assert "slide_004.png" in result

    @patch("src.ppt.image_agent.create_image_generator")
    @patch("src.ppt.image_agent._HAS_IMAGEGEN", True)
    def test_get_image_creates_directory(self, mock_factory, tmp_path):
        """Verify that the images directory is created."""
        mock_gen, mock_image = _make_mock_generator()
        mock_factory.return_value = mock_gen

        agent = ImageAgent(config={}, workspace=str(tmp_path))
        slide = _make_slide(
            page=1,
            layout=LayoutType.TITLE_HERO,
        )

        result = agent.get_image(slide, "proj_dir")
        assert result is not None

        images_dir = tmp_path / "ppt" / "proj_dir" / "images"
        assert images_dir.exists()

    def test_get_image_none_strategy(self):
        """A slide with none of the image indicators returns None."""
        agent = ImageAgent(config={})
        slide = _make_slide(
            layout=LayoutType.THREE_COLUMNS,
            needs_image=False,
        )
        result = agent.get_image(slide, "proj_none")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: edge cases and constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_image_layouts_set(self):
        assert LayoutType.FULL_IMAGE_OVERLAY in _IMAGE_LAYOUTS
        assert LayoutType.TEXT_LEFT_IMAGE_RIGHT in _IMAGE_LAYOUTS
        assert LayoutType.IMAGE_LEFT_TEXT_RIGHT in _IMAGE_LAYOUTS
        assert LayoutType.BULLET_WITH_ICONS not in _IMAGE_LAYOUTS

    def test_background_layouts_set(self):
        assert LayoutType.TITLE_HERO in _BACKGROUND_LAYOUTS
        assert LayoutType.CLOSING in _BACKGROUND_LAYOUTS
        assert LayoutType.DATA_HIGHLIGHT in _BACKGROUND_LAYOUTS
        assert LayoutType.QUOTE_PAGE not in _BACKGROUND_LAYOUTS

    def test_orientation_sizes(self):
        assert _ORIENTATION_SIZES[ImageOrientation.LANDSCAPE] == (1024, 576)
        assert _ORIENTATION_SIZES[ImageOrientation.PORTRAIT] == (576, 1024)
        assert _ORIENTATION_SIZES[ImageOrientation.SQUARE] == (768, 768)
