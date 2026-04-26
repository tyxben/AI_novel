"""Writer Agent - 章节正文生成

负责根据场景计划、角色档案、世界观设定和上下文，
逐场景生成章节正文，并支持基于反馈的重写。
"""

from __future__ import annotations

import logging
import re as _re
from datetime import datetime, timezone
from typing import Any

from src.llm.llm_client import LLMClient, LLMResponse, create_llm_client
from src.novel.llm_utils import get_stage_llm_config
from src.novel.models.chapter import Chapter, Scene
from src.novel.models.character import CharacterProfile
from src.novel.models.novel import ChapterOutline
from src.novel.models.world import WorldSetting
from src.novel.templates.style_presets import get_style
from src.novel.utils import count_words, truncate_text

log = logging.getLogger("novel")

# ---------------------------------------------------------------------------
# 系统 UI 元素清洗（移除游戏化系统提示，避免污染叙事文本）
# ---------------------------------------------------------------------------

# Patterns for system UI elements that should not appear in narrative text
_SYSTEM_UI_PATTERNS = [
    # Bracketed system messages: 【...】
    _re.compile(r"【[^】]{1,80}】"),
    # Loyalty/stat changes: 忠诚度：71→79, 兵煞值+8
    _re.compile(r"[\u4e00-\u9fa5]{2,8}[:：]\s*\d+\s*[→\-+]\s*\d+"),
    _re.compile(r"[\u4e00-\u9fa5]{2,8}\s*[+\-]\s*\d+\s*$", _re.MULTILINE),
]

# Allowlist of system messages that ARE part of the story (system-cultivation novel)
# These get kept; everything else gets stripped
_SYSTEM_UI_ALLOWLIST = {
    "【叮！】",  # iconic system notification
}


def _sanitize_chapter_text(text: str) -> str:
    """Strip game-UI elements from generated chapter text.

    The Writer sometimes leaks system messages, stat displays, and other
    game-UI elements into the narrative. This filter removes them while
    preserving allowlisted iconic markers like 【叮！】.
    """
    if not text:
        return text

    cleaned_lines = []
    for line in text.split("\n"):
        original = line
        # Remove bracketed system messages (except allowlisted)
        def _strip_brackets(m):
            return m.group() if m.group() in _SYSTEM_UI_ALLOWLIST else ""
        line = _SYSTEM_UI_PATTERNS[0].sub(_strip_brackets, line)
        # Remove stat changes
        line = _SYSTEM_UI_PATTERNS[1].sub("", line)
        line = _SYSTEM_UI_PATTERNS[2].sub("", line)
        # Skip lines that became empty or only whitespace
        if line.strip() or not original.strip():
            cleaned_lines.append(line)

    result = "\n".join(cleaned_lines)
    # Collapse 3+ consecutive newlines into 2
    result = _re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()

# 续写相关常量
_MAX_CONTINUATIONS = 3  # 最多续写次数，防止无限循环

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

_CHARACTER_NAME_LOCK = (
    "【角色名称锁定 — 绝对禁止违反】\n"
    "1. 每个角色只能使用【角色档案】中定义的名字，禁止自行给角色起新名字、加姓氏或改名\n"
    "2. 禁止使用占位符称呼：禁止写「角色A」「女学生B」「老人C」「男子D」「路人甲」等编号式称呼\n"
    "3. 如果需要引入新的路人/NPC，可以用职业/特征称呼（如「收银员」「保安」），但同一个NPC前后称呼必须一致\n"
    "4. 角色名字一旦出现在前文中，后续必须使用完全相同的名字，不能缩写或扩展（如「小玲」不能变成「李小玲」）\n"
)

# ---------------------------------------------------------------------------
# 正面写作指导（提升文笔质量、细节和逻辑）
# ---------------------------------------------------------------------------

_CRAFT_QUALITY = (
    "【写作质量要求 — 必须遵守】\n"
    "1. **展示而非陈述（Show Don't Tell）**：\n"
    "   - 错误示范：「他很害怕」 → 正确：「他的手指不受控制地颤抖，嘴唇咬出了血痕」\n"
    "   - 错误示范：「她很生气」 → 正确：「她把茶杯重重搁在桌上，杯底在桃木面上磕出一道白印」\n"
    "   - 情绪必须通过具体的身体反应、微表情、小动作来传达，禁止直接写情绪词\n"
    "2. **感官细节**：每个场景至少调动2种以上感官（视觉+听觉/嗅觉/触觉/味觉）\n"
    "   - 室内场景写出光线质感、温度变化、物品触感\n"
    "   - 室外场景写出天气体感、地面质地、远近声音层次\n"
    "   - 战斗场面写出冲击力的物理反馈（地面震颤、气流扰动、关节酸麻）\n"
    "3. **因果逻辑链 — 每个行为必须有动机，每个结果必须有原因**：\n"
    "   - 角色做出决定前，必须交代他的顾虑、信息和权衡过程\n"
    "   - 角色改变态度，必须有具体的触发事件（一句话、一个发现、一次冲突）\n"
    "   - 战斗/冲突中的胜负翻转必须有铺垫：利用环境、对手的弱点、之前埋下的伏笔\n"
    "   - 禁止「突然」「忽然」解决问题（deus ex machina），所有转折必须可追溯\n"
    "4. **对话要有潜台词**：\n"
    "   - 人物不会直接说出自己的真实意图。想要求助的人会绕弯子，心虚的人会岔开话题\n"
    "   - 每句对话至少承担两个功能：推进剧情+揭示性格 / 传递信息+暗示情绪\n"
    "   - 对话间插入微动作（搅咖啡、整理衣角、回避视线）来表达言外之意\n"
    "5. **场景节奏**：\n"
    "   - 紧张场景用短句、快节奏：「他转身。刀光闪过。血珠溅落。」\n"
    "   - 舒缓场景用长句、细描写，让读者放慢呼吸\n"
    "   - 一个场景内必须有至少一次节奏变化（从快到慢、或从慢到快）\n"
    "6. **环境不是背景板**：\n"
    "   - 环境描写必须与人物情绪或剧情走向呼应\n"
    "   - 角色与环境要有互动（踩到碎石、拂过树枝、被雨淋湿），而不是人物在真空中行动\n"
)

# ---------------------------------------------------------------------------
# 上下文最大字符数
# ---------------------------------------------------------------------------

_MAX_CONTEXT_CHARS = 4000

