"""实体注册与管理服务（知识图谱 P0）"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class EntityService:
    """实体注册与管理服务

    负责：提取 → 去重 → 注册 → 别名合并 → 名称冲突检测。
    """

    def __init__(self, db: Any, llm_client: Any | None = None) -> None:
        """
        Args:
            db: StructuredDB 实例
            llm_client: 可选的 LLM 客户端（用于 LLM 提取）
        """
        from src.novel.services.entity_extractor import (
            LLMEntityExtractor,
            RuleBasedExtractor,
        )

        self.db = db
        self.llm = llm_client
        self.rule_extractor = RuleBasedExtractor()
        self.llm_extractor = (
            LLMEntityExtractor(llm_client) if llm_client else None
        )

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def extract_and_register(
        self,
        chapter_text: str,
        chapter_number: int,
        use_llm: bool = False,
    ) -> dict[str, Any]:
        """提取并注册实体

        Args:
            chapter_text: 章节正文
            chapter_number: 章节号
            use_llm: 是否启用 LLM 补充提取

        Returns:
            {"new_count": int, "updated_count": int, "entities": list[dict]}
        """
        from src.novel.models.entity import Entity  # noqa: F811

        # 1. 规则提取
        entities: list[Entity] = self.rule_extractor.extract_entities(
            chapter_text, chapter_number
        )

        # 2. LLM 补充（可选）
        if use_llm and self.llm_extractor:
            try:
                llm_entities = self.llm_extractor.extract_entities(
                    chapter_text, chapter_number
                )
                entities.extend(llm_entities)
            except Exception as exc:
                log.warning("LLM 实体提取失败（回退规则结果）: %s", exc)

        # 3. 去重
        entities = self._deduplicate_entities(entities)

        # 4. 注册到数据库
        new_count = 0
        updated_count = 0
        for ent in entities:
            try:
                existing = self.db.get_entity_by_name_and_type(
                    ent.canonical_name, ent.entity_type
                )
                if existing:
                    # 更新提及次数
                    self.db.update_entity_mention(
                        entity_id=existing["entity_id"],
                        chapter=chapter_number,
                    )
                    updated_count += 1
                else:
                    # 新增实体
                    self.db.insert_entity(ent.model_dump())
                    new_count += 1
            except Exception as exc:
                log.warning("实体注册失败（%s）: %s", ent.canonical_name, exc)

        return {
            "new_count": new_count,
            "updated_count": updated_count,
            "entities": [e.model_dump() for e in entities],
        }

    def merge_aliases(self, dry_run: bool = True) -> int:
        """别名合并（SequenceMatcher >= 0.8）

        同类型实体中，名称相似度 >= 80% 的合并为同一实体。
        保留首次出现的为主名，另一个作为别名。

        Args:
            dry_run: True 仅检测不实际合并

        Returns:
            合并组数
        """
        from difflib import SequenceMatcher

        try:
            entities = self.db.get_all_entities()
        except Exception as exc:
            log.warning("别名合并读取实体失败: %s", exc)
            return 0

        merged_count = 0

        # 按类型分组（只在同类型内合并）
        by_type: dict[str, list[dict]] = {}
        for ent in entities:
            t = ent.get("entity_type", "other")
            by_type.setdefault(t, []).append(ent)

        # 记录已被合并的 entity_id，避免重复处理
        merged_ids: set[str] = set()

        for _etype, group in by_type.items():
            for i, ent1 in enumerate(group):
                if ent1["entity_id"] in merged_ids:
                    continue
                for ent2 in group[i + 1:]:
                    if ent2["entity_id"] in merged_ids:
                        continue

                    name1 = ent1.get("canonical_name", "")
                    name2 = ent2.get("canonical_name", "")

                    ratio = SequenceMatcher(None, name1, name2).ratio()
                    if ratio >= 0.8:
                        # 保留首次出现的为主名
                        ch1 = ent1.get("first_mention_chapter", 9999)
                        ch2 = ent2.get("first_mention_chapter", 9999)
                        if ch1 <= ch2:
                            primary, secondary = ent1, ent2
                        else:
                            primary, secondary = ent2, ent1

                        if not dry_run:
                            try:
                                self.db.merge_entity_as_alias(
                                    primary_id=primary["entity_id"],
                                    secondary_id=secondary["entity_id"],
                                )
                            except Exception as exc:
                                log.warning(
                                    "别名合并失败 (%s <- %s): %s",
                                    name1, name2, exc,
                                )
                                continue

                        merged_ids.add(secondary["entity_id"])
                        merged_count += 1
                        log.info(
                            "实体合并: %s <- %s (相似度: %.2f)",
                            primary.get("canonical_name"),
                            secondary.get("canonical_name"),
                            ratio,
                        )

        return merged_count

    def detect_name_conflicts(
        self,
        current_entities: list[dict | Any],
        threshold: float = 0.7,
    ) -> list[dict]:
        """检测名称冲突（相似但不完全一致的实体名）

        Args:
            current_entities: 当前章节提取的实体列表（dict 或 Entity）
            threshold: 相似度阈值

        Returns:
            冲突列表 [{"current_name", "existing_name", "type", "similarity", "conflict_type"}]
        """
        from difflib import SequenceMatcher

        conflicts: list[dict] = []

        try:
            all_entities = self.db.get_all_entities()
        except Exception as exc:
            log.warning("名称冲突检测读取实体失败: %s", exc)
            return conflicts

        # 按类型索引已有实体
        by_type: dict[str, list[dict]] = {}
        for ent in all_entities:
            t = ent.get("entity_type", "other")
            by_type.setdefault(t, []).append(ent)

        for cur in current_entities:
            # 兼容 dict 和 Entity 对象
            if hasattr(cur, "canonical_name"):
                cur_name = cur.canonical_name
                cur_type = cur.entity_type
            else:
                cur_name = cur.get("canonical_name", "")
                cur_type = cur.get("entity_type", "other")

            candidates = by_type.get(cur_type, [])
            for existing in candidates:
                existing_name = existing.get("canonical_name", "")
                if existing_name == cur_name:
                    continue  # 完全一致不算冲突

                ratio = SequenceMatcher(None, cur_name, existing_name).ratio()
                if ratio >= threshold:
                    conflicts.append({
                        "current_name": cur_name,
                        "existing_name": existing_name,
                        "type": cur_type,
                        "similarity": round(ratio, 3),
                        "conflict_type": "name_variant",
                    })

        return conflicts

    def get_entity_stats(self) -> dict[str, Any]:
        """获取实体统计信息

        Returns:
            {
                "total_count": int,
                "by_type": {type: count, ...},
                "top_mentioned": [...],
            }
        """
        try:
            by_type = self.db.get_entity_count_by_type()
            total = sum(by_type.values())
            all_entities = self.db.get_all_entities()

            # 按提及次数排序取 Top10
            sorted_entities = sorted(
                all_entities,
                key=lambda e: e.get("mention_count", 0),
                reverse=True,
            )
            top = [
                {
                    "name": e.get("canonical_name"),
                    "type": e.get("entity_type"),
                    "mention_count": e.get("mention_count", 0),
                }
                for e in sorted_entities[:10]
            ]

            return {
                "total_count": total,
                "by_type": by_type,
                "top_mentioned": top,
            }
        except Exception as exc:
            log.warning("实体统计失败: %s", exc)
            return {"total_count": 0, "by_type": {}, "top_mentioned": []}

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate_entities(entities: list) -> list:
        """同名同类型去重，保留第一个"""
        seen: set[tuple[str, str]] = set()
        result = []
        for ent in entities:
            key = (ent.canonical_name, ent.entity_type)
            if key not in seen:
                seen.add(key)
                result.append(ent)
        return result
