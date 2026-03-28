"""Tests for outline coverage pre-check in generate_chapters().

Verifies:
1. Placeholder outlines are detected before the generation loop.
2. _fill_placeholder_outline is called for each placeholder.
3. Chapters with unfilled placeholders are skipped in the inner loop.
4. Already-valid outlines are not touched.
5. All external deps (LLM, FileManager, etc.) are mocked.
"""

from __future__ import annotations

import json
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


def _make_outline(total: int = 5, placeholder_chapters: list[int] | None = None) -> dict:
    """Create an outline dict. Chapters in *placeholder_chapters* get placeholder goals."""
    placeholder_chapters = placeholder_chapters or []
    chapters = []
    for i in range(1, total + 1):
        if i in placeholder_chapters:
            chapters.append({
                "chapter_number": i,
                "title": f"第{i}章",
                "goal": "待规划",
                "key_events": ["待规划"],
                "estimated_words": 2500,
                "mood": "蓄力",
            })
        else:
            chapters.append({
                "chapter_number": i,
                "title": f"第{i}章·测试",
                "goal": f"目标{i}",
                "key_events": [f"事件{i}"],
                "estimated_words": 2500,
                "mood": "蓄力",
            })
    return {
        "template": "cyclic_upgrade",
        "acts": [{"name": "第一幕", "description": "开端", "start_chapter": 1, "end_chapter": total}],
        "volumes": [{"volume_number": 1, "title": "第一卷", "core_conflict": "矛盾",
                      "resolution": "解决", "chapters": list(range(1, total + 1))}],
        "chapters": chapters,
    }


def _make_state(novel_id: str = "test_novel", total: int = 5,
                placeholder_chapters: list[int] | None = None) -> dict:
    """Create a minimal state dict suitable for generate_chapters."""
    outline = _make_outline(total, placeholder_chapters)
    return {
        "genre": "玄幻",
        "theme": "修仙逆袭",
        "target_words": 50000,
        "style_name": "webnovel.shuangwen",
        "template": "cyclic_upgrade",
        "novel_id": novel_id,
        "workspace": "/tmp/test_workspace",
        "config": {},
        "current_chapter": 0,
        "total_chapters": total,
        "review_interval": 5,
        "silent_mode": True,
        "auto_approve_threshold": 6.0,
        "max_retries": 2,
        "outline": outline,
        "world_setting": {"era": "上古", "location": "九州", "rules": [], "terms": {}, "power_system": None},
        "characters": [{"name": "主角", "gender": "男", "age": 18, "occupation": "修仙者",
                         "role": "主角", "personality": {"traits": ["勇敢"], "speech_style": "简洁",
                         "core_belief": "不放弃", "flaw": "冲动", "catchphrases": []},
                         "appearance": {"height": "180", "build": "修长",
                         "distinctive_features": ["剑眉"], "clothing_style": "青色"},
                         "background": "少年"}],
        "chapters": [],
        "decisions": [],
        "errors": [],
        "completed_nodes": [],
        "retry_counts": {},
        "should_continue": True,
    }


# Mock node functions
_NODES_PATCH_TARGET = "src.novel.agents.graph._get_node_functions"


def _mock_plot_planner(state: dict) -> dict:
    return {
        "current_scenes": [{"scene_number": 1, "target_words": 800, "summary": "场景1"}],
        "decisions": [], "errors": [], "completed_nodes": ["plot_planner"],
    }


def _mock_writer(state: dict) -> dict:
    ch = state.get("current_chapter", 1)
    return {
        "current_chapter_text": f"第{ch}章正文。" * 50,
        "decisions": [], "errors": [], "completed_nodes": ["writer"],
    }


def _mock_consistency(state: dict) -> dict:
    return {
        "current_chapter_quality": {"consistency_check": {"passed": True}},
        "decisions": [], "errors": [], "completed_nodes": ["consistency_checker"],
    }


def _mock_style_keeper(state: dict) -> dict:
    quality = dict(state.get("current_chapter_quality") or {})
    quality["style_similarity"] = 0.9
    return {
        "current_chapter_quality": quality,
        "decisions": [], "errors": [], "completed_nodes": ["style_keeper"],
    }


