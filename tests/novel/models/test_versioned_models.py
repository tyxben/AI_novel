"""测试数据模型版本字段扩展 — 向后兼容性 + 新字段验证"""

import pytest
from pydantic import ValidationError

from src.novel.models.character import (
    Appearance,
    CharacterArc,
    CharacterProfile,
    Personality,
)
from src.novel.models.novel import ChapterOutline
from src.novel.models.world import PowerLevel, PowerSystem, WorldSetting


# ---------------------------------------------------------------------------
# Fixtures: minimal valid data without new version fields (simulates old data)
# ---------------------------------------------------------------------------


def _minimal_character_data() -> dict:
    """Return the smallest dict that was valid BEFORE version fields existed."""
    return {
        "name": "李明",
        "gender": "男",
        "age": 20,
        "occupation": "剑客",
        "appearance": {
            "height": "175cm",
            "build": "匀称",
            "hair": "黑色长发",
            "eyes": "黑色",
            "clothing_style": "白袍",
        },
        "personality": {
            "traits": ["果断", "善良", "沉稳"],
            "core_belief": "正义必胜",
            "motivation": "保护家人",
            "flaw": "过于信任他人",
            "speech_style": "冷淡简短",
        },
    }


def _minimal_chapter_outline_data() -> dict:
    return {
        "chapter_number": 1,
        "title": "初入江湖",
        "goal": "介绍主角",
        "key_events": ["主角出场"],
    }


def _minimal_world_setting_data() -> dict:
    return {
        "era": "古代",
        "location": "九州大陆",
    }


# ---------------------------------------------------------------------------
# CharacterProfile backward-compat tests
# ---------------------------------------------------------------------------


class TestCharacterProfileVersionFields:
    def test_old_data_loads_without_version_fields(self):
        """Old data (no version fields) must load successfully with defaults."""
        data = _minimal_character_data()
        profile = CharacterProfile.model_validate(data)

        assert profile.name == "李明"
        assert profile.effective_from_chapter is None
        assert profile.deprecated_at_chapter is None
        assert profile.version == 1

    def test_new_data_with_version_fields(self):
        """Data that includes version fields must load correctly."""
        data = _minimal_character_data()
        data["effective_from_chapter"] = 10
        data["deprecated_at_chapter"] = 20
        data["version"] = 3

        profile = CharacterProfile.model_validate(data)

        assert profile.effective_from_chapter == 10
        assert profile.deprecated_at_chapter == 20
        assert profile.version == 3

    def test_version_ge_1(self):
        """Version must be >= 1."""
        data = _minimal_character_data()
        data["version"] = 0

        with pytest.raises(ValidationError) as exc_info:
            CharacterProfile.model_validate(data)

        errors = exc_info.value.errors()
        assert any("version" in str(e["loc"]) for e in errors)

    def test_version_default_is_1(self):
        """Default version value is 1."""
        data = _minimal_character_data()
        profile = CharacterProfile.model_validate(data)
        assert profile.version == 1

    def test_effective_from_chapter_none_means_always(self):
        """effective_from_chapter=None means from the beginning."""
        data = _minimal_character_data()
        data["effective_from_chapter"] = None
        profile = CharacterProfile.model_validate(data)
        assert profile.effective_from_chapter is None

    def test_deprecated_at_chapter_none_means_active(self):
        """deprecated_at_chapter=None means still active."""
        data = _minimal_character_data()
        data["deprecated_at_chapter"] = None
        profile = CharacterProfile.model_validate(data)
        assert profile.deprecated_at_chapter is None

    def test_serialization_roundtrip(self):
        """Serialize to dict then back should preserve version fields."""
        data = _minimal_character_data()
        data["effective_from_chapter"] = 5
        data["version"] = 2

        profile = CharacterProfile.model_validate(data)
        dumped = profile.model_dump()
        restored = CharacterProfile.model_validate(dumped)

        assert restored.effective_from_chapter == 5
        assert restored.version == 2
        assert restored.deprecated_at_chapter is None

    def test_json_roundtrip(self):
        """JSON serialize/deserialize preserves version fields."""
        data = _minimal_character_data()
        data["effective_from_chapter"] = 7
        data["deprecated_at_chapter"] = 15
        data["version"] = 4

        profile = CharacterProfile.model_validate(data)
        json_str = profile.model_dump_json()
        restored = CharacterProfile.model_validate_json(json_str)

        assert restored.effective_from_chapter == 7
        assert restored.deprecated_at_chapter == 15
        assert restored.version == 4


# ---------------------------------------------------------------------------
# ChapterOutline backward-compat tests
# ---------------------------------------------------------------------------


