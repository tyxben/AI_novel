"""Tests for SelfRefineLoop — Phase 0 档 4b 单轮审阅语义。

历史：本模块曾跑 draft → verify × N → critic × N 自动重写循环；
档 4b 改为**单次**产 RefineReport，不调 rewrite_fn、不改章节正文。

这些测试覆盖新语义：
- 单次 sanitize / verify / critic
- 返回 RefineReport（verifier_findings / critic_findings / recommended_action）
- rewrite_fn 即便传入也不被调用
- 章节原文不被修改
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.chapter_critic import ChapterCritic, CritiqueResult, Issue
from src.novel.models.refine_report import RefineReport
from src.novel.services.chapter_verifier import ChapterVerifier
from src.novel.services.refine_loop import (
    RefineConfig,
    RefineTrace,
    run_refine_loop,
)


def _llm(payload):
    """LLM mock that returns a fixed payload (dict → json or str)."""
    m = MagicMock()
    if isinstance(payload, dict):
        m.chat.return_value = LLMResponse(
            content=json.dumps(payload, ensure_ascii=False),
            model="mock",
            usage=None,
        )
    else:
        m.chat.return_value = LLMResponse(
            content=str(payload), model="mock", usage=None
        )
    return m


# ---------------------------------------------------------------------------
# Single-pass happy path
# ---------------------------------------------------------------------------


def test_clean_draft_returns_accept_report():
    """干净初稿 → verify pass + critic pass → recommended_action=accept。"""
    text = "林辰睁眼，看见的是熟悉的木顶。" * 10

    draft_fn = MagicMock(return_value=text)
    rewrite_fn = MagicMock()  # must NOT be invoked under new semantics
    verifier = ChapterVerifier()
    critic = ChapterCritic(_llm({"strengths": ["清爽"], "issues": []}))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=verifier,
        critic=critic,
        banned_phrases=["黑眸"],
        chapter_number=1,
    )

    assert isinstance(trace, RefineTrace)
    assert trace.verify_passed
    assert trace.critic_passed
    assert rewrite_fn.call_count == 0  # 单轮语义：永不调用
    assert trace.final_text == text  # 未被修改
    assert trace.report is not None
    assert isinstance(trace.report, RefineReport)
    assert trace.report.chapter_number == 1
    assert trace.report.recommended_action == "accept"
    assert trace.report.verifier_findings == []
    assert trace.report.critic_findings == []


def test_verify_failure_reports_needs_rewrite_without_rewriting():
    """硬约束失败 → recommended_action=needs_rewrite，但 rewrite_fn 不会被调用，正文不变。"""
    bad = "林辰黑眸一凝，再次黑眸冷下来。"  # 2x 禁词

    draft_fn = MagicMock(return_value=bad)
    rewrite_fn = MagicMock(return_value="不应被使用的新文本")
    critic = ChapterCritic(_llm({"strengths": [], "issues": []}))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=ChapterVerifier(),
        critic=critic,
        banned_phrases=["黑眸"],
    )

    assert rewrite_fn.call_count == 0
    assert not trace.verify_passed
    assert trace.final_text == bad  # 没被重写
    # 单轮：verify_attempts 只有 1 条
    assert len(trace.verify_attempts) == 1
    assert trace.report is not None
    assert trace.report.recommended_action == "needs_rewrite"
    assert any(
        f["rule"] == "banned_phrase" for f in trace.report.verifier_findings
    )


def test_rewrite_fn_none_is_allowed():
    """rewrite_fn 不传也能正常跑 — 它是遗留参数。"""
    draft_fn = MagicMock(return_value="林辰睁眼。" * 50)
    critic = ChapterCritic(_llm({"strengths": [], "issues": []}))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        verifier=ChapterVerifier(),
        critic=critic,
    )
    assert trace.report is not None
    assert trace.verify_passed
    assert trace.critic_passed


# ---------------------------------------------------------------------------
# Critic single-pass
# ---------------------------------------------------------------------------


def test_critic_high_severity_reports_suggest_refine():
    """verify pass 但 critic 标 high severity → recommended_action=suggest_refine。"""
    draft_fn = MagicMock(return_value="林辰睁眼，木顶映入视野。" * 40)
    rewrite_fn = MagicMock()

    critic_payload = {
        "strengths": ["开篇明确"],
        "issues": [
            {"type": "pacing", "severity": "high", "reason": "过短"},
        ],
        "specific_revisions": [
            {"target": "林辰睁眼", "suggestion": "加点环境细节"},
        ],
        "overall_assessment": "开头偏干",
    }
    critic = ChapterCritic(_llm(critic_payload))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=ChapterVerifier(),
        critic=critic,
    )

    # 单轮：critique_attempts 只有 1 条，rewrite_fn 不被调用
    assert rewrite_fn.call_count == 0
    assert len(trace.critique_attempts) == 1
    assert trace.verify_passed
    assert not trace.critic_passed
    assert trace.report is not None
    assert trace.report.recommended_action == "suggest_refine"
    assert len(trace.report.critic_findings) == 1
    assert trace.report.critic_findings[0]["severity"] == "high"
    assert trace.report.overall_assessment == "开头偏干"


def test_critic_disabled_via_config():
    """enable_critic=False → critic 不被调用，默认 accept。"""
    draft_fn = MagicMock(return_value="林辰睁眼。" * 50)
    rewrite_fn = MagicMock()
    critic = MagicMock()

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=ChapterVerifier(),
        critic=critic,
        config=RefineConfig(enable_critic=False),
    )
    assert critic.critique.call_count == 0
    assert trace.critic_passed  # disabled → treated as pass
    assert trace.report is not None
    assert trace.report.recommended_action == "accept"


def test_critic_none_is_skipped():
    draft_fn = MagicMock(return_value="林辰睁眼。" * 50)
    trace = run_refine_loop(
        draft_fn=draft_fn,
        verifier=ChapterVerifier(),
        critic=None,
    )
    assert trace.critic_passed
    assert trace.report is not None
    assert trace.report.critic_findings == []


def test_critic_exception_treated_as_pass():
    """critic 自身抛异常 → 按通过处理，不推荐重写。"""
    draft_fn = MagicMock(return_value="林辰睁眼。" * 50)

    critic = MagicMock()
    critic.critique.side_effect = RuntimeError("LLM down")

    trace = run_refine_loop(
        draft_fn=draft_fn,
        verifier=ChapterVerifier(),
        critic=critic,
    )
    assert trace.critic_passed  # exception → not blocking
    assert any("critic failed" in n for n in trace.notes)
    assert trace.report is not None
    assert trace.report.recommended_action == "accept"


# ---------------------------------------------------------------------------
# Sanitize still runs exactly once
# ---------------------------------------------------------------------------


def test_sanitize_strips_markdown_once():
    draft = "# 第10章 标题\n\n林辰睁眼。" + "正文。" * 50
    draft_fn = MagicMock(return_value=draft)
    critic = ChapterCritic(_llm({"issues": []}))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        verifier=ChapterVerifier(),
        critic=critic,
    )
    assert "# 第10章" not in trace.final_text
    assert "strip_markdown_chapter_head" in trace.sanitize_actions
    assert trace.report is not None
    assert trace.report.sanitized is True


def test_opening_duplicate_flag_surfaces_in_report():
    """首句和上章高度相似 → trace 打标记；不再因此触发 rewrite。"""
    prev = "晨光刺破西岭的雾气，照在辰风村简陋的木栅栏上。" + "前章正文。" * 30
    draft = "晨光刺破西岭的雾气，照在辰风村简陋的木栅栏上。" + "继续写。" * 30

    draft_fn = MagicMock(return_value=draft)
    critic = ChapterCritic(_llm({"issues": []}))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        verifier=ChapterVerifier(),
        critic=critic,
        prev_chapter_text=prev,
    )
    assert trace.opening_duplicate_flagged
    # 单轮语义下无"rewrite 收到 opening 反馈"概念，只剩 trace 标记


# ---------------------------------------------------------------------------
# Verify + critic call counts are exactly 1
# ---------------------------------------------------------------------------


def test_each_stage_runs_exactly_once():
    """单轮语义核心断言：sanitize / verify / critic 每个阶段最多调 1 次。"""
    draft_fn = MagicMock(return_value="林辰睁眼。" * 50)

    verifier = MagicMock()
    verifier.verify.return_value = MagicMock(
        passed=True, failures=[], word_count=200, high_severity_count=0
    )

    critic = MagicMock()
    critic.critique.return_value = CritiqueResult(issues=[])

    trace = run_refine_loop(
        draft_fn=draft_fn,
        verifier=verifier,
        critic=critic,
    )

    assert draft_fn.call_count == 1
    assert verifier.verify.call_count == 1
    assert critic.critique.call_count == 1
    assert len(trace.verify_attempts) == 1
    assert len(trace.critique_attempts) == 1


def test_total_llm_calls_counts_only_critic():
    """单轮语义下：verifier 零 LLM，critic 至多 1 次，total=critic_count。"""
    draft_fn = MagicMock(return_value="林辰睁眼。" * 50)

    # critic 返回 high severity（但仍只调一次）
    critic_payload = {
        "strengths": [],
        "issues": [{"type": "pacing", "severity": "high", "reason": "x"}],
        "specific_revisions": [{"target": "x", "suggestion": "y"}],
    }
    critic = ChapterCritic(_llm(critic_payload))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        verifier=ChapterVerifier(),
        critic=critic,
    )
    assert trace.total_llm_calls == 1
    assert len(trace.critique_attempts) == 1


def test_deprecated_iter_configs_have_no_effect():
    """max_verify_retries / max_refine_iters 被保留但失效——无论传什么都只跑 1 轮。"""
    draft_fn = MagicMock(return_value="林辰黑眸冷。")  # 禁词
    rewrite_fn = MagicMock(return_value="不会被用到")
    critic = ChapterCritic(_llm({"strengths": [], "issues": []}))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=ChapterVerifier(),
        critic=critic,
        banned_phrases=["黑眸"],
        config=RefineConfig(max_verify_retries=5, max_refine_iters=5),
    )
    assert rewrite_fn.call_count == 0
    assert len(trace.verify_attempts) == 1
    assert not trace.verify_passed


# ---------------------------------------------------------------------------
# RefineReport schema
# ---------------------------------------------------------------------------


def test_report_fields_serializable():
    """RefineReport 必须可 model_dump（供 agent_chat 返回给 LLM）。"""
    draft_fn = MagicMock(return_value="林辰黑眸冷。")
    critic = ChapterCritic(_llm({"issues": []}))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        verifier=ChapterVerifier(),
        critic=critic,
        banned_phrases=["黑眸"],
        chapter_number=7,
    )
    assert trace.report is not None
    d = trace.report.model_dump()
    assert d["chapter_number"] == 7
    assert "verifier_findings" in d
    assert "critic_findings" in d
    assert "recommended_action" in d
    assert d["recommended_action"] in ("accept", "suggest_refine", "needs_rewrite")
