"""Tests for NovelPipeline._drop_stale_llm_provider.

Regression: checkpoint.json may contain a provider/model from an earlier
session whose API key is no longer in the environment. Subsequent runs
would try that provider, fail, log a warning, and fall back to auto-detect
on every LLM call. We now strip the stale fields up front.
"""

from __future__ import annotations

import pytest

from src.novel.pipeline import NovelPipeline


def _state(**llm_kwargs) -> dict:
    return {"config": {"llm": dict(llm_kwargs)}}


class TestDropStaleProvider:
    def test_strips_openai_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        state = _state(provider="openai", model="gpt-5.4")
        NovelPipeline._drop_stale_llm_provider(state)
        assert "provider" not in state["config"]["llm"]
        assert "model" not in state["config"]["llm"]

    def test_keeps_provider_when_key_present(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        state = _state(provider="openai", model="gpt-5.4")
        NovelPipeline._drop_stale_llm_provider(state)
        assert state["config"]["llm"]["provider"] == "openai"
        assert state["config"]["llm"]["model"] == "gpt-5.4"

    def test_keeps_provider_when_inline_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        state = _state(provider="openai", model="gpt-x", api_key="sk-inline")
        NovelPipeline._drop_stale_llm_provider(state)
        assert state["config"]["llm"]["provider"] == "openai"

    def test_strips_deepseek_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        state = _state(provider="deepseek", model="deepseek-chat")
        NovelPipeline._drop_stale_llm_provider(state)
        assert "provider" not in state["config"]["llm"]

    def test_leaves_auto_alone(self):
        state = _state(provider="auto")
        NovelPipeline._drop_stale_llm_provider(state)
        assert state["config"]["llm"]["provider"] == "auto"

    def test_leaves_unknown_provider_alone(self, monkeypatch):
        # We don't know how to validate ollama / custom backends — don't touch
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        state = _state(provider="ollama", model="qwen")
        NovelPipeline._drop_stale_llm_provider(state)
        assert state["config"]["llm"]["provider"] == "ollama"

    def test_no_config_section(self):
        state: dict = {}
        NovelPipeline._drop_stale_llm_provider(state)
        assert state == {}

    def test_no_llm_section(self):
        state: dict = {"config": {}}
        NovelPipeline._drop_stale_llm_provider(state)
        assert state == {"config": {}}

    def test_llm_not_dict_safe(self):
        state: dict = {"config": {"llm": "not-a-dict"}}
        NovelPipeline._drop_stale_llm_provider(state)
        # Should not raise and should not mutate
        assert state["config"]["llm"] == "not-a-dict"

    def test_preserves_other_llm_fields(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        state = _state(
            provider="openai",
            model="gpt-x",
            scene_writing="deepseek-chat",
            quality_review="deepseek-chat",
            temperature=0.7,
        )
        NovelPipeline._drop_stale_llm_provider(state)
        # Stage models + non-provider fields preserved
        assert state["config"]["llm"]["scene_writing"] == "deepseek-chat"
        assert state["config"]["llm"]["quality_review"] == "deepseek-chat"
        assert state["config"]["llm"]["temperature"] == 0.7
        assert "provider" not in state["config"]["llm"]
        assert "model" not in state["config"]["llm"]
