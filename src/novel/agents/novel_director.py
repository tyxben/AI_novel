"""NovelDirector - 总导演 Agent

负责：
1. 分析用户输入（题材、主题、字数）
2. 生成三层大纲（总大纲 -> 卷大纲 -> 章大纲）
3. 规划 Agent 工作流
4. 作为 LangGraph 节点协调整个创作流程
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any

from src.llm.llm_client import create_llm_client
from src.novel.agents.state import Decision, NovelState
from src.novel.llm_utils import get_stage_llm_config
from src.novel.models.novel import (
    Act,
    ChapterOutline,
    Outline,
    VolumeOutline,
)
from src.novel.models.story_unit import StoryUnit
from src.novel.templates.outline_templates import get_template

log = logging.getLogger("novel")

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

_GENRE_TEMPLATE_MAP: dict[str, str] = {
    "玄幻": "cyclic_upgrade",
    "修仙": "cyclic_upgrade",
    "都市": "cyclic_upgrade",
    "系统流": "cyclic_upgrade",
    "宫斗": "multi_thread",
    "群像": "multi_thread",
    "悬疑": "multi_thread",
    "权谋": "multi_thread",
    "武侠": "four_act",
    "仙侠": "four_act",
    "言情": "four_act",
    "科幻": "scifi_crisis",
}

_GENRE_STYLE_MAP: dict[str, str] = {
    "玄幻": "webnovel.xuanhuan",
    "修仙": "wuxia.classical",
    "都市": "webnovel.shuangwen",
    "系统流": "webnovel.shuangwen",
    "武侠": "wuxia.classical",
    "仙侠": "wuxia.modern",
    "宫斗": "webnovel.shuangwen",
    "群像": "literary.realism",
    "悬疑": "literary.realism",
    "言情": "webnovel.romance",
    "科幻": "scifi.hardscifi",
    "轻小说": "light_novel.campus",
}

_WORDS_PER_CHAPTER = 2500  # 每章约 2000-3000 字（default 兜底，见 _resolve_target_words）
_CHAPTERS_PER_VOLUME = 30  # 每卷约 30 章


def _resolve_target_words(chapter: Any | None = None) -> int:
    """解析章节目标字数。

    Phase 0 架构重构：去掉硬编码阈值。优先读 chapter 模型上的
    ``target_words`` / ``estimated_words`` 字段；缺失时退回
    ``_WORDS_PER_CHAPTER`` 兜底。

    Args:
        chapter: ``Chapter`` / ``ChapterOutline`` / dict 三种形态。None 则直接用默认。

    Returns:
        int 目标字数。永远 > 0。
    """
    if chapter is None:
        return _WORDS_PER_CHAPTER
    # 支持 dict
    if isinstance(chapter, dict):
        val = chapter.get("target_words") or chapter.get("estimated_words")
    else:
        val = getattr(chapter, "target_words", None) or getattr(
            chapter, "estimated_words", None
        )
    try:
        ival = int(val) if val is not None else 0
    except (TypeError, ValueError):
        ival = 0
    return ival if ival > 0 else _WORDS_PER_CHAPTER

# Outline.template Literal 值 → outline_templates.py 中的模板名称
_TEMPLATE_ALIAS: dict[str, str] = {
    "four_act": "classic_four_act",
    "custom": "cyclic_upgrade",  # custom 没有对应模板，用 cyclic_upgrade 兜底
}


def _make_decision(
    step: str,
    decision: str,
    reason: str,
    data: dict[str, Any] | None = None,
) -> Decision:
    """创建 NovelDirector 的决策记录。"""
    return Decision(
        agent="NovelDirector",
        step=step,
        decision=decision,
        reason=reason,
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# Prompt-leak / meta-text keywords that must NOT appear in a derived title.
# Matches the (private) _BAD_PATTERNS list in pipeline._sanitize_title — kept
# in sync manually because pipeline is a downstream import from here and we
# don't want a circular dependency just to share a constant.
_TITLE_BAD_PATTERNS = (
    "字数", "场景", "目标", "要求", "注意", "提示", "格式",
    "左右", "以上", "以下", "不超过", "大约",
)


def _derive_title_from_outline_fields(
    goal: Any, key_events: Any
) -> str | None:
    """Derive a 4-8 char chapter title from outline ``goal`` / ``key_events``.

    Called from ``NovelDirector._parse_outline`` when the LLM omits a title
    or returns a placeholder like ``第N章``.  Pure local logic — no LLM call.
    Returns ``None`` when no usable phrase can be extracted.

    The returned candidate is pre-filtered against the same prompt-leak
    keyword list that ``pipeline._sanitize_title`` uses, so a candidate
    like "林辰的目标场景" (contains "目标"/"场景") never reaches the
    downstream sanitizer to be silently rejected.
    """
    import re as _re_t

    def _from_phrase(phrase: str) -> str | None:
        if not phrase:
            return None
        # Cut at first natural boundary
        head = _re_t.split(r"[，,。.！!？?；;、]", phrase)[0].strip()
        # Strip quotation marks
        head = head.strip("\"'\u201c\u201d\u300c\u300d\u300e\u300f")
        if len(head) > 12:
            head = head[:8]
        if len(head) < 2:
            return None
        # Reject if the candidate contains any prompt-leak keyword — matches
        # pipeline._sanitize_title's _BAD_PATTERNS filter.
        if any(p in head for p in _TITLE_BAD_PATTERNS):
            return None
        return head

    if isinstance(goal, str):
        candidate = _from_phrase(goal)
        if candidate:
            return candidate

    if isinstance(key_events, list) and key_events:
        first = key_events[0]
        if isinstance(first, str):
            candidate = _from_phrase(first)
            if candidate:
                return candidate

    return None


from src.novel.utils.json_extract import extract_json_obj

# Backward-compat alias — existing tests import ``_extract_json_obj`` from this
# module. Canonical implementation lives in ``src.novel.utils.json_extract``.
_extract_json_obj = extract_json_obj


# ---------------------------------------------------------------------------
# NovelDirector
# ---------------------------------------------------------------------------


class NovelDirector:
    """总导演 Agent - 负责大纲生成和流程协调。"""

    MAX_OUTLINE_RETRIES = 3

    def __init__(self, llm_client: Any):
        """
        Args:
            llm_client: 实现 ``chat(messages, temperature, json_mode)`` 的 LLMClient。
        """
        self.llm = llm_client

    # ------------------------------------------------------------------
    # 1. 分析用户输入
    # ------------------------------------------------------------------

    def analyze_input(
        self,
        genre: str,
        theme: str,
        target_words: int,
        custom_ideas: str | None = None,
    ) -> dict[str, Any]:
        """分析并丰富用户输入。

        Returns:
            dict 包含 suggested_template, suggested_style,
            volume_count, chapters_per_volume,
            total_chapters, analysis_summary。
        """
        total_chapters = max(1, target_words // _WORDS_PER_CHAPTER)
        volume_count = max(1, total_chapters // _CHAPTERS_PER_VOLUME)
        chapters_per_volume = max(1, total_chapters // volume_count)

        suggested_template = _GENRE_TEMPLATE_MAP.get(genre, "cyclic_upgrade")
        suggested_style = _GENRE_STYLE_MAP.get(genre, "webnovel.shuangwen")

        analysis_summary = f"题材: {genre}, 主题: {theme}, 目标字数: {target_words}"
        if custom_ideas:
            analysis_summary += f", 用户自定义: {custom_ideas}"

        return {
            "suggested_template": suggested_template,
            "suggested_style": suggested_style,
            "volume_count": volume_count,
            "chapters_per_volume": chapters_per_volume,
            "total_chapters": total_chapters,
            "analysis_summary": analysis_summary,
        }

    # ------------------------------------------------------------------
    # 2. 生成三层大纲
    # ------------------------------------------------------------------

    def generate_outline(
        self,
        genre: str,
        theme: str,
        target_words: int,
        template_name: str = "cyclic_upgrade",
        style_name: str | None = None,
        custom_ideas: str | None = None,
    ) -> Outline:
        """通过 LLM 生成三层大纲。

        流程：
        1. 根据模板确定幕数量
        2. LLM 生成总体故事弧线（acts）
        3. 拆分为卷大纲（volumes）
        4. 每卷拆分为章大纲（chapters）

        Returns:
            Outline 模型实例

        Raises:
            RuntimeError: LLM 连续 MAX_OUTLINE_RETRIES 次返回无效 JSON
        """
        # 获取模板元信息（处理 Outline.template 与 templates 文件的名称差异）
        tpl_lookup = _TEMPLATE_ALIAS.get(template_name, template_name)
        try:
            tpl = get_template(tpl_lookup)
        except KeyError:
            tpl = get_template("cyclic_upgrade")
            template_name = "cyclic_upgrade"

        total_chapters = max(1, target_words // _WORDS_PER_CHAPTER)
        volume_count = max(1, total_chapters // _CHAPTERS_PER_VOLUME)
        chapters_per_volume = max(1, total_chapters // volume_count)

        # 超长篇模式：当总章节超过 _CHAPTERS_PER_VOLUME 时，只生成第1卷的
        # 详细章节大纲 + 所有卷的概要框架，后续卷通过 generate_volume_outline
        # 按需生成。
        is_long_novel = total_chapters > _CHAPTERS_PER_VOLUME
        prompt_chapters = chapters_per_volume if is_long_novel else total_chapters

        # ---- Step 1: 用 LLM 生成大纲 JSON ----
        prompt = self._build_outline_prompt(
            genre=genre,
            theme=theme,
            target_words=target_words,
            template_name=template_name,
            act_count=tpl.act_count,
            volume_count=volume_count,
            chapters_per_volume=chapters_per_volume,
            total_chapters=total_chapters,
            custom_ideas=custom_ideas,
            first_volume_only=is_long_novel,
        )

        outline_data: dict | None = None
        last_error: str = ""

        for attempt in range(self.MAX_OUTLINE_RETRIES):
            try:
                response = self.llm.chat(
                    messages=[
                        {"role": "system", "content": "你是一位资深网络小说策划编辑。请严格按照 JSON 格式返回大纲。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.8,
                    json_mode=True,
                    max_tokens=8192,
                )
                outline_data = extract_json_obj(response.content)
                if outline_data is not None:
                    break
                last_error = f"LLM 返回内容无法解析为 JSON: {response.content[:200]}"
            except Exception as exc:
                last_error = f"LLM 调用失败: {exc}"
                log.warning("大纲生成第 %d 次尝试失败: %s", attempt + 1, last_error)
                if attempt < self.MAX_OUTLINE_RETRIES - 1:
                    time.sleep(2 ** attempt)

        if outline_data is None:
            raise RuntimeError(
                f"大纲生成失败，已重试 {self.MAX_OUTLINE_RETRIES} 次。最后错误: {last_error}"
            )

        # ---- Step 2: 解析 LLM 返回，构建 Outline ----
        # 超长篇模式下只填充第1卷的章节（prompt_chapters），而非全部
        return self._parse_outline(outline_data, template_name, prompt_chapters)

    # ------------------------------------------------------------------
    # 3. 规划下一章
    # ------------------------------------------------------------------

    def plan_next_chapter(self, state: NovelState) -> dict[str, Any]:
        """根据当前状态确定下一个要写的章节。

        Returns:
            dict 包含 current_chapter, current_chapter_outline 等字段。
        """
        current = state.get("current_chapter", 0)
        outline_data = state.get("outline")
        chapters_done = state.get("chapters") or []

        if not outline_data:
            return {"errors": [{"agent": "NovelDirector", "message": "大纲不存在，无法规划下一章"}]}

        # 找到下一个未完成的章节
        completed_numbers = {ch.get("chapter_number", 0) for ch in chapters_done}
        outline = Outline(**outline_data)
        next_chapter = None

        for ch_outline in sorted(outline.chapters, key=lambda c: c.chapter_number):
            if ch_outline.chapter_number not in completed_numbers:
                next_chapter = ch_outline
                break

        if next_chapter is None:
            # 所有章节已完成
            return {
                "should_continue": False,
                "decisions": [
                    _make_decision(
                        step="plan_next_chapter",
                        decision="所有章节已完成",
                        reason=f"已完成 {len(completed_numbers)} 章",
                    )
                ],
            }

        return {
            "current_chapter": next_chapter.chapter_number,
            "current_chapter_outline": next_chapter.model_dump(),
            "should_continue": True,
            "decisions": [
                _make_decision(
                    step="plan_next_chapter",
                    decision=f"下一章: 第 {next_chapter.chapter_number} 章 - {next_chapter.title}",
                    reason=f"已完成 {len(completed_numbers)} 章，按序推进",
                )
            ],
        }

    # ------------------------------------------------------------------
    # 4. 分卷大纲生成（超长篇支持）
    # ------------------------------------------------------------------

    def generate_volume_outline(
        self,
        novel_data: dict,
        volume_number: int,
        previous_summary: str = "",
    ) -> list[dict]:
        """为指定卷生成章节大纲（基于已有内容和整体框架）。

        当目标字数超过 75000 字（约30章）时，创建项目只生成第1卷的详细
        章节大纲。后续卷的章节大纲在需要时通过此方法动态生成，避免一次性
        生成过多章节导致 token 爆炸。

        Args:
            novel_data: Novel dict（包含 outline.acts, outline.volumes 等整体框架）
            volume_number: 要生成大纲的卷号（从1开始）
            previous_summary: 前面各卷的内容摘要

        Returns:
            list[dict]: 章节大纲列表（ChapterOutline 格式的 dict）
        """
        outline = novel_data.get("outline", {})
        volumes = outline.get("volumes", [])
        main_storyline = outline.get("main_storyline", {})

        # 找到目标卷的信息
        target_volume = None
        for vol in volumes:
            if vol.get("volume_number") == volume_number:
                target_volume = vol
                break

        if target_volume is None:
            log.warning("卷 %d 在整体框架中不存在，使用默认信息", volume_number)
            target_volume = {
                "volume_number": volume_number,
                "title": f"第{volume_number}卷",
                "core_conflict": "待规划",
                "resolution": "待规划",
                "chapters": [],
            }

        # 计算本卷的章节范围
        vol_chapters = target_volume.get("chapters", [])
        if vol_chapters:
            start_ch = min(vol_chapters)
            end_ch = max(vol_chapters)
            chapters_count = len(vol_chapters)
        else:
            # 根据 volumes 列表推断章节范围
            chapters_count = _CHAPTERS_PER_VOLUME
            existing_max = 0
            for ch in outline.get("chapters", []):
                ch_num = ch.get("chapter_number", 0) if isinstance(ch, dict) else 0
                if ch_num > existing_max:
                    existing_max = ch_num
            start_ch = existing_max + 1
            end_ch = start_ch + chapters_count - 1

        # 提取世界观和角色信息
        world_setting = novel_data.get("world_setting", {})
        characters = novel_data.get("characters", [])
        # Phase 0 架构重构：零默认体裁。项目数据必须带 genre。
        genre = novel_data.get("genre")
        if not genre:
            raise ValueError(
                "novel_data 缺少 genre 字段（Phase 0 架构重构：禁止默认回退到玄幻）"
            )
        theme = novel_data.get("theme", "")

        world_info = ""
        if world_setting:
            era = world_setting.get("era", "")
            location = world_setting.get("location", "")
            if era or location:
                world_info = f"世界观：{era}，{location}"

        char_info = ""
        if characters:
            char_names = []
            for c in characters[:5]:  # 最多取5个主要角色
                if isinstance(c, dict):
                    name = c.get("name", "")
                    role = c.get("role", "")
                    if name:
                        char_names.append(f"{name}({role})" if role else name)
            if char_names:
                char_info = f"主要角色：{'、'.join(char_names)}"

        # 构建整体框架摘要
        acts_info = ""
        for act in outline.get("acts", []):
            if isinstance(act, dict):
                acts_info += f"  - {act.get('name', '')}: {act.get('description', '')} (第{act.get('start_chapter', '?')}-{act.get('end_chapter', '?')}章)\n"

        volumes_info = ""
        for vol in volumes:
            if isinstance(vol, dict):
                vol_num = vol.get("volume_number", "?")
                vol_title = vol.get("title", "")
                vol_conflict = vol.get("core_conflict", "")
                vol_resolution = vol.get("resolution", "")
                marker = " [当前卷]" if vol_num == volume_number else ""
                volumes_info += f"  - 第{vol_num}卷「{vol_title}」: 核心矛盾={vol_conflict}, 解决方向={vol_resolution}{marker}\n"

        # 主线信息
        storyline_info = ""
        if main_storyline:
            storyline_info = f"""
