"""NovelDirector - 总导演 Agent

负责：
1. 分析用户输入（题材、主题、字数）
2. 生成三层大纲（总大纲 -> 卷大纲 -> 章大纲）
3. 规划 Agent 工作流
4. 作为 LangGraph 节点协调整个创作流程
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from src.llm.llm_client import create_llm_client
from src.novel.agents.state import Decision, NovelState
from src.novel.models.novel import (
    Act,
    ChapterOutline,
    Outline,
    VolumeOutline,
)
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

_WORDS_PER_CHAPTER = 2500  # 每章约 2000-3000 字
_CHAPTERS_PER_VOLUME = 30  # 每卷约 30 章

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


def _extract_json_obj(text: str | None) -> dict | None:
    """从 LLM 输出中稳健提取 JSON 对象。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


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
            dict 包含 suggested_template, suggested_style_category,
            suggested_style, volume_count, chapters_per_volume,
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

        # ---- Step 1: 用 LLM 生成完整大纲 JSON ----
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
                outline_data = _extract_json_obj(response.content)
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
        return self._parse_outline(outline_data, template_name, total_chapters)

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
        chapters_done = state.get("chapters", [])

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
    ) -> str:
        """构建大纲生成的 LLM prompt（中文）。"""
        custom_part = f"\n用户额外要求：{custom_ideas}" if custom_ideas else ""

        return f"""请为以下小说生成完整三层大纲：

题材：{genre}
主题：{theme}
目标字数：{target_words} 字
大纲模板：{template_name}
幕数量：{act_count}
卷数量：{volume_count}
每卷章节数：{chapters_per_volume}
总章节数：{total_chapters}{custom_part}

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
1. 章节号从 1 开始连续递增，总共 {total_chapters} 章
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
    llm_config = state.get("config", {}).get("llm", {})
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
    genre = state.get("genre", "玄幻")
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

    return {
        "outline": outline.model_dump(),
        "template": template_name,
        "style_name": style_name,
        "total_chapters": len(outline.chapters),
        "current_chapter": 0,
        "should_continue": True,
        "decisions": decisions,
        "errors": errors,
        "completed_nodes": ["novel_director"],
    }
