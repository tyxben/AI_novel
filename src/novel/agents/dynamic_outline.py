"""DynamicOutlinePlanner - Pre-write dynamic outline revision

Before each chapter is written, this node revises the static outline
based on what actually happened in previous chapters.  It compares the
original outline goals with actual narrative progress and produces a
revised outline that accounts for plot deviations, unresolved narrative
debts, character state changes and story arc phase requirements.

All methods are SYNC (not async).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.llm.llm_client import LLMClient, LLMResponse, create_llm_client
from src.novel.agents.state import Decision
from src.novel.llm_utils import get_stage_llm_config
from src.novel.utils import extract_json_from_llm

log = logging.getLogger("novel")

# ---------------------------------------------------------------------------
# Required fields that must appear in every revised outline
# ---------------------------------------------------------------------------

_REQUIRED_OUTLINE_FIELDS = {
    "title",
    "goal",
    "key_events",
    "mood",
    "involved_characters",
    "estimated_words",
}

# ---------------------------------------------------------------------------
# System / User prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
你是小说章纲修订专家。你的任务是对比"原始章纲"和"实际前文进展"，决定本章大纲是否需要调整。

## 修订原则
1. 如果原始章纲与前文连贯，不需要大改——保持稳定性
2. 如果前文出现了原始章纲没预料到的重大变化，必须调整本章目标
3. 必须考虑未解决的叙事债务——逾期的伏笔优先回收
4. 角色当前状态必须和章纲一致（不能让受伤角色突然健康出场）
5. 故事弧线阶段决定本章应该处于什么张力水平
6. 修订后的大纲必须保持与后续章节的兼容性，不能破坏后续计划

## 输出要求
返回严格的 JSON（不要添加额外文字）：
{
  "revision_needed": true/false,
  "revision_reason": "修订原因（如无需修订写'原始大纲与前文一致'）",
  "revised_outline": {
    "title": "章节标题",
    "goal": "本章目标",
    "key_events": ["事件1", "事件2"],
    "mood": "蓄力|小爽|大爽|过渡|虐心|反转|日常",
    "involved_characters": ["角色名1", "角色名2"],
    "estimated_words": 2500,
    "chapter_brief": {
      "main_conflict": "...",
      "payoff": "...",
      "character_arc_step": "...",
      "foreshadowing_plant": [],
      "foreshadowing_collect": [],
      "end_hook_type": "..."
    }
  }
}

如果 revision_needed 为 false，revised_outline 中直接返回原始大纲内容。"""