主线信息：
  - 主角：{main_storyline.get('protagonist', '未知')}
  - 目标：{main_storyline.get('protagonist_goal', '未知')}
  - 核心冲突：{main_storyline.get('core_conflict', '未知')}
  - 角色弧线：{main_storyline.get('character_arc', '未知')}
  - 赌注：{main_storyline.get('stakes', '未知')}
"""

        prompt = f"""请为小说的第{volume_number}卷生成详细的章节大纲。

题材：{genre}
主题：{theme}
{world_info}
{char_info}
{storyline_info}

【整体故事框架】
幕结构：
{acts_info}
卷结构：
{volumes_info}

【当前卷信息】
卷号：第{volume_number}卷「{target_volume.get('title', '')}」
核心矛盾：{target_volume.get('core_conflict', '')}
解决方向：{target_volume.get('resolution', '')}
章节范围：第{start_ch}章 - 第{end_ch}章（共{chapters_count}章）

【前情摘要】
{previous_summary if previous_summary else '（这是第一卷，无前情）'}

请严格按以下 JSON 格式返回：
{{
  "chapters": [
    {{
      "chapter_number": {start_ch},
      "title": "章节标题",
      "goal": "本章目标",
      "key_events": ["事件1", "事件2"],
      "involved_characters": [],
      "plot_threads": [],
      "estimated_words": 2500,
      "mood": "蓄力",
      "storyline_progress": "本章如何推进主线",
      "chapter_summary": "本章内容2-3句话摘要",
      "chapter_brief": {{
        "main_conflict": "本章主冲突",
        "payoff": "本章爽点/情绪回报",
        "character_arc_step": "主角变化",
        "foreshadowing_plant": ["要埋的伏笔"],
        "foreshadowing_collect": ["要回收的伏笔"],
        "end_hook_type": "悬疑|危机|反转|情感|发现|无"
      }}
    }}
  ]
}}

