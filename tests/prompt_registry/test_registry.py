"""Comprehensive tests for PromptRegistry class."""

import os
import tempfile

import pytest

from src.prompt_registry.models import FeedbackRecord, PromptBlock, PromptTemplate
from src.prompt_registry.registry import PromptRegistry


@pytest.fixture
def registry(tmp_path):
    """Create a PromptRegistry with a temporary database."""
    db_path = str(tmp_path / "test_registry.db")
    reg = PromptRegistry(db_path=db_path)
    yield reg
    reg.close()


@pytest.fixture
def seeded_registry(registry):
    """Registry with some pre-populated blocks and templates."""
    # Blocks
    registry.create_block("anti_ai", "anti_pattern", "Avoid AI-isms", agent="writer")
    registry.create_block("anti_rep", "anti_pattern", "No repetition", agent="writer")
    registry.create_block("style_wuxia", "system_instruction", "Wuxia style", agent="writer", genre="wuxia")
    registry.create_block("style_scifi", "system_instruction", "Scifi style", agent="writer", genre="scifi")
    registry.create_block("craft_general", "craft_technique", "General craft tips", agent="writer")
    registry.create_block("craft_battle", "craft_technique", "Battle craft", agent="writer", scene_type="battle")
    registry.create_block(
        "feedback_injection",
        "feedback_injection",
        "Strengths:\n{strengths}\n\nWeaknesses:\n{weaknesses}",
        agent="writer",
    )

    # Templates
    registry.create_template(
        "writer_default", "writer",
        ["style_{genre}", "craft_general", "anti_ai", "anti_rep", "feedback_injection"],
    )
    registry.create_template(
        "writer_battle", "writer",
        ["style_{genre}", "craft_battle", "craft_general", "anti_ai", "anti_rep", "feedback_injection"],
        scenario="battle",
    )
    registry.create_template(
        "writer_wuxia_default", "writer",
        ["style_wuxia", "craft_general", "anti_ai", "anti_rep"],
        scenario="default",
        genre="wuxia",
    )
    return registry


# =====================================================================
# Block CRUD
# =====================================================================


class TestBlockCRUD:
    def test_create_block(self, registry):
        block = registry.create_block("test_block", "anti_pattern", "content here")
        assert isinstance(block, PromptBlock)
        assert block.base_id == "test_block"
        assert block.version == 1
        assert block.active is True
        assert block.content == "content here"

    def test_create_block_with_all_fields(self, registry):
        block = registry.create_block(
            "full_block",
            "craft_technique",
            "full content",
            agent="writer",
            genre="wuxia",
            scene_type="battle",
            metadata={"source": "test"},
        )
        assert block.agent == "writer"
        assert block.genre == "wuxia"
        assert block.scene_type == "battle"
        assert block.metadata == {"source": "test"}

    def test_get_active_block(self, registry):
        registry.create_block("b1", "anti_pattern", "v1 content")
        active = registry.get_active_block("b1")
        assert active is not None
        assert active.content == "v1 content"
        assert active.active is True

    def test_get_active_block_not_found(self, registry):
        result = registry.get_active_block("nonexistent")
        assert result is None

    def test_get_block_versions(self, registry):
        registry.create_block("versioned", "anti_pattern", "v1")
        registry.create_block("versioned", "anti_pattern", "v2")
        registry.create_block("versioned", "anti_pattern", "v3")
        versions = registry.get_block_versions("versioned")
        assert len(versions) == 3
        assert versions[0].version == 1
        assert versions[1].version == 2
        assert versions[2].version == 3
        # Only latest should be active
        active_count = sum(1 for v in versions if v.active)
        assert active_count == 1
        assert versions[2].active is True

    def test_update_block_creates_new_version(self, registry):
        registry.create_block("upd", "anti_pattern", "original")
        updated = registry.update_block("upd", "updated content")
        assert updated.version == 2
        assert updated.content == "updated content"
        assert updated.active is True
        # Old version should be inactive
        versions = registry.get_block_versions("upd")
        assert versions[0].active is False
        assert versions[1].active is True

    def test_update_block_preserves_fields(self, registry):
        registry.create_block("upd2", "craft_technique", "orig", agent="writer", genre="wuxia")
        updated = registry.update_block("upd2", "new content")
        assert updated.agent == "writer"
        assert updated.genre == "wuxia"
        assert updated.block_type == "craft_technique"

    def test_update_block_not_found_raises(self, registry):
        with pytest.raises(ValueError, match="No active block"):
            registry.update_block("ghost", "new content")

    def test_rollback_block(self, registry):
        registry.create_block("rb", "anti_pattern", "v1")
        registry.create_block("rb", "anti_pattern", "v2")
        registry.create_block("rb", "anti_pattern", "v3")
        rolled_back = registry.rollback_block("rb", 1)
        assert rolled_back.version == 1
        assert rolled_back.content == "v1"
        assert rolled_back.active is True
        # v2 and v3 should be inactive
        for v in registry.get_block_versions("rb"):
            if v.version != 1:
                assert v.active is False

    def test_rollback_block_invalid_version(self, registry):
        registry.create_block("rb2", "anti_pattern", "v1")
        with pytest.raises(ValueError, match="Version 99 not found"):
            registry.rollback_block("rb2", 99)

    def test_list_blocks_all_active(self, registry):
        registry.create_block("a", "anti_pattern", "a")
        registry.create_block("b", "craft_technique", "b", agent="writer")
        blocks = registry.list_blocks()
        assert len(blocks) == 2

    def test_list_blocks_filter_by_agent(self, registry):
        registry.create_block("a", "anti_pattern", "a", agent="writer")
        registry.create_block("b", "anti_pattern", "b", agent="reviewer")
        blocks = registry.list_blocks(agent="writer")
        assert len(blocks) == 1
        assert blocks[0].agent == "writer"

    def test_list_blocks_filter_by_type(self, registry):
        registry.create_block("a", "anti_pattern", "a")
        registry.create_block("b", "craft_technique", "b")
        blocks = registry.list_blocks(block_type="craft_technique")
        assert len(blocks) == 1
        assert blocks[0].block_type == "craft_technique"

    def test_list_blocks_include_inactive(self, registry):
        registry.create_block("x", "anti_pattern", "v1")
        registry.create_block("x", "anti_pattern", "v2")
        active_blocks = registry.list_blocks(active_only=True)
        all_blocks = registry.list_blocks(active_only=False)
        assert len(active_blocks) == 1
        assert len(all_blocks) == 2