_USER_PROMPT_TEMPLATE = """\
## 原始章纲（第{chapter_number}章）
- 标题: {title}
- 目标: {goal}
- 关键事件: {key_events}
- 情绪基调: {mood}
- 涉及角色: {involved_characters}
- 预估字数: {estimated_words}
{chapter_brief_section}

## 前文摘要（最近章节实际发生的事）
{previous_summaries}

## 连续性约束
{continuity_brief}

## 未了结叙事债务
{debt_summary}

## 角色当前状态
{character_states}

## 故事弧线状态
{arc_status}

## 后续章纲预览（保持兼容）
{upcoming_outlines}

请判断原始章纲是否需要修订，并返回 JSON。"""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_decision(
    step: str,
    decision: str,
    reason: str,
    data: dict[str, Any] | None = None,
) -> Decision:
    return Decision(
        agent="DynamicOutlinePlanner",
        step=step,
        decision=decision,
        reason=reason,
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _format_chapter_brief(brief: dict | None) -> str:
    """Format chapter_brief dict into readable lines."""
    if not brief:
        return ""
    lines = ["\n### 章节任务书"]
    if brief.get("main_conflict"):
        lines.append(f"- 主冲突: {brief['main_conflict']}")
    if brief.get("payoff"):
        lines.append(f"- 爽点/回报: {brief['payoff']}")
    if brief.get("character_arc_step"):
        lines.append(f"- 角色弧线推进: {brief['character_arc_step']}")
    if brief.get("foreshadowing_plant"):
        plant = brief["foreshadowing_plant"]
        if isinstance(plant, list):
            plant = ", ".join(plant)
        lines.append(f"- 需埋伏笔: {plant}")
    if brief.get("foreshadowing_collect"):
        collect = brief["foreshadowing_collect"]
        if isinstance(collect, list):
            collect = ", ".join(collect)
        lines.append(f"- 需回收伏笔: {collect}")
    if brief.get("end_hook_type"):
        lines.append(f"- 章尾钩子类型: {brief['end_hook_type']}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _build_upcoming_outlines(
    outline: dict | None,
    chapter_number: int,
    window: int = 5,
) -> str:
    """Extract the next *window* chapter outlines after *chapter_number*."""
    if not outline or not isinstance(outline, dict):
        return "无后续章纲信息"

    all_chapters = outline.get("chapters", [])
    if not all_chapters:
        return "无后续章纲信息"

    upcoming: list[str] = []
    for ch in all_chapters:
        ch_num = ch.get("chapter_number", 0)
        if chapter_number < ch_num <= chapter_number + window:
            upcoming.append(
                f"- 第{ch_num}章「{ch.get('title', '?')}」: "
                f"{ch.get('goal', '?')} (关键事件: "
                f"{'、'.join(ch.get('key_events', []))})"
            )
    return "\n".join(upcoming) if upcoming else "无后续章纲信息"


def _build_previous_summaries(chapters: list[dict], count: int = 2) -> str:
    """Build summary text from the last *count* completed chapters."""
    if not chapters:
        return "无前文（第一章）"

    recent = chapters[-count:]
    lines: list[str] = []
    for ch in recent:
        ch_num = ch.get("chapter_number", "?")
        title = ch.get("title", "?")
        summary = ch.get("chapter_summary", "") or ch.get("summary", "")
        if not summary:
            # Fallback: use first 300 chars of full text
            text = ch.get("full_text", "")
            summary = text[:300] + "..." if len(text) > 300 else text
        lines.append(f"第{ch_num}章「{title}」: {summary}")
    return "\n".join(lines) if lines else "无前文信息"


def _format_character_states(characters: list[dict]) -> str:
    """Produce a compact summary of current character states."""
    if not characters:
        return "无角色信息"
    lines: list[str] = []
    for c in characters:
        name = c.get("name", "?")
        occupation = c.get("occupation", "")
        # character state might live in nested dict
        state_info = c.get("current_state", "")
        if state_info:
            lines.append(f"- {name}({occupation}): {state_info}")
        else:
            lines.append(f"- {name}({occupation})")
    return "\n".join(lines)


def _validate_revised_outline(
    revised: dict, original: dict
) -> dict:
    """Ensure the revised outline has all required fields.

    Missing fields are patched from *original* so downstream nodes
    never receive an incomplete outline.
    """
    for field in _REQUIRED_OUTLINE_FIELDS:
        if field not in revised or revised[field] is None:
            revised[field] = original.get(field)
    # Ensure key_events is a list
    if not isinstance(revised.get("key_events"), list):
        revised["key_events"] = original.get("key_events", [])
    # Ensure involved_characters is a list
    if not isinstance(revised.get("involved_characters"), list):
        revised["involved_characters"] = original.get(
            "involved_characters", []
        )
    # Ensure estimated_words is int
    try:
        revised["estimated_words"] = int(revised["estimated_words"])
    except (TypeError, ValueError):
        revised["estimated_words"] = original.get("estimated_words", 2500)
    # Carry over fields from original that the LLM may not return
    for key in ("chapter_number", "plot_threads", "storyline_progress",
                "chapter_summary", "arc_id", "effective_from_chapter",
                "deprecated_at_chapter", "version"):
        if key not in revised and key in original:
            revised[key] = original[key]
    # Ensure chapter_brief exists
    if "chapter_brief" not in revised or not isinstance(
        revised.get("chapter_brief"), dict
    ):
        revised["chapter_brief"] = original.get("chapter_brief", {})
    return revised


# ---------------------------------------------------------------------------
# DynamicOutlinePlanner class
# ---------------------------------------------------------------------------


class DynamicOutlinePlanner:
    """Revises a chapter's static outline based on actual narrative state.

    Compares the original outline goals with what actually happened in
    previous chapters, then produces a revised outline that accounts for:
    - Plot deviations from the original plan
    - Unresolved narrative debts that need attention
    - Character state changes that affect the story
    - Story arc phase requirements
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    def revise_outline(
        self,
        chapter_number: int,
        original_outline: dict,
        previous_summaries: str,
        continuity_brief: str,
        debt_summary: str,
        character_states: list[dict],
        arc_status: str,
        world_changes: str = "",
        upcoming_outlines: str = "",
    ) -> dict:
        """Revise the chapter outline based on current narrative state.

        Returns a dict with keys:
        - ``revision_needed`` (bool)
        - ``revision_reason`` (str)
        - ``revised_outline`` (dict) — same structure as the original
          (title, goal, key_events, mood, involved_characters,
          estimated_words, chapter_brief) with content updated to
          reflect actual story progress.

        If no revision is needed the original outline is returned
        unchanged inside ``revised_outline``.
        """
        key_events_str = "、".join(
            original_outline.get("key_events", [])
        )
        involved_str = "、".join(
            original_outline.get("involved_characters", [])
        ) or "未指定"

        chapter_brief_section = _format_chapter_brief(
            original_outline.get("chapter_brief")
        )

        user_msg = _USER_PROMPT_TEMPLATE.format(
            chapter_number=chapter_number,
            title=original_outline.get("title", "?"),
            goal=original_outline.get("goal", "?"),
            key_events=key_events_str,
            mood=original_outline.get("mood", "蓄力"),
            involved_characters=involved_str,
            estimated_words=original_outline.get("estimated_words", 2500),
            chapter_brief_section=chapter_brief_section,
            previous_summaries=previous_summaries,
            continuity_brief=continuity_brief or "无",
            debt_summary=debt_summary or "无",
            character_states=_format_character_states(character_states),
            arc_status=arc_status or "无弧线信息",
            upcoming_outlines=upcoming_outlines or "无后续章纲信息",
        )

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        response: LLMResponse = self.llm.chat(
            messages, temperature=0.4, json_mode=True, max_tokens=4096
        )
        if not response or not response.content:
            raise ValueError("LLM 返回空响应")

        parsed = extract_json_from_llm(response.content)

        revision_needed = parsed.get("revision_needed", False)
        revision_reason = parsed.get("revision_reason", "")
        revised = parsed.get("revised_outline", {})

        if not isinstance(revised, dict) or not revised:
            # LLM failed to produce a valid revised outline — keep original
            revised = dict(original_outline)
            revision_needed = False
            revision_reason = "LLM 未返回有效修订大纲，保留原始"

        revised = _validate_revised_outline(revised, original_outline)

        return {
            "revision_needed": bool(revision_needed),
            "revision_reason": revision_reason,
            "revised_outline": revised,
        }


# ---------------------------------------------------------------------------
# LangGraph node function
# ---------------------------------------------------------------------------


def dynamic_outline_node(state: dict) -> dict:
    """LangGraph node: revise the current chapter outline before writing.

    Reads from state:
    - ``current_chapter_outline``
    - ``continuity_brief``
    - ``debt_summary``
    - ``chapters`` (previous)
    - ``characters``
    - ``outline`` (for sliding window)
    - ``config``

    Returns state updates including ``current_chapter_outline`` (revised),
    ``decisions`` and ``completed_nodes``.
    """
    decisions: list[dict] = []

    chapter_number = state.get("current_chapter", 1)
    original_outline = state.get("current_chapter_outline")

    if not original_outline:
        return {
            "errors": [
                {
                    "agent": "DynamicOutlinePlanner",
                    "message": "当前章节大纲不存在",
                }
            ],
            "completed_nodes": ["dynamic_outline"],
        }

    # --- Fast-path: skip revision for early chapters (1-3) ---
    if chapter_number <= 3:
        decisions.append(
            _make_decision(
                step="skip_early",
                decision=f"跳过第{chapter_number}章动态修订（前3章无需修订）",
                reason="前3章缺少足够前文上下文",
            )
        )
        log.info(
            "DynamicOutline: 跳过第%d章（前3章无需修订）",
            chapter_number,
        )
        return {
            "decisions": decisions,
            "completed_nodes": ["dynamic_outline"],
        }

    # --- Build inputs ---
    chapters = state.get("chapters") or []
    previous_summaries = _build_previous_summaries(chapters, count=2)
    continuity_brief = state.get("continuity_brief", "")
    debt_summary = state.get("debt_summary", "")
    characters = state.get("characters", [])
    outline_data = state.get("outline")

    # Build arc_status from debt_summary or outline
    arc_status = ""
    if debt_summary and "故事弧线推进指引" in debt_summary:
        # The arc prompt is already embedded in debt_summary
        arc_status = debt_summary
    elif outline_data and isinstance(outline_data, dict):
        arcs = outline_data.get("story_arcs", [])
        if arcs:
            arc_lines = []
            for arc in arcs:
                phase = arc.get("phase", "setup")
                name = arc.get("name", "?")
                arc_lines.append(f"- {name}: {phase}")
            arc_status = "\n".join(arc_lines)

    # Enrich upcoming outlines from full outline
    upcoming_text = _build_upcoming_outlines(
        outline_data, chapter_number, window=5
    )

    # --- Create LLM client ---
    llm_config = get_stage_llm_config(state, "outline_generation")
    try:
        llm = create_llm_client(llm_config)
    except Exception as exc:
        log.error("DynamicOutline: LLM 初始化失败: %s", exc)
        return {
            "errors": [
                {
                    "agent": "DynamicOutlinePlanner",
                    "message": f"LLM 初始化失败: {exc}",
                }
            ],
            "completed_nodes": ["dynamic_outline"],
        }

    planner = DynamicOutlinePlanner(llm)

    try:
        result = planner.revise_outline(
            chapter_number=chapter_number,
            original_outline=original_outline,
            previous_summaries=previous_summaries,
            continuity_brief=continuity_brief,
            debt_summary=debt_summary,
            character_states=characters,
            arc_status=arc_status,
            upcoming_outlines=upcoming_text,
        )
    except Exception as exc:
        log.error(
            "DynamicOutline: 第%d章大纲修订失败，保留原始: %s",
            chapter_number,
            exc,
        )
        decisions.append(
            _make_decision(
                step="revise_outline",
                decision="大纲修订失败，保留原始",
                reason=str(exc),
            )
        )
        return {
            "decisions": decisions,
            "completed_nodes": ["dynamic_outline"],
        }

    revision_needed = result["revision_needed"]
    revision_reason = result["revision_reason"]
    revised_outline = result["revised_outline"]

    if revision_needed:
        decisions.append(
            _make_decision(
                step="revise_outline",
                decision=f"第{chapter_number}章大纲已修订",
                reason=revision_reason,
                data={"original_title": original_outline.get("title"),
                      "revised_title": revised_outline.get("title")},
            )
        )
        log.info(
            "DynamicOutline: 第%d章大纲已修订 — %s",
            chapter_number,
            revision_reason,
        )
        return {
            "current_chapter_outline": revised_outline,
            "decisions": decisions,
            "completed_nodes": ["dynamic_outline"],
        }

    decisions.append(
        _make_decision(
            step="revise_outline",
            decision=f"第{chapter_number}章大纲无需修订",
            reason=revision_reason or "原始大纲与前文一致",
        )
    )
    log.info("DynamicOutline: 第%d章大纲无需修订", chapter_number)
    return {
        "decisions": decisions,
        "completed_nodes": ["dynamic_outline"],
    }
