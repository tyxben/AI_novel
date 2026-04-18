"""ProjectArchitect 单元测试（Phase 2-γ）

覆盖：
    - 每个 propose_* 方法的 happy path（mock LLM）
    - regenerate_section 各 section 分支
    - LLM 返回非法 JSON / 空串 / 异常时的兜底
    - accept_into 把 proposal 正确写入 Novel-ish dict / 对象
    - propose_project_setup 在 hints 覆盖全部字段时跳过 LLM
    - _require_genre 无 genre 时直接抛 ValueError（Phase 0 约束）
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from src.novel.agents.project_architect import (
    ArcsProposal,
    CharactersProposal,
    ProjectArchitect,
    ProjectSetupProposal,
    SynopsisProposal,
    VolumeBreakdownProposal,
    WorldProposal,
)
from src.novel.models.character import (
    Appearance,
    CharacterArc,
    CharacterProfile,
    Personality,
)
from src.novel.models.world import WorldSetting


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake"
    usage: dict | None = None


def _fake_llm(json_payload: dict | None = None, error: Exception | None = None) -> MagicMock:
    llm = MagicMock()
    if error:
        llm.chat.side_effect = error
    elif json_payload is not None:
        llm.chat.return_value = FakeLLMResponse(
            content=json.dumps(json_payload, ensure_ascii=False)
        )
    else:
        llm.chat.return_value = FakeLLMResponse(content="{}")
    return llm


def _make_profile(name: str = "林辰", role: str = "主角") -> CharacterProfile:
    return CharacterProfile(
        name=name,
        role=role,
        age=18,
        gender="男",
        occupation="修士",
        appearance=Appearance(
            height="175cm",
            build="瘦削",
            hair="乌黑",
            eyes="幽深",
            clothing_style="素衣",
        ),
        personality=Personality(
            traits=["沉稳", "隐忍", "果决"],
            core_belief="守护至亲",
            motivation="报仇",
            flaw="偶尔冲动",
            speech_style="冷淡简短",
        ),
        character_arc=CharacterArc(
            initial_state="凡人少年",
            final_state="逆天强者",
            turning_points=[],
        ),
    )


# ---------------------------------------------------------------------------
# propose_project_setup
# ---------------------------------------------------------------------------


class TestProposeProjectSetup:
    def test_llm_happy_path(self):
        llm = _fake_llm({
            "genre": "玄幻",
            "theme": "少年修炼逆天改命",
            "style_name": "webnovel.xuanhuan",
            "target_length_class": "webnovel",
            "target_words": 500_000,
            "narrative_template": "cyclic_upgrade",
        })
        arch = ProjectArchitect(llm)
        proposal = arch.propose_project_setup("我想写一个少年修仙的故事")
        assert isinstance(proposal, ProjectSetupProposal)
        assert proposal.genre == "玄幻"
        assert proposal.target_words == 500_000
        assert proposal.narrative_template == "cyclic_upgrade"
        assert proposal.inspiration.startswith("我想写")

    def test_hints_fully_override_skips_llm(self):
        llm = _fake_llm()
        arch = ProjectArchitect(llm)
        proposal = arch.propose_project_setup(
            "",
            hints={
                "genre": "悬疑",
                "theme": "校园连环案",
                "target_length_class": "novella",
                "target_words": 80_000,
                "style_name": "literary.realism",
                "narrative_template": "multi_thread",
            },
        )
        assert proposal.genre == "悬疑"
        assert proposal.target_words == 80_000
        assert proposal.style_name == "literary.realism"
        # hints 全量时，LLM 不应被调用
        llm.chat.assert_not_called()

    def test_raises_when_no_inspiration_no_hint_genre(self):
        llm = _fake_llm()
        arch = ProjectArchitect(llm)
        with pytest.raises(ValueError, match="inspiration"):
            arch.propose_project_setup("", hints=None)

    def test_llm_garbage_then_raises_no_genre(self):
        # LLM 返回无 genre，且 hints 无 genre → 抛 ValueError
        llm = _fake_llm({"theme": "x"})
        arch = ProjectArchitect(llm)
        with pytest.raises(ValueError, match="genre"):
            arch.propose_project_setup("一些灵感")

    def test_accept_into_updates_meta_dict(self):
        proposal = ProjectSetupProposal(
            genre="玄幻",
            theme="t",
            style_name="s",
            target_length_class="novel",
            target_words=200_000,
            narrative_template="cyclic_upgrade",
        )
        meta: dict = {"existing": 1}
        proposal.accept_into(meta)
        assert meta["genre"] == "玄幻"
        assert meta["target_words"] == 200_000
        assert meta["existing"] == 1  # 保留原有字段


# ---------------------------------------------------------------------------
# propose_synopsis
# ---------------------------------------------------------------------------


class TestProposeSynopsis:
    def test_happy_path(self):
        payload = {
            "synopsis": "林辰身负家仇，苦修三年，终斩敌酋。",
            "main_storyline": {
                "protagonist": "林辰",
                "protagonist_goal": "为父报仇",
                "core_conflict": "敌酋强大",
                "character_arc": "从隐忍到爆发",
                "stakes": "家族覆灭",
                "theme_statement": "坚韧终能破局",
            },
        }
        llm = _fake_llm(payload)
        arch = ProjectArchitect(llm)
        result = arch.propose_synopsis({"genre": "玄幻", "theme": "复仇"})
        assert isinstance(result, SynopsisProposal)
        assert "林辰" in result.synopsis
        assert result.main_storyline["protagonist"] == "林辰"

    def test_requires_genre(self):
        llm = _fake_llm({})
        arch = ProjectArchitect(llm)
        with pytest.raises(ValueError, match="genre"):
            arch.propose_synopsis({"theme": "x"})

    def test_llm_returns_garbage_returns_empty(self):
        llm = _fake_llm()
        llm.chat.return_value = FakeLLMResponse(content="not json at all")
        arch = ProjectArchitect(llm)
        result = arch.propose_synopsis({"genre": "玄幻"})
        assert result.synopsis == ""
        assert result.main_storyline == {}

    def test_accept_into_dict(self):
        proposal = SynopsisProposal(
            synopsis="短短一句",
            main_storyline={"protagonist": "林辰"},
        )
        novel: dict = {}
        proposal.accept_into(novel)
        assert novel["synopsis"] == "短短一句"
        assert novel["outline"]["main_storyline"]["protagonist"] == "林辰"


# ---------------------------------------------------------------------------
# propose_main_characters
# ---------------------------------------------------------------------------


class TestProposeMainCharacters:
    def test_delegates_to_character_service(self):
        llm = _fake_llm()
        arch = ProjectArchitect(llm)
        arch._character_service.extract_characters = MagicMock(  # type: ignore[method-assign]
            return_value=[{"name": "林辰", "role": "主角"}, {"name": "苏瑶", "role": "爱情线"}]
        )
        arch._character_service.generate_profile = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda name, role, genre, context: _make_profile(name=name, role=role)
        )
        result = arch.propose_main_characters({"genre": "玄幻", "theme": "t"}, synopsis="林辰复仇")
        assert isinstance(result, CharactersProposal)
        assert len(result.characters) == 2
        assert result.characters[0].name == "林辰"

    def test_skips_invalid_entries(self):
        llm = _fake_llm()
        arch = ProjectArchitect(llm)
        arch._character_service.extract_characters = MagicMock(  # type: ignore[method-assign]
            return_value=[{"name": "", "role": "主角"}, {"name": "苏瑶", "role": "配角"}]
        )
        arch._character_service.generate_profile = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda name, role, genre, context: _make_profile(name=name, role=role)
        )
        result = arch.propose_main_characters({"genre": "玄幻"})
        # 空 name 被跳过
        assert len(result.characters) == 1
        assert result.characters[0].name == "苏瑶"

    def test_profile_error_is_logged_but_continues(self):
        llm = _fake_llm()
        arch = ProjectArchitect(llm)
        arch._character_service.extract_characters = MagicMock(  # type: ignore[method-assign]
            return_value=[{"name": "A", "role": "主角"}, {"name": "B", "role": "配角"}]
        )

        def _raising_profile(name, role, genre, context):
            if name == "A":
                raise RuntimeError("boom")
            return _make_profile(name=name, role=role)

        arch._character_service.generate_profile = MagicMock(side_effect=_raising_profile)  # type: ignore[method-assign]
        result = arch.propose_main_characters({"genre": "玄幻"})
        assert [c.name for c in result.characters] == ["B"]

    def test_extract_exception_non_fatal(self):
        llm = _fake_llm()
        arch = ProjectArchitect(llm)
        arch._character_service.extract_characters = MagicMock(side_effect=RuntimeError("x"))  # type: ignore[method-assign]
        result = arch.propose_main_characters({"genre": "玄幻"})
        assert result.characters == []

    def test_accept_into_dict(self):
        proposal = CharactersProposal(characters=[_make_profile("林辰", "主角")])
        novel: dict = {}
        proposal.accept_into(novel)
        assert isinstance(novel["characters"], list)
        assert novel["characters"][0]["name"] == "林辰"


# ---------------------------------------------------------------------------
# propose_world_setting
# ---------------------------------------------------------------------------


class TestProposeWorldSetting:
    def test_happy_path_with_power_system(self):
        llm = _fake_llm()
        arch = ProjectArchitect(llm)
        fake_world = WorldSetting(era="古代修仙", location="九州", rules=["不能飞行"])
        arch._world_service.create_world_setting = MagicMock(return_value=fake_world)  # type: ignore[method-assign]
        arch._world_service.define_power_system = MagicMock(return_value=None)  # type: ignore[method-assign]
        result = arch.propose_world_setting({"genre": "玄幻"})
        assert isinstance(result, WorldProposal)
        assert result.world.era == "古代修仙"
        arch._world_service.define_power_system.assert_called_once()

    def test_power_system_error_is_non_fatal(self):
        llm = _fake_llm()
        arch = ProjectArchitect(llm)
        fake_world = WorldSetting(era="现代", location="都市", rules=[])
        arch._world_service.create_world_setting = MagicMock(return_value=fake_world)  # type: ignore[method-assign]
        arch._world_service.define_power_system = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        result = arch.propose_world_setting({"genre": "都市"})
        assert result.world.era == "现代"  # still returns world

    def test_requires_genre(self):
        llm = _fake_llm()
        arch = ProjectArchitect(llm)
        with pytest.raises(ValueError, match="genre"):
            arch.propose_world_setting({})

    def test_accept_into_dict(self):
        proposal = WorldProposal(world=WorldSetting(era="x", location="y", rules=[]))
        novel: dict = {}
        proposal.accept_into(novel)
        assert novel["world_setting"]["era"] == "x"


# ---------------------------------------------------------------------------
# propose_story_arcs
# ---------------------------------------------------------------------------


class TestProposeStoryArcs:
    def test_returns_empty_when_outline_absent(self):
        llm = _fake_llm()
        arch = ProjectArchitect(llm)
        result = arch.propose_story_arcs({"genre": "玄幻"}, synopsis="s")
        assert isinstance(result, ArcsProposal)
        assert result.arcs == []

    def test_delegates_to_novel_director(self):
        llm = _fake_llm()
        arch = ProjectArchitect(llm)
        meta = {
            "genre": "玄幻",
            "outline": {
                "chapters": [{"chapter_number": 1}, {"chapter_number": 2}],
                "volumes": [{"volume_number": 1, "chapters": [1, 2]}],
            },
        }
        fake_arcs = [{"arc_id": "arc_1_1", "name": "新生", "chapters": [1, 2]}]
        with patch(
            "src.novel.agents.novel_director.NovelDirector"
        ) as MockDirector:
            MockDirector.return_value.generate_story_arcs.return_value = fake_arcs
            result = arch.propose_story_arcs(meta, synopsis="s")
        assert result.arcs == fake_arcs

    def test_director_exception_is_non_fatal(self):
        llm = _fake_llm()
        arch = ProjectArchitect(llm)
        meta = {
            "genre": "玄幻",
            "outline": {"chapters": [{"chapter_number": 1}]},
        }
        with patch(
            "src.novel.agents.novel_director.NovelDirector"
        ) as MockDirector:
            MockDirector.return_value.generate_story_arcs.side_effect = RuntimeError("x")
            result = arch.propose_story_arcs(meta, synopsis="")
        assert result.arcs == []

    def test_accept_into_dict(self):
        proposal = ArcsProposal(arcs=[{"arc_id": "a1"}])
        novel: dict = {"story_arcs": [{"arc_id": "a0"}]}
        proposal.accept_into(novel)
        assert [a["arc_id"] for a in novel["story_arcs"]] == ["a0", "a1"]


# ---------------------------------------------------------------------------
# propose_volume_breakdown
# ---------------------------------------------------------------------------


class TestProposeVolumeBreakdown:
    def test_happy_path(self):
        payload = {
            "volumes": [
                {
                    "volume_number": 1,
                    "title": "初登场",
                    "core_conflict": "出山",
                    "resolution": "立足",
                },
                {
                    "volume_number": 2,
                    "title": "历练",
                    "core_conflict": "苦修",
                    "resolution": "突破",
                },
            ]
        }
        llm = _fake_llm(payload)
        arch = ProjectArchitect(llm)
        result = arch.propose_volume_breakdown(
            {"genre": "玄幻", "target_words": 500_000}, synopsis="s", arcs=[]
        )
        assert isinstance(result, VolumeBreakdownProposal)
        assert len(result.volumes) == 2
        assert result.volumes[0]["title"] == "初登场"

    def test_llm_garbage_returns_empty(self):
        llm = _fake_llm()
        llm.chat.return_value = FakeLLMResponse(content="not json")
        arch = ProjectArchitect(llm)
        result = arch.propose_volume_breakdown(
            {"genre": "玄幻", "target_words": 100_000}, synopsis="s"
        )
        assert result.volumes == []

    def test_fills_missing_fields(self):
        payload = {"volumes": [{"title": ""}]}  # no volume_number/title
        llm = _fake_llm(payload)
        arch = ProjectArchitect(llm)
        result = arch.propose_volume_breakdown(
            {"genre": "玄幻", "target_words": 100_000}, synopsis="s"
        )
        assert len(result.volumes) == 1
        assert result.volumes[0]["volume_number"] == 1
        assert result.volumes[0]["title"] == "第1卷"

    def test_accept_into_dict(self):
        proposal = VolumeBreakdownProposal(
            volumes=[{"volume_number": 1, "title": "Volume one"}]
        )
        novel: dict = {"outline": {"existing_key": "keep"}}
        proposal.accept_into(novel)
        assert novel["outline"]["volumes"][0]["title"] == "Volume one"
        assert novel["outline"]["existing_key"] == "keep"


# ---------------------------------------------------------------------------
# regenerate_section
# ---------------------------------------------------------------------------


class TestRegenerateSection:
    @pytest.fixture
    def arch(self):
        llm = _fake_llm()
        return ProjectArchitect(llm)

    def test_synopsis(self, arch):
        arch.propose_synopsis = MagicMock(return_value=SynopsisProposal(synopsis="hi"))  # type: ignore[method-assign]
        result = arch.regenerate_section(
            "synopsis", {"meta": {"genre": "玄幻"}}, hints="更紧凑"
        )
        arch.propose_synopsis.assert_called_once()
        assert isinstance(result, SynopsisProposal)
        # hints 应注入 meta.custom_ideas
        call_meta = arch.propose_synopsis.call_args[0][0]
        assert "更紧凑" in call_meta["custom_ideas"]

    def test_characters(self, arch):
        arch.propose_main_characters = MagicMock(return_value=CharactersProposal())  # type: ignore[method-assign]
        arch.regenerate_section(
            "characters", {"meta": {"genre": "玄幻"}, "synopsis": "s"}, hints=""
        )
        arch.propose_main_characters.assert_called_once()

    def test_world(self, arch):
        arch.propose_world_setting = MagicMock(  # type: ignore[method-assign]
            return_value=WorldProposal(world=WorldSetting(era="x", location="y", rules=[]))
        )
        arch.regenerate_section(
            "world", {"meta": {"genre": "玄幻"}, "synopsis": "s"}, hints=""
        )
        arch.propose_world_setting.assert_called_once()

    def test_arcs(self, arch):
        arch.propose_story_arcs = MagicMock(return_value=ArcsProposal())  # type: ignore[method-assign]
        arch.regenerate_section(
            "arcs",
            {"meta": {"genre": "玄幻"}, "synopsis": "s", "characters": [], "world": {}},
            hints="",
        )
        arch.propose_story_arcs.assert_called_once()

    def test_volume_breakdown(self, arch):
        arch.propose_volume_breakdown = MagicMock(return_value=VolumeBreakdownProposal())  # type: ignore[method-assign]
        arch.regenerate_section(
            "volume_breakdown",
            {"meta": {"genre": "玄幻", "target_words": 100_000}, "synopsis": "s", "arcs": []},
            hints="",
        )
        arch.propose_volume_breakdown.assert_called_once()

    def test_unknown_section_raises(self, arch):
        with pytest.raises(ValueError, match="section"):
            arch.regenerate_section(
                "garbage", {"meta": {"genre": "玄幻"}}, hints=""  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# _retry_json_chat / LLM exception path
# ---------------------------------------------------------------------------


class TestLLMRetry:
    def test_all_attempts_fail_returns_none(self):
        llm = _fake_llm()
        llm.chat.side_effect = RuntimeError("timeout")
        arch = ProjectArchitect(llm)
        # synopsis wraps _retry_json_chat with no raise — returns empty proposal
        result = arch.propose_synopsis({"genre": "玄幻"})
        assert result.synopsis == ""
        assert llm.chat.call_count >= 1  # retried at least once
