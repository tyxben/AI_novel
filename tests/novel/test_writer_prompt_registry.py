"""Tests for Writer + PromptRegistry integration.

Verifies:
1. Default behavior (no registry) -- hardcoded prompts used
2. enable_prompt_registry() sets attributes correctly
3. generate_scene with registry -- dynamic prompt replaces hardcoded blocks
4. generate_scene with registry returning empty string -- falls back to hardcoded
5. _detect_scenario() with various scene plans
6. Usage recording after generation
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, call, patch

import pytest

from src.novel.agents.writer import (
    Writer,
    _ANTI_AI_FLAVOR,
    _ANTI_REPETITION,
    _CHARACTER_NAME_LOCK,
    _NARRATIVE_LOGIC,
)
from src.novel.models.chapter import Scene
from src.novel.models.character import (
    Appearance,
    CharacterArc,
    CharacterProfile,
    Personality,
)
from src.novel.models.novel import ChapterOutline
from src.novel.models.world import WorldSetting


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "test"
    usage: dict | None = None
    finish_reason: str | None = "stop"


def _make_llm(content: str = "测试生成的场景内容，至少要有一些文字。") -> MagicMock:
    llm = MagicMock()
    llm.chat.return_value = FakeLLMResponse(content=content)
    return llm


def _make_character(name: str = "张伟") -> CharacterProfile:
    return CharacterProfile(
        name=name,
        gender="男",
        age=28,
        occupation="快递员",
        appearance=Appearance(
            height="175cm",
            build="瘦削",
            hair="短发",
            eyes="黑色眼睛",
            clothing_style="工装外套",
            distinctive_features=["左眉有疤"],
        ),
        personality=Personality(
            traits=["勇敢", "固执", "善良"],
            core_belief="不抛弃不放弃",
            motivation="保护身边的人",
            flaw="过于冲动",
            speech_style="直爽口语化",
            catchphrases=["搞什么鬼"],
        ),
        character_arc=CharacterArc(
            initial_state="胆小懦弱",
            turning_points=[],
            final_state="勇敢坚毅",
        ),
    )


def _make_outline(chapter_number: int = 1) -> ChapterOutline:
    return ChapterOutline(
        chapter_number=chapter_number,
        title="测试章节",
        goal="推进剧情",
        mood="蓄力",
        estimated_words=2500,
        key_events=["测试事件"],
    )


def _make_world() -> WorldSetting:
    return WorldSetting(era="现代都市", location="某一线城市")


def _make_scene_plan(**overrides) -> dict:
    defaults = {
        "scene_number": 1,
        "location": "街道",
        "time": "黄昏",
        "characters_involved": ["张伟"],
        "goal": "主角在街头漫步",
        "mood": "平静",
        "target_words": 800,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# 1. Default behavior (no registry)
# ---------------------------------------------------------------------------


class TestDefaultBehaviorNoRegistry:
    """When _registry is None, hardcoded prompts must appear in LLM call."""

    def test_hardcoded_prompts_present_in_system_prompt(self):
        llm = _make_llm()
        writer = Writer(llm)

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        assert llm.chat.called
        system_msg = llm.chat.call_args[0][0][0]["content"]
        assert "典型 AI 生成痕迹" in system_msg  # from _ANTI_AI_FLAVOR
        assert "反重复规则" in system_msg  # from _ANTI_REPETITION
        assert "叙事逻辑规则" in system_msg  # from _NARRATIVE_LOGIC
        assert "角色名称锁定" in system_msg  # from _CHARACTER_NAME_LOCK

    def test_registry_attributes_none_by_default(self):
        llm = _make_llm()
        writer = Writer(llm)
        assert writer._registry is None
        assert writer._novel_id is None


# ---------------------------------------------------------------------------
# 2. enable_prompt_registry() sets attributes
# ---------------------------------------------------------------------------


class TestEnablePromptRegistry:

    def test_sets_registry_and_novel_id(self):
        llm = _make_llm()
        writer = Writer(llm)
        mock_registry = MagicMock()

        writer.enable_prompt_registry(mock_registry, novel_id="novel_abc")

        assert writer._registry is mock_registry
        assert writer._novel_id == "novel_abc"

    def test_novel_id_defaults_to_none(self):
        llm = _make_llm()
        writer = Writer(llm)
        mock_registry = MagicMock()

        writer.enable_prompt_registry(mock_registry)

        assert writer._registry is mock_registry
        assert writer._novel_id is None

    def test_can_override_registry(self):
        llm = _make_llm()
        writer = Writer(llm)
        reg1 = MagicMock()
        reg2 = MagicMock()

        writer.enable_prompt_registry(reg1, novel_id="n1")
        writer.enable_prompt_registry(reg2, novel_id="n2")

        assert writer._registry is reg2
        assert writer._novel_id == "n2"


# ---------------------------------------------------------------------------
# 3. generate_scene with registry -- dynamic prompt replaces hardcoded
# ---------------------------------------------------------------------------


class TestGenerateSceneWithRegistry:

    def test_registry_prompt_replaces_hardcoded_blocks(self):
        """When registry returns a non-empty prompt, it replaces the 4 hardcoded blocks."""
        llm = _make_llm()
        writer = Writer(llm)

        mock_registry = MagicMock()
        mock_registry.build_prompt.return_value = "【REGISTRY DYNAMIC PROMPT HERE】"
        # For usage recording
        mock_registry.get_template_for.return_value = MagicMock(template_id="tpl_test")

        writer.enable_prompt_registry(mock_registry, novel_id="novel_123")

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        system_msg = llm.chat.call_args[0][0][0]["content"]

        # Dynamic prompt present
        assert "REGISTRY DYNAMIC PROMPT HERE" in system_msg

        # Hardcoded blocks should NOT be in the system prompt
        assert _ANTI_AI_FLAVOR not in system_msg
        assert _ANTI_REPETITION not in system_msg
        assert _NARRATIVE_LOGIC not in system_msg
        assert _CHARACTER_NAME_LOCK not in system_msg

    def test_registry_build_prompt_called_with_correct_args(self):
        """Verify build_prompt is called with correct agent, scenario, genre."""
        llm = _make_llm()
        writer = Writer(llm)

        mock_registry = MagicMock()
        mock_registry.build_prompt.return_value = "动态提示词"
        mock_registry.get_template_for.return_value = None

        writer.enable_prompt_registry(mock_registry)

        # Scene with battle keywords
        scene_plan = _make_scene_plan(goal="主角与敌人展开战斗")

        writer.generate_scene(
            scene_plan=scene_plan,
            chapter_outline=_make_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="wuxia.classical",
        )

        mock_registry.build_prompt.assert_called_once_with(
            agent_name="writer",
            scenario="battle",
            genre="wuxia",
        )

    def test_non_dotted_style_name_used_as_genre(self):
        """Style names without dots are passed directly as genre."""
        llm = _make_llm()
        writer = Writer(llm)

        mock_registry = MagicMock()
        mock_registry.build_prompt.return_value = "prompt content"
        mock_registry.get_template_for.return_value = None

        writer.enable_prompt_registry(mock_registry)

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="scifi",
        )

        mock_registry.build_prompt.assert_called_once_with(
            agent_name="writer",
            scenario="default",
            genre="scifi",
        )

    def test_other_prompt_parts_remain_unchanged(self):
        """Style, world, characters, chapter info -- all stay when registry is used."""
        llm = _make_llm()
        writer = Writer(llm)

        mock_registry = MagicMock()
        mock_registry.build_prompt.return_value = "DYNAMIC_BLOCK"
        mock_registry.get_template_for.return_value = None

        writer.enable_prompt_registry(mock_registry)

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="前文内容",
            style_name="webnovel.shuangwen",
        )

        system_msg = llm.chat.call_args[0][0][0]["content"]

        # Standard parts must still be present
        assert "第1章" in system_msg
        assert "测试章节" in system_msg
        assert "推进剧情" in system_msg
        assert "现代都市" in system_msg
        assert "张伟" in system_msg
        assert "字数限制" in system_msg


# ---------------------------------------------------------------------------
# 4. generate_scene with registry returning empty string -- falls back
# ---------------------------------------------------------------------------


class TestRegistryFallback:

    def test_empty_registry_prompt_falls_back_to_hardcoded(self):
        """When build_prompt returns empty string, hardcoded blocks are used."""
        llm = _make_llm()
        writer = Writer(llm)

        mock_registry = MagicMock()
        mock_registry.build_prompt.return_value = ""
        mock_registry.get_template_for.return_value = None

        writer.enable_prompt_registry(mock_registry)

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        system_msg = llm.chat.call_args[0][0][0]["content"]

        # Hardcoded blocks should be present since registry returned empty
        assert "典型 AI 生成痕迹" in system_msg
        assert "反重复规则" in system_msg
        assert "叙事逻辑规则" in system_msg
        assert "角色名称锁定" in system_msg


# ---------------------------------------------------------------------------
# 5. _detect_scenario() with various scene plans
# ---------------------------------------------------------------------------


class TestDetectScenario:

    def test_battle_detected(self):
        assert Writer._detect_scenario({"goal": "主角与敌人战斗"}) == "battle"
        assert Writer._detect_scenario({"goal": "一场激烈的打斗"}) == "battle"
        assert Writer._detect_scenario({"goal": "拔剑对决"}) == "battle"
        assert Writer._detect_scenario({"summary": "发动攻击"}) == "battle"

    def test_dialogue_detected(self):
        assert Writer._detect_scenario({"goal": "两人进行对话"}) == "dialogue"
        assert Writer._detect_scenario({"goal": "说服长老同意"}) == "dialogue"
        assert Writer._detect_scenario({"goal": "激烈的争论"}) == "dialogue"

    def test_emotional_detected(self):
        assert Writer._detect_scenario({"goal": "兄弟离别"}) == "emotional"
        assert Writer._detect_scenario({"goal": "多年后的重逢"}) == "emotional"
        assert Writer._detect_scenario({"goal": "悲伤的告白"}) == "emotional"

    def test_strategy_detected(self):
        assert Writer._detect_scenario({"goal": "布局谋略"}) == "strategy"
        assert Writer._detect_scenario({"goal": "一场阴谋"}) == "strategy"
        assert Writer._detect_scenario({"goal": "制定策略"}) == "strategy"

    def test_default_when_no_match(self):
        assert Writer._detect_scenario({"goal": "主角在街头漫步"}) == "default"
        assert Writer._detect_scenario({}) == "default"
        assert Writer._detect_scenario({"goal": ""}) == "default"

    def test_combined_goal_and_summary(self):
        """Keywords in summary field are also detected."""
        assert Writer._detect_scenario({"goal": "未指定", "summary": "一场战斗"}) == "battle"

    def test_first_matching_scenario_wins(self):
        """When multiple keywords match, the first matching scenario wins (dict order)."""
        # "battle" comes before "dialogue" in iteration order
        plan = {"goal": "战斗中的对话"}
        result = Writer._detect_scenario(plan)
        assert result == "battle"

    def test_case_insensitive_via_lower(self):
        """Goal text is lowered, but Chinese chars are unaffected by .lower()."""
        assert Writer._detect_scenario({"goal": "BATTLE 战斗"}) == "battle"


# ---------------------------------------------------------------------------
# 6. Usage recording after generation
# ---------------------------------------------------------------------------


class TestUsageRecording:

    def test_usage_recorded_when_registry_enabled_and_template_found(self):
        llm = _make_llm()
        writer = Writer(llm)

        mock_registry = MagicMock()
        mock_registry.build_prompt.return_value = "动态提示词"
        mock_template = MagicMock()
        mock_template.template_id = "writer_default"
        mock_registry.get_template_for.return_value = mock_template
        mock_registry.record_usage.return_value = "usage_001"

        writer.enable_prompt_registry(mock_registry, novel_id="novel_xyz")

        scene = writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_outline(chapter_number=5),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        mock_registry.record_usage.assert_called_once_with(
            template_id="writer_default",
            block_ids=[],
            agent_name="writer",
            scenario="default",
            novel_id="novel_xyz",
            chapter_number=5,
        )

    def test_no_usage_recorded_when_template_not_found(self):
        llm = _make_llm()
        writer = Writer(llm)

        mock_registry = MagicMock()
        mock_registry.build_prompt.return_value = "动态提示词"
        mock_registry.get_template_for.return_value = None

        writer.enable_prompt_registry(mock_registry, novel_id="novel_xyz")

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        mock_registry.record_usage.assert_not_called()

    def test_no_usage_recorded_when_registry_not_enabled(self):
        llm = _make_llm()
        writer = Writer(llm)

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        # No registry => no crash, no recording attempt

    def test_usage_recording_exception_does_not_propagate(self):
        """If record_usage raises, generate_scene still returns normally."""
        llm = _make_llm()
        writer = Writer(llm)

        mock_registry = MagicMock()
        mock_registry.build_prompt.return_value = "动态提示词"
        mock_template = MagicMock()
        mock_template.template_id = "tpl"
        mock_registry.get_template_for.return_value = mock_template
        mock_registry.record_usage.side_effect = RuntimeError("DB error")

        writer.enable_prompt_registry(mock_registry, novel_id="n")

        # Should not raise
        scene = writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )
        assert isinstance(scene, Scene)
        assert scene.text  # still got generated text

    def test_usage_scenario_matches_detected_scenario(self):
        """Usage recording uses the same scenario detected for build_prompt."""
        llm = _make_llm()
        writer = Writer(llm)

        mock_registry = MagicMock()
        mock_registry.build_prompt.return_value = "battle prompt"
        mock_template = MagicMock()
        mock_template.template_id = "writer_battle"
        mock_registry.get_template_for.return_value = mock_template

        writer.enable_prompt_registry(mock_registry, novel_id="n")

        writer.generate_scene(
            scene_plan=_make_scene_plan(goal="与魔王展开战斗"),
            chapter_outline=_make_outline(chapter_number=10),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.xuanhuan",
        )

        # build_prompt called with battle scenario
        mock_registry.build_prompt.assert_called_once_with(
            agent_name="writer",
            scenario="battle",
            genre="webnovel",
        )

        # record_usage called with same scenario
        mock_registry.record_usage.assert_called_once()
        kwargs = mock_registry.record_usage.call_args[1]
        assert kwargs["scenario"] == "battle"
        assert kwargs["chapter_number"] == 10


# ---------------------------------------------------------------------------
# 7. Return value correctness with registry enabled
# ---------------------------------------------------------------------------


class TestReturnValueWithRegistry:

    def test_scene_returned_correctly(self):
        llm = _make_llm("生成的场景文本内容。")
        writer = Writer(llm)

        mock_registry = MagicMock()
        mock_registry.build_prompt.return_value = "DYNAMIC"
        mock_registry.get_template_for.return_value = None

        writer.enable_prompt_registry(mock_registry)

        scene = writer.generate_scene(
            scene_plan=_make_scene_plan(scene_number=2, location="山顶"),
            chapter_outline=_make_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        assert isinstance(scene, Scene)
        assert scene.scene_number == 2
        assert scene.location == "山顶"
        assert "生成的场景文本内容" in scene.text
