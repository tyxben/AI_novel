"""WorldSettingEditor 单元测试 — 世界观设定合并更新"""

import copy

import pytest

from src.novel.editors.world_editor import WorldSettingEditor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _novel_data_with_world_setting() -> dict:
    return {
        "world_setting": {
            "era": "古代",
            "location": "九州大陆",
            "power_system": {
                "name": "修炼境界",
                "levels": [
                    {"rank": 1, "name": "炼气期", "description": "入门阶段"},
                    {"rank": 2, "name": "筑基期", "description": "筑造根基"},
                ],
            },
            "terms": {
                "灵石": "修炼货币",
                "丹药": "辅助修炼的药物",
            },
            "rules": ["灵气为修炼之本", "突破需渡劫"],
            "version": 1,
            "effective_from_chapter": None,
            "deprecated_at_chapter": None,
        }
    }


@pytest.fixture
def editor():
    return WorldSettingEditor()


# ---------------------------------------------------------------------------
# Update tests
# ---------------------------------------------------------------------------


class TestUpdateWorldSetting:
    def test_update_era(self, editor):
        novel_data = _novel_data_with_world_setting()
        change = {
            "change_type": "update",
            "effective_from_chapter": 20,
            "data": {"era": "远古"},
        }

        old, new = editor.apply(novel_data, change)

        assert old["era"] == "古代"
        assert new["era"] == "远古"
        # Other fields preserved
        assert new["location"] == "九州大陆"

    def test_update_terms_merge(self, editor):
        """Dict fields should merge, not replace."""
        novel_data = _novel_data_with_world_setting()
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {
                "terms": {"法宝": "修炼者使用的武器"},
            },
        }

        old, new = editor.apply(novel_data, change)

        # Old terms should still be present
        assert "灵石" in new["terms"]
        assert "丹药" in new["terms"]
        # New term added
        assert new["terms"]["法宝"] == "修炼者使用的武器"

    def test_update_terms_overwrite_existing(self, editor):
        """Merging should overwrite existing keys."""
        novel_data = _novel_data_with_world_setting()
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {
                "terms": {"灵石": "通用交易媒介"},  # override
            },
        }

        _, new = editor.apply(novel_data, change)

        assert new["terms"]["灵石"] == "通用交易媒介"
        assert new["terms"]["丹药"] == "辅助修炼的药物"  # untouched

    def test_update_rules_replaces_list(self, editor):
        """List fields should be replaced (not merged)."""
        novel_data = _novel_data_with_world_setting()
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {
                "rules": ["新规则一", "新规则二"],
            },
        }

        old, new = editor.apply(novel_data, change)

        assert old["rules"] == ["灵气为修炼之本", "突破需渡劫"]
        assert new["rules"] == ["新规则一", "新规则二"]

    def test_update_power_system(self, editor):
        """Replacing power_system entirely."""
        novel_data = _novel_data_with_world_setting()
        change = {
            "change_type": "update",
            "effective_from_chapter": 10,
            "data": {
                "power_system": {
                    "name": "武道境界",
                    "levels": [
                        {"rank": 1, "name": "武徒", "description": "初学者"},
                    ],
                },
            },
        }

        old, new = editor.apply(novel_data, change)

        assert old["power_system"]["name"] == "修炼境界"
        assert new["power_system"]["name"] == "武道境界"
        assert len(new["power_system"]["levels"]) == 1

    def test_update_version_increments(self, editor):
        novel_data = _novel_data_with_world_setting()
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {"location": "中原"},
        }

        _, new = editor.apply(novel_data, change)
        assert new["version"] == 2  # was 1

    def test_update_effective_from_chapter_set(self, editor):
        novel_data = _novel_data_with_world_setting()
        change = {
            "change_type": "update",
            "effective_from_chapter": 15,
            "data": {"location": "西域"},
        }

        _, new = editor.apply(novel_data, change)
        assert new["effective_from_chapter"] == 15

    def test_update_preserves_old_immutably(self, editor):
        novel_data = _novel_data_with_world_setting()
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {"era": "未来"},
        }

        old, _ = editor.apply(novel_data, change)
        old["era"] = "被篡改"
        assert novel_data["world_setting"]["era"] == "未来"

    def test_update_empty_data(self, editor):
        """Update with empty data should still increment version."""
        novel_data = _novel_data_with_world_setting()
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {},
        }

        old, new = editor.apply(novel_data, change)
        assert new["version"] == 2
        assert new["era"] == "古代"  # unchanged


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestWorldSettingEditorErrors:
    def test_missing_world_setting(self, editor):
        novel_data = {}
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {"era": "未来"},
        }

        with pytest.raises(ValueError, match="world_setting"):
            editor.apply(novel_data, change)

    def test_add_not_supported(self, editor):
        novel_data = _novel_data_with_world_setting()
        change = {
            "change_type": "add",
            "data": {},
        }

        with pytest.raises(ValueError, match="不支持"):
            editor.apply(novel_data, change)

    def test_delete_not_supported(self, editor):
        novel_data = _novel_data_with_world_setting()
        change = {
            "change_type": "delete",
            "data": {},
        }

        with pytest.raises(ValueError, match="不支持"):
            editor.apply(novel_data, change)

    def test_unknown_change_type(self, editor):
        novel_data = _novel_data_with_world_setting()
        change = {"change_type": "reset", "data": {}}

        with pytest.raises(ValueError, match="不支持"):
            editor.apply(novel_data, change)

    def test_validation_error_invalid_era(self, editor):
        """Setting era to empty string should fail Pydantic validation."""
        novel_data = _novel_data_with_world_setting()
        change = {
            "change_type": "update",
            "effective_from_chapter": None,
            "data": {"era": ""},  # min_length=1 violation
        }

        with pytest.raises(Exception):  # ValidationError
            editor.apply(novel_data, change)
