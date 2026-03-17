"""演示计划器测试"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.ppt.models import (
    Audience,
    ContentBlock,
    ContentMap,
    DeckType,
    DocumentAnalysis,
    DocumentType,
    ImageStrategy,
    PageRole,
    PresentationPlan,
    SlideTask,
    Tone,
)
from src.ppt.presentation_planner import (
    PresentationPlanner,
    _DEFAULT_NARRATIVE_ARC,
    _DEFAULT_SLIDES,
    _MAX_PAGES_DEFAULT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_response(data: dict) -> LLMResponse:
    """构造 LLM 响应。"""
    return LLMResponse(content=json.dumps(data, ensure_ascii=False), model="test")


def _make_analysis(
    doc_type: DocumentType = DocumentType.BUSINESS_REPORT,
    tone: Tone = Tone.PROFESSIONAL,
    audience: Audience = Audience.BUSINESS,
) -> DocumentAnalysis:
    """构造 DocumentAnalysis。"""
    return DocumentAnalysis(
        theme="AI 技术正在重塑全球市场格局",
        doc_type=doc_type,
        audience=audience,
        tone=tone,
        key_points=["AI 市场规模达5.2万亿", "增长率30%", "企业数字化转型加速"],
        has_sections=True,
        has_data=True,
        has_quotes=True,
        estimated_pages=15,
    )


def _make_content_map(n_blocks: int = 8) -> ContentMap:
    """构造 ContentMap。"""
    blocks = []
    for i in range(n_blocks):
        blocks.append(
            ContentBlock(
                block_id=f"b{i + 1}",
                block_type=["thesis", "argument", "data", "quote", "example", "conclusion"][
                    i % 6
                ],
                title=f"内容块标题{i + 1}",
                summary=f"这是第{i + 1}个内容块的摘要，包含关键数据增长率达到30%。",
                source_text=f"原文片段{i + 1}。",
                importance=max(1, min(5, 5 - i)),
            )
        )
    return ContentMap(
        document_thesis="AI 技术正在重塑全球市场格局",
        content_blocks=blocks,
        logical_flow=[f"b{i + 1}" for i in range(n_blocks)],
        key_data_points=["市场规模5.2万亿", "增长率30%"],
        key_quotes=["AI不是未来，AI就是现在"],
    )


def _valid_plan_json(n_slides: int | None = None) -> dict:
    """返回一个合法的 PresentationPlan LLM 响应 JSON。

    默认包含覆盖 BUSINESS_REPORT 所有 required_roles 的 9 页骨架。
    指定 n_slides 时从基础 roles 循环生成指定数量。
    """
    # 基础 roles 覆盖 BUSINESS_REPORT required_roles:
    # cover, executive_summary, progress, next_steps, closing
    base_roles = [
        "cover",
        "executive_summary",
        "background",
        "progress",
        "data_evidence",
        "solution",
        "risk_problem",
        "next_steps",
        "closing",
    ]

    if n_slides is None:
        roles_to_use = base_roles
    else:
        roles_to_use = [base_roles[i % len(base_roles)] for i in range(n_slides)]

    slides = []
    for i, role in enumerate(roles_to_use):
        slides.append(
            {
                "page_role": role,
                "page_goal": f"第{i + 1}页目标：展示{role}相关内容",
                "must_include": [f"内容要求{i + 1}"],
                "forbidden_content": [],
                "image_strategy": "none" if i == 0 else "chart",
                "layout_preference": "title_hero" if role == "cover" else None,
            }
        )
    return {
        "audience": "企业管理层和技术负责人",
        "core_message": "AI 正在重塑市场格局，我们需要抓住机遇",
        "presentation_goal": "让受众认识到 AI 转型的紧迫性并采取行动",
        "slides": slides,
    }


@pytest.fixture()
def planner():
    """创建 mock LLM 的 PresentationPlanner。"""
    with patch("src.ppt.presentation_planner.create_llm_client") as mock_create:
        mock_llm = MagicMock()
        mock_create.return_value = mock_llm
        pp = PresentationPlanner({"llm": {}})
        pp._mock_llm = mock_llm  # 方便测试中设置返回值
        yield pp


# ---------------------------------------------------------------------------
# 1. plan() with valid content_map -> returns valid PresentationPlan
# ---------------------------------------------------------------------------


class TestPlanHappyPath:
    """测试正常规划流程。"""

    def test_plan_returns_valid_presentation_plan(self, planner: PresentationPlanner):
        """plan() 返回有效的 PresentationPlan 对象。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        analysis = _make_analysis()
        content_map = _make_content_map()

        result = planner.plan("文档内容", analysis, content_map=content_map)

        assert isinstance(result, PresentationPlan)
        assert result.deck_type == DeckType.BUSINESS_REPORT
        assert result.audience == "企业管理层和技术负责人"
        assert result.core_message == "AI 正在重塑市场格局，我们需要抓住机遇"
        assert result.presentation_goal == "让受众认识到 AI 转型的紧迫性并采取行动"
        assert len(result.slides) == 9  # 9-page BUSINESS_REPORT skeleton
        assert all(isinstance(s, SlideTask) for s in result.slides)

    def test_slides_have_required_fields(self, planner: PresentationPlanner):
        """每个 SlideTask 都包含 page_role, page_goal, must_include。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan("文档内容", _make_analysis(), content_map=_make_content_map())

        for slide in result.slides:
            assert isinstance(slide.page_role, PageRole)
            assert len(slide.page_goal) > 0
            assert isinstance(slide.must_include, list)
            assert isinstance(slide.forbidden_content, list)
            assert isinstance(slide.image_strategy, ImageStrategy)

    def test_plan_with_content_map_includes_thesis_in_prompt(
        self, planner: PresentationPlanner
    ):
        """content_map 非空时，LLM 提示中包含文档核心论点。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        content_map = _make_content_map()
        planner.plan("文档内容", _make_analysis(), content_map=content_map)

        call_args = planner._mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "AI 技术正在重塑全球市场格局" in user_msg


