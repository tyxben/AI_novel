"""WriterReactAgent 单元测试

覆盖:
- 构造函数: 7 个工具注册、toolkit 共享 LLM
- generate_scene happy path: ReAct 循环 (generate_draft -> check -> submit)
- generate_scene fallback: ReAct 产出空文本时降级到 one-shot Writer
- generate_scene budget_mode: check 类工具被跳过
- generate_scene 结果字段: Scene 对象各字段正确
- _build_scene_prompt: 风格、章节信息、世界观、角色、反馈、debt_summary、context
- 边界条件: 无世界观、无角色、空上下文、未知风格名、dict result from ReAct
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.writer_react import WriterReactAgent, _MAX_CONTEXT
from src.novel.models.chapter import Scene
from src.novel.models.character import (
    Appearance,
    CharacterProfile,
    Personality,
)
from src.novel.models.novel import ChapterOutline
from src.novel.models.world import PowerLevel, PowerSystem, WorldSetting


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resp(content: str, usage: dict | None = None) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test",
        usage=usage or {"total_tokens": 50},
    )


def _react_json(thinking: str, tool: str, args: dict | None = None) -> str:
    """Build a JSON string that the ReAct agent loop expects."""
    return json.dumps(
        {"thinking": thinking, "tool": tool, "args": args or {}},
        ensure_ascii=False,
    )


def _make_chapter_outline(
    chapter_number: int = 1, title: str = "风云突变"
) -> ChapterOutline:
    return ChapterOutline(
        chapter_number=chapter_number,
        title=title,
        goal="主角与敌人首次交锋",
        key_events=["遭遇敌人", "激烈战斗"],
        involved_characters=["char_1", "char_2"],
        estimated_words=3000,
        mood="蓄力",
    )


def _make_character(
    name: str = "林凡", gender: str = "男"
) -> CharacterProfile:
    return CharacterProfile(
        name=name,
        gender=gender,
        age=22,
        occupation="剑客",
        appearance=Appearance(
            height="180cm",
            build="匀称",
            hair="黑色短发",
            eyes="深邃黑眸",
            clothing_style="白衣",
        ),
        personality=Personality(
            traits=["冷静", "果敢", "隐忍"],
            core_belief="实力为尊",
            motivation="为师报仇",
            flaw="过于自负",
            speech_style="冷淡简短",
            catchphrases=["哼", "不过如此"],
        ),
    )


def _make_world() -> WorldSetting:
    return WorldSetting(
        era="古代",
        location="九州大陆",
        power_system=PowerSystem(
            name="修炼境界",
            levels=[
                PowerLevel(
                    rank=1,
                    name="炼气期",
                    description="初入修炼",
                    typical_abilities=["基础剑术"],
                ),
            ],
        ),
        terms={"九霄门": "主角所属门派"},
        rules=["修炼需要灵石", "境界突破有天劫"],
    )


def _make_scene_plan(
    scene_number: int = 1,
    target_words: int = 800,
) -> dict:
    return {
        "scene_number": scene_number,
        "location": "九霄门演武场",
        "time": "清晨",
        "characters": ["林凡", "赵无极"],
        "goal": "主角与对手切磋",
        "mood": "蓄力",
        "summary": "切磋武艺",
        "target_words": target_words,
    }


# A substantial Chinese text that passes the len(text) >= 50 guard.
_SCENE_TEXT = "他拔出长剑，目光如炬，直视前方的敌人。" * 5  # ~90 chars


# ---------------------------------------------------------------------------
# Constructor tests
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_seven_tools_registered(self):
        llm = MagicMock()
        agent = WriterReactAgent(llm)
        expected = {
            "generate_draft",
            "check_repetition",
            "check_character_names",
            "check_narrative_logic",
            "revise_draft",
            "get_current_draft",
            "submit",
        }
        assert set(agent._tools.keys()) == expected

    def test_toolkit_shares_llm(self):
        llm = MagicMock()
        agent = WriterReactAgent(llm)
        assert agent.toolkit.llm is llm

    def test_check_tools_flagged(self):
        """check_repetition, check_character_names, check_narrative_logic
        should have check_tool=True."""
        agent = WriterReactAgent(MagicMock())
        for name in [
            "check_repetition",
            "check_character_names",
            "check_narrative_logic",
        ]:
            assert agent._tools[name].check_tool is True

    def test_non_check_tools_not_flagged(self):
        agent = WriterReactAgent(MagicMock())
        for name in ["generate_draft", "revise_draft", "get_current_draft", "submit"]:
            assert agent._tools[name].check_tool is False

    def test_default_submit_replaced(self):
        """The base ReactAgent's default submit is replaced by WriterToolkit's
        submit_final, not the lambda."""
        agent = WriterReactAgent(MagicMock())
        submit_tool = agent._tools["submit"]
        assert submit_tool.func == agent.toolkit.submit_final


# ---------------------------------------------------------------------------
# generate_scene - happy path
# ---------------------------------------------------------------------------


class TestGenerateSceneHappyPath:
    def test_basic_scene_generation(self):
        """Simulate ReAct loop: generate_draft -> submit."""
        llm = MagicMock()
        # Call 1: generate_draft tool (from toolkit, called via generate_draft scene_prompt)
        # But the ReAct loop calls llm.chat for the ReAct reasoning, not the tool calls.
        # ReAct loop LLM calls: step1 = generate_draft, step2 = submit
        # The toolkit's generate_draft also calls llm.chat internally.
        # So the full sequence is:
        #   1. ReAct loop llm.chat -> returns JSON to call generate_draft
        #   2. toolkit.generate_draft internally calls llm.chat -> returns scene text
        #   3. ReAct loop llm.chat -> returns JSON to call submit
        llm.chat.side_effect = [
            # Step 1: ReAct loop decides to call generate_draft
            _resp(
                _react_json(
                    "先生成初稿",
                    "generate_draft",
                    {"scene_prompt": "测试场景"},
                )
            ),
            # Step 2: toolkit.generate_draft internally calls llm.chat
            _resp(_SCENE_TEXT),
            # Step 3: ReAct loop decides to submit
            _resp(
                _react_json("初稿满意，提交", "submit", {"text": ""})
            ),
        ]

        agent = WriterReactAgent(llm)
        scene = agent.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="前文回顾",
            style_name="webnovel.shuangwen",
        )

        assert isinstance(scene, Scene)
        assert scene.scene_number == 1
        assert scene.location == "九霄门演武场"
        assert scene.time == "清晨"
        assert len(scene.text) > 50
        assert scene.word_count > 0

    def test_scene_characters_from_plan(self):
        """Scene.characters should come from scene_plan's characters field."""
        llm = MagicMock()
        llm.chat.side_effect = [
            _resp(
                _react_json(
                    "生成", "generate_draft", {"scene_prompt": "p"}
                )
            ),
            _resp(_SCENE_TEXT),
            _resp(_react_json("提交", "submit", {"text": ""})),
        ]
        agent = WriterReactAgent(llm)
        plan = _make_scene_plan()
        plan["characters"] = ["角色甲", "角色乙"]
        scene = agent.generate_scene(
            scene_plan=plan,
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )
        assert scene.characters == ["角色甲", "角色乙"]

    def test_scene_characters_involved_takes_priority(self):
        """characters_involved has priority over characters in scene_plan."""
        llm = MagicMock()
        llm.chat.side_effect = [
            _resp(
                _react_json(
                    "生成", "generate_draft", {"scene_prompt": "p"}
                )
            ),
            _resp(_SCENE_TEXT),
            _resp(_react_json("提交", "submit", {"text": ""})),
        ]
        agent = WriterReactAgent(llm)
        plan = _make_scene_plan()
        plan["characters_involved"] = ["VIP角色"]
        plan["characters"] = ["普通角色"]
        scene = agent.generate_scene(
            scene_plan=plan,
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )
        assert scene.characters == ["VIP角色"]

    def test_submit_with_explicit_text(self):
        """When submit provides explicit text, that text is used."""
        explicit_text = "这是显式提交的最终文本，足够长度以通过检查。" * 3
        llm = MagicMock()
        llm.chat.side_effect = [
            _resp(
                _react_json(
                    "生成", "generate_draft", {"scene_prompt": "p"}
                )
            ),
            _resp(_SCENE_TEXT),
            _resp(
                _react_json(
                    "提交", "submit", {"text": explicit_text}
                )
            ),
        ]
        agent = WriterReactAgent(llm)
        scene = agent.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )
        assert scene.text == explicit_text

    def test_goal_from_scene_plan(self):
        """Scene.goal should come from scene_plan's goal field."""
        llm = MagicMock()
        llm.chat.side_effect = [
            _resp(
                _react_json(
                    "生成", "generate_draft", {"scene_prompt": "p"}
                )
            ),
            _resp(_SCENE_TEXT),
            _resp(_react_json("提交", "submit", {"text": ""})),
        ]
        agent = WriterReactAgent(llm)
        scene = agent.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )
        assert scene.goal == "主角与对手切磋"

    def test_goal_falls_back_to_summary(self):
        """If 'goal' is missing from scene_plan, fallback to 'summary'."""
        llm = MagicMock()
        llm.chat.side_effect = [
            _resp(
                _react_json(
                    "生成", "generate_draft", {"scene_prompt": "p"}
                )
            ),
            _resp(_SCENE_TEXT),
            _resp(_react_json("提交", "submit", {"text": ""})),
        ]
        agent = WriterReactAgent(llm)
        plan = _make_scene_plan()
        del plan["goal"]
        plan["summary"] = "总结文本"
        scene = agent.generate_scene(
            scene_plan=plan,
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )
        assert scene.goal == "总结文本"


