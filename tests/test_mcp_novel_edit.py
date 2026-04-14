"""Tests for MCP novel edit tools.

Covers:
- novel_edit_setting
- novel_get_change_history
- novel_analyze_change_impact
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    novels_dir = tmp_path / "novels" / "novel_edit_test"
    novels_dir.mkdir(parents=True)

    novel_json = {
        "novel_id": "novel_edit_test",
        "title": "编辑测试",
        "genre": "玄幻",
        "current_chapter": 3,
        "outline": {"chapters": []},
        "characters": [],
        "world_setting": {"era": "古代"},
    }
    (novels_dir / "novel.json").write_text(
        json.dumps(novel_json, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


def _make_edit_result(
    status: str = "success",
    impact_report: dict | None = None,
    **overrides,
):
    """Build a minimal EditResult-like instance for mocking."""
    from src.novel.services.edit_service import EditResult

    kwargs = {
        "change_id": "change_123",
        "status": status,
        "change_type": "update",
        "entity_type": "character",
        "entity_id": "char_1",
        "old_value": {"age": 18},
        "new_value": {"age": 20},
        "effective_from_chapter": 4,
        "reasoning": "test reasoning",
        "error": None,
        "impact_report": impact_report,
    }
    kwargs.update(overrides)
    return EditResult(**kwargs)


# ---------------------------------------------------------------------------
# novel_edit_setting
# ---------------------------------------------------------------------------

@pytest.fixture
def configured_workspace(tmp_workspace):
    """Configure mcp_server._DEFAULT_WORKSPACE to tmp_workspace."""
    import mcp_server
    mcp_server._DEFAULT_WORKSPACE = str(tmp_workspace)
    return tmp_workspace


class TestNovelEditSetting:
    """测试 novel_edit_setting MCP 工具。"""

    def test_edit_success_returns_dataclass_dict(self, configured_workspace):
        """成功时返回 EditResult.asdict()。"""
        import mcp_server

        project_path = str(configured_workspace / "novels" / "novel_edit_test")
        service_mock = MagicMock()
        service_mock.edit.return_value = _make_edit_result()

        with patch(
            "src.novel.services.edit_service.NovelEditService",
            return_value=service_mock,
        ):
            result = mcp_server.novel_edit_setting(
                project_path=project_path,
                instruction="把张三的年龄改为20岁",
            )

        assert result["status"] == "success"
        assert result["change_id"] == "change_123"
        assert result["change_type"] == "update"
        assert result["entity_type"] == "character"
        assert result["new_value"] == {"age": 20}
        # dry_run 默认 False
        service_mock.edit.assert_called_once()
        call_kwargs = service_mock.edit.call_args.kwargs
        assert call_kwargs["instruction"] == "把张三的年龄改为20岁"
        assert call_kwargs["dry_run"] is False

    def test_edit_dry_run_includes_impact_report(self, configured_workspace):
        """dry_run=True 时返回的结果包含 impact_report。"""
        import mcp_server

        project_path = str(configured_workspace / "novels" / "novel_edit_test")
        impact = {
            "affected_chapters": [4, 5],
            "severity": "medium",
            "conflicts": [],
            "warnings": ["修改非核心属性"],
            "summary": "影响 2 个章节",
        }
        service_mock = MagicMock()
        service_mock.edit.return_value = _make_edit_result(
            status="preview",
            impact_report=impact,
        )

        with patch(
            "src.novel.services.edit_service.NovelEditService",
            return_value=service_mock,
        ):
            result = mcp_server.novel_edit_setting(
                project_path=project_path,
                instruction="修改角色",
                dry_run=True,
            )

        assert result["status"] == "preview"
        assert result["impact_report"] is not None
        assert result["impact_report"]["severity"] == "medium"
        assert result["impact_report"]["affected_chapters"] == [4, 5]

        assert service_mock.edit.call_args.kwargs["dry_run"] is True

    def test_edit_service_raises_returns_failed(self, configured_workspace):
        """service.edit 抛异常时返回 failed。"""
        import mcp_server

        project_path = str(configured_workspace / "novels" / "novel_edit_test")
        service_mock = MagicMock()
        service_mock.edit.side_effect = RuntimeError("LLM exploded")

        with patch(
            "src.novel.services.edit_service.NovelEditService",
            return_value=service_mock,
        ):
            result = mcp_server.novel_edit_setting(
                project_path=project_path,
                instruction="随便改点什么",
            )

        assert result["status"] == "failed"
        assert "LLM exploded" in result["error"]

    def test_edit_path_traversal_rejected(self, configured_workspace):
        """越界路径被 _validate_project_path 拒绝。"""
        import mcp_server

        result = mcp_server.novel_edit_setting(
            project_path="/etc/passwd",
            instruction="破坏世界",
        )
        assert result["status"] == "failed"
        assert "error" in result

    def test_edit_passes_effective_from_chapter(self, configured_workspace):
        """effective_from_chapter 参数正确传递。"""
        import mcp_server

        project_path = str(configured_workspace / "novels" / "novel_edit_test")
        service_mock = MagicMock()
        service_mock.edit.return_value = _make_edit_result()

        with patch(
            "src.novel.services.edit_service.NovelEditService",
            return_value=service_mock,
        ):
            mcp_server.novel_edit_setting(
                project_path=project_path,
                instruction="修改",
                effective_from_chapter=10,
            )

        assert (
            service_mock.edit.call_args.kwargs["effective_from_chapter"] == 10
        )


# ---------------------------------------------------------------------------
# novel_get_change_history
# ---------------------------------------------------------------------------

class TestNovelGetChangeHistory:
    """测试 novel_get_change_history MCP 工具。"""

    def test_get_history_success(self, configured_workspace):
        import mcp_server

        project_path = str(configured_workspace / "novels" / "novel_edit_test")
        changes = [
            {"change_id": "c1", "change_type": "update"},
            {"change_id": "c2", "change_type": "add"},
        ]
        service_mock = MagicMock()
        service_mock.get_history.return_value = changes

        with patch(
            "src.novel.services.edit_service.NovelEditService",
            return_value=service_mock,
        ):
            result = mcp_server.novel_get_change_history(
                project_path=project_path,
                limit=10,
            )

        assert result["total"] == 2
        assert result["changes"] == changes
        service_mock.get_history.assert_called_once()
        # 确保 limit 传递正确
        assert service_mock.get_history.call_args.kwargs["limit"] == 10

    def test_limit_clamped_upper(self, configured_workspace):
        """limit 超过 100 被截断到 100。"""
        import mcp_server

        project_path = str(configured_workspace / "novels" / "novel_edit_test")
        service_mock = MagicMock()
        service_mock.get_history.return_value = []

        with patch(
            "src.novel.services.edit_service.NovelEditService",
            return_value=service_mock,
        ):
            mcp_server.novel_get_change_history(
                project_path=project_path,
                limit=500,
            )

        assert service_mock.get_history.call_args.kwargs["limit"] == 100

    def test_limit_clamped_lower(self, configured_workspace):
        """limit 小于 1 被提升到 1。"""
        import mcp_server

        project_path = str(configured_workspace / "novels" / "novel_edit_test")
        service_mock = MagicMock()
        service_mock.get_history.return_value = []

        with patch(
            "src.novel.services.edit_service.NovelEditService",
            return_value=service_mock,
        ):
            mcp_server.novel_get_change_history(
                project_path=project_path,
                limit=0,
            )

        assert service_mock.get_history.call_args.kwargs["limit"] == 1

    def test_service_raises_returns_failed(self, configured_workspace):
        """service 抛异常 -> failed。"""
        import mcp_server

        project_path = str(configured_workspace / "novels" / "novel_edit_test")
        service_mock = MagicMock()
        service_mock.get_history.side_effect = FileNotFoundError("no changelog")

        with patch(
            "src.novel.services.edit_service.NovelEditService",
            return_value=service_mock,
        ):
            result = mcp_server.novel_get_change_history(
                project_path=project_path,
            )

        assert result["status"] == "failed"
        assert "no changelog" in result["error"]

    def test_path_traversal_rejected(self, configured_workspace):
        import mcp_server

        result = mcp_server.novel_get_change_history(
            project_path="../../../etc",
        )
        assert result["status"] == "failed"
        assert "error" in result


# ---------------------------------------------------------------------------
# novel_analyze_change_impact
# ---------------------------------------------------------------------------

class TestNovelAnalyzeChangeImpact:
    """测试 novel_analyze_change_impact MCP 工具。"""

    def test_analyze_returns_impact_report(self, configured_workspace):
        """成功 dry_run 返回 impact_report。"""
        import mcp_server

        project_path = str(configured_workspace / "novels" / "novel_edit_test")
        impact = {
            "affected_chapters": [4, 5, 6],
            "severity": "high",
            "conflicts": ["角色核心属性变更与章节冲突"],
            "warnings": [],
            "summary": "影响 3 个章节",
        }
        service_mock = MagicMock()
        service_mock.edit.return_value = _make_edit_result(
            status="preview",
            impact_report=impact,
        )

        with patch(
            "src.novel.services.edit_service.NovelEditService",
            return_value=service_mock,
        ):
            result = mcp_server.novel_analyze_change_impact(
                project_path=project_path,
                instruction="删除角色张三",
            )

        # 调用 edit(dry_run=True)
        assert service_mock.edit.call_args.kwargs["dry_run"] is True
        assert service_mock.edit.call_args.kwargs["instruction"] == "删除角色张三"

        assert result["status"] == "preview"
        assert result["impact_report"]["severity"] == "high"
        assert result["impact_report"]["affected_chapters"] == [4, 5, 6]
        assert "角色核心属性变更" in result["impact_report"]["conflicts"][0]

    def test_analyze_passes_effective_from_chapter(self, configured_workspace):
        """effective_from_chapter 参数透传。"""
        import mcp_server

        project_path = str(configured_workspace / "novels" / "novel_edit_test")
        service_mock = MagicMock()
        service_mock.edit.return_value = _make_edit_result(status="preview")

        with patch(
            "src.novel.services.edit_service.NovelEditService",
            return_value=service_mock,
        ):
            mcp_server.novel_analyze_change_impact(
                project_path=project_path,
                instruction="添加角色",
                effective_from_chapter=7,
            )

        assert (
            service_mock.edit.call_args.kwargs["effective_from_chapter"] == 7
        )

    def test_analyze_empty_instruction_rejected(self, configured_workspace):
        """空 instruction 直接返回 failed。"""
        import mcp_server

        project_path = str(configured_workspace / "novels" / "novel_edit_test")

        with patch(
            "src.novel.services.edit_service.NovelEditService"
        ) as MockService:
            result = mcp_server.novel_analyze_change_impact(
                project_path=project_path,
                instruction="",
            )

        assert result["status"] == "failed"
        assert "instruction" in result["error"]
        # service 不应被构造或调用
        MockService.assert_not_called()

    def test_analyze_whitespace_instruction_rejected(
        self, configured_workspace
    ):
        """全空白 instruction 也拒绝。"""
        import mcp_server

        project_path = str(configured_workspace / "novels" / "novel_edit_test")

        with patch(
            "src.novel.services.edit_service.NovelEditService"
        ) as MockService:
            result = mcp_server.novel_analyze_change_impact(
                project_path=project_path,
                instruction="   \n\t  ",
            )

        assert result["status"] == "failed"
        MockService.assert_not_called()

    def test_analyze_service_raises_returns_failed(self, configured_workspace):
        """service.edit 抛异常 -> failed。"""
        import mcp_server

        project_path = str(configured_workspace / "novels" / "novel_edit_test")
        service_mock = MagicMock()
        service_mock.edit.side_effect = ValueError("parse failed")

        with patch(
            "src.novel.services.edit_service.NovelEditService",
            return_value=service_mock,
        ):
            result = mcp_server.novel_analyze_change_impact(
                project_path=project_path,
                instruction="随便写点",
            )

        assert result["status"] == "failed"
        assert "parse failed" in result["error"]

    def test_analyze_path_traversal_rejected(self, configured_workspace):
        """路径越界 -> failed。"""
        import mcp_server

        result = mcp_server.novel_analyze_change_impact(
            project_path="/tmp/outside_workspace",
            instruction="修改",
        )
        assert result["status"] == "failed"
        assert "error" in result

    def test_analyze_nonexistent_project_path(self, configured_workspace):
        """项目目录不存在时 service 会返回 failed 的 EditResult。"""
        import mcp_server

        # 真实调用但 service 返回 failed
        project_path = str(configured_workspace / "novels" / "nonexistent_novel")
        # 需要目录存在以通过 resolve，这里手动创建
        Path(project_path).mkdir(parents=True, exist_ok=True)
        service_mock = MagicMock()
        service_mock.edit.return_value = _make_edit_result(
            status="failed",
            error="小说项目不存在: nonexistent_novel",
            change_type="",
            entity_type="",
            entity_id=None,
            old_value=None,
            new_value=None,
            effective_from_chapter=None,
            reasoning="",
            impact_report=None,
        )

        with patch(
            "src.novel.services.edit_service.NovelEditService",
            return_value=service_mock,
        ):
            result = mcp_server.novel_analyze_change_impact(
                project_path=project_path,
                instruction="修改",
            )

        assert result["status"] == "failed"
        assert result["error"] is not None

    def test_analyze_returns_all_edit_result_fields(
        self, configured_workspace
    ):
        """返回结果包含 EditResult 所有字段。"""
        import mcp_server

        project_path = str(configured_workspace / "novels" / "novel_edit_test")
        service_mock = MagicMock()
        service_mock.edit.return_value = _make_edit_result(
            status="preview",
            impact_report={
                "affected_chapters": [],
                "severity": "low",
                "conflicts": [],
                "warnings": [],
                "summary": "",
            },
        )

        with patch(
            "src.novel.services.edit_service.NovelEditService",
            return_value=service_mock,
        ):
            result = mcp_server.novel_analyze_change_impact(
                project_path=project_path,
                instruction="修改",
            )

        # EditResult dataclass 所有字段应存在
        for field in (
            "change_id",
            "status",
            "change_type",
            "entity_type",
            "entity_id",
            "old_value",
            "new_value",
            "effective_from_chapter",
            "reasoning",
            "error",
            "impact_report",
        ):
            assert field in result, f"缺少字段: {field}"


# ---------------------------------------------------------------------------
# MCP 工具注册检查
# ---------------------------------------------------------------------------

class TestToolsRegistered:
    """确保 3 个编辑相关 MCP 工具均已注册。"""

    def test_all_three_edit_tools_registered(self):
        import asyncio
        import mcp_server

        async def _list():
            return await mcp_server.mcp.list_tools()

        tools = asyncio.run(_list())
        names = {t.name for t in tools}

        assert "novel_edit_setting" in names
        assert "novel_get_change_history" in names
        assert "novel_analyze_change_impact" in names


class TestInferWorkspace:
    """Regression: `_infer_workspace` must use the LAST 'novels' segment.

    A user whose ancestor path is named 'novels' would otherwise be redirected
    to the wrong project tree.
    """

    def test_last_novels_used_when_ancestor_also_named_novels(self):
        from mcp_server import _infer_workspace

        ws = _infer_workspace(
            "/Users/alice/novels/archive/workspace/novels/novel_1"
        )
        assert ws == "/Users/alice/novels/archive/workspace"

    def test_single_novels_still_works(self):
        from mcp_server import _infer_workspace

        ws = _infer_workspace("workspace/novels/novel_abc")
        assert ws == "workspace"

    def test_no_novels_segment_falls_back_to_default(self):
        from mcp_server import _DEFAULT_WORKSPACE, _infer_workspace

        ws = _infer_workspace("/tmp/somewhere/novel_abc")
        assert ws == _DEFAULT_WORKSPACE
