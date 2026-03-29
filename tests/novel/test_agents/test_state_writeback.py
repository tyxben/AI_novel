"""StateWriteback Agent unit tests

Covers:
- LLM-based extraction with mock LLM returning structured changes
- Rule-based fallback when LLM is None
- write_back merges character updates correctly
- Foreshadowing collection marks debts fulfilled
- World setting updates are merged
- Graceful handling when memory/tracker are None
- Node function reads from state and returns updates
- Edge cases: empty text, missing fields, non-dict characters
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.novel.agents.state_writeback import (
    StateWriteback,
    _empty_changes,
    _is_matching_debt,
    _normalize_changes,
    state_writeback_node,
)


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake-model"
    usage: dict | None = None


def _make_fake_llm(response_json: dict | None = None) -> MagicMock:
    llm = MagicMock()
    if response_json is None:
        response_json = {
            "character_updates": [
                {
                    "name": "林辰",
                    "changes": {
                        "health": "轻伤→恢复",
                        "new_ability": "引灵术",
                        "relationship": {"苏晚照": "初识"},
                        "location": "山洞",
                        "emotion": "坚定",
                    },
                }
            ],
            "world_updates": [
                {
                    "type": "new_location",
                    "name": "山北断崖",
                    "description": "枯松下的藏物点",
                }
            ],
            "foreshadowing_planted": [
                {"description": "引灵外物暗示无灵根有解", "chapter": 15}
            ],
            "foreshadowing_collected": [
                {"description": "第2章埋下的神秘人终于冒头", "original_chapter": 2}
            ],
            "arc_updates": [
                {
                    "arc_name": "矿脉争夺",
                    "progress_delta": 0.15,
                    "phase_note": "资源整合完成",
                }
            ],
            "outline_summary": "林辰整顿矿脉管理，建立分配制度，发现神秘修士",
        }
    llm.chat.return_value = FakeLLMResponse(
        content=json.dumps(response_json, ensure_ascii=False)
    )
    return llm


# Sample chapter text with rich narrative state changes
_SAMPLE_TEXT = (
    "林辰来到山洞深处，发现了一道隐秘的密室入口。\n"
    "他深吸一口气，毅然推开了石门。\n"
    "洞中弥漫着一股奇异的灵气，让他的经脉隐隐作痛。\n"
    "经过三天苦修，林辰终于领悟了引灵术的奥义。\n"
    "林辰的修为突破到了筑基中期，浑身伤势也逐渐恢复。\n"
    "苏晚照在洞口等候多时，见他出来，欣慰地笑了。\n"
    "这是他们初次见面以来，她第一次露出真心的笑容。\n"
    "远处传来阵阵战鼓声，青云门派的人似乎已经杀到了山脚。\n"
    "林辰暗下决心，不管前路如何，他都要守护这片矿脉。\n"
)

# Text with foreshadowing patterns
_FORESHADOW_TEXT = (
    "他隐约感觉到一股不为人知的力量在暗中涌动。\n"
    "这个秘密似乎与他的身世有关，但他暂时无法参悟。\n"
    "原来当年第3章提到的那个神秘老者果然就是他的师傅。\n"
    "难怪之前总觉得有人在暗中帮助自己，真相终于揭开了。\n"
)

_CHARS = [
    {"name": "林辰", "character_id": "char_linchen", "status": {}, "abilities": [], "relationships": {}},
    {"name": "苏晚照", "character_id": "char_suwanzhao", "status": {}, "abilities": []},
]


def _make_base_state(**overrides) -> dict:
    """Create a minimal state dict for testing."""
    state = {
        "current_chapter_text": _SAMPLE_TEXT,
        "current_chapter": 15,
        "characters": [dict(c) for c in _CHARS],  # Deep copy
        "world_setting": {"name": "灵界"},
        "current_chapter_brief": None,
        "obligation_tracker": None,
        "memory": None,
        "config": {"llm": {"provider": "openai"}},
        "outline": {
            "chapters": [
                {"chapter_number": 14, "chapter_summary": ""},
                {"chapter_number": 15, "goal": "矿脉整顿", "chapter_summary": ""},
                {"chapter_number": 16, "chapter_summary": ""},
            ]
        },
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# Test: LLM-based extraction
# ---------------------------------------------------------------------------


class TestLLMExtraction:
    """Test LLM-based extraction with mock LLM."""

    def test_llm_extract_returns_structured_changes(self):
        """LLM extraction returns all expected fields."""
        llm = _make_fake_llm()
        wb = StateWriteback(llm)

        changes = wb.extract_changes(
            chapter_text=_SAMPLE_TEXT,
            chapter_number=15,
            characters=_CHARS,
        )

        assert "character_updates" in changes
        assert "world_updates" in changes
        assert "foreshadowing_planted" in changes
        assert "foreshadowing_collected" in changes
        assert "arc_updates" in changes
        assert "outline_summary" in changes

        # Verify character updates from mock
        assert len(changes["character_updates"]) == 1
        assert changes["character_updates"][0]["name"] == "林辰"
        assert changes["character_updates"][0]["changes"]["new_ability"] == "引灵术"

        # Verify world updates
        assert len(changes["world_updates"]) == 1
        assert changes["world_updates"][0]["name"] == "山北断崖"

        # Verify foreshadowing
        assert len(changes["foreshadowing_planted"]) == 1
        assert len(changes["foreshadowing_collected"]) == 1

        # Verify arc updates
        assert len(changes["arc_updates"]) == 1
        assert changes["arc_updates"][0]["arc_name"] == "矿脉争夺"

        # Verify outline summary
        assert "林辰" in changes["outline_summary"]

    def test_llm_extract_calls_chat_with_correct_params(self):
        """LLM chat is called with system + user messages."""
        llm = _make_fake_llm()
        wb = StateWriteback(llm)

        wb.extract_changes(
            chapter_text="短文本",
            chapter_number=5,
            characters=[{"name": "张三"}],
        )

        llm.chat.assert_called_once()
        call_args = llm.chat.call_args
        messages = call_args[0][0]  # first positional arg
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "张三" in messages[1]["content"]

    def test_llm_failure_falls_back_to_rule_based(self):
        """When LLM raises an exception, falls back to rule-based."""
        llm = MagicMock()
        llm.chat.side_effect = RuntimeError("LLM down")
        wb = StateWriteback(llm)

        changes = wb.extract_changes(
            chapter_text=_SAMPLE_TEXT,
            chapter_number=15,
            characters=_CHARS,
        )

        # Should still return valid changes (from rule-based)
        assert "character_updates" in changes
        # Rule-based should detect something from the sample text
        assert isinstance(changes["character_updates"], list)

    def test_llm_returns_empty_json(self):
        """LLM returns valid but empty JSON."""
        llm = _make_fake_llm({})
        wb = StateWriteback(llm)

        changes = wb.extract_changes(
            chapter_text=_SAMPLE_TEXT,
            chapter_number=5,
        )

        # All fields should be empty but present
        assert changes["character_updates"] == []
        assert changes["world_updates"] == []
        assert changes["outline_summary"] == ""

    def test_llm_returns_partial_json(self):
        """LLM returns JSON with only some fields."""
        llm = _make_fake_llm({
            "character_updates": [{"name": "X", "changes": {"health": "ok"}}],
            # Missing other fields
        })
        wb = StateWriteback(llm)

        changes = wb.extract_changes(chapter_text="text", chapter_number=1)

        assert len(changes["character_updates"]) == 1
        assert changes["world_updates"] == []
        assert changes["foreshadowing_planted"] == []


# ---------------------------------------------------------------------------
# Test: Rule-based extraction
# ---------------------------------------------------------------------------


class TestRuleBasedExtraction:
    """Test rule-based fallback when LLM is None."""

    def test_rule_based_detects_character_health(self):
        """Rule-based detects injury/recovery keywords."""
        wb = StateWriteback(llm_client=None)
        changes = wb.extract_changes(
            chapter_text=_SAMPLE_TEXT,
            chapter_number=15,
            characters=_CHARS,
        )

        # Should detect 林辰's health change
        lin_updates = [u for u in changes["character_updates"] if u["name"] == "林辰"]
        assert len(lin_updates) > 0
        lin_changes = lin_updates[0]["changes"]
        assert "health" in lin_changes

    def test_rule_based_detects_abilities(self):
        """Rule-based detects new ability acquisition."""
        wb = StateWriteback(llm_client=None)
        changes = wb.extract_changes(
            chapter_text=_SAMPLE_TEXT,
            chapter_number=15,
            characters=_CHARS,
        )

        lin_updates = [u for u in changes["character_updates"] if u["name"] == "林辰"]
        assert len(lin_updates) > 0
        lin_changes = lin_updates[0]["changes"]
        # Should detect "领悟" or "突破"
        assert "new_ability" in lin_changes or "power_level" in lin_changes

    def test_rule_based_detects_location(self):
        """Rule-based detects location keywords."""
        wb = StateWriteback(llm_client=None)
        changes = wb.extract_changes(
            chapter_text=_SAMPLE_TEXT,
            chapter_number=15,
            characters=_CHARS,
        )

        lin_updates = [u for u in changes["character_updates"] if u["name"] == "林辰"]
        assert len(lin_updates) > 0
        assert "location" in lin_updates[0]["changes"]

    def test_rule_based_detects_emotion(self):
        """Rule-based detects emotional state."""
        wb = StateWriteback(llm_client=None)
        changes = wb.extract_changes(
            chapter_text=_SAMPLE_TEXT,
            chapter_number=15,
            characters=_CHARS,
        )

        lin_updates = [u for u in changes["character_updates"] if u["name"] == "林辰"]
        assert len(lin_updates) > 0
        assert "emotion" in lin_updates[0]["changes"]

    def test_rule_based_detects_world_updates(self):
        """Rule-based detects new locations from text."""
        wb = StateWriteback(llm_client=None)
        changes = wb.extract_changes(
            chapter_text=_SAMPLE_TEXT,
            chapter_number=15,
            characters=_CHARS,
        )

        # Should find at least one world update (from "来到山洞" or "发现...密室")
        assert isinstance(changes["world_updates"], list)

    def test_rule_based_detects_foreshadowing_planted(self):
        """Rule-based detects foreshadowing plant keywords."""
        wb = StateWriteback(llm_client=None)
        changes = wb.extract_changes(
            chapter_text=_FORESHADOW_TEXT,
            chapter_number=10,
            characters=[],
        )

        # "隐约" + "不为人知" + "秘密" in same area should trigger
        assert len(changes["foreshadowing_planted"]) >= 1

    def test_rule_based_detects_foreshadowing_collected(self):
        """Rule-based detects foreshadowing collection keywords."""
        wb = StateWriteback(llm_client=None)
        changes = wb.extract_changes(
            chapter_text=_FORESHADOW_TEXT,
            chapter_number=10,
            characters=[],
        )

        # "原来" + "果然" in the same sentence should trigger
        assert len(changes["foreshadowing_collected"]) >= 1

    def test_rule_based_extracts_chapter_reference(self):
        """Rule-based extracts '第N章' references from collected foreshadowing."""
        wb = StateWriteback(llm_client=None)
        changes = wb.extract_changes(
            chapter_text=_FORESHADOW_TEXT,
            chapter_number=10,
            characters=[],
        )

        collected = changes["foreshadowing_collected"]
        # At least one should have original_chapter = 3 (from "第3章")
        has_chapter_ref = any(
            c.get("original_chapter") == 3 for c in collected
        )
        assert has_chapter_ref

    def test_rule_based_generates_outline_summary(self):
        """Rule-based generates an outline summary from first/last sentences."""
        wb = StateWriteback(llm_client=None)
        changes = wb.extract_changes(
            chapter_text=_SAMPLE_TEXT,
            chapter_number=15,
            characters=[],
        )

        assert changes["outline_summary"]
        assert len(changes["outline_summary"]) > 0

    def test_empty_text_returns_empty_changes(self):
        """Empty chapter text returns empty changes."""
        wb = StateWriteback(llm_client=None)
        changes = wb.extract_changes(
            chapter_text="",
            chapter_number=1,
            characters=[],
        )

        assert changes == _empty_changes()

    def test_no_characters_still_works(self):
        """Rule-based works with no character list."""
        wb = StateWriteback(llm_client=None)
        changes = wb.extract_changes(
            chapter_text=_SAMPLE_TEXT,
            chapter_number=15,
            characters=None,
        )

        assert "character_updates" in changes
        assert changes["character_updates"] == []  # No chars to match

    def test_rule_based_detects_faction(self):
        """Rule-based detects faction/organization mentions."""
        wb = StateWriteback(llm_client=None)
        changes = wb.extract_changes(
            chapter_text=_SAMPLE_TEXT,
            chapter_number=15,
            characters=[],
        )

        # "青云门派" should be detected
        faction_updates = [u for u in changes["world_updates"] if u.get("type") == "new_faction"]
        assert len(faction_updates) >= 1
        assert any("青云" in f["name"] for f in faction_updates)


# ---------------------------------------------------------------------------
# Test: write_back merges correctly
# ---------------------------------------------------------------------------


class TestWriteBack:
    """Test write_back merges changes into state correctly."""

    def test_merge_character_health(self):
        """Character health update is merged into state."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {"health": "重伤"}}
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        summary = wb.write_back(changes, chapter_number=15, state=state)

        assert summary["characters_updated"] == 1
        lin = next(c for c in state["characters"] if c["name"] == "林辰")
        assert lin["status"]["health"] == "重伤"

    def test_merge_character_new_ability(self):
        """New ability is appended to character's abilities list."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {"new_ability": "火球术"}}
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        wb.write_back(changes, chapter_number=15, state=state)

        lin = next(c for c in state["characters"] if c["name"] == "林辰")
        assert "火球术" in lin["abilities"]

    def test_merge_does_not_duplicate_abilities(self):
        """Same ability added twice is not duplicated."""
        wb = StateWriteback()
        state = _make_base_state()
        # Pre-set an ability
        state["characters"][0]["abilities"] = ["引灵术"]

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {"new_ability": "引灵术"}}
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        wb.write_back(changes, chapter_number=15, state=state)

        lin = next(c for c in state["characters"] if c["name"] == "林辰")
        assert lin["abilities"].count("引灵术") == 1

    def test_merge_character_power_level(self):
        """Power level update is merged."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {"power_level": "筑基"}}
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        wb.write_back(changes, chapter_number=15, state=state)

        lin = next(c for c in state["characters"] if c["name"] == "林辰")
        assert lin["status"]["power_level"] == "筑基"

    def test_merge_character_emotion(self):
        """Emotion update is merged."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {"emotion": "坚定"}}
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        wb.write_back(changes, chapter_number=15, state=state)

        lin = next(c for c in state["characters"] if c["name"] == "林辰")
        assert lin["status"]["emotional_state"] == "坚定"

    def test_merge_character_location(self):
        """Location update is merged."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {"location": "山洞"}}
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        wb.write_back(changes, chapter_number=15, state=state)

        lin = next(c for c in state["characters"] if c["name"] == "林辰")
        assert lin["status"]["location"] == "山洞"

    def test_merge_character_relationship_dict(self):
        """Relationship dict update is merged."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {"relationship": {"苏晚照": "初识"}}}
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        wb.write_back(changes, chapter_number=15, state=state)

        lin = next(c for c in state["characters"] if c["name"] == "林辰")
        assert lin["relationships"]["苏晚照"] == "初识"

    def test_merge_unknown_character_skipped(self):
        """Updates for characters not in state are silently skipped."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [
                {"name": "不存在的角色", "changes": {"health": "重伤"}}
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        summary = wb.write_back(changes, chapter_number=15, state=state)
        assert summary["characters_updated"] == 0

    def test_merge_multiple_characters(self):
        """Updates for multiple characters are all applied."""
        wb = StateWriteback()
        state = _make_base_state()
        state["characters"][1]["status"] = {}  # Ensure su has status dict

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {"health": "重伤"}},
                {"name": "苏晚照", "changes": {"emotion": "喜悦"}},
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        summary = wb.write_back(changes, chapter_number=15, state=state)
        assert summary["characters_updated"] == 2

        lin = next(c for c in state["characters"] if c["name"] == "林辰")
        assert lin["status"]["health"] == "重伤"

        su = next(c for c in state["characters"] if c["name"] == "苏晚照")
        assert su["status"]["emotional_state"] == "喜悦"

    def test_merge_preserves_existing_data(self):
        """Merging new data doesn't remove existing fields."""
        wb = StateWriteback()
        state = _make_base_state()
        state["characters"][0]["status"] = {"health": "轻伤", "custom_field": "keep_me"}
        state["characters"][0]["abilities"] = ["引灵术"]

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {"emotion": "愤怒"}}
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        wb.write_back(changes, chapter_number=15, state=state)

        lin = next(c for c in state["characters"] if c["name"] == "林辰")
        # Existing data preserved
        assert lin["status"]["health"] == "轻伤"
        assert lin["status"]["custom_field"] == "keep_me"
        assert "引灵术" in lin["abilities"]
        # New data added
        assert lin["status"]["emotional_state"] == "愤怒"


