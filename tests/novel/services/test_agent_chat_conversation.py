"""Tests for agent chat conversational mode — direct reply format, tool calls, fallbacks."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.novel.services.agent_chat import run_agent_chat


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temp workspace with a fake novel project."""
    novel_dir = tmp_path / "novels" / "novel_test"
    novel_dir.mkdir(parents=True)

    novel_json = {
        "novel_id": "novel_test",
        "title": "测试小说",
        "genre": "玄幻",
        "status": "generating",
        "current_chapter": 3,
        "target_words": 50000,
        "outline": {
            "chapters": [
                {"chapter_number": i, "title": f"第{i}章"}
                for i in range(1, 6)
            ],
        },
        "characters": [{"name": "张三", "role": "protagonist"}],
        "synopsis": "一个修仙故事",
    }
    (novel_dir / "novel.json").write_text(
        json.dumps(novel_json, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


def _make_llm_response(content: str):
    """Create a mock LLMResponse with the given content."""
    from src.llm.llm_client import LLMResponse

    return LLMResponse(
        content=content,
        model="mock-model",
        usage={"prompt_tokens": 100, "completion_tokens": 50},
    )


def _make_mock_llm(responses: list[str]):
    """Create a mock LLM client that returns the given responses in sequence."""
    client = MagicMock()
    client.model = "mock-model"
    client.chat.side_effect = [_make_llm_response(r) for r in responses]
    return client


# ---------------------------------------------------------------------------
# Tests: Direct reply format
# ---------------------------------------------------------------------------


class TestDirectReplyFormat:
    """Test that {"reply": "..."} is properly extracted as the final reply."""

    @patch("src.llm.llm_client.create_llm_client")
    def test_direct_reply_extracted(self, mock_create_llm, tmp_workspace):
        """Agent returns {"reply": "analysis..."} — should be the final reply."""
        reply_content = "第15章整体质量不错，但有两个问题：\n1. 节奏偏慢\n2. 对话过多"
        mock_llm = _make_mock_llm([
            json.dumps({"reply": reply_content}),
        ])
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="你觉得第15章怎么样？",
        )

        assert result["reply"] == reply_content

    @patch("src.llm.llm_client.create_llm_client")
    def test_direct_reply_logged_in_conversation_log(self, mock_create_llm, tmp_workspace):
        """Direct reply should appear in the conversation log as a step."""
        reply_content = "这是我的分析结果"
        mock_llm = _make_mock_llm([
            json.dumps({"reply": reply_content}),
        ])
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="分析一下情节",
        )

        assert result["total_steps"] == 1
        step = result["steps"][0]
        assert step["tool"] == "direct_reply"
        assert step["result"]["reply"] == reply_content

    @patch("src.llm.llm_client.create_llm_client")
    def test_direct_reply_with_thinking(self, mock_create_llm, tmp_workspace):
        """Agent can include thinking with direct reply — still extracted correctly."""
        reply_content = "基于已有信息，我认为角色发展线很好"
        mock_llm = _make_mock_llm([
            json.dumps({
                "thinking": "用户在讨论，不需要工具",
                "reply": reply_content,
            }),
        ])
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="你觉得角色发展怎么样？",
        )

        assert result["reply"] == reply_content
        # Thinking should be logged
        assert result["steps"][0]["thinking"] == "用户在讨论，不需要工具"

    @patch("src.llm.llm_client.create_llm_client")
    def test_reply_field_ignored_when_tool_present(self, mock_create_llm, tmp_workspace):
        """If both "reply" and "tool" are present, tool takes priority."""
        mock_llm = _make_mock_llm([
            # Agent sends reply + tool — tool should execute, not the reply
            json.dumps({
                "reply": "让我先看看",
                "tool": "reply_to_user",
                "args": {"message": "工具回复内容"},
            }),
        ])
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="检查第一章",
        )

        # reply_to_user tool should have been used, not the direct reply
        assert result["reply"] == "工具回复内容"


# ---------------------------------------------------------------------------
# Tests: Tool call still works
# ---------------------------------------------------------------------------


