"""Tests for NarrativeRebuildService.

Covers chapter loading, debt extraction, auto-fulfillment detection,
arc detection with mock LLM, idempotent rebuild (no duplicates), and
edge cases (empty project, missing text).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.services.narrative_rebuild import (
    NarrativeRebuildService,
    _extract_key_terms,
)


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------


def _create_project(
    tmp_dir: str,
    chapters: list[dict] | None = None,
    novel_json_override: dict | None = None,
) -> str:
    """Create a minimal novel project directory with chapter files.

    Args:
        tmp_dir: Base temporary directory.
        chapters: Optional list of chapter dicts to write as JSON files.
        novel_json_override: If provided, used as the full novel.json content
            instead of the default minimal structure.

    Returns:
        The project_path string.
    """
    project_path = os.path.join(tmp_dir, "test_novel")
    os.makedirs(project_path, exist_ok=True)

    if novel_json_override is not None:
        novel_data = novel_json_override
    else:
        # Minimal novel.json
        novel_data = {
            "title": "Test Novel",
            "genre": "玄幻",
            "status": "writing",
            "current_chapter": len(chapters) if chapters else 0,
            "outline": {"chapters": []},
        }
    with open(
        os.path.join(project_path, "novel.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(novel_data, f, ensure_ascii=False)

    if chapters:
        chapters_dir = os.path.join(project_path, "chapters")
        os.makedirs(chapters_dir, exist_ok=True)
        for ch in chapters:
            num = ch["chapter_number"]
            filename = f"chapter_{num:03d}.json"
            with open(
                os.path.join(chapters_dir, filename), "w", encoding="utf-8"
            ) as f:
                json.dump(ch, f, ensure_ascii=False)

    return project_path


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture()
def mock_llm():
    llm = MagicMock()
    return llm


# ---------------------------------------------------------------
# Sample chapter data
# ---------------------------------------------------------------


_CHAPTER_1 = {
    "chapter_number": 1,
    "title": "第一章 出发",
    "full_text": (
        "陈凡握紧拳头，发誓一定要为师父报仇。"
        "他转身离开山门，准备去寻找那颗传说中的灵珠。"
        "这一切的真相究竟是什么，他还不知道。"
    ),
}

_CHAPTER_2 = {
    "chapter_number": 2,
    "title": "第二章 山中",
    "full_text": (
        "陈凡在密林中穿行，心中暗暗下定决心。"
        "忽然前方传来一阵喊杀声，他急忙赶往声音传来的方向。"
    ),
}

_CHAPTER_3 = {
    "chapter_number": 3,
    "title": "第三章 报仇",
    "full_text": (
        "经过数日追踪，陈凡终于找到了杀害师父的凶手。"
        "他提剑而上，为师父报仇雪恨。"
        "灵珠的秘密也在这一刻揭开了真相。"
    ),
}


# ---------------------------------------------------------------
# Tests
# ---------------------------------------------------------------


class TestLoadChapters:
    """Test _load_chapters sorts chapters correctly."""

    def test_load_chapters_sorted(self, tmp_dir):
        """Chapters are loaded in order even when files are created out of order."""
        chapters = [
            {"chapter_number": 3, "title": "Ch3", "full_text": "text3"},
            {"chapter_number": 1, "title": "Ch1", "full_text": "text1"},
            {"chapter_number": 2, "title": "Ch2", "full_text": "text2"},
        ]
        project_path = _create_project(tmp_dir, chapters)
        service = NarrativeRebuildService(project_path)
        try:
            loaded = service._load_chapters()
            assert len(loaded) == 3
            assert loaded[0]["chapter_number"] == 1
            assert loaded[1]["chapter_number"] == 2
            assert loaded[2]["chapter_number"] == 3
        finally:
            service.close()

    def test_load_chapters_empty_project(self, tmp_dir):
        """No chapters directory returns empty list."""
        project_path = _create_project(tmp_dir, chapters=None)
        service = NarrativeRebuildService(project_path)
        try:
            loaded = service._load_chapters()
            assert loaded == []
        finally:
            service.close()


class TestRebuildDebts:
    """Test debt extraction from chapters."""

    def test_rebuild_debts_from_chapters(self, tmp_dir):
        """Extracts debts from chapters with promise/action/unresolved patterns."""
        chapters = [_CHAPTER_1, _CHAPTER_2]
        project_path = _create_project(tmp_dir, chapters)
        service = NarrativeRebuildService(project_path)
        try:
            result = service.rebuild_debts(method="rule_based")
            assert result["chapters_scanned"] == 2
            assert result["debts_extracted"] > 0
            # Chapter 1 has: 发誓, 一定要, 准备去, 究竟, 真相
            assert any(
                d["chapter"] == 1 and d["debts_found"] > 0
                for d in result["details"]
            )
        finally:
            service.close()

    def test_rebuild_empty_project(self, tmp_dir):
        """Empty project returns zero debts."""
        project_path = _create_project(tmp_dir, chapters=None)
        service = NarrativeRebuildService(project_path)
        try:
            result = service.rebuild_debts(method="rule_based")
            assert result["chapters_scanned"] == 0
            assert result["debts_extracted"] == 0
            assert result["details"] == []
        finally:
            service.close()

    def test_rebuild_chapter_with_no_text(self, tmp_dir):
        """Chapter with empty text produces zero debts but is counted."""
        chapters = [{"chapter_number": 1, "title": "Empty", "full_text": ""}]
        project_path = _create_project(tmp_dir, chapters)
        service = NarrativeRebuildService(project_path)
        try:
            result = service.rebuild_debts(method="rule_based")
            assert result["chapters_scanned"] == 1
            assert result["debts_extracted"] == 0
            assert result["details"][0]["debts_found"] == 0
        finally:
            service.close()


class TestAutoFulfillDetection:
    """Test cross-chapter auto-fulfill heuristic."""

    def test_auto_fulfill_detection(self, tmp_dir):
        """Debt from chapter 1 ('报仇') found in chapter 3 is auto-fulfilled."""
        chapters = [_CHAPTER_1, _CHAPTER_2, _CHAPTER_3]
        project_path = _create_project(tmp_dir, chapters)
        service = NarrativeRebuildService(project_path)
        try:
            result = service.rebuild_debts(method="rule_based")
            assert result["debts_auto_fulfilled"] > 0
            # Verify at least one debt was marked fulfilled in the DB
            fulfilled = service.db.query_debts(status="fulfilled")
            assert len(fulfilled) > 0
            # Check fulfillment note mentions auto-detection
            note = fulfilled[0].get("fulfillment_note", "")
            assert "自动检测" in note
        finally:
            service.close()


class TestRebuildIdempotent:
    """Test that running rebuild twice doesn't create duplicates."""

    def test_rebuild_clears_old_debts(self, tmp_dir):
        """Running rebuild twice yields the same debt count (no duplicates)."""
        chapters = [_CHAPTER_1, _CHAPTER_2]
        project_path = _create_project(tmp_dir, chapters)
        service = NarrativeRebuildService(project_path)
        try:
            result1 = service.rebuild_debts(method="rule_based")
            result2 = service.rebuild_debts(method="rule_based")
            assert result1["debts_extracted"] == result2["debts_extracted"]

            # Verify DB only has one set of debts
            all_debts = service.db.query_debts()
            assert len(all_debts) == result2["debts_extracted"]
        finally:
            service.close()


