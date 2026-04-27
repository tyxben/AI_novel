"""CritiqueResult — Reviewer 产出的结构化审稿报告。

Phase 2-β 架构重构：合并 QualityReviewer + ConsistencyChecker + StyleKeeper
为单一 Reviewer agent。Reviewer 不再打分，只标问题 + 出具建议。

字段设计（参考 ``specs/architecture-rework-2026/DESIGN.md`` Part 2 A5）：

- ``strengths``：本章优点（保留）
- ``issues``：待修问题（按 ``severity`` 分级）
- ``specific_revisions``：段落级修改建议（喂给 Writer.refine 的原料）
- ``overall_assessment``：≤200 字总评
- ``style_overuse_hits``：StyleProfile 命中（本书口头禅的回响）
- ``consistency_flags``：与 Ledger 事实冲突的点
- ``need_rewrite``：信息标签（仅供作者参考，不触发任何自动行为）

严格与旧 QualityReport 区别：
- 无 ``scores`` / ``retention_scores`` / ``quality_score`` 字段
- 无 ``rule_check`` 子字段（RuleCheckResult 已随 quality_check_tool 一起砍）
- ``need_rewrite`` 退化为信息标签，不再触发 Writer 回写

本模型旨在被 ``Reviewer.review()`` 返回，写进 ``state["current_chapter_quality"]``
继续走 state_writeback 持久化。未来（Phase 3+）可替换到一个更明确的
``critique_report`` state 字段里。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


IssueType = Literal[
    "pacing",
    "characterization",
    "world_consistency",
    "dialogue",
    "trope_overuse",
    "transition",
    "logic",
    "consistency",              # 与 ledger 冲突
    "style_overuse",            # 本书口头禅过密
    "cross_chapter_verbatim",   # 跨章 verbatim 复读（C 阶段 P2 兜底网，2026-04-28）
    "other",
]


Severity = Literal["low", "medium", "high"]


class CritiqueIssue(BaseModel):
    """单条具体问题。"""

    type: IssueType = "other"
    severity: Severity = "medium"
    quote: str = Field(default="", description="原文引用片段（≤200字，自动截断）")
    reason: str = Field(default="", description="问题描述")

    @field_validator("quote")
    @classmethod
    def _trim_quote(cls, v: str) -> str:
        return (v or "")[:200]


class Revision(BaseModel):
    """具体修改建议。"""

    target: str = Field(default="", description="原文引用片段（≤300字）")
    suggestion: str = Field(default="", description="建议改成什么样")

    @field_validator("target", "suggestion")
    @classmethod
    def _trim(cls, v: str) -> str:
        return (v or "")[:300]


class ConsistencyFlag(BaseModel):
    """Ledger 一致性标记（Reviewer 从 LedgerStore 快照检查的结果）。"""

    type: str = Field(
        default="other",
        description=(
            "标记类型：character_state / world_fact / foreshadowing / "
            "debt / other"
        ),
    )
    severity: Severity = "medium"
    detail: str = Field(default="", description="冲突描述")
    ref_chapter: int | None = Field(
        default=None, description="冲突涉及的历史章节号（若适用）"
    )


class CritiqueResult(BaseModel):
    """Reviewer 输出。

    所有字段均可为空；下游（state_writeback / UI）必须防御性取值。
    """

    chapter_number: int = Field(default=0, ge=0)
    strengths: list[str] = Field(default_factory=list)
    issues: list[CritiqueIssue] = Field(default_factory=list)
    specific_revisions: list[Revision] = Field(default_factory=list)
    overall_assessment: str = Field(
        default="", description="≤200 字总评"
    )

    # --- 附加信息通道 ---
    style_overuse_hits: list[str] = Field(
        default_factory=list,
        description="StyleProfile.detect_overuse 命中的短语（本书口头禅）",
    )
    consistency_flags: list[ConsistencyFlag] = Field(
        default_factory=list,
        description="与 LedgerStore 快照不一致的标记",
    )

    # --- 信息标签（不触发任何自动行为）---
    need_rewrite: bool = Field(
        default=False,
        description=(
            "信息标签：Reviewer 建议本章值得重写。"
            "仅供作者参考，不驱动任何写入。"
        ),
    )

    raw_response: str = Field(default="", exclude=True)

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def high_severity_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "high")

    @property
    def medium_severity_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "medium")

    @property
    def needs_refine(self) -> bool:
        """是否值得再走一轮 refine（同 ChapterCritic 旧语义）。

        保留给 ``refine_loop`` 兼容：有任一 high 或 ≥2 medium 即认为值得。
        """
        return self.high_severity_count > 0 or self.medium_severity_count >= 2

    def to_writer_prompt(self) -> str:
        """格式化成给 Writer.refine 用的提示（兼容 ChapterCritic 旧接口）。"""
        if not self.issues and not self.specific_revisions:
            return ""
        lines = ["## 编辑批注（请按下列建议精修，保留 strengths 部分）"]
        if self.strengths:
            lines.append("\n### 保留的优点")
            for s in self.strengths[:5]:
                lines.append(f"- {s}")
        if self.issues:
            lines.append("\n### 待修问题")
            for i in self.issues:
                tag = {
                    "high": "[HIGH]",
                    "medium": "[MED]",
                    "low": "[LOW]",
                }.get(i.severity, "-")
                quote = f"「{i.quote}」" if i.quote else ""
                lines.append(f"- {tag} [{i.type}] {quote} {i.reason}")
        if self.specific_revisions:
            lines.append("\n### 具体改写建议")
            for r in self.specific_revisions[:8]:
                target = f"原: {r.target}" if r.target else ""
                lines.append(f"- {target}\n  改: {r.suggestion}")
        if self.style_overuse_hits:
            lines.append("\n### 本书口头禅（过密，考虑换说法）")
            lines.append("、".join(self.style_overuse_hits[:15]))
        if self.consistency_flags:
            lines.append("\n### 一致性提醒")
            for f in self.consistency_flags[:10]:
                ref = (
                    f"（参考第{f.ref_chapter}章）"
                    if f.ref_chapter is not None
                    else ""
                )
                lines.append(f"- [{f.type}/{f.severity}] {f.detail}{ref}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Backwards-compat aliases
# ---------------------------------------------------------------------------

# 旧 ChapterCritic 代码里 Issue/Revision 是独立类；保留别名让外部引用平滑。
Issue = CritiqueIssue
