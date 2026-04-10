"""Post-generation intra-chapter dialogue echo detection.

Background: a small number of generated chapters (notably novel_12e1c974
chapter 5 lines 191-205) contained a cluster of verbatim re-pasted short
dialogue lines mid-narrative, likely introduced by a truncation-recovery
fragment carrying recycled LLM context that later survived hook-generator
splicing.

This module provides a surgical post-processing pass that detects and
removes a **dense cluster of echoed short dialogue lines** — a window
where 3+ distinct short dialogue lines all appear verbatim earlier in
the same chapter.  The *earlier* occurrence is always preserved.

Design choices:
- Conservative: only removes dialogue lines inside an "echo cluster" —
  a sliding window of at most ``_CLUSTER_WINDOW`` paragraphs containing
  at least ``_MIN_ECHO_LINES`` distinct echoed short dialogue lines
  (each appearing earlier in the chapter).  Individual repetition
  without a surrounding cluster is left alone (legitimate emphasis).
- Long dialogue (>20 Chinese chars) is never touched — it is almost
  certainly a legitimate quotation.
- Narrative paragraphs are never touched.
- The earlier occurrences are always kept.
- Idempotent: running it twice is safe.
- Pure local logic, no LLM calls.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("novel")


# Only LEFT-quote openers count as "start of a dialogue line".  U+201D (right
# double quote) and U+300D (right corner bracket) can appear at the start of a
# paragraph only when a closing quote got orphaned — that is usually a
# dialogue attribution fragment, not a new dialogue line, so we don't classify
# them as dialogue candidates.
_DIALOGUE_OPENERS = (
    "\u201c",  # left double quotation mark "
    "\u300c",  # left corner bracket 「
    "\u300e",  # left white corner bracket 『
    '"',
)

# Only short dialogue lines are candidates.  Long lines are assumed to be
# legitimate quotations.
_MAX_DIALOGUE_LEN_FOR_ECHO = 20

# Minimum consecutive-run length required before we call it a consecutive-run
# "echo" (used by the Pattern-1 detector).
_MIN_ECHO_RUN = 3

# Cluster detector parameters (Pattern-2).
#
# A cluster is a sliding window of at most ``_CLUSTER_WINDOW`` paragraphs
# containing at least ``_MIN_ECHO_LINES`` *distinct* short dialogue lines
# that each appear verbatim earlier in the chapter.  When detected, all
# echoed lines inside the cluster are removed.
_CLUSTER_WINDOW = 12
_MIN_ECHO_LINES = 3

# Dialogue density floor for cluster detection.  A genuine echo cluster is
# a DENSE stack of dialogue lines with almost no interleaved narrative (the
# LLM pasted recycled context verbatim).  Legitimate callback dialogue
# (rally cries, catchphrases repeated across scenes) is interleaved with
# narrative at normal prose rate, typically ~50% density.  Requiring >=70%
# dialogue inside the window spares legitimate callbacks while catching the
# copy-paste pattern observed in novel_12e1c974 chapter 5.
_MIN_CLUSTER_DIALOGUE_DENSITY = 0.7


def _count_chinese_chars(s: str) -> int:
    return sum(1 for c in s if "\u4e00" <= c <= "\u9fa5")


def _is_short_dialogue(para: str) -> bool:
    """Return True if ``para`` is a short dialogue line worth deduping."""
    if not para:
        return False
    stripped = para.strip()
    if not stripped:
        return False
    if stripped[0] not in _DIALOGUE_OPENERS:
        return False
    # Length cap: Chinese chars only (punctuation / quote marks don't count)
    if _count_chinese_chars(stripped) > _MAX_DIALOGUE_LEN_FOR_ECHO:
        return False
    return True


def _normalize(s: str) -> str:
    """Normalize a paragraph for echo-run comparison."""
    return re.sub(r"\s+", "", s.strip())


def strip_intra_chapter_dialogue_repeats(text: str) -> str:
    """Detect and remove echoed short dialogue lines within one chapter.

    Two detection patterns:

    **Pattern 1 — consecutive-run echo.**  A contiguous run of
    ``_MIN_ECHO_RUN`` or more short dialogue paragraphs that identically
    matches an earlier consecutive run in the chapter.  The later run is
    removed.

    **Pattern 2 — cluster echo.**  A sliding window of at most
    ``_CLUSTER_WINDOW`` paragraphs containing at least ``_MIN_ECHO_LINES``
    *distinct* short dialogue lines that each appear verbatim earlier
    in the chapter (where each individual earlier occurrence is
    outside the cluster window).  All echoed lines inside the cluster
    are removed.  Pattern 2 covers the case where the echoed lines are
    interleaved with brief narrative fragments or with each other in
    a different order from their original occurrences.

    Narrative paragraphs and long dialogue lines are always preserved.

    Returns the cleaned text.  If nothing was stripped, returns the
    original string unchanged.
    """
    if not text or not text.strip():
        return text

    # Split on blank lines (one or more) to preserve multi-paragraph layout.
    paragraphs = re.split(r"\n\s*\n", text)
    n = len(paragraphs)
    if n < _MIN_ECHO_RUN * 2:
        return text

    # Build normalized form + dialogue flag for every paragraph.
    norm = [_normalize(p) for p in paragraphs]
    is_dlg = [_is_short_dialogue(p) for p in paragraphs]

    # `drop[i]` = True means paragraph i should be removed (echo).
    drop = [False] * n

    # ------------------------------------------------------------------
    # Pattern 1: consecutive-run echo detection
    # ------------------------------------------------------------------
    i = 0
    while i < n:
        if not is_dlg[i]:
            i += 1
            continue

        # Find the length of the current dialogue run.
        run_end = i
        while run_end < n and is_dlg[run_end]:
            run_end += 1
        run_len = run_end - i

        if run_len < _MIN_ECHO_RUN:
            i = run_end
            continue

        # Look back for an earlier identical consecutive run.
        matched_start = -1
        for j in range(0, i):
            if j + run_len > i:
                break  # earlier run would overlap current
            if drop[j]:
                continue
            ok = True
            for k in range(run_len):
                if drop[j + k]:
                    ok = False
                    break
                if not is_dlg[j + k]:
                    ok = False
                    break
                if norm[j + k] != norm[i + k]:
                    ok = False
                    break
            if ok:
                matched_start = j
                break

        if matched_start >= 0:
            for k in range(run_len):
                drop[i + k] = True
            preview = " / ".join(paragraphs[i + k].strip() for k in range(run_len))
            log.info(
                "检测到章节对白复读，已移除 %d 段重复: %s",
                run_len,
                preview[:80],
            )
            i = run_end
            continue

        i = run_end

    # ------------------------------------------------------------------
    # Pattern 2: cluster echo detection
    # ------------------------------------------------------------------
    # Build a map of "first occurrence index" for every short dialogue
    # line, so we can cheaply ask "does this line appear earlier?".
    first_occurrence: dict[str, int] = {}
    for idx in range(n):
        if not is_dlg[idx]:
            continue
        key = norm[idx]
        if not key:
            continue
        if key not in first_occurrence:
            first_occurrence[key] = idx

    # A line at position ``idx`` is an "echo candidate" if it is a short
    # dialogue line AND its first occurrence is strictly before idx.
    echo_candidate = [False] * n
    for idx in range(n):
        if not is_dlg[idx]:
            continue
        if drop[idx]:
            continue
        key = norm[idx]
        if not key:
            continue
        first = first_occurrence.get(key, idx)
        if first < idx:
            echo_candidate[idx] = True

    # Slide a window of size _CLUSTER_WINDOW over the paragraphs and
    # count distinct echo-candidate lines whose first occurrence lies
    # OUTSIDE the window (i.e. truly earlier, not merely an adjacent dup).
    marked: list[int] = []
    start = 0
    while start < n:
        end = min(n, start + _CLUSTER_WINDOW)
        distinct_keys: set[str] = set()
        window_echo_positions: list[int] = []
        for idx in range(start, end):
            if not echo_candidate[idx]:
                continue
            key = norm[idx]
            first = first_occurrence[key]
            if first >= start:
                # First occurrence is inside the window → not a cluster echo
                continue
            distinct_keys.add(key)
            window_echo_positions.append(idx)

        if len(distinct_keys) >= _MIN_ECHO_LINES:
            # False-positive guard: a genuine echo cluster is DENSE dialogue
            # (copy-pasted LLM context); legitimate callback dialogue
            # (rally cries, catchphrases reused across scenes) is
            # interleaved with narrative at prose rate.  Compute dialogue
            # density in the window and skip if it looks like a callback.
            total_in_window = end - start
            dlg_in_window = sum(
                1 for idx in range(start, end) if is_dlg[idx]
            )
            if (
                total_in_window > 0
                and dlg_in_window / total_in_window
                < _MIN_CLUSTER_DIALOGUE_DENSITY
            ):
                start += 1
                continue

            # Cluster detected: mark all echoed positions in the window
            # for removal.  Leave narrative and non-echo dialogue intact.
            for idx in window_echo_positions:
                if not drop[idx]:
                    drop[idx] = True
                    marked.append(idx)
            # Skip past this window to avoid double-counting
            start = end
            continue

        start += 1

    if marked:
        preview = " / ".join(paragraphs[idx].strip() for idx in marked[:4])
        log.info(
            "检测到章节对白复读(cluster)，已移除 %d 段重复: %s",
            len(marked),
            preview[:80],
        )

    if not any(drop):
        return text

    kept = [paragraphs[i] for i in range(n) if not drop[i]]
    return "\n\n".join(kept)