# ---------------------------------------------------------------------------
# 2. Deck type auto-detection from analysis
# ---------------------------------------------------------------------------


class TestDeckTypeAutoDetection:
    """测试 PPT 类型自动检测。"""

    def test_teaching_doc_type_maps_to_course_lecture(self, planner: PresentationPlanner):
        """教学类文档自动检测为 COURSE_LECTURE。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        analysis = _make_analysis(doc_type=DocumentType.TEACHING)

        # 禁用 deck_strategies 模块以测试内置映射
        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", analysis)

        assert result.deck_type == DeckType.COURSE_LECTURE

    def test_product_intro_doc_type_maps_correctly(self, planner: PresentationPlanner):
        """产品介绍类文档自动检测为 PRODUCT_INTRO。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        analysis = _make_analysis(doc_type=DocumentType.PRODUCT_INTRO)

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", analysis)

        assert result.deck_type == DeckType.PRODUCT_INTRO

    def test_creative_pitch_maps_to_product_intro(self, planner: PresentationPlanner):
        """创意提案文档映射为 PRODUCT_INTRO。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        analysis = _make_analysis(doc_type=DocumentType.CREATIVE_PITCH)

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", analysis)

        assert result.deck_type == DeckType.PRODUCT_INTRO

    def test_other_doc_type_defaults_to_business_report(self, planner: PresentationPlanner):
        """其他文档类型默认为 BUSINESS_REPORT。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        analysis = _make_analysis(doc_type=DocumentType.OTHER)

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", analysis)

        assert result.deck_type == DeckType.BUSINESS_REPORT

    def test_no_analysis_defaults_to_business_report(self, planner: PresentationPlanner):
        """analysis 为 None 时默认为 BUSINESS_REPORT。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", analysis=None)

        assert result.deck_type == DeckType.BUSINESS_REPORT


# ---------------------------------------------------------------------------
# 3. Explicit deck_type override
# ---------------------------------------------------------------------------


class TestExplicitDeckType:
    """测试显式指定 deck_type。"""

    def test_explicit_deck_type_overrides_analysis(self, planner: PresentationPlanner):
        """显式指定 deck_type 时忽略 analysis 的推断。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        # analysis 指向 teaching，但显式指定 product_intro
        analysis = _make_analysis(doc_type=DocumentType.TEACHING)

        result = planner.plan(
            "文档内容",
            analysis,
            deck_type=DeckType.PRODUCT_INTRO,
        )

        assert result.deck_type == DeckType.PRODUCT_INTRO

    def test_explicit_course_lecture(self, planner: PresentationPlanner):
        """显式指定 COURSE_LECTURE。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan(
            "文档内容",
            _make_analysis(),
            deck_type=DeckType.COURSE_LECTURE,
        )

        assert result.deck_type == DeckType.COURSE_LECTURE


# ---------------------------------------------------------------------------
# 4. max_pages constraint
# ---------------------------------------------------------------------------


class TestMaxPagesConstraint:
    """测试最大页数限制。"""

    def test_slides_capped_at_max_pages(self, planner: PresentationPlanner):
        """slides 数量不超过 max_pages。"""
        data = _valid_plan_json(n_slides=15)
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan(
            "文档内容",
            _make_analysis(),
            max_pages=8,
        )

        assert len(result.slides) <= 8

    def test_default_max_pages_applied(self, planner: PresentationPlanner):
        """未指定 max_pages 时使用默认值。"""
        data = _valid_plan_json(n_slides=30)
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan("文档内容", _make_analysis())

        assert len(result.slides) <= _MAX_PAGES_DEFAULT

    def test_max_pages_in_llm_prompt(self, planner: PresentationPlanner):
        """max_pages 值出现在发送给 LLM 的提示中。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        planner.plan("文档内容", _make_analysis(), max_pages=10)

        call_args = planner._mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "10" in user_msg


