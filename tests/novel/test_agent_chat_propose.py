"""Tests for Phase 4 三段式 propose / accept / regenerate agent_chat tools.

Covers:
    * TOOLS registration: 9 propose_* + accept_proposal + regenerate_section
    * Each tool happy path dispatches to NovelToolFacade
    * accept idempotency (facade returns status="already_accepted")
    * facade raising an exception → tool returns {"error": ...} (agent_chat
      must not crash)
    * plan_chapters retains [DEPRECATED] marker

All tests stub ``NovelToolFacade`` via ``unittest.mock.patch`` — the facade
itself is implemented by E1 in parallel and is not exercised here.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.novel.services.agent_chat import TOOLS, AgentToolExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


PROPOSE_TOOLS = (
    "propose_project_setup",
    "propose_synopsis",
    "propose_main_outline",
    "propose_characters",
    "propose_world_setting",
    "propose_story_arcs",
    "propose_volume_breakdown",
    "propose_volume_outline",
    "propose_chapter_brief",
)


def _fake_envelope(
    proposal_type: str,
    *,
    data: dict | None = None,
    decisions: list | None = None,
    errors: list | None = None,
) -> MagicMock:
    """Build a MagicMock envelope with to_dict() returning a realistic payload."""
    env = MagicMock()
    env.to_dict.return_value = {
        "proposal_id": f"pid-{proposal_type}",
        "proposal_type": proposal_type,
        "project_path": "/tmp/novels/n1",
        "data": data or {"example": "data"},
        "decisions": decisions or [],
        "errors": errors or [],
        "warnings": [],
        "created_at": "2026-04-21T00:00:00+00:00",
    }
    return env


def _fake_accept_result(
    proposal_id: str,
    proposal_type: str,
    status: str = "accepted",
    error: str | None = None,
) -> MagicMock:
    res = MagicMock()
    payload: dict = {
        "status": status,
        "proposal_id": proposal_id,
        "proposal_type": proposal_type,
    }
    if error:
        payload["error"] = error
    res.to_dict.return_value = payload
    return res


@pytest.fixture
def workspace(tmp_path):
    novel_id = "novel_p4_test"
    d = tmp_path / "novels" / novel_id
    d.mkdir(parents=True)
    # Minimal novel.json so _project_path is a real directory
    (d / "novel.json").write_text(
        json.dumps({"novel_id": novel_id, "title": "p4"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return tmp_path, novel_id


@pytest.fixture
def executor(workspace):
    ws, nid = workspace
    return AgentToolExecutor(str(ws), nid)


# ---------------------------------------------------------------------------
# TOOLS registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_all_propose_tools_registered(self):
        names = {t["name"] for t in TOOLS}
        for n in PROPOSE_TOOLS:
            assert n in names, f"missing propose tool: {n}"

    def test_accept_and_regenerate_registered(self):
        names = {t["name"] for t in TOOLS}
        assert "accept_proposal" in names
        assert "regenerate_section" in names

    def test_each_tool_has_executor_method(self):
        for n in PROPOSE_TOOLS + ("accept_proposal", "regenerate_section"):
            assert hasattr(AgentToolExecutor, f"_tool_{n}"), n

    def test_schema_fields_complete(self):
        """Each new tool must have name / description / parameters."""
        wanted = set(PROPOSE_TOOLS) | {"accept_proposal", "regenerate_section"}
        found = {}
        for t in TOOLS:
            if t["name"] in wanted:
                found[t["name"]] = t
        assert len(found) == len(wanted), (
            f"missing schema entries: {wanted - found.keys()}"
        )
        for name, schema in found.items():
            assert isinstance(schema.get("description"), str) and schema["description"], (
                f"{name} missing description"
            )
            assert schema["description"].strip() != "", f"{name} empty description"
            assert isinstance(schema.get("parameters"), dict), (
                f"{name} missing parameters dict"
            )

    def test_propose_project_setup_schema_has_inspiration(self):
        entry = next(t for t in TOOLS if t["name"] == "propose_project_setup")
        assert "inspiration" in entry["parameters"]
        assert entry["parameters"]["inspiration"]["type"] == "string"
        # hints is optional
        assert entry["parameters"]["hints"].get("optional") is True

    def test_propose_volume_outline_schema_has_volume_number(self):
        entry = next(t for t in TOOLS if t["name"] == "propose_volume_outline")
        assert "volume_number" in entry["parameters"]
        assert entry["parameters"]["volume_number"]["type"] == "integer"

    def test_propose_chapter_brief_schema_has_chapter_number(self):
        entry = next(t for t in TOOLS if t["name"] == "propose_chapter_brief")
        assert "chapter_number" in entry["parameters"]

    def test_accept_proposal_schema_fields(self):
        entry = next(t for t in TOOLS if t["name"] == "accept_proposal")
        params = entry["parameters"]
        assert "proposal_id" in params
        assert "proposal_type" in params
        assert "data" in params
        assert params["data"]["type"] == "object"

    def test_regenerate_section_schema_fields(self):
        entry = next(t for t in TOOLS if t["name"] == "regenerate_section")
        params = entry["parameters"]
        assert "section" in params
        assert "hints" in params
        # volume_number only needed for volume_outline
        assert params.get("volume_number", {}).get("optional") is True


# ---------------------------------------------------------------------------
# plan_chapters deprecation
# ---------------------------------------------------------------------------


class TestPlanChaptersDeprecated:
    def test_plan_chapters_description_contains_deprecated(self):
        entry = next(t for t in TOOLS if t["name"] == "plan_chapters")
        assert "[DEPRECATED]" in entry["description"]
        # Still recommends the replacement
        assert "propose_chapter_brief" in entry["description"]

    def test_plan_chapters_still_implemented(self):
        # Deprecated does NOT mean removed — the handler must still exist so
        # existing callers keep working through the one-version deprecation
        # window.
        assert hasattr(AgentToolExecutor, "_tool_plan_chapters")


# ---------------------------------------------------------------------------
# propose_* happy paths
# ---------------------------------------------------------------------------


class TestProposeHappyPaths:
    def test_propose_project_setup_calls_facade(self, executor):
        facade = MagicMock()
        facade.propose_project_setup.return_value = _fake_envelope(
            "project_setup", data={"genre": "玄幻", "target_words": 100000}
        )
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            result = executor.execute(
                "propose_project_setup",
                {"inspiration": "少年修炼逆天改命"},
            )
        facade.propose_project_setup.assert_called_once_with(
            inspiration="少年修炼逆天改命", hints=None
        )
        assert result["proposal_type"] == "project_setup"
        assert result["proposal_id"] == "pid-project_setup"
        assert result["data"]["genre"] == "玄幻"

    def test_propose_project_setup_forwards_hints(self, executor):
        facade = MagicMock()
        facade.propose_project_setup.return_value = _fake_envelope("project_setup")
        hints = {"genre": "科幻", "target_words": 200000}
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            executor.execute(
                "propose_project_setup",
                {"inspiration": "星辰大海", "hints": hints},
            )
        facade.propose_project_setup.assert_called_once_with(
            inspiration="星辰大海", hints=hints
        )

    def test_propose_synopsis_calls_facade(self, executor, workspace):
        ws, nid = workspace
        expected_path = str(Path(ws) / "novels" / nid)
        facade = MagicMock()
        facade.propose_synopsis.return_value = _fake_envelope(
            "synopsis", data={"synopsis": "主角踏上修仙路"}
        )
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            result = executor.execute("propose_synopsis", {})
        facade.propose_synopsis.assert_called_once_with(project_path=expected_path)
        assert result["proposal_type"] == "synopsis"
        assert result["data"]["synopsis"] == "主角踏上修仙路"

    def test_propose_main_outline_forwards_custom_ideas(self, executor):
        facade = MagicMock()
        facade.propose_main_outline.return_value = _fake_envelope(
            "main_outline", data={"outline": {}, "style_name": "wuxia.classical"}
        )
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            result = executor.execute(
                "propose_main_outline",
                {"custom_ideas": "主角要是个哑巴"},
            )
        call_kwargs = facade.propose_main_outline.call_args.kwargs
        assert call_kwargs["custom_ideas"] == "主角要是个哑巴"
        assert result["proposal_type"] == "main_outline"

    def test_propose_main_outline_without_custom_ideas(self, executor):
        facade = MagicMock()
        facade.propose_main_outline.return_value = _fake_envelope("main_outline")
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            executor.execute("propose_main_outline", {})
        call_kwargs = facade.propose_main_outline.call_args.kwargs
        assert call_kwargs["custom_ideas"] is None

    def test_propose_characters_forwards_synopsis(self, executor):
        facade = MagicMock()
        facade.propose_characters.return_value = _fake_envelope(
            "characters", data={"characters": [{"name": "林辰", "role": "主角"}]}
        )
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            result = executor.execute(
                "propose_characters",
                {"synopsis": "主角林辰踏上修炼路"},
            )
        facade.propose_characters.assert_called_once()
        assert facade.propose_characters.call_args.kwargs["synopsis"] == (
            "主角林辰踏上修炼路"
        )
        assert result["data"]["characters"][0]["name"] == "林辰"

    def test_propose_world_setting_without_synopsis(self, executor):
        facade = MagicMock()
        facade.propose_world_setting.return_value = _fake_envelope("world_setting")
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            executor.execute("propose_world_setting", {})
        assert facade.propose_world_setting.call_args.kwargs["synopsis"] is None

    def test_propose_story_arcs_zero_args(self, executor, workspace):
        ws, nid = workspace
        expected_path = str(Path(ws) / "novels" / nid)
        facade = MagicMock()
        facade.propose_story_arcs.return_value = _fake_envelope(
            "story_arcs", data={"arcs": [{"arc_id": "a1", "name": "主线"}]}
        )
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            result = executor.execute("propose_story_arcs", {})
        facade.propose_story_arcs.assert_called_once_with(
            project_path=expected_path
        )
        assert result["data"]["arcs"][0]["arc_id"] == "a1"

    def test_propose_volume_breakdown_forwards_synopsis(self, executor):
        facade = MagicMock()
        facade.propose_volume_breakdown.return_value = _fake_envelope(
            "volume_breakdown",
            data={"volumes": [{"volume_number": 1, "title": "卷一"}]},
        )
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            executor.execute(
                "propose_volume_breakdown", {"synopsis": "简短概要"}
            )
        assert facade.propose_volume_breakdown.call_args.kwargs["synopsis"] == (
            "简短概要"
        )

    def test_propose_volume_outline_coerces_volume_number(self, executor):
        facade = MagicMock()
        facade.propose_volume_outline.return_value = _fake_envelope(
            "volume_outline", data={"volume_number": 2}
        )
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            result = executor.execute(
                "propose_volume_outline", {"volume_number": "2"}
            )
        # Tool layer coerces string → int before passing to facade
        assert facade.propose_volume_outline.call_args.kwargs[
            "volume_number"
        ] == 2
        assert result["proposal_type"] == "volume_outline"

    def test_propose_chapter_brief_coerces_chapter_number(self, executor):
        facade = MagicMock()
        facade.propose_chapter_brief.return_value = _fake_envelope(
            "chapter_brief",
            data={"chapter_number": 5, "chapter_brief": {"main_conflict": "x"}},
        )
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            result = executor.execute(
                "propose_chapter_brief", {"chapter_number": "5"}
            )
        assert facade.propose_chapter_brief.call_args.kwargs[
            "chapter_number"
        ] == 5
        assert result["data"]["chapter_number"] == 5


# ---------------------------------------------------------------------------
# accept_proposal
# ---------------------------------------------------------------------------


class TestAcceptProposal:
    def test_happy_path(self, executor):
        facade = MagicMock()
        facade.accept_proposal.return_value = _fake_accept_result(
            "pid-1", "synopsis", status="accepted"
        )
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            result = executor.execute(
                "accept_proposal",
                {
                    "proposal_id": "pid-1",
                    "proposal_type": "synopsis",
                    "data": {"synopsis": "一句话主线"},
                },
            )
        facade.accept_proposal.assert_called_once()
        call_kwargs = facade.accept_proposal.call_args.kwargs
        assert call_kwargs["proposal_id"] == "pid-1"
        assert call_kwargs["proposal_type"] == "synopsis"
        assert call_kwargs["data"] == {"synopsis": "一句话主线"}
        assert result["status"] == "accepted"
        assert result["proposal_id"] == "pid-1"

    def test_already_accepted_idempotent(self, executor):
        facade = MagicMock()
        facade.accept_proposal.return_value = _fake_accept_result(
            "pid-1", "synopsis", status="already_accepted"
        )
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            result = executor.execute(
                "accept_proposal",
                {
                    "proposal_id": "pid-1",
                    "proposal_type": "synopsis",
                    "data": {"synopsis": "同样的内容"},
                },
            )
        assert result["status"] == "already_accepted"
        assert result["proposal_id"] == "pid-1"

    def test_missing_proposal_id(self, executor):
        result = executor.execute(
            "accept_proposal",
            {"proposal_id": "", "proposal_type": "synopsis", "data": {}},
        )
        assert "error" in result
        assert "proposal_id" in result["error"]

    def test_missing_proposal_type(self, executor):
        result = executor.execute(
            "accept_proposal",
            {"proposal_id": "pid-1", "proposal_type": "", "data": {}},
        )
        assert "error" in result
        assert "proposal_type" in result["error"]

    def test_invalid_data_type(self, executor):
        result = executor.execute(
            "accept_proposal",
            {
                "proposal_id": "pid-1",
                "proposal_type": "synopsis",
                "data": "not a dict",  # type: ignore[arg-type]
            },
        )
        assert "error" in result
        assert "data" in result["error"]


# ---------------------------------------------------------------------------
# regenerate_section
# ---------------------------------------------------------------------------


class TestRegenerateSection:
    def test_happy_path_synopsis(self, executor, workspace):
        ws, nid = workspace
        expected_path = str(Path(ws) / "novels" / nid)
        facade = MagicMock()
        facade.regenerate_section.return_value = _fake_envelope(
            "synopsis", data={"synopsis": "重写后的简介"}
        )
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            result = executor.execute(
                "regenerate_section",
                {"section": "synopsis", "hints": "更紧凑"},
            )
        facade.regenerate_section.assert_called_once_with(
            project_path=expected_path,
            section="synopsis",
            hints="更紧凑",
            volume_number=None,
        )
        assert result["proposal_type"] == "synopsis"
        assert result["data"]["synopsis"] == "重写后的简介"

    def test_volume_outline_with_volume_number(self, executor):
        facade = MagicMock()
        facade.regenerate_section.return_value = _fake_envelope("volume_outline")
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            executor.execute(
                "regenerate_section",
                {
                    "section": "volume_outline",
                    "hints": "要更悲壮",
                    "volume_number": 2,
                },
            )
        call_kwargs = facade.regenerate_section.call_args.kwargs
        assert call_kwargs["section"] == "volume_outline"
        assert call_kwargs["hints"] == "要更悲壮"
        assert call_kwargs["volume_number"] == 2

    def test_missing_section(self, executor):
        result = executor.execute("regenerate_section", {"section": ""})
        assert "error" in result
        assert "section" in result["error"]

    def test_hints_default_empty(self, executor):
        facade = MagicMock()
        facade.regenerate_section.return_value = _fake_envelope("characters")
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            executor.execute(
                "regenerate_section", {"section": "characters"}
            )
        # hints defaults to "" (not None), preserving facade signature contract
        assert facade.regenerate_section.call_args.kwargs["hints"] == ""
        assert facade.regenerate_section.call_args.kwargs["volume_number"] is None


# ---------------------------------------------------------------------------
# Facade error propagation — tools must not crash agent_chat loop
# ---------------------------------------------------------------------------


class TestFacadeErrorResilience:
    def test_propose_synopsis_facade_raises(self, executor):
        facade = MagicMock()
        facade.propose_synopsis.side_effect = RuntimeError("LLM quota exceeded")
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            result = executor.execute("propose_synopsis", {})
        assert "error" in result
        assert "LLM quota exceeded" in result["error"]

    def test_propose_main_outline_facade_raises(self, executor):
        facade = MagicMock()
        facade.propose_main_outline.side_effect = ValueError("invalid meta")
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            result = executor.execute("propose_main_outline", {})
        assert "error" in result
        assert "invalid meta" in result["error"]

    def test_accept_proposal_facade_raises(self, executor):
        facade = MagicMock()
        facade.accept_proposal.side_effect = RuntimeError("novel.json locked")
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            result = executor.execute(
                "accept_proposal",
                {
                    "proposal_id": "pid-1",
                    "proposal_type": "synopsis",
                    "data": {"synopsis": "x"},
                },
            )
        assert "error" in result
        assert "novel.json locked" in result["error"]

    def test_regenerate_section_facade_raises(self, executor):
        facade = MagicMock()
        facade.regenerate_section.side_effect = RuntimeError("down")
        with patch.object(executor, "_get_tool_facade", return_value=facade):
            result = executor.execute(
                "regenerate_section",
                {"section": "synopsis", "hints": ""},
            )
        assert "error" in result
        # execute() retries transient errors; "down" is not in the transient
        # keywords list so we expect a single propagation without retry.
        assert "down" in result["error"]

    def test_facade_import_failure_surfaces_as_error(self, executor):
        # Simulate facade module missing (E1 not merged yet on a fresh checkout)
        with patch.object(
            executor,
            "_get_tool_facade",
            side_effect=ImportError("No module named 'src.novel.services.tool_facade'"),
        ):
            result = executor.execute("propose_synopsis", {})
        assert "error" in result
        assert "tool_facade" in result["error"]


# ---------------------------------------------------------------------------
# _envelope_to_dict helper
# ---------------------------------------------------------------------------


class TestEnvelopeToDict:
    def test_passes_through_plain_dict(self, executor):
        out = executor._envelope_to_dict({"proposal_id": "x"})
        assert out == {"proposal_id": "x"}

    def test_calls_to_dict_on_dataclass_like(self, executor):
        env = MagicMock()
        env.to_dict.return_value = {"proposal_id": "y", "data": {}}
        out = executor._envelope_to_dict(env)
        assert out == {"proposal_id": "y", "data": {}}

    def test_fallback_on_broken_envelope(self, executor):
        # Object without to_dict should yield an error dict, not raise
        class Broken:
            def __str__(self) -> str:
                return "broken-repr"

        out = executor._envelope_to_dict(Broken())
        assert "error" in out
        assert "broken-repr" in out.get("raw", "")

    def test_to_dict_returning_non_dict_falls_back(self, executor):
        env = MagicMock()
        env.to_dict.return_value = "not a dict"
        out = executor._envelope_to_dict(env)
        assert "error" in out
