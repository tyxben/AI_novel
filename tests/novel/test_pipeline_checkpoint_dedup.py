"""Tests for NovelPipeline checkpoint chapters list deduplication.

Covers Bug 3 fix: `state["chapters"]` previously accumulated duplicate entries
across regeneration runs. The pipeline now heals the list on every checkpoint
load and at the top of generate_chapters, and apply_feedback rewrites remove
all duplicate entries for the rewritten chapter number.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.novel.pipeline import NovelPipeline


# ---------------------------------------------------------------------------
# _dedupe_chapters_list unit tests
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline():
    """Pipeline with an isolated workspace (no config/LLM calls expected)."""
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.novel.pipeline.load_novel_config") as lc:
            lc.return_value = MagicMock()
            p = NovelPipeline(workspace=tmp)
            yield p


def test_dedupe_empty_list(pipeline):
    assert pipeline._dedupe_chapters_list([]) == []


def test_dedupe_none_safe(pipeline):
    # type: ignore[arg-type]
    assert pipeline._dedupe_chapters_list(None) == []  # noqa: E712


def test_dedupe_single_entry(pipeline):
    chapters = [{"chapter_number": 1, "word_count": 1000, "title": "开篇"}]
    result = pipeline._dedupe_chapters_list(chapters)
    assert len(result) == 1
    assert result[0]["title"] == "开篇"
    # Input not mutated
    assert chapters is not result


def test_dedupe_already_unique(pipeline):
    chapters = [
        {"chapter_number": 1, "word_count": 1000},
        {"chapter_number": 2, "word_count": 1500},
        {"chapter_number": 3, "word_count": 2000},
    ]
    result = pipeline._dedupe_chapters_list(chapters)
    assert [c["chapter_number"] for c in result] == [1, 2, 3]


def test_dedupe_two_duplicates_highest_wc_wins(pipeline):
    chapters = [
        {"chapter_number": 5, "word_count": 1000, "title": "旧版"},
        {"chapter_number": 5, "word_count": 2500, "title": "新版"},
    ]
    result = pipeline._dedupe_chapters_list(chapters)
    assert len(result) == 1
    assert result[0]["title"] == "新版"
    assert result[0]["word_count"] == 2500


def test_dedupe_three_duplicates_highest_wins(pipeline):
    chapters = [
        {"chapter_number": 12, "word_count": 1200, "title": "A"},
        {"chapter_number": 12, "word_count": 2400, "title": "B"},
        {"chapter_number": 12, "word_count": 1800, "title": "C"},
    ]
    result = pipeline._dedupe_chapters_list(chapters)
    assert len(result) == 1
    assert result[0]["title"] == "B"


def test_dedupe_mixed_duplicates_and_uniques_sorted(pipeline):
    chapters = [
        {"chapter_number": 3, "word_count": 900},
        {"chapter_number": 1, "word_count": 1000},
        {"chapter_number": 3, "word_count": 2000, "title": "winner"},
        {"chapter_number": 2, "word_count": 1500},
        {"chapter_number": 1, "word_count": 500},  # loser dup
    ]
    result = pipeline._dedupe_chapters_list(chapters)
    assert [c["chapter_number"] for c in result] == [1, 2, 3]
    ch3 = next(c for c in result if c["chapter_number"] == 3)
    assert ch3.get("title") == "winner"
    ch1 = next(c for c in result if c["chapter_number"] == 1)
    assert ch1["word_count"] == 1000


def test_dedupe_missing_word_count_treated_as_zero(pipeline):
    chapters = [
        {"chapter_number": 7, "title": "无字数"},
        {"chapter_number": 7, "word_count": 100, "title": "有字数"},
    ]
    result = pipeline._dedupe_chapters_list(chapters)
    assert len(result) == 1
    assert result[0]["title"] == "有字数"


def test_dedupe_preserves_entries_missing_chapter_number(pipeline):
    chapters = [
        {"chapter_number": 1, "word_count": 500},
        {"word_count": 999, "title": "no ch num"},
        {"chapter_number": 2, "word_count": 600},
        {"chapter_number": None, "title": "explicit none"},
    ]
    result = pipeline._dedupe_chapters_list(chapters)
    # 2 numbered + 2 preserved at tail
    assert len(result) == 4
    # Numbered come first and sorted
    assert result[0]["chapter_number"] == 1
    assert result[1]["chapter_number"] == 2
    # Preserved entries at tail, in original order
    tail_titles = [r.get("title") for r in result[2:]]
    assert "no ch num" in tail_titles
    assert "explicit none" in tail_titles


def test_dedupe_non_dict_entries_preserved(pipeline):
    chapters = [
        {"chapter_number": 1, "word_count": 500},
        "bogus string",
        42,
        {"chapter_number": 1, "word_count": 1000},
    ]
    result = pipeline._dedupe_chapters_list(chapters)
    # 1 dedup'd + 2 preserved non-dict entries
    assert len(result) == 3
    numbered = [c for c in result if isinstance(c, dict) and "chapter_number" in c]
    assert len(numbered) == 1
    assert numbered[0]["word_count"] == 1000


def test_dedupe_input_not_mutated(pipeline):
    chapters = [
        {"chapter_number": 1, "word_count": 500},
        {"chapter_number": 1, "word_count": 1000},
    ]
    original_len = len(chapters)
    pipeline._dedupe_chapters_list(chapters)
    assert len(chapters) == original_len


# ---------------------------------------------------------------------------
# _load_checkpoint integration
# ---------------------------------------------------------------------------


def test_load_checkpoint_heals_duplicates(pipeline):
    """Writing a dup'd checkpoint then loading should dedupe in place."""
    novel_id = "novel_testdup"
    novel_dir = Path(pipeline.workspace) / "novels" / novel_id
    novel_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = novel_dir / "checkpoint.json"

    raw = {
        "novel_id": novel_id,
        "chapters": [
            {"chapter_number": 1, "word_count": 2000, "title": "一"},
            {"chapter_number": 1, "word_count": 1500, "title": "旧一"},
            {"chapter_number": 2, "word_count": 2200, "title": "二"},
            {"chapter_number": 3, "word_count": 2100, "title": "三"},
            {"chapter_number": 2, "word_count": 1800, "title": "旧二"},
        ],
        "retry_counts": {},
    }
    ckpt_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    loaded = pipeline._load_checkpoint(novel_id)
    assert loaded is not None
    assert len(loaded["chapters"]) == 3
    nums = [c["chapter_number"] for c in loaded["chapters"]]
    assert nums == [1, 2, 3]
    ch1 = loaded["chapters"][0]
    assert ch1["title"] == "一"
    assert ch1["word_count"] == 2000


