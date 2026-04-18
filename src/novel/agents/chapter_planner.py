"""ChapterPlanner — Phase 2-δ consolidated chapter brain.

Consolidates three previously-separate Agents / services into one:

* ``DynamicOutlinePlanner`` — pre-write outline revision based on what
  actually happened in earlier chapters.  (removed file)
* ``PlotPlanner`` — decomposes a chapter outline into concrete scenes.
  (removed file)
* ``HookGenerator`` — suggests / strengthens chapter-end suspense.
  (removed file)

Why merge? The three stages all need the same Ledger snapshot (debts,
foreshadowings, active characters).  Running them as separate LangGraph
nodes meant assembling that context three times; more importantly it
split the "what this chapter should accomplish" decision across nodes.

The new flow is::

    chapter_planner  (brief + scenes + hook)  →  writer  →  reviewer  →  state_writeback

``ChapterPlanner`` pulls the Ledger snapshot through
:class:`BriefAssembler` and writes the resulting ``ChapterBrief`` back
onto ``current_chapter_outline.chapter_brief`` so the Writer prompt
keeps working unchanged.

Backwards compatibility:
    * ``state["current_scenes"]`` — still a ``list[dict]`` (scene plans)
    * ``state["current_chapter_outline"]`` — dict, possibly revised
    * ``state["current_chapter_outline"]["chapter_brief"]`` — legacy dict
      filled from ``ChapterBrief.to_legacy_chapter_brief()`` + the LLM-
      derived scene hints, so the Writer's existing prompt section works.

See ``specs/architecture-rework-2026/DESIGN.md`` Part 2 A3 / Part 3 B2.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.llm.llm_client import LLMClient, LLMResponse, create_llm_client
from src.novel.llm_utils import get_stage_llm_config
from src.novel.models.chapter import MoodTag
from src.novel.models.chapter_brief import (
    ChapterBrief,
    ChapterBriefProposal,
    SceneSummary,
)
from src.novel.models.character import CharacterProfile
from src.novel.models.novel import ChapterOutline
from src.novel.utils import extract_json_from_llm

if TYPE_CHECKING:  # pragma: no cover
    from src.novel.services.brief_assembler import BriefAssembler
    from src.novel.services.ledger_store import LedgerStore

log = logging.getLogger("novel.chapter_planner")

# ---------------------------------------------------------------------------
# Constants (copied from legacy plot_planner; kept minimal)
# ---------------------------------------------------------------------------

_MOOD_VALUES: dict[str, str] = {tag.value: tag.value for tag in MoodTag}

# chapter_type → target_words multiplier (DESIGN.md Part 6).  Base word
# target comes from the ChapterOutline; missing outlines fall back to
# the default 2500.
_CHAPTER_TYPE_MULTIPLIER: dict[str, float] = {
    "setup": 0.8,
    "buildup": 1.0,
    "climax": 1.5,
    "resolution": 1.2,
    "interlude": 0.6,
}

# Mood → default chapter_type mapping (keeps old MoodTag chapters working).
_MOOD_TO_CHAPTER_TYPE: dict[str, str] = {
    MoodTag.BUILDUP.value: "buildup",
    MoodTag.SMALL_WIN.value: "buildup",
    MoodTag.BIG_WIN.value: "climax",
    MoodTag.TRANSITION.value: "interlude",
    MoodTag.HEARTBREAK.value: "buildup",
    MoodTag.TWIST.value: "climax",
    MoodTag.DAILY.value: "interlude",
}

_DEFAULT_SCENE_COUNT = 3

# Strong hook indicators carried over from the old HookGenerator
_STRONG_HOOK_PATTERNS = [
    re.compile(r"[？?！!]\s*$"),
    re.compile(r"(突然|忽然|猛然|骤然)[^。]*[。！？]\s*$"),
    re.compile(r"(?:就在这时|与此同时|可就在|然而)[^。]*[。！？]\s*$"),
    re.compile(r"[^。]{0,30}(?:不见了|消失了|没了|断了)[。！？]\s*$"),
    re.compile(r"[\u2026\u22ef]{2,}\s*$"),
]

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
你是一位网文章节规划师，在写章之前为作者做三件事：
1. 对比原始章纲 + 前文摘要，必要时微调本章目标（revision）
2. 把本章拆成 2-5 个具体场景（scenes）
3. 给本章一个 1-2 句的章尾悬念钩子（end_hook）

返回严格 JSON（不要加额外文字）：
{
  "revised_goal": "本章修正后的目标（如无需修正则抄原目标）",
  "revision_reason": "修正原因；无修正写 'no_revision'",
  "scenes": [
    {
      "scene_number": 1,
      "title": "场景标题",
      "summary": "场景概要",
      "characters_involved": ["角色A"],
      "mood": "蓄力|小爽|大爽|过渡|虐心|反转|日常",
      "tension_level": 0.5,
      "target_words": 800,
      "narrative_focus": "对话|动作|描写|心理"
    }
  ],
  "tone_notes": "本章整体语感/节奏提示",
  "end_hook": "章尾悬念钩子文字",
  "end_hook_type": "悬疑|危机|反转|情感|发现"
}

规划原则：
- 场景必须推进主线，不允许纯水字数的场景
- 第一个场景必须衔接上章结尾（时间/空间/未完成动作）
- 如果账本给出"应兑现债务"或"应回收伏笔"，在某个场景中安排
- 如果账本给出角色状态（已死亡/离场/受伤），禁止违反
- 章尾钩子要自然，不要生硬嫁接
"""