要求：
1. 章节号从 {start_ch} 开始，到 {end_ch} 结束，共 {chapters_count} 章
2. 承接前情，自然过渡
3. 围绕本卷核心矛盾展开
4. 每章必须推进主线
5. 情节有起伏，节奏合理
6. mood 可选：蓄力、小爽、大爽、过渡、虐心、反转、日常
"""

        # 调用 LLM
        result_data: dict | None = None
        last_error = ""

        for attempt in range(self.MAX_OUTLINE_RETRIES):
            try:
                response = self.llm.chat(
                    messages=[
                        {"role": "system", "content": "你是一位资深网络小说策划编辑。请严格按照 JSON 格式返回章节大纲。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.8,
                    json_mode=True,
                    max_tokens=8192,
                )
                result_data = extract_json_obj(response.content)
                if result_data is not None:
                    break
                last_error = f"LLM 返回内容无法解析为 JSON: {response.content[:200]}"
            except Exception as exc:
                last_error = f"LLM 调用失败: {exc}"
                log.warning("卷%d大纲生成第 %d 次尝试失败: %s", volume_number, attempt + 1, last_error)
                if attempt < self.MAX_OUTLINE_RETRIES - 1:
                    time.sleep(2 ** attempt)

        if result_data is None:
            raise RuntimeError(
                f"卷{volume_number}大纲生成失败，已重试 {self.MAX_OUTLINE_RETRIES} 次。最后错误: {last_error}"
            )

        # 解析章节
        chapters_data = result_data.get("chapters", [])
        parsed_chapters: list[dict] = []

        for ch_data in chapters_data:
            try:
                if "chapter_brief" not in ch_data or not isinstance(ch_data.get("chapter_brief"), dict):
                    ch_data["chapter_brief"] = {}
                # Validate by constructing a ChapterOutline
                co = ChapterOutline(**ch_data)
                parsed_chapters.append(co.model_dump())
            except Exception:
                log.warning("跳过无效卷大纲 chapter 数据: %s", ch_data)

        # 兜底：填充缺失的章节
        existing_nums = {ch["chapter_number"] for ch in parsed_chapters}
        for i in range(start_ch, end_ch + 1):
            if i not in existing_nums:
                parsed_chapters.append(
                    ChapterOutline(
                        chapter_number=i,
                        title=f"第{i}章",
                        goal="待规划",
                        key_events=["待规划"],
                        estimated_words=2500,
                        mood="蓄力",
                    ).model_dump()
                )

        parsed_chapters.sort(key=lambda c: c["chapter_number"])
        log.info("卷%d大纲生成完成: %d章 (第%d-%d章)", volume_number, len(parsed_chapters), start_ch, end_ch)
        return parsed_chapters

    # ------------------------------------------------------------------
    # 4b. 里程碑自动生成（Intervention A 补全）
    # ------------------------------------------------------------------

    def generate_volume_milestones(
        self,
        volume: dict,
        chapter_outlines: list[dict],
        genre: str = "",
    ) -> list[dict]:
        """为一卷自动生成叙事里程碑。

        Args:
            volume: Volume dict with volume_number, title, core_conflict, resolution.
            chapter_outlines: Chapter outlines belonging to this volume.
            genre: Novel genre for context.

        Returns:
            list[dict]: NarrativeMilestone-shaped dicts ready for storage.
        """
        vol_num = volume.get("volume_number", 1)
        vol_title = volume.get("title", f"第{vol_num}卷")
        core_conflict = volume.get("core_conflict", "")
        resolution = volume.get("resolution", "")
        start_ch = volume.get("start_chapter") or (
            min((c.get("chapter_number", 999) for c in chapter_outlines), default=1)
        )
        end_ch = volume.get("end_chapter") or (
            max((c.get("chapter_number", 0) for c in chapter_outlines), default=start_ch)
        )

        # Summarise chapter goals for context
        ch_goals = []
        for ch in sorted(chapter_outlines, key=lambda c: c.get("chapter_number", 0)):
            cn = ch.get("chapter_number", 0)
            goal = ch.get("goal", "")
            if goal and goal != "待规划":
                ch_goals.append(f"第{cn}章: {goal}")
        ch_goals_text = "\n".join(ch_goals[:15]) or "（章节目标暂无）"

        prompt = f"""请为小说的第{vol_num}卷「{vol_title}」生成 3-5 个叙事里程碑。

