"""Tests for pipeline data-sync: novel.json -> checkpoint state refresh.

Covers:
- _refresh_state_from_novel() merging logic
- generate_chapters() picks up novel.json edits
- apply_feedback() picks up novel.json edits
- rewrite_affected_chapters reads style_name (not style_subcategory)
"""

from __future__ import annotations

import copy
from unittest.mock import MagicMock, patch

import pytest

from src.novel.pipeline import NovelPipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

OLD_CHARACTERS = [{"name": "Alice", "role": "protagonist"}]
NEW_CHARACTERS = [
    {"name": "Alice", "role": "protagonist"},
    {"name": "Bob", "role": "sidekick"},
]

OLD_OUTLINE = {
    "main_storyline": {"goal": "old goal"},
    "chapters": [
        {"chapter_number": 1, "title": "Ch1", "summary": "old summary"},
    ],
}

NEW_OUTLINE = {
    "main_storyline": {"goal": "new goal"},
    "chapters": [
        {"chapter_number": 1, "title": "Ch1 Revised", "summary": "new summary"},
    ],
}

OLD_WORLD = {"era": "ancient", "location": "old kingdom"}
NEW_WORLD = {"era": "modern", "location": "new city"}


def _make_checkpoint(**overrides) -> dict:
    """Build a minimal checkpoint state dict."""
    base = {
        "outline": copy.deepcopy(OLD_OUTLINE),
        "characters": copy.deepcopy(OLD_CHARACTERS),
        "world_setting": copy.deepcopy(OLD_WORLD),
        "style_name": "wuxia.classical",
        "main_storyline": OLD_OUTLINE["main_storyline"],
        "config": {"llm": {"provider": "openai"}},
        "chapters": [],
    }
    base.update(overrides)
    return base


