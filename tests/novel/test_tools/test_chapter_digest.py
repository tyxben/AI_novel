"""Chapter digest unit tests.

Covers:
- Basic digest creation
- Opening/closing extraction
- Dialogue samples
- Key sentences with character names
- Digest text compactness
- Empty text handling
- Stats correctness
"""

from __future__ import annotations

import pytest

from src.novel.tools.chapter_digest import create_digest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_TEXT = (
    "清晨的阳光洒在窗台上，张三缓缓睁开眼睛。\n"
    "他看了一眼身旁的长剑，心中涌起一股豪情。\n\n"
    "\u201c今天就是决战的日子。\u201d张三说道。\n"
    "\u201c你确定准备好了吗？\u201d李四问道。\n"
    "\u201c生死有命，富贵在天。\u201d张三笑道。\n\n"
    "两人走出客栈，街上已经站满了围观的百姓。\n"
    "张三拔出长剑，剑身在阳光下闪烁着寒光。\n"
    "李四握紧了拳头，准备随时支援。\n\n"
    "敌人从对面走来，黑色的斗篷在风中猎猎作响。\n"
    "\u201c张三，今日便是你的死期！\u201d敌人喊道。\n"
    "张三冷笑一声，提剑迎了上去。\n\n"
    "一场激战之后，张三身上多了几道伤口。\n"
    "但最终，他还是将敌人击败了。\n"
    "李四跑上前来，扶住了摇摇欲坠的张三。\n"
    "\u201c赢了！我们赢了！\u201d李四激动地说道。"
)

_CHARACTERS = ["张三", "李四"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateDigest:
    def test_create_digest_basic(self) -> None:
        """Basic digest creation returns all expected keys."""
        digest = create_digest(_SAMPLE_TEXT, _CHARACTERS)
        expected_keys = {
            "opening", "closing", "dialogue_samples",
            "key_sentences", "action_summary", "stats", "digest_text",
        }
        assert expected_keys == set(digest.keys())

    def test_opening_closing_extraction(self) -> None:
        """Opening and closing are extracted from first/last paragraphs."""
        digest = create_digest(_SAMPLE_TEXT, _CHARACTERS)

        # Opening should start with the first paragraph content
        assert "清晨" in digest["opening"]
        # Closing should contain content from the last paragraph
        assert "赢了" in digest["closing"] or "李四" in digest["closing"]

    def test_dialogue_samples(self) -> None:
        """Dialogue samples are extracted correctly."""
        digest = create_digest(_SAMPLE_TEXT, _CHARACTERS)
        assert len(digest["dialogue_samples"]) > 0
        assert len(digest["dialogue_samples"]) <= 5

    def test_key_sentences_with_characters(self) -> None:
        """Key sentences contain character names."""
        digest = create_digest(_SAMPLE_TEXT, _CHARACTERS)
        assert len(digest["key_sentences"]) > 0
        for sent in digest["key_sentences"]:
            assert any(name in sent for name in _CHARACTERS), (
                f"Key sentence should mention a character: {sent}"
            )

    def test_digest_text_compact(self) -> None:
        """digest_text is shorter than the original text."""
        digest = create_digest(_SAMPLE_TEXT, _CHARACTERS)
        assert len(digest["digest_text"]) > 0
        assert len(digest["digest_text"]) <= 800

    def test_empty_text(self) -> None:
        """Empty text returns an empty digest with correct structure."""
        digest = create_digest("")
        assert digest["opening"] == ""
        assert digest["closing"] == ""
        assert digest["dialogue_samples"] == []
        assert digest["key_sentences"] == []
        assert digest["digest_text"] == ""
        assert digest["stats"]["total_chars"] == 0
        assert digest["stats"]["paragraph_count"] == 0

    def test_stats(self) -> None:
        """Stats contain correct metadata."""
        digest = create_digest(_SAMPLE_TEXT, _CHARACTERS)
        stats = digest["stats"]

        assert stats["total_chars"] == len(_SAMPLE_TEXT)
        assert stats["paragraph_count"] > 0
        assert 0.0 <= stats["dialogue_ratio"] <= 1.0
        # Both characters should be mentioned
        assert "张三" in stats["unique_characters_mentioned"]
        assert "李四" in stats["unique_characters_mentioned"]

    def test_no_characters_still_works(self) -> None:
        """Digest works when no character list is provided."""
        digest = create_digest(_SAMPLE_TEXT)
        assert digest["key_sentences"] == []
        assert digest["stats"]["unique_characters_mentioned"] == []

    def test_short_text_uses_same_opening_closing(self) -> None:
        """For very short text (<=2 paragraphs), opening and closing overlap."""
        short = "第一段内容。\n第二段内容。"
        digest = create_digest(short)
        assert digest["opening"] != ""
        assert digest["closing"] != ""

    def test_opening_closing_truncated(self) -> None:
        """Opening is capped at 200 chars, closing at 500 chars."""
        long_para = "这是一段很长的文字。" * 100
        text = long_para + "\n\n中间段落。\n\n" + long_para
        digest = create_digest(text)
        assert len(digest["opening"]) <= 203  # 200 + "..."
        assert len(digest["closing"]) <= 503  # 500 + "..."