def _mock_quality_pass(state: dict) -> dict:
    return {
        "current_chapter_quality": {"need_rewrite": False, "rule_check": {"passed": True}},
        "decisions": [], "errors": [], "completed_nodes": ["quality_reviewer"],
    }


def _get_mock_nodes() -> dict:
    return {
        "plot_planner": _mock_plot_planner,
        "writer": _mock_writer,
        "consistency_checker": _mock_consistency,
        "style_keeper": _mock_style_keeper,
        "quality_reviewer": _mock_quality_pass,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return str(ws)


@pytest.fixture
def pipeline(tmp_workspace):
    from src.novel.pipeline import NovelPipeline
    from src.novel.config import NovelConfig
    config = NovelConfig()
    return NovelPipeline(config=config, workspace=tmp_workspace)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOutlinePrecheck:
    """Tests for the outline pre-check logic before chapter generation."""

    def _setup_checkpoint(self, pipeline, novel_id: str, state: dict, tmp_workspace: str):
        """Save a checkpoint so generate_chapters can load it."""
        novel_dir = Path(tmp_workspace) / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)
        (novel_dir / "chapters").mkdir(exist_ok=True)

        # Save checkpoint
        pipeline._save_checkpoint(novel_id, state)

        # Save novel.json (needed by _refresh_state_from_novel)
        fm = pipeline._get_file_manager()
        fm.save_novel(novel_id, {
            "novel_id": novel_id,
            "genre": state["genre"],
            "theme": state["theme"],
            "outline": state["outline"],
            "characters": state["characters"],
            "world_setting": state["world_setting"],
        })

    def test_placeholder_outlines_detected_and_filled_before_loop(self, pipeline, tmp_workspace):
        """Placeholder outlines (goal=='待规划') should be detected and filled
        in the pre-check, before the chapter generation loop starts."""
        novel_id = "test_precheck_fill"
        state = _make_state(novel_id, total=5, placeholder_chapters=[3, 4])
        self._setup_checkpoint(pipeline, novel_id, state, tmp_workspace)

        project_path = str(Path(tmp_workspace) / "novels" / novel_id)
        fill_calls = []

        original_fill = pipeline._fill_placeholder_outline

        def tracking_fill(st, ch_outline, ch_num):
            fill_calls.append(ch_num)
            # Simulate a successful fill
            ch_outline = dict(ch_outline)
            ch_outline["goal"] = f"补全目标{ch_num}"
            ch_outline["key_events"] = [f"补全事件{ch_num}"]
            ch_outline["title"] = f"第{ch_num}章·补全"
            return ch_outline

        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                with patch.object(pipeline, "_fill_placeholder_outline", side_effect=tracking_fill):
                    result = pipeline.generate_chapters(
                        project_path, start_chapter=1, end_chapter=5, silent=True,
                    )

        # Pre-check should have called fill for chapters 3 and 4
        # The inner loop may also call fill but since pre-check already filled them,
        # the inner loop's _is_placeholder_outline check should be False.
        # So we expect exactly 2 calls from the pre-check.
        assert 3 in fill_calls
        assert 4 in fill_calls
        # All 5 chapters should have been generated
        assert result["total_generated"] == 5

    def test_valid_outlines_not_touched(self, pipeline, tmp_workspace):
        """Chapters with proper outlines (non-placeholder) should not have
        _fill_placeholder_outline called."""
        novel_id = "test_precheck_no_fill"
        # All chapters have valid outlines (no placeholders)
        state = _make_state(novel_id, total=3, placeholder_chapters=[])
        self._setup_checkpoint(pipeline, novel_id, state, tmp_workspace)

        project_path = str(Path(tmp_workspace) / "novels" / novel_id)

        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                with patch.object(pipeline, "_fill_placeholder_outline") as mock_fill:
                    result = pipeline.generate_chapters(
                        project_path, start_chapter=1, end_chapter=3, silent=True,
                    )

        # _fill_placeholder_outline should never be called
        mock_fill.assert_not_called()
        assert result["total_generated"] == 3

    def test_checkpoint_saved_after_precheck_fill(self, pipeline, tmp_workspace):
        """After filling placeholder outlines in the pre-check, the updated
        outline should be saved to checkpoint."""
        novel_id = "test_precheck_save"
        state = _make_state(novel_id, total=3, placeholder_chapters=[2])
        self._setup_checkpoint(pipeline, novel_id, state, tmp_workspace)

        project_path = str(Path(tmp_workspace) / "novels" / novel_id)
        save_calls = []

        original_save = pipeline._save_checkpoint

        def tracking_save(nid, st):
            save_calls.append(nid)
            return original_save(nid, st)

        def fake_fill(st, ch_outline, ch_num):
            ch_outline = dict(ch_outline)
            ch_outline["goal"] = "补全目标"
            ch_outline["key_events"] = ["补全事件"]
            ch_outline["title"] = "补全标题"
            return ch_outline

        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                with patch.object(pipeline, "_fill_placeholder_outline", side_effect=fake_fill):
                    with patch.object(pipeline, "_save_checkpoint", side_effect=tracking_save):
                        pipeline.generate_chapters(
                            project_path, start_chapter=1, end_chapter=3, silent=True,
                        )

        # The pre-check should have triggered a save (novel_id appears in save_calls)
        assert novel_id in save_calls

    def test_unfilled_placeholder_skipped_in_inner_loop(self, pipeline, tmp_workspace):
        """If _fill_placeholder_outline fails and the outline remains a
        placeholder, the chapter should be skipped with an error logged."""
        novel_id = "test_skip_placeholder"
        state = _make_state(novel_id, total=4, placeholder_chapters=[2, 3])
        self._setup_checkpoint(pipeline, novel_id, state, tmp_workspace)

        project_path = str(Path(tmp_workspace) / "novels" / novel_id)

        def failing_fill(st, ch_outline, ch_num):
            # Return the outline unchanged — it stays a placeholder
            return ch_outline

        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                with patch.object(pipeline, "_fill_placeholder_outline", side_effect=failing_fill):
                    result = pipeline.generate_chapters(
                        project_path, start_chapter=1, end_chapter=4, silent=True,
                    )

        # Chapters 2 and 3 should be skipped because fill failed
        assert 2 not in result["chapters_generated"]
        assert 3 not in result["chapters_generated"]
        # Chapters 1 and 4 should succeed
        assert 1 in result["chapters_generated"]
        assert 4 in result["chapters_generated"]
        assert result["total_generated"] == 2

    def test_unfilled_placeholder_records_error(self, pipeline, tmp_workspace):
        """Skipped placeholder chapters should record an error in state."""
        novel_id = "test_placeholder_error"
        state = _make_state(novel_id, total=3, placeholder_chapters=[2])
        self._setup_checkpoint(pipeline, novel_id, state, tmp_workspace)

        project_path = str(Path(tmp_workspace) / "novels" / novel_id)

        def failing_fill(st, ch_outline, ch_num):
            return ch_outline  # unchanged, stays placeholder

        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                with patch.object(pipeline, "_fill_placeholder_outline", side_effect=failing_fill):
                    result = pipeline.generate_chapters(
                        project_path, start_chapter=1, end_chapter=3, silent=True,
                    )

        # Load checkpoint to inspect errors
        loaded_state = pipeline._load_checkpoint(novel_id)
        errors = loaded_state.get("errors", [])
        pipeline_errors = [e for e in errors if e.get("agent") == "pipeline"]
        assert len(pipeline_errors) >= 1
        assert "第2章" in pipeline_errors[0]["message"]
        assert "占位符" in pipeline_errors[0]["message"]

    def test_precheck_fill_exception_does_not_crash(self, pipeline, tmp_workspace):
        """If _fill_placeholder_outline raises an exception during pre-check,
        it should be caught. Then in the inner loop, the method is called again
        (the real implementation has internal try/except and returns unchanged
        outline on failure). We simulate this: raise in pre-check (caught by
        pre-check try/except), return unchanged in inner loop (caught by our
        new placeholder guard which triggers `continue`)."""
        novel_id = "test_precheck_exception"
        state = _make_state(novel_id, total=3, placeholder_chapters=[2])
        self._setup_checkpoint(pipeline, novel_id, state, tmp_workspace)

        project_path = str(Path(tmp_workspace) / "novels" / novel_id)

        call_count = [0]

        def fill_that_fails_differently(st, ch_outline, ch_num):
            call_count[0] += 1
            if call_count[0] == 1:
                # Pre-check call: raise (caught by pre-check try/except)
                raise RuntimeError("LLM connection failed")
            # Inner-loop call: return unchanged (mimicking real method's internal error handling)
            return ch_outline

        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                with patch.object(pipeline, "_fill_placeholder_outline", side_effect=fill_that_fails_differently):
                    result = pipeline.generate_chapters(
                        project_path, start_chapter=1, end_chapter=3, silent=True,
                    )

        # Chapter 2 should be skipped, chapters 1 and 3 generated
        assert 1 in result["chapters_generated"]
        assert 2 not in result["chapters_generated"]
        assert 3 in result["chapters_generated"]
        assert result["total_generated"] == 2

    def test_mixed_placeholder_and_valid(self, pipeline, tmp_workspace):
        """Mix of valid and placeholder outlines: only placeholders are filled,
        valid ones are untouched."""
        novel_id = "test_mixed"
        state = _make_state(novel_id, total=5, placeholder_chapters=[1, 3, 5])
        self._setup_checkpoint(pipeline, novel_id, state, tmp_workspace)

        project_path = str(Path(tmp_workspace) / "novels" / novel_id)
        fill_calls = []

        def tracking_fill(st, ch_outline, ch_num):
            fill_calls.append(ch_num)
            ch_outline = dict(ch_outline)
            ch_outline["goal"] = f"补全目标{ch_num}"
            ch_outline["key_events"] = [f"补全事件{ch_num}"]
            ch_outline["title"] = f"第{ch_num}章·补全"
            return ch_outline

        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                with patch.object(pipeline, "_fill_placeholder_outline", side_effect=tracking_fill):
                    result = pipeline.generate_chapters(
                        project_path, start_chapter=1, end_chapter=5, silent=True,
                    )

        # Only placeholder chapters should have been filled
        assert sorted(fill_calls) == [1, 3, 5]
        # All 5 chapters should be generated
        assert result["total_generated"] == 5

    def test_chapter_not_in_outline_skipped_in_precheck(self, pipeline, tmp_workspace):
        """If a chapter number doesn't exist in the outline at all (not even
        as placeholder), the pre-check should list it as a placeholder_num
        but skip the fill (ch is None). Also _extend_outline must be mocked
        since the outline has fewer chapters than end_chapter implies."""
        novel_id = "test_missing_ch"
        # Create outline with 3 chapters, all valid
        state = _make_state(novel_id, total=3, placeholder_chapters=[])
        # Manually remove chapter 2 from outline (simulating a gap)
        state["outline"]["chapters"] = [
            ch for ch in state["outline"]["chapters"] if ch["chapter_number"] != 2
        ]
        # total_chapters in outline is now 2, but we'll ask for 1-3
        self._setup_checkpoint(pipeline, novel_id, state, tmp_workspace)

        project_path = str(Path(tmp_workspace) / "novels" / novel_id)
        fill_calls = []

        def tracking_fill(st, ch_outline, ch_num):
            fill_calls.append(ch_num)
            return ch_outline

        def noop_extend(nid, st, end_ch, cb=None):
            # Don't actually extend — leave the gap
            pass

        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                with patch.object(pipeline, "_fill_placeholder_outline", side_effect=tracking_fill):
                    with patch.object(pipeline, "_extend_outline", side_effect=noop_extend):
                        result = pipeline.generate_chapters(
                            project_path, start_chapter=1, end_chapter=3, silent=True,
                        )

        # Fill should NOT have been called for ch 2 (it doesn't exist in outline)
        assert 2 not in fill_calls
        # Chapter 2 should be skipped (outline returns None)
        assert 2 not in result["chapters_generated"]
        assert result["total_generated"] == 2
