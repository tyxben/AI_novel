"""测试 src.novel.utils.setting_version 的版本化查询辅助。"""

from __future__ import annotations

import pytest

from src.novel.utils.setting_version import (
    get_chapter_outline_at,
    get_setting_at_chapter,
    is_effective_at,
    list_settings_at_chapter,
)


# ---------------------------------------------------------------------------
# is_effective_at
# ---------------------------------------------------------------------------


class TestIsEffectiveAt:
    def test_no_version_fields_is_always_effective(self):
        assert is_effective_at({"character_id": "c1"}, 1) is True
        assert is_effective_at({"character_id": "c1"}, 99) is True

    def test_effective_from_inclusive(self):
        entry = {"effective_from_chapter": 5}
        assert is_effective_at(entry, 4) is False
        assert is_effective_at(entry, 5) is True
        assert is_effective_at(entry, 10) is True

    def test_deprecated_at_exclusive(self):
        entry = {"deprecated_at_chapter": 10}
        assert is_effective_at(entry, 9) is True
        assert is_effective_at(entry, 10) is False
        assert is_effective_at(entry, 11) is False

    def test_both_bounds(self):
        entry = {"effective_from_chapter": 1, "deprecated_at_chapter": 10}
        assert is_effective_at(entry, 1) is True
        assert is_effective_at(entry, 5) is True
        assert is_effective_at(entry, 9) is True
        assert is_effective_at(entry, 10) is False

    def test_none_fields_treated_as_unbounded(self):
        assert is_effective_at(
            {"effective_from_chapter": None, "deprecated_at_chapter": None}, 50
        ) is True


# ---------------------------------------------------------------------------
# get_setting_at_chapter — single version
# ---------------------------------------------------------------------------


class TestGetSettingSingleVersion:
    def test_no_version_fields_returns_entry(self):
        chars = [{"character_id": "c1", "name": "张三"}]
        result = get_setting_at_chapter(chars, "c1", chapter_num=5)
        assert result is not None
        assert result["name"] == "张三"

    def test_returns_none_for_unknown_id(self):
        chars = [{"character_id": "c1", "name": "张三"}]
        result = get_setting_at_chapter(chars, "c_missing", chapter_num=5)
        assert result is None

    def test_returns_none_when_before_effective_from(self):
        chars = [
            {
                "character_id": "c1",
                "name": "张三",
                "effective_from_chapter": 5,
            }
        ]
        assert get_setting_at_chapter(chars, "c1", 4) is None
        assert get_setting_at_chapter(chars, "c1", 5) is not None

    def test_returns_none_when_deprecated(self):
        chars = [
            {
                "character_id": "c1",
                "name": "张三",
                "effective_from_chapter": 1,
                "deprecated_at_chapter": 10,
            }
        ]
        assert get_setting_at_chapter(chars, "c1", 9)["name"] == "张三"
        assert get_setting_at_chapter(chars, "c1", 10) is None


# ---------------------------------------------------------------------------
# get_setting_at_chapter — multi version (spec example)
# ---------------------------------------------------------------------------


class TestGetSettingMultiVersion:
    def test_spec_example_two_versions(self):
        """来自 specs tasks 18.3 的验收示例。"""
        chars = [
            {
                "character_id": "c1",
                "name": "李明v1",
                "effective_from_chapter": 1,
                "deprecated_at_chapter": 10,
                "version": 1,
            },
            {
                "character_id": "c1",
                "name": "李明v2",
                "effective_from_chapter": 10,
                "version": 2,
            },
        ]
        assert get_setting_at_chapter(chars, "c1", 5)["name"] == "李明v1"
        assert get_setting_at_chapter(chars, "c1", 10)["name"] == "李明v2"
        assert get_setting_at_chapter(chars, "c1", 15)["name"] == "李明v2"

    def test_chapter_at_boundary_picks_v2(self):
        """effective_from=N, deprecated_at=N 的边界 → chapter=N 取新版。"""
        chars = [
            {
                "character_id": "c1",
                "name": "old",
                "effective_from_chapter": 1,
                "deprecated_at_chapter": 5,
            },
            {
                "character_id": "c1",
                "name": "new",
                "effective_from_chapter": 5,
            },
        ]
        assert get_setting_at_chapter(chars, "c1", 4)["name"] == "old"
        assert get_setting_at_chapter(chars, "c1", 5)["name"] == "new"

    def test_three_versions_middle_picked(self):
        chars = [
            {
                "character_id": "c1",
                "name": "v1",
                "effective_from_chapter": 1,
                "deprecated_at_chapter": 5,
                "version": 1,
            },
            {
                "character_id": "c1",
                "name": "v2",
                "effective_from_chapter": 5,
                "deprecated_at_chapter": 10,
                "version": 2,
            },
            {
                "character_id": "c1",
                "name": "v3",
                "effective_from_chapter": 10,
                "version": 3,
            },
        ]
        assert get_setting_at_chapter(chars, "c1", 2)["name"] == "v1"
        assert get_setting_at_chapter(chars, "c1", 7)["name"] == "v2"
        assert get_setting_at_chapter(chars, "c1", 99)["name"] == "v3"

    def test_overlap_prefers_higher_version(self):
        """重叠期间（数据异常）应选 effective_from 更大的那一版。"""
        chars = [
            {
                "character_id": "c1",
                "name": "v1",
                "effective_from_chapter": 1,
                "version": 1,
            },
            {
                "character_id": "c1",
                "name": "v2",
                "effective_from_chapter": 5,
                "version": 2,
            },
        ]
        result = get_setting_at_chapter(chars, "c1", 10)
        assert result["name"] == "v2"

    def test_only_older_version_effective(self):
        """目标章在较早版本范围内，应忽略之后的版本。"""
        chars = [
            {
                "character_id": "c1",
                "name": "v1",
                "effective_from_chapter": 1,
                "deprecated_at_chapter": 5,
            },
            {
                "character_id": "c1",
                "name": "v2",
                "effective_from_chapter": 5,
            },
        ]
        assert get_setting_at_chapter(chars, "c1", 3)["name"] == "v1"


