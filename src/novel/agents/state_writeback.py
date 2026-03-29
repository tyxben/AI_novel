"""StateWriteback - Post-write state extraction and persistence

Extracts narrative state changes from a generated chapter and writes them
back to persistent storage.

Handles:
- Character changes: injuries, power-ups, relationship shifts, new abilities
- World changes: new locations discovered, factions introduced, rules revealed
- Foreshadowing: marks planted/collected foreshadowing
- Arc progress: updates story arc completion rates
- Outline sync: updates the current chapter's outline with actual content summary
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from src.novel.agents.state import Decision, NovelState

log = logging.getLogger("novel")


# ---------------------------------------------------------------------------
# Helper: decision factory
# ---------------------------------------------------------------------------


def _make_decision(
    step: str,
    decision: str,
    reason: str,
    data: dict[str, Any] | None = None,
) -> Decision:
    """Create a StateWriteback decision record."""
    return Decision(
        agent="StateWriteback",
        step=step,
        decision=decision,
        reason=reason,
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Rule-based keyword tables (shared with _extract_character_snapshot)
# ---------------------------------------------------------------------------

_LOCATION_KW = (
    "客栈", "酒楼", "山洞", "广场", "大殿", "密室", "街道", "城门",
    "书房", "卧室", "花园", "市集", "学院", "宫殿", "战场", "森林",
    "河边", "山顶", "谷底", "码头", "府邸", "府中", "院中", "门口",
    "城中", "城外", "山下", "洞中", "阵前", "殿中", "房间", "帐篷",
    "城池", "村庄", "小巷", "客房", "厅堂", "密道", "湖边", "崖边",
    "山北", "山南", "断崖", "藏物点", "矿脉", "洞穴", "废墟",
)

_INJURY_KW = (
    "重伤", "轻伤", "受伤", "吐血", "昏迷", "中毒", "虚弱",
    "伤势", "断臂", "失血", "濒死", "瘫倒",
)

_HEALTHY_KW = ("痊愈", "恢复", "无恙", "康复", "好转")

_ABILITY_KW = (
    "领悟", "学会", "掌握", "习得", "觉醒", "练成", "突破",
    "获得", "融合", "炼成", "悟出", "参悟",
)

_POWER_KW = (
    "突破", "晋级", "进阶", "升级", "觉醒", "领悟", "化神",
    "筑基", "金丹", "元婴", "渡劫", "飞升", "凝气", "结丹",
)

_RELATIONSHIP_KW = {
    "结盟": ("结盟", "联手", "合作", "结为", "盟友"),
    "敌对": ("反目", "敌对", "仇敌", "翻脸", "决裂"),
    "初识": ("初识", "初次见面", "相遇", "认识", "邂逅"),
    "师徒": ("拜师", "收徒", "师父", "师傅"),
    "友好": ("救命之恩", "信任", "感激", "相助", "好感"),
}

_EMOTION_KW = {
    "愤怒": ("怒", "暴怒", "愤怒", "恼怒", "大怒"),
    "悲伤": ("悲", "痛哭", "泪", "哀", "悲伤", "悲痛", "哭泣"),
    "恐惧": ("恐惧", "害怕", "惊恐", "颤抖", "胆寒"),
    "喜悦": ("喜", "笑", "高兴", "欣慰", "开心", "大喜"),
    "焦虑": ("焦虑", "不安", "忧虑", "担忧", "焦急"),
    "坚定": ("坚定", "决心", "下定决心", "毅然", "义无反顾"),
    "震惊": ("震惊", "惊讶", "愕然", "大惊", "骇然"),
    "平静": ("平静", "淡然", "冷静", "从容"),
}

_WORLD_LOCATION_PATTERNS = (
    r"(?:来到|抵达|进入|踏入|走进|到达|发现)(?:了)?(.{2,10})",
)

_WORLD_FACTION_KW = (
    "门派", "宗门", "帮派", "势力", "组织", "家族", "王朝",
    "军队", "商会", "教派", "联盟", "暗部",
)

_FORESHADOWING_PLANT_KW = (
    "暗示", "隐约", "似乎", "不为人知", "秘密", "留下",
    "悄悄", "谜团", "伏笔", "征兆", "预兆", "隐藏",
)

_FORESHADOWING_COLLECT_KW = (
    "原来", "终于", "真相", "揭开", "谜底", "恍然大悟",
    "这才明白", "难怪", "怪不得", "果然", "印证",
)


# ---------------------------------------------------------------------------
# LLM extraction prompt
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM_PROMPT = """\
你是小说叙事状态分析师。从章节文本中提取以下变化：

