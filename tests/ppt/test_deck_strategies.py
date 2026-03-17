"""tests/ppt/test_deck_strategies.py - 三类 PPT 策略定义测试"""

import pytest

from src.ppt.deck_strategies import (
    BUSINESS_REPORT_STRATEGY,
    COURSE_LECTURE_STRATEGY,
    PRODUCT_INTRO_STRATEGY,
    STRATEGIES,
    detect_deck_type,
    get_anti_patterns,
    get_default_slides,
    get_strategy,
    get_writing_style,
)
from src.ppt.models import (
    DeckType,
    ImageStrategy,
    PageRole,
    SlideTask,
)

# =========================================================================
# Required keys that every strategy dict must have
# =========================================================================

REQUIRED_STRATEGY_KEYS = {
    "narrative_arc",
    "default_slides",
    "required_roles",
    "preferred_image_strategy",
    "default_enrich_level",
    "writing_style",
    "audience_hint",
    "anti_patterns",
}


# =========================================================================
# Strategy structure validation
# =========================================================================


class TestStrategyStructure:
    """Every strategy dict must have the right shape."""

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_all_deck_types_have_strategies(self, deck_type: DeckType):
        assert deck_type in STRATEGIES, (
            f"DeckType.{deck_type.name} has no entry in STRATEGIES"
        )

    @pytest.mark.parametrize(
        "name,strategy",
        [
            ("BUSINESS_REPORT", BUSINESS_REPORT_STRATEGY),
            ("COURSE_LECTURE", COURSE_LECTURE_STRATEGY),
            ("PRODUCT_INTRO", PRODUCT_INTRO_STRATEGY),
        ],
    )
    def test_required_keys_present(self, name: str, strategy: dict):
        missing = REQUIRED_STRATEGY_KEYS - set(strategy.keys())
        assert not missing, f"{name} is missing keys: {missing}"

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_narrative_arc_is_nonempty_list(self, deck_type: DeckType):
        arc = STRATEGIES[deck_type]["narrative_arc"]
        assert isinstance(arc, list)
        assert len(arc) > 0
        assert all(isinstance(item, str) for item in arc)

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_default_slides_are_slide_task_instances(self, deck_type: DeckType):
        slides = STRATEGIES[deck_type]["default_slides"]
        assert isinstance(slides, list)
        assert len(slides) > 0
        for slide in slides:
            assert isinstance(slide, SlideTask), (
                f"Expected SlideTask, got {type(slide)}"
            )

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_required_roles_subset_of_default_slides(self, deck_type: DeckType):
        strategy = STRATEGIES[deck_type]
        slide_roles = {s.page_role for s in strategy["default_slides"]}
        required = strategy["required_roles"]
        missing = required - slide_roles
        assert not missing, (
            f"DeckType.{deck_type.name}: required roles {missing} "
            f"not found in default_slides"
        )

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_preferred_image_strategy_is_valid(self, deck_type: DeckType):
        pref = STRATEGIES[deck_type]["preferred_image_strategy"]
        assert isinstance(pref, ImageStrategy)

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_default_enrich_level_is_valid(self, deck_type: DeckType):
        level = STRATEGIES[deck_type]["default_enrich_level"]
        assert level in {"none", "llm", "web"}

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_writing_style_contains_examples(self, deck_type: DeckType):
        style = STRATEGIES[deck_type]["writing_style"]
        assert isinstance(style, str)
        assert len(style) > 50
        # Must contain both positive and negative examples
        assert "正确示范" in style, (
            f"DeckType.{deck_type.name} writing_style missing positive example"
        )
        assert "错误示范" in style, (
            f"DeckType.{deck_type.name} writing_style missing negative example"
        )

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_anti_patterns_is_nonempty_list(self, deck_type: DeckType):
        patterns = STRATEGIES[deck_type]["anti_patterns"]
        assert isinstance(patterns, list)
        assert len(patterns) > 0
        assert all(isinstance(p, str) for p in patterns)

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_audience_hint_is_nonempty_string(self, deck_type: DeckType):
        hint = STRATEGIES[deck_type]["audience_hint"]
        assert isinstance(hint, str)
        assert len(hint) > 0


# =========================================================================
# Specific strategy content checks
# =========================================================================


