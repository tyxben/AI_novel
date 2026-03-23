"""Tests for volume-based outline generation (long novel support).

Covers:
1. NovelDirector.generate_volume_outline — generates chapter outlines for a
   specific volume given overall framework and previous content summary.
2. NovelPipeline._extend_outline — automatically extends the outline when
   requested chapters exceed the current outline range.
3. Large novel creation — verifies that novels > 30 chapters only produce
   first-volume chapter outlines at creation time.
"""

from __future__ import annotations

import json
import os
import shutil
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


def _make_volume_outline_response(start_ch: int, end_ch: int) -> str:
    """Return a JSON string that mimics LLM output for volume outline."""
    chapters = []
    for i in range(start_ch, end_ch + 1):
        chapters.append({
            "chapter_number": i,
            "title": f"第{i}章测试",
            "goal": f"目标{i}",
            "key_events": [f"事件{i}"],
            "involved_characters": [],
            "plot_threads": [],
            "estimated_words": 2500,
            "mood": "蓄力",
            "storyline_progress": f"推进主线{i}",
            "chapter_summary": f"第{i}章摘要",
            "chapter_brief": {
                "main_conflict": f"冲突{i}",
                "payoff": f"爽点{i}",
                "character_arc_step": f"变化{i}",
                "foreshadowing_plant": [],
                "foreshadowing_collect": [],
                "end_hook_type": "悬疑",
            },
        })
    return json.dumps({"chapters": chapters}, ensure_ascii=False)


def _make_outline_dict(total_chapters: int = 5) -> dict:
    """Create a minimal outline dict."""
    return {
        "template": "cyclic_upgrade",
        "main_storyline": {
            "protagonist": "张三",
            "protagonist_goal": "成为最强",
            "core_conflict": "天赋不足",
            "character_arc": "从弱小到强大",
            "stakes": "失去生命",
            "theme_statement": "坚持就是胜利",
        },
        "acts": [
            {
                "name": "第一幕",
                "description": "开端",
                "start_chapter": 1,
                "end_chapter": total_chapters,
            }
        ],
        "volumes": [
            {
                "volume_number": 1,
                "title": "第一卷",
                "core_conflict": "矛盾1",
                "resolution": "解决1",
                "chapters": list(range(1, total_chapters + 1)),
            }
        ],
        "chapters": [
            {
                "chapter_number": i,
                "title": f"第{i}章测试",
                "goal": f"目标{i}",
                "key_events": [f"事件{i}"],
                "estimated_words": 2500,
                "mood": "蓄力",
            }
            for i in range(1, total_chapters + 1)
        ],
    }


def _make_long_outline_dict(
    first_volume_chapters: int = 30,
    volume_count: int = 4,
) -> dict:
    """Create an outline for a long novel with only first-volume chapters."""
    volumes = []
    cpv = first_volume_chapters
    for v in range(1, volume_count + 1):
        start = (v - 1) * cpv + 1
        end = v * cpv
        volumes.append({
            "volume_number": v,
            "title": f"第{v}卷",
            "core_conflict": f"矛盾{v}",
            "resolution": f"解决{v}",
            "chapters": list(range(start, end + 1)),
        })

    # Only first volume has detailed chapter outlines
    chapters = [
        {
            "chapter_number": i,
            "title": f"第{i}章",
            "goal": f"目标{i}",
            "key_events": [f"事件{i}"],
            "estimated_words": 2500,
            "mood": "蓄力",
        }
        for i in range(1, first_volume_chapters + 1)
    ]

    return {
        "template": "cyclic_upgrade",
        "main_storyline": {
            "protagonist": "张三",
            "protagonist_goal": "成为最强",
            "core_conflict": "天赋不足",
            "character_arc": "从弱小到强大",
            "stakes": "失去生命",
        },
        "acts": [
            {
                "name": "第一幕",
                "description": "开端",
                "start_chapter": 1,
                "end_chapter": first_volume_chapters * volume_count,
            }
        ],
        "volumes": volumes,
        "chapters": chapters,
    }


