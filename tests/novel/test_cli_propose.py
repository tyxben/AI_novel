"""CLI tests for the Phase 4 three-stage command group.

Covers `main.py novel propose <sub>` (9 subcommands), `novel accept`, and
`novel regenerate`. Also covers:
- ``--output json`` produces valid JSON on stdout
- ``--auto-accept`` triggers a second facade call
- ``--auto-accept`` is skipped when the envelope has errors
- ``--proposal-file`` loads proposal from disk for ``novel accept``
- boundary: missing/invalid options produce non-zero exit
- Facade exceptions surface as ``click.Abort``

The facade is mocked via ``src.novel.services.tool_facade.NovelToolFacade``
(patched at the import site used by ``main._make_facade``). This mirrors
the pattern used in ``tests/novel/test_cli_edit.py`` and keeps these tests
independent from E1's real implementation.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from main import cli


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeEnvelope:
    """Mirror of ``ProposalEnvelope.to_dict()`` shape."""

    def __init__(
        self,
        proposal_id: str = "env-1",
        proposal_type: str = "synopsis",
        project_path: str = "",
        data: dict | None = None,
        decisions: list | None = None,
        errors: list | None = None,
        warnings: list | None = None,
    ):
        self._d = {
            "proposal_id": proposal_id,
            "proposal_type": proposal_type,
            "project_path": project_path,
            "data": data if data is not None else {"synopsis": "demo"},
            "decisions": decisions or [],
            "errors": errors or [],
            "warnings": warnings or [],
            "created_at": "2026-04-21T00:00:00+00:00",
        }

    def to_dict(self) -> dict:
        return dict(self._d)


class _FakeAcceptResult:
    def __init__(
        self,
        status: str = "accepted",
        proposal_id: str = "env-1",
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


def _make_project(tmp_path: Path, novel_id: str = "novel_cli_test") -> Path:
    """Create a minimal novel project dir for Click's exists=True to pass."""
    project = tmp_path / "ws" / "novels" / novel_id
    project.mkdir(parents=True, exist_ok=True)
    (project / "novel.json").write_text(
        json.dumps(
            {"novel_id": novel_id, "title": "测试", "genre": "玄幻"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def facade_mock():
    """Patch ``_make_facade`` in main.py to return a mock facade instance."""
    mock = MagicMock()
    with patch("main._make_facade", return_value=mock) as _patched:
        yield mock


# ---------------------------------------------------------------------------
# novel propose project-setup
# ---------------------------------------------------------------------------


class TestProjectSetupCmd:
    def test_happy_default_table(self, runner, facade_mock):
        facade_mock.propose_project_setup.return_value = _FakeEnvelope(
            proposal_type="project_setup",
            data={"genre": "玄幻", "target_words": 80000},
        )

        result = runner.invoke(
            cli,
            [
                "novel", "propose", "project-setup", "少年逆天改命",
                "--genre", "玄幻",
                "--target-words", "80000",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "project_setup" in result.output
        # hints dict must carry our overrides
        kw = facade_mock.propose_project_setup.call_args.kwargs
        assert kw["inspiration"] == "少年逆天改命"
        assert kw["hints"] == {"genre": "玄幻", "target_words": 80000}

    def test_output_json_is_valid_json(self, runner, facade_mock):
        facade_mock.propose_project_setup.return_value = _FakeEnvelope(
            proposal_type="project_setup",
            data={"genre": "玄幻"},
        )

        result = runner.invoke(
            cli,
            [
                "novel", "propose", "project-setup", "一句灵感",
                "--output", "json",
            ],
        )

        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert parsed["proposal_type"] == "project_setup"
        assert parsed["data"]["genre"] == "玄幻"

    def test_no_hints_passes_none(self, runner, facade_mock):
        facade_mock.propose_project_setup.return_value = _FakeEnvelope(
            proposal_type="project_setup"
        )
        result = runner.invoke(
            cli, ["novel", "propose", "project-setup", "inspiration"]
        )
        assert result.exit_code == 0
        assert facade_mock.propose_project_setup.call_args.kwargs["hints"] is None


# ---------------------------------------------------------------------------
# novel propose synopsis
# ---------------------------------------------------------------------------


class TestSynopsisCmd:
    def test_happy(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        facade_mock.propose_synopsis.return_value = _FakeEnvelope(
            proposal_type="synopsis",
            data={"synopsis": "故事梗概"},
        )

        result = runner.invoke(
            cli, ["novel", "propose", "synopsis", str(project)]
        )

        assert result.exit_code == 0, result.output
        # Envelope fields visible in the table
        assert "synopsis" in result.output
        assert "env-1" in result.output
        args = facade_mock.propose_synopsis.call_args.args
        assert args[0] == str(project)

    def test_nonexistent_project(self, runner, facade_mock, tmp_path):
        result = runner.invoke(
            cli,
            [
                "novel", "propose", "synopsis",
                str(tmp_path / "does_not_exist"),
            ],
        )
        assert result.exit_code != 0
        facade_mock.propose_synopsis.assert_not_called()

    def test_auto_accept_triggers_second_call(
        self, runner, facade_mock, tmp_path
    ):
        project = _make_project(tmp_path)
        facade_mock.propose_synopsis.return_value = _FakeEnvelope(
            proposal_id="xy-9",
            proposal_type="synopsis",
            data={"synopsis": "demo"},
        )
        facade_mock.accept_proposal.return_value = _FakeAcceptResult(
            status="accepted",
            proposal_id="xy-9",
            proposal_type="synopsis",
            changelog_id="log-5",
        )

        result = runner.invoke(
            cli,
            [
                "novel", "propose", "synopsis", str(project),
                "--auto-accept",
            ],
        )

        assert result.exit_code == 0, result.output
        assert facade_mock.propose_synopsis.call_count == 1
        assert facade_mock.accept_proposal.call_count == 1
        accept_args = facade_mock.accept_proposal.call_args.args
        assert accept_args[1] == "xy-9"      # proposal_id
        assert accept_args[2] == "synopsis"  # proposal_type
        assert accept_args[3] == {"synopsis": "demo"}  # data
        assert "accepted" in result.output
        assert "log-5" in result.output

    def test_auto_accept_skipped_when_errors_present(
        self, runner, facade_mock, tmp_path
    ):
        project = _make_project(tmp_path)
        facade_mock.propose_synopsis.return_value = _FakeEnvelope(
            proposal_type="synopsis",
            errors=[{"message": "LLM returned garbage"}],
        )

        result = runner.invoke(
            cli,
            [
                "novel", "propose", "synopsis", str(project),
                "--auto-accept",
            ],
        )

        assert result.exit_code == 0, result.output
        assert facade_mock.propose_synopsis.call_count == 1
        facade_mock.accept_proposal.assert_not_called()
        assert "跳过" in result.output or "skipped" in result.output.lower()

    def test_facade_exception_aborts(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        facade_mock.propose_synopsis.side_effect = RuntimeError("LLM timeout")

        result = runner.invoke(
            cli, ["novel", "propose", "synopsis", str(project)]
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# novel propose main-outline
# ---------------------------------------------------------------------------


class TestMainOutlineCmd:
    def test_with_custom_ideas(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        facade_mock.propose_main_outline.return_value = _FakeEnvelope(
            proposal_type="main_outline",
            data={"outline": {"premise": "p"}},
        )

        result = runner.invoke(
            cli,
            [
                "novel", "propose", "main-outline", str(project),
                "--custom-ideas", "要多情感",
            ],
        )

        assert result.exit_code == 0, result.output
        kw = facade_mock.propose_main_outline.call_args.kwargs
        assert kw["custom_ideas"] == "要多情感"


# ---------------------------------------------------------------------------
# novel propose characters / world-setting
# ---------------------------------------------------------------------------


class TestCharactersCmd:
    def test_happy_with_inline_synopsis(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        facade_mock.propose_characters.return_value = _FakeEnvelope(
            proposal_type="characters",
            data={"characters": [{"name": "张三"}]},
        )

        result = runner.invoke(
            cli,
            [
                "novel", "propose", "characters", str(project),
                "--synopsis", "ctx",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "张三" in result.output or "characters" in result.output
        assert facade_mock.propose_characters.call_args.kwargs["synopsis"] == "ctx"

    def test_synopsis_file_is_read(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        synopsis_file = tmp_path / "syn.txt"
        synopsis_file.write_text("file content", encoding="utf-8")
        facade_mock.propose_characters.return_value = _FakeEnvelope(
            proposal_type="characters"
        )

        result = runner.invoke(
            cli,
            [
                "novel", "propose", "characters", str(project),
                "--synopsis-file", str(synopsis_file),
            ],
        )

        assert result.exit_code == 0, result.output
        assert (
            facade_mock.propose_characters.call_args.kwargs["synopsis"]
            == "file content"
        )


class TestWorldSettingCmd:
    def test_happy(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        facade_mock.propose_world_setting.return_value = _FakeEnvelope(
            proposal_type="world_setting",
            data={"world_setting": {"era": "古代"}},
        )

        result = runner.invoke(
            cli,
            ["novel", "propose", "world-setting", str(project)],
        )

        assert result.exit_code == 0, result.output
        assert "world_setting" in result.output


# ---------------------------------------------------------------------------
# novel propose story-arcs / volume-breakdown / volume-outline / chapter-brief
# ---------------------------------------------------------------------------


class TestStoryArcsCmd:
    def test_happy(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        facade_mock.propose_story_arcs.return_value = _FakeEnvelope(
            proposal_type="story_arcs",
            data={"arcs": [{"name": "主弧"}]},
        )

        result = runner.invoke(
            cli, ["novel", "propose", "story-arcs", str(project)]
        )

        assert result.exit_code == 0, result.output
        assert "story_arcs" in result.output


class TestVolumeBreakdownCmd:
    def test_happy(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        facade_mock.propose_volume_breakdown.return_value = _FakeEnvelope(
            proposal_type="volume_breakdown",
            data={"volumes": [{"number": 1}]},
        )

        result = runner.invoke(
            cli, ["novel", "propose", "volume-breakdown", str(project)]
        )

        assert result.exit_code == 0, result.output
        assert "volume_breakdown" in result.output


class TestVolumeOutlineCmd:
    def test_happy(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        facade_mock.propose_volume_outline.return_value = _FakeEnvelope(
            proposal_type="volume_outline",
            data={"chapters": []},
        )

        result = runner.invoke(
            cli,
            [
                "novel", "propose", "volume-outline", str(project),
                "--volume", "2",
            ],
        )

        assert result.exit_code == 0, result.output
        args = facade_mock.propose_volume_outline.call_args.args
        assert args[1] == 2

    def test_missing_volume_fails(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)

        result = runner.invoke(
            cli, ["novel", "propose", "volume-outline", str(project)]
        )
        assert result.exit_code != 0
        facade_mock.propose_volume_outline.assert_not_called()


class TestChapterBriefCmd:
    def test_happy(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        facade_mock.propose_chapter_brief.return_value = _FakeEnvelope(
            proposal_type="chapter_brief",
            data={"chapter_number": 5, "goal": "g"},
        )

        result = runner.invoke(
            cli,
            [
                "novel", "propose", "chapter-brief", str(project),
                "--chapter", "5",
            ],
        )

        assert result.exit_code == 0, result.output
        args = facade_mock.propose_chapter_brief.call_args.args
        assert args[1] == 5


# ---------------------------------------------------------------------------
# novel accept
# ---------------------------------------------------------------------------


class TestAcceptCmd:
    def test_accept_via_proposal_file(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        envelope = {
            "proposal_id": "abc",
            "proposal_type": "synopsis",
            "data": {"synopsis": "text"},
        }
        prop_file = tmp_path / "prop.json"
        prop_file.write_text(
            json.dumps(envelope, ensure_ascii=False), encoding="utf-8"
        )

        facade_mock.accept_proposal.return_value = _FakeAcceptResult(
            status="accepted",
            proposal_id="abc",
            proposal_type="synopsis",
        )

        result = runner.invoke(
            cli,
            [
                "novel", "accept", str(project),
                "--proposal-file", str(prop_file),
            ],
        )

        assert result.exit_code == 0, result.output
        assert "accepted" in result.output
        accept_args = facade_mock.accept_proposal.call_args.args
        assert accept_args[1] == "abc"
        assert accept_args[2] == "synopsis"
        assert accept_args[3] == {"synopsis": "text"}

    def test_accept_via_manual_flags(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        data_file = tmp_path / "data.json"
        data_file.write_text(json.dumps({"a": 1}), encoding="utf-8")

        facade_mock.accept_proposal.return_value = _FakeAcceptResult(
            status="accepted",
            proposal_id="xxx",
            proposal_type="characters",
        )

        result = runner.invoke(
            cli,
            [
                "novel", "accept", str(project),
                "--proposal-id", "xxx",
                "--type", "characters",
                "--data-file", str(data_file),
            ],
        )

        assert result.exit_code == 0, result.output
        accept_args = facade_mock.accept_proposal.call_args.args
        assert accept_args[1] == "xxx"
        assert accept_args[2] == "characters"
        assert accept_args[3] == {"a": 1}

    def test_accept_missing_inputs_aborts(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)

        result = runner.invoke(
            cli, ["novel", "accept", str(project)]
        )
        assert result.exit_code != 0
        facade_mock.accept_proposal.assert_not_called()

    def test_accept_proposal_file_not_json_aborts(
        self, runner, facade_mock, tmp_path
    ):
        """L2：proposal 文件不是合法 JSON → UsageError 非零退出。"""
        project = _make_project(tmp_path)
        bad = tmp_path / "bad.json"
        bad.write_text("not a json blob {", encoding="utf-8")
        result = runner.invoke(
            cli,
            [
                "novel", "accept", str(project),
                "--proposal-file", str(bad),
            ],
        )
        assert result.exit_code != 0
        assert "不是合法 JSON" in result.output
        facade_mock.accept_proposal.assert_not_called()

    def test_accept_proposal_file_is_list_aborts(
        self, runner, facade_mock, tmp_path
    ):
        """L2：proposal 文件 JSON 但不是 object（是 list）→ UsageError。"""
        project = _make_project(tmp_path)
        bad = tmp_path / "list.json"
        bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        result = runner.invoke(
            cli,
            [
                "novel", "accept", str(project),
                "--proposal-file", str(bad),
            ],
        )
        assert result.exit_code != 0
        assert "JSON object" in result.output or "dict" in result.output
        facade_mock.accept_proposal.assert_not_called()

    def test_accept_proposal_file_missing_proposal_id_aborts(
        self, runner, facade_mock, tmp_path
    ):
        """L2：proposal file 缺 proposal_id 字段 → UsageError。"""
        project = _make_project(tmp_path)
        bad = tmp_path / "no_pid.json"
        bad.write_text(
            json.dumps({"proposal_type": "synopsis", "data": {}}),
            encoding="utf-8",
        )
        result = runner.invoke(
            cli,
            [
                "novel", "accept", str(project),
                "--proposal-file", str(bad),
            ],
        )
        assert result.exit_code != 0
        assert "proposal_id" in result.output
        facade_mock.accept_proposal.assert_not_called()

    def test_accept_proposal_file_missing_proposal_type_aborts(
        self, runner, facade_mock, tmp_path
    ):
        """L2：proposal file 缺 proposal_type 字段 → UsageError。"""
        project = _make_project(tmp_path)
        bad = tmp_path / "no_ptype.json"
        bad.write_text(
            json.dumps({"proposal_id": "abc", "data": {}}),
            encoding="utf-8",
        )
        result = runner.invoke(
            cli,
            [
                "novel", "accept", str(project),
                "--proposal-file", str(bad),
            ],
        )
        assert result.exit_code != 0
        assert "proposal_type" in result.output
        facade_mock.accept_proposal.assert_not_called()

    def test_accept_proposal_file_data_not_dict_aborts(
        self, runner, facade_mock, tmp_path
    ):
        """L2：proposal file 的 data 字段不是 dict → UsageError。"""
        project = _make_project(tmp_path)
        bad = tmp_path / "bad_data.json"
        bad.write_text(
            json.dumps({
                "proposal_id": "abc",
                "proposal_type": "synopsis",
                "data": [1, 2, 3],
            }),
            encoding="utf-8",
        )
        result = runner.invoke(
            cli,
            [
                "novel", "accept", str(project),
                "--proposal-file", str(bad),
            ],
        )
        assert result.exit_code != 0
        assert "JSON object" in result.output or "data" in result.output
        facade_mock.accept_proposal.assert_not_called()

    def test_accept_output_json(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        envelope = {
            "proposal_id": "jj",
            "proposal_type": "world_setting",
            "data": {"world_setting": {"era": "x"}},
        }
        prop_file = tmp_path / "p.json"
        prop_file.write_text(json.dumps(envelope), encoding="utf-8")

        facade_mock.accept_proposal.return_value = _FakeAcceptResult(
            status="accepted",
            proposal_id="jj",
            proposal_type="world_setting",
            changelog_id="cl-1",
        )

        result = runner.invoke(
            cli,
            [
                "novel", "accept", str(project),
                "--proposal-file", str(prop_file),
                "--output", "json",
            ],
        )

        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert parsed["status"] == "accepted"
        assert parsed["proposal_id"] == "jj"
        assert parsed["changelog_id"] == "cl-1"


# ---------------------------------------------------------------------------
# novel regenerate
# ---------------------------------------------------------------------------


class TestRegenerateCmd:
    def test_happy_synopsis(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        facade_mock.regenerate_section.return_value = _FakeEnvelope(
            proposal_id="regen-1",
            proposal_type="synopsis",
            data={"synopsis": "v2"},
        )

        result = runner.invoke(
            cli,
            [
                "novel", "regenerate", str(project),
                "--section", "synopsis",
                "--hints", "换主角性别",
            ],
        )

        assert result.exit_code == 0, result.output
        kw = facade_mock.regenerate_section.call_args.kwargs
        assert kw["section"] == "synopsis"
        assert kw["hints"] == "换主角性别"
        assert kw["volume_number"] is None

    def test_volume_outline_requires_volume_number(
        self, runner, facade_mock, tmp_path
    ):
        project = _make_project(tmp_path)
        facade_mock.regenerate_section.return_value = _FakeEnvelope(
            proposal_type="volume_outline"
        )

        result = runner.invoke(
            cli,
            [
                "novel", "regenerate", str(project),
                "--section", "volume_outline",
                "--hints", "节奏紧凑",
                "--volume", "2",
            ],
        )

        assert result.exit_code == 0, result.output
        assert (
            facade_mock.regenerate_section.call_args.kwargs["volume_number"]
            == 2
        )

    def test_missing_section_fails(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        result = runner.invoke(
            cli, ["novel", "regenerate", str(project)]
        )
        assert result.exit_code != 0
        facade_mock.regenerate_section.assert_not_called()

    def test_facade_exception_aborts(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        facade_mock.regenerate_section.side_effect = RuntimeError("boom")

        result = runner.invoke(
            cli,
            [
                "novel", "regenerate", str(project),
                "--section", "synopsis",
            ],
        )
        assert result.exit_code != 0

    def test_output_json(self, runner, facade_mock, tmp_path):
        project = _make_project(tmp_path)
        facade_mock.regenerate_section.return_value = _FakeEnvelope(
            proposal_id="regen-j",
            proposal_type="synopsis",
            data={"synopsis": "x"},
        )

        result = runner.invoke(
            cli,
            [
                "novel", "regenerate", str(project),
                "--section", "synopsis",
                "--output", "json",
            ],
        )

        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert parsed["proposal_id"] == "regen-j"


# ---------------------------------------------------------------------------
# Help / discoverability
# ---------------------------------------------------------------------------


class TestCLIDiscoverability:
    def test_all_nine_propose_subcommands_visible(self, runner):
        result = runner.invoke(cli, ["novel", "propose", "--help"])
        assert result.exit_code == 0
        out = result.output
        for name in (
            "project-setup",
            "synopsis",
            "main-outline",
            "characters",
            "world-setting",
            "story-arcs",
            "volume-breakdown",
            "volume-outline",
            "chapter-brief",
        ):
            assert name in out, f"subcommand {name} missing from help"

    def test_accept_command_registered(self, runner):
        result = runner.invoke(cli, ["novel", "accept", "--help"])
        assert result.exit_code == 0
        assert "proposal-file" in result.output
        assert "proposal-id" in result.output

    def test_regenerate_command_registered(self, runner):
        result = runner.invoke(cli, ["novel", "regenerate", "--help"])
        assert result.exit_code == 0
        assert "section" in result.output
        assert "hints" in result.output