1. 角色变化：受伤/恢复、获得新能力、关系变化（敌→友、陌生→认识等）、情绪转变、位置移动
2. 世界观变化：新地点、新势力、新规则、新物品
3. 伏笔：本章埋下的新伏笔、本章回收的旧伏笔
4. 弧线推进：哪条故事线有进展、推进了多少（0.0~1.0之间的增量）
5. 章节摘要：一句话概括本章核心事件

只提取明确发生的变化，不要推测。输出严格 JSON 格式如下：
{
    "character_updates": [
        {"name": "角色名", "changes": {"health": "轻伤→恢复", "new_ability": "引灵术", "relationship": {"苏晚照": "初识"}, "location": "山洞", "emotion": "坚定"}}
    ],
    "world_updates": [
        {"type": "new_location", "name": "山北断崖", "description": "枯松下的藏物点"}
    ],
    "foreshadowing_planted": [
        {"description": "引灵外物暗示无灵根有解", "chapter": %d}
    ],
    "foreshadowing_collected": [
        {"description": "第2章埋下的神秘人终于冒头", "original_chapter": 2}
    ],
    "arc_updates": [
        {"arc_name": "矿脉争夺", "progress_delta": 0.15, "phase_note": "资源整合完成"}
    ],
    "outline_summary": "林辰整顿矿脉管理，建立分配制度，发现神秘修士"
}

