"""演示计划器 — 在逐页生成之前先规划整套演示

不是直接写页文案，而是先回答：
1. 这套 PPT 要达成什么目标？
2. 受众最关心什么？
3. 核心信息是什么（一句话）？
4. 叙事弧线怎么走？
5. 每页的角色和任务是什么？

输出 PresentationPlan，供 OutlineGenerator 和 ContentCreator 使用。
"""

from __future__ import annotations

import logging
from typing import Any

from src.agents.utils import extract_json_obj
from src.llm.llm_client import LLMClient, create_llm_client
from src.ppt.models import (
    ContentMap,
    DeckType,
    DocumentAnalysis,
    ImageStrategy,
    PageRole,
    PresentationPlan,
    SlideTask,
)

# deck_strategies 由另一个 agent 创建，可能尚未就绪
try:
    from src.ppt.deck_strategies import (
        detect_deck_type,
        get_default_slides,
        get_strategy,
    )

    _HAS_STRATEGIES = True
except ImportError:
    _HAS_STRATEGIES = False

log = logging.getLogger("ppt")

# ---------------------------------------------------------------------------
# 默认值（deck_strategies 不可用时的最小骨架）
# ---------------------------------------------------------------------------

_DEFAULT_NARRATIVE_ARC = [
    "开篇引入",
    "背景铺垫",
    "核心内容",
    "数据/案例支撑",
    "总结行动",
]

_DEFAULT_SLIDES: list[dict[str, Any]] = [
    {"page_role": "cover", "page_goal": "点题 + 吸引注意力"},
    {"page_role": "executive_summary", "page_goal": "一页概述全篇核心要点"},
    {"page_role": "background", "page_goal": "交代背景和问题"},
    {"page_role": "data_evidence", "page_goal": "用数据/案例支撑核心论点"},
    {"page_role": "solution", "page_goal": "给出方案或建议"},
    {"page_role": "next_steps", "page_goal": "下一步行动计划"},
    {"page_role": "closing", "page_goal": "收尾 + 致谢"},
]

_DEFAULT_REQUIRED_ROLES: set[str] = {"cover", "closing"}

# ---------------------------------------------------------------------------
# 最大页数默认值
# ---------------------------------------------------------------------------

_MAX_PAGES_DEFAULT = 20

# ---------------------------------------------------------------------------
# LLM Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
你是一位资深演示策划师。你的任务是根据文档内容和 PPT 类型，设计一份完整的演示计划。

你不是在写 PPT 内容，而是在做"演示策划"：
1. 确定核心信息（一句话说清这次演示要传达什么）
2. 确定受众画像（谁在看这份 PPT）
3. 确定演示目标（看完后受众应该怎样）
4. 按叙事弧线编排每页的角色和任务

你收到的是已提取的文档内容结构，请基于实际内容来规划。
"""


def _build_user_prompt(
    deck_type: DeckType,
    content_map: ContentMap | None,
    analysis: DocumentAnalysis | None,
    narrative_arc: list[str],
    default_slides: list[dict[str, Any]],
    max_pages: int,
) -> str:
    """组装发送给 LLM 的用户提示。"""
    parts: list[str] = []

    parts.append(f"## PPT 类型: {deck_type.value}")

    # 文档信息
    if content_map is not None:
        parts.append(f"## 文档核心论点: {content_map.document_thesis}")

        if content_map.content_blocks:
            blocks_desc = []
            for b in content_map.content_blocks:
                blocks_desc.append(
                    f"- [{b.block_type}] {b.title}（重要性{b.importance}）: {b.summary[:80]}"
                )
            parts.append("## 文档内容块:\n" + "\n".join(blocks_desc))

        if content_map.key_data_points:
            parts.append(
                "## 关键数据: " + " | ".join(content_map.key_data_points[:10])
            )
        if content_map.key_quotes:
            parts.append(
                "## 金句: " + " | ".join(content_map.key_quotes[:5])
            )
    elif analysis is not None:
        parts.append(f"## 文档主题: {analysis.theme}")
        if analysis.key_points:
            parts.append(
                "## 关键要点:\n"
                + "\n".join(f"- {p}" for p in analysis.key_points)
            )

    # 策略骨架
    parts.append("## 默认叙事骨架:\n" + " → ".join(narrative_arc))

    slides_desc = []
    for s in default_slides:
        role = s.get("page_role", "unknown")
        goal = s.get("page_goal", "")
        slides_desc.append(f"- {role}: {goal}")
    parts.append("## 默认页面结构:\n" + "\n".join(slides_desc))

    # 指令
    parts.append(f"""
