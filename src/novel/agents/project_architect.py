"""ProjectArchitect — 立项 + 骨架架构师 Agent（Phase 2-γ，架构重构 2026-04）

职责
----
处理新项目的"立项 + 骨架"阶段。每一段（synopsis / characters / world /
arcs / volume_breakdown）都是独立的 ``propose_*`` 方法，**各自**一次独立
LLM 调用。作者可以对任一段不满意时通过 :meth:`regenerate_section` 单独重生，
不触及其它段。

设计约束
--------
* **propose 不入库**：每个 ``propose_*`` 返回 ``*Proposal`` dataclass，需调
  ``.accept(novel)`` / ``.accept_into(novel)`` 才写入 Novel 实例。
* **SYNC only**（与 LLMClient 一致）。
* **零默认体裁**：传入 ``meta`` 必须带 ``genre``，否则抛 ``ValueError``。
* 取代的 Agent：
    - ``WorldBuilder`` —— 本模块 :meth:`propose_world_setting`
    - ``CharacterDesigner`` —— 本模块 :meth:`propose_main_characters`
    - ``NovelDirector`` 的立项/骨架部分（synopsis/arcs/volume_breakdown）
* ``NovelDirector.generate_outline`` / ``generate_volume_outline`` /
  ``generate_story_arcs`` 保留为 legacy shim（大量测试/pipeline 依赖），在
  Phase 3 剥离。本模块的 :meth:`propose_story_arcs` 内部复用 NovelDirector
  的 arc 生成逻辑，避免重复 prompt。

数据流
------
::

    propose_project_setup(inspiration) -> ProjectSetupProposal
        .accept_into(meta_dict)  # 写 ProjectMeta
    propose_synopsis(meta) -> SynopsisProposal
        .accept_into(novel)       # 写 Novel.synopsis / main_storyline
    propose_main_characters(meta, synopsis) -> CharactersProposal
        .accept_into(novel)       # 写 Novel.characters
    propose_world_setting(meta, synopsis) -> WorldProposal
        .accept_into(novel)       # 写 Novel.world_setting
    propose_story_arcs(meta, synopsis, characters, world) -> ArcsProposal
        .accept_into(novel)       # 写 Novel.story_arcs
    propose_volume_breakdown(meta, synopsis, arcs?) -> VolumeBreakdownProposal
        .accept_into(novel)       # 写 Novel.outline.volumes
"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from src.novel.models.character import CharacterProfile
from src.novel.models.novel import Act, ChapterOutline, Outline, VolumeOutline
from src.novel.models.world import WorldSetting
from src.novel.services.character_service import CharacterService
from src.novel.services.world_service import WorldService
from src.novel.templates.outline_templates import get_template
from src.novel.utils.json_extract import extract_json_obj

log = logging.getLogger("novel.agents.project_architect")

MAX_RETRIES: int = 3

SectionName = Literal[
    "synopsis",
    "characters",
    "world",
    "arcs",
    "volume_breakdown",
]


# ---------------------------------------------------------------------------
# Proposal dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ProjectSetupProposal:
    """立项草案（ProjectMeta proposal）。

    Attributes:
        genre: 主题材（玄幻/悬疑/言情/…）。
        theme: 主题一句话描述。
        style_name: 风格预设键（如 ``webnovel.shuangwen``）。
        target_length_class: 长度等级（``short``/``novel``/``webnovel``/…）。
        target_words: 目标总字数。
        narrative_template: 叙事模板（``three_act`` / ``four_act`` / ``cyclic`` / …）。
        inspiration: 原始灵感文本。
        raw_llm_data: LLM 原始返回（调试/审计用）。
    """

    genre: str
    theme: str
    style_name: str
    target_length_class: str
    target_words: int
    narrative_template: str
    inspiration: str = ""
    raw_llm_data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "genre": self.genre,
            "theme": self.theme,
            "style_name": self.style_name,
            "target_length_class": self.target_length_class,
            "target_words": self.target_words,
            "narrative_template": self.narrative_template,
            "inspiration": self.inspiration,
        }

    def accept_into(self, meta: dict[str, Any]) -> dict[str, Any]:
        """Mutate a ProjectMeta-shape dict with the proposal fields (in place)."""
        meta.update(
            {
                "genre": self.genre,
                "theme": self.theme,
                "style_name": self.style_name,
                "target_length_class": self.target_length_class,
                "target_words": self.target_words,
                "narrative_template": self.narrative_template,
            }
        )
        return meta


@dataclass
class SynopsisProposal:
    """主线 synopsis 草案（3-5 句，保留结构化 main_storyline）。"""

    synopsis: str
    main_storyline: dict[str, Any] = field(default_factory=dict)
    raw_llm_data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "synopsis": self.synopsis,
            "main_storyline": dict(self.main_storyline),
        }

    def accept_into(self, novel: Any) -> Any:
        """Write synopsis + main_storyline into a Novel-ish object or dict."""
        if isinstance(novel, dict):
            novel["synopsis"] = self.synopsis
            outline = novel.setdefault("outline", {}) or {}
            if isinstance(outline, dict):
                outline["main_storyline"] = dict(self.main_storyline)
                novel["outline"] = outline
            novel["main_storyline"] = dict(self.main_storyline)
        else:
            setattr(novel, "synopsis", self.synopsis)
            outline = getattr(novel, "outline", None)
            if outline is not None and hasattr(outline, "main_storyline"):
                # Pydantic model path — direct assign
                try:
                    outline.main_storyline = dict(self.main_storyline)
                except Exception:  # pragma: no cover
                    pass
        return novel


@dataclass
class CharactersProposal:
    """主角 + 核心配角草案。"""

    characters: list[CharacterProfile] = field(default_factory=list)
    raw_llm_data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"characters": [c.model_dump() for c in self.characters]}

    def accept_into(self, novel: Any) -> Any:
        dumped = [c.model_dump() for c in self.characters]
        if isinstance(novel, dict):
            novel["characters"] = dumped
        else:
            setattr(novel, "characters", dumped)
        return novel


@dataclass
class WorldProposal:
    """世界观草案。"""

    world: WorldSetting
    raw_llm_data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"world_setting": self.world.model_dump()}

    def accept_into(self, novel: Any) -> Any:
        dumped = self.world.model_dump()
        if isinstance(novel, dict):
            novel["world_setting"] = dumped
        else:
            setattr(novel, "world_setting", dumped)
        return novel


@dataclass
class ArcsProposal:
    """跨卷大弧线草案。"""

    arcs: list[dict] = field(default_factory=list)
    raw_llm_data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"arcs": list(self.arcs)}

    def accept_into(self, novel: Any) -> Any:
        arcs_list = list(self.arcs)
        if isinstance(novel, dict):
            novel.setdefault("story_arcs", []).extend(arcs_list)
        else:
            existing = getattr(novel, "story_arcs", None) or []
            try:
                setattr(novel, "story_arcs", list(existing) + arcs_list)
            except Exception:  # pragma: no cover
                pass
        return novel


@dataclass
class MainOutlineProposal:
    """主干大纲草案（outline + style_bible + template/style 推断）。

    Phase 3-B2 产物：替代 ``novel_director_node`` 输出。pipeline 拿到本
    dataclass 后把字段直接写入 state，保留原有字段形状。
    """

    outline: dict[str, Any] = field(default_factory=dict)
    template: str = ""
    style_name: str = ""
    style_bible: dict[str, Any] | None = None
    total_chapters: int = 0
    decisions: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outline": self.outline,
            "template": self.template,
            "style_name": self.style_name,
            "style_bible": self.style_bible,
            "total_chapters": self.total_chapters,
        }

    def accept_into(self, novel: Any) -> Any:
        if isinstance(novel, dict):
            novel["outline"] = self.outline
            novel["template"] = self.template
            novel["style_name"] = self.style_name
            if self.style_bible is not None:
                novel["style_bible"] = self.style_bible
        return novel


@dataclass
class VolumeBreakdownProposal:
    """卷骨架草案（每卷一两句 — 不是单卷细纲！单卷细纲见 VolumeDirector）。"""

    volumes: list[dict] = field(default_factory=list)
    raw_llm_data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"volumes": list(self.volumes)}

    def accept_into(self, novel: Any) -> Any:
        vols = list(self.volumes)
        if isinstance(novel, dict):
            outline = novel.setdefault("outline", {}) or {}
            if isinstance(outline, dict):
                outline["volumes"] = vols
                novel["outline"] = outline
        else:
            outline = getattr(novel, "outline", None)
            if outline is not None:
                try:
                    outline.volumes = vols
                except Exception:  # pragma: no cover
                    pass
        return novel


# ---------------------------------------------------------------------------
# ProjectArchitect
# ---------------------------------------------------------------------------


_TARGET_LENGTH_CLASS_WORDS: dict[str, int] = {
    "short": 30_000,
    "novella": 80_000,
    "novel": 200_000,
    "webnovel": 500_000,
    "epic": 1_000_000,
}

_GENRE_DEFAULT_STYLE: dict[str, str] = {
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

_GENRE_DEFAULT_TEMPLATE: dict[str, str] = {
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

# Outline.template Literal → outline_templates.py 模板名映射
_TEMPLATE_ALIAS: dict[str, str] = {
    "four_act": "classic_four_act",
    "custom": "cyclic_upgrade",
}

# 大纲拆章用的默认常量（仅 ProjectArchitect 内部使用；generate_volume_outline
# 的 _CHAPTERS_PER_VOLUME 还在 novel_director，数字相同但各自独立）。
_OUTLINE_WORDS_PER_CHAPTER = 2500
_OUTLINE_CHAPTERS_PER_VOLUME = 30

# Prompt-leak 关键词 —— _parse_outline 做 title fallback 时的黑名单，
# 与 pipeline._sanitize_title 的 _BAD_PATTERNS 保持一致（手动同步，避免
# 反向 import 循环）。
_TITLE_BAD_PATTERNS = (
    "字数", "场景", "目标", "要求", "注意", "提示", "格式",
    "左右", "以上", "以下", "不超过", "大约",
)


def _derive_title_from_outline_fields(
    goal: Any, key_events: Any
) -> str | None:
    """Derive a 4-8 char chapter title from outline ``goal`` / ``key_events``.

    Pure local logic — 不调 LLM。命中 ``_TITLE_BAD_PATTERNS`` 返回 None。
    """

    def _from_phrase(phrase: str) -> str | None:
        if not phrase:
            return None
        head = re.split(r"[，,。.！!？?；;、]", phrase)[0].strip()
        head = head.strip("\"'\u201c\u201d\u300c\u300d\u300e\u300f")
        if len(head) > 12:
            head = head[:8]
        if len(head) < 2:
            return None
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


class ProjectArchitect:
    """立项 + 骨架架构师。每段独立 LLM 调用，作者可按段重生。

    与 :class:`~src.novel.agents.novel_director.NovelDirector` 的关系：
        * ``NovelDirector.generate_outline`` 是"一次性三层大纲"的 legacy
          shim，仍被 :func:`~src.novel.agents.novel_director.novel_director_node`
          + 老 pipeline 路径使用。
        * ``ProjectArchitect`` 是"分段 propose/accept"的新入口，pipeline 新路径
          通过它组装项目骨架。
        * ``propose_story_arcs`` 复用 ``NovelDirector.generate_story_arcs``，
          避免重复 prompt 实现（Phase 3 再拆）。
    """

    def __init__(self, llm: Any, config: Any | None = None) -> None:
        """
        Args:
            llm: LLMClient，实现 ``chat(messages, temperature, json_mode, max_tokens)``。
            config: 可选 NovelConfig（当前未使用，保留以兼容未来扩展）。
        """
        self.llm = llm
        self.config = config
        self._character_service = CharacterService(llm)
        self._world_service = WorldService(llm)

    # ==================================================================
    # 1. 立项 ProjectMeta
    # ==================================================================

    def propose_main_outline(
        self,
        genre: str,
        theme: str,
        target_words: int,
        template_name: str = "",
        style_name: str = "",
        custom_ideas: str | None = None,
    ) -> MainOutlineProposal:
        """生成主干大纲（三层 outline + style_bible）。

        Phase 3-B3：outline 生成已物理迁入本模块（``_generate_outline`` /
        ``_build_outline_prompt`` / ``_parse_outline``），不再依赖
        ``NovelDirector``。

        - 未指定 ``template_name`` 时按 genre 查 ``_GENRE_DEFAULT_TEMPLATE``。
        - 未指定 ``style_name`` 时按 genre 查 ``_GENRE_DEFAULT_STYLE``。
        - style_bible 生成失败不阻塞 outline 返回。
        """
        if not genre:
            raise ValueError(
                "genre 必须显式指定（Phase 0 架构重构：禁止默认回退到玄幻）"
            )

        decisions: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        resolved_template = (template_name or "").strip() or _GENRE_DEFAULT_TEMPLATE.get(
            genre, "cyclic_upgrade"
        )
        resolved_style = (style_name or "").strip() or _GENRE_DEFAULT_STYLE.get(
            genre, "webnovel.shuangwen"
        )

        # --- Outline 本体（Phase 3-B3：物理迁入本模块） ---
        outline = self._generate_outline(
            genre=genre,
            theme=theme,
            target_words=target_words,
            template_name=resolved_template,
            custom_ideas=custom_ideas,
        )
        outline_dict = outline.model_dump()
        total_chapters = len(outline.chapters)
        decisions.append({
            "agent": "ProjectArchitect",
            "step": "propose_main_outline",
            "decision": (
                f"大纲生成完成: {len(outline.acts)} 幕, "
                f"{len(outline.volumes)} 卷, {total_chapters} 章"
            ),
            "reason": "Phase 3-B2 propose_main_outline",
        })

        # --- Style Bible（可选，非阻塞） ---
        style_bible_data: dict[str, Any] | None = None
        try:
            from src.novel.services.style_bible_generator import StyleBibleGenerator

            bible_gen = StyleBibleGenerator(self.llm)
            bible = bible_gen.generate(
                genre=genre, theme=theme, style_name=resolved_style
            )
            style_bible_data = bible.model_dump()
            decisions.append({
                "agent": "ProjectArchitect",
                "step": "generate_style_bible",
                "decision": "风格圣经生成完成",
                "reason": f"基于风格预设 {resolved_style} 生成量化目标",
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("风格圣经生成失败（非阻塞）: %s", exc)
            errors.append({
                "agent": "ProjectArchitect",
                "message": f"风格圣经生成失败: {exc}",
            })

        return MainOutlineProposal(
            outline=outline_dict,
            template=resolved_template,
            style_name=resolved_style,
            style_bible=style_bible_data,
            total_chapters=total_chapters,
            decisions=decisions,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Outline 生成内部实现（Phase 3-B3 从 NovelDirector 物理迁入）
    # ------------------------------------------------------------------

    MAX_OUTLINE_RETRIES = 3

    def _generate_outline(
        self,
        genre: str,
        theme: str,
        target_words: int,
        template_name: str,
        custom_ideas: str | None = None,
    ) -> Outline:
        """通过 LLM 生成三层大纲。"""
        tpl_lookup = _TEMPLATE_ALIAS.get(template_name, template_name)
        try:
            tpl = get_template(tpl_lookup)
        except KeyError:
            tpl = get_template("cyclic_upgrade")
            template_name = "cyclic_upgrade"

        total_chapters = max(1, target_words // _OUTLINE_WORDS_PER_CHAPTER)
        volume_count = max(1, total_chapters // _OUTLINE_CHAPTERS_PER_VOLUME)
        chapters_per_volume = max(1, total_chapters // volume_count)

        is_long_novel = total_chapters > _OUTLINE_CHAPTERS_PER_VOLUME
        prompt_chapters = chapters_per_volume if is_long_novel else total_chapters

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

        return self._parse_outline(outline_data, template_name, prompt_chapters)

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
        """构建大纲生成的 LLM prompt（中文）。"""
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
        """将 LLM 返回的 JSON 解析为 Outline 模型。缺字段走兜底。"""
        acts: list[Act] = []
        for act_data in data.get("acts", []):
            try:
                acts.append(Act(**act_data))
            except Exception:
                log.warning("跳过无效 act 数据: %s", act_data)

        volumes: list[VolumeOutline] = []
        for vol_data in data.get("volumes", []):
            try:
                volumes.append(VolumeOutline(**vol_data))
            except Exception:
                log.warning("跳过无效 volume 数据: %s", vol_data)

        chapters: list[ChapterOutline] = []
        for ch_data in data.get("chapters", []):
            try:
                if "chapter_brief" not in ch_data or not isinstance(ch_data.get("chapter_brief"), dict):
                    ch_data["chapter_brief"] = {}
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

        chapters.sort(key=lambda c: c.chapter_number)

        if not acts:
            acts = [
                Act(
                    name="第一幕：开端",
                    description="故事铺垫与主角登场",
                    start_chapter=1,
                    end_chapter=total_chapters,
                )
            ]

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

        main_storyline = data.get("main_storyline") or {}
        if not isinstance(main_storyline, dict):
            main_storyline = {}

        return Outline(
            template=template_name,
            main_storyline=main_storyline,
            acts=acts,
            volumes=volumes,
            chapters=chapters,
        )

    def propose_project_setup(
        self,
        inspiration: str,
        hints: dict[str, Any] | None = None,
    ) -> ProjectSetupProposal:
        """从灵感/类型偏好/长度偏好生成 ProjectMeta 草案。

        Args:
            inspiration: 作者的灵感/想法原文。
            hints: 可选提示，可覆盖 LLM 推断：
                ``{"genre": "玄幻", "target_length_class": "webnovel",
                "target_words": 500000, "theme": "...", "style_name": "..."}``

        Returns:
            :class:`ProjectSetupProposal`。

        Raises:
            ValueError: ``inspiration`` 为空且 hints 未提供 genre。
        """
        hints = dict(hints or {})
        forced_genre = (hints.get("genre") or "").strip()
        forced_theme = (hints.get("theme") or "").strip()
        forced_length = (hints.get("target_length_class") or "").strip()
        forced_words = hints.get("target_words")
        forced_style = (hints.get("style_name") or "").strip()
        forced_template = (hints.get("narrative_template") or "").strip()

        # Short-circuit if user provides all fields (skip LLM)
        have_all = all(
            [
                forced_genre,
                forced_theme,
                forced_length or forced_words,
            ]
        )
        llm_data: dict[str, Any] | None = None

        if not have_all:
            if not inspiration and not forced_genre:
                raise ValueError(
                    "propose_project_setup 需要 inspiration 或 hints.genre 至少提供一个"
                )
            llm_data = self._call_llm_for_setup(inspiration, hints) or {}

        genre = forced_genre or (llm_data or {}).get("genre", "") or ""
        if not genre:
            raise ValueError(
                "LLM 未返回 genre 且 hints 也未指定（Phase 0 架构重构：零默认体裁）"
            )
        theme = forced_theme or (llm_data or {}).get("theme", "") or inspiration[:80]
        style_name = (
            forced_style
            or (llm_data or {}).get("style_name", "")
            or _GENRE_DEFAULT_STYLE.get(genre, "webnovel.shuangwen")
        )
        length_class = (
            forced_length
            or (llm_data or {}).get("target_length_class", "")
            or "novel"
        )
        target_words = (
            int(forced_words)
            if forced_words
            else int(
                (llm_data or {}).get("target_words", 0)
                or _TARGET_LENGTH_CLASS_WORDS.get(length_class, 200_000)
            )
        )
        template = (
            forced_template
            or (llm_data or {}).get("narrative_template", "")
            or _GENRE_DEFAULT_TEMPLATE.get(genre, "cyclic_upgrade")
        )

        return ProjectSetupProposal(
            genre=genre,
            theme=theme,
            style_name=style_name,
            target_length_class=length_class,
            target_words=target_words,
            narrative_template=template,
            inspiration=inspiration,
            raw_llm_data=llm_data,
        )

    def _call_llm_for_setup(
        self, inspiration: str, hints: dict[str, Any]
    ) -> dict | None:
        """Call LLM to propose ProjectMeta fields; returns dict or None on failure."""
        prompt = f"""请基于以下灵感，为作者规划一个小说项目的立项方案。

