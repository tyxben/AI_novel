"""Tests for LLM truncation detection + auto-continuation in Writer.

Covers:
- LLMResponse.finish_reason field
- Writer._continue_if_truncated helper
- generate_scene continuation on truncation
- rewrite_chapter continuation on truncation
- polish_chapter continuation on truncation
- No continuation when finish_reason != "length"
- Max continuation limit respected
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, call

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.writer import Writer, _MAX_CONTINUATIONS
from src.novel.models.chapter import Scene
from src.novel.models.character import CharacterProfile
from src.novel.models.novel import ChapterOutline
from src.novel.models.world import WorldSetting


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(content: str, finish_reason: str = "stop") -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test-model",
        usage={"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60},
        finish_reason=finish_reason,
    )


def _make_writer(side_effects: list[LLMResponse]) -> Writer:
    """Create a Writer with a mock LLM that returns responses in order."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = side_effects
    return Writer(mock_llm)


def _minimal_chapter_outline(chapter_number: int = 1) -> ChapterOutline:
    return ChapterOutline(
        chapter_number=chapter_number,
        title="测试章节",
        goal="推进情节",
        key_events=["事件A"],
        involved_characters=["主角"],
        plot_threads=[],
        estimated_words=2500,
        mood="蓄力",
    )


def _minimal_world() -> WorldSetting:
    return WorldSetting(
        era="现代",
        location="城市",
        rules=["无超能力"],
        terms={},
    )


def _minimal_character() -> CharacterProfile:
    return CharacterProfile(
        name="张三",
        gender="男",
        age=25,
        occupation="工程师",
        appearance={
            "height": "175cm",
            "build": "匀称",
            "hair": "黑色短发",
            "eyes": "黑色",
            "clothing_style": "休闲装",
        },
        personality={
            "traits": ["勇敢", "坚韧", "善良"],
            "core_belief": "正义必胜",
            "motivation": "保护家人",
            "flaw": "冲动",
            "speech_style": "简洁有力",
        },
    )


# ---------------------------------------------------------------------------
# LLMResponse.finish_reason
# ---------------------------------------------------------------------------


class TestLLMResponseFinishReason:
    def test_default_none(self):
        r = LLMResponse(content="hi", model="m")
        assert r.finish_reason is None

    def test_stop(self):
        r = LLMResponse(content="hi", model="m", finish_reason="stop")
        assert r.finish_reason == "stop"

    def test_length(self):
        r = LLMResponse(content="hi", model="m", finish_reason="length")
        assert r.finish_reason == "length"


# ---------------------------------------------------------------------------
# _continue_if_truncated
# ---------------------------------------------------------------------------


class TestContinueIfTruncated:
    def test_no_continuation_on_stop(self):
        """finish_reason='stop' should return content as-is."""
        writer = _make_writer([])
        response = _make_response("完整的文本。", "stop")
        messages = [{"role": "user", "content": "test"}]

        result = writer._continue_if_truncated(response, messages, 0.85, 4096)

        assert result == "完整的文本。"
        writer.llm.chat.assert_not_called()

    def test_no_continuation_on_none(self):
        """finish_reason=None should return content as-is."""
        writer = _make_writer([])
        response = _make_response("完整的文本。", finish_reason="stop")
        response.finish_reason = None
        messages = [{"role": "user", "content": "test"}]

        result = writer._continue_if_truncated(response, messages, 0.85, 4096)

        assert result == "完整的文本。"
        writer.llm.chat.assert_not_called()

    def test_single_continuation(self):
        """Truncated response followed by a complete continuation."""
        cont_response = _make_response("续写的结尾部分。", "stop")
        writer = _make_writer([cont_response])
        initial = _make_response("被截断的文本", "length")
        messages = [{"role": "user", "content": "test"}]

        result = writer._continue_if_truncated(initial, messages, 0.85, 4096)

        assert result == "被截断的文本续写的结尾部分。"
        assert writer.llm.chat.call_count == 1

    def test_multiple_continuations(self):
        """Truncated twice, then completes on third try."""
        responses = [
            _make_response("第二段", "length"),
            _make_response("最终结尾。", "stop"),
        ]
        writer = _make_writer(responses)
        initial = _make_response("第一段", "length")
        messages = [{"role": "user", "content": "test"}]

        result = writer._continue_if_truncated(initial, messages, 0.85, 4096)

        assert result == "第一段第二段最终结尾。"
        assert writer.llm.chat.call_count == 2

    def test_max_continuations_limit(self):
        """Should stop after _MAX_CONTINUATIONS even if still truncated."""
        # All continuations also truncated
        responses = [
            _make_response(f"续写{i}", "length")
            for i in range(1, _MAX_CONTINUATIONS + 2)
        ]
        writer = _make_writer(responses)
        initial = _make_response("起始", "length")
        messages = [{"role": "user", "content": "test"}]

        result = writer._continue_if_truncated(initial, messages, 0.85, 4096)

        assert writer.llm.chat.call_count == _MAX_CONTINUATIONS
        assert result.startswith("起始续写1")

    def test_empty_continuation_stops(self):
        """Empty continuation response should stop the loop."""
        cont_response = _make_response("", "stop")
        writer = _make_writer([cont_response])
        initial = _make_response("被截断", "length")
        messages = [{"role": "user", "content": "test"}]

        result = writer._continue_if_truncated(initial, messages, 0.85, 4096)

        assert result == "被截断"
        assert writer.llm.chat.call_count == 1

    def test_continuation_messages_structure(self):
        """Verify that continuation messages include assistant + user continuation."""
        cont_response = _make_response("尾部。", "stop")
        writer = _make_writer([cont_response])
        initial = _make_response("前半段", "length")
        original_messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "usr"},
        ]

        writer._continue_if_truncated(initial, original_messages, 0.85, 4096)

        call_args = writer.llm.chat.call_args
        passed_messages = call_args[0][0]  # first positional arg
        # Should have: system, user, assistant(前半段), user(续写指令)
        assert len(passed_messages) == 4
        assert passed_messages[0]["role"] == "system"
        assert passed_messages[1]["role"] == "user"
        assert passed_messages[2]["role"] == "assistant"
        assert passed_messages[2]["content"] == "前半段"
        assert passed_messages[3]["role"] == "user"
        assert "续写" in passed_messages[3]["content"] or "截断" in passed_messages[3]["content"]


