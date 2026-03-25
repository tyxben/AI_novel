"""CharacterEditor 单元测试 — 增删改角色"""

import copy

import pytest

from src.novel.editors.character_editor import CharacterEditor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _full_character_data() -> dict:
    """A complete character data dict for add operations."""
    return {
        "name": "柳青鸾",
        "gender": "女",
        "age": 28,
        "occupation": "剑客",
        "appearance": {
            "height": "168cm",
            "build": "匀称",
            "hair": "黑色长发",
            "eyes": "凤眼",
            "clothing_style": "青衣",
        },
        "personality": {
            "traits": ["冷傲", "聪慧", "重情"],
            "core_belief": "以剑问道",
            "motivation": "寻找失踪的师父",
            "flaw": "不信任他人",
            "speech_style": "冷淡简短",
        },
    }


def _novel_data_with_character() -> dict:
    """Novel data containing one existing character."""
    char = _full_character_data()
    char["character_id"] = "char_001"
    char["status"] = "active"
    char["version"] = 1
    char["effective_from_chapter"] = None
    char["deprecated_at_chapter"] = None
    return {"characters": [char]}


@pytest.fixture
def editor():
    return CharacterEditor()


# ---------------------------------------------------------------------------
# Add tests
# ---------------------------------------------------------------------------


class TestAddCharacter:
    def test_add_character_basic(self, editor):
        novel_data = {"characters": []}
        change = {
            "change_type": "add",
            "effective_from_chapter": 5,
            "data": _full_character_data(),
        }

        old, new = editor.apply(novel_data, change)

        assert old is None
        assert new["name"] == "柳青鸾"
        assert "character_id" in new
        assert new["effective_from_chapter"] == 5
        assert new["version"] == 1  # first version
        assert len(novel_data["characters"]) == 1

    def test_add_character_auto_generates_uuid(self, editor):
        novel_data = {"characters": []}
        change = {
            "change_type": "add",
            "effective_from_chapter": None,
            "data": _full_character_data(),
        }

        _, new = editor.apply(novel_data, change)
        assert len(new["character_id"]) == 36  # UUID length

    def test_add_character_preserves_provided_id(self, editor):
        novel_data = {"characters": []}
        data = _full_character_data()
        data["character_id"] = "my_custom_id"
        change = {
            "change_type": "add",
            "effective_from_chapter": 1,
            "data": data,
        }

        _, new = editor.apply(novel_data, change)
        assert new["character_id"] == "my_custom_id"

    def test_add_character_creates_characters_list_if_missing(self, editor):
        novel_data = {}
        change = {
            "change_type": "add",
            "effective_from_chapter": None,
            "data": _full_character_data(),
        }

        editor.apply(novel_data, change)
        assert "characters" in novel_data
        assert len(novel_data["characters"]) == 1

    def test_add_character_validation_error(self, editor):
        """Missing required fields should raise."""
        novel_data = {"characters": []}
        change = {
            "change_type": "add",
            "effective_from_chapter": None,
            "data": {"name": "不完整角色"},  # missing required fields
        }

        with pytest.raises(Exception):  # ValidationError
            editor.apply(novel_data, change)

    def test_add_character_with_empty_data(self, editor):
        novel_data = {"characters": []}
        change = {
            "change_type": "add",
            "effective_from_chapter": None,
            "data": {},
        }

        with pytest.raises(Exception):
            editor.apply(novel_data, change)


# ---------------------------------------------------------------------------
# Update tests
# ---------------------------------------------------------------------------


