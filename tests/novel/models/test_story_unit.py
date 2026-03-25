"""Tests for StoryUnit and ArcBrief data models"""

import pytest
from pydantic import ValidationError

from src.novel.models.story_unit import ArcBrief, StoryUnit


# ---------------------------------------------------------------------------
# Fixtures: minimal valid data
# ---------------------------------------------------------------------------


def _valid_story_unit_data() -> dict:
    """Return smallest valid StoryUnit dict."""
    return {
        "volume_id": 1,
        "name": "新生试炼篇",
        "chapters": [1, 2, 3],
        "hook": "主角被卷入试炼场",
        "escalation_point": 2,
        "turning_point": 3,
        "closure_method": "主角险胜试炼",
        "residual_question": "试炼背后的黑手是谁？",
    }


def _valid_arc_brief_data() -> dict:
    """Return smallest valid ArcBrief dict."""
    return {
        "arc_id": "test-arc-001",
        "central_conflict": "主角与师门叛徒的对决",
        "protagonist_goal": "找回被盗的宗门秘宝",
        "success_consequence": "宗门地位稳固",
        "failure_consequence": "宗门面临解散危机",
        "climax_description": "主角在绝境中觉醒隐藏血脉",
        "resolution_outcome": "秘宝夺回，叛徒逃走留下伏笔",
    }


# ---------------------------------------------------------------------------
# StoryUnit tests
# ---------------------------------------------------------------------------


class TestStoryUnit:
    def test_story_unit_valid(self):
        """Create valid StoryUnit, verify all fields."""
        data = _valid_story_unit_data()
        unit = StoryUnit.model_validate(data)

        assert unit.volume_id == 1
        assert unit.name == "新生试炼篇"
        assert unit.chapters == [1, 2, 3]
        assert unit.phase == "setup"
        assert unit.hook == "主角被卷入试炼场"
        assert unit.escalation_point == 2
        assert unit.turning_point == 3
        assert unit.closure_method == "主角险胜试炼"
        assert unit.residual_question == "试炼背后的黑手是谁？"
        assert unit.status == "planning"
        assert unit.completion_rate == 0.0
        # arc_id auto-generated
        assert len(unit.arc_id) > 0

    def test_story_unit_invalid_chapters_too_few(self):
        """Chapters list shorter than 3 raises ValidationError."""
        data = _valid_story_unit_data()
        data["chapters"] = [1, 2]

        with pytest.raises(ValidationError) as exc_info:
            StoryUnit.model_validate(data)

        errors = exc_info.value.errors()
        assert any("chapters" in str(e["loc"]) for e in errors)

    def test_story_unit_invalid_chapters_too_many(self):
        """Chapters list longer than 7 raises ValidationError."""
        data = _valid_story_unit_data()
        data["chapters"] = [1, 2, 3, 4, 5, 6, 7, 8]

        with pytest.raises(ValidationError) as exc_info:
            StoryUnit.model_validate(data)

        errors = exc_info.value.errors()
        assert any("chapters" in str(e["loc"]) for e in errors)

    def test_story_unit_max_chapters_valid(self):
        """7 chapters (maximum) should be valid."""
        data = _valid_story_unit_data()
        data["chapters"] = [1, 2, 3, 4, 5, 6, 7]

        unit = StoryUnit.model_validate(data)
        assert len(unit.chapters) == 7

    def test_story_unit_invalid_phase(self):
        """Invalid phase value raises ValidationError."""
        data = _valid_story_unit_data()
        data["phase"] = "unknown_phase"

        with pytest.raises(ValidationError):
            StoryUnit.model_validate(data)

    def test_story_unit_invalid_status(self):
        """Invalid status value raises ValidationError."""
        data = _valid_story_unit_data()
        data["status"] = "invalid_status"

        with pytest.raises(ValidationError):
            StoryUnit.model_validate(data)

    def test_story_unit_completion_rate_bounds(self):
        """completion_rate must be between 0.0 and 1.0."""
        data = _valid_story_unit_data()

        data["completion_rate"] = -0.1
        with pytest.raises(ValidationError):
            StoryUnit.model_validate(data)

        data["completion_rate"] = 1.1
        with pytest.raises(ValidationError):
            StoryUnit.model_validate(data)

        data["completion_rate"] = 0.5
        unit = StoryUnit.model_validate(data)
        assert unit.completion_rate == 0.5

    def test_story_unit_empty_name_rejected(self):
        """Empty name string raises ValidationError."""
        data = _valid_story_unit_data()
        data["name"] = ""

        with pytest.raises(ValidationError):
            StoryUnit.model_validate(data)

    def test_story_unit_volume_id_must_be_positive(self):
        """volume_id must be >= 1."""
        data = _valid_story_unit_data()
        data["volume_id"] = 0

        with pytest.raises(ValidationError):
            StoryUnit.model_validate(data)

    def test_story_unit_serialization_json_roundtrip(self):
        """JSON serialize/deserialize preserves all fields."""
        data = _valid_story_unit_data()
        data["phase"] = "escalation"
        data["status"] = "in_progress"
        data["completion_rate"] = 0.6

        unit = StoryUnit.model_validate(data)
        json_str = unit.model_dump_json()
        restored = StoryUnit.model_validate_json(json_str)

        assert restored.name == unit.name
        assert restored.chapters == unit.chapters
        assert restored.phase == "escalation"
        assert restored.status == "in_progress"
        assert restored.completion_rate == 0.6
        assert restored.arc_id == unit.arc_id

    def test_story_unit_serialization_dict_roundtrip(self):
        """Dict serialize/deserialize preserves all fields."""
        data = _valid_story_unit_data()
        unit = StoryUnit.model_validate(data)
        dumped = unit.model_dump()
        restored = StoryUnit.model_validate(dumped)

        assert restored.name == unit.name
        assert restored.arc_id == unit.arc_id
        assert restored.chapters == unit.chapters

    def test_story_unit_repr(self):
        """__repr__ includes key fields."""
        unit = StoryUnit.model_validate(_valid_story_unit_data())
        repr_str = repr(unit)

        assert "StoryUnit" in repr_str
        assert "新生试炼篇" in repr_str
        assert "setup" in repr_str

    def test_story_unit_str(self):
        """__str__ produces human-readable summary."""
        unit = StoryUnit.model_validate(_valid_story_unit_data())
        str_repr = str(unit)

        assert "planning" in str_repr
        assert "新生试炼篇" in str_repr
        assert "ch.1-3" in str_repr


