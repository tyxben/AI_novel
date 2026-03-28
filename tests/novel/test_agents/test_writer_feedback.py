"""Test that feedback_prompt is injected into the one-shot Writer branch.

Verifies that when generate_scene() is called with a non-empty feedback_prompt
in non-ReAct mode, the feedback text appears in the messages sent to the LLM.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.llm.llm_client import LLMResponse
from src.novel.agents.writer import Writer
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


def _make_llm(text: str = "他拔出长剑，目光如炬，直视前方的敌人。") -> MagicMock:
    client = MagicMock()
    client.chat.return_value = LLMResponse(content=text, model="mock-model")
    return client


def _make_chapter_outline() -> ChapterOutline:
    return ChapterOutline(
        chapter_number=1,
        title="风云突变",
        goal="主角与敌人首次交锋",
        key_events=["遭遇敌人", "激烈战斗"],
        involved_characters=["char_1"],
        estimated_words=3000,
        mood="蓄力",
    )


def _make_character() -> CharacterProfile:
    return CharacterProfile(
        name="林凡",
        gender="男",
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
            catchphrases=["哼"],
        ),
    )


def _make_world() -> WorldSetting:
    return WorldSetting(
        era="古代",
        location="九州大陆",
        power_system=PowerSystem(
            name="修炼境界",
            levels=[
                PowerLevel(rank=1, name="炼气期", description="初入修炼", typical_abilities=["基础剑术"]),
            ],
        ),
    )


def _make_scene_plan() -> dict:
    return {
        "scene_number": 1,
        "location": "九霄门演武场",
        "time": "清晨",
        "characters": ["林凡"],
        "goal": "主角修炼",
        "mood": "蓄力",
        "target_words": 800,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFeedbackPromptInjection:
    """Ensure feedback_prompt is injected into the one-shot (non-ReAct) path."""

    def test_feedback_prompt_appears_in_llm_messages(self) -> None:
        """When feedback_prompt is provided, its text must appear in the
        user message sent to the LLM in the one-shot branch."""
        llm = _make_llm()
        writer = Writer(llm)

        feedback_text = "第3章节奏太慢，需要加快叙事节奏并减少重复描写"

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="前文内容",
            style_name="webnovel.shuangwen",
            react_mode=False,
            feedback_prompt=feedback_text,
        )

        # LLM.chat should have been called at least once
        assert llm.chat.call_count >= 1

        # Extract the messages from the first call
        call_args = llm.chat.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]

        # Find the user message(s) and check feedback text is present
        user_messages = [m["content"] for m in messages if m["role"] == "user"]
        assert len(user_messages) > 0, "No user messages found in LLM call"

        combined = "\n".join(user_messages)
        assert feedback_text in combined, (
            f"feedback_prompt not found in user messages. Got:\n{combined[:500]}"
        )
        assert "前文质量反馈" in combined, (
            "Feedback section header not found in user messages"
        )

    def test_no_feedback_section_when_empty(self) -> None:
        """When feedback_prompt is empty, no feedback section should appear."""
        llm = _make_llm()
        writer = Writer(llm)

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="前文内容",
            style_name="webnovel.shuangwen",
            react_mode=False,
            feedback_prompt="",
        )

        assert llm.chat.call_count >= 1

        call_args = llm.chat.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]
        user_messages = [m["content"] for m in messages if m["role"] == "user"]
        combined = "\n".join(user_messages)

        assert "前文质量反馈" not in combined, (
            "Feedback section should not appear when feedback_prompt is empty"
        )

    def test_feedback_appears_before_scene_info(self) -> None:
        """feedback_prompt should be injected before the scene info block."""
        llm = _make_llm()
        writer = Writer(llm)

        feedback_text = "对话太生硬需要改进"

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
            react_mode=False,
            feedback_prompt=feedback_text,
        )

        call_args = llm.chat.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]
        user_messages = [m["content"] for m in messages if m["role"] == "user"]
        combined = "\n".join(user_messages)

        feedback_pos = combined.find("前文质量反馈")
        scene_info_pos = combined.find("【场景信息】")
        assert feedback_pos >= 0, "Feedback section not found"
        assert scene_info_pos >= 0, "Scene info section not found"
        assert feedback_pos < scene_info_pos, (
            "Feedback section should appear BEFORE scene info"
        )
