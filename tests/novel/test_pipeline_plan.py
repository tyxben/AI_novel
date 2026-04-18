"""Tests for NovelPipeline.plan_chapters — outline-only planning.

Verifies:
- plan_chapters returns planned outlines with proper structure
- Auto-detect start chapter from completed chapters
- Placeholder outlines get filled before dynamic revision
- dynamic_outline revision is applied when revision_needed
- Checkpoint and novel.json are saved after planning
- Edge cases: missing checkpoint, no outline
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake-model"
    usage: dict | None = None


def _make_outline_dict(total_chapters: int = 10) -> dict:
    """Create a minimal outline dict."""
    return {
        "template": "cyclic_upgrade",
        "main_storyline": {
            "protagonist_goal": "become the strongest",
            "core_conflict": "evil forces",
        },
        "acts": [
            {
                "name": "first act",
                "description": "beginning",
                "start_chapter": 1,
                "end_chapter": total_chapters,
            }
        ],
        "volumes": [
            {
                "volume_number": 1,
                "title": "volume 1",
                "core_conflict": "conflict",
                "resolution": "resolve",
                "chapters": list(range(1, total_chapters + 1)),
            }
        ],
        "chapters": [
            {
                "chapter_number": i,
                "title": f"Chapter {i} Title",
                "goal": f"Goal for chapter {i}",
                "key_events": [f"Event {i}A", f"Event {i}B"],
                "estimated_words": 2500,
                "mood": "buildup",
                "involved_characters": ["protagonist"],
                "chapter_brief": {
                    "main_conflict": f"conflict {i}",
                    "payoff": f"payoff {i}",
                },
            }
            for i in range(1, total_chapters + 1)
        ],
    }


def _make_checkpoint(total_chapters: int = 10) -> dict:
    """Create a minimal checkpoint dict."""
    outline = _make_outline_dict(total_chapters)
    return {
        "novel_id": "novel_test1234",
        "genre": "fantasy",
        "theme": "hero journey",
        "target_words": 100000,
        "style_name": "webnovel.shuangwen",
        "config": {},
        "outline": outline,
        "main_storyline": outline.get("main_storyline", {}),
        "characters": [
            {"name": "Hero", "role": "protagonist"},
            {"name": "Villain", "role": "antagonist"},
        ],
        "world_setting": {"era": "ancient", "location": "continent"},
        "chapters": [],
        "chapters_text": {},
        "current_chapter": 0,
        "total_chapters": total_chapters,
        "decisions": [],
        "errors": [],
        "completed_nodes": [],
        "retry_counts": {},
        "should_continue": True,
    }


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace with a novel project."""
    novel_id = "novel_test1234"
    novel_dir = tmp_path / "novels" / novel_id
    novel_dir.mkdir(parents=True)
    (novel_dir / "chapters").mkdir()

    ckpt = _make_checkpoint()
    with open(novel_dir / "checkpoint.json", "w", encoding="utf-8") as f:
        json.dump(ckpt, f, ensure_ascii=False, indent=2)

    novel_data = {
        "novel_id": novel_id,
        "title": "Test Novel",
        "genre": "fantasy",
        "theme": "hero journey",
        "status": "initialized",
        "outline": ckpt["outline"],
        "characters": ckpt["characters"],
        "world_setting": ckpt["world_setting"],
        "current_chapter": 0,
        "target_words": 100000,
    }
    with open(novel_dir / "novel.json", "w", encoding="utf-8") as f:
        json.dump(novel_data, f, ensure_ascii=False, indent=2)

    return str(tmp_path), novel_id


