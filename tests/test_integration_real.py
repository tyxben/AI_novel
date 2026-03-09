"""Real API integration tests for the novel-video pipeline.

These tests call real external APIs and are NOT meant for CI.
They verify that API integrations work end-to-end with actual credentials.

Usage:
    # 1. Set API keys in .env or environment
    # 2. Run integration tests only:
    pytest tests/test_integration_real.py -m integration -v

    # Run a specific test class:
    pytest tests/test_integration_real.py::TestTTSReal -m integration -v
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path so `src.*` imports work
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Short Chinese texts to minimize API cost
_SHORT_TEXT = "少年站在山顶，望着远方的云海。他拔出长剑，剑身闪烁着寒光。"
_WUXIA_TEXT = (
    "李逍遥手持长剑，站在悬崖边。"
    "身后是万丈深渊，面前是黑衣杀手。"
    "他运起内力，剑尖指向对方，冷声道：来吧。"
)
_MODERN_TEXT = "她拿起手机，刷了一会儿视频，然后关灯睡觉了。窗外的城市灯火依然璀璨。"


def _has_any_llm_key() -> bool:
    """Return True if at least one LLM API key is set."""
    return bool(
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )


def _has_any_imagegen_key() -> bool:
    """Return True if at least one image generation API key is set."""
    return bool(
        os.environ.get("SILICONFLOW_API_KEY")
        or os.environ.get("TOGETHER_API_KEY")
        or os.environ.get("DASHSCOPE_API_KEY")
    )


def _detect_imagegen_backend() -> str | None:
    """Return the first available image generation backend name."""
    if os.environ.get("SILICONFLOW_API_KEY"):
        return "siliconflow"
    if os.environ.get("TOGETHER_API_KEY"):
        return "together"
    if os.environ.get("DASHSCOPE_API_KEY"):
        return "dashscope"
    return None


def _load_config() -> dict:
    """Load the default config.yaml from the project root."""
    from src.config_manager import load_config

    return load_config(_PROJECT_ROOT / "config.yaml")


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.integration

_skip_no_llm = pytest.mark.skipif(
    not _has_any_llm_key(),
    reason="No LLM API key set (need GEMINI_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY)",
)
_skip_no_imagegen = pytest.mark.skipif(
    not _has_any_imagegen_key(),
    reason="No image-gen API key set (need SILICONFLOW_API_KEY, TOGETHER_API_KEY, or DASHSCOPE_API_KEY)",
)


# ===========================================================================
# TestLLMReal
# ===========================================================================


@_skip_no_llm
class TestLLMReal:
    """Test real LLM connectivity."""

    def test_llm_auto_detect(self):
        """Auto-detection should find a working LLM provider."""
        from src.llm.llm_client import create_llm_client

        client = create_llm_client({"provider": "auto"})
        assert client is not None

    def test_llm_generate_response(self):
        """A simple prompt should return a non-empty response."""
        from src.llm.llm_client import create_llm_client

        client = create_llm_client({"provider": "auto"})
        response = client.chat(
            messages=[{"role": "user", "content": "Say hello in Chinese, one sentence only."}],
            temperature=0.3,
        )
        assert response.content.strip(), "LLM returned empty content"
        assert len(response.content) > 0


# ===========================================================================
# TestSegmenterReal
# ===========================================================================


@_skip_no_llm
class TestSegmenterReal:
    """Test LLM-based segmentation with a real API."""

    def test_llm_segmenter(self):
        """LLM segmenter should return at least one segment."""
        from src.segmenter.text_segmenter import create_segmenter

        config = _load_config()
        seg_config = dict(config.get("segmenter", {}))
        seg_config["method"] = "llm"
        # Inherit the global LLM config
        if "llm" not in seg_config or not seg_config["llm"]:
            seg_config["llm"] = config.get("llm", {})

        segmenter = create_segmenter(seg_config)
        segments = segmenter.segment(_SHORT_TEXT)

        assert isinstance(segments, list)
        assert len(segments) >= 1, "Expected at least 1 segment"
        for seg in segments:
            assert "text" in seg
            assert "index" in seg
            assert len(seg["text"].strip()) > 0


# ===========================================================================
# TestPromptGenReal
# ===========================================================================


@_skip_no_llm
class TestPromptGenReal:
    """Test real prompt generation via LLM."""

    def test_generate_image_prompt(self):
        """Generated image prompt should be English and descriptive."""
        config = _load_config()
        pg_config = dict(config.get("promptgen", {}))
        # Ensure LLM config is available
        if "llm" not in pg_config or not pg_config["llm"]:
            pg_config["llm"] = config.get("llm", {})

        from src.promptgen.prompt_generator import PromptGenerator

        generator = PromptGenerator(pg_config)
        prompt = generator.generate(_SHORT_TEXT, segment_index=0)

        assert isinstance(prompt, str)
        assert len(prompt) > 10, f"Prompt too short: {prompt!r}"
        # Should contain at least some ASCII (English) words
        ascii_chars = sum(1 for c in prompt if c.isascii() and c.isalpha())
        assert ascii_chars > 5, f"Prompt does not appear to be English: {prompt!r}"


# ===========================================================================
# TestImageGenReal
# ===========================================================================


@_skip_no_imagegen
class TestImageGenReal:
    """Test real image generation with whichever cloud backend is available."""

    def test_generate_image(self, tmp_path: Path):
        """Generate a single image and verify the file is valid."""
        from src.imagegen.image_generator import create_image_generator

        backend = _detect_imagegen_backend()
        assert backend is not None

        config = _load_config()
        ig_config = dict(config.get("imagegen", {}))
        ig_config["backend"] = backend
        # Use small size to reduce cost / time
        ig_config["width"] = 512
        ig_config["height"] = 512

        generator = create_image_generator(ig_config)

        prompt = "A young swordsman standing on a mountain cliff, dramatic lighting, anime style"
        image = generator.generate(prompt)

        # Save and verify
        out_path = tmp_path / "test_image.png"
        image.save(str(out_path))
        assert out_path.exists()
        assert out_path.stat().st_size > 0, "Generated image file is empty"


# ===========================================================================
# TestTTSReal
# ===========================================================================


class TestTTSReal:
    """Test real TTS generation (edge-tts is free, always available)."""

    def test_edge_tts_generate(self, tmp_path: Path):
        """Generate audio from Chinese text, verify .mp3 output."""
        from src.tts.tts_engine import TTSEngine

        engine = TTSEngine({"voice": "zh-CN-YunxiNeural", "rate": "+0%", "volume": "+0%"})
        audio_path = tmp_path / "test.mp3"
        result_path, boundaries = engine.synthesize(_SHORT_TEXT, audio_path)

        assert result_path.exists()
        assert result_path.stat().st_size > 100, "Audio file suspiciously small"
        assert isinstance(boundaries, list)

    def test_edge_tts_with_srt(self, tmp_path: Path):
        """Generate audio + SRT subtitle, verify both files."""
        from src.tts.tts_engine import TTSEngine
        from src.tts.subtitle_generator import SubtitleGenerator

        engine = TTSEngine({"voice": "zh-CN-YunxiNeural", "rate": "+0%", "volume": "+0%"})
        audio_path = tmp_path / "test.mp3"
        srt_path = tmp_path / "test.srt"

        result_path, boundaries = engine.synthesize(_SHORT_TEXT, audio_path)
        SubtitleGenerator().generate_srt(boundaries, _SHORT_TEXT, srt_path)

        assert result_path.exists()
        assert result_path.stat().st_size > 100

        assert srt_path.exists()
        srt_content = srt_path.read_text(encoding="utf-8")
        assert len(srt_content) > 0, "SRT file is empty"
        # SRT should contain at least one timestamp line
        assert "-->" in srt_content, "SRT file missing timestamp markers"


# ===========================================================================
# TestContentAnalyzerReal
# ===========================================================================


@_skip_no_llm
class TestContentAnalyzerReal:
    """Test real content analysis with LLM."""

    def test_classify_genre_with_llm(self):
        """Classify a wuxia text, verify genre is reasonable."""
        from src.agents.content_analyzer import ContentAnalyzerAgent

        config = _load_config()
        agent = ContentAnalyzerAgent(config, budget_mode=False)
        result = agent.classify_genre(_WUXIA_TEXT)

        assert isinstance(result, dict)
        assert "genre" in result
        assert "confidence" in result
        # The wuxia text should be classified as something martial-arts related
        assert result["genre"] in (
            "武侠", "玄幻", "历史", "其他"
        ), f"Unexpected genre for wuxia text: {result['genre']}"

    def test_extract_characters_with_llm(self):
        """Extract characters from text with names."""
        from src.agents.content_analyzer import ContentAnalyzerAgent

        config = _load_config()
        agent = ContentAnalyzerAgent(config, budget_mode=False)
        characters = agent.extract_characters(_WUXIA_TEXT)

        assert isinstance(characters, list)
        assert len(characters) >= 1, "Expected at least 1 character"
        for char in characters:
            assert "name" in char
            assert len(char["name"]) > 0


# ===========================================================================
# TestAgentPipelineSmoke
# ===========================================================================


@_skip_no_llm
class TestAgentPipelineSmoke:
    """Smoke test of the agent pipeline stages (NOT full video assembly)."""

    def test_agent_mode_smoke(self, tmp_path: Path):
        """Run agent pipeline on tiny text through first few stages.

        Tests: content analysis -> segmentation -> prompt generation -> TTS.
        Does NOT assemble final video (too slow).
        """
        config = _load_config()

        # 1. Content analysis
        from src.agents.content_analyzer import ContentAnalyzerAgent

        analyzer = ContentAnalyzerAgent(config, budget_mode=False)
        genre_info = analyzer.classify_genre(_WUXIA_TEXT)
        assert "genre" in genre_info

        characters = analyzer.extract_characters(_WUXIA_TEXT)
        assert isinstance(characters, list)

        style = analyzer.suggest_style(
            genre_info["genre"], genre_info.get("era", "古代")
        )
        assert isinstance(style, str) and len(style) > 0

        # 2. Segmentation (use simple method to avoid extra LLM cost)
        from src.segmenter.text_segmenter import create_segmenter

        seg_config = dict(config.get("segmenter", {}))
        seg_config["method"] = "simple"
        segmenter = create_segmenter(seg_config)
        segments = segmenter.segment(_WUXIA_TEXT)
        assert len(segments) >= 1

        # 3. Prompt generation (LLM)
        from src.promptgen.prompt_generator import PromptGenerator

        pg_config = dict(config.get("promptgen", {}))
        if "llm" not in pg_config or not pg_config["llm"]:
            pg_config["llm"] = config.get("llm", {})
        pg_config["style"] = style

        prompt_gen = PromptGenerator(pg_config)
        prompt_gen.set_full_text(_WUXIA_TEXT)

        prompts = []
        for seg in segments[:2]:  # Only first 2 segments to save cost
            p = prompt_gen.generate(seg["text"], seg["index"])
            prompts.append(p)
            assert isinstance(p, str) and len(p) > 0

        # 4. TTS (free, always works)
        from src.tts.tts_engine import TTSEngine
        from src.tts.subtitle_generator import SubtitleGenerator

        engine = TTSEngine(config["tts"])
        sub_gen = SubtitleGenerator()

        audio_dir = tmp_path / "audio"
        srt_dir = tmp_path / "subtitles"
        audio_dir.mkdir()
        srt_dir.mkdir()

        for i, seg in enumerate(segments[:2]):
            audio_path = audio_dir / f"{i:04d}.mp3"
            srt_path = srt_dir / f"{i:04d}.srt"

            result_path, boundaries = engine.synthesize(seg["text"], audio_path)
            sub_gen.generate_srt(boundaries, seg["text"], srt_path)

            assert result_path.exists()
            assert result_path.stat().st_size > 0
            assert srt_path.exists()

        # Verify we produced outputs at each stage
        assert len(prompts) >= 1, "No prompts generated"
        audio_files = list(audio_dir.glob("*.mp3"))
        srt_files = list(srt_dir.glob("*.srt"))
        assert len(audio_files) >= 1, "No audio files generated"
        assert len(srt_files) >= 1, "No SRT files generated"