【作者灵感】
{inspiration or "（作者未提供具体灵感）"}

【作者偏好提示】
{hints if hints else "（无）"}

请严格按以下 JSON 格式返回（不要加多余说明）：
{{
  "genre": "主题材（如：玄幻/悬疑/言情/科幻/武侠/都市…）",
  "theme": "主题一句话（如：少年修炼逆天改命）",
  "style_name": "风格预设键（如：webnovel.shuangwen / wuxia.classical / literary.realism）",
  "target_length_class": "长度（short/novella/novel/webnovel/epic）",
  "target_words": 200000,
  "narrative_template": "叙事模板（three_act/four_act/cyclic_upgrade/multi_thread/scifi_crisis）"
}}

要求：
1. genre 必须是具体题材名（中文），不能留空
2. target_length_class 与 target_words 保持匹配：short≈30k, novella≈80k, novel≈200k, webnovel≈500k, epic≈1M
3. 如果作者灵感里已明确体裁/长度，严格沿用
"""
        for attempt in range(MAX_RETRIES):
            try:
                response = self.llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": "你是一位资深小说项目策划。严格按 JSON 返回立项方案。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.6,
                    json_mode=True,
                    max_tokens=1024,
                )
                data = extract_json_obj(response.content)
                if data:
                    return data
            except Exception as exc:  # pragma: no cover - network-ish
                log.warning("propose_project_setup LLM attempt %d failed: %s", attempt + 1, exc)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
        return None

    # ==================================================================
    # 2. 骨架 —— synopsis（主线一段话）
    # ==================================================================

    def propose_synopsis(self, meta: dict[str, Any]) -> SynopsisProposal:
        """生成 3-5 句主线 + 结构化 main_storyline。

        Args:
            meta: ProjectMeta dict，至少含 ``genre``/``theme``。

        Returns:
            :class:`SynopsisProposal`。

        Raises:
            ValueError: ``meta`` 缺少 genre。
        """
        self._require_genre(meta)
        genre = meta["genre"]
        theme = meta.get("theme", "")
        custom = meta.get("custom_ideas") or meta.get("inspiration") or ""

        prompt = f"""请为以下小说生成"主线故事骨架"（synopsis）：

