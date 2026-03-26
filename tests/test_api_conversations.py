"""Tests for conversation REST API endpoints.

Uses FastAPI TestClient with mocked task queue.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.helpers import set_workspace, configure_task_queue


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _workspace(tmp_path):
    """Set workspace to a temp dir for every test."""
    set_workspace(str(tmp_path))
    yield tmp_path
    set_workspace("workspace")  # restore default


@pytest.fixture()
def mock_db():
    """Mock TaskDB that tracks created tasks."""
    db = MagicMock()
    _tasks = {}

    def _create_task(task_type, params):
        record = MagicMock()
        record.task_id = f"test_{len(_tasks):04d}"
        record.task_type = task_type
        record.params = params
        _tasks[record.task_id] = record
        return record

    db.create_task = MagicMock(side_effect=_create_task)
    db.get_task = MagicMock(side_effect=lambda tid: _tasks.get(tid))
    db.update_status = MagicMock()
    db.update_progress = MagicMock()
    return db


@pytest.fixture()
def mock_executor():
    """Mock executor that records submitted tasks but does not run them."""
    ex = MagicMock()
    ex.submit = MagicMock()
    return ex


@pytest.fixture()
def client(mock_db, mock_executor):
    """Create a TestClient with mocked task queue."""
    configure_task_queue(mock_db, mock_executor)
    from src.api.app import create_app
    app = create_app()
    return TestClient(app)


def _create_novel_on_disk(workspace: Path, novel_id: str = "novel_test001") -> str:
    """Create a minimal novel project directory."""
    novel_dir = workspace / "novels" / novel_id
    novel_dir.mkdir(parents=True, exist_ok=True)

    novel_data = {
        "title": "Test Novel",
        "genre": "玄幻",
        "status": "generating",
        "style_name": "webnovel.shuangwen",
        "author_name": "TestAuthor",
        "target_audience": "通用",
        "target_words": 100000,
        "current_chapter": 0,
        "synopsis": "A test novel.",
        "tags": [],
        "protagonist_names": [],
        "outline": {"chapters": [], "main_storyline": "Test"},
        "characters": [],
        "world_setting": {},
    }
    (novel_dir / "novel.json").write_text(
        json.dumps(novel_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return novel_id


# ---------------------------------------------------------------------------
# Tests: Conversation CRUD endpoints
# ---------------------------------------------------------------------------

class TestListConversations:
    def test_list_conversations_empty(self, client, _workspace):
        novel_id = _create_novel_on_disk(_workspace)
        r = client.get(f"/api/novels/{novel_id}/conversations")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_conversations_returns_created(self, client, _workspace):
        novel_id = _create_novel_on_disk(_workspace)

        # Create two conversations
        r1 = client.post(
            f"/api/novels/{novel_id}/conversations",
            json={"title": "First"},
        )
        assert r1.status_code == 201
        r2 = client.post(
            f"/api/novels/{novel_id}/conversations",
            json={"title": "Second"},
        )
        assert r2.status_code == 201

        r = client.get(f"/api/novels/{novel_id}/conversations")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        titles = {c["title"] for c in data}
        assert "First" in titles
        assert "Second" in titles


class TestCreateConversation:
    def test_create_conversation(self, client, _workspace):
        novel_id = _create_novel_on_disk(_workspace)
        r = client.post(
            f"/api/novels/{novel_id}/conversations",
            json={"title": "My Chat"},
        )
        assert r.status_code == 201
        data = r.json()
        assert data["title"] == "My Chat"
        assert data["novel_id"] == novel_id
        assert data["session_id"].startswith("conv_")
        assert data["message_count"] == 0

    def test_create_conversation_default_title(self, client, _workspace):
        novel_id = _create_novel_on_disk(_workspace)
        r = client.post(
            f"/api/novels/{novel_id}/conversations",
            json={},
        )
        assert r.status_code == 201
        assert r.json()["title"] == "新对话"


class TestGetMessages:
    def test_get_messages_empty(self, client, _workspace):
        novel_id = _create_novel_on_disk(_workspace)
        # Create conversation first
        r = client.post(
            f"/api/novels/{novel_id}/conversations",
            json={"title": "Empty"},
        )
        session_id = r.json()["session_id"]

        r2 = client.get(f"/api/novels/{novel_id}/conversations/{session_id}/messages")
        assert r2.status_code == 200
        assert r2.json() == []

    def test_get_messages_nonexistent_session(self, client, _workspace):
        novel_id = _create_novel_on_disk(_workspace)
        r = client.get(f"/api/novels/{novel_id}/conversations/conv_nonexistent/messages")
        assert r.status_code == 200
        assert r.json() == []


class TestDeleteConversation:
    def test_delete_conversation(self, client, _workspace):
        novel_id = _create_novel_on_disk(_workspace)
        r = client.post(
            f"/api/novels/{novel_id}/conversations",
            json={"title": "To Delete"},
        )
        session_id = r.json()["session_id"]

        r2 = client.delete(f"/api/novels/{novel_id}/conversations/{session_id}")
        assert r2.status_code == 200
        assert r2.json() == {"ok": True}

        # Verify it's gone
        r3 = client.get(f"/api/novels/{novel_id}/conversations")
        assert r3.status_code == 200
        assert len(r3.json()) == 0


# ---------------------------------------------------------------------------
# Tests: Agent Chat with session persistence
# ---------------------------------------------------------------------------

class TestAgentChatSessionPersistence:
    def test_agent_chat_creates_session(self, client, _workspace, mock_db):
        """When no session_id is provided, agent-chat should create one."""
        novel_id = _create_novel_on_disk(_workspace)

        r = client.post(
            f"/api/novels/{novel_id}/agent-chat",
            json={"message": "帮我修改主角名字为李逍遥"},
        )
        assert r.status_code == 201
        data = r.json()
        assert "task_id" in data
        assert "session_id" in data
        assert data["session_id"].startswith("conv_")

        # Verify the conversation was created
        r2 = client.get(f"/api/novels/{novel_id}/conversations")
        convs = r2.json()
        assert len(convs) == 1
        assert convs[0]["session_id"] == data["session_id"]
        # Title should be first 20 chars of message
        assert convs[0]["title"] == "帮我修改主角名字为李逍遥"

        # Verify user message was saved
        r3 = client.get(
            f"/api/novels/{novel_id}/conversations/{data['session_id']}/messages"
        )
        msgs = r3.json()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "帮我修改主角名字为李逍遥"

    def test_agent_chat_reuses_session(self, client, _workspace, mock_db):
        """When session_id is provided, it should reuse existing session."""
        novel_id = _create_novel_on_disk(_workspace)

        # Create a conversation first
        r_conv = client.post(
            f"/api/novels/{novel_id}/conversations",
            json={"title": "Existing Chat"},
        )
        session_id = r_conv.json()["session_id"]

        # Send agent-chat with existing session_id
        r = client.post(
            f"/api/novels/{novel_id}/agent-chat",
            json={
                "message": "继续之前的对话",
                "session_id": session_id,
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["session_id"] == session_id

        # Verify no new conversation was created
        r2 = client.get(f"/api/novels/{novel_id}/conversations")
        convs = r2.json()
        assert len(convs) == 1
        assert convs[0]["session_id"] == session_id

        # Verify user message was saved
        r3 = client.get(
            f"/api/novels/{novel_id}/conversations/{session_id}/messages"
        )
        msgs = r3.json()
        assert len(msgs) == 1
        assert msgs[0]["content"] == "继续之前的对话"

    def test_agent_chat_title_truncation(self, client, _workspace, mock_db):
        """Title should be truncated to 20 chars + ellipsis for long messages."""
        novel_id = _create_novel_on_disk(_workspace)

        long_message = "这是一条非常非常非常长的消息，需要被截断处理"
        r = client.post(
            f"/api/novels/{novel_id}/agent-chat",
            json={"message": long_message},
        )
        data = r.json()

        r2 = client.get(f"/api/novels/{novel_id}/conversations")
        convs = r2.json()
        assert len(convs) == 1
        assert convs[0]["title"] == long_message[:20] + "..."

    def test_agent_chat_session_id_in_task_params(self, client, _workspace, mock_db):
        """Session_id should be passed through to the task worker params."""
        novel_id = _create_novel_on_disk(_workspace)

        r = client.post(
            f"/api/novels/{novel_id}/agent-chat",
            json={"message": "测试"},
        )
        session_id = r.json()["session_id"]

        # Verify the mock executor received the task with session_id in params
        # The submit_to_queue function calls mock_db.create_task(task_type, params)
        # where params should contain session_id
        assert mock_db.create_task.called
        call_args = mock_db.create_task.call_args
        params = call_args[0][1]  # Second positional arg is params
        assert params.get("session_id") == session_id
