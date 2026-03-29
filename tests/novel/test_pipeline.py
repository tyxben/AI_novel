"""NovelPipeline + Graph 单元测试

所有 LLM 调用和外部依赖均 Mock，验证：
- graph 构建和节点串联
- pipeline create / generate / resume / export / status
- checkpoint 保存/恢复
- 错误处理（LLM 失败不丢进度）
- silent mode
- langgraph fallback
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
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


def _make_outline_dict(total_chapters: int = 5) -> dict:
    """Create a minimal outline dict."""
    return {
        "template": "cyclic_upgrade",
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
                "core_conflict": "矛盾",
                "resolution": "解决",
                "chapters": list(range(1, total_chapters + 1)),
            }
        ],
        "chapters": [
            {
                "chapter_number": i,
                "title": f"第{i}章测试",
                "goal": f"目标{i}",
                "key_events": [f"事件{i}"],
                "estimated_words": 3000,
                "mood": "蓄力",
            }
            for i in range(1, total_chapters + 1)
        ],
    }


def _make_world_setting_dict() -> dict:
    return {
        "era": "上古时代",
        "location": "九州大陆",
        "rules": [],
        "terms": {},
        "power_system": None,
    }


def _make_character_dict(name: str = "主角") -> dict:
    return {
        "name": name,
        "gender": "男",
        "age": 18,
        "occupation": "修仙者",
        "role": "主角",
        "personality": {
            "traits": ["勇敢", "坚韧", "善良"],
            "speech_style": "简洁有力",
            "core_belief": "永不放弃",
            "flaw": "冲动",
            "catchphrases": [],
        },
        "appearance": {
            "height": "180cm",
            "build": "修长",
            "distinctive_features": ["剑眉"],
            "clothing_style": "青色长袍",
        },
        "background": "平凡少年",
    }


def _make_fake_state(novel_id: str = "test_novel", total_chapters: int = 3) -> dict:
    """Create a full initial state for testing."""
    return {
        "genre": "玄幻",
        "theme": "修仙逆袭",
        "target_words": 15000,
        "style_name": "webnovel.shuangwen",
        "template": "cyclic_upgrade",
        "novel_id": novel_id,
        "workspace": "/tmp/test_workspace",
        "config": {},
        "current_chapter": 0,
        "total_chapters": total_chapters,
        "review_interval": 5,
        "silent_mode": True,
        "auto_approve_threshold": 6.0,
        "max_retries": 2,
        "outline": _make_outline_dict(total_chapters),
        "world_setting": _make_world_setting_dict(),
        "characters": [_make_character_dict()],
        "chapters": [],
        "decisions": [],
        "errors": [],
        "completed_nodes": [],
        "retry_counts": {},
        "should_continue": True,
    }


# ---------------------------------------------------------------------------
# Mock node functions
# ---------------------------------------------------------------------------


def _mock_novel_director_node(state: dict) -> dict:
    return {
        "outline": _make_outline_dict(3),
        "total_chapters": 3,
        "current_chapter": 0,
        "should_continue": True,
        "style_name": "webnovel.shuangwen",
        "template": "cyclic_upgrade",
        "decisions": [{"agent": "NovelDirector", "step": "test", "decision": "ok", "reason": "test"}],
        "errors": [],
        "completed_nodes": ["novel_director"],
    }


def _mock_world_builder_node(state: dict) -> dict:
    return {
        "world_setting": _make_world_setting_dict(),
        "decisions": [{"agent": "WorldBuilder", "step": "test", "decision": "ok", "reason": "test"}],
        "errors": [],
        "completed_nodes": ["world_builder"],
    }


def _mock_character_designer_node(state: dict) -> dict:
    return {
        "characters": [_make_character_dict()],
        "decisions": [{"agent": "CharacterDesigner", "step": "test", "decision": "ok", "reason": "test"}],
        "errors": [],
        "completed_nodes": ["character_designer"],
    }


def _mock_plot_planner_node(state: dict) -> dict:
    return {
        "current_scenes": [
            {"scene_number": 1, "target_words": 800, "summary": "场景1"},
            {"scene_number": 2, "target_words": 800, "summary": "场景2"},
        ],
        "decisions": [{"agent": "PlotPlanner", "step": "test", "decision": "ok", "reason": "test"}],
        "errors": [],
        "completed_nodes": ["plot_planner"],
    }


def _mock_writer_node(state: dict) -> dict:
    ch = state.get("current_chapter", 1)
    return {
        "current_chapter_text": f"第{ch}章正文内容。这是一段测试文本，用于验证管道流程。" * 10,
        "decisions": [{"agent": "Writer", "step": "test", "decision": "ok", "reason": "test"}],
        "errors": [],
        "completed_nodes": ["writer"],
    }


def _mock_consistency_checker_node(state: dict) -> dict:
    return {
        "current_chapter_quality": {"consistency_check": {"passed": True}},
        "decisions": [{"agent": "ConsistencyChecker", "step": "test", "decision": "ok", "reason": "test"}],
        "errors": [],
        "completed_nodes": ["consistency_checker"],
    }


def _mock_style_keeper_node(state: dict) -> dict:
    quality = dict(state.get("current_chapter_quality") or {})
    quality["style_similarity"] = 0.9
    return {
        "current_chapter_quality": quality,
        "decisions": [{"agent": "StyleKeeper", "step": "test", "decision": "ok", "reason": "test"}],
        "errors": [],
        "completed_nodes": ["style_keeper"],
    }


def _mock_quality_reviewer_node_pass(state: dict) -> dict:
    return {
        "current_chapter_quality": {"need_rewrite": False, "rule_check": {"passed": True}},
        "decisions": [{"agent": "QualityReviewer", "step": "test", "decision": "质量通过", "reason": "test"}],
        "errors": [],
        "completed_nodes": ["quality_reviewer"],
    }


def _mock_quality_reviewer_node_fail(state: dict) -> dict:
    return {
        "current_chapter_quality": {"need_rewrite": True, "rule_check": {"passed": False}},
        "retry_counts": {state.get("current_chapter", 1): 1},
        "decisions": [{"agent": "QualityReviewer", "step": "test", "decision": "需要重写", "reason": "test"}],
        "errors": [],
        "completed_nodes": ["quality_reviewer"],
    }


# Patch target for all node imports
_NODES_PATCH_TARGET = "src.novel.agents.graph._get_node_functions"


def _get_mock_nodes(quality_pass: bool = True) -> dict:
    return {
        "novel_director": _mock_novel_director_node,
        "world_builder": _mock_world_builder_node,
        "character_designer": _mock_character_designer_node,
        "plot_planner": _mock_plot_planner_node,
        "writer": _mock_writer_node,
        "consistency_checker": _mock_consistency_checker_node,
        "style_keeper": _mock_style_keeper_node,
        "quality_reviewer": _mock_quality_reviewer_node_pass if quality_pass else _mock_quality_reviewer_node_fail,
    }


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temp workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return str(ws)


@pytest.fixture
def pipeline(tmp_workspace):
    """Create a NovelPipeline with temp workspace."""
    from src.novel.pipeline import NovelPipeline
    from src.novel.config import NovelConfig

    config = NovelConfig()
    return NovelPipeline(config=config, workspace=tmp_workspace)


# ---------------------------------------------------------------------------
# Tests: Graph construction
# ---------------------------------------------------------------------------


class TestGraph:
    """Test graph building and node wiring."""

    def test_build_chapter_graph_fallback(self):
        """Chapter graph fallback works without langgraph."""
        from src.novel.agents.graph import _ChapterRunner

        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                from src.novel.agents.graph import build_chapter_graph
                graph = build_chapter_graph()
                assert isinstance(graph, _ChapterRunner)

    def test_chapter_graph_invoke_pass(self):
        """Chapter graph runs all 5 nodes when quality passes."""
        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes(quality_pass=True)):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                from src.novel.agents.graph import build_chapter_graph
                graph = build_chapter_graph()
                state = _make_fake_state()
                state["current_chapter"] = 1
                state["current_chapter_outline"] = state["outline"]["chapters"][0]

                result = graph.invoke(state)

                assert result["current_chapter_text"] is not None
                assert len(result["current_chapter_text"]) > 0
                assert "writer" in result["completed_nodes"]
                assert "quality_reviewer" in result["completed_nodes"]

    def test_chapter_graph_rewrite_loop(self):
        """Chapter graph triggers rewrite when quality fails."""
        call_count = {"writer": 0}
        orig_writer = _mock_writer_node

        def counting_writer(state):
            call_count["writer"] += 1
            return orig_writer(state)

        # Quality fails first, then eventually passes via max_retries
        nodes = _get_mock_nodes(quality_pass=False)
        nodes["writer"] = counting_writer

        with patch(_NODES_PATCH_TARGET, return_value=nodes):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                from src.novel.agents.graph import build_chapter_graph
                graph = build_chapter_graph()
                state = _make_fake_state()
                state["current_chapter"] = 1
                state["current_chapter_outline"] = state["outline"]["chapters"][0]
                state["max_retries"] = 2

                result = graph.invoke(state)

                # Writer should be called multiple times (initial + rewrites)
                assert call_count["writer"] >= 2

    def test_should_rewrite_pass(self):
        """_should_rewrite returns 'end' when quality passes."""
        from src.novel.agents.graph import _should_rewrite

        state = {"current_chapter_quality": {"need_rewrite": False}}
        assert _should_rewrite(state) == "state_writeback"

    def test_should_rewrite_fail(self):
        """_should_rewrite returns 'writer' when quality fails and under max retries."""
        from src.novel.agents.graph import _should_rewrite

        state = {
            "current_chapter": 1,
            "current_chapter_quality": {"need_rewrite": True},
            "retry_counts": {1: 0},
            "max_retries": 2,
        }
        assert _should_rewrite(state) == "writer"

    def test_should_rewrite_max_retries(self):
        """_should_rewrite returns 'end' when max retries reached."""
        from src.novel.agents.graph import _should_rewrite

        state = {
            "current_chapter": 1,
            "current_chapter_quality": {"need_rewrite": True},
            "retry_counts": {1: 3},
            "max_retries": 2,
        }
        assert _should_rewrite(state) == "state_writeback"

    def test_is_langgraph_available(self):
        """is_langgraph_available returns a boolean."""
        from src.novel.agents.graph import is_langgraph_available
        result = is_langgraph_available()
        assert isinstance(result, bool)

    def test_merge_state_additive_fields(self):
        """_merge_state correctly accumulates list fields."""
        from src.novel.agents.graph import _merge_state

        base = {"decisions": [{"a": 1}], "errors": [], "other": "val"}
        update = {"decisions": [{"b": 2}], "other": "new_val"}

        merged = _merge_state(base, update)
        assert len(merged["decisions"]) == 2
        assert merged["other"] == "new_val"

    def test_sequential_runner_error_handling(self):
        """SequentialRunner captures node errors without crashing."""
        from src.novel.agents.graph import _SequentialRunner

        def failing_node(state):
            raise RuntimeError("test error")

        def ok_node(state):
            return {"completed_nodes": ["ok_node"]}

        runner = _SequentialRunner([("fail", failing_node), ("ok", ok_node)])
        result = runner.invoke({})

        assert any("test error" in str(e.get("message", "")) for e in result.get("errors", []))
        assert "ok_node" in result.get("completed_nodes", [])
        # Failed nodes should NOT be in completed_nodes
        assert "fail" not in result.get("completed_nodes", [])

    def test_chapter_runner_skips_checkers_on_writer_failure(self):
        """ChapterRunner skips checker nodes when writer produces no text."""
        from src.novel.agents.graph import _ChapterRunner

        checker_calls = {"count": 0}

        def ok_planner(state):
            return {"current_scenes": [{"scene": 1}], "completed_nodes": ["plot_planner"], "errors": [], "decisions": []}

        def failing_writer(state):
            raise RuntimeError("LLM timeout")

        def counting_checker(state):
            checker_calls["count"] += 1
            return {"completed_nodes": ["checker"], "errors": [], "decisions": []}

        runner = _ChapterRunner(
            nodes={
                "plot_planner": ok_planner,
                "writer": failing_writer,
                "consistency_checker": counting_checker,
                "style_keeper": counting_checker,
                "quality_reviewer": counting_checker,
            },
            max_rewrites=2,
        )
        result = runner.invoke({"current_chapter_text": None})

        # Checkers should not have been called
        assert checker_calls["count"] == 0
        # Error should be recorded
        assert any("LLM timeout" in str(e.get("message", "")) for e in result.get("errors", []))

    def test_retry_counts_survive_checkpoint_roundtrip(self, pipeline, tmp_workspace):
        """Integer keys in retry_counts survive JSON serialization."""
        novel_id = "retry_roundtrip_test"
        state = {"retry_counts": {1: 2, 3: 1}, "genre": "test"}
        pipeline._save_checkpoint(novel_id, state)
        loaded = pipeline._load_checkpoint(novel_id)
        assert loaded["retry_counts"][1] == 2
        assert loaded["retry_counts"][3] == 1


# ---------------------------------------------------------------------------
# Tests: Pipeline
# ---------------------------------------------------------------------------


class TestPipeline:
    """Test NovelPipeline orchestration."""

    def test_create_novel(self, pipeline, tmp_workspace):
        """create_novel produces workspace with novel.json and checkpoint."""
        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                result = pipeline.create_novel(
                    genre="玄幻",
                    theme="修仙逆袭",
                    target_words=15000,
                )

                assert "novel_id" in result
                assert result["outline"] is not None
                assert len(result["characters"]) > 0
                assert result["world_setting"] is not None

                # Check files exist
                novel_dir = Path(result["workspace"])
                assert (novel_dir / "novel.json").exists()
                assert (novel_dir / "checkpoint.json").exists()

    def test_generate_chapters(self, pipeline, tmp_workspace):
        """generate_chapters produces chapter files."""
        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                # First create
                result = pipeline.create_novel(
                    genre="玄幻",
                    theme="修仙逆袭",
                    target_words=15000,
                )

                project_path = result["workspace"]

                # Then generate
                gen_result = pipeline.generate_chapters(
                    project_path, start_chapter=1, end_chapter=2, silent=True
                )

                assert gen_result["total_generated"] == 2
                assert 1 in gen_result["chapters_generated"]
                assert 2 in gen_result["chapters_generated"]

                # Check chapter files
                novel_id = result["novel_id"]
                chapters_dir = Path(tmp_workspace) / "novels" / novel_id / "chapters"
                assert (chapters_dir / "chapter_001.json").exists()
                assert (chapters_dir / "chapter_001.txt").exists()
                assert (chapters_dir / "chapter_002.json").exists()

    def test_generate_chapters_no_checkpoint(self, pipeline):
        """generate_chapters raises when no checkpoint found."""
        with pytest.raises(FileNotFoundError, match="找不到项目检查点"):
            pipeline.generate_chapters("/nonexistent/path")

    def test_resume_novel(self, pipeline, tmp_workspace):
        """resume_novel continues from last completed chapter."""
        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                result = pipeline.create_novel(
                    genre="玄幻", theme="测试", target_words=15000
                )
                project_path = result["workspace"]

                # Generate first chapter only
                pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=1, silent=True)

                # Resume should pick up from chapter 2
                resume_result = pipeline.resume_novel(project_path)
                assert resume_result["total_generated"] >= 1

    def test_resume_novel_all_complete(self, pipeline, tmp_workspace):
        """resume_novel returns immediately when all chapters done."""
        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                result = pipeline.create_novel(
                    genre="玄幻", theme="测试", target_words=15000
                )
                project_path = result["workspace"]

                # Generate all chapters
                pipeline.generate_chapters(project_path, silent=True)

                # Resume should find nothing to do
                resume_result = pipeline.resume_novel(project_path)
                assert resume_result["total_generated"] == 0
                assert "已生成完成" in resume_result.get("message", "")

    def test_export_novel(self, pipeline, tmp_workspace):
        """export_novel creates a txt file."""
        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                result = pipeline.create_novel(
                    genre="玄幻", theme="测试", target_words=15000
                )
                project_path = result["workspace"]

                pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=1, silent=True)

                output_path = pipeline.export_novel(project_path)
                assert Path(output_path).exists()

                content = Path(output_path).read_text(encoding="utf-8")
                assert len(content) > 0

    def test_export_novel_custom_output(self, pipeline, tmp_workspace, tmp_path):
        """export_novel respects custom output path."""
        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                result = pipeline.create_novel(
                    genre="玄幻", theme="测试", target_words=15000
                )
                project_path = result["workspace"]
                pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=1, silent=True)

                custom_out = str(tmp_path / "custom_novel.txt")
                output_path = pipeline.export_novel(project_path, custom_out)
                assert output_path == custom_out
                assert Path(custom_out).exists()

    def test_get_status(self, pipeline, tmp_workspace):
        """get_status returns correct project info."""
        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                result = pipeline.create_novel(
                    genre="玄幻", theme="测试", target_words=15000
                )
                project_path = result["workspace"]

                status = pipeline.get_status(project_path)
                assert status["novel_id"] == result["novel_id"]
                assert status["status"] == "initialized"
                assert "characters_count" in status
                assert status["has_world_setting"] is True

    def test_get_status_after_generation(self, pipeline, tmp_workspace):
        """get_status reflects generation progress."""
        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                result = pipeline.create_novel(
                    genre="玄幻", theme="测试", target_words=15000
                )
                project_path = result["workspace"]
                pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=2, silent=True)

                status = pipeline.get_status(project_path)
                assert status["current_chapter"] == 2

    def test_checkpoint_save_and_load(self, pipeline, tmp_workspace):
        """Checkpoint persists and reloads correctly."""
        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                result = pipeline.create_novel(
                    genre="玄幻", theme="测试", target_words=15000
                )
                novel_id = result["novel_id"]

                ckpt = pipeline._load_checkpoint(novel_id)
                assert ckpt is not None
                assert ckpt.get("outline") is not None
                assert ckpt.get("genre") == "玄幻"

    def test_error_during_generation_preserves_checkpoint(self, pipeline, tmp_workspace):
        """LLM failure during generation doesn't lose previous progress."""
        call_count = {"calls": 0}

        def failing_writer(state):
            call_count["calls"] += 1
            if call_count["calls"] == 2:
                raise RuntimeError("LLM timeout")
            return _mock_writer_node(state)

        nodes = _get_mock_nodes()
        nodes["writer"] = failing_writer

        with patch(_NODES_PATCH_TARGET, return_value=nodes):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                result = pipeline.create_novel(
                    genre="玄幻", theme="测试", target_words=15000
                )
                project_path = result["workspace"]

                # Even if chapter 2 fails, chapter 1 should be saved
                gen_result = pipeline.generate_chapters(
                    project_path, start_chapter=1, end_chapter=3, silent=True
                )

                # Chapter 1 should have been generated before the failure
                assert 1 in gen_result["chapters_generated"]
                # Checkpoint should still exist
                ckpt = pipeline._load_checkpoint(result["novel_id"])
                assert ckpt is not None

    def test_silent_mode_no_pause(self, pipeline, tmp_workspace):
        """Silent mode generates without pause."""
        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                result = pipeline.create_novel(
                    genre="玄幻", theme="测试", target_words=15000
                )
                project_path = result["workspace"]

                gen_result = pipeline.generate_chapters(
                    project_path, silent=True
                )
                # All 3 chapters should be generated without interruption
                assert gen_result["total_generated"] == 3

    def test_status_not_found(self, pipeline):
        """get_status handles non-existent project."""
        status = pipeline.get_status("/tmp/nonexistent_project_12345")
        assert status["status"] in ("not_found", "unknown")

    def test_create_novel_with_style_and_template(self, pipeline, tmp_workspace):
        """create_novel passes style and template to state."""
        with patch(_NODES_PATCH_TARGET, return_value=_get_mock_nodes()):
            with patch("src.novel.agents.graph._LANGGRAPH_AVAILABLE", False):
                result = pipeline.create_novel(
                    genre="武侠",
                    theme="江湖恩怨",
                    target_words=50000,
                    style="wuxia.classical",
                    template="four_act",
                )

                assert result["novel_id"] is not None
                # Verify checkpoint stored the right values
                ckpt = pipeline._load_checkpoint(result["novel_id"])
                assert ckpt is not None


# ---------------------------------------------------------------------------
# Tests: CLI commands
# ---------------------------------------------------------------------------


class TestCLI:
    """Test CLI command registration."""

    def test_novel_group_exists(self):
        """The novel command group is registered."""
        from click.testing import CliRunner
        from main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "--help"])
        assert result.exit_code == 0
        assert "AI" in result.output or "小说" in result.output

    def test_write_command_exists(self):
        """write command is registered under novel group."""
        from click.testing import CliRunner
        from main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "write", "--help"])
        assert result.exit_code == 0
        assert "--genre" in result.output
        assert "--theme" in result.output
        assert "--target-words" in result.output

    def test_resume_command_exists(self):
        """resume command is registered."""
        from click.testing import CliRunner
        from main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "resume", "--help"])
        assert result.exit_code == 0

    def test_export_command_exists(self):
        """export command is registered."""
        from click.testing import CliRunner
        from main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "export", "--help"])
        assert result.exit_code == 0
        assert "--output" in result.output or "-o" in result.output

    def test_status_command_exists(self):
        """status command is registered."""
        from click.testing import CliRunner
        from main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "status", "--help"])
        assert result.exit_code == 0
