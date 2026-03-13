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

_ANTI_REPETITION = (
    "【反重复规则 — 严格遵守】\n"
    "1. 禁止重复前文已经出现过的场景、事件或描写。如果前文已经写过导弹攻击，不要再写一次类似场景\n"
    "2. 禁止在不同章节中重复使用同一个比喻或意象。一个比喻全书只能用一次\n"
    "3. 如果前文回顾中已有某个信息（角色说过的话、发生过的事），本场景中必须推进到新的内容，不能重述\n"
    "4. 每个场景必须包含至少一个前文中没有出现过的新信息、新发现或新转折\n"
    "5. 不同角色说话必须有明显区别：\n"
    "   - 指挥官：简短命令式，不解释\n"
    "   - 科学家：用数据和术语，但夹带个人情绪\n"
    "   - 工程师：关注实际操作，用具体数字\n"
    "   - 普通船员：口语化，会害怕、会抱怨\n"
    "6. 禁止不同角色说出措辞相似的台词。每个角色有自己的语言习惯和口头禅\n"
)

_NARRATIVE_LOGIC = (
    "【叙事逻辑规则 — 必须遵守】\n"
    "1. 每个提出的方案/计划必须有明确结局（成功、失败、或被放弃），不能悬而未决就开始新方案\n"
    "2. 出场的角色必须有交代：如果角色去执行任务，后续必须写到他的结果（成功/失败/牺牲）\n"
    "3. 角色的死亡/受伤只能发生一次，且必须前后一致。已死的角色不能再出现\n"
    "4. 数字和距离等具体细节必须与前文保持一致（如果前文说距离0.3光年，后文不能变成柯伊伯带）\n"
    "5. 关键转折不能依赖巧合（如'突然引擎自启'），必须有前文铺垫的合理解释\n"
    "6. 同一个事件只能出现一次。如果前文已经写过新闻发布会，不要再写第二次\n"
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
        self._main_storyline: dict[str, Any] | None = None
        self._story_position: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # 主线上下文设置
    # ------------------------------------------------------------------

    def set_storyline_context(
        self,
        main_storyline: dict,
        current_chapter: int,
        total_chapters: int,
        storyline_progress: str = "",
    ) -> None:
        """设置主线上下文，让写作时具有全局意识。"""
        self._main_storyline = main_storyline

        # 计算故事位置和节奏指令
        progress_pct = int(current_chapter / max(total_chapters, 1) * 100)

        # 根据位置给出不同节奏指令
        if current_chapter == 1:
            pacing = (
                "开场章：必须在前500字内制造冲突或悬念，禁止慢热铺垫。"
                "用动作/对话/危机开场，不要用背景介绍开场。"
            )
        elif current_chapter <= 3:
            pacing = (
                "前期章节：核心矛盾必须在本章完全展开，读者必须能清楚感知主角面临的困境。"
                "节奏要快，每个场景都要有事件推进。"
            )
        elif progress_pct < 25:
            pacing = (
                "铺展期：在推进主线的同时可以适当展开世界观和人物关系，"
                "但每章必须有至少一个推动主线的关键事件。"
            )
        elif progress_pct < 50:
            pacing = (
                "发展期：矛盾开始升级，主角遭遇更大的挑战。"
                "可以设置小高潮和反转，保持读者紧张感。"
            )
        elif progress_pct < 75:
            pacing = (
                "高潮前期：赌注全面升级，主角面临最大考验。"
                "节奏加快，每章结尾必须有强钩子。"
            )
        elif progress_pct < 90:
            pacing = (
                "高潮期：故事进入最紧张阶段，核心冲突正面对决。"
                "禁止拖沓，每个场景都要推进剧情。"
            )
        else:
            pacing = "收束期：解决核心冲突，完成角色弧线。给读者满足感的同时留下回味。"

        self._story_position = {
            "current": current_chapter,
            "total": total_chapters,
            "progress_pct": progress_pct,
            "storyline_progress": storyline_progress,
            "pacing_instruction": pacing,
        }

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
        scenes_written_summary: str = "",
    ) -> Scene:
        """生成单个场景正文。"""
        char_desc = self._build_character_description(characters)
        world_desc = self._build_world_description(world_setting)
        style = self._get_style_prompt(style_name)
        trimmed_context = truncate_text(context, _MAX_CONTEXT_CHARS) if context else ""
        target_words = scene_plan.get("target_words", 800)

        # 构建主线提示
        main_storyline_prompt = ""
        if self._main_storyline:
            sl = self._main_storyline
            main_storyline_prompt = (
                f"\n【故事主线 — 写作时必须牢记】\n"
                f"主角目标：{sl.get('protagonist_goal', '')}\n"
                f"核心冲突：{sl.get('core_conflict', '')}\n"
                f"角色弧线：{sl.get('character_arc', '')}\n"
                f"赌注：{sl.get('stakes', '')}\n"
            )

        # 构建位置感提示
        position_prompt = ""
        if self._story_position:
            pos = self._story_position
            position_prompt = (
                f"\n【当前故事位置】\n"
                f"第 {pos.get('current', 1)} 章 / 共 {pos.get('total', 1)} 章"
                f"（进度 {pos.get('progress_pct', 0)}%）\n"
                f"本章主线推进：{pos.get('storyline_progress', '')}\n"
                f"节奏要求：{pos.get('pacing_instruction', '')}\n"
            )

        system_prompt = (
            f"{style}\n\n"
            f"你是一位专业小说写手，正在创作第{chapter_outline.chapter_number}章"
            f"「{chapter_outline.title}」中的第{scene_plan.get('scene_number', 1)}个场景。\n"
            f"本章目标：{chapter_outline.goal}\n"
            f"本章情绪基调：{chapter_outline.mood}\n\n"
            f"{main_storyline_prompt}"
            f"{position_prompt}"
            f"【极其重要的字数限制】你必须严格控制输出在{target_words}字左右。"
            f"绝对不能超过{target_words + 200}字。宁可写少也不要写多。"
            f"写到接近目标字数时，必须在一个完整的句子处自然收束，不要强行展开新情节。\n\n"
            f"【世界观设定】\n{world_desc}\n\n"
            f"【角色档案】\n{char_desc}\n\n"
            f"{_ANTI_AI_FLAVOR}\n"
            f"{_ANTI_REPETITION}\n"
            f"{_NARRATIVE_LOGIC}"
        )

        # 构建角色说话方式提醒
        speech_style_prompt = ""
        characters_involved_names = set(
            scene_plan.get("characters_involved", scene_plan.get("characters", []))
        )
        if characters and characters_involved_names:
            speech_lines = []
            for c in characters:
                if c.name in characters_involved_names and c.personality.speech_style:
                    line = f"- {c.name}: {c.personality.speech_style}"
                    if c.personality.catchphrases:
                        line += f"（口头禅：{'、'.join(c.personality.catchphrases)}）"
                    speech_lines.append(line)
            if speech_lines:
                speech_style_prompt = (
                    "\n【出场角色的说话方式 — 每个角色必须有区分度】\n"
                    + "\n".join(speech_lines)
                    + "\n"
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

        if scenes_written_summary:
            user_prompt += f"【本章已写内容摘要 — 禁止重复以下内容】\n{scenes_written_summary}\n\n"

        if trimmed_context:
            user_prompt += f"【前文回顾】\n{trimmed_context}\n\n"

        if speech_style_prompt:
            user_prompt += f"{speech_style_prompt}\n"

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
            # 构建本章已写场景摘要，帮助 Writer 避免重复
            scenes_written_summary = ""
            if scenes:
                summaries = []
                for prev_scene in scenes:
                    text = prev_scene.text
                    if len(text) > 200:
                        summary = text[:100] + "……" + text[-100:]
                    else:
                        summary = text
                    summaries.append(f"场景{prev_scene.scene_number}摘要: {summary}")
                scenes_written_summary = "\n".join(summaries)

            scene = self.generate_scene(
                scene_plan=plan,
                chapter_outline=chapter_outline,
                characters=characters,
                world_setting=world_setting,
                context=running_context,
                style_name=style_name,
                scenes_written_summary=scenes_written_summary,
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
    # 自审 + 精修
    # ------------------------------------------------------------------

    def self_critique(
        self,
        chapter_text: str,
        chapter_outline: ChapterOutline,
        context: str = "",
        all_chapter_summaries: str = "",
    ) -> str:
        """AI 自审：以编辑视角审读章节，找出具体问题。

        Returns:
            具体问题列表和修改建议（文本）
        """
        system_prompt = (
            "你是一位严格的小说编辑，正在审稿。你的任务是找出章节中的具体问题，"
            "而不是泛泛而谈。每个问题必须指出具体的文字位置。\n\n"
            "审稿标准：\n"
            "1. 【重复】是否有场景、描写、比喻、对话在本章或前文中重复出现？指出具体重复的内容\n"
            "2. 【对话】每个角色说话是否有区分度？是否所有人说话语气雷同？指出具体台词\n"
            "3. 【逻辑】是否有情节矛盾、角色消失、方案悬而未决？指出具体位置\n"
            "4. 【节奏】是否有拖沓段落？哪些段落可以删减或压缩？\n"
            "5. 【细节】数字、距离、时间等是否前后一致？\n"
            "6. 【AI味】是否有空洞抒情、无意义排比、过度使用'仿佛'/'宛如'？\n"
            "7. 【转折】关键转折是否依赖巧合？是否有铺垫？\n\n"
            "请用以下格式输出（不要输出 JSON）：\n"
            "【问题1】类型：重复\n"
            "位置：第X段「具体引用原文几个字」\n"
            "问题：XXX\n"
            "建议：XXX\n\n"
            "【问题2】...\n\n"
            "如果章节质量很好没有明显问题，输出「审稿通过，无需修改」"
        )

        user_prompt = f"## 第{chapter_outline.chapter_number}章「{chapter_outline.title}」\n\n"
        user_prompt += f"本章目标：{chapter_outline.goal}\n\n"

        if all_chapter_summaries:
            user_prompt += f"【前文各章摘要（用于检查重复和一致性）】\n{all_chapter_summaries}\n\n"

        if context:
            trimmed = truncate_text(context, 1500)
            user_prompt += f"【上一章结尾】\n{trimmed}\n\n"

        user_prompt += f"【待审章节全文】\n{chapter_text}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = self.llm.chat(messages, temperature=0.3, max_tokens=2048)
        return response.content.strip()

    def polish_chapter(
        self,
        chapter_text: str,
        critique: str,
        chapter_outline: ChapterOutline,
        characters: list[CharacterProfile],
        world_setting: WorldSetting,
        context: str,
        style_name: str,
    ) -> str:
        """精修章节：根据自审结果改稿。

        与 rewrite_chapter 的区别：
        - rewrite_chapter 是根据外部反馈重写（可能大改）
        - polish_chapter 是根据自审结果精修（保留好的部分，只改有问题的部分）
        """
        if "审稿通过" in critique and "无需修改" in critique:
            log.info("第%d章审稿通过，无需精修", chapter_outline.chapter_number)
            return chapter_text

        char_desc = self._build_character_description(characters)
        world_desc = self._build_world_description(world_setting)
        style = self._get_style_prompt(style_name)
        trimmed_context = truncate_text(context, _MAX_CONTEXT_CHARS) if context else ""
        target_words = chapter_outline.estimated_words

        # 构建主线提示（如果有的话）
        main_storyline_prompt = ""
        if self._main_storyline:
            sl = self._main_storyline
            main_storyline_prompt = (
                f"\n【故事主线】\n"
                f"主角目标：{sl.get('protagonist_goal', '')}\n"
                f"核心冲突：{sl.get('core_conflict', '')}\n"
            )

        system_prompt = (
            f"{style}\n\n"
            f"你是一位专业小说写手，正在精修第{chapter_outline.chapter_number}章"
            f"「{chapter_outline.title}」。\n"
            f"本章目标：{chapter_outline.goal}\n"
            f"本章情绪基调：{chapter_outline.mood}\n"
            f"{main_storyline_prompt}\n"
            f"【精修原则】\n"
            f"1. 保留原文好的部分（精彩描写、有力对话、关键情节）\n"
            f"2. 只改有问题的部分，不要重写没问题的段落\n"
            f"3. 修复编辑指出的每一个具体问题\n"
            f"4. 保持原文的整体结构和节奏\n"
            f"5. 修改后的文字要自然融入原文，不能有拼接感\n\n"
            f"【世界观设定】\n{world_desc}\n\n"
            f"【角色档案】\n{char_desc}\n\n"
            f"{_ANTI_AI_FLAVOR}\n"
            f"{_ANTI_REPETITION}\n"
            f"{_NARRATIVE_LOGIC}"
        )

        user_prompt = f"【原文】\n{chapter_text}\n\n"
        user_prompt += f"【编辑审稿意见 — 必须逐条修复】\n{critique}\n\n"

        if trimmed_context:
            user_prompt += f"【前文回顾】\n{trimmed_context}\n\n"

        user_prompt += (
            f"请输出精修后的完整章节正文。不要输出标题或元信息。\n"
            f"【字数要求】\n"
            f"- 目标字数：{target_words}字（允许范围：{max(target_words - 300, 500)}-{target_words + 300}字）\n"
            f"- 宁可少写也不要超出上限"
        )

        max_tokens = min(4096, target_words + 500)
        response = self.llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=max_tokens,
        )

        polished = response.content.strip()

        # 安全截断
        hard_limit = int(target_words * 1.5)
        if len(polished) > hard_limit:
            cut_pos = polished.rfind("\n\n", 0, hard_limit)
            if cut_pos > hard_limit // 2:
                polished = polished[:cut_pos]
            else:
                for sep in ("。", "！", "？", "!", "?", "\n"):
                    cut_pos = polished.rfind(sep, 0, hard_limit)
                    if cut_pos > hard_limit // 2:
                        polished = polished[:cut_pos + 1]
                        break
                else:
                    polished = polished[:hard_limit]
            log.warning("精修文本超长(%d字)，截断至%d字", len(response.content), len(polished))

        return polished

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
    total_chapters = state.get("total_chapters", 1)
    scene_plans = state.get("current_scenes") or []
    style_name = state.get("style_name", "webnovel.shuangwen")

    # 设置主线上下文和故事位置
    outline_data = state.get("outline")
    main_storyline = {}
    storyline_progress = ""
    if outline_data and isinstance(outline_data, dict):
        main_storyline = outline_data.get("main_storyline", {})
        # 从当前章节大纲中提取主线推进信息
        ch_outline_for_progress = state.get("current_chapter_outline")
        if ch_outline_for_progress and isinstance(ch_outline_for_progress, dict):
            storyline_progress = (
                ch_outline_for_progress.get("storyline_progress", "")
                or ch_outline_for_progress.get("goal", "")
            )

    if main_storyline:
        writer.set_storyline_context(
            main_storyline=main_storyline,
            current_chapter=current_chapter,
            total_chapters=total_chapters,
            storyline_progress=storyline_progress,
        )

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
