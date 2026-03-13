"""Writer Agent - 章节正文生成

负责根据场景计划、角色档案、世界观设定和上下文，
逐场景生成章节正文，并支持基于反馈的重写。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.llm.llm_client import LLMClient, create_llm_client
from src.novel.models.chapter import Chapter, Scene
from src.novel.models.character import CharacterProfile
from src.novel.models.novel import ChapterOutline
from src.novel.models.world import WorldSetting
from src.novel.templates.style_presets import get_style
from src.novel.utils import count_words, truncate_text

log = logging.getLogger("novel")

# ---------------------------------------------------------------------------
# 反 AI 味指令（写入每个 scene prompt）
# ---------------------------------------------------------------------------

_ANTI_AI_FLAVOR = (
    "【重要】以下短语和写法是典型 AI 生成痕迹，必须完全避免：\n"
    "- 禁止使用：内心翻涌、莫名的力量、不由得、深深的、满满的、"
    "说实话、老实说、竟然（过度使用）、一股莫名的、仿佛、宛如（过度使用）\n"
    "- 禁止空洞抒情和无意义排比\n"
    "- 禁止所有角色说话语气雷同\n"
    "- 用具体动作和细节代替抽象形容\n"
    "- 对话要符合角色性格和身份，不同角色说话方式必须有区别\n"
)

# ---------------------------------------------------------------------------
# 上下文最大字符数
# ---------------------------------------------------------------------------

_MAX_CONTEXT_CHARS = 2000


# ---------------------------------------------------------------------------
# Writer 类
# ---------------------------------------------------------------------------


class Writer:
    """写手 Agent - 正文生成"""

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    # ------------------------------------------------------------------
    # 场景生成
    # ------------------------------------------------------------------

    def generate_scene(
        self,
        scene_plan: dict[str, Any],
        chapter_outline: ChapterOutline,
        characters: list[CharacterProfile],
        world_setting: WorldSetting,
        context: str,
        style_name: str,
    ) -> Scene:
        """生成单个场景正文。"""
        char_desc = self._build_character_description(characters)
        world_desc = self._build_world_description(world_setting)
        style = self._get_style_prompt(style_name)
        trimmed_context = truncate_text(context, _MAX_CONTEXT_CHARS) if context else ""
        target_words = scene_plan.get("target_words", 800)

        system_prompt = (
            f"{style}\n\n"
            f"你是一位专业小说写手，正在创作第{chapter_outline.chapter_number}章"
            f"「{chapter_outline.title}」中的第{scene_plan.get('scene_number', 1)}个场景。\n"
            f"本章目标：{chapter_outline.goal}\n"
            f"本章情绪基调：{chapter_outline.mood}\n\n"
            f"【极其重要的字数限制】你必须严格控制输出在{target_words}字左右。"
            f"绝对不能超过{target_words + 200}字。宁可写少也不要写多。"
            f"写到接近目标字数时，必须在一个完整的句子处自然收束，不要强行展开新情节。\n\n"
            f"【世界观设定】\n{world_desc}\n\n"
            f"【角色档案】\n{char_desc}\n\n"
            f"{_ANTI_AI_FLAVOR}"
        )

        user_prompt = (
            f"【场景信息】\n"
            f"- 地点：{scene_plan.get('location', '未指定')}\n"
            f"- 时间：{scene_plan.get('time', '未指定')}\n"
            f"- 出场角色：{', '.join(scene_plan.get('characters_involved', scene_plan.get('characters', [])))}\n"
            f"- 场景目标：{scene_plan.get('goal', scene_plan.get('summary', '未指定'))}\n"
            f"- 情绪氛围：{scene_plan.get('mood', chapter_outline.mood)}\n"
            f"- 目标字数：约{target_words}字\n\n"
        )

        if trimmed_context:
            user_prompt += f"【前文回顾】\n{trimmed_context}\n\n"

        user_prompt += (
            f"请直接输出场景正文，不要输出标题、序号或任何元信息。\n"
            f"【字数要求 - 必须遵守】\n"
            f"- 目标字数：{target_words}字（允许范围：{max(target_words - 200, 300)}-{target_words + 200}字）\n"
            f"- 超过{target_words + 200}字的内容会被强制截断导致情节不完整，你必须自行控制节奏\n"
            f"- 写到{target_words - 100}字左右时开始收束当前场景，在完整的句子处结束\n"
            f"- 宁可少写50字，也不要超出上限"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # 用 max_tokens 硬限制输出长度
        # DeepSeek/GPT 对中文 tokenizer 效率高：1 中文字 ≈ 0.6~1.0 token
        # 用 1.0 作为保守换算，确保 max_tokens 真正约束输出长度
        max_tokens = min(2048, target_words + 200)
        response = self.llm.chat(messages, temperature=0.85, max_tokens=max_tokens)
        scene_text = response.content.strip()

        # 安全截断：仅在严重超标（1.5 倍）时触发，优先在段落/句子边界截断
        hard_limit = int(target_words * 1.5)
        if len(scene_text) > hard_limit:
            # 优先找段落边界（\n\n）
            cut_pos = scene_text.rfind("\n\n", 0, hard_limit)
            if cut_pos > hard_limit // 2:
                scene_text = scene_text[:cut_pos]
            else:
                # 其次找句子边界（。！？）
                for sep in ("。", "！", "？", "!", "?", "\n"):
                    cut_pos = scene_text.rfind(sep, 0, hard_limit)
                    if cut_pos > hard_limit // 2:
                        scene_text = scene_text[: cut_pos + 1]
                        break
                else:
                    # 最后兜底：硬截断（极少触发）
                    scene_text = scene_text[:hard_limit]
            log.warning("场景文本超长(%d字)，截断至%d字", len(response.content), len(scene_text))

        scene_chars = scene_plan.get("characters_involved", scene_plan.get("characters", []))
        return Scene(
            scene_number=scene_plan.get("scene_number", 1),
            location=scene_plan.get("location", "未指定"),
            time=scene_plan.get("time", "未指定"),
            characters=scene_chars if scene_chars else ["unknown"],
            goal=scene_plan.get("goal", scene_plan.get("summary", "未指定")),
            text=scene_text,
            word_count=count_words(scene_text),
            narrative_modes=scene_plan.get("narrative_modes", []),
        )

    # ------------------------------------------------------------------
    # 章节生成（顺序生成多个场景）
    # ------------------------------------------------------------------

    def generate_chapter(
        self,
        chapter_outline: ChapterOutline,
        scene_plans: list[dict[str, Any]],
        characters: list[CharacterProfile],
        world_setting: WorldSetting,
        context: str,
        style_name: str,
    ) -> Chapter:
        """生成完整章节（逐场景生成，滑动窗口传递上下文）。"""
        scenes: list[Scene] = []
        running_context = context or ""

        for plan in scene_plans:
            scene = self.generate_scene(
                scene_plan=plan,
                chapter_outline=chapter_outline,
                characters=characters,
                world_setting=world_setting,
                context=running_context,
                style_name=style_name,
            )
            scenes.append(scene)

            running_context = truncate_text(
                running_context + "\n" + scene.text,
                _MAX_CONTEXT_CHARS,
            )

        full_text = "\n\n".join(s.text for s in scenes)
        total_words = count_words(full_text)

        return Chapter(
            chapter_number=chapter_outline.chapter_number,
            title=chapter_outline.title,
            scenes=scenes,
            full_text=full_text,
            word_count=total_words,
            outline=chapter_outline,
            status="draft",
        )

    # ------------------------------------------------------------------
    # 场景重写
    # ------------------------------------------------------------------

    def rewrite_scene(
        self,
        scene: Scene,
        feedback: str,
        style_name: str,
    ) -> Scene:
        """根据质量反馈重写场景。"""
        style = self._get_style_prompt(style_name)

        system_prompt = (
            f"{style}\n\n"
            f"你是一位专业小说写手，需要根据反馈意见重写以下场景。\n\n"
            f"{_ANTI_AI_FLAVOR}"
        )

        user_prompt = (
            f"【原始场景】\n{scene.text}\n\n"
            f"【反馈意见】\n{feedback}\n\n"
            f"请根据反馈意见重写此场景，保持场景的基本设定（地点、时间、角色、目标）不变，"
            f"改进文笔质量。直接输出重写后的正文，不要输出标题或元信息。"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = self.llm.chat(messages, temperature=0.85)
        rewritten_text = response.content.strip()

        return Scene(
            scene_number=scene.scene_number,
            location=scene.location,
            time=scene.time,
            characters=scene.characters,
            goal=scene.goal,
            text=rewritten_text,
            word_count=count_words(rewritten_text),
            narrative_modes=scene.narrative_modes,
        )

    # ------------------------------------------------------------------
    # 章节重写
    # ------------------------------------------------------------------

    def rewrite_chapter(
        self,
        original_text: str,
        rewrite_instruction: str,
        chapter_outline: ChapterOutline,
        characters: list[CharacterProfile],
        world_setting: WorldSetting,
        context: str,
        style_name: str,
        is_propagation: bool = False,
    ) -> str:
        """根据反馈指令重写整章。

        Args:
            original_text: 原始章节文本
            rewrite_instruction: 具体重写指令
            chapter_outline: 章节大纲
            characters: 角色列表
            world_setting: 世界观
            context: 前文上下文
            style_name: 风格名
            is_propagation: 是否为传播调整（True=轻量修改）

        Returns:
            重写后的章节文本
        """
        char_desc = self._build_character_description(characters)
        style = self._get_style_prompt(style_name)
        trimmed_context = truncate_text(context, _MAX_CONTEXT_CHARS) if context else ""
        # Compress original text to save tokens
        original_summary = truncate_text(original_text, 2000)
        target_words = chapter_outline.estimated_words

        if is_propagation:
            system_prompt = (
                f"{style}\n\n"
                f"你是一位专业小说写手。前面的章节做了修改，你需要微调当前章节以保持一致性。\n"
                f"只做必要的最小修改，保持原文风格和节奏。\n\n"
                f"{_ANTI_AI_FLAVOR}"
            )
            user_prompt = (
                f"【第{chapter_outline.chapter_number}章「{chapter_outline.title}」原文】\n"
                f"{original_summary}\n\n"
                f"【需要调整的原因】\n{rewrite_instruction}\n\n"
            )
            if trimmed_context:
                user_prompt += f"【修改后的前文】\n{trimmed_context}\n\n"
            user_prompt += (
                f"请在原文基础上做最小必要修改，保持连贯。直接输出修改后的完整章节正文。\n"
                f"【字数要求 - 必须遵守】\n"
                f"- 目标字数：{target_words}字（允许范围：{max(target_words - 300, 500)}-{target_words + 300}字）\n"
                f"- 写到接近目标字数时在完整句子处自然收束，宁少勿多"
            )
        else:
            system_prompt = (
                f"{style}\n\n"
                f"你是一位专业小说写手，正在根据读者反馈重写第{chapter_outline.chapter_number}章"
                f"「{chapter_outline.title}」。\n"
                f"本章目标：{chapter_outline.goal}\n"
                f"本章情绪基调：{chapter_outline.mood}\n\n"
                f"【角色档案】\n{char_desc}\n\n"
                f"{_ANTI_AI_FLAVOR}"
            )
            user_prompt = (
                f"【原文摘要】\n{original_summary}\n\n"
                f"【读者反馈/修改指令】\n{rewrite_instruction}\n\n"
            )
            if trimmed_context:
                user_prompt += f"【前文回顾】\n{trimmed_context}\n\n"
            user_prompt += (
                f"请根据修改指令重写此章节。直接输出重写后的完整正文，不要标题或元信息。\n"
                f"【字数要求 - 必须遵守】\n"
                f"- 目标字数：{target_words}字（允许范围：{max(target_words - 300, 500)}-{target_words + 300}字）\n"
                f"- 写到接近目标字数时在完整句子处自然收束，宁少勿多"
            )

        # 1 中文字 ≈ 0.6~1.0 token，用 1.0 保守换算
        max_tokens = min(2048, target_words + 300)
        response = self.llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=max_tokens,
        )

        rewritten = response.content.strip()

        # 安全截断：仅在严重超标时触发，优先在段落/句子边界截断
        hard_limit = int(target_words * 1.5)
        if len(rewritten) > hard_limit:
            cut_pos = rewritten.rfind("\n\n", 0, hard_limit)
            if cut_pos > hard_limit // 2:
                rewritten = rewritten[:cut_pos]
            else:
                for sep in ("。", "！", "？", "!", "?", "\n"):
                    cut_pos = rewritten.rfind(sep, 0, hard_limit)
                    if cut_pos > hard_limit // 2:
                        rewritten = rewritten[: cut_pos + 1]
                        break
                else:
                    rewritten = rewritten[:hard_limit]
            log.warning("重写文本超长(%d字)，截断至%d字", len(response.content), len(rewritten))

        return rewritten

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _build_character_description(
        self, characters: list[CharacterProfile]
    ) -> str:
        if not characters:
            return "（无指定角色）"

        parts: list[str] = []
        for c in characters:
            traits = "、".join(c.personality.traits) if c.personality.traits else "未知"
            speech = c.personality.speech_style
            desc = (
                f"- {c.name}（{c.gender}，{c.age}岁，{c.occupation}）\n"
                f"  性格：{traits}\n"
                f"  说话风格：{speech}\n"
                f"  核心信念：{c.personality.core_belief}\n"
                f"  缺陷：{c.personality.flaw}"
            )
            if c.personality.catchphrases:
                desc += f"\n  口头禅：{'、'.join(c.personality.catchphrases)}"
            parts.append(desc)

        return "\n".join(parts)

    def _build_world_description(self, world_setting: WorldSetting) -> str:
        parts = [
            f"时代背景：{world_setting.era}",
            f"地域设定：{world_setting.location}",
        ]

        if world_setting.power_system:
            levels = ", ".join(
                lv.name for lv in world_setting.power_system.levels
            )
            parts.append(f"力量体系：{world_setting.power_system.name}（{levels}）")

        if world_setting.rules:
            parts.append("世界规则：" + "；".join(world_setting.rules))

        if world_setting.terms:
            term_list = [f"{k}={v}" for k, v in list(world_setting.terms.items())[:10]]
            parts.append("专有名词：" + "、".join(term_list))

        return "\n".join(parts)

    def _get_style_prompt(self, style_name: str) -> str:
        try:
            preset = get_style(style_name)
            prompt = preset.get("system_prompt", "")
            examples = preset.get("few_shot_examples", [])
            if examples:
                prompt += "\n\n【风格示例】\n" + "\n---\n".join(examples[:2])
            return prompt
        except KeyError:
            log.warning("未知风格预设 '%s'，使用默认写作指令", style_name)
            return "你是一位专业的小说作家，文笔流畅，善于刻画人物和营造氛围。"


# ---------------------------------------------------------------------------
# LangGraph 节点函数
# ---------------------------------------------------------------------------


def writer_node(state: dict) -> dict:
    """LangGraph 节点函数。

    从 state 中读取当前章节计划，调用 Writer 生成章节正文。
    """
    decisions: list[dict] = []
    errors: list[dict] = []

    # 创建 LLM 客户端
    llm_config = state.get("config", {}).get("llm", {})
    try:
        llm = create_llm_client(llm_config)
    except Exception as exc:
        return {
            "errors": [{"agent": "Writer", "message": f"LLM 初始化失败: {exc}"}],
            "completed_nodes": ["writer"],
        }

    writer = Writer(llm)

    current_chapter = state.get("current_chapter", 1)
    scene_plans = state.get("current_scenes") or []
    style_name = state.get("style_name", "webnovel.shuangwen")

    # 从 state 中恢复 ChapterOutline
    ch_outline_data = state.get("current_chapter_outline")
    if not ch_outline_data:
        return {
            "errors": [{"agent": "Writer", "message": "当前章节大纲不存在"}],
            "completed_nodes": ["writer"],
        }

    try:
        chapter_outline = ChapterOutline(**ch_outline_data) if isinstance(ch_outline_data, dict) else ch_outline_data
    except Exception as exc:
        return {
            "errors": [{"agent": "Writer", "message": f"章节大纲解析失败: {exc}"}],
            "completed_nodes": ["writer"],
        }

    # 恢复角色和世界观
    characters = []
    for c_data in state.get("characters", []):
        try:
            characters.append(CharacterProfile(**c_data) if isinstance(c_data, dict) else c_data)
        except Exception:
            pass

    world_data = state.get("world_setting")
    world_setting = None
    if world_data:
        try:
            world_setting = WorldSetting(**world_data) if isinstance(world_data, dict) else world_data
        except Exception:
            pass

    if world_setting is None:
        world_setting = WorldSetting(era="未知", location="未知")

    # 前文上下文：取最后一章的结尾部分（而非开头），确保悬念和转折传递给下一章
    context = ""
    chapters_done = state.get("chapters", [])
    if chapters_done:
        last_ch = chapters_done[-1]
        last_text = last_ch.get("full_text", "")
        if last_text:
            # 取结尾 _MAX_CONTEXT_CHARS 字符，在段落边界截断
            if len(last_text) > _MAX_CONTEXT_CHARS:
                tail = last_text[-_MAX_CONTEXT_CHARS:]
                # 找到第一个段落边界，避免从半个段落开始
                first_break = tail.find("\n\n")
                if first_break > 0 and first_break < len(tail) // 3:
                    tail = tail[first_break + 2:]
                context = tail
            else:
                context = last_text

    # 如果没有 scene_plans，生成默认 4 场景
    if not scene_plans:
        scene_plans = [
            {"scene_number": i + 1, "target_words": chapter_outline.estimated_words // 3}
            for i in range(3)
        ]

    try:
        chapter = writer.generate_chapter(
            chapter_outline=chapter_outline,
            scene_plans=scene_plans,
            characters=characters,
            world_setting=world_setting,
            context=context,
            style_name=style_name,
        )

        decisions.append({
            "agent": "Writer",
            "step": "generate_chapter",
            "decision": f"生成第{current_chapter}章完成",
            "reason": f"共{len(chapter.scenes)}个场景，总字数{chapter.word_count}",
            "data": {
                "chapter_number": current_chapter,
                "scene_count": len(chapter.scenes),
                "word_count": chapter.word_count,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return {
            "current_chapter_text": chapter.full_text,
            "current_scenes": [s.model_dump() for s in chapter.scenes],
            "decisions": decisions,
            "errors": errors,
            "completed_nodes": ["writer"],
        }

    except Exception as exc:
        log.error("Writer 章节生成失败: %s", exc)
        return {
            "errors": [{"agent": "Writer", "message": f"章节生成失败: {exc}"}],
            "decisions": [{
                "agent": "Writer",
                "step": "generate_chapter",
                "decision": "章节生成失败",
                "reason": str(exc),
                "data": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }],
            "completed_nodes": ["writer"],
        }