def _make_world_setting_dict() -> dict:
    return {
        "era": "上古时代",
        "location": "九州大陆",
        "rules": [],
        "terms": {},
        "power_system": None,
    }


# ---------------------------------------------------------------------------
# Test: generate_volume_outline
# ---------------------------------------------------------------------------


class TestGenerateVolumeOutline:
    """Test NovelDirector.generate_volume_outline."""

    def test_generates_chapters_for_specified_volume(self):
        """Should generate chapter outlines for the requested volume."""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        # Volume 2 should be chapters 31-60
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(31, 60)
        )

        director = NovelDirector(mock_llm)
        novel_data = {
            "genre": "玄幻",
            "theme": "少年修炼",
            "outline": _make_long_outline_dict(30, 4),
            "world_setting": _make_world_setting_dict(),
            "characters": [
                {"name": "张三", "role": "主角"},
                {"name": "李四", "role": "反派"},
            ],
        }

        result = director.generate_volume_outline(
            novel_data=novel_data,
            volume_number=2,
            previous_summary="第1卷：张三觉醒天赋...",
        )

        assert len(result) == 30
        assert result[0]["chapter_number"] == 31
        assert result[-1]["chapter_number"] == 60
        mock_llm.chat.assert_called_once()

    def test_fallback_for_missing_volume(self):
        """When volume_number is not in outline.volumes, should still work."""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        # No volume 5 exists in the outline, so it should compute range from existing chapters
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(31, 60)
        )

        director = NovelDirector(mock_llm)
        novel_data = {
            "genre": "玄幻",
            "theme": "少年修炼",
            "outline": _make_long_outline_dict(30, 2),  # only 2 volumes defined
            "world_setting": {},
            "characters": [],
        }

        result = director.generate_volume_outline(
            novel_data=novel_data,
            volume_number=5,
            previous_summary="",
        )

        # Should still produce valid chapters (fallback uses existing_max + 1)
        assert len(result) >= 1
        assert all("chapter_number" in ch for ch in result)

    def test_fills_placeholder_on_missing_chapters(self):
        """If LLM returns fewer chapters than expected, placeholders are filled."""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        # Return only 2 of the expected 30 chapters
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(31, 32)
        )

        director = NovelDirector(mock_llm)
        novel_data = {
            "genre": "玄幻",
            "theme": "少年修炼",
            "outline": _make_long_outline_dict(30, 4),
            "world_setting": {},
            "characters": [],
        }

        result = director.generate_volume_outline(
            novel_data=novel_data,
            volume_number=2,
            previous_summary="",
        )

        # Should have all 30 chapters filled (2 real + 28 placeholder)
        assert len(result) == 30
        # First 2 have real goals, rest are placeholders
        assert result[0]["goal"] == "目标31"
        assert result[2]["goal"] == "待规划"

    def test_retries_on_llm_failure(self):
        """Should retry up to MAX_OUTLINE_RETRIES on LLM errors."""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            RuntimeError("API error"),
            RuntimeError("API error"),
            FakeLLMResponse(content=_make_volume_outline_response(31, 60)),
        ]

        director = NovelDirector(mock_llm)
        novel_data = {
            "genre": "玄幻",
            "theme": "少年修炼",
            "outline": _make_long_outline_dict(30, 4),
            "world_setting": {},
            "characters": [],
        }

        result = director.generate_volume_outline(
            novel_data=novel_data,
            volume_number=2,
            previous_summary="",
        )

        assert len(result) == 30
        assert mock_llm.chat.call_count == 3

    def test_raises_after_max_retries(self):
        """Should raise RuntimeError if all retries fail."""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("API error")

        director = NovelDirector(mock_llm)
        novel_data = {
            "genre": "玄幻",
            "theme": "少年修炼",
            "outline": _make_long_outline_dict(30, 4),
            "world_setting": {},
            "characters": [],
        }

        with pytest.raises(RuntimeError, match="大纲生成失败"):
            director.generate_volume_outline(
                novel_data=novel_data,
                volume_number=2,
                previous_summary="",
            )

    def test_invalid_json_response(self):
        """Should retry on non-JSON LLM responses."""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            FakeLLMResponse(content="这不是JSON"),
            FakeLLMResponse(content="still not json"),
            FakeLLMResponse(content=_make_volume_outline_response(31, 60)),
        ]

        director = NovelDirector(mock_llm)
        novel_data = {
            "genre": "玄幻",
            "theme": "少年修炼",
            "outline": _make_long_outline_dict(30, 4),
            "world_setting": {},
            "characters": [],
        }

        result = director.generate_volume_outline(
            novel_data=novel_data,
            volume_number=2,
            previous_summary="",
        )

        assert len(result) == 30
        assert mock_llm.chat.call_count == 3


