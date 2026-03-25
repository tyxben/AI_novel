"""Tests for ChapterDebt, DebtExtractionResult, and DebtContext models"""

import pytest
from pydantic import ValidationError

from src.novel.models.debt import ChapterDebt, DebtContext, DebtExtractionResult


# ---------------------------------------------------------------------------
# Fixtures: minimal valid data
# ---------------------------------------------------------------------------


def _valid_chapter_debt_data() -> dict:
    """Return smallest valid ChapterDebt dict."""
    return {
        "source_chapter": 5,
        "type": "must_pay_next",
        "description": "主角答应师妹明天一起探索密林",
    }


# ---------------------------------------------------------------------------
# ChapterDebt tests
# ---------------------------------------------------------------------------


class TestChapterDebt:
    def test_chapter_debt_valid(self):
        """Create valid ChapterDebt, verify fields."""
        data = _valid_chapter_debt_data()
        debt = ChapterDebt.model_validate(data)

        assert debt.source_chapter == 5
        assert debt.type == "must_pay_next"
        assert debt.description == "主角答应师妹明天一起探索密林"
        assert debt.status == "pending"
        assert debt.urgency_level == "normal"
        assert debt.character_pending_actions == []
        assert debt.emotional_debt is None
        assert debt.target_chapter is None
        assert debt.fulfilled_at is None
        assert debt.fulfillment_note is None
        assert debt.escalation_history == []
        # auto-generated fields
        assert len(debt.debt_id) > 0
        assert len(debt.created_at) > 0

    def test_chapter_debt_all_fields(self):
        """ChapterDebt with all optional fields populated."""
        data = _valid_chapter_debt_data()
        data.update({
            "character_pending_actions": ["师妹等待回复", "主角需出发"],
            "emotional_debt": "师妹的失望情绪未解",
            "target_chapter": 7,
            "status": "fulfilled",
            "fulfilled_at": 6,
            "fulfillment_note": "主角在第6章兑现了承诺",
            "urgency_level": "high",
            "escalation_history": [
                {"from": "normal", "to": "high", "chapter": 6}
            ],
        })
        debt = ChapterDebt.model_validate(data)

        assert debt.character_pending_actions == ["师妹等待回复", "主角需出发"]
        assert debt.emotional_debt == "师妹的失望情绪未解"
        assert debt.target_chapter == 7
        assert debt.status == "fulfilled"
        assert debt.fulfilled_at == 6
        assert debt.fulfillment_note == "主角在第6章兑现了承诺"
        assert debt.urgency_level == "high"
        assert len(debt.escalation_history) == 1

    def test_chapter_debt_invalid_type(self):
        """Invalid type value raises ValidationError."""
        data = _valid_chapter_debt_data()
        data["type"] = "invalid_type"

        with pytest.raises(ValidationError) as exc_info:
            ChapterDebt.model_validate(data)

        errors = exc_info.value.errors()
        assert any("type" in str(e["loc"]) for e in errors)

    def test_chapter_debt_invalid_status(self):
        """Invalid status value raises ValidationError."""
        data = _valid_chapter_debt_data()
        data["status"] = "unknown_status"

        with pytest.raises(ValidationError) as exc_info:
            ChapterDebt.model_validate(data)

        errors = exc_info.value.errors()
        assert any("status" in str(e["loc"]) for e in errors)

    def test_chapter_debt_invalid_urgency_level(self):
        """Invalid urgency_level raises ValidationError."""
        data = _valid_chapter_debt_data()
        data["urgency_level"] = "ultra"

        with pytest.raises(ValidationError):
            ChapterDebt.model_validate(data)

    def test_chapter_debt_source_chapter_must_be_positive(self):
        """source_chapter must be >= 1."""
        data = _valid_chapter_debt_data()
        data["source_chapter"] = 0

        with pytest.raises(ValidationError):
            ChapterDebt.model_validate(data)

    def test_chapter_debt_empty_description_rejected(self):
        """Empty description raises ValidationError."""
        data = _valid_chapter_debt_data()
        data["description"] = ""

        with pytest.raises(ValidationError):
            ChapterDebt.model_validate(data)

    def test_chapter_debt_all_type_values(self):
        """All valid type values should work."""
        for debt_type in ("must_pay_next", "pay_within_3", "long_tail_payoff"):
            data = _valid_chapter_debt_data()
            data["type"] = debt_type
            debt = ChapterDebt.model_validate(data)
            assert debt.type == debt_type

    def test_chapter_debt_all_status_values(self):
        """All valid status values should work."""
        for status in ("pending", "fulfilled", "overdue", "abandoned"):
            data = _valid_chapter_debt_data()
            data["status"] = status
            debt = ChapterDebt.model_validate(data)
            assert debt.status == status

    def test_chapter_debt_created_at_iso_format(self):
        """created_at should be a valid ISO format timestamp."""
        debt = ChapterDebt.model_validate(_valid_chapter_debt_data())
        # Should contain 'T' separator (ISO 8601)
        assert "T" in debt.created_at

    def test_chapter_debt_serialization_json_roundtrip(self):
        """JSON serialize/deserialize preserves all fields."""
        data = _valid_chapter_debt_data()
        data["character_pending_actions"] = ["行动一"]
        data["urgency_level"] = "critical"

        debt = ChapterDebt.model_validate(data)
        json_str = debt.model_dump_json()
        restored = ChapterDebt.model_validate_json(json_str)

        assert restored.debt_id == debt.debt_id
        assert restored.source_chapter == debt.source_chapter
        assert restored.type == debt.type
        assert restored.description == debt.description
        assert restored.character_pending_actions == ["行动一"]
        assert restored.urgency_level == "critical"
        assert restored.created_at == debt.created_at

    def test_chapter_debt_serialization_dict_roundtrip(self):
        """Dict serialize/deserialize preserves all fields."""
        data = _valid_chapter_debt_data()
        debt = ChapterDebt.model_validate(data)
        dumped = debt.model_dump()
        restored = ChapterDebt.model_validate(dumped)

        assert restored.debt_id == debt.debt_id
        assert restored.description == debt.description


