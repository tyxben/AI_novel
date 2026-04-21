"""Unit tests for ``src.novel.services.tool_facade.NovelToolFacade``.

覆盖：
* propose_* × 9 方法 happy path（mock Agent）
* propose_* 错误路径：project 不存在 / novel_id 非法
* accept 幂等 + dispatch × 9 proposal_type
* accept 未知 proposal_type 抛 ValueError
* accept project 不存在 / project_setup 的 NotImplemented 策略
* regenerate 各 section dispatch + 不支持的 section 抛错
* _extract_novel_id 路径解析（绝对/相对/末尾斜杠）
* ProposalEnvelope / AcceptResult.to_dict() 序列化

Mock 模式：
- FileManager 用 MagicMock 替换
- ProjectArchitect / VolumeDirector / ChapterPlanner 用 MagicMock 注入
- create_llm_client 通过 patch facade 的 _create_llm_from_cfg seam 隔离
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.novel.models.character import (
    Appearance,
    CharacterArc,
    CharacterProfile,
    Personality,
)
from src.novel.models.chapter_brief import (
    ChapterBrief,
    ChapterBriefProposal,
)
from src.novel.models.world import WorldSetting
from src.novel.agents.project_architect import (
    ArcsProposal,
    CharactersProposal,
    MainOutlineProposal,
    ProjectSetupProposal,
    SynopsisProposal,
    VolumeBreakdownProposal,
    WorldProposal,
)
from src.novel.agents.volume_director import VolumeOutlineProposal
from src.novel.services.tool_facade import (
    AcceptResult,
    NovelToolFacade,
    ProposalEnvelope,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _minimal_world() -> WorldSetting:
    return WorldSetting(
        era="修仙时代",
        location="青云大陆",
        rules=["灵气复苏"],
        terminology={"修士": "修炼者"},
    )


def _novel_data_stub(
    genre: str = "玄幻",
    theme: str = "少年逆天",
    target_words: int = 100_000,
    with_outline: bool = False,
    with_volumes: bool = False,
    with_chapters: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "novel_id": "novel_xyz",
        "title": "测试小说",
        "genre": genre,
        "theme": theme,
        "target_words": target_words,
        "style_name": "webnovel.shuangwen",
        "template": "cyclic_upgrade",
        "synopsis": "一个少年从凡人到强者的修炼故事",
        "characters": [],
        "world_setting": {},
        "story_arcs": [],
        "config": {"llm": {"provider": "openai"}},
    }
    if with_outline:
        data["outline"] = {
            "template": "cyclic_upgrade",
            "main_storyline": {"protagonist": "林辰"},
            "acts": [],
            "volumes": [],
            "chapters": [],
        }
    if with_volumes and with_outline:
        data["outline"]["volumes"] = [
            {
                "volume_number": 1,
                "title": "第一卷",
                "core_conflict": "入门",
                "resolution": "站稳",
                "chapters": [1, 2, 3],
            }
        ]
    if with_chapters and with_outline:
        data["outline"]["chapters"] = [
            {
                "chapter_number": 1,
                "title": "第1章",
                "goal": "开场",
                "key_events": ["主角登场"],
                "estimated_words": 2500,
                "chapter_type": "setup",
                "mood": "蓄力",
                "chapter_brief": {},
            },
            {
                "chapter_number": 2,
                "title": "第2章",
                "goal": "冲突",
                "key_events": ["遇到反派"],
                "estimated_words": 2500,
                "chapter_type": "buildup",
                "mood": "蓄力",
                "chapter_brief": {},
            },
        ]
    return data


@pytest.fixture
def facade(tmp_path) -> NovelToolFacade:
    """Create a facade with an in-memory mock FileManager."""
    f = NovelToolFacade(workspace=str(tmp_path))
    f._fm = MagicMock()
    # 默认返回 None，测试按需覆盖
    f._fm.load_novel.return_value = None
    # 默认 create_llm patched 成 MagicMock
    f._create_llm_from_cfg = MagicMock(return_value=MagicMock())  # type: ignore[assignment]
    return f


# ---------------------------------------------------------------------------
# ProposalEnvelope / AcceptResult basics
# ---------------------------------------------------------------------------


class TestEnvelopeSerialization:
    def test_proposal_envelope_to_dict_has_all_fields(self):
        env = ProposalEnvelope(
            proposal_type="synopsis",
            project_path="/tmp/foo",
            data={"synopsis": "x"},
            decisions=[{"a": 1}],
            errors=[{"e": 2}],
            warnings=["w"],
        )
        d = env.to_dict()
        assert d["proposal_type"] == "synopsis"
        assert d["project_path"] == "/tmp/foo"
        assert d["data"] == {"synopsis": "x"}
        assert d["decisions"] == [{"a": 1}]
        assert d["errors"] == [{"e": 2}]
        assert d["warnings"] == ["w"]
        assert "proposal_id" in d and len(d["proposal_id"]) > 0
        assert "created_at" in d and "T" in d["created_at"]

    def test_proposal_envelope_default_factories_generate_uuid_and_ts(self):
        a = ProposalEnvelope()
        b = ProposalEnvelope()
        assert a.proposal_id != b.proposal_id
        assert a.created_at and b.created_at

    def test_accept_result_accepted_to_dict(self):
        r = AcceptResult(
            status="accepted",
            proposal_id="pid-1",
            proposal_type="synopsis",
            changelog_id="ch-1",
        )
        d = r.to_dict()
        assert d == {
            "status": "accepted",
            "proposal_id": "pid-1",
            "proposal_type": "synopsis",
            "changelog_id": "ch-1",
        }

    def test_accept_result_already_accepted_omits_error_field(self):
        r = AcceptResult(
            status="already_accepted",
            proposal_id="pid-1",
            proposal_type="synopsis",
        )
        d = r.to_dict()
        assert "error" not in d
        assert "changelog_id" not in d
        assert d["status"] == "already_accepted"

    def test_accept_result_failed_includes_error(self):
        r = AcceptResult(
            status="failed",
            proposal_id="pid-1",
            proposal_type="synopsis",
            error="boom",
        )
        d = r.to_dict()
        assert d["status"] == "failed"
        assert d["error"] == "boom"


# ---------------------------------------------------------------------------
# _extract_novel_id
# ---------------------------------------------------------------------------


class TestExtractNovelId:
    def test_relative_path(self):
        assert (
            NovelToolFacade._extract_novel_id("workspace/novels/novel_abc")
            == "novel_abc"
        )

    def test_absolute_path(self):
        assert (
            NovelToolFacade._extract_novel_id("/tmp/ws/novels/novel_abc")
            == "novel_abc"
        )

    def test_trailing_slash(self):
        assert (
            NovelToolFacade._extract_novel_id("workspace/novels/novel_abc/")
            == "novel_abc"
        )

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            NovelToolFacade._extract_novel_id("")

    def test_dot_raises(self):
        with pytest.raises(ValueError):
            NovelToolFacade._extract_novel_id(".")

    def test_double_dot_raises(self):
        with pytest.raises(ValueError):
            NovelToolFacade._extract_novel_id("..")


# ---------------------------------------------------------------------------
# propose_project_setup
# ---------------------------------------------------------------------------


class TestProposeProjectSetup:
    def test_happy_path(self, facade):
        fake_proposal = ProjectSetupProposal(
            genre="玄幻",
            theme="少年修炼",
            style_name="webnovel.xuanhuan",
            target_length_class="webnovel",
            target_words=500_000,
            narrative_template="cyclic_upgrade",
            inspiration="我想写少年修仙",
        )
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            pa_cls.return_value.propose_project_setup.return_value = fake_proposal
            env = facade.propose_project_setup("我想写少年修仙")
        assert env.proposal_type == "project_setup"
        assert env.project_path == ""
        assert env.data["genre"] == "玄幻"
        assert env.data["target_words"] == 500_000
        assert env.errors == []

    def test_exception_returns_errors(self, facade):
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            pa_cls.return_value.propose_project_setup.side_effect = RuntimeError("boom")
            env = facade.propose_project_setup("")
        assert env.proposal_type == "project_setup"
        assert env.errors and "boom" in env.errors[0]["message"]


# ---------------------------------------------------------------------------
# propose_synopsis / propose_characters / propose_world_setting /
# propose_story_arcs / propose_volume_breakdown
# ---------------------------------------------------------------------------


class TestProposeViaProjectArchitect:
    def test_synopsis_happy_path(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub()
        fake = SynopsisProposal(
            synopsis="主线三句话", main_storyline={"protagonist": "林辰"}
        )
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            pa_cls.return_value.propose_synopsis.return_value = fake
            env = facade.propose_synopsis("workspace/novels/novel_xyz")
        assert env.proposal_type == "synopsis"
        assert env.project_path.endswith("novel_xyz")
        assert env.data["synopsis"] == "主线三句话"
        # 校验 meta 透传给 Agent
        call_meta = pa_cls.return_value.propose_synopsis.call_args.args[0]
        assert call_meta["genre"] == "玄幻"
        assert call_meta["theme"] == "少年逆天"

    def test_synopsis_project_missing(self, facade):
        facade._fm.load_novel.return_value = None
        env = facade.propose_synopsis("workspace/novels/novel_missing")
        assert env.proposal_type == "synopsis"
        assert env.errors
        assert "不存在" in env.errors[0]["message"]

    def test_synopsis_agent_raises_wrapped_in_errors(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub()
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            pa_cls.return_value.propose_synopsis.side_effect = RuntimeError("llm down")
            env = facade.propose_synopsis("workspace/novels/novel_xyz")
        assert env.errors and "llm down" in env.errors[0]["message"]

    def test_characters_maps_to_propose_main_characters(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub()
        fake = CharactersProposal(characters=[_make_profile()])
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            pa_cls.return_value.propose_main_characters.return_value = fake
            env = facade.propose_characters("workspace/novels/novel_xyz")
        assert env.proposal_type == "characters"
        assert len(env.data["characters"]) == 1
        assert env.data["characters"][0]["name"] == "林辰"
        pa_cls.return_value.propose_main_characters.assert_called_once()

    def test_characters_synopsis_override(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub()
        fake = CharactersProposal(characters=[])
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            pa_cls.return_value.propose_main_characters.return_value = fake
            facade.propose_characters(
                "workspace/novels/novel_xyz", synopsis="自定义摘要"
            )
        call = pa_cls.return_value.propose_main_characters.call_args
        # synopsis 以 kwarg 或 positional 传递，两种都支持
        synopsis_arg = call.kwargs.get("synopsis")
        if synopsis_arg is None:
            # positional
            synopsis_arg = call.args[1] if len(call.args) > 1 else None
        assert synopsis_arg == "自定义摘要"

    def test_world_setting_happy_path(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub()
        fake = WorldProposal(world=_minimal_world())
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            pa_cls.return_value.propose_world_setting.return_value = fake
            env = facade.propose_world_setting("workspace/novels/novel_xyz")
        assert env.proposal_type == "world_setting"
        assert env.data["world_setting"]["era"] == "修仙时代"

    def test_story_arcs_passes_outline_through_meta(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub(
            with_outline=True, with_chapters=True
        )
        fake = ArcsProposal(arcs=[{"arc_id": "arc_1_1", "name": "新生"}])
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            pa_cls.return_value.propose_story_arcs.return_value = fake
            env = facade.propose_story_arcs("workspace/novels/novel_xyz")
        assert env.proposal_type == "story_arcs"
        assert env.data["arcs"] == [{"arc_id": "arc_1_1", "name": "新生"}]
        # meta 应含 outline
        meta_arg = pa_cls.return_value.propose_story_arcs.call_args.args[0]
        assert "outline" in meta_arg

    def test_volume_breakdown_happy_path(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub()
        fake = VolumeBreakdownProposal(
            volumes=[
                {
                    "volume_number": 1,
                    "title": "第一卷",
                    "core_conflict": "入门",
                    "resolution": "站稳",
                }
            ]
        )
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            pa_cls.return_value.propose_volume_breakdown.return_value = fake
            env = facade.propose_volume_breakdown("workspace/novels/novel_xyz")
        assert env.proposal_type == "volume_breakdown"
        assert len(env.data["volumes"]) == 1

    def test_main_outline_passes_project_fields(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub()
        fake = MainOutlineProposal(
            outline={"template": "cyclic_upgrade", "chapters": []},
            template="cyclic_upgrade",
            style_name="webnovel.xuanhuan",
            total_chapters=40,
            decisions=[{"agent": "ProjectArchitect", "step": "outline"}],
            errors=[],
        )
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            pa_cls.return_value.propose_main_outline.return_value = fake
            env = facade.propose_main_outline(
                "workspace/novels/novel_xyz", custom_ideas="多线叙事"
            )
        assert env.proposal_type == "main_outline"
        assert env.data["template"] == "cyclic_upgrade"
        assert env.decisions and env.decisions[0]["step"] == "outline"
        # 校验 target_words / custom_ideas 透传
        kwargs = pa_cls.return_value.propose_main_outline.call_args.kwargs
        assert kwargs["target_words"] == 100_000
        assert kwargs["custom_ideas"] == "多线叙事"


# ---------------------------------------------------------------------------
# propose_volume_outline
# ---------------------------------------------------------------------------


class TestProposeVolumeOutline:
    def test_happy_path(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub(
            with_outline=True, with_volumes=True
        )
        fake = VolumeOutlineProposal(
            volume_number=1,
            title="第一卷",
            volume_goal="入门",
            chapter_numbers=[1, 2, 3],
            chapter_outlines=[],
            chapter_type_dist={"setup": 1, "buildup": 2},
            foreshadowing_plan={"to_plant": [], "to_collect_from_previous": []},
        )
        with patch(
            "src.novel.services.tool_facade.VolumeDirector"
        ) as vd_cls:
            vd_cls.return_value.propose_volume_outline.return_value = fake
            env = facade.propose_volume_outline(
                "workspace/novels/novel_xyz", volume_number=1
            )
        assert env.proposal_type == "volume_outline"
        assert env.data["volume_number"] == 1
        assert env.data["chapter_numbers"] == [1, 2, 3]

    def test_project_missing(self, facade):
        facade._fm.load_novel.return_value = None
        env = facade.propose_volume_outline(
            "workspace/novels/novel_missing", volume_number=1
        )
        assert env.errors
        assert "不存在" in env.errors[0]["message"]


# ---------------------------------------------------------------------------
# propose_chapter_brief
# ---------------------------------------------------------------------------


class TestProposeChapterBrief:
    def test_happy_path(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub(
            with_outline=True, with_volumes=True, with_chapters=True
        )
        brief = ChapterBrief(
            chapter_number=1,
            goal="开场冲突",
            scenes=[],
            target_words=2500,
            chapter_type="setup",
        )
        fake = ChapterBriefProposal(brief=brief, source="chapter_planner")
        with patch(
            "src.novel.services.tool_facade.ChapterPlanner"
        ) as cp_cls:
            cp_cls.return_value.propose_chapter_brief.return_value = fake
            env = facade.propose_chapter_brief(
                "workspace/novels/novel_xyz", chapter_number=1
            )
        assert env.proposal_type == "chapter_brief"
        # data 应含 brief 序列化
        assert env.data["brief"]["chapter_number"] == 1

    def test_project_missing(self, facade):
        facade._fm.load_novel.return_value = None
        env = facade.propose_chapter_brief(
            "workspace/novels/novel_missing", chapter_number=1
        )
        assert env.errors


# ---------------------------------------------------------------------------
# accept_proposal
# ---------------------------------------------------------------------------


class TestAcceptProposal:
    def test_synopsis_happy_path(self, facade):
        novel = _novel_data_stub()
        facade._fm.load_novel.return_value = novel
        result = facade.accept_proposal(
            "workspace/novels/novel_xyz",
            proposal_id="pid-1",
            proposal_type="synopsis",
            data={"synopsis": "新主线", "main_storyline": {"protagonist": "阿雷"}},
        )
        assert result.status == "accepted"
        assert result.proposal_id == "pid-1"
        # save_novel 必须被调用一次
        facade._fm.save_novel.assert_called_once()
        saved_id, saved_data = facade._fm.save_novel.call_args.args
        assert saved_id == "novel_xyz"
        assert saved_data["synopsis"] == "新主线"
        assert saved_data["_meta"]["last_accepted_proposal_id"] == "pid-1"
        assert saved_data["_meta"]["last_accepted_type"] == "synopsis"

    def test_idempotent_already_accepted_skips_save(self, facade):
        novel = _novel_data_stub()
        novel["_meta"] = {"last_accepted_proposal_id": "pid-1"}
        facade._fm.load_novel.return_value = novel
        result = facade.accept_proposal(
            "workspace/novels/novel_xyz",
            proposal_id="pid-1",
            proposal_type="synopsis",
            data={"synopsis": "x"},
        )
        assert result.status == "already_accepted"
        facade._fm.save_novel.assert_not_called()

    def test_project_missing(self, facade):
        facade._fm.load_novel.return_value = None
        result = facade.accept_proposal(
            "workspace/novels/novel_missing",
            proposal_id="pid",
            proposal_type="synopsis",
            data={"synopsis": "x"},
        )
        assert result.status == "failed"
        assert "不存在" in (result.error or "")
        facade._fm.save_novel.assert_not_called()

    def test_project_setup_returns_not_implemented(self, facade):
        # 立项 accept 暂不支持 — 预期 failed + 明确的 error 提示
        result = facade.accept_proposal(
            "workspace/novels/novel_anything",
            proposal_id="pid",
            proposal_type="project_setup",
            data={"genre": "玄幻"},
        )
        assert result.status == "failed"
        assert "create_novel" in (result.error or "") or "尚未实现" in (
            result.error or ""
        )
        facade._fm.save_novel.assert_not_called()

    def test_unknown_proposal_type_raises(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub()
        with pytest.raises(ValueError, match="未知 proposal_type"):
            facade.accept_proposal(
                "workspace/novels/novel_xyz",
                proposal_id="pid",
                proposal_type="bogus_type",
                data={},
            )
        facade._fm.save_novel.assert_not_called()

    def test_characters_dispatch(self, facade):
        novel = _novel_data_stub()
        facade._fm.load_novel.return_value = novel
        profile = _make_profile()
        data = {"characters": [profile.model_dump()]}
        result = facade.accept_proposal(
            "workspace/novels/novel_xyz",
            proposal_id="pid-c",
            proposal_type="characters",
            data=data,
        )
        assert result.status == "accepted"
        _, saved = facade._fm.save_novel.call_args.args
        assert len(saved["characters"]) == 1
        assert saved["characters"][0]["name"] == "林辰"

    def test_characters_strict_one_invalid_rejects_batch(self, facade):
        """H1：任一 profile 非法 → 整批 ValueError，不静默吞 + save。"""
        novel = _novel_data_stub()
        # novel 已有 1 个现有角色
        novel["characters"] = [{"existing": "stays"}]
        facade._fm.load_novel.return_value = novel
        good = _make_profile()
        data = {
            "characters": [
                good.model_dump(),
                {"invalid": "missing required fields"},  # 非法
            ],
        }
        with pytest.raises(ValueError, match="character profiles 非法"):
            facade.accept_proposal(
                "workspace/novels/novel_xyz",
                proposal_id="pid-c",
                proposal_type="characters",
                data=data,
            )
        # 关键：save 不应被调用——不能因为 1 个非法就把已有角色覆盖写丢
        facade._fm.save_novel.assert_not_called()

    def test_characters_strict_all_invalid_rejects_batch(self, facade):
        """H1：全部 profile 非法 → 整批 ValueError，绝不写空 list 抹掉已有角色。"""
        novel = _novel_data_stub()
        novel["characters"] = [{"existing": "must_not_be_wiped"}]
        facade._fm.load_novel.return_value = novel
        data = {
            "characters": [
                {"bad": 1},
                {"also_bad": 2},
                "not_even_a_dict",  # 连 dict 都不是
            ],
        }
        with pytest.raises(ValueError, match="3/3 character profiles 非法"):
            facade.accept_proposal(
                "workspace/novels/novel_xyz",
                proposal_id="pid-c",
                proposal_type="characters",
                data=data,
            )
        facade._fm.save_novel.assert_not_called()

    def test_characters_strict_all_valid_saves_normally(self, facade):
        """H1 对照：全部合法 → 正常落盘。"""
        novel = _novel_data_stub()
        facade._fm.load_novel.return_value = novel
        profiles = [
            _make_profile(name="林辰"),
            _make_profile(name="苏瑶", role="女主"),
        ]
        data = {"characters": [p.model_dump() for p in profiles]}
        result = facade.accept_proposal(
            "workspace/novels/novel_xyz",
            proposal_id="pid-c-ok",
            proposal_type="characters",
            data=data,
        )
        assert result.status == "accepted"
        _, saved = facade._fm.save_novel.call_args.args
        assert [c["name"] for c in saved["characters"]] == ["林辰", "苏瑶"]

    def test_world_setting_dispatch(self, facade):
        novel = _novel_data_stub()
        facade._fm.load_novel.return_value = novel
        world = _minimal_world()
        result = facade.accept_proposal(
            "workspace/novels/novel_xyz",
            proposal_id="pid-w",
            proposal_type="world_setting",
            data={"world_setting": world.model_dump()},
        )
        assert result.status == "accepted"
        _, saved = facade._fm.save_novel.call_args.args
        assert saved["world_setting"]["era"] == "修仙时代"

    def test_story_arcs_dispatch_replaces(self, facade):
        """Phase 4 §4.3：arcs accept 覆盖而非 extend。

        regenerate 后的二次 accept 必须替换旧 arcs，否则 regenerate 毫无意义。
        """
        novel = _novel_data_stub()
        novel["story_arcs"] = [{"arc_id": "arc_0"}]
        facade._fm.load_novel.return_value = novel
        result = facade.accept_proposal(
            "workspace/novels/novel_xyz",
            proposal_id="pid-a",
            proposal_type="story_arcs",
            data={"arcs": [{"arc_id": "arc_1"}, {"arc_id": "arc_2"}]},
        )
        assert result.status == "accepted"
        _, saved = facade._fm.save_novel.call_args.args
        arc_ids = [a["arc_id"] for a in saved["story_arcs"]]
        # 覆盖语义：arc_0 应被替换为新 arcs
        assert arc_ids == ["arc_1", "arc_2"]
        assert "arc_0" not in arc_ids

    def test_volume_breakdown_dispatch(self, facade):
        novel = _novel_data_stub(with_outline=True)
        facade._fm.load_novel.return_value = novel
        result = facade.accept_proposal(
            "workspace/novels/novel_xyz",
            proposal_id="pid-v",
            proposal_type="volume_breakdown",
            data={
                "volumes": [
                    {
                        "volume_number": 1,
                        "title": "新一卷",
                        "core_conflict": "c",
                        "resolution": "r",
                    }
                ]
            },
        )
        assert result.status == "accepted"
        _, saved = facade._fm.save_novel.call_args.args
        assert saved["outline"]["volumes"][0]["title"] == "新一卷"

    def test_main_outline_dispatch(self, facade):
        novel = _novel_data_stub()
        facade._fm.load_novel.return_value = novel
        result = facade.accept_proposal(
            "workspace/novels/novel_xyz",
            proposal_id="pid-m",
            proposal_type="main_outline",
            data={
                "outline": {"template": "cyclic_upgrade", "chapters": []},
                "template": "cyclic_upgrade",
                "style_name": "webnovel.xuanhuan",
                "style_bible": {"tone": "fast"},
                "total_chapters": 40,
            },
        )
        assert result.status == "accepted"
        _, saved = facade._fm.save_novel.call_args.args
        assert saved["outline"] == {"template": "cyclic_upgrade", "chapters": []}
        assert saved["template"] == "cyclic_upgrade"
        assert saved["style_name"] == "webnovel.xuanhuan"
        assert saved["style_bible"] == {"tone": "fast"}

    def test_volume_outline_dispatch_merges_into_existing_volume(self, facade):
        novel = _novel_data_stub(with_outline=True, with_volumes=True)
        facade._fm.load_novel.return_value = novel
        result = facade.accept_proposal(
            "workspace/novels/novel_xyz",
            proposal_id="pid-vo",
            proposal_type="volume_outline",
            data={
                "volume_number": 1,
                "title": "第一卷-refined",
                "volume_goal": "从凡到士",
                "chapter_numbers": [1, 2, 3],
                "chapter_type_dist": {"setup": 1, "buildup": 2},
                "foreshadowing_plan": {
                    "to_plant": [{"description": "x"}],
                    "to_collect_from_previous": [],
                },
                "chapter_outlines": [
                    {
                        "chapter_number": 1,
                        "title": "开场",
                        "goal": "g1",
                        "key_events": ["e1"],
                        "estimated_words": 2500,
                        "chapter_type": "setup",
                        "mood": "蓄力",
                    }
                ],
            },
        )
        assert result.status == "accepted"
        _, saved = facade._fm.save_novel.call_args.args
        v1 = saved["outline"]["volumes"][0]
        assert v1["title"] == "第一卷-refined"
        assert v1["volume_goal"] == "从凡到士"
        assert v1["chapter_type_dist"] == {"setup": 1, "buildup": 2}
        assert any(
            c.get("chapter_number") == 1
            for c in saved["outline"].get("chapters", [])
        )

    def test_volume_outline_missing_volume_number_raises(self, facade):
        novel = _novel_data_stub(with_outline=True, with_volumes=True)
        facade._fm.load_novel.return_value = novel
        with pytest.raises(ValueError, match="volume_number"):
            facade.accept_proposal(
                "workspace/novels/novel_xyz",
                proposal_id="pid-vo",
                proposal_type="volume_outline",
                data={"title": "no number"},
            )

    def test_chapter_brief_dispatch_merges_legacy_fields(self, facade):
        novel = _novel_data_stub(
            with_outline=True, with_volumes=True, with_chapters=True
        )
        facade._fm.load_novel.return_value = novel
        result = facade.accept_proposal(
            "workspace/novels/novel_xyz",
            proposal_id="pid-cb",
            proposal_type="chapter_brief",
            data={
                "brief": {
                    "chapter_number": 1,
                    "goal": "找到线索",
                    "tone_notes": "紧张",
                    "must_collect_foreshadowings": ["旧账"],
                    "end_hook_type": "悬疑",
                },
            },
        )
        assert result.status == "accepted"
        _, saved = facade._fm.save_novel.call_args.args
        ch = saved["outline"]["chapters"][0]
        assert ch["chapter_brief"]["main_conflict"] == "找到线索"
        assert ch["chapter_brief"]["end_hook_type"] == "悬疑"
        assert ch["chapter_brief"]["foreshadowing_collect"] == ["旧账"]

    def test_chapter_brief_chapter_not_found_raises(self, facade):
        novel = _novel_data_stub(
            with_outline=True, with_volumes=True, with_chapters=True
        )
        facade._fm.load_novel.return_value = novel
        with pytest.raises(ValueError, match="找不到对应章节"):
            facade.accept_proposal(
                "workspace/novels/novel_xyz",
                proposal_id="pid-cb",
                proposal_type="chapter_brief",
                data={"brief": {"chapter_number": 99, "goal": "oops"}},
            )

    def test_invalid_data_type_raises(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub()
        with pytest.raises(ValueError, match="dict"):
            facade.accept_proposal(
                "workspace/novels/novel_xyz",
                proposal_id="pid",
                proposal_type="synopsis",
                data="not a dict",  # type: ignore[arg-type]
            )

    def test_agent_layer_raises_returns_failed_not_propagated(self, facade):
        """world_setting 传入非法世界数据 — Agent 层 Pydantic 爆掉 → ValueError 透传。"""
        facade._fm.load_novel.return_value = _novel_data_stub()
        with pytest.raises(ValueError):
            facade.accept_proposal(
                "workspace/novels/novel_xyz",
                proposal_id="pid",
                proposal_type="world_setting",
                data={"world_setting": {"era": ""}},  # min_length=1 — will fail
            )

    def test_save_novel_failure_returns_failed_status(self, facade):
        """M1：save_novel 抛异常不得传播，返回 AcceptResult(status="failed")。"""
        novel = _novel_data_stub()
        facade._fm.load_novel.return_value = novel
        facade._fm.save_novel.side_effect = OSError("disk full")
        result = facade.accept_proposal(
            "workspace/novels/novel_xyz",
            proposal_id="pid-disk",
            proposal_type="synopsis",
            data={"synopsis": "x", "main_storyline": {}},
        )
        assert result.status == "failed"
        assert result.proposal_id == "pid-disk"
        assert result.proposal_type == "synopsis"
        assert result.error and "disk full" in result.error
        assert result.error.startswith("save failed:")


# ---------------------------------------------------------------------------
# regenerate_section
# ---------------------------------------------------------------------------


class TestRegenerateSection:
    def test_synopsis_dispatch(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub()
        fake = SynopsisProposal(synopsis="重生版", main_storyline={})
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            pa_cls.return_value.regenerate_section.return_value = fake
            env = facade.regenerate_section(
                "workspace/novels/novel_xyz",
                section="synopsis",
                hints="更爽快",
            )
        assert env.proposal_type == "synopsis"
        assert env.data["synopsis"] == "重生版"
        call = pa_cls.return_value.regenerate_section.call_args
        assert call.kwargs["section"] == "synopsis"
        assert call.kwargs["hints"] == "更爽快"

    def test_world_setting_maps_to_pa_world(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub()
        fake = WorldProposal(world=_minimal_world())
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            pa_cls.return_value.regenerate_section.return_value = fake
            env = facade.regenerate_section(
                "workspace/novels/novel_xyz",
                section="world_setting",
                hints="灵气枯竭",
            )
        assert env.proposal_type == "world_setting"
        # PA.regenerate_section 用的 section 名应该被映射为 "world"
        assert (
            pa_cls.return_value.regenerate_section.call_args.kwargs["section"]
            == "world"
        )

    def test_story_arcs_maps_to_pa_arcs(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub(with_outline=True)
        fake = ArcsProposal(arcs=[])
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            pa_cls.return_value.regenerate_section.return_value = fake
            facade.regenerate_section(
                "workspace/novels/novel_xyz",
                section="story_arcs",
                hints="",
            )
        assert (
            pa_cls.return_value.regenerate_section.call_args.kwargs["section"]
            == "arcs"
        )

    def test_main_outline_uses_propose_path(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub()
        fake = MainOutlineProposal(
            outline={"template": "cyclic_upgrade", "chapters": []},
            template="cyclic_upgrade",
            style_name="webnovel.xuanhuan",
            total_chapters=0,
        )
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            pa_cls.return_value.propose_main_outline.return_value = fake
            env = facade.regenerate_section(
                "workspace/novels/novel_xyz",
                section="main_outline",
                hints="加反转",
            )
        assert env.proposal_type == "main_outline"
        # main_outline 走 propose_main_outline 路径，hints → custom_ideas
        kwargs = pa_cls.return_value.propose_main_outline.call_args.kwargs
        assert kwargs["custom_ideas"] == "加反转"

    def test_volume_outline_requires_volume_number(self, facade):
        with pytest.raises(ValueError, match="volume_number"):
            facade.regenerate_section(
                "workspace/novels/novel_xyz",
                section="volume_outline",
                hints="改掉第三章",
            )

    def test_volume_outline_happy_path_with_hints(self, facade):
        facade._fm.load_novel.return_value = _novel_data_stub(
            with_outline=True, with_volumes=True
        )
        fake = VolumeOutlineProposal(
            volume_number=1,
            title="第一卷",
            volume_goal="改",
            chapter_numbers=[1, 2, 3],
            chapter_outlines=[],
        )
        with patch(
            "src.novel.services.tool_facade.VolumeDirector"
        ) as vd_cls:
            vd_cls.return_value.propose_volume_outline.return_value = fake
            env = facade.regenerate_section(
                "workspace/novels/novel_xyz",
                section="volume_outline",
                hints="改节奏",
                volume_number=1,
            )
        assert env.proposal_type == "volume_outline"
        assert env.data["volume_goal"] == "改"

    def test_volume_outline_fallback_when_hints_signature_missing(self, facade):
        """若 VolumeDirector.propose_volume_outline 暂时不认 hints=...（E3 未上线）—
        facade 应捕获 TypeError 并无 hints 重试一次，同时给 warning。"""
        facade._fm.load_novel.return_value = _novel_data_stub(
            with_outline=True, with_volumes=True
        )
        fake = VolumeOutlineProposal(
            volume_number=1,
            title="第一卷",
            volume_goal="改",
            chapter_numbers=[1, 2, 3],
            chapter_outlines=[],
        )
        mock_method = MagicMock(
            side_effect=[
                TypeError("unexpected keyword argument 'hints'"),
                fake,
            ]
        )
        with patch(
            "src.novel.services.tool_facade.VolumeDirector"
        ) as vd_cls:
            vd_cls.return_value.propose_volume_outline = mock_method
            env = facade.regenerate_section(
                "workspace/novels/novel_xyz",
                section="volume_outline",
                hints="改节奏",
                volume_number=1,
            )
        assert env.proposal_type == "volume_outline"
        assert env.warnings  # 带警告提示
        assert mock_method.call_count == 2

    def test_unsupported_project_setup_raises(self, facade):
        with pytest.raises(ValueError, match="project_setup"):
            facade.regenerate_section(
                "workspace/novels/novel_xyz",
                section="project_setup",
                hints="",
            )

    def test_unsupported_chapter_brief_raises(self, facade):
        with pytest.raises(ValueError, match="chapter_brief"):
            facade.regenerate_section(
                "workspace/novels/novel_xyz",
                section="chapter_brief",
                hints="",
            )

    def test_unknown_section_raises(self, facade):
        with pytest.raises(ValueError, match="未知 section"):
            facade.regenerate_section(
                "workspace/novels/novel_xyz",
                section="bogus",
                hints="",
            )

    def test_regenerate_non_proposal_return_raises_type_error(self, facade):
        """M2：ProjectArchitect.regenerate_section 返回非 Proposal（如 dict）
        必须抛 TypeError 暴露契约错误，不能鸭子类型兜底写空 data。"""
        facade._fm.load_novel.return_value = _novel_data_stub()
        with patch(
            "src.novel.services.tool_facade.ProjectArchitect"
        ) as pa_cls:
            # 返回纯 dict —— 无 .to_dict() 方法
            pa_cls.return_value.regenerate_section.return_value = {
                "fake": "not a proposal"
            }
            with pytest.raises(TypeError, match="non-proposal"):
                facade.regenerate_section(
                    "workspace/novels/novel_xyz",
                    section="synopsis",
                    hints="",
                )

    def test_project_missing_returns_envelope_with_errors(self, facade):
        facade._fm.load_novel.return_value = None
        env = facade.regenerate_section(
            "workspace/novels/novel_missing",
            section="synopsis",
            hints="",
        )
        assert env.errors
