"""Tests for narrative control integration in NovelPipeline.

Verifies:
- Narrative control services (ObligationTracker, DebtExtractor, BriefValidator)
  are initialized in generate_chapters()
- Debts are escalated before each chapter generation
- Services are passed to chapter graph state
- Pipeline works without narrative control (graceful degradation)
- Debt statistics are included in the generation result
- chapter_brief is extracted and added to state
- Story arc generation in create_novel() is attempted (with hasattr guard)
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake-model"
    usage: dict | None = None


def _make_outline_dict(total_chapters: int = 3) -> dict:
    """Create a minimal outline dict with chapter_brief fields."""
    return {
        "template": "cyclic_upgrade",
        "main_storyline": {"core": "测试主线"},
        "acts": [
            {
                "name": "第一幕",
                "description": "开端",
                "start_chapter": 1,
                "end_chapter": total_chapters,
            }
        ],
        "volumes": [
            {
                "volume_number": 1,
                "title": "第一卷",
                "core_conflict": "矛盾",
                "resolution": "解决",
                "chapters": list(range(1, total_chapters + 1)),
            }
        ],
        "chapters": [
            {
                "chapter_number": i,
                "title": f"第{i}章测试",
                "goal": f"目标{i}",
                "key_events": [f"事件{i}"],
                "estimated_words": 3000,
                "mood": "蓄力",
                "chapter_brief": {
                    "main_conflict": f"第{i}章主冲突",
                    "payoff": f"第{i}章爽点",
                    "end_hook_type": "悬念",
                },
            }
            for i in range(1, total_chapters + 1)
        ],
    }


def _make_world_setting_dict() -> dict:
    return {
        "era": "上古时代",
        "location": "九州大陆",
        "rules": [],
        "terms": {},
        "power_system": None,
    }


def _make_character_dict(name: str = "主角") -> dict:
    return {
        "name": name,
        "gender": "男",
        "age": 18,
        "occupation": "修仙者",
        "role": "主角",
        "personality": {
            "traits": ["勇敢"],
            "speech_style": "简洁有力",
            "core_belief": "永不放弃",
            "flaw": "冲动",
            "catchphrases": [],
        },
        "appearance": {
            "height": "180cm",
            "build": "修长",
            "distinctive_features": ["剑眉"],
            "clothing_style": "青色长袍",
        },
        "background": "平凡少年",
    }


def _make_fake_state(novel_id: str = "test_novel", total_chapters: int = 3) -> dict:
    return {
        "genre": "玄幻",
        "theme": "修仙逆袭",
        "target_words": 15000,
        "style_name": "webnovel.shuangwen",
        "template": "cyclic_upgrade",
        "novel_id": novel_id,
        "workspace": "/tmp/test_workspace",
        "config": {"llm": {"provider": "auto"}},
        "current_chapter": 0,
        "total_chapters": total_chapters,
        "review_interval": 5,
        "silent_mode": True,
        "auto_approve_threshold": 6.0,
        "max_retries": 2,
        "outline": _make_outline_dict(total_chapters),
        "world_setting": _make_world_setting_dict(),
        "characters": [_make_character_dict()],
        "main_storyline": {"core": "测试主线"},
        "chapters": [],
        "decisions": [],
        "errors": [],
        "completed_nodes": [],
        "retry_counts": {},
        "should_continue": True,
    }


# ---------------------------------------------------------------------------
# Mock chapter graph that captures state
# ---------------------------------------------------------------------------


class MockChapterGraph:
    """A mock chapter graph that records states passed to invoke()."""

    def __init__(self):
        self.invoked_states: list[dict] = []

    def invoke(self, state: dict) -> dict:
        # Record a snapshot of the state at invoke time
        self.invoked_states.append(dict(state))
        ch = state.get("current_chapter", 1)
        state["current_chapter_text"] = f"第{ch}章正文内容。测试文本。" * 10
        state["current_chapter_quality"] = {"need_rewrite": False}
        return state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return str(ws)


@pytest.fixture
def pipeline(tmp_workspace):
    from src.novel.pipeline import NovelPipeline
    from src.novel.config import NovelConfig

    config = NovelConfig()
    return NovelPipeline(config=config, workspace=tmp_workspace)


def _setup_project(pipeline, novel_id: str = "test_novel", total_chapters: int = 3):
    """Create project directory with checkpoint and novel.json."""
    state = _make_fake_state(novel_id, total_chapters)
    novel_dir = Path(pipeline.workspace) / "novels" / novel_id
    novel_dir.mkdir(parents=True, exist_ok=True)

    # Save checkpoint
    pipeline._save_checkpoint(novel_id, state)

    # Save novel.json
    fm = pipeline._get_file_manager()
    novel_data = {
        "novel_id": novel_id,
        "title": "测试小说",
        "genre": "玄幻",
        "theme": "修仙逆袭",
        "target_words": 15000,
        "status": "initialized",
        "current_chapter": 0,
        "outline": state["outline"],
        "characters": state["characters"],
        "world_setting": state["world_setting"],
        "style_name": "webnovel.shuangwen",
    }
    fm.save_novel(novel_id, novel_data)
    return state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGenerateChaptersInitializesServices:
    """Task 6.1: Verify narrative control services are initialized."""

    def test_generate_chapters_initializes_services(self, pipeline, tmp_workspace):
        """Services should be created when generate_chapters is called."""
        novel_id = "test_novel"
        _setup_project(pipeline, novel_id)
        project_path = str(Path(tmp_workspace) / "novels" / novel_id)

        mock_graph = MockChapterGraph()

        with patch("src.novel.pipeline.build_chapter_graph", return_value=mock_graph), \
             patch("src.novel.services.obligation_tracker.ObligationTracker") as MockTracker, \
             patch("src.novel.services.debt_extractor.DebtExtractor") as MockExtractor, \
             patch("src.novel.tools.brief_validator.BriefValidator") as MockValidator, \
             patch("src.llm.llm_client.create_llm_client") as mock_create_llm:

            mock_llm = MagicMock()
            mock_create_llm.return_value = mock_llm

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.escalate_debts.return_value = 0
            mock_tracker_inst.get_debt_statistics.return_value = {
                "pending_count": 0,
                "fulfilled_count": 0,
                "overdue_count": 0,
            }
            MockTracker.return_value = mock_tracker_inst

            mock_extractor_inst = MagicMock()
            MockExtractor.return_value = mock_extractor_inst

            mock_validator_inst = MagicMock()
            MockValidator.return_value = mock_validator_inst

            result = pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=2, silent=True)

            # Services should have been created
            MockTracker.assert_called_once()
            MockExtractor.assert_called_once_with(mock_llm)
            MockValidator.assert_called_once_with(mock_llm)

            assert result["total_generated"] == 2


class TestGenerateChaptersEscalatesDebts:
    """Task 6.1: Verify escalate_debts is called per chapter."""

    def test_generate_chapters_escalates_debts(self, pipeline, tmp_workspace):
        """escalate_debts should be called before each chapter generation."""
        novel_id = "test_novel"
        _setup_project(pipeline, novel_id, total_chapters=3)
        project_path = str(Path(tmp_workspace) / "novels" / novel_id)

        mock_graph = MockChapterGraph()

        with patch("src.novel.pipeline.build_chapter_graph", return_value=mock_graph), \
             patch("src.novel.services.obligation_tracker.ObligationTracker") as MockTracker, \
             patch("src.novel.services.debt_extractor.DebtExtractor"), \
             patch("src.novel.tools.brief_validator.BriefValidator"), \
             patch("src.llm.llm_client.create_llm_client") as mock_create_llm:

            mock_create_llm.return_value = MagicMock()

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.escalate_debts.return_value = 0
            mock_tracker_inst.get_debt_statistics.return_value = {"pending_count": 0}
            MockTracker.return_value = mock_tracker_inst

            pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=3, silent=True)

            # escalate_debts should be called for each chapter
            assert mock_tracker_inst.escalate_debts.call_count == 3
            mock_tracker_inst.escalate_debts.assert_any_call(1)
            mock_tracker_inst.escalate_debts.assert_any_call(2)
            mock_tracker_inst.escalate_debts.assert_any_call(3)

    def test_escalate_debts_logs_escalated_count(self, pipeline, tmp_workspace):
        """When debts are escalated, log message should be generated."""
        novel_id = "test_novel"
        _setup_project(pipeline, novel_id, total_chapters=2)
        project_path = str(Path(tmp_workspace) / "novels" / novel_id)

        mock_graph = MockChapterGraph()

        with patch("src.novel.pipeline.build_chapter_graph", return_value=mock_graph), \
             patch("src.novel.services.obligation_tracker.ObligationTracker") as MockTracker, \
             patch("src.novel.services.debt_extractor.DebtExtractor"), \
             patch("src.novel.tools.brief_validator.BriefValidator"), \
             patch("src.llm.llm_client.create_llm_client") as mock_create_llm:

            mock_create_llm.return_value = MagicMock()

            mock_tracker_inst = MagicMock()
            # Return 2 escalated debts for chapter 2
            mock_tracker_inst.escalate_debts.side_effect = [0, 2]
            mock_tracker_inst.get_debt_statistics.return_value = {"overdue_count": 2}
            MockTracker.return_value = mock_tracker_inst

            result = pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=2, silent=True)
            assert result["total_generated"] == 2


class TestGenerateChaptersPassesServicesToState:
    """Task 6.1 + 6.3: Verify state contains services and chapter_brief."""

    def test_generate_chapters_passes_services_to_state(self, pipeline, tmp_workspace):
        """State dict passed to chapter graph should contain narrative control services."""
        novel_id = "test_novel"
        _setup_project(pipeline, novel_id)
        project_path = str(Path(tmp_workspace) / "novels" / novel_id)

        mock_graph = MockChapterGraph()

        with patch("src.novel.pipeline.build_chapter_graph", return_value=mock_graph), \
             patch("src.novel.services.obligation_tracker.ObligationTracker") as MockTracker, \
             patch("src.novel.services.debt_extractor.DebtExtractor") as MockExtractor, \
             patch("src.novel.tools.brief_validator.BriefValidator") as MockValidator, \
             patch("src.llm.llm_client.create_llm_client") as mock_create_llm:

            mock_create_llm.return_value = MagicMock()

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.escalate_debts.return_value = 0
            mock_tracker_inst.get_debt_statistics.return_value = {}
            MockTracker.return_value = mock_tracker_inst

            mock_extractor_inst = MagicMock()
            MockExtractor.return_value = mock_extractor_inst

            mock_validator_inst = MagicMock()
            MockValidator.return_value = mock_validator_inst

            pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=1, silent=True)

            # Check state passed to the chapter graph
            assert len(mock_graph.invoked_states) == 1
            invoked_state = mock_graph.invoked_states[0]

            assert invoked_state["obligation_tracker"] is mock_tracker_inst
            assert invoked_state["brief_validator"] is mock_validator_inst
            assert invoked_state["debt_extractor"] is mock_extractor_inst


class TestGenerateChaptersWithoutNarrativeControl:
    """Task 6.1: Verify pipeline works when services fail to initialize."""

    def test_generate_chapters_without_narrative_control(self, pipeline, tmp_workspace):
        """Pipeline should work even if narrative control fails to initialize."""
        novel_id = "test_novel"
        _setup_project(pipeline, novel_id)
        project_path = str(Path(tmp_workspace) / "novels" / novel_id)

        mock_graph = MockChapterGraph()

        # Make the import of ObligationTracker raise an exception
        with patch("src.novel.pipeline.build_chapter_graph", return_value=mock_graph), \
             patch.dict("sys.modules", {
                 "src.novel.services.obligation_tracker": None,
             }):
            # The import will fail, but pipeline should still work
            result = pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=2, silent=True)

            assert result["total_generated"] == 2
            assert "debt_statistics" not in result

    def test_services_none_in_state_when_init_fails(self, pipeline, tmp_workspace):
        """When service initialization fails, state should have None services."""
        novel_id = "test_novel"
        _setup_project(pipeline, novel_id)
        project_path = str(Path(tmp_workspace) / "novels" / novel_id)

        mock_graph = MockChapterGraph()

        # Force initialization failure by making create_llm_client raise
        with patch("src.novel.pipeline.build_chapter_graph", return_value=mock_graph), \
             patch("src.llm.llm_client.create_llm_client", side_effect=RuntimeError("No API key")):

            result = pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=1, silent=True)

            assert result["total_generated"] == 1
            invoked_state = mock_graph.invoked_states[0]
            assert invoked_state["obligation_tracker"] is None
            assert invoked_state["brief_validator"] is None
            assert invoked_state["debt_extractor"] is None


class TestDebtStatisticsInResult:
    """Task 6.1: Verify result includes debt statistics."""

    def test_debt_statistics_in_result(self, pipeline, tmp_workspace):
        """Result dict should include debt_statistics when tracker is available."""
        novel_id = "test_novel"
        _setup_project(pipeline, novel_id)
        project_path = str(Path(tmp_workspace) / "novels" / novel_id)

        mock_graph = MockChapterGraph()

        expected_stats = {
            "pending_count": 3,
            "fulfilled_count": 1,
            "overdue_count": 2,
            "abandoned_count": 0,
            "avg_fulfillment_chapters": 1.5,
        }

        with patch("src.novel.pipeline.build_chapter_graph", return_value=mock_graph), \
             patch("src.novel.services.obligation_tracker.ObligationTracker") as MockTracker, \
             patch("src.novel.services.debt_extractor.DebtExtractor"), \
             patch("src.novel.tools.brief_validator.BriefValidator"), \
             patch("src.llm.llm_client.create_llm_client") as mock_create_llm:

            mock_create_llm.return_value = MagicMock()

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.escalate_debts.return_value = 0
            mock_tracker_inst.get_debt_statistics.return_value = expected_stats
            MockTracker.return_value = mock_tracker_inst

            result = pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=1, silent=True)

            assert "debt_statistics" in result
            assert result["debt_statistics"] == expected_stats

    def test_debt_statistics_missing_when_tracker_fails(self, pipeline, tmp_workspace):
        """Result should not have debt_statistics when stats call fails."""
        novel_id = "test_novel"
        _setup_project(pipeline, novel_id)
        project_path = str(Path(tmp_workspace) / "novels" / novel_id)

        mock_graph = MockChapterGraph()

        with patch("src.novel.pipeline.build_chapter_graph", return_value=mock_graph), \
             patch("src.novel.services.obligation_tracker.ObligationTracker") as MockTracker, \
             patch("src.novel.services.debt_extractor.DebtExtractor"), \
             patch("src.novel.tools.brief_validator.BriefValidator"), \
             patch("src.llm.llm_client.create_llm_client") as mock_create_llm:

            mock_create_llm.return_value = MagicMock()

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.escalate_debts.return_value = 0
            mock_tracker_inst.get_debt_statistics.side_effect = RuntimeError("DB error")
            MockTracker.return_value = mock_tracker_inst

            result = pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=1, silent=True)

            # debt_statistics should be absent (exception caught)
            assert "debt_statistics" not in result


class TestChapterBriefInState:
    """Task 6.3: Verify chapter_brief extracted and added to state."""

    def test_chapter_brief_in_state(self, pipeline, tmp_workspace):
        """State should contain current_chapter_brief from the chapter outline."""
        novel_id = "test_novel"
        _setup_project(pipeline, novel_id, total_chapters=2)
        project_path = str(Path(tmp_workspace) / "novels" / novel_id)

        mock_graph = MockChapterGraph()

        with patch("src.novel.pipeline.build_chapter_graph", return_value=mock_graph), \
             patch("src.novel.services.obligation_tracker.ObligationTracker") as MockTracker, \
             patch("src.novel.services.debt_extractor.DebtExtractor"), \
             patch("src.novel.tools.brief_validator.BriefValidator"), \
             patch("src.llm.llm_client.create_llm_client") as mock_create_llm:

            mock_create_llm.return_value = MagicMock()
            mock_tracker_inst = MagicMock()
            mock_tracker_inst.escalate_debts.return_value = 0
            mock_tracker_inst.get_debt_statistics.return_value = {}
            MockTracker.return_value = mock_tracker_inst

            pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=2, silent=True)

            assert len(mock_graph.invoked_states) == 2

            # Chapter 1
            state1 = mock_graph.invoked_states[0]
            assert "current_chapter_brief" in state1
            assert state1["current_chapter_brief"]["main_conflict"] == "第1章主冲突"
            assert state1["current_chapter_brief"]["payoff"] == "第1章爽点"
            assert state1["current_chapter"] == 1

            # Chapter 2
            state2 = mock_graph.invoked_states[1]
            assert state2["current_chapter_brief"]["main_conflict"] == "第2章主冲突"
            assert state2["current_chapter"] == 2

    def test_chapter_brief_empty_when_not_in_outline(self, pipeline, tmp_workspace):
        """When chapter outline has no chapter_brief, state should have empty dict."""
        novel_id = "test_novel"

        # Create project with outlines missing chapter_brief
        state = _make_fake_state(novel_id, total_chapters=1)
        # Remove chapter_brief from outline
        for ch in state["outline"]["chapters"]:
            ch.pop("chapter_brief", None)

        novel_dir = Path(pipeline.workspace) / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)
        pipeline._save_checkpoint(novel_id, state)

        fm = pipeline._get_file_manager()
        fm.save_novel(novel_id, {
            "novel_id": novel_id,
            "outline": state["outline"],
            "characters": state["characters"],
            "world_setting": state["world_setting"],
        })

        project_path = str(Path(pipeline.workspace) / "novels" / novel_id)
        mock_graph = MockChapterGraph()

        with patch("src.novel.pipeline.build_chapter_graph", return_value=mock_graph), \
             patch("src.novel.services.obligation_tracker.ObligationTracker") as MockTracker, \
             patch("src.novel.services.debt_extractor.DebtExtractor"), \
             patch("src.novel.tools.brief_validator.BriefValidator"), \
             patch("src.llm.llm_client.create_llm_client") as mock_create_llm:

            mock_create_llm.return_value = MagicMock()
            mock_tracker_inst = MagicMock()
            mock_tracker_inst.escalate_debts.return_value = 0
            mock_tracker_inst.get_debt_statistics.return_value = {}
            MockTracker.return_value = mock_tracker_inst

            pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=1, silent=True)

            state_invoked = mock_graph.invoked_states[0]
            assert state_invoked["current_chapter_brief"] == {}


class TestCreateNovelStoryArcs:
    """Task 6.2: Verify story arc generation in create_novel."""

    def test_create_novel_attempts_story_arc_generation(self, pipeline, tmp_workspace):
        """create_novel should try to generate story arcs using director."""
        mock_nodes = {
            "novel_director": lambda s: {
                "outline": _make_outline_dict(3),
                "total_chapters": 3,
                "style_name": "webnovel.shuangwen",
                "template": "cyclic_upgrade",
                "decisions": [],
                "errors": [],
                "completed_nodes": ["novel_director"],
            },
            "world_builder": lambda s: {
                "world_setting": _make_world_setting_dict(),
                "decisions": [],
                "errors": [],
                "completed_nodes": ["world_builder"],
            },
            "character_designer": lambda s: {
                "characters": [_make_character_dict()],
                "decisions": [],
                "errors": [],
                "completed_nodes": ["character_designer"],
            },
        }

        fake_arcs = [
            {"arc_id": "arc_1", "name": "开篇弧", "chapters": [1, 2]},
            {"arc_id": "arc_2", "name": "发展弧", "chapters": [3]},
        ]

        # Phase 3-B1: arc generation now lives on ProjectArchitect; patch the
        # impl directly so we can both stub the return value and assert the call.
        from src.novel.agents.project_architect import ProjectArchitect as _PA
        with patch("src.novel.agents.graph._get_node_functions", return_value=mock_nodes), \
             patch.object(_PA, "_generate_story_arcs", return_value=fake_arcs) as mock_arcs, \
             patch("src.llm.llm_client.create_llm_client", return_value=MagicMock()):

            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙逆袭",
                target_words=15000,
            )

            assert "novel_id" in result
            assert "outline" in result
            mock_arcs.assert_called_once()

    def test_create_novel_works_when_arc_impl_returns_empty(self, pipeline, tmp_workspace):
        """create_novel should work even if the arc impl returns no arcs."""
        mock_nodes = {
            "novel_director": lambda s: {
                "outline": _make_outline_dict(3),
                "total_chapters": 3,
                "style_name": "webnovel.shuangwen",
                "template": "cyclic_upgrade",
                "decisions": [],
                "errors": [],
                "completed_nodes": ["novel_director"],
            },
            "world_builder": lambda s: {
                "world_setting": _make_world_setting_dict(),
                "decisions": [],
                "errors": [],
                "completed_nodes": ["world_builder"],
            },
            "character_designer": lambda s: {
                "characters": [_make_character_dict()],
                "decisions": [],
                "errors": [],
                "completed_nodes": ["character_designer"],
            },
        }

        from src.novel.agents.project_architect import ProjectArchitect as _PA
        with patch("src.novel.agents.graph._get_node_functions", return_value=mock_nodes), \
             patch.object(_PA, "_generate_story_arcs", return_value=[]), \
             patch("src.llm.llm_client.create_llm_client", return_value=MagicMock()):

            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙逆袭",
                target_words=15000,
            )

            assert "novel_id" in result
            assert result["outline"] is not None

    def test_create_novel_arc_generation_exception_non_fatal(self, pipeline, tmp_workspace):
        """Exception in story arc generation should not crash create_novel."""
        mock_nodes = {
            "novel_director": lambda s: {
                "outline": _make_outline_dict(3),
                "total_chapters": 3,
                "style_name": "webnovel.shuangwen",
                "template": "cyclic_upgrade",
                "decisions": [],
                "errors": [],
                "completed_nodes": ["novel_director"],
            },
            "world_builder": lambda s: {
                "world_setting": _make_world_setting_dict(),
                "decisions": [],
                "errors": [],
                "completed_nodes": ["world_builder"],
            },
            "character_designer": lambda s: {
                "characters": [_make_character_dict()],
                "decisions": [],
                "errors": [],
                "completed_nodes": ["character_designer"],
            },
        }

        # Phase 3-B1: arc generation is guarded by propose_story_arcs'
        # try/except; raising from the impl must not crash create_novel.
        from src.novel.agents.project_architect import ProjectArchitect as _PA
        with patch("src.novel.agents.graph._get_node_functions", return_value=mock_nodes), \
             patch.object(_PA, "_generate_story_arcs", side_effect=RuntimeError("x")):
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙逆袭",
                target_words=15000,
            )

            assert "novel_id" in result
            assert result["outline"] is not None
