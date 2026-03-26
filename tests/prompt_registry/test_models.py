"""Tests for Prompt Registry Pydantic models."""

from datetime import datetime

from src.prompt_registry.models import (
    FeedbackRecord,
    PromptBlock,
    PromptTemplate,
    PromptUsage,
)


class TestPromptBlock:
    def test_default_values(self):
        block = PromptBlock(base_id="test", block_type="anti_pattern", content="hello")
        assert block.base_id == "test"
        assert block.version == 1
        assert block.agent == "universal"
        assert block.genre is None
        assert block.scene_type is None
        assert block.active is True
        assert block.needs_optimization is False
        assert block.avg_score is None
        assert block.usage_count == 0
        assert block.metadata == {}
        assert isinstance(block.created_at, datetime)
        assert isinstance(block.updated_at, datetime)
        assert len(block.block_id) == 8

    def test_full_values(self):
        now = datetime(2025, 1, 1, 12, 0, 0)
        block = PromptBlock(
            block_id="abc12345",
            base_id="writer_anti_ai",
            version=3,
            block_type="anti_pattern",
            agent="writer",
            genre="wuxia",
            scene_type="battle",
            content="some content",
            active=False,
            needs_optimization=True,
            avg_score=7.5,
            usage_count=42,
            metadata={"source": "writer.py"},
            created_at=now,
            updated_at=now,
        )
        assert block.block_id == "abc12345"
        assert block.version == 3
        assert block.genre == "wuxia"
        assert block.scene_type == "battle"
        assert block.avg_score == 7.5
        assert block.usage_count == 42
        assert block.metadata["source"] == "writer.py"

    def test_serialization_roundtrip(self):
        block = PromptBlock(
            base_id="test",
            block_type="system_instruction",
            content="content here",
            metadata={"key": "value"},
        )
        data = block.model_dump()
        restored = PromptBlock(**data)
        assert restored.base_id == block.base_id
        assert restored.content == block.content
        assert restored.metadata == block.metadata

    def test_json_roundtrip(self):
        block = PromptBlock(
            base_id="test",
            block_type="craft_technique",
            content="technique content",
        )
        json_str = block.model_dump_json()
        restored = PromptBlock.model_validate_json(json_str)
        assert restored.base_id == block.base_id
        assert restored.content == block.content


class TestPromptTemplate:
    def test_default_values(self):
        tpl = PromptTemplate(
            agent_name="writer",
            block_refs=["block_a", "block_b"],
        )
        assert tpl.agent_name == "writer"
        assert tpl.scenario == "default"
        assert tpl.genre is None
        assert tpl.block_refs == ["block_a", "block_b"]
        assert tpl.active is True
        assert len(tpl.template_id) == 8

    def test_full_values(self):
        tpl = PromptTemplate(
            template_id="tpl_001",
            agent_name="writer",
            scenario="battle",
            genre="wuxia",
            block_refs=["style_wuxia", "craft_battle"],
            active=True,
        )
        assert tpl.template_id == "tpl_001"
        assert tpl.scenario == "battle"
        assert tpl.genre == "wuxia"

    def test_serialization_roundtrip(self):
        tpl = PromptTemplate(
            agent_name="writer",
            block_refs=["a", "b", "c"],
            scenario="emotional",
        )
        data = tpl.model_dump()
        restored = PromptTemplate(**data)
        assert restored.block_refs == tpl.block_refs
        assert restored.scenario == "emotional"


class TestPromptUsage:
    def test_default_values(self):
        usage = PromptUsage(
            template_id="tpl_001",
            block_ids=["b1", "b2"],
            agent_name="writer",
            scenario="default",
        )
        assert usage.template_id == "tpl_001"
        assert usage.novel_id is None
        assert usage.chapter_number is None
        assert usage.quality_score is None
        assert usage.strengths == []
        assert usage.weaknesses == []

    def test_with_scores(self):
        usage = PromptUsage(
            template_id="tpl_001",
            block_ids=["b1"],
            agent_name="writer",
            scenario="battle",
            novel_id="novel_001",
            chapter_number=5,
            quality_score=8.0,
            strengths=["good pacing"],
            weaknesses=["weak dialogue"],
        )
        assert usage.quality_score == 8.0
        assert len(usage.strengths) == 1
        assert len(usage.weaknesses) == 1


class TestFeedbackRecord:
    def test_default_values(self):
        fb = FeedbackRecord(
            novel_id="novel_001",
            chapter_number=3,
        )
        assert fb.novel_id == "novel_001"
        assert fb.chapter_number == 3
        assert fb.strengths == []
        assert fb.weaknesses == []
        assert fb.overall_score is None

    def test_full_values(self):
        fb = FeedbackRecord(
            novel_id="novel_001",
            chapter_number=5,
            strengths=["good", "pacing"],
            weaknesses=["bland dialogue"],
            overall_score=7.2,
        )
        assert fb.strengths == ["good", "pacing"]
        assert fb.overall_score == 7.2

    def test_json_roundtrip(self):
        fb = FeedbackRecord(
            novel_id="n1",
            chapter_number=1,
            strengths=["a"],
            weaknesses=["b"],
            overall_score=6.0,
        )
        json_str = fb.model_dump_json()
        restored = FeedbackRecord.model_validate_json(json_str)
        assert restored.novel_id == fb.novel_id
        assert restored.strengths == fb.strengths
