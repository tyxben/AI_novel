"""PPT Pipeline V2 集成测试 -- 从主题生成模式"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.ppt.models import (
    ColorScheme,
    EditableOutline,
    EditableSlide,
    FontSpec,
    PageRole,
    QualityReport,
    SlideContent,
    SlideDesign,
    LayoutType,
)
from src.ppt.pipeline import PPTPipeline


# ---------------------------------------------------------------------------
# Mock LLM responses
# ---------------------------------------------------------------------------


def _mock_llm_narrative_response():
    """Mock NarrativeDesigner 的 LLM 返回"""
    return LLMResponse(
        content=json.dumps(
            {
                "sections": [
                    {"role": "cover", "title_hint": "Q1 汇报"},
                    {
                        "role": "executive_summary",
                        "title_hint": "核心亮点",
                        "key_points_hint": ["GMV +30%"],
                    },
                    {"role": "progress", "title_hint": "进展"},
                    {"role": "data_evidence", "title_hint": "数据"},
                    {"role": "closing", "title_hint": "谢谢"},
                ]
            }
        ),
        model="test",
    )


def _mock_llm_outline_response():
    """Mock OutlineGenerator 的 LLM 返回"""
    return LLMResponse(
        content=json.dumps(
            [
                {"title": "Q1 产品进展", "key_points": [], "image_prompt": "bg"},
                {
                    "title": "核心亮点",
                    "key_points": ["GMV增长30%"],
                    "image_prompt": None,
                },
                {"title": "关键进展", "key_points": ["项目完成"], "image_prompt": None},
                {
                    "title": "数据表现",
                    "key_points": ["DAU 10万"],
                    "image_prompt": "chart",
                },
                {"title": "感谢", "key_points": [], "image_prompt": None},
            ]
        ),
        model="test",
    )


# ===========================================================================
# TestRouteMode
# ===========================================================================


class TestRouteMode:
    def test_topic_mode(self):
        assert PPTPipeline._route_mode("测试主题", None) == "topic"

    def test_document_mode(self):
        assert PPTPipeline._route_mode(None, "文档内容") == "document"

    def test_document_mode_when_both(self):
        """两者都有时优先 document"""
        assert PPTPipeline._route_mode("主题", "文档") == "document"

    def test_neither_raises(self):
        with pytest.raises(ValueError):
            PPTPipeline._route_mode(None, None)

    def test_empty_topic_with_document(self):
        """空字符串 topic + 有效 document -> document 模式"""
        assert PPTPipeline._route_mode("", "文档内容") == "document"

    def test_empty_both_raises(self):
        """空字符串 topic + None document -> ValueError"""
        with pytest.raises(ValueError):
            PPTPipeline._route_mode("", None)


# ===========================================================================
# TestGenerateOutlineOnly
# ===========================================================================


class TestGenerateOutlineOnly:
    @patch("src.ppt.outline_generator.create_llm_client")
    @patch("src.ppt.narrative_designer.create_llm_client")
    def test_topic_mode_returns_editable_outline(
        self, mock_narr_llm, mock_outline_llm, tmp_path
    ):
        """topic 模式返回 EditableOutline"""
        mock_llm_narr = MagicMock()
        mock_llm_narr.chat.return_value = _mock_llm_narrative_response()
        mock_narr_llm.return_value = mock_llm_narr

        mock_llm_out = MagicMock()
        mock_llm_out.chat.return_value = _mock_llm_outline_response()
        mock_outline_llm.return_value = mock_llm_out

        pipe = PPTPipeline(workspace=str(tmp_path), config={"llm": {}})

        project_id, outline = pipe.generate_outline_only(
            topic="Q1 产品进展",
            audience="business",
            scenario="quarterly_review",
            theme="modern",
        )

        assert isinstance(project_id, str)
        assert project_id.startswith("ppt_")
        assert isinstance(outline, EditableOutline)
        assert outline.total_pages >= 3
        assert len(outline.slides) >= 3

    @patch("src.ppt.outline_generator.create_llm_client")
    @patch("src.ppt.pipeline.DocumentAnalyzer")
    def test_document_mode_returns_editable_outline(
        self, mock_analyzer_cls, mock_outline_llm, tmp_path
    ):
        """document 模式返回 EditableOutline"""
        from src.ppt.models import Audience, DocumentAnalysis, DocumentType, Tone

        mock_llm = MagicMock()
        mock_llm.chat.return_value = _mock_llm_outline_response()
        mock_outline_llm.return_value = mock_llm

        # Mock DocumentAnalyzer
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = DocumentAnalysis(
            theme="测试主题",
            doc_type=DocumentType.BUSINESS_REPORT,
            audience=Audience.BUSINESS,
            tone=Tone.PROFESSIONAL,
            key_points=["要点1"],
            estimated_pages=10,
        )
        mock_analyzer_cls.return_value = mock_analyzer

        pipe = PPTPipeline(workspace=str(tmp_path), config={"llm": {}})

        project_id, outline = pipe.generate_outline_only(
            document_text="这是一份测试文档，包含各种数据和分析...",
            theme="modern",
        )

        assert isinstance(outline, EditableOutline)
        assert outline.total_pages >= 3

    @patch("src.ppt.outline_generator.create_llm_client")
    @patch("src.ppt.narrative_designer.create_llm_client")
    def test_topic_mode_creates_project_dir(
        self, mock_narr_llm, mock_outline_llm, tmp_path
    ):
        """topic 模式会创建项目目录"""
        mock_llm_narr = MagicMock()
        mock_llm_narr.chat.return_value = _mock_llm_narrative_response()
        mock_narr_llm.return_value = mock_llm_narr

        mock_llm_out = MagicMock()
        mock_llm_out.chat.return_value = _mock_llm_outline_response()
        mock_outline_llm.return_value = mock_llm_out

        pipe = PPTPipeline(workspace=str(tmp_path), config={"llm": {}})
        project_id, _ = pipe.generate_outline_only(
            topic="测试", theme="modern"
        )

        project_dir = tmp_path / "ppt" / project_id
        assert project_dir.exists()

    @patch("src.ppt.outline_generator.create_llm_client")
    @patch("src.ppt.narrative_designer.create_llm_client")
    def test_progress_callback_called(
        self, mock_narr_llm, mock_outline_llm, tmp_path
    ):
        """进度回调被调用"""
        mock_llm_narr = MagicMock()
        mock_llm_narr.chat.return_value = _mock_llm_narrative_response()
        mock_narr_llm.return_value = mock_llm_narr

        mock_llm_out = MagicMock()
        mock_llm_out.chat.return_value = _mock_llm_outline_response()
        mock_outline_llm.return_value = mock_llm_out

        callback = MagicMock()
        pipe = PPTPipeline(workspace=str(tmp_path), config={"llm": {}})
        pipe.generate_outline_only(
            topic="测试",
            progress_callback=callback,
        )

        assert callback.call_count >= 1

    def test_neither_topic_nor_document_raises(self, tmp_path):
        """不提供 topic 和 document_text 会抛出 ValueError"""
        pipe = PPTPipeline(workspace=str(tmp_path), config={"llm": {}})

        with pytest.raises(ValueError, match="必须提供"):
            pipe.generate_outline_only(theme="modern")


# ===========================================================================
# TestContinueFromOutline
# ===========================================================================


class TestContinueFromOutline:
    @patch("src.ppt.pipeline.PPTRenderer")
    @patch("src.ppt.pipeline.QualityChecker")
    @patch("src.ppt.pipeline.DesignOrchestrator")
    @patch("src.ppt.pipeline.ContentCreator")
    def test_continue_generates_pptx(
        self,
        mock_creator_cls,
        mock_orchestrator_cls,
        mock_checker_cls,
        mock_renderer_cls,
        tmp_path,
    ):
        """continue_from_outline 生成 pptx"""
        # Mock ContentCreator
        mock_creator = MagicMock()
        mock_creator.create.return_value = [
            SlideContent(title="封面"),
            SlideContent(title="内容", bullet_points=["要点"]),
            SlideContent(title="结束"),
        ]
        mock_creator_cls.return_value = mock_creator

        # Mock DesignOrchestrator
        colors = ColorScheme(
            primary="#333333",
            secondary="#666666",
            accent="#0066CC",
            text="#333333",
        )
        font = FontSpec(size=24, color="#333333")
        mock_design = SlideDesign(
            layout=LayoutType.BULLET_WITH_ICONS,
            colors=colors,
            title_font=font,
            body_font=font,
            note_font=font,
        )
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = [mock_design] * 3
        mock_orchestrator.get_image_requests.return_value = []
        mock_orchestrator_cls.return_value = mock_orchestrator

        # Mock QualityChecker
        mock_checker = MagicMock()
        mock_checker.check.return_value = QualityReport(
            total_pages=3, score=8.0
        )
        mock_checker_cls.return_value = mock_checker

        # Mock PPTRenderer
        mock_renderer = MagicMock()
        mock_renderer_cls.return_value = mock_renderer

        # 创建 pipeline 并创建项目目录
        pipe = PPTPipeline(workspace=str(tmp_path), config={"llm": {}})
        pipe.file_manager.create_project("test_proj")

        outline = EditableOutline(
            project_id="test_proj",
            total_pages=3,
            slides=[
                EditableSlide(
                    page_number=1,
                    role="cover",
                    title="封面",
                    layout="title_hero",
                    image_strategy="none",
                ),
                EditableSlide(
                    page_number=2,
                    role="progress",
                    title="内容",
                    key_points=["要点"],
                    layout="bullet_with_icons",
                    image_strategy="none",
                ),
                EditableSlide(
                    page_number=3,
                    role="closing",
                    title="结束",
                    layout="closing",
                    image_strategy="none",
                ),
            ],
        )

        result = pipe.continue_from_outline(
            project_id="test_proj",
            edited_outline=outline,
            generate_images=False,
        )

        assert isinstance(result, str)
        mock_renderer.render.assert_called_once()
        mock_renderer.save.assert_called_once()

    @patch("src.ppt.pipeline.PPTRenderer")
    @patch("src.ppt.pipeline.QualityChecker")
    @patch("src.ppt.pipeline.DesignOrchestrator")
    @patch("src.ppt.pipeline.ContentCreator")
    def test_continue_with_progress_callback(
        self,
        mock_creator_cls,
        mock_orchestrator_cls,
        mock_checker_cls,
        mock_renderer_cls,
        tmp_path,
    ):
        """continue_from_outline 调用进度回调"""
        mock_creator = MagicMock()
        mock_creator.create.return_value = [SlideContent(title="封面")]
        mock_creator_cls.return_value = mock_creator

        colors = ColorScheme(
            primary="#333333",
            secondary="#666666",
            accent="#0066CC",
            text="#333333",
        )
        font = FontSpec(size=24, color="#333333")
        mock_design = SlideDesign(
            layout=LayoutType.BULLET_WITH_ICONS,
            colors=colors,
            title_font=font,
            body_font=font,
            note_font=font,
        )
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = [mock_design]
        mock_orchestrator.get_image_requests.return_value = []
        mock_orchestrator_cls.return_value = mock_orchestrator

        mock_checker = MagicMock()
        mock_checker.check.return_value = QualityReport(
            total_pages=1, score=9.0
        )
        mock_checker_cls.return_value = mock_checker

        mock_renderer = MagicMock()
        mock_renderer_cls.return_value = mock_renderer

        pipe = PPTPipeline(workspace=str(tmp_path), config={"llm": {}})
        pipe.file_manager.create_project("test_proj2")

        outline = EditableOutline(
            project_id="test_proj2",
            total_pages=1,
            slides=[
                EditableSlide(
                    page_number=1,
                    role="cover",
                    title="封面",
                    layout="title_hero",
                    image_strategy="none",
                ),
            ],
        )

        callback = MagicMock()
        pipe.continue_from_outline(
            project_id="test_proj2",
            edited_outline=outline,
            generate_images=False,
            progress_callback=callback,
        )

        assert callback.call_count >= 1
        # 检查最后一次回调包含 "completed"
        stages_called = [call[0][0] for call in callback.call_args_list]
        assert "completed" in stages_called

    @patch("src.ppt.pipeline.PPTRenderer")
    @patch("src.ppt.pipeline.QualityChecker")
    @patch("src.ppt.pipeline.DesignOrchestrator")
    @patch("src.ppt.pipeline.ContentCreator")
    def test_continue_quality_check_fix(
        self,
        mock_creator_cls,
        mock_orchestrator_cls,
        mock_checker_cls,
        mock_renderer_cls,
        tmp_path,
    ):
        """质量检查有问题时触发自动修复"""
        from src.ppt.models import QualityIssue

        mock_creator = MagicMock()
        mock_creator.create.return_value = [SlideContent(title="封面")]
        mock_creator_cls.return_value = mock_creator

        colors = ColorScheme(
            primary="#333333",
            secondary="#666666",
            accent="#0066CC",
            text="#333333",
        )
        font = FontSpec(size=24, color="#333333")
        mock_design = SlideDesign(
            layout=LayoutType.BULLET_WITH_ICONS,
            colors=colors,
            title_font=font,
            body_font=font,
            note_font=font,
        )
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = [mock_design]
        mock_orchestrator.get_image_requests.return_value = []
        mock_orchestrator_cls.return_value = mock_orchestrator

        # 质量检查发现问题
        mock_checker = MagicMock()
        mock_checker.check.return_value = QualityReport(
            total_pages=1,
            score=6.0,
            issues=[
                QualityIssue(
                    page_number=1,
                    issue_type="text_overflow",
                    severity="medium",
                    description="标题过长",
                    auto_fixable=True,
                )
            ],
        )
        mock_checker_cls.return_value = mock_checker

        mock_renderer = MagicMock()
        mock_renderer_cls.return_value = mock_renderer

        pipe = PPTPipeline(workspace=str(tmp_path), config={"llm": {}})
        pipe.file_manager.create_project("test_proj_fix")

        outline = EditableOutline(
            project_id="test_proj_fix",
            total_pages=1,
            slides=[
                EditableSlide(
                    page_number=1,
                    role="cover",
                    title="封面",
                    layout="title_hero",
                    image_strategy="none",
                ),
            ],
        )

        pipe.continue_from_outline(
            project_id="test_proj_fix",
            edited_outline=outline,
            generate_images=False,
        )

        # 质量检查有 issues 时调用 fix
        mock_checker.fix.assert_called_once()
