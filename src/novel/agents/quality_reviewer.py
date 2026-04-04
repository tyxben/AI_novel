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
from uuid import uuid4

from src.llm.llm_client import create_llm_client
from src.novel.agents.state import Decision, NovelState
from src.novel.llm_utils import get_stage_llm_config
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
        chapter_brief: dict | None = None,
        brief_validator: Any | None = None,
        debt_extractor: Any | None = None,
        obligation_tracker: Any | None = None,
        chapter_number: int = 0,
        enable_rule_check: bool = True,
        blacklist_overrides: dict[str, int] | None = None,
        existing_style_check: dict | None = None,
    ) -> dict:
        """完整质量审查流程。

        Args:
            chapter_text: 章节文本
            chapter_outline: 章节大纲（可选）
            characters: 角色列表（可选）
            style_name: 目标风格名称（可选）
            budget_mode: 省钱模式，跳过 LLM 评分
            chapter_brief: 章节任务书（可选，用于追更价值评估的任务完成度）
            brief_validator: BriefValidator 实例（可选，用于章节任务书验证）
            debt_extractor: DebtExtractor 实例（可选，用于提取叙事债务）
            obligation_tracker: ObligationTracker 实例（可选，用于管理叙事债务）
            chapter_number: 当前章节号（默认 0）
            enable_rule_check: 是否执行规则硬指标检查（默认 True）
            blacklist_overrides: AI 味短语阈值覆盖（可选，来自 config）
            existing_style_check: 已有的风格检查结果（来自 style_keeper 节点），
                提供时跳过内部 StyleKeeper 调用以避免重复执行。
                期望格式: {"similarity": float, "deviations": list, "suggestions": list}

        Returns:
            综合质量报告字典，包含：
            - rule_check: RuleCheckResult 的字典形式
            - style_check: 风格检查结果（如有）
            - scores: LLM 评分（如有）
            - retention_scores: 追更价值评分（如有）
            - need_rewrite: 是否需要重写
            - rewrite_reason: 重写原因
            - suggestions: 改进建议
            - brief_fulfillment: 任务书验证报告（如有）
            - debts_extracted: 提取的叙事债务数量（如有）
        """
        report: dict[str, Any] = {
            "need_rewrite": False,
            "rewrite_reason": None,
            "suggestions": [],
        }

        # --- 1. 规则硬指标检查（可通过 config 禁用） ---
        if enable_rule_check:
            rule_result = self.quality_tool.rule_check(
                chapter_text, characters, blacklist_overrides=blacklist_overrides
            )
        else:
            from src.novel.models.quality import RuleCheckResult as _RCR
            rule_result = _RCR(passed=True)
            log.info("规则检查已通过 config 禁用，跳过")
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

        # --- 2. 风格检查 ---
        if existing_style_check:
            # Read from style_keeper node output (avoid duplicate execution)
            report["style_check"] = {
                "similarity": existing_style_check.get("similarity"),
                "deviations": existing_style_check.get("deviations", []),
            }
            deviations = existing_style_check.get("deviations", [])
            if deviations:
                style_suggestions = existing_style_check.get("suggestions", [])
                if style_suggestions:
                    report["suggestions"].extend(style_suggestions)
                else:
                    for dev in deviations[:3]:
                        desc = dev.get("description", str(dev)) if isinstance(dev, dict) else str(dev)
                        report["suggestions"].append(f"风格偏差：{desc}")
        elif style_name:
            # Fallback: run style check ourselves (e.g., when called outside the graph)
            try:
                from src.novel.templates.style_presets import get_style  # noqa: F401
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
            report["retention_scores"] = quality_report.retention_scores

            if quality_report.need_rewrite and not report["need_rewrite"]:
                report["need_rewrite"] = True
                report["rewrite_reason"] = quality_report.rewrite_reason

            if quality_report.suggestions:
                report["suggestions"].extend(quality_report.suggestions)
        else:
            report["scores"] = {}
            report["retention_scores"] = {}

        # --- 4. Narrative Control: Brief Validation ---
        if brief_validator and chapter_brief:
            try:
                brief_report = brief_validator.validate_chapter(
                    chapter_text=chapter_text,
                    chapter_brief=chapter_brief,
                    chapter_number=chapter_number,
                )
                report["brief_fulfillment"] = brief_report
                # Create debts for unfulfilled items
                if obligation_tracker and not brief_report.get("overall_pass", True):
                    for debt in brief_report.get("suggested_debts", []):
                        obligation_tracker.add_debt(
                            debt_id=f"brief_{chapter_number}_{debt.get('type', 'unknown')}_{uuid4().hex[:6]}",
                            source_chapter=chapter_number,
                            debt_type=debt.get("type", "must_pay_next"),
                            description=debt.get("description", ""),
                            urgency_level=debt.get("urgency_level", "high"),
                        )
            except Exception as e:
                log.warning("Brief validation failed: %s", e)

        # --- 5. Narrative Control: Debt Extraction ---
        if debt_extractor:
            try:
                extraction = debt_extractor.extract_from_chapter(
                    chapter_text=chapter_text,
                    chapter_number=chapter_number,
                )
                report["debts_extracted"] = len(extraction.get("debts", []))
                if obligation_tracker:
                    for debt in extraction.get("debts", []):
                        obligation_tracker.add_debt(**debt)
            except Exception as e:
                log.warning("Debt extraction failed: %s", e)

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

        # 追更价值评分极低 -> 重写
        retention_scores = report.get("retention_scores", {})
        if retention_scores:
            retention_avg = sum(retention_scores.values()) / len(retention_scores)
            if retention_avg < 4.0:
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
    llm_config = get_stage_llm_config(state, "quality_review")
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
    quality_cfg = state.get("config", {}).get("quality", {})
    enable_llm_scoring = quality_cfg.get("enable_llm_scoring", True)
    if not enable_llm_scoring:
        budget_mode = True  # Skip LLM scoring entirely when disabled
    else:
        budget_mode = current_chapter % 5 != 0 and current_chapter != total_chapters

    # 尝试从 state 中获取章节任务书（chapter_brief）
    chapter_brief = state.get("current_chapter_brief") or None

    # 从 state 中提取叙事控制服务（可能为 None）
    obligation_tracker = state.get("obligation_tracker")
    brief_validator = state.get("brief_validator")
    debt_extractor = state.get("debt_extractor")

    enable_rule_check = quality_cfg.get("enable_rule_check", True)
    blacklist_overrides = quality_cfg.get("ai_flavor_blacklist") or None

    # Read style check results produced by the style_keeper node (already executed
    # in parallel before quality_reviewer) to avoid duplicate StyleKeeper calls.
    existing_quality = state.get("current_chapter_quality") or {}
    existing_style_check = None
    if existing_quality.get("style_similarity") is not None:
        existing_style_check = {
            "similarity": existing_quality["style_similarity"],
            "deviations": existing_quality.get("style_deviations", []),
            "suggestions": existing_quality.get("style_suggestions", []),
        }

    report = reviewer.review_chapter(
        chapter_text=chapter_text,
        chapter_outline=state.get("current_chapter_outline"),
        characters=state.get("characters"),
        style_name=style_name,
        budget_mode=budget_mode,
        chapter_brief=chapter_brief,
        brief_validator=brief_validator,
        debt_extractor=debt_extractor,
        obligation_tracker=obligation_tracker,
        chapter_number=current_chapter,
        enable_rule_check=enable_rule_check,
        blacklist_overrides=blacklist_overrides,
        existing_style_check=existing_style_check,
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

    # Save feedback if registry available
    feedback_injector = state.get("feedback_injector")
    novel_id = state.get("novel_id", "")
    if feedback_injector and novel_id:
        try:
            feedback_injector.save_chapter_feedback(
                novel_id=novel_id,
                chapter_number=current_chapter,
                quality_report=report,
            )
        except Exception as e:
            log.debug("Failed to save chapter feedback: %s", e)

    # 更新重试计数
    if need_rewrite:
        current_chapter = state.get("current_chapter", 1)
        retry_counts = dict(state.get("retry_counts") or {})
        retry_counts[current_chapter] = retry_counts.get(current_chapter, 0) + 1
        result["retry_counts"] = retry_counts

        # Build rewrite prompt from review findings
        rewrite_parts: list[str] = []
        if report.get("rewrite_reason"):
            rewrite_parts.append(f"重写原因：{report['rewrite_reason']}")

        # Rule check failures
        rule_check = report.get("rule_check", {})
        if not rule_check.get("passed", True):
            if rule_check.get("ai_flavor_issues"):
                phrases = []
                for issue in rule_check["ai_flavor_issues"][:5]:
                    if isinstance(issue, dict):
                        phrases.append(issue.get("phrase", str(issue)))
                    else:
                        phrases.append(str(issue))
                rewrite_parts.append(f"必须消除以下 AI 味短语：{'、'.join(phrases)}")
            if rule_check.get("repetition_issues"):
                rewrite_parts.append(f"修复 {len(rule_check['repetition_issues'])} 处重复句")
            if rule_check.get("dialogue_distinction_issues"):
                rewrite_parts.append("增加不同角色对话的区分度，每个角色必须有独特口吻")
            if rule_check.get("paragraph_length_issues"):
                rewrite_parts.append("调整段落长度，避免过长或过短的段落")

        # Style deviations
        style_check = report.get("style_check", {})
        if style_check.get("deviations"):
            for dev in style_check["deviations"][:3]:
                if isinstance(dev, dict):
                    rewrite_parts.append(f"风格偏差：{dev.get('description', dev)}")
                else:
                    rewrite_parts.append(f"风格偏差：{dev}")

        # Suggestions
        suggestions = report.get("suggestions", [])
        if suggestions:
            rewrite_parts.append("改进建议：" + "；".join(suggestions[:5]))

        # Brief fulfillment failures
        brief_report = report.get("brief_fulfillment", {})
        if brief_report and not brief_report.get("overall_pass", True):
            unfulfilled = brief_report.get("unfulfilled_items", [])
            if unfulfilled:
                rewrite_parts.append("任务书未完成项：" + "；".join(str(u) for u in unfulfilled[:3]))

        if rewrite_parts:
            result["current_chapter_rewrite_prompt"] = (
                "【当前章质量审查反馈 — 重写时必须针对性修正以下问题】\n"
                + "\n".join(f"- {p}" for p in rewrite_parts)
            )

        max_retries = state.get("max_retries", 2)
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
            result["current_chapter_rewrite_prompt"] = ""  # Clear on force pass
            result["current_chapter_quality"] = report
    else:
        # Chapter passed — clear rewrite prompt for next chapter
        result["current_chapter_rewrite_prompt"] = ""

    return result