# ---------------------------------------------------------------------------
# 5. LLM failure -> fallback to strategy skeleton
# ---------------------------------------------------------------------------


class TestLLMFailureFallback:
    """测试 LLM 失败时降级为策略骨架。"""

    def test_llm_exception_falls_back(self, planner: PresentationPlanner):
        """LLM 调用抛异常时使用 fallback。"""
        planner._mock_llm.chat.side_effect = RuntimeError("API Error")

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", _make_analysis())

        assert isinstance(result, PresentationPlan)
        assert len(result.slides) >= 1
        assert result.deck_type == DeckType.BUSINESS_REPORT

    def test_llm_garbage_response_falls_back(self, planner: PresentationPlanner):
        """LLM 返回非 JSON 文本时使用 fallback。"""
        planner._mock_llm.chat.return_value = LLMResponse(
            content="这不是 JSON 格式的回复，无法解析。", model="test"
        )

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", _make_analysis())

        assert isinstance(result, PresentationPlan)
        assert len(result.slides) >= 1

    def test_llm_empty_slides_falls_back(self, planner: PresentationPlanner):
        """LLM 返回空 slides 列表时使用 fallback。"""
        data = {
            "audience": "受众",
            "core_message": "核心信息",
            "presentation_goal": "目标",
            "slides": [],
        }
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", _make_analysis())

        assert isinstance(result, PresentationPlan)
        assert len(result.slides) >= 1

    def test_llm_missing_slides_key_falls_back(self, planner: PresentationPlanner):
        """LLM 返回 JSON 但无 slides 字段时使用 fallback。"""
        data = {
            "audience": "受众",
            "core_message": "核心信息",
        }
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", _make_analysis())

        assert isinstance(result, PresentationPlan)
        assert len(result.slides) >= 1

    def test_fallback_uses_content_map_thesis(self, planner: PresentationPlanner):
        """fallback 模式下使用 content_map 的 thesis 作为 core_message。"""
        planner._mock_llm.chat.side_effect = RuntimeError("API Error")

        content_map = _make_content_map()

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", _make_analysis(), content_map=content_map)

        assert result.core_message == "AI 技术正在重塑全球市场格局"

    def test_fallback_uses_analysis_theme_when_no_content_map(
        self, planner: PresentationPlanner
    ):
        """fallback 模式下无 content_map 时使用 analysis.theme。"""
        planner._mock_llm.chat.side_effect = RuntimeError("API Error")

        analysis = _make_analysis()

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", analysis)

        assert result.core_message == analysis.theme


# ---------------------------------------------------------------------------
# 6. Required roles are always present in output
# ---------------------------------------------------------------------------


class TestRequiredRoles:
    """测试必需角色始终出现在输出中。"""

    def test_cover_always_present(self, planner: PresentationPlanner):
        """输出中始终包含 cover 页。"""
        # LLM 返回没有 cover 的 slides
        data = _valid_plan_json()
        data["slides"] = [
            s for s in data["slides"] if s["page_role"] != "cover"
        ]
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", _make_analysis())

        roles = [s.page_role for s in result.slides]
        assert PageRole.COVER in roles

    def test_closing_always_present(self, planner: PresentationPlanner):
        """输出中始终包含 closing 页。"""
        # LLM 返回没有 closing 的 slides
        data = _valid_plan_json()
        data["slides"] = [
            s for s in data["slides"] if s["page_role"] != "closing"
        ]
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", _make_analysis())

        roles = [s.page_role for s in result.slides]
        assert PageRole.CLOSING in roles

    def test_cover_is_first_slide(self, planner: PresentationPlanner):
        """cover 页在第一个位置。"""
        # LLM 没有返回 cover，系统自动补充并放在首位
        data = _valid_plan_json()
        data["slides"] = [
            s for s in data["slides"] if s["page_role"] != "cover"
        ]
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", _make_analysis())

        assert result.slides[0].page_role == PageRole.COVER

    def test_closing_is_last_slide(self, planner: PresentationPlanner):
        """closing 页在最后位置。"""
        # LLM 没有返回 closing，系统自动补充并放在末尾
        data = _valid_plan_json()
        data["slides"] = [
            s for s in data["slides"] if s["page_role"] != "closing"
        ]
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", _make_analysis())

        assert result.slides[-1].page_role == PageRole.CLOSING

    def test_both_cover_and_closing_missing_are_added(
        self, planner: PresentationPlanner
    ):
        """cover 和 closing 都缺失时都被补上。"""
        data = _valid_plan_json()
        data["slides"] = [
            s
            for s in data["slides"]
            if s["page_role"] not in ("cover", "closing")
        ]
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", _make_analysis())

        roles = {s.page_role for s in result.slides}
        assert PageRole.COVER in roles
        assert PageRole.CLOSING in roles


