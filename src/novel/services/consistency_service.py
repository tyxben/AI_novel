"""一致性检查服务 - 三层混合检测（SQLite / NetworkX / Vector）"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.novel.models.memory import Fact

log = logging.getLogger("novel")


def _extract_json_array(text: str | None) -> list | None:
    """从 LLM 输出中稳健提取 JSON 数组。"""
    if not text:
        return None
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "facts" in result:
            return result["facts"]
        return None
    except (json.JSONDecodeError, TypeError):
        pass
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _extract_json_obj(text: str | None) -> dict | None:
    """从 LLM 输出中稳健提取 JSON 对象。"""
    if not text:
        return None
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
        return None
    except (json.JSONDecodeError, TypeError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


_FACT_TYPE_MAP = {
    "time": "structured",
    "character_state": "structured",
    "location": "structured",
    "event": "vector",
    "relationship": "graph",
}


class ConsistencyService:
    """一致性检查服务

    提供事实提取和三层矛盾检测能力：
    1. 结构化检查（SQLite 精确匹配）
    2. 知识图谱检查（NetworkX 关系查询）
    3. 向量语义检查（Chroma 语义兜底）
    4. LLM 裁决（模糊矛盾判断）
    """

    def __init__(self, llm_client: Any) -> None:
        self.llm = llm_client

    # ------------------------------------------------------------------
    # 事实提取
    # ------------------------------------------------------------------

    def extract_facts(
        self, chapter_text: str, chapter_number: int
    ) -> list[Fact]:
        """通过 LLM 从章节文本中提取关键事实。

        事实类型: time, character_state, location, event, relationship
        """
        prompt = f"""请从以下章节文本中提取关键事实，每个事实分类为以下类型之一：
- time: 时间相关（如"三天后"、"黄昏时分"）
- character_state: 角色状态（如"受伤"、"突破境界"、"死亡"）
- location: 地点（如"到达某城"、"进入某洞府"）
- event: 重要事件（如"击败某人"、"获得宝物"）
- relationship: 角色关系（如"结拜"、"反目"、"师徒"）

请以 JSON 数组格式返回，每个元素包含:
- "type": 事实类型
- "content": 事实描述（简洁准确）

章节文本（第{chapter_number}章）：
{chapter_text[:3000]}"""

        try:
            response = self.llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "你是一位专业的小说编辑，擅长从文本中提取关键事实。请严格按 JSON 格式返回。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                json_mode=True,
            )
            raw_facts = _extract_json_array(response.content)
            if raw_facts is None:
                log.warning("事实提取失败：LLM 返回无法解析为 JSON 数组")
                return []
        except Exception as exc:
            log.error("事实提取 LLM 调用失败: %s", exc)
            return []

        facts: list[Fact] = []
        for item in raw_facts:
            if not isinstance(item, dict):
                continue
            fact_type = item.get("type", "event")
            if fact_type not in _FACT_TYPE_MAP:
                fact_type = "event"
            content = item.get("content", "")
            if not content:
                continue
            storage_layer = _FACT_TYPE_MAP[fact_type]
            facts.append(
                Fact(
                    chapter=chapter_number,
                    type=fact_type,
                    content=content,
                    storage_layer=storage_layer,
                )
            )
        return facts

    # ------------------------------------------------------------------
    # 第一层：结构化检查（SQLite）
    # ------------------------------------------------------------------

    def check_structured(
        self, new_facts: list[Fact], db: Any
    ) -> list[dict]:
        """第一层检查：SQLite 精确匹配。

        对比新事实与数据库中已有事实，检测同一实体的状态矛盾。
        例如：角色已死亡但后续章节又出现。

        Args:
            new_facts: 新提取的事实列表
            db: StructuredDB 实例

        Returns:
            矛盾列表，每项包含 {fact, conflicting_fact, reason, layer, confidence}
        """
        contradictions: list[dict] = []

        for fact in new_facts:
            if fact.type not in ("character_state", "time", "location"):
                continue

            # 查询同类型的历史事实
            existing = db.get_facts(fact_type=fact.type)
            for ex in existing:
                if ex.get("chapter", 0) >= fact.chapter:
                    continue
                # 简单关键词重叠检测：同一实体的不同状态
                ex_content = ex.get("content", "")
                if self._content_overlaps(fact.content, ex_content):
                    contradictions.append(
                        {
                            "fact": {
                                "chapter": fact.chapter,
                                "type": fact.type,
                                "content": fact.content,
                            },
                            "conflicting_fact": {
                                "chapter": ex.get("chapter"),
                                "type": ex.get("type"),
                                "content": ex_content,
                            },
                            "reason": f"同一实体在第{ex.get('chapter')}章和第{fact.chapter}章的状态可能矛盾",
                            "layer": "structured",
                            "confidence": 0.7,
                        }
                    )
        return contradictions

    # ------------------------------------------------------------------
    # 第二层：知识图谱检查（NetworkX）
    # ------------------------------------------------------------------

    def check_graph(
        self, new_facts: list[Fact], graph: Any
    ) -> list[dict]:
        """第二层检查：NetworkX 关系矛盾。

        检测角色关系变化是否合理（如无铺垫的突变）。

        Args:
            new_facts: 新提取的事实列表
            graph: KnowledgeGraph 实例

        Returns:
            矛盾列表
        """
        contradictions: list[dict] = []

        relationship_facts = [f for f in new_facts if f.type == "relationship"]
        for fact in relationship_facts:
            # 从事实内容中尝试提取角色对
            characters = self._extract_character_pair(fact.content)
            if not characters:
                continue

            char1, char2 = characters
            # 查询现有关系
            latest_rel = graph.get_latest_relationship(char1, char2)
            if latest_rel is None:
                continue

            old_type = latest_rel.get("type", "")
            old_chapter = latest_rel.get("chapter", 0)

            # 检测关系突变（跨越多章无铺垫）
            if old_chapter > 0 and fact.chapter - old_chapter > 1:
                contradictions.append(
                    {
                        "fact": {
                            "chapter": fact.chapter,
                            "type": fact.type,
                            "content": fact.content,
                        },
                        "conflicting_fact": {
                            "chapter": old_chapter,
                            "type": "relationship",
                            "content": f"{char1}与{char2}的关系为: {old_type}",
                        },
                        "reason": f"角色关系从'{old_type}'发生变化，中间跨越{fact.chapter - old_chapter}章可能缺少铺垫",
                        "layer": "graph",
                        "confidence": 0.6,
                    }
                )
        return contradictions

    # ------------------------------------------------------------------
    # 第三层：向量语义检查（Chroma）
    # ------------------------------------------------------------------

    def check_vector(
        self, chapter_text: str, memory: Any
    ) -> list[dict]:
        """第三层检查：语义相似度检测。

        通过向量搜索找到语义相似的历史内容，识别潜在矛盾。

        Args:
            chapter_text: 当前章节文本
            memory: NovelMemory 实例（需要 vector_store）

        Returns:
            矛盾列表
        """
        contradictions: list[dict] = []

        try:
            vector_store = memory.vector_store
            results = vector_store.search_similar_facts(
                query=chapter_text[:500],
                n_results=5,
            )
        except Exception as exc:
            log.debug("向量检索不可用或失败，跳过第三层检查: %s", exc)
            return contradictions

        documents = results.get("documents", [[]])[0] if results else []
        metadatas = results.get("metadatas", [[]])[0] if results else []
        distances = results.get("distances", [[]])[0] if results else []

        for doc, meta, dist in zip(documents, metadatas, distances):
            # cosine distance < 0.3 表示高度相似（可能矛盾）
            if dist < 0.3 and doc:
                contradictions.append(
                    {
                        "fact": {
                            "chapter": "current",
                            "type": "semantic",
                            "content": chapter_text[:200],
                        },
                        "conflicting_fact": {
                            "chapter": meta.get("chapter", "unknown"),
                            "type": meta.get("type", "unknown"),
                            "content": doc,
                        },
                        "reason": f"当前章节内容与第{meta.get('chapter', '?')}章高度相似（距离={dist:.3f}），可能存在矛盾或重复",
                        "layer": "vector",
                        "confidence": round(1.0 - dist, 2),
                    }
                )
        return contradictions

    # ------------------------------------------------------------------
    # LLM 裁决
    # ------------------------------------------------------------------

    def llm_judge(
        self, potential_contradiction: dict
    ) -> tuple[bool, str]:
        """LLM 裁决潜在矛盾是否为真实矛盾。

        Args:
            potential_contradiction: 包含 fact, conflicting_fact, reason 的字典

        Returns:
            (is_contradiction, reason) 元组
        """
        fact = potential_contradiction.get("fact", {})
        conflicting = potential_contradiction.get("conflicting_fact", {})
        initial_reason = potential_contradiction.get("reason", "")

        prompt = f"""请判断以下两个事实是否存在矛盾：