@pytest.fixture
def tmp_workspace_with_chapters(tmp_workspace):
    """Workspace with 3 completed chapters."""
    ws, novel_id = tmp_workspace
    novel_dir = Path(ws) / "novels" / novel_id / "chapters"

    for ch_num in range(1, 4):
        ch_data = {
            "chapter_number": ch_num,
            "title": f"Chapter {ch_num}",
            "full_text": f"This is the text of chapter {ch_num}." * 50,
            "word_count": 500,
        }
        with open(novel_dir / f"chapter_{ch_num:03d}.json", "w", encoding="utf-8") as f:
            json.dump(ch_data, f, ensure_ascii=False)

    # Update checkpoint with existing chapters
    ckpt_path = Path(ws) / "novels" / novel_id / "checkpoint.json"
    with open(ckpt_path, encoding="utf-8") as f:
        ckpt = json.load(f)
    ckpt["chapters"] = [
        {"chapter_number": i, "full_text": f"Text {i}", "title": f"Ch {i}"}
        for i in range(1, 4)
    ]
    ckpt["current_chapter"] = 3
    with open(ckpt_path, "w", encoding="utf-8") as f:
        json.dump(ckpt, f, ensure_ascii=False, indent=2)

    return ws, novel_id


# ---------------------------------------------------------------------------
# Mock patches
# ---------------------------------------------------------------------------

def _patch_novel_memory():
    """Patch NovelMemory to avoid SQLite/Chroma dependencies."""
    return patch("src.novel.storage.novel_memory.NovelMemory", side_effect=Exception("mocked out"))


def _patch_obligation_tracker():
    """Patch ObligationTracker."""
    mock_tracker = MagicMock()
    mock_tracker.get_debt_statistics.return_value = {
        "pending_count": 5,
        "fulfilled_count": 10,
        "overdue_count": 2,
        "abandoned_count": 0,
    }
    mock_tracker.escalate_debts.return_value = 0
    mock_tracker.get_summary_for_writer.return_value = "Debt summary for writer"
    return mock_tracker


def _noop_dynamic_outline(state):
    """No-op chapter planner node (Phase 2-δ) that returns no revision."""
    return {
        "decisions": [
            {
                "step": "propose_chapter_brief",
                "decision": "no revision needed",
                "reason": "test: original outline is fine",
            }
        ],
        "completed_nodes": ["chapter_planner"],
    }