def test_load_checkpoint_no_chapters_key_safe(pipeline):
    novel_id = "novel_empty"
    novel_dir = Path(pipeline.workspace) / "novels" / novel_id
    novel_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = novel_dir / "checkpoint.json"
    ckpt_path.write_text(
        json.dumps({"novel_id": novel_id, "retry_counts": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    loaded = pipeline._load_checkpoint(novel_id)
    assert loaded is not None
    assert "chapters" not in loaded  # untouched


def test_load_checkpoint_chapters_not_list_safe(pipeline):
    novel_id = "novel_weird"
    novel_dir = Path(pipeline.workspace) / "novels" / novel_id
    novel_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = novel_dir / "checkpoint.json"
    ckpt_path.write_text(
        json.dumps({"chapters": {"weird": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    loaded = pipeline._load_checkpoint(novel_id)
    assert loaded is not None
    # dedupe only runs for list-type chapters
    assert loaded["chapters"] == {"weird": True}


# ---------------------------------------------------------------------------
# apply_feedback rewrite path: ensures duplicates are wiped on rewrite
# ---------------------------------------------------------------------------


class TestUpsertRewrittenChapter:
    """Exercise the real helper that apply_feedback delegates to.

    Bug 3 fix extracted this logic into a pure helper so tests can call
    the same code the pipeline calls — no re-implementation, no mocking
    of Writer / FeedbackAnalyzer / FileManager required.
    """

    def test_three_duplicates_collapse_to_one(self):
        """When state has 3 dup entries for ch5, rewrite leaves exactly 1."""
        from src.novel.pipeline import NovelPipeline

        state_chapters = [
            {"chapter_number": 5, "word_count": 1000, "title": "A", "quality_score": 8.0},
            {"chapter_number": 5, "word_count": 1500, "title": "B", "quality_score": 7.5},
            {"chapter_number": 5, "word_count": 1800, "title": "C", "quality_score": 9.0},
            {"chapter_number": 6, "word_count": 2000, "title": "六"},
        ]
        new_text = "完全重写后的第五章内容。" * 100
        new_title = "重写后的标题"

        result = NovelPipeline._upsert_rewritten_chapter(
            existing_chapters=state_chapters,
            ch_num=5,
            new_text=new_text,
            new_title=new_title,
        )

        ch5_entries = [c for c in result if c["chapter_number"] == 5]
        assert len(ch5_entries) == 1
        canonical = ch5_entries[0]
        assert canonical["title"] == new_title
        assert canonical["word_count"] == len(new_text)
        assert canonical["quality_score"] is None
        assert canonical["quality_scores"] is None
        assert canonical["retention_scores"] is None
        assert canonical["rule_passed"] is True
        assert canonical["rule_checked"] is False
        assert canonical["scored_by_llm"] is False

        # Ch6 completely untouched
        ch6_entries = [c for c in result if c["chapter_number"] == 6]
        assert len(ch6_entries) == 1
        assert ch6_entries[0]["title"] == "六"

    def test_single_entry_replaced(self):
        """Normal case: one existing entry for ch5, rewrite replaces it."""
        from src.novel.pipeline import NovelPipeline

        state_chapters = [
            {"chapter_number": 5, "word_count": 1000, "title": "Old", "quality_score": 7.5},
        ]
        result = NovelPipeline._upsert_rewritten_chapter(
            existing_chapters=state_chapters,
            ch_num=5,
            new_text="new body text" * 50,
            new_title="New Title",
        )

        assert len(result) == 1
        assert result[0]["chapter_number"] == 5
        assert result[0]["title"] == "New Title"
        assert result[0]["quality_score"] is None

    def test_zero_entries_creates_fresh_record(self):
        """CRITICAL regression: state had no entry for ch5, rewrite must
        still land a canonical entry in the list.

        This was the C1 finding in the code review — the previous
        implementation silently skipped the state update when no
        pre-existing entry was found. A chapter on disk without a
        matching state entry would lose its rewrite in-memory and
        the next checkpoint save would not reflect it.
        """
        from src.novel.pipeline import NovelPipeline

        state_chapters = [
            {"chapter_number": 1, "word_count": 500, "title": "第一章"},
            {"chapter_number": 2, "word_count": 600, "title": "第二章"},
        ]
        result = NovelPipeline._upsert_rewritten_chapter(
            existing_chapters=state_chapters,
            ch_num=5,  # no pre-existing ch5 entry!
            new_text="fresh ch5 content" * 30,
            new_title="Chapter Five",
        )

        # Original entries still present
        assert any(c["chapter_number"] == 1 for c in result)
        assert any(c["chapter_number"] == 2 for c in result)
        # AND ch5 now exists as a fresh entry
        ch5_entries = [c for c in result if c["chapter_number"] == 5]
        assert len(ch5_entries) == 1
        assert ch5_entries[0]["title"] == "Chapter Five"
        assert ch5_entries[0]["status"] == "draft"
        assert ch5_entries[0]["quality_score"] is None
        assert ch5_entries[0]["rule_checked"] is False
        # Result is sorted
        numbers = [c["chapter_number"] for c in result]
        assert numbers == sorted(numbers)

    def test_preserves_carryover_fields_from_first_match(self):
        """Non-content fields like chapter_id should carry over from the
        first matching entry (the canonical one), not be dropped."""
        from src.novel.pipeline import NovelPipeline

        state_chapters = [
            {
                "chapter_number": 5,
                "word_count": 1000,
                "title": "Old",
                "chapter_id": "abc-123",
                "generated_at": "2026-01-01T00:00:00Z",
            },
        ]
        result = NovelPipeline._upsert_rewritten_chapter(
            existing_chapters=state_chapters,
            ch_num=5,
            new_text="new text" * 100,
            new_title="New Title",
        )
        assert result[0]["chapter_id"] == "abc-123"
        assert result[0]["generated_at"] == "2026-01-01T00:00:00Z"
        assert result[0]["title"] == "New Title"

    def test_input_not_mutated(self):
        """Pure helper: the input list must not be mutated in place."""
        from src.novel.pipeline import NovelPipeline

        state_chapters = [
            {"chapter_number": 5, "word_count": 1000, "title": "Old", "quality_score": 7.0},
        ]
        snapshot = [dict(c) for c in state_chapters]

        NovelPipeline._upsert_rewritten_chapter(
            existing_chapters=state_chapters,
            ch_num=5,
            new_text="x" * 100,
            new_title="New",
        )

        # Input unchanged
        assert state_chapters == snapshot

    def test_result_is_sorted_by_chapter_number(self):
        """Result must be sorted ascending by chapter_number."""
        from src.novel.pipeline import NovelPipeline

        state_chapters = [
            {"chapter_number": 10, "word_count": 500, "title": "十"},
            {"chapter_number": 3, "word_count": 500, "title": "三"},
            {"chapter_number": 7, "word_count": 500, "title": "七"},
        ]
        result = NovelPipeline._upsert_rewritten_chapter(
            existing_chapters=state_chapters,
            ch_num=5,
            new_text="five" * 100,
            new_title="五",
        )
        numbers = [c["chapter_number"] for c in result]
        assert numbers == [3, 5, 7, 10]