题材：{genre}
本卷核心矛盾：{core_conflict}
本卷解决方向：{resolution}
章节范围：第{start_ch}章 - 第{end_ch}章

【各章目标概览】
{ch_goals_text}

请严格按以下 JSON 格式返回：
{{
  "milestones": [
    {{
      "milestone_id": "vol{vol_num}_m1",
      "description": "里程碑描述（10-50字，必须是可验证的叙事事件）",
      "target_chapter_range": [{start_ch}, {end_ch}],
      "verification_type": "auto_keyword",
      "verification_criteria": ["关键词1", "关键词2"],
      "priority": "critical"
    }}
  ]
}}

要求：
1. milestone_id 格式: vol{vol_num}_m1, vol{vol_num}_m2, ...
2. 第一个里程碑 priority 必须为 critical（本卷核心事件）
3. target_chapter_range 必须在 [{start_ch}, {end_ch}] 范围内
4. 里程碑应覆盖本卷开头、中段、结尾，确保主线推进可追踪
5. verification_type 优先用 auto_keyword（免费），只有无法用关键词验证时才用 llm_review
6. verification_criteria: auto_keyword 时为关键词列表，llm_review 时为验证问题字符串
7. 里程碑描述必须是具体的叙事事件，不能是抽象目标
"""

        try:
            response = self.llm.chat(
                messages=[
                    {"role": "system", "content": "你是一位资深网络小说策划编辑。请严格按照 JSON 格式返回里程碑。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                json_mode=True,
                max_tokens=2048,
            )
            data = extract_json_obj(response.content)
            if not data:
                log.warning("里程碑生成 LLM 返回无效 JSON，使用空列表")
                return []

            raw_milestones = data.get("milestones", [])
        except Exception as exc:
            log.warning("里程碑自动生成失败: %s", exc)
            return []

        # Validate each milestone via the Pydantic model
        from src.novel.models.narrative_control import NarrativeMilestone

        valid: list[dict] = []
        for m in raw_milestones:
            try:
                # Clamp range to volume boundaries
                rng = m.get("target_chapter_range", [start_ch, end_ch])
                if len(rng) >= 2:
                    rng = [max(rng[0], start_ch), min(rng[1], end_ch)]
                    m["target_chapter_range"] = rng
                obj = NarrativeMilestone(**m)
                valid.append(obj.model_dump())
            except Exception:
                log.warning("跳过无效里程碑: %s", m)

        log.info(
            "卷%d 自动生成 %d 个里程碑 (共 %d 个候选)",
            vol_num, len(valid), len(raw_milestones),
        )
        return valid

    # ------------------------------------------------------------------
    # 5. Story Arc 生成（叙事弧线）
    # ------------------------------------------------------------------

    def generate_story_arcs(
        self,
        volume_outline: VolumeOutline | dict,
        chapter_outlines: list[ChapterOutline | dict],
        genre: str,
    ) -> list[dict]:
        """为指定卷生成故事弧线（StoryUnit 结构）。

        将一卷的章节分组为多个 3-7 章的叙事弧线（mini-arc），每个弧线
        有自己的开端钩子、升级点、转折点、收束方式和遗留悬念。

        Args:
            volume_outline: 卷大纲对象（含 volume_number, core_conflict 等）。
            chapter_outlines: 本卷的章节大纲列表。
            genre: 题材（玄幻/科幻/都市等），影响弧线风格。

        Returns:
            list[dict]: StoryUnit 兼容字段的 dict 列表。如果 LLM 调用
            失败，返回基本的占位弧线结构。
        """
        if isinstance(volume_outline, dict):
            raw_chapters = volume_outline.get("chapters") or []
            # 顶层 Outline.chapters 是 list[ChapterOutline]，而 VolumeOutline.chapters 是 list[int]
            if raw_chapters and isinstance(raw_chapters[0], dict):
                chapters = [
                    c.get("chapter_number")
                    for c in raw_chapters
                    if c.get("chapter_number") is not None
                ]
            else:
                chapters = list(raw_chapters)
            volume_id = volume_outline.get("volume_number", 1)
            core_conflict = volume_outline.get("core_conflict", "")
        else:
            chapters = volume_outline.chapters
            volume_id = volume_outline.volume_number
            core_conflict = getattr(volume_outline, "core_conflict", "")

        if not chapters:
            return []

        # 确定弧线数量：目标每弧线约 5 章
        arc_count = max(1, math.ceil(len(chapters) / 5))

        # 分配章节到各弧线（每弧线 3-7 章）
        arc_chapter_groups = self._distribute_chapters_to_arcs(
            chapters, arc_count
        )

        # 构建章节信息摘要，供 LLM 使用
        ch_outline_map: dict[int, dict] = {}
        for co in chapter_outlines:
            if isinstance(co, dict):
                ch_outline_map[co.get("chapter_number", 0)] = co
            else:
                ch_outline_map[co.chapter_number] = co.model_dump() if hasattr(co, "model_dump") else {"chapter_number": co.chapter_number, "title": co.title, "goal": co.goal}

        arcs: list[dict] = []
        for i, arc_chapters in enumerate(arc_chapter_groups):
            arc_id = f"arc_{volume_id}_{i + 1}"

            # 收集本弧线章节的大纲信息
            arc_ch_outlines = [
                ch_outline_map.get(ch_num, {"chapter_number": ch_num, "title": f"第{ch_num}章", "goal": "待规划"})
                for ch_num in arc_chapters
            ]

            arc_data = self._generate_single_arc(
                volume_outline=volume_outline,
                arc_chapters=arc_chapters,
                arc_chapter_outlines=arc_ch_outlines,
                arc_number=i + 1,
                arc_id=arc_id,
                genre=genre,
                volume_id=volume_id,
                core_conflict=core_conflict,
            )
            arcs.append(arc_data)

        log.info(
            "卷%d弧线生成完成: %d个弧线",
            volume_id, len(arcs),
        )
        return arcs

    def _distribute_chapters_to_arcs(
        self, chapters: list[int], arc_count: int
    ) -> list[list[int]]:
        """将章节列表均匀分配到弧线中，每弧线 3-7 章。

        Args:
            chapters: 排序后的章节号列表。
            arc_count: 目标弧线数。

        Returns:
            每个弧线的章节号列表。
        """
        sorted_chapters = sorted(chapters)
        total = len(sorted_chapters)

        if total <= 7:
            return [sorted_chapters]

        base_size = total // arc_count
        remainder = total % arc_count

        groups: list[list[int]] = []
        idx = 0
        for i in range(arc_count):
            size = base_size + (1 if i < remainder else 0)
            # Clamp to 3-7
            size = max(3, min(7, size))
            group = sorted_chapters[idx : idx + size]
            if group:
                groups.append(group)
            idx += size
            if idx >= total:
                break

        # Handle remaining chapters (assign to last group)
        if idx < total and groups:
            groups[-1].extend(sorted_chapters[idx:])
            # If last group exceeds 7, split it
            if len(groups[-1]) > 7:
                overflow = groups[-1][7:]
                groups[-1] = groups[-1][:7]
                groups.append(overflow)

        return groups

    def _generate_single_arc(
        self,
        volume_outline: VolumeOutline | dict,
        arc_chapters: list[int],
        arc_chapter_outlines: list[dict],
        arc_number: int,
        arc_id: str,
        genre: str,
        volume_id: int | None = None,
        core_conflict: str | None = None,
    ) -> dict:
        """通过 LLM 生成单个弧线的叙事结构。

        Args:
            volume_outline: 父卷大纲。
            arc_chapters: 本弧线包含的章节号。
            arc_chapter_outlines: 本弧线各章节的大纲信息。
            arc_number: 弧线序号（从 1 开始）。
            arc_id: 弧线唯一标识。
            genre: 题材。

        Returns:
            StoryUnit 兼容的 dict。
        """
        # 构建章节摘要
        ch_summaries = []
        for co in arc_chapter_outlines:
            ch_num = co.get("chapter_number", "?")
            title = co.get("title", "")
            goal = co.get("goal", "")
            ch_summaries.append(f"  第{ch_num}章「{title}」：{goal}")
        chapters_text = "\n".join(ch_summaries)

        # 计算关键点位
        escalation_idx = max(0, int(len(arc_chapters) * 0.6) - 1)
        turning_idx = max(0, int(len(arc_chapters) * 0.75) - 1)
        escalation_ch = arc_chapters[min(escalation_idx, len(arc_chapters) - 1)]
        turning_ch = arc_chapters[min(turning_idx, len(arc_chapters) - 1)]

        # 兼容 dict / 对象 volume_outline
        if volume_id is None:
            volume_id = (
                volume_outline.get("volume_number", 1)
                if isinstance(volume_outline, dict)
                else volume_outline.volume_number
            )
        if core_conflict is None:
            core_conflict = (
                volume_outline.get("core_conflict", "")
                if isinstance(volume_outline, dict)
                else getattr(volume_outline, "core_conflict", "")
            )

        prompt = f"""请为小说的第{volume_id}卷第{arc_number}段叙事弧线生成结构。

