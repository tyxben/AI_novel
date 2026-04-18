"""RefineReport — 单轮"审阅报告"数据模型（Phase 0 档 4b）。

refine_loop 在"零自动重写"架构下只出报告不改文本。作者/上层 UI 读了报告
自行决定是否触发 rewrite。``recommended_action`` 只是建议，不是触发器。

- accept:          通过 verify + critic，无需动作
- suggest_refine:  critic 有软质量问题，建议但不强制
- needs_rewrite:   verifier 有硬约束失败，强烈建议重写
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RecommendedAction = Literal["accept", "suggest_refine", "needs_rewrite"]


class RefineReport(BaseModel):
    """一次章节审阅的完整报告（纯只读）。"""

    chapter_number: int = Field(default=0, description="被审阅的章节号")
    sanitized: bool = Field(
        default=False, description="是否对原文执行过 sanitize（删 markdown 等）"
    )
    verifier_findings: list[dict] = Field(
        default_factory=list,
        description="硬约束报告（debt/foreshadowing/banned_phrase/length）",
    )
    critic_findings: list[dict] = Field(
        default_factory=list,
        description="软质量报告（pacing/trope/logic 等）",
    )
    overall_assessment: str = Field(
        default="", description="≤200 字总评，多来自 critic"
    )
    recommended_action: RecommendedAction = Field(
        default="accept",
        description="建议动作；不触发任何写操作，仅供作者参考",
    )
