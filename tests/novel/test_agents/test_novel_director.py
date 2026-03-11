"""NovelDirector Agent 单元测试"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.novel.agents.novel_director import (
    NovelDirector,
    _extract_json_obj,
    _make_decision,
    novel_director_node,
)
from src.novel.agents.state import NovelState
from src.novel.models.novel import Act, ChapterOutline, Outline, VolumeOutline


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake-model"
    usage: dict | None = None


def _make_outline_json(
    total_chapters: int = 5,
    template: str = "cyclic_upgrade",
) -> dict:
    acts = [
        {
            "name": "第一幕：开端",
            "description": "主角出场",
            "start_chapter": 1,
            "end_chapter": total_chapters,
        }
    ]
    volumes = [
        {
            "volume_number": 1,
            "title": "第一卷",
            "core_conflict": "测试矛盾",
            "resolution": "测试解决",
            "chapters": list(range(1, total_chapters + 1)),
        }
    ]
    chapters = []
    moods = ["蓄力", "小爽", "大爽", "过渡", "虐心"]
    for i in range(1, total_chapters + 1):
        chapters.append(
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
        )
    return {"acts": acts, "volumes": volumes, "chapters": chapters}


def _make_llm_client(response_json: dict | None = None, error: Exception | None = None) -> MagicMock:
    client = MagicMock()
    if error:
        client.chat.side_effect = error
    elif response_json is not None:
        client.chat.return_value = FakeLLMResponse(content=json.dumps(response_json, ensure_ascii=False))
    else:
        client.chat.return_value = FakeLLMResponse(content="{}")
    return client


# ---------------------------------------------------------------------------
# 辅助函数测试
# ---------------------------------------------------------------------------


class TestExtractJsonObj:
    def test_valid_json(self):
        assert _extract_json_obj('{"a": 1}') == {"a": 1}

    def test_json_with_surrounding_text(self):
        result = _extract_json_obj('Some text {"key": "value"} more text')
        assert result == {"key": "value"}

    def test_none_input(self):
        assert _extract_json_obj(None) is None

    def test_empty_string(self):
        assert _extract_json_obj("") is None

    def test_garbage_input(self):
        assert _extract_json_obj("this is not json at all") is None


class TestMakeDecision:
    def test_creates_decision(self):
        d = _make_decision(step="test", decision="do something", reason="because")
        assert d["agent"] == "NovelDirector"
        assert d["step"] == "test"
        assert d["decision"] == "do something"
        assert d["reason"] == "because"
        assert "timestamp" in d


# ---------------------------------------------------------------------------
# analyze_input 测试
# ---------------------------------------------------------------------------


class TestAnalyzeInput:
    def test_xuanhuan_genre(self):
        client = _make_llm_client()
        director = NovelDirector(client)
        result = director.analyze_input("玄幻", "修炼成仙", 100000)

        assert result["suggested_template"] == "cyclic_upgrade"
        assert result["suggested_style"] == "webnovel.xuanhuan"
        assert result["total_chapters"] == 40  # 100000 / 2500
        assert result["volume_count"] >= 1

    def test_suspense_genre(self):
        client = _make_llm_client()
        director = NovelDirector(client)
        result = director.analyze_input("悬疑", "连环杀手", 80000)

        assert result["suggested_template"] == "multi_thread"
        assert result["total_chapters"] == 32  # 80000 / 2500

    def test_wuxia_genre(self):
        client = _make_llm_client()
        director = NovelDirector(client)
        result = director.analyze_input("武侠", "江湖恩怨", 120000)

        assert result["suggested_template"] == "four_act"
        assert result["suggested_style"] == "wuxia.classical"

    def test_unknown_genre_defaults(self):
        client = _make_llm_client()
        director = NovelDirector(client)
        result = director.analyze_input("末日", "求生", 50000)

        assert result["suggested_template"] == "cyclic_upgrade"
        assert result["suggested_style"] == "webnovel.shuangwen"
        assert result["total_chapters"] == 20  # 50000 / 2500

    def test_custom_ideas_included(self):
        client = _make_llm_client()
        director = NovelDirector(client)
        result = director.analyze_input("玄幻", "修炼", 100000, custom_ideas="要有金手指")

        assert "金手指" in result["analysis_summary"]

    def test_small_target_words(self):
        client = _make_llm_client()
        director = NovelDirector(client)
        result = director.analyze_input("言情", "校园恋爱", 3000)

        assert result["total_chapters"] >= 1
        assert result["volume_count"] >= 1


# ---------------------------------------------------------------------------
# generate_outline 测试
# ---------------------------------------------------------------------------


class TestGenerateOutline:
    def test_valid_outline(self):
        outline_json = _make_outline_json(total_chapters=10)
        client = _make_llm_client(response_json=outline_json)
        director = NovelDirector(client)

        outline = director.generate_outline("玄幻", "修炼", 25000)  # 25000 / 2500 = 10

        assert isinstance(outline, Outline)
        assert outline.template == "cyclic_upgrade"
        assert len(outline.chapters) == 10
        assert len(outline.acts) >= 1
        assert len(outline.volumes) >= 1

    def test_chapters_sorted(self):
        outline_json = _make_outline_json(total_chapters=5)
        client = _make_llm_client(response_json=outline_json)
        director = NovelDirector(client)

        outline = director.generate_outline("都市", "重生", 12500)  # 12500 / 2500 = 5

        numbers = [ch.chapter_number for ch in outline.chapters]
        assert numbers == sorted(numbers)

    def test_fallback_on_missing_chapters(self):
        partial_json = _make_outline_json(total_chapters=3)
        client = _make_llm_client(response_json=partial_json)
        director = NovelDirector(client)

        outline = director.generate_outline("玄幻", "修炼", 12500)  # 12500 / 2500 = 5

        assert len(outline.chapters) == 5
        ch4 = next(c for c in outline.chapters if c.chapter_number == 4)
        assert ch4.title == "第4章"
        assert ch4.goal == "待规划"

    def test_fallback_on_empty_acts_and_volumes(self):
        client = _make_llm_client(response_json={"chapters": []})
        director = NovelDirector(client)

        outline = director.generate_outline("玄幻", "修炼", 7500)  # 7500 / 2500 = 3

        assert len(outline.acts) == 1
        assert outline.acts[0].name == "第一幕：开端"
        assert len(outline.volumes) == 1

    def test_invalid_template_falls_back(self):
        outline_json = _make_outline_json(total_chapters=2)
        client = _make_llm_client(response_json=outline_json)
        director = NovelDirector(client)

        outline = director.generate_outline(
            "玄幻", "修炼", 8000, template_name="nonexistent_template"
        )

        assert outline.template == "cyclic_upgrade"

    def test_llm_returns_garbage_then_valid(self):
        outline_json = _make_outline_json(total_chapters=5)
        client = MagicMock()
        client.chat.side_effect = [
            FakeLLMResponse(content="this is not json"),
            FakeLLMResponse(content=json.dumps(outline_json, ensure_ascii=False)),
        ]
        director = NovelDirector(client)

        outline = director.generate_outline("玄幻", "修炼", 20000)

        assert isinstance(outline, Outline)
        assert client.chat.call_count == 2

    def test_llm_always_returns_garbage_raises(self):
        client = MagicMock()
        client.chat.return_value = FakeLLMResponse(content="garbage")
        director = NovelDirector(client)

        with pytest.raises(RuntimeError, match="大纲生成失败"):
            director.generate_outline("玄幻", "修炼", 20000)

        assert client.chat.call_count == NovelDirector.MAX_OUTLINE_RETRIES

    def test_llm_raises_exception(self):
        client = _make_llm_client(error=ConnectionError("network down"))
        director = NovelDirector(client)

        with pytest.raises(RuntimeError, match="大纲生成失败"):
            director.generate_outline("玄幻", "修炼", 20000)


# ---------------------------------------------------------------------------
# plan_next_chapter 测试
# ---------------------------------------------------------------------------


class TestPlanNextChapter:
    def test_plan_first_chapter(self):
        client = _make_llm_client()
        director = NovelDirector(client)
        outline = Outline(
            template="cyclic_upgrade",
            acts=[Act(name="第一幕", description="开端", start_chapter=1, end_chapter=3)],
            volumes=[VolumeOutline(volume_number=1, title="V1", core_conflict="矛盾", resolution="解决", chapters=[1, 2, 3])],
            chapters=[
                ChapterOutline(chapter_number=1, title="第一章", goal="目标1", key_events=["E1"]),
                ChapterOutline(chapter_number=2, title="第二章", goal="目标2", key_events=["E2"]),
                ChapterOutline(chapter_number=3, title="第三章", goal="目标3", key_events=["E3"]),
            ],
        )
        state: NovelState = {"outline": outline.model_dump(), "chapters": [], "current_chapter": 0}

        result = director.plan_next_chapter(state)

        assert result["current_chapter"] == 1
        assert result["should_continue"] is True

    def test_plan_skips_completed(self):
        client = _make_llm_client()
        director = NovelDirector(client)
        outline = Outline(
            template="cyclic_upgrade",
            acts=[Act(name="Act1", description="D", start_chapter=1, end_chapter=2)],
            volumes=[VolumeOutline(volume_number=1, title="V1", core_conflict="C", resolution="R", chapters=[1, 2])],
            chapters=[
                ChapterOutline(chapter_number=1, title="Ch1", goal="G1", key_events=["E"]),
                ChapterOutline(chapter_number=2, title="Ch2", goal="G2", key_events=["E"]),
            ],
        )
        state: NovelState = {
            "outline": outline.model_dump(),
            "chapters": [{"chapter_number": 1}],
            "current_chapter": 1,
        }

        result = director.plan_next_chapter(state)

        assert result["current_chapter"] == 2

    def test_all_chapters_complete(self):
        client = _make_llm_client()
        director = NovelDirector(client)
        outline = Outline(
            template="cyclic_upgrade",
            acts=[Act(name="A", description="D", start_chapter=1, end_chapter=1)],
            volumes=[VolumeOutline(volume_number=1, title="V", core_conflict="C", resolution="R", chapters=[1])],
            chapters=[ChapterOutline(chapter_number=1, title="Ch1", goal="G", key_events=["E"])],
        )
        state: NovelState = {
            "outline": outline.model_dump(),
            "chapters": [{"chapter_number": 1}],
            "current_chapter": 1,
        }

        result = director.plan_next_chapter(state)

        assert result.get("should_continue") is False

    def test_plan_without_outline_returns_error(self):
        client = _make_llm_client()
        director = NovelDirector(client)
        state: NovelState = {"chapters": []}

        result = director.plan_next_chapter(state)

        assert "errors" in result
        assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# novel_director_node 测试
# ---------------------------------------------------------------------------


class TestNovelDirectorNode:
    def test_generates_outline_for_new_project(self):
        outline_json = _make_outline_json(total_chapters=5)
        fake_response = FakeLLMResponse(content=json.dumps(outline_json, ensure_ascii=False))
        mock_client = MagicMock()
        mock_client.chat.return_value = fake_response

        state: NovelState = {
            "genre": "玄幻",
            "theme": "修炼成仙",
            "target_words": 20000,
            "config": {},
        }

        with patch("src.novel.agents.novel_director.create_llm_client", return_value=mock_client):
            result = novel_director_node(state)

        assert result["outline"] is not None
        assert result["total_chapters"] >= 1
        assert "novel_director" in result["completed_nodes"]
        assert len(result["decisions"]) >= 1

    def test_resume_mode_plans_next_chapter(self):
        outline_json = _make_outline_json(total_chapters=3)
        mock_client = MagicMock()

        state: NovelState = {
            "genre": "玄幻",
            "theme": "修炼",
            "target_words": 12000,
            "config": {},
            "outline": {
                "template": "cyclic_upgrade",
                "acts": outline_json["acts"],
                "volumes": outline_json["volumes"],
                "chapters": outline_json["chapters"],
            },
            "chapters": [{"chapter_number": 1}],
            "current_chapter": 1,
        }

        with patch("src.novel.agents.novel_director.create_llm_client", return_value=mock_client):
            result = novel_director_node(state)

        assert result["current_chapter"] == 2
        assert result["should_continue"] is True
        assert "novel_director" in result["completed_nodes"]
        mock_client.chat.assert_not_called()

    def test_llm_init_failure(self):
        state: NovelState = {
            "genre": "玄幻",
            "theme": "修炼",
            "target_words": 20000,
            "config": {},
        }

        with patch(
            "src.novel.agents.novel_director.create_llm_client",
            side_effect=RuntimeError("No LLM available"),
        ):
            result = novel_director_node(state)

        assert len(result["errors"]) >= 1
        assert "LLM 初始化失败" in result["errors"][0]["message"]

    def test_outline_generation_failure_in_node(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = FakeLLMResponse(content="not json")

        state: NovelState = {
            "genre": "玄幻",
            "theme": "修炼",
            "target_words": 20000,
            "config": {},
        }

        with patch("src.novel.agents.novel_director.create_llm_client", return_value=mock_client):
            result = novel_director_node(state)

        assert len(result["errors"]) >= 1
        assert "大纲生成失败" in result["errors"][-1]["message"]
        assert "novel_director" in result["completed_nodes"]

    def test_default_values_when_no_input(self):
        outline_json = _make_outline_json(total_chapters=25)
        mock_client = MagicMock()
        mock_client.chat.return_value = FakeLLMResponse(
            content=json.dumps(outline_json, ensure_ascii=False)
        )

        state: NovelState = {"config": {}}

        with patch("src.novel.agents.novel_director.create_llm_client", return_value=mock_client):
            result = novel_director_node(state)

        assert result["outline"] is not None
        assert result["template"] == "cyclic_upgrade"

    def test_node_sets_style_from_analysis(self):
        outline_json = _make_outline_json(total_chapters=5)
        mock_client = MagicMock()
        mock_client.chat.return_value = FakeLLMResponse(
            content=json.dumps(outline_json, ensure_ascii=False)
        )

        state: NovelState = {
            "genre": "武侠",
            "theme": "江湖",
            "target_words": 20000,
            "config": {},
        }

        with patch("src.novel.agents.novel_director.create_llm_client", return_value=mock_client):
            result = novel_director_node(state)

        assert result["style_name"] == "wuxia.classical"
