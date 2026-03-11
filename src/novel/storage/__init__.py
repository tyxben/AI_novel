"""小说模块存储层 - 统一导出"""

from src.novel.storage.file_manager import FileManager
from src.novel.storage.knowledge_graph import KnowledgeGraph
from src.novel.storage.novel_memory import NovelMemory
from src.novel.storage.structured_db import StructuredDB
from src.novel.storage.vector_store import VectorStore

__all__ = [
    "StructuredDB",
    "KnowledgeGraph",
    "VectorStore",
    "NovelMemory",
    "FileManager",
]
