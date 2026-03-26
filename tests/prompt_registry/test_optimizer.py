"""Comprehensive tests for PromptOptimizer."""

import json
from unittest.mock import MagicMock

import pytest

from src.llm.llm_client import LLMResponse
from src.prompt_registry.optimizer import PromptOptimizer
from src.prompt_registry.registry import PromptRegistry


@pytest.fixture
def registry(tmp_path):
    """Create a PromptRegistry with a temporary database."""
    db_path = str(tmp_path / "test_opt.db")
    reg = PromptRegistry(db_path=db_path)
    yield reg
    reg.close()


@pytest.fixture
def mock_llm():
    """Create a mock LLM client that returns a valid improved prompt."""
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(
        content=json.dumps(
            {
                "improved_prompt": "This is an improved prompt with enough content to pass validation length check.",
                "rationale": "Made it clearer and more actionable.",
            }
        ),
        model="mock-model",
        usage={"prompt_tokens": 100, "completion_tokens": 50},
    )
    return llm


@pytest.fixture
def optimizer(registry, mock_llm):
    """Create a PromptOptimizer with mock LLM."""
    return PromptOptimizer(registry, mock_llm)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _seed_block_with_usages(
    registry: PromptRegistry,
    base_id: str,
    content: str = "Original prompt content here",
    scores: list[float] | None = None,
    weaknesses_per_usage: list[list[str]] | None = None,
) -> str:
    """Create a block and optionally seed usages. Returns block_id."""
    block = registry.create_block(base_id, "craft_technique", content, agent="writer")
    if scores:
        for i, score in enumerate(scores):
            uid = registry.record_usage("tpl", [block.block_id], "writer", "default")
            ws = weaknesses_per_usage[i] if weaknesses_per_usage else []
            registry.update_usage_score(uid, score, weaknesses=ws)
    return block.block_id


# =====================================================================
# generate_improved_block
# =====================================================================


class TestGenerateImprovedBlock:
    def test_calls_llm_with_correct_prompt(self, optimizer, registry, mock_llm):
        _seed_block_with_usages(registry, "opt_a", content="Write wuxia battles well")
        optimizer.generate_improved_block("opt_a")

        mock_llm.chat.assert_called_once()
        call_args = mock_llm.chat.call_args
        messages = call_args[0][0]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "Write wuxia battles well" in messages[0]["content"]
        assert "prompt 工程专家" in messages[0]["content"]
        # Check kwargs
        assert call_args[1]["temperature"] == 0.4
        assert call_args[1]["json_mode"] is True
        assert call_args[1]["max_tokens"] == 4096

    def test_creates_new_version_inactive(self, optimizer, registry):
        _seed_block_with_usages(registry, "opt_b")
        result = optimizer.generate_improved_block("opt_b")

        assert result["base_id"] == "opt_b"
        assert result["old_version"] == 1
        assert result["new_version"] == 2
        assert result["new_content"] != result["old_content"]
        assert "improved prompt" in result["new_content"].lower()

        # The new block should be INACTIVE (pending review)
        versions = registry.get_block_versions("opt_b")
        new_version = [v for v in versions if v.version == 2]
        assert len(new_version) == 1
        assert new_version[0].active is False

    def test_old_version_stays_active(self, optimizer, registry):
        _seed_block_with_usages(registry, "opt_c")
        optimizer.generate_improved_block("opt_c")

        active = registry.get_active_block("opt_c")
        assert active is not None
        assert active.version == 1
        assert active.active is True

    def test_nonexistent_block_raises_value_error(self, optimizer):
        with pytest.raises(ValueError, match="No active block found"):
            optimizer.generate_improved_block("nonexistent")

    def test_empty_llm_response_raises_value_error(self, optimizer, registry, mock_llm):
        _seed_block_with_usages(registry, "opt_empty")
        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps({"improved_prompt": "", "rationale": "n/a"}),
            model="mock-model",
        )
        with pytest.raises(ValueError, match="LLM failed to generate"):
            optimizer.generate_improved_block("opt_empty")

    def test_short_llm_response_raises_value_error(self, optimizer, registry, mock_llm):
        _seed_block_with_usages(registry, "opt_short")
        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps({"improved_prompt": "too short", "rationale": "n/a"}),
            model="mock-model",
        )
        with pytest.raises(ValueError, match="LLM failed to generate"):
            optimizer.generate_improved_block("opt_short")

    def test_non_json_llm_response_uses_raw_content(self, optimizer, registry, mock_llm):
        """When LLM returns non-JSON, use the raw content as the improved prompt."""
        _seed_block_with_usages(registry, "opt_raw")
        raw_content = "This is a raw improved prompt without JSON wrapping - long enough to pass validation."
        mock_llm.chat.return_value = LLMResponse(
            content=raw_content,
            model="mock-model",
        )
        result = optimizer.generate_improved_block("opt_raw")
        assert result["new_content"] == raw_content
        assert result["improvement_rationale"] == "LLM returned non-JSON response"

    def test_metadata_includes_optimization_info(self, optimizer, registry):
        _seed_block_with_usages(
            registry,
            "opt_meta",
            scores=[5.0, 4.0],
            weaknesses_per_usage=[["weak dialogue"], ["poor pacing"]],
        )
        result = optimizer.generate_improved_block("opt_meta")

        # Check metadata on the new block
        versions = registry.get_block_versions("opt_meta")
        new_block = [v for v in versions if v.version == 2][0]
        assert new_block.metadata.get("pending_review") is True
        assert new_block.metadata.get("optimization_source_version") == 1
        assert "optimization_rationale" in new_block.metadata


# =====================================================================
# approve_improved_block
# =====================================================================


