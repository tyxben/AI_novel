"""Tests for agent chat session auto-restore and working memory."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from src.novel.services.agent_chat import (
    run_agent_chat,
    _extract_working_memory,
)


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


@pytest.fixture
def mock_llm():
    """Mock LLM that returns a reply_to_user tool call on first invocation."""
    from src.llm.llm_client import LLMResponse

    response = LLMResponse(
        content=json.dumps({
            "tool": "reply_to_user",
            "args": {"message": "已完成操作"},
        }),
        model="mock-model",
        usage={"prompt_tokens": 100, "completion_tokens": 50},
    )
    client = MagicMock()
    client.chat.return_value = response
    client.model = "mock-model"
    return client


@pytest.fixture
def mock_db():
    """Mock StructuredDB with get_conversation_messages."""
    db = MagicMock()
    db.get_conversation_messages.return_value = [
        {"role": "user", "content": "请帮我修改第一章的标题"},
        {"role": "agent", "content": "好的，我来帮你修改标题。"},
        {"role": "user", "content": "改成'龙啸九天'"},
        {"role": "agent", "content": "标题已修改为'龙啸九天'。"},
    ]
    return db


# ---------------------------------------------------------------------------
# Tests: _extract_working_memory
# ---------------------------------------------------------------------------


class TestExtractWorkingMemory:
    """Tests for the _extract_working_memory helper."""

    def test_basic_extraction(self):
        messages = [
            {"role": "user", "content": "修改标题"},
            {"role": "assistant", "content": '{"tool": "edit_setting"}'},
        ]
        result = _extract_working_memory(messages, "修改第一章标题")
        assert "当前用户目标：修改第一章标题" in result

    def test_includes_recent_tool_calls(self):
        messages = [
            {"role": "user", "content": "[工具结果] read_chapter: {\"title\": \"第一章\"}"},
            {"role": "assistant", "content": "thinking"},
            {"role": "user", "content": "[工具结果] edit_setting: {\"status\": \"ok\"}"},
        ]
        result = _extract_working_memory(messages, "修改设定")
        assert "最近工具调用" in result
        assert "工具结果" in result

    def test_empty_messages(self):
        result = _extract_working_memory([], "测试查询")
        assert "当前用户目标：测试查询" in result
        assert "最近工具调用" not in result

    def test_truncates_long_query(self):
        long_query = "A" * 500
        result = _extract_working_memory([], long_query)
        # The query is truncated to 200 chars
        assert len(result) < 500

    def test_only_recent_messages_considered(self):
        """Only last 6 messages are scanned for tool references."""
        messages = [
            {"role": "user", "content": f"[工具结果] tool_{i}: ok"}
            for i in range(20)
        ]
        result = _extract_working_memory(messages, "query")
        # Should only mention tools from the last 6 messages (tool_14..tool_19)
        # and only keep last 3
        assert "最近工具调用" in result

    def test_no_tool_calls_no_recent_section(self):
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，有什么需要帮忙的？"},
        ]
        result = _extract_working_memory(messages, "打个招呼")
        assert "最近工具调用" not in result


# ---------------------------------------------------------------------------
# Tests: run_agent_chat with session auto-restore
# ---------------------------------------------------------------------------


class TestRunAgentChatSessionRestore:
    """Tests for auto-restoring conversation history from DB."""

    @patch("src.llm.llm_client.create_llm_client")
    def test_auto_loads_history_from_db(self, mock_create_llm, tmp_workspace, mock_llm, mock_db):
        """When session_id and db are provided with short/no explicit history,
        conversation history should be loaded from DB."""
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="继续帮我修改",
            history=[],  # Empty explicit history
            session_id="sess_001",
            db=mock_db,
        )

        # DB should have been queried
        mock_db.get_conversation_messages.assert_called_once_with("sess_001")

        # LLM should have been called
        assert mock_llm.chat.called
        # Verify the messages sent to LLM include DB history
        call_args = mock_llm.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0]
        # Messages should include: system + restored history + current user message
        roles = [m["role"] for m in messages]
        # System prompt is first
        assert roles[0] == "system"
        # Should contain user and assistant messages from DB
        assert "user" in roles[1:]
        assert "assistant" in roles[1:]

        assert result["reply"] == "已完成操作"

    @patch("src.llm.llm_client.create_llm_client")
    def test_skips_db_when_explicit_history_is_long(self, mock_create_llm, tmp_workspace, mock_llm, mock_db):
        """When explicit history has >= 3 entries, DB is NOT queried."""
        mock_create_llm.return_value = mock_llm

        explicit_history = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "reply1"},
            {"role": "user", "content": "msg2"},
            {"role": "assistant", "content": "reply2"},
        ]

        run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="再修改一下",
            history=explicit_history,
            session_id="sess_001",
            db=mock_db,
        )

        # DB should NOT be queried because explicit history len >= 3
        mock_db.get_conversation_messages.assert_not_called()

    @patch("src.llm.llm_client.create_llm_client")
    def test_skips_db_when_no_session_id(self, mock_create_llm, tmp_workspace, mock_llm, mock_db):
        """When session_id is empty, DB is NOT queried."""
        mock_create_llm.return_value = mock_llm

        run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="测试",
            history=[],
            session_id="",
            db=mock_db,
        )

        mock_db.get_conversation_messages.assert_not_called()

    @patch("src.llm.llm_client.create_llm_client")
    def test_skips_db_when_no_db(self, mock_create_llm, tmp_workspace, mock_llm):
        """When db is None, no error is raised."""
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="测试",
            history=[],
            session_id="sess_001",
            db=None,
        )

        assert result["reply"] == "已完成操作"

    @patch("src.llm.llm_client.create_llm_client")
    def test_db_exception_falls_back_gracefully(self, mock_create_llm, tmp_workspace, mock_llm):
        """When DB raises an exception, it is caught and execution continues."""
        mock_create_llm.return_value = mock_llm

        broken_db = MagicMock()
        broken_db.get_conversation_messages.side_effect = RuntimeError("DB corrupt")

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="测试",
            history=[],
            session_id="sess_001",
            db=broken_db,
        )

        # Should still succeed despite DB error
        assert result["reply"] == "已完成操作"

    @patch("src.llm.llm_client.create_llm_client")
    def test_dedup_merges_db_and_explicit_history(self, mock_create_llm, tmp_workspace, mock_llm):
        """DB history and explicit history are merged without duplicates."""
        mock_create_llm.return_value = mock_llm

        db = MagicMock()
        db.get_conversation_messages.return_value = [
            {"role": "user", "content": "消息A"},
            {"role": "agent", "content": "回复A"},
        ]

        explicit_history = [
            {"role": "user", "content": "消息A"},  # Duplicate
            {"role": "assistant", "content": "回复B"},  # New
        ]

        run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="继续",
            history=explicit_history,
            session_id="sess_001",
            db=db,
        )

        # Verify LLM was called and check messages
        call_args = mock_llm.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0]

        # Count non-system, non-current messages
        history_msgs = [m for m in messages[1:] if m["content"] != "继续"]
        contents = [m["content"] for m in history_msgs]

        # "消息A" should appear only once (deduped)
        assert contents.count("消息A") == 1
        # "回复A" from DB
        assert "回复A" in contents
        # "回复B" from explicit
        assert "回复B" in contents


# ---------------------------------------------------------------------------
# Tests: working memory injection
# ---------------------------------------------------------------------------


class TestWorkingMemoryInjection:
    """Tests that working memory is injected into the system prompt."""

    @patch("src.llm.llm_client.create_llm_client")
    def test_working_memory_injected_with_long_history(self, mock_create_llm, tmp_workspace, mock_llm):
        """When history has > 2 entries, working memory is added to system prompt."""
        mock_create_llm.return_value = mock_llm

        history = [
            {"role": "user", "content": "修改第一章"},
            {"role": "assistant", "content": "好的"},
            {"role": "user", "content": "[工具结果] edit_setting: ok"},
        ]

        run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="继续修改第二章",
            history=history,
        )

        call_args = mock_llm.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0]

        system_msg = messages[0]["content"]
        assert "工作记忆" in system_msg
        assert "当前用户目标：继续修改第二章" in system_msg

    @patch("src.llm.llm_client.create_llm_client")
    def test_no_working_memory_with_short_history(self, mock_create_llm, tmp_workspace, mock_llm):
        """When history has <= 2 entries, no working memory is injected."""
        mock_create_llm.return_value = mock_llm

        history = [
            {"role": "user", "content": "你好"},
        ]

        run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="测试",
            history=history,
        )

        call_args = mock_llm.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0]

        system_msg = messages[0]["content"]
        assert "工作记忆" not in system_msg

    @patch("src.llm.llm_client.create_llm_client")
    def test_no_working_memory_without_history(self, mock_create_llm, tmp_workspace, mock_llm):
        """When history is None, no working memory is injected."""
        mock_create_llm.return_value = mock_llm

        run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="测试",
            history=None,
        )

        call_args = mock_llm.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0]

        system_msg = messages[0]["content"]
        assert "工作记忆" not in system_msg


# ---------------------------------------------------------------------------
# Tests: backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Ensure existing callers that don't pass session_id/db still work."""

    @patch("src.llm.llm_client.create_llm_client")
    def test_no_session_id_no_db(self, mock_create_llm, tmp_workspace, mock_llm):
        """Call without session_id and db (original signature) still works."""
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="获取小说信息",
        )

        assert result["reply"] == "已完成操作"
        assert result["model"] == "mock-model"

    @patch("src.llm.llm_client.create_llm_client")
    def test_positional_args_still_work(self, mock_create_llm, tmp_workspace, mock_llm):
        """Old-style positional calls still work (session_id and db are keyword-only via defaults)."""
        mock_create_llm.return_value = mock_llm

        result = run_agent_chat(
            workspace=str(tmp_workspace),
            novel_id="novel_test",
            message="测试",
            context_chapters=None,
            history=None,
            progress_callback=None,
        )

        assert result["reply"] == "已完成操作"