# =====================================================================
# Template CRUD
# =====================================================================


class TestTemplateCRUD:
    def test_create_template(self, registry):
        tpl = registry.create_template("t1", "writer", ["a", "b"])
        assert isinstance(tpl, PromptTemplate)
        assert tpl.template_id == "t1"
        assert tpl.agent_name == "writer"
        assert tpl.block_refs == ["a", "b"]
        assert tpl.scenario == "default"

    def test_get_template(self, registry):
        registry.create_template("t2", "writer", ["a"])
        tpl = registry.get_template("t2")
        assert tpl is not None
        assert tpl.template_id == "t2"

    def test_get_template_not_found(self, registry):
        assert registry.get_template("nonexistent") is None

    def test_get_template_for_exact_match(self, seeded_registry):
        tpl = seeded_registry.get_template_for("writer", "default", "wuxia")
        assert tpl is not None
        assert tpl.template_id == "writer_wuxia_default"

    def test_get_template_for_genre_fallback(self, seeded_registry):
        # No scifi-specific template, should fall back to genre=None
        tpl = seeded_registry.get_template_for("writer", "default", "scifi")
        assert tpl is not None
        assert tpl.template_id == "writer_default"

    def test_get_template_for_scenario_fallback(self, seeded_registry):
        # No "emotional" scenario template, should fall back to "default"
        tpl = seeded_registry.get_template_for("writer", "emotional")
        assert tpl is not None
        assert tpl.template_id == "writer_default"

    def test_get_template_for_both_fallback(self, seeded_registry):
        # Non-existent scenario + genre -> falls back to default+None
        tpl = seeded_registry.get_template_for("writer", "mystery", "romance")
        assert tpl is not None
        assert tpl.template_id == "writer_default"

    def test_get_template_for_no_match(self, registry):
        tpl = registry.get_template_for("nonexistent_agent")
        assert tpl is None

    def test_list_templates(self, seeded_registry):
        templates = seeded_registry.list_templates()
        assert len(templates) == 3

    def test_list_templates_by_agent(self, seeded_registry):
        templates = seeded_registry.list_templates("writer")
        assert len(templates) == 3
        templates = seeded_registry.list_templates("reviewer")
        assert len(templates) == 0


# =====================================================================
# build_prompt
# =====================================================================


