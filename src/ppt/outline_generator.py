"""大纲生成器 - 阶段2：生成 PPT 大纲（页数、布局、要点）

两种模式：
1. plan-driven: 当有 PresentationPlan 时，直接从 plan 转换大纲，
   LLM 只填 title/key_points/image_prompt，结构完全由 plan 决定。
2. free-form: 无 plan 时，让 LLM 自由生成大纲（旧行为）。
"""

from __future__ import annotations

import logging

from src.agents.utils import extract_json_array, extract_json_obj
from src.llm.llm_client import LLMClient, create_llm_client
from src.ppt.models import (
    ContentMap,
    DocumentAnalysis,
    EditableOutline,
    EditableSlide,
    ImageStrategy,
    LayoutType,
    NarrativeSection,
    NarrativeStructure,
    PageRole,
    PresentationPlan,
    SlideOutline,
    SlideTask,
)

log = logging.getLogger("ppt")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 纯文字布局（没有图片的）
_TEXT_ONLY_LAYOUTS = frozenset({
    LayoutType.SECTION_DIVIDER,
    LayoutType.QUOTE_PAGE,
    LayoutType.DATA_HIGHLIGHT,
    LayoutType.CLOSING,
    LayoutType.BULLET_WITH_ICONS,
    LayoutType.THREE_COLUMNS,
    LayoutType.TIMELINE,
    LayoutType.COMPARISON,
})

# 图片布局
_IMAGE_LAYOUTS = frozenset({
    LayoutType.TITLE_HERO,
    LayoutType.TEXT_LEFT_IMAGE_RIGHT,
    LayoutType.IMAGE_LEFT_TEXT_RIGHT,
    LayoutType.FULL_IMAGE_OVERLAY,
})

# 每分钟演讲约覆盖 2 页
_PAGES_PER_MINUTE = 2

# ---------------------------------------------------------------------------
# PageRole → 默认布局映射（当 layout_preference 为 None 时使用）
# ---------------------------------------------------------------------------

_PAGE_ROLE_TO_LAYOUT: dict[str, LayoutType] = {
    "cover": LayoutType.TITLE_HERO,
    "executive_summary": LayoutType.BULLET_WITH_ICONS,
    "background": LayoutType.TEXT_LEFT_IMAGE_RIGHT,
    "progress": LayoutType.BULLET_WITH_ICONS,
    "data_evidence": LayoutType.DATA_HIGHLIGHT,
    "risk_problem": LayoutType.BULLET_WITH_ICONS,
    "solution": LayoutType.THREE_COLUMNS,
    "next_steps": LayoutType.TIMELINE,
    "learning_objectives": LayoutType.BULLET_WITH_ICONS,
    "concept_intro": LayoutType.TEXT_LEFT_IMAGE_RIGHT,
    "knowledge_point": LayoutType.TEXT_LEFT_IMAGE_RIGHT,
    "example_case": LayoutType.IMAGE_LEFT_TEXT_RIGHT,
    "method_steps": LayoutType.TIMELINE,
    "common_mistakes": LayoutType.COMPARISON,
    "summary_review": LayoutType.BULLET_WITH_ICONS,
    "exercise": LayoutType.BULLET_WITH_ICONS,
    "pain_point": LayoutType.FULL_IMAGE_OVERLAY,
    "market_opportunity": LayoutType.DATA_HIGHLIGHT,
    "product_overview": LayoutType.TEXT_LEFT_IMAGE_RIGHT,
    "core_features": LayoutType.THREE_COLUMNS,
    "use_case": LayoutType.IMAGE_LEFT_TEXT_RIGHT,
    "competitive_advantage": LayoutType.COMPARISON,
    "case_data": LayoutType.DATA_HIGHLIGHT,
    "business_model": LayoutType.BULLET_WITH_ICONS,
    "cta": LayoutType.CLOSING,
    "section_break": LayoutType.SECTION_DIVIDER,
    "closing": LayoutType.CLOSING,
}

# ---------------------------------------------------------------------------
# Plan-driven 模式的 LLM prompt
# ---------------------------------------------------------------------------

_PLAN_DRIVEN_SYSTEM_PROMPT = """\
你是一位资深 PPT 文案策划师。你收到的是一份已确定结构的演示计划，
你的任务是为每一页填写：标题、要点、图片描述。

## 核心要求

1. **标题必须是中文**，精炼有力，10-15字以内
2. **key_points 必须来自提供的内容块**，不要编造事实
3. **每条 key_points 20-50字**，是一句完整的信息点
4. **content_block_ids** 标明该页使用了哪些内容块
5. **image_prompt** 用英文，描述具体画面和风格
6. 不同页的标题不要重复
7. 每页 3-5 个 key_points

## 输出格式

返回 JSON 数组，与输入的页面一一对应：
[
  {
    "title": "中文标题",
    "subtitle": "中文副标题（可选，可为 null）",
    "key_points": ["要点1", "要点2", "要点3"],
    "content_block_ids": ["b1", "b2"],
    "image_prompt": "English image prompt or null",
    "speaker_notes_hint": "这页要传递的核心信息"
  },
  ...
]
"""

