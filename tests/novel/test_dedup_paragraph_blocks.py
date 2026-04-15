"""测试 strip_repeated_paragraph_blocks — 章内段落整块复读去重。"""

from __future__ import annotations

import pytest

from src.novel.services.dedup_dialogue import (
    strip_repeated_paragraph_blocks,
)


def _para(text: str) -> str:
    """Helper: build a multi-paragraph text with blank-line separators."""
    return text


# ---------------------------------------------------------------------------
# Positive cases — duplication removed
# ---------------------------------------------------------------------------


class TestRemovesDuplicates:
    def test_adjacent_single_paragraph_dup(self):
        text = (
            "他抹掉脸上的血泥，转身，朝着断剑最后指引的方向——密林更深处，迈开了脚步。脚步很沉，但一步比一步稳。\n"
            "\n"
            "他抹掉脸上的血泥，转身，朝着断剑最后指引的方向——密林更深处，迈开了脚步。脚步很沉，但一步比一步稳。"
        )
        result = strip_repeated_paragraph_blocks(text)
        # 去重后只剩一份
        assert result.count("他抹掉脸上的血泥") == 1

    def test_adjacent_two_paragraph_block_dup(self):
        """实测 chapter_001.txt 场景：两段连续照搬。"""
        block = (
            "他抹掉脸上的血泥，转身，朝着断剑最后指引的方向——密林更深处，迈开了脚步。脚步很沉，但一步比一步稳。\n"
            "\n"
            "那柄断剑，或许斩不断仇人的脖子，但至少，能为他指出一条活路。"
        )
        text = block + "\n\n" + block
        result = strip_repeated_paragraph_blocks(text)
        assert result.count("他抹掉脸上的血泥") == 1
        assert result.count("那柄断剑") == 1

    def test_block_dup_with_small_gap(self):
        """两组重复之间隔了一段不相关内容，仍应被检出。"""
        text = (
            "段A：他走向深处，脚步沉重但坚定。\n"
            "\n"
            "段B：断剑无声地嵌在他腰间。\n"
            "\n"
            "中间段：晨雾缠绕，万籁俱寂。\n"
            "\n"
            "段A：他走向深处，脚步沉重但坚定。\n"
            "\n"
            "段B：断剑无声地嵌在他腰间。"
        )
        result = strip_repeated_paragraph_blocks(text)
        # 第二次的 A/B 被移除，中间段保留
        assert result.count("他走向深处") == 1
        assert result.count("断剑无声地嵌在他腰间") == 1
        assert result.count("晨雾缠绕") == 1


# ---------------------------------------------------------------------------
# Negative cases — legitimate content preserved
# ---------------------------------------------------------------------------


class TestPreservesLegitimate:
    def test_different_paragraphs_preserved(self):
        text = (
            "第一段讲述主角的决定，内容是完全独立的叙述。\n"
            "\n"
            "第二段是完全不同的内容，描述场景转换到城门口的情景。"
        )
        result = strip_repeated_paragraph_blocks(text)
        assert result == text

    def test_short_repeated_exclamations_preserved(self):
        """短句免检（<8 汉字），避免误伤"他笑了"这类。"""
        text = "他笑了。\n\n他笑了。"
        result = strip_repeated_paragraph_blocks(text)
        assert result == text  # 短句不参与判重

    def test_far_apart_same_paragraph_preserved(self):
        """相隔较远（>MAX_GAP）的相同段落保留 — 可能是作者意图的呼应。"""
        text = (
            "他走向深处，脚步沉重但坚定。\n"
            "\n"
            "第 2 段：场景描写甲。\n"
            "\n"
            "第 3 段：场景描写乙。\n"
            "\n"
            "第 4 段：场景描写丙。\n"
            "\n"
            "第 5 段：场景描写丁。\n"
            "\n"
            "他走向深处，脚步沉重但坚定。"
        )
        result = strip_repeated_paragraph_blocks(text)
        # 两次出现间隔 4 段（> MAX_GAP=3），保留
        assert result.count("他走向深处") == 2

    def test_empty_input(self):
        assert strip_repeated_paragraph_blocks("") == ""

    def test_single_paragraph(self):
        text = "只有一段内容，无从重复。"
        assert strip_repeated_paragraph_blocks(text) == text


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotent:
    def test_running_twice_is_stable(self):
        text = (
            "段A：完全相同的内容在这里反复。\n"
            "\n"
            "段A：完全相同的内容在这里反复。"
        )
        once = strip_repeated_paragraph_blocks(text)
        twice = strip_repeated_paragraph_blocks(once)
        assert once == twice
        assert once.count("段A") == 1