class TestRebuildWithLLM:
    """Test hybrid extraction with mock LLM."""

    def test_rebuild_with_llm(self, tmp_dir, mock_llm):
        """Hybrid extraction calls LLM and merges results."""
        llm_response = LLMResponse(
            content=json.dumps({
                "debts": [
                    {
                        "type": "must_pay_next",
                        "description": "主角必须找到灵珠",
                        "urgency_level": "high",
                    }
                ]
            }),
            model="mock",
            usage=None,
        )
        mock_llm.chat.return_value = llm_response

        chapters = [_CHAPTER_1]
        project_path = _create_project(tmp_dir, chapters)
        service = NarrativeRebuildService(project_path, llm_client=mock_llm)
        try:
            result = service.rebuild_debts(method="hybrid")
            assert result["chapters_scanned"] == 1
            assert result["debts_extracted"] > 0
            # LLM was called
            assert mock_llm.chat.called
        finally:
            service.close()


class TestRebuildArcsWithLLM:
    """Test story arc detection with mock LLM."""

    def test_rebuild_arcs_with_llm(self, tmp_dir, mock_llm):
        """Mock LLM returns arc JSON which is saved to DB."""
        arc_response = LLMResponse(
            content=json.dumps({
                "arcs": [
                    {
                        "name": "复仇之路",
                        "chapters": [1, 2, 3],
                        "phase": "escalation",
                        "hook": "师父被杀",
                        "turning_point": "发现凶手",
                    }
                ]
            }),
            model="mock",
            usage=None,
        )
        mock_llm.chat.return_value = arc_response

        chapters = [_CHAPTER_1, _CHAPTER_2, _CHAPTER_3]
        project_path = _create_project(tmp_dir, chapters)
        service = NarrativeRebuildService(project_path, llm_client=mock_llm)
        try:
            result = service.rebuild_arcs()
            assert result["arcs_detected"] == 1
            assert result["arcs"][0]["name"] == "复仇之路"

            # Verify saved to DB
            db_arcs = service.db.query_story_units()
            assert len(db_arcs) == 1
            assert "复仇之路" in db_arcs[0]["name"]
        finally:
            service.close()

    def test_rebuild_arcs_no_llm(self, tmp_dir):
        """Without LLM, arc detection returns empty."""
        chapters = [_CHAPTER_1, _CHAPTER_2]
        project_path = _create_project(tmp_dir, chapters)
        service = NarrativeRebuildService(project_path, llm_client=None)
        try:
            result = service.rebuild_arcs()
            assert result["arcs_detected"] == 0
        finally:
            service.close()


