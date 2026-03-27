"""Tests for per-stage LLM model routing.

Covers:
- get_stage_llm_config: stage-specific model extraction
- get_stage_llm_config: stage keys stripped from output
- get_stage_llm_config: graceful fallback when stage key missing
- get_stage_llm_config: preserves non-stage keys (provider, api_key, etc.)
- get_stage_llm_config: empty / missing state handling
- Integration: node functions receive correct model via config
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from src.novel.config import NovelConfig
from src.novel.llm_utils import get_stage_llm_config, _STAGE_KEYS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(llm_overrides: dict | None = None, extra_config: dict | None = None) -> dict:
    """Build a minimal novel state dict with LLM config."""
    config = NovelConfig()
    state_config = config.model_dump()
    if llm_overrides:
        state_config["llm"].update(llm_overrides)
    if extra_config:
        state_config.update(extra_config)
    return {"config": state_config}


def _make_state_raw(llm_dict: dict) -> dict:
    """Build a state with a raw llm config dict (no NovelConfig)."""
    return {"config": {"llm": llm_dict}}


# ---------------------------------------------------------------------------
# get_stage_llm_config: basic extraction
# ---------------------------------------------------------------------------


class TestGetStageLlmConfig:
    """Test the get_stage_llm_config helper function."""

    def test_extracts_outline_generation_model(self) -> None:
        state = _make_state()
        result = get_stage_llm_config(state, "outline_generation")
        assert result["model"] == "gpt-5.4"

    def test_extracts_consistency_check_model(self) -> None:
        state = _make_state()
        result = get_stage_llm_config(state, "consistency_check")
        # Default from NovelConfig is "gemini-2.5-pro" (or whatever current default)
        assert "model" in result
        assert result["model"]  # Non-empty

    def test_extracts_style_rewrite_model(self) -> None:
        state = _make_state()
        result = get_stage_llm_config(state, "style_rewrite")
        assert result["model"] == "deepseek-chat"

    def test_extracts_scene_writing_model(self) -> None:
        state = _make_state()
        result = get_stage_llm_config(state, "scene_writing")
        assert result["model"] == "gpt-5.4"

    def test_extracts_quality_review_model(self) -> None:
        state = _make_state()
        result = get_stage_llm_config(state, "quality_review")
        assert result["model"] == "gpt-5.4"

    def test_extracts_character_design_model(self) -> None:
        state = _make_state()
        result = get_stage_llm_config(state, "character_design")
        assert result["model"] == "gpt-5.4"


# ---------------------------------------------------------------------------
# Stage keys stripped from output
# ---------------------------------------------------------------------------


class TestStageKeysStripped:
    """Verify that stage-specific keys are removed from the output dict."""

    def test_no_stage_keys_in_result(self) -> None:
        state = _make_state()
        result = get_stage_llm_config(state, "outline_generation")
        for key in _STAGE_KEYS:
            assert key not in result, f"Stage key '{key}' should be stripped"

    def test_all_six_stages_produce_clean_dicts(self) -> None:
        state = _make_state()
        for stage in _STAGE_KEYS:
            result = get_stage_llm_config(state, stage)
            for key in _STAGE_KEYS:
                assert key not in result


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------


class TestFallback:
    """Test graceful fallback when stage key is missing or empty."""

    def test_unknown_stage_key_no_model(self) -> None:
        """Unknown stage key => no 'model' key in result."""
        state = _make_state()
        result = get_stage_llm_config(state, "nonexistent_stage")
        assert "model" not in result

    def test_empty_llm_config(self) -> None:
        """Empty llm config => empty dict returned."""
        state = _make_state_raw({})
        result = get_stage_llm_config(state, "scene_writing")
        assert result == {}

    def test_missing_config_key(self) -> None:
        """State without 'config' key => empty dict."""
        result = get_stage_llm_config({}, "scene_writing")
        assert result == {}

    def test_missing_llm_key(self) -> None:
        """State with 'config' but no 'llm' key => empty dict."""
        result = get_stage_llm_config({"config": {}}, "scene_writing")
        assert result == {}

    def test_none_state_config(self) -> None:
        """State with config=None handled via .get() defaults."""
        result = get_stage_llm_config({"config": None}, "scene_writing")
        assert result == {}

    def test_empty_model_value_not_set(self) -> None:
        """If stage model value is empty string, 'model' key not set."""
        state = _make_state_raw({"scene_writing": ""})
        result = get_stage_llm_config(state, "scene_writing")
        assert "model" not in result


# ---------------------------------------------------------------------------
# Preserves non-stage keys
# ---------------------------------------------------------------------------


class TestPreservesExtraKeys:
    """Test that provider, api_key, and other non-stage keys are preserved."""

    def test_preserves_provider(self) -> None:
        state = _make_state_raw({
            "provider": "openai",
            "scene_writing": "gpt-5.4",
        })
        result = get_stage_llm_config(state, "scene_writing")
        assert result["provider"] == "openai"
        assert result["model"] == "gpt-5.4"

    def test_preserves_api_key(self) -> None:
        state = _make_state_raw({
            "api_key": "sk-test",
            "outline_generation": "gpt-5.4",
        })
        result = get_stage_llm_config(state, "outline_generation")
        assert result["api_key"] == "sk-test"

    def test_preserves_base_url(self) -> None:
        state = _make_state_raw({
            "base_url": "https://custom.api.com",
            "provider": "openai",
            "quality_review": "gpt-5.4",
        })
        result = get_stage_llm_config(state, "quality_review")
        assert result["base_url"] == "https://custom.api.com"
        assert result["provider"] == "openai"
        assert result["model"] == "gpt-5.4"

    def test_does_not_mutate_original_state(self) -> None:
        """The function should not modify the original state dict."""
        state = _make_state()
        original_llm = dict(state["config"]["llm"])
        get_stage_llm_config(state, "scene_writing")
        assert state["config"]["llm"] == original_llm


# ---------------------------------------------------------------------------
# Different stages get different models
# ---------------------------------------------------------------------------


class TestDifferentModelsPerStage:
    """Verify that different stages can return different model names."""

    def test_distinct_models_for_each_stage(self) -> None:
        state = _make_state_raw({
            "outline_generation": "gpt-5.4",
            "character_design": "gpt-5.4",
            "scene_writing": "gpt-5.4",
            "quality_review": "gpt-5.4",
            "consistency_check": "gemini-2.5-pro",
            "style_rewrite": "deepseek-chat",
        })
        outline = get_stage_llm_config(state, "outline_generation")
        consistency = get_stage_llm_config(state, "consistency_check")
        style = get_stage_llm_config(state, "style_rewrite")

        assert outline["model"] == "gpt-5.4"
        assert consistency["model"] == "gemini-2.5-pro"
        assert style["model"] == "deepseek-chat"


# ---------------------------------------------------------------------------
# Integration: node functions call create_llm_client with correct config
# ---------------------------------------------------------------------------


class TestNodeIntegrationRouting:
    """Verify that node functions pass the stage-specific model to create_llm_client."""

    @patch("src.novel.agents.quality_reviewer.create_llm_client")
    def test_quality_reviewer_uses_quality_review_model(
        self, mock_create_llm: MagicMock
    ) -> None:
        from src.novel.agents.quality_reviewer import quality_reviewer_node

        mock_llm = MagicMock()
        mock_llm.chat.return_value = MagicMock(
            content=json.dumps({
                "plot_coherence": 8.0,
                "writing_quality": 7.5,
                "character_portrayal": 7.0,
                "ai_flavor_score": 8.0,
                "summary": "ok",
            }),
            model="test",
            usage=None,
        )
        mock_create_llm.return_value = mock_llm

        state: dict[str, Any] = {
            "current_chapter_text": "Some chapter text here.",
            "config": {
                "llm": {
                    "quality_review": "special-review-model",
                    "scene_writing": "writer-model",
                },
                "quality": {},
            },
            "current_chapter": 1,
            "auto_approve_threshold": 6.0,
        }
        quality_reviewer_node(state)

        # Verify create_llm_client was called with the quality_review model
        call_config = mock_create_llm.call_args[0][0]
        assert call_config.get("model") == "special-review-model"
        # Stage keys should be stripped
        assert "quality_review" not in call_config
        assert "scene_writing" not in call_config

    @patch("src.novel.agents.plot_planner.create_llm_client")
    def test_plot_planner_uses_outline_generation_model(
        self, mock_create_llm: MagicMock
    ) -> None:
        from src.novel.agents.plot_planner import plot_planner_node
        from src.novel.models.novel import ChapterOutline

        mock_llm = MagicMock()
        scenes_json = json.dumps({
            "scenes": [{
                "scene_number": 1,
                "title": "Scene 1",
                "summary": "test",
                "characters_involved": ["A"],
                "mood": "buildup",
                "tension_level": 0.5,
                "target_words": 800,
                "narrative_focus": "dialogue",
            }]
        })
        mock_llm.chat.return_value = MagicMock(
            content=scenes_json,
            model="test",
            usage=None,
        )
        mock_create_llm.return_value = mock_llm

        ch_outline = ChapterOutline(
            chapter_number=1,
            title="Test",
            goal="Test goal",
            key_events=["event1"],
            involved_characters=["A"],
            estimated_words=2500,
            mood="\u84c4\u529b",
        )
        state: dict[str, Any] = {
            "config": {
                "llm": {
                    "outline_generation": "planner-model",
                    "scene_writing": "writer-model",
                },
            },
            "current_chapter_outline": ch_outline.model_dump(),
            "characters": [],
        }
        plot_planner_node(state)

        call_config = mock_create_llm.call_args[0][0]
        assert call_config.get("model") == "planner-model"
        assert "outline_generation" not in call_config