class TestBuildPrompt:
    def test_build_prompt_basic(self, seeded_registry):
        prompt = seeded_registry.build_prompt("writer", "default", "wuxia")
        # Should use writer_wuxia_default template: style_wuxia + craft_general + anti_ai + anti_rep
        assert "Wuxia style" in prompt
        assert "General craft tips" in prompt
        assert "Avoid AI-isms" in prompt
        assert "No repetition" in prompt

    def test_build_prompt_genre_substitution(self, seeded_registry):
        # writer_default template has "style_{genre}" ref
        prompt = seeded_registry.build_prompt("writer", "default", "scifi")
        assert "Scifi style" in prompt

    def test_build_prompt_missing_genre_block_skips(self, seeded_registry):
        # "webnovel" genre has no style block, should skip
        prompt = seeded_registry.build_prompt("writer", "default", "webnovel")
        # Should still have other blocks
        assert "General craft tips" in prompt
        assert "Avoid AI-isms" in prompt

    def test_build_prompt_no_template_returns_empty(self, registry):
        prompt = registry.build_prompt("nonexistent_agent")
        assert prompt == ""

    def test_build_prompt_with_feedback_context(self, seeded_registry):
        context = {
            "last_strengths": ["good pacing", "vivid imagery"],
            "last_weaknesses": ["weak dialogue"],
        }
        prompt = seeded_registry.build_prompt("writer", "default", "scifi", context=context)
        assert "good pacing" in prompt
        assert "vivid imagery" in prompt
        assert "weak dialogue" in prompt

    def test_build_prompt_feedback_skipped_when_no_context(self, seeded_registry):
        # No feedback context -> feedback_injection block should be skipped
        prompt = seeded_registry.build_prompt("writer", "default", "scifi")
        assert "{strengths}" not in prompt
        assert "{weaknesses}" not in prompt

    def test_build_prompt_battle_scenario(self, seeded_registry):
        prompt = seeded_registry.build_prompt("writer", "battle", "wuxia")
        assert "Battle craft" in prompt
        assert "Wuxia style" in prompt

    def test_build_prompt_increments_usage_count(self, seeded_registry):
        # Initial usage count should be 0
        block = seeded_registry.get_active_block("craft_general")
        assert block.usage_count == 0

        seeded_registry.build_prompt("writer", "default", "wuxia")

        block = seeded_registry.get_active_block("craft_general")
        assert block.usage_count == 1


# =====================================================================
# Usage Recording
# =====================================================================


class TestUsageRecording:
    def test_record_usage(self, registry):
        usage_id = registry.record_usage(
            template_id="tpl_001",
            block_ids=["b1", "b2"],
            agent_name="writer",
            scenario="default",
            novel_id="novel_001",
            chapter_number=5,
        )
        assert isinstance(usage_id, str)
        assert len(usage_id) == 8

    def test_update_usage_score(self, registry):
        registry.create_block("score_block", "anti_pattern", "content")
        block = registry.get_active_block("score_block")

        usage_id = registry.record_usage(
            template_id="tpl",
            block_ids=[block.block_id],
            agent_name="writer",
            scenario="default",
        )
        registry.update_usage_score(
            usage_id,
            quality_score=8.5,
            strengths=["great pacing"],
            weaknesses=["minor typos"],
        )
        # Block should have updated avg_score
        updated_block = registry.get_active_block("score_block")
        assert updated_block.avg_score is not None
        assert updated_block.avg_score == pytest.approx(8.5, abs=0.1)

    def test_multiple_scores_averaged(self, registry):
        registry.create_block("avg_block", "anti_pattern", "content")
        block = registry.get_active_block("avg_block")

        # Record two usages with different scores
        uid1 = registry.record_usage("tpl", [block.block_id], "writer", "default")
        registry.update_usage_score(uid1, 6.0)

        uid2 = registry.record_usage("tpl", [block.block_id], "writer", "default")
        registry.update_usage_score(uid2, 10.0)

        updated = registry.get_active_block("avg_block")
        # Average of 6.0 and 10.0 = 8.0
        assert updated.avg_score is not None
        assert updated.avg_score == pytest.approx(8.0, abs=0.1)


# =====================================================================
# Feedback
# =====================================================================