class TestRebuildAll:
    """Test the full rebuild_all method."""

    def test_rebuild_all_returns_summary(self, tmp_dir):
        """Verify return dict has correct structure."""
        chapters = [_CHAPTER_1, _CHAPTER_2]
        project_path = _create_project(tmp_dir, chapters)
        service = NarrativeRebuildService(project_path)
        try:
            result = service.rebuild_all(method="rule_based")
            assert "chapters_scanned" in result
            assert "debts_extracted" in result
            assert "debts_auto_fulfilled" in result
            assert "arcs_detected" in result
            assert "details" in result
            assert isinstance(result["details"], list)
            assert result["chapters_scanned"] == 2
        finally:
            service.close()


class TestExtractKeyTerms:
    """Test the _extract_key_terms helper."""

    def test_extract_from_description(self):
        terms = _extract_key_terms("角色承诺: 一定要为师父报仇")
        assert len(terms) > 0
        # Should contain multi-char Chinese terms
        for t in terms:
            assert len(t) >= 2

    def test_extract_from_empty(self):
        assert _extract_key_terms("") == []

    def test_extract_strips_label(self):
        terms = _extract_key_terms("悬念未解: 真相究竟是什么")
        # "悬念未解:" prefix should be stripped
        assert len(terms) > 0
        # Should not include "悬念未解" as a term since it was a label prefix
        descriptions = " ".join(terms)
        assert "真相" in descriptions or "究竟" in descriptions

    def test_extract_max_five_terms(self):
        long_desc = "角色承诺: 必须完成修炼突破境界掌握秘法打败强敌拯救世界"
        terms = _extract_key_terms(long_desc)
        assert len(terms) <= 5


# ---------------------------------------------------------------
# Outline debt extraction tests
# ---------------------------------------------------------------