# ---------------------------------------------------------------------------
# Test: World setting merge
# ---------------------------------------------------------------------------


class TestWorldSettingMerge:
    """Test world_setting updates are merged correctly."""

    def test_new_location_added(self):
        """New location is added to world_setting."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [],
            "world_updates": [
                {"type": "new_location", "name": "山北断崖", "description": "悬崖边的藏物点"}
            ],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        summary = wb.write_back(changes, chapter_number=15, state=state)

        assert summary["world_updates_applied"] == 1
        locations = state["world_setting"]["discovered_locations"]
        assert len(locations) == 1
        assert locations[0]["name"] == "山北断崖"
        assert locations[0]["discovered_chapter"] == 15

    def test_duplicate_location_not_added(self):
        """Duplicate location is not added again."""
        wb = StateWriteback()
        state = _make_base_state()
        state["world_setting"]["discovered_locations"] = [
            {"name": "山北断崖", "description": "old"}
        ]

        changes = {
            "character_updates": [],
            "world_updates": [
                {"type": "new_location", "name": "山北断崖", "description": "new"}
            ],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        summary = wb.write_back(changes, chapter_number=15, state=state)
        assert summary["world_updates_applied"] == 0
        assert len(state["world_setting"]["discovered_locations"]) == 1

    def test_new_faction_added(self):
        """New faction is added to world_setting."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [],
            "world_updates": [
                {"type": "new_faction", "name": "青云宗", "description": "山中宗门"}
            ],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        summary = wb.write_back(changes, chapter_number=15, state=state)

        assert summary["world_updates_applied"] == 1
        factions = state["world_setting"]["discovered_factions"]
        assert len(factions) == 1
        assert factions[0]["name"] == "青云宗"

    def test_world_setting_none_creates_dict(self):
        """When world_setting is None, a new dict is created."""
        wb = StateWriteback()
        state = _make_base_state(world_setting=None)

        changes = {
            "character_updates": [],
            "world_updates": [
                {"type": "new_location", "name": "密林", "description": "深处"}
            ],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        summary = wb.write_back(changes, chapter_number=15, state=state)

        assert summary["world_updates_applied"] == 1
        assert state["world_setting"] is not None
        assert len(state["world_setting"]["discovered_locations"]) == 1

    def test_world_updates_with_memory(self):
        """World updates are persisted to memory's structured DB as facts."""
        wb = StateWriteback()
        state = _make_base_state()

        mock_db = MagicMock()
        mock_memory = MagicMock()
        mock_memory.structured_db = mock_db

        changes = {
            "character_updates": [],
            "world_updates": [
                {"type": "new_location", "name": "密林", "description": "dark forest"}
            ],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        wb.write_back(changes, chapter_number=15, state=state, memory=mock_memory)

        mock_db.insert_fact.assert_called_once()


# ---------------------------------------------------------------------------
# Test: Foreshadowing collection marks debts fulfilled
# ---------------------------------------------------------------------------


class TestForeshadowingDebtFulfillment:
    """Test that collected foreshadowing marks debts as fulfilled."""

    def test_matching_debt_is_fulfilled(self):
        """Collected foreshadowing matching a debt marks it fulfilled."""
        wb = StateWriteback()
        state = _make_base_state()

        tracker = MagicMock()
        tracker.get_debts_for_chapter.return_value = [
            {
                "debt_id": "debt_2_foreshadow",
                "source_chapter": 2,
                "description": "神秘人出现但未揭示身份",
                "status": "pending",
            }
        ]

        changes = {
            "character_updates": [],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [
                {
                    "description": "第2章埋下的神秘人终于冒头揭示身份",
                    "original_chapter": 2,
                }
            ],
            "arc_updates": [],
            "outline_summary": "",
        }

        summary = wb.write_back(
            changes, chapter_number=15, state=state, obligation_tracker=tracker
        )

        assert summary["debts_fulfilled"] == 1
        tracker.mark_debt_fulfilled.assert_called_once()
        call_args = tracker.mark_debt_fulfilled.call_args
        assert call_args[0][0] == "debt_2_foreshadow"
        assert call_args[0][1] == 15
        assert call_args[1]["note"]  # note is not empty

    def test_non_matching_debt_not_fulfilled(self):
        """When no debt matches, nothing is fulfilled."""
        wb = StateWriteback()
        state = _make_base_state()

        tracker = MagicMock()
        tracker.get_debts_for_chapter.return_value = [
            {
                "debt_id": "debt_5_unrelated",
                "source_chapter": 5,
                "description": "完全无关的债务内容",
                "status": "pending",
            }
        ]

        changes = {
            "character_updates": [],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [
                {
                    "description": "第2章的神秘人身份揭示",
                    "original_chapter": 2,
                }
            ],
            "arc_updates": [],
            "outline_summary": "",
        }

        summary = wb.write_back(
            changes, chapter_number=15, state=state, obligation_tracker=tracker
        )

        assert summary["debts_fulfilled"] == 0
        tracker.mark_debt_fulfilled.assert_not_called()

    def test_no_tracker_skips_fulfillment(self):
        """When obligation_tracker is None, no fulfillment attempted."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [
                {"description": "something", "original_chapter": 2}
            ],
            "arc_updates": [],
            "outline_summary": "",
        }

        # Should not raise
        summary = wb.write_back(
            changes, chapter_number=15, state=state, obligation_tracker=None
        )
        assert summary["debts_fulfilled"] == 0

    def test_tracker_exception_handled_gracefully(self):
        """Tracker exceptions don't crash write_back."""
        wb = StateWriteback()
        state = _make_base_state()

        tracker = MagicMock()
        tracker.get_debts_for_chapter.side_effect = RuntimeError("DB error")

        changes = {
            "character_updates": [],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [
                {"description": "something", "original_chapter": 2}
            ],
            "arc_updates": [],
            "outline_summary": "",
        }

        summary = wb.write_back(
            changes, chapter_number=15, state=state, obligation_tracker=tracker
        )
        assert summary["debts_fulfilled"] == 0


# ---------------------------------------------------------------------------
# Test: Outline summary update
# ---------------------------------------------------------------------------


class TestOutlineSummaryUpdate:
    """Test outline chapter summary is updated."""

    def test_outline_summary_updated(self):
        """Outline entry gets chapter_summary set."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "林辰整顿矿脉，击退外敌",
        }

        summary = wb.write_back(changes, chapter_number=15, state=state)

        assert summary["outline_updated"] is True
        ch15 = next(
            c for c in state["outline"]["chapters"] if c["chapter_number"] == 15
        )
        assert ch15["chapter_summary"] == "林辰整顿矿脉，击退外敌"

    def test_outline_summary_no_match(self):
        """When chapter not found in outline, returns False."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "some summary",
        }

        summary = wb.write_back(changes, chapter_number=999, state=state)
        assert summary["outline_updated"] is False

    def test_outline_none_no_crash(self):
        """When outline is None, doesn't crash."""
        wb = StateWriteback()
        state = _make_base_state(outline=None)

        changes = {
            "character_updates": [],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "something",
        }

        summary = wb.write_back(changes, chapter_number=15, state=state)
        assert summary["outline_updated"] is False


# ---------------------------------------------------------------------------
# Test: Graceful handling of None memory/tracker
# ---------------------------------------------------------------------------


class TestGracefulNoneHandling:
    """Test graceful handling when memory, tracker, and other deps are None."""

    def test_all_none_no_crash(self):
        """write_back works with all optional deps as None."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {"health": "恢复"}}
            ],
            "world_updates": [
                {"type": "new_location", "name": "新地方", "description": "desc"}
            ],
            "foreshadowing_planted": [
                {"description": "伏笔", "chapter": 15}
            ],
            "foreshadowing_collected": [
                {"description": "回收", "original_chapter": 2}
            ],
            "arc_updates": [],
            "outline_summary": "摘要",
        }

        summary = wb.write_back(
            changes, chapter_number=15, state=state,
            memory=None, obligation_tracker=None,
        )

        # Should still work for state-based updates
        assert summary["characters_updated"] == 1
        assert summary["world_updates_applied"] == 1
        assert summary["foreshadowing_planted"] == 1
        assert summary["debts_fulfilled"] == 0

    def test_memory_db_exception_handled(self):
        """Exception from memory.structured_db is caught."""
        wb = StateWriteback()
        state = _make_base_state()

        mock_db = MagicMock()
        mock_db.insert_character_state.side_effect = RuntimeError("DB error")
        mock_memory = MagicMock()
        mock_memory.structured_db = mock_db

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {"health": "重伤"}}
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        # Should not raise
        summary = wb.write_back(
            changes, chapter_number=15, state=state, memory=mock_memory
        )
        # Character update still counts (in-memory merge succeeded)
        assert summary["characters_updated"] == 1

    def test_empty_changes_dict(self):
        """Empty changes dict produces zero counts."""
        wb = StateWriteback()
        state = _make_base_state()

        summary = wb.write_back(
            changes=_empty_changes(),
            chapter_number=15,
            state=state,
        )

        assert summary["characters_updated"] == 0
        assert summary["world_updates_applied"] == 0
        assert summary["foreshadowing_planted"] == 0
        assert summary["debts_fulfilled"] == 0
        assert summary["outline_updated"] is False

    def test_update_with_empty_name_skipped(self):
        """Character update with empty name is skipped."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [
                {"name": "", "changes": {"health": "重伤"}}
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        summary = wb.write_back(changes, chapter_number=15, state=state)
        assert summary["characters_updated"] == 0

    def test_update_with_empty_changes_skipped(self):
        """Character update with empty changes dict is skipped."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {}}
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        summary = wb.write_back(changes, chapter_number=15, state=state)
        assert summary["characters_updated"] == 0

    def test_characters_list_is_none(self):
        """State with characters=None doesn't crash."""
        wb = StateWriteback()
        state = _make_base_state(characters=None)

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {"health": "重伤"}}
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        summary = wb.write_back(changes, chapter_number=15, state=state)
        assert summary["characters_updated"] == 0