class TestBusinessReportStrategy:
    """汇报材料策略特定验证"""

    def test_first_slide_is_cover(self):
        slides = BUSINESS_REPORT_STRATEGY["default_slides"]
        assert slides[0].page_role == PageRole.COVER

    def test_second_slide_is_executive_summary(self):
        slides = BUSINESS_REPORT_STRATEGY["default_slides"]
        assert slides[1].page_role == PageRole.EXECUTIVE_SUMMARY

    def test_last_slide_is_closing(self):
        slides = BUSINESS_REPORT_STRATEGY["default_slides"]
        assert slides[-1].page_role == PageRole.CLOSING

    def test_enrich_level_is_none(self):
        """汇报材料最怕补错数据，default_enrich_level 必须是 none"""
        assert BUSINESS_REPORT_STRATEGY["default_enrich_level"] == "none"

    def test_preferred_image_is_chart(self):
        assert (
            BUSINESS_REPORT_STRATEGY["preferred_image_strategy"]
            == ImageStrategy.CHART
        )

    def test_executive_summary_has_forbidden_content(self):
        slides = BUSINESS_REPORT_STRATEGY["default_slides"]
        exec_summary = slides[1]
        assert len(exec_summary.forbidden_content) > 0


class TestCourseLectureStrategy:
    """课程讲义策略特定验证"""

    def test_first_slide_is_cover(self):
        slides = COURSE_LECTURE_STRATEGY["default_slides"]
        assert slides[0].page_role == PageRole.COVER

    def test_has_learning_objectives(self):
        roles = {s.page_role for s in COURSE_LECTURE_STRATEGY["default_slides"]}
        assert PageRole.LEARNING_OBJECTIVES in roles

    def test_has_exercise_page(self):
        roles = {s.page_role for s in COURSE_LECTURE_STRATEGY["default_slides"]}
        assert PageRole.EXERCISE in roles

    def test_has_summary_review(self):
        roles = {s.page_role for s in COURSE_LECTURE_STRATEGY["default_slides"]}
        assert PageRole.SUMMARY_REVIEW in roles

    def test_preferred_image_is_diagram(self):
        assert (
            COURSE_LECTURE_STRATEGY["preferred_image_strategy"]
            == ImageStrategy.DIAGRAM
        )

    def test_enrich_level_is_llm(self):
        assert COURSE_LECTURE_STRATEGY["default_enrich_level"] == "llm"

    def test_last_slide_is_closing(self):
        slides = COURSE_LECTURE_STRATEGY["default_slides"]
        assert slides[-1].page_role == PageRole.CLOSING


class TestProductIntroStrategy:
    """产品介绍策略特定验证"""

    def test_first_slide_is_cover(self):
        slides = PRODUCT_INTRO_STRATEGY["default_slides"]
        assert slides[0].page_role == PageRole.COVER

    def test_has_pain_point(self):
        roles = {s.page_role for s in PRODUCT_INTRO_STRATEGY["default_slides"]}
        assert PageRole.PAIN_POINT in roles

    def test_has_cta(self):
        roles = {s.page_role for s in PRODUCT_INTRO_STRATEGY["default_slides"]}
        assert PageRole.CTA in roles

    def test_pain_point_forbids_direct_sales(self):
        slides = PRODUCT_INTRO_STRATEGY["default_slides"]
        pain_slide = [
            s for s in slides if s.page_role == PageRole.PAIN_POINT
        ][0]
        assert "直接推销产品" in pain_slide.forbidden_content

    def test_preferred_image_is_ui_mock(self):
        assert (
            PRODUCT_INTRO_STRATEGY["preferred_image_strategy"]
            == ImageStrategy.UI_MOCK
        )

    def test_enrich_level_is_llm(self):
        assert PRODUCT_INTRO_STRATEGY["default_enrich_level"] == "llm"

    def test_last_slide_is_cta(self):
        slides = PRODUCT_INTRO_STRATEGY["default_slides"]
        assert slides[-1].page_role == PageRole.CTA


# =========================================================================
# Helper functions
# =========================================================================


class TestGetStrategy:
    """get_strategy() 辅助函数测试"""

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_returns_dict(self, deck_type: DeckType):
        result = get_strategy(deck_type)
        assert isinstance(result, dict)
        assert REQUIRED_STRATEGY_KEYS <= set(result.keys())

    def test_returns_correct_strategy(self):
        assert get_strategy(DeckType.BUSINESS_REPORT) is BUSINESS_REPORT_STRATEGY
        assert get_strategy(DeckType.COURSE_LECTURE) is COURSE_LECTURE_STRATEGY
        assert get_strategy(DeckType.PRODUCT_INTRO) is PRODUCT_INTRO_STRATEGY

    def test_invalid_key_raises(self):
        with pytest.raises(KeyError):
            get_strategy("nonexistent")  # type: ignore[arg-type]