# ---------------------------------------------------------------------------
# DebtExtractionResult tests
# ---------------------------------------------------------------------------


class TestDebtExtractionResult:
    def test_debt_extraction_result_valid(self):
        """Create valid DebtExtractionResult."""
        debt = ChapterDebt.model_validate(_valid_chapter_debt_data())
        result = DebtExtractionResult(
            chapter_number=5,
            debts=[debt],
            extraction_method="hybrid",
            confidence=0.85,
        )

        assert result.chapter_number == 5
        assert len(result.debts) == 1
        assert result.extraction_method == "hybrid"
        assert result.confidence == 0.85

    def test_debt_extraction_result_defaults(self):
        """Default values for debts, method, confidence."""
        result = DebtExtractionResult(chapter_number=1)

        assert result.debts == []
        assert result.extraction_method == "llm"
        assert result.confidence == 1.0

    def test_debt_extraction_result_invalid_method(self):
        """Invalid extraction_method raises ValidationError."""
        with pytest.raises(ValidationError):
            DebtExtractionResult(
                chapter_number=1, extraction_method="magic"
            )

    def test_debt_extraction_result_confidence_bounds(self):
        """Confidence must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            DebtExtractionResult(chapter_number=1, confidence=-0.1)

        with pytest.raises(ValidationError):
            DebtExtractionResult(chapter_number=1, confidence=1.5)

    def test_debt_extraction_result_serialization(self):
        """JSON round-trip preserves nested debts."""
        debt = ChapterDebt.model_validate(_valid_chapter_debt_data())
        result = DebtExtractionResult(
            chapter_number=5,
            debts=[debt],
            extraction_method="rule_based",
            confidence=0.7,
        )

        json_str = result.model_dump_json()
        restored = DebtExtractionResult.model_validate_json(json_str)

        assert restored.chapter_number == 5
        assert len(restored.debts) == 1
        assert restored.debts[0].description == debt.description
        assert restored.extraction_method == "rule_based"
        assert restored.confidence == 0.7


# ---------------------------------------------------------------------------
# DebtContext tests
# ---------------------------------------------------------------------------


class TestDebtContext:
    def test_debt_context_valid(self):
        """Create valid DebtContext."""
        debt1 = ChapterDebt.model_validate(_valid_chapter_debt_data())
        debt2 = ChapterDebt.model_validate({
            **_valid_chapter_debt_data(),
            "type": "pay_within_3",
            "description": "伏笔：神秘人的身份",
            "status": "overdue",
        })

        ctx = DebtContext(
            chapter_number=10,
            pending_debts=[debt1],
            overdue_debts=[debt2],
            critical_debts=[],
            formatted_summary="待偿还叙事债务...",
            token_count=50,
        )

        assert ctx.chapter_number == 10
        assert len(ctx.pending_debts) == 1
        assert len(ctx.overdue_debts) == 1
        assert len(ctx.critical_debts) == 0
        assert ctx.formatted_summary == "待偿还叙事债务..."
        assert ctx.token_count == 50

    def test_debt_context_defaults(self):
        """Default values for all list/string fields."""
        ctx = DebtContext(chapter_number=1)

        assert ctx.pending_debts == []
        assert ctx.overdue_debts == []
        assert ctx.critical_debts == []
        assert ctx.formatted_summary == ""
        assert ctx.token_count == 0

    def test_debt_context_chapter_number_must_be_positive(self):
        """chapter_number must be >= 1."""
        with pytest.raises(ValidationError):
            DebtContext(chapter_number=0)

    def test_debt_context_token_count_non_negative(self):
        """token_count must be >= 0."""
        with pytest.raises(ValidationError):
            DebtContext(chapter_number=1, token_count=-1)

    def test_debt_context_serialization(self):
        """JSON round-trip preserves nested debts and summary."""
        debt = ChapterDebt.model_validate(_valid_chapter_debt_data())
        ctx = DebtContext(
            chapter_number=5,
            pending_debts=[debt],
            formatted_summary="摘要内容",
            token_count=20,
        )

        json_str = ctx.model_dump_json()
        restored = DebtContext.model_validate_json(json_str)

        assert restored.chapter_number == 5
        assert len(restored.pending_debts) == 1
        assert restored.formatted_summary == "摘要内容"
        assert restored.token_count == 20