_SYSTEM_PROMPT = """\
你是一位 TED 演讲编排师和顶级 PPT 策划专家。你的任务是根据文档分析结果，
设计一份结构清晰、节奏感强、视觉多样的 PPT 大纲。

## 设计原则

1. **叙事弧线**：按照 "开场吸引 → 背景/问题 → 核心论述 → 数据/案例支撑 → 总结展望" 的结构编排
2. **每页一个核心信息**：每页只传递一个关键信息，不堆砌内容
3. **布局多样性**：不连续 3 页使用相同布局，文字页和图片页交替出现
4. **节奏感**：密集信息页之后接一个轻松的引用页或图片页，让观众"喘口气"
5. **数据突出**：重要数据用 data_highlight 布局单独展示，不埋在文字里
6. **内容完整**：key_points 要包含原文的核心信息，每条20-50字，必须是完整的信息点
7. **image_prompt 要具体**：不是"配一张图"，而是描述具体画面（英文）

## 可用的布局类型

- title_hero: 封面页（大标题+副标题+背景图）— 仅用于第1页
- section_divider: 章节分隔页（大标题居中）— 用于主题切换
- text_left_image_right: 左文右图（适合带配图的内容页）
- image_left_text_right: 左图右文（同上，换个方向增加变化）
- full_image_overlay: 全屏图+文字叠加（视觉冲击力强）
- three_columns: 三栏并列（适合对比、列举）
- quote_page: 引用/金句页（适合名言、核心观点）
- data_highlight: 数据突出展示（巨大数字+小字说明）
- timeline: 时间线/流程图
- bullet_with_icons: 要点+图标
- comparison: 对比页（A vs B）
- closing: 结束页（感谢+联系方式）— 仅用于最后一页

## 输出格式

请以 JSON 数组格式返回大纲，每页一个对象：
[
  {
    "page_number": 1,
    "slide_type": "title_hero",
    "layout": "title_hero",
    "title": "页面标题",
    "subtitle": "副标题（可选，可为 null）",
    "key_points": ["要点1（20-50字的完整信息）", "要点2"],
    "needs_image": true,
    "image_prompt": "English prompt for image generation, be specific about style and content",
    "speaker_notes_hint": "这页想传递的核心信息"
  },
  ...
]

## 示例大纲片段

假设原文是关于"2024年AI行业趋势报告"：
- 第1页 title_hero: "AI 重塑一切" — 副标题 "2024年人工智能行业趋势洞察"
- 第2页 section_divider: "市场全景"
- 第3页 data_highlight: 数字"5.2万亿" — 全球AI市场预估规模
- 第4页 text_left_image_right: "三大驱动力" — 大模型突破/算力下降/数据爆发
- 第5页 quote_page: "AI不是未来，AI就是现在" — Gartner 2024
- ...

## 规则

- 第1页必须是 title_hero（封面），标题要有冲击力
- 最后一页必须是 closing（结束页）
- section_divider 用于章节切换，不要连续出现两个
- quote_page 不超过总页数的 10%
- key_points 每条20-50字，3-5条，必须来自原文内容
- image_prompt 用英文，风格要具体（如 "minimalist blue tech background with data visualization elements, clean and professional"）
- 不要在每一页都放图片，文字页和图片页交替
- 标题不要重复，每页标题都应独特
"""

_CONTENT_MAP_SYSTEM_PROMPT = """\
你是一位 TED 演讲编排师和顶级 PPT 策划专家。

你的任务是基于已提取的结构化内容块，将它们编排为一份 PPT 大纲。
每页必须绑定 1-3 个具体的 content_block_id，确保内容有据可查、不编造。

## 编排原则

1. importance >= 4 的内容块必须出现在正文页中，不可遗漏
2. block_type 为 "data" 的内容块优先使用 data_highlight 布局
3. block_type 为 "quote" 的内容块优先使用 quote_page 布局
4. 按 logical_flow 建议的顺序编排内容
5. key_points 必须来自绑定的内容块的 summary，不要编造
6. 每页一个核心信息，不堆砌内容
7. 布局多样性：不连续 3 页使用相同布局
8. 节奏感：密集信息页之后穿插轻松的引用页或图片页
9. image_prompt 要具体，描述具体画面（英文）

## 可用的布局类型

- title_hero: 封面页（大标题+副标题+背景图）— 仅用于第1页
- section_divider: 章节分隔页（大标题居中）— 用于主题切换
- text_left_image_right: 左文右图（适合带配图的内容页）
- image_left_text_right: 左图右文（同上，换个方向增加变化）
- full_image_overlay: 全屏图+文字叠加（视觉冲击力强）
- three_columns: 三栏并列（适合对比、列举）
- quote_page: 引用/金句页（适合名言、核心观点）
- data_highlight: 数据突出展示（巨大数字+小字说明）
- timeline: 时间线/流程图
- bullet_with_icons: 要点+图标
- comparison: 对比页（A vs B）
- closing: 结束页（感谢+联系方式）— 仅用于最后一页

## 规则

- 第1页必须是 title_hero（封面），标题要有冲击力
- 最后一页必须是 closing（结束页）
- section_divider 用于章节切换，不要连续出现两个
- quote_page 不超过总页数的 10%
- key_points 每条20-50字，3-5条，必须来自绑定的内容块
- image_prompt 用英文，风格要具体
- 不要在每一页都放图片，文字页和图片页交替
- 标题不要重复，每页标题都应独特

## 输出格式

请以 JSON 数组格式返回大纲，每页一个对象：
[
  {
    "page_number": 1,
    "slide_type": "title_hero",
    "layout": "title_hero",
    "title": "页面标题",
    "subtitle": "副标题（可选，可为 null）",
    "key_points": ["来自内容块的具体信息..."],
    "content_block_ids": ["b1", "b3"],
    "needs_image": true,
    "image_prompt": "English prompt for image generation",
    "speaker_notes_hint": "这页想传递的核心信息"
  },
  ...
]
"""


