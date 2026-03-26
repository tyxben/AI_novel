"""Feedback Injector -- bridges QualityReviewer output to Writer input."""

from __future__ import annotations

import logging
from typing import Any

from src.prompt_registry.registry import PromptRegistry

log = logging.getLogger("prompt_registry.feedback")


class FeedbackInjector:
    """Manages the feedback loop between QualityReviewer and Writer."""

    def __init__(self, registry: PromptRegistry):
        self.registry = registry

    def save_chapter_feedback(
        self,
        novel_id: str,
        chapter_number: int,
        quality_report: dict,
    ) -> None:
        """Extract strengths/weaknesses from QualityReviewer report and save."""
        strengths: list[str] = []
        weaknesses: list[str] = []

        # Extract from rule_check
        rule_check = quality_report.get("rule_check", {})
        if rule_check.get("passed"):
            strengths.append("规则检查全部通过")
        else:
            if rule_check.get("ai_flavor_issues"):
                weaknesses.append(f"AI味问题: {len(rule_check['ai_flavor_issues'])}处")
            if rule_check.get("repetition_issues"):
                weaknesses.append(f"重复问题: {len(rule_check['repetition_issues'])}处")

        # Extract from scores
        scores = quality_report.get("scores", {})
        for metric, score in scores.items():
            if score >= 8.0:
                strengths.append(f"{metric}表现优秀({score}分)")
            elif score < 6.0:
                weaknesses.append(f"{metric}需改进({score}分)")

        # Extract from suggestions
        suggestions = quality_report.get("suggestions", [])
        weaknesses.extend(suggestions[:5])  # Cap at 5

        overall_score: float | None = None
        if scores:
            overall_score = sum(scores.values()) / len(scores)

        self.registry.save_feedback(
            novel_id=novel_id,
            chapter_number=chapter_number,
            strengths=strengths,
            weaknesses=weaknesses,
            overall_score=overall_score,
        )

    def get_feedback_prompt(self, novel_id: str, current_chapter: int) -> str:
        """Get formatted feedback from previous chapter for injection into Writer prompt."""
        feedback = self.registry.get_last_feedback(novel_id, current_chapter)
        if feedback is None:
            return ""

        parts = ["【上一章质量反馈 — 请在本章中改进】"]

        if feedback.weaknesses:
            parts.append("需要改进的问题：")
            for w in feedback.weaknesses:
                parts.append(f"  - {w}")

        if feedback.strengths:
            parts.append("继续保持的优点：")
            for s in feedback.strengths:
                parts.append(f"  + {s}")

        if feedback.overall_score is not None:
            parts.append(f"上一章综合评分：{feedback.overall_score:.1f}/10")

        return "\n".join(parts)
