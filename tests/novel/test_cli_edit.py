"""CLI tests for `novel edit` and `novel history` subcommands.

Covers:
- novel edit: success, dry-run (preview), failed (service returns status=failed)
- novel history: non-empty, empty project, filter by change-type
- boundary: nonexistent project path (Click exists=True validation)
- mocks NovelEditService to avoid real LLM / filesystem coupling
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from main import cli


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeEditResult:
    """Mirror of src.novel.services.edit_service.EditResult used for mocking."""

    change_id: str
    status: str
    change_type: str
    entity_type: str
    entity_id: str | None = None
    old_value: dict | None = None
    new_value: dict | None = None
    effective_from_chapter: int | None = None
    reasoning: str = ""
    error: str | None = None
    impact_report: dict | None = None  # optional, tolerated by CLI


def _make_project(tmp_path: Path, novel_id: str = "novel_test") -> Path:
    """Create a minimal novel project directory so Click's exists=True passes."""
    project = tmp_path / "ws" / "novels" / novel_id
    project.mkdir(parents=True, exist_ok=True)

    data = {
        "novel_id": novel_id,
        "title": "测试小说",
        "genre": "玄幻",
        "current_chapter": 4,
        "characters": [],
    }
    (project / "novel.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    return project


# ---------------------------------------------------------------------------
# novel edit
# ---------------------------------------------------------------------------


class TestNovelEdit:
    """Tests for `main.py novel edit`."""

    @patch("src.novel.services.edit_service.NovelEditService")
    def test_edit_success(self, mock_svc_cls, tmp_path):
        project = _make_project(tmp_path)

        mock_svc = MagicMock()
        mock_svc.edit.return_value = FakeEditResult(
            change_id="abc-123",
            status="success",
            change_type="add",
            entity_type="character",
            entity_id="li_ming",
            effective_from_chapter=5,
            reasoning="添加新角色 李明",
        )
        mock_svc_cls.return_value = mock_svc

        runner = CliRunner()
        result = runner.invoke(cli, [
            "novel", "edit", str(project),
            "--instruction", "添加角色李明",
            "--effective-from", "5",
        ])

        assert result.exit_code == 0, result.output
        assert "编辑成功" in result.output
        assert "abc-123" in result.output
        assert "add" in result.output
        assert "character" in result.output
        assert "li_ming" in result.output
        assert "第 5 章" in result.output

        # service called once with matching kwargs
        mock_svc.edit.assert_called_once()
        call_kwargs = mock_svc.edit.call_args.kwargs
        assert call_kwargs["project_path"] == str(project)
        assert call_kwargs["instruction"] == "添加角色李明"
        assert call_kwargs["effective_from_chapter"] == 5
        assert call_kwargs["dry_run"] is False

    @patch("src.novel.services.edit_service.NovelEditService")
    def test_edit_dry_run_preview(self, mock_svc_cls, tmp_path):
        project = _make_project(tmp_path)

        mock_svc = MagicMock()
        mock_svc.edit.return_value = FakeEditResult(
            change_id="preview-1",
            status="preview",
            change_type="update",
            entity_type="character",
            entity_id="main_character",
            effective_from_chapter=5,
            reasoning="预览：修改主角性格",
            impact_report={
                "affected_chapters": [5, 6, 7],
                "summary": "将影响后续3章主角行为",
                "severity": "low",
                "conflicts": [],
                "warnings": [],
            },
        )
        mock_svc_cls.return_value = mock_svc

        runner = CliRunner()
        result = runner.invoke(cli, [
            "novel", "edit", str(project),
            "-i", "修改主角性格为更冷酷",
            "--dry-run",
        ])

        assert result.exit_code == 0, result.output
        assert "PREVIEW" in result.output
        # Should NOT claim success in dry-run
        assert "编辑成功" not in result.output
        # Impact analysis must render
        assert "影响分析" in result.output or "affected" in result.output
        assert "5" in result.output and "6" in result.output
        assert "low" in result.output

        call_kwargs = mock_svc.edit.call_args.kwargs
        assert call_kwargs["dry_run"] is True
        assert call_kwargs["effective_from_chapter"] is None

    @patch("src.novel.services.edit_service.NovelEditService")
    def test_edit_failed(self, mock_svc_cls, tmp_path):
        project = _make_project(tmp_path)

        mock_svc = MagicMock()
        mock_svc.edit.return_value = FakeEditResult(
            change_id="fail-1",
            status="failed",
            change_type="",
            entity_type="",
            error="小说项目不存在: novel_xxx",
        )
        mock_svc_cls.return_value = mock_svc

        runner = CliRunner()
        result = runner.invoke(cli, [
            "novel", "edit", str(project),
            "-i", "乱七八糟的指令",
        ])

        assert result.exit_code != 0
        assert "编辑失败" in result.output
        assert "小说项目不存在" in result.output

    @patch("src.novel.services.edit_service.NovelEditService")
    def test_edit_service_exception(self, mock_svc_cls, tmp_path):
        """Unexpected exceptions should abort cleanly (not crash with traceback)."""
        project = _make_project(tmp_path)

        mock_svc = MagicMock()
        mock_svc.edit.side_effect = RuntimeError("LLM 超时")
        mock_svc_cls.return_value = mock_svc

        runner = CliRunner()
        result = runner.invoke(cli, [
            "novel", "edit", str(project),
            "-i", "测试指令",
        ])

        assert result.exit_code != 0

    def test_edit_nonexistent_project(self, tmp_path):
        """Click's exists=True should reject bogus paths before service runs."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "novel", "edit", str(tmp_path / "does_not_exist"),
            "-i", "添加角色",
        ])
        assert result.exit_code != 0

    def test_edit_missing_instruction(self, tmp_path):
        """--instruction is required."""
        project = _make_project(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "edit", str(project)])
        assert result.exit_code != 0
        assert "instruction" in result.output.lower() or "required" in result.output.lower()


# ---------------------------------------------------------------------------
# novel history
# ---------------------------------------------------------------------------


class TestNovelHistory:
    """Tests for `main.py novel history`."""

    @patch("src.novel.services.edit_service.NovelEditService")
    def test_history_non_empty(self, mock_svc_cls, tmp_path):
        project = _make_project(tmp_path)

        mock_svc = MagicMock()
        mock_svc.get_history.return_value = [
            {
                "change_id": "c1",
                "timestamp": "2026-04-01T10:00:00+00:00",
                "change_type": "add_character",
                "entity_type": "character",
                "description": "添加角色 李明",
                "author": "user",
            },
            {
                "change_id": "c2",
                "timestamp": "2026-04-02T12:00:00+00:00",
                "change_type": "update_outline",
                "entity_type": "outline",
                "description": "修改第5章目标",
                "author": "ai",
            },
        ]
        mock_svc_cls.return_value = mock_svc

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "history", str(project)])

        assert result.exit_code == 0, result.output
        assert "add_character" in result.output
        assert "update_outline" in result.output
        assert "李明" in result.output or "修改第5章" in result.output
        assert "user" in result.output
        assert "ai" in result.output
        assert "共 2 条" in result.output

        mock_svc.get_history.assert_called_once()
        assert mock_svc.get_history.call_args.kwargs["limit"] == 20

    @patch("src.novel.services.edit_service.NovelEditService")
    def test_history_empty(self, mock_svc_cls, tmp_path):
        project = _make_project(tmp_path)

        mock_svc = MagicMock()
        mock_svc.get_history.return_value = []
        mock_svc_cls.return_value = mock_svc

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "history", str(project)])

        assert result.exit_code == 0
        assert "暂无变更历史" in result.output

    @patch("src.novel.services.edit_service.NovelEditService")
    def test_history_limit_passes_through(self, mock_svc_cls, tmp_path):
        project = _make_project(tmp_path)
        mock_svc = MagicMock()
        mock_svc.get_history.return_value = []
        mock_svc_cls.return_value = mock_svc

        runner = CliRunner()
        result = runner.invoke(cli, [
            "novel", "history", str(project),
            "--limit", "5",
        ])
        assert result.exit_code == 0
        assert mock_svc.get_history.call_args.kwargs["limit"] == 5

    @patch("src.novel.services.edit_service.NovelEditService")
    def test_history_filter_by_change_type(self, mock_svc_cls, tmp_path):
        project = _make_project(tmp_path)

        mock_svc = MagicMock()
        # CLI now delegates filter to the service — mock returns pre-filtered result.
        mock_svc.get_history.return_value = [
            {
                "change_id": "c1",
                "timestamp": "2026-04-01T10:00:00+00:00",
                "change_type": "add_character",
                "entity_type": "character",
                "description": "添加 李明",
                "author": "user",
            },
            {
                "change_id": "c3",
                "timestamp": "2026-04-03T10:00:00+00:00",
                "change_type": "add_character",
                "entity_type": "character",
                "description": "添加 王五",
                "author": "ai",
            },
        ]
        mock_svc_cls.return_value = mock_svc

        runner = CliRunner()
        result = runner.invoke(cli, [
            "novel", "history", str(project),
            "--change-type", "add_character",
        ])

        assert result.exit_code == 0, result.output
        assert "李明" in result.output
        assert "王五" in result.output
        assert "共 2 条" in result.output
        # Filter must be pushed to service layer (applied before limit)
        call_kwargs = mock_svc.get_history.call_args.kwargs
        assert call_kwargs["change_type"] == "add_character"

    @patch("src.novel.services.edit_service.NovelEditService")
    def test_history_filter_no_match(self, mock_svc_cls, tmp_path):
        """Filter is applied at service layer — mock returns empty when no match."""
        project = _make_project(tmp_path)
        mock_svc = MagicMock()
        # Service-side filter already returned nothing for this type.
        mock_svc.get_history.return_value = []
        mock_svc_cls.return_value = mock_svc

        runner = CliRunner()
        result = runner.invoke(cli, [
            "novel", "history", str(project),
            "-t", "delete_world_setting",
        ])
        assert result.exit_code == 0
        assert "暂无变更历史" in result.output
        call_kwargs = mock_svc.get_history.call_args.kwargs
        assert call_kwargs["change_type"] == "delete_world_setting"

    def test_history_nonexistent_project(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "novel", "history", str(tmp_path / "nope"),
        ])
        assert result.exit_code != 0

    @patch("src.novel.services.edit_service.NovelEditService")
    def test_history_service_exception(self, mock_svc_cls, tmp_path):
        project = _make_project(tmp_path)
        mock_svc = MagicMock()
        mock_svc.get_history.side_effect = RuntimeError("IO error")
        mock_svc_cls.return_value = mock_svc

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "history", str(project)])
        assert result.exit_code != 0
