"""tests/ppt/test_models.py - PPT 数据模型测试"""

import json

import pytest
from pydantic import ValidationError

from src.ppt.models import (
    Audience,
    ColorScheme,
    DeckType,
    DecorationSpec,
    DocumentAnalysis,
    DocumentType,
    FontSpec,
    ImageOrientation,
    ImageRequest,
    ImageStrategy,
    LayoutType,
    PageRole,
    PPTOutline,
    PPTProject,
    PresentationPlan,
    QualityIssue,
    QualityReport,
    SlideContent,
    SlideDesign,
    SlideOutline,
    SlideSpec,
    SlideTask,
    ThemeConfig,
    ThemeStyle,
    Tone,
)


# =========================================================================
# 枚举测试
# =========================================================================


class TestEnums:
    """枚举值覆盖"""

    def test_document_type_values(self):
        assert DocumentType.BUSINESS_REPORT == "business_report"
        assert DocumentType.PRODUCT_INTRO == "product_intro"
        assert DocumentType.TECH_SHARE == "tech_share"
        assert DocumentType.TEACHING == "teaching"
        assert DocumentType.CREATIVE_PITCH == "creative_pitch"
        assert DocumentType.OTHER == "other"
        assert len(DocumentType) == 6

    def test_audience_values(self):
        assert Audience.BUSINESS == "business"
        assert len(Audience) == 5

    def test_tone_values(self):
        assert Tone.PROFESSIONAL == "professional"
        assert Tone.WARM == "warm"
        assert len(Tone) == 5

    def test_layout_type_values(self):
        assert LayoutType.TITLE_HERO == "title_hero"
        assert LayoutType.CLOSING == "closing"
        assert len(LayoutType) == 12

    def test_theme_style_values(self):
        assert ThemeStyle.MODERN == "modern"
        assert len(ThemeStyle) == 5

    def test_image_orientation_values(self):
        assert ImageOrientation.LANDSCAPE == "landscape"
        assert ImageOrientation.PORTRAIT == "portrait"
        assert ImageOrientation.SQUARE == "square"

    def test_invalid_enum_value(self):
        with pytest.raises(ValueError):
            DocumentType("nonexistent")


# =========================================================================
# DocumentAnalysis 测试
# =========================================================================


class TestDocumentAnalysis:

    def _make(self, **overrides):
        defaults = {
            "theme": "AI 技术在教育中的应用",
            "doc_type": DocumentType.TECH_SHARE,
            "audience": Audience.TECHNICAL,
            "tone": Tone.PROFESSIONAL,
            "key_points": ["要点1", "要点2"],
            "estimated_pages": 15,
        }
        defaults.update(overrides)
        return DocumentAnalysis(**defaults)

    def test_basic_creation(self):
        analysis = self._make()
        assert analysis.theme == "AI 技术在教育中的应用"
        assert analysis.doc_type == DocumentType.TECH_SHARE
        assert analysis.estimated_pages == 15
        assert analysis.has_sections is False
        assert analysis.has_data is False
        assert analysis.has_quotes is False

    def test_all_fields(self):
        analysis = self._make(
            has_sections=True, has_data=True, has_quotes=True
        )
        assert analysis.has_sections is True
        assert analysis.has_data is True
        assert analysis.has_quotes is True

    def test_estimated_pages_min(self):
        analysis = self._make(estimated_pages=5)
        assert analysis.estimated_pages == 5

    def test_estimated_pages_max(self):
        analysis = self._make(estimated_pages=50)
        assert analysis.estimated_pages == 50

    def test_estimated_pages_too_low(self):
        with pytest.raises(ValidationError):
            self._make(estimated_pages=4)

    def test_estimated_pages_too_high(self):
        with pytest.raises(ValidationError):
            self._make(estimated_pages=51)

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            DocumentAnalysis(
                doc_type=DocumentType.OTHER,
                audience=Audience.GENERAL,
                tone=Tone.CASUAL,
                key_points=[],
                estimated_pages=10,
            )  # missing theme

    def test_json_roundtrip(self):
        original = self._make()
        json_str = original.model_dump_json()
        restored = DocumentAnalysis.model_validate_json(json_str)
        assert restored == original

    def test_doc_type_from_string(self):
        analysis = self._make(doc_type="product_intro")
        assert analysis.doc_type == DocumentType.PRODUCT_INTRO