请基于以上信息，定制演示计划。
你可以：
- 根据实际内容调整页面数量（但不超过{max_pages}页）
- 根据内容丰富度合并或拆分页面
- 为每页填写具体的 must_include（基于文档实际内容）
- 选择合适的 image_strategy

返回 JSON:
{{
  "audience": "具体受众描述",
  "core_message": "一句话核心信息",
  "presentation_goal": "演示目标",
  "slides": [
    {{
      "page_role": "cover",
      "page_goal": "...",
      "must_include": ["从文档中提取的具体内容..."],
      "forbidden_content": ["..."],
      "image_strategy": "none",
      "layout_preference": "title_hero"
    }}
  ]
}}

page_role 可选值: {', '.join(r.value for r in PageRole)}
image_strategy 可选值: {', '.join(s.value for s in ImageStrategy)}
""")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# PresentationPlanner 类
# ---------------------------------------------------------------------------


class PresentationPlanner:
    """演示计划器 — 规划整套 PPT 的全局策略和每页任务。

    在 ContentExtractor 之后、OutlineGenerator 之前运行。
    输出 PresentationPlan，指导后续阶段生成有全局一致性的 PPT。
    """

    def __init__(self, config: dict) -> None:
        """初始化 LLM 客户端。

        Args:
            config: 项目配置字典，需包含 llm 配置段。
        """
        self._llm: LLMClient = create_llm_client(config.get("llm", {}))

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def plan(
        self,
        text: str,
        analysis: DocumentAnalysis | None,
        content_map: ContentMap | None = None,
        deck_type: DeckType | None = None,
        max_pages: int | None = None,
    ) -> PresentationPlan:
        """规划整套演示。

        Args:
            text: 原始文档文本（用于 fallback）。
            analysis: 阶段 1 的文档分析结果。
            content_map: 阶段 1.5 的内容地图（可为 None）。
            deck_type: 显式指定 PPT 类型（None 则自动检测）。
            max_pages: 最大页数限制。

        Returns:
            PresentationPlan 对象。
        """
        effective_max = max_pages or _MAX_PAGES_DEFAULT

        # 1. 确定 deck_type
        resolved_type = self._resolve_deck_type(deck_type, analysis)

        # 2. 加载策略骨架
        narrative_arc, default_slides, required_roles = self._load_strategy(
            resolved_type
        )

        # 3. 调用 LLM 定制计划
        raw = self._call_llm(
            resolved_type,
            content_map,
            analysis,
            narrative_arc,
            default_slides,
            effective_max,
        )

        # 4. 解析 + 校验
        plan = self._parse_plan(
            raw,
            resolved_type,
            narrative_arc,
            default_slides,
            required_roles,
            effective_max,
            content_map,
            analysis,
        )

        return plan

    # ------------------------------------------------------------------
    # 内部：类型检测
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_deck_type(
        explicit: DeckType | None,
        analysis: DocumentAnalysis | None,
    ) -> DeckType:
        """确定 PPT 类型。优先使用显式指定，否则从 analysis 自动检测。"""
        if explicit is not None:
            return explicit

        if _HAS_STRATEGIES and analysis is not None:
            return detect_deck_type(analysis.doc_type.value, analysis.tone.value)

        # 最终 fallback: 根据 analysis 的 doc_type 做简单映射
        if analysis is not None:
            doc_type_val = analysis.doc_type.value
            if doc_type_val in ("teaching",):
                return DeckType.COURSE_LECTURE
            if doc_type_val in ("product_intro", "creative_pitch"):
                return DeckType.PRODUCT_INTRO
        return DeckType.BUSINESS_REPORT

    # ------------------------------------------------------------------
    # 内部：策略加载
    # ------------------------------------------------------------------

    @staticmethod
    def _load_strategy(
        deck_type: DeckType,
    ) -> tuple[list[str], list[dict[str, Any]], set[str]]:
        """加载策略骨架。返回 (narrative_arc, default_slides, required_roles)。"""
        if _HAS_STRATEGIES:
            try:
                strategy = get_strategy(deck_type)
                arc = strategy.get("narrative_arc", _DEFAULT_NARRATIVE_ARC)
                slides_raw = get_default_slides(deck_type)
                # 转换 SlideTask -> dict（如果是 pydantic model）
                slides: list[dict[str, Any]] = []
                for s in slides_raw:
                    if hasattr(s, "model_dump"):
                        slides.append(s.model_dump())
                    elif isinstance(s, dict):
                        slides.append(s)
                    else:
                        slides.append(
                            {"page_role": str(s.page_role), "page_goal": str(s.page_goal)}
                        )
                required = strategy.get("required_roles", _DEFAULT_REQUIRED_ROLES)
                # 确保 required 是 set[str]
                required = {
                    r.value if hasattr(r, "value") else str(r) for r in required
                }
                return arc, slides, required
            except Exception as e:
                log.warning("加载 deck_strategies 失败: %s，使用默认骨架", e)

        return (
            list(_DEFAULT_NARRATIVE_ARC),
            list(_DEFAULT_SLIDES),
            set(_DEFAULT_REQUIRED_ROLES),
        )

    # ------------------------------------------------------------------
    # 内部：LLM 调用
    # ------------------------------------------------------------------

    def _call_llm(
        self,
        deck_type: DeckType,
        content_map: ContentMap | None,
        analysis: DocumentAnalysis | None,
        narrative_arc: list[str],
        default_slides: list[dict[str, Any]],
        max_pages: int,
    ) -> dict | None:
        """调用 LLM 生成定制计划，返回解析后的 JSON 字典。"""
        user_prompt = _build_user_prompt(
            deck_type, content_map, analysis, narrative_arc, default_slides, max_pages
        )

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._llm.chat(
                messages,
                temperature=0.4,
                json_mode=True,
                max_tokens=4096,
            )
            return extract_json_obj(response.content)
        except Exception as e:
            log.warning("LLM 演示规划调用失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 内部：解析 + 校验
    # ------------------------------------------------------------------

    def _parse_plan(
        self,
        raw: dict | None,
        deck_type: DeckType,
        narrative_arc: list[str],
        default_slides: list[dict[str, Any]],
        required_roles: set[str],
        max_pages: int,
        content_map: ContentMap | None,
        analysis: DocumentAnalysis | None,
    ) -> PresentationPlan:
        """解析 LLM 返回的 JSON，校验并构建 PresentationPlan。"""
        if raw is None:
            log.warning("LLM 返回无效结果，使用策略骨架作为 fallback")
            return self._build_fallback_plan(
                deck_type, narrative_arc, default_slides, content_map, analysis
            )

        try:
            return self._build_plan_from_llm(
                raw,
                deck_type,
                narrative_arc,
                required_roles,
                max_pages,
            )
        except Exception as e:
            log.warning("解析 LLM 演示规划结果失败: %s，使用 fallback", e)
            return self._build_fallback_plan(
                deck_type, narrative_arc, default_slides, content_map, analysis
            )

    def _build_plan_from_llm(
        self,
        raw: dict,
        deck_type: DeckType,
        narrative_arc: list[str],
        required_roles: set[str],
        max_pages: int,
    ) -> PresentationPlan:
        """从 LLM 输出构建 PresentationPlan。"""
        # 提取顶层字段
        audience = str(raw.get("audience", "通用受众")).strip()
        core_message = str(raw.get("core_message", "")).strip()
        presentation_goal = str(raw.get("presentation_goal", "")).strip()

        if not core_message:
            core_message = "待确定核心信息"
        if not presentation_goal:
            presentation_goal = "传达文档核心内容"

        # 解析 slides
        raw_slides = raw.get("slides", [])
        if not isinstance(raw_slides, list) or not raw_slides:
            raise ValueError("LLM 未返回有效的 slides 列表")

        slides = self._parse_slides(raw_slides)

        # 校验：确保 required_roles 存在
        slides = self._ensure_required_roles(slides, required_roles)

        # 校验：max_pages
        if len(slides) > max_pages:
            slides = slides[:max_pages]

        return PresentationPlan(
            deck_type=deck_type,
            audience=audience,
            core_message=core_message,
            presentation_goal=presentation_goal,
            narrative_arc=narrative_arc,
            slides=slides,
        )

    @staticmethod
    def _parse_slides(raw_slides: list[dict]) -> list[SlideTask]:
        """解析 LLM 返回的 slides 列表为 SlideTask 对象。"""
        slides: list[SlideTask] = []
        for rs in raw_slides:
            if not isinstance(rs, dict):
                continue

            # page_role
            role_str = str(rs.get("page_role", "")).strip()
            try:
                page_role = PageRole(role_str)
            except ValueError:
                # 尝试容错映射
                log.debug("未识别的 page_role: %s, 跳过", role_str)
                continue

            # page_goal
            page_goal = str(rs.get("page_goal", "")).strip()
            if not page_goal:
                page_goal = f"展示 {page_role.value} 内容"

            # must_include
            mi = rs.get("must_include", [])
            must_include = [str(x) for x in mi] if isinstance(mi, list) else []

            # forbidden_content
            fc = rs.get("forbidden_content", [])
            forbidden_content = [str(x) for x in fc] if isinstance(fc, list) else []

            # image_strategy
            is_str = str(rs.get("image_strategy", "none")).strip()
            try:
                image_strategy = ImageStrategy(is_str)
            except ValueError:
                image_strategy = ImageStrategy.NONE

            # layout_preference
            layout_pref = rs.get("layout_preference")
            if layout_pref is not None:
                layout_pref = str(layout_pref).strip() or None

            slides.append(
                SlideTask(
                    page_role=page_role,
                    page_goal=page_goal,
                    must_include=must_include,
                    forbidden_content=forbidden_content,
                    image_strategy=image_strategy,
                    layout_preference=layout_pref,
                )
            )

        if not slides:
            raise ValueError("无法从 LLM 输出中解析出有效的 slides")

        return slides

    @staticmethod
    def _ensure_required_roles(
        slides: list[SlideTask], required_roles: set[str]
    ) -> list[SlideTask]:
        """确保 required_roles 中的页面角色都出现在 slides 中。"""
        existing_roles = {s.page_role.value for s in slides}
        missing = required_roles - existing_roles

        for role_str in missing:
            try:
                role = PageRole(role_str)
            except ValueError:
                continue

            task = SlideTask(
                page_role=role,
                page_goal=f"展示 {role.value} 内容",
            )

            # cover 放最前面，closing 放最后面
            if role_str == "cover":
                slides.insert(0, task)
            elif role_str == "closing":
                slides.append(task)
            else:
                # 放在 closing 之前（如果有的话）
                insert_idx = len(slides)
                for i, s in enumerate(slides):
                    if s.page_role == PageRole.CLOSING:
                        insert_idx = i
                        break
                slides.insert(insert_idx, task)

        return slides

    # ------------------------------------------------------------------
    # 内部：Fallback 计划
    # ------------------------------------------------------------------

    @staticmethod
    def _build_fallback_plan(
        deck_type: DeckType,
        narrative_arc: list[str],
        default_slides: list[dict[str, Any]],
        content_map: ContentMap | None,
        analysis: DocumentAnalysis | None,
    ) -> PresentationPlan:
        """从策略骨架直接构建 fallback 计划。"""
        # 提取受众和核心信息
        audience = "通用受众"
        core_message = "文档核心内容"
        presentation_goal = "传达文档核心信息"

        if content_map is not None:
            core_message = content_map.document_thesis
        elif analysis is not None:
            core_message = analysis.theme
            audience_map = {
                "business": "商务管理层",
                "technical": "技术人员",
                "educational": "学员/学生",
                "creative": "创意工作者",
                "general": "通用受众",
            }
            audience = audience_map.get(analysis.audience.value, "通用受众")

        # 从默认 slides 构建 SlideTask
        slides: list[SlideTask] = []
        for sd in default_slides:
            role_str = sd.get("page_role", "background")
            try:
                role = PageRole(role_str)
            except ValueError:
                role = PageRole.BACKGROUND

            is_str = sd.get("image_strategy", "none")
            try:
                img_strat = ImageStrategy(is_str)
            except ValueError:
                img_strat = ImageStrategy.NONE

            slides.append(
                SlideTask(
                    page_role=role,
                    page_goal=sd.get("page_goal", f"展示 {role.value} 内容"),
                    must_include=sd.get("must_include", []),
                    forbidden_content=sd.get("forbidden_content", []),
                    image_strategy=img_strat,
                    layout_preference=sd.get("layout_preference"),
                )
            )

        return PresentationPlan(
            deck_type=deck_type,
            audience=audience,
            core_message=core_message,
            presentation_goal=presentation_goal,
            narrative_arc=narrative_arc,
            slides=slides,
        )