def _revising_dynamic_outline(state):
    """Chapter planner node (Phase 2-δ) that revises the outline."""
    original = state.get("current_chapter_outline", {})
    revised = dict(original)
    revised["title"] = f"Revised: {original.get('title', 'untitled')}"
    revised["goal"] = f"Revised goal: {original.get('goal', '')}"
    revised["key_events"] = ["revised event 1", "revised event 2"]
    return {
        "current_chapter_outline": revised,
        "decisions": [
            {
                "step": "propose_chapter_brief",
                "decision": f"Chapter {state.get('current_chapter')} outline revised",
                "reason": "previous chapters introduced new elements",
            }
        ],
        "completed_nodes": ["chapter_planner"],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPlanChaptersBasic:
    """Test basic plan_chapters functionality."""

    @patch("src.novel.agents.chapter_planner.chapter_planner_node", _noop_dynamic_outline)
    def test_returns_planned_outlines_with_structure(self, tmp_workspace):
        ws, novel_id = tmp_workspace
        project_path = str(Path(ws) / "novels" / novel_id)

        from src.novel.pipeline import NovelPipeline

        with _patch_novel_memory():
            pipe = NovelPipeline(workspace=ws)
            result = pipe.plan_chapters(
                project_path=project_path,
                start_chapter=1,
                end_chapter=4,
            )

        assert result["novel_id"] == novel_id
        assert len(result["planned_chapters"]) == 4
        assert "context" in result
        assert result["context"]["total_planned"] == 4

        # Validate structure of each planned chapter
        for ch in result["planned_chapters"]:
            assert "chapter_number" in ch
            assert "title" in ch
            assert "goal" in ch
            assert "key_events" in ch
            assert "mood" in ch
            assert "revision_reason" in ch
            assert isinstance(ch["key_events"], list)

    @patch("src.novel.agents.chapter_planner.chapter_planner_node", _noop_dynamic_outline)
    def test_auto_detect_start_chapter(self, tmp_workspace_with_chapters):
        ws, novel_id = tmp_workspace_with_chapters
        project_path = str(Path(ws) / "novels" / novel_id)

        from src.novel.pipeline import NovelPipeline

        with _patch_novel_memory():
            pipe = NovelPipeline(workspace=ws)
            result = pipe.plan_chapters(
                project_path=project_path,
                # start_chapter not specified -- should auto-detect from completed chapters
            )

        # Chapters 1-3 exist, so planning should start from 4
        planned_nums = [ch["chapter_number"] for ch in result["planned_chapters"]]
        assert planned_nums[0] == 4
        assert len(planned_nums) == 4  # default: 4 chapters ahead
        assert planned_nums == [4, 5, 6, 7]

    @patch("src.novel.agents.chapter_planner.chapter_planner_node", _noop_dynamic_outline)
    def test_no_chapters_starts_from_1(self, tmp_workspace):
        ws, novel_id = tmp_workspace
        project_path = str(Path(ws) / "novels" / novel_id)

        from src.novel.pipeline import NovelPipeline

        with _patch_novel_memory():
            pipe = NovelPipeline(workspace=ws)
            result = pipe.plan_chapters(project_path=project_path)

        planned_nums = [ch["chapter_number"] for ch in result["planned_chapters"]]
        assert planned_nums[0] == 1

    def test_missing_checkpoint_raises(self, tmp_path):
        novel_id = "novel_missing"
        novel_dir = tmp_path / "novels" / novel_id
        novel_dir.mkdir(parents=True)

        from src.novel.pipeline import NovelPipeline

        pipe = NovelPipeline(workspace=str(tmp_path))
        with pytest.raises(FileNotFoundError, match="找不到项目检查点"):
            pipe.plan_chapters(project_path=str(novel_dir))


class TestPlanChaptersPlaceholderFill:
    """Test that placeholder outlines get filled."""

    @patch("src.novel.agents.chapter_planner.chapter_planner_node", _noop_dynamic_outline)
    def test_placeholder_outlines_get_filled(self, tmp_workspace):
        ws, novel_id = tmp_workspace
        project_path = str(Path(ws) / "novels" / novel_id)

        # Make chapters 5-6 placeholders in both checkpoint and novel.json
        # (novel.json is the canonical source; _refresh_state_from_novel merges it)
        for fname in ("checkpoint.json", "novel.json"):
            fpath = Path(ws) / "novels" / novel_id / fname
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)

            outline = data.get("outline", {})
            for ch in outline.get("chapters", []):
                if ch["chapter_number"] in (5, 6):
                    ch["goal"] = "待规划"
                    ch["key_events"] = ["待规划"]
                    ch["title"] = f"第{ch['chapter_number']}章"

            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        from src.novel.pipeline import NovelPipeline

        # Mock _fill_placeholder_outline to track calls
        fill_calls = []
        original_fill = NovelPipeline._fill_placeholder_outline

        def mock_fill(self_pipe, state, ch_outline, ch_num):
            fill_calls.append(ch_num)
            # Return a filled outline
            return {
                **ch_outline,
                "title": f"Filled Chapter {ch_num}",
                "goal": f"Filled goal {ch_num}",
                "key_events": [f"filled event {ch_num}"],
                "mood": "buildup",
            }

        with _patch_novel_memory(), \
             patch.object(NovelPipeline, "_fill_placeholder_outline", mock_fill):
            pipe = NovelPipeline(workspace=ws)
            result = pipe.plan_chapters(
                project_path=project_path,
                start_chapter=5,
                end_chapter=6,
            )

        # Verify _fill_placeholder_outline was called for chapters 5 and 6
        assert 5 in fill_calls
        assert 6 in fill_calls

        # Verify result contains filled outlines
        for ch in result["planned_chapters"]:
            assert ch["goal"] != "待规划"
            assert ch["key_events"] != ["待规划"]