# ---------------------------------------------------------------------------
# 7. Plan without content_map (content_map=None) still works
# ---------------------------------------------------------------------------


class TestPlanWithoutContentMap:
    """测试 content_map 为 None 时的行为。"""

    def test_plan_without_content_map(self, planner: PresentationPlanner):
        """content_map=None 时依然返回有效 plan。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan("文档内容", _make_analysis(), content_map=None)

        assert isinstance(result, PresentationPlan)
        assert len(result.slides) >= 1

    def test_plan_without_content_map_uses_analysis_in_prompt(
        self, planner: PresentationPlanner
    ):
        """content_map=None 时 LLM 提示中使用 analysis 信息。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        analysis = _make_analysis()
        planner.plan("文档内容", analysis, content_map=None)

        call_args = planner._mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert analysis.theme in user_msg

    def test_plan_without_analysis_and_content_map(self, planner: PresentationPlanner):
        """analysis 和 content_map 都为 None 时依然正常工作。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan("文档内容", analysis=None, content_map=None)

        assert isinstance(result, PresentationPlan)
        assert len(result.slides) >= 1

    def test_fallback_without_content_map_and_analysis(
        self, planner: PresentationPlanner
    ):
        """LLM 失败 + content_map=None + analysis=None 时 fallback 仍工作。"""
        planner._mock_llm.chat.side_effect = RuntimeError("API Error")

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", analysis=None, content_map=None)

        assert isinstance(result, PresentationPlan)
        assert result.core_message == "文档核心内容"
        assert result.audience == "通用受众"


# ---------------------------------------------------------------------------
# 8. Each deck_type produces a valid plan
# ---------------------------------------------------------------------------


class TestAllDeckTypes:
    """测试每种 DeckType 都能生成有效计划。"""

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_each_deck_type_produces_valid_plan(
        self, planner: PresentationPlanner, deck_type: DeckType
    ):
        """每种 DeckType 都能生成有效的 PresentationPlan。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan(
            "文档内容",
            _make_analysis(),
            deck_type=deck_type,
        )

        assert isinstance(result, PresentationPlan)
        assert result.deck_type == deck_type
        assert len(result.slides) >= 1

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_each_deck_type_fallback_works(
        self, planner: PresentationPlanner, deck_type: DeckType
    ):
        """每种 DeckType 在 LLM 失败时 fallback 也工作正常。"""
        planner._mock_llm.chat.side_effect = RuntimeError("API Error")

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan(
                "文档内容",
                _make_analysis(),
                deck_type=deck_type,
            )

        assert isinstance(result, PresentationPlan)
        assert result.deck_type == deck_type
        assert len(result.slides) >= 1


# ---------------------------------------------------------------------------
# 9. Narrative arc is preserved from strategy
# ---------------------------------------------------------------------------