# =========================================================================
# SlideContent 测试
# =========================================================================


class TestSlideContent:

    def test_minimal(self):
        content = SlideContent(title="标题")
        assert content.title == "标题"
        assert content.subtitle is None
        assert content.bullet_points == []
        assert content.body_text is None
        assert content.speaker_notes == ""
        assert content.data_value is None
        assert content.data_label is None

    def test_full(self):
        content = SlideContent(
            title="核心数据",
            subtitle="2024年度总结",
            bullet_points=["收入增长30%", "用户突破百万"],
            body_text="详细说明...",
            speaker_notes="大家好，这页展示...",
            data_value="30%",
            data_label="年增长率",
        )
        assert len(content.bullet_points) == 2
        assert content.data_value == "30%"

    def test_title_max_length(self):
        with pytest.raises(ValidationError):
            SlideContent(title="x" * 51)

    def test_subtitle_max_length(self):
        with pytest.raises(ValidationError):
            SlideContent(title="ok", subtitle="x" * 101)

    def test_json_roundtrip(self):
        content = SlideContent(title="测试", bullet_points=["a", "b"])
        restored = SlideContent.model_validate_json(content.model_dump_json())
        assert restored == content


# =========================================================================
# ColorScheme 测试
# =========================================================================


class TestColorScheme:

    def _make(self, **overrides):
        defaults = {
            "primary": "#2D3436",
            "secondary": "#636E72",
            "accent": "#0984E3",
            "text": "#2D3436",
        }
        defaults.update(overrides)
        return ColorScheme(**defaults)

    def test_basic(self):
        cs = self._make()
        assert cs.primary == "#2D3436"
        assert cs.background == "#FFFFFF"  # default

    def test_custom_background(self):
        cs = self._make(background="#000000")
        assert cs.background == "#000000"

    def test_invalid_color_format(self):
        with pytest.raises(ValidationError):
            self._make(primary="red")

    def test_invalid_color_short(self):
        with pytest.raises(ValidationError):
            self._make(primary="#FFF")

    def test_lowercase_hex_ok(self):
        cs = self._make(primary="#abcdef")
        assert cs.primary == "#abcdef"


# =========================================================================
# FontSpec 测试
# =========================================================================


class TestFontSpec:

    def test_basic(self):
        f = FontSpec(size=16, color="#000000")
        assert f.size == 16
        assert f.bold is False
        assert f.italic is False
        assert f.family == "微软雅黑"

    def test_size_min(self):
        f = FontSpec(size=10, color="#000000")
        assert f.size == 10

    def test_size_max(self):
        f = FontSpec(size=72, color="#000000")
        assert f.size == 72

    def test_size_too_small(self):
        with pytest.raises(ValidationError):
            FontSpec(size=9, color="#000000")

    def test_size_too_large(self):
        with pytest.raises(ValidationError):
            FontSpec(size=73, color="#000000")

    def test_custom_family(self):
        f = FontSpec(size=16, color="#000000", family="Arial")
        assert f.family == "Arial"


# =========================================================================
# DecorationSpec 测试
# =========================================================================