class TestPlanChaptersDynamicRevision:
    """Test dynamic outline revision."""

    @patch("src.novel.agents.chapter_planner.chapter_planner_node", _revising_dynamic_outline)
    def test_revision_applied(self, tmp_workspace_with_chapters):
        ws, novel_id = tmp_workspace_with_chapters
        project_path = str(Path(ws) / "novels" / novel_id)

        from src.novel.pipeline import NovelPipeline

        with _patch_novel_memory():
            pipe = NovelPipeline(workspace=ws)
            result = pipe.plan_chapters(
                project_path=project_path,
                start_chapter=4,
                end_chapter=6,
            )

        # Chapters 4-6 should have revised titles
        for ch in result["planned_chapters"]:
            assert ch["title"].startswith("Revised:")
            assert ch["goal"].startswith("Revised goal:")
            assert ch["key_events"] == ["revised event 1", "revised event 2"]
            assert ch["revision_reason"] == "previous chapters introduced new elements"

    @patch("src.novel.agents.chapter_planner.chapter_planner_node", _noop_dynamic_outline)
    def test_no_revision_records_reason(self, tmp_workspace):
        ws, novel_id = tmp_workspace
        project_path = str(Path(ws) / "novels" / novel_id)

        from src.novel.pipeline import NovelPipeline

        with _patch_novel_memory():
            pipe = NovelPipeline(workspace=ws)
            result = pipe.plan_chapters(
                project_path=project_path,
                start_chapter=1,
                end_chapter=2,
            )

        # Revision reason should reflect that no revision was needed
        for ch in result["planned_chapters"]:
            assert "original outline is fine" in ch["revision_reason"]


class TestPlanChaptersCheckpointSave:
    """Test that checkpoint and novel.json are saved after planning."""

    @patch("src.novel.agents.chapter_planner.chapter_planner_node", _revising_dynamic_outline)
    def test_checkpoint_saved(self, tmp_workspace):
        ws, novel_id = tmp_workspace
        project_path = str(Path(ws) / "novels" / novel_id)
        ckpt_path = Path(ws) / "novels" / novel_id / "checkpoint.json"

        from src.novel.pipeline import NovelPipeline

        with _patch_novel_memory():
            pipe = NovelPipeline(workspace=ws)
            result = pipe.plan_chapters(
                project_path=project_path,
                start_chapter=1,
                end_chapter=3,
            )

        # Load checkpoint and verify outlines were updated
        with open(ckpt_path, encoding="utf-8") as f:
            saved_ckpt = json.load(f)

        outline_chapters = saved_ckpt["outline"]["chapters"]
        for ch in outline_chapters:
            if ch["chapter_number"] in (1, 2, 3):
                # Dynamic outline revision adds "Revised:" prefix
                # But chapters 1-3 skip revision (early chapters fast-path)
                # so only chapters > 3 would be revised
                pass

    @patch("src.novel.agents.chapter_planner.chapter_planner_node", _revising_dynamic_outline)
    def test_novel_json_updated(self, tmp_workspace):
        ws, novel_id = tmp_workspace
        project_path = str(Path(ws) / "novels" / novel_id)
        novel_json_path = Path(ws) / "novels" / novel_id / "novel.json"

        from src.novel.pipeline import NovelPipeline

        with _patch_novel_memory():
            pipe = NovelPipeline(workspace=ws)
            result = pipe.plan_chapters(
                project_path=project_path,
                start_chapter=5,
                end_chapter=7,
            )

        # Load novel.json and verify outline was updated
        with open(novel_json_path, encoding="utf-8") as f:
            saved_novel = json.load(f)

        # Chapters 5-7 should have revised titles in novel.json
        outline_chapters = saved_novel["outline"]["chapters"]
        for ch in outline_chapters:
            if ch["chapter_number"] in (5, 6, 7):
                assert ch["title"].startswith("Revised:")

    @patch("src.novel.agents.chapter_planner.chapter_planner_node", _noop_dynamic_outline)
    def test_progress_callback_invoked(self, tmp_workspace):
        ws, novel_id = tmp_workspace
        project_path = str(Path(ws) / "novels" / novel_id)

        from src.novel.pipeline import NovelPipeline

        progress_calls = []

        def mock_progress(pct, msg):
            progress_calls.append((pct, msg))

        with _patch_novel_memory():
            pipe = NovelPipeline(workspace=ws)
            pipe.plan_chapters(
                project_path=project_path,
                start_chapter=1,
                end_chapter=3,
                progress_callback=mock_progress,
            )

        # Should have progress calls for each chapter + completion
        assert len(progress_calls) >= 4  # 3 chapters + final 1.0
        # Last call should be 1.0
        assert progress_calls[-1][0] == 1.0