class TestOutlineDebts:
    """Test debt extraction from outline foreshadowing."""

    def test_extract_foreshadowing_debts(self, tmp_dir):
        """Outline foreshadowing creates long_tail_payoff debts."""
        novel_json = {
            "title": "Test",
            "genre": "玄幻",
            "outline": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "第一章",
                        "foreshadowing": ["神秘黑影的身份", "灵珠的来历"],
                        "key_events": [],
                    },
                ]
            },
        }
        chapters = [_CHAPTER_1]
        project_path = _create_project(
            tmp_dir, chapters, novel_json_override=novel_json
        )
        service = NarrativeRebuildService(project_path)
        try:
            result = service.rebuild_debts(method="rule_based")
            assert result["debts_from_outline"] == 2
            # Verify the outline debts are in the DB
            all_debts = service.db.query_debts()
            outline_debts = [
                d for d in all_debts
                if "大纲伏笔" in d.get("description", "")
            ]
            assert len(outline_debts) == 2
            # All should be long_tail_payoff
            for d in outline_debts:
                assert d["type"] == "long_tail_payoff"
        finally:
            service.close()

    def test_extract_key_event_debts(self, tmp_dir):
        """Key events with continuation keywords create pay_within_3 debts."""
        novel_json = {
            "title": "Test",
            "genre": "玄幻",
            "outline": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "第一章",
                        "foreshadowing": [],
                        "key_events": [
                            "主角发现了隐藏的宝藏",
                            "一场大战开始了",
                            "普通的叙述",  # no keyword match
                        ],
                    },
                ]
            },
        }
        chapters = [_CHAPTER_1]
        project_path = _create_project(
            tmp_dir, chapters, novel_json_override=novel_json
        )
        service = NarrativeRebuildService(project_path)
        try:
            result = service.rebuild_debts(method="rule_based")
            assert result["debts_from_outline"] == 2  # "发现" and "开始"
            all_debts = service.db.query_debts()
            event_debts = [
                d for d in all_debts
                if "大纲事件" in d.get("description", "")
            ]
            assert len(event_debts) == 2
            for d in event_debts:
                assert d["type"] == "pay_within_3"
        finally:
            service.close()

    def test_skip_unwritten_chapters(self, tmp_dir):
        """Outline debts only for chapters that have been written."""
        novel_json = {
            "title": "Test",
            "genre": "玄幻",
            "outline": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "foreshadowing": ["伏笔A"],
                        "key_events": [],
                    },
                    {
                        "chapter_number": 5,  # not written
                        "foreshadowing": ["伏笔B"],
                        "key_events": ["发现了新线索"],
                    },
                ]
            },
        }
        # Only chapter 1 is written
        chapters = [_CHAPTER_1]
        project_path = _create_project(
            tmp_dir, chapters, novel_json_override=novel_json
        )
        service = NarrativeRebuildService(project_path)
        try:
            result = service.rebuild_debts(method="rule_based")
            # Only chapter 1 foreshadowing should be extracted
            assert result["debts_from_outline"] == 1
        finally:
            service.close()

    def test_no_outline(self, tmp_dir):
        """No outline in novel.json -> no outline debts."""
        novel_json = {
            "title": "Test",
            "genre": "玄幻",
        }
        chapters = [_CHAPTER_1]
        project_path = _create_project(
            tmp_dir, chapters, novel_json_override=novel_json
        )
        service = NarrativeRebuildService(project_path)
        try:
            result = service.rebuild_debts(method="rule_based")
            assert result["debts_from_outline"] == 0
        finally:
            service.close()


# ---------------------------------------------------------------
# Character graph rebuild tests
# ---------------------------------------------------------------