class TestApproveImprovedBlock:
    def test_activates_new_deactivates_old(self, optimizer, registry):
        _seed_block_with_usages(registry, "apr_a")
        result = optimizer.generate_improved_block("apr_a")
        new_block_id = result["block_id"]

        # Before approval: old is active, new is not
        assert registry.get_active_block("apr_a").version == 1

        approval = optimizer.approve_improved_block(new_block_id)
        assert approval["status"] == "approved"
        assert approval["base_id"] == "apr_a"

        # After approval: new is active
        active = registry.get_active_block("apr_a")
        assert active.block_id == new_block_id
        assert active.version == 2

    def test_clears_pending_review_metadata(self, optimizer, registry):
        _seed_block_with_usages(registry, "apr_meta")
        result = optimizer.generate_improved_block("apr_meta")
        optimizer.approve_improved_block(result["block_id"])

        active = registry.get_active_block("apr_meta")
        assert "pending_review" not in active.metadata
        assert "approved_at" in active.metadata

    def test_clears_needs_optimization_flag(self, optimizer, registry):
        _seed_block_with_usages(registry, "apr_flag")
        result = optimizer.generate_improved_block("apr_flag")

        # Manually set needs_optimization on the new block
        with registry._transaction() as cur:
            cur.execute(
                "UPDATE prompt_blocks SET needs_optimization = 1 WHERE block_id = ?",
                (result["block_id"],),
            )

        optimizer.approve_improved_block(result["block_id"])
        active = registry.get_active_block("apr_flag")
        assert active.needs_optimization is False

    def test_nonexistent_block_raises_value_error(self, optimizer):
        with pytest.raises(ValueError, match="not found"):
            optimizer.approve_improved_block("nonexistent_id")


# =====================================================================
# reject_improved_block
# =====================================================================


class TestRejectImprovedBlock:
    def test_marks_metadata_as_rejected(self, optimizer, registry):
        _seed_block_with_usages(registry, "rej_a")
        result = optimizer.generate_improved_block("rej_a")
        rejection = optimizer.reject_improved_block(result["block_id"])

        assert rejection["status"] == "rejected"
        assert rejection["base_id"] == "rej_a"

        # Check metadata
        versions = registry.get_block_versions("rej_a")
        rejected_block = [v for v in versions if v.block_id == result["block_id"]][0]
        assert rejected_block.metadata.get("rejected") is True
        assert "rejected_at" in rejected_block.metadata
        assert "pending_review" not in rejected_block.metadata

    def test_with_reason(self, optimizer, registry):
        _seed_block_with_usages(registry, "rej_b")
        result = optimizer.generate_improved_block("rej_b")
        rejection = optimizer.reject_improved_block(
            result["block_id"], reason="Quality not good enough"
        )

        assert rejection["reason"] == "Quality not good enough"
        versions = registry.get_block_versions("rej_b")
        rejected_block = [v for v in versions if v.block_id == result["block_id"]][0]
        assert rejected_block.metadata["rejection_reason"] == "Quality not good enough"

    def test_old_version_remains_active(self, optimizer, registry):
        _seed_block_with_usages(registry, "rej_c")
        result = optimizer.generate_improved_block("rej_c")
        optimizer.reject_improved_block(result["block_id"])

        active = registry.get_active_block("rej_c")
        assert active.version == 1

    def test_nonexistent_block_raises_value_error(self, optimizer):
        with pytest.raises(ValueError, match="not found"):
            optimizer.reject_improved_block("ghost_id")


# =====================================================================
# optimize_all_candidates
# =====================================================================


class TestOptimizeAllCandidates:
    def test_processes_multiple_blocks(self, optimizer, registry):
        for name in ("cand_1", "cand_2", "cand_3"):
            block = registry.create_block(name, "anti_pattern", f"content for {name}")
            for _ in range(12):
                uid = registry.record_usage("tpl", [block.block_id], "writer", "default")
                registry.update_usage_score(uid, 4.0)

        results = optimizer.optimize_all_candidates(threshold=6.0, min_usage=10)
        assert len(results) >= 2  # at least some candidates processed
        successful = [r for r in results if "error" not in r]
        assert len(successful) >= 1

    def test_handles_errors_gracefully(self, optimizer, registry, mock_llm):
        # Create one valid block
        block = registry.create_block("err_cand", "anti_pattern", "content")
        for _ in range(12):
            uid = registry.record_usage("tpl", [block.block_id], "writer", "default")
            registry.update_usage_score(uid, 4.0)

        # Make LLM fail
        mock_llm.chat.side_effect = RuntimeError("LLM API error")

        results = optimizer.optimize_all_candidates(threshold=6.0, min_usage=10)
        assert len(results) >= 1
        assert "error" in results[0]
        assert "LLM API error" in results[0]["error"]

    def test_respects_max_candidates(self, optimizer, registry):
        for i in range(10):
            block = registry.create_block(f"max_{i}", "anti_pattern", f"content {i}")
            for _ in range(12):
                uid = registry.record_usage("tpl", [block.block_id], "writer", "default")
                registry.update_usage_score(uid, 4.0)

        results = optimizer.optimize_all_candidates(
            threshold=6.0, min_usage=10, max_candidates=2
        )
        assert len(results) <= 2

    def test_returns_empty_when_no_candidates(self, optimizer, registry):
        # Create block with high scores
        block = registry.create_block("good_blk", "anti_pattern", "content")
        for _ in range(12):
            uid = registry.record_usage("tpl", [block.block_id], "writer", "default")
            registry.update_usage_score(uid, 9.0)

        results = optimizer.optimize_all_candidates(threshold=6.0, min_usage=10)
        assert len(results) == 0
