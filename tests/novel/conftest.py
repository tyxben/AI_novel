"""Shared test fixtures for novel module tests.

Common mock objects and data factories used across test files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fake LLM Response
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    """Mock LLM response matching the LLMResponse interface."""

    content: str
    model: str = "fake-model"
    usage: dict | None = None


# ---------------------------------------------------------------------------
# LLM Client Factory
# ---------------------------------------------------------------------------


def make_llm_client(
    response_json: dict | list | None = None,
    response_text: str | None = None,
    error: Exception | None = None,
) -> MagicMock:
    """Create a mock LLM client.

    Args:
        response_json: If provided, client.chat returns FakeLLMResponse with JSON content
        response_text: If provided, client.chat returns FakeLLMResponse with raw text
        error: If provided, client.chat raises this exception
    """
    client = MagicMock()
    if error:
        client.chat.side_effect = error
    elif response_json is not None:
        client.chat.return_value = FakeLLMResponse(
            content=json.dumps(response_json, ensure_ascii=False)
        )
    elif response_text is not None:
        client.chat.return_value = FakeLLMResponse(content=response_text)
    else:
        client.chat.return_value = FakeLLMResponse(content="{}")
    return client


# ---------------------------------------------------------------------------
# Sample Data Factories
# ---------------------------------------------------------------------------


def make_outline_dict(total_chapters: int = 5, template: str = "cyclic_upgrade") -> dict:
    """Create a minimal outline dict for testing."""
    moods = ["蓄力", "小爽", "大爽", "过渡", "虐心"]
    return {
        "template": template,
        "acts": [
            {
                "name": "第一幕：开端",
                "description": "主角出场",
                "start_chapter": 1,
                "end_chapter": total_chapters,
            }
        ],
        "volumes": [
            {
                "volume_number": 1,
                "title": "第一卷",
                "core_conflict": "测试矛盾",
                "resolution": "测试解决",
                "chapters": list(range(1, total_chapters + 1)),
            }
        ],
        "chapters": [
            {
                "chapter_number": i,
                "title": f"第{i}章 测试",
                "goal": f"推进第{i}章情节",
                "key_events": [f"事件{i}A", f"事件{i}B"],
                "involved_characters": [],
                "plot_threads": [],
                "estimated_words": 4000,
                "mood": moods[(i - 1) % len(moods)],
            }
            for i in range(1, total_chapters + 1)
        ],
    }


def make_world_setting_dict() -> dict:
    """Create a sample world setting dict."""
    return {
        "era": "上古时代",
        "location": "九州大陆",
        "rules": ["灵气复苏", "万族争锋"],
        "terms": {"灵气": "天地间的能量"},
        "power_system": "炼气、筑基、金丹、元婴",
    }


def make_character_dict(name: str = "主角", role: str = "主角") -> dict:
    """Create a sample character profile dict."""
    return {
        "name": name,
        "gender": "男",
        "age": 18,
        "occupation": "修仙者",
        "role": role,
        "personality": {
            "traits": ["勇敢", "坚韧", "善良"],
            "speech_style": "简洁有力",
            "core_belief": "永不放弃",
            "flaw": "冲动",
            "catchphrases": [],
        },
        "appearance": {
            "height": "180cm",
            "build": "修长",
            "distinctive_features": ["剑眉"],
            "clothing_style": "青色长袍",
        },
        "background": "平凡少年",
    }


# ---------------------------------------------------------------------------
# Pipeline Mock Nodes
# ---------------------------------------------------------------------------


def make_mock_nodes(quality_pass: bool = True) -> dict:
    """Create a complete set of mock node functions for graph testing."""

    def novel_director_node(state: dict) -> dict:
        total = state.get("_mock_total_chapters", 5)
        return {
            "outline": make_outline_dict(total),
            "total_chapters": total,
            "current_chapter": 0,
            "should_continue": True,
            "style_name": "webnovel.shuangwen",
            "template": "cyclic_upgrade",
            "decisions": [{"agent": "NovelDirector", "step": "init", "decision": "ok", "reason": "test"}],
            "errors": [],
            "completed_nodes": ["novel_director"],
        }

    def world_builder_node(state: dict) -> dict:
        return {
            "world_setting": make_world_setting_dict(),
            "decisions": [{"agent": "WorldBuilder", "step": "init", "decision": "ok", "reason": "test"}],
            "errors": [],
            "completed_nodes": ["world_builder"],
        }

    def character_designer_node(state: dict) -> dict:
        return {
            "characters": [make_character_dict("主角"), make_character_dict("反派", "反派")],
            "decisions": [{"agent": "CharacterDesigner", "step": "init", "decision": "ok", "reason": "test"}],
            "errors": [],
            "completed_nodes": ["character_designer"],
        }

    def plot_planner_node(state: dict) -> dict:
        ch = state.get("current_chapter", 1)
        return {
            "current_scenes": [
                {"scene_number": 1, "target_words": 800, "summary": f"第{ch}章场景1"},
                {"scene_number": 2, "target_words": 800, "summary": f"第{ch}章场景2"},
            ],
            "decisions": [{"agent": "PlotPlanner", "step": f"ch{ch}", "decision": "ok", "reason": "test"}],
            "errors": [],
            "completed_nodes": ["plot_planner"],
        }

    def writer_node(state: dict) -> dict:
        ch = state.get("current_chapter", 1)
        text = f"第{ch}章正文。云逸踏入了第{ch}层秘境。灵气如潮水般涌来。" * 10
        return {
            "current_chapter_text": text,
            "decisions": [{"agent": "Writer", "step": f"ch{ch}", "decision": "ok", "reason": "test"}],
            "errors": [],
            "completed_nodes": ["writer"],
        }

    def consistency_checker_node(state: dict) -> dict:
        return {
            "current_chapter_quality": {"consistency_check": {"passed": True}},
            "decisions": [{"agent": "ConsistencyChecker", "step": "check", "decision": "ok", "reason": "test"}],
            "errors": [],
            "completed_nodes": ["consistency_checker"],
        }

    def style_keeper_node(state: dict) -> dict:
        quality = dict(state.get("current_chapter_quality") or {})
        quality["style_similarity"] = 0.9
        return {
            "current_chapter_quality": quality,
            "decisions": [{"agent": "StyleKeeper", "step": "check", "decision": "ok", "reason": "test"}],
            "errors": [],
            "completed_nodes": ["style_keeper"],
        }

    def quality_pass_node(state: dict) -> dict:
        return {
            "current_chapter_quality": {"need_rewrite": False, "rule_check": {"passed": True}, "score": 8.5},
            "decisions": [{"agent": "QualityReviewer", "step": "review", "decision": "pass", "reason": "test"}],
            "errors": [],
            "completed_nodes": ["quality_reviewer"],
        }

    def quality_fail_node(state: dict) -> dict:
        return {
            "current_chapter_quality": {"need_rewrite": True, "rule_check": {"passed": False}},
            "retry_counts": {state.get("current_chapter", 1): 1},
            "decisions": [{"agent": "QualityReviewer", "step": "review", "decision": "fail", "reason": "test"}],
            "errors": [],
            "completed_nodes": ["quality_reviewer"],
        }

    return {
        "novel_director": novel_director_node,
        "world_builder": world_builder_node,
        "character_designer": character_designer_node,
        "plot_planner": plot_planner_node,
        "writer": writer_node,
        "consistency_checker": consistency_checker_node,
        "style_keeper": style_keeper_node,
        "quality_reviewer": quality_pass_node if quality_pass else quality_fail_node,
    }


# ---------------------------------------------------------------------------
# Pytest Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_llm_client():
    """Return a no-op mock LLM client."""
    return make_llm_client()


@pytest.fixture
def sample_outline():
    """Return a sample outline dict."""
    return make_outline_dict(total_chapters=5)


@pytest.fixture
def sample_world_setting():
    """Return a sample world setting dict."""
    return make_world_setting_dict()


@pytest.fixture
def sample_character():
    """Return a sample character dict."""
    return make_character_dict()
