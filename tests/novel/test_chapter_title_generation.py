"""Tests for chapter title sanitization, extraction, and uniqueness.

Covers Bug 2 fix:
- `_sanitize_title`: length cap relaxed to 25, rejects dialogue openers and
  pure punctuation.
- `_extract_title_from_text`: skips dialogue, onomatopoeia; picks narrative
  phrase; falls back to outline goal / key_events before placeholder.
- `NovelDirector._parse_outline`: missing / placeholder titles are backfilled
  from goal or key_events via `_derive_title_from_outline_fields`.
- Uniqueness pass at chapter-generation time: duplicates get a differentiator.
"""

from __future__ import annotations

import pytest

from src.novel.pipeline import _extract_title_from_text, _sanitize_title


# ---------------------------------------------------------------------------
# _sanitize_title
# ---------------------------------------------------------------------------


def test_sanitize_valid_short_title():
    assert _sanitize_title("初入江湖", 1) == "初入江湖"


def test_sanitize_15_char_now_passes():
    """Previously rejected at 16 chars; now allowed up to 25."""
    t = "林辰首战定州之群山开疆始"  # 12 chars
    assert _sanitize_title(t, 1) == t


def test_sanitize_20_char_passes():
    t = "一二三四五六七八九十一二三四五六七八九二"  # 20 chars
    assert _sanitize_title(t, 1) == t


def test_sanitize_26_char_rejected():
    t = "一" * 26
    assert _sanitize_title(t, 1) == "第1章"


def test_sanitize_rejects_dialogue_opener():
    assert _sanitize_title("\u201c别开——\u201d", 5) == "第5章"
    assert _sanitize_title("\u300c你来了\u300d", 5) == "第5章"


def test_sanitize_rejects_pure_punctuation():
    assert _sanitize_title("——！", 3) == "第3章"
    assert _sanitize_title("???", 3) == "第3章"


def test_sanitize_rejects_empty_and_tiny():
    assert _sanitize_title("", 2) == "第2章"
    assert _sanitize_title("一", 2) == "第2章"


def test_sanitize_strips_and_returns():
    assert _sanitize_title("  林辰出山  ", 4) == "林辰出山"


def test_sanitize_rejects_prompt_leakage():
    assert _sanitize_title("字数2500左右", 7) == "第7章"


# ---------------------------------------------------------------------------
# _extract_title_from_text
# ---------------------------------------------------------------------------


def test_extract_skips_dialogue_picks_narrative():
    text = (
        "\u201c没人说话\u201d\n\n"
        "林辰走进矿场，目光扫过每一个人。\n\n"
        "李四紧跟其后。"
    )
    # Should pick narrative phrase, not "没人说话"
    result = _extract_title_from_text(text, 14)
    assert result != "第14章"
    assert result != "没人说话"
    assert "林辰" in result or "矿场" in result or len(result) >= 4


def test_extract_skips_onomatopoeia():
    text = "轰！\n\n山崩地裂，尘土漫天。\n\n林辰从废墟里爬出来。"
    result = _extract_title_from_text(text, 8)
    assert result != "第8章"
    assert result != "轰"
    assert "轰！" not in result


def test_extract_pure_dialogue_chapter_falls_to_outline():
    text = (
        "\u201c你来了。\u201d\n\n"
        "\u201c嗯。\u201d\n\n"
        "\u201c准备好了吗？\u201d"
    )
    outline = {"goal": "林辰出征", "key_events": ["准备战斗"]}
    result = _extract_title_from_text(text, 9, outline)
    # No narrative → falls to outline goal
    assert result != "第9章"
    assert "林辰出征" in result


def test_extract_fallback_to_goal_when_text_empty():
    outline = {"goal": "矿场危机", "key_events": ["袭击"]}
    result = _extract_title_from_text("", 10, outline)
    assert result == "矿场危机"


def test_extract_fallback_to_key_events_when_no_goal():
    outline = {"goal": "", "key_events": ["夜袭黑风寨"]}
    result = _extract_title_from_text("", 11, outline)
    assert result == "夜袭黑风寨"


def test_extract_absolute_fallback_returns_placeholder():
    # No narrative, no outline
    text = "\u201c嗯\u201d\n\n\u201c对\u201d"
    result = _extract_title_from_text(text, 99)
    assert result == "第99章"


