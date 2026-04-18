"""LangGraph 图构建 - 小说创作流水线

Chapter graph (Phase 2-β 合并后)::

    dynamic_outline -> plot_planner -> writer -> reviewer -> state_writeback -> END

``reviewer`` 节点是三合一产物：取代了
``consistency_checker + style_keeper + quality_reviewer``，零打分零自动重写。
Reviewer 只产报告（``CritiqueResult``）写进 ``state["current_chapter_quality"]``，
然后由 state_writeback 持久化。作者看报告后主动决定是否调 ``apply_feedback`` /
``rewrite_chapter`` 工具改文。

LangGraph 为可选依赖。如果未安装，提供 sequential fallback。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from src.novel.agents.state import NovelState

log = logging.getLogger("novel")

# ---------------------------------------------------------------------------
# Lazy LangGraph import
# ---------------------------------------------------------------------------

_LANGGRAPH_AVAILABLE = False

try:
    from langgraph.graph import END, StateGraph

    _LANGGRAPH_AVAILABLE = True
except ImportError:
    log.debug("langgraph 未安装，将使用顺序执行 fallback")

# ---------------------------------------------------------------------------
# Node imports (lazy, to avoid circular)
# ---------------------------------------------------------------------------


def _get_node_functions() -> dict[str, Callable]:
    """延迟导入所有节点函数，避免模块级循环依赖。"""
    from src.novel.agents.novel_director import novel_director_node
    from src.novel.agents.world_builder import world_builder_node
    from src.novel.agents.character_designer import character_designer_node
    from src.novel.agents.dynamic_outline import dynamic_outline_node
    from src.novel.agents.plot_planner import plot_planner_node
    from src.novel.agents.writer import writer_node
    from src.novel.agents.reviewer import reviewer_node
    from src.novel.agents.state_writeback import state_writeback_node

    return {
        "novel_director": novel_director_node,
        "world_builder": world_builder_node,
        "character_designer": character_designer_node,
        "dynamic_outline": dynamic_outline_node,
        "plot_planner": plot_planner_node,
        "writer": writer_node,
        "reviewer": reviewer_node,
        "state_writeback": state_writeback_node,
    }


# ---------------------------------------------------------------------------
# Build chapter graph
# ---------------------------------------------------------------------------


def build_chapter_graph() -> Any:
    """Build the per-chapter generation graph.

    Flow::

        dynamic_outline -> plot_planner -> writer -> reviewer -> state_writeback -> END

    Reviewer 是合并后的单节点（取代 consistency_checker + style_keeper +
    quality_reviewer）。只产报告（``CritiqueResult``），不触发 Writer 回写。
    """
    nodes = _get_node_functions()

    if _LANGGRAPH_AVAILABLE:
        graph = StateGraph(NovelState)
        graph.add_node("dynamic_outline", nodes["dynamic_outline"])
        graph.add_node("plot_planner", nodes["plot_planner"])
        graph.add_node("writer", nodes["writer"])
        graph.add_node("reviewer", nodes["reviewer"])
        graph.add_node("state_writeback", nodes["state_writeback"])

        graph.set_entry_point("dynamic_outline")
        graph.add_edge("dynamic_outline", "plot_planner")
        graph.add_edge("plot_planner", "writer")
        graph.add_edge("writer", "reviewer")
        graph.add_edge("reviewer", "state_writeback")
        graph.add_edge("state_writeback", END)

        return graph.compile()

    # Fallback: sequential runner (single pass, 无重写循环)
    fallback_nodes = {
        "plot_planner": nodes["plot_planner"],
        "writer": nodes["writer"],
        "reviewer": nodes["reviewer"],
    }
    if "dynamic_outline" in nodes:
        fallback_nodes["dynamic_outline"] = nodes["dynamic_outline"]
    if "state_writeback" in nodes:
        fallback_nodes["state_writeback"] = nodes["state_writeback"]

    return _ChapterRunner(nodes=fallback_nodes)


# ---------------------------------------------------------------------------
# Sequential fallback runners
# ---------------------------------------------------------------------------


def _merge_state(base: dict, update: dict) -> dict:
    """Merge node output into state, respecting Annotated[list, operator.add] fields."""
    additive_fields = {"decisions", "errors", "completed_nodes"}
    merged = dict(base)
    for key, value in update.items():
        if key in additive_fields and isinstance(value, list):
            existing = merged.get(key, [])
            if isinstance(existing, list):
                merged[key] = existing + value
            else:
                merged[key] = value
        else:
            merged[key] = value
    return merged


class _SequentialRunner:
    """Fallback sequential runner when LangGraph is not installed."""

    def __init__(self, steps: list[tuple[str, Callable]]) -> None:
        self.steps = steps

    def invoke(self, state: dict) -> dict:
        current_state = dict(state)
        for name, node_fn in self.steps:
            log.info("执行节点: %s (fallback)", name)
            try:
                result = node_fn(current_state)
                if "completed_nodes" not in result:
                    result["completed_nodes"] = [name]
                current_state = _merge_state(current_state, result)
            except Exception as exc:
                log.error("节点 %s 执行失败: %s", name, exc)
                current_state = _merge_state(
                    current_state,
                    {"errors": [{"agent": name, "message": str(exc)}]},
                )
        return current_state


class _ChapterRunner:
    """Fallback for chapter graph — single linear pass, 无重写循环。

    Phase 2-β: reviewer 单节点，只产报告不触发 writer 回写。
    """

    def __init__(self, nodes: dict[str, Callable]) -> None:
        self.nodes = nodes

    def invoke(self, state: dict) -> dict:
        current_state = dict(state)

        if "dynamic_outline" in self.nodes:
            current_state = self._run_node("dynamic_outline", current_state)

        current_state = self._run_node("plot_planner", current_state)
        current_state = self._run_node("writer", current_state)

        if current_state.get("current_chapter_text"):
            current_state = self._run_node("reviewer", current_state)
        else:
            log.error("Writer 未产生文本，跳过 reviewer 节点")

        if "state_writeback" in self.nodes:
            current_state = self._run_node("state_writeback", current_state)

        return current_state

    def _run_node(self, name: str, state: dict) -> dict:
        node_fn = self.nodes[name]
        try:
            result = node_fn(state)
            if "completed_nodes" not in result:
                result["completed_nodes"] = [name]
            return _merge_state(state, result)
        except Exception as exc:
            log.error("节点 %s 执行失败: %s", name, exc)
            return _merge_state(
                state,
                {"errors": [{"agent": name, "message": str(exc)}]},
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_langgraph_available() -> bool:
    """Check if LangGraph is installed."""
    return _LANGGRAPH_AVAILABLE
