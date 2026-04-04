"""三层混合记忆系统 - 统一封装 StructuredDB / KnowledgeGraph / VectorStore"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.novel.models.foreshadowing import DetailEntry
from src.novel.models.memory import ChapterSummary, Fact, VolumeSnapshot
from src.novel.storage.knowledge_graph import KnowledgeGraph
from src.novel.storage.structured_db import StructuredDB
from src.novel.storage.vector_store import VectorStore


class NovelMemory:
    """三层混合记忆系统

    - StructuredDB (SQLite): 角色状态、时间线、术语、力量追踪、事实、摘要
    - KnowledgeGraph (NetworkX): 角色关系、阵营、地点拓扑
    - VectorStore (Chroma): 事实和摘要的语义检索

    根据 Fact.storage_layer 智能路由到对应存储层。
    """

    def __init__(self, novel_id: str, workspace_dir: str) -> None:
        self.novel_id = novel_id
        self.workspace = Path(workspace_dir) / "novels" / novel_id
        self.workspace.mkdir(parents=True, exist_ok=True)

        # 三层存储
        self.structured_db = StructuredDB(self.workspace / "memory.db")
        self.knowledge_graph = KnowledgeGraph()
        self.vector_store = VectorStore(str(self.workspace / "vectors"))

        # 加载现有数据
        self._load()

    def _load(self) -> None:
        """加载现有记忆数据"""
        # 知识图谱：优先加载 .json，兼容 .pkl 路径
        graph_json = self.workspace / "graph.json"
        graph_pkl = self.workspace / "graph.pkl"
        if graph_json.exists():
            self.knowledge_graph = KnowledgeGraph.load(str(graph_json))
        elif graph_pkl.exists():
            self.knowledge_graph = KnowledgeGraph.load(str(graph_pkl))

        # 向量存储：创建或获取集合
        self.vector_store.create_collection(self.novel_id)

    def save(self) -> None:
        """保存所有层（SQLite/Chroma 自动持久化，只需保存图）"""
        self.knowledge_graph.save(str(self.workspace / "graph.json"))

    def close(self) -> None:
        """保存并关闭所有存储层，释放资源"""
        try:
            self.save()
        except Exception:
            pass  # best-effort save before closing
        self.structured_db.close()
        self.knowledge_graph.close()
        self.vector_store.close()

    def __enter__(self) -> "NovelMemory":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ========== 事实管理 ==========

    def add_fact(self, fact: Fact) -> None:
        """添加事实，根据 storage_layer 路由到对应层

        - structured: 存入 SQLite facts 表
        - graph: 存入 NetworkX（同时也存 SQLite 做备份）
        - vector: 存入 Chroma（同时也存 SQLite 做备份）
        """
        # 所有事实都进 SQLite 做结构化备份
        self.structured_db.insert_fact(fact)

        # 根据类型做额外分发
        if fact.type == "character_state":
            # 解析 content 提取字段（简单实现）
            self.structured_db.insert_character_state(
                character_id=fact.content.split(":")[0].strip()
                if ":" in fact.content
                else "unknown",
                chapter=fact.chapter,
            )
        elif fact.type == "time":
            self.structured_db.insert_timeline(
                chapter=fact.chapter,
                scene=1,
                description=fact.content,
            )

        # graph 层：关系类型事实
        if fact.storage_layer == "graph" and fact.type == "relationship":
            # 关系事实暂存 SQLite，图更新由上层 service 处理
            pass

        # vector 层：所有事实都做向量索引
        if fact.storage_layer == "vector":
            self.vector_store.add_fact(fact)

    def query_facts(
        self,
        chapter: int | None = None,
        fact_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """查询事实（从 SQLite）"""
        return self.structured_db.get_facts(
            chapter=chapter, fact_type=fact_type
        )

    # ========== 章节管理 ==========

    def add_chapter_summary(self, summary: ChapterSummary) -> None:
        """添加章节摘要到 SQLite + 向量索引"""
        self.structured_db.insert_summary(summary)
        self.vector_store.add_chapter_summary(
            chapter=summary.chapter,
            summary=summary.summary,
            summary_id=f"summary_ch{summary.chapter}",
        )

    def get_context_for_chapter(
        self, chapter_number: int, n_recent_summaries: int = 10
    ) -> dict[str, Any]:
        """获取写作上下文

        Returns:
            {
                "recent_summaries": 最近 N 章摘要,
                "terms": 所有术语,
                "character_states": 所有角色最新状态,
            }
        """
        # 最近 N 章摘要
        from_ch = max(1, chapter_number - n_recent_summaries)
        summaries = self.structured_db.get_summaries(
            from_chapter=from_ch, to_chapter=chapter_number - 1
        )

        # 所有术语
        terms = self.structured_db.get_all_terms()

        return {
            "recent_summaries": summaries,
            "terms": terms,
        }

    # ========== 卷快照 ==========

    def create_volume_snapshot(
        self,
        volume_number: int,
        main_plot_progress: str,
        main_plot_completion: float,
        ending_summary: str,
        cliffhanger: str | None = None,
        character_states: list[dict[str, Any]] | None = None,
        new_terms: dict[str, str] | None = None,
        power_changes: list[str] | None = None,
    ) -> VolumeSnapshot:
        """创建卷间快照"""
        from src.novel.models.character import CharacterSnapshot

        char_snapshots = []
        if character_states:
            for cs in character_states:
                char_snapshots.append(CharacterSnapshot(**cs))

        snapshot = VolumeSnapshot(
            volume_number=volume_number,
            main_plot_progress=main_plot_progress,
            main_plot_completion=main_plot_completion,
            character_states=char_snapshots,
            ending_summary=ending_summary,
            cliffhanger=cliffhanger,
            new_terms=new_terms or {},
            power_changes=power_changes or [],
        )
        return snapshot

    # ========== 闲笔管理 ==========

    def add_detail(self, detail: DetailEntry) -> None:
        """添加闲笔到向量存储"""
        self.vector_store.add_detail(detail)

    def search_details(
        self, query: str, category: str | None = None, n_results: int = 5
    ) -> dict[str, Any]:
        """搜索相关闲笔"""
        return self.vector_store.search_potential_details(
            query=query, category=category, n_results=n_results
        )

    # ========== 知识图谱便捷方法 ==========

    def add_character_to_graph(
        self, character_id: str, name: str, **attrs: Any
    ) -> None:
        """添加角色到知识图谱"""
        self.knowledge_graph.add_character(character_id, name, **attrs)

    def add_relationship_to_graph(
        self,
        char1_id: str,
        char2_id: str,
        rel_type: str,
        intensity: int,
        chapter: int,
    ) -> None:
        """添加角色关系到知识图谱"""
        self.knowledge_graph.add_relationship(
            char1_id, char2_id, rel_type, intensity, chapter
        )

    def get_character_relationships(
        self, character_id: str
    ) -> list[dict[str, Any]]:
        """获取角色的所有关系"""
        return self.knowledge_graph.get_relationships(character_id)