# ---------------------------------------------------------------------------
# generate_scene - fallback to one-shot Writer
# ---------------------------------------------------------------------------


class TestGenerateSceneFallback:
    def test_empty_output_triggers_fallback(self):
        """When ReAct loop produces empty text, fallback to Writer."""
        llm = MagicMock()
        # ReAct returns submit with empty string -> text is ""
        llm.chat.side_effect = [
            _resp(_react_json("提交", "submit", {"text": ""})),
        ]
        agent = WriterReactAgent(llm)

        with patch(
            "src.novel.agents.writer.Writer"
        ) as MockWriter:
            mock_writer_instance = MagicMock()
            MockWriter.return_value = mock_writer_instance
            mock_writer_instance.generate_scene.return_value = Scene(
                scene_number=1,
                location="演武场",
                time="清晨",
                characters=["林凡"],
                goal="切磋",
                text="fallback生成的场景文本，长度足够通过检测。" * 3,
                word_count=100,
            )

            scene = agent.generate_scene(
                scene_plan=_make_scene_plan(),
                chapter_outline=_make_chapter_outline(),
                characters=[_make_character()],
                world_setting=_make_world(),
                context="前文",
                style_name="webnovel.shuangwen",
            )

            MockWriter.assert_called_once_with(llm)
            mock_writer_instance.generate_scene.assert_called_once()
            assert "fallback" in scene.text

    def test_short_output_triggers_fallback(self):
        """When output is non-empty but < 50 chars, fallback to Writer."""
        llm = MagicMock()
        # Submit with short text
        llm.chat.side_effect = [
            _resp(_react_json("提交", "submit", {"text": "太短"})),
        ]
        agent = WriterReactAgent(llm)

        with patch(
            "src.novel.agents.writer.Writer"
        ) as MockWriter:
            mock_writer_instance = MagicMock()
            MockWriter.return_value = mock_writer_instance
            mock_writer_instance.generate_scene.return_value = Scene(
                scene_number=1,
                location="演武场",
                time="清晨",
                characters=["林凡"],
                goal="切磋",
                text="fallback文本足够长度。" * 5,
                word_count=80,
            )

            scene = agent.generate_scene(
                scene_plan=_make_scene_plan(),
                chapter_outline=_make_chapter_outline(),
                characters=[_make_character()],
                world_setting=_make_world(),
                context="",
                style_name="webnovel.shuangwen",
            )

            MockWriter.assert_called_once()

    def test_dict_output_extracts_draft(self):
        """When ReAct output is a dict (from get_current_draft), extract 'draft'."""
        llm = MagicMock()
        draft_text = "这是从draft字段提取的场景文本，长度足够通过五十字符检查。" * 2
        # Simulate: generate_draft -> max iterations reached, last step is get_current_draft
        llm.chat.side_effect = [
            _resp(
                _react_json(
                    "生成", "generate_draft", {"scene_prompt": "p"}
                )
            ),
            _resp(draft_text),
            # ReAct loop step 2: no tool call -> treated as final output
            # But we need to be more precise. Let's use submit with text=""
            # and toolkit has draft set from generate_draft
            _resp(_react_json("提交", "submit", {"text": ""})),
        ]
        agent = WriterReactAgent(llm)
        scene = agent.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )
        # submit_final("") returns the internal draft
        assert scene.text == draft_text.strip()


