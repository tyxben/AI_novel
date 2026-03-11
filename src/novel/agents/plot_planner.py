"""PlotPlanner Agent - 情节规划师

将章大纲分解为场景计划，设计节奏曲线，管理伏笔织入。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.llm.llm_client import LLMClient, LLMResponse, create_llm_client
from src.novel.models.chapter import MoodTag
from src.novel.models.character import CharacterProfile
from src.novel.models.novel import ChapterOutline, VolumeOutline
from src.novel.templates.rhythm_templates import get_rhythm
from src.novel.utils import extract_json_from_llm

log = logging.getLogger("novel")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_MOOD_VALUES: dict[str, str] = {tag.value: tag.value for tag in MoodTag}

_CHAPTER_TYPE_MAP: dict[str, str] = {
    MoodTag.BUILDUP.value: "铺垫",
    MoodTag.SMALL_WIN.value: "发展",
    MoodTag.BIG_WIN.value: "高潮",
    MoodTag.TRANSITION.value: "过渡",
    MoodTag.HEARTBREAK.value: "发展",
    MoodTag.TWIST.value: "高潮",
    MoodTag.DAILY.value: "过渡",
}

_TENSION_MAP: dict[str, float] = {
    MoodTag.BUILDUP.value: 0.4,
    MoodTag.SMALL_WIN.value: 0.6,
    MoodTag.BIG_WIN.value: 0.9,
    MoodTag.TRANSITION.value: 0.3,
    MoodTag.HEARTBREAK.value: 0.7,
    MoodTag.TWIST.value: 0.8,
    MoodTag.DAILY.value: 0.2,
}

_SCENE_COUNT_MAP: dict[str, int] = {
    MoodTag.BUILDUP.value: 3,
    MoodTag.SMALL_WIN.value: 3,
    MoodTag.BIG_WIN.value: 4,
    MoodTag.TRANSITION.value: 2,
    MoodTag.HEARTBREAK.value: 3,
    MoodTag.TWIST.value: 3,
    MoodTag.DAILY.value: 2,
}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_DECOMPOSE_SYSTEM = """\
你是一位专业的网文情节规划师。你的任务是将章节大纲分解为具体的场景计划。

要求：
1. 每个场景必须有明确的目标和冲突
2. 场景之间要有张力变化（不能全程高潮或全程平淡）
3. 合理分配字数（关键场景字数更多）
4. 叙事焦点要多样（对话/动作/描写/心理交替使用）
5. 如果有伏笔提示，自然地织入场景中

返回严格的 JSON 格式（不要添加任何额外文字）：
{
  "scenes": [
    {
      "scene_number": 1,
      "title": "场景标题",
      "summary": "场景概要",
      "characters_involved": ["角色名"],
      "mood": "蓄力|小爽|大爽|过渡|虐心|反转|日常",
      "tension_level": 0.5,
      "target_words": 800,
      "narrative_focus": "对话|动作|描写|心理",
      "foreshadowing_to_plant": ["要埋设的伏笔描述"] 或 null,
      "foreshadowing_to_collect": ["要回收的伏笔描述"] 或 null
    }
  ]
}"""

_DECOMPOSE_USER = """\
## 章节大纲
- 章节号: {chapter_number}
- 标题: {title}
- 目标: {goal}
- 关键事件: {key_events}
- 涉及角色: {involved_characters}
- 情绪基调: {mood}
- 预估字数: {estimated_words}

## 卷上下文
{volume_context}

## 角色信息
{characters_info}

## 伏笔提示
{foreshadowing_info}

请将此章节分解为 {target_scenes} 个场景，总字数目标约 {estimated_words} 字。"""

_CLIFFHANGER_SYSTEM = """\
你是一位擅长制造悬念的网文作者。你的任务是为章节设计一个悬念结尾（钩子），
让读者迫不及待想看下一章。

要求：
1. 悬念要自然，不能生硬
2. 要与下一章内容衔接
3. 简洁有力，一两句话即可

返回 JSON 格式：
{
  "cliffhanger": "悬念描述文字",
  "type": "悬疑|危机|反转|情感|发现"
}

如果当前章节不适合设置悬念（如卷末收束章），返回：
{"cliffhanger": null, "type": null}"""

_CLIFFHANGER_USER = """\
## 当前章节
- 章节号: {chapter_number}
- 标题: {title}
- 目标: {goal}
- 关键事件: {key_events}

## 下一章概要
{next_chapter_info}