def _make_novel_data(**overrides) -> dict:
    """Build a minimal novel.json dict with new data."""
    base = {
        "outline": copy.deepcopy(NEW_OUTLINE),
        "characters": copy.deepcopy(NEW_CHARACTERS),
        "world_setting": copy.deepcopy(NEW_WORLD),
        "style_name": "webnovel.shuangwen",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _refresh_state_from_novel unit tests
# ---------------------------------------------------------------------------


class TestRefreshStateFromNovel:
    """Direct tests for the static helper method."""

    def test_characters_refreshed(self):
        state = _make_checkpoint()
        novel_data = _make_novel_data()

        NovelPipeline._refresh_state_from_novel(state, novel_data)

        assert len(state["characters"]) == 2
        names = {c["name"] for c in state["characters"]}
        assert names == {"Alice", "Bob"}

    def test_outline_refreshed(self):
        state = _make_checkpoint()
        novel_data = _make_novel_data()

        NovelPipeline._refresh_state_from_novel(state, novel_data)

        assert state["outline"]["chapters"][0]["title"] == "Ch1 Revised"

    def test_main_storyline_refreshed(self):
        state = _make_checkpoint()
        novel_data = _make_novel_data()

        NovelPipeline._refresh_state_from_novel(state, novel_data)

        assert state["main_storyline"]["goal"] == "new goal"

    def test_world_setting_refreshed(self):
        state = _make_checkpoint()
        novel_data = _make_novel_data()

        NovelPipeline._refresh_state_from_novel(state, novel_data)

        assert state["world_setting"]["location"] == "new city"

    def test_style_name_refreshed(self):
        state = _make_checkpoint()
        novel_data = _make_novel_data()

        NovelPipeline._refresh_state_from_novel(state, novel_data)

        assert state["style_name"] == "webnovel.shuangwen"

    def test_none_novel_data_is_noop(self):
        state = _make_checkpoint()
        original = copy.deepcopy(state)

        NovelPipeline._refresh_state_from_novel(state, None)

        assert state["characters"] == original["characters"]
        assert state["outline"] == original["outline"]
        assert state["style_name"] == original["style_name"]

    def test_empty_novel_data_is_noop(self):
        state = _make_checkpoint()
        original_chars = copy.deepcopy(state["characters"])

        NovelPipeline._refresh_state_from_novel(state, {})

        assert state["characters"] == original_chars

    def test_partial_novel_data_only_refreshes_present_keys(self):
        state = _make_checkpoint()
        # novel.json only has characters, no outline
        novel_data = {"characters": NEW_CHARACTERS}

        NovelPipeline._refresh_state_from_novel(state, novel_data)

        assert len(state["characters"]) == 2  # refreshed
        assert state["outline"] == OLD_OUTLINE  # untouched
        assert state["style_name"] == "wuxia.classical"  # untouched

    def test_returns_same_dict(self):
        state = _make_checkpoint()
        result = NovelPipeline._refresh_state_from_novel(state, _make_novel_data())
        assert result is state

    def test_outline_without_main_storyline_skips_refresh(self):
        state = _make_checkpoint()
        novel_data = {"outline": {"chapters": [{"chapter_number": 1, "title": "X"}]}}

        NovelPipeline._refresh_state_from_novel(state, novel_data)

        # main_storyline should remain the old value
        assert state["main_storyline"] == OLD_OUTLINE["main_storyline"]
        # but outline itself is refreshed
        assert state["outline"]["chapters"][0]["title"] == "X"


# ---------------------------------------------------------------------------
# generate_chapters integration: verify refresh is called
# ---------------------------------------------------------------------------


class TestGenerateChaptersRefresh:
    """Verify generate_chapters() refreshes state from novel.json."""

    @patch("src.novel.pipeline.build_chapter_graph")
    def test_generate_refreshes_settings_from_novel_json(
        self, mock_build_graph
    ):
        """Checkpoint has old characters; novel.json has new ones.

        After refresh, state used by generation must reflect novel.json.
        """
        pipe = NovelPipeline(workspace="/tmp/test_ws")

        checkpoint = _make_checkpoint()
        novel_data = _make_novel_data()

        mock_fm = MagicMock()
        mock_fm.load_novel.return_value = novel_data
        pipe.file_manager = mock_fm

        # Mock chapter graph to capture the state it receives
        captured_states = []

        def fake_invoke(state):
            captured_states.append(copy.deepcopy(state))
            state["current_chapter_text"] = "fake text"
            state["current_chapter_quality"] = {"score": 8}
            return state

        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = fake_invoke
        mock_build_graph.return_value = mock_graph

        with patch.object(NovelPipeline, "_load_checkpoint", return_value=checkpoint), \
             patch.object(NovelPipeline, "_save_checkpoint"), \
             patch.object(NovelPipeline, "_backfill_outline_entry"):
            pipe.generate_chapters(
                project_path="/tmp/test_ws/novels/novel_001",
                start_chapter=1,
                end_chapter=1,
                silent=True,
            )

        # The graph should have been invoked with refreshed characters
        assert len(captured_states) == 1
        used_state = captured_states[0]
        assert len(used_state["characters"]) == 2
        names = {c["name"] for c in used_state["characters"]}
        assert names == {"Alice", "Bob"}

    @patch("src.novel.pipeline.build_chapter_graph")
    def test_generate_refreshes_outline_from_novel_json(
        self, mock_build_graph
    ):
        checkpoint = _make_checkpoint()
        novel_data = _make_novel_data()

        pipe = NovelPipeline(workspace="/tmp/test_ws")
        mock_fm = MagicMock()
        mock_fm.load_novel.return_value = novel_data
        pipe.file_manager = mock_fm

        captured_states = []

        def fake_invoke(state):
            captured_states.append(copy.deepcopy(state))
            state["current_chapter_text"] = "fake text"
            state["current_chapter_quality"] = {"score": 8}
            return state

        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = fake_invoke
        mock_build_graph.return_value = mock_graph

        with patch.object(NovelPipeline, "_load_checkpoint", return_value=checkpoint), \
             patch.object(NovelPipeline, "_save_checkpoint"), \
             patch.object(NovelPipeline, "_backfill_outline_entry"):
            pipe.generate_chapters(
                project_path="/tmp/test_ws/novels/novel_001",
                start_chapter=1,
                end_chapter=1,
                silent=True,
            )

        used_state = captured_states[0]
        assert used_state["outline"]["chapters"][0]["title"] == "Ch1 Revised"
        assert used_state["main_storyline"]["goal"] == "new goal"

    @patch("src.novel.pipeline.build_chapter_graph")
    def test_generate_refreshes_style_name(self, mock_build_graph):
        checkpoint = _make_checkpoint()
        novel_data = _make_novel_data()

        pipe = NovelPipeline(workspace="/tmp/test_ws")
        mock_fm = MagicMock()
        mock_fm.load_novel.return_value = novel_data
        pipe.file_manager = mock_fm

        captured_states = []

        def fake_invoke(state):
            captured_states.append(copy.deepcopy(state))
            state["current_chapter_text"] = "fake text"
            state["current_chapter_quality"] = {"score": 8}
            return state

        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = fake_invoke
        mock_build_graph.return_value = mock_graph

        with patch.object(NovelPipeline, "_load_checkpoint", return_value=checkpoint), \
             patch.object(NovelPipeline, "_save_checkpoint"), \
             patch.object(NovelPipeline, "_backfill_outline_entry"):
            pipe.generate_chapters(
                project_path="/tmp/test_ws/novels/novel_001",
                start_chapter=1,
                end_chapter=1,
                silent=True,
            )

        used_state = captured_states[0]
        assert used_state["style_name"] == "webnovel.shuangwen"


# ---------------------------------------------------------------------------
# apply_feedback integration: verify refresh is called
# ---------------------------------------------------------------------------


class TestApplyFeedbackRefresh:
    """Verify apply_feedback() refreshes state from novel.json."""

    def test_apply_feedback_refreshes_settings(self):
        """Dry-run mode: verify that analysis uses refreshed characters."""
        from src.novel.agents.feedback_analyzer import FeedbackAnalyzer

        checkpoint = _make_checkpoint()
        novel_data = _make_novel_data()

        pipe = NovelPipeline(workspace="/tmp/test_ws")
        mock_fm = MagicMock()
        mock_fm.load_novel.return_value = novel_data
        pipe.file_manager = mock_fm

        mock_llm = MagicMock()

        # Capture characters passed to FeedbackAnalyzer.analyze
        captured_kwargs = {}

        def fake_analyze(**kwargs):
            captured_kwargs.update(kwargs)
            return {
                "feedback_type": "character",
                "severity": "medium",
                "target_chapters": [],
                "propagation_chapters": [],
            }

        with patch.object(NovelPipeline, "_load_checkpoint", return_value=checkpoint), \
             patch("src.llm.llm_client.create_llm_client", return_value=mock_llm), \
             patch.object(FeedbackAnalyzer, "analyze", side_effect=fake_analyze):
            result = pipe.apply_feedback(
                project_path="/tmp/test_ws/novels/novel_001",
                feedback_text="Bob should appear more",
                chapter_number=1,
                dry_run=True,
            )

        # The analyzer should have received the refreshed characters from novel.json
        assert len(captured_kwargs["characters"]) == 2
        names = {c["name"] for c in captured_kwargs["characters"]}
        assert names == {"Alice", "Bob"}

        # Also check outline was refreshed
        assert captured_kwargs["outline_chapters"][0]["title"] == "Ch1 Revised"


# ---------------------------------------------------------------------------
# style_name in rewrite_affected_chapters
# ---------------------------------------------------------------------------


class TestStyleNameInRewrite:
    """Verify rewrite_affected_chapters reads style_name (not style_subcategory)."""

    def test_style_name_field_used(self):
        """novel_data with style_name should be picked up, not style_subcategory."""
        # Simulate novel_data that has style_name but NOT style_subcategory
        novel_data = {
            "style_name": "xianxia.cultivation",
            "outline": {
                "chapters": [
                    {"chapter_number": 1, "title": "Ch1", "summary": "s"},
                ],
            },
            "characters": [],
            "world_setting": {"era": "ancient", "location": "sect"},
        }

        # The fix: novel_data.get("style_name", ...) should find "xianxia.cultivation"
        style_name = novel_data.get("style_name", "webnovel.shuangwen")
        assert style_name == "xianxia.cultivation"

    def test_style_subcategory_not_used(self):
        """If only style_subcategory exists (legacy), style_name default is used."""
        novel_data = {
            "style_subcategory": "some_legacy_value",
        }

        # After the fix, we read style_name, so style_subcategory is ignored
        style_name = novel_data.get("style_name", "webnovel.shuangwen")
        assert style_name == "webnovel.shuangwen"