# ---------------------------------------------------------------------------
# generate_scene - budget_mode
# ---------------------------------------------------------------------------


class TestGenerateSceneBudgetMode:
    def test_check_tools_skipped_in_budget_mode(self):
        """In budget_mode, check tools return skipped result."""
        llm = MagicMock()
        llm.chat.side_effect = [
            # Step 1: generate_draft
            _resp(
                _react_json(
                    "生成初稿",
                    "generate_draft",
                    {"scene_prompt": "场景prompt"},
                )
            ),
            # Step 2: toolkit.generate_draft calls llm.chat
            _resp(_SCENE_TEXT),
            # Step 3: try to check_repetition (will be skipped)
            _resp(
                _react_json("检查重复", "check_repetition", {})
            ),
            # Step 4: submit
            _resp(_react_json("提交", "submit", {"text": ""})),
        ]
        agent = WriterReactAgent(llm)
        scene = agent.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
            budget_mode=True,
        )
        assert isinstance(scene, Scene)
        assert len(scene.text) > 50


# ---------------------------------------------------------------------------
# generate_scene - max_iterations and context handling
# ---------------------------------------------------------------------------


class TestGenerateSceneEdgeCases:
    def test_no_characters_defaults_to_unknown(self):
        """When scene_plan has no characters, default to ['unknown']."""
        llm = MagicMock()
        llm.chat.side_effect = [
            _resp(
                _react_json(
                    "生成", "generate_draft", {"scene_prompt": "p"}
                )
            ),
            _resp(_SCENE_TEXT),
            _resp(_react_json("提交", "submit", {"text": ""})),
        ]
        agent = WriterReactAgent(llm)
        plan = _make_scene_plan()
        del plan["characters"]
        scene = agent.generate_scene(
            scene_plan=plan,
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )
        assert scene.characters == ["unknown"]

    def test_narrative_modes_from_plan(self):
        """Scene.narrative_modes should come from scene_plan."""
        llm = MagicMock()
        llm.chat.side_effect = [
            _resp(
                _react_json(
                    "生成", "generate_draft", {"scene_prompt": "p"}
                )
            ),
            _resp(_SCENE_TEXT),
            _resp(_react_json("提交", "submit", {"text": ""})),
        ]
        agent = WriterReactAgent(llm)
        plan = _make_scene_plan()
        plan["narrative_modes"] = ["对话", "动作"]
        scene = agent.generate_scene(
            scene_plan=plan,
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )
        assert scene.narrative_modes == ["对话", "动作"]

    def test_context_set_on_toolkit(self):
        """generate_scene should set context on the toolkit."""
        llm = MagicMock()
        llm.chat.side_effect = [
            _resp(
                _react_json(
                    "生成", "generate_draft", {"scene_prompt": "p"}
                )
            ),
            _resp(_SCENE_TEXT),
            _resp(_react_json("提交", "submit", {"text": ""})),
        ]
        agent = WriterReactAgent(llm)
        agent.generate_scene(
            scene_plan=_make_scene_plan(target_words=900),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="前文内容",
            style_name="webnovel.shuangwen",
        )
        assert agent.toolkit._context["target_words"] == 900
        assert len(agent.toolkit._context["characters"]) == 1

    def test_max_iterations_passed_to_run(self):
        """max_iterations parameter is forwarded to ReactAgent.run."""
        llm = MagicMock()
        # Force ReAct to submit immediately
        llm.chat.side_effect = [
            _resp(
                _react_json(
                    "生成", "generate_draft", {"scene_prompt": "p"}
                )
            ),
            _resp(_SCENE_TEXT),
            _resp(_react_json("提交", "submit", {"text": ""})),
        ]
        agent = WriterReactAgent(llm)
        with patch.object(
            agent, "run", wraps=agent.run
        ) as mock_run:
            agent.generate_scene(
                scene_plan=_make_scene_plan(),
                chapter_outline=_make_chapter_outline(),
                characters=[_make_character()],
                world_setting=_make_world(),
                context="",
                style_name="webnovel.shuangwen",
                max_iterations=10,
            )
            _, kwargs = mock_run.call_args
            assert kwargs["max_iterations"] == 10
            assert kwargs["budget_mode"] is False