class TestDecorationSpec:

    def test_defaults(self):
        d = DecorationSpec()
        assert d.has_divider is False
        assert d.divider_width == 2
        assert d.has_background_shape is False
        assert d.shape_type is None
        assert d.shape_opacity == 0.2

    def test_divider_width_bounds(self):
        d = DecorationSpec(divider_width=1)
        assert d.divider_width == 1
        d = DecorationSpec(divider_width=5)
        assert d.divider_width == 5
        with pytest.raises(ValidationError):
            DecorationSpec(divider_width=0)
        with pytest.raises(ValidationError):
            DecorationSpec(divider_width=6)

    def test_shape_opacity_bounds(self):
        DecorationSpec(shape_opacity=0.0)
        DecorationSpec(shape_opacity=1.0)
        with pytest.raises(ValidationError):
            DecorationSpec(shape_opacity=-0.1)
        with pytest.raises(ValidationError):
            DecorationSpec(shape_opacity=1.1)

    def test_shape_type_literal(self):
        d = DecorationSpec(shape_type="rectangle")
        assert d.shape_type == "rectangle"
        d = DecorationSpec(shape_type="circle")
        assert d.shape_type == "circle"
        d = DecorationSpec(shape_type="gradient")
        assert d.shape_type == "gradient"
        with pytest.raises(ValidationError):
            DecorationSpec(shape_type="triangle")


# =========================================================================
# SlideDesign 测试
# =========================================================================


def _make_colors(**kw):
    defaults = {
        "primary": "#2D3436",
        "secondary": "#636E72",
        "accent": "#0984E3",
        "text": "#2D3436",
    }
    defaults.update(kw)
    return ColorScheme(**defaults)


def _make_font(**kw):
    defaults = {"size": 16, "color": "#000000"}
    defaults.update(kw)
    return FontSpec(**defaults)


class TestSlideDesign:

    def test_basic(self):
        sd = SlideDesign(
            layout=LayoutType.TITLE_HERO,
            colors=_make_colors(),
            title_font=_make_font(size=36),
            body_font=_make_font(size=16),
            note_font=_make_font(size=14),
        )
        assert sd.layout == LayoutType.TITLE_HERO
        assert sd.padding == {"left": 80, "right": 80, "top": 60, "bottom": 60}
        assert sd.decoration.has_divider is False

    def test_custom_padding(self):
        sd = SlideDesign(
            layout=LayoutType.CLOSING,
            colors=_make_colors(),
            title_font=_make_font(size=36),
            body_font=_make_font(size=16),
            note_font=_make_font(size=14),
            padding={"left": 100, "right": 100, "top": 80, "bottom": 80},
        )
        assert sd.padding["left"] == 100


# =========================================================================
# ImageRequest 测试
# =========================================================================


class TestImageRequest:

    def test_basic(self):
        req = ImageRequest(
            page_number=1,
            prompt="abstract modern background",
            style="abstract_business",
        )
        assert req.page_number == 1
        assert req.size == ImageOrientation.LANDSCAPE

    def test_custom_size(self):
        req = ImageRequest(
            page_number=2,
            prompt="test",
            size=ImageOrientation.SQUARE,
            style="flat",
        )
        assert req.size == ImageOrientation.SQUARE

    def test_page_number_zero(self):
        with pytest.raises(ValidationError):
            ImageRequest(page_number=0, prompt="test", style="flat")


# =========================================================================
# SlideSpec 测试
# =========================================================================


def _make_slide_spec(page_number=1, **kw):
    content = SlideContent(title=f"Page {page_number}")
    design = SlideDesign(
        layout=LayoutType.BULLET_WITH_ICONS,
        colors=_make_colors(),
        title_font=_make_font(size=36),
        body_font=_make_font(size=16),
        note_font=_make_font(size=14),
    )
    defaults = {
        "page_number": page_number,
        "content": content,
        "design": design,
    }
    defaults.update(kw)
    return SlideSpec(**defaults)


class TestSlideSpec:

    def test_basic(self):
        s = _make_slide_spec()
        assert s.page_number == 1
        assert s.needs_image is False
        assert s.image_request is None
        assert s.image_path is None

    def test_with_image(self):
        req = ImageRequest(page_number=3, prompt="tech bg", style="tech")
        s = _make_slide_spec(page_number=3, needs_image=True, image_request=req)
        assert s.needs_image is True
        assert s.image_request.prompt == "tech bg"

    def test_page_number_zero(self):
        with pytest.raises(ValidationError):
            _make_slide_spec(page_number=0)

    def test_json_roundtrip(self):
        s = _make_slide_spec(page_number=5)
        restored = SlideSpec.model_validate_json(s.model_dump_json())
        assert restored.page_number == 5
        assert restored.content.title == "Page 5"