class TestNarrativeArc:
    """测试叙事弧线保留。"""

    def test_narrative_arc_from_default_strategy(self, planner: PresentationPlanner):
        """默认策略骨架的叙事弧线被正确保留。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", _make_analysis())

        assert result.narrative_arc == list(_DEFAULT_NARRATIVE_ARC)

    def test_narrative_arc_not_empty(self, planner: PresentationPlanner):
        """叙事弧线不为空。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan("文档内容", _make_analysis())

        assert len(result.narrative_arc) >= 1

    def test_narrative_arc_is_list_of_strings(self, planner: PresentationPlanner):
        """叙事弧线是字符串列表。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan("文档内容", _make_analysis())

        assert isinstance(result.narrative_arc, list)
        assert all(isinstance(item, str) for item in result.narrative_arc)


# ---------------------------------------------------------------------------
# 10. Slides have page_role, page_goal, must_include fields
# ---------------------------------------------------------------------------


class TestSlideTaskFields:
    """测试 SlideTask 的字段完整性。"""

    def test_all_slides_have_page_role(self, planner: PresentationPlanner):
        """每个 slide 都有有效的 page_role。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan("文档内容", _make_analysis())

        for slide in result.slides:
            assert isinstance(slide.page_role, PageRole)

    def test_all_slides_have_page_goal(self, planner: PresentationPlanner):
        """每个 slide 都有非空的 page_goal。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan("文档内容", _make_analysis())

        for slide in result.slides:
            assert isinstance(slide.page_goal, str)
            assert len(slide.page_goal) > 0

    def test_must_include_is_list(self, planner: PresentationPlanner):
        """must_include 是列表。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan("文档内容", _make_analysis())

        for slide in result.slides:
            assert isinstance(slide.must_include, list)

    def test_image_strategy_is_valid_enum(self, planner: PresentationPlanner):
        """image_strategy 是有效的 ImageStrategy 枚举值。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan("文档内容", _make_analysis())

        for slide in result.slides:
            assert isinstance(slide.image_strategy, ImageStrategy)

    def test_forbidden_content_is_list(self, planner: PresentationPlanner):
        """forbidden_content 是列表。"""
        data = _valid_plan_json()
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan("文档内容", _make_analysis())

        for slide in result.slides:
            assert isinstance(slide.forbidden_content, list)


# ---------------------------------------------------------------------------
# Edge cases: invalid page_role from LLM
# ---------------------------------------------------------------------------


class TestInvalidPageRoles:
    """测试 LLM 返回无效 page_role 的处理。"""

    def test_invalid_page_roles_skipped(self, planner: PresentationPlanner):
        """无效的 page_role 被跳过。"""
        data = _valid_plan_json()
        data["slides"].append(
            {
                "page_role": "invalid_role_xyz",
                "page_goal": "这页有无效角色",
                "must_include": [],
            }
        )
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        with patch("src.ppt.presentation_planner._HAS_STRATEGIES", False):
            result = planner.plan("文档内容", _make_analysis())

        # 无效角色应被跳过，不影响整体
        for slide in result.slides:
            assert isinstance(slide.page_role, PageRole)

    def test_invalid_image_strategy_defaults_to_none(
        self, planner: PresentationPlanner
    ):
        """无效的 image_strategy 默认为 NONE。"""
        data = _valid_plan_json()
        for s in data["slides"]:
            s["image_strategy"] = "nonexistent_strategy"
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan("文档内容", _make_analysis())

        for slide in result.slides:
            assert slide.image_strategy == ImageStrategy.NONE

    def test_empty_page_goal_gets_default(self, planner: PresentationPlanner):
        """空 page_goal 得到默认值。"""
        data = _valid_plan_json()
        data["slides"][0]["page_goal"] = ""
        planner._mock_llm.chat.return_value = _make_llm_response(data)

        result = planner.plan("文档内容", _make_analysis())

        assert len(result.slides[0].page_goal) > 0


# ---------------------------------------------------------------------------
# LLM call parameters
# ---------------------------------------------------------------------------


class TestLLMCallParams:
    """测试 LLM 调用参数正确性。"""

    def test_json_mode_enabled(self, planner: PresentationPlanner):
        """确认使用 json_mode=True。"""
        planner._mock_llm.chat.return_value = _make_llm_response(_valid_plan_json())
        planner.plan("文档内容", _make_analysis())

        call_kwargs = planner._mock_llm.chat.call_args
        assert call_kwargs[1].get("json_mode") is True

    def test_system_prompt_present(self, planner: PresentationPlanner):
        """确认包含 system prompt。"""
        planner._mock_llm.chat.return_value = _make_llm_response(_valid_plan_json())
        planner.plan("文档内容", _make_analysis())

        messages = planner._mock_llm.chat.call_args[0][0]
        assert messages[0]["role"] == "system"
        assert "演示策划师" in messages[0]["content"]

    def test_temperature_is_moderate(self, planner: PresentationPlanner):
        """确认使用适中的 temperature。"""
        planner._mock_llm.chat.return_value = _make_llm_response(_valid_plan_json())
        planner.plan("文档内容", _make_analysis())

        call_kwargs = planner._mock_llm.chat.call_args
        temp = call_kwargs[1].get("temperature", 1.0)
        assert 0.1 <= temp <= 0.7

    def test_max_tokens_set(self, planner: PresentationPlanner):
        """确认设置了 max_tokens。"""
        planner._mock_llm.chat.return_value = _make_llm_response(_valid_plan_json())
        planner.plan("文档内容", _make_analysis())

        call_kwargs = planner._mock_llm.chat.call_args
        assert call_kwargs[1].get("max_tokens") is not None
        assert call_kwargs[1]["max_tokens"] > 0