题材：{genre}
卷核心矛盾：{core_conflict}
本弧线章节（第{arc_chapters[0]}-{arc_chapters[-1]}章）：
{chapters_text}

请严格按以下 JSON 格式返回：
{{
  "name": "弧线名称（如：新生试炼篇）",
  "hook": "开端钩子：什么事件启动了这段故事弧线",
  "closure_method": "收束方式：这段弧线如何结束",
  "residual_question": "遗留悬念：结束后留下什么未解之谜引入下一弧线"
}}

要求：
1. name 简短有力，2-6个字
2. hook 必须与第{arc_chapters[0]}章的内容相关
3. closure_method 必须与第{arc_chapters[-1]}章的结局相关
4. residual_question 要为后续弧线留钩子
"""

        try:
            response = self.llm.chat(
                messages=[
                    {"role": "system", "content": "你是一位资深网络小说策划编辑。请严格按照 JSON 格式返回弧线结构。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                json_mode=True,
                max_tokens=1024,
            )
            if not response or not response.content:
                raise ValueError("LLM 返回空响应")
            arc_data = extract_json_obj(response.content)
        except Exception as exc:
            log.warning("弧线%d LLM 生成失败: %s，使用占位结构", arc_number, exc)
            arc_data = None

        if arc_data is None:
            arc_data = {}

        return {
            "arc_id": arc_id,
            "volume_id": volume_id,
            "name": arc_data.get("name", f"第{arc_number}段"),
            "chapters": arc_chapters,
            "phase": "setup",
            "hook": arc_data.get("hook", f"第{arc_chapters[0]}章开始"),
            "escalation_point": escalation_ch,
            "turning_point": turning_ch,
            "closure_method": arc_data.get("closure_method", f"第{arc_chapters[-1]}章收束"),
            "residual_question": arc_data.get("residual_question", "待规划"),
            "status": "planning",
            "completion_rate": 0.0,
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _build_outline_prompt(
        self,
        genre: str,
        theme: str,
        target_words: int,
        template_name: str,
        act_count: int,
        volume_count: int,
        chapters_per_volume: int,
        total_chapters: int,
        custom_ideas: str | None = None,
        first_volume_only: bool = False,
    ) -> str:
        """构建大纲生成的 LLM prompt（中文）。

        Args:
            first_volume_only: 超长篇模式 -- 生成所有卷的概要框架，
                但只输出第1卷的详细章节大纲（chapters_per_volume 章），
                后续卷的章节大纲按需通过 generate_volume_outline 生成。
        """
        custom_part = f"\n用户额外要求：{custom_ideas}" if custom_ideas else ""

        if first_volume_only:
            chapter_instruction = (
                f"\n【超长篇模式】这是一部超长篇小说（共{total_chapters}章/{volume_count}卷），"
                f"chapters 数组只需要生成第1卷的详细章节大纲（第1-{chapters_per_volume}章，"
                f"共{chapters_per_volume}章）。但 acts 和 volumes 必须覆盖全书所有卷的概要框架。\n"
            )
            chapter_count_instruction = (
                f"1. chapters 数组：章节号从 1 开始连续递增，总共 {chapters_per_volume} 章（仅第1卷）"
            )
        else:
            chapter_instruction = ""
            chapter_count_instruction = (
                f"1. 章节号从 1 开始连续递增，总共 {total_chapters} 章"
            )

        return f"""请为以下小说生成完整三层大纲：

