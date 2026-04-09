"""Regression tests for quality_score persistence through the pipeline.

Background
----------
Before this fix, ``NovelPipeline.generate_chapters`` built a ``ch_data`` dict
with only five fields (chapter_number / title / full_text / word_count /
status) and dropped everything that ``QualityReviewer`` wrote into
``state["current_chapter_quality"]``. Every chapter persisted with
``quality_score=None`` even when it should have been LLM-scored.

These tests exercise the extracted helper ``_build_chapter_record`` directly
so we do not need to run the full chapter graph. Round-trip tests verify
persistence through both ``FileManager`` (disk) and ``_save_checkpoint`` /
``_load_checkpoint`` (cross-process state travel).

Four states are distinguished via two orthogonal flags:

    | case             | rule_checked | scored_by_llm |
    | LLM-scored       | True         | True          |
    | Budget mode      | True         | False         |
    | Reviewer crashed | False        | False         |
    | Malformed report | False        | False         |

``rule_checked=False`` is the only signal that the reviewer never produced a
structured report; ``scored_by_llm`` alone does not distinguish budget mode
from a crash, because both produce ``scored_by_llm=False``.
"""

from __future__ import annotations

import pytest

from src.novel.pipeline import NovelPipeline
from src.novel.storage.file_manager import FileManager


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


_CH_TEXT = (
    "第五章  风起\n\n"
    "林牧站在断崖边，望着远方翻涌的云海，心中思绪万千。"
    "昨日一战的余波尚未散去，他紧握的剑柄依旧带着血腥气。"
    "这一次，他终于明白了师父临终的那句话。" * 10
)


def _make_state_with_quality(quality_report: dict | None) -> dict:
    """Build the minimal state dict ``_build_chapter_record`` reads from."""
    return {"current_chapter_quality": quality_report}


def _full_scored_report() -> dict:
    """A realistic QualityReviewer output for an LLM-scored chapter."""
    return {
        "rule_check": {"passed": True, "violations": []},
        "scores": {
            "plot_coherence": 7.0,
            "writing_quality": 6.5,
            "character_portrayal": 7.5,
            "ai_flavor_score": 6.0,
        },
        "retention_scores": {
            "information_gain": 7.0,
            "conflict_effectiveness": 7.5,
            "memorable_moment": 6.5,
            "cliffhanger_strength": 8.0,
            "protagonist_appeal": 7.0,
        },
        "need_rewrite": False,
        "rewrite_reason": None,
        "suggestions": [],
    }


def _budget_mode_report() -> dict:
    """A realistic budget-mode report: rule_check ran, scores empty."""
    return {
        "rule_check": {"passed": True, "violations": []},
        "scores": {},
        "retention_scores": {},
        "need_rewrite": False,
        "rewrite_reason": None,
        "suggestions": [],
    }


def _rule_failed_report() -> dict:
    """A rule_check failure — scores may be empty (budget mode)."""
    return {
        "rule_check": {
            "passed": False,
            "violations": [
                {"rule": "no_modern_term", "detail": "出现'手机'"},
            ],
        },
        "scores": {},
        "retention_scores": {},
        "need_rewrite": True,
        "rewrite_reason": "规则检查未通过",
        "suggestions": ["移除现代词汇"],
    }


# ---------------------------------------------------------------------------
# Unit tests: _build_chapter_record
# ---------------------------------------------------------------------------