# ---------------------------------------------------------------------------
# 场景去重：Jaccard 相似度阈值
# ---------------------------------------------------------------------------

# 去重分级阈值
_DEDUP_HARD_DELETE = 0.6   # ≥60% 句子完全相同 → 删除整段（确定是照搬）
_DEDUP_STRIP_OVERLAP = 0.4  # ≥40% → 只删重复句，保留独有句（可能是承接+新内容混合）
# < 40% → 不处理（正常的呼应和承接）


# ---------------------------------------------------------------------------
# Writer 类
# ---------------------------------------------------------------------------


class Writer:
    """写手 Agent - 正文生成"""

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client
        self._main_storyline: dict[str, Any] | None = None
        self._story_position: dict[str, Any] | None = None
        self._chapter_brief: dict[str, Any] | None = None
        self._registry: Any | None = None
        self._novel_id: str | None = None

    def set_chapter_brief(self, chapter_brief: dict[str, Any] | None) -> None:
        """设置章节任务书，让场景生成时具有明确的叙事目标。"""
        self._chapter_brief = chapter_brief if chapter_brief else None

    def enable_prompt_registry(self, registry: "PromptRegistry", novel_id: str | None = None) -> None:  # noqa: F821
        """Enable dynamic prompts from Prompt Registry."""
        self._registry = registry
        self._novel_id = novel_id

    # ------------------------------------------------------------------
    # 场景类型检测（用于 Prompt Registry 模板匹配）
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_scenario(scene_plan: dict) -> str:
        """Detect scene scenario from plan for template matching."""
        goal = (scene_plan.get("goal", "") + " " + scene_plan.get("summary", "")).lower()
        keywords = {
            "battle": ["战斗", "打斗", "攻击", "战争", "拳", "剑", "杀"],
            "dialogue": ["对话", "交谈", "说服", "谈判", "争论"],
            "emotional": ["感情", "离别", "重逢", "告白", "悲伤", "感动"],
            "strategy": ["谋略", "计划", "布局", "阴谋", "策略"],
        }
        for scenario, kws in keywords.items():
            if any(kw in goal for kw in kws):
                return scenario
        return "default"

    # ------------------------------------------------------------------
    # 续写辅助：检测截断并自动续写
    # ------------------------------------------------------------------

    def _continue_if_truncated(
        self,
        response: LLMResponse,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        soft_max_chars: int | None = None,
    ) -> str:
        """如果 LLM 回复因 max_tokens 被截断，自动续写直到完成。

        Args:
            response: 初始 LLM 回复
            messages: 原始消息列表
            temperature: 生成温度
            max_tokens: 单次最大 token 数
            soft_max_chars: 软上限（可选）。一旦当前文本已超过此长度，
                即使 finish_reason=length 也不再续写，避免无限扩张。
                不做硬截断 —— 当前已写的内容全部保留。

        Returns:
            完整的文本（可能经过多次续写拼接）
        """
        if not response or not response.content:
            raise ValueError("LLM 返回空响应")
        text = response.content.strip()

        if response.finish_reason != "length":
            return text

        if soft_max_chars is not None and len(text) >= soft_max_chars:
            log.warning(
                "LLM 已写 %d 字（≥软上限 %d），不再续写",
                len(text), soft_max_chars,
            )
            return text

        log.warning(
            "LLM 输出被截断（finish_reason=length, %d字），尝试续写...",
            len(text),
        )

        for attempt in range(1, _MAX_CONTINUATIONS + 1):
            # 构建续写消息：在原始对话后追加已生成内容 + 续写指令
            continuation_messages = messages + [
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": (
                        "你的上一段输出被截断了，请从断点处继续写完。"
                        "直接续写正文，不要重复已写内容，不要加任何前缀说明。"
                        "必须写出完整的结尾段落，让场景有收束感，不要在动作或对话中途停止。"
                    ),
                },
            ]

            cont_response = self.llm.chat(
                continuation_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if not cont_response or not cont_response.content:
                break
            continuation = cont_response.content.strip()

            if not continuation:
                break

            text = text + continuation
            log.info("续写第%d次，累计%d字", attempt, len(text))

            if cont_response.finish_reason != "length":
                break  # 正常结束

            # 在续写循环中也遵守软上限：已够长则停止而非继续扩张
            if soft_max_chars is not None and len(text) >= soft_max_chars:
                log.warning(
                    "续写后已达 %d 字（≥软上限 %d），停止扩张",
                    len(text), soft_max_chars,
                )
                break

        return text

    # ------------------------------------------------------------------
    # 字数硬截：last-resort enforcement layer
    # ------------------------------------------------------------------

    @staticmethod
    def _trim_to_hard_cap(text: str, hard_cap: int, target: int) -> str:
        """超过 hard_cap 时，回退到 hard_cap 内最近的句末标点处截断。

        DeepSeek 实测对 prompt 字数约束完全无视（见 memory
        novel-length-control-floor），soft_max_chars 只能阻止续写扩张，
        但首轮就超长时无能为力。本函数是最后一道执行层。

        策略：从 hard_cap 位置向前扫，找到最后一个句末标点（。！？!?）。
        命中后顺带把紧随其后的闭合引号/括号 ("'」』）】) 一起带出，
        最多带 4 个（避免极端连续闭合标点导致 cut 越过 hard_cap 太多）。
        若窗口内没有句末标点（极少），硬切到 hard_cap。
        下界 floor = hard_cap // 2，保证至少保留半数硬上限的内容。

        Note: 中文 "……"（省略号）刻意排除在 sentence_end 之外，因为它常用作
        句中悬念（"至于林炎……"），切在那里会留下明显残句。

        防御性：hard_cap <= 0 或空输入直接原样返回（避免数值误配传播）。
        """
        if hard_cap <= 0 or not text:
            return text

        if len(text) <= hard_cap:
            return text

        # 句末标点：只用真正的句号/问号/感叹号（中文/英文标点都列出以兼容混排文本）
        sentence_end = "。！？!?"
        closing = "\"'」』）】"
        # floor 必须 < hard_cap，否则搜索窗口为空。
        # 取 hard_cap//2 保证至少保留半数硬上限的内容，不会切到极短。
        floor = hard_cap // 2
        cut = -1
        i = hard_cap
        while i > floor:
            if text[i - 1] in sentence_end:
                j = i
                # 闭合标点最多带 4 个，防止极端连续闭合越过 hard_cap 太多
                while j < len(text) and j - i < 4 and text[j] in closing:
                    j += 1
                cut = j
                break
            i -= 1

        if cut == -1:
            cut = hard_cap

        trimmed = text[:cut].rstrip()
        log.info(
            "[trim] 文本超长裁剪：%d 字 → %d 字 (target=%d, hard_cap=%d)",
            len(text), len(trimmed), target, hard_cap,
        )
        return trimmed

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
        debt_summary: str = "",
        budget_mode: bool = False,
        feedback_prompt: str = "",
        continuity_brief: str = "",
    ) -> Scene:
        """生成单个场景正文。"""
        char_desc = self._build_character_description(characters)
        world_desc = self._build_world_description(world_setting)
        style = self._get_style_prompt(style_name)
        max_ctx = _MAX_CONTEXT_CHARS
        trimmed_context = truncate_text(context, max_ctx) if context else ""
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

        # 构建章节任务书提示
        chapter_brief_prompt = ""
        if self._chapter_brief and isinstance(self._chapter_brief, dict):
            brief = self._chapter_brief
            brief_lines = ["【本章任务书 — 场景必须服务于以下目标】"]
            if brief.get("main_conflict"):
                brief_lines.append(f"- 本章主冲突：{brief['main_conflict']}")
            if brief.get("payoff"):
                brief_lines.append(f"- 本章必须兑现：{brief['payoff']}")
            if brief.get("character_arc_step"):
                brief_lines.append(f"- 角色变化：{brief['character_arc_step']}")
            if brief.get("end_hook_type"):
                brief_lines.append(f"- 章尾钩子：{brief['end_hook_type']}")
            if len(brief_lines) > 1:
                chapter_brief_prompt = "\n".join(brief_lines) + "\n"

        # Determine craft/anti-pattern prompt blocks: use registry if enabled, else hardcoded
        scenario = self._detect_scenario(scene_plan)
        if self._registry is not None:
            # Extract genre from style_name for registry lookup (e.g. "webnovel.shuangwen" -> "webnovel")
            _genre_for_registry = style_name.split(".")[0] if "." in style_name else style_name
            registry_prompt = self._registry.build_prompt(
                agent_name="writer",
                scenario=scenario,
                genre=_genre_for_registry,
            )
            if registry_prompt:
                craft_blocks = f"{registry_prompt}\n{_CRAFT_QUALITY}"
            else:
                # Registry returned empty -- fall back to hardcoded
                craft_blocks = (
                    f"{_CRAFT_QUALITY}\n"
                    f"{_ANTI_AI_FLAVOR}\n"
                    f"{_ANTI_REPETITION}\n"
                    f"{_NARRATIVE_LOGIC}\n"
                    f"{_CHARACTER_NAME_LOCK}"
                )
        else:
            craft_blocks = (
                f"{_CRAFT_QUALITY}\n"
                f"{_ANTI_AI_FLAVOR}\n"
                f"{_ANTI_REPETITION}\n"
                f"{_NARRATIVE_LOGIC}\n"
                f"{_CHARACTER_NAME_LOCK}"
            )

        # 连续性约束注入
        continuity_prompt = ""
        if continuity_brief:
            continuity_prompt = f"\n{continuity_brief}\n"

        # First scene of chapter: add explicit transition requirement
        is_first_scene = scene_plan.get('scene_number', 1) == 1
        if is_first_scene and chapter_outline.chapter_number > 1:
            continuity_prompt += (
                "\n【章节衔接要求 — 最高优先级】\n"
                "你正在写本章的第一个场景。必须遵守以下规则：\n"
                "1. 第一段必须与上章结尾在时间、空间、人物状态上无缝衔接\n"
                "2. 如果上章结尾有悬念（如出现神秘人物、计划了某个行动），本场景必须先交代其结果\n"
                "3. 禁止跳过时间段（如上章说'明天集合'，本章必须写到集合时刻）\n"
                "4. 禁止凭空开始新场景，必须先接续上章的动作/对话/事件\n"
                "5. 开头不要使用'却说''话说''且说'等跳跃性连接词\n\n"
            )

        # 结构化字数约束：用"硬上限 + 段落数 + 自检"三件套逼近目标
        # DeepSeek 对字数数字不敏感，但对"失败输出"和段落结构相对敏感
        hard_cap = int(target_words * 1.2)
        soft_floor = max(int(target_words * 0.7), 300)
        para_min = max(3, target_words // 200)
        para_max = max(para_min + 2, target_words // 100)

        system_prompt = (
            f"{style}\n\n"
            f"你是一位专业小说写手，正在创作第{chapter_outline.chapter_number}章"
            f"「{chapter_outline.title}」中的第{scene_plan.get('scene_number', 1)}个场景。\n"
            f"本章目标：{chapter_outline.goal}\n"
            f"本章情绪基调：{chapter_outline.mood}\n\n"
            f"{main_storyline_prompt}"
            f"{position_prompt}"
            f"{chapter_brief_prompt}"
            f"{continuity_prompt}"
            f"【字数硬约束 — 超出视为失败输出，不可交付】\n"
            f"- 本场景范围 {soft_floor}-{hard_cap} 字（含标点）。上限 {hard_cap} 字是硬线，超一字即失败。\n"
            f"- 目标 {target_words} 字，分 {para_min}-{para_max} 段，段与段之间空一行。\n"
            f"- 输出前必须心算总字数：超过 {hard_cap} 字则删减到 {target_words} 字以内再输出。\n"
            f"- 宁可在 {soft_floor} 字处收束，也不要水字数到 {hard_cap} 字以上。\n\n"
            f"【世界观设定】\n{world_desc}\n\n"
            f"【角色档案】\n{char_desc}\n\n"
            f"{craft_blocks}"
        )

        # 构建角色说话方式提醒 + 外貌锁定
        speech_style_prompt = ""
        character_lock_prompt = ""
        characters_involved_names = set(
            scene_plan.get("characters_involved", scene_plan.get("characters", []))
        )
        if characters and characters_involved_names:
            speech_lines = []
            lock_lines = []
            for c in characters:
                if c.name not in characters_involved_names:
                    continue
                # 说话方式
                if c.personality.speech_style:
                    line = f"- {c.name}: {c.personality.speech_style}"
                    if c.personality.catchphrases:
                        line += f"（口头禅：{'、'.join(c.personality.catchphrases)}）"
                    speech_lines.append(line)
                # 【修复】角色外貌锁定：每个场景都强制提醒角色外貌
                lock = f"- {c.name}（{c.gender}，{c.age}岁）"
                if c.appearance:
                    app = c.appearance
                    lock += f"：{app.build}体型，{app.hair}，{app.eyes}，{app.clothing_style}"
                    if app.distinctive_features:
                        lock += f"，{'/'.join(app.distinctive_features)}"
                if c.character_arc:
                    lock += f"  弧线：{c.character_arc.initial_state} → {c.character_arc.final_state}"
                lock_lines.append(lock)
            if speech_lines:
                speech_style_prompt = (
                    "\n【出场角色的说话方式 — 每个角色必须有区分度】\n"
                    + "\n".join(speech_lines)
                    + "\n"
                )
            if lock_lines:
                # 收集所有合法角色名（名字+别名）
                all_names = []
                for c in characters:
                    all_names.append(c.name)
                    if c.alias:
                        all_names.extend(c.alias)
                name_list = "、".join(all_names)
                character_lock_prompt = (
                    "\n【本场景出场角色外貌锁定 — 描写必须与以下一致，禁止偏离】\n"
                    + "\n".join(lock_lines)
                    + f"\n\n【合法角色名白名单】只允许使用以下名字：{name_list}\n"
                    + "禁止自行创造新角色名或给已有角色改名/加姓氏。路人用职业称呼即可。\n"
                )

        # 叙事债务注入
        debt_prompt = ""
        if debt_summary:
            debt_prompt = (
                f"【前文未了结的叙事义务 — 本场景应尽量推进以下事项】\n"
                f"{debt_summary}\n\n"
            )

        # 反馈约束注入
        feedback_constraint_prompt = ""
        if feedback_prompt:
            feedback_constraint_prompt = (
                f"【前文质量反馈 — 本场景写作必须遵守以下改进要求】\n"
                f"{feedback_prompt}\n\n"
            )

        user_prompt = (
            f"{feedback_constraint_prompt}"
            f"{debt_prompt}"
            f"【场景信息】\n"
            f"- 地点：{scene_plan.get('location', '未指定')}\n"
            f"- 时间：{scene_plan.get('time', '未指定')}\n"
            f"- 出场角色：{', '.join(scene_plan.get('characters_involved', scene_plan.get('characters', [])))}\n"
            f"- 场景目标：{scene_plan.get('goal', scene_plan.get('summary', '未指定'))}\n"
            f"- 情绪氛围：{scene_plan.get('mood', chapter_outline.mood)}\n"
            f"- 字数上限：{hard_cap} 字（目标 {target_words}，下限 {soft_floor}）\n\n"
        )

        if scenes_written_summary:
            user_prompt += f"【本章已写内容 — 严禁重复以下任何段落、描写或对话】\n{scenes_written_summary}\n\n"

        if trimmed_context:
            if is_first_scene and chapter_outline.chapter_number > 1:
                user_prompt += (
                    f"【上章衔接要点 — 必须在本场景开头自然承接，严禁照抄以下文字】\n"
                    f"{trimmed_context}\n\n"
                )
            else:
                user_prompt += f"【本章前文回顾】\n{trimmed_context}\n\n"

        if character_lock_prompt:
            user_prompt += f"{character_lock_prompt}\n"

        if speech_style_prompt:
            user_prompt += f"{speech_style_prompt}\n"

        user_prompt += (
            f"请直接输出场景正文，不要输出标题、序号或任何元信息。\n\n"
            f"【收束要求】\n"
            f"- 场景必须有明确的结尾段落：角色做出决定、事件有阶段性结果、或情绪有落点\n"
            f"- 禁止在对话、动作、战斗的中途戛然而止\n"
            f"- 结尾至少需要2-3个完整句子来收束当前场景的叙事\n"
            f"- 可以留悬念引出下文，但当前场景本身必须是完整的\n\n"
            f"【最终字数检查 — 最高优先级，输出前必读】\n"
            f"本场景输出 ≤ {hard_cap} 字（目标 {target_words}，分 {para_min}-{para_max} 段）。\n"
            f"写完请自检：超过 {hard_cap} 字必须删减后再交付，绝不能直接输出超长版本。"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # max_tokens: 按目标字数估算 token 预算（中文 1 字 ≈ 1.5 token）
        # 1.4x 倍率给 LLM 少量收束余地；配合 soft_max_chars=target*1.5 的续写
        # 软上限形成双保险（任一触发都不再扩张）。
        # 下限 900 token (~1350 字) 保证极短 target 也能完整写完一个段落；
        # 上限 4096 token 防止极端大 target 爆量。
        max_tokens = min(4096, max(900, int(target_words * 1.4)))
        # soft_max_chars 必须 < max_tokens 字符容量，否则对大 target 失效；
        # 按 1.4 字/token 留 margin，确保软上限总能在 LLM 输出前触发
        soft_max_chars = min(int(target_words * 1.5), int(max_tokens * 1.4))
        response = self.llm.chat(messages, temperature=0.85, max_tokens=max_tokens)
        scene_text = self._continue_if_truncated(
            response, messages, temperature=0.85, max_tokens=max_tokens,
            soft_max_chars=soft_max_chars,
        )

        # 后处理硬截：DeepSeek 不听 prompt 字数指令，在这里强制收口
        scene_text = self._trim_to_hard_cap(scene_text, hard_cap, target_words)

        # 清洗系统 UI 元素（避免游戏化提示泄漏到叙事文本）
        scene_text = _sanitize_chapter_text(scene_text)

        # 角色名称校验：检测占位符和未知名称
        scene_text = self._check_character_names(scene_text, characters)

        scene_chars = scene_plan.get("characters_involved", scene_plan.get("characters", []))
        result_scene = Scene(
            scene_number=scene_plan.get("scene_number", 1),
            location=scene_plan.get("location", "未指定"),
            time=scene_plan.get("time", "未指定"),
            characters=scene_chars if scene_chars else ["unknown"],
            goal=scene_plan.get("goal", scene_plan.get("summary", "未指定")),
            text=scene_text,
            word_count=count_words(scene_text),
            narrative_modes=scene_plan.get("narrative_modes", []),
        )

        # Record usage for quality tracking (fire-and-forget, don't block generation)
        if self._registry is not None:
            try:
                _genre_for_usage = style_name.split(".")[0] if "." in style_name else style_name
                template = self._registry.get_template_for("writer", scenario, _genre_for_usage)
                if template:
                    self._registry.record_usage(
                        template_id=template.template_id,
                        block_ids=[],
                        agent_name="writer",
                        scenario=scenario,
                        novel_id=self._novel_id,
                        chapter_number=chapter_outline.chapter_number,
                    )
            except Exception:
                log.debug("Failed to record prompt usage", exc_info=True)

        return result_scene

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
        debt_summary: str = "",
        budget_mode: bool = False,
        feedback_prompt: str = "",
        continuity_brief: str = "",
    ) -> Chapter:
        """生成完整章节（逐场景生成，滑动窗口传递上下文）。"""
        # 从 chapter_outline 设置章节任务书
        brief = getattr(chapter_outline, "chapter_brief", None)
        if brief and isinstance(brief, dict) and brief:
            self.set_chapter_brief(brief)

        scenes: list[Scene] = []
        running_context = ""   # 本章内滑动窗口，不混入跨章 context

        for plan_idx, plan in enumerate(scene_plans):
            is_last_scene = (plan_idx == len(scene_plans) - 1)

            # 构建本章已写场景上下文（渐进式：最近场景全文，更早场景给摘要）
            # 这样既能有效检测重复，又控制 token 增长
            scenes_written_summary = ""
            if scenes:
                summaries = []
                for i, prev_scene in enumerate(scenes):
                    is_latest = (i == len(scenes) - 1)
                    if is_latest:
                        # 最近一个场景：给全文（去重最关键的参考）
                        summaries.append(
                            f"=== 场景{prev_scene.scene_number} 全文 ===\n{prev_scene.text}"
                        )
                    else:
                        # 更早的场景：给结尾300字（保留关键转折和承接点）
                        text = prev_scene.text
                        if len(text) > 300:
                            summary = "（前略）…" + text[-300:]
                        else:
                            summary = text
                        summaries.append(
                            f"=== 场景{prev_scene.scene_number} 摘要 ===\n{summary}"
                        )
                scenes_written_summary = "\n\n".join(summaries)

            # 最后一个场景需要强调章节结尾收束
            if is_last_scene:
                plan = dict(plan)  # don't mutate original
                existing_goal = plan.get("goal", plan.get("summary", ""))
                plan["goal"] = (
                    existing_goal + "\n"
                    "【这是本章最后一个场景】必须为整章写出完整的结尾：\n"
                    "- 本场景的事件必须有阶段性结论（不能悬在半空）\n"
                    "- 结尾用2-3段收束本章叙事，给读者一个「章节结束」的完整感\n"
                    "- 可以留一个引向下章的钩子（一句话暗示即可），但本章的主要情节必须闭合"
                )

            # 叙事债务仅注入第一个场景
            scene_debt_summary = debt_summary if plan_idx == 0 else ""

            scene_context = context if plan_idx == 0 else running_context
            scene = self.generate_scene(
                scene_plan=plan,
                chapter_outline=chapter_outline,
                characters=characters,
                world_setting=world_setting,
                context=scene_context,
                style_name=style_name,
                scenes_written_summary=scenes_written_summary,
                debt_summary=scene_debt_summary,
                budget_mode=budget_mode,
                feedback_prompt=feedback_prompt,
                continuity_brief=continuity_brief,
            )

            # 【修复】场景去重：移除与前文重复的段落
            if scenes:
                previous_texts = [s.text for s in scenes]
                original_text = scene.text
                deduped_text = self._deduplicate_paragraphs(original_text, previous_texts)
                if len(deduped_text) < len(original_text):
                    log.info(
                        "场景%d去重：%d字 → %d字",
                        scene.scene_number, len(original_text), len(deduped_text),
                    )
                    scene = Scene(
                        scene_number=scene.scene_number,
                        location=scene.location,
                        time=scene.time,
                        characters=scene.characters,
                        goal=scene.goal,
                        text=deduped_text,
                        word_count=count_words(deduped_text),
                        narrative_modes=scene.narrative_modes,
                    )

            scenes.append(scene)

            # 【修复】滑动窗口加大，保留更多前文
            running_context = truncate_text(
                running_context + "\n" + scene.text,
                _MAX_CONTEXT_CHARS,
            )

        full_text = "\n\n".join(s.text for s in scenes)
        # 章节级清洗：兜底过滤系统 UI 元素
        full_text = _sanitize_chapter_text(full_text)
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
        if not response or not response.content:
            raise ValueError("LLM 返回空响应")
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
        # Propagation needs full text for minimal edits; direct rewrite can use summary
        if is_propagation:
            original_summary = original_text
        else:
            original_summary = truncate_text(original_text, 3000)
        target_words = chapter_outline.estimated_words
        # 字数硬约束三件套（与 write_scene 保持一致的口径）
        hard_cap = int(target_words * 1.2)
        soft_floor = max(int(target_words * 0.7), 500)
        para_min = max(3, target_words // 200)
        para_max = max(para_min + 2, target_words // 100)

        if is_propagation:
            system_prompt = (
                f"{style}\n\n"
                f"你是一位专业小说写手。前面的章节做了修改，你需要微调当前章节以保持一致性。\n"
                f"只做必要的最小修改，保持原文风格和节奏。\n\n"
                f"【字数硬约束 — 超出视为失败】本章 {soft_floor}-{hard_cap} 字，分 {para_min}-{para_max} 段。\n\n"
                f"{_ANTI_AI_FLAVOR}"
            )
            user_prompt = (
                f"【第{chapter_outline.chapter_number}章「{chapter_outline.title}」原文】\n"
                f"{original_summary}\n\n"
                f"【需要调整的原因】\n{rewrite_instruction}\n\n"
            )
            if trimmed_context:
                user_prompt += (
                    f"【修改后的前章状态摘要 — 仅供衔接参考，严禁照抄】\n"
                    f"{trimmed_context}\n\n"
                )
            user_prompt += (
                f"请在原文基础上做最小必要修改，保持连贯。直接输出修改后的完整章节正文。\n\n"
                f"【最终字数检查 — 最高优先级，输出前必读】\n"
                f"本章 ≤ {hard_cap} 字（目标 {target_words}，下限 {soft_floor}）。\n"
                f"写完自检字数：超过 {hard_cap} 必须删减后再交付，绝不可直接输出超长版本。"
            )
        else:
            system_prompt = (
                f"{style}\n\n"
                f"你是一位专业小说写手，正在根据读者反馈重写第{chapter_outline.chapter_number}章"
                f"「{chapter_outline.title}」。\n"
                f"本章目标：{chapter_outline.goal}\n"
                f"本章情绪基调：{chapter_outline.mood}\n\n"
                f"【字数硬约束 — 超出视为失败输出】\n"
                f"- 本章 {soft_floor}-{hard_cap} 字（含标点），上限 {hard_cap} 字是硬线\n"
                f"- 分 {para_min}-{para_max} 段，输出前心算总字数，超出必须删减\n\n"
                f"【角色档案】\n{char_desc}\n\n"
                f"{_CRAFT_QUALITY}\n"
                f"{_ANTI_AI_FLAVOR}"
            )
            user_prompt = (
                f"【原文摘要】\n{original_summary}\n\n"
                f"【读者反馈/修改指令】\n{rewrite_instruction}\n\n"
            )
            if trimmed_context:
                user_prompt += (
                    f"【前章状态摘要 — 仅供衔接参考，严禁照抄】\n"
                    f"{trimmed_context}\n\n"
                )
            user_prompt += (
                f"请根据修改指令重写此章节。直接输出重写后的完整正文，不要标题或元信息。\n\n"
                f"【最终字数检查 — 最高优先级，输出前必读】\n"
                f"本章 ≤ {hard_cap} 字（目标 {target_words}，下限 {soft_floor}，分 {para_min}-{para_max} 段）。\n"
                f"写完自检字数：超过 {hard_cap} 必须删减后再交付，绝不可直接输出超长版本。"
            )

        # max_tokens: 按目标字数估算 token 预算（中文 1 字 ≈ 1.5 token）
        # 1.4x 倍率给 LLM 少量收束余地；配合 soft_max_chars=target*1.5 的续写
        # 软上限形成双保险（任一触发都不再扩张）。
        # 下限 900 token (~1350 字) 保证极短 target 也能完整写完一个段落；
        # 上限 4096 token 防止极端大 target 爆量。
        max_tokens = min(4096, max(900, int(target_words * 1.4)))
        soft_max_chars = min(int(target_words * 1.5), int(max_tokens * 1.4))
        rewrite_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = self.llm.chat(
            messages=rewrite_messages,
            temperature=0.8,
            max_tokens=max_tokens,
        )

        rewritten = self._continue_if_truncated(
            response, rewrite_messages, temperature=0.8, max_tokens=max_tokens,
            soft_max_chars=soft_max_chars,
        )

        # 后处理硬截：见 _trim_to_hard_cap docstring
        rewritten = self._trim_to_hard_cap(rewritten, hard_cap, target_words)

        return rewritten

    # ------------------------------------------------------------------
    # 精修
    # ------------------------------------------------------------------

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
        """精修章节：根据 Reviewer 批注改稿。

        与 rewrite_chapter 的区别：
        - rewrite_chapter 是根据外部反馈重写（可能大改）
        - polish_chapter 是根据 Reviewer 批注精修（保留好的部分，只改有问题的部分）

        critique 参数固定接收 ``CritiqueResult.to_writer_prompt()`` 产出的结构化
        批注文本。调用方（pipeline.polish_chapters）在更上层用
        ``CritiqueResult.issues`` 判断是否跳过精修，这里不再做文本字面量守卫。
        """
        char_desc = self._build_character_description(characters)
        world_desc = self._build_world_description(world_setting)
        style = self._get_style_prompt(style_name)
        trimmed_context = truncate_text(context, _MAX_CONTEXT_CHARS) if context else ""
        target_words = chapter_outline.estimated_words
        # 字数硬约束三件套（与 write_scene/rewrite_chapter 保持一致）
        hard_cap = int(target_words * 1.2)
        soft_floor = max(int(target_words * 0.7), 500)
        para_min = max(3, target_words // 200)
        para_max = max(para_min + 2, target_words // 100)

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
            f"【字数硬约束 — 超出视为失败输出】\n"
            f"- 本章 {soft_floor}-{hard_cap} 字，上限 {hard_cap} 是硬线\n"
            f"- 分 {para_min}-{para_max} 段，精修不得显著扩张原文长度\n\n"
            f"【精修原则】\n"
            f"1. 保留原文好的部分（精彩描写、有力对话、关键情节）\n"
            f"2. 只改有问题的部分，不要重写没问题的段落\n"
            f"3. 修复编辑指出的每一个具体问题\n"
            f"4. 保持原文的整体结构和节奏\n"
            f"5. 修改后的文字要自然融入原文，不能有拼接感\n\n"
            f"【世界观设定】\n{world_desc}\n\n"
            f"【角色档案】\n{char_desc}\n\n"
            f"{_CRAFT_QUALITY}\n"
            f"{_ANTI_AI_FLAVOR}\n"
            f"{_ANTI_REPETITION}\n"
            f"{_NARRATIVE_LOGIC}"
        )

        user_prompt = f"【原文】\n{chapter_text}\n\n"
        user_prompt += f"【编辑审稿意见 — 必须逐条修复】\n{critique}\n\n"

        if trimmed_context:
            user_prompt += (
                f"【前章状态摘要 — 仅供衔接参考，严禁照抄】\n"
                f"{trimmed_context}\n\n"
            )

        user_prompt += (
            f"请输出精修后的完整章节正文。不要输出标题或元信息。\n\n"
            f"【最终字数检查 — 最高优先级，输出前必读】\n"
            f"本章 ≤ {hard_cap} 字（目标 {target_words}，下限 {soft_floor}）。\n"
            f"写完自检字数：超过 {hard_cap} 必须删减后再交付，宁可少写也不要超出。"
        )

        # max_tokens: 按目标字数估算 token 预算（中文 1 字 ≈ 1.5 token）
        # 1.4x 倍率给 LLM 少量收束余地；配合 soft_max_chars=target*1.5 的续写
        # 软上限形成双保险（任一触发都不再扩张）。
        # 下限 900 token (~1350 字) 保证极短 target 也能完整写完一个段落；
        # 上限 4096 token 防止极端大 target 爆量。
        max_tokens = min(4096, max(900, int(target_words * 1.4)))
        soft_max_chars = min(int(target_words * 1.5), int(max_tokens * 1.4))
        polish_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = self.llm.chat(
            messages=polish_messages,
            temperature=0.7,
            max_tokens=max_tokens,
        )

        polished = self._continue_if_truncated(
            response, polish_messages, temperature=0.7, max_tokens=max_tokens,
            soft_max_chars=soft_max_chars,
        )

        # 后处理硬截：见 _trim_to_hard_cap docstring
        polished = self._trim_to_hard_cap(polished, hard_cap, target_words)

        return polished

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 场景去重
    # ------------------------------------------------------------------

    @staticmethod
    def _jaccard_similarity(text_a: str, text_b: str) -> float:
        """计算两段文本的段落级 Jaccard 相似度。

        将文本按句子切分，比较句子集合的重叠度。
        """
        import re as _re

        def _split_sentences(text: str) -> set[str]:
            # 按句号、感叹号、问号分句，过滤短句（< 6 字）
            sents = _re.split(r'[。！？!?\n]', text)
            return {s.strip() for s in sents if len(s.strip()) >= 6}

        set_a = _split_sentences(text_a)
        set_b = _split_sentences(text_b)

        if not set_a or not set_b:
            return 0.0

        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union) if union else 0.0

    def _deduplicate_paragraphs(
        self, new_text: str, previous_texts: list[str]
    ) -> str:
        """分级去重：区分"照搬"和"正常承接"。

        三级处理：
        - ≥60% 句子完全相同 → 删除整段（确定是照搬废段）
        - ≥40% 句子重复 → 只剥离重复句，保留独有内容（混合段）
        - <40% → 不处理（正常的叙事呼应和承接）
        """
        if not previous_texts:
            return new_text

        # 合并所有前文
        all_previous = "\n\n".join(previous_texts)

        import re as _re
        prev_sentences = set()
        for sent in _re.split(r'[。！？!?\n]', all_previous):
            s = sent.strip()
            if len(s) >= 6:
                prev_sentences.add(s)

        if not prev_sentences:
            return new_text

        # 按段落分级处理
        paragraphs = new_text.split("\n\n")
        kept = []
        hard_deleted = 0
        stripped = 0

        for para in paragraphs:
            # 拆句
            raw_sentences = _re.split(r'(?<=[。！？!?\n])', para)
            para_sentences = {
                s.strip()
                for s in _re.split(r'[。！？!?\n]', para)
                if len(s.strip()) >= 6
            }

            if not para_sentences:
                kept.append(para)
                continue

            overlap = para_sentences & prev_sentences
            ratio = len(overlap) / len(para_sentences)

            if ratio >= _DEDUP_HARD_DELETE:
                # 级别1: 照搬 → 整段删除
                hard_deleted += 1
                log.warning(
                    "去重[删除]：整段照搬前文（%d/%d句重复，%.0f%%）",
                    len(overlap), len(para_sentences), ratio * 100,
                )
                continue

            elif ratio >= _DEDUP_STRIP_OVERLAP:
                # 级别2: 混合段 → 只剥离重复句，保留独有内容
                unique_parts = []
                for raw_sent in raw_sentences:
                    clean = raw_sent.strip()
                    # 检查这个句子片段是否包含重复句
                    sent_core = _re.sub(r'[。！？!?\n]', '', clean).strip()
                    if len(sent_core) >= 6 and sent_core in overlap:
                        continue  # 跳过重复句
                    if clean:
                        unique_parts.append(clean)
                if unique_parts:
                    stripped += 1
                    kept.append("".join(unique_parts))
                    log.info(
                        "去重[剥离]：保留独有内容，移除%d句重复",
                        len(overlap),
                    )
                else:
                    hard_deleted += 1
                continue

            else:
                # 级别3: 正常呼应 → 保留
                kept.append(para)

        if hard_deleted > 0 or stripped > 0:
            log.info(
                "场景去重完成：删除%d段，剥离%d段",
                hard_deleted, stripped,
            )

        return "\n\n".join(kept)

    # ------------------------------------------------------------------
    # 角色名称校验 + 占位符替换
    # ------------------------------------------------------------------

    @staticmethod
    def _check_character_names(
        text: str, characters: list[CharacterProfile]
    ) -> str:
        """检测并修复场景文本中的角色名称问题。

        三层校验：
        1. 检测占位符（角色A、女学生B、老人C 等），替换为已知角色名
        2. 扫描对话引语中的未知人名，记录警告
        3. 检测中文人名模式，发现白名单外的新名字时警告
        """
        import re as _re

        if not text or not characters:
            return text

        # 构建合法名称集合（名字 + 别名）
        known_names: set[str] = set()
        for c in characters:
            known_names.add(c.name)
            if c.alias:
                known_names.update(c.alias)

        # --- 层1: 占位符检测与替换 ---
        placeholder_pattern = _re.compile(
            r'(?:角色|人物|女学生|男学生|学生|老人|男子|女子|男人|女人|少年|少女|青年)'
            r'[A-Za-z0-9甲乙丙丁]'
        )
        placeholders_found = placeholder_pattern.findall(text)
        if placeholders_found:
            log.warning(
                "角色名校验：检测到占位符称呼 %s，应使用具体角色名",
                placeholders_found,
            )
            for ph in set(placeholders_found):
                type_keyword = _re.sub(r'[A-Za-z0-9甲乙丙丁]$', '', ph)
                candidates = []
                for c in characters:
                    if type_keyword in ("女学生", "学生", "少女") and c.gender == "女":
                        candidates.append(c.name)
                    elif type_keyword in ("男学生", "学生", "少年") and c.gender == "男":
                        candidates.append(c.name)
                    elif type_keyword in ("老人",) and c.age >= 55:
                        candidates.append(c.name)
                    elif type_keyword in ("男子", "男人", "青年") and c.gender == "男":
                        candidates.append(c.name)
                    elif type_keyword in ("女子", "女人") and c.gender == "女":
                        candidates.append(c.name)
                if len(candidates) == 1:
                    text = text.replace(ph, candidates[0])
                    log.info("角色名校验：占位符「%s」→「%s」", ph, candidates[0])

        # --- 层2: 未知人名检测 ---
        # 扫描"X说"、"X问"、"X喊"等对话引语模式中的人名
        # 以及"X走"、"X看"等动作主语
        dialogue_name_pattern = _re.compile(
            r'(?:^|[。！？!?\n""\s])([^\s。！？!?\n""]{1,4})'
            r'(?:说|问|喊|叫|答|道|笑|哭|吼|嚷|叹|骂|低声|冷笑|咬牙|转身|走|站|蹲|跑|看|盯|抬头|回头)'
        )
        # 排除常见非人名的词
        _NOT_NAMES = {
            "他", "她", "它", "我", "你", "谁", "这", "那", "什么",
            "大家", "所有人", "众人", "两人", "三人", "几个人",
            "对方", "自己", "彼此", "有人", "没人", "别人",
            "然后", "突然", "忽然", "于是", "但是", "因为",
            "一个", "两个", "这个", "那个",
        }

        matches = dialogue_name_pattern.findall(text)
        unknown_names: set[str] = set()
        # 代词前缀集合（单字）：若候选以这些字开头，说明整体是"代词+动词"而非人名
        # 例：「他低头」「她抬头」「我转身」——剥掉代词前缀后剩下的是动词短语，应整体跳过
        _PRONOUN_PREFIXES = {"他", "她", "它", "我", "你"}
        # Unicode 弯引号 + ASCII 直引号 + CJK 括号；用 \uXXXX 转义避免编辑器字体渲染歧义
        _QUOTE_STRIP = (
            '"\''  # ASCII straight quotes
            '\u201c\u201d\u2018\u2019'  # "" '' curly quotes (Unicode)
            '\u300c\u300d\u300e\u300f\u3010\u3011'  # 「」『』【】
        )
        for name_candidate in matches:
            # 剥离候选前后的引号/括号字符
            name_candidate = name_candidate.strip(_QUOTE_STRIP)
            if not name_candidate or len(name_candidate) < 2:
                continue
            if name_candidate in _NOT_NAMES:
                continue
            # 代词前缀剥离：若候选以单字代词开头，剥掉后再看。
            # 剥完 < 2 字说明是纯"代词+单字动词"，整体跳过。
            # 剥完 >= 2 字则是"代词+双字动词"（如「他低头」→「低头」），
            # 这类同样不是人名 —— 直接跳过整个候选，不当作未知名字报警。
            if name_candidate[0] in _PRONOUN_PREFIXES:
                continue
            # 检查是否在已知名称中（含部分匹配：如"陈工"匹配"陈远"）
            is_known = False
            for kn in known_names:
                if name_candidate == kn or name_candidate in kn or kn in name_candidate:
                    is_known = True
                    break
            if not is_known:
                # 排除职业称呼（收银员、保安、老板等）
                if not _re.match(
                    r'^(?:收银员|保安|老板|司机|医生|护士|警察|服务员|店员|摊主|老头|中年|年轻)',
                    name_candidate,
                ):
                    unknown_names.add(name_candidate)

        if unknown_names:
            log.warning(
                "角色名校验：检测到白名单外的角色名 %s（合法名单：%s）",
                unknown_names, known_names,
            )

        return text

    # ------------------------------------------------------------------
    # 角色档案构建（完整版，含外貌锁定）
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
            )
            # 外貌锁定：每次都包含完整外貌描述，防止角色漂移
            if c.appearance:
                app = c.appearance
                desc += (
                    f"  外貌：身高{app.height}，{app.build}体型，"
                    f"{app.hair}，{app.eyes}，{app.clothing_style}"
                )
                if app.distinctive_features:
                    desc += f"，特征：{'、'.join(app.distinctive_features)}"
                desc += "\n"
            desc += (
                f"  性格：{traits}\n"
                f"  说话风格：{speech}\n"
                f"  核心信念：{c.personality.core_belief}\n"
                f"  缺陷：{c.personality.flaw}"
            )
            if c.personality.catchphrases:
                desc += f"\n  口头禅：{'、'.join(c.personality.catchphrases)}"
            # 角色弧线锁定
            if c.character_arc:
                desc += f"\n  初始状态：{c.character_arc.initial_state}"
                desc += f"\n  最终状态：{c.character_arc.final_state}"
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
    llm_config = get_stage_llm_config(state, "scene_writing")
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

    # Read budget mode from state
    budget_mode_writer = state.get("budget_mode", False)
    feedback_prompt = state.get("feedback_prompt", "")
    debt_summary = state.get("debt_summary", "")
    continuity_brief = state.get("continuity_brief", "")

    # Priority: current chapter rewrite feedback > previous chapter feedback
    current_rewrite = state.get("current_chapter_rewrite_prompt", "")
    if current_rewrite:
        feedback_prompt = current_rewrite  # Override with rewrite-specific feedback
    elif not feedback_prompt:
        # Get feedback from previous chapter via FeedbackInjector if not already set
        feedback_injector = state.get("feedback_injector")
        novel_id = state.get("novel_id", "")
        if feedback_injector and novel_id:
            try:
                feedback_prompt = feedback_injector.get_feedback_prompt(
                    novel_id, current_chapter
                )
            except Exception:
                log.debug("Failed to get feedback prompt", exc_info=True)

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

    # 设置章节任务书
    ch_outline_for_brief = state.get("current_chapter_outline")
    if ch_outline_for_brief and isinstance(ch_outline_for_brief, dict):
        chapter_brief = ch_outline_for_brief.get("chapter_brief")
        if chapter_brief and isinstance(chapter_brief, dict):
            writer.set_chapter_brief(chapter_brief)

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

    # 前文衔接：用 chapter_brief 的结构化摘要，不再读上章原文（防 verbatim 复读）
    # chapter_planner_node 写入两个位置：current_chapter_brief (Pydantic dump) +
    # current_chapter_outline.chapter_brief (legacy dict)。优先取前者，fallback 后者。
    context = ""
    if current_chapter > 1:
        brief = (
            state.get("current_chapter_brief")
            or (state.get("current_chapter_outline") or {}).get("chapter_brief")
            or state.get("chapter_brief")
            or {}
        )
        tail_summary = str(brief.get("previous_chapter_tail_summary", "") or "").strip()
        end_hook = str(brief.get("previous_chapter_end_hook", "") or "").strip()
        parts = []
        if tail_summary:
            parts.append(f"上章结尾状态：{tail_summary}")
        if end_hook:
            parts.append(f"上章钩子：{end_hook}")
        context = "\n".join(parts)

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
            debt_summary=debt_summary,
            budget_mode=budget_mode_writer,
            feedback_prompt=feedback_prompt,
            continuity_brief=continuity_brief,
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