# ---------------------------------------------------------------------------
# Test: _is_matching_debt helper
# ---------------------------------------------------------------------------


class TestIsMatchingDebt:
    """Test the debt matching heuristic."""

    def test_matching_chapter_and_description(self):
        """Debt with matching chapter and overlapping description matches."""
        debt = {
            "debt_id": "d1",
            "source_chapter": 2,
            "description": "神秘人出现未揭示身份",
        }
        assert _is_matching_debt(debt, "神秘人的身份终于揭示了", original_chapter=2) is True

    def test_wrong_chapter_no_match(self):
        """Debt with wrong chapter doesn't match."""
        debt = {
            "debt_id": "d1",
            "source_chapter": 5,
            "description": "神秘人出现未揭示身份",
        }
        assert _is_matching_debt(debt, "神秘人身份揭示", original_chapter=2) is False

    def test_no_overlap_no_match(self):
        """Debt with no description overlap doesn't match."""
        debt = {
            "debt_id": "d1",
            "source_chapter": 2,
            "description": "完全不同的内容说的事情",
        }
        assert _is_matching_debt(debt, "ABCDEFGHIJKLMNOP", original_chapter=2) is False

    def test_no_original_chapter_matches_by_text(self):
        """When original_chapter is None, match by text overlap only."""
        debt = {
            "debt_id": "d1",
            "source_chapter": 3,
            "description": "林辰的师傅身份之谜",
        }
        assert _is_matching_debt(debt, "林辰的师傅身份终于揭开", original_chapter=None) is True

    def test_empty_descriptions_no_match(self):
        """Empty descriptions don't match."""
        assert _is_matching_debt(
            {"debt_id": "d1", "source_chapter": 1, "description": ""},
            "",
            original_chapter=None,
        ) is False

    def test_very_short_text_no_match(self):
        """Very short text doesn't match."""
        assert _is_matching_debt(
            {"debt_id": "d1", "source_chapter": 1, "description": "X"},
            "Y",
            original_chapter=None,
        ) is False


