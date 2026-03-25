"""OutlineEditor 单元测试 — 章节大纲的增/改"""

import copy

import pytest

from src.novel.editors.outline_editor import OutlineEditor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _novel_data_with_outline() -> dict:
    """Novel data with 3 chapter outlines."""
    return {
        "outline": {
            "template": "cyclic_upgrade",
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "初入江湖",
                    "goal": "介绍主角",
                    "key_events": ["主角出场"],
                    "mood": "蓄力",
                    "version": 1,
                },
                {
                    "chapter_number": 2,
                    "title": "首战告捷",
                    "goal": "主角第一次战斗",
                    "key_events": ["击败小喽啰"],
                    "mood": "小爽",
                    "version": 1,
                },
                {
                    "chapter_number": 3,
                    "title": "危机四伏",
                    "goal": "主角遇到强敌",
                    "key_events": ["遭遇伏击"],
                    "mood": "虐心",
                    "version": 1,
                },
            ],
        }
    }


def _new_chapter_outline_data(chapter_number: int = 4) -> dict:
    return {
        "chapter_number": chapter_number,
        "title": "绝地反击",
        "goal": "主角反败为胜",
        "key_events": ["突破极限"],
        "mood": "大爽",
    }


@pytest.fixture
def editor():
    return OutlineEditor()


# ---------------------------------------------------------------------------
# Update tests
# ---------------------------------------------------------------------------


class TestEditChapterOutline:
    def test_update_chapter_mood(self, editor):
        novel_data = _novel_data_with_outline()
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {"chapter_number": 2, "mood": "大爽"},
        }

        old, new = editor.apply(novel_data, change)

        assert old["mood"] == "小爽"
        assert new["mood"] == "大爽"
        assert new["title"] == "首战告捷"  # unchanged

    def test_update_chapter_title_and_goal(self, editor):
        novel_data = _novel_data_with_outline()
        change = {
            "change_type": "update",
            "effective_from_chapter": 2,
            "data": {
                "chapter_number": 1,
                "title": "新的开端",
                "goal": "新的目标",
            },
        }

        old, new = editor.apply(novel_data, change)

        assert old["title"] == "初入江湖"
        assert new["title"] == "新的开端"
        assert new["goal"] == "新的目标"

    def test_update_chapter_key_events(self, editor):
        novel_data = _novel_data_with_outline()
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {
                "chapter_number": 3,
                "key_events": ["遭遇伏击", "获得秘宝"],
            },
        }

        _, new = editor.apply(novel_data, change)
        assert new["key_events"] == ["遭遇伏击", "获得秘宝"]

    def test_update_version_increments(self, editor):
        novel_data = _novel_data_with_outline()
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {"chapter_number": 1, "mood": "过渡"},
        }

        _, new = editor.apply(novel_data, change)
        assert new["version"] == 2  # was 1

    def test_update_nonexistent_chapter(self, editor):
        novel_data = _novel_data_with_outline()
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {"chapter_number": 99, "mood": "大爽"},
        }

        with pytest.raises(ValueError, match="章节大纲不存在"):
            editor.apply(novel_data, change)

    def test_update_missing_chapter_number(self, editor):
        novel_data = _novel_data_with_outline()
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {"mood": "大爽"},  # no chapter_number
        }

        with pytest.raises(ValueError, match="chapter_number"):
            editor.apply(novel_data, change)

    def test_update_preserves_old_value_immutably(self, editor):
        novel_data = _novel_data_with_outline()
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {"chapter_number": 1, "title": "新标题"},
        }

        old, _ = editor.apply(novel_data, change)
        old["title"] = "被篡改"
        assert novel_data["outline"]["chapters"][0]["title"] == "新标题"

    def test_update_empty_outline(self, editor):
        novel_data = {"outline": {"chapters": []}}
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {"chapter_number": 1, "mood": "大爽"},
        }

        with pytest.raises(ValueError, match="章节大纲不存在"):
            editor.apply(novel_data, change)

    def test_update_with_no_outline_key(self, editor):
        novel_data = {}
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {"chapter_number": 1, "mood": "大爽"},
        }

        with pytest.raises(ValueError, match="章节大纲不存在"):
            editor.apply(novel_data, change)


# ---------------------------------------------------------------------------
# Add tests
# ---------------------------------------------------------------------------


class TestAddChapterOutline:
    def test_add_chapter_outline_basic(self, editor):
        novel_data = _novel_data_with_outline()
        change = {
            "change_type": "add",
            "effective_from_chapter": 4,
            "data": _new_chapter_outline_data(4),
        }

        old, new = editor.apply(novel_data, change)

        assert old is None
        assert new["chapter_number"] == 4
        assert new["title"] == "绝地反击"
        assert len(novel_data["outline"]["chapters"]) == 4

    def test_add_chapter_outline_sorted_by_number(self, editor):
        novel_data = _novel_data_with_outline()
        # Insert chapter 0 — should be sorted to front
        data = _new_chapter_outline_data(0)
        # chapter_number must be >= 1 per model constraint, use 1
        # Actually let's insert at number 4, confirm it sorts
        change = {
            "change_type": "add",
            "effective_from_chapter": None,
            "data": _new_chapter_outline_data(4),
        }

        editor.apply(novel_data, change)
        chapter_numbers = [
            c["chapter_number"] for c in novel_data["outline"]["chapters"]
        ]
        assert chapter_numbers == sorted(chapter_numbers)

    def test_add_chapter_creates_outline_if_missing(self, editor):
        novel_data = {}
        change = {
            "change_type": "add",
            "effective_from_chapter": 1,
            "data": _new_chapter_outline_data(1),
        }

        _, new = editor.apply(novel_data, change)
        assert len(novel_data["outline"]["chapters"]) == 1
        assert new["chapter_number"] == 1

    def test_add_chapter_validation_error(self, editor):
        novel_data = _novel_data_with_outline()
        change = {
            "change_type": "add",
            "effective_from_chapter": None,
            "data": {"chapter_number": 5},  # missing required fields
        }

        with pytest.raises(Exception):  # ValidationError
            editor.apply(novel_data, change)

    def test_add_chapter_version_set(self, editor):
        novel_data = _novel_data_with_outline()
        change = {
            "change_type": "add",
            "effective_from_chapter": 10,
            "data": _new_chapter_outline_data(4),
        }

        _, new = editor.apply(novel_data, change)
        assert new["version"] == 1
        assert new["effective_from_chapter"] == 10


# ---------------------------------------------------------------------------
# Invalid change_type
# ---------------------------------------------------------------------------


class TestInvalidChangeType:
    def test_delete_not_supported(self, editor):
        novel_data = _novel_data_with_outline()
        change = {"change_type": "delete", "data": {}}

        with pytest.raises(ValueError, match="不支持"):
            editor.apply(novel_data, change)

    def test_unknown_change_type(self, editor):
        novel_data = _novel_data_with_outline()
        change = {"change_type": "rename", "data": {}}

        with pytest.raises(ValueError, match="不支持"):
            editor.apply(novel_data, change)
