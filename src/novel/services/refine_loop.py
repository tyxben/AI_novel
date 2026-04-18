"""SelfRefineLoop — "单轮审阅报告"（Phase 0 档 4b：零自动重写）。

**历史**：本模块曾经是 draft → sanitize → verify × N → critic × N 的多轮循环，
会自动调 rewrite_fn 反复改写章节。Phase 0 档 4a 拔掉了 graph 层 Reviewer→Writer
的自动回边；档 4b 进一步把本文件改成**单次**产报告，不再调用 rewrite_fn。

**现在**：``run_refine_loop`` 只做一次 sanitize → verify → critic → 返回
``RefineReport``。章节正文不会被本模块修改；作者若决定重写，走 agent_chat
的 ``rewrite_chapter`` 工具（apply_feedback 路径）。

**TODO (Phase 3)**：由 ChapterFlow 统一编排 sanitize/verify/critic/commit，届时
本文件将被拆解或内联。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from src.novel.agents.reviewer import Reviewer
from src.novel.models.critique_result import CritiqueResult

# Backwards-compat alias: older call sites imported ChapterCritic from here.
ChapterCritic = Reviewer
from src.novel.models.refine_report import RefineReport
from src.novel.services.chapter_verifier import ChapterVerifier, VerifyReport
from src.novel.utils.chapter_sanitizer import sanitize_chapter

log = logging.getLogger("novel.refine_loop")


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class RefineConfig:
    """控制 refine 行为的参数。

    注意：Phase 0 档 4b 后，``max_verify_retries`` 和 ``max_refine_iters`` 已失效
    （固定单轮）。字段保留仅为向后兼容调用方签名，不影响行为。
    """

    max_verify_retries: int = 2  # deprecated: ignored since Phase 0 档 4b
    max_refine_iters: int = 2    # deprecated: ignored since Phase 0 档 4b
    enable_critic: bool = True   # 关掉则跳过 critic 阶段（省成本）


@dataclass
class RefineTrace:
    """完整执行轨迹（单轮语义下，verify/critique 各至多 1 条）。

    保留字段兼容老 API：``refine_iterations`` 固定 0 或 1（语义：是否生成过报告），
    ``verify_attempts`` / ``critique_attempts`` 分别至多 1 条。
    """

    final_text: str = ""
    sanitize_actions: list[str] = field(default_factory=list)
    opening_duplicate_flagged: bool = False
    verify_attempts: list[VerifyReport] = field(default_factory=list)
    critique_attempts: list[CritiqueResult] = field(default_factory=list)
    refine_iterations: int = 0
    verify_passed: bool = False
    critic_passed: bool = False
    notes: list[str] = field(default_factory=list)
    report: RefineReport | None = None  # 单轮报告（Phase 0 档 4b）

    @property
    def total_llm_calls(self) -> int:
        """单轮下：verifier 零 LLM，critic 至多 1 次。"""
        return len(self.critique_attempts)


# Type aliases — 保留以不破坏调用方签名；rewrite_fn 不会被调用。
DraftFn = Callable[[], str]
"""返回章节正文。无副作用。"""

RewriteFn = Callable[[str, str], str]
"""DEPRECATED (Phase 0 档 4b): 参数保留但不会被调用。作者主动重写走
agent_chat.rewrite_chapter 工具（apply_feedback 路径）。"""


# ---------------------------------------------------------------------------
# Single-pass runner
# ---------------------------------------------------------------------------


def run_refine_loop(
    *,
    draft_fn: DraftFn,
    rewrite_fn: RewriteFn | None = None,  # deprecated, ignored
    verifier: ChapterVerifier,
    critic: Reviewer | None = None,
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
    """跑**单次**审阅，返回 ``RefineTrace``（含 ``report: RefineReport``）。

    阶段（严格单次，无重试无循环）：
        1. draft_fn() 取章节正文
        2. sanitize → 删 markdown/元注释；首句重复 → 标记
        3. verify 一次（硬约束报告）
        4. critic 一次（软质量报告；可选）
        5. 综合成 RefineReport 返回

    ``rewrite_fn`` 参数保留仅为向后兼容，**不会被调用**。若上层想落盘
    重写版本，应走 ``NovelPipeline.apply_feedback`` 或 agent_chat 的
    ``rewrite_chapter`` 工具，而不是本模块。
    """
    cfg = config or RefineConfig()
    trace = RefineTrace()

    if rewrite_fn is not None:
        log.debug(
            "run_refine_loop: rewrite_fn supplied but ignored "
            "(Phase 0 档 4b 单轮语义)"
        )

    # ---- Stage 1: draft ----
    text = draft_fn()
    original_text = text
    text, trace = _sanitize(text, prev_chapter_text, trace)
    trace.notes.append(f"draft: {len(text)} chars")
    sanitized_flag = bool(trace.sanitize_actions) or (text != original_text)

    # ---- Stage 2: verify (single pass) ----
    verify_report = verifier.verify(
        text,
        must_fulfill_debts=must_fulfill_debts,
        must_collect_foreshadowings=must_collect_foreshadowings,
        banned_phrases=banned_phrases,
        target_words=target_words,
    )
    trace.verify_attempts.append(verify_report)
    trace.verify_passed = bool(verify_report.passed)
    if verify_report.passed:
        trace.notes.append("verify passed (single pass)")
    else:
        trace.notes.append(
            f"verify failed: {len(verify_report.failures)} issues (no retry)"
        )

    # ---- Stage 3: critic (single pass, optional) ----
    critique: CritiqueResult | None = None
    if cfg.enable_critic and critic is not None:
        prev_tail = (prev_chapter_text or "")[-500:] if prev_chapter_text else ""
        try:
            # Use the .critique() alias so legacy call sites and tests that
            # MagicMock `critic.critique` keep working.
            critique = critic.critique(
                text,
                chapter_number=chapter_number,
                chapter_title=chapter_title,
                chapter_goal=chapter_goal,
                previous_tail=prev_tail,
                prior_critiques=[],
            )
            trace.critique_attempts.append(critique)
            trace.critic_passed = not critique.needs_refine
            if critique.needs_refine:
                trace.notes.append(
                    f"critic flagged issues "
                    f"(high={critique.high_severity_count}, "
                    f"med={critique.medium_severity_count}) — report only"
                )
            else:
                trace.notes.append("critic passed (single pass)")
        except Exception as exc:  # noqa: BLE001
            log.warning("critic.critique failed: %s", exc)
            trace.notes.append(f"critic failed: {exc}")
            trace.critic_passed = True  # 失败按通过处理，避免误推荐重写
    else:
        trace.notes.append("critic stage skipped")
        trace.critic_passed = True

    # ---- Build RefineReport (authoritative single-pass result) ----
    trace.report = _build_report(
        chapter_number=chapter_number,
        sanitized=sanitized_flag,
        verify_report=verify_report,
        critique=critique,
    )
    trace.final_text = text  # 注意：这里等于 sanitize 后的原文，没有 rewrite
    return trace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize(
    text: str, prev: str | None, trace: RefineTrace
) -> tuple[str, RefineTrace]:
    result = sanitize_chapter(text, prev_chapter_text=prev)
    trace.sanitize_actions.extend(result.actions)
    if result.opening_duplicate:
        trace.opening_duplicate_flagged = True
    return result.cleaned, trace


def _build_report(
    *,
    chapter_number: int,
    sanitized: bool,
    verify_report: VerifyReport,
    critique: CritiqueResult | None,
) -> RefineReport:
    """把 verify + critic 的结构化结果聚合成 ``RefineReport``。"""
    verifier_findings: list[dict] = []
    for f in verify_report.failures:
        verifier_findings.append(
            {
                "rule": f.rule,
                "severity": f.severity,
                "detail": f.detail,
            }
        )

    critic_findings: list[dict] = []
    overall_assessment = ""
    if critique is not None:
        for issue in critique.issues:
            critic_findings.append(
                {
                    "type": getattr(issue, "type", "other"),
                    "severity": getattr(issue, "severity", "medium"),
                    "quote": getattr(issue, "quote", ""),
                    "reason": getattr(issue, "reason", ""),
                }
            )
        overall_assessment = (critique.overall_assessment or "")[:200]

    # Decide recommended_action (建议，不触发)
    if not verify_report.passed:
        action = "needs_rewrite"
    elif critique is not None and critique.needs_refine:
        action = "suggest_refine"
    else:
        action = "accept"

    return RefineReport(
        chapter_number=chapter_number,
        sanitized=sanitized,
        verifier_findings=verifier_findings,
        critic_findings=critic_findings,
        overall_assessment=overall_assessment,
        recommended_action=action,  # type: ignore[arg-type]
    )