class OutlineGenerator:
    """生成 PPT 大纲，确定每页的类型、布局、内容要点。"""

    def __init__(self, config: dict):
        """创建 LLM client。

        Args:
            config: 项目配置字典，需包含 llm 配置段。
        """
        self._llm: LLMClient = create_llm_client(config.get("llm", {}))

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def generate(
        self,
        text: str,
        analysis: DocumentAnalysis,
        max_pages: int | None = None,
        content_map: ContentMap | None = None,
        presentation_plan: PresentationPlan | None = None,
    ) -> list[SlideOutline]:
        """生成大纲。

        两种模式：
        - **plan-driven**（presentation_plan 非空）：
          直接从 plan 转换大纲，LLM 只填 title/key_points/image_prompt，
          结构完全由 plan 决定。这是首选模式，生成质量远高于 free-form。
        - **free-form**（无 plan）：让 LLM 自由生成大纲。

        Args:
            text: 原始文档文本。
            analysis: 文档分析结果。
            max_pages: 最大页数上限（None 则使用 analysis 建议页数）。
            content_map: 结构化内容地图（可选）。
            presentation_plan: 演示计划（可选）。提供时使用 plan-driven 模式。

        Returns:
            SlideOutline 列表。
        """
        # ---- Plan-driven 模式 ----
        if presentation_plan is not None:
            slides = self._generate_from_plan(
                presentation_plan, content_map, text
            )
            # Plan-driven 模式只做最轻量的修复（不改变 plan 决定的结构）:
            # 仅修复连续 section_divider（planner 不会故意生成这种情况）
            for i in range(1, len(slides)):
                if (
                    slides[i].layout == LayoutType.SECTION_DIVIDER
                    and slides[i - 1].layout == LayoutType.SECTION_DIVIDER
                ):
                    slides[i].layout = LayoutType.BULLET_WITH_ICONS
                    slides[i].slide_type = "bullet_with_icons"
            for i, slide in enumerate(slides):
                slide.page_number = i + 1
            return slides

        # ---- Free-form 模式 ----
        total_pages = self._determine_page_count(analysis, max_pages)

        if content_map is not None:
            raw_slides = self._call_llm_with_content_map(
                content_map, analysis, total_pages
            )
        else:
            raw_slides = self._call_llm(text, analysis, total_pages)

        slides = self._parse_slides(raw_slides, total_pages)

        # 后处理
        slides = self._ensure_layout_diversity(slides)
        slides = self._ensure_rhythm(slides)

        # 重新编号
        for i, slide in enumerate(slides):
            slide.page_number = i + 1

        return slides

    # ------------------------------------------------------------------
    # Narrative-driven 大纲生成（V2 从主题生成模式）
    # ------------------------------------------------------------------

    def from_narrative(
        self,
        narrative: NarrativeStructure,
        theme: str = "modern",
        target_pages: int | None = None,
    ) -> list[SlideOutline]:
        """从叙事结构生成大纲（V2 从主题生成模式）。

        与 plan-driven 模式类似，但输入是 NarrativeStructure（来自 NarrativeDesigner），
        而非 PresentationPlan。

        Args:
            narrative: 叙事结构。
            theme: 主题名称。
            target_pages: 目标页数（None 则使用 narrative.total_pages）。

        Returns:
            SlideOutline 列表。
        """
        total = target_pages or narrative.total_pages
        log.info(
            "从叙事结构生成大纲（%d 页，场景: %s）",
            total, narrative.scenario,
        )

        # 1. 构建骨架
        skeletons = self._build_narrative_skeletons(narrative)

        # 2. 调 LLM 填充 title / key_points / image_prompt
        filled = self._fill_narrative_with_llm(skeletons, narrative)

        # 3. 如果 LLM 失败，用叙事结构做 fallback
        if filled is None:
            log.warning("LLM 填充失败，使用叙事结构 fallback")
            filled = self._fill_narrative_fallback(skeletons, narrative)

        # 4. 后处理
        filled = self._ensure_layout_diversity(filled)
        for i, slide in enumerate(filled):
            slide.page_number = i + 1

        return filled

    def _build_narrative_skeletons(
        self, narrative: NarrativeStructure
    ) -> list[SlideOutline]:
        """从 NarrativeStructure 构建大纲骨架。"""
        skeletons: list[SlideOutline] = []
        for i, section in enumerate(narrative.sections):
            # 推断布局
            layout = section.layout_preference
            if layout is None:
                role_value = section.role.value if hasattr(section.role, "value") else str(section.role)
                layout = _PAGE_ROLE_TO_LAYOUT.get(role_value, LayoutType.BULLET_WITH_ICONS)

            needs_image = section.image_strategy != ImageStrategy.NONE

            skeletons.append(SlideOutline(
                page_number=i + 1,
                slide_type=layout.value,
                layout=layout,
                title=section.title_hint or "",
                key_points=list(section.key_points_hint),
                needs_image=needs_image,
                image_prompt=None,
                speaker_notes_hint=section.speaker_notes_hint,
                page_role=section.role,
                page_goal=section.title_hint,
                image_strategy=section.image_strategy,
            ))
        return skeletons

    def _fill_narrative_with_llm(
        self,
        skeletons: list[SlideOutline],
        narrative: NarrativeStructure,
    ) -> list[SlideOutline] | None:
        """调用 LLM 为叙事骨架填充 title / key_points / image_prompt。"""
        # 构建页面任务描述
        pages_desc = []
        for i, section in enumerate(narrative.sections):
            kph = "、".join(section.key_points_hint) if section.key_points_hint else "由你生成"
            pages_desc.append(
                f"第{i + 1}页 | 角色: {section.role.value} | "
                f"标题提示: {section.title_hint} | "
                f"要点提示: {kph}"
            )

        user_prompt = (
            f"## 演示主题\n{narrative.topic}\n\n"
            f"## 目标受众\n{narrative.audience}\n\n"
            f"## 使用场景\n{narrative.scenario}\n\n"
            f"## 页面任务（你必须严格按此结构生成）\n"
            + "\n".join(pages_desc)
            + f"\n\n请为以上 {len(narrative.sections)} 页生成标题和要点。"
            f"返回 JSON 数组，每页一个对象，顺序与任务一一对应。\n"
            f"注意：\n"
            f"- 所有标题和要点必须是中文\n"
            f"- key_points 每条 20-50 字，3-5 条\n"
            f"- 如果要点提示已有内容，在此基础上扩展\n"
            f"- image_prompt 用英文，描述具体画面"
        )

        messages = [
            {"role": "system", "content": _PLAN_DRIVEN_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._llm.chat(
                messages, temperature=0.4, json_mode=True, max_tokens=4096
            )
            raw = extract_json_array(response.content)
        except Exception as e:
            log.warning("Narrative LLM 调用失败: %s", e)
            return None

        if raw is None or not isinstance(raw, list):
            return None

        return self._merge_llm_into_skeletons(skeletons, raw)

    def _fill_narrative_fallback(
        self,
        skeletons: list[SlideOutline],
        narrative: NarrativeStructure,
    ) -> list[SlideOutline]:
        """LLM 失败时，直接使用叙事结构的 hints 作为内容。"""
        for skeleton, section in zip(skeletons, narrative.sections):
            if not skeleton.title:
                skeleton.title = section.title_hint or f"第 {skeleton.page_number} 页"
            if not skeleton.key_points and section.key_points_hint:
                skeleton.key_points = list(section.key_points_hint)
            if skeleton.needs_image and not skeleton.image_prompt:
                skeleton.image_prompt = (
                    f"professional minimalist illustration for {skeleton.title}"
                )
        return skeletons

    # ------------------------------------------------------------------
    # Plan-driven 大纲生成
    # ------------------------------------------------------------------

    def _generate_from_plan(
        self,
        plan: PresentationPlan,
        content_map: ContentMap | None,
        text: str,
    ) -> list[SlideOutline]:
        """从 PresentationPlan 直接转换为 SlideOutline 列表。

        结构（页数、page_role、layout、must_include 等）完全由 plan 决定，
        LLM 只负责填写每页的 title / key_points / image_prompt。
        """
        log.info(
            "使用 plan-driven 模式生成大纲（%d 页，类型: %s）",
            len(plan.slides), plan.deck_type.value,
        )

        # 1. 先构建骨架（不依赖 LLM）
        skeletons = self._build_skeletons(plan)

        # 2. 调 LLM 填充 title / key_points / image_prompt
        filled = self._fill_with_llm(skeletons, plan, content_map, text)

        # 3. 如果 LLM 填充失败，用 content_map 做规则 fallback
        if filled is None:
            log.warning("LLM 填充失败，使用规则 fallback")
            return self._fill_with_rules(skeletons, content_map, text)

        return filled

    def _build_skeletons(
        self, plan: PresentationPlan
    ) -> list[SlideOutline]:
        """从 PresentationPlan.slides 构建大纲骨架（无 title/key_points）。"""
        skeletons: list[SlideOutline] = []
        for i, task in enumerate(plan.slides):
            layout = self._resolve_layout(task)
            needs_image = task.image_strategy != ImageStrategy.NONE

            skeletons.append(
                SlideOutline(
                    page_number=i + 1,
                    slide_type=layout.value,
                    layout=layout,
                    title="",  # LLM 填充
                    key_points=[],  # LLM 填充
                    needs_image=needs_image,
                    image_prompt=None,  # LLM 填充
                    speaker_notes_hint="",
                    content_block_ids=[],
                    page_role=task.page_role,
                    page_goal=task.page_goal,
                    must_include=list(task.must_include),
                    forbidden_content=list(task.forbidden_content),
                    image_strategy=task.image_strategy,
                )
            )
        return skeletons

    @staticmethod
    def _resolve_layout(task: SlideTask) -> LayoutType:
        """从 SlideTask 推断布局类型。"""
        # 优先用显式指定的 layout_preference
        if task.layout_preference:
            try:
                return LayoutType(task.layout_preference)
            except (ValueError, KeyError):
                pass

        # 按 page_role 映射
        role_value = task.page_role.value if hasattr(task.page_role, "value") else str(task.page_role)
        return _PAGE_ROLE_TO_LAYOUT.get(role_value, LayoutType.BULLET_WITH_ICONS)

    def _fill_with_llm(
        self,
        skeletons: list[SlideOutline],
        plan: PresentationPlan,
        content_map: ContentMap | None,
        text: str,
    ) -> list[SlideOutline] | None:
        """调用 LLM 为骨架填充 title / key_points / image_prompt。"""
        # 构建 user prompt
        parts: list[str] = []

        parts.append(f"## 演示主题\n{plan.core_message}")
        parts.append(f"## 目标受众\n{plan.audience}")
        parts.append(f"## 演示目标\n{plan.presentation_goal}")
        parts.append(f"## 叙事弧线\n{' → '.join(plan.narrative_arc)}")

        # 内容块列表
        if content_map is not None:
            blocks_text = ""
            for block in content_map.content_blocks:
                ext_mark = " [外部补充]" if block.is_external else ""
                stars = "★" * block.importance
                blocks_text += (
                    f"- [{block.block_id}] ({block.block_type}, {stars}{ext_mark}) "
                    f"{block.title} — {block.summary}\n"
                )
            parts.append(f"## 可用内容块\n{blocks_text}")

            if content_map.key_data_points:
                parts.append(
                    "## 关键数据\n"
                    + "\n".join(f"- {d}" for d in content_map.key_data_points[:10])
                )
            if content_map.key_quotes:
                parts.append(
                    "## 金句\n"
                    + "\n".join(f"- {q}" for q in content_map.key_quotes[:5])
                )
        else:
            # 没有 content_map，用原文摘要
            truncated = text[:8000] if len(text) > 8000 else text
            parts.append(f"## 原文内容\n{truncated}")

        # 每页的任务说明
        pages_desc: list[str] = []
        for i, task in enumerate(plan.slides):
            mi = "、".join(task.must_include) if task.must_include else "无"
            fc = "、".join(task.forbidden_content) if task.forbidden_content else "无"
            needs_img = "是" if task.image_strategy != ImageStrategy.NONE else "否"
            pages_desc.append(
                f"第{i + 1}页 | 角色: {task.page_role.value} | "
                f"目标: {task.page_goal} | 必含: {mi} | "
                f"禁止: {fc} | 需要配图: {needs_img}"
            )
        parts.append("## 页面任务（你必须严格按此结构生成）\n" + "\n".join(pages_desc))

        parts.append(
            f"请为以上 {len(plan.slides)} 页生成标题和要点。"
            f"返回 JSON 数组，每页一个对象，顺序与任务一一对应。\n"
            f"注意：\n"
            f"- 所有标题和要点必须是中文\n"
            f"- key_points 必须基于提供的内容块，不要编造\n"
            f"- 优先使用 importance >= 4 的内容块\n"
            f"- 外部补充内容块（标记为 [外部补充]）每页最多引用1个\n"
            f"- image_prompt 用英文，描述具体画面"
        )

        user_prompt = "\n\n".join(parts)

        messages = [
            {"role": "system", "content": _PLAN_DRIVEN_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._llm.chat(
                messages,
                temperature=0.4,
                json_mode=True,
                max_tokens=4096,
            )
            raw = extract_json_array(response.content)
        except Exception as e:
            log.warning("Plan-driven LLM 调用失败: %s", e)
            return None

        if raw is None or not isinstance(raw, list):
            return None

        # 合并 LLM 输出到骨架
        return self._merge_llm_into_skeletons(skeletons, raw)

    @staticmethod
    def _merge_llm_into_skeletons(
        skeletons: list[SlideOutline],
        raw: list[dict],
    ) -> list[SlideOutline]:
        """将 LLM 返回的 JSON 合并到骨架中。"""
        for i, skeleton in enumerate(skeletons):
            if i >= len(raw):
                # LLM 返回的页数不够，用 page_goal 作为标题
                skeleton.title = skeleton.page_goal or f"第 {i + 1} 页"
                continue

            item = raw[i]
            if not isinstance(item, dict):
                skeleton.title = skeleton.page_goal or f"第 {i + 1} 页"
                continue

            # 填充 title
            title = str(item.get("title", "")).strip()
            if title:
                skeleton.title = title
            else:
                skeleton.title = skeleton.page_goal or f"第 {i + 1} 页"

            # 填充 subtitle
            subtitle = item.get("subtitle")
            if subtitle and str(subtitle).strip():
                skeleton.subtitle = str(subtitle).strip()

            # 填充 key_points（只接受标量值，拒绝嵌套对象）
            kps = item.get("key_points", [])
            if isinstance(kps, list):
                skeleton.key_points = [
                    str(p) for p in kps
                    if isinstance(p, (str, int, float)) and p
                ][:5]

            # 填充 content_block_ids
            bids = item.get("content_block_ids", [])
            if isinstance(bids, list):
                skeleton.content_block_ids = [str(b) for b in bids if b]

            # 填充 image_prompt
            img_prompt = item.get("image_prompt")
            if img_prompt and str(img_prompt).strip().lower() != "null":
                skeleton.image_prompt = str(img_prompt).strip()
            elif skeleton.needs_image:
                # 需要图片但 LLM 没给 prompt，生成默认的
                skeleton.image_prompt = (
                    f"professional minimalist illustration for "
                    f"{skeleton.title}, clean modern style"
                )

            # 填充 speaker_notes_hint
            notes = item.get("speaker_notes_hint", "")
            if notes and str(notes).strip():
                skeleton.speaker_notes_hint = str(notes).strip()

        return skeletons

    def _fill_with_rules(
        self,
        skeletons: list[SlideOutline],
        content_map: ContentMap | None,
        text: str,
    ) -> list[SlideOutline]:
        """LLM 失败时，用规则为骨架填充基本内容。"""
        # 按 importance 降序排列可用内容块
        available_blocks: list = []
        if content_map is not None:
            available_blocks = sorted(
                content_map.content_blocks,
                key=lambda b: b.importance,
                reverse=True,
            )

        block_idx = 0
        for skeleton in skeletons:
            # title 用 page_goal
            skeleton.title = skeleton.page_goal or f"第 {skeleton.page_number} 页"

            # 分配内容块
            if available_blocks and block_idx < len(available_blocks):
                # 每页分配 1-2 个内容块
                assigned = []
                for _ in range(2):
                    if block_idx < len(available_blocks):
                        blk = available_blocks[block_idx]
                        assigned.append(blk)
                        block_idx += 1

                skeleton.content_block_ids = [b.block_id for b in assigned]
                skeleton.key_points = [b.summary for b in assigned]

                if skeleton.needs_image:
                    skeleton.image_prompt = (
                        f"professional illustration for {skeleton.title}"
                    )
            elif text:
                # 没有 content_map，从原文截取
                chunk_size = max(100, len(text) // max(len(skeletons), 1))
                start = (skeleton.page_number - 1) * chunk_size
                chunk = text[start : start + chunk_size]
                if not chunk and skeleton.page_number > 1:
                    # 文本不够分，复用开头内容
                    chunk = text[:chunk_size]
                if chunk:
                    skeleton.key_points = [chunk[:100]]

        return skeletons

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _determine_page_count(
        self, analysis: DocumentAnalysis, max_pages: int | None
    ) -> int:
        """根据分析结果确定总页数。"""
        suggested = analysis.estimated_pages
        if max_pages is not None:
            return min(suggested, max_pages)
        return suggested

    def _call_llm(
        self,
        text: str,
        analysis: DocumentAnalysis,
        total_pages: int,
    ) -> list[dict] | None:
        """调用 LLM 生成大纲（传统模式：基于原始文本）。"""
        # 截断文本以节省 tokens
        truncated = text[:16000] if len(text) > 16000 else text

        user_prompt = (
            f"请根据以下文档分析结果和原文内容，设计一份 {total_pages} 页的 PPT 大纲。\n\n"
            f"## 文档分析结果\n"
            f"- 主题：{analysis.theme}\n"
            f"- 类型：{analysis.doc_type.value}\n"
            f"- 受众：{analysis.audience.value}\n"
            f"- 风格：{analysis.tone.value}\n"
            f"- 关键要点：{', '.join(analysis.key_points)}\n"
            f"- 含数据：{'是' if analysis.has_data else '否'}\n"
            f"- 含引用：{'是' if analysis.has_quotes else '否'}\n"
            f"- 有章节：{'是' if analysis.has_sections else '否'}\n\n"
            f"## 原文内容\n{truncated}\n\n"
            f"请生成恰好 {total_pages} 页的大纲（JSON 数组）。"
        )

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        response = self._llm.chat(
            messages,
            temperature=0.5,
            json_mode=True,
            max_tokens=4096,
        )

        return extract_json_array(response.content)

    def _call_llm_with_content_map(
        self,
        content_map: ContentMap,
        analysis: DocumentAnalysis,
        total_pages: int,
    ) -> list[dict] | None:
        """调用 LLM 生成大纲（内容地图模式：基于结构化内容块）。"""
        # 构建内容块列表
        blocks_text = ""
        for block in content_map.content_blocks:
            stars = "★" * block.importance
            blocks_text += (
                f"- [{block.block_id}] ({block.block_type}, {stars}) "
                f"{block.title} — {block.summary}\n"
            )

        # 构建关键数据
        data_points_text = ""
        if content_map.key_data_points:
            data_points_text = "\n".join(
                f"- {dp}" for dp in content_map.key_data_points
            )
        else:
            data_points_text = "（无）"

        # 构建金句引用
        quotes_text = ""
        if content_map.key_quotes:
            quotes_text = "\n".join(
                f"- {q}" for q in content_map.key_quotes
            )
        else:
            quotes_text = "（无）"

        # 构建逻辑流顺序
        flow_text = " → ".join(content_map.logical_flow)

        user_prompt = (
            f"请基于以下结构化内容，设计一份 {total_pages} 页的 PPT 大纲。\n\n"
            f"## 文档核心论点\n{content_map.document_thesis}\n\n"
            f"## 文档分析结果\n"
            f"- 主题：{analysis.theme}\n"
            f"- 类型：{analysis.doc_type.value}\n"
            f"- 受众：{analysis.audience.value}\n"
            f"- 风格：{analysis.tone.value}\n\n"
            f"## 内容块列表\n{blocks_text}\n"
            f"## 建议逻辑顺序\n{flow_text}\n\n"
            f"## 关键数据\n{data_points_text}\n\n"
            f"## 金句引用\n{quotes_text}\n\n"
            f"请生成恰好 {total_pages} 页的大纲（JSON 数组）。"
            f"每页必须包含 content_block_ids 字段，标明该页展示哪些内容块。"
        )

        messages = [
            {"role": "system", "content": _CONTENT_MAP_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        response = self._llm.chat(
            messages,
            temperature=0.5,
            json_mode=True,
            max_tokens=4096,
        )

        return extract_json_array(response.content)

    def _parse_slides(
        self,
        raw: list[dict] | None,
        total_pages: int,
    ) -> list[SlideOutline]:
        """将 LLM 返回的 JSON 数组解析为 SlideOutline 列表。"""
        if raw is None or not isinstance(raw, list) or len(raw) == 0:
            log.warning("LLM 返回无效大纲，使用 fallback")
            return self._fallback_outline(total_pages)

        slides: list[SlideOutline] = []
        for i, item in enumerate(raw):
            try:
                slide = self._parse_single_slide(item, i + 1)
                slides.append(slide)
            except Exception as e:
                log.warning(f"解析第 {i + 1} 页大纲失败: {e}，跳过")

        if len(slides) < 3:
            log.warning(f"有效大纲页数不足 ({len(slides)})，使用 fallback")
            return self._fallback_outline(total_pages)

        return slides

    def _parse_single_slide(self, item: dict, page_num: int) -> SlideOutline:
        """解析单页大纲。"""
        layout_str = item.get("layout", "bullet_with_icons")
        layout = self._safe_layout(layout_str)

        slide_type = item.get("slide_type", layout.value)

        # 处理 key_points
        key_points = item.get("key_points", [])
        if not isinstance(key_points, list):
            key_points = []
        key_points = [str(p) for p in key_points if p]

        # 处理 content_block_ids
        content_block_ids = item.get("content_block_ids", [])
        if not isinstance(content_block_ids, list):
            content_block_ids = []
        content_block_ids = [str(bid) for bid in content_block_ids if bid]

        return SlideOutline(
            page_number=page_num,
            slide_type=str(slide_type),
            layout=layout,
            title=str(item.get("title", f"第 {page_num} 页")),
            subtitle=item.get("subtitle"),
            key_points=key_points,
            needs_image=bool(item.get("needs_image", False)),
            image_prompt=item.get("image_prompt"),
            speaker_notes_hint=str(item.get("speaker_notes_hint", "")),
            content_block_ids=content_block_ids,
        )

    def _ensure_layout_diversity(
        self, slides: list[SlideOutline]
    ) -> list[SlideOutline]:
        """确保布局多样性。

        规则：
        - 不连续 3 页使用相同布局
        - 封面必须是 title_hero
        - 最后一页必须是 closing
        - 章节分隔页后不能紧跟另一个章节分隔页
        """
        if not slides:
            return slides

        # 规则1：封面必须是 title_hero
        slides[0].layout = LayoutType.TITLE_HERO
        slides[0].slide_type = "title_hero"
        slides[0].needs_image = True

        # 规则2：最后一页必须是 closing
        slides[-1].layout = LayoutType.CLOSING
        slides[-1].slide_type = "closing"
        slides[-1].needs_image = False

        # 规则3：不连续 3 页相同布局
        # 从第2页到倒数第2页检查（跳过封面和结尾）
        for i in range(2, len(slides) - 1):
            if (
                slides[i].layout == slides[i - 1].layout
                and slides[i].layout == slides[i - 2].layout
            ):
                # 替换为一个不同的布局
                slides[i].layout = self._pick_alternative_layout(
                    slides[i].layout, slides[i - 1].layout
                )
                slides[i].slide_type = slides[i].layout.value

        # 规则4：章节分隔页不连续
        for i in range(1, len(slides) - 1):
            if (
                slides[i].layout == LayoutType.SECTION_DIVIDER
                and i > 0
                and slides[i - 1].layout == LayoutType.SECTION_DIVIDER
            ):
                # 把当前页换成 bullet_with_icons
                slides[i].layout = LayoutType.BULLET_WITH_ICONS
                slides[i].slide_type = "bullet_with_icons"

        return slides

    def _ensure_rhythm(self, slides: list[SlideOutline]) -> list[SlideOutline]:
        """确保节奏感。

        规则：
        - 不连续出现 3 个纯文字页
        - 数据页(data_highlight)分散分布
        - quote_page 不超过总页数的 10%
        """
        if len(slides) <= 3:
            return slides

        # 规则1：不连续 3 个纯文字页
        # 跳过封面和结尾
        for i in range(2, len(slides) - 1):
            if (
                self._is_text_only(slides[i])
                and self._is_text_only(slides[i - 1])
                and self._is_text_only(slides[i - 2])
            ):
                # 把中间的换成带图的布局
                slides[i - 1].layout = LayoutType.TEXT_LEFT_IMAGE_RIGHT
                slides[i - 1].slide_type = "text_left_image_right"
                slides[i - 1].needs_image = True
                if not slides[i - 1].image_prompt:
                    slides[i - 1].image_prompt = (
                        "professional minimalist illustration related to "
                        + slides[i - 1].title
                    )

        # 规则2：quote_page 不超过 10%
        max_quotes = max(1, len(slides) // 10)
        quote_count = 0
        for slide in slides[1:-1]:  # 跳过封面和结尾
            if slide.layout == LayoutType.QUOTE_PAGE:
                quote_count += 1
                if quote_count > max_quotes:
                    slide.layout = LayoutType.BULLET_WITH_ICONS
                    slide.slide_type = "bullet_with_icons"

        # 规则3：data_highlight 分散分布 — 不连续出现
        for i in range(1, len(slides) - 1):
            if (
                slides[i].layout == LayoutType.DATA_HIGHLIGHT
                and i > 0
                and slides[i - 1].layout == LayoutType.DATA_HIGHLIGHT
            ):
                slides[i].layout = LayoutType.TEXT_LEFT_IMAGE_RIGHT
                slides[i].slide_type = "text_left_image_right"
                slides[i].needs_image = True
                if not slides[i].image_prompt:
                    slides[i].image_prompt = (
                        "data visualization chart, clean professional style"
                    )

        return slides

    def _is_text_only(self, slide: SlideOutline) -> bool:
        """判断是否为纯文字页（无图片）。"""
        return slide.layout in _TEXT_ONLY_LAYOUTS and not slide.needs_image

    def _pick_alternative_layout(
        self, current: LayoutType, previous: LayoutType
    ) -> LayoutType:
        """选择一个与当前和前一页不同的布局。"""
        alternatives = [
            LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            LayoutType.BULLET_WITH_ICONS,
            LayoutType.THREE_COLUMNS,
            LayoutType.IMAGE_LEFT_TEXT_RIGHT,
            LayoutType.DATA_HIGHLIGHT,
            LayoutType.TIMELINE,
        ]
        for alt in alternatives:
            if alt != current and alt != previous:
                return alt
        return LayoutType.BULLET_WITH_ICONS

    @staticmethod
    def _safe_layout(value: str | None) -> LayoutType:
        """安全地将字符串转换为 LayoutType。"""
        if value is None:
            return LayoutType.BULLET_WITH_ICONS
        try:
            return LayoutType(value)
        except (ValueError, KeyError):
            return LayoutType.BULLET_WITH_ICONS

    def _fallback_outline(self, total_pages: int) -> list[SlideOutline]:
        """LLM 失败时的降级大纲。"""
        slides: list[SlideOutline] = []

        # 封面
        slides.append(
            SlideOutline(
                page_number=1,
                slide_type="title_hero",
                layout=LayoutType.TITLE_HERO,
                title="演示文稿",
                subtitle="由 AI 自动生成",
                key_points=[],
                needs_image=True,
                image_prompt="abstract minimalist presentation cover, gradient blue background, professional style",
                speaker_notes_hint="欢迎各位，今天为大家分享这份文档的核心内容。",
            )
        )

        # 中间内容页
        content_layouts = [
            LayoutType.SECTION_DIVIDER,
            LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            LayoutType.BULLET_WITH_ICONS,
            LayoutType.IMAGE_LEFT_TEXT_RIGHT,
            LayoutType.THREE_COLUMNS,
            LayoutType.DATA_HIGHLIGHT,
        ]

        for i in range(1, total_pages - 1):
            layout = content_layouts[i % len(content_layouts)]
            needs_img = layout in _IMAGE_LAYOUTS
            slides.append(
                SlideOutline(
                    page_number=i + 1,
                    slide_type=layout.value,
                    layout=layout,
                    title=f"内容 {i}",
                    key_points=["待补充内容"],
                    needs_image=needs_img,
                    image_prompt=(
                        "clean professional illustration, minimalist style"
                        if needs_img
                        else None
                    ),
                    speaker_notes_hint="",
                )
            )

        # 结束页
        slides.append(
            SlideOutline(
                page_number=total_pages,
                slide_type="closing",
                layout=LayoutType.CLOSING,
                title="谢谢",
                subtitle="欢迎提问",
                key_points=[],
                needs_image=False,
                speaker_notes_hint="感谢大家的聆听，欢迎提问。",
            )
        )

        return slides


# ---------------------------------------------------------------------------
# 大纲序列化 / 反序列化（暂停点）
# ---------------------------------------------------------------------------


def serialize_outline_for_edit(
    outline: list[SlideOutline],
    project_id: str,
    narrative_arc: str = "",
) -> EditableOutline:
    """将内部大纲序列化为可编辑格式（暂停点数据）。

    Args:
        outline: SlideOutline 列表。
        project_id: 项目 ID。
        narrative_arc: 叙事弧线描述。

    Returns:
        EditableOutline。
    """
    pages = len(outline)
    duration_min = max(1, int(pages * 0.5))
    duration_max = max(2, int(pages * 0.7))

    slides = []
    for slide in outline:
        role_str = slide.page_role.value if slide.page_role else "knowledge_point"
        layout_str = slide.layout.value if hasattr(slide.layout, "value") else str(slide.layout)
        img_strategy_str = slide.image_strategy.value if hasattr(slide.image_strategy, "value") else "none"

        slides.append(EditableSlide(
            page_number=slide.page_number,
            role=role_str,
            title=slide.title,
            subtitle=slide.subtitle or "",
            key_points=list(slide.key_points),
            layout=layout_str,
            image_strategy=img_strategy_str,
            speaker_notes_hint=slide.speaker_notes_hint,
            editable=role_str not in ("cover", "closing"),
            locked=False,
        ))

    return EditableOutline(
        project_id=project_id,
        total_pages=pages,
        estimated_duration=f"{duration_min}-{duration_max} 分钟",
        narrative_arc=narrative_arc,
        slides=slides,
    )


def deserialize_edited_outline(edited: EditableOutline) -> list[SlideOutline]:
    """将用户编辑后的大纲反序列化为内部格式。

    Args:
        edited: 用户编辑后的 EditableOutline。

    Returns:
        SlideOutline 列表。
    """
    slides = []
    for es in edited.slides:
        # 安全解析枚举
        try:
            layout = LayoutType(es.layout)
        except (ValueError, KeyError):
            layout = LayoutType.BULLET_WITH_ICONS

        try:
            page_role = PageRole(es.role)
        except (ValueError, KeyError):
            page_role = PageRole.KNOWLEDGE_POINT

        try:
            image_strategy = ImageStrategy(es.image_strategy)
        except (ValueError, KeyError):
            image_strategy = ImageStrategy.NONE

        needs_image = image_strategy != ImageStrategy.NONE
        image_prompt = None
        if needs_image:
            image_prompt = (
                f"professional minimalist illustration for "
                f"{es.title}, clean modern style"
            )

        slides.append(SlideOutline(
            page_number=es.page_number,
            slide_type=layout.value,
            layout=layout,
            title=es.title,
            subtitle=es.subtitle or None,
            key_points=list(es.key_points),
            needs_image=needs_image,
            image_prompt=image_prompt,
            speaker_notes_hint=es.speaker_notes_hint,
            page_role=page_role,
            page_goal=es.title,
            image_strategy=image_strategy,
        ))

    return slides