# ---------------------------------------------------------------------------
# _build_scene_prompt
# ---------------------------------------------------------------------------


class TestBuildScenePrompt:
    def _build(self, **overrides):
        """Helper that creates an agent and calls _build_scene_prompt."""
        agent = WriterReactAgent(MagicMock())
        defaults = dict(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="前文回顾内容",
            style_name="webnovel.shuangwen",
            scenes_written="",
            debt_summary="",
            feedback_prompt="",
        )
        defaults.update(overrides)
        return agent._build_scene_prompt(**defaults)

    def test_contains_style_prompt(self):
        prompt = self._build()
        # webnovel.shuangwen style should be included
        assert "爽文" in prompt or "网文" in prompt or "爽点" in prompt

    def test_contains_chapter_info(self):
        prompt = self._build()
        assert "第1章" in prompt
        assert "风云突变" in prompt
        assert "主角与敌人首次交锋" in prompt

    def test_contains_world_setting(self):
        prompt = self._build()
        assert "古代" in prompt
        assert "九州大陆" in prompt
        assert "修炼需要灵石" in prompt

    def test_contains_character_info(self):
        prompt = self._build()
        assert "林凡" in prompt
        assert "男" in prompt
        assert "22" in prompt

    def test_contains_scene_plan_details(self):
        prompt = self._build()
        assert "九霄门演武场" in prompt
        assert "清晨" in prompt
        # 字数硬约束块包含目标字数 800（hard_cap=960）
        assert "字数硬约束" in prompt
        assert "目标 800" in prompt

    def test_contains_context(self):
        prompt = self._build(context="这是一段前文回顾")
        assert "前文" in prompt
        assert "这是一段前文回顾" in prompt

    def test_contains_feedback(self):
        prompt = self._build(feedback_prompt="请注意节奏加快")
        assert "请注意节奏加快" in prompt

    def test_contains_debt_summary(self):
        prompt = self._build(debt_summary="伏笔：宝剑来历需交代")
        assert "叙事义务" in prompt
        assert "宝剑来历" in prompt

    def test_contains_scenes_written(self):
        prompt = self._build(scenes_written="已写内容摘要")
        assert "禁止重复" in prompt
        assert "已写内容摘要" in prompt

    def test_no_world_setting(self):
        """When world_setting is None, prompt should not crash."""
        prompt = self._build(world_setting=None)
        assert "第1章" in prompt
        # Should NOT contain world setting section
        assert "世界观" not in prompt

    def test_no_characters(self):
        """When characters is empty, no character section."""
        prompt = self._build(characters=[])
        assert "角色" not in prompt

    def test_empty_context(self):
        """When context is empty, no 前文 section."""
        prompt = self._build(context="")
        assert "前文" not in prompt

    def test_unknown_style_fallback(self):
        """When style name is invalid, falls back to default prompt."""
        prompt = self._build(style_name="nonexistent.style")
        assert "专业小说写手" in prompt

    def test_mood_included(self):
        """Chapter mood should be included in the prompt."""
        prompt = self._build()
        assert "蓄力" in prompt

    def test_target_words_from_plan(self):
        """target_words comes from scene_plan."""
        plan = _make_scene_plan(target_words=1200)
        prompt = self._build(scene_plan=plan)
        # 字数硬约束块：目标 1200，hard_cap = 1200 * 1.2 = 1440
        assert "目标 1200" in prompt
        assert "1440" in prompt

    def test_scenes_written_truncated(self):
        """scenes_written should be truncated to 800 chars."""
        long_scenes = "已" * 1000
        prompt = self._build(scenes_written=long_scenes)
        # The prompt includes scenes_written[:800], so at most 800 "已" chars
        # We check that NOT all 1000 are present
        assert "已" * 1000 not in prompt

    def test_character_as_dict(self):
        """Characters provided as dicts (without .name attr) should work."""
        agent = WriterReactAgent(MagicMock())
        char_dict = {"name": "苏瑶", "gender": "女", "age": 20}
        prompt = agent._build_scene_prompt(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[char_dict],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
            scenes_written="",
            debt_summary="",
            feedback_prompt="",
        )
        assert "苏瑶" in prompt
        assert "女" in prompt

    def test_world_rules_limited_to_three(self):
        """Only first 3 world rules should be included."""
        world = _make_world()
        world.rules = ["规则1", "规则2", "规则3", "规则4", "规则5"]
        prompt = self._build(world_setting=world)
        assert "规则3" in prompt
        assert "规则4" not in prompt