# =========================================================================
# PPTOutline 测试
# =========================================================================


class TestPPTOutline:

    def test_basic(self):
        slides = [_make_slide_spec(i) for i in range(1, 11)]
        outline = PPTOutline(
            total_pages=10,
            estimated_duration="5-8分钟",
            slides=slides,
        )
        assert outline.total_pages == 10
        assert len(outline.slides) == 10

    def test_total_pages_min(self):
        slides = [_make_slide_spec(i) for i in range(1, 6)]
        outline = PPTOutline(total_pages=5, estimated_duration="3分钟", slides=slides)
        assert outline.total_pages == 5

    def test_total_pages_too_low(self):
        with pytest.raises(ValidationError):
            PPTOutline(total_pages=4, estimated_duration="x", slides=[])

    def test_total_pages_too_high(self):
        with pytest.raises(ValidationError):
            PPTOutline(total_pages=51, estimated_duration="x", slides=[])

    def test_json_roundtrip(self):
        slides = [_make_slide_spec(i) for i in range(1, 8)]
        outline = PPTOutline(total_pages=7, estimated_duration="5分钟", slides=slides)
        json_str = outline.model_dump_json()
        restored = PPTOutline.model_validate_json(json_str)
        assert restored.total_pages == 7
        assert len(restored.slides) == 7


# =========================================================================
# PPTProject 测试
# =========================================================================


class TestPPTProject:

    def test_minimal(self):
        p = PPTProject(project_id="ppt_abc123", input_text="Hello world")
        assert p.project_id == "ppt_abc123"
        assert p.theme == "modern"
        assert p.max_pages == 20
        assert p.status == "analyzing"
        assert p.current_stage == "文档分析"
        assert p.progress == 0.0
        assert p.analysis is None
        assert p.outline is None
        assert p.output_path is None
        assert p.quality_report is None
        assert p.errors == []

    def test_status_values(self):
        for status in [
            "analyzing", "outlining", "writing", "designing",
            "imaging", "rendering", "completed", "failed",
        ]:
            p = PPTProject(
                project_id="test", input_text="x", status=status
            )
            assert p.status == status

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            PPTProject(project_id="test", input_text="x", status="invalid")

    def test_max_pages_bounds(self):
        PPTProject(project_id="t", input_text="x", max_pages=5)
        PPTProject(project_id="t", input_text="x", max_pages=50)
        with pytest.raises(ValidationError):
            PPTProject(project_id="t", input_text="x", max_pages=4)
        with pytest.raises(ValidationError):
            PPTProject(project_id="t", input_text="x", max_pages=51)

    def test_progress_bounds(self):
        PPTProject(project_id="t", input_text="x", progress=0.0)
        PPTProject(project_id="t", input_text="x", progress=1.0)
        with pytest.raises(ValidationError):
            PPTProject(project_id="t", input_text="x", progress=-0.1)
        with pytest.raises(ValidationError):
            PPTProject(project_id="t", input_text="x", progress=1.1)

    def test_with_errors(self):
        p = PPTProject(
            project_id="t",
            input_text="x",
            status="failed",
            errors=["图片生成失败", "渲染超时"],
        )
        assert len(p.errors) == 2

    def test_json_roundtrip(self):
        p = PPTProject(project_id="ppt_round", input_text="test doc content")
        restored = PPTProject.model_validate_json(p.model_dump_json())
        assert restored.project_id == "ppt_round"
        assert restored.input_text == "test doc content"

    def test_json_roundtrip_exclude_none(self):
        p = PPTProject(project_id="t", input_text="x")
        json_str = p.model_dump_json(exclude_none=True)
        data = json.loads(json_str)
        assert "analysis" not in data
        assert "outline" not in data


