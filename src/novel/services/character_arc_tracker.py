"""Character arc tracker — monitors character growth across chapters."""
from __future__ import annotations
from typing import Any
import logging
import re

log = logging.getLogger("novel.services.character_arc")


# Growth stage indicators
_GROWTH_KEYWORDS = {
    "awakening": ["觉醒", "悟道", "突破", "顿悟", "明白了", "理解了"],
    "trial": ["试炼", "考验", "困境", "挫败", "受挫", "反思"],
    "bonding": ["信任", "联手", "结盟", "共识", "情愫", "心动"],
    "conflict": ["对立", "决裂", "背叛", "翻脸", "争执", "对抗"],
    "transformation": ["蜕变", "改变", "重生", "脱胎换骨", "判若两人"],
    "loss": ["失去", "牺牲", "伤痛", "悲痛", "陨落"],
    "victory": ["胜利", "成功", "击败", "拿下", "完成"],
}


class CharacterArcTracker:
    """Tracks character growth arcs across chapters.

    Each character has an "arc_state" dict with:
        - current_stage: short label like "trial" / "awakening"
        - milestones: list of {chapter, event} entries
        - growth_summary: concise text about overall development
        - last_appearance: chapter number
    """

    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}

    def update_from_chapter(
        self,
        chapter_number: int,
        actual_summary: str,
        characters: list[dict],
    ) -> None:
        """Extract character development from a chapter's actual_summary.

        Args:
            chapter_number: The chapter just generated.
            actual_summary: Brief description of what happened.
            characters: List of character dicts with 'name' field.
        """
        if not actual_summary:
            return

        for char in characters:
            name = char.get("name", "")
            if not name or name not in actual_summary:
                continue

            state = self._states.setdefault(name, {
                "current_stage": "introduction",
                "milestones": [],
                "growth_summary": "",
                "last_appearance": 0,
            })

            # Update last appearance
            state["last_appearance"] = chapter_number

            # Detect growth stage from keywords
            new_stage = self._detect_stage(actual_summary, name)
            if new_stage and new_stage != state["current_stage"]:
                state["milestones"].append({
                    "chapter": chapter_number,
                    "from_stage": state["current_stage"],
                    "to_stage": new_stage,
                    "trigger": self._extract_trigger_sentence(actual_summary, name),
                })
                state["current_stage"] = new_stage
                log.info(
                    "角色 %s 弧线推进: %s -> %s (第%d章)",
                    name,
                    state["milestones"][-1]["from_stage"],
                    new_stage,
                    chapter_number,
                )

    def _detect_stage(self, summary: str, name: str) -> str:
        """Detect which growth stage the character is in based on keywords."""
        # Find sentences mentioning this character
        sentences = re.split(r'[。！？]', summary)
        relevant = [s for s in sentences if name in s]
        if not relevant:
            return ""

        relevant_text = "".join(relevant)

        # Score each stage
        scores: dict[str, int] = {}
        for stage, keywords in _GROWTH_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in relevant_text)
            if score > 0:
                scores[stage] = score

        if scores:
            return max(scores, key=scores.get)
        return ""

    def _extract_trigger_sentence(self, summary: str, name: str) -> str:
        """Get the sentence describing the character's milestone trigger."""
        sentences = re.split(r'(?<=[。！？])', summary)
        for s in sentences:
            if name in s and len(s.strip()) > 5:
                return s.strip()[:100]
        return ""

    def get_state(self, character_name: str) -> dict[str, Any]:
        """Get the current arc state for a character."""
        return self._states.get(character_name, {})

    def get_all_states(self) -> dict[str, dict[str, Any]]:
        """Return all tracked character states."""
        return dict(self._states)

    def format_for_prompt(self, character_names: list[str], current_chapter: int) -> str:
        """Format arc states as prompt injection for Writer.

        Only includes characters that will appear in the current chapter.
        """
        if not character_names:
            return ""

        lines = []
        for name in character_names:
            state = self._states.get(name)
            if not state:
                continue
            stage = state.get("current_stage", "introduction")
            chapters_since = current_chapter - state.get("last_appearance", current_chapter)

            stage_names = {
                "introduction": "初登场",
                "awakening": "觉醒/突破期",
                "trial": "试炼/挫败期",
                "bonding": "结盟/情感发展期",
                "conflict": "冲突/对立期",
                "transformation": "蜕变期",
                "loss": "失落/伤痛期",
                "victory": "胜利期",
            }

            line = f"- {name}: 当前处于「{stage_names.get(stage, stage)}」"
            if chapters_since > 5:
                line += f"（已 {chapters_since} 章未出场，需要重新介绍）"
            elif chapters_since > 0:
                line += f"（上次出场在第 {state['last_appearance']} 章）"

            milestones = state.get("milestones", [])
            if milestones:
                last_ms = milestones[-1]
                line += f"\n  最近成长：第{last_ms['chapter']}章 {last_ms.get('trigger', '')[:50]}"

            lines.append(line)

        if not lines:
            return ""

        return "## 角色弧线状态\n" + "\n".join(lines) + "\n\n要求：本章涉及的角色行为必须与其当前弧线阶段一致，禁止性格漂移。"

    def to_dict(self) -> dict:
        """Serialize for persistence."""
        return {"states": self._states}

    def from_dict(self, data: dict) -> None:
        """Restore from persisted data."""
        self._states = data.get("states", {})