题材：{genre}
主题：{theme}
{'作者额外灵感：' + custom if custom else ''}

请严格按以下 JSON 格式返回：
{{
  "synopsis": "3-5 句主线总括（不是简介，是故事骨架）",
  "main_storyline": {{
    "protagonist": "主角姓名（如未定，用一个符合题材的人名）",
    "protagonist_goal": "主角的核心目标/欲望",
    "core_conflict": "主角实现目标的最大障碍",
    "character_arc": "主角从什么状态变成什么状态（内在成长）",
    "stakes": "如果主角失败会怎样",
    "theme_statement": "故事想传达的核心主题（一句话）"
  }}
}}

要求：
1. synopsis 聚焦主线三要素：目标→障碍→变化
2. 不要花哨修辞，写给策划读的骨架
3. protagonist 必须是具体人名
"""
        data = self._retry_json_chat(
            system="你是一位资深小说策划编辑。严格按 JSON 返回主线骨架。",
            prompt=prompt,
            temperature=0.7,
            max_tokens=1024,
        )
        if not data:
            return SynopsisProposal(synopsis="", main_storyline={}, raw_llm_data=None)

        synopsis = str(data.get("synopsis", "")).strip()
        main_storyline = data.get("main_storyline") or {}
        if not isinstance(main_storyline, dict):
            main_storyline = {}
        return SynopsisProposal(
            synopsis=synopsis,
            main_storyline=main_storyline,
            raw_llm_data=data,
        )

    # ==================================================================
    # 3. 骨架 —— 主角 + 核心配角
    # ==================================================================

    def propose_main_characters(
        self,
        meta: dict[str, Any],
        synopsis: str = "",
    ) -> CharactersProposal:
        """从 meta + synopsis 提取主角 + 核心配角档案。

        直接复用 :class:`~src.novel.services.character_service.CharacterService`
        的 ``extract_characters`` + ``generate_profile``。

        Args:
            meta: 至少含 ``genre``/``theme``。
            synopsis: 可选 —— 用于上下文丰富 prompt。

        Returns:
            :class:`CharactersProposal`。
        """
        self._require_genre(meta)
        genre = meta["genre"]
        theme = meta.get("theme", "")
        outline_summary = synopsis.strip() or (
            f"题材：{genre}；主题：{theme}".strip("；")
        )
        try:
            raw = self._character_service.extract_characters(outline_summary, genre)
        except Exception as exc:
            log.warning("propose_main_characters extract failed: %s", exc)
            raw = []

        profiles: list[CharacterProfile] = []
        for ch_info in raw:
            name = ch_info.get("name", "") if isinstance(ch_info, dict) else ""
            role = ch_info.get("role", "配角") if isinstance(ch_info, dict) else "配角"
            if not name:
                continue
            try:
                profile = self._character_service.generate_profile(
                    name=name,
                    role=role,
                    genre=genre,
                    outline_context=outline_summary,
                )
                profiles.append(profile)
            except Exception as exc:
                log.warning("角色 %s 档案生成失败: %s", name, exc)

        return CharactersProposal(characters=profiles, raw_llm_data={"raw": raw})

    # ==================================================================
    # 4. 骨架 —— 世界观
    # ==================================================================

    def propose_world_setting(
        self,
        meta: dict[str, Any],
        synopsis: str = "",
    ) -> WorldProposal:
        """生成世界观（时代/地点/术语/规则 + 力量体系）。

        复用 :class:`~src.novel.services.world_service.WorldService`。

        Args:
            meta: 至少含 ``genre``。
            synopsis: 可选 —— 世界观生成的大纲摘要。

        Returns:
            :class:`WorldProposal`。
        """
        self._require_genre(meta)
        genre = meta["genre"]
        theme = meta.get("theme", "")
        summary = synopsis.strip() or f"题材：{genre}；主题：{theme}".strip("；")

        world = self._world_service.create_world_setting(genre, summary)
        try:
            power = self._world_service.define_power_system(
                genre, f"{world.era} - {world.location}"
            )
            if power is not None:
                world.power_system = power
        except Exception as exc:
            log.warning("力量体系生成失败（非致命）: %s", exc)

        return WorldProposal(world=world, raw_llm_data=world.model_dump())

    # ==================================================================
    # 5. 骨架 —— 跨卷大弧线（可选）
    # ==================================================================

    def propose_story_arcs(
        self,
        meta: dict[str, Any],
        synopsis: str,
        characters: list[Any] | None = None,
        world: dict | None = None,
    ) -> ArcsProposal:
        """生成跨卷大弧线。

        Phase 3-B1：arc 生成实现从 :class:`NovelDirector` 物理迁入本模块，
        :meth:`_generate_story_arcs` / :meth:`_distribute_chapters_to_arcs`
        / :meth:`_generate_single_arc`。NovelDirector 不再参与该路径。

        Args:
            meta: 至少含 ``genre``；可含 ``outline``。
            synopsis: 主线文本。
            characters: 主要角色列表（可选，当前未直接使用但保留接口位）。
            world: 世界观 dict（可选）。

        Returns:
            :class:`ArcsProposal`。
        """
        self._require_genre(meta)
        genre = meta["genre"]

        outline = meta.get("outline") or {}
        chapters = outline.get("chapters", []) if isinstance(outline, dict) else []
        if not chapters:
            log.info("propose_story_arcs: meta 无 outline.chapters，跳过（稍后补）")
            return ArcsProposal(arcs=[], raw_llm_data=None)

        try:
            arcs = self._generate_story_arcs(
                volume_outline=outline,
                chapter_outlines=chapters,
                genre=genre,
            )
        except Exception as exc:
            log.warning("propose_story_arcs 生成失败（非致命）: %s", exc)
            arcs = []

        return ArcsProposal(arcs=list(arcs or []), raw_llm_data={"count": len(arcs or [])})

    # ==================================================================
    # Story Arc 生成实现（Phase 3-B1：从 NovelDirector 物理迁入）
    # ==================================================================

    def _generate_story_arcs(
        self,
        volume_outline: Any,
        chapter_outlines: list[Any],
        genre: str,
    ) -> list[dict]:
        """为指定卷生成故事弧线（StoryUnit 兼容 dict 列表）。

        章节按 ~5 章/弧线分组，每组独立调一次 LLM 产 name/hook/closure/
        residual_question。分组与关键点位纯算法，LLM 只做命名 + 钩子。
        """
        if isinstance(volume_outline, dict):
            raw_chapters = volume_outline.get("chapters") or []
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
            chapters = getattr(volume_outline, "chapters", [])
            volume_id = getattr(volume_outline, "volume_number", 1)
            core_conflict = getattr(volume_outline, "core_conflict", "")

        if not chapters:
            return []

        arc_count = max(1, math.ceil(len(chapters) / 5))
        arc_chapter_groups = self._distribute_chapters_to_arcs(chapters, arc_count)

        ch_outline_map: dict[int, dict] = {}
        for co in chapter_outlines:
            if isinstance(co, dict):
                ch_outline_map[co.get("chapter_number", 0)] = co
            else:
                ch_outline_map[co.chapter_number] = (
                    co.model_dump()
                    if hasattr(co, "model_dump")
                    else {
                        "chapter_number": co.chapter_number,
                        "title": getattr(co, "title", ""),
                        "goal": getattr(co, "goal", ""),
                    }
                )

        arcs: list[dict] = []
        for i, arc_chapters in enumerate(arc_chapter_groups):
            arc_id = f"arc_{volume_id}_{i + 1}"
            arc_ch_outlines = [
                ch_outline_map.get(
                    ch_num,
                    {"chapter_number": ch_num, "title": f"第{ch_num}章", "goal": "待规划"},
                )
                for ch_num in arc_chapters
            ]
            arc_data = self._generate_single_arc(
                arc_chapters=arc_chapters,
                arc_chapter_outlines=arc_ch_outlines,
                arc_number=i + 1,
                arc_id=arc_id,
                genre=genre,
                volume_id=volume_id,
                core_conflict=core_conflict,
            )
            arcs.append(arc_data)

        log.info("卷%d弧线生成完成: %d个弧线", volume_id, len(arcs))
        return arcs

    @staticmethod
    def _distribute_chapters_to_arcs(
        chapters: list[int], arc_count: int
    ) -> list[list[int]]:
        """均匀分配章节到弧线，每弧线 clamp 到 3-7 章。"""
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
            size = max(3, min(7, size))
            group = sorted_chapters[idx : idx + size]
            if group:
                groups.append(group)
            idx += size
            if idx >= total:
                break

        if idx < total and groups:
            groups[-1].extend(sorted_chapters[idx:])
            if len(groups[-1]) > 7:
                overflow = groups[-1][7:]
                groups[-1] = groups[-1][:7]
                groups.append(overflow)

        return groups

    def _generate_single_arc(
        self,
        arc_chapters: list[int],
        arc_chapter_outlines: list[dict],
        arc_number: int,
        arc_id: str,
        genre: str,
        volume_id: int,
        core_conflict: str,
    ) -> dict:
        """通过 LLM 生成单个弧线的 name/hook/closure/residual_question。"""
        ch_summaries = []
        for co in arc_chapter_outlines:
            ch_num = co.get("chapter_number", "?")
            title = co.get("title", "")
            goal = co.get("goal", "")
            ch_summaries.append(f"  第{ch_num}章「{title}」：{goal}")
        chapters_text = "\n".join(ch_summaries)

        escalation_idx = max(0, int(len(arc_chapters) * 0.6) - 1)
        turning_idx = max(0, int(len(arc_chapters) * 0.75) - 1)
        escalation_ch = arc_chapters[min(escalation_idx, len(arc_chapters) - 1)]
        turning_ch = arc_chapters[min(turning_idx, len(arc_chapters) - 1)]

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

    # ==================================================================
    # 6. 骨架 —— 卷骨架（全书 N 卷，每卷一两句）
    # ==================================================================

    def propose_volume_breakdown(
        self,
        meta: dict[str, Any],
        synopsis: str,
        arcs: list[dict] | None = None,
    ) -> VolumeBreakdownProposal:
        """生成全书的卷划分骨架（不是单卷细纲！）。

        每卷只包含 ``volume_number`` / ``title`` / ``core_conflict`` /
        ``resolution`` 几个字段。单卷 N 章细纲由
        :class:`~src.novel.agents.volume_director.VolumeDirector.propose_volume_outline`
        进卷时生成。

        Args:
            meta: 至少含 ``genre``/``target_length_class`` 或 ``target_words``。
            synopsis: 主线文本。
            arcs: 可选的大弧线列表，供 prompt 参考。

        Returns:
            :class:`VolumeBreakdownProposal`。
        """
        self._require_genre(meta)
        genre = meta["genre"]
        theme = meta.get("theme", "")
        target_words = int(
            meta.get("target_words", 0)
            or _TARGET_LENGTH_CLASS_WORDS.get(meta.get("target_length_class", "novel"), 200_000)
        )
        # 粗估卷数：每卷约 2.5 万字（和 NovelDirector 的 _CHAPTERS_PER_VOLUME*_WORDS_PER_CHAPTER 对齐）
        approx_volumes = max(1, target_words // 75_000)
        arcs_text = (
            "\n".join(f"- {a.get('name', '?')}: {a.get('hook', '')}" for a in (arcs or []))
            if arcs
            else "（无）"
        )

        prompt = f"""请为以下小说生成"全书卷骨架"（每卷一两句，**不是每卷N章细纲**）。