class TestChapterOutlineVersionFields:
    def test_old_data_loads_without_version_fields(self):
        data = _minimal_chapter_outline_data()
        outline = ChapterOutline.model_validate(data)

        assert outline.chapter_number == 1
        assert outline.effective_from_chapter is None
        assert outline.deprecated_at_chapter is None
        assert outline.version == 1

    def test_new_data_with_version_fields(self):
        data = _minimal_chapter_outline_data()
        data["effective_from_chapter"] = 3
        data["deprecated_at_chapter"] = 10
        data["version"] = 2

        outline = ChapterOutline.model_validate(data)

        assert outline.effective_from_chapter == 3
        assert outline.deprecated_at_chapter == 10
        assert outline.version == 2

    def test_version_ge_1(self):
        data = _minimal_chapter_outline_data()
        data["version"] = 0

        with pytest.raises(ValidationError) as exc_info:
            ChapterOutline.model_validate(data)

        errors = exc_info.value.errors()
        assert any("version" in str(e["loc"]) for e in errors)

    def test_serialization_roundtrip(self):
        data = _minimal_chapter_outline_data()
        data["effective_from_chapter"] = 2
        data["version"] = 3

        outline = ChapterOutline.model_validate(data)
        dumped = outline.model_dump()
        restored = ChapterOutline.model_validate(dumped)

        assert restored.effective_from_chapter == 2
        assert restored.version == 3


# ---------------------------------------------------------------------------
# WorldSetting backward-compat tests
# ---------------------------------------------------------------------------


class TestWorldSettingVersionFields:
    def test_old_data_loads_without_version_fields(self):
        data = _minimal_world_setting_data()
        ws = WorldSetting.model_validate(data)

        assert ws.era == "古代"
        assert ws.effective_from_chapter is None
        assert ws.deprecated_at_chapter is None
        assert ws.version == 1

    def test_new_data_with_version_fields(self):
        data = _minimal_world_setting_data()
        data["effective_from_chapter"] = 1
        data["deprecated_at_chapter"] = 50
        data["version"] = 5

        ws = WorldSetting.model_validate(data)

        assert ws.effective_from_chapter == 1
        assert ws.deprecated_at_chapter == 50
        assert ws.version == 5

    def test_version_ge_1(self):
        data = _minimal_world_setting_data()
        data["version"] = -1

        with pytest.raises(ValidationError) as exc_info:
            WorldSetting.model_validate(data)

        errors = exc_info.value.errors()
        assert any("version" in str(e["loc"]) for e in errors)

    def test_with_power_system_and_version(self):
        """WorldSetting with power_system plus version fields."""
        data = _minimal_world_setting_data()
        data["power_system"] = {
            "name": "修炼境界",
            "levels": [
                {
                    "rank": 1,
                    "name": "炼气期",
                    "description": "修炼入门阶段",
                }
            ],
        }
        data["rules"] = ["灵气为修炼之本"]
        data["version"] = 2
        data["effective_from_chapter"] = 1

        ws = WorldSetting.model_validate(data)

        assert ws.power_system is not None
        assert ws.power_system.name == "修炼境界"
        assert ws.version == 2
        assert len(ws.rules) == 1

    def test_serialization_roundtrip(self):
        data = _minimal_world_setting_data()
        data["effective_from_chapter"] = 10
        data["deprecated_at_chapter"] = 30
        data["version"] = 2
        data["terms"] = {"灵石": "修炼货币"}

        ws = WorldSetting.model_validate(data)
        dumped = ws.model_dump()
        restored = WorldSetting.model_validate(dumped)

        assert restored.effective_from_chapter == 10
        assert restored.deprecated_at_chapter == 30
        assert restored.version == 2
        assert restored.terms["灵石"] == "修炼货币"


# ---------------------------------------------------------------------------
# Cross-model consistency tests
# ---------------------------------------------------------------------------


class TestVersionFieldConsistency:
    """Ensure all three models share the same version field semantics."""

    @pytest.mark.parametrize(
        "model_cls,factory",
        [
            (CharacterProfile, _minimal_character_data),
            (ChapterOutline, _minimal_chapter_outline_data),
            (WorldSetting, _minimal_world_setting_data),
        ],
    )
    def test_defaults_consistent(self, model_cls, factory):
        """All models default to version=1, effective_from=None, deprecated_at=None."""
        obj = model_cls.model_validate(factory())
        assert obj.version == 1
        assert obj.effective_from_chapter is None
        assert obj.deprecated_at_chapter is None

    @pytest.mark.parametrize(
        "model_cls,factory",
        [
            (CharacterProfile, _minimal_character_data),
            (ChapterOutline, _minimal_chapter_outline_data),
            (WorldSetting, _minimal_world_setting_data),
        ],
    )
    def test_negative_version_rejected(self, model_cls, factory):
        data = factory()
        data["version"] = -5
        with pytest.raises(ValidationError):
            model_cls.model_validate(data)
