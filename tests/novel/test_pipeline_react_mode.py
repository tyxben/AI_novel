"""Tests for react_mode / budget_mode pass-through in writer_node and pipeline.

Verifies:
1. writer_node reads react_mode/budget_mode/feedback_prompt/debt_summary from state
2. writer_node defaults to False/"" when fields are absent
3. pipeline.generate_chapters accepts react_mode/budget_mode parameters
4. state dict includes react_mode/budget_mode when passed to chapter graph
"""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chapter_outline_dict(chapter_number: int = 1) -> dict:
    """Create a chapter outline dict with valid Pydantic fields."""
    return {
        "chapter_number": chapter_number,
        "title": f"第{chapter_number}章",
        "goal": "测试目标",
        "mood": "蓄力",  # Must be a valid Literal value for ChapterOutline
        "estimated_words": 2500,
        "key_events": ["事件1"],
        "involved_characters": ["主角"],
    }


def _make_minimal_state(overrides: dict | None = None) -> dict:
    """Create a minimal state dict for writer_node."""
    state = {
        "config": {"llm": {"provider": "openai", "api_key": "fake"}},
        "current_chapter": 1,
        "total_chapters": 10,
        "current_scenes": [
            {"scene_number": 1, "target_words": 800},
            {"scene_number": 2, "target_words": 800},
        ],
        "style_name": "webnovel.shuangwen",
        "current_chapter_outline": _make_chapter_outline_dict(),
        "characters": [],
        "world_setting": {"era": "现代", "location": "北京"},
        "chapters": [],
        "outline": {
            "main_storyline": {
                "protagonist_goal": "测试",
                "core_conflict": "测试冲突",
            },
        },
    }
    if overrides:
        state.update(overrides)
    return state


def _make_fake_chapter():
    """Create a mock Chapter object returned by Writer.generate_chapter."""
    chapter = MagicMock()
    chapter.full_text = "这是测试章节内容。" * 50
    chapter.word_count = len(chapter.full_text)
    scene = MagicMock()
    scene.scene_number = 1
    scene.text = "场景文本"
    scene.model_dump.return_value = {"scene_number": 1, "text": "场景文本"}
    chapter.scenes = [scene]
    return chapter


def _get_call_kwarg(mock_method, key):
    """Extract a keyword argument from a mock's most recent call."""
    call_kwargs = mock_method.call_args
    if call_kwargs is None:
        raise AssertionError(f"{mock_method} was not called")
    # call_args is (args, kwargs); try kwargs first, then positional dict
    if key in call_kwargs.kwargs:
        return call_kwargs.kwargs[key]
    if len(call_kwargs) > 1 and isinstance(call_kwargs[1], dict) and key in call_kwargs[1]:
        return call_kwargs[1][key]
    raise KeyError(f"Keyword argument '{key}' not found in call_args: {call_kwargs}")


# ---------------------------------------------------------------------------
# Tests: writer_node reads react_mode/budget_mode from state
# ---------------------------------------------------------------------------


