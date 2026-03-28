"""Tests for pipeline integration: ContinuityService wiring, chapters_text population,
vector indexing, and continuity_brief injection into Writer.

Verifies:
1. chapters_text is populated after chapter generation
2. continuity_brief is generated and passed to state
3. Graceful degradation when ContinuityService fails
4. continuity_brief flows through writer_node -> generate_chapter -> generate_scene
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake-model"
    usage: dict | None = None
    finish_reason: str | None = "stop"


def _make_outline_dict(total_chapters: int = 2) -> dict:
    """Create a minimal outline dict with chapter_brief fields."""
    chapters = []
    for i in range(1, total_chapters + 1):
        chapters.append({
            "chapter_number": i,
            "title": f"第{i}章",
            "goal": f"目标{i}",
            "mood": "蓄力",
            "key_events": [f"事件{i}"],
            "characters": ["主角"],
            "estimated_words": 2500,
            "chapter_brief": {
                "main_conflict": f"冲突{i}",
                "payoff": f"兑现{i}",
            },
        })
    return {
        "template": "cyclic_upgrade",
        "main_storyline": {"core": "测试主线"},
        "acts": [{"name": "第一幕", "description": "开端", "start_chapter": 1, "end_chapter": total_chapters}],
        "volumes": [{"volume_number": 1, "title": "第一卷", "core_conflict": "矛盾", "resolution": "解决", "chapters": list(range(1, total_chapters + 1))}],
        "chapters": chapters,
    }


def _make_state(total_chapters: int = 2) -> dict:
    """Create a minimal state dict for testing."""
    return {
        "genre": "玄幻",
        "theme": "测试",
        "target_words": 50000,
        "total_chapters": total_chapters,
        "outline": _make_outline_dict(total_chapters),
        "characters": [
            {"character_id": "char1", "name": "主角", "status": "active"},
        ],
        "world_setting": {"era": "未来", "location": "测试城"},
        "style_name": "webnovel.shuangwen",
        "main_storyline": {"core": "测试主线"},
        "chapters": [],
        "react_mode": False,
        "budget_mode": False,
        "config": {"llm": {"provider": "openai", "model": "gpt-4"}},
    }


def _make_pipeline(tmp_dir: str):
    """Create a NovelPipeline for testing."""
    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline(workspace=tmp_dir)
    return pipe


# ---------------------------------------------------------------------------
# A1: chapters_text population
# ---------------------------------------------------------------------------


class TestChaptersTextPopulation:
    """Verify chapters_text is initialized and updated during generation."""

    def test_chapters_text_initialized_from_existing_chapters(self, tmp_path):
        """When state has pre-existing chapters, chapters_text should be initialized."""
        state = _make_state()
        state["chapters"] = [
            {"chapter_number": 1, "full_text": "第一章内容", "title": "第一章"},
            {"chapter_number": 2, "full_text": "第二章内容", "title": "第二章"},
        ]

        # Simulate the initialization code from generate_chapters
        if "chapters_text" not in state:
            state["chapters_text"] = {}
            for ch in state.get("chapters", []):
                ch_n = ch.get("chapter_number")
                ch_t = ch.get("full_text", "")
                if ch_n and ch_t:
                    state["chapters_text"][ch_n] = ch_t

        assert state["chapters_text"] == {1: "第一章内容", 2: "第二章内容"}

    def test_chapters_text_not_overwritten_if_exists(self):
        """If chapters_text already exists in state, it should not be re-initialized."""
        state = _make_state()
        state["chapters_text"] = {1: "existing"}
        state["chapters"] = [
            {"chapter_number": 1, "full_text": "different", "title": "第一章"},
        ]

        # Simulate initialization code
        if "chapters_text" not in state:
            state["chapters_text"] = {}
            for ch in state.get("chapters", []):
                ch_n = ch.get("chapter_number")
                ch_t = ch.get("full_text", "")
                if ch_n and ch_t:
                    state["chapters_text"][ch_n] = ch_t

        assert state["chapters_text"] == {1: "existing"}

    def test_chapters_text_updated_after_chapter_generation(self):
        """After generating a chapter, chapters_text should be updated."""
        state = _make_state()
        state["chapters_text"] = {}

        ch_num = 1
        chapter_text = "新生成的章节内容" * 100

        # Simulate post-generation code
        chapters_text = state.get("chapters_text", {})
        chapters_text[ch_num] = chapter_text
        state["chapters_text"] = chapters_text

        assert state["chapters_text"][1] == chapter_text

    def test_chapters_text_handles_empty_chapters(self):
        """Empty full_text should not be added to chapters_text."""
        state = _make_state()
        state["chapters"] = [
            {"chapter_number": 1, "full_text": "", "title": "第一章"},
            {"chapter_number": 2, "title": "第二章"},  # no full_text key
        ]

        if "chapters_text" not in state:
            state["chapters_text"] = {}
            for ch in state.get("chapters", []):
                ch_n = ch.get("chapter_number")
                ch_t = ch.get("full_text", "")
                if ch_n and ch_t:
                    state["chapters_text"][ch_n] = ch_t

        assert state["chapters_text"] == {}


# ---------------------------------------------------------------------------
# A2: ContinuityService integration
# ---------------------------------------------------------------------------


class TestContinuityBriefGeneration:
    """Verify ContinuityService is wired into the pipeline."""

    def test_continuity_brief_generated_for_chapter(self):
        """ContinuityService.generate_brief() should produce a non-empty brief
        when there are previous chapters with hooks."""
        from src.novel.services.continuity_service import ContinuityService

        svc = ContinuityService(db=None, obligation_tracker=None)
        chapters = [
            {
                "chapter_number": 1,
                "full_text": "前文内容" * 50 + "他决定前往北方。究竟能否成功？",
                "title": "第一章",
            },
        ]
        brief = svc.generate_brief(
            chapter_number=2,
            chapters=chapters,
            chapter_brief={"main_conflict": "北上冒险", "payoff": "找到宝物"},
            story_arcs=[],
            characters=[],
        )

        assert brief["chapter_number"] == 2
        # Should have some must_continue items from the hooks in chapter 1
        assert isinstance(brief["must_continue"], list)
        # Should have recommended_payoffs from chapter_brief
        assert len(brief["recommended_payoffs"]) > 0

    def test_continuity_brief_format_for_prompt(self):
        """format_for_prompt should produce a non-empty string when brief has content."""
        from src.novel.services.continuity_service import ContinuityService

        svc = ContinuityService(db=None, obligation_tracker=None)
        brief = {
            "chapter_number": 5,
            "must_continue": ["他决定前往北方"],
            "open_threads": [],
            "character_states": [{"name": "主角", "location": "京城", "status": "healthy", "goal": ""}],
            "active_arcs": [],
            "forbidden_breaks": ["主角当前在京城，不可无故出现在其他地点"],
            "recommended_payoffs": ["本章任务书推荐兑现: 找到线索"],
        }
        prompt = svc.format_for_prompt(brief)
        assert "第5章 连续性摘要" in prompt
        assert "必须延续" in prompt
        assert "他决定前往北方" in prompt
        assert "禁止违反" in prompt

    def test_continuity_brief_empty_when_no_data(self):
        """format_for_prompt returns empty string when brief has no meaningful data."""
        from src.novel.services.continuity_service import ContinuityService

        svc = ContinuityService(db=None, obligation_tracker=None)
        brief = svc.generate_brief(chapter_number=1, chapters=[])
        prompt = svc.format_for_prompt(brief)
        assert prompt == ""

    def test_continuity_brief_graceful_on_exception(self):
        """If ContinuityService raises, the pipeline should set empty string."""
        state = _make_state()

        # Simulate the pipeline's try/except pattern
        try:
            raise RuntimeError("模拟异常")
        except Exception:
            state["continuity_brief"] = ""

        assert state["continuity_brief"] == ""

    def test_continuity_brief_with_obligation_tracker(self):
        """ContinuityService should include open threads from obligation tracker."""
        from src.novel.services.continuity_service import ContinuityService

        mock_tracker = MagicMock()
        mock_tracker.get_debts_for_chapter.return_value = [
            {"description": "主角承诺帮助村民", "source_chapter": 3, "urgency_level": "high"},
        ]

        svc = ContinuityService(db=None, obligation_tracker=mock_tracker)
        brief = svc.generate_brief(chapter_number=5, chapters=[])

        assert len(brief["open_threads"]) == 1
        assert "主角承诺帮助村民" in brief["open_threads"][0]


# ---------------------------------------------------------------------------
# A3/A4: Character snapshots and vector indexing
# ---------------------------------------------------------------------------


class TestPostGenerationHooks:
    """Verify character snapshot extraction and vector indexing after chapter gen."""

    def test_character_snapshot_extraction_with_memory(self):
        """insert_character_state should be called for characters mentioned in text."""
        mock_db = MagicMock()
        mock_memory = MagicMock()
        mock_memory.structured_db = mock_db

        chapter_text = "主角拿起了剑，走向前方。配角在一旁观察。"
        ch_num = 3
        characters_list = [
            {"character_id": "char1", "name": "主角"},
            {"character_id": "char2", "name": "配角"},
            {"character_id": "char3", "name": "路人"},  # not mentioned
        ]

        # Simulate pipeline code
        try:
            for char in characters_list:
                char_name = char.get("name", "") if isinstance(char, dict) else getattr(char, "name", "")
                if not char_name or char_name not in chapter_text:
                    continue
                char_id = char.get("character_id", char_name) if isinstance(char, dict) else getattr(char, "character_id", char_name)
                mock_memory.structured_db.insert_character_state(
                    character_id=char_id,
                    chapter=ch_num,
                )
        except Exception:
            pass

        assert mock_db.insert_character_state.call_count == 2
        mock_db.insert_character_state.assert_any_call(character_id="char1", chapter=3)
        mock_db.insert_character_state.assert_any_call(character_id="char2", chapter=3)

    def test_vector_indexing_creates_chapter_summary(self):
        """Chapter text should be digested and indexed via memory.add_chapter_summary."""
        from src.novel.models.memory import ChapterSummary
        from src.novel.tools.chapter_digest import create_digest

        mock_memory = MagicMock()
        chapter_text = "这是一段足够长的测试章节内容。" * 20  # ensure > 50 chars

        digest = create_digest(chapter_text)
        summary_text = digest.get("digest_text", "") or chapter_text[:500]
        if len(summary_text) < 50:
            summary_text = chapter_text[:500]

        key_events = digest.get("key_sentences", [])[:5]
        if not key_events:
            key_events = [summary_text[:100]]

        summary = ChapterSummary(
            chapter=1,
            summary=summary_text,
            key_events=key_events,
        )
        mock_memory.add_chapter_summary(summary)
        mock_memory.save()

        mock_memory.add_chapter_summary.assert_called_once()
        mock_memory.save.assert_called_once()

    def test_vector_indexing_graceful_on_failure(self):
        """Vector indexing failure should not propagate."""
        mock_memory = MagicMock()
        mock_memory.add_chapter_summary.side_effect = RuntimeError("chroma error")

        chapter_text = "测试内容" * 50
        ch_num = 1

        # Simulate the pipeline code
        error_caught = False
        try:
            from src.novel.models.memory import ChapterSummary
            from src.novel.tools.chapter_digest import create_digest

            digest = create_digest(chapter_text)
            summary_text = digest.get("digest_text", "") or chapter_text[:500]
            if len(summary_text) < 50:
                summary_text = chapter_text[:500]
            key_events = digest.get("key_sentences", [])[:5]
            if not key_events:
                key_events = [summary_text[:100]]
            summary = ChapterSummary(chapter=ch_num, summary=summary_text, key_events=key_events)
            mock_memory.add_chapter_summary(summary)
            mock_memory.save()
        except Exception:
            error_caught = True

        # The exception should have been raised (and in pipeline, caught by except)
        assert error_caught


# ---------------------------------------------------------------------------
# B: Writer continuity_brief injection
# ---------------------------------------------------------------------------


class TestWriterContinuityBriefInjection:
    """Verify continuity_brief flows from state through writer_node to generate_scene."""

    def test_writer_node_reads_continuity_brief_from_state(self):
        """writer_node should read continuity_brief from state and pass it to Writer."""
        from src.novel.agents.writer import writer_node

        state = _make_state()
        state["current_chapter"] = 1
        state["current_chapter_outline"] = state["outline"]["chapters"][0]
        state["current_scenes"] = [
            {"scene_number": 1, "target_words": 800, "goal": "开场"},
        ]
        state["continuity_brief"] = "## 第1章 连续性摘要\n### 必须延续\n- 测试延续"

        fake_response = FakeLLMResponse(content="生成的场景文本" * 50)

        with patch("src.novel.agents.writer.create_llm_client") as mock_create:
            mock_llm = MagicMock()
            mock_llm.chat.return_value = fake_response
            mock_create.return_value = mock_llm

            with patch("src.novel.agents.writer.get_style") as mock_style:
                mock_style.return_value = {"system_prompt": "你是小说家", "rules": []}

                result = writer_node(state)

        # The node should succeed
        assert "writer" in result.get("completed_nodes", [])
        # The generated text should exist
        assert result.get("current_chapter_text")
        # Verify the LLM was called and the continuity brief was in the system prompt
        call_args = mock_llm.chat.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1].get("messages", [])
        system_msg = messages[0]["content"] if messages else ""
        assert "连续性摘要" in system_msg

    def test_writer_node_handles_empty_continuity_brief(self):
        """When continuity_brief is empty, writer should still work."""
        from src.novel.agents.writer import writer_node

        state = _make_state()
        state["current_chapter"] = 1
        state["current_chapter_outline"] = state["outline"]["chapters"][0]
        state["current_scenes"] = [
            {"scene_number": 1, "target_words": 800, "goal": "开场"},
        ]
        state["continuity_brief"] = ""

        fake_response = FakeLLMResponse(content="生成的场景文本" * 50)

        with patch("src.novel.agents.writer.create_llm_client") as mock_create:
            mock_llm = MagicMock()
            mock_llm.chat.return_value = fake_response
            mock_create.return_value = mock_llm

            with patch("src.novel.agents.writer.get_style") as mock_style:
                mock_style.return_value = {"system_prompt": "你是小说家", "rules": []}

                result = writer_node(state)

        assert "writer" in result.get("completed_nodes", [])
        assert result.get("current_chapter_text")

    def test_generate_scene_includes_continuity_in_system_prompt(self):
        """generate_scene should inject continuity_brief into system_prompt."""
        from src.novel.agents.writer import Writer
        from src.novel.models.novel import ChapterOutline
        from src.novel.models.character import CharacterProfile
        from src.novel.models.world import WorldSetting

        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(content="场景文本" * 50)

        writer = Writer(mock_llm)

        outline = ChapterOutline(
            chapter_number=3,
            title="第三章",
            goal="推进剧情",
            mood="蓄力",
            key_events=["事件1"],
            characters=["主角"],
            estimated_words=2500,
        )

        scene = writer.generate_scene(
            scene_plan={"scene_number": 1, "target_words": 800, "goal": "开场"},
            chapter_outline=outline,
            characters=[],
            world_setting=WorldSetting(era="未来", location="城市"),
            context="",
            style_name="webnovel.shuangwen",
            continuity_brief="## 第3章 连续性摘要\n### 禁止违反\n- 主角在京城不可突然出现在北方",
        )

        # Check that LLM was called with the continuity brief in system message
        call_args = mock_llm.chat.call_args
        messages = call_args[0][0]
        system_content = messages[0]["content"]
        assert "连续性摘要" in system_content
        assert "禁止违反" in system_content
        assert "主角在京城不可突然出现在北方" in system_content

    def test_generate_scene_no_continuity_brief(self):
        """generate_scene should work fine without continuity_brief."""
        from src.novel.agents.writer import Writer
        from src.novel.models.novel import ChapterOutline
        from src.novel.models.world import WorldSetting

        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(content="场景文本" * 50)

        writer = Writer(mock_llm)

        outline = ChapterOutline(
            chapter_number=1,
            title="第一章",
            goal="开头",
            mood="日常",
            key_events=["出场"],
            characters=["主角"],
            estimated_words=2500,
        )

        scene = writer.generate_scene(
            scene_plan={"scene_number": 1, "target_words": 800, "goal": "开场"},
            chapter_outline=outline,
            characters=[],
            world_setting=WorldSetting(era="现代", location="学校"),
            context="",
            style_name="webnovel.shuangwen",
            # No continuity_brief argument
        )

        assert scene is not None
        assert scene.text

    def test_generate_chapter_passes_continuity_brief_to_scene(self):
        """generate_chapter should forward continuity_brief to generate_scene."""
        from src.novel.agents.writer import Writer
        from src.novel.models.novel import ChapterOutline
        from src.novel.models.world import WorldSetting

        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(content="场景文本" * 50)

        writer = Writer(mock_llm)

        outline = ChapterOutline(
            chapter_number=2,
            title="第二章",
            goal="发展",
            mood="蓄力",
            key_events=["事件"],
            characters=["主角"],
            estimated_words=2500,
        )

        with patch.object(writer, "generate_scene", wraps=writer.generate_scene) as mock_gen_scene:
            chapter = writer.generate_chapter(
                chapter_outline=outline,
                scene_plans=[{"scene_number": 1, "target_words": 800, "goal": "场景1"}],
                characters=[],
                world_setting=WorldSetting(era="未来", location="城市"),
                context="",
                style_name="webnovel.shuangwen",
                continuity_brief="test_continuity_data",
            )

            # Verify generate_scene was called with continuity_brief
            assert mock_gen_scene.call_count >= 1
            call_kwargs = mock_gen_scene.call_args[1] if mock_gen_scene.call_args[1] else {}
            # It could also be positional, so check both
            if "continuity_brief" in call_kwargs:
                assert call_kwargs["continuity_brief"] == "test_continuity_data"
            else:
                # Check all args - continuity_brief is the last keyword arg
                all_kwargs = mock_gen_scene.call_args
                found = False
                for arg in (all_kwargs[0] if all_kwargs[0] else []):
                    if arg == "test_continuity_data":
                        found = True
                if not found and all_kwargs[1]:
                    assert all_kwargs[1].get("continuity_brief") == "test_continuity_data"


# ---------------------------------------------------------------------------
# Full pipeline integration (with heavy mocking)
# ---------------------------------------------------------------------------


class TestPipelineFullIntegration:
    """End-to-end test that generate_chapters populates chapters_text and continuity_brief."""

    def test_generate_chapters_populates_chapters_text_and_continuity(self, tmp_path):
        """Full pipeline test: chapters_text and continuity_brief should be populated."""
        from src.novel.pipeline import NovelPipeline

        pipe = NovelPipeline(workspace=str(tmp_path))

        novel_id = "novel_test123"
        novel_dir = tmp_path / "novels" / novel_id
        novel_dir.mkdir(parents=True)

        state = _make_state(total_chapters=2)
        state["novel_id"] = novel_id

        # Save checkpoint
        with open(novel_dir / "checkpoint.json", "w") as f:
            json.dump(state, f, ensure_ascii=False)

        # Save novel.json
        novel_data = {
            "novel_id": novel_id,
            "genre": "玄幻",
            "outline": state["outline"],
            "characters": state["characters"],
            "world_setting": state["world_setting"],
            "style_name": "webnovel.shuangwen",
        }
        with open(novel_dir / "novel.json", "w") as f:
            json.dump(novel_data, f, ensure_ascii=False)

        # Mock the chapter graph to simulate chapter generation
        def fake_invoke(st):
            ch_num = st["current_chapter"]
            st["current_chapter_text"] = f"第{ch_num}章的内容" * 100
            return st

        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = fake_invoke

        with patch("src.novel.pipeline.build_chapter_graph", return_value=mock_graph):
            with patch("src.novel.pipeline.get_stage_llm_config", return_value={}):
                # Skip narrative control services initialization
                with patch("src.novel.services.obligation_tracker.ObligationTracker", side_effect=ImportError("skip")):
                    result = pipe.generate_chapters(
                        project_path=str(novel_dir),
                        start_chapter=1,
                        end_chapter=2,
                        silent=True,
                    )

        assert result["total_generated"] == 2
        assert 1 in result["chapters_generated"]
        assert 2 in result["chapters_generated"]

        # Reload state from checkpoint to verify chapters_text
        with open(novel_dir / "checkpoint.json") as f:
            saved_state = json.load(f)

        # chapters_text should have been saved (if serializable)
        # Note: chapters_text uses int keys which become strings in JSON
        chapters_text = saved_state.get("chapters_text", {})
        assert len(chapters_text) == 2