题材：{genre}
主题：{theme}
目标总字数：{target_words}
推荐卷数：{approx_volumes}

【主线摘要】
{synopsis or '（未提供）'}

【大弧线】
{arcs_text}

请严格按以下 JSON 返回：
{{
  "volumes": [
    {{
      "volume_number": 1,
      "title": "卷名（4-8字）",
      "core_conflict": "本卷核心矛盾（一句话）",
      "resolution": "本卷如何收束（一句话）"
    }}
  ]
}}

要求：
1. volumes 数量 ≈ {approx_volumes}，允许 ±1
2. 每卷 core_conflict 必须不同，逐卷推进主线
3. 最后一卷 resolution 需呼应主角最终目标
4. 不要填 chapters 字段（章节号在进卷时由 VolumeDirector 规划）
"""
        data = self._retry_json_chat(
            system="你是一位资深小说策划编辑。严格按 JSON 返回卷骨架。",
            prompt=prompt,
            temperature=0.7,
            max_tokens=2048,
        )
        if not data:
            return VolumeBreakdownProposal(volumes=[], raw_llm_data=None)

        raw_vols = data.get("volumes", []) or []
        cleaned: list[dict] = []
        for i, vol in enumerate(raw_vols, 1):
            if not isinstance(vol, dict):
                continue
            cleaned.append(
                {
                    "volume_number": int(vol.get("volume_number", i) or i),
                    "title": str(vol.get("title", f"第{i}卷")).strip() or f"第{i}卷",
                    "core_conflict": str(vol.get("core_conflict", "")).strip(),
                    "resolution": str(vol.get("resolution", "")).strip(),
                }
            )
        return VolumeBreakdownProposal(volumes=cleaned, raw_llm_data=data)

    # ==================================================================
    # 7. 重生成调度
    # ==================================================================

    def regenerate_section(
        self,
        section: SectionName,
        current_spine: dict[str, Any],
        hints: str = "",
    ) -> Any:
        """某段不满意时按 hints 重生。

        Args:
            section: ``synopsis`` / ``characters`` / ``world`` / ``arcs`` /
                ``volume_breakdown`` 之一。
            current_spine: 当前 spine dict（含 ``meta``/``synopsis``/
                ``characters``/``world``/``arcs`` 子键；字段缺失时用 {}）。
            hints: 作者对 "哪里不满意/想要什么" 的自然语言提示。

        Returns:
            对应的 ``*Proposal`` 实例。

        Raises:
            ValueError: 未知 section 名。
        """
        meta = dict(current_spine.get("meta", {}) or {})
        # 把 hints 注入 meta，各 propose_* 的 prompt 会读到
        if hints:
            existing = meta.get("custom_ideas", "") or ""
            meta["custom_ideas"] = (existing + ("\n" if existing else "") + f"作者补充：{hints}").strip()

        synopsis = str(current_spine.get("synopsis", "") or "")

        if section == "synopsis":
            return self.propose_synopsis(meta)
        if section == "characters":
            return self.propose_main_characters(meta, synopsis)
        if section == "world":
            return self.propose_world_setting(meta, synopsis)
        if section == "arcs":
            return self.propose_story_arcs(
                meta,
                synopsis,
                characters=current_spine.get("characters"),
                world=current_spine.get("world"),
            )
        if section == "volume_breakdown":
            return self.propose_volume_breakdown(
                meta, synopsis, arcs=current_spine.get("arcs")
            )
        raise ValueError(f"未知 section: {section!r}")

    # ==================================================================
    # 内部工具
    # ==================================================================

    @staticmethod
    def _require_genre(meta: dict[str, Any]) -> None:
        if not meta or not meta.get("genre"):
            raise ValueError(
                "meta 缺少 genre 字段（Phase 0 架构重构：零默认体裁）"
            )

    def _retry_json_chat(
        self,
        system: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> dict | None:
        """Call self.llm.chat with JSON mode + retries, returns dict or None."""
        last_error = ""
        for attempt in range(MAX_RETRIES):
            try:
                response = self.llm.chat(
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    json_mode=True,
                    max_tokens=max_tokens,
                )
                data = extract_json_obj(response.content)
                if data is not None:
                    return data
                last_error = f"LLM 返回非 JSON: {response.content[:200]}"
            except Exception as exc:
                last_error = f"LLM 调用异常: {exc}"
                log.warning("ProjectArchitect LLM attempt %d failed: %s", attempt + 1, exc)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
        log.warning("ProjectArchitect LLM 连续 %d 次失败: %s", MAX_RETRIES, last_error)
        return None