class TestFeedback:
    def test_save_and_get_feedback(self, registry):
        registry.save_feedback(
            novel_id="n1",
            chapter_number=3,
            strengths=["good"],
            weaknesses=["bad"],
            overall_score=7.0,
        )
        fb = registry.get_last_feedback("n1", current_chapter=4)
        assert fb is not None
        assert isinstance(fb, FeedbackRecord)
        assert fb.chapter_number == 3
        assert fb.strengths == ["good"]
        assert fb.weaknesses == ["bad"]
        assert fb.overall_score == 7.0

    def test_get_last_feedback_returns_most_recent(self, registry):
        registry.save_feedback("n1", 1, ["a"], ["b"], 5.0)
        registry.save_feedback("n1", 3, ["c"], ["d"], 7.0)
        registry.save_feedback("n1", 5, ["e"], ["f"], 9.0)

        fb = registry.get_last_feedback("n1", current_chapter=4)
        assert fb.chapter_number == 3
        assert fb.strengths == ["c"]

    def test_get_last_feedback_no_previous(self, registry):
        registry.save_feedback("n1", 5, ["a"], ["b"])
        fb = registry.get_last_feedback("n1", current_chapter=1)
        assert fb is None

    def test_get_last_feedback_different_novel(self, registry):
        registry.save_feedback("n1", 3, ["a"], ["b"])
        fb = registry.get_last_feedback("n2", current_chapter=5)
        assert fb is None


# =====================================================================
# Quality Tracking
# =====================================================================


class TestQualityTracking:
    def test_get_block_stats(self, registry):
        registry.create_block("stat_block", "anti_pattern", "content")
        stats = registry.get_block_stats("stat_block")
        assert stats["avg_score"] is None
        assert stats["usage_count"] == 0
        assert stats["needs_optimization"] is False

    def test_get_block_stats_not_found(self, registry):
        stats = registry.get_block_stats("nonexistent")
        assert stats["avg_score"] is None
        assert stats["usage_count"] == 0

    def test_analyze_performance_marks_low_blocks(self, registry):
        registry.create_block("low_block", "anti_pattern", "content")
        block = registry.get_active_block("low_block")

        # Simulate enough usage with low scores
        for i in range(12):
            uid = registry.record_usage("tpl", [block.block_id], "writer", "default")
            registry.update_usage_score(uid, 4.0)

        # Set usage_count manually to match
        low_blocks = registry.analyze_performance(threshold=6.0, min_usage=10)
        assert len(low_blocks) >= 1
        assert any(b.base_id == "low_block" for b in low_blocks)
        assert all(b.needs_optimization is True for b in low_blocks)

    def test_analyze_performance_ignores_high_score(self, registry):
        registry.create_block("high_block", "anti_pattern", "content")
        block = registry.get_active_block("high_block")

        for i in range(12):
            uid = registry.record_usage("tpl", [block.block_id], "writer", "default")
            registry.update_usage_score(uid, 9.0)

        low_blocks = registry.analyze_performance(threshold=6.0, min_usage=10)
        assert not any(b.base_id == "high_block" for b in low_blocks)

    def test_analyze_performance_ignores_low_usage(self, registry):
        registry.create_block("few_block", "anti_pattern", "content")
        block = registry.get_active_block("few_block")

        # Only 3 usages (below min_usage=10)
        for i in range(3):
            uid = registry.record_usage("tpl", [block.block_id], "writer", "default")
            registry.update_usage_score(uid, 3.0)

        low_blocks = registry.analyze_performance(threshold=6.0, min_usage=10)
        assert not any(b.base_id == "few_block" for b in low_blocks)


# =====================================================================
# Edge cases
# =====================================================================


class TestEdgeCases:
    def test_context_manager(self, tmp_path):
        db_path = str(tmp_path / "cm_test.db")
        with PromptRegistry(db_path=db_path) as reg:
            reg.create_block("cm_block", "anti_pattern", "content")
            block = reg.get_active_block("cm_block")
            assert block is not None

    def test_empty_content_block(self, registry):
        block = registry.create_block("empty", "anti_pattern", "")
        assert block.content == ""

    def test_unicode_content(self, registry):
        content = "禁止使用：内心翻涌、莫名的力量"
        block = registry.create_block("unicode", "anti_pattern", content)
        retrieved = registry.get_active_block("unicode")
        assert retrieved.content == content

    def test_create_template_replaces_existing(self, registry):
        registry.create_template("t1", "writer", ["a", "b"])
        registry.create_template("t1", "writer", ["c", "d"])
        tpl = registry.get_template("t1")
        assert tpl.block_refs == ["c", "d"]

    def test_build_prompt_with_all_blocks_missing(self, registry):
        registry.create_template("empty_tpl", "writer", ["missing_a", "missing_b"])
        prompt = registry.build_prompt("writer")
        assert prompt == ""

    def test_parent_dir_creation(self, tmp_path):
        db_path = str(tmp_path / "deep" / "nested" / "dir" / "test.db")
        reg = PromptRegistry(db_path=db_path)
        reg.create_block("test", "anti_pattern", "ok")
        assert reg.get_active_block("test") is not None
        reg.close()
