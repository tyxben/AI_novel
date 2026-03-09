"""LangGraph 工作流图构建"""
from __future__ import annotations

from src.agents.state import AgentState
from src.agents.utils import make_decision
from src.logger import log


def _make_skip_or_run(node_name: str, node_fn):
    """包装节点函数，支持断点续传跳过已完成节点。"""

    def wrapped(state: AgentState, config=None):
        completed = state.get("completed_nodes", [])
        if node_name in completed:
            log.info("[Resume] 跳过已完成节点: %s", node_name)
            return {
                "decisions": [
                    make_decision(
                        node_name, "skip", f"断点续传跳过 {node_name}", "已完成"
                    )
                ],
                "completed_nodes": [node_name],
            }

        result = node_fn(state)
        # operator.add reducer 会累积，所以只需返回当前节点名
        result["completed_nodes"] = [node_name]

        # 保存中间状态（通过 configurable 传入的 pipeline 实例）
        if config and "configurable" in config:
            pipeline = config["configurable"].get("pipeline")
            if pipeline:
                # 合并当前结果到 state 用于保存
                merged = dict(state)
                for k, v in result.items():
                    if k in ("decisions", "errors", "completed_nodes"):
                        # 这些字段使用 operator.add reducer，需要合并列表
                        existing = merged.get(k, [])
                        merged[k] = existing + v
                    else:
                        merged[k] = v
                pipeline._save_state(merged)

        return result

    return wrapped


def create_agent_graph(config: dict):
    """构建并编译 Agent 工作流图"""
    from langgraph.graph import StateGraph, END

    from src.agents.director import director_node
    from src.agents.content_analyzer import content_analyzer_node
    from src.agents.art_director import art_director_node
    from src.agents.voice_director import voice_director_node
    from src.agents.editor import editor_node

    graph = StateGraph(AgentState)

    # 添加节点（用 wrapper 包装，支持断点续传跳过）
    graph.add_node("director", _make_skip_or_run("director", director_node))
    graph.add_node(
        "content_analyzer",
        _make_skip_or_run("content_analyzer", content_analyzer_node),
    )
    graph.add_node(
        "art_director", _make_skip_or_run("art_director", art_director_node)
    )
    graph.add_node(
        "voice_director",
        _make_skip_or_run("voice_director", voice_director_node),
    )
    graph.add_node("editor", _make_skip_or_run("editor", editor_node))

    # 定义流程
    graph.set_entry_point("director")
    graph.add_edge("director", "content_analyzer")
    graph.add_edge("content_analyzer", "art_director")
    graph.add_edge("art_director", "voice_director")
    graph.add_edge("voice_director", "editor")
    graph.add_edge("editor", END)

    return graph.compile()
