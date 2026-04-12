"""伏笔图谱管理服务 (P1)

负责伏笔节点的注册、回收匹配、文本验证。
所有方法同步执行，不依赖 LLM（除非显式传入）。
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from src.novel.storage.knowledge_graph import KnowledgeGraph

log = logging.getLogger("novel.services.foreshadowing")


class ForeshadowingService:
    """伏笔图谱管理服务"""

    def __init__(
        self,
        knowledge_graph: "KnowledgeGraph",
        llm_client: Any = None,
    ) -> None:
        self.graph = knowledge_graph
        self.llm = llm_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_planned_foreshadowings(
        self,
        chapter_brief: dict,
        chapter_number: int,
    ) -> int:
        """从 chapter_brief 注册计划的伏笔。

        解析 ``foreshadowing_plant`` 和 ``foreshadowing_collect`` 字段，
        创建图节点和回收边。

        Returns:
            注册的伏笔数量
        """
        count = 0

        # --- 埋设伏笔 ---
        plants = chapter_brief.get("foreshadowing_plant", [])
        if isinstance(plants, str):
            plants = [plants]

        for plant in plants:
            if not plant or not isinstance(plant, str):
                continue
            fid = f"foreshadow_{chapter_number}_{uuid4().hex[:8]}"
            self.graph.add_foreshadowing_node(
                foreshadowing_id=fid,
                planted_chapter=chapter_number,
                content=plant,
                target_chapter=-1,
                status="pending",
            )
            count += 1
            log.info("伏笔节点已注册: %s (第%d章)", plant, chapter_number)

        # --- 回收伏笔（建立回收边） ---
        collects = chapter_brief.get("foreshadowing_collect", [])
        if isinstance(collects, str):
            collects = [collects]

        for collect in collects:
            if not collect or not isinstance(collect, str):
                continue
            matched = self._find_matching_foreshadowing(collect)
            if matched:
                self.graph.add_foreshadowing_edge(
                    from_id=matched["foreshadowing_id"],
                    to_id=f"collect_{chapter_number}_{uuid4().hex[:8]}",
                    relation_type="collect",
                    chapter=chapter_number,
                )
                self.graph.mark_foreshadowing_collected(
                    foreshadowing_id=matched["foreshadowing_id"],
                    collected_chapter=chapter_number,
                )
                log.info("伏笔回收: %s (第%d章)", collect, chapter_number)

        return count

    def verify_foreshadowings_in_text(
        self,
        chapter_text: str,
        chapter_number: int,
        planned_plants: list[str],
        planned_collects: list[str],
    ) -> dict[str, Any]:
        """验证伏笔是否真的在文本中执行。

        使用关键词匹配（不依赖 LLM）。

        Returns:
            {
                "plants_confirmed": list[str],
                "plants_missing": list[str],
                "collects_confirmed": list[str],
                "collects_missing": list[str],
            }
        """
        result: dict[str, list[str]] = {
            "plants_confirmed": [],
            "plants_missing": [],
            "collects_confirmed": [],
            "collects_missing": [],
        }

        for plant in planned_plants:
            if not plant or not isinstance(plant, str):
                continue
            keywords = self._extract_keywords(plant)
            if any(kw in chapter_text for kw in keywords):
                result["plants_confirmed"].append(plant)
            else:
                result["plants_missing"].append(plant)
                log.warning("伏笔埋设缺失: %s (第%d章)", plant, chapter_number)

        for collect in planned_collects:
            if not collect or not isinstance(collect, str):
                continue
            keywords = self._extract_keywords(collect)
            if any(kw in chapter_text for kw in keywords):
                result["collects_confirmed"].append(collect)
            else:
                result["collects_missing"].append(collect)
                log.warning("伏笔回收缺失: %s (第%d章)", collect, chapter_number)

        return result

    def get_forgotten_foreshadowings(
        self,
        current_chapter: int,
        threshold: int = 10,
    ) -> list[dict]:
        """获取即将遗忘的伏笔。

        Args:
            current_chapter: 当前章节号
            threshold: 遗忘阈值（默认10章）

        Returns:
            满足遗忘条件的伏笔列表
        """
        pending = self.graph.get_pending_foreshadowings(current_chapter)
        return [
            f for f in pending
            if (current_chapter - (f.get("last_mentioned_chapter") or f["planted_chapter"])) >= threshold
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_matching_foreshadowing(self, collect_desc: str) -> dict | None:
        """模糊匹配待回收伏笔（基于内容相似度）。

        使用 SequenceMatcher，阈值 >= 0.5。
        """
        from difflib import SequenceMatcher

        pending = self.graph.get_pending_foreshadowings(current_chapter=999999)
        best_match: dict | None = None
        best_score = 0.0

        for foreshadow in pending:
            content = foreshadow.get("content", "")
            score = SequenceMatcher(None, collect_desc, content).ratio()
            if score > best_score:
                best_score = score
                best_match = foreshadow

        if best_score >= 0.5:
            return best_match
        return None

    @staticmethod
    def _extract_keywords(desc: str, top_n: int = 10) -> list[str]:
        """从描述中提取关键词。

        不使用 jieba（可能未安装）。采用两级策略：
        1. 按标点和空格分割，取长度 >= 2 的片段
        2. 对较长片段（>= 4字符），额外生成 2-4 字的滑动窗口子串

        优先保留较长的子串（更有区分度），然后补充短子串。
        这确保即使伏笔描述无标点（如"主角获得神秘戒指"），
        也能生成 "神秘戒指", "主角", "获得", "神秘", "戒指" 等子关键词。
        """
        # 按中文标点、英文标点、空格分割
        segments = re.split(
            r"[，。！？、；：""''（）《》【】\s,.:;!?\"'()\[\]{}<>]+",
            desc,
        )
        segments = [seg.strip() for seg in segments if len(seg.strip()) >= 2]

        keywords: list[str] = []
        seen: set[str] = set()

        def _add(kw: str) -> None:
            if kw not in seen:
                seen.add(kw)
                keywords.append(kw)

        for seg in segments:
            if len(seg) <= 4:
                _add(seg)
            else:
                # Full segment for exact match
                _add(seg)
                # Generate sub-keywords: longer widths first (more discriminative)
                for width in (4, 3, 2):
                    for i in range(len(seg) - width + 1):
                        _add(seg[i : i + width])

        # Filter out very common stop-words that cause false positives
        _STOP = {
            "一个", "一些", "但是", "因为", "所以", "而且", "或者",
            "如果", "这个", "那个", "已经", "可以", "他们", "她们",
        }
        keywords = [kw for kw in keywords if kw not in _STOP]
        return keywords[:top_n] if top_n else keywords
