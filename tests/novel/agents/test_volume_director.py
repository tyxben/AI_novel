"""Tests for ``src.novel.agents.volume_director.VolumeDirector``.

Covers:
    * ``propose_volume_outline`` happy path + previous_settlement injection
    * ``propose_volume_outline`` LLM JSON fallback (invalid JSON → rule fallback)
    * ``settle_volume`` with LedgerStore mock + ledger=None 降级
    * ``plan_volume_breakdown`` for short / novel / webnovel length classes
    * ``VolumeOutlineProposal.accept`` writes to Volume correctly
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.novel.agents.volume_director import (
    VolumeDirector,
    VolumeOutlineProposal,
    VolumeSettlementReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake"
    usage: dict | None = None


def _llm_response(payload: dict) -> FakeLLMResponse:
    return FakeLLMResponse(content=json.dumps(payload, ensure_ascii=False))


def _make_novel_data(
    volume_number: int = 1,
    start_ch: int = 1,
    end_ch: int = 5,
    title: str = "第一卷",
    core_conflict: str = "初入江湖",
    resolution: str = "站稳脚跟",
) -> dict:
    """Construct a minimal novel dict for VolumeDirector tests."""
    vol_chapters = list(range(start_ch, end_ch + 1))
    return {
        "novel_id": "novel_test",
        "title": "测试小说",
        "genre": "玄幻",
        "theme": "少年成长",
        "target_words": 100000,
        "outline": {
            "template": "cyclic_upgrade",
            "main_storyline": {
                "protagonist": "林辰",
                "protagonist_goal": "修炼成仙",
                "core_conflict": "天赋不足",
                "character_arc": "弱->强",
                "stakes": "性命",
                "theme_statement": "坚持",
            },
            "acts": [],
            "volumes": [
                {
                    "volume_number": volume_number,
                    "title": title,
                    "core_conflict": core_conflict,
                    "resolution": resolution,
                    "chapters": vol_chapters,
                }
            ],
            "chapters": [],
        },
        "chapters": [],
        "characters": [{"name": "林辰", "role": "主角"}],
        "world_setting": {"era": "古代", "location": "青云山"},
    }


def _make_full_propose_payload(start_ch: int, end_ch: int) -> dict:
    """Full valid LLM payload for propose_volume_outline."""
    n = end_ch - start_ch + 1
    # simple dist summing to n
    setup = 1 if n >= 3 else 0
    climax = 1 if n >= 3 else 0
    resolution = 1 if n >= 4 else 0
    buildup = n - setup - climax - resolution
    interlude = 0
    chapters = []
    for i in range(start_ch, end_ch + 1):
        if i == start_ch:
            ctype = "setup"
        elif i == end_ch - 1 and resolution:
            ctype = "climax"
        elif i == end_ch and resolution:
            ctype = "resolution"
        else:
            ctype = "buildup"
        chapters.append({
            "chapter_number": i,
            "title": f"第{i}章标题",
            "goal": f"目标{i}",
            "key_events": [f"事件{i}"],
            "involved_characters": ["林辰"],
            "plot_threads": [],
            "estimated_words": 2500,
            "chapter_type": ctype,
            "mood": "蓄力",
            "storyline_progress": f"推进主线{i}",
            "chapter_summary": f"第{i}章摘要",
            "chapter_brief": {
                "main_conflict": f"冲突{i}",
                "payoff": f"爽点{i}",
                "character_arc_step": "成长",
                "foreshadowing_plant": [],
                "foreshadowing_collect": [],
                "end_hook_type": "悬疑",
            },
        })
    return {
        "volume_goal": "主角开启修炼之路",
        "chapter_type_dist": {
            "setup": setup,
            "buildup": buildup,
            "climax": climax,
            "resolution": resolution,
            "interlude": interlude,
        },
        "foreshadowing_plan": {
            "to_plant": [
                {
                    "description": "神秘玉佩",
                    "planted_chapter": start_ch,
                    "target_chapter": end_ch,
                }
            ],
            "to_collect_from_previous": [],
        },
        "chapters": chapters,
    }


# ---------------------------------------------------------------------------
# propose_volume_outline
# ---------------------------------------------------------------------------


class TestProposeVolumeOutline:
    def test_happy_path_returns_proposal(self):
        mock_llm = MagicMock()
        payload = _make_full_propose_payload(1, 5)
        mock_llm.chat.return_value = _llm_response(payload)

        director = VolumeDirector(llm=mock_llm, workspace="/tmp/test")
        novel = _make_novel_data(start_ch=1, end_ch=5)

        proposal = director.propose_volume_outline(
            novel=novel, volume_number=1, previous_settlement=None
        )

        assert isinstance(proposal, VolumeOutlineProposal)
        assert proposal.volume_number == 1
        assert proposal.volume_goal == "主角开启修炼之路"
        assert proposal.chapter_numbers == [1, 2, 3, 4, 5]
        assert len(proposal.chapter_outlines) == 5
        assert sum(proposal.chapter_type_dist.values()) == 5
        assert len(proposal.foreshadowing_plan["to_plant"]) == 1
        # chapter dicts should carry chapter_type
        ct_values = {
            c.get("chapter_type") for c in proposal.chapter_outlines
        }
        assert ct_values <= {
            "setup", "buildup", "climax", "resolution", "interlude"
        }

    def test_empty_previous_settlement_branch(self):
        mock_llm = MagicMock()
        payload = _make_full_propose_payload(1, 3)
        mock_llm.chat.return_value = _llm_response(payload)

        director = VolumeDirector(llm=mock_llm)
        novel = _make_novel_data(start_ch=1, end_ch=3)

        proposal = director.propose_volume_outline(
            novel=novel, volume_number=1, previous_settlement=None
        )
        # Prompt must not mention previous volume settlement
        call_args = mock_llm.chat.call_args
        user_prompt = call_args.kwargs["messages"][1]["content"]
        assert "首卷或无上卷信息" in user_prompt
        assert proposal.volume_number == 1

    def test_with_previous_settlement_injects_context(self):
        mock_llm = MagicMock()
        payload = _make_full_propose_payload(6, 10)
        mock_llm.chat.return_value = _llm_response(payload)

        director = VolumeDirector(llm=mock_llm)
        novel = _make_novel_data(
            volume_number=2, start_ch=6, end_ch=10, title="第二卷"
        )
        prev = {
            "unfulfilled_foreshadowings": [
                {"description": "师父留下的谜团"},
            ],
            "pending_debts": [
                {"description": "报仇"},
            ],
            "next_volume_hook": "神秘势力登场",
        }

        proposal = director.propose_volume_outline(
            novel=novel, volume_number=2, previous_settlement=prev
        )

        user_prompt = mock_llm.chat.call_args.kwargs["messages"][1]["content"]
        assert "师父留下的谜团" in user_prompt
        assert "报仇" in user_prompt
        assert "神秘势力登场" in user_prompt
        assert proposal.chapter_numbers == [6, 7, 8, 9, 10]

    def test_invalid_volume_raises(self):
        mock_llm = MagicMock()
        director = VolumeDirector(llm=mock_llm)
        novel = _make_novel_data(volume_number=1, start_ch=1, end_ch=5)

        with pytest.raises(ValueError, match="不存在"):
            director.propose_volume_outline(novel=novel, volume_number=99)

    def test_llm_returns_garbage_falls_back_to_rule(self):
        mock_llm = MagicMock()
        # All retries return non-JSON garbage
        mock_llm.chat.return_value = FakeLLMResponse(content="not json at all")

        director = VolumeDirector(llm=mock_llm)
        novel = _make_novel_data(start_ch=1, end_ch=4)

        proposal = director.propose_volume_outline(novel=novel, volume_number=1)

        # Rule fallback: still returns valid proposal with all chapters
        assert proposal.volume_number == 1
        assert proposal.chapter_numbers == [1, 2, 3, 4]
        assert len(proposal.chapter_outlines) == 4
        assert sum(proposal.chapter_type_dist.values()) == 4
        # Raw LLM data should be None in fallback
        assert proposal.raw_llm_data is None

    def test_llm_exception_falls_back(self):
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("network down")

        director = VolumeDirector(llm=mock_llm)
        novel = _make_novel_data(start_ch=1, end_ch=3)

        proposal = director.propose_volume_outline(novel=novel, volume_number=1)
        assert proposal.chapter_numbers == [1, 2, 3]

    def test_partial_chapters_filled_in(self):
        """LLM returns only some chapters; missing ones should be filled."""
        mock_llm = MagicMock()
        partial = _make_full_propose_payload(1, 5)
        # Remove two chapters
        partial["chapters"] = partial["chapters"][:3]
        mock_llm.chat.return_value = _llm_response(partial)

        director = VolumeDirector(llm=mock_llm)
        novel = _make_novel_data(start_ch=1, end_ch=5)

        proposal = director.propose_volume_outline(novel=novel, volume_number=1)
        assert len(proposal.chapter_outlines) == 5
        nums = [c["chapter_number"] for c in proposal.chapter_outlines]
        assert nums == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# Proposal.accept
# ---------------------------------------------------------------------------


class TestProposalAccept:
    def test_accept_writes_volume_fields(self):
        from src.novel.models.novel import Volume

        proposal = VolumeOutlineProposal(
            volume_number=1,
            title="第一卷",
            volume_goal="主角修炼",
            chapter_numbers=[1, 2, 3, 4, 5],
            chapter_outlines=[],
            chapter_type_dist={
                "setup": 1, "buildup": 3, "climax": 1,
                "resolution": 0, "interlude": 0,
            },
            foreshadowing_plan={"to_plant": [], "to_collect_from_previous": []},
        )
        # Volume.title has min_length=1; use an initial title that accept()
        # must NOT overwrite (only fills when empty).
        vol = Volume(volume_number=1, title="占位名")
        out = proposal.accept(vol)

        assert out is vol
        assert vol.volume_goal == "主角修炼"
        assert vol.volume_outline == [1, 2, 3, 4, 5]
        assert vol.chapters == [1, 2, 3, 4, 5]
        assert vol.chapter_type_dist == {
            "setup": 1, "buildup": 3, "climax": 1,
            "resolution": 0, "interlude": 0,
        }
        # Existing non-empty title is preserved (accept only fills empty)
        assert vol.title == "占位名"
        assert vol.status == "writing"

    def test_accept_number_mismatch_raises(self):
        from src.novel.models.novel import Volume

        proposal = VolumeOutlineProposal(
            volume_number=1,
            title="",
            volume_goal="",
            chapter_numbers=[1],
            chapter_outlines=[],
        )
        vol = Volume(volume_number=2, title="x")
        with pytest.raises(ValueError, match="mismatch"):
            proposal.accept(vol)


# ---------------------------------------------------------------------------
# settle_volume
# ---------------------------------------------------------------------------


class TestSettleVolume:
    def test_settle_with_ledger_aggregates_foreshadowings(self):
        mock_llm = MagicMock()
        director = VolumeDirector(llm=mock_llm)

        novel = _make_novel_data(start_ch=1, end_ch=5)
        # Simulate some written chapters
        novel["chapters"] = [
            {"chapter_number": i, "title": f"第{i}章", "chapter_brief": {}}
            for i in range(1, 6)
        ]

        ledger = MagicMock()
        ledger.snapshot_for_chapter.return_value = {
            "pending_debts": [{"description": "复仇债务", "debt_id": "d1"}],
            "plantable_foreshadowings": [],
            "collectable_foreshadowings": [],
            "active_characters": [],
            "world_facts": [],
            "pending_milestones": [],
        }
        ledger.list_foreshadowings.return_value = [
            {
                "foreshadowing_id": "f1",
                "description": "神秘玉佩",
                "status": "collected",
                "planted_chapter": 1,
                "target_chapter": 3,
            },
            {
                "foreshadowing_id": "f2",
                "description": "师父隐秘",
                "status": "pending",
                "planted_chapter": 2,
                "target_chapter": 5,
            },
            {
                "foreshadowing_id": "f3",
                "description": "下卷钩子",
                "status": "pending",
                "planted_chapter": 4,
                "target_chapter": 20,  # long-tail, not unfulfilled
            },
        ]

        report = director.settle_volume(
            novel=novel, volume_number=1, ledger=ledger
        )

        assert isinstance(report, VolumeSettlementReport)
        assert report.volume_number == 1
        assert report.chapter_count == 5
        assert len(report.fulfilled_foreshadowings) == 1
        assert len(report.unfulfilled_foreshadowings) == 1
        assert report.foreshadowing_recovery_rate == 0.5
        assert len(report.pending_debts) == 1
        # next_volume_hook should prefer first unfulfilled description
        assert report.next_volume_hook == "师父隐秘"

    def test_settle_without_ledger_degrades(self):
        mock_llm = MagicMock()
        director = VolumeDirector(llm=mock_llm)

        novel = _make_novel_data(start_ch=1, end_ch=3)
        novel["chapters"] = [
            {
                "chapter_number": 1,
                "title": "第1章",
                "chapter_brief": {"foreshadowing_collect": ["玉佩秘密"]},
            },
            {
                "chapter_number": 2,
                "title": "第2章",
                "chapter_brief": {},
            },
            {
                "chapter_number": 3,
                "title": "第3章",
                "chapter_brief": {"foreshadowing_collect": []},
            },
        ]

        report = director.settle_volume(
            novel=novel, volume_number=1, ledger=None
        )

        assert report.chapter_count == 3
        assert len(report.fulfilled_foreshadowings) == 1
        assert report.fulfilled_foreshadowings[0]["description"] == "玉佩秘密"
        assert report.unfulfilled_foreshadowings == []
        # recovery_rate is fulfilled/(fulfilled+unfulfilled)
        assert report.foreshadowing_recovery_rate == 1.0
        # degraded note present
        assert any("降级" in n for n in report.notes)
        # next_hook falls back to resolution field
        assert report.next_volume_hook == "站稳脚跟"

    def test_settle_missing_volume_returns_empty_report(self):
        mock_llm = MagicMock()
        director = VolumeDirector(llm=mock_llm)
        novel = _make_novel_data(start_ch=1, end_ch=3)

        report = director.settle_volume(
            novel=novel, volume_number=99, ledger=None
        )
        assert report.volume_number == 99
        assert report.chapter_count == 0
        assert any("不存在" in n for n in report.notes)

    def test_settle_ledger_snapshot_exception_tolerated(self):
        mock_llm = MagicMock()
        director = VolumeDirector(llm=mock_llm)
        novel = _make_novel_data(start_ch=1, end_ch=2)

        ledger = MagicMock()
        ledger.snapshot_for_chapter.side_effect = RuntimeError("db down")
        ledger.list_foreshadowings.return_value = []

        report = director.settle_volume(
            novel=novel, volume_number=1, ledger=ledger
        )
        assert report.pending_debts == []
        assert any("snapshot_for_chapter 失败" in n for n in report.notes)


# ---------------------------------------------------------------------------
# plan_volume_breakdown
# ---------------------------------------------------------------------------


class TestPlanVolumeBreakdown:
    def test_short_length_class(self):
        director = VolumeDirector(llm=MagicMock())
        novel = {"genre": "悬疑", "target_words": 25000}

        breakdown = director.plan_volume_breakdown(
            novel=novel, target_length_class="short"
        )
        assert len(breakdown) >= 1
        total = sum(v["chapters_count"] for v in breakdown)
        assert total >= 10  # short hint minimum

    def test_novel_length_class(self):
        director = VolumeDirector(llm=MagicMock())
        novel = {"genre": "都市", "target_words": 100000}

        breakdown = director.plan_volume_breakdown(
            novel=novel, target_length_class="novel"
        )
        # 100k words / 2500 = 40 chapters, per_vol=30 (都市) → 2 volumes
        assert len(breakdown) >= 1
        assert breakdown[0]["start_chapter"] == 1
        # chapters are contiguous across volumes
        for i in range(1, len(breakdown)):
            assert breakdown[i]["start_chapter"] == breakdown[i - 1]["end_chapter"] + 1

    def test_webnovel_length_class_produces_multiple_volumes(self):
        director = VolumeDirector(llm=MagicMock())
        novel = {"genre": "玄幻", "target_words": 1_000_000}

        breakdown = director.plan_volume_breakdown(
            novel=novel, target_length_class="webnovel"
        )
        # 1M words / 2500 = 400 chapters, 玄幻 per_vol=35 → 11-12 volumes
        assert len(breakdown) >= 5
        assert breakdown[-1]["end_chapter"] >= 300

    def test_unknown_length_class_falls_back_to_novel(self):
        director = VolumeDirector(llm=MagicMock())
        novel = {"genre": "都市", "target_words": 100000}

        a = director.plan_volume_breakdown(
            novel=novel, target_length_class="bogus"
        )
        b = director.plan_volume_breakdown(
            novel=novel, target_length_class="novel"
        )
        assert a == b

    def test_unknown_genre_uses_length_hint_per_vol(self):
        director = VolumeDirector(llm=MagicMock())
        novel = {"genre": "奇异题材", "target_words": 60000}
        breakdown = director.plan_volume_breakdown(
            novel=novel, target_length_class="novel"
        )
        assert breakdown  # non-empty
        assert breakdown[0]["volume_number"] == 1