class TestGetDefaultSlides:
    """get_default_slides() 辅助函数测试"""

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_returns_list_of_slide_tasks(self, deck_type: DeckType):
        slides = get_default_slides(deck_type)
        assert isinstance(slides, list)
        assert all(isinstance(s, SlideTask) for s in slides)

    def test_business_report_slide_count(self):
        slides = get_default_slides(DeckType.BUSINESS_REPORT)
        assert len(slides) == 9

    def test_course_lecture_slide_count(self):
        slides = get_default_slides(DeckType.COURSE_LECTURE)
        assert len(slides) == 11

    def test_product_intro_slide_count(self):
        slides = get_default_slides(DeckType.PRODUCT_INTRO)
        assert len(slides) == 10


class TestGetWritingStyle:
    """get_writing_style() 辅助函数测试"""

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_returns_nonempty_string(self, deck_type: DeckType):
        style = get_writing_style(deck_type)
        assert isinstance(style, str)
        assert len(style) > 0


class TestGetAntiPatterns:
    """get_anti_patterns() 辅助函数测试"""

    @pytest.mark.parametrize("deck_type", list(DeckType))
    def test_returns_nonempty_list(self, deck_type: DeckType):
        patterns = get_anti_patterns(deck_type)
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    def test_business_report_anti_patterns(self):
        patterns = get_anti_patterns(DeckType.BUSINESS_REPORT)
        assert "持续推进" in patterns
        assert "阶段性成果" in patterns

    def test_course_lecture_anti_patterns(self):
        patterns = get_anti_patterns(DeckType.COURSE_LECTURE)
        assert "众所周知" in patterns

    def test_product_intro_anti_patterns(self):
        patterns = get_anti_patterns(DeckType.PRODUCT_INTRO)
        assert "业界领先" in patterns


# =========================================================================
# detect_deck_type
# =========================================================================


class TestDetectDeckType:
    """detect_deck_type() 自动检测测试"""

    # doc_type based detection
    def test_tech_share_maps_to_course_lecture(self):
        assert detect_deck_type("tech_share", "") == DeckType.COURSE_LECTURE

    def test_teaching_maps_to_course_lecture(self):
        assert detect_deck_type("teaching", "") == DeckType.COURSE_LECTURE

    def test_academic_maps_to_course_lecture(self):
        assert detect_deck_type("academic", "") == DeckType.COURSE_LECTURE

    def test_business_report_maps_to_business_report(self):
        assert (
            detect_deck_type("business_report", "")
            == DeckType.BUSINESS_REPORT
        )

    def test_summary_maps_to_business_report(self):
        assert detect_deck_type("summary", "") == DeckType.BUSINESS_REPORT

    def test_marketing_maps_to_product_intro(self):
        assert detect_deck_type("marketing", "") == DeckType.PRODUCT_INTRO

    def test_product_intro_maps_to_product_intro(self):
        assert detect_deck_type("product_intro", "") == DeckType.PRODUCT_INTRO

    def test_product_maps_to_product_intro(self):
        assert detect_deck_type("product", "") == DeckType.PRODUCT_INTRO

    # tone-based fallback
    def test_unknown_doc_type_technical_tone(self):
        assert (
            detect_deck_type("other", "technical") == DeckType.COURSE_LECTURE
        )

    def test_unknown_doc_type_creative_tone(self):
        assert detect_deck_type("other", "creative") == DeckType.PRODUCT_INTRO

    # default fallback
    def test_unknown_doc_type_unknown_tone(self):
        assert detect_deck_type("other", "casual") == DeckType.BUSINESS_REPORT

    def test_empty_strings_default(self):
        assert detect_deck_type("", "") == DeckType.BUSINESS_REPORT

    # doc_type takes priority over tone
    def test_doc_type_priority_over_tone(self):
        """Even if tone suggests PRODUCT_INTRO, doc_type wins."""
        assert (
            detect_deck_type("tech_share", "creative")
            == DeckType.COURSE_LECTURE
        )

    def test_doc_type_priority_business(self):
        assert (
            detect_deck_type("business_report", "technical")
            == DeckType.BUSINESS_REPORT
        )
