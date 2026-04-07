"""Unified continuity brief aggregation layer.

Aggregates data from existing but disconnected components into a single
``continuity_brief`` dict that is injected into the Writer's prompt before
each chapter generation.  Every data source is optional -- the service
degrades gracefully when components are absent.

Example::

    svc = ContinuityService(db=structured_db, obligation_tracker=tracker)
    brief = svc.generate_brief(
        chapter_number=12,
        chapters=state["chapters"],
        chapter_brief=outline.chapter_brief,
        story_arcs=arcs,
        characters=character_profiles,
    )
    prompt_block = svc.format_for_prompt(brief)
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.novel.services.obligation_tracker import ObligationTracker
    from src.novel.storage.structured_db import StructuredDB

log = logging.getLogger("novel.services.continuity")

# Tail length used when extracting continuation hooks from previous chapter text
_TAIL_CHARS = 1500

# Patterns that signal an unresolved hook at chapter end (Chinese fiction).
# All use non-capturing groups so finditer().group() returns the full match.
_HOOK_PATTERNS: list[re.Pattern[str]] = [
    # Question / exclamation at or near end of a sentence
    re.compile(r"[^。？！\n]{4,}[？?！!]"),
    # Decision / plan verbs followed by content
    re.compile(r"[^。！？\n]{0,15}(?:决定|打算|答应|准备|计划|承诺|约好|商定)[^。！？\n]{2,30}"),
    # Sudden events
    re.compile(r"[^。！？\n]{0,10}(?:突然|忽然|猛然|骤然|陡然)[^。！？\n]{2,30}"),
    # Departure verbs
    re.compile(r"[^。！？\n]{0,15}(?:离开|出发|赶往|动身|启程|前往)[^。！？\n]{2,20}"),
    # Trailing ellipsis (Chinese or ASCII)
    re.compile(r"[^。！？\n]{2,20}[\u2026\u22ef]{2,}"),
    # Temporal anchors (time markers signaling upcoming events)
    re.compile(r"[^。！？\n]{0,10}(?:明天|今晚|子时|午时|傍晚|天亮|次日|三日后|明早|入夜)[^。！？\n]{2,20}"),
    # Pending/upcoming actions
    re.compile(r"[^。！？\n]{0,10}(?:准备|即将|打算|要去|将要|等到|一到)[^。！？\n]{2,20}"),
    # Mysterious/suspense endings (someone appearing, something discovered)
    re.compile(r"[^。！？\n]{0,15}(?:一个人|一道身影|一个声音|一个熟人|有人|来人)[^。！？\n]{2,20}"),
    # Unfinished movement/location change
    re.compile(r"[^。！？\n]{0,10}(?:走向|朝着|赶往|奔向|冲向|跑向)[^。！？\n]{2,20}"),
]


class ContinuityService:
    """Aggregates existing narrative tracking components into a unified continuity brief."""

    def __init__(
        self,
        db: "StructuredDB | None" = None,
        obligation_tracker: "ObligationTracker | None" = None,
    ) -> None:
        self.db = db
        self.obligation_tracker = obligation_tracker

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_brief(
        self,
        chapter_number: int,
        chapters: list[dict] | None = None,
        chapter_brief: dict | None = None,
        story_arcs: list[dict] | None = None,
        characters: list | None = None,
    ) -> dict[str, Any]:
        """Generate a unified continuity brief for the given chapter.

        Every parameter except *chapter_number* is optional.  Missing data
        simply results in the corresponding section being left empty.

        Args:
            chapter_number: The upcoming chapter to generate.
            chapters: List of previous chapter dicts (each with at least
                ``chapter_number``, ``title``, ``full_text``).
            chapter_brief: The ``chapter_brief`` dict from the current
                chapter's ``ChapterOutline`` (optional fields: main_conflict,
                payoff, character_arc_step, foreshadowing_plant,
                foreshadowing_collect, end_hook_type).
            story_arcs: List of story arc dicts (each with at least
                ``arc_id``, ``name``, ``chapters``, ``phase``, ``status``).
            characters: List of ``CharacterProfile`` (Pydantic models or
                plain dicts with ``character_id``, ``name``, ``status``).

        Returns:
            A continuity brief dict ready for ``format_for_prompt()``.
        """
        brief: dict[str, Any] = {
            "chapter_number": chapter_number,
            "must_continue": [],
            "open_threads": [],
            "character_states": [],
            "active_arcs": [],
            "forbidden_breaks": [],
            "recommended_payoffs": [],
        }

        self._extract_continuation_hooks(brief, chapters or [], chapter_number)
        self._extract_open_threads(brief, chapter_number)
        self._extract_character_states(brief, chapter_number, characters)
        self._extract_active_arcs(brief, chapter_number, story_arcs)
        self._extract_dead_characters(brief, chapters or [], chapter_number)
        self._derive_forbidden_breaks(brief)
        self._extract_recommended_payoffs(brief, chapter_brief, chapter_number)

        return brief

    def format_for_prompt(self, brief: dict[str, Any]) -> str:
        """Format the brief into a readable Chinese prompt block for Writer injection.

        Returns an empty string when there is nothing meaningful to inject.
        """
        sections: list[str] = []

        ch = brief.get("chapter_number", "?")
        sections.append(f"## 第{ch}章 连续性摘要\n")

        # must_continue
        items = brief.get("must_continue", [])
        if items:
            sections.append("### 必须延续（上章遗留）")
            for item in items:
                sections.append(f"- {item}")
            sections.append("")

        # previous_ending — verbatim last sentences
        ending = brief.get("previous_ending", "")
        if ending:
            sections.append("### 上章结尾原文（本章必须从这里接续）")
            sections.append(f"「{ending}」")
            sections.append("⚠️ 本章第一段必须在时间、空间、人物动作上与上述结尾无缝衔接，禁止跳过任何未完成的事件。")
            sections.append("")

        # open_threads
        items = brief.get("open_threads", [])
        if items:
            sections.append("### 未解决的叙事线")
            for item in items:
                sections.append(f"- {item}")
            sections.append("")

        # character_states
        chars = brief.get("character_states", [])
        if chars:
            sections.append("### 角色当前状态")
            for c in chars:
                parts = [c.get("name", "?")]
                if c.get("location"):
                    parts.append(f"位置: {c['location']}")
                if c.get("status"):
                    parts.append(f"状态: {c['status']}")
                if c.get("goal"):
                    parts.append(f"目标: {c['goal']}")
                sections.append(f"- {'，'.join(parts)}")
            sections.append("")

        # active_arcs
        arcs = brief.get("active_arcs", [])
        if arcs:
            sections.append("### 活跃故事弧线")
            for a in arcs:
                name = a.get("arc_name", "?")
                phase = a.get("phase", "?")
                remaining = a.get("chapters_remaining")
                rem_str = f"，剩余{remaining}章" if remaining is not None else ""
                sections.append(f"- {name}（阶段: {phase}{rem_str}）")
            sections.append("")

        # forbidden_breaks
        items = brief.get("forbidden_breaks", [])
        if items:
            sections.append("### 禁止违反")
            for item in items:
                sections.append(f"- {item}")
            sections.append("")

        # recommended_payoffs
        items = brief.get("recommended_payoffs", [])
        if items:
            sections.append("### 推荐推进")
            for item in items:
                sections.append(f"- {item}")
            sections.append("")

        # If only the header was added, return empty
        if len(sections) <= 1:
            return ""

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_continuation_hooks(
        self,
        brief: dict[str, Any],
        chapters: list[dict],
        chapter_number: int,
    ) -> None:
        """Extract must-continue items from the previous chapter's ending."""
        if not chapters:
            return

        # Find the previous chapter (chapter_number - 1)
        prev_chapter = None
        for ch in chapters:
            ch_num = ch.get("chapter_number", 0)
            if ch_num == chapter_number - 1:
                prev_chapter = ch
                break

        if prev_chapter is None:
            return

        # Scan the tail of the previous chapter text for hook patterns
        full_text = prev_chapter.get("full_text", "")
        if full_text:
            tail = full_text[-_TAIL_CHARS:]
            for pattern in _HOOK_PATTERNS:
                for m in pattern.finditer(tail):
                    cleaned = m.group().strip()
                    if cleaned and len(cleaned) > 4:
                        brief["must_continue"].append(cleaned)

            # Deduplicate while preserving order
            seen: set[str] = set()
            deduped: list[str] = []
            for item in brief["must_continue"]:
                if item not in seen:
                    seen.add(item)
                    deduped.append(item)
            brief["must_continue"] = deduped[:5]  # Cap at 5

            # Always include the last 2-3 sentences verbatim as "ending_text"
            # This is critical for the Writer to know exactly where to pick up
            sentences = [s.strip() for s in re.split(r'[。！？\n]', full_text) if s.strip()]
            if sentences:
                last_sentences = '。'.join(sentences[-3:]) + '。'
                brief["previous_ending"] = last_sentences

        # Also check the *previous* chapter's outline chapter_brief for end_hook_type
        prev_outline = prev_chapter.get("outline")
        if prev_outline:
            # outline may be a Pydantic model or a dict
            if hasattr(prev_outline, "chapter_brief"):
                prev_brief = prev_outline.chapter_brief
            elif isinstance(prev_outline, dict):
                prev_brief = prev_outline.get("chapter_brief", {})
            else:
                prev_brief = {}

            if isinstance(prev_brief, dict):
                hook_type = prev_brief.get("end_hook_type")
                if hook_type:
                    brief["must_continue"].insert(
                        0,
                        f"上一章结尾钩子类型：{hook_type}，本章需要衔接",
                    )

    def _extract_open_threads(
        self,
        brief: dict[str, Any],
        chapter_number: int,
    ) -> None:
        """Get unresolved debts from the obligation tracker."""
        if self.obligation_tracker is None:
            return

        try:
            debts = self.obligation_tracker.get_debts_for_chapter(chapter_number)
        except Exception:
            log.warning("获取叙事债务失败", exc_info=True)
            return

        for debt in debts:
            desc = debt.get("description", "")
            source = debt.get("source_chapter", "?")
            urgency = debt.get("urgency_level", "normal")
            brief["open_threads"].append(
                f"{desc} (来源: 第{source}章, 紧急度: {urgency})"
            )

    def _extract_character_states(
        self,
        brief: dict[str, Any],
        chapter_number: int,
        characters: list | None,
    ) -> None:
        """Get latest character states from StructuredDB or character profiles."""
        if characters is None:
            characters = []

        for char in characters:
            # Support both Pydantic models and plain dicts
            if hasattr(char, "character_id"):
                char_id = char.character_id
                char_name = char.name
                char_status = getattr(char, "status", "active")
            elif isinstance(char, dict):
                char_id = char.get("character_id", "")
                char_name = char.get("name", "?")
                char_status = char.get("status", "active")
            else:
                continue

            entry: dict[str, Any] = {"name": char_name}

            # Try to get rich state from DB
            db_state = None
            if self.db is not None:
                try:
                    db_state = self.db.get_character_state(char_id)
                except Exception:
                    log.debug("查询角色状态失败: %s", char_id, exc_info=True)

            if db_state:
                # Only use DB values when they are non-empty; otherwise
                # fall through to profile-based defaults.
                entry["location"] = db_state.get("location", "") or ""
                entry["status"] = db_state.get("health", "") or char_status
                entry["goal"] = db_state.get("emotional_state", "") or ""
                entry["power_level"] = db_state.get("power_level", "") or ""
            else:
                # Fallback: derive from character profile
                entry["location"] = ""
                entry["status"] = char_status
                entry["goal"] = ""

            brief["character_states"].append(entry)

    def _extract_active_arcs(
        self,
        brief: dict[str, Any],
        chapter_number: int,
        story_arcs: list[dict] | None,
    ) -> None:
        """Filter story arcs that are currently active."""
        if not story_arcs:
            return

        for arc in story_arcs:
            status = arc.get("status", "")
            # Accept active, in_progress, planning arcs
            if status in ("completed", "abandoned"):
                continue

            chapters_raw = arc.get("chapters", [])
            # chapters may be a JSON string or a list
            if isinstance(chapters_raw, str):
                try:
                    chapters_list = json.loads(chapters_raw)
                except (json.JSONDecodeError, TypeError):
                    chapters_list = []
            else:
                chapters_list = chapters_raw

            if not chapters_list:
                continue

            # Check if the current chapter falls within or ahead of the arc range
            arc_start = min(chapters_list) if chapters_list else 0
            arc_end = max(chapters_list) if chapters_list else 0

            if chapter_number > arc_end:
                # Arc is in the past
                continue

            remaining = max(0, arc_end - chapter_number + 1)
            brief["active_arcs"].append({
                "arc_name": arc.get("name", "?"),
                "phase": arc.get("phase", "?"),
                "chapters_remaining": remaining,
            })

    def _derive_forbidden_breaks(self, brief: dict[str, Any]) -> None:
        """Derive hard continuity rules from character states and open threads."""
        # Location-based rules
        for char in brief.get("character_states", []):
            name = char.get("name", "")
            location = char.get("location", "")
            status = char.get("status", "")

            if location:
                brief["forbidden_breaks"].append(
                    f"{name}当前在{location}，不可无故出现在其他地点"
                )

            if status in ("deceased", "已死"):
                brief["forbidden_breaks"].append(
                    f"{name}已死亡，不能在本章出现（除非有合理解释如回忆/幻觉）"
                )
            elif status in ("absent", "离队", "离开"):
                brief["forbidden_breaks"].append(
                    f"{name}已离队/离开，不能无解释回归"
                )
            elif status and "伤" in status:
                brief["forbidden_breaks"].append(
                    f"{name}当前状态为{status}，不应有超出合理范围的行动表现"
                )

    def _extract_dead_characters(
        self,
        brief: dict,
        chapters: list[dict],
        chapter_number: int,
    ) -> None:
        """Detect characters that died in previous chapters from actual_summaries.

        Scans actual_summary fields for death keywords and adds entries to
        forbidden_breaks so the Writer knows not to reference them as alive.
        """
        if not chapters:
            return

        # Death-indicating patterns
        death_patterns = [
            re.compile(r"([\u4e00-\u9fa5]{2,8})(?:被)?(?:处决|处死|杀死|杀掉|斩杀|斩首|击杀|身亡|阵亡|死亡|毙命|身死|咽气|气绝|没了声息)"),
            re.compile(r"([\u4e00-\u9fa5]{2,8})(?:已)?(?:死|亡)(?:了|去)?"),
            re.compile(r"林辰(?:亲手)?(?:杀了|处决了|斩了)([\u4e00-\u9fa5]{2,8})"),
        ]

        dead_chars: set[str] = set()

        for ch in chapters:
            ch_n = ch.get("chapter_number", 0)
            if ch_n >= chapter_number:
                continue
            summary = ch.get("actual_summary", "")
            if not summary:
                continue
            for pattern in death_patterns:
                for m in pattern.finditer(summary):
                    name = m.group(1).strip()
                    # Filter out common verbs/words that aren't names
                    if name and len(name) >= 2 and name not in ("林辰", "他", "她", "那人", "众人", "敌人", "大家", "所有"):
                        # Skip captures that contain the protagonist's name
                        # (e.g. "林辰差点" from "林辰差点死在敌人手里")
                        if "林辰" in name:
                            continue
                        dead_chars.add(name)

        if dead_chars:
            for name in dead_chars:
                brief["forbidden_breaks"].append(
                    f"{name} 已死亡（前文章节中），不可作为活人出现，只能以'{name}余部'、'{name}残部'、'{name}的旧部'等形式提及"
                )

    def _extract_recommended_payoffs(
        self,
        brief: dict[str, Any],
        chapter_brief: dict | None,
        chapter_number: int,
    ) -> None:
        """Combine chapter_brief payoffs with approaching-deadline debts."""
        # From chapter_brief
        if chapter_brief and isinstance(chapter_brief, dict):
            payoff = chapter_brief.get("payoff")
            if payoff:
                brief["recommended_payoffs"].append(
                    f"本章任务书推荐兑现: {payoff}"
                )

            foreshadowing_collect = chapter_brief.get("foreshadowing_collect")
            if foreshadowing_collect:
                if isinstance(foreshadowing_collect, list):
                    for item in foreshadowing_collect:
                        brief["recommended_payoffs"].append(
                            f"伏笔收回: {item}"
                        )
                elif isinstance(foreshadowing_collect, str):
                    brief["recommended_payoffs"].append(
                        f"伏笔收回: {foreshadowing_collect}"
                    )

        # From obligation tracker -- debts approaching deadline
        if self.obligation_tracker is not None:
            try:
                debts = self.obligation_tracker.get_debts_for_chapter(
                    chapter_number
                )
            except Exception:
                debts = []

            for debt in debts:
                urgency = debt.get("urgency_level", "normal")
                if urgency in ("critical", "high"):
                    desc = debt.get("description", "")
                    source = debt.get("source_chapter", "?")
                    brief["recommended_payoffs"].append(
                        f"推进: {desc} (来自第{source}章, 紧急度: {urgency})"
                    )
