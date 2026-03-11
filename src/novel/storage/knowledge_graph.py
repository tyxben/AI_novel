"""NetworkX 知识图谱 - 角色关系、阵营、地点"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx
from networkx.readwrite import json_graph


class KnowledgeGraph:
    """NetworkX 知识图谱管理

    使用 MultiDiGraph 支持同一对节点间的多条有向边。
    序列化采用 JSON 格式（比 pickle 更安全、可读）。
    """

    def __init__(self) -> None:
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()

    # ========== 节点操作 ==========

    def add_character(self, character_id: str, name: str, **attrs: Any) -> None:
        """添加角色节点"""
        self.graph.add_node(
            character_id, type="character", name=name, **attrs
        )

    def add_faction(self, faction_id: str, name: str, **attrs: Any) -> None:
        """添加阵营/势力节点"""
        self.graph.add_node(
            faction_id, type="faction", name=name, **attrs
        )

    def add_location(self, location_id: str, name: str, **attrs: Any) -> None:
        """添加地点节点"""
        self.graph.add_node(
            location_id, type="location", name=name, **attrs
        )

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """获取节点属性"""
        if node_id not in self.graph:
            return None
        return dict(self.graph.nodes[node_id])

    def get_nodes_by_type(self, node_type: str) -> list[dict[str, Any]]:
        """按类型获取所有节点"""
        results = []
        for node_id, attrs in self.graph.nodes(data=True):
            if attrs.get("type") == node_type:
                results.append({"id": node_id, **attrs})
        return results

    # ========== 边操作 ==========

    def add_relationship(
        self,
        char1_id: str,
        char2_id: str,
        rel_type: str,
        intensity: int,
        chapter: int,
        **attrs: Any,
    ) -> None:
        """添加角色关系边"""
        key = f"{rel_type}_{chapter}"
        self.graph.add_edge(
            char1_id,
            char2_id,
            key=key,
            edge_type="relationship",
            type=rel_type,
            intensity=intensity,
            chapter=chapter,
            **attrs,
        )

    def add_affiliation(
        self,
        character_id: str,
        faction_id: str,
        role: str = "member",
        chapter: int = 1,
        **attrs: Any,
    ) -> None:
        """添加角色-阵营隶属边"""
        key = f"affiliation_{chapter}"
        self.graph.add_edge(
            character_id,
            faction_id,
            key=key,
            edge_type="affiliation",
            role=role,
            chapter=chapter,
            **attrs,
        )

    def add_location_transition(
        self,
        loc1_id: str,
        loc2_id: str,
        distance: str = "",
        chapter: int = 1,
        **attrs: Any,
    ) -> None:
        """添加地点间过渡边"""
        key = f"transition_{chapter}"
        self.graph.add_edge(
            loc1_id,
            loc2_id,
            key=key,
            edge_type="transition",
            distance=distance,
            chapter=chapter,
            **attrs,
        )

    # ========== 查询 ==========

    def get_relationships(self, character_id: str) -> list[dict[str, Any]]:
        """查询角色的所有关系（出边 + 入边）"""
        if character_id not in self.graph:
            return []

        results: list[dict[str, Any]] = []

        # 出边
        for _, target, _key, data in self.graph.out_edges(
            character_id, data=True, keys=True
        ):
            if data.get("edge_type") == "relationship":
                results.append({"source": character_id, "target": target, **data})

        # 入边
        for source, _, _key, data in self.graph.in_edges(
            character_id, data=True, keys=True
        ):
            if data.get("edge_type") == "relationship":
                results.append({"source": source, "target": character_id, **data})

        return results

    def get_latest_relationship(
        self, char1_id: str, char2_id: str
    ) -> dict[str, Any] | None:
        """获取两个角色之间最新的关系"""
        edges = []
        if self.graph.has_node(char1_id) and self.graph.has_node(char2_id):
            # 双向查找
            for u, v in [(char1_id, char2_id), (char2_id, char1_id)]:
                if self.graph.has_edge(u, v):
                    for _key, data in self.graph[u][v].items():
                        if data.get("edge_type") == "relationship":
                            edges.append(
                                {"source": u, "target": v, **data}
                            )
        if not edges:
            return None
        return max(edges, key=lambda e: e.get("chapter", 0))

    def find_shortest_path(
        self, loc1: str, loc2: str
    ) -> list[str] | None:
        """查找地点间最短路径"""
        try:
            return nx.shortest_path(self.graph, loc1, loc2)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def get_faction_members(self, faction_id: str) -> list[str]:
        """查询阵营成员（所有 affiliation 入边的来源节点）"""
        if faction_id not in self.graph:
            return []
        members = []
        for source, _, _key, data in self.graph.in_edges(
            faction_id, data=True, keys=True
        ):
            if data.get("edge_type") == "affiliation":
                members.append(source)
        return members

    # ========== 序列化 ==========

    def save(self, path: str) -> None:
        """保存为 JSON 文件"""
        data = json_graph.node_link_data(self.graph)
        file_path = Path(path)
        # 使用 .json 后缀，即使传入 .pkl 也写 JSON
        if file_path.suffix == ".pkl":
            file_path = file_path.with_suffix(".json")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "KnowledgeGraph":
        """从 JSON 文件加载"""
        kg = cls()
        file_path = Path(path)
        # 兼容 .pkl 后缀（实际存 .json）
        if file_path.suffix == ".pkl":
            json_path = file_path.with_suffix(".json")
            if json_path.exists():
                file_path = json_path
        if not file_path.exists():
            return kg
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        kg.graph = json_graph.node_link_graph(data, multigraph=True, directed=True)
        return kg

    def close(self) -> None:
        """释放资源（NetworkX 是内存图，清空即可）"""
        self.graph.clear()

    def __enter__(self) -> "KnowledgeGraph":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
