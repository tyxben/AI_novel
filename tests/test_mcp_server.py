"""Tests for MCP server tools."""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_mcp_state():
    """Reset mcp_server globals between tests to avoid cross-test leaks."""
    import mcp_server
    original_ws = mcp_server._DEFAULT_WORKSPACE
    mcp_server._pipeline_instance = None
    yield
    mcp_server._DEFAULT_WORKSPACE = original_ws
    mcp_server._pipeline_instance = None


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temp workspace with a fake novel project."""
    novels_dir = tmp_path / "novels" / "novel_test123"
    novels_dir.mkdir(parents=True)

    novel_json = {
        "novel_id": "novel_test123",
        "title": "测试小说",
        "genre": "玄幻",
        "theme": "测试主题",
        "target_words": 50000,
        "status": "generating",
        "current_chapter": 2,
        "outline": {
            "chapters": [
                {"chapter_number": 1, "title": "第一章 起源"},
                {"chapter_number": 2, "title": "第二章 觉醒"},
                {"chapter_number": 3, "title": "第三章 试炼"},
            ],
        },
        "author_name": "测试作者",
        "target_audience": "男频",
        "protagonist_names": ["张三"],
        "synopsis": "一个测试故事",
        "tags": ["玄幻", "测试"],
    }
    (novels_dir / "novel.json").write_text(
        json.dumps(novel_json, ensure_ascii=False), encoding="utf-8"
    )

    # Checkpoint
    checkpoint = {
        "outline": novel_json["outline"],
        "characters": [{"name": "张三"}],
        "world_setting": {"era": "古代"},
        "current_chapter": 2,
        "total_chapters": 3,
        "errors": [],
        "decisions": [],
        "retry_counts": {},
    }
    (novels_dir / "checkpoint.json").write_text(
        json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8"
    )

    # Chapters
    chapters_dir = novels_dir / "chapters"
    chapters_dir.mkdir()
    for ch_num in [1, 2]:
        ch_dir = chapters_dir / f"chapter_{ch_num:03d}"
        ch_dir.mkdir()
        (ch_dir / "chapter.json").write_text(
            json.dumps({
                "chapter_number": ch_num,
                "title": f"第{ch_num}章",
                "full_text": f"这是第{ch_num}章的内容。" * 100,
                "word_count": 800,
                "status": "draft",
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        (ch_dir / "text.txt").write_text(
            f"这是第{ch_num}章的内容。" * 100, encoding="utf-8"
        )

    return tmp_path


@pytest.fixture
def tmp_video_workspace(tmp_path):
    """Create a temp workspace with a fake video project."""
    video_dir = tmp_path / "test_video"
    video_dir.mkdir()

    checkpoint = {
        "stages": {
            "segment": {"done": True},
            "prompt": {"done": True},
            "image": {"done": False},
            "tts": {"done": False},
            "video": {"done": False},
        },
        "segments": [
            {"text": "段落1"},
            {"text": "段落2"},
            {"text": "段落3"},
        ],
    }
    (video_dir / "checkpoint.json").write_text(
        json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8"
    )

    return tmp_path


# ---------------------------------------------------------------------------
# novel_list_projects
# ---------------------------------------------------------------------------

class TestNovelListProjects:
    def test_list_projects(self, tmp_workspace):
        import mcp_server
        mcp_server._DEFAULT_WORKSPACE = str(tmp_workspace)
        result = mcp_server.novel_list_projects()
        assert len(result) == 1
        assert result[0]["novel_id"] == "novel_test123"
        assert result[0]["title"] == "测试小说"
        assert result[0]["status"] == "generating"
        assert result[0]["total_chapters"] == 3

    def test_empty_workspace(self, tmp_path):
        import mcp_server
        mcp_server._DEFAULT_WORKSPACE = str(tmp_path)
        result = mcp_server.novel_list_projects()
        assert result == []

    def test_no_workspace_dir(self, tmp_path):
        import mcp_server
        mcp_server._DEFAULT_WORKSPACE = str(tmp_path / "nonexistent")
        result = mcp_server.novel_list_projects()
        assert result == []


# ---------------------------------------------------------------------------
# novel_get_status
# ---------------------------------------------------------------------------

class TestNovelGetStatus:
    def test_get_status(self, tmp_workspace):
        import mcp_server
        mcp_server._DEFAULT_WORKSPACE = str(tmp_workspace)
        mcp_server._pipeline_instance = None
        pipe_mock = MagicMock()
        pipe_mock.get_status.return_value = {
            "novel_id": "novel_test123",
            "title": "测试小说",
            "status": "generating",
            "current_chapter": 2,
            "total_chapters": 3,
        }
        project_path = str(tmp_workspace / "novels" / "novel_test123")
        with patch.object(mcp_server, "_get_pipeline", return_value=pipe_mock):
            result = mcp_server.novel_get_status(project_path)
        assert result["title"] == "测试小说"
        assert result["current_chapter"] == 2
        pipe_mock.get_status.assert_called_once()

    def test_get_status_error(self):
        import mcp_server
        pipe_mock = MagicMock()
        pipe_mock.get_status.side_effect = FileNotFoundError("not found")
        with patch.object(mcp_server, "_get_pipeline", return_value=pipe_mock):
            result = mcp_server.novel_get_status("workspace/novels/nonexistent")
        assert "error" in result


# ---------------------------------------------------------------------------
# novel_read_chapter
# ---------------------------------------------------------------------------

class TestNovelReadChapter:
    def test_read_existing_chapter(self):
        import mcp_server
        fm_mock = MagicMock()
        fm_mock.load_chapter_text.return_value = "这是第一章的内容"
        fm_mock.load_chapter.return_value = {
            "title": "起源",
            "word_count": 500,
            "status": "draft",
        }
        pipe_mock = MagicMock()
        pipe_mock._get_file_manager.return_value = fm_mock

        with patch.object(mcp_server, "_get_pipeline", return_value=pipe_mock):
            result = mcp_server.novel_read_chapter("workspace/novels/novel_test123", 1)

        assert result["chapter_number"] == 1
        assert result["title"] == "起源"
        assert result["text"] == "这是第一章的内容"
        assert result["word_count"] == 8

    def test_read_nonexistent_chapter(self):
        import mcp_server
        fm_mock = MagicMock()
        fm_mock.load_chapter_text.return_value = None
        fm_mock.load_chapter.return_value = None
        pipe_mock = MagicMock()
        pipe_mock._get_file_manager.return_value = fm_mock

        with patch.object(mcp_server, "_get_pipeline", return_value=pipe_mock):
            result = mcp_server.novel_read_chapter("workspace/novels/novel_test123", 99)

        assert "error" in result


# ---------------------------------------------------------------------------
# novel_create
# ---------------------------------------------------------------------------

class TestNovelCreate:
    def test_create_success(self):
        import mcp_server
        pipe_mock = MagicMock()
        pipe_mock.create_novel.return_value = {
            "novel_id": "novel_new",
            "outline": {"chapters": []},
        }
        with patch.object(mcp_server, "_get_pipeline", return_value=pipe_mock):
            result = mcp_server.novel_create(genre="玄幻", theme="测试")

        assert result["novel_id"] == "novel_new"
        pipe_mock.create_novel.assert_called_once_with(
            genre="玄幻",
            theme="测试",
            target_words=100000,
            style="",
            template="",
            custom_ideas="",
            author_name="",
            target_audience="",
        )

    def test_create_error(self):
        import mcp_server
        pipe_mock = MagicMock()
        pipe_mock.create_novel.side_effect = RuntimeError("LLM failed")
        with patch.object(mcp_server, "_get_pipeline", return_value=pipe_mock):
            result = mcp_server.novel_create(genre="玄幻", theme="测试")
        assert "error" in result
        assert "LLM failed" in result["error"]


# ---------------------------------------------------------------------------
# novel_generate_chapters
# ---------------------------------------------------------------------------

class TestNovelGenerateChapters:
    def test_generate_batch(self):
        import mcp_server
        fm_mock = MagicMock()
        fm_mock.list_chapters.return_value = [1, 2]
        fm_mock.load_novel.return_value = {
            "outline": {"chapters": [{"chapter_number": i} for i in range(1, 11)]},
        }
        pipe_mock = MagicMock()
        pipe_mock._get_file_manager.return_value = fm_mock
        pipe_mock.generate_chapters.return_value = {
            "chapters_generated": [3, 4, 5],
        }

        with patch.object(mcp_server, "_get_pipeline", return_value=pipe_mock):
            result = mcp_server.novel_generate_chapters(
                "workspace/novels/novel_test123", batch_size=3
            )

        assert result["chapters_generated"] == [3, 4, 5]
        pipe_mock.generate_chapters.assert_called_once_with(
            project_path=ANY,
            start_chapter=3,
            end_chapter=5,
            silent=True,
        )

    def test_all_chapters_done(self):
        import mcp_server
        fm_mock = MagicMock()
        fm_mock.list_chapters.return_value = [1, 2, 3]
        fm_mock.load_novel.return_value = {
            "outline": {"chapters": [{"chapter_number": i} for i in range(1, 4)]},
        }
        pipe_mock = MagicMock()
        pipe_mock._get_file_manager.return_value = fm_mock

        with patch.object(mcp_server, "_get_pipeline", return_value=pipe_mock):
            result = mcp_server.novel_generate_chapters(
                "workspace/novels/novel_test123", batch_size=5
            )

        assert result["message"] == "所有章节已生成完成"
        pipe_mock.generate_chapters.assert_not_called()

    def test_project_not_found(self):
        import mcp_server
        fm_mock = MagicMock()
        fm_mock.list_chapters.return_value = []
        fm_mock.load_novel.return_value = None
        pipe_mock = MagicMock()
        pipe_mock._get_file_manager.return_value = fm_mock

        with patch.object(mcp_server, "_get_pipeline", return_value=pipe_mock):
            result = mcp_server.novel_generate_chapters("workspace/novels/no_exist")

        assert "error" in result


# ---------------------------------------------------------------------------
# novel_apply_feedback
# ---------------------------------------------------------------------------

class TestNovelApplyFeedback:
    def test_dry_run(self):
        import mcp_server
        pipe_mock = MagicMock()
        pipe_mock.apply_feedback.return_value = {
            "analysis": {"severity": "medium"},
            "rewritten_chapters": [],
            "dry_run": True,
        }
        with patch.object(mcp_server, "_get_pipeline", return_value=pipe_mock):
            result = mcp_server.novel_apply_feedback(
                project_path="workspace/novels/novel_test123",
                feedback_text="主角性格不一致",
                chapter_number=5,
                dry_run=True,
            )
        assert result["dry_run"] is True
        pipe_mock.apply_feedback.assert_called_once_with(
            project_path=ANY,
            feedback_text="主角性格不一致",
            chapter_number=5,
            dry_run=True,
        )


# ---------------------------------------------------------------------------
# novel_export
# ---------------------------------------------------------------------------

class TestNovelExport:
    def test_export_success(self):
        import mcp_server
        pipe_mock = MagicMock()
        pipe_mock.export_novel.return_value = "/tmp/novel.txt"
        with patch.object(mcp_server, "_get_pipeline", return_value=pipe_mock):
            result = mcp_server.novel_export("workspace/novels/novel_test123")
        assert result["output_path"] == "/tmp/novel.txt"

    def test_export_error(self):
        import mcp_server
        pipe_mock = MagicMock()
        pipe_mock.export_novel.side_effect = FileNotFoundError("no chapters")
        with patch.object(mcp_server, "_get_pipeline", return_value=pipe_mock):
            result = mcp_server.novel_export("workspace/novels/nonexistent")
        assert "error" in result


# ---------------------------------------------------------------------------
# video_list_projects
# ---------------------------------------------------------------------------

class TestVideoListProjects:
    def test_list_video_projects(self, tmp_video_workspace):
        import mcp_server
        mcp_server._DEFAULT_WORKSPACE = str(tmp_video_workspace)
        result = mcp_server.video_list_projects()
        assert len(result) == 1
        assert result[0]["project"] == "test_video"
        assert result[0]["segment_count"] == 3
        assert result[0]["completed"] is False
        assert "segment" in result[0]["done_stages"]
        assert "prompt" in result[0]["done_stages"]

    def test_excludes_novels_dir(self, tmp_workspace):
        import mcp_server
        mcp_server._DEFAULT_WORKSPACE = str(tmp_workspace)
        result = mcp_server.video_list_projects()
        # novels/ should be excluded
        names = [p.get("project") for p in result]
        assert "novels" not in names


# ---------------------------------------------------------------------------
# video_status
# ---------------------------------------------------------------------------

class TestVideoStatus:
    def test_status(self, tmp_video_workspace):
        import mcp_server
        result = mcp_server.video_status(str(tmp_video_workspace / "test_video"))
        assert result["segment_count"] == 3
        assert result["stages"]["segment"] is True
        assert result["stages"]["image"] is False

    def test_status_nonexistent(self):
        import mcp_server
        result = mcp_server.video_status("/nonexistent/path")
        assert "error" in result


# ---------------------------------------------------------------------------
# video_segment
# ---------------------------------------------------------------------------

class TestVideoSegment:
    def test_file_not_found(self):
        import mcp_server
        result = mcp_server.video_segment("/nonexistent/file.txt")
        assert "error" in result

    def test_segment_success(self, tmp_path):
        import mcp_server
        input_file = tmp_path / "story.txt"
        input_file.write_text("第一段。\n\n第二段。\n\n第三段。", encoding="utf-8")

        mock_segmenter = MagicMock()
        mock_segmenter.segment.return_value = [
            {"text": "第一段。"},
            {"text": "第二段。"},
            {"text": "第三段。"},
        ]

        with patch("mcp_server.Path.exists", return_value=True), \
             patch("src.segmenter.text_segmenter.create_segmenter", return_value=mock_segmenter), \
             patch("src.config_manager.load_config", return_value={
                 "segmenter": {"method": "simple"},
                 "llm": {},
             }):
            result = mcp_server.video_segment(str(input_file), method="simple")

        assert result["count"] == 3


# ---------------------------------------------------------------------------
# video_generate
# ---------------------------------------------------------------------------

class TestVideoGenerate:
    def test_file_not_found(self):
        import mcp_server
        result = mcp_server.video_generate("/nonexistent/file.txt")
        assert "error" in result
        assert "不存在" in result["error"]

    def test_generate_classic(self, tmp_path):
        import mcp_server
        input_file = tmp_path / "novel.txt"
        input_file.write_text("一段小说文本", encoding="utf-8")

        pipe_mock = MagicMock()
        pipe_mock.run.return_value = Path("/tmp/output.mp4")

        with patch("src.pipeline.Pipeline", return_value=pipe_mock):
            result = mcp_server.video_generate(str(input_file), mode="classic")

        assert result["status"] == "success"
        assert result["output_path"] == "/tmp/output.mp4"


# ---------------------------------------------------------------------------
# MCP server meta
# ---------------------------------------------------------------------------

class TestMCPServerMeta:
    def test_all_tools_registered(self):
        """Verify all expected tools are registered."""
        import asyncio
        import mcp_server

        async def _list():
            return await mcp_server.mcp.list_tools()

        tools = asyncio.run(_list())
        tool_names = {t.name for t in tools}

        # Novel tools
        assert "novel_list_projects" in tool_names
        assert "novel_create" in tool_names
        assert "novel_generate_chapters" in tool_names
        assert "novel_get_status" in tool_names
        assert "novel_read_chapter" in tool_names
        assert "novel_apply_feedback" in tool_names
        assert "novel_export" in tool_names

        # Video tools
        assert "video_generate" in tool_names
        assert "video_segment" in tool_names
        assert "video_status" in tool_names
        assert "video_list_projects" in tool_names

    def test_total_tool_count(self):
        """Should have 19 tools total (10 novel + 4 video + 5 ppt)."""
        import asyncio
        import mcp_server

        async def _list():
            return await mcp_server.mcp.list_tools()

        tools = asyncio.run(_list())
        assert len(tools) == 19
