"""Tests for PPT CLI commands in main.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def input_file(tmp_path):
    """Create a temporary input text file."""
    f = tmp_path / "test_input.txt"
    f.write_text("这是一份测试文档的内容，用于生成PPT。", encoding="utf-8")
    return str(f)


@pytest.fixture
def empty_file(tmp_path):
    """Create an empty input file."""
    f = tmp_path / "empty.txt"
    f.write_text("", encoding="utf-8")
    return str(f)


@pytest.fixture
def project_dir(tmp_path):
    """Create a temporary project directory."""
    d = tmp_path / "ppt_test_project"
    d.mkdir()
    return str(d)


class TestPptGenerate:
    """Tests for 'ppt generate' command."""

    @patch("src.ppt.pipeline.PPTPipeline")
    def test_generate_basic(self, mock_cls, runner, input_file):
        """Test basic PPT generation with default options."""
        mock_instance = MagicMock()
        mock_instance.generate.return_value = "/output/result.pptx"
        mock_cls.return_value = mock_instance

        result = runner.invoke(cli, ["ppt", "generate", input_file])
        assert result.exit_code == 0
        assert "PPT 生成完成" in result.output
        mock_instance.generate.assert_called_once()
        call_kwargs = mock_instance.generate.call_args.kwargs
        assert call_kwargs["theme"] == "modern"
        assert call_kwargs["generate_images"] is True

    def test_generate_nonexistent_file(self, runner):
        """Test error when input file does not exist."""
        result = runner.invoke(cli, ["ppt", "generate", "/nonexistent/file.txt"])
        assert result.exit_code != 0

    @patch("src.ppt.pipeline.PPTPipeline")
    def test_generate_with_theme(self, mock_cls, runner, input_file):
        """Test generation with a specific theme."""
        mock_instance = MagicMock()
        mock_instance.generate.return_value = "/output/result.pptx"
        mock_cls.return_value = mock_instance

        result = runner.invoke(cli, [
            "ppt", "generate", input_file,
            "--theme", "business",
        ])
        assert result.exit_code == 0
        call_kwargs = mock_instance.generate.call_args.kwargs
        assert call_kwargs["theme"] == "business"

    def test_generate_invalid_theme(self, runner, input_file):
        """Test error with invalid theme choice."""
        result = runner.invoke(cli, [
            "ppt", "generate", input_file,
            "--theme", "nonexistent",
        ])
        assert result.exit_code != 0

    @patch("src.ppt.pipeline.PPTPipeline")
    def test_generate_with_no_images(self, mock_cls, runner, input_file):
        """Test generation with --no-images flag."""
        mock_instance = MagicMock()
        mock_instance.generate.return_value = "/output/result.pptx"
        mock_cls.return_value = mock_instance

        result = runner.invoke(cli, [
            "ppt", "generate", input_file,
            "--no-images",
        ])
        assert result.exit_code == 0
        call_kwargs = mock_instance.generate.call_args.kwargs
        assert call_kwargs["generate_images"] is False

    @patch("src.ppt.pipeline.PPTPipeline")
    def test_generate_with_max_pages(self, mock_cls, runner, input_file):
        """Test generation with --max-pages option."""
        mock_instance = MagicMock()
        mock_instance.generate.return_value = "/output/result.pptx"
        mock_cls.return_value = mock_instance

        result = runner.invoke(cli, [
            "ppt", "generate", input_file,
            "--max-pages", "10",
        ])
        assert result.exit_code == 0
        call_kwargs = mock_instance.generate.call_args.kwargs
        assert call_kwargs["max_pages"] == 10

    @patch("src.ppt.pipeline.PPTPipeline")
    def test_generate_empty_file(self, mock_cls, runner, empty_file):
        """Test generation with empty input file aborts."""
        result = runner.invoke(cli, ["ppt", "generate", empty_file])
        assert result.exit_code != 0
        assert "空" in result.output

    @patch("src.ppt.pipeline.PPTPipeline")
    def test_generate_pipeline_exception(self, mock_cls, runner, input_file):
        """Test graceful handling when pipeline raises an exception."""
        mock_instance = MagicMock()
        mock_instance.generate.side_effect = RuntimeError("LLM调用失败")
        mock_cls.return_value = mock_instance

        result = runner.invoke(cli, ["ppt", "generate", input_file])
        assert result.exit_code != 0

    @patch("src.ppt.pipeline.PPTPipeline")
    def test_generate_with_output_path(self, mock_cls, runner, input_file, tmp_path):
        """Test generation with custom output path."""
        mock_instance = MagicMock()
        output = str(tmp_path / "custom_output.pptx")
        mock_instance.generate.return_value = output
        mock_cls.return_value = mock_instance

        result = runner.invoke(cli, [
            "ppt", "generate", input_file,
            "--output", output,
        ])
        assert result.exit_code == 0
        call_kwargs = mock_instance.generate.call_args.kwargs
        assert call_kwargs["output_path"] == output


class TestPptThemes:
    """Tests for 'ppt themes' command."""

    @patch("src.ppt.theme_manager.ThemeManager")
    def test_themes_list(self, mock_tm_cls, runner):
        """Test listing available themes."""
        mock_tm = MagicMock()
        mock_tm.list_themes.return_value = ["modern", "business", "creative"]
        mock_tm_cls.return_value = mock_tm

        result = runner.invoke(cli, ["ppt", "themes"])
        assert result.exit_code == 0
        assert "modern" in result.output
        assert "business" in result.output
        assert "creative" in result.output

    @patch("src.ppt.theme_manager.ThemeManager")
    def test_themes_empty(self, mock_tm_cls, runner):
        """Test when no themes are available."""
        mock_tm = MagicMock()
        mock_tm.list_themes.return_value = []
        mock_tm_cls.return_value = mock_tm

        result = runner.invoke(cli, ["ppt", "themes"])
        assert result.exit_code == 0

    @patch("src.ppt.theme_manager.ThemeManager")
    def test_themes_exception(self, mock_tm_cls, runner):
        """Test graceful error handling when ThemeManager fails."""
        mock_tm_cls.side_effect = RuntimeError("YAML目录不存在")

        result = runner.invoke(cli, ["ppt", "themes"])
        assert result.exit_code != 0


class TestPptStatus:
    """Tests for 'ppt status' command."""

    def test_status_nonexistent_path(self, runner):
        """Test error when project path does not exist."""
        result = runner.invoke(cli, ["ppt", "status", "/nonexistent/path"])
        assert result.exit_code != 0

    @patch("src.ppt.pipeline.PPTPipeline")
    def test_status_success(self, mock_cls, runner, project_dir):
        """Test successful status display."""
        mock_instance = MagicMock()
        mock_instance.get_status.return_value = {
            "project_id": "ppt_001",
            "status": "completed",
            "pages": 12,
        }
        mock_cls.return_value = mock_instance

        result = runner.invoke(cli, ["ppt", "status", project_dir])
        assert result.exit_code == 0
        assert "ppt_001" in result.output
        assert "completed" in result.output

    @patch("src.ppt.pipeline.PPTPipeline")
    def test_status_pipeline_exception(self, mock_cls, runner, project_dir):
        """Test graceful handling when status check fails."""
        mock_instance = MagicMock()
        mock_instance.get_status.side_effect = RuntimeError("项目不存在")
        mock_cls.return_value = mock_instance

        result = runner.invoke(cli, ["ppt", "status", project_dir])
        assert result.exit_code != 0


class TestPptResume:
    """Tests for 'ppt resume' command."""

    def test_resume_nonexistent_path(self, runner):
        """Test error when project path does not exist."""
        result = runner.invoke(cli, ["ppt", "resume", "/nonexistent/path"])
        assert result.exit_code != 0

    @patch("src.ppt.pipeline.PPTPipeline")
    def test_resume_success(self, mock_cls, runner, project_dir):
        """Test successful resume."""
        mock_instance = MagicMock()
        mock_instance.resume.return_value = "/output/resumed.pptx"
        mock_cls.return_value = mock_instance

        result = runner.invoke(cli, ["ppt", "resume", project_dir])
        assert result.exit_code == 0
        assert "续传完成" in result.output

    @patch("src.ppt.pipeline.PPTPipeline")
    def test_resume_pipeline_exception(self, mock_cls, runner, project_dir):
        """Test graceful handling when resume fails."""
        mock_instance = MagicMock()
        mock_instance.resume.side_effect = RuntimeError("检查点损坏")
        mock_cls.return_value = mock_instance

        result = runner.invoke(cli, ["ppt", "resume", project_dir])
        assert result.exit_code != 0


class TestPptGroup:
    """Tests for the ppt command group itself."""

    def test_ppt_help(self, runner):
        """Test ppt --help output."""
        result = runner.invoke(cli, ["ppt", "--help"])
        assert result.exit_code == 0
        assert "PPT" in result.output

    def test_ppt_generate_help(self, runner):
        """Test ppt generate --help output."""
        result = runner.invoke(cli, ["ppt", "generate", "--help"])
        assert result.exit_code == 0
        assert "theme" in result.output.lower() or "主题" in result.output

    def test_ppt_subcommands_listed(self, runner):
        """Test that all subcommands are listed in help."""
        result = runner.invoke(cli, ["ppt", "--help"])
        assert result.exit_code == 0
        assert "generate" in result.output
        assert "resume" in result.output
        assert "status" in result.output
        assert "themes" in result.output
