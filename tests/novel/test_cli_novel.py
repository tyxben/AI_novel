"""CLI novel 子命令测试

覆盖：
- novel import 命令
- novel list 命令
- novel status 命令（含 --verbose 增强）
- 边界条件
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from main import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake-model"
    usage: dict | None = None


CHARACTERS_JSON = json.dumps({
    "characters": [
        {"name": "李明", "role": "主角", "description": "少年", "personality": "勇敢"},
    ]
})

WORLD_SETTING_JSON = json.dumps({
    "era": "现代",
    "location": "北京",
    "rules": [],
    "terms": {},
})


def _create_mock_project(base_dir: Path, novel_id: str, **overrides) -> Path:
    """Create a minimal mock novel project directory."""
    project_dir = base_dir / "novels" / novel_id
    project_dir.mkdir(parents=True, exist_ok=True)

    chapters_dir = project_dir / "chapters"
    chapters_dir.mkdir(exist_ok=True)

    novel_data = {
        "novel_id": novel_id,
        "title": overrides.get("title", f"测试小说-{novel_id}"),
        "genre": overrides.get("genre", "玄幻"),
        "theme": overrides.get("theme", "测试"),
        "target_words": overrides.get("target_words", 50000),
        "status": overrides.get("status", "writing"),
        "current_chapter": overrides.get("current_chapter", 5),
        "updated_at": overrides.get("updated_at", "2026-01-01T00:00:00"),
        "outline": {
            "template": "custom",
            "chapters": [
                {
                    "chapter_number": i,
                    "title": f"第{i}章",
                    "goal": f"目标{i}",
                    "key_events": [f"事件{i}"],
                }
                for i in range(1, overrides.get("total_chapters", 10) + 1)
            ],
        },
        "characters": overrides.get("characters", [
            {"name": "主角", "role": "主角", "occupation": "修仙者"},
        ]),
        "world_setting": overrides.get("world_setting", {
            "era": "架空",
            "location": "九州",
            "rules": ["天道无情"],
        }),
    }

    with open(project_dir / "novel.json", "w", encoding="utf-8") as f:
        json.dump(novel_data, f, ensure_ascii=False, indent=2)

    # Create some chapter files
    for i in range(1, overrides.get("current_chapter", 5) + 1):
        ch_data = {
            "chapter_number": i,
            "title": f"第{i}章",
            "word_count": 2500,
            "status": "draft",
        }
        with open(chapters_dir / f"chapter_{i:03d}.json", "w", encoding="utf-8") as f:
            json.dump(ch_data, f, ensure_ascii=False)
        (chapters_dir / f"chapter_{i:03d}.txt").write_text(
            f"第{i}章内容" * 500, encoding="utf-8"
        )

    return project_dir


# ---------------------------------------------------------------------------
# novel list tests
# ---------------------------------------------------------------------------


class TestNovelList:
    """Test the 'novel list' command."""

    def test_list_empty_workspace(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "list", "-w", str(tmp_path)])
        assert result.exit_code == 0
        assert "没有找到" in result.output

    def test_list_no_novels_dir(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "list", "-w", str(tmp_path)])
        assert result.exit_code == 0
        assert "没有找到" in result.output

    def test_list_with_projects(self, tmp_path):
        ws = tmp_path / "ws"
        _create_mock_project(ws, "novel_aaa", title="小说A", updated_at="2026-03-01T00:00:00")
        _create_mock_project(ws, "novel_bbb", title="小说B", updated_at="2026-04-01T00:00:00")

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "list", "-w", str(ws)])
        assert result.exit_code == 0
        assert "novel_aaa" in result.output
        assert "novel_bbb" in result.output
        assert "小说A" in result.output or "小说" in result.output
        assert "2" in result.output  # "共 2 个项目"

    def test_list_sorted_by_update_time(self, tmp_path):
        ws = tmp_path / "ws"
        _create_mock_project(ws, "novel_old", updated_at="2025-01-01T00:00:00")
        _create_mock_project(ws, "novel_new", updated_at="2026-06-01T00:00:00")

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "list", "-w", str(ws)])
        assert result.exit_code == 0
        # novel_new should appear before novel_old in output
        pos_new = result.output.find("novel_new")
        pos_old = result.output.find("novel_old")
        assert pos_new < pos_old, "Newer project should appear first"

    def test_list_skips_invalid_dirs(self, tmp_path):
        ws = tmp_path / "ws"
        _create_mock_project(ws, "novel_good")
        # Create a directory without novel.json
        (ws / "novels" / "invalid_dir").mkdir(parents=True, exist_ok=True)
        # Create a file (not a directory)
        (ws / "novels" / "not_a_dir.txt").write_text("test", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "list", "-w", str(ws)])
        assert result.exit_code == 0
        assert "novel_good" in result.output
        assert "1" in result.output  # "共 1 个项目"


# ---------------------------------------------------------------------------
# novel status tests
# ---------------------------------------------------------------------------


class TestNovelStatus:
    """Test the 'novel status' command."""

    def test_status_basic(self, tmp_path):
        ws = tmp_path / "ws"
        project = _create_mock_project(ws, "novel_test", current_chapter=5, total_chapters=10)

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "status", str(project)])
        assert result.exit_code == 0
        assert "novel_test" in result.output
        assert "5" in result.output  # current chapter
        assert "10" in result.output  # total chapters

    def test_status_verbose_shows_characters(self, tmp_path):
        ws = tmp_path / "ws"
        characters = [
            {"name": "陈风", "role": "主角", "occupation": "修仙者"},
            {"name": "王霸", "role": "反派", "occupation": "魔修"},
        ]
        project = _create_mock_project(ws, "novel_test", characters=characters)

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "status", str(project), "-v"])
        assert result.exit_code == 0
        assert "陈风" in result.output
        assert "王霸" in result.output

    def test_status_verbose_shows_world_setting(self, tmp_path):
        ws = tmp_path / "ws"
        world = {"era": "上古", "location": "蛮荒大陆", "rules": ["弱肉强食"]}
        project = _create_mock_project(ws, "novel_test", world_setting=world)

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "status", str(project), "-v"])
        assert result.exit_code == 0
        assert "上古" in result.output
        assert "蛮荒大陆" in result.output

    def test_status_verbose_shows_decisions(self, tmp_path):
        ws = tmp_path / "ws"
        project = _create_mock_project(ws, "novel_test")
        # Add checkpoint with decisions
        ckpt = {
            "decisions": [
                {"agent": "writer", "step": "generate", "decision": "使用第一人称"},
            ]
        }
        with open(project / "checkpoint.json", "w", encoding="utf-8") as f:
            json.dump(ckpt, f, ensure_ascii=False)

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "status", str(project), "-v"])
        assert result.exit_code == 0
        assert "writer" in result.output
        assert "generate" in result.output

    def test_status_shows_completion_percentage(self, tmp_path):
        ws = tmp_path / "ws"
        project = _create_mock_project(ws, "novel_test", current_chapter=5, total_chapters=10)

        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "status", str(project)])
        assert result.exit_code == 0
        assert "50.0%" in result.output

    def test_status_nonexistent_project(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["novel", "status", "/nonexistent/path"])
        # Click should report the path doesn't exist
        assert result.exit_code != 0


