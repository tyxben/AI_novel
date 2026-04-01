"""Chroma 向量存储 - 事实和章节摘要的语义检索"""

from __future__ import annotations

from typing import Any

from src.novel.models.foreshadowing import DetailEntry
from src.novel.models.memory import Fact


def _get_chromadb():
    """懒加载 chromadb，未安装时给出友好提示"""
    try:
        import chromadb

        return chromadb
    except ImportError:
        raise ImportError(
            "chromadb 未安装。请运行: pip install chromadb\n"
            "或安装完整依赖: pip install -e '.[all]'"
        )


class VectorStore:
    """Chroma 向量存储管理

    封装 chromadb 的 PersistentClient，支持事实和闲笔的语义检索。
    chromadb 做懒加载，未安装时给出友好提示。
    """

    def __init__(self, persist_directory: str) -> None:
        self._persist_directory = persist_directory
        self._client: Any = None
        self._collection: Any = None

    def _ensure_client(self) -> None:
        """确保 client 已初始化（懒加载）"""
        if self._client is None:
            chromadb = _get_chromadb()
            from chromadb.config import Settings

            self._client = chromadb.PersistentClient(
                path=self._persist_directory,
                settings=Settings(anonymized_telemetry=False),
            )

    def create_collection(self, novel_id: str) -> None:
        """创建或获取集合"""
        self._ensure_client()
        self._collection = self._client.get_or_create_collection(
            name=f"novel_{novel_id}",
            metadata={"hnsw:space": "cosine"},
        )

    def _ensure_collection(self) -> None:
        """确保 collection 已创建"""
        if self._collection is None:
            raise RuntimeError(
                "VectorStore collection 未初始化，请先调用 create_collection()"
            )

    def add_fact(self, fact: Fact) -> None:
        """添加事实向量"""
        self._ensure_collection()
        self._collection.add(
            documents=[fact.content],
            metadatas=[
                {
                    "chapter": fact.chapter,
                    "type": fact.type,
                    "fact_id": fact.fact_id,
                }
            ],
            ids=[fact.fact_id],
        )

    def add_detail(self, detail: DetailEntry) -> None:
        """添加闲笔条目（后置伏笔）"""
        self._ensure_collection()
        self._collection.add(
            documents=[detail.content],
            metadatas=[
                {
                    "chapter": detail.chapter,
                    "category": detail.category,
                    "detail_id": detail.detail_id,
                    "type": "detail",
                }
            ],
            ids=[detail.detail_id],
        )

    def add_chapter_summary(
        self, chapter: int, summary: str, summary_id: str
    ) -> None:
        """添加章节摘要向量"""
        self._ensure_collection()
        self._collection.add(
            documents=[summary],
            metadatas=[
                {
                    "chapter": chapter,
                    "type": "chapter_summary",
                }
            ],
            ids=[summary_id],
        )

    def search_similar_facts(
        self,
        query: str,
        n_results: int = 5,
        filter_type: str | None = None,
    ) -> dict[str, Any]:
        """向量检索相似事实

        Returns:
            chromadb query result dict with keys:
            ids, documents, metadatas, distances
        """
        self._ensure_collection()
        where = {"type": filter_type} if filter_type else None
        results = self._collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
        )
        return results

    def search_potential_details(
        self,
        query: str,
        category: str | None = None,
        n_results: int = 5,
    ) -> dict[str, Any]:
        """检索潜在可利用的闲笔（后置伏笔）"""
        self._ensure_collection()
        where: dict[str, Any] = {"type": "detail"}
        if category:
            where = {"$and": [{"type": "detail"}, {"category": category}]}

        results = self._collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
        )
        return results

    def count(self) -> int:
        """返回集合中的文档数量"""
        self._ensure_collection()
        return self._collection.count()

    def close(self) -> None:
        """释放资源"""
        if self._client is not None:
            if hasattr(self._client, "close"):
                try:
                    self._client.close()
                except Exception:
                    pass
        self._collection = None
        self._client = None

    def __enter__(self) -> "VectorStore":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
