"""一致性检查工具 - 封装 ConsistencyService，提供统一检测接口"""

from __future__ import annotations

import logging
from typing import Any

from src.novel.models.memory import Fact
from src.novel.services.consistency_service import ConsistencyService

log = logging.getLogger("novel")


class ConsistencyTool:
    """一致性检查工具

    封装 ConsistencyService，提供：
    - extract_facts: 从章节文本提取事实
    - check_consistency: 三层混合一致性检查
    """

    def __init__(self, llm_client: Any) -> None:
        self.service = ConsistencyService(llm_client)

    def extract_facts(
        self, chapter_text: str, chapter_number: int
    ) -> list[Fact]:
        """从章节文本提取关键事实。

        Args:
            chapter_text: 章节文本
            chapter_number: 章节号

        Returns:
            提取的事实列表
        """
        return self.service.extract_facts(chapter_text, chapter_number)

    def check_consistency(
        self, new_facts: list[Fact], memory: Any
    ) -> list[dict]:
        """执行三层混合一致性检查。

        依次执行：
        1. 结构化检查（SQLite）
        2. 知识图谱检查（NetworkX）
        3. 向量语义检查（Chroma，可选）

        合并所有检测结果，按 confidence 降序排列。

        Args:
            new_facts: 新提取的事实列表
            memory: NovelMemory 实例

        Returns:
            合并后的矛盾列表，按 confidence 降序排列
        """
        all_contradictions: list[dict] = []

        # 第一层：结构化检查
        try:
            structured_results = self.service.check_structured(
                new_facts, memory.structured_db
            )
            all_contradictions.extend(structured_results)
        except Exception as exc:
            log.warning("结构化检查失败: %s", exc)

        # 第二层：知识图谱检查
        try:
            graph_results = self.service.check_graph(
                new_facts, memory.knowledge_graph
            )
            all_contradictions.extend(graph_results)
        except Exception as exc:
            log.warning("知识图谱检查失败: %s", exc)

        # 第三层：向量语义检查（可选，Chroma 不可用时优雅降级）
        if new_facts:
            # 用第一个事实的内容做语义搜索
            combined_text = " ".join(f.content for f in new_facts[:5])
            try:
                vector_results = self.service.check_vector(
                    combined_text, memory
                )
                all_contradictions.extend(vector_results)
            except Exception as exc:
                log.debug("向量检查不可用，跳过: %s", exc)

        # 按 confidence 降序排列
        all_contradictions.sort(
            key=lambda x: x.get("confidence", 0), reverse=True
        )

        return all_contradictions
