"""WriterToolkit 单元测试

覆盖:
- set_context: 更新上下文、覆盖已有键、保留不相关键
- generate_draft: 基本调用、内部状态、字数统计、preview截断、max_tokens计算、
                  默认target_words、LLM消息参数、temperature值、空白文本strip
- check_repetition: 无重复、有重复、无前文、空草稿、高重复率触发 has_issues、
                    仅短句(<6字)忽略、only-prev无current
- check_character_names: 合法名称、占位符检测、无角色、无草稿、alias、dict角色、
                         多个角色合并名称、混合占位符
- check_narrative_logic: 无问题、有问题、JSON 解析失败、空草稿、LLM调用参数验证、
                         前文截断
- revise_draft: 基本修改、无草稿错误、with focus、max_tokens与generate一致
- submit_final: 使用草稿、使用传入文本、空文本回退草稿
- get_current_draft: 空状态、有草稿
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.tools.react_writer_tools import WriterToolkit


def _resp(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, model="test", usage={"total_tokens": 50}
    )


# -------------------------------------------------------------------------
# set_context
# -------------------------------------------------------------------------


class TestSetContext:
    def test_basic_set(self):
        tk = WriterToolkit(MagicMock())
        tk.set_context(target_words=800, characters=["a"])
        assert tk._context["target_words"] == 800
        assert tk._context["characters"] == ["a"]

    def test_overwrite_existing_key(self):
        tk = WriterToolkit(MagicMock())
        tk.set_context(target_words=800)
        tk.set_context(target_words=1200)
        assert tk._context["target_words"] == 1200

    def test_preserves_unrelated_keys(self):
        tk = WriterToolkit(MagicMock())
        tk.set_context(target_words=800)
        tk.set_context(previous_text="some text")
        assert tk._context["target_words"] == 800
        assert tk._context["previous_text"] == "some text"

    def test_empty_call_no_change(self):
        tk = WriterToolkit(MagicMock())
        tk.set_context(target_words=800)
        tk.set_context()  # no kwargs
        assert tk._context == {"target_words": 800}


# -------------------------------------------------------------------------
# generate_draft
# -------------------------------------------------------------------------


class TestGenerateDraft:
    def test_basic(self):
        llm = MagicMock()
        llm.chat.return_value = _resp("生成的正文内容。" * 20)
        tk = WriterToolkit(llm)
        tk.set_context(target_words=800)
        result = tk.generate_draft("prompt")
        assert "word_count" in result
        assert result["word_count"] > 0
        assert tk._draft != ""
        llm.chat.assert_called_once()

    def test_sets_internal_draft(self):
        llm = MagicMock()
        llm.chat.return_value = _resp("内容ABC")
        tk = WriterToolkit(llm)
        tk.generate_draft("p")
        assert tk._draft == "内容ABC"

    def test_preview_truncation(self):
        """Draft longer than 500 chars should have truncated preview."""
        llm = MagicMock()
        long_text = "字" * 600
        llm.chat.return_value = _resp(long_text)
        tk = WriterToolkit(llm)
        result = tk.generate_draft("p")
        assert result["draft_preview"].endswith("...")
        assert len(result["draft_preview"]) == 503  # 500 + "..."

    def test_max_tokens_calculation(self):
        """max_tokens should use formula min(4096, max(900, target*1.4))."""
        llm = MagicMock()
        llm.chat.return_value = _resp("ok")
        tk = WriterToolkit(llm)

        # target=100 → max(900, 140) = 900
        tk.set_context(target_words=100)
        tk.generate_draft("p")
        _, kwargs = llm.chat.call_args
        assert kwargs["max_tokens"] == 900

        # target=800 → max(900, 1120) = 1120
        tk.set_context(target_words=800)
        tk.generate_draft("p")
        _, kwargs = llm.chat.call_args
        assert kwargs["max_tokens"] == 1120

        # target=5000 → min(4096, 7000) = 4096
        tk.set_context(target_words=5000)
        tk.generate_draft("p")
        _, kwargs = llm.chat.call_args
        assert kwargs["max_tokens"] == 4096

    def test_default_target_words(self):
        """When target_words is not set in context, defaults to 800."""
        llm = MagicMock()
        llm.chat.return_value = _resp("content")
        tk = WriterToolkit(llm)
        result = tk.generate_draft("p")
        assert result["target_words"] == 800

    def test_chat_messages_structure(self):
        """Verify the messages sent to LLM have correct structure."""
        llm = MagicMock()
        llm.chat.return_value = _resp("content")
        tk = WriterToolkit(llm)
        tk.generate_draft("my scene prompt")
        args, kwargs = llm.chat.call_args
        messages = args[0]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "my scene prompt"
        assert messages[1]["role"] == "user"
        assert kwargs["temperature"] == 0.85

    def test_strips_whitespace(self):
        """LLM response with leading/trailing whitespace is stripped."""
        llm = MagicMock()
        llm.chat.return_value = _resp("  内容  \n")
        tk = WriterToolkit(llm)
        tk.generate_draft("p")
        assert tk._draft == "内容"

    def test_short_draft_no_ellipsis(self):
        """Draft shorter than 500 chars should not have ellipsis."""
        llm = MagicMock()
        llm.chat.return_value = _resp("短文")
        tk = WriterToolkit(llm)
        result = tk.generate_draft("p")
        assert "..." not in result["draft_preview"]
        assert result["draft_preview"] == "短文"


# -------------------------------------------------------------------------
# check_repetition
# -------------------------------------------------------------------------


class TestCheckRepetition:
    def test_no_overlap(self):
        tk = WriterToolkit(MagicMock())
        tk._draft = "完全不同的句子在这里出现。另一个句子也不同的内容。"
        tk.set_context(previous_text="前文内容完全不一样的文字。前文另一句独立的。")
        r = tk.check_repetition()
        assert r["has_issues"] is False

    def test_with_overlap(self):
        tk = WriterToolkit(MagicMock())
        sent = "这是一个重复的句子有六个字以上。"
        tk._draft = f"{sent}还有一些不同的内容在这里。"
        tk.set_context(previous_text=f"{sent}前文独有句子在这里。")
        r = tk.check_repetition()
        assert len(r["repeated_sentences"]) > 0

    def test_no_previous(self):
        tk = WriterToolkit(MagicMock())
        tk._draft = "some text here"
        r = tk.check_repetition()
        assert r["has_issues"] is False
        assert "无前文" in r.get("details", "")

    def test_empty_draft(self):
        tk = WriterToolkit(MagicMock())
        tk.set_context(previous_text="前文")
        r = tk.check_repetition()
        assert r["has_issues"] is False

    def test_high_overlap_triggers_issue(self):
        """When >30% sentences overlap, has_issues should be True."""
        tk = WriterToolkit(MagicMock())
        shared = "这个句子在两段中都出现了。第二个共同的句子也在这里。第三个共同句子还是重复了。"
        tk._draft = shared + "唯一的新句子在草稿里面。"
        tk.set_context(previous_text=shared + "前文里的独有句子。")
        r = tk.check_repetition()
        # 3 out of 4 sentences overlap → 75% > 30%
        assert r["has_issues"] is True
        assert r["overlap_ratio"] > 0.3

    def test_short_sentences_ignored(self):
        """Sentences with <= 5 chars are filtered out."""
        tk = WriterToolkit(MagicMock())
        tk._draft = "短。短短。一个比较长的句子在这里出现。"
        tk.set_context(previous_text="短。短短。完全不同内容的长句子。")
        r = tk.check_repetition()
        # "短" and "短短" are <= 5 chars, ignored
        assert r["has_issues"] is False

    def test_repeated_sentences_capped_at_five(self):
        """repeated_sentences list should be capped at 5 items."""
        tk = WriterToolkit(MagicMock())
        sents = [f"这是第{i}个重复句子在文本中出现。" for i in range(10)]
        tk._draft = "。".join(sents)
        tk.set_context(previous_text="。".join(sents))
        r = tk.check_repetition()
        assert len(r["repeated_sentences"]) <= 5


# -------------------------------------------------------------------------
# check_character_names
# -------------------------------------------------------------------------


class TestCheckNames:
    def test_valid(self):
        tk = WriterToolkit(MagicMock())
        tk._draft = "林辰走了过去，看着远方的天空。"

        class FakeChar:
            name = "林辰"
            alias = []

        tk.set_context(characters=[FakeChar()])
        r = tk.check_character_names()
        assert r["has_issues"] is False

    def test_placeholder(self):
        tk = WriterToolkit(MagicMock())
        tk._draft = "角色A走了过去。男子甲也来了。"

        class FakeChar:
            name = "林辰"
            alias = []

        tk.set_context(characters=[FakeChar()])
        r = tk.check_character_names()
        assert r["has_issues"] is True
        assert len(r["issues"]) > 0

    def test_no_characters(self):
        tk = WriterToolkit(MagicMock())
        tk._draft = "一些正文。"
        r = tk.check_character_names()
        assert r["has_issues"] is False

    def test_no_draft(self):
        tk = WriterToolkit(MagicMock())

        class FakeChar:
            name = "林辰"
            alias = []

        tk.set_context(characters=[FakeChar()])
        r = tk.check_character_names()
        assert r["has_issues"] is False

    def test_alias_in_valid_names(self):
        tk = WriterToolkit(MagicMock())
        tk._draft = "小辰走了过去。"

        class FakeChar:
            name = "林辰"
            alias = ["小辰"]

        tk.set_context(characters=[FakeChar()])
        r = tk.check_character_names()
        assert "小辰" in r["valid_names"]

    def test_dict_characters(self):
        """Characters provided as dicts instead of objects."""
        tk = WriterToolkit(MagicMock())
        tk._draft = "林辰走了过去。"
        tk.set_context(
            characters=[{"name": "林辰", "alias": ["小辰"]}]
        )
        r = tk.check_character_names()
        assert "林辰" in r["valid_names"]
        assert "小辰" in r["valid_names"]

    def test_multiple_characters_merged(self):
        """Valid names from multiple characters are merged."""
        tk = WriterToolkit(MagicMock())
        tk._draft = "林辰和苏瑶走了过去。"

        class Char1:
            name = "林辰"
            alias = []

        class Char2:
            name = "苏瑶"
            alias = ["瑶儿"]

        tk.set_context(characters=[Char1(), Char2()])
        r = tk.check_character_names()
        assert "林辰" in r["valid_names"]
        assert "苏瑶" in r["valid_names"]
        assert "瑶儿" in r["valid_names"]

    def test_dict_with_empty_name(self):
        """Dict character with empty name should not add empty string."""
        tk = WriterToolkit(MagicMock())
        tk._draft = "角色A走了过去。"
        tk.set_context(characters=[{"name": "", "alias": []}])
        r = tk.check_character_names()
        assert "" not in r.get("valid_names", [])

    def test_multiple_placeholder_types(self):
        """Detect various placeholder patterns: 角色A, 人物B, 男子甲, 女子乙."""
        tk = WriterToolkit(MagicMock())
        tk._draft = "角色A在这里。人物B也来了。女子乙走过来。"

        class FakeChar:
            name = "林辰"
            alias = []

        tk.set_context(characters=[FakeChar()])
        r = tk.check_character_names()
        assert r["has_issues"] is True


# -------------------------------------------------------------------------
# check_narrative_logic
# -------------------------------------------------------------------------


class TestNarrativeLogic:
    def test_no_issues(self):
        llm = MagicMock()
        llm.chat.return_value = _resp('{"issues": [], "score": 9.0}')
        tk = WriterToolkit(llm)
        tk._draft = "一些正文内容在这里。"
        r = tk.check_narrative_logic()
        assert r["has_issues"] is False
        assert r["score"] == 9.0

    def test_with_issues(self):
        llm = MagicMock()
        llm.chat.return_value = _resp(
            '{"issues": ["角色消失"], "score": 5.0}'
        )
        tk = WriterToolkit(llm)
        tk._draft = "正文"
        r = tk.check_narrative_logic()
        assert r["has_issues"] is True
        assert "角色消失" in r["issues"]

    def test_json_parse_failure(self):
        llm = MagicMock()
        llm.chat.return_value = _resp("not valid json at all")
        tk = WriterToolkit(llm)
        tk._draft = "正文"
        r = tk.check_narrative_logic()
        assert r["has_issues"] is False
        assert r["score"] == 7.0

    def test_empty_draft(self):
        tk = WriterToolkit(MagicMock())
        r = tk.check_narrative_logic()
        assert r["has_issues"] is False

    def test_llm_params(self):
        """Verify LLM is called with json_mode=True and temperature=0.2."""
        llm = MagicMock()
        llm.chat.return_value = _resp('{"issues": [], "score": 8.0}')
        tk = WriterToolkit(llm)
        tk._draft = "正文内容"
        tk.check_narrative_logic()
        _, kwargs = llm.chat.call_args
        assert kwargs["temperature"] == 0.2
        assert kwargs["json_mode"] is True
        assert kwargs["max_tokens"] == 512

    def test_previous_text_truncated_in_prompt(self):
        """Previous text in context is truncated to 500 chars."""
        llm = MagicMock()
        llm.chat.return_value = _resp('{"issues": [], "score": 8.0}')
        tk = WriterToolkit(llm)
        tk._draft = "正文"
        long_prev = "前" * 1000
        tk.set_context(previous_text=long_prev)
        tk.check_narrative_logic()
        args, _ = llm.chat.call_args
        prompt_text = args[0][0]["content"]
        # The previous text in the prompt should be at most 500 chars of the original
        assert "前" * 500 in prompt_text
        assert "前" * 501 not in prompt_text

    def test_missing_score_defaults_to_seven(self):
        """When LLM returns JSON without score field, default to 7.0."""
        llm = MagicMock()
        llm.chat.return_value = _resp('{"issues": ["问题1"]}')
        tk = WriterToolkit(llm)
        tk._draft = "正文"
        r = tk.check_narrative_logic()
        assert r["score"] == 7.0
        assert r["has_issues"] is True


# -------------------------------------------------------------------------
# revise_draft
# -------------------------------------------------------------------------


class TestRevise:
    def test_basic(self):
        llm = MagicMock()
        llm.chat.return_value = _resp("修改后的正文。")
        tk = WriterToolkit(llm)
        tk._draft = "原始正文"
        r = tk.revise_draft(issues="对话重复")
        assert r["word_count"] > 0
        assert tk._draft == "修改后的正文。"

    def test_no_draft(self):
        tk = WriterToolkit(MagicMock())
        r = tk.revise_draft(issues="问题")
        assert "error" in r

    def test_with_focus(self):
        llm = MagicMock()
        llm.chat.return_value = _resp("带焦点修改。")
        tk = WriterToolkit(llm)
        tk._draft = "原始正文"
        r = tk.revise_draft(issues="重复", focus="减少对话")
        assert tk._draft == "带焦点修改。"

    def test_max_tokens_matches_generate(self):
        """revise_draft uses the same max_tokens formula as generate_draft."""
        llm = MagicMock()
        llm.chat.return_value = _resp("revised")
        tk = WriterToolkit(llm)
        tk._draft = "原始正文"
        # target=100 → max(900, 140) = 900
        tk.set_context(target_words=100)
        tk.revise_draft(issues="问题")
        _, kwargs = llm.chat.call_args
        assert kwargs["max_tokens"] == 900

    def test_revised_preview_in_result(self):
        llm = MagicMock()
        llm.chat.return_value = _resp("修改后的正文内容。")
        tk = WriterToolkit(llm)
        tk._draft = "原始"
        r = tk.revise_draft(issues="问题")
        assert "revised_preview" in r
        assert r["revised_preview"] == "修改后的正文内容。"


# -------------------------------------------------------------------------
# submit_final
# -------------------------------------------------------------------------


class TestSubmit:
    def test_uses_draft(self):
        tk = WriterToolkit(MagicMock())
        tk._draft = "最终文本"
        assert tk.submit_final() == "最终文本"

    def test_with_text(self):
        tk = WriterToolkit(MagicMock())
        tk._draft = "草稿"
        assert tk.submit_final(text="覆盖") == "覆盖"

    def test_empty_text_uses_draft(self):
        tk = WriterToolkit(MagicMock())
        tk._draft = "草稿内容"
        assert tk.submit_final(text="") == "草稿内容"

    def test_rejects_raw_thinking_json(self):
        """submit_final should reject text that looks like raw tool-call JSON."""
        tk = WriterToolkit(MagicMock())
        tk._draft = "真正的小说正文内容"
        raw_json = '{"thinking":"分析场景","tool":"generate_draft","args":{"scene_prompt":"..."}}'
        result = tk.submit_final(text=raw_json)
        assert result == "真正的小说正文内容"

    def test_rejects_raw_tool_json(self):
        """submit_final should reject text starting with {"tool"."""
        tk = WriterToolkit(MagicMock())
        tk._draft = "内部草稿正文"
        raw_json = '{"tool":"submit","args":{"result":"some json"}}'
        result = tk.submit_final(text=raw_json)
        assert result == "内部草稿正文"

    def test_rejects_draft_preview_json(self):
        """submit_final should reject text starting with {"draft_preview"."""
        tk = WriterToolkit(MagicMock())
        tk._draft = "正常草稿"
        raw_json = '{"draft_preview":"预览...","word_count":800,"target_words":800}'
        result = tk.submit_final(text=raw_json)
        assert result == "正常草稿"

    def test_accepts_normal_story_text(self):
        """submit_final should accept legitimate story text even if it contains braces."""
        tk = WriterToolkit(MagicMock())
        tk._draft = "草稿"
        story = "林辰说：「这个计划{很完美}。」他转身离去。"
        result = tk.submit_final(text=story)
        assert result == story


# -------------------------------------------------------------------------
# get_current_draft
# -------------------------------------------------------------------------


class TestGetDraft:
    def test_empty(self):
        tk = WriterToolkit(MagicMock())
        r = tk.get_current_draft()
        assert r["draft"] == ""
        assert r["word_count"] == 0

    def test_with_draft(self):
        tk = WriterToolkit(MagicMock())
        tk._draft = "一些内容"
        r = tk.get_current_draft()
        assert r["draft"] == "一些内容"
        assert r["word_count"] > 0
