from __future__ import annotations
from typing import Any
import logging

log = logging.getLogger("novel.services.global_director")


class GlobalDirector:
    """Monitors whole-book state and produces directorial guidance.

    Key responsibilities:
    - Track current chapter's position within volume and overall story
    - Calculate volume progress (e.g., "you're at chapter 24 of 35 in volume 1, 73%")
    - Identify active story arcs and their phase
    - List unresolved foreshadowing that's about to expire
    - Suggest the chapter's role: setup / rising / climax / resolution
    """

    def __init__(self, novel_data: dict, outline: dict) -> None:
        self.novel_data = novel_data
        self.outline = outline
        self.volumes = outline.get("volumes", [])
        self.story_arcs = outline.get("story_arcs", [])
        self.total_chapters = len(outline.get("chapters", []))

    def analyze(self, chapter_number: int, recent_summaries: list[dict]) -> dict[str, Any]:
        """Produce a directorial brief for the given chapter.

        Args:
            chapter_number: The chapter being generated.
            recent_summaries: List of {chapter_number, title, actual_summary} for last ~5 chapters.

        Returns:
            A dict with keys:
                - position: current volume info, % complete, chapters remaining
                - phase: rising | climax | resolution | setup | transition
                - active_arcs: list of active story arc info
                - unresolved_foreshadowing: list of items planted but not collected
                - directorial_notes: list of guidance strings
        """
        brief: dict[str, Any] = {
            "chapter_number": chapter_number,
            "position": self._calculate_position(chapter_number),
            "phase": self._determine_phase(chapter_number),
            "active_arcs": self._get_active_arcs(chapter_number),
            "unresolved_foreshadowing": [],
            "directorial_notes": [],
        }

        self._add_directorial_notes(brief, recent_summaries)
        return brief

    def _calculate_position(self, chapter_number: int) -> dict[str, Any]:
        """Find which volume and what % of it the chapter is in."""
        for vol in self.volumes:
            # Support two schemas: explicit chapters list OR start_chapter/end_chapter
            start = 0
            end = 0
            chs = vol.get("chapters", [])
            if isinstance(chs, list) and chs and all(isinstance(c, int) for c in chs):
                start = min(chs)
                end = max(chs)
            else:
                start = vol.get("start_chapter", 0) or 0
                end = vol.get("end_chapter", 0) or 0
            if start and end and start <= chapter_number <= end:
                progress = (chapter_number - start + 1) / (end - start + 1) if end > start else 1.0
                return {
                    "volume_number": vol.get("volume_number", 0),
                    "volume_title": vol.get("title", ""),
                    "volume_theme": vol.get("theme", ""),
                    "chapter_in_volume": chapter_number - start + 1,
                    "volume_total": end - start + 1,
                    "progress_pct": round(progress * 100, 1),
                    "chapters_remaining_in_volume": end - chapter_number,
                }
        # Fallback: rough estimate based on total
        return {
            "volume_number": 0,
            "volume_title": "未分卷",
            "progress_pct": round(chapter_number / max(self.total_chapters, 1) * 100, 1),
            "chapters_remaining_in_volume": max(self.total_chapters - chapter_number, 0),
        }

    def _determine_phase(self, chapter_number: int) -> str:
        """Estimate the story phase: setup / rising / climax / resolution / transition."""
        position = self._calculate_position(chapter_number)
        progress = position.get("progress_pct", 0) / 100
        if progress < 0.2:
            return "setup"  # 起势/开篇
        elif progress < 0.6:
            return "rising"  # 上升/铺垫
        elif progress < 0.85:
            return "climax"  # 高潮
        elif progress < 1.0:
            return "resolution"  # 收束
        else:
            return "transition"  # 卷末过渡

    def _get_active_arcs(self, chapter_number: int) -> list[dict]:
        """Filter story arcs that are currently active."""
        active = []
        for arc in self.story_arcs:
            chs = arc.get("chapters", [])
            if isinstance(chs, list) and chs:
                if all(isinstance(c, int) for c in chs):
                    if min(chs) <= chapter_number <= max(chs):
                        active.append({
                            "arc_id": arc.get("arc_id", ""),
                            "name": arc.get("name", "?"),
                            "phase": arc.get("phase", "active"),
                            "status": arc.get("status", "in_progress"),
                        })
        return active

    def _add_directorial_notes(self, brief: dict, recent_summaries: list[dict]) -> None:
        """Generate phase-specific directorial guidance."""
        phase = brief["phase"]
        position = brief["position"]
        remaining = position.get("chapters_remaining_in_volume", 0)

        notes = []

        # Phase-specific guidance
        if phase == "setup":
            notes.append("处于卷首设定期：建立悬念、引入核心角色、铺设主线伏笔")
        elif phase == "rising":
            notes.append("处于上升期：推进核心冲突、加深矛盾、避免节奏停滞")
        elif phase == "climax":
            notes.append(f"处于高潮期（卷剩 {remaining} 章）：情节张力必须持续上升，避免日常水文")
        elif phase == "resolution":
            notes.append(f"处于收束期（卷剩 {remaining} 章）：开始收伏笔、解决主要冲突、为下一卷铺垫")
        elif phase == "transition":
            notes.append("卷末过渡：必须收束当前卷的核心冲突，留下进入下一卷的钩子")

        # Volume nearing end warnings
        if remaining <= 3 and remaining > 0:
            notes.append(f"⚠️ 距离本卷收束仅剩 {remaining} 章，必须开始收线")

        # Repetition warning from recent summaries
        if len(recent_summaries) >= 3:
            recent_titles = [s.get("title", "") for s in recent_summaries[-3:]]
            # Check for repetitive setting (single character match for broad detection)
            common_chars = []
            if all(recent_titles):
                # Single-char keywords that indicate scene type
                for ch in ["矿", "营", "村", "山", "城", "门", "宫", "宗"]:
                    if all(ch in t for t in recent_titles):
                        common_chars.append(ch)
            if common_chars:
                notes.append(f"⚠️ 最近 3 章场景集中在「{','.join(common_chars)}」相关，建议切换场景或推进新冲突")

        brief["directorial_notes"] = notes

    def format_for_prompt(self, brief: dict[str, Any]) -> str:
        """Format the directorial brief as a prompt block for Writer injection."""
        lines = ["## 全局导演视角"]

        pos = brief.get("position", {})
        if pos:
            vol_title = pos.get("volume_title", "")
            ch_in_vol = pos.get("chapter_in_volume", "?")
            vol_total = pos.get("volume_total", "?")
            pct = pos.get("progress_pct", 0)
            lines.append(f"- 位置：「{vol_title}」第 {ch_in_vol}/{vol_total} 章（{pct}%）")
            remaining = pos.get("chapters_remaining_in_volume", 0)
            lines.append(f"- 卷内剩余：{remaining} 章")

        phase = brief.get("phase", "")
        phase_names = {
            "setup": "起势/开篇",
            "rising": "上升/推进",
            "climax": "高潮",
            "resolution": "收束",
            "transition": "卷末过渡",
        }
        if phase:
            lines.append(f"- 阶段：{phase_names.get(phase, phase)}")

        arcs = brief.get("active_arcs", [])
        if arcs:
            arc_names = [f"{a.get('name', '?')}({a.get('phase', '?')})" for a in arcs]
            lines.append(f"- 活跃弧线：{', '.join(arc_names)}")

        notes = brief.get("directorial_notes", [])
        if notes:
            lines.append("- 导演指引：")
            for n in notes:
                lines.append(f"  · {n}")

        if len(lines) <= 1:
            return ""
        return "\n".join(lines)