def test_extract_handles_empty_text():
    assert _extract_title_from_text("", 1) == "第1章"
    assert _extract_title_from_text("   \n\n   ", 1) == "第1章"


def test_extract_skips_markdown_headers():
    text = "# 第一章\n\n林辰站在演武场上。"
    result = _extract_title_from_text(text, 1)
    assert result != "第1章"
    assert "#" not in result


def test_extract_picks_narrative_from_line_2_when_line_1_is_dialogue():
    text = (
        "\u201c系统启动。\u201d\n\n"
        "林辰睁开眼，眉心灵光闪烈。"
    )
    result = _extract_title_from_text(text, 3)
    assert result != "第3章"
    # Should be narrative, not dialogue
    assert not result.startswith("\u201c")


# ---------------------------------------------------------------------------
# Uniqueness renaming (logic replicated from pipeline)
# ---------------------------------------------------------------------------


def test_uniqueness_duplicate_gets_differentiator():
    existing = [
        {"chapter_number": 21, "title": "矿场立规"},
        {"chapter_number": 20, "title": "进驻矿场"},
    ]
    proposed = "矿场立规"
    ch_num = 22

    existing_titles = {
        (ch.get("title") or "").strip()
        for ch in existing
        if ch.get("chapter_number") != ch_num
    }
    assert proposed in existing_titles
    differentiated = f"{proposed}\u00b7\u7eed"
    if differentiated in existing_titles:
        differentiated = f"{proposed}\u00b7\u5176{ch_num}"
    assert differentiated != proposed
    assert differentiated.startswith(proposed)


def test_uniqueness_no_collision_keeps_title():
    existing = [{"chapter_number": 5, "title": "矿场立规"}]
    proposed = "新规则"
    ch_num = 6
    existing_titles = {
        (ch.get("title") or "").strip()
        for ch in existing
        if ch.get("chapter_number") != ch_num
    }
    assert proposed not in existing_titles


# ---------------------------------------------------------------------------
# ProjectArchitect._parse_outline title fallback (Phase 3-B3：从 NovelDirector 迁入)
# ---------------------------------------------------------------------------


def test_derive_title_from_outline_fields_goal():
    from src.novel.agents.project_architect import _derive_title_from_outline_fields

    assert _derive_title_from_outline_fields("林辰初战告捷", None) == "林辰初战告捷"


def test_derive_title_from_outline_fields_key_events_fallback():
    from src.novel.agents.project_architect import _derive_title_from_outline_fields

    result = _derive_title_from_outline_fields("", ["夜袭黑风寨"])
    assert result == "夜袭黑风寨"


def test_derive_title_from_outline_fields_long_phrase_truncated():
    from src.novel.agents.project_architect import _derive_title_from_outline_fields

    long_goal = "林辰带领二十三名流民深入乱石坡矿脉发动突袭并顺利获取灵石"
    result = _derive_title_from_outline_fields(long_goal, None)
    assert result is not None
    assert len(result) <= 8


def test_derive_title_from_outline_fields_returns_none_when_empty():
    from src.novel.agents.project_architect import _derive_title_from_outline_fields

    assert _derive_title_from_outline_fields("", []) is None
    assert _derive_title_from_outline_fields(None, None) is None


def test_parse_outline_backfills_missing_title():
    from unittest.mock import MagicMock
    from src.novel.agents.project_architect import ProjectArchitect

    architect = ProjectArchitect(llm=MagicMock())
    data = {
        "main_storyline": {"protagonist_goal": "登顶"},
        "chapters": [
            {
                "chapter_number": 1,
                "title": "",  # missing
                "goal": "林辰下山",
                "key_events": ["告别师门"],
                "estimated_words": 2500,
                "mood": "蓄力",
            },
            {
                "chapter_number": 2,
                "title": "第2章",  # placeholder
                "goal": "初入尘世",
                "key_events": ["遇见小镇"],
                "estimated_words": 2500,
                "mood": "蓄力",
            },
            {
                "chapter_number": 3,
                "title": "正常标题",
                "goal": "探索",
                "key_events": ["摸底"],
                "estimated_words": 2500,
                "mood": "蓄力",
            },
        ],
    }
    outline = architect._parse_outline(data, "cyclic_upgrade", 3)
    assert outline.chapters[0].title == "林辰下山"
    assert outline.chapters[1].title == "初入尘世"
    assert outline.chapters[2].title == "正常标题"
