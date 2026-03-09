"""LangGraph 工作流图构建"""
from __future__ import annotations

from src.agents.state import AgentState


def create_agent_graph(config: dict):
    """构建并编译 Agent 工作流图"""
    from langgraph.graph import StateGraph, END

    from src.agents.director import director_node
    from src.agents.content_analyzer import content_analyzer_node
    from src.agents.art_director import art_director_node
    from src.agents.voice_director import voice_director_node
    from src.agents.editor import editor_node

    graph = StateGraph(AgentState)

    # 添加节点
    graph.add_node("director", director_node)
    graph.add_node("content_analyzer", content_analyzer_node)
    graph.add_node("art_director", art_director_node)
    graph.add_node("voice_director", voice_director_node)
    graph.add_node("editor", editor_node)

    # 定义流程
    graph.set_entry_point("director")
    graph.add_edge("director", "content_analyzer")
    graph.add_edge("content_analyzer", "art_director")
    graph.add_edge("art_director", "voice_director")
    graph.add_edge("voice_director", "editor")
    graph.add_edge("editor", END)

    return graph.compile()