请为当前章节设计悬念结尾。"""


# ---------------------------------------------------------------------------
# PlotPlanner Agent
# ---------------------------------------------------------------------------


class PlotPlanner:
    """情节规划师 Agent - 场景分解和节奏设计"""

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    # ------------------------------------------------------------------
    # decompose_chapter
    # ------------------------------------------------------------------

    def decompose_chapter(
        self,
        chapter_outline: ChapterOutline,
        volume_context: dict,
        characters: list[CharacterProfile],
        foreshadowing_hints: list[dict] | None = None,
    ) -> list[dict]:
        """将章大纲分解为场景计划列表。"""
        target_scenes = _SCENE_COUNT_MAP.get(chapter_outline.mood, 3)

        char_lines = []
        for c in characters:
            char_lines.append(
                f"- {c.name}（{c.occupation}）: {c.personality.core_belief}"
            )
        characters_info = "\n".join(char_lines) if char_lines else "无特定角色信息"

        if foreshadowing_hints:
            foreshadowing_info = "\n".join(
                f"- {h.get('content', '未知')}"
                f"（状态: {h.get('status', 'pending')}）"
                for h in foreshadowing_hints
            )
        else:
            foreshadowing_info = "无伏笔提示"

        vol_lines = []
        if volume_context.get("volume_theme"):
            vol_lines.append(f"卷主题: {volume_context['volume_theme']}")
        if volume_context.get("previous_chapters_summary"):
            vol_lines.append(
                f"前情提要: {volume_context['previous_chapters_summary']}"
            )
        volume_ctx_str = "\n".join(vol_lines) if vol_lines else "无卷上下文"

        user_msg = _DECOMPOSE_USER.format(
            chapter_number=chapter_outline.chapter_number,
            title=chapter_outline.title,
            goal=chapter_outline.goal,
            key_events="、".join(chapter_outline.key_events),
            involved_characters="、".join(
                chapter_outline.involved_characters
            )
            if chapter_outline.involved_characters
            else "未指定",
            mood=chapter_outline.mood,
            estimated_words=chapter_outline.estimated_words,
            volume_context=volume_ctx_str,
            characters_info=characters_info,
            foreshadowing_info=foreshadowing_info,
            target_scenes=target_scenes,
        )

        messages = [
            {"role": "system", "content": _DECOMPOSE_SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        response: LLMResponse = self.llm.chat(
            messages, temperature=0.7, json_mode=True
        )

        parsed = extract_json_from_llm(response.content)
        scenes_raw = parsed.get("scenes", [])

        if not isinstance(scenes_raw, list) or len(scenes_raw) == 0:
            raise ValueError(
                f"LLM 返回的场景列表为空或格式错误: {response.content[:200]}"
            )

        scenes = self._validate_scenes(
            scenes_raw, chapter_outline.estimated_words
        )
        return scenes

    # ------------------------------------------------------------------
    # design_rhythm
    # ------------------------------------------------------------------

    def design_rhythm(
        self,
        volume_outline: VolumeOutline,
        genre: str,
    ) -> list[dict]:
        """为一卷所有章节设计张力节奏（纯规则，不调用 LLM）。"""
        chapter_count = len(volume_outline.chapters)
        rhythm = get_rhythm(genre, chapter_count)

        result: list[dict] = []
        for i, chapter_num in enumerate(volume_outline.chapters):
            mood = rhythm[i]
            result.append(
                {
                    "chapter_number": chapter_num,
                    "overall_tension": _TENSION_MAP.get(mood.value, 0.5),
                    "chapter_type": _CHAPTER_TYPE_MAP.get(mood.value, "过渡"),
                    "recommended_scenes": _SCENE_COUNT_MAP.get(
                        mood.value, 3
                    ),
                }
            )

        return result

    # ------------------------------------------------------------------
    # suggest_cliffhanger
    # ------------------------------------------------------------------

    def suggest_cliffhanger(
        self,
        chapter_outline: ChapterOutline,
        next_chapter_outline: ChapterOutline | None,
    ) -> str | None:
        """建议章末悬念钩子。"""
        if next_chapter_outline is None:
            next_info = "这是本卷最后一章，没有下一章。"
        else:
            next_info = (
                f"- 章节号: {next_chapter_outline.chapter_number}\n"
                f"- 标题: {next_chapter_outline.title}\n"
                f"- 目标: {next_chapter_outline.goal}\n"
                f"- 关键事件: {'、'.join(next_chapter_outline.key_events)}"
            )

        user_msg = _CLIFFHANGER_USER.format(
            chapter_number=chapter_outline.chapter_number,
            title=chapter_outline.title,
            goal=chapter_outline.goal,
            key_events="、".join(chapter_outline.key_events),
            next_chapter_info=next_info,
        )

        messages = [
            {"role": "system", "content": _CLIFFHANGER_SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        response: LLMResponse = self.llm.chat(
            messages, temperature=0.8, json_mode=True
        )

        parsed = extract_json_from_llm(response.content)
        cliffhanger = parsed.get("cliffhanger")
        return cliffhanger if cliffhanger else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_scenes(
        scenes_raw: list[dict], total_words: int
    ) -> list[dict]:
        """校验并规范化场景数据。"""
        valid_moods = {tag.value for tag in MoodTag}
        valid_focuses = {"对话", "动作", "描写", "心理"}
        scenes: list[dict] = []

        for i, s in enumerate(scenes_raw):
            scene: dict[str, Any] = {
                "scene_number": s.get("scene_number", i + 1),
                "title": s.get("title", f"场景{i + 1}"),
                "summary": s.get("summary", ""),
                "characters_involved": s.get("characters_involved", []),
                "mood": (
                    s.get("mood", "蓄力")
                    if s.get("mood") in valid_moods
                    else "蓄力"
                ),
                "tension_level": max(
                    0.0, min(1.0, float(s.get("tension_level", 0.5)))
                ),
                "target_words": max(
                    200, int(s.get("target_words", total_words // len(scenes_raw)))
                ),
                "narrative_focus": (
                    s.get("narrative_focus", "描写")
                    if s.get("narrative_focus") in valid_focuses
                    else "描写"
                ),
                "foreshadowing_to_plant": s.get("foreshadowing_to_plant"),
                "foreshadowing_to_collect": s.get("foreshadowing_to_collect"),
            }
            scenes.append(scene)

        return scenes


# ---------------------------------------------------------------------------
# LangGraph Node
# ---------------------------------------------------------------------------


def plot_planner_node(state: dict) -> dict:
    """LangGraph 节点函数。

    从 state 中读取当前章节信息，生成场景分解。
    """
    decisions: list[dict] = []
    errors: list[dict] = []

    # 创建 LLM 客户端
    llm_config = state.get("config", {}).get("llm", {})
    try:
        llm = create_llm_client(llm_config)
    except Exception as exc:
        return {
            "errors": [{"agent": "PlotPlanner", "message": f"LLM 初始化失败: {exc}"}],
            "completed_nodes": ["plot_planner"],
        }

    planner = PlotPlanner(llm)

    # 从 state 恢复 ChapterOutline
    ch_outline_data = state.get("current_chapter_outline")
    if not ch_outline_data:
        return {
            "errors": [{"agent": "PlotPlanner", "message": "当前章节大纲不存在"}],
            "completed_nodes": ["plot_planner"],
        }

    try:
        chapter_outline = ChapterOutline(**ch_outline_data) if isinstance(ch_outline_data, dict) else ch_outline_data
    except Exception as exc:
        return {
            "errors": [{"agent": "PlotPlanner", "message": f"章节大纲解析失败: {exc}"}],
            "completed_nodes": ["plot_planner"],
        }

    # 恢复角色
    characters: list[CharacterProfile] = []
    for c_data in state.get("characters", []):
        try:
            characters.append(CharacterProfile(**c_data) if isinstance(c_data, dict) else c_data)
        except Exception:
            pass

    try:
        scene_plans = planner.decompose_chapter(
            chapter_outline=chapter_outline,
            volume_context={},
            characters=characters,
            foreshadowing_hints=None,
        )

        decisions.append({
            "agent": "PlotPlanner",
            "step": "decompose_chapter",
            "decision": f"将第{chapter_outline.chapter_number}章分解为{len(scene_plans)}个场景",
            "reason": f"章节情绪基调: {chapter_outline.mood}，预估字数: {chapter_outline.estimated_words}",
            "data": {"scene_count": len(scene_plans)},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return {
            "current_scenes": scene_plans,
            "decisions": decisions,
            "errors": errors,
            "completed_nodes": ["plot_planner"],
        }

    except Exception as exc:
        log.error("PlotPlanner 场景分解失败: %s", exc)
        return {
            "current_scenes": [],
            "decisions": [{
                "agent": "PlotPlanner",
                "step": "decompose_chapter",
                "decision": "场景分解失败",
                "reason": str(exc),
                "data": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }],
            "errors": [{"agent": "PlotPlanner", "message": f"场景分解失败: {exc}"}],
            "completed_nodes": ["plot_planner"],
        }
