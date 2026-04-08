"""Tests for HookGenerator."""
import pytest
from unittest.mock import MagicMock
from src.novel.services.hook_generator import HookGenerator


@pytest.fixture
def hg():
    return HookGenerator()


class TestHookEvaluation:
    def test_strong_hook_question(self, hg):
        text = "林辰看着远处的山影。\n\n那里，到底藏着什么？"
        result = hg.evaluate(text)
        assert result["score"] >= 6
        assert result["hook_type"] in ("question", "strong")
        assert not result["needs_improvement"]

    def test_strong_hook_sudden_event(self, hg):
        text = "林辰刚要转身离开。\n\n突然，身后传来一声闷响！"
        result = hg.evaluate(text)
        assert result["score"] >= 6
        assert result["hook_type"] == "sudden_event"

    def test_weak_ending_rest(self, hg):
        text = "战斗结束了。\n\n林辰回到营地，安歇休息。"
        result = hg.evaluate(text)
        assert result["score"] < 6
        assert result["needs_improvement"]
        assert any("平淡" in i for i in result["issues"])

    def test_weak_ending_summary(self, hg):
        text = "矿场恢复了平静。\n\n于是众人各自回营，等待天亮。"
        result = hg.evaluate(text)
        assert result["score"] < 6

    def test_ellipsis_mystery(self, hg):
        text = "他望向夜色深处，眼底闪过一丝复杂。\n\n那个人，会是她吗……"
        result = hg.evaluate(text)
        assert result["score"] >= 6
        assert result["hook_type"] == "ellipsis_mystery"

    def test_empty_chapter(self, hg):
        result = hg.evaluate("")
        assert result["score"] == 0
        assert result["hook_type"] == "none"
        assert result["needs_improvement"]

    def test_suspense_words_boost(self, hg):
        text = "他握紧剑柄。\n\n暗影中，杀机已经悄然逼近。"
        result = hg.evaluate(text)
        assert result["score"] >= 6


class TestHookGeneration:
    def test_no_llm_returns_none(self, hg):
        result = hg.generate_hook("some text" * 50, 5, "推进主线")
        assert result is None

    def test_with_llm(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "突然，一道黑影从屋顶掠过，林辰瞳孔骤缩。"
        mock_llm.chat.return_value = mock_response

        hg = HookGenerator(llm_client=mock_llm)
        # Need >200 chars
        text = "林辰回到营地，士兵们正在休息。" * 20
        result = hg.generate_hook(text, 5, "推进主线")
        assert result == "突然，一道黑影从屋顶掠过，林辰瞳孔骤缩。"
        mock_llm.chat.assert_called_once()

    def test_llm_failure_returns_none(self):
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("API error")

        hg = HookGenerator(llm_client=mock_llm)
        text = "林辰回到营地。" * 30
        result = hg.generate_hook(text, 5, "目标")
        assert result is None

    def test_short_text_returns_none(self):
        mock_llm = MagicMock()
        hg = HookGenerator(llm_client=mock_llm)
        result = hg.generate_hook("太短", 5, "目标")
        assert result is None


class TestReplaceEnding:
    def test_replace_at_paragraph_break(self, hg):
        text = "段一内容。\n\n段二内容。\n\n旧的最后一段。"
        new_ending = "新的悬念结尾！"
        result = hg.replace_ending(text, new_ending)
        assert "段一内容" in result
        assert "段二内容" in result
        assert "旧的最后一段" not in result
        assert "新的悬念结尾" in result

    def test_replace_no_paragraph_break(self, hg):
        text = "一段没有换行的连续内容" * 10
        new_ending = "新结尾。"
        result = hg.replace_ending(text, new_ending)
        assert "新结尾" in result
        assert len(result) <= len(text) + len(new_ending)

    def test_empty_inputs(self, hg):
        assert hg.replace_ending("", "new") == ""
        assert hg.replace_ending("text", "") == "text"
