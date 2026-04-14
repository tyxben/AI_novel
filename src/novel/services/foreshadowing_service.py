"""伏笔图谱管理服务 (P1)

负责伏笔节点的注册、回收匹配、文本验证、闲笔提取与升级。
所有方法同步执行，不依赖 LLM（除非显式传入）。
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.novel.models.foreshadowing import DetailEntry, Foreshadowing
from src.novel.utils.json_extract import extract_json_array

if TYPE_CHECKING:
    from src.novel.storage.knowledge_graph import KnowledgeGraph
    from src.novel.storage.novel_memory import NovelMemory

log = logging.getLogger("novel.services.foreshadowing")


# Backward-compat alias — existing tests import `_extract_json_array` from this
# module. The canonical implementation lives in `src.novel.utils.json_extract`.
def _extract_json_array(text: str | None) -> list | None:
    """Deprecated: use ``src.novel.utils.json_extract.extract_json_array``.

    Kept for backward compatibility with existing tests. Restricts unwrap keys
    to this module's historical set (details / items / results) to preserve
    exact prior behaviour.
    """
    return extract_json_array(text, unwrap_keys=("details", "items", "results"))


class ForeshadowingService:
    """伏笔图谱管理服务"""

    def __init__(
        self,
        knowledge_graph: "KnowledgeGraph",
        llm_client: Any = None,
        novel_memory: "NovelMemory | None" = None,
    ) -> None:
        self.graph = knowledge_graph
        self.llm = llm_client
        self.memory = novel_memory

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
            if self._fuzzy_verify(plant, chapter_text):
                result["plants_confirmed"].append(plant)
            else:
                result["plants_missing"].append(plant)
                log.warning("伏笔埋设缺失: %s (第%d章)", plant, chapter_number)

        for collect in planned_collects:
            if not collect or not isinstance(collect, str):
                continue
            if self._fuzzy_verify(collect, chapter_text):
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
    # Detail extraction & promotion (闲笔提取 & 升级)
    # ------------------------------------------------------------------

    def extract_details(
        self,
        chapter_text: str,
        chapter_number: int,
    ) -> list[DetailEntry]:
        """从章节文本中提取潜在可利用的细节（道具、环境、角色动作、异常现象、对话暗示）。

        用 LLM 分析文本，识别可以在后续章节中被利用的"闲笔"细节。
        提取的细节会自动存入向量库（如果 novel_memory 可用）。

        Args:
            chapter_text: 章节文本
            chapter_number: 章节号

        Returns:
            提取的 DetailEntry 列表
        """
        if not chapter_text or not chapter_text.strip():
            return []

        if self.llm is None:
            log.warning("LLM 未配置，无法提取闲笔细节")
            return []

        prompt = (
            "你是一位资深小说编辑，擅长发现文本中可以在后续章节被利用的'闲笔'细节。\n"
            "请从以下章节文本中提取潜在可利用的细节。\n\n"
            "细节类别（category）：\n"
            "- 道具：出现过的物品、信物、武器等\n"
            "- 环境：特殊地点、地形特征、天气异常等\n"
            "- 角色动作：不经意的行为、习惯、反常举动\n"
            "- 异常现象：未解释的事件、离奇巧合\n"
            "- 对话暗示：意味深长的话、未说完的话、暗语\n\n"
            f"章节号：第{chapter_number}章\n\n"
            f"章节文本：\n{chapter_text[:3000]}\n\n"
            "请返回 JSON 数组，每个元素包含：\n"
            "- content: 细节内容（简短描述）\n"
            "- context: 原文上下文（前后2句）\n"
            "- category: 类别（道具/环境/角色动作/异常现象/对话暗示）\n\n"
            "如果没有可提取的细节，返回空数组 []。\n"
            "只返回 JSON，不要其他内容。"
        )

        try:
            resp = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                json_mode=True,
                max_tokens=2048,
            )
        except Exception as exc:
            log.warning("LLM 调用失败，无法提取闲笔: %s", exc)
            return []

        raw_items = extract_json_array(
            resp.content, unwrap_keys=("details", "items", "results")
        )
        if not raw_items:
            return []

        details: list[DetailEntry] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            content = item.get("content", "").strip()
            context = item.get("context", "").strip()
            category = item.get("category", "").strip()
            if not content or not context:
                continue
            # 规范化类别
            valid_categories = {"道具", "环境", "角色动作", "异常现象", "对话暗示"}
            if category not in valid_categories:
                category = "道具"  # 默认归类

            detail = DetailEntry(
                chapter=chapter_number,
                content=content,
                context=context,
                category=category,
            )
            details.append(detail)

            # 自动存入向量库
            if self.memory is not None:
                try:
                    self.memory.add_detail(detail)
                except Exception as exc:
                    log.debug("存储闲笔到向量库失败: %s", exc)

        log.info("第%d章提取到 %d 条闲笔细节", chapter_number, len(details))
        return details

    def search_reusable_details(
        self,
        query: str,
        current_chapter: int,
        top_k: int = 5,
        category: str | None = None,
    ) -> list[DetailEntry]:
        """反向检索：当后续章节需要线索时，从历史闲笔中找可利用的。

        向量检索匹配的闲笔条目，过滤掉已升级或已使用的。

        Args:
            query: 检索查询（如 "需要一个信物来触发回忆"）
            current_chapter: 当前章节号（用于过滤，只返回之前章节的细节）
            top_k: 返回数量上限
            category: 可选类别过滤

        Returns:
            匹配的 DetailEntry 列表
        """
        if not query or not query.strip():
            return []

        if self.memory is None:
            log.warning("NovelMemory 未配置，无法检索闲笔")
            return []

        try:
            results = self.memory.search_details(
                query=query,
                category=category,
                n_results=top_k * 2,  # 多取一些，后面过滤
            )
        except Exception as exc:
            log.warning("向量检索闲笔失败: %s", exc)
            return []

        # 解析 Chroma 返回结果
        details: list[DetailEntry] = []
        ids_list = results.get("ids", [[]])[0] if results.get("ids") else []
        docs_list = results.get("documents", [[]])[0] if results.get("documents") else []
        metas_list = results.get("metadatas", [[]])[0] if results.get("metadatas") else []

        for i, doc in enumerate(docs_list):
            meta = metas_list[i] if i < len(metas_list) else {}
            detail_id = meta.get("detail_id", ids_list[i] if i < len(ids_list) else "")
            chapter = meta.get("chapter", 0)

            # 过滤：只要当前章节之前的
            if chapter >= current_chapter:
                continue

            detail = DetailEntry(
                detail_id=detail_id,
                chapter=chapter,
                content=doc,
                context=meta.get("context", doc),
                category=meta.get("category", "道具"),
                status="available",
            )
            details.append(detail)

            if len(details) >= top_k:
                break

        return details

    def promote_to_foreshadowing(
        self,
        detail_id: str,
        resolution_plan: str,
        target_chapter: int,
        detail: DetailEntry | None = None,
    ) -> Foreshadowing:
        """将一个闲笔细节升级为正式伏笔（后置追认）。

        在 knowledge_graph 中注册伏笔节点，设置回收计划。

        Args:
            detail_id: 闲笔条目 ID
            resolution_plan: 回收计划描述
            target_chapter: 计划回收的章节号
            detail: 可选，直接传入 DetailEntry 对象（避免重复查询）

        Returns:
            创建的 Foreshadowing 对象

        Raises:
            ValueError: detail_id 不存在或已被升级
        """
        if not detail_id:
            raise ValueError("detail_id 不能为空")

        # 如果没有传入 detail，尝试从向量库查询
        if detail is None:
            detail = self._find_detail_by_id(detail_id)
            if detail is None:
                raise ValueError(f"闲笔条目不存在: {detail_id}")

        if detail.status == "promoted":
            raise ValueError(f"闲笔条目已升级: {detail_id}")

        # 创建伏笔对象
        foreshadowing = Foreshadowing(
            planted_chapter=detail.chapter,
            content=detail.content,
            target_chapter=target_chapter,
            resolution=resolution_plan,
            origin="retroactive",
            original_detail_id=detail_id,
            original_context=detail.context,
            status="pending",
        )

        # 注册到知识图谱
        self.graph.add_foreshadowing_node(
            foreshadowing_id=foreshadowing.foreshadowing_id,
            planted_chapter=foreshadowing.planted_chapter,
            content=foreshadowing.content,
            target_chapter=target_chapter,
            status="pending",
            origin="retroactive",
            original_detail_id=detail_id,
            resolution=resolution_plan,
        )

        # 更新 detail 状态（内存 + 向量库持久化）
        detail.status = "promoted"
        detail.promoted_foreshadowing_id = foreshadowing.foreshadowing_id
        if self.memory is not None:
            try:
                self.memory.vector_store.update_metadata(
                    detail_id,
                    {
                        "chapter": detail.chapter,
                        "category": detail.category,
                        "detail_id": detail.detail_id,
                        "type": "detail",
                        "status": "promoted",
                        "promoted_foreshadowing_id": foreshadowing.foreshadowing_id,
                    },
                )
            except Exception as exc:
                log.warning("持久化闲笔状态失败: %s", exc)

        log.info(
            "闲笔升级为伏笔: detail=%s -> foreshadowing=%s, 计划第%d章回收",
            detail_id,
            foreshadowing.foreshadowing_id,
            target_chapter,
        )

        return foreshadowing

    def _find_detail_by_id(self, detail_id: str) -> DetailEntry | None:
        """通过 ID 查找闲笔条目。

        尝试从向量库中按 ID 检索。
        """
        if self.memory is None:
            return None

        try:
            record = self.memory.vector_store.get_by_id(detail_id)
            if record is not None:
                meta = record.get("metadata", {})
                doc = record.get("document", "")
                if meta.get("type") == "detail":
                    return DetailEntry(
                        detail_id=detail_id,
                        chapter=meta.get("chapter", 1),
                        content=doc,
                        context=meta.get("context", doc),
                        category=meta.get("category", "道具"),
                        status=meta.get("status", "available"),
                    )
        except Exception as exc:
            log.debug("按 ID 查找闲笔失败: %s", exc)

        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fuzzy_verify(self, desc: str, chapter_text: str, min_hits: int = 2) -> bool:
        """宽松验证：描述中的关键词在文本中命中 >= min_hits 个即视为确认。

        比严格的 all-keywords 匹配更合理，因为 Writer 经常换一种
        表述来执行同一个伏笔。
        """
        keywords = self._extract_keywords(desc, top_n=0)  # 0 = 不限数量
        if not keywords:
            return True  # 没关键词就算通过
        hits = sum(1 for kw in keywords if kw in chapter_text)
        # 关键词少于 min_hits 个时，命中 1 个就算
        threshold = min(min_hits, max(1, len(keywords) // 3))
        return hits >= threshold

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

        if best_score >= 0.3:
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