_USER_TEMPLATE = """\
## 原始章纲（第 {chapter_number} 章）
- 标题：{title}
- 目标：{goal}
- 关键事件：{key_events}
- 情绪基调：{mood}
- 涉及角色：{involved_characters}
- 目标字数：{target_words}

## 前文摘要（最近章节）
{previous_summaries}

## 账本快照（来自 Ledger，必须遵守）
{ledger_block}

## 连续性约束
{continuity_brief}

## 后续章纲（保持兼容）
{upcoming_outlines}

请给出本章的完整规划 JSON。"""


# ---------------------------------------------------------------------------
# ChapterPlanner
# ---------------------------------------------------------------------------


class ChapterPlanner:
    """Chapter-level brain: brief + scene decomposition + end-hook.

    Pulls Ledger context via :class:`BriefAssembler` on every call so the
    resulting ``ChapterBrief`` reflects current narrative state rather
    than the stale outline snapshot.

    Args:
        llm_client: sync LLM client.
        ledger: optional ``LedgerStore``.  Absent → Ledger-derived
            sections stay empty (planner still produces a brief).
        brief_assembler: optional pre-built ``BriefAssembler``.  When
            ``None`` and ``ledger`` is given, one will be lazily created.
        config: reserved for future knobs.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        ledger: "LedgerStore | None" = None,
        brief_assembler: "BriefAssembler | None" = None,
        config: dict | None = None,
    ) -> None:
        self.llm = llm_client
        self.ledger = ledger
        self._brief_assembler = brief_assembler
        self.config = config or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def propose_chapter_brief(
        self,
        novel: Any,
        volume_number: int,
        chapter_number: int,
        chapter_outline: ChapterOutline | dict | None = None,
        previous_tail: str | None = None,
        previous_summaries: str = "",
        continuity_brief: str = "",
        upcoming_outlines: str = "",
    ) -> ChapterBriefProposal:
        """Produce a ``ChapterBriefProposal`` for *chapter_number*.

        Ledger snapshot is fetched via the assembler (or built
        lazily).  Returns a proposal that is **not** persisted —
        callers are expected to ``accept`` it via the pipeline /
        tool layer.
        """
        # Normalize outline input
        co = self._normalize_outline(chapter_outline, chapter_number)

        # Pull Ledger context
        ledger_ctx = self._ledger_context(novel, volume_number, chapter_number)

        # Call LLM
        scenes_raw, revised_goal, tone_notes, end_hook, end_hook_type = (
            self._call_llm(
                chapter_outline=co,
                chapter_number=chapter_number,
                previous_summaries=previous_summaries,
                continuity_brief=continuity_brief,
                ledger_ctx=ledger_ctx,
                upcoming_outlines=upcoming_outlines,
            )
        )

        # Validate / normalize scenes
        target_words = self._resolve_target_words(co)
        scenes = self._validate_scenes(scenes_raw, target_words)

        # Build structured ChapterBrief
        brief = ChapterBrief(
            chapter_number=chapter_number,
            goal=revised_goal or (co.goal if co else ""),
            scenes=[
                SceneSummary(
                    summary=s.get("summary", ""),
                    characters=s.get("characters_involved", []) or [],
                    title=s.get("title"),
                    target_words=s.get("target_words"),
                    mood=s.get("mood"),
                    tension_level=s.get("tension_level"),
                    narrative_focus=s.get("narrative_focus"),
                )
                for s in scenes
            ],
            must_collect_foreshadowings=list(
                ledger_ctx.get("must_collect_foreshadowings", [])
            ),
            must_fulfill_debts=list(
                ledger_ctx.get("must_fulfill_debts", [])
            ),
            active_characters=list(ledger_ctx.get("active_characters", [])),
            world_facts_to_respect=list(
                ledger_ctx.get("world_facts_to_respect", [])
            ),
            target_words=target_words,
            chapter_type=self._resolve_chapter_type(co),
            tone_notes=tone_notes or "",
            end_hook=end_hook or "",
            end_hook_type=end_hook_type or "",
        )

        return ChapterBriefProposal(
            brief=brief,
            source="chapter_planner",
            warnings=list(ledger_ctx.get("warnings", [])),
            scene_plans=scenes,
        )

    def update_chapter_brief(
        self,
        brief: dict | ChapterBrief,
        edits: dict,
    ) -> ChapterBriefProposal:
        """Merge *edits* into *brief* and return an updated proposal.

        Used for manual author edits.  ``brief`` may be a dict (legacy
        serialization) or a ``ChapterBrief``; *edits* is a shallow
        override dict.
        """
        if isinstance(brief, ChapterBrief):
            data = brief.model_dump()
        elif isinstance(brief, dict):
            data = dict(brief)
        else:
            raise TypeError(f"Unsupported brief type: {type(brief).__name__}")

        # Apply edits, preserving nested scenes when not explicitly edited
        for key, value in (edits or {}).items():
            data[key] = value

        # Coerce scenes if passed as list[dict]
        scenes_in = data.get("scenes") or []
        scenes: list[SceneSummary] = []
        for s in scenes_in:
            if isinstance(s, SceneSummary):
                scenes.append(s)
            elif isinstance(s, dict):
                try:
                    scenes.append(SceneSummary(**s))
                except Exception:
                    # Skip malformed scene edits rather than failing hard
                    log.debug("malformed scene edit skipped: %r", s)
        data["scenes"] = scenes

        updated = ChapterBrief(**data)
        scene_plans = [self._scene_summary_to_plan_dict(s, i) for i, s in enumerate(scenes)]
        return ChapterBriefProposal(
            brief=updated,
            source="manual_edit",
            warnings=[],
            scene_plans=scene_plans,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ledger_context(
        self,
        novel: Any,
        volume_number: int,
        chapter_number: int,
    ) -> dict[str, Any]:
        assembler = self._brief_assembler
        if assembler is None and self.ledger is not None:
            from src.novel.services.brief_assembler import BriefAssembler

            # Build an assembler that only consumes the ledger. Legacy
            # rule-based fields (dead-chars / hooks) come from the
            # pipeline's own ContinuityService call earlier in the flow.
            assembler = BriefAssembler(ledger=self.ledger)
            self._brief_assembler = assembler

        if assembler is None:
            # Still give callers a sensible ``active_characters`` default
            # by falling back to the novel roster — mirrors
            # ``BriefAssembler._default_active_characters``.
            from src.novel.services.brief_assembler import BriefAssembler as _BA
            return {
                "must_collect_foreshadowings": [],
                "must_fulfill_debts": [],
                "active_characters": _BA._default_active_characters(novel),
                "world_facts_to_respect": [],
                "pending_milestones": [],
                "warnings": ["no_ledger_or_assembler"],
            }

        return assembler.assemble_for_chapter(
            novel=novel,
            volume_number=volume_number,
            chapter_number=chapter_number,
        )

    def _call_llm(
        self,
        chapter_outline: ChapterOutline | None,
        chapter_number: int,
        previous_summaries: str,
        continuity_brief: str,
        ledger_ctx: dict[str, Any],
        upcoming_outlines: str,
    ) -> tuple[list[dict], str, str, str, str]:
        """Invoke the LLM; return (scenes, revised_goal, tone_notes, end_hook, hook_type)."""
        ledger_block = self._format_ledger_block(ledger_ctx)

        if chapter_outline is not None:
            title = chapter_outline.title
            goal = chapter_outline.goal
            key_events = "、".join(chapter_outline.key_events or []) or "未指定"
            mood = chapter_outline.mood or "蓄力"
            involved = (
                "、".join(chapter_outline.involved_characters or [])
                or "未指定"
            )
            target_words = chapter_outline.estimated_words
        else:
            title = f"第{chapter_number}章"
            goal = ""
            key_events = "未指定"
            mood = "蓄力"
            involved = "未指定"
            target_words = 2500

        user_msg = _USER_TEMPLATE.format(
            chapter_number=chapter_number,
            title=title,
            goal=goal,
            key_events=key_events,
            mood=mood,
            involved_characters=involved,
            target_words=target_words,
            previous_summaries=previous_summaries or "（无前文）",
            ledger_block=ledger_block,
            continuity_brief=continuity_brief or "（无额外约束）",
            upcoming_outlines=upcoming_outlines or "（无后续章纲）",
        )

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        try:
            response: LLMResponse = self.llm.chat(
                messages, temperature=0.6, json_mode=True, max_tokens=3000
            )
        except Exception as exc:
            log.warning("ChapterPlanner LLM call failed: %s", exc)
            return self._fallback_output(chapter_outline, chapter_number)

        if not response or not response.content:
            log.warning("ChapterPlanner LLM returned empty response")
            return self._fallback_output(chapter_outline, chapter_number)

        try:
            parsed = extract_json_from_llm(response.content)
        except Exception as exc:
            log.warning("ChapterPlanner JSON parse failed: %s", exc)
            return self._fallback_output(chapter_outline, chapter_number)

        scenes_raw = parsed.get("scenes")
        if not isinstance(scenes_raw, list) or not scenes_raw:
            scenes_raw = self._default_scenes(chapter_outline, chapter_number)

        revised_goal = parsed.get("revised_goal", "") or (
            chapter_outline.goal if chapter_outline else ""
        )
        tone_notes = str(parsed.get("tone_notes") or "")
        end_hook = str(parsed.get("end_hook") or "")
        end_hook_type = str(parsed.get("end_hook_type") or "")

        return scenes_raw, revised_goal, tone_notes, end_hook, end_hook_type

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_ledger_block(ctx: dict[str, Any]) -> str:
        lines: list[str] = []
        if ctx.get("must_fulfill_debts"):
            lines.append("- 应兑现债务：")
            for d in ctx["must_fulfill_debts"][:5]:
                lines.append(f"  · {d}")
        if ctx.get("must_collect_foreshadowings"):
            lines.append("- 应回收伏笔：")
            for f in ctx["must_collect_foreshadowings"][:5]:
                lines.append(f"  · {f}")
        if ctx.get("active_characters"):
            lines.append(
                "- 活跃角色：" + "、".join(ctx["active_characters"][:10])
            )
        if ctx.get("pending_milestones"):
            lines.append("- 待推进里程碑：")
            for m in ctx["pending_milestones"][:3]:
                lines.append(f"  · {m}")
        if ctx.get("world_facts_to_respect"):
            lines.append(
                "- 世界观事实（不可违反）：" + "、".join(
                    ctx["world_facts_to_respect"][:10]
                )
            )
        return "\n".join(lines) if lines else "（账本为空）"

    @staticmethod
    def _normalize_outline(
        outline: ChapterOutline | dict | None,
        chapter_number: int,
    ) -> ChapterOutline | None:
        if outline is None:
            return None
        if isinstance(outline, ChapterOutline):
            return outline
        if isinstance(outline, dict):
            try:
                data = dict(outline)
                data.setdefault("chapter_number", chapter_number)
                return ChapterOutline(**data)
            except Exception as exc:
                log.debug("ChapterOutline coerce failed: %s", exc)
                return None
        return None

    def _resolve_target_words(self, outline: ChapterOutline | None) -> int:
        if outline is None:
            return 2500
        base = int(outline.estimated_words or 2500)
        return max(300, base)

    @staticmethod
    def _resolve_chapter_type(outline: ChapterOutline | None) -> str:
        if outline is None:
            return "buildup"
        mood = getattr(outline, "mood", "") or ""
        return _MOOD_TO_CHAPTER_TYPE.get(mood, "buildup")

    @staticmethod
    def _scene_summary_to_plan_dict(
        scene: SceneSummary, idx: int
    ) -> dict[str, Any]:
        return {
            "scene_number": idx + 1,
            "title": scene.title or f"场景{idx + 1}",
            "summary": scene.summary,
            "characters_involved": list(scene.characters or []),
            "mood": scene.mood or "蓄力",
            "tension_level": scene.tension_level
            if scene.tension_level is not None
            else 0.5,
            "target_words": scene.target_words or 800,
            "narrative_focus": scene.narrative_focus or "描写",
        }

    # ------------------------------------------------------------------
    # Scene validation + fallbacks
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_scenes(
        scenes_raw: list[dict], total_words: int
    ) -> list[dict]:
        valid_moods = {tag.value for tag in MoodTag}
        valid_focuses = {"对话", "动作", "描写", "心理"}
        out: list[dict] = []
        n = max(len(scenes_raw), 1)

        for i, s in enumerate(scenes_raw):
            if not isinstance(s, dict):
                continue
            mood = s.get("mood", "蓄力")
            if mood not in valid_moods:
                mood = "蓄力"
            focus = s.get("narrative_focus", "描写")
            if focus not in valid_focuses:
                focus = "描写"
            try:
                tension = float(s.get("tension_level", 0.5))
            except (TypeError, ValueError):
                tension = 0.5
            tension = max(0.0, min(1.0, tension))
            try:
                tw = int(s.get("target_words", max(200, total_words // n)))
            except (TypeError, ValueError):
                tw = max(200, total_words // n)
            tw = max(200, tw)

            out.append({
                "scene_number": s.get("scene_number", i + 1),
                "title": s.get("title", f"场景{i + 1}"),
                "summary": s.get("summary", ""),
                "characters_involved": list(s.get("characters_involved") or []),
                "mood": mood,
                "tension_level": tension,
                "target_words": tw,
                "narrative_focus": focus,
                "foreshadowing_to_plant": s.get("foreshadowing_to_plant"),
                "foreshadowing_to_collect": s.get("foreshadowing_to_collect"),
            })
        if not out:
            return [
                {
                    "scene_number": i + 1,
                    "title": f"场景{i + 1}",
                    "summary": "",
                    "characters_involved": [],
                    "mood": "蓄力",
                    "tension_level": 0.5,
                    "target_words": max(200, total_words // _DEFAULT_SCENE_COUNT),
                    "narrative_focus": "描写",
                }
                for i in range(_DEFAULT_SCENE_COUNT)
            ]
        return out

    @staticmethod
    def _default_scenes(
        outline: ChapterOutline | None,
        chapter_number: int,
    ) -> list[dict]:
        target = (outline.estimated_words if outline else 2500) or 2500
        per = max(200, target // _DEFAULT_SCENE_COUNT)
        goal = outline.goal if outline else ""
        return [
            {
                "scene_number": i + 1,
                "title": f"第{chapter_number}章·场景{i + 1}",
                "summary": goal or "推进剧情",
                "mood": "蓄力",
                "target_words": per,
            }
            for i in range(_DEFAULT_SCENE_COUNT)
        ]

    def _fallback_output(
        self,
        outline: ChapterOutline | None,
        chapter_number: int,
    ) -> tuple[list[dict], str, str, str, str]:
        return (
            self._default_scenes(outline, chapter_number),
            outline.goal if outline else "",
            "",
            "",
            "",
        )

    # ------------------------------------------------------------------
    # End-hook evaluation (absorbed from HookGenerator)
    # ------------------------------------------------------------------

    @staticmethod
    def evaluate_hook(chapter_text: str) -> dict[str, Any]:
        """Lightweight end-hook quality check kept for pipeline compatibility.

        Returns ``{"score": int, "hook_type": str, "needs_improvement": bool}``.
        No LLM call.  The old ``HookGenerator.generate_hook`` LLM rewrite
        path is intentionally not replicated here — ChapterPlanner writes
        the hook *before* the chapter, so post-hoc rewrites are redundant.
        """
        if not chapter_text:
            return {"score": 0, "hook_type": "none", "needs_improvement": True}
        tail = chapter_text.strip()[-300:]
        last = tail.split("\n")[-1] if "\n" in tail else tail
        score = 5
        hook_type = "neutral"
        for pat in _STRONG_HOOK_PATTERNS:
            if pat.search(last):
                score += 2
                hook_type = "strong"
                break
        return {
            "score": max(0, min(10, score)),
            "hook_type": hook_type,
            "needs_improvement": score < 6,
        }


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------


def chapter_planner_node(state: dict) -> dict:
    """LangGraph node: plan the current chapter end-to-end.

    Reads from state:
        current_chapter, current_chapter_outline, previous summaries
        (via chapters), ledger_store, continuity_brief, outline, novel
        identity fields.

    Writes to state:
        current_chapter_outline (possibly revised), current_scenes,
        current_chapter_brief.
    """
    decisions: list[dict] = []
    errors: list[dict] = []

    chapter_number = state.get("current_chapter", 1)
    ch_outline_data = state.get("current_chapter_outline")
    if not ch_outline_data:
        return {
            "errors": [
                {"agent": "ChapterPlanner", "message": "当前章节大纲不存在"}
            ],
            "completed_nodes": ["chapter_planner"],
        }

    # --- LLM client ---
    llm_config = get_stage_llm_config(state, "outline_generation")
    try:
        llm = create_llm_client(llm_config)
    except Exception as exc:
        return {
            "errors": [
                {"agent": "ChapterPlanner", "message": f"LLM 初始化失败: {exc}"}
            ],
            "completed_nodes": ["chapter_planner"],
        }

    ledger = state.get("ledger_store")
    planner = ChapterPlanner(llm, ledger=ledger)

    # Coerce outline for prompt assembly
    try:
        chapter_outline = (
            ChapterOutline(**ch_outline_data)
            if isinstance(ch_outline_data, dict)
            else ch_outline_data
        )
    except Exception as exc:
        return {
            "errors": [
                {
                    "agent": "ChapterPlanner",
                    "message": f"章节大纲解析失败: {exc}",
                }
            ],
            "completed_nodes": ["chapter_planner"],
        }

    # Build previous_summaries / upcoming from state
    chapters = state.get("chapters") or []
    recent = chapters[-2:]
    prev_summaries_lines: list[str] = []
    for ch in recent:
        ch_n = ch.get("chapter_number", "?")
        title = ch.get("title", "?")
        summary = ch.get("chapter_summary") or ch.get("actual_summary") or ""
        if not summary:
            text = ch.get("full_text", "")
            summary = text[:300] + ("..." if len(text) > 300 else "")
        prev_summaries_lines.append(f"第{ch_n}章「{title}」: {summary}")
    previous_summaries = (
        "\n".join(prev_summaries_lines) if prev_summaries_lines else ""
    )

    upcoming_lines: list[str] = []
    outline_data = state.get("outline")
    if outline_data and isinstance(outline_data, dict):
        for ch in outline_data.get("chapters", []):
            n = ch.get("chapter_number", 0)
            if chapter_number < n <= chapter_number + 5:
                upcoming_lines.append(
                    f"- 第{n}章「{ch.get('title', '?')}」: "
                    f"{ch.get('goal', '?')}"
                )
    upcoming_outlines = "\n".join(upcoming_lines)

    continuity_brief = state.get("continuity_brief", "")
    volume_number = state.get("current_volume") or 1

    # Build pseudo-novel dict for default-active-character fallback
    novel_stub = {"characters": state.get("characters") or []}

    try:
        proposal = planner.propose_chapter_brief(
            novel=novel_stub,
            volume_number=volume_number,
            chapter_number=chapter_number,
            chapter_outline=chapter_outline,
            previous_summaries=previous_summaries,
            continuity_brief=continuity_brief,
            upcoming_outlines=upcoming_outlines,
        )
    except Exception as exc:
        log.error("ChapterPlanner 规划失败: %s", exc)
        errors.append(
            {"agent": "ChapterPlanner", "message": f"规划失败: {exc}"}
        )
        return {
            "current_scenes": [],
            "decisions": decisions,
            "errors": errors,
            "completed_nodes": ["chapter_planner"],
        }

    brief = proposal.brief
    scene_plans = proposal.scene_plans

    # Merge brief back into current_chapter_outline so Writer keeps working
    revised_outline: dict = (
        dict(ch_outline_data)
        if isinstance(ch_outline_data, dict)
        else chapter_outline.model_dump()
    )
    if brief.goal and brief.goal != revised_outline.get("goal"):
        revised_outline["goal"] = brief.goal

    # Preserve the original chapter_brief dict if present, layering ours on top
    legacy = dict(revised_outline.get("chapter_brief") or {})
    legacy.update(brief.to_legacy_chapter_brief())
    revised_outline["chapter_brief"] = legacy

    decisions.append({
        "agent": "ChapterPlanner",
        "step": "propose_chapter_brief",
        "decision": f"规划第{chapter_number}章：{len(scene_plans)} 场景，目标 {brief.target_words} 字",
        "reason": (
            "revised" if proposal.warnings else "ledger_snapshot"
        )
        + (f"; warnings={','.join(proposal.warnings)}" if proposal.warnings else ""),
        "data": {
            "scene_count": len(scene_plans),
            "target_words": brief.target_words,
            "chapter_type": brief.chapter_type,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "current_chapter_outline": revised_outline,
        "current_scenes": scene_plans,
        "current_chapter_brief": brief.model_dump(),
        "decisions": decisions,
        "errors": errors,
        "completed_nodes": ["chapter_planner"],
    }