class TestCharacterGraph:
    """Test character relationship graph rebuild."""

    def test_rebuild_character_graph(self, tmp_dir):
        """Characters from novel.json are added as facts in the DB."""
        novel_json = {
            "title": "Test",
            "genre": "玄幻",
            "outline": {"chapters": []},
            "characters": [
                {
                    "name": "林峰",
                    "role": "protagonist",
                    "personality": "坚毅果断",
                    "goals": ["修炼到巅峰", "为师报仇"],
                    "relationships": [],
                },
                {
                    "name": "赵灵儿",
                    "role": "heroine",
                    "personality": "温柔善良",
                    "goals": ["寻找真相"],
                    "relationships": [],
                },
            ],
        }
        chapters = [_CHAPTER_1]
        project_path = _create_project(
            tmp_dir, chapters, novel_json_override=novel_json
        )
        service = NarrativeRebuildService(project_path)
        try:
            result = service._rebuild_character_graph()
            assert result["nodes"] == 2
            assert result["edges"] == 0

            # Verify facts exist in DB
            facts = service.db.get_facts(fact_type="character_state")
            char_facts = [f for f in facts if f["fact_id"].startswith("char_")]
            assert len(char_facts) == 2

            # Check content includes personality and goals
            lf_fact = next(
                f for f in char_facts if f["fact_id"] == "char_林峰"
            )
            assert "protagonist" in lf_fact["content"]
            assert "坚毅果断" in lf_fact["content"]
            assert "修炼到巅峰" in lf_fact["content"]
        finally:
            service.close()

    def test_rebuild_relationships(self, tmp_dir):
        """Character relationships create relationship facts in DB."""
        novel_json = {
            "title": "Test",
            "genre": "玄幻",
            "outline": {"chapters": []},
            "characters": [
                {
                    "name": "林峰",
                    "role": "protagonist",
                    "relationships": [
                        {
                            "target": "赵灵儿",
                            "type": "恋人",
                            "description": "青梅竹马",
                        },
                        {
                            "target": "张老",
                            "type": "师徒",
                            "description": "修炼导师",
                        },
                    ],
                },
            ],
        }
        chapters = [_CHAPTER_1]
        project_path = _create_project(
            tmp_dir, chapters, novel_json_override=novel_json
        )
        service = NarrativeRebuildService(project_path)
        try:
            result = service._rebuild_character_graph()
            assert result["nodes"] == 1
            assert result["edges"] == 2

            # Verify relationship facts
            facts = service.db.get_facts(fact_type="relationship")
            rel_facts = [f for f in facts if f["fact_id"].startswith("rel_")]
            assert len(rel_facts) == 2

            # Check content
            contents = [f["content"] for f in rel_facts]
            assert any("恋人" in c and "青梅竹马" in c for c in contents)
            assert any("师徒" in c and "修炼导师" in c for c in contents)
        finally:
            service.close()

    def test_no_characters(self, tmp_dir):
        """Empty characters list -> no nodes or edges."""
        novel_json = {
            "title": "Test",
            "genre": "玄幻",
            "outline": {"chapters": []},
            "characters": [],
        }
        chapters = [_CHAPTER_1]
        project_path = _create_project(
            tmp_dir, chapters, novel_json_override=novel_json
        )
        service = NarrativeRebuildService(project_path)
        try:
            result = service._rebuild_character_graph()
            assert result["nodes"] == 0
            assert result["edges"] == 0
        finally:
            service.close()

    def test_character_without_name_skipped(self, tmp_dir):
        """Character entries with empty name are skipped."""
        novel_json = {
            "title": "Test",
            "genre": "玄幻",
            "outline": {"chapters": []},
            "characters": [
                {"name": "", "role": "unknown"},
                {"name": "有名角色", "role": "protagonist"},
            ],
        }
        chapters = [_CHAPTER_1]
        project_path = _create_project(
            tmp_dir, chapters, novel_json_override=novel_json
        )
        service = NarrativeRebuildService(project_path)
        try:
            result = service._rebuild_character_graph()
            assert result["nodes"] == 1
        finally:
            service.close()


# ---------------------------------------------------------------
# Enhanced rebuild_all tests
# ---------------------------------------------------------------


class TestEnhancedRebuildAll:
    """Test full rebuild with all sources."""

    def test_rebuild_all_includes_outline_and_graph(self, tmp_dir):
        """rebuild_all returns outline debt count and character graph stats."""
        novel_json = {
            "title": "Test",
            "genre": "玄幻",
            "outline": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "foreshadowing": ["神秘人物的身份"],
                        "key_events": ["主角发现线索"],
                    },
                ]
            },
            "characters": [
                {
                    "name": "林峰",
                    "role": "protagonist",
                    "personality": "坚毅",
                    "goals": ["修炼"],
                    "relationships": [
                        {"target": "赵灵儿", "type": "恋人"},
                    ],
                },
            ],
        }
        chapters = [_CHAPTER_1]
        project_path = _create_project(
            tmp_dir, chapters, novel_json_override=novel_json
        )
        service = NarrativeRebuildService(project_path)
        try:
            result = service.rebuild_all(method="rule_based")

            # Standard keys
            assert "chapters_scanned" in result
            assert "debts_extracted" in result
            assert "arcs_detected" in result

            # New keys from outline
            assert "debts_from_outline" in result
            assert "debts_from_chapters" in result
            assert result["debts_from_outline"] >= 2  # 1 foreshadowing + 1 key event

            # New keys from character graph
            assert "character_nodes" in result
            assert "character_edges" in result
            assert result["character_nodes"] == 1
            assert result["character_edges"] == 1
        finally:
            service.close()

    def test_rebuild_all_no_novel_json(self, tmp_dir):
        """Project without novel.json still works (graceful fallback)."""
        project_path = os.path.join(tmp_dir, "test_novel")
        os.makedirs(project_path, exist_ok=True)
        # Create chapters dir with one chapter, but NO novel.json
        chapters_dir = os.path.join(project_path, "chapters")
        os.makedirs(chapters_dir, exist_ok=True)
        ch_path = os.path.join(chapters_dir, "chapter_001.json")
        with open(ch_path, "w", encoding="utf-8") as f:
            json.dump(_CHAPTER_1, f, ensure_ascii=False)

        service = NarrativeRebuildService(project_path)
        try:
            result = service.rebuild_all(method="rule_based")
            assert result["chapters_scanned"] == 1
            assert result["debts_from_outline"] == 0
            assert result["character_nodes"] == 0
            assert result["character_edges"] == 0
        finally:
            service.close()


