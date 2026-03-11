"""StyleKeeper - 风格守护者 Agent

负责：
1. 分析文本风格特征
2. 与目标风格预设比较
3. 生成风格改进建议
4. 作为 LangGraph 节点检查章节风格一致性
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.llm.llm_client import create_llm_client
from src.novel.agents.state import Decision, NovelState
from src.novel.models.quality import StyleMetrics
from src.novel.templates.style_presets import get_style
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
    """创建 StyleKeeper 的决策记录。"""
    return Decision(
        agent="StyleKeeper",
        step=step,
        decision=decision,
        reason=reason,
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# StyleKeeper Agent
# ---------------------------------------------------------------------------


class StyleKeeper:
    """风格守护者 Agent - 检查并维持文本风格一致性。"""

    def __init__(self, llm_client: Any):
        """
        Args:
            llm_client: 实现 ``chat(messages, temperature, json_mode)`` 的 LLMClient。
                        当前版本中 StyleKeeper 主要做规则检查，LLM 仅预留。
        """
        self.llm = llm_client
        self.tool = StyleAnalysisTool()

    def analyze_style(self, text: str) -> StyleMetrics:
        """分析文本风格特征。

        Args:
            text: 待分析文本

        Returns:
            StyleMetrics 实例
        """
        return self.tool.analyze(text)

    def check_style(self, text: str, target_style_name: str) -> tuple[float, list[str]]:
        """检查文本是否匹配目标风格预设。

        Args:
            text: 待检查文本
            target_style_name: 风格预设名称，如 "wuxia.classical"

        Returns:
            (similarity, deviations):
            - similarity: 0.0 ~ 1.0
            - deviations: 偏差描述列表

        Raises:
            KeyError: 风格名称不存在
        """
        preset = get_style(target_style_name)
        constraints = preset.get("constraints", {})

        # 从 constraints 构建参考 StyleMetrics
        reference = _constraints_to_metrics(constraints)

        # 分析当前文本
        metrics = self.tool.analyze(text)

        # 对比
        return self.tool.compare(metrics, reference)

    def suggest_improvements(self, text: str, deviations: list[str]) -> list[str]:
        """根据风格偏差生成改进建议（规则驱动）。

        Args:
            text: 原始文本
            deviations: 偏差描述列表

        Returns:
            改进建议列表
        """
        suggestions: list[str] = []
        for dev in deviations:
            if "平均句长" in dev and "偏高" in dev:
                suggestions.append("尝试将长句拆分为短句，增加节奏感")
            elif "平均句长" in dev and "偏低" in dev:
                suggestions.append("适当合并短句，增加叙述的流畅感和厚重感")
            elif "对话占比" in dev and "偏高" in dev:
                suggestions.append("减少对话，增加叙述、描写或心理活动段落")
            elif "对话占比" in dev and "偏低" in dev:
                suggestions.append("增加角色对话，让场景更生动")
            elif "感叹句占比" in dev and "偏高" in dev:
                suggestions.append("减少感叹句的使用，改用陈述句降低情绪强度")
            elif "感叹句占比" in dev and "偏低" in dev:
                suggestions.append("适当增加感叹句，增强情绪表达")
            elif "段落平均长度" in dev and "偏高" in dev:
                suggestions.append("将长段落拆分为多个短段落，提升阅读节奏")
            elif "段落平均长度" in dev and "偏低" in dev:
                suggestions.append("合并过短的段落，增加叙述的连贯性")
            elif "古风用词占比" in dev and "偏低" in dev:
                suggestions.append("增加文言词汇和半文半白表达，增强古典韵味")
            elif "古风用词占比" in dev and "偏高" in dev:
                suggestions.append("减少文言词汇，让语言更通俗易懂")
            elif "描写占比" in dev:
                if "偏低" in dev:
                    suggestions.append("增加环境描写和场景描述，增强画面感")
                else:
                    suggestions.append("减少描写性文字，加快叙事节奏")
            elif "第一人称占比" in dev:
                if "偏低" in dev:
                    suggestions.append("增加第一人称叙述和内心独白")
                else:
                    suggestions.append("减少第一人称叙述，增加客观描写")
            else:
                suggestions.append(f"调整风格以改善：{dev}")

        return suggestions


# ---------------------------------------------------------------------------
# 辅助：constraints -> StyleMetrics
# ---------------------------------------------------------------------------


def _constraints_to_metrics(constraints: dict[str, Any]) -> StyleMetrics:
    """将风格预设中的 constraints 转换为参考 StyleMetrics。

    constraints 中的范围取中间值作为参考。
    """

    def _mid(key: str, default: float) -> float:
        val = constraints.get(key)
        if val is None:
            return default
        if isinstance(val, list) and len(val) == 2:
            return (val[0] + val[1]) / 2
        if isinstance(val, (int, float)):
            return float(val)
        return default

    # max_paragraph_sentences -> paragraph_length 近似
    max_para_sentences = constraints.get("max_paragraph_sentences", 6)
    avg_sent = _mid("avg_sentence_length", 15.0)
    para_length = avg_sent * max_para_sentences * 0.7  # 近似

    return StyleMetrics(
        avg_sentence_length=_mid("avg_sentence_length", 15.0),
        dialogue_ratio=_mid("dialogue_ratio", 0.3),
        exclamation_ratio=_mid("exclamation_ratio", 0.05),
        paragraph_length=para_length,
        classical_word_ratio=_mid("classical_word_ratio", 0.0) if "classical_word_ratio" in constraints else None,
        description_ratio=None,
        first_person_ratio=_mid("first_person_ratio", 0.0) if "first_person_ratio" in constraints else None,
    )


# ---------------------------------------------------------------------------
# LangGraph 节点函数
# ---------------------------------------------------------------------------


def style_keeper_node(state: NovelState) -> dict[str, Any]:
    """LangGraph 节点：StyleKeeper。

    检查当前章节草稿的风格一致性。
    """
    decisions: list[Decision] = []
    errors: list[dict] = []

    chapter_text = state.get("current_chapter_text")
    if not chapter_text:
        return {
            "errors": [{"agent": "StyleKeeper", "message": "当前章节文本为空，跳过风格检查"}],
            "completed_nodes": ["style_keeper"],
        }

    # 获取风格名称：从 state 中组合
    style_cat = state.get("style_category", "")
    style_sub = state.get("style_subcategory", "")
    style_name = f"{style_cat}.{style_sub}" if style_cat and style_sub else None

    # 创建 StyleKeeper（LLM 可选，当前主要做规则检查）
    llm_config = state.get("config", {}).get("llm", {})
    try:
        llm = create_llm_client(llm_config)
    except Exception:
        llm = None

    keeper = StyleKeeper(llm)

    # 分析风格
    metrics = keeper.analyze_style(chapter_text)
    decisions.append(
        _make_decision(
            step="analyze_style",
            decision="风格分析完成",
            reason=f"avg_sentence_length={metrics.avg_sentence_length}, dialogue_ratio={metrics.dialogue_ratio}",
            data=metrics.model_dump(),
        )
    )

    # 风格对比（如有目标风格）
    similarity = None
    deviations: list[str] = []
    suggestions: list[str] = []

    if style_name:
        try:
            similarity, deviations = keeper.check_style(chapter_text, style_name)
            decisions.append(
                _make_decision(
                    step="check_style",
                    decision=f"风格相似度: {similarity:.2f}",
                    reason=f"与 {style_name} 对比，偏差 {len(deviations)} 项",
                    data={"similarity": similarity, "deviations": deviations},
                )
            )

            if deviations:
                suggestions = keeper.suggest_improvements(chapter_text, deviations)
        except KeyError as exc:
            errors.append({"agent": "StyleKeeper", "message": f"风格预设不存在: {exc}"})

    result: dict[str, Any] = {
        "decisions": decisions,
        "errors": errors,
        "completed_nodes": ["style_keeper"],
    }

    # 写入质量报告中的风格部分
    quality = dict(state.get("current_chapter_quality") or {})
    quality["style_metrics"] = metrics.model_dump()
    if similarity is not None:
        quality["style_similarity"] = similarity
        quality["style_deviations"] = deviations
        quality["style_suggestions"] = suggestions
    result["current_chapter_quality"] = quality

    return result