# ---------------------------------------------------------------------------
# Test: _normalize_changes helper
# ---------------------------------------------------------------------------


class TestNormalizeChanges:
    """Test _normalize_changes sanitizes LLM output."""

    def test_valid_input_preserved(self):
        """Valid LLM output is preserved."""
        raw = {
            "character_updates": [{"name": "A", "changes": {}}],
            "world_updates": [{"name": "B", "type": "new_location"}],
            "foreshadowing_planted": [{"description": "C"}],
            "foreshadowing_collected": [{"description": "D"}],
            "arc_updates": [{"arc_name": "E"}],
            "outline_summary": "F",
        }
        result = _normalize_changes(raw, chapter_number=5)
        assert len(result["character_updates"]) == 1
        assert len(result["world_updates"]) == 1
        assert len(result["foreshadowing_planted"]) == 1
        assert result["foreshadowing_planted"][0]["chapter"] == 5
        assert result["outline_summary"] == "F"

    def test_non_dict_input_returns_empty(self):
        """Non-dict input returns empty changes."""
        result = _normalize_changes("not a dict", chapter_number=1)
        assert result == _empty_changes()

    def test_invalid_items_filtered(self):
        """Items without required fields are filtered out."""
        raw = {
            "character_updates": [
                {"name": "A", "changes": {}},  # valid
                {"changes": {}},  # no name -> filtered
                "not a dict",  # not a dict -> filtered
            ],
            "world_updates": [
                {"name": "B"},  # valid
                {"type": "foo"},  # no name -> filtered
            ],
            "foreshadowing_planted": [
                {"description": "C"},  # valid
                {},  # no description -> filtered
            ],
            "arc_updates": [
                {"arc_name": "D"},  # valid
                {"progress": 0.5},  # no arc_name -> filtered
            ],
        }
        result = _normalize_changes(raw, chapter_number=3)
        assert len(result["character_updates"]) == 1
        assert len(result["world_updates"]) == 1
        assert len(result["foreshadowing_planted"]) == 1
        assert len(result["arc_updates"]) == 1

    def test_missing_fields_default_to_empty(self):
        """Missing top-level fields default to empty."""
        result = _normalize_changes({"outline_summary": "X"}, chapter_number=1)
        assert result["character_updates"] == []
        assert result["world_updates"] == []
        assert result["outline_summary"] == "X"


