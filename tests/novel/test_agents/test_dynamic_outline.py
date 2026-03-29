"""DynamicOutlinePlanner Agent tests

Covers:
1. Revision when previous chapter deviated from plan
2. No revision when outline is still appropriate
3. Skip for early chapters (1-3)
4. Revised outline maintains required fields
5. Graceful fallback when LLM fails (return original)
6. All LLM / state interactions are mocked
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.dynamic_outline import (
    DynamicOutlinePlanner,
    _build_previous_summaries,
    _build_upcoming_outlines,
    _format_character_states,
    _format_chapter_brief,
    _validate_revised_outline,
    dynamic_outline_node,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, model="mock-model", usage=None)


def _make_original_outline(**overrides) -> dict:
    defaults = {
        "chapter_number": 5,
        "title": "暗流涌动",
        "goal": "主角发现门派内有叛徒",
        "key_events": ["发现密信", "追踪线索", "遭遇伏击"],
        "mood": "蓄力",
        "involved_characters": ["张三", "李师傅"],
        "estimated_words": 2500,
        "plot_threads": ["叛徒线"],
        "storyline_progress": "推进叛徒调查",
        "chapter_brief": {
            "main_conflict": "门派内鬼",
            "payoff": "发现关键证据",
            "character_arc_step": "主角从信任变为怀疑",
            "foreshadowing_plant": ["神秘符文"],
            "foreshadowing_collect": [],
            "end_hook_type": "悬疑",
        },
    }
    defaults.update(overrides)
    return defaults


def _make_state(**overrides) -> dict:
    """Build a minimal valid state dict for the node."""
    defaults = {
        "current_chapter": 5,
        "current_chapter_outline": _make_original_outline(),
        "chapters": [
            {
                "chapter_number": 3,
                "title": "入门考验",
                "chapter_summary": "主角通过了门派入门考验，正式拜入李师傅门下。",
                "full_text": "..." * 100,
            },
            {
                "chapter_number": 4,
                "title": "初遇危机",
                "chapter_summary": "门派遭遇神秘势力袭击，主角意外发现一封密信，暗示门派内部有内鬼。",
                "full_text": "..." * 100,
            },
        ],
        "characters": [
            {"name": "张三", "occupation": "少年侠客", "current_state": "轻伤"},
            {"name": "李师傅", "occupation": "门派长老"},
        ],
        "outline": {
            "chapters": [
                {"chapter_number": 6, "title": "对峙", "goal": "与叛徒正面交锋", "key_events": ["揭穿叛徒"]},
                {"chapter_number": 7, "title": "余波", "goal": "处理叛变后续", "key_events": ["门派重建"]},
            ],
        },
        "continuity_brief": "上章遗留：主角轻伤未愈，密信线索指向长老堂",
        "debt_summary": "伏笔：第2章提到的黑衣人身份尚未揭晓（逾期）",
        "config": {
            "llm": {"provider": "openai", "model": "gpt-4"},
        },
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Tests: DynamicOutlinePlanner class
# ---------------------------------------------------------------------------


class TestDynamicOutlinePlanner:
    """Unit tests for the DynamicOutlinePlanner class."""

    def test_revision_when_deviated(self):
        """When previous chapters deviated from the plan, outline gets revised."""
        revised_json = json.dumps(
            {
                "revision_needed": True,
                "revision_reason": "前文第4章引入了神秘伤者，原始大纲未考虑此线索",
                "revised_outline": {
                    "title": "暗流涌动（修订）",
                    "goal": "主角追查密信线索，同时处理神秘伤者事件",
                    "key_events": ["审问伤者", "发现密信关联", "新线索浮现"],
                    "mood": "蓄力",
                    "involved_characters": ["张三", "李师傅", "神秘伤者"],
                    "estimated_words": 2500,
                    "chapter_brief": {
                        "main_conflict": "多线索交汇",
                        "payoff": "发现伤者与叛徒有关",
                        "character_arc_step": "主角学会多线思考",
                        "foreshadowing_plant": [],
                        "foreshadowing_collect": ["黑衣人身份"],
                        "end_hook_type": "悬疑",
                    },
                },
            },
            ensure_ascii=False,
        )

        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(revised_json)

        planner = DynamicOutlinePlanner(mock_llm)
        result = planner.revise_outline(
            chapter_number=5,
            original_outline=_make_original_outline(),
            previous_summaries="第4章: 门派遭袭，发现密信",
            continuity_brief="密信线索",
            debt_summary="黑衣人身份未揭晓",
            character_states=[{"name": "张三", "occupation": "侠客"}],
            arc_status="叛徒线: escalation",
        )

        assert result["revision_needed"] is True
        assert "神秘伤者" in result["revision_reason"]
        assert result["revised_outline"]["title"] == "暗流涌动（修订）"
        assert "审问伤者" in result["revised_outline"]["key_events"]
        mock_llm.chat.assert_called_once()

    def test_no_revision_when_consistent(self):
        """When the outline is still appropriate, return original unchanged."""
        no_change_json = json.dumps(
            {
                "revision_needed": False,
                "revision_reason": "原始大纲与前文一致",
                "revised_outline": {
                    "title": "暗流涌动",
                    "goal": "主角发现门派内有叛徒",
                    "key_events": ["发现密信", "追踪线索", "遭遇伏击"],
                    "mood": "蓄力",
                    "involved_characters": ["张三", "李师傅"],
                    "estimated_words": 2500,
                    "chapter_brief": {
                        "main_conflict": "门派内鬼",
                        "payoff": "发现关键证据",
                        "character_arc_step": "主角从信任变为怀疑",
                        "foreshadowing_plant": ["神秘符文"],
                        "foreshadowing_collect": [],
                        "end_hook_type": "悬疑",
                    },
                },
            },
            ensure_ascii=False,
        )

        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(no_change_json)

        planner = DynamicOutlinePlanner(mock_llm)
        result = planner.revise_outline(
            chapter_number=5,
            original_outline=_make_original_outline(),
            previous_summaries="正常进展",
            continuity_brief="",
            debt_summary="",
            character_states=[],
            arc_status="",
        )

        assert result["revision_needed"] is False
        assert result["revised_outline"]["title"] == "暗流涌动"

    def test_fallback_when_llm_returns_invalid_outline(self):
        """When LLM returns no revised_outline, keep original."""
        bad_json = json.dumps(
            {"revision_needed": True, "revision_reason": "需要修改"},
            ensure_ascii=False,
        )

        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(bad_json)

        planner = DynamicOutlinePlanner(mock_llm)
        original = _make_original_outline()
        result = planner.revise_outline(
            chapter_number=5,
            original_outline=original,
            previous_summaries="偏离",
            continuity_brief="",
            debt_summary="",
            character_states=[],
            arc_status="",
        )

        # Should fall back to original
        assert result["revision_needed"] is False
        assert result["revised_outline"]["title"] == original["title"]
        assert result["revised_outline"]["goal"] == original["goal"]

    def test_fallback_when_llm_raises(self):
        """When LLM chat raises an exception, revise_outline propagates it."""
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("API timeout")

        planner = DynamicOutlinePlanner(mock_llm)

        with pytest.raises(RuntimeError, match="API timeout"):
            planner.revise_outline(
                chapter_number=5,
                original_outline=_make_original_outline(),
                previous_summaries="text",
                continuity_brief="",
                debt_summary="",
                character_states=[],
                arc_status="",
            )

    def test_llm_returns_garbage_text(self):
        """When LLM returns non-JSON text, revise_outline raises ValueError."""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(
            "I'm sorry, I cannot help with that."
        )

        planner = DynamicOutlinePlanner(mock_llm)

        with pytest.raises(ValueError, match="无法从响应中提取有效 JSON"):
            planner.revise_outline(
                chapter_number=5,
                original_outline=_make_original_outline(),
                previous_summaries="text",
                continuity_brief="",
                debt_summary="",
                character_states=[],
                arc_status="",
            )


# ---------------------------------------------------------------------------
# Tests: dynamic_outline_node (LangGraph node)
# ---------------------------------------------------------------------------


class TestDynamicOutlineNode:
    """Integration-level tests for the node function."""

    @patch("src.novel.agents.dynamic_outline.create_llm_client")
    def test_skip_early_chapters(self, mock_create):
        """Chapters 1-3 should be skipped without calling LLM."""
        for ch in (1, 2, 3):
            state = _make_state(current_chapter=ch)
            result = dynamic_outline_node(state)

            assert "dynamic_outline" in result["completed_nodes"]
            assert any(
                "跳过" in d.get("decision", "") for d in result["decisions"]
            )
            # LLM should never be created
            mock_create.assert_not_called()

            # current_chapter_outline should NOT be in result (unchanged)
            assert "current_chapter_outline" not in result

    @patch("src.novel.agents.dynamic_outline.create_llm_client")
    def test_revision_applied(self, mock_create):
        """When revision is needed, current_chapter_outline is updated."""
        revised_json = json.dumps(
            {
                "revision_needed": True,
                "revision_reason": "前文偏离了原计划",
                "revised_outline": {
                    "title": "暗流涌动（修订版）",
                    "goal": "追查新线索",
                    "key_events": ["发现新证据"],
                    "mood": "蓄力",
                    "involved_characters": ["张三"],
                    "estimated_words": 2500,
                    "chapter_brief": {},
                },
            },
            ensure_ascii=False,
        )

        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(revised_json)
        mock_create.return_value = mock_llm

        state = _make_state(current_chapter=5)
        result = dynamic_outline_node(state)

        assert "dynamic_outline" in result["completed_nodes"]
        assert "current_chapter_outline" in result
        assert result["current_chapter_outline"]["title"] == "暗流涌动（修订版）"
        assert any(
            "修订" in d.get("decision", "") for d in result["decisions"]
        )

    @patch("src.novel.agents.dynamic_outline.create_llm_client")
    def test_no_revision(self, mock_create):
        """When no revision needed, current_chapter_outline is NOT in result."""
        no_change_json = json.dumps(
            {
                "revision_needed": False,
                "revision_reason": "原始大纲合适",
                "revised_outline": _make_original_outline(),
            },
            ensure_ascii=False,
        )

        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(no_change_json)
        mock_create.return_value = mock_llm

        state = _make_state(current_chapter=5)
        result = dynamic_outline_node(state)

        assert "dynamic_outline" in result["completed_nodes"]
        assert "current_chapter_outline" not in result
        assert any(
            "无需修订" in d.get("decision", "") for d in result["decisions"]
        )

    @patch("src.novel.agents.dynamic_outline.create_llm_client")
    def test_llm_failure_graceful(self, mock_create):
        """When LLM raises, node returns original outline + error decision."""
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("network error")
        mock_create.return_value = mock_llm

        state = _make_state(current_chapter=5)
        result = dynamic_outline_node(state)

        assert "dynamic_outline" in result["completed_nodes"]
        # Should NOT update outline
        assert "current_chapter_outline" not in result
        # Should have a decision about the failure
        assert any(
            "失败" in d.get("decision", "") for d in result["decisions"]
        )

    def test_missing_outline_returns_error(self):
        """When current_chapter_outline is missing, return error."""
        state = _make_state()
        state["current_chapter_outline"] = None

        result = dynamic_outline_node(state)

        assert "dynamic_outline" in result["completed_nodes"]
        assert len(result.get("errors", [])) > 0
        assert "大纲不存在" in result["errors"][0]["message"]

    @patch("src.novel.agents.dynamic_outline.create_llm_client")
    def test_llm_init_failure(self, mock_create):
        """When create_llm_client raises, return error."""
        mock_create.side_effect = ValueError("No API key")

        state = _make_state(current_chapter=5)
        result = dynamic_outline_node(state)

        assert "dynamic_outline" in result["completed_nodes"]
        assert len(result.get("errors", [])) > 0
        assert "LLM 初始化失败" in result["errors"][0]["message"]

    @patch("src.novel.agents.dynamic_outline.create_llm_client")
    def test_revised_outline_preserves_required_fields(self, mock_create):
        """Revised outline must have all required fields from the original."""
        # LLM returns incomplete outline (missing involved_characters, estimated_words)
        partial_json = json.dumps(
            {
                "revision_needed": True,
                "revision_reason": "需要微调",
                "revised_outline": {
                    "title": "修订标题",
                    "goal": "修订目标",
                    "key_events": ["事件A"],
                    "mood": "小爽",
                    # missing: involved_characters, estimated_words
                },
            },
            ensure_ascii=False,
        )

        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(partial_json)
        mock_create.return_value = mock_llm

        state = _make_state(current_chapter=5)
        result = dynamic_outline_node(state)

        revised = result["current_chapter_outline"]
        # Should have patched missing fields from original
        assert revised["involved_characters"] == ["张三", "李师傅"]
        assert revised["estimated_words"] == 2500
        assert revised["title"] == "修订标题"
        assert revised["mood"] == "小爽"
        # Carried-over fields
        assert revised["chapter_number"] == 5
        assert "chapter_brief" in revised

    @patch("src.novel.agents.dynamic_outline.create_llm_client")
    def test_chapter_4_is_not_skipped(self, mock_create):
        """Chapter 4 is the first chapter eligible for revision."""
        no_change_json = json.dumps(
            {
                "revision_needed": False,
                "revision_reason": "合适",
                "revised_outline": _make_original_outline(chapter_number=4),
            },
            ensure_ascii=False,
        )

        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(no_change_json)
        mock_create.return_value = mock_llm

        state = _make_state(current_chapter=4)
        result = dynamic_outline_node(state)

        # LLM should have been called (not skipped)
        mock_create.assert_called_once()
        mock_llm.chat.assert_called_once()

    @patch("src.novel.agents.dynamic_outline.create_llm_client")
    def test_no_previous_chapters(self, mock_create):
        """Node handles empty chapters list gracefully (chapter 4, no prior)."""
        no_change_json = json.dumps(
            {
                "revision_needed": False,
                "revision_reason": "无前文",
                "revised_outline": _make_original_outline(chapter_number=4),
            },
            ensure_ascii=False,
        )

        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(no_change_json)
        mock_create.return_value = mock_llm

        state = _make_state(current_chapter=4, chapters=[])
        result = dynamic_outline_node(state)

        assert "dynamic_outline" in result["completed_nodes"]
        # Should still complete without error
        assert not result.get("errors")


# ---------------------------------------------------------------------------
# Tests: helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    """Unit tests for module-level helper functions."""

    def test_build_previous_summaries_normal(self):
        chapters = [
            {"chapter_number": 1, "title": "A", "chapter_summary": "Summary A"},
            {"chapter_number": 2, "title": "B", "chapter_summary": "Summary B"},
            {"chapter_number": 3, "title": "C", "chapter_summary": "Summary C"},
        ]
        text = _build_previous_summaries(chapters, count=2)
        assert "Summary B" in text
        assert "Summary C" in text
        assert "Summary A" not in text

    def test_build_previous_summaries_empty(self):
        text = _build_previous_summaries([])
        assert "无前文" in text

    def test_build_previous_summaries_fallback_to_full_text(self):
        chapters = [
            {"chapter_number": 1, "title": "A", "full_text": "X" * 400},
        ]
        text = _build_previous_summaries(chapters, count=1)
        assert "..." in text  # Should be truncated
        assert len(text) < 500

    def test_format_character_states_normal(self):
        chars = [
            {"name": "Alice", "occupation": "warrior", "current_state": "injured"},
            {"name": "Bob", "occupation": "mage"},
        ]
        text = _format_character_states(chars)
        assert "Alice" in text
        assert "injured" in text
        assert "Bob" in text

    def test_format_character_states_empty(self):
        text = _format_character_states([])
        assert "无角色信息" in text

    def test_build_upcoming_outlines(self):
        outline = {
            "chapters": [
                {"chapter_number": 6, "title": "Ch6", "goal": "G6", "key_events": ["E6"]},
                {"chapter_number": 7, "title": "Ch7", "goal": "G7", "key_events": ["E7"]},
                {"chapter_number": 12, "title": "Ch12", "goal": "G12", "key_events": ["E12"]},
            ]
        }
        text = _build_upcoming_outlines(outline, chapter_number=5, window=3)
        assert "Ch6" in text
        assert "Ch7" in text
        assert "Ch12" not in text  # outside window

    def test_build_upcoming_outlines_none(self):
        text = _build_upcoming_outlines(None, chapter_number=5)
        assert "无后续章纲信息" in text

    def test_format_chapter_brief_normal(self):
        brief = {
            "main_conflict": "内鬼",
            "payoff": "发现证据",
            "end_hook_type": "悬疑",
        }
        text = _format_chapter_brief(brief)
        assert "内鬼" in text
        assert "发现证据" in text
        assert "悬疑" in text

    def test_format_chapter_brief_empty(self):
        assert _format_chapter_brief({}) == ""
        assert _format_chapter_brief(None) == ""

    def test_validate_revised_outline_patches_missing_fields(self):
        revised = {"title": "New", "goal": "New goal"}
        original = _make_original_outline()

        result = _validate_revised_outline(revised, original)

        assert result["title"] == "New"
        assert result["goal"] == "New goal"
        # Patched from original
        assert result["key_events"] == original["key_events"]
        assert result["mood"] == original["mood"]
        assert result["involved_characters"] == original["involved_characters"]
        assert result["estimated_words"] == 2500
        assert result["chapter_number"] == 5
        assert "chapter_brief" in result

    def test_validate_revised_outline_bad_estimated_words(self):
        revised = {
            "title": "T",
            "goal": "G",
            "key_events": ["E"],
            "mood": "蓄力",
            "involved_characters": ["A"],
            "estimated_words": "not_a_number",
        }
        original = _make_original_outline()

        result = _validate_revised_outline(revised, original)
        assert result["estimated_words"] == 2500  # Fallback

    def test_validate_revised_outline_key_events_not_list(self):
        revised = {
            "title": "T",
            "goal": "G",
            "key_events": "not a list",
            "mood": "蓄力",
            "involved_characters": ["A"],
            "estimated_words": 2500,
        }
        original = _make_original_outline()

        result = _validate_revised_outline(revised, original)
        assert result["key_events"] == original["key_events"]
