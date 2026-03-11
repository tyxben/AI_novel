"""FeedbackAnalyzer - 读者反馈分析 Agent

负责：
1. 分类反馈类型（角色/节奏/伏笔/对话/情节/风格）
2. 确定影响范围（哪些章节需要直接修改，哪些需要传播调整）
3. 生成逐章重写指令
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.novel.agents.state import Decision
from src.novel.utils import extract_json_from_llm

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
    """创建 FeedbackAnalyzer 的决策记录。"""
    return Decision(
        agent="FeedbackAnalyzer",
        step=step,
        decision=decision,
        reason=reason,
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# FeedbackAnalyzer Agent
# ---------------------------------------------------------------------------


class FeedbackAnalyzer:
    """读者反馈分析器"""

    def __init__(self, llm_client: Any) -> None:
        self.llm = llm_client

    def analyze(
        self,
        feedback_text: str,
        chapter_number: int | None,
        outline_chapters: list[dict],
        characters: list[dict],
        max_propagation: int = 10,
    ) -> dict:
        """分析反馈，返回 FeedbackAnalysis 格式的字典。

        Args:
            feedback_text: 读者反馈原文
            chapter_number: 反馈针对的章节号（None=全局）
            outline_chapters: 大纲章节列表 [{chapter_number, title, goal, involved_characters, ...}]
            characters: 角色列表 [{name, ...}]
            max_propagation: 最大传播章节数

        Returns:
            dict with keys: feedback_type, severity, target_chapters,
                propagation_chapters, rewrite_instructions, summary
        """
        # Build context about the novel structure
        chapters_summary = "\n".join(
            f"第{ch['chapter_number']}章「{ch.get('title', '')}」: {ch.get('goal', '')} "
            f"[角色: {', '.join(ch.get('involved_characters', []))}]"
            for ch in outline_chapters[:50]  # cap at 50
        )

        char_names = ", ".join(c.get("name", "?") for c in characters[:20])

        target_hint = (
            f"读者反馈针对第{chapter_number}章"
            if chapter_number
            else "读者给出的全局反馈"
        )

        prompt = f"""{target_hint}：
「{feedback_text}」

【小说章节结构】
{chapters_summary}

【主要角色】
{char_names}

请分析这条反馈，返回 JSON：
{{
    "feedback_type": "character|pacing|foreshadowing|dialogue|plot_hole|style|other",
    "severity": "low|medium|high",
    "target_chapters": [需要直接修改的章节号列表],
    "propagation_chapters": [下游需要微调的章节号列表，最多{max_propagation}个],
    "rewrite_instructions": {{
        "章节号": "该章的具体修改指令"
    }},
    "character_changes": [如需修改角色设定，列出修改项] 或 null,
    "summary": "一句话概括分析结果"
}}