# ---------------------------------------------------------------------------
# Test: state_writeback_node (LangGraph node)
# ---------------------------------------------------------------------------


class TestStateWritebackNode:
    """Test the LangGraph node function."""

    @patch("src.llm.llm_client.create_llm_client")
    def test_node_returns_completed(self, mock_create_llm):
        """Node returns completed_nodes with state_writeback."""
        mock_create_llm.side_effect = RuntimeError("no LLM")  # Force rule-based

        state = _make_base_state()
        result = state_writeback_node(state)

        assert "state_writeback" in result["completed_nodes"]
        assert len(result["decisions"]) >= 1
        assert result["decisions"][0]["agent"] == "StateWriteback"

    def test_node_empty_text_returns_error(self):
        """Node with no chapter text returns error."""
        state = _make_base_state(current_chapter_text=None)
        result = state_writeback_node(state)

        assert "state_writeback" in result["completed_nodes"]
        assert len(result["errors"]) == 1
        assert "No chapter text" in result["errors"][0]["message"]

    def test_node_empty_string_text_returns_error(self):
        """Node with empty string chapter text returns error."""
        state = _make_base_state(current_chapter_text="")
        result = state_writeback_node(state)

        assert "state_writeback" in result["completed_nodes"]
        assert len(result["errors"]) == 1

    @patch("src.llm.llm_client.create_llm_client")
    def test_node_with_llm(self, mock_create_llm):
        """Node uses LLM when available."""
        mock_llm = _make_fake_llm()
        mock_create_llm.return_value = mock_llm

        state = _make_base_state()
        result = state_writeback_node(state)

        assert "state_writeback" in result["completed_nodes"]
        mock_llm.chat.assert_called_once()

    @patch("src.llm.llm_client.create_llm_client")
    def test_node_updates_state_in_place(self, mock_create_llm):
        """Node mutates state characters and world_setting."""
        mock_create_llm.side_effect = RuntimeError("no LLM")

        state = _make_base_state()
        original_lin = next(c for c in state["characters"] if c["name"] == "林辰")
        result = state_writeback_node(state)

        # State should be mutated (write_back modifies in place)
        assert "state_writeback" in result["completed_nodes"]
        # The node should have decisions logged
        assert len(result.get("decisions", [])) >= 1

    @patch("src.llm.llm_client.create_llm_client")
    def test_node_with_obligation_tracker(self, mock_create_llm):
        """Node passes obligation_tracker to write_back."""
        mock_create_llm.side_effect = RuntimeError("no LLM")

        tracker = MagicMock()
        tracker.get_debts_for_chapter.return_value = []

        state = _make_base_state(obligation_tracker=tracker)
        result = state_writeback_node(state)

        assert "state_writeback" in result["completed_nodes"]

    @patch("src.llm.llm_client.create_llm_client")
    def test_node_extraction_exception_returns_error(self, mock_create_llm):
        """When extract_changes raises, node returns error without crashing."""
        mock_create_llm.side_effect = RuntimeError("no LLM")

        state = _make_base_state()
        # Patch extract_changes to raise
        with patch.object(
            StateWriteback, "extract_changes",
            side_effect=ValueError("parse error"),
        ):
            result = state_writeback_node(state)

        assert "state_writeback" in result["completed_nodes"]
        assert any("Extraction failed" in e["message"] for e in result["errors"])

    @patch("src.llm.llm_client.create_llm_client")
    def test_node_writeback_exception_returns_error(self, mock_create_llm):
        """When write_back raises, node returns error with partial decisions."""
        mock_create_llm.side_effect = RuntimeError("no LLM")

        state = _make_base_state()
        with patch.object(
            StateWriteback, "write_back",
            side_effect=RuntimeError("persistence error"),
        ):
            result = state_writeback_node(state)

        assert "state_writeback" in result["completed_nodes"]
        assert any("Writeback failed" in e["message"] for e in result["errors"])
        # Should still have a decision about the failure
        assert len(result.get("decisions", [])) >= 1


