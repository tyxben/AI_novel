"""Tests for ContinuityService -- unified continuity brief aggregation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.novel.services.continuity_service import ContinuityService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_chapter(
    chapter_number: int,
    title: str = "Test Chapter",
    full_text: str = "",
    outline: dict | None = None,
) -> dict:
    """Helper to build a chapter dict."""
    ch: dict = {
        "chapter_number": chapter_number,
        "title": title,
        "full_text": full_text,
        "word_count": len(full_text),
        "status": "draft",
    }
    if outline is not None:
        ch["outline"] = outline
    return ch


def _make_obligation_tracker(debts: list[dict] | None = None):
    """Return a mock ObligationTracker with configurable debts."""
    tracker = MagicMock()
    tracker.get_debts_for_chapter.return_value = debts or []
    return tracker


def _make_db(character_states: dict | None = None):
    """Return a mock StructuredDB.

    *character_states* maps ``character_id`` -> state dict.
    """
    db = MagicMock()
    states = character_states or {}

    def _get_character_state(character_id, chapter=None):
        return states.get(character_id)

    db.get_character_state.side_effect = _get_character_state
    return db


# ---------------------------------------------------------------------------
# Tests: generate_brief with all components
# ---------------------------------------------------------------------------

class TestGenerateBriefFull:
    """Test generate_brief when all components are available."""

    def test_full_brief_structure(self):
        """All sections are populated when data is available."""
        tracker = _make_obligation_tracker([
            {
                "description": "黑匣子的来源未解释",
                "source_chapter": 8,
                "urgency_level": "high",
                "status": "pending",
            },
        ])
        db = _make_db({
            "char_1": {
                "character_id": "char_1",
                "health": "轻伤",
                "location": "客栈",
                "power_level": "炼气三层",
                "emotional_state": "查黑匣子",
            },
        })
        svc = ContinuityService(db=db, obligation_tracker=tracker)

        chapters = [
            _make_chapter(
                11,
                full_text="前文省略" * 100 + "沈夜决定夜探仓库，独自一人出发了",
            ),
        ]
        characters = [
            {"character_id": "char_1", "name": "沈夜", "status": "active"},
        ]
        story_arcs = [
            {
                "arc_id": "arc_1",
                "name": "黑匣子之谜",
                "chapters": [9, 10, 11, 12, 13, 14],
                "phase": "rising",
                "status": "active",
            },
        ]
        chapter_brief = {
            "main_conflict": "沈夜夜探仓库",
            "payoff": "推进黑匣子线索",
            "end_hook_type": "cliffhanger",
        }

        brief = svc.generate_brief(
            chapter_number=12,
            chapters=chapters,
            chapter_brief=chapter_brief,
            story_arcs=story_arcs,
            characters=characters,
        )

        assert brief["chapter_number"] == 12

        # must_continue should have hook from previous chapter ending
        assert len(brief["must_continue"]) > 0

        # open_threads from obligation tracker
        assert len(brief["open_threads"]) == 1
        assert "黑匣子的来源未解释" in brief["open_threads"][0]
        assert "high" in brief["open_threads"][0]

        # character_states from DB
        assert len(brief["character_states"]) == 1
        assert brief["character_states"][0]["name"] == "沈夜"
        assert brief["character_states"][0]["location"] == "客栈"

        # active_arcs
        assert len(brief["active_arcs"]) == 1
        assert brief["active_arcs"][0]["arc_name"] == "黑匣子之谜"
        assert brief["active_arcs"][0]["phase"] == "rising"
        assert brief["active_arcs"][0]["chapters_remaining"] == 3  # 12,13,14

        # forbidden_breaks
        assert any("沈夜" in fb and "客栈" in fb for fb in brief["forbidden_breaks"])

        # recommended_payoffs from chapter_brief
        assert any("推进黑匣子线索" in rp for rp in brief["recommended_payoffs"])

    def test_chapter_brief_foreshadowing_collect(self):
        """foreshadowing_collect entries appear in recommended_payoffs."""
        svc = ContinuityService()
        chapter_brief = {
            "foreshadowing_collect": ["密室钥匙的去向", "师父的遗言"],
        }
        brief = svc.generate_brief(
            chapter_number=5,
            chapter_brief=chapter_brief,
        )
        texts = " ".join(brief["recommended_payoffs"])
        assert "密室钥匙的去向" in texts
        assert "师父的遗言" in texts

    def test_chapter_brief_foreshadowing_collect_string(self):
        """foreshadowing_collect can be a single string."""
        svc = ContinuityService()
        chapter_brief = {"foreshadowing_collect": "密室钥匙的去向"}
        brief = svc.generate_brief(
            chapter_number=5,
            chapter_brief=chapter_brief,
        )
        assert any("密室钥匙的去向" in rp for rp in brief["recommended_payoffs"])


# ---------------------------------------------------------------------------
# Tests: graceful degradation (partial components)
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    """Brief should still work when some or all components are absent."""

    def test_no_components(self):
        """Bare minimum: no DB, no tracker, no chapters."""
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=1)

        assert brief["chapter_number"] == 1
        assert brief["must_continue"] == []
        assert brief["open_threads"] == []
        assert brief["character_states"] == []
        assert brief["active_arcs"] == []
        assert brief["forbidden_breaks"] == []
        assert brief["recommended_payoffs"] == []

    def test_no_db_with_characters(self):
        """Characters provided but DB is None -- fallback to profile info."""
        svc = ContinuityService(db=None)
        characters = [
            {"character_id": "c1", "name": "林秋", "status": "absent"},
        ]
        brief = svc.generate_brief(
            chapter_number=3,
            characters=characters,
        )
        assert len(brief["character_states"]) == 1
        assert brief["character_states"][0]["name"] == "林秋"
        assert brief["character_states"][0]["status"] == "absent"
        # absent triggers a forbidden break
        assert any("林秋" in fb for fb in brief["forbidden_breaks"])

    def test_no_tracker(self):
        """No obligation tracker -- open_threads and recommended_payoffs from tracker are empty."""
        svc = ContinuityService(obligation_tracker=None)
        brief = svc.generate_brief(chapter_number=5)
        assert brief["open_threads"] == []

    def test_tracker_raises(self):
        """Tracker that raises should not crash the service."""
        tracker = MagicMock()
        tracker.get_debts_for_chapter.side_effect = RuntimeError("DB exploded")
        svc = ContinuityService(obligation_tracker=tracker)
        brief = svc.generate_brief(chapter_number=5)
        assert brief["open_threads"] == []

    def test_db_get_character_state_raises(self):
        """DB error for a character should not crash; fallback to profile."""
        db = MagicMock()
        db.get_character_state.side_effect = RuntimeError("table locked")
        svc = ContinuityService(db=db)

        characters = [
            {"character_id": "c1", "name": "方岩", "status": "active"},
        ]
        brief = svc.generate_brief(chapter_number=3, characters=characters)
        assert len(brief["character_states"]) == 1
        assert brief["character_states"][0]["name"] == "方岩"
        assert brief["character_states"][0]["status"] == "active"

    def test_none_chapters(self):
        """chapters=None should not crash."""
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=2, chapters=None)
        assert brief["must_continue"] == []

    def test_empty_chapters_list(self):
        """Empty chapters list produces no continuation hooks."""
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=2, chapters=[])
        assert brief["must_continue"] == []

    def test_no_story_arcs(self):
        """story_arcs=None produces empty active_arcs."""
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=5, story_arcs=None)
        assert brief["active_arcs"] == []


# ---------------------------------------------------------------------------
# Tests: _extract_continuation_hooks
# ---------------------------------------------------------------------------

class TestContinuationHooks:
    """Test hook extraction from previous chapter text."""

    def test_question_hook(self):
        """Chapter ending with a question is detected."""
        svc = ContinuityService()
        chapters = [
            _make_chapter(4, full_text="普通内容" * 50 + "那个人到底是谁？"),
        ]
        brief = svc.generate_brief(chapter_number=5, chapters=chapters)
        assert any("那个人到底是谁" in item for item in brief["must_continue"])

    def test_decision_hook(self):
        """Chapter ending with a decision/plan is detected."""
        svc = ContinuityService()
        chapters = [
            _make_chapter(4, full_text="普通内容" * 50 + "他决定明天一早动身前往北境"),
        ]
        brief = svc.generate_brief(chapter_number=5, chapters=chapters)
        assert len(brief["must_continue"]) > 0

    def test_departure_hook(self):
        """Chapter ending with departure is detected."""
        svc = ContinuityService()
        chapters = [
            _make_chapter(4, full_text="普通内容" * 50 + "两人收拾行囊，赶往密林深处"),
        ]
        brief = svc.generate_brief(chapter_number=5, chapters=chapters)
        assert len(brief["must_continue"]) > 0

    def test_no_hooks_in_boring_ending(self):
        """Chapter with a neutral ending produces no hooks."""
        svc = ContinuityService()
        chapters = [
            _make_chapter(4, full_text="今天天气不错。"),
        ]
        brief = svc.generate_brief(chapter_number=5, chapters=chapters)
        assert brief["must_continue"] == []

    def test_previous_chapter_not_found(self):
        """If previous chapter (N-1) is missing, no hooks are generated."""
        svc = ContinuityService()
        # Only chapter 3 exists, requesting brief for chapter 5
        chapters = [
            _make_chapter(3, full_text="普通内容" * 50 + "他决定离开"),
        ]
        brief = svc.generate_brief(chapter_number=5, chapters=chapters)
        assert brief["must_continue"] == []

    def test_outline_end_hook_type(self):
        """end_hook_type from previous chapter outline appears in must_continue."""
        svc = ContinuityService()
        outline = {
            "chapter_brief": {
                "end_hook_type": "cliffhanger",
            },
        }
        chapters = [
            _make_chapter(4, full_text="内容", outline=outline),
        ]
        brief = svc.generate_brief(chapter_number=5, chapters=chapters)
        assert any("cliffhanger" in item for item in brief["must_continue"])

    def test_hooks_deduplication(self):
        """Duplicate hook lines are deduped."""
        svc = ContinuityService()
        # Repeat the same hook pattern twice in the tail
        chapters = [
            _make_chapter(
                4,
                full_text="普通内容" * 50
                + "他决定动身出发\n他决定动身出发",
            ),
        ]
        brief = svc.generate_brief(chapter_number=5, chapters=chapters)
        # Should not have the same item twice
        assert len(brief["must_continue"]) == len(set(brief["must_continue"]))

    def test_hooks_capped_at_five(self):
        """At most 5 continuation hooks are returned."""
        svc = ContinuityService()
        many_hooks = "\n".join([f"他决定去第{i}个地方出发" for i in range(20)])
        chapters = [_make_chapter(4, full_text=many_hooks)]
        brief = svc.generate_brief(chapter_number=5, chapters=chapters)
        assert len(brief["must_continue"]) <= 5


# ---------------------------------------------------------------------------
# Tests: _extract_open_threads
# ---------------------------------------------------------------------------

class TestOpenThreads:

    def test_multiple_debts(self):
        """Multiple debts are all listed."""
        tracker = _make_obligation_tracker([
            {"description": "伏笔A", "source_chapter": 3, "urgency_level": "normal"},
            {"description": "伏笔B", "source_chapter": 5, "urgency_level": "critical"},
        ])
        svc = ContinuityService(obligation_tracker=tracker)
        brief = svc.generate_brief(chapter_number=10)
        assert len(brief["open_threads"]) == 2
        assert "伏笔A" in brief["open_threads"][0]
        assert "伏笔B" in brief["open_threads"][1]

    def test_empty_debts(self):
        """No debts means empty open_threads."""
        tracker = _make_obligation_tracker([])
        svc = ContinuityService(obligation_tracker=tracker)
        brief = svc.generate_brief(chapter_number=10)
        assert brief["open_threads"] == []


# ---------------------------------------------------------------------------
# Tests: _extract_character_states
# ---------------------------------------------------------------------------

class TestCharacterStates:

    def test_db_state_preferred_over_profile(self):
        """When DB has state, it should be used instead of profile defaults."""
        db = _make_db({
            "c1": {
                "character_id": "c1",
                "health": "重伤",
                "location": "密室",
                "power_level": "筑基",
                "emotional_state": "焦虑",
            },
        })
        svc = ContinuityService(db=db)
        characters = [
            {"character_id": "c1", "name": "张三", "status": "active"},
        ]
        brief = svc.generate_brief(chapter_number=5, characters=characters)
        cs = brief["character_states"][0]
        assert cs["name"] == "张三"
        assert cs["location"] == "密室"
        assert cs["status"] == "重伤"
        assert cs["goal"] == "焦虑"

    def test_pydantic_model_characters(self):
        """Characters passed as objects with attributes (Pydantic-like)."""
        svc = ContinuityService()
        char = MagicMock()
        char.character_id = "c1"
        char.name = "李四"
        char.status = "active"

        brief = svc.generate_brief(chapter_number=2, characters=[char])
        assert brief["character_states"][0]["name"] == "李四"

    def test_empty_characters(self):
        """Empty character list produces no character states."""
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=2, characters=[])
        assert brief["character_states"] == []

    def test_unsupported_character_type_skipped(self):
        """Non-dict, non-object characters are gracefully skipped."""
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=2, characters=["not_a_char", 42])
        assert brief["character_states"] == []


# ---------------------------------------------------------------------------
# Tests: _extract_active_arcs
# ---------------------------------------------------------------------------

class TestActiveArcs:

    def test_active_arc_within_range(self):
        """Arc spanning current chapter is active."""
        svc = ContinuityService()
        arcs = [
            {
                "arc_id": "a1", "name": "试炼篇",
                "chapters": [5, 6, 7, 8, 9],
                "phase": "escalation", "status": "active",
            },
        ]
        brief = svc.generate_brief(chapter_number=7, story_arcs=arcs)
        assert len(brief["active_arcs"]) == 1
        assert brief["active_arcs"][0]["arc_name"] == "试炼篇"
        assert brief["active_arcs"][0]["chapters_remaining"] == 3  # 7,8,9

    def test_completed_arc_excluded(self):
        """Completed arcs are not included."""
        svc = ContinuityService()
        arcs = [
            {
                "arc_id": "a1", "name": "完结篇",
                "chapters": [1, 2, 3],
                "phase": "resolution", "status": "completed",
            },
        ]
        brief = svc.generate_brief(chapter_number=4, story_arcs=arcs)
        assert brief["active_arcs"] == []

    def test_past_arc_excluded(self):
        """Arcs whose last chapter is before current chapter are excluded."""
        svc = ContinuityService()
        arcs = [
            {
                "arc_id": "a1", "name": "过去篇",
                "chapters": [1, 2, 3],
                "phase": "setup", "status": "active",
            },
        ]
        brief = svc.generate_brief(chapter_number=5, story_arcs=arcs)
        assert brief["active_arcs"] == []

    def test_chapters_as_json_string(self):
        """Arc chapters stored as JSON string are parsed correctly."""
        svc = ContinuityService()
        arcs = [
            {
                "arc_id": "a1", "name": "密林探险",
                "chapters": "[10, 11, 12, 13]",
                "phase": "climax", "status": "in_progress",
            },
        ]
        brief = svc.generate_brief(chapter_number=12, story_arcs=arcs)
        assert len(brief["active_arcs"]) == 1
        assert brief["active_arcs"][0]["chapters_remaining"] == 2  # 12,13

    def test_invalid_chapters_json(self):
        """Invalid JSON in chapters field is handled gracefully."""
        svc = ContinuityService()
        arcs = [
            {
                "arc_id": "a1", "name": "坏数据",
                "chapters": "not valid json",
                "phase": "setup", "status": "active",
            },
        ]
        brief = svc.generate_brief(chapter_number=5, story_arcs=arcs)
        assert brief["active_arcs"] == []

    def test_empty_chapters(self):
        """Arc with empty chapters list is skipped."""
        svc = ContinuityService()
        arcs = [
            {
                "arc_id": "a1", "name": "空篇",
                "chapters": [],
                "phase": "setup", "status": "active",
            },
        ]
        brief = svc.generate_brief(chapter_number=5, story_arcs=arcs)
        assert brief["active_arcs"] == []


# ---------------------------------------------------------------------------
# Tests: _derive_forbidden_breaks
# ---------------------------------------------------------------------------

class TestForbiddenBreaks:

    def test_location_based_rule(self):
        """Character with a known location produces a location constraint."""
        db = _make_db({
            "c1": {
                "character_id": "c1",
                "health": "正常",
                "location": "王府",
                "power_level": None,
                "emotional_state": None,
            },
        })
        svc = ContinuityService(db=db)
        characters = [{"character_id": "c1", "name": "王五", "status": "active"}]
        brief = svc.generate_brief(chapter_number=3, characters=characters)
        assert any("王五" in fb and "王府" in fb for fb in brief["forbidden_breaks"])

    def test_deceased_character(self):
        """Deceased character triggers death constraint."""
        svc = ContinuityService()
        characters = [{"character_id": "c1", "name": "赵六", "status": "deceased"}]
        brief = svc.generate_brief(chapter_number=3, characters=characters)
        assert any("赵六" in fb and "死亡" in fb for fb in brief["forbidden_breaks"])

    def test_absent_character(self):
        """Absent character triggers absence constraint."""
        svc = ContinuityService()
        characters = [{"character_id": "c1", "name": "林秋", "status": "absent"}]
        brief = svc.generate_brief(chapter_number=3, characters=characters)
        assert any("林秋" in fb and "离队" in fb for fb in brief["forbidden_breaks"])

    def test_injured_character(self):
        """Injured character triggers injury constraint."""
        db = _make_db({
            "c1": {
                "character_id": "c1",
                "health": "重伤",
                "location": "",
                "power_level": None,
                "emotional_state": None,
            },
        })
        svc = ContinuityService(db=db)
        characters = [{"character_id": "c1", "name": "方岩", "status": "active"}]
        brief = svc.generate_brief(chapter_number=3, characters=characters)
        assert any("方岩" in fb and "重伤" in fb for fb in brief["forbidden_breaks"])


# ---------------------------------------------------------------------------
# Tests: _extract_recommended_payoffs
# ---------------------------------------------------------------------------

class TestRecommendedPayoffs:

    def test_payoff_from_chapter_brief(self):
        """chapter_brief payoff field appears in recommended_payoffs."""
        svc = ContinuityService()
        brief = svc.generate_brief(
            chapter_number=5,
            chapter_brief={"payoff": "揭示黑匣子真相"},
        )
        assert any("揭示黑匣子真相" in rp for rp in brief["recommended_payoffs"])

    def test_critical_debts_recommended(self):
        """Critical/high urgency debts appear in recommended_payoffs."""
        tracker = _make_obligation_tracker([
            {"description": "必须交代宝剑下落", "source_chapter": 2, "urgency_level": "critical"},
            {"description": "长期伏笔", "source_chapter": 1, "urgency_level": "normal"},
        ])
        svc = ContinuityService(obligation_tracker=tracker)
        brief = svc.generate_brief(chapter_number=5)
        payoff_text = " ".join(brief["recommended_payoffs"])
        assert "必须交代宝剑下落" in payoff_text
        # normal urgency should NOT appear in recommended_payoffs
        assert "长期伏笔" not in payoff_text

    def test_no_chapter_brief(self):
        """chapter_brief=None should not crash."""
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=5, chapter_brief=None)
        assert isinstance(brief["recommended_payoffs"], list)

    def test_empty_chapter_brief(self):
        """Empty chapter_brief dict produces no payoffs."""
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=5, chapter_brief={})
        assert brief["recommended_payoffs"] == []


# ---------------------------------------------------------------------------
# Tests: format_for_prompt
# ---------------------------------------------------------------------------

class TestFormatForPrompt:

    def test_empty_brief_returns_empty(self):
        """A brief with no meaningful data returns empty string."""
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=1)
        result = svc.format_for_prompt(brief)
        assert result == ""

    def test_all_sections_present(self):
        """All populated sections appear in the formatted output."""
        svc = ContinuityService()
        brief = {
            "chapter_number": 12,
            "must_continue": ["上一章沈夜决定夜探仓库"],
            "open_threads": ["黑匣子来源未解释 (来源: 第8章, 紧急度: high)"],
            "character_states": [
                {"name": "沈夜", "location": "客栈", "status": "轻伤", "goal": "查黑匣子"},
            ],
            "active_arcs": [
                {"arc_name": "黑匣子之谜", "phase": "rising", "chapters_remaining": 3},
            ],
            "forbidden_breaks": [
                "沈夜当前在客栈，不可无故出现在其他地点",
            ],
            "recommended_payoffs": [
                "推进黑匣子线索",
            ],
        }
        result = svc.format_for_prompt(brief)
        assert "第12章" in result
        assert "必须延续" in result
        assert "上一章沈夜决定夜探仓库" in result
        assert "未解决的叙事线" in result
        assert "黑匣子来源未解释" in result
        assert "角色当前状态" in result
        assert "沈夜" in result
        assert "客栈" in result
        assert "活跃故事弧线" in result
        assert "黑匣子之谜" in result
        assert "剩余3章" in result
        assert "禁止违反" in result
        assert "推荐推进" in result

    def test_partial_sections(self):
        """Only populated sections appear in the output."""
        svc = ContinuityService()
        brief = {
            "chapter_number": 3,
            "must_continue": ["测试钩子"],
            "open_threads": [],
            "character_states": [],
            "active_arcs": [],
            "forbidden_breaks": [],
            "recommended_payoffs": [],
        }
        result = svc.format_for_prompt(brief)
        assert "必须延续" in result
        assert "测试钩子" in result
        assert "未解决的叙事线" not in result
        assert "角色当前状态" not in result

    def test_character_state_missing_fields(self):
        """Character state with missing fields still renders."""
        svc = ContinuityService()
        brief = {
            "chapter_number": 1,
            "must_continue": [],
            "open_threads": [],
            "character_states": [
                {"name": "无名氏", "location": "", "status": "", "goal": ""},
            ],
            "active_arcs": [],
            "forbidden_breaks": [],
            "recommended_payoffs": [],
        }
        result = svc.format_for_prompt(brief)
        assert "无名氏" in result

    def test_arc_without_remaining(self):
        """Arc entry without chapters_remaining renders without remainder text."""
        svc = ContinuityService()
        brief = {
            "chapter_number": 1,
            "must_continue": [],
            "open_threads": [],
            "character_states": [],
            "active_arcs": [
                {"arc_name": "测试弧", "phase": "setup", "chapters_remaining": None},
            ],
            "forbidden_breaks": [],
            "recommended_payoffs": [],
        }
        result = svc.format_for_prompt(brief)
        assert "测试弧" in result
        assert "剩余" not in result


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_chapter_number_one(self):
        """Chapter 1 has no previous chapter -- should produce empty hooks."""
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=1, chapters=[])
        assert brief["must_continue"] == []

    def test_previous_chapter_empty_text(self):
        """Previous chapter with empty full_text produces no hooks."""
        svc = ContinuityService()
        chapters = [_make_chapter(4, full_text="")]
        brief = svc.generate_brief(chapter_number=5, chapters=chapters)
        assert brief["must_continue"] == []

    def test_story_arcs_abandoned_excluded(self):
        """Abandoned arcs are excluded from active_arcs."""
        svc = ContinuityService()
        arcs = [
            {
                "arc_id": "a1", "name": "被放弃的线",
                "chapters": [1, 2, 3, 4, 5, 6, 7, 8],
                "phase": "setup", "status": "abandoned",
            },
        ]
        brief = svc.generate_brief(chapter_number=3, story_arcs=arcs)
        assert brief["active_arcs"] == []

    def test_multiple_characters_mixed_sources(self):
        """Some characters have DB state, others fallback to profile."""
        db = _make_db({
            "c1": {
                "character_id": "c1",
                "health": "正常",
                "location": "山顶",
                "power_level": "金丹",
                "emotional_state": "冷静",
            },
            # c2 not in DB
        })
        svc = ContinuityService(db=db)
        characters = [
            {"character_id": "c1", "name": "角色A", "status": "active"},
            {"character_id": "c2", "name": "角色B", "status": "active"},
        ]
        brief = svc.generate_brief(chapter_number=5, characters=characters)
        assert len(brief["character_states"]) == 2
        # c1 from DB
        assert brief["character_states"][0]["location"] == "山顶"
        # c2 fallback
        assert brief["character_states"][1]["location"] == ""
        assert brief["character_states"][1]["status"] == "active"

    def test_sudden_hook_pattern(self):
        """Sudden event pattern (突然) is detected."""
        svc = ContinuityService()
        chapters = [
            _make_chapter(4, full_text="普通内容" * 50 + "突然一声巨响传来"),
        ]
        brief = svc.generate_brief(chapter_number=5, chapters=chapters)
        assert len(brief["must_continue"]) > 0

    def test_ellipsis_hook_pattern(self):
        """Trailing ellipsis is detected."""
        svc = ContinuityService()
        chapters = [
            _make_chapter(4, full_text="普通内容" * 50 + "他看着远方\u2026\u2026"),
        ]
        brief = svc.generate_brief(chapter_number=5, chapters=chapters)
        assert len(brief["must_continue"]) > 0