# ---------------------------------------------------------------------------
# ReAct loop with revise step
# ---------------------------------------------------------------------------


class TestGenerateSceneWithRevise:
    def test_generate_check_revise_submit(self):
        """Full cycle: generate -> check_repetition -> revise -> submit."""
        llm = MagicMock()
        revised_text = "修改后的长篇场景正文，林凡举起长剑，迎着晨光。" * 3
        llm.chat.side_effect = [
            # ReAct step 1: generate_draft
            _resp(
                _react_json(
                    "先生成初稿",
                    "generate_draft",
                    {"scene_prompt": "场景描述"},
                )
            ),
            # toolkit.generate_draft calls llm.chat
            _resp(_SCENE_TEXT),
            # ReAct step 2: check_repetition
            _resp(
                _react_json("检查重复", "check_repetition", {})
            ),
            # ReAct step 3: revise_draft (suppose check found issues)
            _resp(
                _react_json(
                    "需要修改",
                    "revise_draft",
                    {"issues": "有重复段落", "focus": "去重"},
                )
            ),
            # toolkit.revise_draft calls llm.chat
            _resp(revised_text),
            # ReAct step 4: submit
            _resp(_react_json("提交", "submit", {"text": ""})),
        ]

        agent = WriterReactAgent(llm)
        scene = agent.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="前文",
            style_name="webnovel.shuangwen",
        )
        assert isinstance(scene, Scene)
        # After revise, draft is updated; submit("") returns the revised draft
        assert scene.text == revised_text.strip()