# ---------------------------------------------------------------
# Arc detection with outline context tests
# ---------------------------------------------------------------


class TestArcDetectionWithOutlineContext:
    """Test that arc detection includes outline context in LLM prompt."""

    def test_outline_context_included_in_prompt(self, tmp_dir, mock_llm):
        """When outline has main_storyline and acts, they appear in the LLM prompt."""
        arc_response = LLMResponse(
            content=json.dumps({
                "arcs": [
                    {
                        "name": "修炼之路",
                        "chapters": [1],
                        "phase": "setup",
                        "hook": "开始修炼",
                        "turning_point": "突破",
                    }
                ]
            }),
            model="mock",
            usage=None,
        )
        mock_llm.chat.return_value = arc_response

        novel_json = {
            "title": "Test",
            "genre": "玄幻",
            "outline": {
                "main_storyline": "少年修炼逆天改命的故事",
                "acts": [
                    {"name": "第一幕", "description": "主角踏上修炼之路"},
                    {"name": "第二幕", "description": "遭遇强敌考验"},
                ],
                "chapters": [],
            },
        }
        chapters = [_CHAPTER_1]
        project_path = _create_project(
            tmp_dir, chapters, novel_json_override=novel_json
        )
        service = NarrativeRebuildService(project_path, llm_client=mock_llm)
        try:
            service.rebuild_arcs()

            # Verify the prompt sent to LLM includes outline context
            assert mock_llm.chat.called
            call_args = mock_llm.chat.call_args
            messages = call_args[0][0]
            user_msg = messages[1]["content"]
            assert "少年修炼逆天改命" in user_msg
            assert "第一幕" in user_msg
            assert "踏上修炼之路" in user_msg
        finally:
            service.close()

    def test_arc_detection_without_outline(self, tmp_dir, mock_llm):
        """Arc detection works fine without outline context."""
        arc_response = LLMResponse(
            content=json.dumps({"arcs": []}),
            model="mock",
            usage=None,
        )
        mock_llm.chat.return_value = arc_response

        novel_json = {"title": "Test", "genre": "玄幻"}
        chapters = [_CHAPTER_1]
        project_path = _create_project(
            tmp_dir, chapters, novel_json_override=novel_json
        )
        service = NarrativeRebuildService(project_path, llm_client=mock_llm)
        try:
            result = service.rebuild_arcs()
            assert result["arcs_detected"] == 0
            # LLM was still called (just no outline context in prompt)
            assert mock_llm.chat.called
        finally:
            service.close()


# ---------------------------------------------------------------
# Novel metadata loading tests
# ---------------------------------------------------------------