# ---------------------------------------------------------------------------
# Test: _extend_outline
# ---------------------------------------------------------------------------


class TestExtendOutline:
    """Test NovelPipeline._extend_outline."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_project(self, outline: dict, target_words: int = 300000) -> str:
        """Create a minimal project structure on disk."""
        novel_id = "novel_test1234"
        novel_dir = Path(self.tmpdir) / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)
        (novel_dir / "chapters").mkdir(exist_ok=True)

        novel_data = {
            "novel_id": novel_id,
            "title": "Test Novel",
            "genre": "玄幻",
            "theme": "测试主题",
            "target_words": target_words,
            "outline": outline,
            "characters": [{"name": "张三", "role": "主角"}],
            "world_setting": _make_world_setting_dict(),
            "status": "initialized",
            "current_chapter": 0,
        }
        with open(novel_dir / "novel.json", "w", encoding="utf-8") as f:
            json.dump(novel_data, f, ensure_ascii=False, indent=2)

        checkpoint = {
            "outline": outline,
            "config": {"llm": {}},
            "chapters": [],
        }
        with open(novel_dir / "checkpoint.json", "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)

        return novel_id

    @patch("src.llm.llm_client.create_llm_client")
    def test_extends_outline_to_cover_target(self, mock_create_llm):
        """_extend_outline should add chapters until target_chapter is covered."""
        from src.novel.pipeline import NovelPipeline
        from src.novel.config import load_novel_config

        outline = _make_long_outline_dict(30, 4)
        novel_id = self._create_project(outline)

        # Mock the LLM to return volume 2 chapters
        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(31, 60)
        )
        mock_create_llm.return_value = mock_llm

        pipe = NovelPipeline(workspace=self.tmpdir)

        state = {
            "outline": outline,
            "config": {"llm": {}},
            "chapters": [],
        }

        pipe._extend_outline(novel_id, state, target_chapter=45)

        # State should now have 60 chapters (30 original + 30 new)
        chapters = state["outline"]["chapters"]
        chapter_nums = sorted(ch["chapter_number"] for ch in chapters)
        assert max(chapter_nums) >= 45
        assert len(chapters) == 60

    @patch("src.llm.llm_client.create_llm_client")
    def test_extends_multiple_volumes(self, mock_create_llm):
        """Should extend across multiple volumes if needed."""
        from src.novel.pipeline import NovelPipeline

        outline = _make_long_outline_dict(30, 4)
        novel_id = self._create_project(outline)

        # First call returns volume 2 (31-60), second returns volume 3 (61-90)
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            FakeLLMResponse(content=_make_volume_outline_response(31, 60)),
            FakeLLMResponse(content=_make_volume_outline_response(61, 90)),
        ]
        mock_create_llm.return_value = mock_llm

        pipe = NovelPipeline(workspace=self.tmpdir)

        state = {
            "outline": outline,
            "config": {"llm": {}},
            "chapters": [],
        }

        pipe._extend_outline(novel_id, state, target_chapter=75)

        chapters = state["outline"]["chapters"]
        chapter_nums = sorted(ch["chapter_number"] for ch in chapters)
        assert max(chapter_nums) >= 75
        assert len(chapters) == 90  # 30 + 30 + 30

    @patch("src.llm.llm_client.create_llm_client")
    def test_no_duplicate_chapters(self, mock_create_llm):
        """Should not add duplicate chapter numbers."""
        from src.novel.pipeline import NovelPipeline

        outline = _make_long_outline_dict(30, 4)
        novel_id = self._create_project(outline)

        # Return chapters that partially overlap with existing ones
        response_content = _make_volume_outline_response(25, 60)
        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(content=response_content)
        mock_create_llm.return_value = mock_llm

        pipe = NovelPipeline(workspace=self.tmpdir)

        state = {
            "outline": outline,
            "config": {"llm": {}},
            "chapters": [],
        }

        pipe._extend_outline(novel_id, state, target_chapter=50)

        chapters = state["outline"]["chapters"]
        chapter_nums = [ch["chapter_number"] for ch in chapters]
        # No duplicates
        assert len(chapter_nums) == len(set(chapter_nums))

    @patch("src.llm.llm_client.create_llm_client")
    def test_saves_checkpoint_and_novel(self, mock_create_llm):
        """Should persist changes to checkpoint.json and novel.json."""
        from src.novel.pipeline import NovelPipeline

        outline = _make_long_outline_dict(30, 4)
        novel_id = self._create_project(outline)

        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(31, 60)
        )
        mock_create_llm.return_value = mock_llm

        pipe = NovelPipeline(workspace=self.tmpdir)

        state = {
            "outline": outline,
            "config": {"llm": {}},
            "chapters": [],
        }

        pipe._extend_outline(novel_id, state, target_chapter=45)

        # Verify checkpoint was saved
        ckpt_path = Path(self.tmpdir) / "novels" / novel_id / "checkpoint.json"
        with open(ckpt_path, encoding="utf-8") as f:
            saved_ckpt = json.load(f)
        assert len(saved_ckpt["outline"]["chapters"]) == 60

        # Verify novel.json was saved
        novel_path = Path(self.tmpdir) / "novels" / novel_id / "novel.json"
        with open(novel_path, encoding="utf-8") as f:
            saved_novel = json.load(f)
        assert len(saved_novel["outline"]["chapters"]) == 60


# ---------------------------------------------------------------------------
# Test: _build_previous_summary
# ---------------------------------------------------------------------------


class TestBuildPreviousSummary:
    """Test NovelPipeline._build_previous_summary."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_written_chapters(self):
        """Should return placeholder when no chapters are written."""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=self.tmpdir)
        fm = FileManager(self.tmpdir)

        # Create project dir with no chapters
        novel_id = "novel_test1234"
        novel_dir = Path(self.tmpdir) / "novels" / novel_id / "chapters"
        novel_dir.mkdir(parents=True, exist_ok=True)

        result = pipe._build_previous_summary(novel_id, fm, up_to_chapter=30)
        assert "尚未生成" in result

    def test_summarizes_written_chapters(self):
        """Should include excerpts from written chapters."""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=self.tmpdir)
        fm = FileManager(self.tmpdir)

        novel_id = "novel_test1234"
        chapters_dir = Path(self.tmpdir) / "novels" / novel_id / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)

        # Write some chapter files
        for i in range(1, 4):
            fm.save_chapter(novel_id, i, {"chapter_number": i, "title": f"Ch{i}"})
            fm.save_chapter_text(novel_id, i, f"这是第{i}章的内容，讲述了主角的冒险故事。")

        result = pipe._build_previous_summary(novel_id, fm, up_to_chapter=10)
        assert "第1章" in result
        assert "第2章" in result
        assert "第3章" in result

    def test_respects_up_to_chapter_limit(self):
        """Should not include chapters beyond up_to_chapter."""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=self.tmpdir)
        fm = FileManager(self.tmpdir)

        novel_id = "novel_test1234"
        chapters_dir = Path(self.tmpdir) / "novels" / novel_id / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)

        for i in range(1, 6):
            fm.save_chapter(novel_id, i, {"chapter_number": i, "title": f"Ch{i}"})
            fm.save_chapter_text(novel_id, i, f"第{i}章内容")

        result = pipe._build_previous_summary(novel_id, fm, up_to_chapter=3)
        assert "第1章" in result
        assert "第3章" in result
        assert "第4章" not in result
        assert "第5章" not in result