事实A（第{fact.get('chapter', '?')}章）：{fact.get('content', '')}
事实B（第{conflicting.get('chapter', '?')}章）：{conflicting.get('content', '')}

初步判断理由：{initial_reason}

请以 JSON 格式返回：
{{"is_contradiction": true/false, "reason": "判断理由"}}

注意：
- 如果两个事实描述的是不同时间点的合理变化（如角色受伤后康复），不算矛盾
- 如果是同一事件的不同角度描述，不算矛盾
- 只有逻辑上不可能同时成立的才算矛盾"""

        try:
            response = self.llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "你是一位严谨的小说编辑，擅长判断情节一致性。请仔细分析后给出判断。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                json_mode=True,
            )
            result = _extract_json_obj(response.content)
            if result is not None:
                return (
                    bool(result.get("is_contradiction", False)),
                    str(result.get("reason", "无理由")),
                )
        except Exception as exc:
            log.error("LLM 裁决调用失败: %s", exc)

        # 默认不判定为矛盾
        return False, "LLM 裁决失败，默认为非矛盾"

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _content_overlaps(content1: str, content2: str) -> bool:
        """检测两段内容是否涉及同一实体（简单关键词重叠）。"""
        chars1 = set(content1)
        chars2 = set(content2)
        # 提取中文字符
        cn1 = {c for c in chars1 if "\u4e00" <= c <= "\u9fff"}
        cn2 = {c for c in chars2 if "\u4e00" <= c <= "\u9fff"}
        if not cn1 or not cn2:
            return False
        overlap = cn1 & cn2
        min_len = min(len(cn1), len(cn2))
        if min_len == 0:
            return False
        return len(overlap) / min_len > 0.3

    @staticmethod
    def _extract_character_pair(content: str) -> tuple[str, str] | None:
        """从关系描述中提取角色对。

        尝试匹配 "A与B" "A和B" "A跟B" 等模式。
        """
        import re

        patterns = [
            r"(.+?)(?:与|和|跟|对)(.+?)(?:的关系|关系|之间|成为|变为|是)",
            r"(.+?)(?:与|和|跟|对)(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                char1 = match.group(1).strip()
                char2 = match.group(2).strip()
                # 清理过长的匹配
                if len(char1) <= 10 and len(char2) <= 10:
                    return char1, char2
        return None
