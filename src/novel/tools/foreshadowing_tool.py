"""伏笔管理工具 - 封装 ForeshadowingService，提供统一的闲笔提取/检索/升级接口"""

from __future__ import annotations

import logging
from typing import Any

from src.novel.models.foreshadowing import DetailEntry, Foreshadowing
from src.novel.services.foreshadowing_service import ForeshadowingService

log = logging.getLogger("novel")


class ForeshadowingTool:
    """伏笔管理工具

    封装 ForeshadowingService，提供：
    - extract_details: 从章节文本提取潜在可利用的闲笔细节
    - search_reusable_details: 反向检索历史闲笔
    - promote_to_foreshadowing: 将闲笔升级为正式伏笔
    - verify_foreshadowings: 验证伏笔是否在文本中执行
    - get_forgotten: 获取即将遗忘的伏笔
    """

    def __init__(self, service: ForeshadowingService) -> None:
        self.service = service

    @classmethod
    def from_components(
        cls,
        knowledge_graph: Any,
        llm_client: Any = None,
        novel_memory: Any = None,
    ) -> "ForeshadowingTool":
        """从组件创建工具实例。

        Args:
            knowledge_graph: KnowledgeGraph 实例
            llm_client: LLM 客户端（可选，extract_details 需要）
            novel_memory: NovelMemory 实例（可选，search/promote 需要）

        Returns:
            ForeshadowingTool 实例
        """
        service = ForeshadowingService(
            knowledge_graph=knowledge_graph,
            llm_client=llm_client,
            novel_memory=novel_memory,
        )
        return cls(service)

    def extract_details(
        self, chapter_text: str, chapter_number: int
    ) -> list[DetailEntry]:
        """从章节文本提取潜在可利用的闲笔细节。

        Args:
            chapter_text: 章节文本
            chapter_number: 章节号

        Returns:
            提取的 DetailEntry 列表
        """
        return self.service.extract_details(chapter_text, chapter_number)

    def search_reusable_details(
        self,
        query: str,
        current_chapter: int,
        top_k: int = 5,
        category: str | None = None,
    ) -> list[DetailEntry]:
        """反向检索：从历史闲笔中查找可利用的细节。

        Args:
            query: 检索查询
            current_chapter: 当前章节号
            top_k: 返回数量上限
            category: 可选类别过滤

        Returns:
            匹配的 DetailEntry 列表
        """
        return self.service.search_reusable_details(
            query=query,
            current_chapter=current_chapter,
            top_k=top_k,
            category=category,
        )

    def promote_to_foreshadowing(
        self,
        detail_id: str,
        resolution_plan: str,
        target_chapter: int,
        detail: DetailEntry | None = None,
    ) -> Foreshadowing:
        """将闲笔升级为正式伏笔。

        Args:
            detail_id: 闲笔条目 ID
            resolution_plan: 回收计划描述
            target_chapter: 计划回收的章节号
            detail: 可选，直接传入 DetailEntry 对象

        Returns:
            创建的 Foreshadowing 对象

        Raises:
            ValueError: detail_id 不存在或已被升级
        """
        return self.service.promote_to_foreshadowing(
            detail_id=detail_id,
            resolution_plan=resolution_plan,
            target_chapter=target_chapter,
            detail=detail,
        )

    def verify_foreshadowings(
        self,
        chapter_text: str,
        chapter_number: int,
        planned_plants: list[str],
        planned_collects: list[str],
    ) -> dict[str, Any]:
        """验证伏笔是否在文本中执行。

        Args:
            chapter_text: 章节文本
            chapter_number: 章节号
            planned_plants: 计划埋设的伏笔列表
            planned_collects: 计划回收的伏笔列表

        Returns:
            验证结果字典
        """
        return self.service.verify_foreshadowings_in_text(
            chapter_text=chapter_text,
            chapter_number=chapter_number,
            planned_plants=planned_plants,
            planned_collects=planned_collects,
        )

    def get_forgotten(
        self,
        current_chapter: int,
        threshold: int = 10,
    ) -> list[dict]:
        """获取即将遗忘的伏笔列表。

        Args:
            current_chapter: 当前章节号
            threshold: 遗忘阈值（默认10章）

        Returns:
            满足遗忘条件的伏笔列表
        """
        return self.service.get_forgotten_foreshadowings(
            current_chapter=current_chapter,
            threshold=threshold,
        )