# ---------------------------------------------------------------------------
# ReAct loop - LLM returns non-JSON (no tool call)
# ---------------------------------------------------------------------------


class TestGenerateSceneNoToolCall:
    def test_llm_returns_plain_text(self):
        """When LLM returns non-JSON, ReAct treats it as final output."""
        plain_text = "这是一段足够长的纯文本输出，没有包含任何JSON格式的工具调用指令。" * 3
        llm = MagicMock()
        llm.chat.side_effect = [
            _resp(plain_text),
        ]
        agent = WriterReactAgent(llm)
        scene = agent.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )
        assert isinstance(scene, Scene)
        assert scene.text == plain_text.strip()


# ---------------------------------------------------------------------------
# generate_scene - dict output from ReactResult
# ---------------------------------------------------------------------------


class TestGenerateSceneDictOutput:
    def test_dict_with_draft_key(self):
        """When ReactResult.output is a dict with 'draft', extract it."""
        llm = MagicMock()
        draft_content = "从字典中提取的草稿文本内容，需要足够长才能通过检查。" * 3
        # Simulate: get_current_draft as last step before max_iterations
        llm.chat.side_effect = [
            # Step 1: get_current_draft (which returns a dict)
            _resp(
                _react_json("查看草稿", "get_current_draft", {})
            ),
        ] * 5 + [
            # After max iterations, output will be the last step result
            # which is a dict {"draft": "...", "word_count": N}
        ]

        # Easier approach: patch self.run to return a dict output directly
        agent = WriterReactAgent(llm)
        from src.react.agent import ReactResult

        with patch.object(
            agent,
            "run",
            return_value=ReactResult(
                output={"draft": draft_content, "word_count": 100},
                steps=[],
                total_steps=1,
                total_tokens=50,
                finished=True,
            ),
        ):
            scene = agent.generate_scene(
                scene_plan=_make_scene_plan(),
                chapter_outline=_make_chapter_outline(),
                characters=[_make_character()],
                world_setting=_make_world(),
                context="",
                style_name="webnovel.shuangwen",
            )
            assert scene.text == draft_content

    def test_dict_with_text_key(self):
        """When ReactResult.output is a dict with 'text', extract it."""
        agent = WriterReactAgent(MagicMock())
        text_content = "从text字段提取的内容，足够长度。" * 5
        from src.react.agent import ReactResult

        with patch.object(
            agent,
            "run",
            return_value=ReactResult(
                output={"text": text_content},
                steps=[],
                total_steps=1,
                total_tokens=50,
                finished=True,
            ),
        ):
            scene = agent.generate_scene(
                scene_plan=_make_scene_plan(),
                chapter_outline=_make_chapter_outline(),
                characters=[_make_character()],
                world_setting=_make_world(),
                context="",
                style_name="webnovel.shuangwen",
            )
            assert scene.text == text_content

    def test_dict_without_draft_or_text_triggers_fallback(self):
        """Dict without 'draft' or 'text' -> empty string -> fallback."""
        agent = WriterReactAgent(MagicMock())
        from src.react.agent import ReactResult

        with patch.object(
            agent,
            "run",
            return_value=ReactResult(
                output={"other_key": "value"},
                steps=[],
                total_steps=1,
                total_tokens=50,
                finished=True,
            ),
        ):
            with patch(
                "src.novel.agents.writer.Writer"
            ) as MockWriter:
                mock_writer = MagicMock()
                MockWriter.return_value = mock_writer
                mock_writer.generate_scene.return_value = Scene(
                    scene_number=1,
                    location="loc",
                    time="time",
                    characters=["c"],
                    goal="g",
                    text="fallback output" * 10,
                    word_count=100,
                )

                scene = agent.generate_scene(
                    scene_plan=_make_scene_plan(),
                    chapter_outline=_make_chapter_outline(),
                    characters=[_make_character()],
                    world_setting=_make_world(),
                    context="",
                    style_name="webnovel.shuangwen",
                )
                MockWriter.assert_called_once()


# ---------------------------------------------------------------------------
# generate_scene - None output
# ---------------------------------------------------------------------------


class TestGenerateSceneNoneOutput:
    def test_none_output_triggers_fallback(self):
        """When ReactResult.output is None, fallback to Writer."""
        agent = WriterReactAgent(MagicMock())
        from src.react.agent import ReactResult

        with patch.object(
            agent,
            "run",
            return_value=ReactResult(
                output=None,
                steps=[],
                total_steps=0,
                total_tokens=0,
                finished=False,
            ),
        ):
            with patch(
                "src.novel.agents.writer.Writer"
            ) as MockWriter:
                mock_writer = MagicMock()
                MockWriter.return_value = mock_writer
                mock_writer.generate_scene.return_value = Scene(
                    scene_number=1,
                    location="loc",
                    time="time",
                    characters=["c"],
                    goal="g",
                    text="fallback" * 20,
                    word_count=100,
                )

                scene = agent.generate_scene(
                    scene_plan=_make_scene_plan(),
                    chapter_outline=_make_chapter_outline(),
                    characters=[_make_character()],
                    world_setting=_make_world(),
                    context="",
                    style_name="webnovel.shuangwen",
                )
                MockWriter.assert_called_once()
