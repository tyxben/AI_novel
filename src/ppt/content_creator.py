"""内容创作器 - 阶段3：为每页生成精炼文案"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.agents.utils import extract_json_obj
from src.llm import LLMClient, create_llm_client
from src.ppt.models import (
    ColumnItem,
    ContentBlock,
    ContentMap,
    DocumentAnalysis,
    IconItem,
    LayoutType,
    SlideContent,
    SlideOutline,
    TimelineStep,
    Tone,
)

try:
    from src.ppt.models import DeckType, ImageStrategy, PageRole
except ImportError:  # pragma: no cover
    DeckType = None  # type: ignore[assignment,misc]
    PageRole = None  # type: ignore[assignment,misc]
    ImageStrategy = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# 字段长度软限制（超过则触发精炼）
# ---------------------------------------------------------------------------

_LIMIT_TITLE = 25
_LIMIT_SUBTITLE = 60
_LIMIT_BULLET = 60
_LIMIT_BODY_TEXT = 80
_LIMIT_DATA_VALUE = 20  # 硬截断，纯数字无需精炼
_LIMIT_DATA_LABEL = 30
_LIMIT_DATA_DESC = 50
_LIMIT_QUOTE = 150
_LIMIT_QUOTE_AUTHOR = 30  # 硬截断，人名无需精炼
_LIMIT_COL_SUBTITLE = 20
_LIMIT_COL_DESC = 60
_LIMIT_STEP_LABEL = 20  # 硬截断，标签无需精炼
_LIMIT_STEP_DESC = 50
_LIMIT_ICON_TEXT = 60
_LIMIT_COMPARE_TITLE = 20
_LIMIT_COMPARE_ITEM = 60
_LIMIT_CONTACT = 100  # 硬截断，联系信息无需精炼

log = logging.getLogger("ppt")

# ---------------------------------------------------------------------------
# AI 味黑名单词汇
# ---------------------------------------------------------------------------

AI_BLACKLIST: list[str] = [
    "赋能",
    "闭环",
    "抓手",
    "打通",
    "沉淀",
    "拉通",
    "对齐",
    "颗粒度",
    "组合拳",
    "落地",
    "串联",
    "解耦",
    "反哺",
    "全链路",
    "底层逻辑",
    "顶层设计",
    "方法论",
    "新赛道",
    "护城河",
    "生态位",
    "心智",
    "认知差",
    "势能",
    "深耕",
    "精准",
    "高效",
    "全方位",
    "多维度",
    "一站式",
    "智能化",
    "数字化转型",
]

# 替换映射：黑名单词 -> 更自然的表达
_AI_REPLACEMENTS: dict[str, str] = {
    "赋能": "帮助",
    "闭环": "完整流程",
    "抓手": "切入点",
    "打通": "连接",
    "沉淀": "积累",
    "拉通": "协调",
    "对齐": "统一",
    "颗粒度": "细节程度",
    "组合拳": "组合策略",
    "落地": "实施",
    "串联": "连接",
    "解耦": "分离",
    "反哺": "回馈",
    "全链路": "全流程",
    "底层逻辑": "核心原理",
    "顶层设计": "整体规划",
    "方法论": "方法",
    "新赛道": "新方向",
    "护城河": "竞争壁垒",
    "生态位": "市场定位",
    "心智": "认知",
    "认知差": "信息差",
    "势能": "潜力",
    "深耕": "专注于",
    "精准": "准确",
    "高效": "快速",
    "全方位": "各方面",
    "多维度": "多角度",
    "一站式": "综合",
    "智能化": "自动化",
    "数字化转型": "数字化升级",
}


# ---------------------------------------------------------------------------
# 每种布局的 prompt 模板和 JSON schema 说明
# ---------------------------------------------------------------------------

_LAYOUT_PROMPTS: dict[LayoutType, str] = {
    LayoutType.TITLE_HERO: """\
这是封面页。生成一个简洁有力的主标题和副标题。
- 主标题：精炼到10字以内，有冲击力
- 副标题：20字以内，概括核心价值
- 不要用"大家好"、"今天我来分享"这种开头

返回 JSON：
{{"title": "主标题", "subtitle": "副标题", "speaker_notes": "开场白..."}}""",
    LayoutType.SECTION_DIVIDER: """\
这是章节分隔页，只需要一个章节标题。
- 标题：精炼到8字以内，简洁有力
- 不需要要点