分析要求：
1. target_chapters 只包含必须修改的章节（通常1-3章）
2. propagation_chapters 是受间接影响的后续章节（如角色性格改变影响后续互动）
3. rewrite_instructions 要具体可操作，不要泛泛而谈
4. 如果反馈指向全局问题（如"节奏太慢"），选择最关键的几章修改"""

        response = self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": "你是一位资深小说编辑。请分析读者反馈，制定精准的修改方案。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            json_mode=True,
            max_tokens=2048,
        )

        try:
            data = extract_json_from_llm(response.content)
        except (ValueError, AttributeError) as exc:
            log.warning("反馈分析 LLM 返回无法解析: %s", exc)
            # Fallback: just rewrite the target chapter
            target = [chapter_number] if chapter_number else []
            return {
                "feedback_type": "other",
                "severity": "medium",
                "target_chapters": target,
                "propagation_chapters": [],
                "rewrite_instructions": (
                    {str(chapter_number): feedback_text} if chapter_number else {}
                ),
                "character_changes": None,
                "summary": "LLM 分析失败，回退到直接重写",
            }

        # Validate and sanitize
        valid_types = {
            "character",
            "pacing",
            "foreshadowing",
            "dialogue",
            "plot_hole",
            "style",
            "other",
        }
        if data.get("feedback_type") not in valid_types:
            data["feedback_type"] = "other"
        if data.get("severity") not in {"low", "medium", "high"}:
            data["severity"] = "medium"

        # Ensure target_chapters are ints and within range
        total = len(outline_chapters)
        data["target_chapters"] = [
            int(ch)
            for ch in data.get("target_chapters", [])
            if isinstance(ch, (int, float)) and 1 <= int(ch) <= total
        ]
        data["propagation_chapters"] = [
            int(ch)
            for ch in data.get("propagation_chapters", [])
            if isinstance(ch, (int, float)) and 1 <= int(ch) <= total
        ][:max_propagation]

        # Ensure rewrite_instructions keys are strings of ints
        raw_instructions = data.get("rewrite_instructions", {})
        data["rewrite_instructions"] = {
            str(int(k)): v
            for k, v in raw_instructions.items()
            if str(k).isdigit()
        }

        return data


# ---------------------------------------------------------------------------
# LangGraph 节点函数
# ---------------------------------------------------------------------------


def feedback_analyzer_node(state: dict) -> dict:
    """LangGraph 节点：FeedbackAnalyzer。

    分析待处理的读者反馈，生成重写指令和影响范围。

    从 state 中读取:
    - feedback_entries: 反馈条目列表
    - config.llm: LLM 配置
    - outline.chapters: 大纲章节列表
    - characters: 角色列表

    更新 state:
    - feedback_analysis: 反馈分析结果
    - rewrite_queue: 需要重写的章节队列
    - rewrite_instructions: 逐章重写指令
    - decisions: 添加决策记录
    - errors: 添加错误信息（如有）
    - completed_nodes: 添加 "feedback_analyzer"
    """
    from src.llm.llm_client import create_llm_client

    decisions: list[Decision] = []
    errors: list[dict] = []

    feedback_entries = state.get("feedback_entries", [])
    pending = [f for f in feedback_entries if f.get("status") == "pending"]

    if not pending:
        return {
            "errors": [
                {"agent": "FeedbackAnalyzer", "message": "没有待处理的反馈"}
            ],
            "completed_nodes": ["feedback_analyzer"],
        }

    llm_config = state.get("config", {}).get("llm", {})
    try:
        llm = create_llm_client(llm_config)
    except Exception as exc:
        return {
            "errors": [
                {
                    "agent": "FeedbackAnalyzer",
                    "message": f"LLM 初始化失败: {exc}",
                }
            ],
            "completed_nodes": ["feedback_analyzer"],
        }

    analyzer = FeedbackAnalyzer(llm)
    outline_chapters = state.get("outline", {}).get("chapters", [])
    characters = state.get("characters", [])

    # Process the first pending feedback
    entry = pending[0]
    analysis = analyzer.analyze(
        feedback_text=entry["content"],
        chapter_number=entry.get("chapter_number"),
        outline_chapters=outline_chapters,
        characters=characters,
    )

    # Update feedback entry status
    entry["status"] = "analyzed"
    entry["feedback_type"] = analysis.get("feedback_type")

    # Build rewrite queue: target chapters first, then propagation
    rewrite_queue = sorted(
        set(
            analysis.get("target_chapters", [])
            + analysis.get("propagation_chapters", [])
        )
    )

    decisions.append(
        _make_decision(
            step="analyze_feedback",
            decision=f"反馈分析完成: {analysis.get('feedback_type', 'other')}",
            reason=analysis.get("summary", ""),
            data={
                "target_count": len(analysis.get("target_chapters", [])),
                "propagation_count": len(
                    analysis.get("propagation_chapters", [])
                ),
                "severity": analysis.get("severity"),
            },
        )
    )

    return {
        "feedback_analysis": analysis,
        "rewrite_queue": rewrite_queue,
        "rewrite_instructions": {
            int(k): v
            for k, v in analysis.get("rewrite_instructions", {}).items()
        },
        "decisions": decisions,
        "errors": errors,
        "completed_nodes": ["feedback_analyzer"],
    }