# ---------------------------------------------------------------------------
# Test: Large novel creation (first_volume_only mode)
# ---------------------------------------------------------------------------


class TestLargeNovelOutlineGeneration:
    """Test that generate_outline produces only first-volume chapters for large novels."""

    def test_long_novel_only_generates_first_volume(self):
        """For 100k+ words, should only generate first volume chapters."""
        from src.novel.agents.novel_director import NovelDirector, _CHAPTERS_PER_VOLUME

        mock_llm = MagicMock()

        # Simulate LLM returning a proper outline with only first volume chapters
        first_vol_chapters = _CHAPTERS_PER_VOLUME  # 30
        llm_response = {
            "main_storyline": {
                "protagonist": "张三",
                "protagonist_goal": "修炼成仙",
                "core_conflict": "天赋不足",
                "character_arc": "弱小到强大",
                "stakes": "身死道消",
                "theme_statement": "逆天改命",
            },
            "acts": [
                {"name": "第一幕", "description": "觉醒", "start_chapter": 1, "end_chapter": 100},
                {"name": "第二幕", "description": "崛起", "start_chapter": 101, "end_chapter": 200},
                {"name": "第三幕", "description": "称霸", "start_chapter": 201, "end_chapter": 300},
                {"name": "第四幕", "description": "飞升", "start_chapter": 301, "end_chapter": 400},
            ],
            "volumes": [
                {"volume_number": v, "title": f"第{v}卷", "core_conflict": f"矛盾{v}", "resolution": f"解决{v}",
                 "chapters": list(range((v-1)*first_vol_chapters + 1, v*first_vol_chapters + 1))}
                for v in range(1, 14)  # ~13 volumes for 1M words
            ],
            "chapters": [
                {
                    "chapter_number": i,
                    "title": f"第{i}章",
                    "goal": f"目标{i}",
                    "key_events": [f"事件{i}"],
                    "estimated_words": 2500,
                    "mood": "蓄力",
                    "storyline_progress": f"推进{i}",
                    "chapter_summary": f"摘要{i}",
                    "chapter_brief": {},
                }
                for i in range(1, first_vol_chapters + 1)
            ],
        }
        mock_llm.chat.return_value = FakeLLMResponse(
            content=json.dumps(llm_response, ensure_ascii=False)
        )

        director = NovelDirector(mock_llm)
        outline = director.generate_outline(
            genre="玄幻",
            theme="少年修炼逆天改命",
            target_words=1000000,  # 100万字
        )

        # Should only have first volume chapters (30), not all 400
        assert len(outline.chapters) == first_vol_chapters
        assert outline.chapters[0].chapter_number == 1
        assert outline.chapters[-1].chapter_number == first_vol_chapters

        # But should have all volumes in the framework
        assert len(outline.volumes) >= 10

        # And should have acts covering the full novel
        assert len(outline.acts) >= 2

    def test_small_novel_generates_all_chapters(self):
        """For <75k words, should generate all chapters at once."""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()

        total_ch = 20  # 50000 words / 2500 = 20 chapters
        llm_response = {
            "main_storyline": {
                "protagonist": "张三",
                "protagonist_goal": "修炼",
                "core_conflict": "障碍",
                "character_arc": "成长",
                "stakes": "失败",
                "theme_statement": "主题",
            },
            "acts": [
                {"name": "第一幕", "description": "开端", "start_chapter": 1, "end_chapter": total_ch},
            ],
            "volumes": [
                {"volume_number": 1, "title": "第一卷", "core_conflict": "矛盾", "resolution": "解决",
                 "chapters": list(range(1, total_ch + 1))},
            ],
            "chapters": [
                {
                    "chapter_number": i,
                    "title": f"第{i}章",
                    "goal": f"目标{i}",
                    "key_events": [f"事件{i}"],
                    "estimated_words": 2500,
                    "mood": "蓄力",
                    "chapter_brief": {},
                }
                for i in range(1, total_ch + 1)
            ],
        }
        mock_llm.chat.return_value = FakeLLMResponse(
            content=json.dumps(llm_response, ensure_ascii=False)
        )

        director = NovelDirector(mock_llm)
        outline = director.generate_outline(
            genre="玄幻",
            theme="少年冒险",
            target_words=50000,
        )

        # All 20 chapters should be present
        assert len(outline.chapters) == total_ch

    def test_first_volume_only_prompt_contains_instruction(self):
        """For long novels, prompt should include first_volume_only instruction."""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(
            content=json.dumps({
                "main_storyline": {},
                "acts": [{"name": "幕1", "description": "d", "start_chapter": 1, "end_chapter": 400}],
                "volumes": [{"volume_number": 1, "title": "V1", "core_conflict": "c", "resolution": "r", "chapters": list(range(1, 31))}],
                "chapters": [
                    {"chapter_number": i, "title": f"Ch{i}", "goal": f"G{i}", "key_events": [f"E{i}"],
                     "estimated_words": 2500, "mood": "蓄力", "chapter_brief": {}}
                    for i in range(1, 31)
                ],
            }, ensure_ascii=False)
        )

        director = NovelDirector(mock_llm)
        director.generate_outline(
            genre="玄幻",
            theme="测试",
            target_words=1000000,
        )

        # Check that the prompt sent to LLM contains the first_volume_only instruction
        call_args = mock_llm.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args[0][0] if call_args[0] else call_args.kwargs["messages"]
        user_msg = messages[-1]["content"]
        assert "超长篇模式" in user_msg
        assert "仅第1卷" in user_msg