返回 JSON：
{{"title": "章节标题", "speaker_notes": "过渡语..."}}""",
    LayoutType.TEXT_LEFT_IMAGE_RIGHT: """\
这是左文右图页。为这一页写标题和3-5条要点。

要求：
- 标题：精炼到15字以内，信息量高
- 每条要点：30-50字，一句话说清一个核心信息
- 要点要有具体数据、事实、对比，不要空泛描述
- 不要用"首先/其次/最后"格式

返回 JSON：
{{"title": "标题", "bullet_points": ["要点1", "要点2", "要点3"], "speaker_notes": "解说词..."}}""",
    LayoutType.IMAGE_LEFT_TEXT_RIGHT: """\
这是左图右文页。为这一页写标题和3-5条要点。

要求：
- 标题：精炼到15字以内，信息量高
- 每条要点：30-50字，一句话说清一个核心信息
- 要点要有具体数据、事实、对比，不要空泛描述

返回 JSON：
{{"title": "标题", "bullet_points": ["要点1", "要点2", "要点3"], "speaker_notes": "解说词..."}}""",
    LayoutType.FULL_IMAGE_OVERLAY: """\
这是全屏图片叠加文字页。生成标题和一句短文。
- 标题：精炼到10字以内，有冲击力
- 短文：不超过30字，作为图片上的叠加文字

返回 JSON：
{{"title": "标题", "body_text": "一句短文", "speaker_notes": "解说词..."}}""",
    LayoutType.THREE_COLUMNS: """\
这是三栏并列页。生成标题和3组子标题+描述。
- 标题：精炼到15字以内
- 每组子标题：精炼到8字以内
- 每组描述：精炼到40字以内，要有具体信息

返回 JSON：
{{"title": "标题", "columns": [{{"subtitle": "子标题1", "description": "描述1"}}, {{"subtitle": "子标题2", "description": "描述2"}}, {{"subtitle": "子标题3", "description": "描述3"}}], "speaker_notes": "解说词..."}}""",
    LayoutType.QUOTE_PAGE: """\
这是引用/金句页。从原文中找到最有力、最能打动人的一句话。
- 引用要真实来自原文，不要编造
- 如果原文没有适合引用的句子，提炼一句核心观点（50字以内）
- 注明引用来源

返回 JSON：
{{"title": "引用页标题", "quote": "引用原文...", "quote_author": "来源", "speaker_notes": "解说词..."}}""",
    LayoutType.DATA_HIGHLIGHT: """\
这是数据突出页。从文档中找到最重要的一个数字。
- 数字要醒目（如"30%"、"500亿"、"3倍"）
- 标签：精炼到10字以内，简短说明这个数字是什么
- 补充说明：精炼到30字以内

返回 JSON：
{{"title": "标题", "data_value": "30%", "data_label": "市场增长率", "data_description": "超出行业平均水平2倍", "speaker_notes": "解说词..."}}""",
    LayoutType.TIMELINE: """\
这是时间线/流程页。生成标题和3-5个步骤。
- 标题：精炼到15字以内
- 每个步骤标签：精炼到8字以内
- 每个步骤描述：精炼到30字以内，要有具体信息
- 步骤要有逻辑顺序

返回 JSON：
{{"title": "标题", "steps": [{{"label": "第一步", "description": "描述"}}, {{"label": "第二步", "description": "描述"}}, {{"label": "第三步", "description": "描述"}}], "speaker_notes": "解说词..."}}""",
    LayoutType.BULLET_WITH_ICONS: """\
这是图标要点页。生成标题和3-5个带图标关键词的要点。
- 标题：精炼到15字以内
- 每个要点配一个英文图标关键词（如 chart, team, rocket, shield, clock, target, star）
- 每条要点：30-50字，一句话说清一个核心信息

返回 JSON：
{{"title": "标题", "icon_items": [{{"icon_keyword": "chart", "text": "要点1"}}, {{"icon_keyword": "team", "text": "要点2"}}], "speaker_notes": "解说词..."}}""",
    LayoutType.COMPARISON: """\
这是对比页。生成标题和左右两栏对比内容。
- 标题：精炼到15字以内
- 左右栏标题：各8字以内
- 左右栏各3-4个要点，每条30-50字
- 要点要对仗，形成鲜明对比

返回 JSON：
{{"title": "标题", "left_title": "方案A", "left_items": ["要点1", "要点2", "要点3"], "right_title": "方案B", "right_items": ["要点1", "要点2", "要点3"], "speaker_notes": "解说词..."}}""",
    LayoutType.CLOSING: """\
