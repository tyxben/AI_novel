"""Tests for conversation / chat_messages CRUD operations in StructuredDB."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.novel.storage.structured_db import StructuredDB


# ========== Fixtures ==========


@pytest.fixture
def db(tmp_path: Path) -> StructuredDB:
    """Create StructuredDB with temporary SQLite file."""
    db_path = tmp_path / "test.db"
    return StructuredDB(db_path)


# ========== Table creation ==========


class TestConversationsTableCreation:
    """Verify conversations and chat_messages tables are created during init."""

    def test_conversations_table_exists(self, db: StructuredDB) -> None:
        with db._lock:
            assert db._conn is not None
            cur = db._conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='conversations'"
            )
            assert cur.fetchone() is not None

    def test_chat_messages_table_exists(self, db: StructuredDB) -> None:
        with db._lock:
            assert db._conn is not None
            cur = db._conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_messages'"
            )
            assert cur.fetchone() is not None

    def test_conversations_indexes_exist(self, db: StructuredDB) -> None:
        with db._lock:
            assert db._conn is not None
            cur = db._conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='conversations'"
            )
            index_names = {row["name"] for row in cur.fetchall()}
            assert "idx_conversations_novel_id" in index_names
            assert "idx_conversations_updated_at" in index_names

    def test_chat_messages_indexes_exist(self, db: StructuredDB) -> None:
        with db._lock:
            assert db._conn is not None
            cur = db._conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='chat_messages'"
            )
            index_names = {row["name"] for row in cur.fetchall()}
            assert "idx_chat_messages_session_id" in index_names


# ========== Conversation CRUD ==========


class TestCreateConversation:
    def test_create_conversation(self, db: StructuredDB) -> None:
        conv = db.create_conversation("novel_001")
        assert conv["session_id"].startswith("conv_")
        assert len(conv["session_id"]) == 17  # "conv_" + 12 hex chars
        assert conv["novel_id"] == "novel_001"
        assert conv["title"] == "新对话"
        assert conv["message_count"] == 0
        assert "created_at" in conv
        assert "updated_at" in conv

    def test_create_conversation_custom_title(self, db: StructuredDB) -> None:
        conv = db.create_conversation("novel_001", title="讨论第一章")
        assert conv["title"] == "讨论第一章"

    def test_create_conversation_unique_ids(self, db: StructuredDB) -> None:
        ids = set()
        for _ in range(20):
            conv = db.create_conversation("novel_001")
            ids.add(conv["session_id"])
        assert len(ids) == 20


class TestListConversations:
    def test_list_conversations_empty(self, db: StructuredDB) -> None:
        result = db.list_conversations("novel_001")
        assert result == []

    def test_list_conversations_sorted_by_updated(self, db: StructuredDB) -> None:
        """Conversations should be sorted by updated_at DESC (most recent first)."""
        conv1 = db.create_conversation("novel_001", title="First")
        conv2 = db.create_conversation("novel_001", title="Second")

        # Add a message to conv1 so its updated_at is newer
        db.add_message(conv1["session_id"], "user", "hello")

        result = db.list_conversations("novel_001")
        assert len(result) == 2
        # conv1 should be first because it was updated more recently
        assert result[0]["session_id"] == conv1["session_id"]
        assert result[1]["session_id"] == conv2["session_id"]

    def test_list_conversations_filters_by_novel_id(self, db: StructuredDB) -> None:
        db.create_conversation("novel_001", title="Conv A")
        db.create_conversation("novel_002", title="Conv B")
        db.create_conversation("novel_001", title="Conv C")

        result_1 = db.list_conversations("novel_001")
        assert len(result_1) == 2
        assert all(c["novel_id"] == "novel_001" for c in result_1)

        result_2 = db.list_conversations("novel_002")
        assert len(result_2) == 1
        assert result_2[0]["novel_id"] == "novel_002"

    def test_list_conversations_nonexistent_novel(self, db: StructuredDB) -> None:
        result = db.list_conversations("nonexistent")
        assert result == []


class TestAddMessage:
    def test_add_message_updates_count(self, db: StructuredDB) -> None:
        conv = db.create_conversation("novel_001")
        sid = conv["session_id"]

        db.add_message(sid, "user", "Hello")
        db.add_message(sid, "agent", "Hi there!")
        db.add_message(sid, "user", "Thanks")

        convs = db.list_conversations("novel_001")
        assert len(convs) == 1
        assert convs[0]["message_count"] == 3

    def test_add_message_returns_correct_dict(self, db: StructuredDB) -> None:
        conv = db.create_conversation("novel_001")
        msg = db.add_message(conv["session_id"], "user", "Test message")

        assert msg["message_id"].startswith("msg_")
        assert len(msg["message_id"]) == 16  # "msg_" + 12 hex chars
        assert msg["session_id"] == conv["session_id"]
        assert msg["role"] == "user"
        assert msg["content"] == "Test message"
        assert msg["steps"] is None
        assert msg["model"] is None
        assert "created_at" in msg

    def test_add_message_with_steps_and_model(self, db: StructuredDB) -> None:
        conv = db.create_conversation("novel_001")
        steps = [{"step": 1, "tool": "read_chapter", "args": {"chapter_number": 1}}]
        msg = db.add_message(
            conv["session_id"], "agent", "Done!",
            steps=steps, model="gemini-pro",
        )

        assert msg["steps"] == steps
        assert msg["model"] == "gemini-pro"


class TestGetConversationMessages:
    def test_get_messages_sorted_by_created(self, db: StructuredDB) -> None:
        conv = db.create_conversation("novel_001")
        sid = conv["session_id"]

        db.add_message(sid, "user", "First")
        db.add_message(sid, "agent", "Second")
        db.add_message(sid, "user", "Third")

        msgs = db.get_conversation_messages(sid)
        assert len(msgs) == 3
        assert msgs[0]["content"] == "First"
        assert msgs[0]["role"] == "user"
        assert msgs[1]["content"] == "Second"
        assert msgs[1]["role"] == "agent"
        assert msgs[2]["content"] == "Third"
        assert msgs[2]["role"] == "user"

    def test_get_messages_empty_session(self, db: StructuredDB) -> None:
        conv = db.create_conversation("novel_001")
        msgs = db.get_conversation_messages(conv["session_id"])
        assert msgs == []

    def test_get_messages_nonexistent_session(self, db: StructuredDB) -> None:
        msgs = db.get_conversation_messages("conv_nonexistent")
        assert msgs == []

    def test_steps_json_serialization(self, db: StructuredDB) -> None:
        """Steps should be serialized to JSON on write and deserialized on read."""
        conv = db.create_conversation("novel_001")
        steps = [
            {"step": 1, "tool": "get_novel_info", "args": {}, "result": {"title": "Test"}},
            {"step": 2, "tool": "reply_to_user", "args": {"message": "Done"}, "result": {"reply": "Done"}},
        ]
        db.add_message(conv["session_id"], "agent", "Result", steps=steps)

        msgs = db.get_conversation_messages(conv["session_id"])
        assert len(msgs) == 1
        assert msgs[0]["steps"] == steps
        assert isinstance(msgs[0]["steps"], list)
        assert msgs[0]["steps"][0]["tool"] == "get_novel_info"

    def test_steps_none_preserved(self, db: StructuredDB) -> None:
        """Messages without steps should have steps=None."""
        conv = db.create_conversation("novel_001")
        db.add_message(conv["session_id"], "user", "Hello")

        msgs = db.get_conversation_messages(conv["session_id"])
        assert len(msgs) == 1
        assert msgs[0]["steps"] is None


class TestDeleteConversation:
    def test_delete_conversation_cascades(self, db: StructuredDB) -> None:
        """Deleting a conversation should also delete its messages."""
        conv = db.create_conversation("novel_001")
        sid = conv["session_id"]
        db.add_message(sid, "user", "Hello")
        db.add_message(sid, "agent", "Hi")

        result = db.delete_conversation(sid)
        assert result is True

        # Conversation gone
        convs = db.list_conversations("novel_001")
        assert len(convs) == 0

        # Messages gone
        msgs = db.get_conversation_messages(sid)
        assert len(msgs) == 0

    def test_delete_conversation_nonexistent(self, db: StructuredDB) -> None:
        result = db.delete_conversation("conv_nonexistent")
        assert result is False

    def test_delete_does_not_affect_other_conversations(self, db: StructuredDB) -> None:
        conv1 = db.create_conversation("novel_001", title="Keep")
        conv2 = db.create_conversation("novel_001", title="Delete")

        db.add_message(conv1["session_id"], "user", "Keep me")
        db.add_message(conv2["session_id"], "user", "Delete me")

        db.delete_conversation(conv2["session_id"])

        convs = db.list_conversations("novel_001")
        assert len(convs) == 1
        assert convs[0]["title"] == "Keep"

        msgs = db.get_conversation_messages(conv1["session_id"])
        assert len(msgs) == 1
        assert msgs[0]["content"] == "Keep me"


class TestUpdateConversationTitle:
    def test_update_conversation_title(self, db: StructuredDB) -> None:
        conv = db.create_conversation("novel_001", title="Old Title")
        db.update_conversation_title(conv["session_id"], "New Title")

        convs = db.list_conversations("novel_001")
        assert len(convs) == 1
        assert convs[0]["title"] == "New Title"

    def test_update_title_nonexistent(self, db: StructuredDB) -> None:
        """Updating a nonexistent conversation title is a no-op (no error)."""
        db.update_conversation_title("conv_nonexistent", "Title")
        # Should not raise

    def test_update_title_unicode(self, db: StructuredDB) -> None:
        conv = db.create_conversation("novel_001")
        db.update_conversation_title(conv["session_id"], "修改世界观设定...")

        convs = db.list_conversations("novel_001")
        assert convs[0]["title"] == "修改世界观设定..."


class TestReinitIdempotent:
    def test_reinit_preserves_conversations(self, tmp_path: Path) -> None:
        """Creating StructuredDB twice preserves conversation data."""
        db_path = tmp_path / "test.db"
        db1 = StructuredDB(db_path)
        conv = db1.create_conversation("novel_001", title="Persist me")
        db1.add_message(conv["session_id"], "user", "Hello")
        db1.close()

        db2 = StructuredDB(db_path)
        convs = db2.list_conversations("novel_001")
        assert len(convs) == 1
        assert convs[0]["title"] == "Persist me"

        msgs = db2.get_conversation_messages(conv["session_id"])
        assert len(msgs) == 1
        assert msgs[0]["content"] == "Hello"
        db2.close()