# ---------------------------------------------------------------------------
# ArcBrief tests
# ---------------------------------------------------------------------------


class TestArcBrief:
    def test_arc_brief_valid(self):
        """Create valid ArcBrief, verify fields."""
        data = _valid_arc_brief_data()
        brief = ArcBrief.model_validate(data)

        assert brief.arc_id == "test-arc-001"
        assert brief.central_conflict == "主角与师门叛徒的对决"
        assert brief.protagonist_goal == "找回被盗的宗门秘宝"
        assert brief.antagonist_goal == ""
        assert brief.success_consequence == "宗门地位稳固"
        assert brief.failure_consequence == "宗门面临解散危机"
        assert brief.setup_beats == []
        assert brief.escalation_beats == []
        assert brief.climax_description == "主角在绝境中觉醒隐藏血脉"
        assert brief.resolution_outcome == "秘宝夺回，叛徒逃走留下伏笔"

    def test_arc_brief_with_beats(self):
        """ArcBrief with setup_beats and escalation_beats."""
        data = _valid_arc_brief_data()
        data["setup_beats"] = ["主角抵达宗门", "发现秘宝失踪"]
        data["escalation_beats"] = ["追踪叛徒线索", "遭遇伏击"]

        brief = ArcBrief.model_validate(data)

        assert len(brief.setup_beats) == 2
        assert len(brief.escalation_beats) == 2

    def test_arc_brief_missing_required_field(self):
        """Missing required field raises ValidationError."""
        data = _valid_arc_brief_data()
        del data["central_conflict"]

        with pytest.raises(ValidationError) as exc_info:
            ArcBrief.model_validate(data)

        errors = exc_info.value.errors()
        assert any("central_conflict" in str(e["loc"]) for e in errors)

    def test_arc_brief_empty_central_conflict_rejected(self):
        """Empty central_conflict raises ValidationError."""
        data = _valid_arc_brief_data()
        data["central_conflict"] = ""

        with pytest.raises(ValidationError):
            ArcBrief.model_validate(data)

    def test_arc_brief_serialization_json_roundtrip(self):
        """JSON serialize/deserialize preserves all fields."""
        data = _valid_arc_brief_data()
        data["antagonist_goal"] = "控制宗门势力"
        data["setup_beats"] = ["线索收集"]
        data["escalation_beats"] = ["对峙升级"]

        brief = ArcBrief.model_validate(data)
        json_str = brief.model_dump_json()
        restored = ArcBrief.model_validate_json(json_str)

        assert restored.arc_id == brief.arc_id
        assert restored.antagonist_goal == "控制宗门势力"
        assert restored.setup_beats == ["线索收集"]
        assert restored.escalation_beats == ["对峙升级"]
        assert restored.central_conflict == brief.central_conflict

    def test_arc_brief_serialization_dict_roundtrip(self):
        """Dict serialize/deserialize preserves all fields."""
        data = _valid_arc_brief_data()
        brief = ArcBrief.model_validate(data)
        dumped = brief.model_dump()
        restored = ArcBrief.model_validate(dumped)

        assert restored.arc_id == brief.arc_id
        assert restored.central_conflict == brief.central_conflict
