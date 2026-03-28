"""Tests for generate_chapters tool in Agent Chat."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.novel.services.agent_chat import AgentToolExecutor, TOOLS


class TestGenerateChaptersToolDefinition:
    """Test that generate_chapters is properly registered in TOOLS."""

    def test_tool_exists_in_tools_list(self):
        tool_names = [t["name"] for t in TOOLS]
        assert "generate_chapters" in tool_names

    def test_tool_has_correct_parameters(self):
        tool = next(t for t in TOOLS if t["name"] == "generate_chapters")
        params = tool["parameters"]
        assert "num_chapters" in params
        assert "start_chapter" in params
        assert params["num_chapters"]["type"] == "integer"
        assert params["start_chapter"]["type"] == "integer"
        assert params["num_chapters"].get("optional") is True
        assert params["start_chapter"].get("optional") is True

    def test_tool_has_description(self):
        tool = next(t for t in TOOLS if t["name"] == "generate_chapters")
        assert "生成新章节" in tool["description"]


class TestGenerateChaptersExecution:
    """Test _tool_generate_chapters via the executor."""

    def setup_method(self):
        self.executor = AgentToolExecutor(workspace="/tmp/test_ws", novel_id="novel_abc")

    @patch("src.novel.services.agent_chat.AgentToolExecutor._tool_generate_chapters")
    def test_execute_dispatches_to_generate_chapters(self, mock_method):
        mock_method.return_value = {"success": True}
        result = self.executor.execute("generate_chapters", {"num_chapters": 2})
        mock_method.assert_called_once_with(num_chapters=2)

    @patch("src.novel.pipeline.NovelPipeline.generate_chapters")
    @patch("src.novel.storage.file_manager.FileManager.list_chapters")
    def test_auto_detect_start_chapter(self, mock_list, mock_gen):
        """When start_chapter is not provided, it should be auto-detected."""
        mock_list.return_value = [1, 2, 3, 4, 5]
        mock_gen.return_value = {
            "chapters_generated": [6],
            "total_generated": 1,
            "errors": [],
        }

        result = self.executor._tool_generate_chapters(num_chapters=1)

        assert result["success"] is True
        assert result["start_chapter"] == 6
        assert result["end_chapter"] == 6
        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["start_chapter"] == 6
        assert call_kwargs["end_chapter"] == 6

    @patch("src.novel.pipeline.NovelPipeline.generate_chapters")
    @patch("src.novel.storage.file_manager.FileManager.list_chapters")
    def test_auto_detect_start_chapter_no_existing(self, mock_list, mock_gen):
        """When no chapters exist, start_chapter should be 1."""
        mock_list.return_value = []
        mock_gen.return_value = {
            "chapters_generated": [1],
            "total_generated": 1,
            "errors": [],
        }

        result = self.executor._tool_generate_chapters(num_chapters=1)

        assert result["success"] is True
        assert result["start_chapter"] == 1
        assert result["end_chapter"] == 1

    @patch("src.novel.pipeline.NovelPipeline.generate_chapters")
    @patch("src.novel.storage.file_manager.FileManager.list_chapters")
    def test_explicit_start_chapter(self, mock_list, mock_gen):
        """When start_chapter is provided, use it directly."""
        mock_gen.return_value = {
            "chapters_generated": [10, 11, 12],
            "total_generated": 3,
            "errors": [],
        }

        result = self.executor._tool_generate_chapters(num_chapters=3, start_chapter=10)

        assert result["success"] is True
        assert result["start_chapter"] == 10
        assert result["end_chapter"] == 12
        # list_chapters should not be called when start_chapter is explicit
        mock_list.assert_not_called()

    @patch("src.novel.pipeline.NovelPipeline.generate_chapters")
    @patch("src.novel.storage.file_manager.FileManager.list_chapters")
    def test_num_chapters_capped_at_10(self, mock_list, mock_gen):
        """num_chapters should be capped at 10."""
        mock_list.return_value = [1]
        mock_gen.return_value = {
            "chapters_generated": list(range(2, 12)),
            "total_generated": 10,
            "errors": [],
        }

        result = self.executor._tool_generate_chapters(num_chapters=50)

        assert result["end_chapter"] == 11  # start=2, end=2+10-1=11
        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["end_chapter"] == 11

    @patch("src.novel.pipeline.NovelPipeline.generate_chapters")
    @patch("src.novel.storage.file_manager.FileManager.list_chapters")
    def test_num_chapters_min_is_1(self, mock_list, mock_gen):
        """num_chapters=0 or negative should be clamped to 1."""
        mock_list.return_value = [1, 2]
        mock_gen.return_value = {
            "chapters_generated": [3],
            "total_generated": 1,
            "errors": [],
        }

        result = self.executor._tool_generate_chapters(num_chapters=0)

        assert result["start_chapter"] == 3
        assert result["end_chapter"] == 3  # 3 + 1 - 1

    @patch("src.novel.pipeline.NovelPipeline.generate_chapters")
    @patch("src.novel.storage.file_manager.FileManager.list_chapters")
    def test_pipeline_failure_returns_error(self, mock_list, mock_gen):
        """When pipeline raises an exception, return error dict."""
        mock_list.return_value = [1, 2, 3]
        mock_gen.side_effect = RuntimeError("LLM API timeout")

        result = self.executor._tool_generate_chapters(num_chapters=2)

        assert result["success"] is False
        assert "章节生成失败" in result["error"]
        assert "LLM API timeout" in result["error"]
        assert result["start_chapter"] == 4
        assert result["end_chapter"] == 5

    @patch("src.novel.pipeline.NovelPipeline.generate_chapters")
    @patch("src.novel.storage.file_manager.FileManager.list_chapters")
    def test_warnings_from_errors(self, mock_list, mock_gen):
        """Errors from pipeline should appear as warnings in summary."""
        mock_list.return_value = []
        mock_gen.return_value = {
            "chapters_generated": [1],
            "total_generated": 1,
            "errors": [
                {"message": "Style check skipped"},
                "raw string error",
            ],
        }

        result = self.executor._tool_generate_chapters(num_chapters=1)

        assert result["success"] is True
        assert len(result["warnings"]) == 2
        assert result["warnings"][0] == "Style check skipped"
        assert result["warnings"][1] == "raw string error"

    @patch("src.novel.pipeline.NovelPipeline.generate_chapters")
    @patch("src.novel.storage.file_manager.FileManager.list_chapters")
    def test_debt_statistics_included(self, mock_list, mock_gen):
        """Debt statistics from pipeline result should be included."""
        mock_list.return_value = [1]
        mock_gen.return_value = {
            "chapters_generated": [2],
            "total_generated": 1,
            "errors": [],
            "debt_statistics": {"pending_count": 3, "fulfilled_count": 1},
        }

        result = self.executor._tool_generate_chapters(num_chapters=1)

        assert result["success"] is True
        assert result["debt_statistics"]["pending_count"] == 3

    @patch("src.novel.pipeline.NovelPipeline.generate_chapters")
    @patch("src.novel.storage.file_manager.FileManager.list_chapters")
    def test_silent_mode_always_true(self, mock_list, mock_gen):
        """Pipeline should always be called with silent=True."""
        mock_list.return_value = []
        mock_gen.return_value = {
            "chapters_generated": [1],
            "total_generated": 1,
            "errors": [],
        }

        self.executor._tool_generate_chapters(num_chapters=1)

        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["silent"] is True

    @patch("src.novel.pipeline.NovelPipeline.generate_chapters")
    @patch("src.novel.storage.file_manager.FileManager.list_chapters")
    def test_project_path_constructed_correctly(self, mock_list, mock_gen):
        """project_path should be workspace/novels/novel_id."""
        mock_list.return_value = []
        mock_gen.return_value = {
            "chapters_generated": [],
            "total_generated": 0,
            "errors": [],
        }

        self.executor._tool_generate_chapters(num_chapters=1)

        call_kwargs = mock_gen.call_args[1]
        expected = str(Path("/tmp/test_ws") / "novels" / "novel_abc")
        assert call_kwargs["project_path"] == expected


class TestGenerateChaptersViaExecute:
    """Test calling generate_chapters through the execute() dispatcher."""

    def setup_method(self):
        self.executor = AgentToolExecutor(workspace="/tmp/test_ws", novel_id="novel_xyz")

    @patch("src.novel.pipeline.NovelPipeline.generate_chapters")
    @patch("src.novel.storage.file_manager.FileManager.list_chapters")
    def test_execute_method_routes_correctly(self, mock_list, mock_gen):
        mock_list.return_value = [1, 2]
        mock_gen.return_value = {
            "chapters_generated": [3, 4],
            "total_generated": 2,
            "errors": [],
        }

        result = self.executor.execute("generate_chapters", {"num_chapters": 2})

        assert result["success"] is True
        assert result["total_generated"] == 2

    def test_execute_with_empty_args_uses_defaults(self):
        """Calling with empty args should use defaults (num_chapters=1, auto start)."""
        with patch("src.novel.pipeline.NovelPipeline.generate_chapters") as mock_gen, \
             patch("src.novel.storage.file_manager.FileManager.list_chapters") as mock_list:
            mock_list.return_value = []
            mock_gen.return_value = {
                "chapters_generated": [1],
                "total_generated": 1,
                "errors": [],
            }

            result = self.executor.execute("generate_chapters", {})

            assert result["success"] is True
            assert result["start_chapter"] == 1
            assert result["end_chapter"] == 1