题材：{genre}
主题：{theme}
目标字数：{target_words} 字
大纲模板：{template_name}
幕数量：{act_count}
卷数量：{volume_count}
每卷章节数：{chapters_per_volume}
总章节数：{total_chapters}{custom_part}
{chapter_instruction}
【专业写作原则 — 必须严格遵守】
1. 主线为王：整部小说必须有一条清晰的主线（主角目标→障碍→成长→达成/失败）
2. 开场即冲突：第1章必须用冲突或悬念抓住读者，禁止慢热开场
3. 三章定生死：前3章内读者必须能明确感知到核心矛盾是什么
4. 每章必推进：每章必须在主线上有实质性推进，不允许原地踏步的过渡章
5. 赌注递增：故事赌注随章节推进不断升级，让读者越来越紧张
6. 角色弧线：主角必须有内在成长，从开始到结束是不同的人

请严格按以下 JSON 格式返回：
{{
  "main_storyline": {{
    "protagonist": "主角姓名",
    "protagonist_goal": "主角的核心目标/欲望（贯穿全书）",
    "core_conflict": "主角实现目标的最大障碍",
    "character_arc": "主角从什么状态变成什么状态（内在成长）",
    "stakes": "如果主角失败会怎样（赌注）",
    "theme_statement": "故事想传达的核心主题（一句话）"
  }},
  "acts": [
    {{
      "name": "第一幕：xxx",
      "description": "描述这一幕的主要内容",
      "start_chapter": 1,
      "end_chapter": 10
    }}
  ],
  "volumes": [
    {{
      "volume_number": 1,
      "title": "卷名",
      "core_conflict": "本卷核心矛盾",
      "resolution": "本卷如何解决",
      "chapters": [1, 2, 3, ...]
    }}
  ],
  "chapters": [
    {{
      "chapter_number": 1,
      "title": "章节标题",
      "goal": "本章目标",
      "key_events": ["事件1", "事件2"],
      "involved_characters": [],
      "plot_threads": [],
      "estimated_words": 2500,
      "mood": "蓄力",
      "storyline_progress": "本章如何推进主线（必须具体，不能空泛）",
      "chapter_summary": "本章内容2-3句话摘要",
      "chapter_brief": {{
        "main_conflict": "本章主冲突是什么（必须具体）",
        "payoff": "本章必须兑现的爽点/情绪回报",
        "character_arc_step": "主角在本章的变化（从X到Y）",
        "foreshadowing_plant": ["本章要埋的伏笔"],
        "foreshadowing_collect": ["本章要回收的伏笔"],
        "end_hook_type": "悬疑|危机|反转|情感|发现|无"
      }}
    }}
  ]
}}