这是结束页。生成感谢语和联系信息提示。
- 标题：简洁有力，如"谢谢"、"期待合作"
- 副标题：可选，简短总结
- 联系信息用占位符

返回 JSON：
{{"title": "谢谢", "subtitle": "副标题", "contact_info": "联系方式", "speaker_notes": "结束语..."}}""",
}


class ContentCreator:
    """为每页PPT生成精炼的文案内容"""

    AI_BLACKLIST = AI_BLACKLIST

    def __init__(self, config: dict):
        """创建 LLM client。

        Args:
            config: 项目配置字典，需包含 ``llm`` 子键。
        """
        self.llm: LLMClient = create_llm_client(config.get("llm", {}))

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def create(
        self,
        text: str,
        outlines: list[SlideOutline],
        content_map: ContentMap | None = None,
        deck_type: "DeckType | None" = None,
    ) -> list[SlideContent]:
        """为每页生成内容。

        Args:
            text: 原始文档全文。
            outlines: 每页的大纲信息列表。
            content_map: 结构化内容地图（可选）。提供后将按
                ``SlideOutline.content_block_ids`` 精准关联原文内容块，
                生成质量显著优于按位置切分。
            deck_type: PPT 类型（可选）。提供后将使用模式专属的
                写作风格和约束。

        Returns:
            与 *outlines* 等长的 ``SlideContent`` 列表。
        """
        results: list[SlideContent] = []
        total_pages = len(outlines)
        for outline in outlines:
            try:
                content = self._create_single_slide(
                    text,
                    outline,
                    total_pages,
                    content_map=content_map,
                    deck_type=deck_type,
                )
            except Exception:
                log.exception(
                    "第%d页内容生成失败，使用大纲信息兜底", outline.page_number
                )
                content = SlideContent(
                    title=outline.title or "未命名",
                    subtitle=outline.subtitle,
                    bullet_points=outline.key_points[:5],
                    speaker_notes=outline.speaker_notes_hint,
                )
            results.append(content)
        return results

    # ------------------------------------------------------------------
    # AI 味过滤
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_ai_taste(text: str) -> str:
        """过滤 AI 味词汇，替换为更自然的表达。"""
        if not text:
            return text
        for word, replacement in _AI_REPLACEMENTS.items():
            text = text.replace(word, replacement)
        return text

    # ------------------------------------------------------------------
    # 文本精炼：规则 → LLM 两级策略
    # ------------------------------------------------------------------

    @staticmethod
    def _condense(text: str, max_chars: int) -> str | None:
        """纯规则精炼。成功返回精炼后文本，无法处理返回 None。

        策略：
        1. 如果文本有多个句子（。！？），取前 N 句直到不超过上限
        2. 如果只有一个句子但有分句（，；、），取前 N 个分句 + "..."
        3. 如果是一个不可分割的长句，返回 None 交给 LLM
        """
        if not text or len(text) <= max_chars:
            return text

        # 策略1：按句号/问号/感叹号分句，取前 N 句
        sentences = re.split(r"(?<=[。！？])", text)
        sentences = [s for s in sentences if s.strip()]
        if len(sentences) > 1:
            result = ""
            for s in sentences:
                if len(result) + len(s) <= max_chars:
                    result += s
                else:
                    break
            if result:
                return result

        # 策略2：按逗号/分号/顿号分句，取前 N 个分句
        clauses = re.split(r"(?<=[，；、])", text)
        clauses = [c for c in clauses if c.strip()]
        if len(clauses) > 1:
            result = ""
            for c in clauses:
                candidate = result + c
                if len(candidate) <= max_chars - 3:  # 留空间给 "..."
                    result = candidate
                else:
                    break
            if result:
                return result.rstrip("，；、") + "..."

        # 策略3：无法用规则处理
        return None

    def _summarize(self, text: str, max_chars: int) -> str:
        """让 LLM 精炼长文本到指定字数内。"""
        if not text or len(text) <= max_chars:
            return text

        messages = [
            {
                "role": "system",
                "content": (
                    "你是文案精炼专家。将文本精炼为更简洁的表达，"
                    "保留核心信息和关键数据，不丢失重要事实。"
                    "直接输出精炼后的文本，不要加引号或额外说明。"
                ),
            },
            {
                "role": "user",
                "content": f"请将以下文本精炼到{max_chars}字以内：\n\n{text}",
            },
        ]
        response = self.llm.chat(messages, temperature=0.3, max_tokens=256)
        result = response.content.strip().strip('"\'')
        # 最终安全网
        if len(result) > max_chars:
            result = result[:max_chars]
        return result

    def _smart_trim(self, text: str, max_chars: int) -> str:
        """智能精炼：先规则，规则不行再 LLM。"""
        if not text or len(text) <= max_chars:
            return text
        condensed = self._condense(text, max_chars)
        if condensed is not None:
            return condensed
        return self._summarize(text, max_chars)

    # ------------------------------------------------------------------
    # 模式专属 prompt 构建
    # ------------------------------------------------------------------

    # PageRole -> 页面角色专属内容提示
    _PAGE_ROLE_HINTS: dict[str, str] = {
        "executive_summary": "这是摘要页，30秒内让读者抓住结论。3条要点，每条一个关键信息。",
        "data_evidence": "这是数据页，找出最有说服力的数字，大字展示。",
        "pain_point": "这是痛点页，描述用户的真实困境，让读者产生共鸣。",
        "knowledge_point": "这是知识点页，先用例子引入，再给定义，最后强调关键。",
        "cover": "这是封面页，标题要有冲击力，副标题概括核心价值。",
        "progress": "这是进展页，用具体数字和状态说明进度，避免模糊描述。",
        "risk_problem": "这是风险/问题页，清晰列出问题和影响，不要弱化。",
        "solution": "这是解决方案页，每个方案对应一个具体问题，说清行动和预期效果。",
        "next_steps": "这是下一步行动页，列出具体任务、负责人和时间节点。",
        "learning_objectives": "这是学习目标页，用'学完本节你将能够...'的句式。",
        "concept_intro": "这是概念引入页，先用生活中的类比解释，再给正式定义。",
        "example_case": "这是案例页，讲清背景、做法和结果，让读者能复用。",
        "method_steps": "这是方法/步骤页，每步一个动作，用动词开头。",
        "common_mistakes": "这是常见错误页，列出典型错误和正确做法的对比。",
        "summary_review": "这是总结回顾页，提炼3-5个核心要点，帮助记忆。",
        "exercise": "这是练习页，设计一个能验证理解的实践任务。",
        "market_opportunity": "这是市场机会页，用数据说明市场规模和增长趋势。",
        "product_overview": "这是产品概览页，一句话说清产品是什么、为谁解决什么问题。",
        "core_features": "这是核心功能页，每个功能对应一个用户价值。",
        "use_case": "这是使用场景页，描述具体的用户场景和使用前后对比。",
        "competitive_advantage": "这是竞争优势页，用对比说明差异化，避免自说自话。",
        "case_data": "这是客户案例/数据页，用真实数据证明效果。",
        "business_model": "这是商业模式页，说清楚谁付费、为什么付费、怎么赚钱。",
        "cta": "这是行动号召页，给出一个明确的下一步行动，降低行动门槛。",
        "section_break": "这是章节过渡页，承上启下，一句话预告下一部分。",
        "closing": "这是结束页，简洁有力，留下深刻印象。",
        "background": "这是背景页，简要交代上下文，为后续内容做铺垫。",
    }

    def _build_system_prompt(
        self,
        deck_type: "DeckType | None",
        outline: SlideOutline,
    ) -> str:
        """Build mode-specific system prompt based on deck type and page role."""
        # Base prompt part
        base = "你是一位顶尖的 PPT 文案撰写师。"

        if DeckType is not None and deck_type == DeckType.BUSINESS_REPORT:
            style = (
                "你在为管理层写汇报材料。\n"
                "核心原则：\n"
                "1. 结论优先 — 先说结果，再说过程\n"
                "2. 用事实句 — 每句话包含时间、数字、状态\n"
                "3. 少形容词 — '完成率85%'比'进展顺利'好100倍\n"
                "4. 行动导向 — 每页要回答'so what'\n\n"
                "正确：'本月完成3项核心交付，延期1项（供应商原因，预计下周解决）'\n"
                "错误：'项目持续高效推进，各项工作有序开展'\n\n"
            )
        elif DeckType is not None and deck_type == DeckType.COURSE_LECTURE:
            style = (
                "你在为学员写课程讲义。\n"
                "核心原则：\n"
                "1. 术语必须解释 — 不假设学员已知任何术语\n"
                "2. 例子先行 — 先举例再给定义\n"
                "3. 一页一个知识点 — 不堆砌\n"
                "4. 递进关系 — 这页的内容要承接上一页\n\n"
                "正确：'缓存就像你把常用电话号码写在便签上，不用每次都翻通讯录'\n"
                "错误：'缓存是计算机系统中重要的性能优化机制'\n\n"
            )
        elif DeckType is not None and deck_type == DeckType.PRODUCT_INTRO:
            style = (
                "你在为潜在客户写产品介绍。\n"
                "核心原则：\n"
                "1. 以用户价值为中心 — 不是'我们有什么'，而是'你能得到什么'\n"
                "2. 功能对应收益 — 每个功能都要回答'这对用户意味着什么'\n"
                "3. 场景化表达 — 用'想象一下...'、'当你遇到...'\n"
                "4. 数据说服 — '节省60%时间'比'大幅提升效率'有说服力\n\n"
                "正确：'3步完成数据分析，2小时的工作现在只需5分钟'\n"
                "错误：'采用先进AI算法，具有强大数据处理能力'\n\n"
            )
        else:
            style = "你的文案简洁有力、数据具体、语言有温度。\n"

        # Add page-specific constraints from SlideOutline
        page_constraints = ""
        page_role = getattr(outline, "page_role", None)
        page_goal = getattr(outline, "page_goal", "")
        must_include = getattr(outline, "must_include", [])
        forbidden = getattr(outline, "forbidden_content", [])

        if page_goal:
            page_constraints += f"\n本页目标：{page_goal}\n"
        if must_include:
            page_constraints += f"本页必须包含：{'、'.join(must_include)}\n"
        if forbidden:
            page_constraints += f"本页禁止出现：{'、'.join(forbidden)}\n"

        # Anti AI-taste
        blacklist = (
            "绝对不使用以下词汇："
            + "、".join(self.AI_BLACKLIST[:15])
            + "等。"
        )

        return base + style + page_constraints + blacklist

    def _get_notes_instruction(self, deck_type: "DeckType | None") -> str:
        """Return deck-type-specific speaker notes instruction."""
        if DeckType is not None and deck_type == DeckType.BUSINESS_REPORT:
            return "演讲备注：50-100字，简洁直接，像在向领导汇报。"
        elif DeckType is not None and deck_type == DeckType.COURSE_LECTURE:
            return "演讲备注：200-300字，口语化，包含'怎么讲'的提示和过渡语。"
        elif DeckType is not None and deck_type == DeckType.PRODUCT_INTRO:
            return "演讲备注：100-200字，有感染力，包含与受众的互动提示。"
        else:
            return "演讲备注：200-300字，口语化，像在对听众说话。"

    def _get_page_role_hint(self, outline: SlideOutline) -> str:
        """Return extra guidance based on page_role, if available."""
        page_role = getattr(outline, "page_role", None)
        if page_role is None:
            return ""
        role_value = page_role.value if hasattr(page_role, "value") else str(page_role)
        hint = self._PAGE_ROLE_HINTS.get(role_value, "")
        if hint:
            return f"\n页面角色提示：{hint}\n"
        return ""

    # ------------------------------------------------------------------
    # 单页内容生成
    # ------------------------------------------------------------------

    def _create_single_slide(
        self,
        text: str,
        outline: SlideOutline,
        total_pages: int,
        *,
        content_map: ContentMap | None = None,
        deck_type: "DeckType | None" = None,
    ) -> SlideContent:
        """为单页生成内容。"""
        layout = outline.layout

        # Build context: prefer content blocks, fallback to position-based
        block_ids: list[str] = getattr(outline, "content_block_ids", None) or []
        if content_map and block_ids:
            relevant_context = self._build_context_from_blocks(
                content_map, block_ids
            )
            content_source_hint = (
                "以下是从文档中精准提取的内容块，请基于这些内容撰写 PPT 文案。\n"
                "所有要点必须来自提供的内容，不要编造事实。"
            )
        else:
            relevant_context = self._extract_relevant_chunk(
                text, outline.page_number, total_pages
            )
            content_source_hint = "原文相关片段："

        layout_instruction = _LAYOUT_PROMPTS.get(
            layout, _LAYOUT_PROMPTS[LayoutType.TEXT_LEFT_IMAGE_RIGHT]
        )

        system_msg = self._build_system_prompt(deck_type, outline)

        notes_instruction = self._get_notes_instruction(deck_type)
        page_role_hint = self._get_page_role_hint(outline)

        user_msg = f"""\