class TestToolCallStillWorks:
    """Verify that the existing tool-call format works as before."""

    @patch("src.llm.llm_client.create_llm_client")
    def test_tool_call_with_reply_to_user(self, mock_create_llm, tmp_workspace):
        """Traditional reply_to_user tool call still works."""
        mock_llm = _make_mock_llm([
            json.dumps({
                "tool": "reply_to_user",
                "args": {"message": "已分析完毕，第3章质量很好"},
            }),
        ])
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="分析第3章",
        )

        assert result["reply"] == "已分析完毕，第3章质量很好"
        assert result["total_steps"] == 1
        assert result["steps"][0]["tool"] == "reply_to_user"

    @patch("src.llm.llm_client.create_llm_client")
    def test_multi_step_tool_then_reply(self, mock_create_llm, tmp_workspace):
        """Agent calls tools then gives a direct reply."""
        # Create a chapter file so read_chapter works
        ch_dir = Path(tmp_workspace) / "novels" / "novel_test" / "chapters"
        ch_dir.mkdir(parents=True, exist_ok=True)
        ch_data = {
            "chapter_number": 1,
            "title": "第1章",
            "full_text": "这是第一章的内容" * 50,
            "word_count": 500,
        }
        (ch_dir / "chapter_001.json").write_text(
            json.dumps(ch_data, ensure_ascii=False), encoding="utf-8"
        )

        mock_llm = _make_mock_llm([
            # Step 1: read chapter
            json.dumps({
                "thinking": "需要先读取章节",
                "tool": "read_chapter",
                "args": {"chapter_number": 1},
            }),
            # Step 2: direct reply with analysis
            json.dumps({
                "reply": "读完第1章后，我发现节奏偏快，建议放慢。",
            }),
        ])
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="分析第1章的节奏",
        )

        assert result["reply"] == "读完第1章后，我发现节奏偏快，建议放慢。"
        # Should have 2 steps: tool call + direct reply
        assert result["total_steps"] == 2
        assert result["steps"][0]["tool"] == "read_chapter"
        assert result["steps"][1]["tool"] == "direct_reply"

    @patch("src.llm.llm_client.create_llm_client")
    def test_multi_step_tool_then_reply_to_user(self, mock_create_llm, tmp_workspace):
        """Agent calls tools then uses reply_to_user — traditional flow."""
        mock_llm = _make_mock_llm([
            # Step 1: get info
            json.dumps({
                "tool": "get_novel_info",
                "args": {},
            }),
            # Step 2: reply
            json.dumps({
                "tool": "reply_to_user",
                "args": {"message": "小说信息如下：..."},
            }),
        ])
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="告诉我小说信息",
        )

        assert result["reply"] == "小说信息如下：..."
        assert result["total_steps"] == 2
        assert result["steps"][0]["tool"] == "get_novel_info"
        assert result["steps"][1]["tool"] == "reply_to_user"


# ---------------------------------------------------------------------------
# Tests: Non-JSON response treated as direct reply
# ---------------------------------------------------------------------------


class TestNonJsonFallback:
    """Test that non-JSON LLM output is treated as a direct reply."""

    @patch("src.llm.llm_client.create_llm_client")
    def test_plain_text_response_used_as_reply(self, mock_create_llm, tmp_workspace):
        """If LLM returns plain text, it becomes the final reply."""
        plain_text = "我觉得这个小说写得很好，角色有深度。"
        mock_llm = _make_mock_llm([plain_text])
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="你觉得这个小说怎么样？",
        )

        assert result["reply"] == plain_text
        # No tool steps should be logged
        assert result["total_steps"] == 0

    @patch("src.llm.llm_client.create_llm_client")
    def test_malformed_json_treated_as_reply(self, mock_create_llm, tmp_workspace):
        """Broken JSON is treated as a direct reply, not an error."""
        broken_json = '{"reply": "分析结果", 这不是合法JSON'
        mock_llm = _make_mock_llm([broken_json])
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="检查问题",
        )

        assert result["reply"] == broken_json


# ---------------------------------------------------------------------------
# Tests: max_tokens is 4096
# ---------------------------------------------------------------------------