class TestWriterNodeModePassthrough:
    """writer_node reads mode flags from state and passes to Writer."""

    @patch("src.novel.agents.writer.create_llm_client")
    @patch("src.novel.agents.writer.Writer")
    def test_writer_node_passes_react_mode_true(self, MockWriter, mock_create_llm):
        """When react_mode=True in state, writer_node passes it to generate_chapter."""
        from src.novel.agents.writer import writer_node

        mock_create_llm.return_value = MagicMock()
        mock_writer_instance = MagicMock()
        MockWriter.return_value = mock_writer_instance
        mock_writer_instance.generate_chapter.return_value = _make_fake_chapter()

        state = _make_minimal_state({"react_mode": True, "budget_mode": True})
        result = writer_node(state)

        assert mock_writer_instance.generate_chapter.called, \
            f"generate_chapter not called; result errors: {result.get('errors')}"
        assert _get_call_kwarg(mock_writer_instance.generate_chapter, "react_mode") is True
        assert _get_call_kwarg(mock_writer_instance.generate_chapter, "budget_mode") is True

    @patch("src.novel.agents.writer.create_llm_client")
    @patch("src.novel.agents.writer.Writer")
    def test_writer_node_defaults_react_mode_false(self, MockWriter, mock_create_llm):
        """When react_mode is absent from state, writer_node defaults to False."""
        from src.novel.agents.writer import writer_node

        mock_create_llm.return_value = MagicMock()
        mock_writer_instance = MagicMock()
        MockWriter.return_value = mock_writer_instance
        mock_writer_instance.generate_chapter.return_value = _make_fake_chapter()

        state = _make_minimal_state()
        # Explicitly remove mode flags
        state.pop("react_mode", None)
        state.pop("budget_mode", None)
        state.pop("feedback_prompt", None)
        state.pop("debt_summary", None)

        result = writer_node(state)

        assert mock_writer_instance.generate_chapter.called, \
            f"generate_chapter not called; result errors: {result.get('errors')}"
        assert _get_call_kwarg(mock_writer_instance.generate_chapter, "react_mode") is False
        assert _get_call_kwarg(mock_writer_instance.generate_chapter, "budget_mode") is False
        assert _get_call_kwarg(mock_writer_instance.generate_chapter, "feedback_prompt") == ""
        assert _get_call_kwarg(mock_writer_instance.generate_chapter, "debt_summary") == ""

    @patch("src.novel.agents.writer.create_llm_client")
    @patch("src.novel.agents.writer.Writer")
    def test_writer_node_passes_feedback_prompt(self, MockWriter, mock_create_llm):
        """writer_node passes feedback_prompt from state to generate_chapter."""
        from src.novel.agents.writer import writer_node

        mock_create_llm.return_value = MagicMock()
        mock_writer_instance = MagicMock()
        MockWriter.return_value = mock_writer_instance
        mock_writer_instance.generate_chapter.return_value = _make_fake_chapter()

        state = _make_minimal_state({"feedback_prompt": "请加强打斗描写"})
        result = writer_node(state)

        assert mock_writer_instance.generate_chapter.called, \
            f"generate_chapter not called; result errors: {result.get('errors')}"
        assert _get_call_kwarg(mock_writer_instance.generate_chapter, "feedback_prompt") == "请加强打斗描写"

    @patch("src.novel.agents.writer.create_llm_client")
    @patch("src.novel.agents.writer.Writer")
    def test_writer_node_passes_debt_summary(self, MockWriter, mock_create_llm):
        """writer_node passes debt_summary from state to generate_chapter."""
        from src.novel.agents.writer import writer_node

        mock_create_llm.return_value = MagicMock()
        mock_writer_instance = MagicMock()
        MockWriter.return_value = mock_writer_instance
        mock_writer_instance.generate_chapter.return_value = _make_fake_chapter()

        state = _make_minimal_state({"debt_summary": "第3章伏笔：主角的剑有裂痕"})
        result = writer_node(state)

        assert mock_writer_instance.generate_chapter.called, \
            f"generate_chapter not called; result errors: {result.get('errors')}"
        assert _get_call_kwarg(mock_writer_instance.generate_chapter, "debt_summary") == "第3章伏笔：主角的剑有裂痕"

    @patch("src.novel.agents.writer.create_llm_client")
    @patch("src.novel.agents.writer.Writer")
    def test_writer_node_returns_success_with_modes(self, MockWriter, mock_create_llm):
        """writer_node returns correct result dict even with mode flags set."""
        from src.novel.agents.writer import writer_node

        mock_create_llm.return_value = MagicMock()
        mock_writer_instance = MagicMock()
        MockWriter.return_value = mock_writer_instance
        mock_writer_instance.generate_chapter.return_value = _make_fake_chapter()

        state = _make_minimal_state({
            "react_mode": True,
            "budget_mode": True,
            "feedback_prompt": "注意节奏",
            "debt_summary": "有伏笔待解",
        })

        result = writer_node(state)

        assert mock_writer_instance.generate_chapter.called, \
            f"generate_chapter not called; result errors: {result.get('errors')}"
        assert "writer" in result["completed_nodes"]
        assert result["current_chapter_text"] is not None
        assert len(result.get("errors", [])) == 0


