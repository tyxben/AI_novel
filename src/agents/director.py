"""导演 Agent - 总控调度"""
from __future__ import annotations

from src.agents.state import AgentState
from src.agents.utils import make_decision
from src.logger import log


class DirectorAgent:
    """分析任务，编排流程，纯逻辑决策（不需要 LLM）"""

    def __init__(self, config: dict):
        self.config = config

    def analyze_task(self, state: AgentState) -> dict:
        text = state["full_text"]
        char_count = len(text)
        max_chars = self.config.get("segmenter", {}).get("max_chars", 100)
        estimated_segments = max(1, (char_count // max_chars) + 1)

        analysis_needed = not state.get("budget_mode", False) and char_count > 500
        video_enabled = bool(self.config.get("videogen", {}).get("backend"))

        return {
            "char_count": char_count,
            "segment_count": estimated_segments,
            "analysis_needed": analysis_needed,
            "video_enabled": video_enabled,
        }

    def estimate_cost(self, analysis: dict, budget_mode: bool) -> float:
        n = analysis["segment_count"]
        if budget_mode:
            return n * 0.0007  # DeepSeek 近似成本
        prompt_cost = n * 0.0001
        quality_cost = n * 0.01 * 1.5
        return prompt_cost + quality_cost


def director_node(state: AgentState) -> dict:
    """Director 节点 - LangGraph 节点函数"""
    config = state["config"]
    agent = DirectorAgent(config)

    analysis = agent.analyze_task(state)
    budget_mode = state.get("budget_mode", False)
    cost = agent.estimate_cost(analysis, budget_mode)

    decisions = [
        make_decision(
            "Director", "analyze",
            f"文本 {analysis['char_count']} 字, 预计 {analysis['segment_count']} 段",
            f"max_chars={config.get('segmenter', {}).get('max_chars', 100)}",
        ),
        make_decision(
            "Director", "plan",
            f"预估成本 ${cost:.3f}, 视频={'启用' if analysis['video_enabled'] else '关闭'}",
            "基于配置和文本长度",
        ),
    ]

    log.info(
        "[Director] 分析完成: %d 字, 预计 %d 段, 成本 $%.3f",
        analysis["char_count"],
        analysis["segment_count"],
        cost,
    )

    return {
        "pipeline_plan": {**analysis, "estimated_cost": cost},
        "decisions": decisions,
    }
