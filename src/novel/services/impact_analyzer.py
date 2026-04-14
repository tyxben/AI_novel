"""影响分析器 -- 纯规则分析编辑操作对后续章节的影响。

不调用 LLM，同步执行。配合 NovelEditService 使用。
novel_data 是 FileManager.load_novel() 返回的 dict。
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

log = logging.getLogger("novel.impact_analyzer")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class ChangeRequest(BaseModel):
    """编辑变更请求。"""

    change_type: str = Field(
        ...,
        description=(
            "变更类型: add_character | modify_character | delete_character "
            "| modify_outline | modify_world"
        ),
    )
    entity_type: str = Field(
        ...,
        description="实体类型: character | outline | world",
    )
    entity_id: Optional[str] = Field(
        None,
        description="实体 ID（角色 character_id 或章节号字符串等）",
    )
    effective_from_chapter: int = Field(
        1,
        ge=1,
        description="变更生效起始章节",
    )
    details: dict = Field(
        default_factory=dict,
        description="变更详情（如修改的字段、新值等）",
    )


class ImpactResult(BaseModel):
    """影响分析结果。"""

    affected_chapters: list[int] = Field(
        default_factory=list, description="受影响的章节号"
    )
    severity: str = Field(
        "low", description="严重程度: low | medium | high | critical"
    )
    conflicts: list[str] = Field(
        default_factory=list, description="冲突描述"
    )
    warnings: list[str] = Field(
        default_factory=list, description="警告信息"
    )
    summary: str = Field("", description="影响摘要")


# ---------------------------------------------------------------------------
# Severity thresholds
# ---------------------------------------------------------------------------

_CRITICAL_APPEARANCE_THRESHOLD = 3  # >= 3 chapters -> critical
_HIGH_APPEARANCE_THRESHOLD = 1       # 1-2 chapters -> high


# ---------------------------------------------------------------------------
# ImpactAnalyzer
# ---------------------------------------------------------------------------

class ImpactAnalyzer:
    """分析编辑操作对后续章节的影响（纯规则，无 LLM）。"""

    def analyze(self, novel_data: dict, change: ChangeRequest) -> ImpactResult:
        """分析变更对小说的影响。

        根据 change.entity_type 分派到对应的子分析方法。
        """
        entity_type = change.entity_type
        if entity_type == "character":
            return self._analyze_character_impact(novel_data, change)
        if entity_type == "outline":
            return self._analyze_outline_impact(novel_data, change)
        if entity_type == "world":
            return self._analyze_world_impact(novel_data, change)

        log.warning("未知的 entity_type: %s，返回低影响默认结果", entity_type)
        return ImpactResult(
            severity="low",
            summary=f"未知实体类型 '{entity_type}'，无法分析影响。",
        )

    # ------------------------------------------------------------------
    # Character impact
    # ------------------------------------------------------------------

    def _analyze_character_impact(
        self, novel_data: dict, change: ChangeRequest
    ) -> ImpactResult:
        """角色相关变更的影响分析。"""

        change_type = change.change_type

        if change_type == "add_character":
            return self._analyze_add_character(novel_data, change)
        if change_type == "delete_character":
            return self._analyze_delete_character(novel_data, change)
        if change_type == "modify_character":
            return self._analyze_modify_character(novel_data, change)

        return ImpactResult(
            severity="low",
            summary=f"未知的角色变更类型 '{change_type}'。",
        )

    def _analyze_add_character(
        self, novel_data: dict, change: ChangeRequest
    ) -> ImpactResult:
        """添加新角色 -- 通常无冲突，低影响。"""
        char_name = change.details.get("name", "新角色")
        return ImpactResult(
            severity="low",
            summary=f"添加新角色「{char_name}」，不影响已有章节。",
        )

    def _analyze_delete_character(
        self, novel_data: dict, change: ChangeRequest
    ) -> ImpactResult:
        """删除角色 -- 检查后续章节出现次数决定严重程度。"""
        character_id = change.entity_id
        if not character_id:
            return ImpactResult(
                severity="low",
                warnings=["未指定 entity_id，无法分析删除影响。"],
                summary="缺少角色 ID，跳过影响分析。",
            )

        # Resolve character name for readable messages
        char_name = self._resolve_character_name(novel_data, character_id)

        # Check if character exists
        if not self._character_exists(novel_data, character_id):
            return ImpactResult(
                severity="low",
                warnings=[f"角色 '{character_id}' 不存在于当前小说数据中。"],
                summary=f"角色「{char_name}」不存在，无需分析。",
            )

        # Find appearances from effective_from_chapter onward
        appearances = self._find_character_appearances(
            novel_data, character_id, from_chapter=change.effective_from_chapter
        )

        conflicts: list[str] = []
        warnings: list[str] = []
        count = len(appearances)

        if count > 0:
            conflicts.append(
                f"角色「{char_name}」在第 {', '.join(str(c) for c in appearances)} 章"
                f"的大纲中被引用，删除后这些章节的情节将断裂。"
            )

        # Also check written chapters (content mentions)
        written_mentions = self._find_character_in_written_chapters(
            novel_data, character_id, change.effective_from_chapter
        )
        if written_mentions:
            warnings.append(
                f"角色「{char_name}」在已写的第 "
                f"{', '.join(str(c) for c in written_mentions)} 章正文中出现，"
                f"删除后需要重写这些章节。"
            )

        # Severity
        total_affected = sorted(set(appearances) | set(written_mentions))
        total_count = len(total_affected)

        if total_count >= _CRITICAL_APPEARANCE_THRESHOLD:
            severity = "critical"
        elif total_count >= _HIGH_APPEARANCE_THRESHOLD:
            severity = "high"
        else:
            severity = "low"

        summary = (
            f"删除角色「{char_name}」影响 {total_count} 个章节，"
            f"严重程度: {severity}。"
        )

        return ImpactResult(
            affected_chapters=total_affected,
            severity=severity,
            conflicts=conflicts,
            warnings=warnings,
            summary=summary,
        )

    def _analyze_modify_character(
        self, novel_data: dict, change: ChangeRequest
    ) -> ImpactResult:
        """修改角色属性 -- 检查是否修改核心属性。"""
        character_id = change.entity_id
        if not character_id:
            return ImpactResult(
                severity="low",
                warnings=["未指定 entity_id，无法分析修改影响。"],
                summary="缺少角色 ID，跳过影响分析。",
            )

        char_name = self._resolve_character_name(novel_data, character_id)

        if not self._character_exists(novel_data, character_id):
            return ImpactResult(
                severity="low",
                warnings=[f"角色 '{character_id}' 不存在于当前小说数据中。"],
                summary=f"角色「{char_name}」不存在，无需分析。",
            )

        # Determine if core attributes are being modified
        core_fields = {
            "name", "gender", "personality", "character_arc",
            "status", "occupation",
        }
        modified_fields = set(change.details.keys())
        core_changes = modified_fields & core_fields
        non_core_changes = modified_fields - core_fields

        # Find chapters where this character appears
        appearances = self._find_character_appearances(
            novel_data, character_id, from_chapter=change.effective_from_chapter
        )

        conflicts: list[str] = []
        warnings: list[str] = []

        if core_changes and appearances:
            conflicts.append(
                f"角色「{char_name}」的核心属性 {core_changes} 被修改，"
                f"与第 {', '.join(str(c) for c in appearances)} 章的已有情节可能矛盾。"
            )

        if non_core_changes:
            warnings.append(
                f"角色「{char_name}」的非核心属性 {non_core_changes} 被修改。"
            )

        # Severity: core change + appearances -> high, otherwise medium/low
        if core_changes and appearances:
            severity = "high"
        elif core_changes or appearances:
            severity = "medium"
        else:
            severity = "low"

        summary = (
            f"修改角色「{char_name}」"
            f"{'核心' if core_changes else '非核心'}属性，"
            f"影响 {len(appearances)} 个章节，严重程度: {severity}。"
        )

        return ImpactResult(
            affected_chapters=appearances,
            severity=severity,
            conflicts=conflicts,
            warnings=warnings,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Outline impact
    # ------------------------------------------------------------------

    def _analyze_outline_impact(
        self, novel_data: dict, change: ChangeRequest
    ) -> ImpactResult:
        """大纲变更的影响分析。"""
        current_chapter = novel_data.get("current_chapter", 0)
        details = change.details
        target_chapter = details.get("chapter_number")

        conflicts: list[str] = []
        warnings: list[str] = []
        affected: list[int] = []

        if target_chapter is not None:
            # Modifying a specific chapter's outline
            affected.append(target_chapter)

            if target_chapter <= current_chapter:
                # Modifying an already-written chapter's outline
                conflicts.append(
                    f"第 {target_chapter} 章已写完（当前进度: 第 {current_chapter} 章），"
                    f"修改其大纲可能导致内容与大纲不一致。"
                )

                # Check downstream chapters that may depend on this one
                downstream = self._find_downstream_chapters(
                    novel_data, target_chapter
                )
                if downstream:
                    affected.extend(downstream)
                    conflicts.append(
                        f"第 {', '.join(str(c) for c in downstream)} 章"
                        f"可能依赖第 {target_chapter} 章的情节（因果链风险）。"
                    )
            else:
                warnings.append(
                    f"第 {target_chapter} 章尚未写作，修改大纲影响较小。"
                )
        else:
            # Bulk outline modification
            warnings.append("未指定目标章节号，视为批量大纲修改。")
            # All chapters from effective_from are potentially affected
            outline_chapters = self._get_outline_chapter_numbers(novel_data)
            affected = [
                cn for cn in outline_chapters
                if cn >= change.effective_from_chapter
            ]

        affected = sorted(set(affected))

        # Severity
        written_affected = [c for c in affected if c <= current_chapter]
        if written_affected:
            severity = "high"
        elif affected:
            severity = "medium" if len(affected) > 1 else "low"
        else:
            severity = "low"

        summary = (
            f"大纲变更影响 {len(affected)} 个章节"
            f"（其中 {len(written_affected)} 个已写），"
            f"严重程度: {severity}。"
        )

        return ImpactResult(
            affected_chapters=affected,
            severity=severity,
            conflicts=conflicts,
            warnings=warnings,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # World impact
    # ------------------------------------------------------------------

    def _analyze_world_impact(
        self, novel_data: dict, change: ChangeRequest
    ) -> ImpactResult:
        """世界观变更的影响分析。"""
        current_chapter = novel_data.get("current_chapter", 0)
        details = change.details
        modified_fields = set(details.keys())

        # Core world fields that affect story logic
        core_world_fields = {"rules", "power_system", "era", "location"}
        core_changes = modified_fields & core_world_fields
        non_core_changes = modified_fields - core_world_fields

        conflicts: list[str] = []
        warnings: list[str] = []

        # All written chapters are potentially affected by world changes
        written_chapters = list(range(1, current_chapter + 1))
        affected = [
            c for c in written_chapters
            if c >= change.effective_from_chapter
        ]

        if core_changes and affected:
            conflicts.append(
                f"世界观核心设定 {core_changes} 被修改，"
                f"与已写的第 {', '.join(str(c) for c in affected)} 章内容可能矛盾。"
            )

        if non_core_changes:
            warnings.append(
                f"世界观非核心设定 {non_core_changes} 被修改。"
            )

        # Check if specific rules are being removed that chapters depend on
        if "rules" in details:
            old_rules = set(
                novel_data.get("world_setting", novel_data.get("world", {}))
                .get("rules", [])
                if isinstance(
                    novel_data.get("world_setting", novel_data.get("world", {})),
                    dict,
                )
                else []
            )
            new_rules = set(details.get("rules", []))
            removed_rules = old_rules - new_rules
            if removed_rules:
                conflicts.append(
                    f"以下世界规则被删除: {removed_rules}，"
                    f"可能与已写章节中引用这些规则的内容矛盾。"
                )

        # Severity
        if core_changes and affected:
            severity = "high"
        elif affected:
            severity = "medium"
        else:
            severity = "low"

        summary = (
            f"世界观变更影响 {len(affected)} 个已写章节，"
            f"严重程度: {severity}。"
        )

        return ImpactResult(
            affected_chapters=affected,
            severity=severity,
            conflicts=conflicts,
            warnings=warnings,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _find_character_appearances(
        self,
        novel_data: dict,
        character_id: str,
        from_chapter: int = 1,
    ) -> list[int]:
        """查找角色在大纲 involved_characters 中出现的所有章节。

        Args:
            novel_data: 小说数据 dict
            character_id: 角色 ID
            from_chapter: 从哪一章开始查找

        Returns:
            出现该角色的章节号列表（已排序）
        """
        outline = novel_data.get("outline", {})
        chapters_outline = outline.get("chapters", [])

        result: list[int] = []
        for co in chapters_outline:
            if not isinstance(co, dict):
                continue
            ch_num = co.get("chapter_number")
            if ch_num is None or ch_num < from_chapter:
                continue
            involved = co.get("involved_characters", [])
            if character_id in involved:
                result.append(ch_num)

        return sorted(result)

    def _find_character_in_written_chapters(
        self,
        novel_data: dict,
        character_id: str,
        from_chapter: int = 1,
    ) -> list[int]:
        """查找角色在已写章节正文/摘要中被提及的章节。

        使用角色名进行简单文本匹配（非 LLM）。
        """
        char_name = self._resolve_character_name(novel_data, character_id)
        if not char_name:
            return []

        # Also collect aliases
        aliases = self._resolve_character_aliases(novel_data, character_id)
        search_terms = {char_name} | set(aliases)

        current_chapter = novel_data.get("current_chapter", 0)
        chapters = novel_data.get("chapters", [])
        result: list[int] = []

        for ch in chapters:
            if not isinstance(ch, dict):
                continue
            ch_num = ch.get("chapter_number")
            if ch_num is None or ch_num < from_chapter or ch_num > current_chapter:
                continue

            # Search in content and summary
            content = ch.get("content", "") or ch.get("full_text", "") or ""
            summary = ch.get("summary", "") or ""
            text = content + summary

            for term in search_terms:
                if term and term in text:
                    result.append(ch_num)
                    break

        return sorted(result)

    def _find_downstream_chapters(
        self,
        novel_data: dict,
        target_chapter: int,
    ) -> list[int]:
        """查找可能依赖 target_chapter 的后续章节。

        简单规则：与 target_chapter 共享角色的后续章节。
        """
        outline = novel_data.get("outline", {})
        chapters_outline = outline.get("chapters", [])

        # Get involved characters for the target chapter
        target_chars: set[str] = set()
        for co in chapters_outline:
            if not isinstance(co, dict):
                continue
            if co.get("chapter_number") == target_chapter:
                target_chars = set(co.get("involved_characters", []))
                break

        if not target_chars:
            return []

        # Find subsequent chapters that share characters
        result: list[int] = []
        for co in chapters_outline:
            if not isinstance(co, dict):
                continue
            ch_num = co.get("chapter_number")
            if ch_num is None or ch_num <= target_chapter:
                continue
            involved = set(co.get("involved_characters", []))
            if involved & target_chars:
                result.append(ch_num)

        return sorted(result)

    def _character_exists(
        self, novel_data: dict, character_id: str
    ) -> bool:
        """检查角色是否存在于 novel_data 中。"""
        characters = novel_data.get("characters", [])
        if isinstance(characters, dict):
            return character_id in characters
        # list of dicts (standard format)
        for ch in characters:
            if isinstance(ch, dict) and ch.get("character_id") == character_id:
                return True
        return False

    def _resolve_character_name(
        self, novel_data: dict, character_id: str
    ) -> str:
        """根据 character_id 获取角色名。"""
        characters = novel_data.get("characters", [])
        if isinstance(characters, dict):
            char = characters.get(character_id, {})
            return char.get("name", character_id) if isinstance(char, dict) else character_id
        for ch in characters:
            if isinstance(ch, dict) and ch.get("character_id") == character_id:
                return ch.get("name", character_id)
        return character_id

    def _resolve_character_aliases(
        self, novel_data: dict, character_id: str
    ) -> list[str]:
        """根据 character_id 获取角色别名列表。"""
        characters = novel_data.get("characters", [])
        if isinstance(characters, dict):
            char = characters.get(character_id, {})
            return char.get("alias", []) if isinstance(char, dict) else []
        for ch in characters:
            if isinstance(ch, dict) and ch.get("character_id") == character_id:
                return ch.get("alias", [])
        return []

    def _get_outline_chapter_numbers(self, novel_data: dict) -> list[int]:
        """获取大纲中所有章节号。"""
        outline = novel_data.get("outline", {})
        chapters_outline = outline.get("chapters", [])
        result: list[int] = []
        for co in chapters_outline:
            if isinstance(co, dict) and "chapter_number" in co:
                result.append(co["chapter_number"])
        return sorted(result)
