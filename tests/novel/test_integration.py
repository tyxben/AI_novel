"""Integration tests for the novel writing pipeline.

Tests full end-to-end flows with mocked LLM calls:
1. Full pipeline smoke test (create -> generate -> export)
2. Multi-chapter consistency (state accumulation)
3. Resume from checkpoint
4. Quality rewrite loop
5. Error resilience
6. Large novel simulation (25 chapters)

All LLM / external calls are mocked. Uses sequential fallback runner.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.novel.config import NovelConfig
from src.novel.pipeline import NovelPipeline

# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------

_NODES_PATCH_TARGET = "src.novel.agents.graph._get_node_functions"
_LANGGRAPH_PATCH = "src.novel.agents.graph._LANGGRAPH_AVAILABLE"

# ---------------------------------------------------------------------------
# Helpers: create mock data
# ---------------------------------------------------------------------------


def _make_outline_dict(total_chapters: int = 5) -> dict:
    """Create a minimal outline dict."""
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
                "key_events": [f"事件{i}a", f"事件{i}b"],
                "estimated_words": 3000,
                "mood": "蓄力" if i % 2 == 0 else "爆发",
            }
            for i in range(1, total_chapters + 1)
        ],
    }


def _make_world_setting_dict() -> dict:
    return {
        "era": "上古时代",
        "location": "九州大陆",
        "rules": ["灵气复苏", "万族争锋"],
        "terms": {"灵气": "天地间的能量"},
        "power_system": "炼气、筑基、金丹、元婴",
    }


def _make_character_dict(name: str = "主角") -> dict:
    return {
        "name": name,
        "gender": "男",
        "age": 18,
        "occupation": "修仙者",
        "role": "主角",
        "personality": {
            "traits": ["勇敢", "坚韧", "善良"],
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


# ---------------------------------------------------------------------------
# Mock node functions
# ---------------------------------------------------------------------------

# Unique per-chapter text templates so we can verify distinct content.
_CHAPTER_TEXTS = {}


def _build_chapter_text(ch: int, variation: str = "") -> str:
    """Deterministic but unique chapter text based on chapter number."""
    base = (
        f"第{ch}章正文。{variation}"
        f"云逸踏入了第{ch}层秘境。灵气如潮水般涌来，"
        f"他运转功法，丹田中的灵力缓缓壮大。"
        f"「这就是{ch}级秘境的力量吗？」他喃喃自语。"
    )
    # Pad to ~200 chars per chapter for word count tests
    return base * 5


def _mock_novel_director_node(state: dict) -> dict:
    total = state.get("_mock_total_chapters", 5)
    return {
        "outline": _make_outline_dict(total),
        "total_chapters": total,
        "current_chapter": 0,
        "should_continue": True,
        "style_name": "webnovel.shuangwen",
        "template": "cyclic_upgrade",
        "decisions": [
            {"agent": "NovelDirector", "step": "init", "decision": "创建大纲", "reason": "integration test"}
        ],
        "errors": [],
        "completed_nodes": ["novel_director"],
    }


def _mock_world_builder_node(state: dict) -> dict:
    return {
        "world_setting": _make_world_setting_dict(),
        "decisions": [
            {"agent": "WorldBuilder", "step": "init", "decision": "构建世界", "reason": "integration test"}
        ],
        "errors": [],
        "completed_nodes": ["world_builder"],
    }


def _mock_character_designer_node(state: dict) -> dict:
    return {
        "characters": [_make_character_dict("主角"), _make_character_dict("反派")],
        "decisions": [
            {"agent": "CharacterDesigner", "step": "init", "decision": "设计角色", "reason": "integration test"}
        ],
        "errors": [],
        "completed_nodes": ["character_designer"],
    }


def _mock_chapter_planner_node(state: dict) -> dict:
    ch = state.get("current_chapter", 1)
    return {
        "current_scenes": [
            {"scene_number": 1, "target_words": 800, "summary": f"第{ch}章场景1"},
            {"scene_number": 2, "target_words": 800, "summary": f"第{ch}章场景2"},
            {"scene_number": 3, "target_words": 800, "summary": f"第{ch}章场景3"},
        ],
        "decisions": [
            {"agent": "ChapterPlanner", "step": f"ch{ch}", "decision": "规划场景", "reason": "integration test"}
        ],
        "errors": [],
        "completed_nodes": ["chapter_planner"],
    }


def _mock_writer_node(state: dict) -> dict:
    ch = state.get("current_chapter", 1)
    text = _build_chapter_text(ch)
    return {
        "current_chapter_text": text,
        "decisions": [
            {"agent": "Writer", "step": f"ch{ch}", "decision": "写作完成", "reason": "integration test"}
        ],
        "errors": [],
        "completed_nodes": ["writer"],
    }


def _mock_reviewer_pass(state: dict) -> dict:
    """Merged Reviewer mock (Phase 2-β) — subsumes old trio."""
    return {
        "current_chapter_quality": {
            "need_rewrite": False,
            "rule_check": {"passed": True},
            "strengths": [],
            "issues": [],
            "style_overuse_hits": [],
            "consistency_flags": [],
        },
        "decisions": [
            {"agent": "Reviewer", "step": "review", "decision": "审稿通过", "reason": "integration test"}
        ],
        "errors": [],
        "completed_nodes": ["reviewer"],
    }


def _get_mock_nodes(quality_pass: bool = True) -> dict:
    return {
        "novel_director": _mock_novel_director_node,
        "world_builder": _mock_world_builder_node,
        "character_designer": _mock_character_designer_node,
        "chapter_planner": _mock_chapter_planner_node,
        "writer": _mock_writer_node,
        "reviewer": _mock_reviewer_pass,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> str:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return str(ws)


@pytest.fixture
def pipeline(tmp_workspace: str) -> NovelPipeline:
    config = NovelConfig()
    return NovelPipeline(config=config, workspace=tmp_workspace)


# ---------------------------------------------------------------------------
# Helpers for running with mocked nodes
# ---------------------------------------------------------------------------


def _patch_nodes(nodes=None):
    """Context-manager combo that patches nodes and disables LangGraph."""
    if nodes is None:
        nodes = _get_mock_nodes()
    return patch(_NODES_PATCH_TARGET, return_value=nodes)


def _patch_langgraph():
    return patch(_LANGGRAPH_PATCH, False)


# ---------------------------------------------------------------------------
# 1. Full pipeline smoke test
# ---------------------------------------------------------------------------


class TestFullPipelineSmokeTest:
    """End-to-end: create_novel -> generate all chapters -> export -> verify."""

    def test_create_generate_export(self, pipeline: NovelPipeline, tmp_workspace: str, tmp_path: Path):
        with _patch_nodes(), _patch_langgraph():
            # Step 1: create novel
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙逆袭",
                target_words=15000,
            )

            assert "novel_id" in result
            novel_id = result["novel_id"]
            project_path = result["workspace"]
            assert result["outline"] is not None
            assert len(result["outline"]["chapters"]) == 5
            assert len(result["characters"]) == 2
            assert result["world_setting"] is not None
            assert result["world_setting"]["era"] == "上古时代"

            # Checkpoint should exist
            ckpt_path = Path(project_path) / "checkpoint.json"
            assert ckpt_path.exists()

            # Step 2: generate all chapters
            gen_result = pipeline.generate_chapters(project_path, silent=True)

            assert gen_result["total_generated"] == 5
            assert gen_result["chapters_generated"] == [1, 2, 3, 4, 5]
            assert len(gen_result["errors"]) == 0

            # Verify chapter files exist
            chapters_dir = Path(tmp_workspace) / "novels" / novel_id / "chapters"
            for ch_num in range(1, 6):
                json_file = chapters_dir / f"chapter_{ch_num:03d}.json"
                txt_file = chapters_dir / f"chapter_{ch_num:03d}.txt"
                assert json_file.exists(), f"chapter_{ch_num:03d}.json missing"
                assert txt_file.exists(), f"chapter_{ch_num:03d}.txt missing"

                # Verify JSON content (metadata only, no full_text)
                ch_data = json.loads(json_file.read_text(encoding="utf-8"))
                assert ch_data["chapter_number"] == ch_num
                assert ch_data["word_count"] > 0
                assert "full_text" not in ch_data, "json should not contain full_text"

                # Verify text content in .txt file
                txt_content = txt_file.read_text(encoding="utf-8")
                assert len(txt_content) > 0

            # Step 3: export
            export_path = str(tmp_path / "exported_novel.txt")
            output = pipeline.export_novel(project_path, export_path)
            assert Path(output).exists()

            content = Path(output).read_text(encoding="utf-8")
            # Verify all chapters present in export
            for ch_num in range(1, 6):
                assert f"第{ch_num}章" in content
            # Verify novel title in export
            assert "玄幻" in content

    def test_outline_structure(self, pipeline: NovelPipeline, tmp_workspace: str):
        """Verify outline has correct nested structure after create."""
        with _patch_nodes(), _patch_langgraph():
            result = pipeline.create_novel(
                genre="都市",
                theme="重生逆袭",
                target_words=20000,
            )

            outline = result["outline"]
            assert "acts" in outline
            assert "volumes" in outline
            assert "chapters" in outline
            assert len(outline["acts"]) > 0
            assert outline["acts"][0]["start_chapter"] == 1

            for ch in outline["chapters"]:
                assert "chapter_number" in ch
                assert "title" in ch
                assert "goal" in ch
                assert "key_events" in ch
                assert isinstance(ch["key_events"], list)


# ---------------------------------------------------------------------------
# 2. Multi-chapter consistency
# ---------------------------------------------------------------------------


class TestMultiChapterConsistency:
    """Generate 5 chapters and verify state accumulates correctly."""

    def test_state_accumulation(self, pipeline: NovelPipeline, tmp_workspace: str):
        with _patch_nodes(), _patch_langgraph():
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙",
                target_words=15000,
            )
            project_path = result["workspace"]
            novel_id = result["novel_id"]

            gen_result = pipeline.generate_chapters(project_path, silent=True)
            assert gen_result["total_generated"] == 5

            # Load checkpoint and verify accumulated state
            ckpt = pipeline._load_checkpoint(novel_id)
            assert ckpt is not None

            # completed_nodes should have entries from init + all 5 chapters
            completed = ckpt["completed_nodes"]
            assert "novel_director" in completed
            assert "world_builder" in completed
            assert "character_designer" in completed
            # Each chapter adds: chapter_planner, writer, reviewer (Phase 2-δ merged)
            assert completed.count("writer") == 5
            assert completed.count("reviewer") == 5

            # chapters list should have 5 entries
            assert len(ckpt["chapters"]) == 5

            # decisions should accumulate from init + all chapters
            decisions = ckpt["decisions"]
            assert len(decisions) > 0
            agents_seen = {d["agent"] for d in decisions}
            assert "NovelDirector" in agents_seen
            assert "Writer" in agents_seen
            assert "Reviewer" in agents_seen

            # current_chapter should be 5 (the last one generated)
            assert ckpt["current_chapter"] == 5

    def test_each_chapter_has_distinct_content(self, pipeline: NovelPipeline, tmp_workspace: str):
        """Verify that chapters are not all identical."""
        with _patch_nodes(), _patch_langgraph():
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙",
                target_words=15000,
            )
            project_path = result["workspace"]
            novel_id = result["novel_id"]

            pipeline.generate_chapters(project_path, silent=True)

            # Load all chapter texts and verify they differ
            fm = pipeline._get_file_manager()
            texts = []
            for ch_num in range(1, 6):
                text = fm.load_chapter_text(novel_id, ch_num)
                assert text is not None
                texts.append(text)

            # Each chapter text should be unique (our mock includes ch number)
            unique_texts = set(texts)
            assert len(unique_texts) == 5, "All 5 chapters should have distinct content"

            # Verify chapter-specific markers
            for i, text in enumerate(texts, 1):
                assert f"第{i}章" in text
                assert f"第{i}层秘境" in text

    def test_word_count_accumulates(self, pipeline: NovelPipeline, tmp_workspace: str):
        """Verify total word count grows with each chapter."""
        with _patch_nodes(), _patch_langgraph():
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙",
                target_words=15000,
            )
            project_path = result["workspace"]

            pipeline.generate_chapters(project_path, silent=True)

            status = pipeline.get_status(project_path)
            assert status["total_words"] > 0
            # 5 chapters, each ~1000 chars from our mock
            assert status["total_words"] > 500


# ---------------------------------------------------------------------------
# 3. Resume from checkpoint
# ---------------------------------------------------------------------------


class TestResumeFromCheckpoint:
    """Generate partial, stop, resume, verify no duplicates."""

    def test_resume_continues_from_last(self, pipeline: NovelPipeline, tmp_workspace: str):
        with _patch_nodes(), _patch_langgraph():
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙",
                target_words=15000,
            )
            project_path = result["workspace"]
            novel_id = result["novel_id"]

            # Generate only chapters 1-2
            gen1 = pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=2, silent=True)
            assert gen1["total_generated"] == 2
            assert gen1["chapters_generated"] == [1, 2]

            # Verify only 2 chapter files
            fm = pipeline._get_file_manager()
            chapters_before = fm.list_chapters(novel_id)
            assert chapters_before == [1, 2]

            # Resume should pick up from chapter 3
            resume_result = pipeline.resume_novel(project_path)
            assert resume_result["total_generated"] == 3  # chapters 3, 4, 5
            assert resume_result["chapters_generated"] == [3, 4, 5]

            # Verify all 5 chapters now exist
            chapters_after = fm.list_chapters(novel_id)
            assert chapters_after == [1, 2, 3, 4, 5]

    def test_no_duplicate_chapters_on_resume(self, pipeline: NovelPipeline, tmp_workspace: str):
        """Resume should not re-generate already completed chapters."""
        with _patch_nodes(), _patch_langgraph():
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙",
                target_words=15000,
            )
            project_path = result["workspace"]
            novel_id = result["novel_id"]

            # Generate chapters 1-3
            pipeline.generate_chapters(project_path, start_chapter=1, end_chapter=3, silent=True)

            # Record text of chapter 1 before resume
            fm = pipeline._get_file_manager()
            ch1_text_before = fm.load_chapter_text(novel_id, 1)

            # Resume
            pipeline.resume_novel(project_path)

            # Chapter 1 text should be unchanged (not overwritten)
            ch1_text_after = fm.load_chapter_text(novel_id, 1)
            assert ch1_text_after == ch1_text_before

    def test_resume_all_complete_returns_zero(self, pipeline: NovelPipeline, tmp_workspace: str):
        """Resume when all chapters are done returns 0 generated."""
        with _patch_nodes(), _patch_langgraph():
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙",
                target_words=15000,
            )
            project_path = result["workspace"]

            # Generate all
            pipeline.generate_chapters(project_path, silent=True)

            # Resume should find nothing to do
            resume_result = pipeline.resume_novel(project_path)
            assert resume_result["total_generated"] == 0
            assert "已生成完成" in resume_result.get("message", "")


# ---------------------------------------------------------------------------
# 4. Quality reviewer — 零自动重写 (Phase 0 档 4)
# ---------------------------------------------------------------------------


class TestQualityReviewerSinglePass:
    """档 4 拔除了 graph 自动回边: reviewer 只产报告, writer 只跑一次."""

    def test_writer_called_once_regardless_of_quality(
        self, pipeline: NovelPipeline, tmp_workspace: str
    ):
        """即使 reviewer 标 need_rewrite=True, writer 也只调用一次, 不再回写."""
        writer_call_count = {"count": 0}

        def counting_writer(state: dict) -> dict:
            ch = state.get("current_chapter", 1)
            writer_call_count["count"] += 1
            attempt = writer_call_count["count"]
            text = f"第{ch}章第{attempt}次写作的内容。" * 20
            return {
                "current_chapter_text": text,
                "decisions": [
                    {"agent": "Writer", "step": f"attempt_{attempt}", "decision": "写作", "reason": "test"}
                ],
                "errors": [],
                "completed_nodes": ["writer"],
            }

        reviewer_call_count = {"count": 0}

        def always_fail_reviewer(state: dict) -> dict:
            """Reviewer 永远标记 need_rewrite=True, 但不应触发 writer 回写."""
            reviewer_call_count["count"] += 1
            return {
                "current_chapter_quality": {
                    "need_rewrite": True,
                    "rule_check": {"passed": False},
                },
                "decisions": [
                    {"agent": "Reviewer", "step": "review", "decision": "标记需重写(仅报告)", "reason": "test"}
                ],
                "errors": [],
                "completed_nodes": ["reviewer"],
            }

        nodes = _get_mock_nodes()
        nodes["writer"] = counting_writer
        nodes["reviewer"] = always_fail_reviewer

        with _patch_nodes(nodes), _patch_langgraph():
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙",
                target_words=15000,
            )
            project_path = result["workspace"]

            gen_result = pipeline.generate_chapters(
                project_path, start_chapter=1, end_chapter=1, silent=True
            )

            assert gen_result["total_generated"] == 1
            # 档 4: writer 只跑一次, reviewer 只产一次报告
            assert writer_call_count["count"] == 1
            assert reviewer_call_count["count"] == 1


# ---------------------------------------------------------------------------
# 5. Error resilience
# ---------------------------------------------------------------------------


class TestErrorResilience:
    """One chapter's writer throws; others still generated, error recorded."""

    def test_other_chapters_survive_one_failure(self, pipeline: NovelPipeline, tmp_workspace: str):
        fail_chapter = 3
        call_log: list[int] = []

        def selective_fail_writer(state: dict) -> dict:
            ch = state.get("current_chapter", 1)
            call_log.append(ch)
            if ch == fail_chapter:
                raise RuntimeError(f"LLM 超时: 第{ch}章写作失败")
            return _mock_writer_node(state)

        nodes = _get_mock_nodes()
        nodes["writer"] = selective_fail_writer

        with _patch_nodes(nodes), _patch_langgraph():
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙",
                target_words=15000,
            )
            project_path = result["workspace"]
            novel_id = result["novel_id"]

            gen_result = pipeline.generate_chapters(project_path, silent=True)

            # Chapters 1, 2, 4, 5 should succeed; chapter 3 should fail
            assert 1 in gen_result["chapters_generated"]
            assert 2 in gen_result["chapters_generated"]
            assert 3 not in gen_result["chapters_generated"]
            assert 4 in gen_result["chapters_generated"]
            assert 5 in gen_result["chapters_generated"]
            assert gen_result["total_generated"] == 4

            # Error should be recorded
            errors = gen_result["errors"]
            error_messages = [str(e.get("message", "")) for e in errors]
            assert any("第3章" in msg or "LLM 超时" in msg for msg in error_messages)

            # Checkpoint should still exist and be valid
            ckpt = pipeline._load_checkpoint(novel_id)
            assert ckpt is not None

            # Chapter files for 1, 2, 4, 5 should exist; 3 should not have text
            fm = pipeline._get_file_manager()
            for ch_num in [1, 2, 4, 5]:
                text = fm.load_chapter_text(novel_id, ch_num)
                assert text is not None and len(text) > 0, f"Chapter {ch_num} text missing"

    def test_error_recorded_in_checkpoint(self, pipeline: NovelPipeline, tmp_workspace: str):
        """Errors from failed nodes are persisted in checkpoint."""

        def always_fail_writer(state: dict) -> dict:
            raise RuntimeError("模型服务不可用")

        nodes = _get_mock_nodes()
        nodes["writer"] = always_fail_writer

        with _patch_nodes(nodes), _patch_langgraph():
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙",
                target_words=15000,
            )
            project_path = result["workspace"]
            novel_id = result["novel_id"]

            gen_result = pipeline.generate_chapters(
                project_path, start_chapter=1, end_chapter=1, silent=True
            )

            # No chapters should be generated (writer always fails, so no text)
            assert gen_result["total_generated"] == 0

            # Errors should be in the checkpoint
            ckpt = pipeline._load_checkpoint(novel_id)
            assert ckpt is not None
            assert len(ckpt.get("errors", [])) > 0

    def test_partial_generation_checkpoint_saved(self, pipeline: NovelPipeline, tmp_workspace: str):
        """Even if later chapters fail, earlier ones are saved in checkpoint."""
        call_count = {"n": 0}

        def fail_after_two(state: dict) -> dict:
            call_count["n"] += 1
            ch = state.get("current_chapter", 1)
            if ch > 2:
                raise RuntimeError("网络断开")
            return _mock_writer_node(state)

        nodes = _get_mock_nodes()
        nodes["writer"] = fail_after_two

        with _patch_nodes(nodes), _patch_langgraph():
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙",
                target_words=15000,
            )
            project_path = result["workspace"]
            novel_id = result["novel_id"]

            gen_result = pipeline.generate_chapters(project_path, silent=True)

            # Chapters 1-2 should succeed
            assert 1 in gen_result["chapters_generated"]
            assert 2 in gen_result["chapters_generated"]

            # Checkpoint should have the successful chapters
            ckpt = pipeline._load_checkpoint(novel_id)
            assert len(ckpt.get("chapters", [])) >= 2