# =========================================================================
# ThemeConfig 测试
# =========================================================================


class TestThemeConfig:

    def _make(self, **overrides):
        defaults = {
            "name": "modern",
            "colors": _make_colors(),
            "title_font": _make_font(size=36),
            "body_font": _make_font(size=16),
            "note_font": _make_font(size=14),
        }
        defaults.update(overrides)
        return ThemeConfig(**defaults)

    def test_basic(self):
        tc = self._make()
        assert tc.name == "modern"
        assert tc.display_name == ""
        assert tc.description == ""
        assert tc.brand_logo is None
        assert tc.footer_text is None
        assert tc.layout_preferences["max_bullet_points"] == 5

    def test_custom_layout_prefs(self):
        tc = self._make(layout_preferences={"max_bullet_points": 3, "prefer_images": False})
        assert tc.layout_preferences["max_bullet_points"] == 3

    def test_decoration_defaults(self):
        tc = self._make()
        assert tc.decoration_defaults.has_divider is False

    def test_json_roundtrip(self):
        tc = self._make(display_name="简约现代", description="test")
        restored = ThemeConfig.model_validate_json(tc.model_dump_json())
        assert restored.display_name == "简约现代"


# =========================================================================
# QualityIssue / QualityReport 测试
# =========================================================================


class TestQualityModels:

    def test_quality_issue_basic(self):
        qi = QualityIssue(
            page_number=3,
            issue_type="text_overflow",
            description="标题超出文本框范围",
        )
        assert qi.severity == "medium"
        assert qi.auto_fixable is False

    def test_quality_issue_custom_severity(self):
        qi = QualityIssue(
            page_number=1,
            issue_type="missing_image",
            severity="high",
            description="封面缺少配图",
            auto_fixable=True,
        )
        assert qi.severity == "high"
        assert qi.auto_fixable is True

    def test_quality_issue_invalid_severity(self):
        with pytest.raises(ValidationError):
            QualityIssue(
                page_number=1,
                issue_type="x",
                severity="critical",
                description="x",
            )

    def test_quality_report_basic(self):
        qr = QualityReport(total_pages=10, score=8.5, summary="整体良好")
        assert qr.total_pages == 10
        assert qr.issues == []
        assert qr.score == 8.5

    def test_quality_report_with_issues(self):
        issues = [
            QualityIssue(
                page_number=i,
                issue_type="text_overflow",
                description=f"第{i}页文本溢出",
            )
            for i in range(1, 4)
        ]
        qr = QualityReport(
            total_pages=15,
            issues=issues,
            score=6.0,
            summary="存在3处文本溢出",
        )
        assert len(qr.issues) == 3

    def test_quality_report_score_bounds(self):
        QualityReport(total_pages=1, score=0.0)
        QualityReport(total_pages=1, score=10.0)
        with pytest.raises(ValidationError):
            QualityReport(total_pages=1, score=-0.1)
        with pytest.raises(ValidationError):
            QualityReport(total_pages=1, score=10.1)

    def test_quality_report_json_roundtrip(self):
        qr = QualityReport(total_pages=10, score=9.0, summary="优秀")
        restored = QualityReport.model_validate_json(qr.model_dump_json())
        assert restored.score == 9.0


# =========================================================================
# DeckType 枚举测试
# =========================================================================


class TestDeckType:

    def test_values(self):
        assert DeckType.BUSINESS_REPORT == "business_report"
        assert DeckType.COURSE_LECTURE == "course_lecture"
        assert DeckType.PRODUCT_INTRO == "product_intro"
        assert len(DeckType) == 3

    def test_from_string(self):
        assert DeckType("business_report") == DeckType.BUSINESS_REPORT
        assert DeckType("course_lecture") == DeckType.COURSE_LECTURE
        assert DeckType("product_intro") == DeckType.PRODUCT_INTRO

    def test_invalid_value(self):
        with pytest.raises(ValueError):
            DeckType("nonexistent")