如果某类变化没有发生，对应字段输出空数组 [] 或空字符串。"""


# ---------------------------------------------------------------------------
# StateWriteback class
# ---------------------------------------------------------------------------


class StateWriteback:
    """Extracts narrative state changes from a generated chapter and
    writes them back to persistent storage.

    Handles:
    - Character changes: injuries, power-ups, relationship shifts, new abilities
    - World changes: new locations discovered, factions introduced, rules revealed
    - Foreshadowing: marks planted/collected foreshadowing
    - Arc progress: updates story arc completion rates
    - Outline sync: updates the current chapter's outline with actual content summary
    """

    def __init__(self, llm_client: Any | None = None):
        self.llm = llm_client

    # ------------------------------------------------------------------
    # Public API: extract
    # ------------------------------------------------------------------

    def extract_changes(
        self,
        chapter_text: str,
        chapter_number: int,
        characters: list[dict] | None = None,
        world_setting: dict | None = None,
        chapter_brief: dict | None = None,
    ) -> dict:
        """Extract all narrative state changes from the chapter text.

        Uses LLM extraction when available, otherwise falls back to
        rule-based keyword matching.

        Returns:
            Dict with keys: character_updates, world_updates,
            foreshadowing_planted, foreshadowing_collected,
            arc_updates, outline_summary
        """
        if not chapter_text:
            return _empty_changes()

        if self.llm is not None:
            try:
                return self._extract_via_llm(
                    chapter_text, chapter_number, characters, world_setting, chapter_brief
                )
            except Exception as exc:
                log.warning("LLM extraction failed, falling back to rule-based: %s", exc)

        return self._extract_rule_based(
            chapter_text, chapter_number, characters, world_setting
        )

    # ------------------------------------------------------------------
    # Public API: write back
    # ------------------------------------------------------------------

    def write_back(
        self,
        changes: dict,
        chapter_number: int,
        state: dict,
        memory: Any | None = None,
        obligation_tracker: Any | None = None,
    ) -> dict:
        """Write extracted changes back to persistent storage.

        Updates:
        - state["characters"]: merge character_updates into character profiles
        - state["world_setting"]: merge world_updates
        - memory.structured_db: character states, facts
        - obligation_tracker: mark fulfilled debts based on foreshadowing_collected
        - state["outline"]: update current chapter's summary

        Returns a summary dict of what was updated.
        """
        summary: dict[str, Any] = {
            "characters_updated": 0,
            "world_updates_applied": 0,
            "foreshadowing_planted": 0,
            "foreshadowing_collected": 0,
            "debts_fulfilled": 0,
            "outline_updated": False,
        }

        # --- 1. Character updates ---
        summary["characters_updated"] = self._merge_character_updates(
            changes.get("character_updates", []),
            state,
            memory,
            chapter_number,
        )

        # --- 2. World setting updates ---
        summary["world_updates_applied"] = self._merge_world_updates(
            changes.get("world_updates", []),
            state,
            memory,
            chapter_number,
        )

        # --- 3. Foreshadowing planted → record as facts ---
        planted = changes.get("foreshadowing_planted", [])
        summary["foreshadowing_planted"] = self._record_foreshadowing_planted(
            planted, memory, chapter_number
        )

        # --- 4. Foreshadowing collected → mark debts fulfilled ---
        collected = changes.get("foreshadowing_collected", [])
        summary["foreshadowing_collected"] = len(collected)
        summary["debts_fulfilled"] = self._mark_collected_debts(
            collected, obligation_tracker, chapter_number
        )

        # --- 5. Outline summary update ---
        outline_summary = changes.get("outline_summary", "")
        if outline_summary:
            summary["outline_updated"] = self._update_outline_summary(
                state, chapter_number, outline_summary
            )

        return summary

    # ------------------------------------------------------------------
    # LLM extraction
    # ------------------------------------------------------------------

    def _extract_via_llm(
        self,
        chapter_text: str,
        chapter_number: int,
        characters: list[dict] | None,
        world_setting: dict | None,
        chapter_brief: dict | None,
    ) -> dict:
        """Use a single LLM call to extract all changes."""
        from src.novel.utils import extract_json_from_llm

        char_names = []
        if characters:
            for c in characters:
                name = c.get("name", "") if isinstance(c, dict) else getattr(c, "name", "")
                if name:
                    char_names.append(name)

        user_parts = [f"## 第{chapter_number}章正文\n{chapter_text}"]
        if char_names:
            user_parts.append(f"\n## 已知角色\n{', '.join(char_names)}")
        if chapter_brief:
            user_parts.append(f"\n## 章节任务书摘要\n{chapter_brief}")

        system_prompt = _EXTRACTION_SYSTEM_PROMPT % chapter_number

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

        response = self.llm.chat(messages, temperature=0.3, json_mode=True, max_tokens=2048)
        result = extract_json_from_llm(response.content)

        # Normalize and validate the result
        return _normalize_changes(result, chapter_number)

    # ------------------------------------------------------------------
    # Rule-based extraction
    # ------------------------------------------------------------------

    def _extract_rule_based(
        self,
        chapter_text: str,
        chapter_number: int,
        characters: list[dict] | None,
        world_setting: dict | None,
    ) -> dict:
        """Rule-based extraction using keyword matching."""
        changes = _empty_changes()

        sentences = re.split(r"[。！？\n]", chapter_text)
        sentences = [s.strip() for s in sentences if s.strip()]

        # --- Character changes ---
        char_names = []
        if characters:
            for c in characters:
                name = c.get("name", "") if isinstance(c, dict) else getattr(c, "name", "")
                if name:
                    char_names.append(name)

        for name in char_names:
            char_change = self._extract_char_changes_rule(name, sentences)
            if char_change:
                changes["character_updates"].append({
                    "name": name,
                    "changes": char_change,
                })

        # --- World updates ---
        changes["world_updates"] = self._extract_world_updates_rule(sentences)

        # --- Foreshadowing ---
        changes["foreshadowing_planted"] = self._extract_foreshadowing_planted_rule(
            sentences, chapter_number
        )
        changes["foreshadowing_collected"] = self._extract_foreshadowing_collected_rule(
            sentences
        )

        # --- Outline summary (first + last sentence heuristic) ---
        if sentences:
            first = sentences[0][:50] if sentences else ""
            last = sentences[-1][:50] if len(sentences) > 1 else ""
            changes["outline_summary"] = f"{first}...{last}" if last else first

        return changes

    def _extract_char_changes_rule(
        self, char_name: str, sentences: list[str]
    ) -> dict[str, Any]:
        """Extract changes for a single character using keyword matching."""
        relevant = [s for s in reversed(sentences) if char_name in s]
        if not relevant:
            return {}

        changes: dict[str, Any] = {}

        for sent in relevant:
            # Health
            if "health" not in changes:
                for kw in _INJURY_KW:
                    if kw in sent:
                        changes["health"] = kw
                        break
                if "health" not in changes:
                    for kw in _HEALTHY_KW:
                        if kw in sent:
                            changes["health"] = kw
                            break

            # New abilities
            if "new_ability" not in changes:
                for kw in _ABILITY_KW:
                    if kw in sent:
                        # Try to extract ability name from context
                        m = re.search(rf"{kw}(?:了)?(.{{2,8}})", sent)
                        if m:
                            changes["new_ability"] = m.group(1).strip("，。、！？ ")
                        else:
                            changes["new_ability"] = kw
                        break

            # Power level
            if "power_level" not in changes:
                for kw in _POWER_KW:
                    if kw in sent:
                        changes["power_level"] = kw
                        break

            # Location
            if "location" not in changes:
                for kw in _LOCATION_KW:
                    if kw in sent:
                        changes["location"] = kw
                        break

            # Emotion
            if "emotion" not in changes:
                for emotion, keywords in _EMOTION_KW.items():
                    if any(kw in sent for kw in keywords):
                        changes["emotion"] = emotion
                        break

            # Relationship (check all other known characters)
            if "relationship" not in changes:
                for rel_type, keywords in _RELATIONSHIP_KW.items():
                    if any(kw in sent for kw in keywords):
                        changes["relationship"] = rel_type
                        break

            # Early exit if we have enough
            if len(changes) >= 4:
                break

        return changes

    def _extract_world_updates_rule(self, sentences: list[str]) -> list[dict]:
        """Extract world updates from sentences."""
        updates: list[dict] = []
        seen_locations: set[str] = set()

        for sent in sentences:
            # New locations discovered
            for pattern in _WORLD_LOCATION_PATTERNS:
                for m in re.finditer(pattern, sent):
                    loc_name = m.group(1).strip("，。、！？ ")
                    if loc_name and loc_name not in seen_locations and len(loc_name) >= 2:
                        seen_locations.add(loc_name)
                        updates.append({
                            "type": "new_location",
                            "name": loc_name,
                            "description": sent[:60],
                        })

            # New factions/organizations mentioned
            for kw in _WORLD_FACTION_KW:
                if kw in sent:
                    # Try to extract the faction name
                    m = re.search(rf"(.{{2,6}}){kw}", sent)
                    if m:
                        faction_name = m.group(1).strip("，。、！？的了 ") + kw
                        if len(faction_name) >= 3:
                            updates.append({
                                "type": "new_faction",
                                "name": faction_name,
                                "description": sent[:60],
                            })
                    break  # Only one faction per sentence

        # Deduplicate: keep unique by name
        seen: set[str] = set()
        deduped: list[dict] = []
        for u in updates:
            if u["name"] not in seen:
                seen.add(u["name"])
                deduped.append(u)
        return deduped[:5]  # Cap at 5 updates per chapter

    def _extract_foreshadowing_planted_rule(
        self, sentences: list[str], chapter_number: int
    ) -> list[dict]:
        """Detect potential foreshadowing planted in the chapter."""
        planted: list[dict] = []
        for sent in sentences:
            score = sum(1 for kw in _FORESHADOWING_PLANT_KW if kw in sent)
            if score >= 2:  # Need at least 2 indicators
                planted.append({
                    "description": sent[:80],
                    "chapter": chapter_number,
                })
        return planted[:3]  # Cap at 3

    def _extract_foreshadowing_collected_rule(
        self, sentences: list[str]
    ) -> list[dict]:
        """Detect potential foreshadowing collected (paid off) in the chapter."""
        collected: list[dict] = []
        for sent in sentences:
            score = sum(1 for kw in _FORESHADOWING_COLLECT_KW if kw in sent)
            if score >= 2:  # Need at least 2 indicators
                # Try to extract original chapter reference
                original_chapter = None
                m = re.search(r"第(\d+)章", sent)
                if m:
                    original_chapter = int(m.group(1))
                collected.append({
                    "description": sent[:80],
                    "original_chapter": original_chapter,
                })
        return collected[:3]  # Cap at 3

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _merge_character_updates(
        self,
        updates: list[dict],
        state: dict,
        memory: Any | None,
        chapter_number: int,
    ) -> int:
        """Merge character updates into state and memory. Returns count."""
        if not updates:
            return 0

        characters = state.get("characters") or []
        count = 0

        for update in updates:
            name = update.get("name", "")
            if not name:
                continue

            char_changes = update.get("changes", {})
            if not char_changes:
                continue

            # Find matching character in state
            for char in characters:
                char_name = char.get("name", "") if isinstance(char, dict) else getattr(char, "name", "")
                if char_name != name:
                    continue

                if not isinstance(char, dict):
                    # Can't modify non-dict characters
                    continue

                # Merge changes into the character dict (ADD/UPDATE only, never remove)
                if char_changes.get("health"):
                    char.setdefault("status", {})
                    if isinstance(char.get("status"), dict):
                        char["status"]["health"] = char_changes["health"]

                if char_changes.get("new_ability"):
                    abilities = char.get("abilities", [])
                    if isinstance(abilities, list):
                        new_ab = char_changes["new_ability"]
                        if new_ab not in abilities:
                            abilities.append(new_ab)
                            char["abilities"] = abilities

                if char_changes.get("power_level"):
                    char.setdefault("status", {})
                    if isinstance(char.get("status"), dict):
                        char["status"]["power_level"] = char_changes["power_level"]

                if char_changes.get("location"):
                    char.setdefault("status", {})
                    if isinstance(char.get("status"), dict):
                        char["status"]["location"] = char_changes["location"]

                if char_changes.get("emotion"):
                    char.setdefault("status", {})
                    if isinstance(char.get("status"), dict):
                        char["status"]["emotional_state"] = char_changes["emotion"]

                if char_changes.get("relationship"):
                    relationships = char.get("relationships", {})
                    if isinstance(relationships, dict):
                        rel_data = char_changes["relationship"]
                        if isinstance(rel_data, dict):
                            relationships.update(rel_data)
                        # else: relationship is a string type, we store it as a note
                        char["relationships"] = relationships

                count += 1

                # Persist to structured DB if available
                if memory and hasattr(memory, "structured_db") and memory.structured_db:
                    try:
                        char_id = char.get("character_id", char_name)
                        memory.structured_db.insert_character_state(
                            character_id=char_id,
                            chapter=chapter_number,
                            location=char_changes.get("location", ""),
                            health=char_changes.get("health", ""),
                            emotional_state=char_changes.get("emotion", ""),
                            power_level=char_changes.get("power_level", ""),
                        )
                    except Exception as exc:
                        log.debug("Failed to persist character state to DB: %s", exc)

                break  # Found the matching character

        return count

    def _merge_world_updates(
        self,
        updates: list[dict],
        state: dict,
        memory: Any | None,
        chapter_number: int,
    ) -> int:
        """Merge world updates into state. Returns count."""
        if not updates:
            return 0

        world_setting = state.get("world_setting")
        if world_setting is None:
            world_setting = {}
            state["world_setting"] = world_setting

        if not isinstance(world_setting, dict):
            return 0

        count = 0

        for update in updates:
            update_type = update.get("type", "")
            name = update.get("name", "")
            description = update.get("description", "")

            if not name:
                continue

            if update_type == "new_location":
                locations = world_setting.setdefault("discovered_locations", [])
                if isinstance(locations, list):
                    # Avoid duplicates
                    existing_names = {
                        loc.get("name", "") if isinstance(loc, dict) else str(loc)
                        for loc in locations
                    }
                    if name not in existing_names:
                        locations.append({
                            "name": name,
                            "description": description,
                            "discovered_chapter": chapter_number,
                        })
                        count += 1

            elif update_type == "new_faction":
                factions = world_setting.setdefault("discovered_factions", [])
                if isinstance(factions, list):
                    existing_names = {
                        f.get("name", "") if isinstance(f, dict) else str(f)
                        for f in factions
                    }
                    if name not in existing_names:
                        factions.append({
                            "name": name,
                            "description": description,
                            "discovered_chapter": chapter_number,
                        })
                        count += 1

            else:
                # Generic update
                extras = world_setting.setdefault("extras", [])
                if isinstance(extras, list):
                    extras.append({
                        "type": update_type,
                        "name": name,
                        "description": description,
                        "chapter": chapter_number,
                    })
                    count += 1

            # Persist to memory as fact
            if memory and hasattr(memory, "structured_db") and memory.structured_db:
                try:
                    from src.novel.models.memory import Fact

                    fact_type = "location" if update_type == "new_location" else "event"
                    fact = Fact(
                        chapter=chapter_number,
                        type=fact_type,
                        content=f"{name}: {description}",
                        storage_layer="structured",
                    )
                    memory.structured_db.insert_fact(fact)
                except Exception as exc:
                    log.debug("Failed to persist world update as fact: %s", exc)

        return count

    def _record_foreshadowing_planted(
        self,
        planted: list[dict],
        memory: Any | None,
        chapter_number: int,
    ) -> int:
        """Record planted foreshadowing as facts in memory."""
        if not planted:
            return 0

        count = 0
        for item in planted:
            desc = item.get("description", "")
            if not desc:
                continue

            if memory and hasattr(memory, "structured_db") and memory.structured_db:
                try:
                    from src.novel.models.memory import Fact

                    fact = Fact(
                        chapter=chapter_number,
                        type="event",
                        content=f"[伏笔] {desc}",
                        storage_layer="structured",
                    )
                    memory.structured_db.insert_fact(fact)
                except Exception as exc:
                    log.debug("Failed to record foreshadowing fact: %s", exc)

            count += 1

        return count

    def _mark_collected_debts(
        self,
        collected: list[dict],
        obligation_tracker: Any | None,
        chapter_number: int,
    ) -> int:
        """Try to match collected foreshadowing with existing debts."""
        if not collected or not obligation_tracker:
            return 0

        fulfilled_count = 0
        try:
            debts = obligation_tracker.get_debts_for_chapter(chapter_number + 1)
        except Exception:
            return 0

        for item in collected:
            desc = item.get("description", "")
            original_ch = item.get("original_chapter")
            if not desc:
                continue

            for debt in debts:
                if _is_matching_debt(debt, desc, original_ch):
                    try:
                        obligation_tracker.mark_debt_fulfilled(
                            debt["debt_id"],
                            chapter_number,
                            note=f"Foreshadowing collected: {desc[:50]}",
                        )
                        fulfilled_count += 1
                    except Exception as exc:
                        log.debug("Failed to mark debt fulfilled: %s", exc)
                    break  # One collected item matches one debt

        return fulfilled_count

    @staticmethod
    def _update_outline_summary(
        state: dict, chapter_number: int, summary: str
    ) -> bool:
        """Update the outline entry for the given chapter with actual summary."""
        outline = state.get("outline")
        if not outline or not isinstance(outline, dict):
            return False

        chapters = outline.get("chapters", [])
        for ch in chapters:
            if ch.get("chapter_number") == chapter_number:
                ch["chapter_summary"] = summary
                return True

        return False


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _empty_changes() -> dict:
    """Return an empty changes dict."""
    return {
        "character_updates": [],
        "world_updates": [],
        "foreshadowing_planted": [],
        "foreshadowing_collected": [],
        "arc_updates": [],
        "outline_summary": "",
    }


def _normalize_changes(raw: dict, chapter_number: int) -> dict:
    """Normalize LLM output into expected format."""
    result = _empty_changes()

    if not isinstance(raw, dict):
        return result

    # character_updates
    cu = raw.get("character_updates", [])
    if isinstance(cu, list):
        for item in cu:
            if isinstance(item, dict) and item.get("name"):
                result["character_updates"].append(item)

    # world_updates
    wu = raw.get("world_updates", [])
    if isinstance(wu, list):
        for item in wu:
            if isinstance(item, dict) and item.get("name"):
                result["world_updates"].append(item)

    # foreshadowing_planted
    fp = raw.get("foreshadowing_planted", [])
    if isinstance(fp, list):
        for item in fp:
            if isinstance(item, dict) and item.get("description"):
                item.setdefault("chapter", chapter_number)
                result["foreshadowing_planted"].append(item)

    # foreshadowing_collected
    fc = raw.get("foreshadowing_collected", [])
    if isinstance(fc, list):
        for item in fc:
            if isinstance(item, dict) and item.get("description"):
                result["foreshadowing_collected"].append(item)

    # arc_updates
    au = raw.get("arc_updates", [])
    if isinstance(au, list):
        for item in au:
            if isinstance(item, dict) and item.get("arc_name"):
                result["arc_updates"].append(item)

    # outline_summary
    os_val = raw.get("outline_summary", "")
    if isinstance(os_val, str):
        result["outline_summary"] = os_val

    return result


def _is_matching_debt(
    debt: dict, collected_desc: str, original_chapter: int | None
) -> bool:
    """Heuristic: check if a collected foreshadowing matches a pending debt.

    Matching strategy:
    1. If original_chapter is provided, check source_chapter match
    2. Check keyword overlap between debt description and collected description
    """
    # If we know the original chapter, it must match the debt source
    if original_chapter is not None:
        if debt.get("source_chapter") != original_chapter:
            return False

    # Keyword overlap heuristic
    debt_desc = debt.get("description", "")
    if not debt_desc or not collected_desc:
        return False

    # Simple overlap: count shared 2-char substrings
    debt_chars = {debt_desc[i:i + 2] for i in range(len(debt_desc) - 1)}
    collected_chars = {collected_desc[i:i + 2] for i in range(len(collected_desc) - 1)}

    if not debt_chars or not collected_chars:
        return False

    overlap = len(debt_chars & collected_chars)
    overlap_ratio = overlap / min(len(debt_chars), len(collected_chars))

    return overlap_ratio >= 0.3


# ---------------------------------------------------------------------------
# LangGraph node function
# ---------------------------------------------------------------------------


def state_writeback_node(state: NovelState) -> dict[str, Any]:
    """LangGraph node: StateWriteback.

    Post-write state extraction and persistence:
    1. Read chapter text and metadata from state
    2. Extract narrative changes (LLM or rule-based)
    3. Write changes back to persistent storage
    4. Return state updates with decisions log
    """
    decisions: list[Decision] = []
    errors: list[dict] = []

    chapter_text = state.get("current_chapter_text")
    if not chapter_text:
        return {
            "errors": [{"agent": "StateWriteback", "message": "No chapter text, skipping state writeback"}],
            "completed_nodes": ["state_writeback"],
        }

    current_chapter = state.get("current_chapter", 1)
    characters = state.get("characters") or []
    world_setting = state.get("world_setting")
    chapter_brief = state.get("current_chapter_brief")
    obligation_tracker = state.get("obligation_tracker")

    # Get LLM client (optional — lightweight task, use quality_review config)
    llm = None
    try:
        from src.llm.llm_client import create_llm_client
        from src.novel.llm_utils import get_stage_llm_config

        llm_config = get_stage_llm_config(state, "quality_review")
        llm = create_llm_client(llm_config)
    except Exception:
        log.info("LLM not available, StateWriteback will use rule-based extraction")

    writeback = StateWriteback(llm)

    # --- Step 1: Extract changes ---
    try:
        changes = writeback.extract_changes(
            chapter_text=chapter_text,
            chapter_number=current_chapter,
            characters=characters,
            world_setting=world_setting,
            chapter_brief=chapter_brief,
        )
    except Exception as exc:
        log.error("StateWriteback extraction failed: %s", exc)
        return {
            "errors": [{"agent": "StateWriteback", "message": f"Extraction failed: {exc}"}],
            "completed_nodes": ["state_writeback"],
        }

    # --- Step 2: Get or create memory (if possible) ---
    memory = None
    novel_id = state.get("novel_id", "")
    workspace = state.get("workspace", "")
    if novel_id and workspace:
        try:
            from src.novel.storage.novel_memory import NovelMemory
            memory = NovelMemory(novel_id, workspace)
        except Exception:
            log.debug("StateWriteback: NovelMemory not available")

    # --- Step 3: Write back ---
    try:
        summary = writeback.write_back(
            changes=changes,
            chapter_number=current_chapter,
            state=state,
            memory=memory,
            obligation_tracker=obligation_tracker,
        )
    except Exception as exc:
        log.error("StateWriteback persistence failed: %s", exc)
        return {
            "errors": [{"agent": "StateWriteback", "message": f"Writeback failed: {exc}"}],
            "completed_nodes": ["state_writeback"],
            "decisions": [_make_decision(
                step="extract_changes",
                decision="Extraction succeeded but writeback failed",
                reason=str(exc),
                data={"changes_keys": list(changes.keys())},
            )],
        }

    decisions.append(
        _make_decision(
            step="state_writeback",
            decision="State writeback complete",
            reason=f"Ch{current_chapter}: "
                   f"{summary.get('characters_updated', 0)} chars, "
                   f"{summary.get('world_updates_applied', 0)} world, "
                   f"{summary.get('foreshadowing_planted', 0)} planted, "
                   f"{summary.get('debts_fulfilled', 0)} debts fulfilled",
            data=summary,
        )
    )

    # Close memory if we created it
    if memory:
        try:
            memory.close()
        except Exception:
            pass

    return {
        "decisions": decisions,
        "errors": errors,
        "completed_nodes": ["state_writeback"],
    }
