"""Tests for src/ppt/pipeline.py"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ppt.models import (
    Audience,
    ColorScheme,
    ContentBlock,
    ContentMap,
    DeckType,
    DocumentAnalysis,
    DocumentType,
    FontSpec,
    ImageOrientation,
    ImageRequest,
    LayoutType,
    PresentationPlan,
    QualityIssue,
    QualityReport,
    SlideContent,
    SlideDesign,
    SlideOutline,
    SlideSpec,
    Tone,
)
from src.ppt.pipeline import PPTPipeline, _STAGE_ORDER


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_ANALYSIS = DocumentAnalysis(
    theme="AI technology overview",
    doc_type=DocumentType.TECH_SHARE,
    audience=Audience.TECHNICAL,
    tone=Tone.PROFESSIONAL,
    key_points=["point1", "point2", "point3"],
    estimated_pages=5,
)

_FAKE_CONTENT_MAP = ContentMap(
    document_thesis="AI is transforming industries",
    content_blocks=[
        ContentBlock(
            block_id="b1",
            block_type="thesis",
            title="AI transformation",
            summary="AI is transforming multiple industries with rapid adoption.",
            source_text="AI is transforming multiple industries.",
            importance=5,
        ),
        ContentBlock(
            block_id="b2",
            block_type="data",
            title="Market size",
            summary="The AI market is projected to reach $500 billion by 2025.",
            source_text="The AI market is projected to reach $500 billion.",
            importance=4,
        ),
        ContentBlock(
            block_id="b3",
            block_type="argument",
            title="Key applications",
            summary="NLP, computer vision, and robotics lead adoption.",
            source_text="NLP, computer vision, and robotics lead adoption.",
            importance=3,
        ),
        ContentBlock(
            block_id="b4",
            block_type="conclusion",
            title="Future outlook",
            summary="Continued growth expected across all sectors.",
            source_text="Continued growth expected across all sectors.",
            importance=4,
        ),
    ],
    logical_flow=["b1", "b2", "b3", "b4"],
    key_data_points=["$500 billion by 2025"],
    key_quotes=["AI is the new electricity"],
)

_FAKE_OUTLINES = [
    SlideOutline(
        page_number=i + 1,
        slide_type="bullet_with_icons",
        layout=LayoutType.BULLET_WITH_ICONS,
        title=f"Page {i + 1}",
        key_points=["kp1", "kp2"],
        needs_image=(i == 0),
        image_prompt="test prompt" if i == 0 else None,
    )
    for i in range(5)
]

_FAKE_CONTENTS = [
    SlideContent(
        title=f"Page {i + 1}",
        subtitle="subtitle",
        bullet_points=["bp1", "bp2"],
    )
    for i in range(5)
]

_FAKE_DESIGN = SlideDesign(
    layout=LayoutType.BULLET_WITH_ICONS,
    colors=ColorScheme(
        primary="#2D3436",
        secondary="#636E72",
        accent="#0984E3",
        text="#2D3436",
    ),
    title_font=FontSpec(size=28, bold=True, color="#2D3436"),
    body_font=FontSpec(size=18, color="#2D3436"),
    note_font=FontSpec(size=14, color="#757575"),
)

_FAKE_DESIGNS = [_FAKE_DESIGN] * 5

_FAKE_IMAGE_REQUESTS = [
    ImageRequest(
        page_number=1,
        prompt="test prompt",
        size=ImageOrientation.LANDSCAPE,
        style="modern",
    )
]

_FAKE_REPORT = QualityReport(
    total_pages=5,
    issues=[],
    score=10.0,
    summary="OK",
)


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return str(ws)


# ---------------------------------------------------------------------------
# Module patches
# ---------------------------------------------------------------------------


def _patch_all():
    """Return a dict of all patches needed for a full pipeline run."""
    return {
        "analyzer": patch(
            "src.ppt.pipeline.DocumentAnalyzer",
        ),
        "extractor": patch(
            "src.ppt.pipeline.ContentExtractor",
        ),
        "outline_gen": patch(
            "src.ppt.pipeline.OutlineGenerator",
        ),
        "content_creator": patch(
            "src.ppt.pipeline.ContentCreator",
        ),
        "design_orch": patch(
            "src.ppt.pipeline.DesignOrchestrator",
        ),
        "renderer": patch(
            "src.ppt.pipeline.PPTRenderer",
        ),
        "quality_checker": patch(
            "src.ppt.pipeline.QualityChecker",
        ),
        "theme_manager": patch(
            "src.ppt.pipeline.ThemeManager",
        ),
        "has_extractor": patch(
            "src.ppt.pipeline._HAS_CONTENT_EXTRACTOR", True,
        ),
        "has_planner": patch(
            "src.ppt.pipeline._HAS_PLANNER", False,
        ),
    }


def _enter_patches(patches: dict) -> dict:
    """Enter all context managers in _patch_all() dict, return mocks."""
    mocks = {}
    for key, p in patches.items():
        mocks[key] = p.__enter__()
    return mocks


def _exit_patches(patches: dict) -> None:
    """Exit all context managers."""
    for p in patches.values():
        p.__exit__(None, None, None)


def _setup_standard_mocks(mocks: dict) -> None:
    """Configure standard mock return values for a full pipeline run."""
    mocks["analyzer"].return_value.analyze.return_value = _FAKE_ANALYSIS
    mocks["extractor"].return_value.extract.return_value = _FAKE_CONTENT_MAP
    mocks["outline_gen"].return_value.generate.return_value = _FAKE_OUTLINES
    mocks["content_creator"].return_value.create.return_value = _FAKE_CONTENTS
    mocks["design_orch"].return_value.orchestrate.return_value = _FAKE_DESIGNS
    mocks["design_orch"].return_value.get_image_requests.return_value = []
    mocks["quality_checker"].return_value.check.return_value = _FAKE_REPORT
    mocks["quality_checker"].return_value.fix.return_value = []
    mocks["theme_manager"].return_value.get_theme.return_value = MagicMock()

    def fake_save(path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("fake pptx")
        return path

    mocks["renderer"].return_value.save.side_effect = fake_save


class TestStageOrder:
    """Test _STAGE_ORDER includes all 10 stages."""

    def test_stage_order_has_ten_stages(self):
        assert len(_STAGE_ORDER) == 10

    def test_rewrite_before_analysis(self):
        assert _STAGE_ORDER.index("rewrite") < _STAGE_ORDER.index("analysis")

    def test_extraction_between_analysis_and_outline(self):
        assert _STAGE_ORDER.index("analysis") < _STAGE_ORDER.index("extraction")
        assert _STAGE_ORDER.index("extraction") < _STAGE_ORDER.index("outline")

    def test_planning_between_enrichment_and_outline(self):
        assert _STAGE_ORDER.index("enrichment") < _STAGE_ORDER.index("planning")
        assert _STAGE_ORDER.index("planning") < _STAGE_ORDER.index("outline")

    def test_all_stages_present(self):
        expected = {
            "rewrite", "analysis", "extraction", "enrichment", "planning",
            "outline", "content", "design", "images", "render",
        }
        assert set(_STAGE_ORDER) == expected


class TestGenerate:
    """Test PPTPipeline.generate()."""

    def test_full_pipeline_no_images(self, tmp_workspace):
        """Full pipeline with generate_images=False runs all 7 stages."""
        patches = _patch_all()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            result = pipe.generate(
                text="This is a test document with enough content for analysis.",
                theme="modern",
                generate_images=False,
            )

            assert result.endswith(".pptx")
            assert os.path.exists(result)

            # Verify all stages were called
            mocks["analyzer"].return_value.analyze.assert_called_once()
            mocks["extractor"].return_value.extract.assert_called_once()
            mocks["outline_gen"].return_value.generate.assert_called_once()
            mocks["content_creator"].return_value.create.assert_called_once()
            mocks["design_orch"].return_value.orchestrate.assert_called_once()
            mocks["renderer"].return_value.render.assert_called_once()
            mocks["quality_checker"].return_value.check.assert_called_once()
        finally:
            _exit_patches(patches)

    def test_content_map_passed_to_outline_and_content(self, tmp_workspace):
        """content_map from extraction is passed to outline and content stages."""
        patches = _patch_all()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            pipe.generate(
                text="Test document for content map passing.",
                generate_images=False,
            )

            # Verify content_map was passed to outline generator
            outline_call_kwargs = mocks["outline_gen"].return_value.generate.call_args
            assert outline_call_kwargs.kwargs.get("content_map") == _FAKE_CONTENT_MAP

            # Verify content_map was passed to content creator
            content_call_kwargs = mocks["content_creator"].return_value.create.call_args
            assert content_call_kwargs.kwargs.get("content_map") == _FAKE_CONTENT_MAP
        finally:
            _exit_patches(patches)

    def test_extraction_failure_graceful(self, tmp_workspace):
        """When extraction fails, pipeline continues with content_map=None."""
        patches = _patch_all()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)
            # Make extraction fail
            mocks["extractor"].return_value.extract.side_effect = RuntimeError("LLM down")

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            result = pipe.generate(
                text="Test document with extraction failure.",
                generate_images=False,
            )

            assert result.endswith(".pptx")

            # Outline and content should get content_map=None
            outline_call_kwargs = mocks["outline_gen"].return_value.generate.call_args
            assert outline_call_kwargs.kwargs.get("content_map") is None

            content_call_kwargs = mocks["content_creator"].return_value.create.call_args
            assert content_call_kwargs.kwargs.get("content_map") is None
        finally:
            _exit_patches(patches)

    def test_no_extractor_available_skips_gracefully(self, tmp_workspace):
        """When _HAS_CONTENT_EXTRACTOR is False, extraction is skipped."""
        patches = _patch_all()
        # Override has_extractor to False
        patches["has_extractor"] = patch("src.ppt.pipeline._HAS_CONTENT_EXTRACTOR", False)
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            result = pipe.generate(
                text="Test without extractor available.",
                generate_images=False,
            )

            assert result.endswith(".pptx")

            # Extractor should not be called
            mocks["extractor"].return_value.extract.assert_not_called()

            # Outline and content get content_map=None
            outline_call_kwargs = mocks["outline_gen"].return_value.generate.call_args
            assert outline_call_kwargs.kwargs.get("content_map") is None
        finally:
            _exit_patches(patches)

    def test_progress_callback_called(self, tmp_workspace):
        """Verify progress callback is invoked at each stage including extraction."""
        patches = _patch_all()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)

            callback = MagicMock()
            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            pipe.generate(
                text="Test doc content sufficient for analysis purposes here.",
                generate_images=False,
                progress_callback=callback,
            )

            # Check callback was called multiple times with different stages
            assert callback.call_count >= 6  # at least 6 notifications for 9 stages
            stages_called = {call[0][0] for call in callback.call_args_list}
            assert "analyzing" in stages_called
            assert "extracting" in stages_called
            assert "completed" in stages_called
        finally:
            _exit_patches(patches)

    def test_checkpoint_saved_with_extraction(self, tmp_workspace):
        """Verify checkpoint includes extraction data after completion."""
        patches = _patch_all()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            pipe.generate(
                text="Enough text for testing purposes and analysis.",
                generate_images=False,
            )

            # Find the project dir
            ppt_dir = Path(tmp_workspace) / "ppt"
            project_dirs = list(ppt_dir.iterdir())
            assert len(project_dirs) == 1

            ckpt_path = project_dirs[0] / "checkpoints" / "latest.json"
            assert ckpt_path.exists()

            ckpt = json.loads(ckpt_path.read_text())
            data = ckpt.get("data", ckpt)
            assert data["status"] == "completed"

            # Check extraction stage is recorded
            stages = data["stages"]
            assert stages["extraction"]["completed"] is True
            assert stages["extraction"]["data"] is not None
            assert stages["extraction"]["data"]["document_thesis"] == "AI is transforming industries"
        finally:
            _exit_patches(patches)


class TestResume:
    """Test PPTPipeline.resume()."""

    def test_resume_from_outline_with_extraction(self, tmp_workspace):
        """Resume from a checkpoint where analysis, extraction, and outline are done."""
        patches = _patch_all()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)

            # Set up a project with completed analysis, extraction, and outline
            project_id = "ppt_20260316_test1234"
            project_dir = Path(tmp_workspace) / "ppt" / project_id
            for sub in ("images", "output", "checkpoints"):
                (project_dir / sub).mkdir(parents=True, exist_ok=True)

            # Save input text
            (project_dir / "input.txt").write_text("Test document content.", encoding="utf-8")

            # Save checkpoint with analysis, extraction, and outline complete
            analysis_data = _FAKE_ANALYSIS.model_dump()
            analysis_data["doc_type"] = _FAKE_ANALYSIS.doc_type.value
            analysis_data["audience"] = _FAKE_ANALYSIS.audience.value
            analysis_data["tone"] = _FAKE_ANALYSIS.tone.value
            outline_data = [o.model_dump() for o in _FAKE_OUTLINES]
            extraction_data = _FAKE_CONTENT_MAP.model_dump()

            checkpoint = {
                "stage": "outlined",
                "timestamp": "2026-03-16T00:00:00",
                "data": {
                    "project_id": project_id,
                    "status": "outlined",
                    "theme": "modern",
                    "max_pages": None,
                    "generate_images": False,
                    "stages": {
                        "analysis": {"completed": True, "data": analysis_data},
                        "extraction": {"completed": True, "data": extraction_data},
                        "planning": {"completed": True, "data": None},
                        "outline": {"completed": True, "data": outline_data},
                        "content": {"completed": False},
                        "design": {"completed": False},
                        "images": {"completed": False},
                        "render": {"completed": False},
                    },
                },
            }
            ckpt_path = project_dir / "checkpoints" / "latest.json"
            ckpt_path.write_text(
                json.dumps(checkpoint, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            result = pipe.resume(str(project_dir))

            assert result.endswith(".pptx")
            # Analysis, extraction, and outline should NOT be called again
            mocks["analyzer"].return_value.analyze.assert_not_called()
            mocks["extractor"].return_value.extract.assert_not_called()
            mocks["outline_gen"].return_value.generate.assert_not_called()
            # Content and design SHOULD be called
            mocks["content_creator"].return_value.create.assert_called_once()
            mocks["design_orch"].return_value.orchestrate.assert_called_once()

            # Verify content_map was loaded from checkpoint and passed
            content_call_kwargs = mocks["content_creator"].return_value.create.call_args
            passed_map = content_call_kwargs.kwargs.get("content_map")
            assert passed_map is not None
            assert passed_map.document_thesis == "AI is transforming industries"
            assert len(passed_map.content_blocks) == 4
        finally:
            _exit_patches(patches)

    def test_resume_old_checkpoint_without_extraction(self, tmp_workspace):
        """Resume from an old checkpoint that has no extraction stage."""
        patches = _patch_all()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)

            project_id = "ppt_20260316_old12345"
            project_dir = Path(tmp_workspace) / "ppt" / project_id
            for sub in ("images", "output", "checkpoints"):
                (project_dir / sub).mkdir(parents=True, exist_ok=True)

            (project_dir / "input.txt").write_text("Old format document.", encoding="utf-8")

            analysis_data = _FAKE_ANALYSIS.model_dump()
            analysis_data["doc_type"] = _FAKE_ANALYSIS.doc_type.value
            analysis_data["audience"] = _FAKE_ANALYSIS.audience.value
            analysis_data["tone"] = _FAKE_ANALYSIS.tone.value

            # Old checkpoint format: no extraction stage at all
            checkpoint = {
                "stage": "analyzed",
                "timestamp": "2026-03-16T00:00:00",
                "data": {
                    "project_id": project_id,
                    "status": "analyzed",
                    "theme": "modern",
                    "max_pages": None,
                    "generate_images": False,
                    "stages": {
                        "analysis": {"completed": True, "data": analysis_data},
                        "outline": {"completed": False},
                        "content": {"completed": False},
                        "design": {"completed": False},
                        "images": {"completed": False},
                        "render": {"completed": False},
                    },
                },
            }
            ckpt_path = project_dir / "checkpoints" / "latest.json"
            ckpt_path.write_text(
                json.dumps(checkpoint, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            result = pipe.resume(str(project_dir))

            assert result.endswith(".pptx")
            # Analysis should be skipped (already done)
            mocks["analyzer"].return_value.analyze.assert_not_called()
            # Extraction should run (not in old checkpoint)
            mocks["extractor"].return_value.extract.assert_called_once()
            # Outline and content should run
            mocks["outline_gen"].return_value.generate.assert_called_once()
            mocks["content_creator"].return_value.create.assert_called_once()
        finally:
            _exit_patches(patches)

    def test_resume_not_found(self, tmp_workspace):
        """Resume with non-existent project raises FileNotFoundError."""
        pipe = PPTPipeline(workspace=tmp_workspace, config={})
        with pytest.raises(FileNotFoundError):
            pipe.resume(os.path.join(tmp_workspace, "ppt", "nonexistent"))


class TestGetStatus:
    """Test PPTPipeline.get_status()."""

    def test_not_found(self, tmp_workspace):
        pipe = PPTPipeline(workspace=tmp_workspace, config={})
        status = pipe.get_status(os.path.join(tmp_workspace, "ppt", "no_such"))
        assert status["status"] == "not_found"

    def test_completed_project_with_extraction(self, tmp_workspace):
        """Status for a completed project with all 10 stages."""
        project_id = "ppt_20260316_abcd1234"
        project_dir = Path(tmp_workspace) / "ppt" / project_id
        for sub in ("images", "output", "checkpoints"):
            (project_dir / sub).mkdir(parents=True, exist_ok=True)

        checkpoint = {
            "stage": "completed",
            "timestamp": "2026-03-16T00:00:00",
            "data": {
                "project_id": project_id,
                "status": "completed",
                "theme": "business",
                "created_at": "2026-03-16T00:00:00",
                "output_path": "/some/path.pptx",
                "stages": {
                    "rewrite": {"completed": True, "rewritten": False},
                    "analysis": {"completed": True},
                    "extraction": {"completed": True, "data": _FAKE_CONTENT_MAP.model_dump()},
                    "enrichment": {"completed": True, "data": None},
                    "planning": {"completed": True, "data": None},
                    "outline": {"completed": True},
                    "content": {"completed": True},
                    "design": {"completed": True},
                    "images": {"completed": True},
                    "render": {"completed": True},
                },
            },
        }
        ckpt_path = project_dir / "checkpoints" / "latest.json"
        ckpt_path.write_text(
            json.dumps(checkpoint, ensure_ascii=False),
            encoding="utf-8",
        )

        pipe = PPTPipeline(workspace=tmp_workspace, config={})
        status = pipe.get_status(str(project_dir))
        assert status["status"] == "completed"
        assert status["theme"] == "business"
        assert len(status["completed_stages"]) == 10
        assert status["total_stages"] == 10
        assert status["output_path"] == "/some/path.pptx"

    def test_backward_compatible_old_checkpoint(self, tmp_workspace):
        """Old checkpoint without extraction stage still works."""
        project_id = "ppt_20260316_oldfmt00"
        project_dir = Path(tmp_workspace) / "ppt" / project_id
        for sub in ("images", "output", "checkpoints"):
            (project_dir / sub).mkdir(parents=True, exist_ok=True)

        checkpoint = {
            "stage": "completed",
            "timestamp": "2026-03-16T00:00:00",
            "data": {
                "project_id": project_id,
                "status": "completed",
                "theme": "modern",
                "created_at": "2026-03-16T00:00:00",
                "output_path": "/old/path.pptx",
                "stages": {
                    "analysis": {"completed": True},
                    "outline": {"completed": True},
                    "content": {"completed": True},
                    "design": {"completed": True},
                    "images": {"completed": True},
                    "render": {"completed": True},
                },
            },
        }
        ckpt_path = project_dir / "checkpoints" / "latest.json"
        ckpt_path.write_text(
            json.dumps(checkpoint, ensure_ascii=False),
            encoding="utf-8",
        )

        pipe = PPTPipeline(workspace=tmp_workspace, config={})
        status = pipe.get_status(str(project_dir))
        assert status["status"] == "completed"
        # Only 6 stages are completed (rewrite+extraction+enrichment+planning missing from old checkpoint)
        assert len(status["completed_stages"]) == 6
        assert status["total_stages"] == 10


class TestImageGeneration:
    """Test image generation integration."""

    def test_image_gen_failure_graceful(self, tmp_workspace):
        """When image generation fails, pipeline still completes."""
        patches = _patch_all()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)
            mocks["design_orch"].return_value.get_image_requests.return_value = (
                _FAKE_IMAGE_REQUESTS
            )

            with patch(
                "src.ppt.pipeline.PPTPipeline._generate_single_image",
                return_value=None,
            ):
                pipe = PPTPipeline(workspace=tmp_workspace, config={})
                result = pipe.generate(
                    text="Test with image generation that fails gracefully.",
                    generate_images=True,
                )

                # Pipeline still completes
                assert result.endswith(".pptx")
        finally:
            _exit_patches(patches)

    def test_skip_images_when_disabled(self, tmp_workspace):
        """generate_images=False skips image generation entirely."""
        patches = _patch_all()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)
            mocks["design_orch"].return_value.get_image_requests.return_value = (
                _FAKE_IMAGE_REQUESTS
            )

            with patch(
                "src.ppt.pipeline.PPTPipeline._generate_single_image",
            ) as MockGenSingle:
                pipe = PPTPipeline(workspace=tmp_workspace, config={})
                pipe.generate(
                    text="Test skip images entirely when disabled.",
                    generate_images=False,
                )

                MockGenSingle.assert_not_called()
        finally:
            _exit_patches(patches)


class TestQualityCheckIntegration:
    """Test quality check within the pipeline."""

    def test_quality_fix_applied(self, tmp_workspace):
        """Issues found by QualityChecker are auto-fixed before render."""
        patches = _patch_all()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)

            # Report with issues
            report_with_issues = QualityReport(
                total_pages=5,
                issues=[
                    QualityIssue(
                        page_number=1,
                        issue_type="title_overflow",
                        severity="high",
                        description="too long",
                        auto_fixable=True,
                    )
                ],
                score=8.5,
                summary="1 issue",
            )
            mocks["quality_checker"].return_value.check.return_value = report_with_issues
            # fix returns "fixed" slides
            mocks["quality_checker"].return_value.fix.return_value = [MagicMock()] * 5

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            pipe.generate(
                text="Test that quality fix is applied before rendering.",
                generate_images=False,
            )

            # fix() should have been called because there were issues
            mocks["quality_checker"].return_value.fix.assert_called_once()
        finally:
            _exit_patches(patches)


class TestLoadContentMap:
    """Test _load_content_map helper."""

    def test_load_valid_data(self):
        data = _FAKE_CONTENT_MAP.model_dump()
        result = PPTPipeline._load_content_map(data)
        assert result is not None
        assert result.document_thesis == "AI is transforming industries"
        assert len(result.content_blocks) == 4

    def test_load_none_returns_none(self):
        assert PPTPipeline._load_content_map(None) is None

    def test_load_invalid_data_returns_none(self):
        result = PPTPipeline._load_content_map({"bad": "data"})
        assert result is None


# ---------------------------------------------------------------------------
# Planning stage tests
# ---------------------------------------------------------------------------

_FAKE_PLAN = PresentationPlan(
    deck_type=DeckType.BUSINESS_REPORT,
    audience="管理层",
    core_message="项目进展顺利，需关注供应链风险",
    presentation_goal="让领导了解当前进展和下一步计划",
    narrative_arc=["结论先行", "说明背景", "展示进展"],
    slides=[],
)


def _patch_all_with_planner():
    """Return patches including the planner enabled."""
    patches = _patch_all()
    # Override has_planner to True
    patches["has_planner"] = patch("src.ppt.pipeline._HAS_PLANNER", True)
    patches["planner"] = patch("src.ppt.pipeline.PresentationPlanner")
    return patches


class TestPlanningStage:
    """Test planning stage integration in pipeline."""

    def test_planning_runs_when_planner_available(self, tmp_workspace):
        """When _HAS_PLANNER is True, PresentationPlanner.plan() is called."""
        patches = _patch_all_with_planner()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)
            mocks["planner"].return_value.plan.return_value = _FAKE_PLAN

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            result = pipe.generate(
                text="Test document for planning stage.",
                generate_images=False,
            )

            assert result.endswith(".pptx")
            mocks["planner"].return_value.plan.assert_called_once()
        finally:
            _exit_patches(patches)

    def test_planning_passes_deck_type_enum_to_content_creator(self, tmp_workspace):
        """deck_type from presentation plan is passed to ContentCreator.create()."""
        patches = _patch_all_with_planner()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)
            mocks["planner"].return_value.plan.return_value = _FAKE_PLAN

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            pipe.generate(
                text="Test document for deck_type forwarding.",
                generate_images=False,
            )

            # Verify deck_type_enum was passed to content creator
            content_call_kwargs = mocks["content_creator"].return_value.create.call_args
            assert content_call_kwargs.kwargs.get("deck_type") == DeckType.BUSINESS_REPORT
        finally:
            _exit_patches(patches)

    def test_planning_skipped_when_planner_unavailable(self, tmp_workspace):
        """When _HAS_PLANNER is False, planning is skipped gracefully."""
        patches = _patch_all()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            result = pipe.generate(
                text="Test document without planner.",
                generate_images=False,
            )

            assert result.endswith(".pptx")
            # deck_type_enum should be None -> content creator gets None
            content_call_kwargs = mocks["content_creator"].return_value.create.call_args
            assert content_call_kwargs.kwargs.get("deck_type") is None
        finally:
            _exit_patches(patches)

    def test_planning_failure_graceful(self, tmp_workspace):
        """When planner.plan() raises, pipeline continues without plan."""
        patches = _patch_all_with_planner()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)
            mocks["planner"].return_value.plan.side_effect = RuntimeError("LLM error")

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            result = pipe.generate(
                text="Test document with planner failure.",
                generate_images=False,
            )

            assert result.endswith(".pptx")
            # deck_type_enum should be None after failure
            content_call_kwargs = mocks["content_creator"].return_value.create.call_args
            assert content_call_kwargs.kwargs.get("deck_type") is None
        finally:
            _exit_patches(patches)

    def test_planning_checkpoint_saved(self, tmp_workspace):
        """Planning stage data is saved to checkpoint."""
        patches = _patch_all_with_planner()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)
            mocks["planner"].return_value.plan.return_value = _FAKE_PLAN

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            pipe.generate(
                text="Test document for checkpoint saving.",
                generate_images=False,
            )

            # Find the project dir
            ppt_dir = Path(tmp_workspace) / "ppt"
            project_dirs = list(ppt_dir.iterdir())
            assert len(project_dirs) == 1

            ckpt_path = project_dirs[0] / "checkpoints" / "latest.json"
            assert ckpt_path.exists()

            ckpt = json.loads(ckpt_path.read_text())
            data = ckpt.get("data", ckpt)
            stages = data["stages"]
            assert stages["planning"]["completed"] is True
            assert stages["planning"]["data"] is not None
            assert stages["planning"]["data"]["deck_type"] == "business_report"
            assert stages["planning"]["data"]["core_message"] == _FAKE_PLAN.core_message
        finally:
            _exit_patches(patches)

    def test_deck_type_param_forwarded_to_planner(self, tmp_workspace):
        """deck_type string parameter is forwarded to PresentationPlanner.plan()."""
        patches = _patch_all_with_planner()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)
            mocks["planner"].return_value.plan.return_value = _FAKE_PLAN

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            pipe.generate(
                text="Test document with explicit deck_type.",
                generate_images=False,
                deck_type="business_report",
            )

            plan_call = mocks["planner"].return_value.plan.call_args
            assert plan_call.kwargs.get("deck_type") == "business_report"
        finally:
            _exit_patches(patches)

    def test_resume_with_completed_planning(self, tmp_workspace):
        """Resume from a checkpoint where planning is already completed."""
        patches = _patch_all_with_planner()
        mocks = _enter_patches(patches)
        try:
            _setup_standard_mocks(mocks)

            project_id = "ppt_20260317_plan1234"
            project_dir = Path(tmp_workspace) / "ppt" / project_id
            for sub in ("images", "output", "checkpoints"):
                (project_dir / sub).mkdir(parents=True, exist_ok=True)

            (project_dir / "input.txt").write_text(
                "Test document content.", encoding="utf-8",
            )

            analysis_data = _FAKE_ANALYSIS.model_dump()
            analysis_data["doc_type"] = _FAKE_ANALYSIS.doc_type.value
            analysis_data["audience"] = _FAKE_ANALYSIS.audience.value
            analysis_data["tone"] = _FAKE_ANALYSIS.tone.value
            extraction_data = _FAKE_CONTENT_MAP.model_dump()
            plan_data = _FAKE_PLAN.model_dump()

            checkpoint = {
                "stage": "planned",
                "timestamp": "2026-03-17T00:00:00",
                "data": {
                    "project_id": project_id,
                    "status": "planned",
                    "theme": "modern",
                    "max_pages": None,
                    "generate_images": False,
                    "stages": {
                        "analysis": {"completed": True, "data": analysis_data},
                        "extraction": {"completed": True, "data": extraction_data},
                        "enrichment": {"completed": True, "data": None},
                        "planning": {"completed": True, "data": plan_data},
                        "outline": {"completed": False},
                        "content": {"completed": False},
                        "design": {"completed": False},
                        "images": {"completed": False},
                        "render": {"completed": False},
                    },
                },
            }
            ckpt_path = project_dir / "checkpoints" / "latest.json"
            ckpt_path.write_text(
                json.dumps(checkpoint, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            pipe = PPTPipeline(workspace=tmp_workspace, config={})
            result = pipe.resume(str(project_dir))

            assert result.endswith(".pptx")
            # Planner should NOT be called again
            mocks["planner"].return_value.plan.assert_not_called()
            # But deck_type should be restored from checkpoint and passed to creator
            content_call_kwargs = mocks["content_creator"].return_value.create.call_args
            assert content_call_kwargs.kwargs.get("deck_type") == DeckType.BUSINESS_REPORT
        finally:
            _exit_patches(patches)
