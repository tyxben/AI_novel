"""Tests for ReflexionMemory + reflect() helper."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.services.reflexion_memory import (
    ReflexionEntry,
    ReflexionMemory,
    reflect,
)


# ---------------------------------------------------------------------------
# ReflexionEntry
# ---------------------------------------------------------------------------


class TestEntry:
    def test_default_created_at(self):
        e = ReflexionEntry(chapter_number=1)
        assert e.created_at  # auto-filled
        assert "T" in e.created_at  # ISO format

    def test_long_fields_truncated(self):
        e = ReflexionEntry(
            chapter_number=1,
            what_worked="x" * 500,
            lesson="y" * 500,
        )
        assert len(e.what_worked) <= 300
        assert len(e.lesson) <= 300


# ---------------------------------------------------------------------------
# ReflexionMemory CRUD
# ---------------------------------------------------------------------------


@pytest.fixture
def memory(tmp_path):
    return ReflexionMemory(tmp_path)


class TestMemoryCRUD:
    def test_empty_initially(self, memory):
        assert memory.get_all() == []

    def test_append_and_persist(self, memory, tmp_path):
        memory.append(
            ReflexionEntry(
                chapter_number=5,
                what_worked="开篇紧凑",
                lesson="多用动作少用形容词",
            )
        )
        # Re-instantiate to verify file persistence
        memory2 = ReflexionMemory(tmp_path)
        all_e = memory2.get_all()
        assert len(all_e) == 1
        assert all_e[0].chapter_number == 5
        assert all_e[0].what_worked == "开篇紧凑"

    def test_same_chapter_overwrites(self, memory):
        memory.append(ReflexionEntry(chapter_number=3, lesson="v1"))
        memory.append(ReflexionEntry(chapter_number=3, lesson="v2"))
        all_e = memory.get_all()
        assert len(all_e) == 1
        assert all_e[0].lesson == "v2"

    def test_sorted_by_chapter(self, memory):
        memory.append(ReflexionEntry(chapter_number=10))
        memory.append(ReflexionEntry(chapter_number=2))
        memory.append(ReflexionEntry(chapter_number=5))
        nums = [e.chapter_number for e in memory.get_all()]
        assert nums == [2, 5, 10]

    def test_get_recent(self, memory):
        for n in range(1, 11):
            memory.append(ReflexionEntry(chapter_number=n, lesson=f"l{n}"))
        recent = memory.get_recent(before_chapter=8, k=3)
        assert [e.chapter_number for e in recent] == [5, 6, 7]

    def test_get_recent_handles_empty(self, memory):
        assert memory.get_recent(before_chapter=5) == []

    def test_get_by_type(self, memory):
        memory.append(ReflexionEntry(chapter_number=1, chapter_type="setup"))
        memory.append(ReflexionEntry(chapter_number=2, chapter_type="climax"))
        memory.append(ReflexionEntry(chapter_number=3, chapter_type="climax"))
        memory.append(ReflexionEntry(chapter_number=4, chapter_type="setup"))
        result = memory.get_by_type("climax", before_chapter=10, k=5)
        assert {e.chapter_number for e in result} == {2, 3}

    def test_update_marks_user_edited(self, memory):
        memory.append(ReflexionEntry(chapter_number=1, lesson="auto"))
        ok = memory.update(1, lesson="人工修改")
        assert ok
        e = memory.get_all()[0]
        assert e.lesson == "人工修改"
        assert e.user_edited is True

    def test_update_nonexistent_returns_false(self, memory):
        assert memory.update(99, lesson="x") is False

    def test_update_ignores_unknown_fields(self, memory):
        memory.append(ReflexionEntry(chapter_number=1, lesson="x"))
        memory.update(1, malicious_field="payload")
        e = memory.get_all()[0]
        assert not hasattr(e, "malicious_field")


# ---------------------------------------------------------------------------
# format_for_prompt
# ---------------------------------------------------------------------------


class TestFormatForPrompt:
    def test_empty_returns_empty(self, memory):
        assert memory.format_for_prompt(before_chapter=5) == ""

    def test_includes_recent(self, memory):
        memory.append(
            ReflexionEntry(
                chapter_number=1,
                lesson="开篇要紧凑",
                next_action="下章用动作开头",
            )
        )
        out = memory.format_for_prompt(before_chapter=5)
        assert "历史教训" in out
        assert "开篇要紧凑" in out
        assert "下章用动作开头" in out

    def test_user_edited_marked(self, memory):
        memory.append(ReflexionEntry(chapter_number=1, lesson="auto"))
        memory.update(1, lesson="人工")
        out = memory.format_for_prompt(before_chapter=5)
        assert "👤" in out  # user-edited tag

    def test_typed_section_when_provided(self, memory):
        # Recent 取的是最新 2 条（不分类型）；typed 取 climax 类型最近 2 条。
        # 让 climax 类型的 lesson 不出现在最近 2 条里 → typed 段才会被打印。
        memory.append(ReflexionEntry(chapter_number=1, lesson="老climax教训", chapter_type="climax"))
        memory.append(ReflexionEntry(chapter_number=2, lesson="老climax2", chapter_type="climax"))
        memory.append(ReflexionEntry(chapter_number=8, lesson="新setup1", chapter_type="setup"))
        memory.append(ReflexionEntry(chapter_number=9, lesson="新setup2", chapter_type="setup"))
        out = memory.format_for_prompt(
            before_chapter=10, k_recent=2, chapter_type="climax", k_typed=2
        )
        # Recent 段应该是 ch8/9 的 setup 教训；typed 段补 climax 教训
        assert "同类章节经验" in out
        assert "老climax教训" in out

    def test_dedupes_between_recent_and_typed(self, memory):
        memory.append(
            ReflexionEntry(chapter_number=1, lesson="共同教训", chapter_type="climax")
        )
        out = memory.format_for_prompt(
            before_chapter=10, k_recent=5, chapter_type="climax", k_typed=3
        )
        # 只出现一次
        assert out.count("共同教训") == 1


# ---------------------------------------------------------------------------
# reflect() LLM helper
# ---------------------------------------------------------------------------


def _llm_returns(mock_llm, payload):
    if isinstance(payload, dict):
        content = json.dumps(payload, ensure_ascii=False)
    else:
        content = str(payload)
    mock_llm.chat.return_value = LLMResponse(
        content=content, model="mock", usage=None
    )


class TestReflectHelper:
    def test_happy_path(self):
        llm = MagicMock()
        _llm_returns(
            llm,
            {
                "what_worked": "用动作展示紧张",
                "what_failed": "对话过长",
                "lesson": "对白超过3行就拆",
                "next_action": "下章对白≤2行",
            },
        )
        e = reflect(
            llm,
            chapter_text="测试正文" * 100,
            chapter_number=10,
            chapter_type="climax",
            chapter_goal="冲突收束",
        )
        assert e.chapter_number == 10
        assert e.chapter_type == "climax"
        assert e.what_worked == "用动作展示紧张"
        assert e.what_failed == "对话过长"
        assert e.lesson == "对白超过3行就拆"

    def test_llm_failure_returns_empty_safe(self):
        llm = MagicMock()
        llm.chat.side_effect = RuntimeError("boom")
        e = reflect(llm, chapter_text="x", chapter_number=5, chapter_type="setup")
        assert e.chapter_number == 5
        assert e.chapter_type == "setup"
        assert e.what_worked == ""

    def test_garbage_response_returns_empty_safe(self):
        llm = MagicMock()
        _llm_returns(llm, "not json at all")
        e = reflect(llm, chapter_text="x", chapter_number=5)
        assert e.chapter_number == 5
        assert e.lesson == ""

    def test_truncates_long_fields(self):
        llm = MagicMock()
        _llm_returns(
            llm,
            {
                "what_worked": "x" * 500,
                "what_failed": "y" * 500,
                "lesson": "z" * 500,
                "next_action": "w" * 500,
            },
        )
        e = reflect(llm, chapter_text="正文", chapter_number=1)
        assert all(
            len(getattr(e, k)) <= 300
            for k in ("what_worked", "what_failed", "lesson", "next_action")
        )