# ---------------------------------------------------------------------------
# Tests: pipeline.generate_chapters accepts and passes modes
# ---------------------------------------------------------------------------


class TestPipelineReactMode:
    """Pipeline.generate_chapters accepts react_mode/budget_mode parameters."""

    def test_generate_chapters_signature_accepts_react_mode(self):
        """generate_chapters method accepts react_mode and budget_mode kwargs."""
        import inspect
        from src.novel.pipeline import NovelPipeline

        sig = inspect.signature(NovelPipeline.generate_chapters)
        params = sig.parameters

        assert "react_mode" in params
        assert params["react_mode"].default is False
        assert "budget_mode" in params
        assert params["budget_mode"].default is False

    @patch("src.novel.pipeline.build_chapter_graph")
    @patch("src.novel.pipeline.NovelPipeline._save_checkpoint")
    @patch("src.novel.pipeline.NovelPipeline._load_checkpoint")
    @patch("src.novel.pipeline.NovelPipeline._get_file_manager")
    @patch("src.novel.pipeline.NovelPipeline._refresh_state_from_novel")
    def test_state_contains_react_mode_when_passed(
        self,
        mock_refresh,
        mock_get_fm,
        mock_load_ckpt,
        mock_save_ckpt,
        mock_build_graph,
    ):
        """When react_mode=True is passed, the state dict sent to graph.invoke has react_mode=True."""
        from src.novel.pipeline import NovelPipeline

        mock_fm = MagicMock()
        mock_fm.load_novel.return_value = {"status": "generating"}
        mock_fm.list_chapters.return_value = []
        mock_get_fm.return_value = mock_fm

        mock_load_ckpt.return_value = {
            "config": {"llm": {}},
            "outline": {
                "chapters": [
                    {"chapter_number": 1, "title": "Ch1", "goal": "test",
                     "mood": "蓄力", "estimated_words": 2500,
                     "key_events": ["e1"], "involved_characters": []},
                ],
                "main_storyline": {},
            },
            "characters": [],
            "world_setting": {"era": "现代", "location": "北京"},
            "chapters": [],
        }

        captured_states = []
        mock_graph = MagicMock()

        def capture_invoke(state):
            captured_states.append(dict(state))
            state["current_chapter_text"] = "章节内容"
            return state

        mock_graph.invoke.side_effect = capture_invoke
        mock_build_graph.return_value = mock_graph

        pipe = NovelPipeline(workspace=tempfile.mkdtemp())
        pipe.generate_chapters(
            project_path="workspace/novels/test_novel",
            start_chapter=1,
            end_chapter=1,
            react_mode=True,
            budget_mode=True,
        )

        assert len(captured_states) == 1
        assert captured_states[0]["react_mode"] is True
        assert captured_states[0]["budget_mode"] is True

    @patch("src.novel.pipeline.build_chapter_graph")
    @patch("src.novel.pipeline.NovelPipeline._save_checkpoint")
    @patch("src.novel.pipeline.NovelPipeline._load_checkpoint")
    @patch("src.novel.pipeline.NovelPipeline._get_file_manager")
    @patch("src.novel.pipeline.NovelPipeline._refresh_state_from_novel")
    def test_state_defaults_react_mode_false(
        self,
        mock_refresh,
        mock_get_fm,
        mock_load_ckpt,
        mock_save_ckpt,
        mock_build_graph,
    ):
        """When react_mode is not passed, state dict defaults to False."""
        from src.novel.pipeline import NovelPipeline

        mock_fm = MagicMock()
        mock_fm.load_novel.return_value = {"status": "generating"}
        mock_fm.list_chapters.return_value = []
        mock_get_fm.return_value = mock_fm

        mock_load_ckpt.return_value = {
            "config": {"llm": {}},
            "outline": {
                "chapters": [
                    {"chapter_number": 1, "title": "Ch1", "goal": "test",
                     "mood": "蓄力", "estimated_words": 2500,
                     "key_events": ["e1"], "involved_characters": []},
                ],
                "main_storyline": {},
            },
            "characters": [],
            "world_setting": {"era": "现代", "location": "北京"},
            "chapters": [],
        }

        captured_states = []
        mock_graph = MagicMock()

        def capture_invoke(state):
            captured_states.append(dict(state))
            state["current_chapter_text"] = "章节内容"
            return state

        mock_graph.invoke.side_effect = capture_invoke
        mock_build_graph.return_value = mock_graph

        pipe = NovelPipeline(workspace=tempfile.mkdtemp())
        pipe.generate_chapters(
            project_path="workspace/novels/test_novel",
            start_chapter=1,
            end_chapter=1,
        )

        assert len(captured_states) == 1
        assert captured_states[0]["react_mode"] is False
        assert captured_states[0]["budget_mode"] is False