class TestBuildChapterRecordScored:
    """Case 1: LLM-scored chapter (ch5-style)."""

    def test_quality_score_is_average_of_scores(self):
        state = _make_state_with_quality(_full_scored_report())

        ch_data = NovelPipeline._build_chapter_record(
            state=state,
            ch_num=5,
            ch_title="第五章 风起",
            chapter_text=_CH_TEXT,
        )

        # Average of 7.0 + 6.5 + 7.5 + 6.0 = 27.0 / 4 = 6.75
        assert ch_data["quality_score"] == 6.75

    def test_scored_by_llm_flag_true(self):
        state = _make_state_with_quality(_full_scored_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=5, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["scored_by_llm"] is True

    def test_preserves_quality_scores_dict(self):
        report = _full_scored_report()
        state = _make_state_with_quality(report)
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=5, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["quality_scores"] == report["scores"]
        # Explicit field-by-field check in case reference semantics change
        assert ch_data["quality_scores"]["plot_coherence"] == 7.0
        assert ch_data["quality_scores"]["writing_quality"] == 6.5
        assert ch_data["quality_scores"]["character_portrayal"] == 7.5
        assert ch_data["quality_scores"]["ai_flavor_score"] == 6.0

    def test_preserves_retention_scores_dict(self):
        report = _full_scored_report()
        state = _make_state_with_quality(report)
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=5, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["retention_scores"] == report["retention_scores"]
        assert ch_data["retention_scores"]["cliffhanger_strength"] == 8.0
        assert ch_data["retention_scores"]["protagonist_appeal"] == 7.0

    def test_rule_passed_true(self):
        state = _make_state_with_quality(_full_scored_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=5, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["rule_passed"] is True

    def test_rule_checked_true(self):
        """Scored chapter always has rule_checked=True (reviewer ran)."""
        state = _make_state_with_quality(_full_scored_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=5, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["rule_checked"] is True

    def test_basic_fields_still_populated(self):
        state = _make_state_with_quality(_full_scored_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state,
            ch_num=5,
            ch_title="第五章 风起",
            chapter_text=_CH_TEXT,
        )
        assert ch_data["chapter_number"] == 5
        assert ch_data["title"] == "第五章 风起"
        assert ch_data["full_text"] == _CH_TEXT
        assert ch_data["status"] == "draft"
        assert ch_data["word_count"] > 0


class TestBuildChapterRecordBudgetMode:
    """Case 2: Budget-mode chapter — no LLM scores, rule_check only."""

    def test_quality_score_is_none(self):
        state = _make_state_with_quality(_budget_mode_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=3, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["quality_score"] is None

    def test_scored_by_llm_flag_false(self):
        state = _make_state_with_quality(_budget_mode_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=3, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["scored_by_llm"] is False

    def test_quality_scores_is_none(self):
        state = _make_state_with_quality(_budget_mode_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=3, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["quality_scores"] is None

    def test_retention_scores_is_none(self):
        state = _make_state_with_quality(_budget_mode_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=3, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["retention_scores"] is None

    def test_rule_passed_true(self):
        state = _make_state_with_quality(_budget_mode_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=3, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["rule_passed"] is True

    def test_rule_checked_true(self):
        """Budget mode still ran rule_check — rule_checked must be True."""
        state = _make_state_with_quality(_budget_mode_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=3, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["rule_checked"] is True

    def test_distinguishes_from_crashed_reviewer(self):
        """Budget mode must be distinguishable from crashed reviewer.

        Both produce ``scored_by_llm=False`` and ``quality_score=None``. The
        distinguishing field is ``rule_checked``: True in budget mode (rule
        check still ran, just LLM scoring skipped), False when the reviewer
        crashed and produced no structured report at all.
        """
        budget_state = _make_state_with_quality(_budget_mode_report())
        crashed_state = _make_state_with_quality(None)

        budget_ch = NovelPipeline._build_chapter_record(
            state=budget_state, ch_num=3, ch_title="X", chapter_text=_CH_TEXT
        )
        crashed_ch = NovelPipeline._build_chapter_record(
            state=crashed_state, ch_num=3, ch_title="X", chapter_text=_CH_TEXT
        )

        # Overlap: both skip LLM scoring, so these fields match.
        assert budget_ch["quality_score"] is None
        assert crashed_ch["quality_score"] is None
        assert budget_ch["scored_by_llm"] is False
        assert crashed_ch["scored_by_llm"] is False

        # The actual distinguishing signal — must differ.
        assert budget_ch["rule_checked"] is True
        assert crashed_ch["rule_checked"] is False
        assert budget_ch["rule_checked"] != crashed_ch["rule_checked"]


class TestBuildChapterRecordMissingReport:
    """Case 3: Missing quality report entirely (reviewer crashed / skipped)."""

    def test_none_report_does_not_crash(self):
        state = _make_state_with_quality(None)
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=1, ch_title="X", chapter_text=_CH_TEXT
        )
        # Just building it should not raise — that is the point.
        assert ch_data["chapter_number"] == 1

    def test_missing_key_does_not_crash(self):
        """state does not even have the current_chapter_quality key."""
        state: dict = {}
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=1, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["quality_score"] is None
        assert ch_data["scored_by_llm"] is False
        assert ch_data["quality_scores"] is None
        assert ch_data["retention_scores"] is None
        # Defaults to True when no rule_check signal present — safer than
        # falsely flagging a chapter as rule-violating.
        assert ch_data["rule_passed"] is True

    def test_none_report_all_quality_fields_safe(self):
        state = _make_state_with_quality(None)
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=1, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["quality_score"] is None
        assert ch_data["quality_scores"] is None
        assert ch_data["retention_scores"] is None
        assert ch_data["scored_by_llm"] is False
        assert ch_data["rule_passed"] is True

    def test_empty_dict_report(self):
        """Pathological: reviewer wrote an empty dict — should also be safe."""
        state = _make_state_with_quality({})
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=1, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["quality_score"] is None
        assert ch_data["scored_by_llm"] is False
        assert ch_data["rule_passed"] is True


class TestBuildChapterRecordRuleFailed:
    """Case 4: Rule check failed."""

    def test_rule_passed_false(self):
        state = _make_state_with_quality(_rule_failed_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=7, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["rule_passed"] is False

    def test_rule_failed_still_has_none_score(self):
        """A failed rule check in budget mode still has no score."""
        state = _make_state_with_quality(_rule_failed_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=7, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["quality_score"] is None
        assert ch_data["scored_by_llm"] is False

    def test_rule_failed_with_llm_scores(self):
        """Rule failed but LLM also scored — rare but possible."""
        report = _full_scored_report()
        report["rule_check"] = {"passed": False, "violations": [{"rule": "x"}]}
        state = _make_state_with_quality(report)

        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=5, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["rule_passed"] is False
        assert ch_data["quality_score"] == 6.75
        assert ch_data["scored_by_llm"] is True


class TestBuildChapterRecordMalformed:
    """Case 5: Reviewer returns malformed output (non-dict fields, bad values).

    The whole point of the helper is resilience when the reviewer contract is
    violated. These tests lock in that any non-dict report shape is treated as
    missing rather than crashing the pipeline.
    """

    def test_report_is_list_does_not_crash(self):
        state = _make_state_with_quality(["error", "traceback"])  # type: ignore[arg-type]
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=1, ch_title="X", chapter_text=_CH_TEXT
        )
        # Everything falls back to the "no report" shape.
        assert ch_data["quality_score"] is None
        assert ch_data["scored_by_llm"] is False
        assert ch_data["rule_checked"] is False
        assert ch_data["rule_passed"] is True

    def test_report_is_string_does_not_crash(self):
        state = _make_state_with_quality("reviewer failed")  # type: ignore[arg-type]
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=1, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["quality_score"] is None
        assert ch_data["scored_by_llm"] is False
        assert ch_data["rule_checked"] is False

    def test_scores_is_list_not_dict(self):
        """Reviewer wrote scores as a list of floats — treat as missing."""
        state = _make_state_with_quality(
            {
                "rule_check": {"passed": True},
                "scores": [7.0, 6.5, 7.5, 6.0],  # type: ignore[dict-item]
            }
        )
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=5, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["quality_score"] is None
        assert ch_data["scored_by_llm"] is False
        # rule_check was still present, so rule_checked is True.
        assert ch_data["rule_checked"] is True
        assert ch_data["rule_passed"] is True

    def test_scores_contains_non_numeric_values(self):
        """Mixed numeric + string entries — average numeric ones, skip rest."""
        state = _make_state_with_quality(
            {
                "rule_check": {"passed": True},
                "scores": {
                    "plot_coherence": 7.0,
                    "writing_quality": "invalid",  # should be dropped
                    "character_portrayal": 6.0,
                    "ai_flavor_score": None,  # should be dropped
                },
            }
        )
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=5, ch_title="X", chapter_text=_CH_TEXT
        )
        # Average of the two valid values: (7.0 + 6.0) / 2 = 6.5
        assert ch_data["quality_score"] == 6.5
        # scores dict was non-empty, so flag is True (the helper reports what
        # the reviewer intended even if some entries were bad).
        assert ch_data["scored_by_llm"] is True

    def test_scores_all_non_numeric(self):
        """If no numeric values, quality_score is None but scored_by_llm True."""
        state = _make_state_with_quality(
            {
                "rule_check": {"passed": True},
                "scores": {"plot_coherence": "bad", "writing_quality": None},
            }
        )
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=5, ch_title="X", chapter_text=_CH_TEXT
        )
        assert ch_data["quality_score"] is None
        assert ch_data["scored_by_llm"] is True  # scores dict was non-empty

    def test_rule_check_is_not_a_dict(self):
        """rule_check was written as a bool or string — treat as missing."""
        state = _make_state_with_quality(
            {"rule_check": True, "scores": {}}  # type: ignore[dict-item]
        )
        ch_data = NovelPipeline._build_chapter_record(
            state=state, ch_num=1, ch_title="X", chapter_text=_CH_TEXT
        )
        # rule_check was not a dict, so rule_checked is False and we fall back
        # to the safe default (rule_passed=True so we don't falsely flag).
        assert ch_data["rule_checked"] is False
        assert ch_data["rule_passed"] is True


# ---------------------------------------------------------------------------
# Integration: persistence round-trip via FileManager
# ---------------------------------------------------------------------------


class TestPersistenceRoundTrip:
    """Case 5: ch_data -> FileManager.save_chapter -> load_chapter -> fields survive."""

    @pytest.fixture
    def tmp_workspace(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        return str(ws)

    def test_scored_chapter_round_trip(self, tmp_workspace):
        state = _make_state_with_quality(_full_scored_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state,
            ch_num=5,
            ch_title="第五章 风起",
            chapter_text=_CH_TEXT,
        )

        fm = FileManager(tmp_workspace)
        novel_id = "test_novel_scored"
        fm.save_chapter(novel_id, 5, ch_data)

        loaded = fm.load_chapter(novel_id, 5)
        assert loaded is not None
        assert loaded["chapter_number"] == 5
        assert loaded["title"] == "第五章 风起"
        assert loaded["quality_score"] == 6.75
        assert loaded["scored_by_llm"] is True
        assert loaded["rule_passed"] is True
        assert loaded["quality_scores"]["plot_coherence"] == 7.0
        assert loaded["quality_scores"]["writing_quality"] == 6.5
        assert loaded["retention_scores"]["cliffhanger_strength"] == 8.0
        # full_text is loaded from the .txt sidecar, not the JSON
        assert loaded["full_text"] == _CH_TEXT

    def test_budget_mode_chapter_round_trip(self, tmp_workspace):
        state = _make_state_with_quality(_budget_mode_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state,
            ch_num=3,
            ch_title="第三章 暗流",
            chapter_text=_CH_TEXT,
        )

        fm = FileManager(tmp_workspace)
        novel_id = "test_novel_budget"
        fm.save_chapter(novel_id, 3, ch_data)

        loaded = fm.load_chapter(novel_id, 3)
        assert loaded is not None
        assert loaded["quality_score"] is None
        assert loaded["scored_by_llm"] is False
        assert loaded["quality_scores"] is None
        assert loaded["retention_scores"] is None
        assert loaded["rule_passed"] is True

    def test_crashed_reviewer_round_trip(self, tmp_workspace):
        state = _make_state_with_quality(None)
        ch_data = NovelPipeline._build_chapter_record(
            state=state,
            ch_num=1,
            ch_title="第一章 起航",
            chapter_text=_CH_TEXT,
        )

        fm = FileManager(tmp_workspace)
        novel_id = "test_novel_crashed"
        fm.save_chapter(novel_id, 1, ch_data)

        loaded = fm.load_chapter(novel_id, 1)
        assert loaded is not None
        assert loaded["quality_score"] is None
        assert loaded["scored_by_llm"] is False
        assert loaded["quality_scores"] is None
        assert loaded["retention_scores"] is None
        assert loaded["rule_passed"] is True

    def test_rule_failed_round_trip(self, tmp_workspace):
        state = _make_state_with_quality(_rule_failed_report())
        ch_data = NovelPipeline._build_chapter_record(
            state=state,
            ch_num=7,
            ch_title="第七章 歧路",
            chapter_text=_CH_TEXT,
        )

        fm = FileManager(tmp_workspace)
        novel_id = "test_novel_rule_failed"
        fm.save_chapter(novel_id, 7, ch_data)

        loaded = fm.load_chapter(novel_id, 7)
        assert loaded is not None
        assert loaded["rule_passed"] is False
        assert loaded["quality_score"] is None
        assert loaded["scored_by_llm"] is False


# ---------------------------------------------------------------------------
# Integration: checkpoint round-trip (cross-process state travel)
# ---------------------------------------------------------------------------


class TestCheckpointRoundTrip:
    """Case 6: ch_data in state["chapters"] must survive checkpoint persistence.

    This is distinct from FileManager round-trip: the checkpoint is what
    travels cross-process when ``--resume`` is used, and it's the path where
    ``_save_checkpoint`` strips ``full_text`` but should keep the new
    quality fields. If quality fields got stripped here, a resumed pipeline
    would lose all scoring history.
    """

    @pytest.fixture
    def tmp_workspace(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        return str(ws)

    def _build_state_with_chapter(self, report: dict | None, ch_num: int) -> dict:
        ch_data = NovelPipeline._build_chapter_record(
            state={"current_chapter_quality": report},
            ch_num=ch_num,
            ch_title=f"第{ch_num}章",
            chapter_text=_CH_TEXT,
        )
        return {
            "novel_id": "test_novel_ckpt",
            "current_chapter_quality": report,
            "chapters": [ch_data],
            "current_chapter": ch_num,
        }

    def test_scored_chapter_survives_checkpoint(self, tmp_workspace):
        state = self._build_state_with_chapter(_full_scored_report(), ch_num=5)

        pipe = NovelPipeline(workspace=tmp_workspace)
        pipe._save_checkpoint("test_novel_ckpt", state)
        loaded = pipe._load_checkpoint("test_novel_ckpt")

        assert loaded is not None
        assert len(loaded["chapters"]) == 1
        ch = loaded["chapters"][0]

        # Full text is stripped by design (lives in .txt sidecar).
        assert "full_text" not in ch
        # But all quality fields must survive.
        assert ch["quality_score"] == 6.75
        assert ch["scored_by_llm"] is True
        assert ch["rule_checked"] is True
        assert ch["rule_passed"] is True
        assert ch["quality_scores"]["plot_coherence"] == 7.0
        assert ch["retention_scores"]["cliffhanger_strength"] == 8.0

    def test_budget_mode_chapter_survives_checkpoint(self, tmp_workspace):
        state = self._build_state_with_chapter(_budget_mode_report(), ch_num=3)

        pipe = NovelPipeline(workspace=tmp_workspace)
        pipe._save_checkpoint("test_novel_ckpt", state)
        loaded = pipe._load_checkpoint("test_novel_ckpt")

        ch = loaded["chapters"][0]
        assert ch["quality_score"] is None
        assert ch["scored_by_llm"] is False
        assert ch["rule_checked"] is True  # rule_check still ran in budget mode
        assert ch["rule_passed"] is True
        assert ch["quality_scores"] is None
        assert ch["retention_scores"] is None

    def test_crashed_reviewer_survives_checkpoint(self, tmp_workspace):
        state = self._build_state_with_chapter(None, ch_num=1)

        pipe = NovelPipeline(workspace=tmp_workspace)
        pipe._save_checkpoint("test_novel_ckpt", state)
        loaded = pipe._load_checkpoint("test_novel_ckpt")

        ch = loaded["chapters"][0]
        assert ch["quality_score"] is None
        assert ch["scored_by_llm"] is False
        assert ch["rule_checked"] is False  # this is the distinguishing field
        assert ch["rule_passed"] is True  # safe default


# ---------------------------------------------------------------------------
# Feedback rewrite path invalidates stale quality fields
# ---------------------------------------------------------------------------


class TestFeedbackRewriteInvalidation:
    """Rewriting a chapter must not leave stale quality scores in place.

    The old scores were computed against the old text. After rewrite, both
    the on-disk JSON and the in-memory ``state["chapters"]`` entry must null
    out the quality fields so downstream code knows the chapter needs
    re-scoring.
    """

    def test_in_memory_state_entry_invalidated_after_rewrite(self):
        """Simulate the in-state upsert that apply_feedback performs."""
        # Start with a scored ch_data in state (as after normal generation).
        original_state = _make_state_with_quality(_full_scored_report())
        original_ch = NovelPipeline._build_chapter_record(
            state=original_state,
            ch_num=5,
            ch_title="第五章 风起",
            chapter_text=_CH_TEXT,
        )
        state = {"chapters": [original_ch]}

        # Pre-condition: the chapter was fully scored.
        assert state["chapters"][0]["quality_score"] == 6.75
        assert state["chapters"][0]["scored_by_llm"] is True
        assert state["chapters"][0]["rule_checked"] is True

        # Now simulate apply_feedback's rewrite upsert (copy from pipeline.py:2069+).
        new_text = "完全不同的重写后的文本" * 20
        new_title = "第五章 新方向"
        for ch_data in state["chapters"]:
            if ch_data.get("chapter_number") == 5:
                ch_data["full_text"] = new_text
                ch_data["word_count"] = len(new_text)
                ch_data["title"] = new_title
                ch_data["quality_score"] = None
                ch_data["quality_scores"] = None
                ch_data["retention_scores"] = None
                ch_data["rule_passed"] = True
                ch_data["rule_checked"] = False
                ch_data["scored_by_llm"] = False
                break

        # Post-condition: quality fields invalidated, text updated.
        updated = state["chapters"][0]
        assert updated["full_text"] == new_text
        assert updated["title"] == new_title
        assert updated["quality_score"] is None
        assert updated["quality_scores"] is None
        assert updated["retention_scores"] is None
        assert updated["scored_by_llm"] is False
        # rule_checked=False marks this as "needs re-scoring", the same signal
        # a crashed reviewer would produce.
        assert updated["rule_checked"] is False


# ---------------------------------------------------------------------------
# Pydantic model contract: None is now an accepted value
# ---------------------------------------------------------------------------


class TestPydanticChapterQualityScore:
    """Confirm that Chapter.quality_score now accepts None."""

    def _valid_outline(self) -> dict:
        return {
            "chapter_number": 1,
            "title": "X",
            "goal": "目标",
            "key_events": ["事件"],
            "estimated_words": 3000,
            "mood": "蓄力",
        }

    def test_none_is_accepted(self):
        from src.novel.models.chapter import Chapter
        from src.novel.models.novel import ChapterOutline

        outline = ChapterOutline(**self._valid_outline())
        ch = Chapter(
            chapter_number=1,
            title="X",
            outline=outline,
            quality_score=None,
        )
        assert ch.quality_score is None

    def test_default_is_none_not_zero(self):
        """Regression: default used to be 0.0 which conflated with 'scored 0'."""
        from src.novel.models.chapter import Chapter
        from src.novel.models.novel import ChapterOutline

        outline = ChapterOutline(**self._valid_outline())
        ch = Chapter(chapter_number=1, title="X", outline=outline)
        assert ch.quality_score is None

    def test_float_still_accepted(self):
        """Don't break callers that pass a float."""
        from src.novel.models.chapter import Chapter
        from src.novel.models.novel import ChapterOutline

        outline = ChapterOutline(**self._valid_outline())
        ch = Chapter(
            chapter_number=1,
            title="X",
            outline=outline,
            quality_score=6.75,
        )
        assert ch.quality_score == 6.75

    def test_out_of_range_still_rejected(self):
        """Boundaries ge/le still apply for non-None values."""
        from pydantic import ValidationError
        from src.novel.models.chapter import Chapter
        from src.novel.models.novel import ChapterOutline

        outline = ChapterOutline(**self._valid_outline())
        with pytest.raises(ValidationError):
            Chapter(
                chapter_number=1, title="X", outline=outline, quality_score=10.1
            )
        with pytest.raises(ValidationError):
            Chapter(
                chapter_number=1, title="X", outline=outline, quality_score=-0.1
            )