# =========================================================================
# PageRole 枚举测试
# =========================================================================


class TestPageRole:

    def test_cover_value(self):
        assert PageRole.COVER == "cover"

    def test_closing_value(self):
        assert PageRole.CLOSING == "closing"

    def test_total_count(self):
        assert len(PageRole) == 27

    def test_all_values_are_lowercase(self):
        for role in PageRole:
            assert role.value == role.value.lower()

    def test_invalid_value(self):
        with pytest.raises(ValueError):
            PageRole("nonexistent")


# =========================================================================
# ImageStrategy 枚举测试
# =========================================================================


class TestImageStrategy:

    def test_values(self):
        assert ImageStrategy.CHART == "chart"
        assert ImageStrategy.DIAGRAM == "diagram"
        assert ImageStrategy.UI_MOCK == "ui_mock"
        assert ImageStrategy.ILLUSTRATION == "illustration"
        assert ImageStrategy.NONE == "none"
        assert len(ImageStrategy) == 5

    def test_from_string(self):
        assert ImageStrategy("chart") == ImageStrategy.CHART
        assert ImageStrategy("none") == ImageStrategy.NONE

    def test_invalid_value(self):
        with pytest.raises(ValueError):
            ImageStrategy("photo")


# =========================================================================
# SlideTask 测试
# =========================================================================


class TestSlideTask:

    def test_minimal(self):
        task = SlideTask(page_role=PageRole.COVER, page_goal="建立主题")
        assert task.page_role == PageRole.COVER
        assert task.page_goal == "建立主题"
        assert task.must_include == []
        assert task.forbidden_content == []
        assert task.image_strategy == ImageStrategy.NONE
        assert task.layout_preference is None

    def test_full(self):
        task = SlideTask(
            page_role=PageRole.EXECUTIVE_SUMMARY,
            page_goal="30秒内讲清结论",
            must_include=["进展结论", "关键风险"],
            forbidden_content=["背景复述"],
            image_strategy=ImageStrategy.CHART,
            layout_preference="bullet_with_icons",
        )
        assert task.page_role == PageRole.EXECUTIVE_SUMMARY
        assert len(task.must_include) == 2
        assert len(task.forbidden_content) == 1
        assert task.image_strategy == ImageStrategy.CHART
        assert task.layout_preference == "bullet_with_icons"

    def test_json_roundtrip(self):
        task = SlideTask(
            page_role=PageRole.DATA_EVIDENCE,
            page_goal="用数据说话",
            must_include=["核心指标"],
            image_strategy=ImageStrategy.CHART,
        )
        restored = SlideTask.model_validate_json(task.model_dump_json())
        assert restored.page_role == PageRole.DATA_EVIDENCE
        assert restored.must_include == ["核心指标"]

    def test_page_role_from_string(self):
        task = SlideTask(page_role="cover", page_goal="test")
        assert task.page_role == PageRole.COVER

    def test_image_strategy_from_string(self):
        task = SlideTask(
            page_role=PageRole.COVER,
            page_goal="test",
            image_strategy="diagram",
        )
        assert task.image_strategy == ImageStrategy.DIAGRAM


# =========================================================================
# PresentationPlan 测试
# =========================================================================