# ---------------------------------------------------------------------------
# Tests: task_queue worker passes react_mode/budget_mode
# ---------------------------------------------------------------------------


class TestWorkerReactMode:
    """Task queue worker passes react_mode/budget_mode to pipeline."""

    def test_worker_passes_react_mode(self):
        """_run_novel_generate passes react_mode and budget_mode from params."""
        # Patch at the source since _run_novel_generate imports locally
        with patch("src.novel.pipeline.NovelPipeline") as MockPipeline, \
             patch("src.novel.storage.file_manager.FileManager") as MockFM:
            mock_pipe = MagicMock()
            MockPipeline.return_value = mock_pipe
            mock_pipe._load_checkpoint.return_value = {
                "outline": {"chapters": [{"chapter_number": i} for i in range(1, 11)]},
            }
            mock_pipe.generate_chapters.return_value = {"chapters_generated": [1]}

            mock_fm_instance = MagicMock()
            mock_fm_instance.list_chapters.return_value = []
            MockFM.return_value = mock_fm_instance

            params = {
                "workspace": "workspace",
                "project_path": "workspace/novels/test",
                "start_chapter": 1,
                "end_chapter": 5,
                "react_mode": True,
                "budget_mode": True,
            }

            from src.task_queue.workers import _run_novel_generate
            _run_novel_generate(params, lambda pct, msg: None)

            assert mock_pipe.generate_chapters.called
            assert _get_call_kwarg(mock_pipe.generate_chapters, "react_mode") is True
            assert _get_call_kwarg(mock_pipe.generate_chapters, "budget_mode") is True

    def test_worker_defaults_react_mode_false(self):
        """_run_novel_generate defaults react_mode/budget_mode to False when not in params."""
        with patch("src.novel.pipeline.NovelPipeline") as MockPipeline, \
             patch("src.novel.storage.file_manager.FileManager") as MockFM:
            mock_pipe = MagicMock()
            MockPipeline.return_value = mock_pipe
            mock_pipe._load_checkpoint.return_value = {
                "outline": {"chapters": [{"chapter_number": i} for i in range(1, 11)]},
            }
            mock_pipe.generate_chapters.return_value = {"chapters_generated": [1]}

            mock_fm_instance = MagicMock()
            mock_fm_instance.list_chapters.return_value = []
            MockFM.return_value = mock_fm_instance

            params = {
                "workspace": "workspace",
                "project_path": "workspace/novels/test",
                "start_chapter": 1,
                "end_chapter": 5,
            }

            from src.task_queue.workers import _run_novel_generate
            _run_novel_generate(params, lambda pct, msg: None)

            assert mock_pipe.generate_chapters.called
            assert _get_call_kwarg(mock_pipe.generate_chapters, "react_mode") is False
            assert _get_call_kwarg(mock_pipe.generate_chapters, "budget_mode") is False


# ---------------------------------------------------------------------------
# Tests: NovelState type has new fields
# ---------------------------------------------------------------------------


class TestNovelStateFields:
    """NovelState TypedDict includes react_mode/budget_mode/feedback_prompt fields."""

    def test_novel_state_has_react_mode_field(self):
        from src.novel.agents.state import NovelState

        annotations = NovelState.__annotations__
        assert "react_mode" in annotations
        assert "budget_mode" in annotations
        assert "feedback_prompt" in annotations
        assert "debt_summary" in annotations
