"""LangGraph 图构建 - 小说创作流水线

两种图：
- init graph: novel_director -> world_builder -> character_designer -> END
- chapter graph: plot_planner -> writer -> consistency_checker -> style_keeper -> quality_reviewer -> END (或回到 writer 重写)

LangGraph 为可选依赖。如果未安装，提供 sequential fallback。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    from src.novel.agents.plot_planner import plot_planner_node
    from src.novel.agents.writer import writer_node
    from src.novel.agents.consistency_checker import consistency_checker_node
    from src.novel.agents.style_keeper import style_keeper_node
    from src.novel.agents.quality_reviewer import quality_reviewer_node

    return {
        "novel_director": novel_director_node,
        "world_builder": world_builder_node,
        "character_designer": character_designer_node,
        "plot_planner": plot_planner_node,
        "writer": writer_node,
        "consistency_checker": consistency_checker_node,
        "style_keeper": style_keeper_node,
        "quality_reviewer": quality_reviewer_node,
    }


# ---------------------------------------------------------------------------
# Conditional edge: should rewrite?
# ---------------------------------------------------------------------------

MAX_REWRITES = 2


def _should_rewrite(state: dict) -> str:
    """Conditional edge after quality_reviewer.

    Returns "writer" if rewrite needed and under max retries,
    otherwise returns "end".
    """
    quality = state.get("current_chapter_quality") or {}
    need_rewrite = quality.get("need_rewrite", False)

    if not need_rewrite:
        return "end"

    current_chapter = state.get("current_chapter", 1)
    retry_counts = state.get("retry_counts") or {}
    retries = retry_counts.get(current_chapter, 0)
    max_retries = state.get("max_retries", MAX_REWRITES)

    if retries >= max_retries:
        log.info(
            "第%d章已重试%d次，达到上限，强制通过",
            current_chapter,
            retries,
        )
        return "end"

    log.info("第%d章质量未通过，触发重写（第%d次）", current_chapter, retries + 1)
    return "writer"


# ---------------------------------------------------------------------------
# Build init graph
# ---------------------------------------------------------------------------


def build_init_graph() -> Any:
    """Build the initialization graph (outline + world + characters).

    Returns a compiled LangGraph graph, or a _SequentialRunner fallback.
    """
    nodes = _get_node_functions()

    if _LANGGRAPH_AVAILABLE:
        graph = StateGraph(NovelState)
        graph.add_node("novel_director", nodes["novel_director"])
        graph.add_node("world_builder", nodes["world_builder"])
        graph.add_node("character_designer", nodes["character_designer"])

        graph.set_entry_point("novel_director")
        graph.add_edge("novel_director", "world_builder")
        graph.add_edge("world_builder", "character_designer")
        graph.add_edge("character_designer", END)

        return graph.compile()

    # Fallback: sequential runner
    return _SequentialRunner(
        [
            ("novel_director", nodes["novel_director"]),
            ("world_builder", nodes["world_builder"]),
            ("character_designer", nodes["character_designer"]),
        ]
    )


# ---------------------------------------------------------------------------
# Build chapter graph
# ---------------------------------------------------------------------------


def build_chapter_graph() -> Any:
    """Build the per-chapter generation graph.

    Flow: plot_planner -> writer -> consistency_checker -> style_keeper -> quality_reviewer
    quality_reviewer -> END (pass) or writer (rewrite, max 2)

    Returns a compiled LangGraph graph, or a _SequentialRunner fallback.
    """
    nodes = _get_node_functions()

    if _LANGGRAPH_AVAILABLE:
        graph = StateGraph(NovelState)
        graph.add_node("plot_planner", nodes["plot_planner"])
        graph.add_node("writer", nodes["writer"])
        graph.add_node("consistency_checker", nodes["consistency_checker"])
        graph.add_node("style_keeper", nodes["style_keeper"])
        graph.add_node("quality_reviewer", nodes["quality_reviewer"])

        graph.set_entry_point("plot_planner")
        graph.add_edge("plot_planner", "writer")
        graph.add_edge("writer", "consistency_checker")
        graph.add_edge("consistency_checker", "style_keeper")
        graph.add_edge("style_keeper", "quality_reviewer")

        graph.add_conditional_edges(
            "quality_reviewer",
            _should_rewrite,
            {"end": END, "writer": "writer"},
        )

        return graph.compile()

    # Fallback: sequential runner with rewrite loop
    return _ChapterRunner(
        nodes={
            "plot_planner": nodes["plot_planner"],
            "writer": nodes["writer"],
            "consistency_checker": nodes["consistency_checker"],
            "style_keeper": nodes["style_keeper"],
            "quality_reviewer": nodes["quality_reviewer"],
        },
        max_rewrites=MAX_REWRITES,
    )


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
    """Fallback for init graph when LangGraph is not installed."""

    def __init__(self, steps: list[tuple[str, Callable]]) -> None:
        self.steps = steps

    def invoke(self, state: dict) -> dict:
        current_state = dict(state)
        for name, node_fn in self.steps:
            log.info("执行节点: %s (fallback)", name)
            try:
                result = node_fn(current_state)
                current_state = _merge_state(current_state, result)
            except Exception as exc:
                log.error("节点 %s 执行失败: %s", name, exc)
                current_state = _merge_state(
                    current_state,
                    {
                        "errors": [{"agent": name, "message": str(exc)}],
                    },
                )
        return current_state


class _ChapterRunner:
    """Fallback for chapter graph with rewrite loop."""

    def __init__(self, nodes: dict[str, Callable], max_rewrites: int = 2) -> None:
        self.nodes = nodes
        self.max_rewrites = max_rewrites

    def invoke(self, state: dict) -> dict:
        current_state = dict(state)

        # Step 1: plot_planner
        current_state = self._run_node("plot_planner", current_state)

        # Step 2-5: writer -> checkers loop
        for attempt in range(self.max_rewrites + 1):
            current_state = self._run_node("writer", current_state)

            # C1 fix: skip checker nodes if writer produced no text
            if not current_state.get("current_chapter_text"):
                log.error("Writer 未产生文本，跳过检查节点")
                break

            current_state = self._run_parallel_checkers(current_state)
            current_state = self._run_node("quality_reviewer", current_state)

            # Check if rewrite needed
            route = _should_rewrite(current_state)
            if route == "end":
                break
            log.info("重写循环第%d次", attempt + 1)

        return current_state

    def _run_parallel_checkers(self, state: dict) -> dict:
        """Run consistency_checker and style_keeper in parallel."""
        checker_names = ["consistency_checker", "style_keeper"]
        results = {}

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(self.nodes[name], state): name
                for name in checker_names
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception as exc:
                    log.error("节点 %s 执行失败: %s", name, exc)
                    results[name] = {
                        "errors": [{"agent": name, "message": str(exc)}],
                    }

        current = dict(state)
        for name in checker_names:
            if name in results:
                current = _merge_state(current, results[name])
        return current

    def _run_node(self, name: str, state: dict) -> dict:
        node_fn = self.nodes[name]
        try:
            result = node_fn(state)
            return _merge_state(state, result)
        except Exception as exc:
            log.error("节点 %s 执行失败: %s", name, exc)
            return _merge_state(
                state,
                {
                    "errors": [{"agent": name, "message": str(exc)}],
                },
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_langgraph_available() -> bool:
    """Check if LangGraph is installed."""
    return _LANGGRAPH_AVAILABLE