mood 可选值：蓄力、小爽、大爽、过渡、虐心、反转、日常。
请确保：
{chapter_count_instruction}
2. 每卷的 chapters 列表对应正确的章节号
3. 每幕的 start_chapter 和 end_chapter 不重叠
4. 情节有起伏，节奏合理
5. 【主线清晰】每章的 storyline_progress 必须明确说明本章如何推进主角目标
6. 【开场钩子】第1章必须以冲突/悬念/危机开场，禁止用日常铺垫开头
7. 【节奏紧凑】前3章内必须进入核心冲突，不允许超过2章的纯铺垫
8. 【章节摘要】每章必须有具体的 chapter_summary，不能为空
9. 【赌注升级】随着故事推进，赌注必须不断升级（个人→团队→世界）
10. 【章节任务书】每章必须有 chapter_brief，包含 main_conflict、payoff、character_arc_step、foreshadowing_plant、foreshadowing_collect、end_hook_type
"""

    def _parse_outline(
        self,
        data: dict,
        template_name: str,
        total_chapters: int,
    ) -> Outline:
        """将 LLM 返回的 JSON 解析为 Outline 模型。

        对缺失字段进行兜底填充，确保返回合法的 Outline。
        """
        # 解析 acts
        acts: list[Act] = []
        for act_data in data.get("acts", []):
            try:
                acts.append(Act(**act_data))
            except Exception:
                log.warning("跳过无效 act 数据: %s", act_data)

        # 解析 volumes
        volumes: list[VolumeOutline] = []
        for vol_data in data.get("volumes", []):
            try:
                volumes.append(VolumeOutline(**vol_data))
            except Exception:
                log.warning("跳过无效 volume 数据: %s", vol_data)

        # 解析 chapters
        chapters: list[ChapterOutline] = []
        for ch_data in data.get("chapters", []):
            try:
                # 确保 chapter_brief 存在且为 dict
                if "chapter_brief" not in ch_data or not isinstance(ch_data.get("chapter_brief"), dict):
                    ch_data["chapter_brief"] = {}
                # Title validation: if missing/empty/placeholder, try to
                # derive a short phrase from goal or key_events[0].  Never
                # call the LLM — that would blow up token cost.
                ch_num_raw = ch_data.get("chapter_number") or len(chapters) + 1
                title_raw = (ch_data.get("title") or "").strip()
                placeholder = f"第{ch_num_raw}章"
                if not title_raw or title_raw == placeholder:
                    log.warning(
                        "chapter %s 标题缺失或为占位符，尝试从 goal 派生",
                        ch_num_raw,
                    )
                    fallback = _derive_title_from_outline_fields(
                        ch_data.get("goal"),
                        ch_data.get("key_events"),
                    )
                    if fallback:
                        ch_data["title"] = fallback
                chapters.append(ChapterOutline(**ch_data))
            except Exception:
                log.warning("跳过无效 chapter 数据: %s", ch_data)

        # 兜底：如果 LLM 没有返回足够的 chapters，填充占位
        existing_nums = {ch.chapter_number for ch in chapters}
        for i in range(1, total_chapters + 1):
            if i not in existing_nums:
                chapters.append(
                    ChapterOutline(
                        chapter_number=i,
                        title=f"第{i}章",
                        goal="待规划",
                        key_events=["待规划"],
                        estimated_words=4000,
                        mood="蓄力",
                    )
                )

        # 按章节号排序
        chapters.sort(key=lambda c: c.chapter_number)

        # 兜底：如果没有 acts，创建默认
        if not acts:
            acts = [
                Act(
                    name="第一幕：开端",
                    description="故事铺垫与主角登场",
                    start_chapter=1,
                    end_chapter=total_chapters,
                )
            ]

        # 兜底：如果没有 volumes，创建默认
        if not volumes:
            volumes = [
                VolumeOutline(
                    volume_number=1,
                    title="第一卷",
                    core_conflict="主线矛盾",
                    resolution="阶段性解决",
                    chapters=list(range(1, total_chapters + 1)),
                )
            ]

        # 提取 main_storyline（防御 LLM 返回 null 或非 dict 类型）
        main_storyline = data.get("main_storyline") or {}
        if not isinstance(main_storyline, dict):
            main_storyline = {}
        elif not main_storyline.get("protagonist_goal"):
            # protagonist_goal 缺失时仍可继续，但记录警告
            pass  # 下游代码用 .get() 有默认值，不影响运行

        return Outline(
            template=template_name,
            main_storyline=main_storyline,
            acts=acts,
            volumes=volumes,
            chapters=chapters,
        )


# ---------------------------------------------------------------------------
# LangGraph 节点函数
# ---------------------------------------------------------------------------


def novel_director_node(state: NovelState) -> dict[str, Any]:
    """LangGraph 节点：NovelDirector。

    - 如果 state 中没有 outline：分析输入 + 生成大纲
    - 如果 state 中已有 outline：规划下一章
    """
    decisions: list[Decision] = []
    errors: list[dict] = []

    # 获取 LLM 客户端
    llm_config = get_stage_llm_config(state, "outline_generation")
    try:
        llm = create_llm_client(llm_config)
    except Exception as exc:
        return {
            "errors": [{"agent": "NovelDirector", "message": f"LLM 初始化失败: {exc}"}],
            "completed_nodes": ["novel_director"],
        }

    director = NovelDirector(llm)

    # ---- 情况 1：大纲已存在（恢复模式），规划下一章 ----
    if state.get("outline") is not None:
        decisions.append(
            _make_decision(
                step="entry",
                decision="大纲已存在，跳过生成，规划下一章",
                reason="resume 模式或大纲已在之前生成",
            )
        )
        result = director.plan_next_chapter(state)
        result.setdefault("decisions", [])
        result["decisions"] = decisions + result["decisions"]
        result["completed_nodes"] = ["novel_director"]
        return result

    # ---- 情况 2：全新创作，分析输入 + 生成大纲 ----
    # Phase 0 架构重构：零默认体裁。立项必须显式指定 genre。
    genre = state.get("genre")
    if not genre:
        raise ValueError(
            "genre 必须显式指定（Phase 0 架构重构：禁止默认回退到玄幻）"
        )
    theme = state.get("theme", "成长与冒险")
    target_words = state.get("target_words", 100000)
    custom_ideas = state.get("custom_style_reference")
    template_name = state.get("template", "")
    style_name = state.get("style_name", "")

    # 分析输入
    try:
        analysis = director.analyze_input(genre, theme, target_words, custom_ideas)
        decisions.append(
            _make_decision(
                step="analyze_input",
                decision=f"输入分析完成: {analysis['analysis_summary']}",
                reason="根据用户输入推断模板和风格",
                data=analysis,
            )
        )

        # 如果用户没有指定模板/风格，使用推荐值
        if not template_name:
            template_name = analysis["suggested_template"]
        if not style_name:
            style_name = analysis["suggested_style"]

    except Exception as exc:
        log.warning("输入分析失败，使用默认值: %s", exc)
        errors.append({"agent": "NovelDirector", "message": f"输入分析失败: {exc}"})
        if not template_name:
            template_name = "cyclic_upgrade"
        if not style_name:
            style_name = "webnovel.shuangwen"

    # 生成大纲
    try:
        outline = director.generate_outline(
            genre=genre,
            theme=theme,
            target_words=target_words,
            template_name=template_name,
            style_name=style_name,
            custom_ideas=custom_ideas,
        )
        decisions.append(
            _make_decision(
                step="generate_outline",
                decision=f"大纲生成完成: {len(outline.acts)} 幕, {len(outline.volumes)} 卷, {len(outline.chapters)} 章",
                reason="通过 LLM 生成三层大纲",
            )
        )
    except Exception as exc:
        log.error("大纲生成失败: %s", exc)
        return {
            "errors": errors + [{"agent": "NovelDirector", "message": f"大纲生成失败: {exc}"}],
            "decisions": decisions,
            "completed_nodes": ["novel_director"],
        }

    # --- Style Bible generation (Intervention D) ---
    style_bible_data = None
    try:
        from src.novel.services.style_bible_generator import StyleBibleGenerator

        bible_gen = StyleBibleGenerator(llm)
        style_bible = bible_gen.generate(
            genre=genre,
            theme=theme,
            style_name=style_name,
        )
        style_bible_data = style_bible.model_dump()
        decisions.append(
            _make_decision(
                step="generate_style_bible",
                decision="风格圣经生成完成",
                reason=f"基于风格预设 {style_name} 生成量化目标",
                data={"voice_description": style_bible.voice_description},
            )
        )
        log.info("风格圣经生成完成: %s", style_name)
    except Exception as exc:
        log.warning("风格圣经生成失败（非阻塞）: %s", exc)
        errors.append({"agent": "NovelDirector", "message": f"风格圣经生成失败: {exc}"})

    return {
        "outline": outline.model_dump(),
        "template": template_name,
        "style_name": style_name,
        "style_bible": style_bible_data,
        "total_chapters": len(outline.chapters),
        "current_chapter": 0,
        "should_continue": True,
        "decisions": decisions,
        "errors": errors,
        "completed_nodes": ["novel_director"],
    }
