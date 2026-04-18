"""Tests for Reviewer — 合并后的审稿 Agent（Phase 2-β）。

覆盖：
- CritiqueResult 无打分字段、severity 计数、writer_prompt 格式
- LLM 批评维度（happy / failure / empty / garbage / partial JSON / invalid severity）
- StyleProfile.detect_overuse 命中进 style_overuse_hits
- LedgerStore 一致性（伏笔未兑现/债务未兑现/角色死而复活/里程碑未达）
- Ledger / StyleProfile 为 None 优雅降级
- reviewer_node：写 state["current_chapter_quality"]、不触发 writer 回写
- Reviewer 无 score 字段、need_rewrite 只是信息标签
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from src.novel.agents.reviewer import Reviewer, reviewer_node
from src.novel.models.critique_result import (
    ConsistencyFlag,
    CritiqueIssue,
    CritiqueResult,
    Revision,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "mock"
    usage: dict | None = None


def _mock_llm(payload: dict | str | Exception | None = None):
    llm = MagicMock()
    if isinstance(payload, Exception):
        llm.chat.side_effect = payload
    else:
        if payload is None:
            payload = {
                "strengths": ["节奏不错"],
                "issues": [],
                "specific_revisions": [],
                "overall_assessment": "还行",
            }
        if isinstance(payload, dict):
            content = json.dumps(payload, ensure_ascii=False)
        else:
            content = str(payload)
        llm.chat.return_value = FakeLLMResponse(content=content)
    return llm


# ---------------------------------------------------------------------------
# CritiqueResult data model
# ---------------------------------------------------------------------------


class TestCritiqueResultModel:
    def test_default_empty(self):
        r = CritiqueResult()
        assert r.strengths == []
        assert r.issues == []
        assert r.specific_revisions == []
        assert r.high_severity_count == 0
        assert r.needs_refine is False
        assert r.need_rewrite is False
        # CRITICAL: no score fields at all
        assert not hasattr(r, "scores")
        assert not hasattr(r, "quality_score")
        assert not hasattr(r, "retention_scores")

    def test_severity_counts(self):
        r = CritiqueResult(
            issues=[
                CritiqueIssue(type="pacing", severity="high", reason="x"),
                CritiqueIssue(type="dialogue", severity="medium", reason="y"),
                CritiqueIssue(type="logic", severity="medium", reason="z"),
            ]
        )
        assert r.high_severity_count == 1
        assert r.medium_severity_count == 2
        assert r.needs_refine is True

    def test_needs_refine_threshold(self):
        # 1 medium alone should NOT trigger
        r = CritiqueResult(
            issues=[CritiqueIssue(type="pacing", severity="medium", reason="x")]
        )
        assert r.needs_refine is False
        # 1 high triggers
        r = CritiqueResult(
            issues=[CritiqueIssue(type="pacing", severity="high", reason="x")]
        )
        assert r.needs_refine is True

    def test_writer_prompt_format(self):
        r = CritiqueResult(
            strengths=["开篇紧凑"],
            issues=[
                CritiqueIssue(
                    type="trope_overuse",
                    severity="high",
                    quote="黑眸一凝",
                    reason="禁用词重复",
                )
            ],
            specific_revisions=[
                Revision(target="他黑眸一凝", suggestion="他眯起眼，瞳孔骤缩")
            ],
            style_overuse_hits=["黑眸", "瞳孔骤缩"],
            consistency_flags=[
                ConsistencyFlag(
                    type="foreshadowing",
                    severity="medium",
                    detail="上章伏笔未兑现",
                    ref_chapter=3,
                )
            ],
        )
        prompt = r.to_writer_prompt()
        assert "编辑批注" in prompt
        assert "开篇紧凑" in prompt
        assert "黑眸一凝" in prompt
        assert "本书口头禅" in prompt
        assert "一致性提醒" in prompt
        assert "参考第3章" in prompt

    def test_writer_prompt_empty_when_clean(self):
        assert CritiqueResult(strengths=["都好"]).to_writer_prompt() == ""

    def test_quote_truncated(self):
        long = "字" * 500
        i = CritiqueIssue(type="pacing", severity="high", quote=long, reason="x")
        assert len(i.quote) <= 200


# ---------------------------------------------------------------------------
# Reviewer.review — LLM critique dimension
# ---------------------------------------------------------------------------


class TestReviewerLLMDimension:
    def test_happy_path(self):
        llm = _mock_llm(
            {
                "strengths": ["节奏紧凑"],
                "issues": [
                    {
                        "type": "trope_overuse",
                        "severity": "high",
                        "quote": "黑眸一凝",
                        "reason": "套路词重复",
                    }
                ],
                "specific_revisions": [
                    {"target": "黑眸一凝", "suggestion": "瞳孔骤缩"}
                ],
                "overall_assessment": "AI 套路词太多",
            }
        )
        r = Reviewer(llm).review(
            "林辰黑眸一凝。" * 5,
            chapter_number=10,
            chapter_title="测试章",
            chapter_goal="冲突收束",
        )
        assert r.chapter_number == 10
        assert "节奏紧凑" in r.strengths
        assert len(r.issues) == 1
        assert r.issues[0].severity == "high"
        assert r.need_rewrite is True

    def test_llm_failure_returns_empty_safely(self):
        llm = _mock_llm(RuntimeError("network down"))
        r = Reviewer(llm).review("正文", chapter_number=1)
        assert r.issues == []
        assert "LLM 调用失败" in r.raw_response
        # No auto-trigger anywhere — just a report
        assert r.need_rewrite is False

    def test_empty_llm_response(self):
        llm = _mock_llm("")
        r = Reviewer(llm).review("正文", chapter_number=1)
        assert r.issues == []

    def test_garbage_llm_response(self):
        llm = _mock_llm("this is not json at all")
        r = Reviewer(llm).review("正文", chapter_number=1)
        assert r.issues == []
        assert r.raw_response == "this is not json at all"

    def test_partial_json_extracts_what_it_can(self):
        llm = _mock_llm(
            'prefix text: {"strengths": ["开篇好"], "issues": []}'
        )
        r = Reviewer(llm).review("正文", chapter_number=1)
        assert "开篇好" in r.strengths

    def test_invalid_severity_drops_issue(self):
        llm = _mock_llm(
            {
                "issues": [
                    {"type": "pacing", "severity": "INVALID", "reason": "x"}
                ]
            }
        )
        r = Reviewer(llm).review("正文", chapter_number=1)
        # Invalid severity crashes validation for this issue → dropped (not entire result)
        assert all(i.severity in {"low", "medium", "high"} for i in r.issues)

    def test_uses_json_mode(self):
        llm = _mock_llm({"issues": []})
        Reviewer(llm).review("正文", chapter_number=1)
        # Validate json_mode=True was passed
        kwargs = llm.chat.call_args.kwargs
        assert kwargs.get("json_mode") is True

    def test_no_llm_passes_through(self):
        # llm=None → LLM dimension skipped; other dims still run
        r = Reviewer(llm=None).review("正文", chapter_number=1)
        assert r.issues == []
        assert "LLM 不可用" in r.raw_response

    def test_prior_critiques_injected_into_prompt(self):
        llm = _mock_llm({"issues": [], "strengths": []})
        prior = [
            CritiqueResult(
                issues=[CritiqueIssue(type="pacing", severity="high", reason="拖沓")]
            )
        ]
        Reviewer(llm).review("正文", chapter_number=5, prior_critiques=prior)
        user_msg = llm.chat.call_args[0][0][1]["content"]
        assert "先前批注" in user_msg
        assert "拖沓" in user_msg


# ---------------------------------------------------------------------------
# StyleProfile dimension
# ---------------------------------------------------------------------------


class _FakePhrase:
    def __init__(self, phrase: str, coverage: float = 0.5):
        self.phrase = phrase
        self.chapter_coverage = coverage


class _FakeProfile:
    def __init__(self, phrases: list[str]):
        self.overused_phrases = [_FakePhrase(p) for p in phrases]


class _FakeStyleService:
    def __init__(self, hits: list[str]):
        self._hits = hits

    def detect_overuse(self, text, profile, threshold=0.30):
        return list(self._hits)


class TestReviewerStyleDimension:
    def test_style_overuse_hits_populated(self):
        profile = _FakeProfile(["瞳孔骤缩", "黑眸"])
        svc = _FakeStyleService(["瞳孔骤缩", "黑眸"])
        llm = _mock_llm()
        # Force dense overuse issue by making text contain phrases twice each
        text = "他瞳孔骤缩。他瞳孔骤缩。他黑眸闪动。他黑眸闪动。"
        r = Reviewer(
            llm, style_profile=profile, style_profile_service=svc
        ).review(text, chapter_number=1)
        assert "瞳孔骤缩" in r.style_overuse_hits
        assert "黑眸" in r.style_overuse_hits
        # Dense hits get a synthesized style_overuse issue
        assert any(i.type == "style_overuse" for i in r.issues)

    def test_style_profile_none_degrades(self):
        llm = _mock_llm()
        r = Reviewer(llm, style_profile=None).review("正文", chapter_number=1)
        assert r.style_overuse_hits == []

    def test_style_service_exception_is_silent(self):
        class BadService:
            def detect_overuse(self, *a, **kw):
                raise RuntimeError("boom")

        r = Reviewer(
            _mock_llm(),
            style_profile=_FakeProfile(["x"]),
            style_profile_service=BadService(),
        ).review("正文", chapter_number=1)
        assert r.style_overuse_hits == []


# ---------------------------------------------------------------------------
# Ledger dimension
# ---------------------------------------------------------------------------


class _FakeLedger:
    def __init__(self, snapshot: dict, character_states: dict | None = None):
        self._snap = snapshot
        self._chars = character_states or {}

    def snapshot_for_chapter(self, chapter_number: int):
        return dict(self._snap)

    def get_character_state(self, name: str, chapter_number: int):
        return self._chars.get(name)


class TestReviewerLedgerDimension:
    def test_foreshadowing_not_paid_flagged(self):
        ledger = _FakeLedger(
            snapshot={
                "collectable_foreshadowings": [
                    {
                        "detail": "神秘符咒真身揭示",
                        "planted_chapter": 3,
                    }
                ],
                "pending_debts": [],
                "active_characters": [],
                "pending_milestones": [],
            }
        )
        r = Reviewer(_mock_llm(), ledger=ledger).review(
            "本章与符咒无关的内容", chapter_number=5
        )
        assert any(
            f.type == "foreshadowing" and f.ref_chapter == 3
            for f in r.consistency_flags
        )

    def test_debt_high_urgency_not_met_flagged(self):
        ledger = _FakeLedger(
            snapshot={
                "collectable_foreshadowings": [],
                "pending_debts": [
                    {
                        "description": "主角必须报仇雪恨",
                        "urgency_level": "urgent",
                        "source_chapter": 2,
                    }
                ],
                "active_characters": [],
                "pending_milestones": [],
            }
        )
        r = Reviewer(_mock_llm(), ledger=ledger).review(
            "主角在读书", chapter_number=5
        )
        flags = [f for f in r.consistency_flags if f.type == "debt"]
        assert flags
        assert flags[0].severity == "high"

    def test_low_urgency_debt_not_flagged(self):
        ledger = _FakeLedger(
            snapshot={
                "collectable_foreshadowings": [],
                "pending_debts": [
                    {
                        "description": "小事一桩",
                        "urgency_level": "low",
                        "source_chapter": 2,
                    }
                ],
                "active_characters": [],
                "pending_milestones": [],
            }
        )
        r = Reviewer(_mock_llm(), ledger=ledger).review(
            "无关正文", chapter_number=5
        )
        assert not any(f.type == "debt" for f in r.consistency_flags)

    def test_dead_character_appearing_flagged(self):
        ledger = _FakeLedger(
            snapshot={
                "collectable_foreshadowings": [],
                "pending_debts": [],
                "active_characters": [{"name": "张三"}],
                "pending_milestones": [],
            },
            character_states={"张三": {"health": "dead"}},
        )
        r = Reviewer(_mock_llm(), ledger=ledger).review(
            "张三走到街上", chapter_number=10, active_characters=["张三"]
        )
        flags = [f for f in r.consistency_flags if f.type == "character_state"]
        assert flags
        assert flags[0].severity == "high"

    def test_ledger_none_degrades(self):
        r = Reviewer(_mock_llm(), ledger=None).review("正文", chapter_number=1)
        assert r.consistency_flags == []

    def test_ledger_snapshot_exception_is_silent(self):
        class Broken:
            def snapshot_for_chapter(self, n):
                raise RuntimeError("db down")

        r = Reviewer(_mock_llm(), ledger=Broken()).review(
            "正文", chapter_number=1
        )
        assert r.consistency_flags == []

    def test_high_consistency_flag_adds_issue(self):
        ledger = _FakeLedger(
            snapshot={
                "collectable_foreshadowings": [],
                "pending_debts": [
                    {
                        "description": "主角必须报仇",
                        "urgency_level": "critical",
                        "source_chapter": 2,
                    }
                ],
                "active_characters": [],
                "pending_milestones": [],
            }
        )
        r = Reviewer(_mock_llm(), ledger=ledger).review(
            "无关正文", chapter_number=5
        )
        # consistency dimension high → synthesized into issues list
        assert any(i.type == "consistency" and i.severity == "high" for i in r.issues)
        assert r.need_rewrite is True


# ---------------------------------------------------------------------------
# reviewer_node (LangGraph integration)
# ---------------------------------------------------------------------------


class TestReviewerNode:
    def test_empty_text_returns_error(self):
        state = {"current_chapter_text": "", "current_chapter": 1, "config": {}}
        out = reviewer_node(state)
        assert "reviewer" in out["completed_nodes"]
        assert out.get("errors")

    def test_populates_current_chapter_quality(self, monkeypatch):
        # Provide a Reviewer that bypasses real LLM
        from src.novel.agents import reviewer as rv_mod

        fake_result = CritiqueResult(
            chapter_number=7,
            strengths=["优点1"],
            issues=[CritiqueIssue(type="pacing", severity="medium", reason="慢")],
        )

        class _StubReviewer:
            def __init__(self, *a, **kw):
                pass

            def review(self, *a, **kw):
                return fake_result

        monkeypatch.setattr(rv_mod, "Reviewer", _StubReviewer)
        # Also stub the LLM factory to avoid real calls
        monkeypatch.setattr(
            "src.llm.llm_client.create_llm_client", lambda _c: MagicMock()
        )

        state = {
            "current_chapter_text": "章节正文",
            "current_chapter": 7,
            "config": {"llm": {"provider": "mock"}},
        }
        out = reviewer_node(state)
        q = out["current_chapter_quality"]
        assert q["chapter_number"] == 7
        assert q["strengths"] == ["优点1"]
        assert q["issues"][0]["severity"] == "medium"
        # Back-compat shims for state_writeback._build_chapter_record
        assert q["scores"] == {}
        assert q["retention_scores"] == {}
        assert q["rule_check"]["passed"] is True
        assert "reviewer" in out["completed_nodes"]
        # Clears rewrite prompt so stale feedback doesn't leak to next chapter
        assert out["current_chapter_rewrite_prompt"] == ""

    def test_does_not_trigger_writer_rewrite(self, monkeypatch):
        """need_rewrite is informational only — no Writer invocation here."""
        from src.novel.agents import reviewer as rv_mod

        class _Stub:
            def __init__(self, *a, **kw):
                pass

            def review(self, *a, **kw):
                return CritiqueResult(
                    chapter_number=1,
                    need_rewrite=True,  # strongest possible signal
                    issues=[
                        CritiqueIssue(type="pacing", severity="high", reason="bad"),
                        CritiqueIssue(type="logic", severity="high", reason="bad"),
                    ],
                )

        monkeypatch.setattr(rv_mod, "Reviewer", _Stub)
        monkeypatch.setattr(
            "src.llm.llm_client.create_llm_client", lambda _c: MagicMock()
        )
        state = {
            "current_chapter_text": "正文",
            "current_chapter": 1,
            "config": {"llm": {}},
        }
        out = reviewer_node(state)
        # node does NOT include "writer" in completed_nodes
        assert "writer" not in out["completed_nodes"]
        # need_rewrite propagates as info label only
        assert out["current_chapter_quality"]["need_rewrite"] is True


# ---------------------------------------------------------------------------
# Regression: no scoring fields anywhere
# ---------------------------------------------------------------------------


def test_critique_result_has_no_score_fields():
    fields = set(CritiqueResult.model_fields.keys())
    forbidden = {
        "scores",
        "quality_score",
        "retention_scores",
        "plot_coherence",
        "writing_quality",
        "character_portrayal",
        "ai_flavor_score",
    }
    assert not (fields & forbidden)