请为第 {outline.page_number} 页（布局: {layout.value}）撰写 PPT 文案。

页面大纲标题：{outline.title}
大纲要点：{', '.join(outline.key_points) if outline.key_points else '无'}
{page_role_hint}
{content_source_hint}
{relevant_context}

{layout_instruction}

{notes_instruction}不要念稿式。"""

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
        response = self.llm.chat(
            messages, temperature=0.7, json_mode=True, max_tokens=2048
        )

        data = extract_json_obj(response.content)
        if data is None:
            log.warning("第%d页 LLM 返回非 JSON，尝试兜底", outline.page_number)
            return SlideContent(
                title=outline.title or "未命名",
                bullet_points=outline.key_points[:5],
                speaker_notes="",
            )

        return self._parse_content(data, layout)

    # ------------------------------------------------------------------
    # 解析 + 后处理
    # ------------------------------------------------------------------

    def _parse_content(
        self, data: dict[str, Any], layout: LayoutType
    ) -> SlideContent:
        """将 LLM 返回的 JSON 解析为 SlideContent，并做后处理。

        精炼策略（取代硬截断）：
        - 短标识类字段（data_value, step_label, quote_author, contact_info）：
          仍用硬截断（纯标识无需语义精炼）
        - 其他文本字段：超过软限制时先用规则精炼，规则不行再调 LLM
        """
        # 通用字段
        raw_title = self._filter_ai_taste(str(data.get("title", "未命名")))
        title = self._smart_trim(raw_title, _LIMIT_TITLE)

        subtitle = data.get("subtitle")
        if subtitle:
            raw_sub = self._filter_ai_taste(str(subtitle))
            subtitle = self._smart_trim(raw_sub, _LIMIT_SUBTITLE)

        speaker_notes = self._filter_ai_taste(
            str(data.get("speaker_notes", ""))
        )
        body_text = data.get("body_text")
        if body_text:
            raw_body = self._filter_ai_taste(str(body_text))
            body_text = self._smart_trim(raw_body, _LIMIT_BODY_TEXT)

        # 要点列表
        raw_bullets = data.get("bullet_points", [])
        bullet_points = [
            self._smart_trim(self._filter_ai_taste(str(b)), _LIMIT_BULLET)
            for b in raw_bullets
        ][:5]

        # 布局特有字段
        kwargs: dict[str, Any] = {
            "title": title,
            "subtitle": subtitle,
            "bullet_points": bullet_points,
            "body_text": body_text,
            "speaker_notes": speaker_notes,
        }

        if layout == LayoutType.DATA_HIGHLIGHT:
            kwargs["data_value"] = str(data.get("data_value", ""))[
                :_LIMIT_DATA_VALUE
            ]
            raw_label = self._filter_ai_taste(
                str(data.get("data_label", ""))
            )
            kwargs["data_label"] = self._smart_trim(
                raw_label, _LIMIT_DATA_LABEL
            )
            raw_desc = self._filter_ai_taste(
                str(data.get("data_description", ""))
            )
            kwargs["data_description"] = self._smart_trim(
                raw_desc, _LIMIT_DATA_DESC
            )

        elif layout == LayoutType.QUOTE_PAGE:
            raw_quote = self._filter_ai_taste(str(data.get("quote", "")))
            kwargs["quote"] = self._smart_trim(raw_quote, _LIMIT_QUOTE)
            kwargs["quote_author"] = str(data.get("quote_author", ""))[
                :_LIMIT_QUOTE_AUTHOR
            ]

        elif layout == LayoutType.THREE_COLUMNS:
            raw_cols = data.get("columns", [])
            columns = []
            for c in raw_cols[:3]:
                if isinstance(c, dict):
                    raw_csub = self._filter_ai_taste(
                        str(c.get("subtitle", ""))
                    )
                    raw_cdesc = self._filter_ai_taste(
                        str(c.get("description", ""))
                    )
                    columns.append(
                        ColumnItem(
                            subtitle=self._smart_trim(
                                raw_csub, _LIMIT_COL_SUBTITLE
                            ),
                            description=self._smart_trim(
                                raw_cdesc, _LIMIT_COL_DESC
                            ),
                        )
                    )
            kwargs["columns"] = columns

        elif layout == LayoutType.TIMELINE:
            raw_steps = data.get("steps", [])
            steps = []
            for s in raw_steps[:5]:
                if isinstance(s, dict):
                    raw_sdesc = self._filter_ai_taste(
                        str(s.get("description", ""))
                    )
                    steps.append(
                        TimelineStep(
                            label=str(s.get("label", ""))[
                                :_LIMIT_STEP_LABEL
                            ],
                            description=self._smart_trim(
                                raw_sdesc, _LIMIT_STEP_DESC
                            ),
                        )
                    )
            kwargs["steps"] = steps

        elif layout == LayoutType.BULLET_WITH_ICONS:
            raw_items = data.get("icon_items", [])
            icon_items = []
            for item in raw_items[:5]:
                if isinstance(item, dict):
                    raw_itext = self._filter_ai_taste(
                        str(item.get("text", ""))
                    )
                    icon_items.append(
                        IconItem(
                            icon_keyword=str(
                                item.get("icon_keyword", "star")
                            )[:20],
                            text=self._smart_trim(
                                raw_itext, _LIMIT_ICON_TEXT
                            ),
                        )
                    )
            kwargs["icon_items"] = icon_items

        elif layout == LayoutType.COMPARISON:
            raw_lt = self._filter_ai_taste(
                str(data.get("left_title", ""))
            )
            raw_rt = self._filter_ai_taste(
                str(data.get("right_title", ""))
            )
            kwargs["left_title"] = self._smart_trim(
                raw_lt, _LIMIT_COMPARE_TITLE
            )
            kwargs["right_title"] = self._smart_trim(
                raw_rt, _LIMIT_COMPARE_TITLE
            )
            kwargs["left_items"] = [
                self._smart_trim(
                    self._filter_ai_taste(str(i)), _LIMIT_COMPARE_ITEM
                )
                for i in data.get("left_items", [])
            ][:5]
            kwargs["right_items"] = [
                self._smart_trim(
                    self._filter_ai_taste(str(i)), _LIMIT_COMPARE_ITEM
                )
                for i in data.get("right_items", [])
            ][:5]

        elif layout == LayoutType.CLOSING:
            kwargs["contact_info"] = str(data.get("contact_info", ""))[
                :_LIMIT_CONTACT
            ]

        return SlideContent(**kwargs)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context_from_blocks(
        content_map: ContentMap,
        block_ids: list[str],
    ) -> str:
        """Build rich context for a slide from its bound content blocks.

        Returns a formatted string containing each matched block's type,
        title, summary, and original source text.  Blocks whose IDs are
        not found in *content_map* are silently skipped.
        """
        # Index blocks by id for O(1) lookup
        blocks_by_id: dict[str, ContentBlock] = {
            b.block_id: b for b in content_map.content_blocks
        }

        parts: list[str] = []
        for bid in block_ids:
            block = blocks_by_id.get(bid)
            if block is None:
                log.warning("content_block_id '%s' 在 ContentMap 中未找到，跳过", bid)
                continue
            part = (
                f"[{block.block_type}] {block.title}\n"
                f"摘要: {block.summary}\n"
                f"原文: {block.source_text}"
            )
            parts.append(part)

        if not parts:
            # All block_ids were missing — return thesis as minimal context
            return f"文档核心论点: {content_map.document_thesis}"

        return "\n\n".join(parts)

    @staticmethod
    def _extract_relevant_chunk(
        text: str, page_number: int, total_pages: int
    ) -> str:
        """从原文中提取与当前页相关的文本片段。

        策略：
        - 封面页(page 1) 和结束页(最后一页) → 全文摘要（前500字）
        - 中间内容页 → 按内容页序号均分段落，每页多取一些上下文
        """
        if not text:
            return ""
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
        if not paragraphs:
            return text[:3000]

        # 封面页和结束页：返回全文摘要
        if page_number == 1 or page_number == total_pages:
            return text[:500]

        # 内容页数（去掉封面和结束页）
        content_pages = max(total_pages - 2, 1)
        content_index = page_number - 2  # 0-based index for content pages

        # 每页覆盖的段落数（向上取整，确保覆盖所有段落）
        chunk_size = max(2, len(paragraphs) // content_pages)
        # 加上上下文重叠（前后各多取1段）
        start = max(0, content_index * chunk_size - 1)
        end = min(len(paragraphs), start + chunk_size + 2)
        chunk = "\n\n".join(paragraphs[start:end])
        return chunk[:3000] if chunk else text[:3000]