class TestPresentationPlan:

    def _make_slides(self, count=3):
        roles = [PageRole.COVER, PageRole.KNOWLEDGE_POINT, PageRole.CLOSING]
        return [
            SlideTask(page_role=roles[i % len(roles)], page_goal=f"Goal {i}")
            for i in range(count)
        ]

    def test_basic(self):
        plan = PresentationPlan(
            deck_type=DeckType.COURSE_LECTURE,
            audience="学员",
            core_message="掌握缓存技术",
            presentation_goal="让学员能独立实现缓存方案",
            narrative_arc=["引入", "讲解", "总结"],
            slides=self._make_slides(),
        )
        assert plan.deck_type == DeckType.COURSE_LECTURE
        assert plan.audience == "学员"
        assert len(plan.slides) == 3
        assert len(plan.narrative_arc) == 3

    def test_json_roundtrip(self):
        plan = PresentationPlan(
            deck_type=DeckType.BUSINESS_REPORT,
            audience="管理层",
            core_message="项目进展良好",
            presentation_goal="获得资源支持",
            narrative_arc=["结论", "背景", "下一步"],
            slides=self._make_slides(2),
        )
        restored = PresentationPlan.model_validate_json(plan.model_dump_json())
        assert restored.deck_type == DeckType.BUSINESS_REPORT
        assert restored.core_message == "项目进展良好"
        assert len(restored.slides) == 2

    def test_deck_type_from_string(self):
        plan = PresentationPlan(
            deck_type="product_intro",
            audience="客户",
            core_message="产品很棒",
            presentation_goal="促成合作",
            narrative_arc=["痛点", "产品"],
            slides=self._make_slides(1),
        )
        assert plan.deck_type == DeckType.PRODUCT_INTRO

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            PresentationPlan(
                deck_type=DeckType.COURSE_LECTURE,
                audience="学员",
                # missing core_message
                presentation_goal="目标",
                narrative_arc=["a"],
                slides=[],
            )

    def test_empty_slides_allowed(self):
        plan = PresentationPlan(
            deck_type=DeckType.BUSINESS_REPORT,
            audience="领导",
            core_message="总结",
            presentation_goal="汇报",
            narrative_arc=["结论"],
            slides=[],
        )
        assert len(plan.slides) == 0


# =========================================================================
# SlideOutline 新字段测试
# =========================================================================


class TestSlideOutlineNewFields:
    """Test the newly added fields on SlideOutline."""

    def test_new_fields_have_defaults(self):
        outline = SlideOutline(
            page_number=1,
            slide_type="title_hero",
            layout=LayoutType.TITLE_HERO,
            title="封面",
        )
        assert outline.page_role is None
        assert outline.page_goal == ""
        assert outline.must_include == []
        assert outline.forbidden_content == []
        assert outline.image_strategy == ImageStrategy.NONE

    def test_new_fields_set(self):
        outline = SlideOutline(
            page_number=2,
            slide_type="content",
            layout=LayoutType.BULLET_WITH_ICONS,
            title="核心数据",
            page_role=PageRole.DATA_EVIDENCE,
            page_goal="用数据说话",
            must_include=["核心指标", "趋势"],
            forbidden_content=["空话"],
            image_strategy=ImageStrategy.CHART,
        )
        assert outline.page_role == PageRole.DATA_EVIDENCE
        assert outline.page_goal == "用数据说话"
        assert len(outline.must_include) == 2
        assert outline.forbidden_content == ["空话"]
        assert outline.image_strategy == ImageStrategy.CHART

    def test_backward_compatible_json_roundtrip(self):
        """Old-style SlideOutline (without new fields) still works."""
        outline = SlideOutline(
            page_number=1,
            slide_type="title_hero",
            layout=LayoutType.TITLE_HERO,
            title="旧格式封面",
            needs_image=True,
            image_prompt="abstract background",
        )
        restored = SlideOutline.model_validate_json(outline.model_dump_json())
        assert restored.page_number == 1
        assert restored.needs_image is True
        assert restored.page_role is None
        assert restored.image_strategy == ImageStrategy.NONE

    def test_full_json_roundtrip_with_new_fields(self):
        outline = SlideOutline(
            page_number=3,
            slide_type="content",
            layout=LayoutType.DATA_HIGHLIGHT,
            title="进展",
            page_role=PageRole.PROGRESS,
            page_goal="展示进展",
            must_include=["完成率"],
            forbidden_content=["空泛套话"],
            image_strategy=ImageStrategy.CHART,
        )
        restored = SlideOutline.model_validate_json(outline.model_dump_json())
        assert restored.page_role == PageRole.PROGRESS
        assert restored.must_include == ["完成率"]
        assert restored.image_strategy == ImageStrategy.CHART