class TestLoadNovelJson:
    """Test _load_novel_json edge cases."""

    def test_load_valid_novel_json(self, tmp_dir):
        """Valid novel.json is loaded correctly."""
        novel_json = {
            "title": "My Novel",
            "genre": "玄幻",
            "outline": {"main_storyline": "test story"},
            "characters": [{"name": "A"}],
            "world_setting": {"world_name": "灵界"},
        }
        project_path = _create_project(
            tmp_dir, chapters=[_CHAPTER_1], novel_json_override=novel_json
        )
        service = NarrativeRebuildService(project_path)
        try:
            assert service.outline == {"main_storyline": "test story"}
            assert len(service.characters) == 1
            assert service.characters[0]["name"] == "A"
            assert service.world_setting["world_name"] == "灵界"
        finally:
            service.close()

    def test_load_missing_novel_json(self, tmp_dir):
        """Missing novel.json results in empty metadata."""
        project_path = os.path.join(tmp_dir, "test_novel")
        os.makedirs(project_path, exist_ok=True)
        # No novel.json created
        service = NarrativeRebuildService(project_path)
        try:
            assert service.outline == {}
            assert service.characters == []
            assert service.world_setting == {}
        finally:
            service.close()

    def test_load_corrupt_novel_json(self, tmp_dir):
        """Corrupt novel.json results in empty metadata."""
        project_path = os.path.join(tmp_dir, "test_novel")
        os.makedirs(project_path, exist_ok=True)
        # Write invalid JSON
        with open(
            os.path.join(project_path, "novel.json"), "w", encoding="utf-8"
        ) as f:
            f.write("{invalid json!!!")
        service = NarrativeRebuildService(project_path)
        try:
            assert service.outline == {}
            assert service.characters == []
            assert service.world_setting == {}
        finally:
            service.close()


# ---------------------------------------------------------------
# LLM-based fulfillment detection tests
# ---------------------------------------------------------------


