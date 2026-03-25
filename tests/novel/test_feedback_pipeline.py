"""Tests for the reader feedback pipeline: Writer.rewrite_chapter, feedback models,
FileManager revision/feedback methods, and NovelPipeline.apply_feedback.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.novel.conftest import FakeLLMResponse, make_llm_client, make_outline_dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chapter_outline_obj(**overrides):
    """Create a ChapterOutline model instance for tests."""
    from src.novel.models.novel import ChapterOutline

    defaults = {
        "chapter_number": 1,
        "title": "测试章节",
        "goal": "推进情节",
        "key_events": ["事件A"],
        "involved_characters": [],
        "plot_threads": [],
        "estimated_words": 2000,
        "mood": "蓄力",
    }
    defaults.update(overrides)
    return ChapterOutline(**defaults)


def _make_character_profile(name: str = "主角"):
    """Create a CharacterProfile model instance for tests."""
    from src.novel.models.character import CharacterProfile

    return CharacterProfile(
        name=name,
        gender="男",
        age=18,
        occupation="修仙者",
        appearance={
            "height": "180cm",
            "build": "修长",
            "hair": "黑色短发",
            "eyes": "黑色",
            "clothing_style": "青色长袍",
            "distinctive_features": ["剑眉"],
        },
        personality={
            "traits": ["勇敢", "坚韧", "善良"],
            "speech_style": "简洁有力",
            "core_belief": "永不放弃",
            "motivation": "守护家人",
            "flaw": "冲动",
            "catchphrases": [],
        },
    )


def _make_world_setting():
    """Create a WorldSetting model instance for tests."""
    from src.novel.models.world import WorldSetting

    return WorldSetting(era="上古时代", location="九州大陆")


# =========================================================================
# Writer.rewrite_chapter() tests
# =========================================================================


class TestWriterRewriteChapter:
    """Tests for Writer.rewrite_chapter()."""

    def test_rewrite_direct_mode(self):
        """Direct rewrite (is_propagation=False) calls LLM and returns text."""
        from src.novel.agents.writer import Writer

        rewritten_text = "重写后的章节内容，主角变得更加果敢。" * 20
        llm = make_llm_client(response_text=rewritten_text)
        writer = Writer(llm)

        result = writer.rewrite_chapter(
            original_text="原始章节文本" * 30,
            rewrite_instruction="加强主角性格",
            chapter_outline=_make_chapter_outline_obj(),
            characters=[_make_character_profile()],
            world_setting=_make_world_setting(),
            context="前文摘要",
            style_name="webnovel.shuangwen",
            is_propagation=False,
        )

        assert len(result) > 0
        assert "重写后的章节内容" in result
        llm.chat.assert_called_once()
        # Check that direct mode prompt contains feedback reference
        call_args = llm.chat.call_args
        messages = call_args[1].get("messages") or call_args[0][0]
        system_msg = messages[0]["content"]
        assert "读者反馈" in system_msg or "重写" in system_msg

    def test_rewrite_propagation_mode(self):
        """Propagation rewrite (is_propagation=True) uses lighter prompt."""
        from src.novel.agents.writer import Writer

        rewritten_text = "微调后的章节内容，保持连贯。" * 20
        llm = make_llm_client(response_text=rewritten_text)
        writer = Writer(llm)

        result = writer.rewrite_chapter(
            original_text="原始章节文本" * 30,
            rewrite_instruction="前章角色性格已调整，保持一致",
            chapter_outline=_make_chapter_outline_obj(),
            characters=[_make_character_profile()],
            world_setting=_make_world_setting(),
            context="前文摘要",
            style_name="webnovel.shuangwen",
            is_propagation=True,
        )

        assert len(result) > 0
        assert "微调后的章节内容" in result
        llm.chat.assert_called_once()
        # Propagation mode prompt should mention minimal changes
        call_args = llm.chat.call_args
        messages = call_args[1].get("messages") or call_args[0][0]
        system_msg = messages[0]["content"]
        assert "微调" in system_msg or "最小修改" in system_msg

    def test_rewrite_no_truncation(self):
        """Long text is preserved without truncation (only logged as warning)."""
        from src.novel.agents.writer import Writer

        long_text = "这是一段非常长的文本。" * 500  # ~5000 chars
        llm = make_llm_client(response_text=long_text)
        writer = Writer(llm)

        result = writer.rewrite_chapter(
            original_text="原文" * 100,
            rewrite_instruction="重写",
            chapter_outline=_make_chapter_outline_obj(estimated_words=2000),
            characters=[],
            world_setting=_make_world_setting(),
            context="",
            style_name="webnovel.shuangwen",
            is_propagation=False,
        )

        # No truncation — full text preserved
        assert len(result) == len(long_text)

    def test_rewrite_empty_context(self):
        """Rewrite works fine with empty context string."""
        from src.novel.agents.writer import Writer

        llm = make_llm_client(response_text="正常输出")
        writer = Writer(llm)

        result = writer.rewrite_chapter(
            original_text="原文内容",
            rewrite_instruction="修改",
            chapter_outline=_make_chapter_outline_obj(),
            characters=[],
            world_setting=_make_world_setting(),
            context="",
            style_name="webnovel.shuangwen",
            is_propagation=False,
        )

        assert result == "正常输出"


# =========================================================================
# Feedback model tests
# =========================================================================


class TestFeedbackModels:
    """Tests for FeedbackEntry and FeedbackAnalysis pydantic models."""

    def test_feedback_entry_creation(self):
        """FeedbackEntry can be created with required fields."""
        from src.novel.models.feedback import FeedbackEntry

        entry = FeedbackEntry(content="主角太弱了", chapter_number=3)

        assert entry.content == "主角太弱了"
        assert entry.chapter_number == 3
        assert entry.status == "pending"
        assert entry.feedback_type is None
        assert len(entry.feedback_id) == 8

    def test_feedback_entry_global(self):
        """FeedbackEntry with chapter_number=None is global feedback."""
        from src.novel.models.feedback import FeedbackEntry

        entry = FeedbackEntry(content="节奏太慢")

        assert entry.chapter_number is None
        assert entry.status == "pending"

    def test_feedback_entry_validation(self):
        """FeedbackEntry rejects empty content."""
        from src.novel.models.feedback import FeedbackEntry

        with pytest.raises(Exception):  # pydantic ValidationError
            FeedbackEntry(content="")

    def test_feedback_analysis_creation(self):
        """FeedbackAnalysis can be created with all fields."""
        from src.novel.models.feedback import FeedbackAnalysis, FeedbackType

        analysis = FeedbackAnalysis(
            feedback_id="abc12345",
            feedback_type=FeedbackType.CHARACTER,
            severity="high",
            target_chapters=[1, 2],
            propagation_chapters=[3, 4],
            rewrite_instructions={1: "加强主角", 2: "补充细节"},
            summary="角色需要加强",
        )

        assert analysis.feedback_type == FeedbackType.CHARACTER
        assert analysis.severity == "high"
        assert analysis.target_chapters == [1, 2]
        assert analysis.propagation_chapters == [3, 4]
        assert 1 in analysis.rewrite_instructions
        assert analysis.summary == "角色需要加强"
        assert analysis.character_changes is None

    def test_feedback_analysis_defaults(self):
        """FeedbackAnalysis uses defaults for optional fields."""
        from src.novel.models.feedback import FeedbackAnalysis, FeedbackType

        analysis = FeedbackAnalysis(
            feedback_id="xyz",
            feedback_type=FeedbackType.PACING,
        )

        assert analysis.severity == "medium"
        assert analysis.target_chapters == []
        assert analysis.propagation_chapters == []
        assert analysis.rewrite_instructions == {}
        assert analysis.summary == ""


# =========================================================================
# FileManager revision & feedback tests
# =========================================================================


class TestFileManagerRevisions:
    """Tests for FileManager revision and feedback methods."""

    def test_save_and_load_chapter_revision(self, tmp_path):
        """save_chapter_revision saves text and load_chapter_revision reads it back."""
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(tmp_path))
        novel_id = "test_novel"

        path = fm.save_chapter_revision(novel_id, 1, "第一版文本")

        assert path.exists()
        assert "rev1" in path.name

        loaded = fm.load_chapter_revision(novel_id, 1, 1)
        assert loaded == "第一版文本"

    def test_save_multiple_revisions_auto_increment(self, tmp_path):
        """Multiple revisions auto-increment version numbers."""
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(tmp_path))
        novel_id = "test_novel"

        fm.save_chapter_revision(novel_id, 1, "版本1")
        fm.save_chapter_revision(novel_id, 1, "版本2")
        p3 = fm.save_chapter_revision(novel_id, 1, "版本3")

        assert "rev3" in p3.name
        assert fm.load_chapter_revision(novel_id, 1, 3) == "版本3"
        assert fm.load_chapter_revision(novel_id, 1, 1) == "版本1"

    def test_save_revision_with_metadata(self, tmp_path):
        """save_chapter_revision saves metadata JSON alongside text."""
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(tmp_path))
        novel_id = "test_novel"
        meta = {"reason": "reader feedback", "feedback_id": "abc"}

        path = fm.save_chapter_revision(novel_id, 1, "内容", metadata=meta)

        meta_path = path.with_suffix(".json")
        assert meta_path.exists()
        with open(meta_path) as f:
            saved_meta = json.load(f)
        assert saved_meta["reason"] == "reader feedback"
        assert saved_meta["feedback_id"] == "abc"

    def test_load_nonexistent_revision_returns_none(self, tmp_path):
        """load_chapter_revision returns None for missing revision."""
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(tmp_path))
        assert fm.load_chapter_revision("nope", 1, 99) is None

    def test_list_chapter_revisions(self, tmp_path):
        """list_chapter_revisions returns sorted version numbers."""
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(tmp_path))
        novel_id = "test_novel"

        fm.save_chapter_revision(novel_id, 2, "v1")
        fm.save_chapter_revision(novel_id, 2, "v2")
        fm.save_chapter_revision(novel_id, 2, "v3")

        revs = fm.list_chapter_revisions(novel_id, 2)
        assert revs == [1, 2, 3]

    def test_list_chapter_revisions_empty(self, tmp_path):
        """list_chapter_revisions returns empty list when no revisions exist."""
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(tmp_path))
        revs = fm.list_chapter_revisions("nope", 1)
        assert revs == []

    def test_save_and_list_feedback(self, tmp_path):
        """save_feedback persists and list_feedback reads back."""
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(tmp_path))
        novel_id = "test_novel"

        fb1 = {"feedback_id": "fb001", "content": "太慢了", "status": "pending"}
        fb2 = {"feedback_id": "fb002", "content": "角色扁平", "status": "pending"}

        fm.save_feedback(novel_id, fb1)
        fm.save_feedback(novel_id, fb2)

        all_fb = fm.list_feedback(novel_id)
        assert len(all_fb) == 2
        ids = {fb["feedback_id"] for fb in all_fb}
        assert ids == {"fb001", "fb002"}

    def test_list_feedback_empty(self, tmp_path):
        """list_feedback returns empty list when no feedback exists."""
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(tmp_path))
        assert fm.list_feedback("nope") == []


# =========================================================================
# NovelPipeline.apply_feedback() tests
# =========================================================================


class TestApplyFeedback:
    """Tests for NovelPipeline.apply_feedback()."""

    def _setup_project(self, tmp_path, num_chapters=3):
        """Set up a fake project with checkpoint and chapter files.

        Returns (pipeline, novel_id, project_path).
        """
        from src.novel.config import NovelConfig
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        workspace = str(tmp_path)
        novel_id = "novel_test1234"
        project_path = str(tmp_path / "novels" / novel_id)

        # Create config with defaults
        config = NovelConfig()
        pipeline = NovelPipeline(config=config, workspace=workspace)

        # Create checkpoint
        outline_chapters = make_outline_dict(total_chapters=num_chapters)["chapters"]
        state = {
            "config": {"llm": {"provider": "fake"}},
            "outline": {"chapters": outline_chapters},
            "characters": [
                {
                    "name": "主角",
                    "gender": "男",
                    "age": 18,
                    "occupation": "修仙者",
                    "appearance": {
                        "height": "180cm",
                        "build": "修长",
                        "hair": "黑发",
                        "eyes": "黑色",
                        "clothing_style": "青衣",
                        "distinctive_features": ["剑眉"],
                    },
                    "personality": {
                        "traits": ["勇敢", "坚韧", "善良"],
                        "speech_style": "简洁",
                        "core_belief": "正义",
                        "motivation": "变强",
                        "flaw": "冲动",
                        "catchphrases": [],
                    },
                }
            ],
            "world_setting": {"era": "上古", "location": "九州"},
            "style_name": "webnovel.shuangwen",
            "chapters": [],
        }
        pipeline._save_checkpoint(novel_id, state)

        # Save chapter texts
        fm = FileManager(workspace)
        for i in range(1, num_chapters + 1):
            fm.save_chapter_text(novel_id, i, f"第{i}章原始内容。" * 50)

        return pipeline, novel_id, project_path

    def test_apply_feedback_dry_run(self, tmp_path):
        """dry_run=True returns analysis but does not rewrite."""
        pipeline, novel_id, project_path = self._setup_project(tmp_path)

        analysis_json = {
            "feedback_type": "pacing",
            "severity": "medium",
            "target_chapters": [1],
            "propagation_chapters": [2],
            "rewrite_instructions": {"1": "加快节奏", "2": "微调"},
            "character_changes": None,
            "summary": "节奏问题",
        }
        mock_llm = make_llm_client(response_json=analysis_json)

        with patch(
            "src.llm.llm_client.create_llm_client",
            return_value=mock_llm,
        ):
            result = pipeline.apply_feedback(
                project_path=project_path,
                feedback_text="太慢了",
                chapter_number=1,
                dry_run=True,
            )

        assert result["dry_run"] is True
        assert result["analysis"]["feedback_type"] == "pacing"
        assert result["rewritten_chapters"] == []

    def test_apply_feedback_full_rewrite(self, tmp_path):
        """Full rewrite mode rewrites target + propagation chapters."""
        pipeline, novel_id, project_path = self._setup_project(tmp_path)
        fm = pipeline._get_file_manager()

        analysis_json = {
            "feedback_type": "character",
            "severity": "high",
            "target_chapters": [1],
            "propagation_chapters": [2],
            "rewrite_instructions": {"1": "加强角色", "2": "保持一致"},
            "character_changes": None,
            "summary": "角色改进",
        }

        # analyze now calls LLM twice (diagnose + plan), then rewrite calls
        mock_llm = MagicMock()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # Diagnose + plan calls both get analysis JSON
                return FakeLLMResponse(
                    content=json.dumps(analysis_json, ensure_ascii=False)
                )
            else:
                # Rewrite calls
                return FakeLLMResponse(content="重写后的新内容。" * 30)

        mock_llm.chat.side_effect = side_effect

        with patch(
            "src.llm.llm_client.create_llm_client",
            return_value=mock_llm,
        ):
            result = pipeline.apply_feedback(
                project_path=project_path,
                feedback_text="主角不够鲜明",
                chapter_number=1,
                dry_run=False,
            )

        assert result["dry_run"] is False
        assert len(result["rewritten_chapters"]) == 2

        # Verify chapters were rewritten
        ch1_rewritten = result["rewritten_chapters"][0]
        assert ch1_rewritten["chapter_number"] == 1
        assert ch1_rewritten["is_propagation"] is False
        assert ch1_rewritten["new_chars"] > 0

        ch2_rewritten = result["rewritten_chapters"][1]
        assert ch2_rewritten["chapter_number"] == 2
        assert ch2_rewritten["is_propagation"] is True

        # Verify revision backup was saved
        revisions = fm.list_chapter_revisions(novel_id, 1)
        assert len(revisions) >= 1

        # Verify new text was saved to file
        new_text = fm.load_chapter_text(novel_id, 1)
        assert "重写后的新内容" in new_text

    def test_apply_feedback_missing_chapter_text_skipped(self, tmp_path):
        """Chapters with no original text are skipped during rewrite."""
        pipeline, novel_id, project_path = self._setup_project(
            tmp_path, num_chapters=3
        )
        fm = pipeline._get_file_manager()

        # Delete chapter 2's text file to simulate missing chapter
        ch2_path = (
            Path(tmp_path) / "novels" / novel_id / "chapters" / "chapter_002.txt"
        )
        if ch2_path.exists():
            ch2_path.unlink()

        analysis_json = {
            "feedback_type": "plot_hole",
            "severity": "high",
            "target_chapters": [1, 2],
            "propagation_chapters": [],
            "rewrite_instructions": {"1": "修复漏洞", "2": "同步修复"},
            "character_changes": None,
            "summary": "情节漏洞",
        }

        # analyze now calls LLM twice (diagnose + plan)
        mock_llm = MagicMock()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return FakeLLMResponse(
                    content=json.dumps(analysis_json, ensure_ascii=False)
                )
            else:
                return FakeLLMResponse(content="修复后内容。" * 30)

        mock_llm.chat.side_effect = side_effect

        with patch(
            "src.llm.llm_client.create_llm_client",
            return_value=mock_llm,
        ):
            result = pipeline.apply_feedback(
                project_path=project_path,
                feedback_text="情节矛盾",
                chapter_number=1,
                dry_run=False,
            )

        rewritten_nums = [ch["chapter_number"] for ch in result["rewritten_chapters"]]
        assert 1 in rewritten_nums
        assert 2 not in rewritten_nums  # chapter 2 was skipped

    def test_apply_feedback_missing_checkpoint(self, tmp_path):
        """apply_feedback raises FileNotFoundError with no checkpoint."""
        from src.novel.config import NovelConfig
        from src.novel.pipeline import NovelPipeline

        pipeline = NovelPipeline(
            config=NovelConfig(), workspace=str(tmp_path)
        )

        with pytest.raises(FileNotFoundError, match="找不到项目检查点"):
            pipeline.apply_feedback(
                project_path=str(tmp_path / "novels" / "nonexistent"),
                feedback_text="test",
            )
