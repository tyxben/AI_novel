"""BriefAssembler tests — Phase 2-δ renamed successor of ContinuityService.

BriefAssembler keeps the legacy ``generate_brief`` / ``format_for_prompt``
surface working (inherited) and adds a Ledger-first
``assemble_for_chapter`` method.  The legacy surface is already covered
by :mod:`tests.novel.services.test_continuity_service` so we only add
coverage for the new method here.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# assemble_for_chapter
# ---------------------------------------------------------------------------


def _make_snapshot(**overrides):
    base = {
        "pending_debts": [
            {"description": "应救师妹", "urgency_level": "high"},
            {"description": "归还令牌"},
            {"description": ""},  # empty description should be filtered
        ],
        "collectable_foreshadowings": [
            {"content": "神秘令牌", "planted_chapter": 5},
            {"content": "", "planted_chapter": 6},  # empty filtered
        ],
        "plantable_foreshadowings": [],
        "active_characters": [
            {"name": "主角"},
            {"name": "师妹"},
            {},  # nameless filtered
        ],
        "world_facts": [
            {"name": "归墟阵"},
            {"term": "玄铁"},
            {"canonical_name": "苍云剑"},
            {},  # filtered
        ],
        "pending_milestones": [{"description": "抵达归墟"}],
    }
    base.update(overrides)
    return base


def test_assemble_happy_path():
    from src.novel.services.brief_assembler import BriefAssembler

    ledger = MagicMock()
    ledger.snapshot_for_chapter.return_value = _make_snapshot()

    assembler = BriefAssembler(ledger=ledger)
    ctx = assembler.assemble_for_chapter(
        novel={"characters": [{"name": "主角"}]},
        volume_number=1,
        chapter_number=10,
    )

    assert ctx["must_fulfill_debts"] == ["应救师妹", "归还令牌"]
    assert ctx["must_collect_foreshadowings"] == ["神秘令牌"]
    assert ctx["active_characters"] == ["主角", "师妹"]
    assert set(ctx["world_facts_to_respect"]) == {"归墟阵", "玄铁", "苍云剑"}
    assert ctx["pending_milestones"] == ["抵达归墟"]
    assert ctx["warnings"] == []
    ledger.snapshot_for_chapter.assert_called_once_with(10)


def test_assemble_no_ledger_falls_back_to_novel_chars():
    from src.novel.services.brief_assembler import BriefAssembler

    assembler = BriefAssembler(ledger=None)
    novel = {"characters": [{"name": "主角"}, {"name": "配角"}]}
    ctx = assembler.assemble_for_chapter(novel, 1, 1)

    assert ctx["active_characters"] == ["主角", "配角"]
    assert ctx["must_fulfill_debts"] == []
    assert ctx["must_collect_foreshadowings"] == []
    assert any("ledger_unavailable" in w for w in ctx["warnings"])


def test_assemble_ledger_error_warns_but_returns():
    from src.novel.services.brief_assembler import BriefAssembler

    ledger = MagicMock()
    ledger.snapshot_for_chapter.side_effect = RuntimeError("db dead")

    assembler = BriefAssembler(ledger=ledger)
    ctx = assembler.assemble_for_chapter(
        novel={"characters": [{"name": "主角"}]},
        volume_number=1,
        chapter_number=5,
    )

    assert ctx["must_fulfill_debts"] == []
    assert ctx["active_characters"] == ["主角"]
    assert any(w.startswith("ledger_error") for w in ctx["warnings"])


def test_assemble_empty_snapshot():
    """Ledger returns empty lists → every field empty, no crash."""
    from src.novel.services.brief_assembler import BriefAssembler

    ledger = MagicMock()
    ledger.snapshot_for_chapter.return_value = {
        "pending_debts": [],
        "collectable_foreshadowings": [],
        "plantable_foreshadowings": [],
        "active_characters": [],
        "world_facts": [],
        "pending_milestones": [],
    }

    assembler = BriefAssembler(ledger=ledger)
    ctx = assembler.assemble_for_chapter(None, 1, 1)

    assert ctx["must_fulfill_debts"] == []
    assert ctx["must_collect_foreshadowings"] == []
    assert ctx["active_characters"] == []
    assert ctx["pending_milestones"] == []


def test_assemble_active_character_fallback_when_ledger_empty_but_novel_present():
    from src.novel.services.brief_assembler import BriefAssembler

    ledger = MagicMock()
    snap = _make_snapshot(active_characters=[])
    ledger.snapshot_for_chapter.return_value = snap

    assembler = BriefAssembler(ledger=ledger)
    ctx = assembler.assemble_for_chapter(
        novel={"characters": [{"name": "fallback_hero"}]},
        volume_number=1,
        chapter_number=1,
    )
    # Falls back to novel-roster when ledger gave none
    assert ctx["active_characters"] == ["fallback_hero"]


def test_continuity_service_still_importable_as_alias():
    """BriefAssembler inherits from ContinuityService; the old import path
    continues to work for callers that have not migrated yet."""
    from src.novel.services.brief_assembler import BriefAssembler
    from src.novel.services.continuity_service import ContinuityService

    assert issubclass(BriefAssembler, ContinuityService)

    # ``generate_brief`` is inherited and usable without ledger
    a = BriefAssembler()
    brief = a.generate_brief(chapter_number=2)
    assert brief["chapter_number"] == 2


def test_novel_model_active_characters():
    """Fallback extraction works for pydantic-like objects with ``.characters``."""
    from src.novel.services.brief_assembler import BriefAssembler

    class FakeChar:
        def __init__(self, name: str):
            self.name = name

    class FakeNovel:
        characters = [FakeChar("A"), FakeChar("B")]

    assembler = BriefAssembler(ledger=None)
    ctx = assembler.assemble_for_chapter(FakeNovel(), 1, 1)
    assert ctx["active_characters"] == ["A", "B"]