# ---------------------------------------------------------------------------
# Custom id_field
# ---------------------------------------------------------------------------


class TestCustomIdField:
    def test_custom_id_field(self):
        items = [
            {"item_id": "sword", "name": "断魂剑", "effective_from_chapter": 1},
            {"item_id": "sword", "name": "惊虹剑", "effective_from_chapter": 5},
        ]
        result = get_setting_at_chapter(
            items, "sword", 7, id_field="item_id"
        )
        assert result["name"] == "惊虹剑"


# ---------------------------------------------------------------------------
# Defensive / edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_chapter_zero_raises(self):
        with pytest.raises(ValueError):
            get_setting_at_chapter([], "c1", chapter_num=0)

    def test_negative_chapter_raises(self):
        with pytest.raises(ValueError):
            get_setting_at_chapter([], "c1", chapter_num=-1)

    def test_empty_entries_returns_none(self):
        assert get_setting_at_chapter([], "c1", 1) is None

    def test_non_dict_entries_ignored(self):
        entries = [None, "garbage", 42, {"character_id": "c1", "name": "real"}]
        result = get_setting_at_chapter(entries, "c1", 1)
        assert result is not None
        assert result["name"] == "real"


# ---------------------------------------------------------------------------
# list_settings_at_chapter
# ---------------------------------------------------------------------------


class TestListSettingsAtChapter:
    def test_returns_only_active_entities_at_chapter(self):
        chars = [
            {
                "character_id": "c1",
                "name": "主角",
                "effective_from_chapter": 1,
            },
            {
                "character_id": "c2",
                "name": "已退场",
                "effective_from_chapter": 1,
                "deprecated_at_chapter": 5,
            },
            {
                "character_id": "c3",
                "name": "后来出场",
                "effective_from_chapter": 8,
            },
        ]
        at_3 = list_settings_at_chapter(chars, 3)
        names_3 = {c["name"] for c in at_3}
        assert names_3 == {"主角", "已退场"}

        at_6 = list_settings_at_chapter(chars, 6)
        names_6 = {c["name"] for c in at_6}
        assert names_6 == {"主角"}

        at_10 = list_settings_at_chapter(chars, 10)
        names_10 = {c["name"] for c in at_10}
        assert names_10 == {"主角", "后来出场"}

    def test_multi_version_deduplicated_by_id(self):
        chars = [
            {
                "character_id": "c1",
                "name": "v1",
                "effective_from_chapter": 1,
                "deprecated_at_chapter": 10,
                "version": 1,
            },
            {
                "character_id": "c1",
                "name": "v2",
                "effective_from_chapter": 10,
                "version": 2,
            },
            {
                "character_id": "c2",
                "name": "其他",
                "effective_from_chapter": 1,
            },
        ]
        at_12 = list_settings_at_chapter(chars, 12)
        assert len(at_12) == 2
        names = {c["name"] for c in at_12}
        assert names == {"v2", "其他"}

    def test_empty_list(self):
        assert list_settings_at_chapter([], 1) == []

    def test_chapter_zero_raises(self):
        with pytest.raises(ValueError):
            list_settings_at_chapter([], 0)


# ---------------------------------------------------------------------------
# get_chapter_outline_at
# ---------------------------------------------------------------------------


class TestGetChapterOutlineAt:
    def test_finds_chapter_by_number(self):
        chapters = [
            {"chapter_number": 1, "title": "第一"},
            {"chapter_number": 3, "title": "第三"},
            {"chapter_number": 5, "title": "第五"},
        ]
        assert get_chapter_outline_at(chapters, 3)["title"] == "第三"

    def test_missing_chapter_returns_none(self):
        chapters = [{"chapter_number": 1}]
        assert get_chapter_outline_at(chapters, 99) is None

    def test_ignores_non_dict_items(self):
        chapters = [None, {"chapter_number": 2, "title": "ok"}]
        assert get_chapter_outline_at(chapters, 2)["title"] == "ok"