# ---------------------------------------------------------------------------
# Test: generate_chapters with outline extension
# ---------------------------------------------------------------------------


class TestGenerateChaptersWithExtension:
    """Integration test: generate_chapters triggers _extend_outline."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("src.novel.pipeline.build_chapter_graph")
    @patch("src.llm.llm_client.create_llm_client")
    def test_generate_chapters_extends_outline_when_needed(
        self, mock_create_llm, mock_build_graph
    ):
        """generate_chapters should extend outline if end_chapter > outlined chapters."""
        from src.novel.pipeline import NovelPipeline

        # Setup: project with 30 chapters outlined
        outline = _make_long_outline_dict(30, 4)
        novel_id = "novel_test_ext"
        novel_dir = Path(self.tmpdir) / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)
        (novel_dir / "chapters").mkdir(exist_ok=True)

        novel_data = {
            "novel_id": novel_id,
            "title": "Test",
            "genre": "玄幻",
            "theme": "测试",
            "target_words": 300000,
            "outline": outline,
            "characters": [],
            "world_setting": _make_world_setting_dict(),
            "status": "initialized",
            "current_chapter": 0,
        }
        with open(novel_dir / "novel.json", "w", encoding="utf-8") as f:
            json.dump(novel_data, f, ensure_ascii=False, indent=2)

        checkpoint = {
            "outline": outline,
            "config": {"llm": {}},
            "chapters": [],
        }
        with open(novel_dir / "checkpoint.json", "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)

        # Mock LLM for outline extension
        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(31, 60)
        )
        mock_create_llm.return_value = mock_llm

        # Mock chapter graph to simulate successful chapter generation
        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = lambda state: {
            **state,
            "current_chapter_text": f"第{state['current_chapter']}章正文内容",
        }
        mock_build_graph.return_value = mock_graph

        pipe = NovelPipeline(workspace=self.tmpdir)
        project_path = str(novel_dir)

        # Request chapters 31-35 which are beyond the current outline
        result = pipe.generate_chapters(
            project_path=project_path,
            start_chapter=31,
            end_chapter=35,
        )

        # Outline should have been extended
        ckpt_path = novel_dir / "checkpoint.json"
        with open(ckpt_path, encoding="utf-8") as f:
            saved_ckpt = json.load(f)
        assert len(saved_ckpt["outline"]["chapters"]) == 60

        # Chapters 31-35 should have been generated
        assert len(result["chapters_generated"]) == 5
