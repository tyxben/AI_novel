"""Tests for the Phase 4 three-stage MCP tools.

Covers:
- novel_propose_* (9 tools) happy + failure paths
- novel_accept_proposal happy + failure paths
- novel_regenerate_section happy + failure paths
- _validate_project_path rejection on path traversal
- novel_create remains callable but docstring marked [DEPRECATED]
- All 11 new tools are registered with the FastMCP instance

The tests patch ``src.novel.services.tool_facade.NovelToolFacade`` so we do
NOT depend on E1's real implementation — only on the interface contract.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fakes that mimic ProposalEnvelope / AcceptResult shape
# ---------------------------------------------------------------------------


class _FakeEnvelope:
    """Minimal stand-in for ``ProposalEnvelope``.

    The only contract the caller relies on is ``to_dict()``.
    """

    def __init__(
        self,
        proposal_id: str = "prop-abc",
        proposal_type: str = "synopsis",
        project_path: str = "",
        data: dict | None = None,
        decisions: list | None = None,
        errors: list | None = None,
        warnings: list | None = None,
        created_at: str = "2026-04-21T00:00:00+00:00",
    ):
        self._d = {
            "proposal_id": proposal_id,
            "proposal_type": proposal_type,
            "project_path": project_path,
            "data": data if data is not None else {},
            "decisions": decisions or [],
            "errors": errors or [],
            "warnings": warnings or [],
            "created_at": created_at,
        }

    def to_dict(self) -> dict:
        return dict(self._d)


class _FakeAcceptResult:
    """Minimal stand-in for ``AcceptResult``."""

    def __init__(
        self,
        status: str = "accepted",
        proposal_id: str = "prop-abc",
        proposal_type: str = "synopsis",
        changelog_id: str | None = None,
        error: str | None = None,
    ):
        self._d: dict = {
            "status": status,
            "proposal_id": proposal_id,
            "proposal_type": proposal_type,
        }
        if changelog_id:
            self._d["changelog_id"] = changelog_id
        if error:
            self._d["error"] = error

    def to_dict(self) -> dict:
        return dict(self._d)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_mcp_state():
    """Reset mcp_server globals between tests."""
    import mcp_server

    original_ws = mcp_server._DEFAULT_WORKSPACE
    mcp_server._facade_instance = None
    mcp_server._pipeline_instance = None
    yield
    mcp_server._DEFAULT_WORKSPACE = original_ws
    mcp_server._facade_instance = None
    mcp_server._pipeline_instance = None


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a workspace with a valid novel project directory."""
    novels_dir = tmp_path / "novels" / "novel_propose_test"
    novels_dir.mkdir(parents=True)
    (novels_dir / "novel.json").write_text(
        json.dumps(
            {
                "novel_id": "novel_propose_test",
                "title": "三段式测试",
                "genre": "玄幻",
                "outline": {"chapters": []},
                "characters": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def configured_workspace(tmp_workspace):
    """Point mcp_server at our tmp workspace."""
    import mcp_server

    mcp_server._DEFAULT_WORKSPACE = str(tmp_workspace)
    return tmp_workspace


@pytest.fixture
def mock_facade_factory():
    """Patch NovelToolFacade constructor so every test can inject its own mock."""

    def _make(mock_instance):
        return patch(
            "src.novel.services.tool_facade.NovelToolFacade",
            return_value=mock_instance,
        )

    return _make


@pytest.fixture
def project_path(configured_workspace) -> str:
    return str(configured_workspace / "novels" / "novel_propose_test")


# ---------------------------------------------------------------------------
# novel_propose_project_setup
# ---------------------------------------------------------------------------


class TestProposeProjectSetup:
    def test_happy_path_returns_envelope_dict(self, mock_facade_factory):
        import mcp_server

        fake = _FakeEnvelope(
            proposal_type="project_setup",
            data={"genre": "玄幻", "target_words": 100000},
        )
        facade = MagicMock()
        facade.propose_project_setup.return_value = fake

        with mock_facade_factory(facade):
            result = mcp_server.novel_propose_project_setup(
                inspiration="少年修士逆天改命",
                hints={"genre": "玄幻"},
            )

        assert result["proposal_id"] == "prop-abc"
        assert result["proposal_type"] == "project_setup"
        assert result["data"]["genre"] == "玄幻"
        assert result["data"]["target_words"] == 100000
        facade.propose_project_setup.assert_called_once()
        call_kwargs = facade.propose_project_setup.call_args.kwargs
        assert call_kwargs["inspiration"] == "少年修士逆天改命"
        assert call_kwargs["hints"] == {"genre": "玄幻"}

    def test_hints_none_passed_through(self, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.propose_project_setup.return_value = _FakeEnvelope(
            proposal_type="project_setup",
        )
        with mock_facade_factory(facade):
            mcp_server.novel_propose_project_setup(inspiration="一句话")

        assert facade.propose_project_setup.call_args.kwargs["hints"] is None

    def test_facade_exception_returns_error(self, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.propose_project_setup.side_effect = RuntimeError("LLM timeout")
        with mock_facade_factory(facade):
            result = mcp_server.novel_propose_project_setup(inspiration="x")

        assert "error" in result
        assert "LLM timeout" in result["error"]


# ---------------------------------------------------------------------------
# novel_propose_synopsis
# ---------------------------------------------------------------------------


class TestProposeSynopsis:
    def test_happy_path(self, project_path, mock_facade_factory):
        import mcp_server

        fake = _FakeEnvelope(
            proposal_type="synopsis",
            data={"synopsis": "一段骨架", "main_storyline": {"beats": []}},
        )
        facade = MagicMock()
        facade.propose_synopsis.return_value = fake

        with mock_facade_factory(facade):
            result = mcp_server.novel_propose_synopsis(project_path)

        assert result["proposal_type"] == "synopsis"
        assert result["data"]["synopsis"] == "一段骨架"
        facade.propose_synopsis.assert_called_once()
        (passed_path,) = facade.propose_synopsis.call_args.args
        assert Path(passed_path).resolve() == Path(project_path).resolve()

    def test_path_traversal_rejected(self, configured_workspace):
        import mcp_server

        result = mcp_server.novel_propose_synopsis("/etc/passwd")
        assert "error" in result
        assert "工作空间" in result["error"] or "within" in result["error"].lower()

    def test_facade_exception_returns_error(
        self, project_path, mock_facade_factory
    ):
        import mcp_server

        facade = MagicMock()
        facade.propose_synopsis.side_effect = ValueError("invalid meta")
        with mock_facade_factory(facade):
            result = mcp_server.novel_propose_synopsis(project_path)
        assert "error" in result
        assert "invalid meta" in result["error"]


# ---------------------------------------------------------------------------
# novel_propose_main_outline
# ---------------------------------------------------------------------------


class TestProposeMainOutline:
    def test_happy_path_with_custom_ideas(
        self, project_path, mock_facade_factory
    ):
        import mcp_server

        fake = _FakeEnvelope(
            proposal_type="main_outline",
            data={"outline": {"premise": "x"}, "style_name": "webnovel.shuangwen"},
            decisions=[{"agent": "pa", "step": "propose", "decision": "ok"}],
        )
        facade = MagicMock()
        facade.propose_main_outline.return_value = fake

        with mock_facade_factory(facade):
            result = mcp_server.novel_propose_main_outline(
                project_path, custom_ideas="要多情感线"
            )

        assert result["proposal_type"] == "main_outline"
        assert result["decisions"][0]["agent"] == "pa"
        call_kwargs = facade.propose_main_outline.call_args.kwargs
        assert call_kwargs["custom_ideas"] == "要多情感线"

    def test_custom_ideas_default_none(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.propose_main_outline.return_value = _FakeEnvelope(
            proposal_type="main_outline"
        )
        with mock_facade_factory(facade):
            mcp_server.novel_propose_main_outline(project_path)

        assert facade.propose_main_outline.call_args.kwargs["custom_ideas"] is None

    def test_path_traversal(self, configured_workspace):
        import mcp_server

        result = mcp_server.novel_propose_main_outline("/tmp/outside")
        assert "error" in result


# ---------------------------------------------------------------------------
# novel_propose_characters / world_setting / story_arcs / volume_breakdown
# ---------------------------------------------------------------------------


class TestProposeCharacters:
    def test_happy(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.propose_characters.return_value = _FakeEnvelope(
            proposal_type="characters",
            data={"characters": [{"name": "张三"}]},
        )
        with mock_facade_factory(facade):
            result = mcp_server.novel_propose_characters(
                project_path, synopsis="context"
            )
        assert result["proposal_type"] == "characters"
        assert result["data"]["characters"][0]["name"] == "张三"
        assert facade.propose_characters.call_args.kwargs["synopsis"] == "context"

    def test_synopsis_default_none(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.propose_characters.return_value = _FakeEnvelope(
            proposal_type="characters"
        )
        with mock_facade_factory(facade):
            mcp_server.novel_propose_characters(project_path)
        assert facade.propose_characters.call_args.kwargs["synopsis"] is None

    def test_exception(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.propose_characters.side_effect = KeyError("missing")
        with mock_facade_factory(facade):
            result = mcp_server.novel_propose_characters(project_path)
        assert "error" in result


class TestProposeWorldSetting:
    def test_happy(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.propose_world_setting.return_value = _FakeEnvelope(
            proposal_type="world_setting",
            data={"world_setting": {"era": "古代"}},
        )
        with mock_facade_factory(facade):
            result = mcp_server.novel_propose_world_setting(project_path)
        assert result["data"]["world_setting"]["era"] == "古代"

    def test_exception(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.propose_world_setting.side_effect = RuntimeError("boom")
        with mock_facade_factory(facade):
            result = mcp_server.novel_propose_world_setting(project_path)
        assert "error" in result
        assert "boom" in result["error"]


class TestProposeStoryArcs:
    def test_happy(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.propose_story_arcs.return_value = _FakeEnvelope(
            proposal_type="story_arcs",
            data={"arcs": [{"name": "主线"}]},
        )
        with mock_facade_factory(facade):
            result = mcp_server.novel_propose_story_arcs(project_path)
        assert result["proposal_type"] == "story_arcs"
        assert result["data"]["arcs"][0]["name"] == "主线"

    def test_path_traversal(self, configured_workspace):
        import mcp_server

        result = mcp_server.novel_propose_story_arcs("../../etc")
        assert "error" in result


class TestProposeVolumeBreakdown:
    def test_happy(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.propose_volume_breakdown.return_value = _FakeEnvelope(
            proposal_type="volume_breakdown",
            data={"volumes": [{"number": 1}, {"number": 2}]},
        )
        with mock_facade_factory(facade):
            result = mcp_server.novel_propose_volume_breakdown(project_path)
        assert len(result["data"]["volumes"]) == 2

    def test_synopsis_passthrough(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.propose_volume_breakdown.return_value = _FakeEnvelope(
            proposal_type="volume_breakdown"
        )
        with mock_facade_factory(facade):
            mcp_server.novel_propose_volume_breakdown(
                project_path, synopsis="override"
            )
        assert (
            facade.propose_volume_breakdown.call_args.kwargs["synopsis"]
            == "override"
        )


class TestProposeVolumeOutline:
    def test_happy(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.propose_volume_outline.return_value = _FakeEnvelope(
            proposal_type="volume_outline",
            data={"chapters": list(range(10))},
        )
        with mock_facade_factory(facade):
            result = mcp_server.novel_propose_volume_outline(project_path, 2)
        assert len(result["data"]["chapters"]) == 10
        args = facade.propose_volume_outline.call_args.args
        assert args[1] == 2

    def test_exception(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.propose_volume_outline.side_effect = IndexError("no such volume")
        with mock_facade_factory(facade):
            result = mcp_server.novel_propose_volume_outline(project_path, 99)
        assert "error" in result
        assert "no such volume" in result["error"]


class TestProposeChapterBrief:
    def test_happy(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.propose_chapter_brief.return_value = _FakeEnvelope(
            proposal_type="chapter_brief",
            data={"chapter_number": 5, "goal": "foo"},
            warnings=["character unknown"],
        )
        with mock_facade_factory(facade):
            result = mcp_server.novel_propose_chapter_brief(project_path, 5)
        assert result["data"]["chapter_number"] == 5
        assert "character unknown" in result["warnings"]
        args = facade.propose_chapter_brief.call_args.args
        assert args[1] == 5

    def test_path_traversal(self, configured_workspace):
        import mcp_server

        result = mcp_server.novel_propose_chapter_brief("/etc/passwd", 1)
        assert "error" in result


# ---------------------------------------------------------------------------
# novel_accept_proposal
# ---------------------------------------------------------------------------


class TestAcceptProposal:
    def test_happy_path_accepted(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.accept_proposal.return_value = _FakeAcceptResult(
            status="accepted",
            proposal_id="p-1",
            proposal_type="synopsis",
            changelog_id="cl-42",
        )
        with mock_facade_factory(facade):
            result = mcp_server.novel_accept_proposal(
                project_path,
                proposal_id="p-1",
                proposal_type="synopsis",
                data={"synopsis": "text"},
            )
        assert result["status"] == "accepted"
        assert result["proposal_id"] == "p-1"
        assert result["proposal_type"] == "synopsis"
        assert result["changelog_id"] == "cl-42"
        assert facade.accept_proposal.call_args.args[1] == "p-1"
        assert facade.accept_proposal.call_args.args[2] == "synopsis"
        assert facade.accept_proposal.call_args.args[3] == {"synopsis": "text"}

    def test_already_accepted_idempotent(
        self, project_path, mock_facade_factory
    ):
        import mcp_server

        facade = MagicMock()
        facade.accept_proposal.return_value = _FakeAcceptResult(
            status="already_accepted",
            proposal_id="p-1",
            proposal_type="synopsis",
        )
        with mock_facade_factory(facade):
            result = mcp_server.novel_accept_proposal(
                project_path,
                proposal_id="p-1",
                proposal_type="synopsis",
                data={},
            )
        assert result["status"] == "already_accepted"
        assert "changelog_id" not in result

    def test_facade_returns_failed(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.accept_proposal.return_value = _FakeAcceptResult(
            status="failed",
            proposal_id="p-1",
            proposal_type="synopsis",
            error="project not found",
        )
        with mock_facade_factory(facade):
            result = mcp_server.novel_accept_proposal(
                project_path, "p-1", "synopsis", {}
            )
        assert result["status"] == "failed"
        assert result["error"] == "project not found"

    def test_exception_returns_error_key(
        self, project_path, mock_facade_factory
    ):
        import mcp_server

        facade = MagicMock()
        facade.accept_proposal.side_effect = RuntimeError("disk full")
        with mock_facade_factory(facade):
            result = mcp_server.novel_accept_proposal(
                project_path, "p-1", "synopsis", {}
            )
        assert "error" in result
        assert "disk full" in result["error"]

    def test_path_traversal_rejected(self, configured_workspace):
        import mcp_server

        result = mcp_server.novel_accept_proposal(
            "/etc/passwd", "p", "synopsis", {}
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# novel_regenerate_section
# ---------------------------------------------------------------------------


class TestRegenerateSection:
    def test_happy_returns_new_envelope(
        self, project_path, mock_facade_factory
    ):
        import mcp_server

        facade = MagicMock()
        facade.regenerate_section.return_value = _FakeEnvelope(
            proposal_id="new-id",
            proposal_type="synopsis",
            data={"synopsis": "regenerated"},
        )
        with mock_facade_factory(facade):
            result = mcp_server.novel_regenerate_section(
                project_path,
                section="synopsis",
                hints="换主角性别",
            )
        assert result["proposal_id"] == "new-id"
        assert result["data"]["synopsis"] == "regenerated"
        kw = facade.regenerate_section.call_args.kwargs
        assert kw["section"] == "synopsis"
        assert kw["hints"] == "换主角性别"
        assert kw["volume_number"] is None

    def test_volume_outline_needs_volume_number(
        self, project_path, mock_facade_factory
    ):
        import mcp_server

        facade = MagicMock()
        facade.regenerate_section.return_value = _FakeEnvelope(
            proposal_type="volume_outline"
        )
        with mock_facade_factory(facade):
            mcp_server.novel_regenerate_section(
                project_path,
                section="volume_outline",
                hints="节奏紧凑点",
                volume_number=3,
            )
        assert facade.regenerate_section.call_args.kwargs["volume_number"] == 3

    def test_exception(self, project_path, mock_facade_factory):
        import mcp_server

        facade = MagicMock()
        facade.regenerate_section.side_effect = ValueError("unknown section")
        with mock_facade_factory(facade):
            result = mcp_server.novel_regenerate_section(
                project_path, section="wat", hints=""
            )
        assert "error" in result
        assert "unknown section" in result["error"]

    def test_path_traversal(self, configured_workspace):
        import mcp_server

        result = mcp_server.novel_regenerate_section(
            "/tmp/outside", section="synopsis", hints=""
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# novel_create deprecation marker
# ---------------------------------------------------------------------------


class TestNovelCreateDeprecated:
    def test_docstring_marked_deprecated(self):
        import mcp_server

        doc = mcp_server.novel_create.__doc__ or ""
        assert "[DEPRECATED]" in doc, (
            "novel_create docstring must start with [DEPRECATED] marker"
        )
        # Must point users at the replacement
        assert "novel_propose_project_setup" in doc
        assert "novel_accept_proposal" in doc


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestProposeToolsRegistered:
    def test_all_eleven_propose_tools_registered(self):
        import mcp_server

        async def _list():
            return await mcp_server.mcp.list_tools()

        tools = asyncio.run(_list())
        names = {t.name for t in tools}

        expected = {
            "novel_propose_project_setup",
            "novel_propose_synopsis",
            "novel_propose_main_outline",
            "novel_propose_characters",
            "novel_propose_world_setting",
            "novel_propose_story_arcs",
            "novel_propose_volume_breakdown",
            "novel_propose_volume_outline",
            "novel_propose_chapter_brief",
            "novel_accept_proposal",
            "novel_regenerate_section",
        }
        missing = expected - names
        assert not missing, f"missing tools: {missing}"


# ---------------------------------------------------------------------------
# _get_facade singleton behaviour
# ---------------------------------------------------------------------------


class TestFacadeSingleton:
    def test_facade_singleton_caches_instance(
        self, configured_workspace, mock_facade_factory
    ):
        """_get_facade must return the same instance across calls."""
        import mcp_server

        fake = MagicMock()
        fake.propose_synopsis.return_value = _FakeEnvelope()

        with mock_facade_factory(fake) as mocked_cls:
            inst1 = mcp_server._get_facade()
            inst2 = mcp_server._get_facade()

        assert inst1 is inst2
        # Constructor must have been called exactly once
        assert mocked_cls.call_count == 1
