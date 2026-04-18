"""Tests for SelfRefineLoop — 闭环编排。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.chapter_critic import (
    ChapterCritic,
    CritiqueResult,
    Issue,
    Revision,
)
from src.novel.services.chapter_verifier import ChapterVerifier
from src.novel.services.refine_loop import (
    RefineConfig,
    RefineTrace,
    run_refine_loop,
)


def _llm(payload):
    """LLM mock that returns a fixed payload (dict→json or str)."""
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
# Happy path: clean draft passes both verify and critic
# ---------------------------------------------------------------------------


def test_clean_draft_passes_immediately():
    """初稿就过 verify + critic，无重写无 refine。"""
    text = "林辰睁眼，看见的是熟悉的木顶。" * 10  # 短文，但无禁词

    draft_fn = MagicMock(return_value=text)
    rewrite_fn = MagicMock()  # should NOT be called
    verifier = ChapterVerifier()
    critic = ChapterCritic(_llm({"strengths": ["清爽"], "issues": []}))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=verifier,
        critic=critic,
        banned_phrases=["黑眸"],
    )

    assert trace.verify_passed
    assert trace.critic_passed
    assert trace.refine_iterations == 0
    assert rewrite_fn.call_count == 0
    # text 应基本保留（可能被 sanitize 改一点）
    assert "林辰睁眼" in trace.final_text


# ---------------------------------------------------------------------------
# Verify retry: rewrite is invoked when verifier fails
# ---------------------------------------------------------------------------


def test_verify_failure_triggers_rewrite():
    """初稿有禁词触发 verify 失败，rewrite_fn 被调用，新稿干净 → pass。"""
    bad = "林辰黑眸一凝，再次黑眸冷下来。"  # 2x 禁词
    good = "林辰眯起眼睛，瞳孔骤然收紧。"

    draft_fn = MagicMock(return_value=bad)
    rewrite_fn = MagicMock(return_value=good)
    verifier = ChapterVerifier()
    critic = ChapterCritic(_llm({"strengths": ["简洁"], "issues": []}))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=verifier,
        critic=critic,
        banned_phrases=["黑眸"],
    )

    assert rewrite_fn.call_count == 1
    assert trace.verify_passed
    # 第一次 attempt failed, 第二次 passed
    assert len(trace.verify_attempts) == 2
    assert not trace.verify_attempts[0].passed
    assert trace.verify_attempts[1].passed
    assert trace.final_text == good


def test_verify_exhausts_retries_returns_best_effort():
    """rewrite 持续失败也不抛异常，返回最后一稿。"""
    draft_fn = MagicMock(return_value="林辰黑眸冷冷。")
    rewrite_fn = MagicMock(return_value="林辰黑眸更冷。")  # 仍含禁词
    verifier = ChapterVerifier()
    critic = ChapterCritic(_llm({"strengths": [], "issues": []}))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=verifier,
        critic=critic,
        banned_phrases=["黑眸"],
        config=RefineConfig(max_verify_retries=2),
    )

    assert not trace.verify_passed
    # 1 initial + 2 rewrites = 3 verify attempts
    assert len(trace.verify_attempts) == 3
    assert rewrite_fn.call_count == 2


def test_rewrite_fn_exception_is_caught():
    """rewrite_fn 抛异常不会 crash，会带着原稿退出。"""
    draft_fn = MagicMock(return_value="林辰黑眸冷。")
    rewrite_fn = MagicMock(side_effect=RuntimeError("LLM down"))
    verifier = ChapterVerifier()
    critic = ChapterCritic(_llm({"issues": []}))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=verifier,
        critic=critic,
        banned_phrases=["黑眸"],
    )

    assert not trace.verify_passed
    assert "rewrite_fn failed" in " ".join(trace.notes)


# ---------------------------------------------------------------------------
# Critic loop: refine when high-severity issues exist
# ---------------------------------------------------------------------------


def test_critic_triggers_refine_on_high_severity():
    """初稿过 verify，但 critic 标 high → rewrite_fn 再被调用一次。"""
    draft_fn = MagicMock(return_value="林辰睁眼，木顶映入视野。")
    rewrite_fn = MagicMock(return_value="林辰睁眼，看见熟悉的木顶。新一段精修。")

    # critic 第一次返回 high severity，第二次清空
    critic_responses = [
        {
            "strengths": ["开篇明确"],
            "issues": [
                {"type": "pacing", "severity": "high", "reason": "过短"}
            ],
            "specific_revisions": [
                {"target": "林辰睁眼", "suggestion": "加点环境细节"}
            ],
        },
        {"strengths": ["改进了"], "issues": []},
    ]
    llm = MagicMock()
    llm.chat.side_effect = [
        LLMResponse(content=json.dumps(r, ensure_ascii=False), model="m", usage=None)
        for r in critic_responses
    ]
    critic = ChapterCritic(llm)

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=ChapterVerifier(),
        critic=critic,
        config=RefineConfig(max_refine_iters=2),
    )

    assert trace.verify_passed
    assert trace.critic_passed
    assert trace.refine_iterations == 1
    assert len(trace.critique_attempts) == 2
    assert rewrite_fn.call_count == 1


def test_critic_disabled_via_config():
    """enable_critic=False 时跳过 critic 阶段。"""
    draft_fn = MagicMock(return_value="林辰睁眼。")
    rewrite_fn = MagicMock()
    critic = MagicMock()  # 不应被调用

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=ChapterVerifier(),
        critic=critic,
        config=RefineConfig(enable_critic=False),
    )
    assert critic.critique.call_count == 0
    assert trace.critic_passed  # disabled = not failing


def test_critic_none_skipped():
    draft_fn = MagicMock(return_value="林辰睁眼。")
    rewrite_fn = MagicMock()
    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=ChapterVerifier(),
        critic=None,
    )
    assert trace.critic_passed


def test_critic_empty_feedback_breaks_loop():
    """critic needs_refine=True 但 to_writer_prompt 为空 → 跳出而不是死循环。"""
    draft_fn = MagicMock(return_value="林辰睁眼。")
    rewrite_fn = MagicMock()

    # 直接 mock critic.critique 返回一个 needs_refine=True 但空 feedback 的结果
    fake_critique = CritiqueResult(
        issues=[Issue(type="pacing", severity="high", reason="x")]
    )
    # to_writer_prompt 会包含 issues 段，所以会非空 — 这里我们用 strengths 也空、issues 有
    # 但 ChapterCritic.to_writer_prompt 在有 issues 时一定非空
    # 所以构造一个没有 issues 没有 revisions 但 needs_refine=True 的 — 不可能
    # 改测：rewrite_fn 抛异常确认跳出
    rewrite_fn = MagicMock(side_effect=RuntimeError("nope"))
    critic = MagicMock()
    critic.critique.return_value = fake_critique

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=ChapterVerifier(),
        critic=critic,
        config=RefineConfig(max_refine_iters=2),
    )
    # 应当跳出，不是死循环
    assert "rewrite_fn failed in critic stage" in " ".join(trace.notes)


# ---------------------------------------------------------------------------
# Sanitize integration
# ---------------------------------------------------------------------------


def test_sanitize_strips_markdown_from_draft():
    """初稿带 markdown 标题 → sanitize 删除，verify pass。"""
    draft = "# 第10章 标题\n\n林辰睁眼。" + "正文。" * 50
    draft_fn = MagicMock(return_value=draft)
    rewrite_fn = MagicMock()
    critic = ChapterCritic(_llm({"issues": []}))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=ChapterVerifier(),
        critic=critic,
    )
    assert "# 第10章" not in trace.final_text
    assert "strip_markdown_chapter_head" in trace.sanitize_actions


def test_opening_duplicate_flag_added_to_feedback():
    """首句重复 + verify 失败时，rewrite 收到的 feedback 含 opening 提示。"""
    prev = "晨光刺破西岭的雾气，照在辰风村简陋的木栅栏上。" + "前章正文。" * 30
    draft = "晨光刺破西岭的雾气，照在辰风村简陋的木栅栏上。" + "黑眸冷冷。" * 5

    draft_fn = MagicMock(return_value=draft)
    rewrite_fn = MagicMock(return_value="新开头：林辰大步走出营地。")
    critic = ChapterCritic(_llm({"issues": []}))

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=ChapterVerifier(),
        critic=critic,
        banned_phrases=["黑眸"],
        prev_chapter_text=prev,
    )

    assert trace.opening_duplicate_flagged
    # rewrite_fn 的 feedback 参数应含 opening 提示
    rewrite_call_args = rewrite_fn.call_args[0]
    assert len(rewrite_call_args) == 2
    feedback = rewrite_call_args[1]
    assert "opening" in feedback or "首句" in feedback


# ---------------------------------------------------------------------------
# Trace consistency
# ---------------------------------------------------------------------------


def test_total_llm_calls_count():
    """轨迹的 total_llm_calls 反映 draft/rewrite/critic/refine 总次数。"""
    draft_fn = MagicMock(return_value="林辰黑眸冷。")  # bad
    rewrite_fn = MagicMock(return_value="林辰眯眼。")  # good
    critic_responses = [
        {"strengths": [], "issues": [{"type": "pacing", "severity": "high", "reason": "x"}],
         "specific_revisions": [{"target": "x", "suggestion": "y"}]},
        {"strengths": ["改进"], "issues": []},
    ]
    llm = MagicMock()
    llm.chat.side_effect = [
        LLMResponse(content=json.dumps(r, ensure_ascii=False), model="m", usage=None)
        for r in critic_responses
    ]
    critic = ChapterCritic(llm)

    trace = run_refine_loop(
        draft_fn=draft_fn,
        rewrite_fn=rewrite_fn,
        verifier=ChapterVerifier(),
        critic=critic,
        banned_phrases=["黑眸"],
    )
    # draft (1) + rewrite (1 verify) + critic (2) + refine (1) = 5
    # 注意 verify_attempts 里第一次失败 + 第二次成功 = 2，rewrites = 1
    assert trace.total_llm_calls == 1 + 1 + 2 + 1