class TestUpdateCharacter:
    def test_update_character_basic(self, editor):
        novel_data = _novel_data_with_character()
        change = {
            "change_type": "update",
            "entity_id": "char_001",
            "effective_from_chapter": 10,
            "data": {"age": 30, "occupation": "宗师"},
        }

        old, new = editor.apply(novel_data, change)

        assert old["age"] == 28
        assert old["occupation"] == "剑客"
        assert new["age"] == 30
        assert new["occupation"] == "宗师"
        # Name should be untouched
        assert new["name"] == "柳青鸾"

    def test_update_character_version_increments(self, editor):
        novel_data = _novel_data_with_character()
        change = {
            "change_type": "update",
            "entity_id": "char_001",
            "effective_from_chapter": 10,
            "data": {"age": 30},
        }

        _, new = editor.apply(novel_data, change)
        assert new["version"] == 2  # was 1, now 2

    def test_update_character_not_found(self, editor):
        novel_data = _novel_data_with_character()
        change = {
            "change_type": "update",
            "entity_id": "nonexistent_id",
            "effective_from_chapter": 1,
            "data": {"age": 30},
        }

        with pytest.raises(ValueError, match="角色不存在"):
            editor.apply(novel_data, change)

    def test_update_character_missing_entity_id(self, editor):
        novel_data = _novel_data_with_character()
        change = {
            "change_type": "update",
            "effective_from_chapter": 1,
            "data": {"age": 30},
        }

        with pytest.raises(ValueError, match="entity_id"):
            editor.apply(novel_data, change)

    def test_update_preserves_old_value_immutably(self, editor):
        """old_value should be a deep copy, not a reference."""
        novel_data = _novel_data_with_character()
        change = {
            "change_type": "update",
            "entity_id": "char_001",
            "effective_from_chapter": 5,
            "data": {"name": "新名字"},
        }

        old, _ = editor.apply(novel_data, change)
        # Mutating old should not affect novel_data
        old["name"] = "被篡改"
        assert novel_data["characters"][0]["name"] == "新名字"

    def test_update_character_empty_characters_list(self, editor):
        novel_data = {"characters": []}
        change = {
            "change_type": "update",
            "entity_id": "char_001",
            "effective_from_chapter": 1,
            "data": {"age": 30},
        }

        with pytest.raises(ValueError, match="角色不存在"):
            editor.apply(novel_data, change)


# ---------------------------------------------------------------------------
# Delete tests
# ---------------------------------------------------------------------------


class TestDeleteCharacter:
    def test_delete_character_soft_delete(self, editor):
        novel_data = _novel_data_with_character()
        change = {
            "change_type": "delete",
            "entity_id": "char_001",
            "effective_from_chapter": 15,
        }

        old, new = editor.apply(novel_data, change)

        assert old["status"] == "active"
        assert new["status"] == "retired"
        assert new["deprecated_at_chapter"] == 15
        # Character should still be in the list (soft delete)
        assert len(novel_data["characters"]) == 1

    def test_delete_character_not_found(self, editor):
        novel_data = _novel_data_with_character()
        change = {
            "change_type": "delete",
            "entity_id": "nonexistent",
            "effective_from_chapter": 1,
        }

        with pytest.raises(ValueError, match="角色不存在"):
            editor.apply(novel_data, change)

    def test_delete_character_missing_entity_id(self, editor):
        novel_data = _novel_data_with_character()
        change = {
            "change_type": "delete",
            "effective_from_chapter": 1,
        }

        with pytest.raises(ValueError, match="entity_id"):
            editor.apply(novel_data, change)

    def test_delete_preserves_old_value_immutably(self, editor):
        novel_data = _novel_data_with_character()
        change = {
            "change_type": "delete",
            "entity_id": "char_001",
            "effective_from_chapter": 20,
        }

        old, _ = editor.apply(novel_data, change)
        old["status"] = "tampered"
        assert novel_data["characters"][0]["status"] == "retired"

    def test_delete_without_effective_from(self, editor):
        """Delete with effective_from_chapter=None should still soft-delete."""
        novel_data = _novel_data_with_character()
        change = {
            "change_type": "delete",
            "entity_id": "char_001",
            "effective_from_chapter": None,
        }

        _, new = editor.apply(novel_data, change)
        assert new["status"] == "retired"
        # deprecated_at_chapter not set when effective_from is None
        assert new.get("deprecated_at_chapter") is None


# ---------------------------------------------------------------------------
# Invalid change_type
# ---------------------------------------------------------------------------


class TestInvalidChangeType:
    def test_unsupported_change_type(self, editor):
        novel_data = {"characters": []}
        change = {"change_type": "merge", "data": {}}

        with pytest.raises(ValueError, match="不支持"):
            editor.apply(novel_data, change)

    def test_none_change_type(self, editor):
        novel_data = {"characters": []}
        change = {"data": {}}

        with pytest.raises(ValueError):
            editor.apply(novel_data, change)
