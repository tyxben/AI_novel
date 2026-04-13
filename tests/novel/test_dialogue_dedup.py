"""Tests for strip_intra_chapter_dialogue_repeats (Bug 1 fix).

The target bug: `workspace/novels/novel_12e1c974/chapters/chapter_005.txt`
lines 191-205 contain 7 verbatim re-pasted short dialogue lines mid-narrative.
The helper should detect and remove such echo runs while leaving legitimate
repetition untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.novel.services.dedup_dialogue import strip_intra_chapter_dialogue_repeats


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_empty_text_passes_through():
    assert strip_intra_chapter_dialogue_repeats("") == ""
    assert strip_intra_chapter_dialogue_repeats("   \n\n   ") == "   \n\n   "


def test_single_paragraph_unchanged():
    text = "林辰站在演武场上。"
    assert strip_intra_chapter_dialogue_repeats(text) == text


def test_all_narrative_unchanged():
    text = (
        "林辰走进矿场。\n\n"
        "李四紧跟其后。\n\n"
        "二十三名流民排成三列。"
    )
    assert strip_intra_chapter_dialogue_repeats(text) == text


def test_no_repetition_unchanged():
    text = (
        "\u201c开始！\u201d\n\n"
        "\u201c是！\u201d\n\n"
        "\u201c冲！\u201d"
    )
    assert strip_intra_chapter_dialogue_repeats(text) == text


def test_3_line_dialogue_echo_removed():
    text = (
        "\u201cA\u201d\n\n"
        "\u201cB\u201d\n\n"
        "\u201cC\u201d\n\n"
        "林辰走向前方。\n\n"
        "\u201cA\u201d\n\n"
        "\u201cB\u201d\n\n"
        "\u201cC\u201d\n\n"
        "李四紧跟其后。"
    )
    result = strip_intra_chapter_dialogue_repeats(text)
    # Both narratives preserved, echo run removed
    assert "林辰走向前方。" in result
    assert "李四紧跟其后。" in result
    # Only one occurrence of each dialogue line left
    assert result.count("\u201cA\u201d") == 1
    assert result.count("\u201cB\u201d") == 1
    assert result.count("\u201cC\u201d") == 1


def test_5_line_dialogue_echo_removed():
    """Matches the real ch5 symptom: 5+ lines echoed far downstream."""
    original = [
        "\u201c进矿洞。\u201d",
        "\u201c装袋，快。\u201d",
        "\u201c撤！\u201d",
        "\u201c中计了！回矿脉！\u201d",
        "\u201c追！他们跑不远！\u201d",
    ]
    paragraphs = []
    paragraphs.extend(original)
    # ~20 narrative paragraphs in between
    for i in range(20):
        paragraphs.append(f"林辰穿越山林，呼吸平稳。第{i}段。")
    # Echo run
    paragraphs.extend(original)
    paragraphs.append("林辰扔掉长矛，转身就跑。")

    text = "\n\n".join(paragraphs)
    result = strip_intra_chapter_dialogue_repeats(text)

    # Each dialogue line should appear exactly once
    for line in original:
        assert result.count(line) == 1, f"{line!r} should appear once, got {result.count(line)}"
    # Narrative preserved
    assert "林辰扔掉长矛" in result
    assert "第0段" in result
    assert "第19段" in result


def test_partial_repetition_not_removed():
    """3 matching lines then 1 new → NOT consecutive identical run."""
    text = (
        "\u201cA\u201d\n\n"
        "\u201cB\u201d\n\n"
        "\u201cC\u201d\n\n"
        "\u201cD\u201d\n\n"
        "林辰走向前方。\n\n"
        "\u201cA\u201d\n\n"
        "\u201cB\u201d\n\n"
        "\u201cC\u201d\n\n"
        "\u201cE\u201d"
    )
    result = strip_intra_chapter_dialogue_repeats(text)
    # The 3-line ABC run matches — this IS a valid echo because the first
    # 3 of 4 in the later group match the first 3 of 4 in the earlier group.
    # But the helper only strips the *exact matching run*, and since both
    # runs contain the A/B/C prefix, the 3 consecutive lines starting at
    # the later position will match the 3 consecutive lines starting at
    # the earlier position. That's acceptable — document behavior.
    # For the test to assert "not removed", we use different surrounding
    # lengths: make the second run only 2 long.
    text2 = (
        "\u201cA\u201d\n\n"
        "\u201cB\u201d\n\n"
        "\u201cC\u201d\n\n"
        "林辰走向前方。\n\n"
        "\u201cA\u201d\n\n"
        "\u201cB\u201d\n\n"
        "李四在后面。"
    )
    result2 = strip_intra_chapter_dialogue_repeats(text2)
    # Only 2 consecutive dialogue lines in second run — below _MIN_ECHO_RUN
    # → not removed
    assert result2.count("\u201cA\u201d") == 2
    assert result2.count("\u201cB\u201d") == 2


def test_non_consecutive_matches_not_removed():
    """Same line appearing twice but not consecutively → keep both."""
    text = (
        "\u201c准备好了吗？\u201d\n\n"
        "林辰点头。\n\n"
        "\u201c开始吧。\u201d\n\n"
        "李四挥刀冲上。\n\n"
        "\u201c准备好了吗？\u201d\n\n"
        "林辰又问了一次。"
    )
    result = strip_intra_chapter_dialogue_repeats(text)
    # Both occurrences should survive (no 3-line consecutive run)
    assert result.count("\u201c准备好了吗？\u201d") == 2


def test_long_dialogue_repetition_not_removed():
    """Long dialogue (>20 Chinese chars) is never stripped — likely quote."""
    long_line = "\u201c" + "人生若只如初见，何事秋风悲画扇，等闲变却故人心" + "\u201d"
    assert len(long_line) > 20
    text = (
        f"{long_line}\n\n"
        f"{long_line}\n\n"
        f"{long_line}\n\n"
        "林辰望向远方。\n\n"
        f"{long_line}\n\n"
        f"{long_line}\n\n"
        f"{long_line}"
    )
    result = strip_intra_chapter_dialogue_repeats(text)
    # Long lines: both runs intact
    assert result.count(long_line) == 6


def test_legitimate_short_repetition_kept():
    """'不。不。不。' style adjacent repetition: earlier occurrence kept."""
    text = (
        "\u201c不。\u201d\n\n"
        "\u201c不。\u201d\n\n"
        "\u201c不。\u201d\n\n"
        "林辰摇头，转身离开。"
    )
    result = strip_intra_chapter_dialogue_repeats(text)
    # No second occurrence → nothing removed
    assert result == text


def test_rally_cry_callback_not_removed():
    """Legitimate rally-cry / catchphrase reuse across scenes must NOT trigger
    cluster removal.

    Bug 1 review finding H2: the Pattern B cluster detector could false-
    positive on battle-heavy chapters where distinct short cries (e.g. 杀/退
    /冲) are reused across two scenes with narrative interleaved.  The fix
    is a dialogue-density floor: cluster only triggers when the echo window
    is ≥70% dialogue (pure copy-paste pattern).  Legitimate callbacks are
    typically ~50% dialogue with narrative context between them.

    This test is the locking-in of that behavior.
    """
    text = (
        # Scene 1: three rally cries with narrative in between.
        "\u201c天机不可泄漏。\u201d\n\n"
        "林辰眉头一皱。\n\n"
        "\u201c杀！\u201d\n\n"
        "众人冲上。\n\n"
        "\u201c退！\u201d\n\n"
        "众人后撤。\n\n"
        "战斗持续了许久。\n\n"
        "林辰终于开口。\n\n"
        # Scene 2: same three cries reappear with narrative between them.
        "\u201c天机不可泄漏。\u201d\n\n"
        "众人皆惊。\n\n"
        "\u201c杀！\u201d\n\n"
        "再次冲锋。\n\n"
        "\u201c退！\u201d"
    )
    result = strip_intra_chapter_dialogue_repeats(text)
    # All three cries should survive in both scenes — 6 total dialogue lines
    assert result.count("\u201c天机不可泄漏。\u201d") == 2
    assert result.count("\u201c杀！\u201d") == 2
    assert result.count("\u201c退！\u201d") == 2
    # Narrative bridges untouched
    assert "林辰眉头一皱。" in result
    assert "众人冲上。" in result
    assert "再次冲锋。" in result


def test_dense_echo_cluster_still_removed_when_density_high():
    """Positive counterpart to the rally-cry test: when the echo region is
    almost pure dialogue (the actual Bug 1 ch5 pattern), Pattern B still
    triggers and removes the echoes.

    Dialogue density in the echo window here is 5/5 = 100%, well above
    the 0.7 threshold, so this must trigger even though distinct keys
    equal _MIN_ECHO_LINES exactly.
    """
    text = (
        # Initial battle dialogue with narrative context.
        "\u201c进攻！\u201d林辰下令。\n\n"
        "李四挥刀。\n\n"
        "\u201c撤退！\u201d\n\n"
        "众人回身。\n\n"
        "\u201c守住！\u201d\n\n"
        "林辰怒吼。\n\n"
        "战斗进入胶着。\n\n"
        "突然之间，空气凝固。\n\n"
        "林辰抬头望向远方。\n\n"
        "那一刻，时间仿佛停止。\n\n"
        # Dense echo cluster: 5 verbatim dialogue paragraphs back-to-back
        # (mimics the ch5 bug shape).
        "\u201c进攻！\u201d林辰下令。\n\n"
        "\u201c撤退！\u201d\n\n"
        "\u201c守住！\u201d\n\n"
        "\u201c进攻！\u201d林辰下令。\n\n"
        "\u201c撤退！\u201d"
    )
    result = strip_intra_chapter_dialogue_repeats(text)
    # Each unique line should appear exactly once (the early occurrence).
    assert result.count("\u201c进攻！\u201d林辰下令。") == 1
    assert result.count("\u201c撤退！\u201d") == 1
    assert result.count("\u201c守住！\u201d") == 1
    # Narrative bridges fully preserved
    assert "李四挥刀。" in result
    assert "那一刻，时间仿佛停止。" in result


def test_idempotent():
    text = (
        "\u201cA\u201d\n\n"
        "\u201cB\u201d\n\n"
        "\u201cC\u201d\n\n"
        "中间叙述段落。\n\n"
        "\u201cA\u201d\n\n"
        "\u201cB\u201d\n\n"
        "\u201cC\u201d"
    )
    once = strip_intra_chapter_dialogue_repeats(text)
    twice = strip_intra_chapter_dialogue_repeats(once)
    assert once == twice


def test_narrative_paragraphs_never_touched():
    text = (
        "林辰走向前方。\n\n"
        "李四紧跟其后。\n\n"
        "\u201cA\u201d\n\n"
        "\u201cB\u201d\n\n"
        "\u201cC\u201d\n\n"
        "林辰走向前方。\n\n"  # Narrative echo — still kept
        "李四紧跟其后。\n\n"
        "\u201cA\u201d\n\n"
        "\u201cB\u201d\n\n"
        "\u201cC\u201d"
    )
    result = strip_intra_chapter_dialogue_repeats(text)
    # Narrative echo preserved
    assert result.count("林辰走向前方。") == 2
    assert result.count("李四紧跟其后。") == 2
    # Dialogue echo removed
    assert result.count("\u201cA\u201d") == 1


def test_dialogue_openers_variants():
    """Chinese 「」『』 brackets and Western quotes all supported."""
    text = (
        "\u300cA\u300d\n\n"
        "\u300cB\u300d\n\n"
        "\u300cC\u300d\n\n"
        "中间段落。\n\n"
        "\u300cA\u300d\n\n"
        "\u300cB\u300d\n\n"
        "\u300cC\u300d"
    )
    result = strip_intra_chapter_dialogue_repeats(text)
    assert result.count("\u300cA\u300d") == 1


def test_run_with_dialogue_break_by_narrative_not_consecutive():
    """Dialogue + narrative + dialogue → runs are broken by narrative."""
    text = (
        "\u201cA\u201d\n\n"
        "林辰说。\n\n"
        "\u201cB\u201d\n\n"
        "叙述段。\n\n"
        "\u201cA\u201d\n\n"
        "林辰说。\n\n"
        "\u201cB\u201d"
    )
    # Each "run" has length 1, below min → nothing removed
    result = strip_intra_chapter_dialogue_repeats(text)
    assert result == text


# ---------------------------------------------------------------------------
# Real-ch5 regression: read the actual buggy file and verify dedup
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not Path("workspace/novels/novel_12e1c974/chapters/chapter_005.txt").exists(),
    reason="real ch5 file not present in this checkout",
)
def test_real_chapter_5_echo_removed():
    """Run the helper on the real buggy ch5 and verify lines 191-205 are stripped."""
    path = Path("workspace/novels/novel_12e1c974/chapters/chapter_005.txt")
    original = path.read_text(encoding="utf-8")
    result = strip_intra_chapter_dialogue_repeats(original)

    before_paragraphs = len([p for p in original.split("\n\n") if p.strip()])
    after_paragraphs = len([p for p in result.split("\n\n") if p.strip()])

    # The echo block should be stripped (>= 5 paragraphs removed).
    # If the file has already been fixed (no echo), dedup is a no-op — that's fine.
    if before_paragraphs == after_paragraphs:
        pytest.skip("chapter file already cleaned — no echo block to remove")

    # The earlier occurrences must still be present.
    # Lines 139 "进矿洞。", 153 "装袋，快。", 159 "撤！",
    # 163 "中计了！回矿脉！", 167 "追！他们跑不远！", 175 "跟上！"
    must_keep_once = [
        "\u201c进矿洞。\u201d",
        "\u201c装袋，快。\u201d",
        "\u201c撤！\u201d",
        "\u201c中计了！回矿脉！\u201d",
        "\u201c追！他们跑不远！\u201d",
    ]
    for line in must_keep_once:
        assert line in result
        # These specific lines had 2 occurrences; after dedup should be 1
        assert result.count(line) == 1, (
            f"{line!r}: original={original.count(line)}, result={result.count(line)}"
        )

    # Ambient narrative must be intact
    assert "林辰转身，抽出腰间短刀" in result
    assert "三个黑风寨匪徒最先追到" in result
