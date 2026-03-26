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
    tmp_dir: str, chapters: list[dict] | None = None
) -> str:
    """Create a minimal novel project directory with chapter files.

    Args:
        tmp_dir: Base temporary directory.
        chapters: Optional list of chapter dicts to write as JSON files.

    Returns:
        The project_path string.
    """
    project_path = os.path.join(tmp_dir, "test_novel")
    os.makedirs(project_path, exist_ok=True)

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