# ---------------------------------------------------------------------------
# Test: Memory persistence
# ---------------------------------------------------------------------------


class TestMemoryPersistence:
    """Test that changes are persisted to memory's structured DB."""

    def test_character_state_persisted(self):
        """Character state changes are persisted to structured DB."""
        wb = StateWriteback()
        state = _make_base_state()

        mock_db = MagicMock()
        mock_memory = MagicMock()
        mock_memory.structured_db = mock_db

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {"health": "重伤", "location": "山洞"}}
            ],
            "world_updates": [],
            "foreshadowing_planted": [],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        wb.write_back(changes, chapter_number=15, state=state, memory=mock_memory)

        mock_db.insert_character_state.assert_called_once_with(
            character_id="char_linchen",
            chapter=15,
            location="山洞",
            health="重伤",
            emotional_state="",
            power_level="",
        )

    def test_foreshadowing_planted_persisted_as_fact(self):
        """Planted foreshadowing is recorded as a fact in memory."""
        wb = StateWriteback()
        state = _make_base_state()

        mock_db = MagicMock()
        mock_memory = MagicMock()
        mock_memory.structured_db = mock_db

        changes = {
            "character_updates": [],
            "world_updates": [],
            "foreshadowing_planted": [
                {"description": "mysterious artifact hinted", "chapter": 15}
            ],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        summary = wb.write_back(
            changes, chapter_number=15, state=state, memory=mock_memory
        )

        assert summary["foreshadowing_planted"] == 1
        mock_db.insert_fact.assert_called_once()

    def test_no_memory_no_persistence_call(self):
        """When memory is None, no DB calls are made."""
        wb = StateWriteback()
        state = _make_base_state()

        changes = {
            "character_updates": [
                {"name": "林辰", "changes": {"health": "重伤"}}
            ],
            "world_updates": [
                {"type": "new_location", "name": "X", "description": "Y"}
            ],
            "foreshadowing_planted": [
                {"description": "Z", "chapter": 15}
            ],
            "foreshadowing_collected": [],
            "arc_updates": [],
            "outline_summary": "",
        }

        # Should work without any mock — just no DB calls
        summary = wb.write_back(
            changes, chapter_number=15, state=state, memory=None
        )
        assert summary["characters_updated"] == 1
        assert summary["world_updates_applied"] == 1
        assert summary["foreshadowing_planted"] == 1
