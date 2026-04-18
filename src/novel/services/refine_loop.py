"""SelfRefineLoop — 把 Sanitizer / Verifier / Critic / Writer 串成一个闭环。

调用方传入 ``draft_fn`` 和 ``rewrite_fn``（不绑死特定 Writer 实现），
本服务负责编排：
  draft → sanitize → verify → (rewrite × N) → critique → (refine × N) → done

返回完整执行轨迹（``RefineTrace``），便于审计/调试/UI 展示。

不主动写盘，不依赖 NovelPipeline，纯函数式编排。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from src.novel.agents.chapter_critic import ChapterCritic, CritiqueResult
from src.novel.services.chapter_verifier import ChapterVerifier, VerifyReport
from src.novel.utils.chapter_sanitizer import sanitize_chapter

log = logging.getLogger("novel.refine_loop")


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class RefineConfig:
    """控制 refine 行为的参数。"""

    max_verify_retries: int = 2  # verifier 失败时最多重写次数
    max_refine_iters: int = 2    # critic 不满意时最多优化轮次
    enable_critic: bool = True   # 关掉则跳过 critic 阶段（省成本）


@dataclass
class RefineTrace:
    """完整执行轨迹。"""

    final_text: str = ""
    sanitize_actions: list[str] = field(default_factory=list)
    opening_duplicate_flagged: bool = False
    verify_attempts: list[VerifyReport] = field(default_factory=list)
    critique_attempts: list[CritiqueResult] = field(default_factory=list)
    refine_iterations: int = 0
    verify_passed: bool = False
    critic_passed: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def total_llm_calls(self) -> int:
        """draft + rewrite 次 + critic 次 + refine 次"""
        # draft is always 1; +1 per rewrite (verify_attempts has 1 initial draft + N rewrites)
        rewrites = max(0, len(self.verify_attempts) - 1)
        return 1 + rewrites + len(self.critique_attempts) + self.refine_iterations


# Type aliases for caller-supplied functions
DraftFn = Callable[[], str]
"""返回章节正文。无副作用。"""

RewriteFn = Callable[[str, str], str]
"""(prev_text, feedback) -> new_text. feedback 来自 verifier 或 critic."""


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


def run_refine_loop(
    *,
    draft_fn: DraftFn,
    rewrite_fn: RewriteFn,
    verifier: ChapterVerifier,
    critic: ChapterCritic | None = None,
    must_fulfill_debts: list[dict] | None = None,
    must_collect_foreshadowings: list[dict] | None = None,
    banned_phrases: Iterable[str] | None = None,
    target_words: int | None = None,
    prev_chapter_text: str | None = None,
    chapter_number: int = 0,
    chapter_title: str = "",
    chapter_goal: str = "",
    config: RefineConfig | None = None,
) -> RefineTrace:
    """运行完整 refine 循环。

    阶段:
        1. draft_fn() 出初稿
        2. sanitize → 删 markdown/元注释；首句重复 → 标记
        3. verify 硬约束 — 不过则 rewrite_fn(text, verifier_feedback)，最多 N 次
        4. critic 软质量（可选）— 不满意则 rewrite_fn(text, critic_feedback)，最多 M 次
        5. 返回轨迹

    Args:
        draft_fn: 出初稿。
        rewrite_fn: 拿 (旧稿, 反馈) 出新稿。verifier 阶段和 critic 阶段共用同一个函数。
        verifier: ``ChapterVerifier`` 实例。
        critic: ``ChapterCritic`` 实例。``None`` 或 ``config.enable_critic=False`` 时跳过 critic。
        其余参数透传给 verifier/critic。
        config: ``RefineConfig``，None 用默认值。

    Returns:
        ``RefineTrace``，``final_text`` 是最终成品。
    """
    cfg = config or RefineConfig()
    trace = RefineTrace()

    # ---- Stage 1: draft ----
    text = draft_fn()
    text, trace = _sanitize(text, prev_chapter_text, trace)
    trace.notes.append(f"draft: {len(text)} chars")

    # ---- Stage 2: verify loop ----
    text, trace = _verify_loop(
        text=text,
        prev_chapter_text=prev_chapter_text,
        rewrite_fn=rewrite_fn,
        verifier=verifier,
        must_fulfill_debts=must_fulfill_debts,
        must_collect_foreshadowings=must_collect_foreshadowings,
        banned_phrases=banned_phrases,
        target_words=target_words,
        max_retries=cfg.max_verify_retries,
        trace=trace,
    )

    # ---- Stage 3: critic loop ----
    if cfg.enable_critic and critic is not None:
        text, trace = _critic_loop(
            text=text,
            rewrite_fn=rewrite_fn,
            critic=critic,
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            chapter_goal=chapter_goal,
            prev_chapter_text=prev_chapter_text,
            max_iters=cfg.max_refine_iters,
            trace=trace,
        )
    else:
        trace.notes.append("critic stage skipped")
        trace.critic_passed = True  # disabled = not failing

    trace.final_text = text
    return trace


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------


def _sanitize(
    text: str, prev: str | None, trace: RefineTrace
) -> tuple[str, RefineTrace]:
    result = sanitize_chapter(text, prev_chapter_text=prev)
    trace.sanitize_actions.extend(result.actions)
    if result.opening_duplicate:
        trace.opening_duplicate_flagged = True
    return result.cleaned, trace


def _verify_loop(
    *,
    text: str,
    prev_chapter_text: str | None,
    rewrite_fn: RewriteFn,
    verifier: ChapterVerifier,
    must_fulfill_debts: list[dict] | None,
    must_collect_foreshadowings: list[dict] | None,
    banned_phrases: Iterable[str] | None,
    target_words: int | None,
    max_retries: int,
    trace: RefineTrace,
) -> tuple[str, RefineTrace]:
    """执行 verify 循环：fail → rewrite → verify ... 直到 pass 或耗尽次数。"""
    for attempt in range(max_retries + 1):  # initial verify + N rewrites
        report = verifier.verify(
            text,
            must_fulfill_debts=must_fulfill_debts,
            must_collect_foreshadowings=must_collect_foreshadowings,
            banned_phrases=banned_phrases,
            target_words=target_words,
        )
        trace.verify_attempts.append(report)

        if report.passed:
            trace.verify_passed = True
            trace.notes.append(f"verify passed after {attempt} rewrites")
            return text, trace

        if attempt >= max_retries:
            trace.notes.append(
                f"verify still failing after {attempt} rewrites: "
                f"{len(report.failures)} issues"
            )
            return text, trace

        feedback = report.to_writer_feedback()
        # 如果有首句重复标记，叠加到 feedback
        if trace.opening_duplicate_flagged:
            feedback += "\n  🔴 [opening] 首句与上章高度相似，请换一种开头方式。"

        try:
            new_text = rewrite_fn(text, feedback)
        except Exception as exc:  # noqa: BLE001
            log.warning("rewrite_fn failed during verify loop: %s", exc)
            trace.notes.append(f"rewrite_fn failed: {exc}")
            return text, trace

        new_text, trace = _sanitize(new_text, prev_chapter_text, trace)
        text = new_text
    return text, trace


def _critic_loop(
    *,
    text: str,
    rewrite_fn: RewriteFn,
    critic: ChapterCritic,
    chapter_number: int,
    chapter_title: str,
    chapter_goal: str,
    prev_chapter_text: str | None,
    max_iters: int,
    trace: RefineTrace,
) -> tuple[str, RefineTrace]:
    """执行 critic 循环：critique → 如果 needs_refine → rewrite_fn(text, critic_prompt)。"""
    prev_tail = (prev_chapter_text or "")[-500:] if prev_chapter_text else ""

    for it in range(max_iters):
        critique = critic.critique(
            text,
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            chapter_goal=chapter_goal,
            prev_chapter_tail=prev_tail,
            prior_critiques=trace.critique_attempts,
        )
        trace.critique_attempts.append(critique)

        if not critique.needs_refine:
            trace.critic_passed = True
            trace.notes.append(
                f"critic passed at iter {it} "
                f"(high={critique.high_severity_count}, med={critique.medium_severity_count})"
            )
            return text, trace

        feedback = critique.to_writer_prompt()
        if not feedback:
            # critic 返回空的 issues/revisions（如解析失败）— 跳出
            trace.notes.append(f"critic iter {it} produced no actionable feedback, exiting")
            return text, trace

        try:
            new_text = rewrite_fn(text, feedback)
        except Exception as exc:  # noqa: BLE001
            log.warning("rewrite_fn failed during critic loop: %s", exc)
            trace.notes.append(f"rewrite_fn failed in critic stage: {exc}")
            return text, trace

        new_text, trace = _sanitize(new_text, prev_chapter_text, trace)
        text = new_text
        trace.refine_iterations += 1

    trace.notes.append(
        f"critic exhausted {max_iters} iters; final high="
        f"{trace.critique_attempts[-1].high_severity_count if trace.critique_attempts else 0}"
    )
    return text, trace