class TestLLMFulfillment:
    """Test LLM-based debt fulfillment detection."""

    def test_llm_fulfillment_marks_debts(self, tmp_dir, mock_llm):
        """LLM correctly marks debts as fulfilled with AI note."""
        # Use rule_based extraction so LLM is only called for auto-fulfill.
        # This avoids needing to mock DebtExtractor LLM calls.
        fulfill_response = LLMResponse(
            content=json.dumps({
                "results": [
                    {
                        "index": 1,
                        "fulfilled": True,
                        "fulfilled_in_chapter": 3,
                        "reason": "第三章主角为师父报仇雪恨",
                    },
                ]
            }),
            model="mock",
            usage=None,
        )
        mock_llm.chat.return_value = fulfill_response

        chapters = [_CHAPTER_1, _CHAPTER_2, _CHAPTER_3]
        project_path = _create_project(tmp_dir, chapters)
        service = NarrativeRebuildService(project_path, llm_client=mock_llm)
        try:
            result = service.rebuild_debts(method="rule_based")
            assert result["debts_auto_fulfilled"] > 0
            # Verify fulfilled debts in the DB
            fulfilled = service.db.query_debts(status="fulfilled")
            assert len(fulfilled) > 0
            # Check that at least one has AI note
            ai_notes = [
                d for d in fulfilled
                if "AI判定" in (d.get("fulfillment_note") or "")
            ]
            assert len(ai_notes) > 0
        finally:
            service.close()

    def test_llm_fulfillment_fallback_on_error(self, tmp_dir, mock_llm):
        """Falls back to keyword matching when LLM fails during auto-fulfill."""
        # Use rule_based extraction so LLM is only called for auto-fulfill.
        # Then auto-fulfill LLM raises an error.
        mock_llm.chat.side_effect = RuntimeError("LLM connection failed")

        chapters = [_CHAPTER_1, _CHAPTER_2, _CHAPTER_3]
        project_path = _create_project(tmp_dir, chapters)
        service = NarrativeRebuildService(project_path, llm_client=mock_llm)
        try:
            result = service.rebuild_debts(method="rule_based")
            # Should still have some auto-fulfilled via keyword fallback
            # (Chapter 3 mentions 报仇, which matches debts from chapter 1)
            assert result["chapters_scanned"] == 3
            # The keyword fallback was used, so check debts were processed
            # without raising an error
            assert result["debts_extracted"] > 0
            assert result["debts_auto_fulfilled"] > 0
            # Verify keyword fallback was used (note says "自动检测", not "AI判定")
            fulfilled = service.db.query_debts(status="fulfilled")
            for d in fulfilled:
                note = d.get("fulfillment_note", "")
                assert "自动检测" in note
        finally:
            service.close()

    def test_no_llm_uses_keywords(self, tmp_dir):
        """Without LLM client, uses keyword matching for auto-fulfill."""
        chapters = [_CHAPTER_1, _CHAPTER_2, _CHAPTER_3]
        project_path = _create_project(tmp_dir, chapters)
        # No LLM client
        service = NarrativeRebuildService(project_path, llm_client=None)
        try:
            result = service.rebuild_debts(method="rule_based")
            assert result["chapters_scanned"] == 3
            # Keyword-based fulfillment should find "报仇" match
            assert result["debts_auto_fulfilled"] > 0
            fulfilled = service.db.query_debts(status="fulfilled")
            assert len(fulfilled) > 0
            # Note should say "自动检测" (keyword), not "AI判定"
            for d in fulfilled:
                note = d.get("fulfillment_note", "")
                assert "自动检测" in note
                assert "AI判定" not in note
        finally:
            service.close()

    def test_llm_batch_processing(self, tmp_dir, mock_llm):
        """Debts are processed in batches of 10 — LLM is called multiple times."""
        # Create enough debts to trigger multiple batches (>10)
        # We'll use rule_based extraction so LLM is only called for auto-fulfill
        chapters = [_CHAPTER_1, _CHAPTER_2, _CHAPTER_3]
        project_path = _create_project(tmp_dir, chapters)
        service = NarrativeRebuildService(project_path, llm_client=mock_llm)
        try:
            # Manually create 15 debts to test batching
            test_debts = []
            for k in range(15):
                debt = {
                    "debt_id": f"test_debt_{k}",
                    "source_chapter": 1,
                    "type": "pay_within_3",
                    "description": f"测试债务{k}: 需要兑现的承诺",
                }
                service.tracker.add_debt(
                    debt_id=debt["debt_id"],
                    source_chapter=debt["source_chapter"],
                    debt_type=debt["type"],
                    description=debt["description"],
                )
                test_debts.append(debt)

            # Mock LLM to return empty results (no fulfillments)
            empty_response = LLMResponse(
                content=json.dumps({"results": []}),
                model="mock",
                usage=None,
            )
            mock_llm.chat.return_value = empty_response

            # Call _auto_fulfill_with_llm directly
            result = service._auto_fulfill_with_llm(test_debts, chapters)

            # Should have called LLM twice: batch 0-9 and batch 10-14
            assert mock_llm.chat.call_count == 2
            assert result == 0  # No fulfillments from empty results
        finally:
            service.close()

    def test_llm_fulfillment_skips_already_fulfilled(self, tmp_dir, mock_llm):
        """Debts already marked as fulfilled are not sent to LLM."""
        chapters = [_CHAPTER_1, _CHAPTER_2, _CHAPTER_3]
        project_path = _create_project(tmp_dir, chapters)
        service = NarrativeRebuildService(project_path, llm_client=mock_llm)
        try:
            # All debts already fulfilled
            test_debts = [
                {
                    "debt_id": "d1",
                    "source_chapter": 1,
                    "description": "已兑现的债务",
                    "_fulfilled_in": 2,
                },
                {
                    "debt_id": "d2",
                    "source_chapter": 1,
                    "description": "也已兑现的债务",
                    "_fulfilled_in": 3,
                },
            ]

            result = service._auto_fulfill_with_llm(test_debts, chapters)

            # LLM should NOT be called since all debts are already fulfilled
            assert mock_llm.chat.call_count == 0
            assert result == 0
        finally:
            service.close()

    def test_llm_fulfillment_no_relevant_summaries(self, tmp_dir, mock_llm):
        """When no chapters follow the debt source, LLM is not called."""
        # Only chapter 3 debt, no chapters after it
        chapters = [_CHAPTER_1, _CHAPTER_2, _CHAPTER_3]
        project_path = _create_project(tmp_dir, chapters)
        service = NarrativeRebuildService(project_path, llm_client=mock_llm)
        try:
            test_debts = [
                {
                    "debt_id": "d_last",
                    "source_chapter": 3,
                    "description": "最后一章的债务",
                },
            ]

            result = service._auto_fulfill_with_llm(test_debts, chapters)

            # No chapters after chapter 3, so LLM should not be called
            assert mock_llm.chat.call_count == 0
            assert result == 0
        finally:
            service.close()