class TestMaxTokens:
    """Verify that the LLM is called with max_tokens=4096."""

    @patch("src.llm.llm_client.create_llm_client")
    def test_max_tokens_is_4096(self, mock_create_llm, tmp_workspace):
        """The LLM call should use max_tokens=4096 for richer replies."""
        mock_llm = _make_mock_llm([
            json.dumps({"reply": "ok"}),
        ])
        mock_create_llm.return_value = mock_llm

        run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="你好",
        )

        # Check the kwargs passed to llm.chat
        call_kwargs = mock_llm.chat.call_args
        # Could be positional or keyword — check both
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        if not kwargs:
            # Try the first positional form
            kwargs = call_kwargs[1] if len(call_kwargs) > 1 else {}

        assert kwargs.get("max_tokens") == 4096

    @patch("src.llm.llm_client.create_llm_client")
    def test_temperature_is_0_3(self, mock_create_llm, tmp_workspace):
        """Temperature should be 0.3 for more natural conversation."""
        mock_llm = _make_mock_llm([
            json.dumps({"reply": "ok"}),
        ])
        mock_create_llm.return_value = mock_llm

        run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="你好",
        )

        call_kwargs = mock_llm.chat.call_args
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        if not kwargs:
            kwargs = call_kwargs[1] if len(call_kwargs) > 1 else {}

        assert kwargs.get("temperature") == 0.3


# ---------------------------------------------------------------------------
# Tests: Fallback reply from tool results
# ---------------------------------------------------------------------------


class TestFallbackReplySynthesis:
    """Test that when max iterations are reached, a summary is synthesized."""

    @patch("src.llm.llm_client.create_llm_client")
    def test_fallback_synthesizes_from_tool_results(self, mock_create_llm, tmp_workspace):
        """When agent loops without replying, a summary of tool results is generated."""
        from src.novel.services.agent_chat import MAX_ITERATIONS

        # Agent keeps calling get_novel_info in a loop without ever replying
        responses = [
            json.dumps({"tool": "get_novel_info", "args": {}})
            for _ in range(MAX_ITERATIONS)
        ]
        mock_llm = _make_mock_llm(responses)
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="做点什么",
        )

        # Should have a synthesized fallback reply, not empty
        assert result["reply"]
        assert "步骤上限" in result["reply"] or "再发一条" in result["reply"]
        assert result["total_steps"] == MAX_ITERATIONS

    @patch("src.llm.llm_client.create_llm_client")
    def test_empty_log_fallback(self, mock_create_llm, tmp_workspace):
        """When agent returns empty JSON with no tool/reply, fallback is used."""
        mock_llm = _make_mock_llm([
            json.dumps({}),
        ])
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="什么都不做",
        )

        # Should get the raw JSON content as fallback (no tool, no reply field)
        assert result["reply"]


# ---------------------------------------------------------------------------
# Tests: System prompt contains new format instructions
# ---------------------------------------------------------------------------


class TestSystemPromptFormat:
    """Verify the system prompt includes the new conversational format."""

    @patch("src.llm.llm_client.create_llm_client")
    def test_system_prompt_has_direct_reply_format(self, mock_create_llm, tmp_workspace):
        """System prompt should document the direct reply format."""
        mock_llm = _make_mock_llm([
            json.dumps({"reply": "ok"}),
        ])
        mock_create_llm.return_value = mock_llm

        run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="你好",
        )

        # Get the system message sent to LLM
        call_args = mock_llm.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args[0][0]
        system_msg = messages[0]["content"]

        # Check new format instructions are present
        assert "方式一：直接回复" in system_msg
        assert "方式二：调用工具" in system_msg
        assert '"reply"' in system_msg

    @patch("src.llm.llm_client.create_llm_client")
    def test_system_prompt_has_quality_requirements(self, mock_create_llm, tmp_workspace):
        """System prompt should include reply quality requirements."""
        mock_llm = _make_mock_llm([
            json.dumps({"reply": "ok"}),
        ])
        mock_create_llm.return_value = mock_llm

        run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="你好",
        )

        call_args = mock_llm.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args[0][0]
        system_msg = messages[0]["content"]

        assert "回复质量要求" in system_msg
        assert "讨论型问题" in system_msg
        assert "操作已完成" in system_msg
