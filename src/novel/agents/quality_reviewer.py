"""QualityReviewer - 质量评审官 Agent

负责：
1. 规则硬指标检查（零成本）
2. 风格一致性检查（可选）
3. LLM 打分评估（可选，省钱模式跳过）
4. 综合判断是否需要重写
5. 作为 LangGraph 节点审查章节质量
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.llm.llm_client import create_llm_client
from src.novel.agents.state import Decision, NovelState
from src.novel.tools.quality_check_tool import QualityCheckTool
from src.novel.tools.style_analysis_tool import StyleAnalysisTool

log = logging.getLogger("novel")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _make_decision(
    step: str,
    decision: str,
    reason: str,
    data: dict[str, Any] | None = None,
) -> Decision:
    """创建 QualityReviewer 的决策记录。"""
    return Decision(
        agent="QualityReviewer",
        step=step,
        decision=decision,
        reason=reason,
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# QualityReviewer Agent
# ---------------------------------------------------------------------------


class QualityReviewer:
    """质量评审官 Agent - 综合质量检查和重写判断。"""

    def __init__(self, llm_client: Any | None = None):
        """
        Args:
            llm_client: 可选的 LLM 客户端。规则检查不需要，LLM 打分需要。
        """
        self.llm = llm_client
        self.quality_tool = QualityCheckTool(llm_client)
        self.style_tool = StyleAnalysisTool()

    def review_chapter(
        self,
        chapter_text: str,
        chapter_outline: dict | None = None,
        characters: list[dict] | None = None,
        style_name: str | None = None,
        budget_mode: bool = False,
    ) -> dict:
        """完整质量审查流程。

        Args:
            chapter_text: 章节文本
            chapter_outline: 章节大纲（可选）
            characters: 角色列表（可选）
            style_name: 目标风格名称（可选）
            budget_mode: 省钱模式，跳过 LLM 评分

        Returns:
            综合质量报告字典，包含：
            - rule_check: RuleCheckResult 的字典形式
            - style_check: 风格检查结果（如有）
            - scores: LLM 评分（如有）
            - need_rewrite: 是否需要重写
            - rewrite_reason: 重写原因
            - suggestions: 改进建议
        """
        report: dict[str, Any] = {
            "need_rewrite": False,
            "rewrite_reason": None,
            "suggestions": [],
        }

        # --- 1. 规则硬指标检查（总是执行） ---
        rule_result = self.quality_tool.rule_check(chapter_text, characters)
        report["rule_check"] = rule_result.model_dump()

        if not rule_result.passed:
            report["need_rewrite"] = True
            report["rewrite_reason"] = "规则硬指标未通过"

            # 生成改进建议
            if rule_result.ai_flavor_issues:
                report["suggestions"].append(
                    f"消除 {len(rule_result.ai_flavor_issues)} 处 AI 味短语"
                )
            if rule_result.repetition_issues:
                report["suggestions"].append(
                    f"修复 {len(rule_result.repetition_issues)} 处重复句"
                )
            if rule_result.paragraph_length_issues:
                report["suggestions"].append("调整段落长度")
            if rule_result.dialogue_distinction_issues:
                report["suggestions"].append("增加不同角色对话的区分度")

        # --- 2. 风格检查（如有目标风格） ---
        if style_name:
            try:
                from src.novel.templates.style_presets import get_style
                from src.novel.agents.style_keeper import StyleKeeper

                keeper = StyleKeeper(self.llm)
                similarity, deviations = keeper.check_style(chapter_text, style_name)
                report["style_check"] = {
                    "similarity": similarity,
                    "deviations": deviations,
                }
                if deviations:
                    suggestions = keeper.suggest_improvements(chapter_text, deviations)
                    report["suggestions"].extend(suggestions)
            except KeyError:
                log.warning("风格预设 '%s' 不存在，跳过风格检查", style_name)

        # --- 3. LLM 打分（非省钱模式且 LLM 可用） ---
        if not budget_mode and self.llm is not None:
            quality_report = self.quality_tool.evaluate_chapter(
                chapter_text, chapter_outline
            )
            report["scores"] = quality_report.scores

            if quality_report.need_rewrite and not report["need_rewrite"]:
                report["need_rewrite"] = True
                report["rewrite_reason"] = quality_report.rewrite_reason

            if quality_report.suggestions:
                report["suggestions"].extend(quality_report.suggestions)
        else:
            report["scores"] = {}

        return report

    def should_rewrite(self, report: dict, threshold: float = 6.0) -> bool:
        """判断是否需要重写。

        Args:
            report: review_chapter 返回的报告
            threshold: LLM 评分阈值，低于此值触发重写

        Returns:
            是否需要重写
        """
        # 规则检查未通过 -> 重写
        rule_check = report.get("rule_check", {})
        if not rule_check.get("passed", True):
            return True

        # LLM 评分低于阈值 -> 重写
        scores = report.get("scores", {})
        if scores:
            avg_score = sum(scores.values()) / len(scores)
            if avg_score < threshold:
                return True

        # 显式标记需要重写
        if report.get("need_rewrite", False):
            return True

        return False


# ---------------------------------------------------------------------------
# LangGraph 节点函数
# ---------------------------------------------------------------------------


def quality_reviewer_node(state: NovelState) -> dict[str, Any]:
    """LangGraph 节点：QualityReviewer。

    审查当前章节质量，判断是否需要重写。
    """
    decisions: list[Decision] = []
    errors: list[dict] = []

    chapter_text = state.get("current_chapter_text")
    if not chapter_text:
        return {
            "errors": [{"agent": "QualityReviewer", "message": "当前章节文本为空，跳过质量审查"}],
            "completed_nodes": ["quality_reviewer"],
        }

    # 获取 LLM 客户端
    llm_config = state.get("config", {}).get("llm", {})
    llm = None
    try:
        llm = create_llm_client(llm_config)
    except Exception:
        log.info("LLM 不可用，QualityReviewer 仅执行规则检查")

    reviewer = QualityReviewer(llm)

    style_name = state.get("style_name") or None
    current_chapter = state.get("current_chapter", 1)
    total_chapters = state.get("total_chapters", 25)

    # 省 token 策略：只在关键章节做 LLM 打分
    # 规则检查每章都做（零成本），LLM 打分仅在卷末/每5章做一次
    budget_mode = current_chapter % 5 != 0 and current_chapter != total_chapters

    report = reviewer.review_chapter(
        chapter_text=chapter_text,
        chapter_outline=state.get("current_chapter_outline"),
        characters=state.get("characters"),
        style_name=style_name,
        budget_mode=budget_mode,
    )

    need_rewrite = reviewer.should_rewrite(
        report,
        threshold=state.get("auto_approve_threshold", 6.0),
    )

    decisions.append(
        _make_decision(
            step="review_chapter",
            decision="需要重写" if need_rewrite else "质量通过",
            reason=report.get("rewrite_reason") or "所有检查通过",
            data={
                "rule_passed": report.get("rule_check", {}).get("passed", True),
                "scores": report.get("scores", {}),
                "suggestions_count": len(report.get("suggestions", [])),
            },
        )
    )

    result: dict[str, Any] = {
        "current_chapter_quality": report,
        "decisions": decisions,
        "errors": errors,
        "completed_nodes": ["quality_reviewer"],
    }

    # 更新重试计数
    if need_rewrite:
        current_chapter = state.get("current_chapter", 1)
        retry_counts = dict(state.get("retry_counts") or {})
        retry_counts[current_chapter] = retry_counts.get(current_chapter, 0) + 1
        result["retry_counts"] = retry_counts

        max_retries = state.get("max_retries", 3)
        if retry_counts[current_chapter] >= max_retries:
            decisions.append(
                _make_decision(
                    step="retry_limit",
                    decision="达到最大重试次数，强制通过",
                    reason=f"第 {current_chapter} 章已重试 {retry_counts[current_chapter]} 次",
                )
            )
            # 强制通过
            report["need_rewrite"] = False
            result["current_chapter_quality"] = report

    return result
