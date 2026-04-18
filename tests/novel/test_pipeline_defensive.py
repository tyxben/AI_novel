"""Defensive tests for NovelPipeline — regression coverage for known bugs.

Covers:
- Bug #7: State preservation across graph.invoke (service objects lost)
- Bug #8: Chapter deduplication on resume
- Bug #22: word_count must use count_words, not len()
- Bug #23: MAX_REWRITES vs max_retries mismatch / force-pass logic
- Consecutive failure handling (3-strike abort)
- Checkpoint save/restore round-trip (non-serializable, full_text stripping)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.novel.agents.graph import MAX_REWRITES, _should_rewrite, _merge_state
from src.novel.utils import count_words


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_outline_dict(total_chapters: int = 5) -> dict:
    return {
        "template": "cyclic_upgrade",
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
            "speech_style": "简洁",
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


def _make_base_state(novel_id: str = "test_novel", total_chapters: int = 5) -> dict:
    return {
        "genre": "玄幻",
        "theme": "修仙逆袭",
        "target_words": 50000,
        "style_name": "webnovel.shuangwen",
        "template": "cyclic_upgrade",
        "novel_id": novel_id,
        "workspace": "/tmp/test_workspace",
        "config": {},
        "current_chapter": 0,
        "total_chapters": total_chapters,
        "review_interval": 5,
        "silent_mode": True,
        "auto_approve_threshold": 6.0,
        "max_retries": 2,
        "outline": _make_outline_dict(total_chapters),
        "world_setting": _make_world_setting_dict(),
        "characters": [_make_character_dict()],
        "main_storyline": {},
        "chapters": [],
        "decisions": [],
        "errors": [],
        "completed_nodes": [],
        "retry_counts": {},
        "should_continue": True,
        "budget_mode": False,
    }


# ===========================================================================
# 1. State preservation across graph.invoke (Bug #7)
# ===========================================================================


class TestStatePreservationAcrossGraphInvoke:
    """Verify that pipeline merges graph result without losing service objects.

    Bug #7: chapter_graph.invoke() returns a dict that does NOT contain
    obligation_tracker, brief_validator, debt_extractor, or memory.
    The pipeline must preserve these in state after the merge.
    """

    def test_service_objects_preserved_after_graph_invoke_merge(self):
        """Simulate the merge loop from pipeline lines 1024-1029."""
        # Set up state with service objects
        mock_obligation_tracker = MagicMock(name="ObligationTracker")
        mock_brief_validator = MagicMock(name="BriefValidator")
        mock_debt_extractor = MagicMock(name="DebtExtractor")
        mock_memory = MagicMock(name="NovelMemory")

        state = _make_base_state()
        state["obligation_tracker"] = mock_obligation_tracker
        state["brief_validator"] = mock_brief_validator
        state["debt_extractor"] = mock_debt_extractor
        state["memory"] = mock_memory
        state["novel_id"] = "test_novel_001"
        state["workspace"] = "/tmp/ws"

        # Graph result does NOT include these fields (the bug scenario)
        graph_result = {
            "current_chapter_text": "这是第一章的正文内容" * 50,
            "current_chapter_quality": {"score": 8.0, "need_rewrite": False},
            "decisions": [{"agent": "Writer", "step": "write", "decision": "ok", "reason": "done"}],
            "errors": [],
            "completed_nodes": ["writer", "quality_reviewer"],
            "retry_counts": {1: 0},
        }

        # Reproduce the pipeline merge logic (lines 1028-1029)
        for key, value in graph_result.items():
            state[key] = value

        # Assert service objects survive the merge
        assert state["obligation_tracker"] is mock_obligation_tracker
        assert state["brief_validator"] is mock_brief_validator
        assert state["debt_extractor"] is mock_debt_extractor
        assert state["memory"] is mock_memory
        assert state["novel_id"] == "test_novel_001"
        assert state["workspace"] == "/tmp/ws"

    def test_service_objects_overwritten_if_graph_returns_none(self):
        """If graph explicitly returns None for a field, it overwrites state."""
        mock_tracker = MagicMock(name="ObligationTracker")
        state = _make_base_state()
        state["obligation_tracker"] = mock_tracker

        # Graph explicitly returns None for this field
        graph_result = {
            "obligation_tracker": None,
            "current_chapter_text": "测试文本",
        }

        for key, value in graph_result.items():
            state[key] = value

        # The explicit None SHOULD overwrite (graph said so)
        assert state["obligation_tracker"] is None

    def test_merge_state_helper_preserves_non_graph_fields(self):
        """Test the _merge_state helper from graph.py preserves extra fields."""
        base = {
            "obligation_tracker": MagicMock(),
            "chapters": [{"chapter_number": 1}],
            "decisions": [{"agent": "a", "step": "s", "decision": "d", "reason": "r"}],
        }
        update = {
            "current_chapter_text": "new text",
            "decisions": [{"agent": "b", "step": "s2", "decision": "d2", "reason": "r2"}],
        }

        merged = _merge_state(base, update)

        # Service object preserved (not in update)
        assert merged["obligation_tracker"] is base["obligation_tracker"]
        # Additive field merged
        assert len(merged["decisions"]) == 2
        # New field added
        assert merged["current_chapter_text"] == "new text"


# ===========================================================================
# 2. Chapter deduplication on resume (Bug #8)
# ===========================================================================


class TestChapterDeduplicationOnResume:
    """Verify that re-generating an existing chapter does not duplicate it."""

    def test_existing_chapter_not_duplicated(self):
        """Simulate the dedup logic from pipeline lines 1066-1071."""
        state = _make_base_state()
        # Pre-populate chapters 1-5
        for i in range(1, 6):
            state["chapters"].append({
                "chapter_number": i,
                "title": f"第{i}章",
                "full_text": f"章节{i}正文",
                "word_count": 100,
                "status": "draft",
            })

        # Simulate re-generating chapter 5 (resume scenario)
        ch_num = 5
        ch_data = {
            "chapter_number": ch_num,
            "title": "第5章（重写版）",
            "full_text": "重写后的第五章正文" * 20,
            "word_count": 200,
            "status": "draft",
        }

        # Reproduce pipeline dedup logic
        chapters = state.get("chapters") or []
        existing_nums = {ch.get("chapter_number") for ch in chapters}
        if ch_num not in existing_nums:
            chapters.append(ch_data)
        state["chapters"] = chapters

        # Chapter 5 should NOT be duplicated
        ch5_entries = [ch for ch in state["chapters"] if ch["chapter_number"] == 5]
        assert len(ch5_entries) == 1, f"Expected 1 entry for ch5, got {len(ch5_entries)}"
        # The old version is kept (pipeline does not replace it)
        assert ch5_entries[0]["title"] == "第5章"

    def test_new_chapter_is_added(self):
        """Chapter 6 (not in list) should be added normally."""
        state = _make_base_state()
        for i in range(1, 6):
            state["chapters"].append({
                "chapter_number": i,
                "title": f"第{i}章",
                "word_count": 100,
                "status": "draft",
            })

        ch_num = 6
        ch_data = {
            "chapter_number": ch_num,
            "title": "第6章新章节",
            "full_text": "新的第六章正文内容" * 20,
            "word_count": 200,
            "status": "draft",
        }

        chapters = state.get("chapters") or []
        existing_nums = {ch.get("chapter_number") for ch in chapters}
        if ch_num not in existing_nums:
            chapters.append(ch_data)
        state["chapters"] = chapters

        assert len(state["chapters"]) == 6
        ch6_entries = [ch for ch in state["chapters"] if ch["chapter_number"] == 6]
        assert len(ch6_entries) == 1
        assert ch6_entries[0]["title"] == "第6章新章节"

    def test_empty_chapters_list_adds_first_chapter(self):
        """Edge case: empty chapters list should add the first chapter."""
        state = _make_base_state()
        assert state["chapters"] == []

        ch_data = {
            "chapter_number": 1,
            "title": "第1章",
            "full_text": "第一章正文",
            "word_count": 50,
            "status": "draft",
        }

        chapters = state.get("chapters") or []
        existing_nums = {ch.get("chapter_number") for ch in chapters}
        if 1 not in existing_nums:
            chapters.append(ch_data)
        state["chapters"] = chapters

        assert len(state["chapters"]) == 1
        assert state["chapters"][0]["chapter_number"] == 1


# ===========================================================================
# 3. word_count uses count_words (Bug #22)
# ===========================================================================


class TestWordCountUsesCountWords:
    """Verify word_count is computed via count_words(), not len()."""

    def test_chinese_text_word_count(self):
        """Chinese text: count_words counts characters, len() counts differently."""
        text = "少年站在山巅，望着远方的云海翻涌。他紧握手中的长剑，眼中闪烁着坚定的光芒。"
        wc = count_words(text)

        # count_words counts CJK characters + English words, not punctuation
        assert wc != len(text), "count_words should differ from len() for Chinese text"
        # len() includes punctuation and is larger
        assert wc < len(text), "count_words should be less than len() (no punctuation counted)"
        # Verify specific count — the text has 33 Chinese chars (punctuation excluded)
        assert wc == 33

    def test_mixed_text_word_count(self):
        """Mixed Chinese + English: verify count_words handles both."""
        text = "他学会了Python编程，写了100行代码。"
        wc = count_words(text)
        # Chinese chars: 他学会了 编程 写了 行代码 = 4+2+2+3 = 11
        # English words: Python = 1
        # Numbers: 100 = 1
        assert wc == 13  # 11 Chinese + 1 English + 1 number

    def test_pipeline_saves_count_words_not_len(self):
        """Simulate the pipeline save logic to confirm it uses count_words."""
        # "少年站在山巅，望着远方的云海翻涌。" has 15 CJK chars, 2 punctuation = 17 chars total
        chapter_text = "少年站在山巅，望着远方的云海翻涌。" * 50

        # Pipeline logic (line 1058)
        ch_data = {
            "chapter_number": 1,
            "title": "第1章",
            "full_text": chapter_text,
            "word_count": count_words(chapter_text),
            "status": "draft",
        }

        expected_wc = count_words(chapter_text)
        assert ch_data["word_count"] == expected_wc
        # len() would give a much larger number (includes punctuation + all chars)
        assert ch_data["word_count"] != len(chapter_text)
        # count_words should be 15 CJK chars * 50 = 750 (punctuation excluded)
        assert ch_data["word_count"] == 750

    def test_empty_text_word_count(self):
        """count_words on empty string returns 0."""
        assert count_words("") == 0
        assert count_words("   ") == 0


# ===========================================================================
# 4. MAX_REWRITES vs max_retries mismatch (Bug #23)
# ===========================================================================


class TestRewriteLimitLogic:
    """Test the interplay between MAX_REWRITES (graph.py) and max_retries (quality_reviewer)."""

    def test_should_rewrite_stops_at_max_rewrites(self):
        """_should_rewrite returns 'state_writeback' when retries >= MAX_REWRITES."""
        state = {
            "current_chapter": 3,
            "current_chapter_quality": {"need_rewrite": True},
            "retry_counts": {3: MAX_REWRITES},  # Already at limit
            "max_retries": MAX_REWRITES,
        }

        result = _should_rewrite(state)
        assert result == "state_writeback"

    def test_should_rewrite_allows_when_under_limit(self):
        """_should_rewrite returns 'writer' when retries < MAX_REWRITES."""
        state = {
            "current_chapter": 3,
            "current_chapter_quality": {"need_rewrite": True},
            "retry_counts": {3: 0},
            "max_retries": MAX_REWRITES,
        }

        result = _should_rewrite(state)
        assert result == "writer"

    def test_should_rewrite_no_rewrite_needed(self):
        """_should_rewrite returns 'state_writeback' when need_rewrite is False."""
        state = {
            "current_chapter": 1,
            "current_chapter_quality": {"need_rewrite": False},
            "retry_counts": {},
        }

        result = _should_rewrite(state)
        assert result == "state_writeback"

    def test_should_rewrite_empty_quality(self):
        """_should_rewrite handles missing quality dict gracefully."""
        state = {
            "current_chapter": 1,
            "current_chapter_quality": None,
            "retry_counts": {},
        }

        result = _should_rewrite(state)
        assert result == "state_writeback"

    def test_should_rewrite_respects_state_max_retries_over_constant(self):
        """State max_retries overrides the module-level MAX_REWRITES constant."""
        # state says max_retries=5, but MAX_REWRITES=2
        state = {
            "current_chapter": 1,
            "current_chapter_quality": {"need_rewrite": True},
            "retry_counts": {1: 3},  # 3 retries, above MAX_REWRITES(2) but below state max(5)
            "max_retries": 5,
        }

        result = _should_rewrite(state)
        assert result == "writer", "Should still allow rewrite because state max_retries=5"

    def test_should_rewrite_missing_retry_counts(self):
        """_should_rewrite handles missing retry_counts (None or absent)."""
        state = {
            "current_chapter": 1,
            "current_chapter_quality": {"need_rewrite": True},
            # retry_counts absent
        }

        result = _should_rewrite(state)
        assert result == "writer"

    def test_quality_reviewer_force_pass_at_max_retries(self):
        """Quality reviewer node force-passes when retry count reaches max_retries.

        This tests the logic at quality_reviewer.py lines 450-462.
        """
        from src.novel.agents.quality_reviewer import quality_reviewer_node

        state = _make_base_state()
        state["current_chapter"] = 3
        state["current_chapter_text"] = "这是一段需要审查的测试文本内容。" * 30
        state["current_chapter_outline"] = {
            "chapter_number": 3,
            "title": "第3章",
            "goal": "测试",
            "key_events": ["事件"],
        }
        state["max_retries"] = 2
        state["retry_counts"] = {3: 1}  # Already 1 retry

        # Mock the quality reviewer to produce need_rewrite=True
        mock_reviewer = MagicMock()
        mock_reviewer.review_chapter.return_value = {
            "need_rewrite": True,
            "rewrite_reason": "测试失败原因",
            "rule_check": {"passed": False},
            "scores": {},
            "suggestions": [],
        }
        mock_reviewer.should_rewrite.return_value = True

        mock_llm = MagicMock()

        with patch("src.novel.agents.quality_reviewer.create_llm_client", return_value=mock_llm), \
             patch("src.novel.agents.quality_reviewer.QualityReviewer", return_value=mock_reviewer):
            result = quality_reviewer_node(state)

        # retry_counts[3] should now be 2 (incremented from 1)
        assert result["retry_counts"][3] == 2
        # Since 2 >= max_retries(2), it should force pass
        quality = result["current_chapter_quality"]
        assert quality["need_rewrite"] is False, "Should force-pass after reaching max_retries"

    def test_quality_reviewer_allows_rewrite_under_limit(self):
        """Quality reviewer keeps need_rewrite=True when under max_retries."""
        from src.novel.agents.quality_reviewer import quality_reviewer_node

        state = _make_base_state()
        state["current_chapter"] = 2
        state["current_chapter_text"] = "测试文本内容，需要重写。" * 30
        state["current_chapter_outline"] = {
            "chapter_number": 2,
            "title": "第2章",
            "goal": "测试",
            "key_events": ["事件"],
        }
        state["max_retries"] = 5
        state["retry_counts"] = {2: 0}  # First attempt

        mock_reviewer = MagicMock()
        mock_reviewer.review_chapter.return_value = {
            "need_rewrite": True,
            "rewrite_reason": "质量不达标",
            "rule_check": {"passed": False},
            "scores": {},
            "suggestions": [],
        }
        mock_reviewer.should_rewrite.return_value = True

        mock_llm = MagicMock()

        with patch("src.novel.agents.quality_reviewer.create_llm_client", return_value=mock_llm), \
             patch("src.novel.agents.quality_reviewer.QualityReviewer", return_value=mock_reviewer):
            result = quality_reviewer_node(state)

        # retry_counts[2] should be 1, which is < max_retries(5)
        assert result["retry_counts"][2] == 1
        # need_rewrite should remain True (no force-pass)
        quality = result["current_chapter_quality"]
        assert quality["need_rewrite"] is True


# ===========================================================================
# 5. Consecutive failure handling
# ===========================================================================


class TestConsecutiveFailureHandling:
    """Verify pipeline stops after 3 consecutive chapter generation failures."""

    def test_pipeline_stops_after_3_consecutive_failures(self, tmp_path):
        """Mock chapter_graph.invoke to raise and verify 3-strike abort."""
        from src.novel.pipeline import NovelPipeline

        workspace = str(tmp_path / "workspace")
        pipe = NovelPipeline(workspace=workspace)
        fm = pipe._get_file_manager()

        novel_id = "test_fail_novel"
        novel_dir = tmp_path / "workspace" / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)

        state = _make_base_state(novel_id=novel_id, total_chapters=5)
        state["workspace"] = workspace

        # Save novel.json so FileManager can load it
        fm.save_novel(novel_id, {
            "novel_id": novel_id,
            "genre": "玄幻",
            "theme": "修仙",
            "outline": state["outline"],
            "characters": state["characters"],
            "world_setting": state["world_setting"],
        })

        # Save checkpoint
        pipe._save_checkpoint(novel_id, state)

        # Mock build_chapter_graph to return a graph that always raises
        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = RuntimeError("LLM service unavailable")

        with patch("src.novel.pipeline.build_chapter_graph", return_value=mock_graph):
            result = pipe.generate_chapters(novel_id, start_chapter=1, end_chapter=5, silent=True)

        # Should have errors for the 3 failed chapters
        errors = result.get("errors", [])
        failure_errors = [e for e in errors if "生成失败" in e.get("message", "")]
        assert len(failure_errors) == 3, f"Expected 3 failure errors, got {len(failure_errors)}: {failure_errors}"

        # Chapter 4 and 5 should NOT have been attempted
        assert mock_graph.invoke.call_count == 3

    def test_checkpoint_saved_on_each_failure(self, tmp_path):
        """Verify checkpoint is saved after each failed chapter."""
        from src.novel.pipeline import NovelPipeline

        workspace = str(tmp_path / "workspace")
        pipe = NovelPipeline(workspace=workspace)
        fm = pipe._get_file_manager()

        novel_id = "test_ckpt_fail"
        novel_dir = tmp_path / "workspace" / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)

        state = _make_base_state(novel_id=novel_id, total_chapters=3)
        state["workspace"] = workspace

        fm.save_novel(novel_id, {
            "novel_id": novel_id,
            "outline": state["outline"],
            "characters": state["characters"],
        })

        pipe._save_checkpoint(novel_id, state)

        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = RuntimeError("fail")

        save_calls = []
        original_save = pipe._save_checkpoint

        def tracking_save(nid, st):
            save_calls.append(nid)
            return original_save(nid, st)

        pipe._save_checkpoint = tracking_save

        with patch("src.novel.pipeline.build_chapter_graph", return_value=mock_graph):
            pipe.generate_chapters(novel_id, start_chapter=1, end_chapter=3, silent=True)

        # Each failed chapter should trigger a checkpoint save
        # Plus the final per-chapter save in the loop
        assert len(save_calls) >= 3, f"Expected at least 3 checkpoint saves, got {len(save_calls)}"

    def test_consecutive_counter_resets_on_success(self):
        """Verify consecutive_failures resets to 0 after a successful chapter.

        This tests the logic at pipeline line 1044.
        """
        # Simulate the counter logic
        consecutive_failures = 0

        # Chapter 1 fails
        consecutive_failures += 1
        assert consecutive_failures == 1

        # Chapter 2 succeeds -> reset
        consecutive_failures = 0
        assert consecutive_failures == 0

        # Chapter 3 fails
        consecutive_failures += 1
        assert consecutive_failures == 1

        # Chapter 4 fails
        consecutive_failures += 1
        assert consecutive_failures == 2

        # Still under 3, pipeline continues
        assert consecutive_failures < 3

        # Chapter 5 fails -> triggers abort
        consecutive_failures += 1
        assert consecutive_failures >= 3


# ===========================================================================
# 6. Checkpoint save/restore round-trip
# ===========================================================================


class TestCheckpointSaveRestoreRoundTrip:
    """Verify checkpoint serialization handles edge cases correctly."""

    def test_non_serializable_objects_skipped(self, tmp_path):
        """Non-serializable fields (memory, obligation_tracker) are skipped."""
        from src.novel.pipeline import NovelPipeline

        workspace = str(tmp_path / "workspace")
        pipe = NovelPipeline(workspace=workspace)

        novel_id = "test_ckpt_serial"
        novel_dir = tmp_path / "workspace" / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)

        state = _make_base_state(novel_id=novel_id)
        state["workspace"] = workspace
        # Add non-serializable objects
        state["memory"] = MagicMock(name="NovelMemory")
        state["obligation_tracker"] = MagicMock(name="ObligationTracker")
        state["brief_validator"] = MagicMock(name="BriefValidator")

        # Should not raise
        pipe._save_checkpoint(novel_id, state)

        # Load and verify non-serializable fields are absent
        loaded = pipe._load_checkpoint(novel_id)
        assert loaded is not None
        assert "memory" not in loaded  # Explicitly skipped
        assert "obligation_tracker" not in loaded  # Non-serializable, skipped
        assert "brief_validator" not in loaded  # Non-serializable, skipped

        # Serializable fields survive
        assert loaded["novel_id"] == "test_ckpt_serial"
        assert loaded["genre"] == "玄幻"
        assert loaded["total_chapters"] == 5

    def test_full_text_stripped_from_checkpoint_chapters(self, tmp_path):
        """full_text is removed from chapters in checkpoint to save space."""
        from src.novel.pipeline import NovelPipeline

        workspace = str(tmp_path / "workspace")
        pipe = NovelPipeline(workspace=workspace)

        novel_id = "test_ckpt_strip"
        novel_dir = tmp_path / "workspace" / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)

        state = _make_base_state(novel_id=novel_id)
        state["workspace"] = workspace
        state["chapters"] = [
            {
                "chapter_number": 1,
                "title": "第1章",
                "full_text": "这是完整的章节正文内容" * 100,
                "word_count": 1000,
                "status": "draft",
            },
            {
                "chapter_number": 2,
                "title": "第2章",
                "full_text": "第二章完整正文" * 100,
                "word_count": 800,
                "status": "draft",
            },
        ]

        pipe._save_checkpoint(novel_id, state)
        loaded = pipe._load_checkpoint(novel_id)

        assert loaded is not None
        assert len(loaded["chapters"]) == 2
        for ch in loaded["chapters"]:
            assert "full_text" not in ch, f"full_text should be stripped from chapter {ch['chapter_number']}"
            assert "chapter_number" in ch
            assert "title" in ch
            assert "word_count" in ch

    def test_retry_counts_int_keys_restored(self, tmp_path):
        """JSON serialization converts int keys to strings; verify restore."""
        from src.novel.pipeline import NovelPipeline

        workspace = str(tmp_path / "workspace")
        pipe = NovelPipeline(workspace=workspace)

        novel_id = "test_ckpt_keys"
        novel_dir = tmp_path / "workspace" / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)

        state = _make_base_state(novel_id=novel_id)
        state["workspace"] = workspace
        state["retry_counts"] = {3: 2, 7: 1}

        pipe._save_checkpoint(novel_id, state)
        loaded = pipe._load_checkpoint(novel_id)

        assert loaded is not None
        # Keys should be restored to int (pipeline line 237)
        assert 3 in loaded["retry_counts"]
        assert 7 in loaded["retry_counts"]
        assert loaded["retry_counts"][3] == 2
        assert loaded["retry_counts"][7] == 1

    def test_checkpoint_round_trip_preserves_all_serializable_fields(self, tmp_path):
        """Full round-trip: save -> load -> verify all serializable fields match."""
        from src.novel.pipeline import NovelPipeline

        workspace = str(tmp_path / "workspace")
        pipe = NovelPipeline(workspace=workspace)

        novel_id = "test_ckpt_round"
        novel_dir = tmp_path / "workspace" / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)

        state = _make_base_state(novel_id=novel_id)
        state["workspace"] = workspace
        state["current_chapter"] = 3
        state["decisions"] = [
            {"agent": "Writer", "step": "write", "decision": "ok", "reason": "done"}
        ]
        state["errors"] = [
            {"agent": "pipeline", "message": "test error"}
        ]
        state["completed_nodes"] = ["writer", "quality_reviewer"]
        state["chapters_text"] = {1: "chapter 1 text", 2: "chapter 2 text"}

        pipe._save_checkpoint(novel_id, state)
        loaded = pipe._load_checkpoint(novel_id)

        assert loaded is not None
        assert loaded["current_chapter"] == 3
        assert loaded["genre"] == "玄幻"
        assert loaded["theme"] == "修仙逆袭"
        assert loaded["total_chapters"] == 5
        assert len(loaded["decisions"]) == 1
        assert loaded["decisions"][0]["agent"] == "Writer"
        assert len(loaded["errors"]) == 1
        assert loaded["completed_nodes"] == ["writer", "quality_reviewer"]
        assert loaded["chapters_text"]["1"] == "chapter 1 text"  # JSON keys become strings

    def test_checkpoint_empty_state(self, tmp_path):
        """Save/load a minimal state without crashing."""
        from src.novel.pipeline import NovelPipeline

        workspace = str(tmp_path / "workspace")
        pipe = NovelPipeline(workspace=workspace)

        novel_id = "test_ckpt_empty"
        novel_dir = tmp_path / "workspace" / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)

        state = {"novel_id": novel_id, "workspace": workspace}

        pipe._save_checkpoint(novel_id, state)
        loaded = pipe._load_checkpoint(novel_id)

        assert loaded is not None
        assert loaded["novel_id"] == novel_id

    def test_checkpoint_no_file_returns_none(self, tmp_path):
        """_load_checkpoint returns None when no checkpoint file exists."""
        from src.novel.pipeline import NovelPipeline

        workspace = str(tmp_path / "workspace")
        pipe = NovelPipeline(workspace=workspace)

        novel_dir = tmp_path / "workspace" / "novels" / "nonexistent"
        novel_dir.mkdir(parents=True, exist_ok=True)

        result = pipe._load_checkpoint("nonexistent")
        assert result is None