# ---------------------------------------------------------------------------
# generate_scene with continuation
# ---------------------------------------------------------------------------


class TestGenerateSceneContinuation:
    def test_scene_no_truncation(self):
        """Normal scene generation without truncation."""
        response = _make_response("场景正文。" * 50, "stop")
        writer = _make_writer([response])

        scene = writer.generate_scene(
            scene_plan={"scene_number": 1, "target_words": 800, "location": "森林", "time": "夜"},
            chapter_outline=_minimal_chapter_outline(),
            characters=[_minimal_character()],
            world_setting=_minimal_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        assert scene.text == response.content.strip()
        assert writer.llm.chat.call_count == 1

    def test_scene_with_continuation(self):
        """Scene that gets truncated should be continued."""
        responses = [
            _make_response("场景开头，张三走进了森林", "length"),
            _make_response("张三看到了一棵巨大的古树。", "stop"),
        ]
        writer = _make_writer(responses)

        scene = writer.generate_scene(
            scene_plan={"scene_number": 1, "target_words": 800, "location": "森林", "time": "夜"},
            chapter_outline=_minimal_chapter_outline(),
            characters=[_minimal_character()],
            world_setting=_minimal_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        assert "场景开头" in scene.text
        assert "古树" in scene.text
        assert writer.llm.chat.call_count == 2  # initial + 1 continuation


# ---------------------------------------------------------------------------
# rewrite_chapter with continuation
# ---------------------------------------------------------------------------


class TestRewriteChapterContinuation:
    def test_rewrite_with_continuation(self):
        """Rewrite that gets truncated should be continued."""
        responses = [
            _make_response("重写开头部分", "length"),
            _make_response("重写结尾部分。", "stop"),
        ]
        writer = _make_writer(responses)

        result = writer.rewrite_chapter(
            original_text="原始文本",
            rewrite_instruction="加强冲突",
            chapter_outline=_minimal_chapter_outline(),
            characters=[_minimal_character()],
            world_setting=_minimal_world(),
            context="前文",
            style_name="webnovel.shuangwen",
        )

        assert "重写开头部分" in result
        assert "重写结尾部分" in result
        assert writer.llm.chat.call_count == 2


# ---------------------------------------------------------------------------
# polish_chapter with continuation
# ---------------------------------------------------------------------------


class TestPolishChapterContinuation:
    def test_polish_with_continuation(self):
        """Polish that gets truncated should be continued."""
        responses = [
            _make_response("精修开头部分", "length"),
            _make_response("精修结尾部分。", "stop"),
        ]
        writer = _make_writer(responses)

        result = writer.polish_chapter(
            chapter_text="原文",
            critique="【问题1】类型：重复\n位置：第1段\n问题：重复\n建议：删除",
            chapter_outline=_minimal_chapter_outline(),
            characters=[_minimal_character()],
            world_setting=_minimal_world(),
            context="前文",
            style_name="webnovel.shuangwen",
        )

        assert "精修开头部分" in result
        assert "精修结尾部分" in result
        assert writer.llm.chat.call_count == 2

    def test_polish_skip_if_passed(self):
        """Polish should skip if critique says 审稿通过."""
        writer = _make_writer([])

        result = writer.polish_chapter(
            chapter_text="原文不动",
            critique="审稿通过，无需修改",
            chapter_outline=_minimal_chapter_outline(),
            characters=[_minimal_character()],
            world_setting=_minimal_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        assert result == "原文不动"
        writer.llm.chat.assert_not_called()


# ---------------------------------------------------------------------------
# max_tokens value
# ---------------------------------------------------------------------------


class TestMaxTokensIncreased:
    def test_scene_max_tokens(self):
        """generate_scene should use max(6144, target_words * 3)."""
        response = _make_response("正文。", "stop")
        writer = _make_writer([response])

        writer.generate_scene(
            scene_plan={"scene_number": 1, "target_words": 800, "location": "城市", "time": "日"},
            chapter_outline=_minimal_chapter_outline(),
            characters=[_minimal_character()],
            world_setting=_minimal_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        call_kwargs = writer.llm.chat.call_args
        # max_tokens should be max(6144, 800*3) = 6144
        assert call_kwargs.kwargs.get("max_tokens", call_kwargs[1].get("max_tokens")) == 6144

    def test_scene_max_tokens_large_target(self):
        """For large target_words, max_tokens = target_words * 3."""
        response = _make_response("正文。", "stop")
        writer = _make_writer([response])

        writer.generate_scene(
            scene_plan={"scene_number": 1, "target_words": 3000, "location": "城市", "time": "日"},
            chapter_outline=_minimal_chapter_outline(),
            characters=[_minimal_character()],
            world_setting=_minimal_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        call_kwargs = writer.llm.chat.call_args
        # max_tokens should be min(8192, max(6144, 3000*3)) = 8192 (clamped)
        assert call_kwargs.kwargs.get("max_tokens", call_kwargs[1].get("max_tokens")) == 8192
