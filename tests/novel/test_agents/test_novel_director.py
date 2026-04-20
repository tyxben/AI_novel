"""NovelDirector Agent 单元测试（Phase 3-B3 之后）

Phase 3-B3 删除的测试（已迁到 test_project_architect.py）：
- TestExtractJsonObj（_extract_json_obj 别名已删）
- TestAnalyzeInput（analyze_input 已删）
- TestGenerateOutline（generate_outline 迁到 ProjectArchitect._generate_outline）
- TestNovelDirectorNode（novel_director_node 已删）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from src.novel.agents.novel_director import NovelDirector, _make_decision
from src.novel.agents.state import NovelState
from src.novel.models.novel import Act, ChapterOutline, Outline, VolumeOutline


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake-model"
    usage: dict | None = None


def _make_llm_client(response_json: dict | None = None, error: Exception | None = None) -> MagicMock:
    client = MagicMock()
    if error is not None:
        client.chat.side_effect = error
    elif response_json is not None:
        import json as _json
        client.chat.return_value = FakeLLMResponse(
            content=_json.dumps(response_json, ensure_ascii=False)
        )
    else:
        client.chat.return_value = FakeLLMResponse(content="{}")
    return client


class TestMakeDecision:
    def test_creates_decision(self):
        d = _make_decision(step="test", decision="do something", reason="because")
        assert d["agent"] == "NovelDirector"
        assert d["step"] == "test"
        assert d["decision"] == "do something"
        assert d["reason"] == "because"
        assert "timestamp" in d


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