# ---------------------------------------------------------------------------
# 6. Large novel simulation (25 chapters)
# ---------------------------------------------------------------------------


class TestLargeNovelSimulation:
    """Create 25-chapter outline, generate all, verify word count."""

    def test_25_chapters_generation(self, pipeline: NovelPipeline, tmp_workspace: str):
        # Override novel_director to produce 25 chapters
        def director_25(state: dict) -> dict:
            return {
                "outline": _make_outline_dict(25),
                "total_chapters": 25,
                "current_chapter": 0,
                "should_continue": True,
                "style_name": "webnovel.shuangwen",
                "template": "cyclic_upgrade",
                "decisions": [
                    {"agent": "NovelDirector", "step": "init", "decision": "创建25章大纲", "reason": "test"}
                ],
                "errors": [],
                "completed_nodes": ["novel_director"],
            }

        nodes = _get_mock_nodes()
        nodes["novel_director"] = director_25

        with _patch_nodes(nodes), _patch_langgraph():
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙称帝",
                target_words=100000,
            )
            project_path = result["workspace"]
            novel_id = result["novel_id"]

            assert result["outline"] is not None
            assert len(result["outline"]["chapters"]) == 25

            # Generate all 25 chapters
            gen_result = pipeline.generate_chapters(project_path, silent=True)

            assert gen_result["total_generated"] == 25
            assert gen_result["chapters_generated"] == list(range(1, 26))
            assert len(gen_result["errors"]) == 0

            # Verify total word count is reasonable
            status = pipeline.get_status(project_path)
            # Each mock chapter is ~1000 chars, 25 chapters -> >10K total
            assert status["total_words"] > 5000, (
                f"Expected >5000 total words for 25 chapters, got {status['total_words']}"
            )

            # All chapter files exist
            fm = pipeline._get_file_manager()
            saved_chapters = fm.list_chapters(novel_id)
            assert saved_chapters == list(range(1, 26))

    def test_25_chapters_export(self, pipeline: NovelPipeline, tmp_workspace: str, tmp_path: Path):
        """Export a 25-chapter novel and verify all content present."""

        def director_25(state: dict) -> dict:
            return {
                "outline": _make_outline_dict(25),
                "total_chapters": 25,
                "current_chapter": 0,
                "should_continue": True,
                "style_name": "webnovel.shuangwen",
                "template": "cyclic_upgrade",
                "decisions": [],
                "errors": [],
                "completed_nodes": ["novel_director"],
            }

        nodes = _get_mock_nodes()
        nodes["novel_director"] = director_25

        with _patch_nodes(nodes), _patch_langgraph():
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙称帝",
                target_words=100000,
            )
            project_path = result["workspace"]

            pipeline.generate_chapters(project_path, silent=True)

            export_file = str(tmp_path / "big_novel.txt")
            output = pipeline.export_novel(project_path, export_file)

            content = Path(output).read_text(encoding="utf-8")

            # All 25 chapters should appear
            for ch_num in range(1, 26):
                assert f"第{ch_num}章" in content, f"Chapter {ch_num} missing from export"

            # File should be substantial
            assert len(content) > 5000

    def test_large_novel_checkpoint_integrity(self, pipeline: NovelPipeline, tmp_workspace: str):
        """After 25 chapters, checkpoint JSON is valid and complete."""

        def director_25(state: dict) -> dict:
            return {
                "outline": _make_outline_dict(25),
                "total_chapters": 25,
                "current_chapter": 0,
                "should_continue": True,
                "style_name": "webnovel.shuangwen",
                "template": "cyclic_upgrade",
                "decisions": [],
                "errors": [],
                "completed_nodes": ["novel_director"],
            }

        nodes = _get_mock_nodes()
        nodes["novel_director"] = director_25

        with _patch_nodes(nodes), _patch_langgraph():
            result = pipeline.create_novel(
                genre="玄幻",
                theme="修仙称帝",
                target_words=100000,
            )
            project_path = result["workspace"]
            novel_id = result["novel_id"]

            pipeline.generate_chapters(project_path, silent=True)

            # Reload checkpoint from disk (not from memory)
            ckpt_path = Path(project_path) / "checkpoint.json"
            assert ckpt_path.exists()

            raw = json.loads(ckpt_path.read_text(encoding="utf-8"))
            assert raw["current_chapter"] == 25
            assert len(raw["chapters"]) == 25
            assert raw["outline"] is not None
            assert len(raw["completed_nodes"]) > 0
            # Should have decisions from all agents across all chapters
            assert len(raw["decisions"]) >= 25  # At least 1 per chapter