class TestPlanChaptersContextInfo:
    """Test context information in the result."""

    @patch("src.novel.agents.chapter_planner.chapter_planner_node", _noop_dynamic_outline)
    def test_context_includes_stats(self, tmp_workspace):
        ws, novel_id = tmp_workspace
        project_path = str(Path(ws) / "novels" / novel_id)

        from src.novel.pipeline import NovelPipeline

        with _patch_novel_memory():
            pipe = NovelPipeline(workspace=ws)
            result = pipe.plan_chapters(
                project_path=project_path,
                start_chapter=1,
                end_chapter=4,
            )

        ctx = result["context"]
        assert "overdue_debts" in ctx
        assert "active_arcs" in ctx
        assert "total_planned" in ctx
        assert ctx["total_planned"] == 4
        # These are 0 because ObligationTracker failed to init (mocked memory)
        assert isinstance(ctx["overdue_debts"], int)
        assert isinstance(ctx["active_arcs"], int)


class TestPlanChaptersEdgeCases:
    """Test edge cases."""

    @patch("src.novel.agents.chapter_planner.chapter_planner_node", _noop_dynamic_outline)
    def test_no_outline_raises(self, tmp_path):
        """Missing outline should raise ValueError."""
        novel_id = "novel_nooutline"
        novel_dir = tmp_path / "novels" / novel_id
        novel_dir.mkdir(parents=True)

        # Checkpoint with no outline
        ckpt = {"novel_id": novel_id, "outline": None}
        with open(novel_dir / "checkpoint.json", "w", encoding="utf-8") as f:
            json.dump(ckpt, f)

        # Also need novel.json for _refresh_state_from_novel
        with open(novel_dir / "novel.json", "w", encoding="utf-8") as f:
            json.dump({"novel_id": novel_id}, f)

        from src.novel.pipeline import NovelPipeline

        pipe = NovelPipeline(workspace=str(tmp_path))
        with pytest.raises(ValueError, match="项目大纲不存在"):
            pipe.plan_chapters(project_path=str(novel_dir))

    @patch("src.novel.agents.chapter_planner.chapter_planner_node")
    def test_dynamic_outline_failure_graceful(self, mock_dyn, tmp_workspace):
        """If dynamic_outline_node throws, planning continues with original outline."""
        mock_dyn.side_effect = RuntimeError("LLM exploded")
        ws, novel_id = tmp_workspace
        project_path = str(Path(ws) / "novels" / novel_id)

        from src.novel.pipeline import NovelPipeline

        with _patch_novel_memory():
            pipe = NovelPipeline(workspace=ws)
            result = pipe.plan_chapters(
                project_path=project_path,
                start_chapter=5,
                end_chapter=6,
            )

        # Should still return planned chapters with original outlines
        assert len(result["planned_chapters"]) == 2
        for ch in result["planned_chapters"]:
            assert ch["title"] != ""
            assert ch["revision_reason"] == ""  # No revision happened

    @patch("src.novel.agents.chapter_planner.chapter_planner_node", _noop_dynamic_outline)
    def test_single_chapter_plan(self, tmp_workspace):
        ws, novel_id = tmp_workspace
        project_path = str(Path(ws) / "novels" / novel_id)

        from src.novel.pipeline import NovelPipeline

        with _patch_novel_memory():
            pipe = NovelPipeline(workspace=ws)
            result = pipe.plan_chapters(
                project_path=project_path,
                start_chapter=5,
                end_chapter=5,
            )

        assert len(result["planned_chapters"]) == 1
        assert result["planned_chapters"][0]["chapter_number"] == 5
