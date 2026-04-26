"""Previous-chapter-tail summarizer (extracted from ChapterPlanner).

Compresses the tail of the prior chapter into a short structured summary
that can replace the raw text in any downstream LLM prompt. Used by:

* ``ChapterPlanner.propose_chapter_brief`` (chapter generation entry)
* ``NovelPipeline.polish_chapters`` (Reviewer-driven polish)
* ``NovelPipeline.apply_feedback`` rewrite path
* ``NovelPipeline.rewrite_affected_chapters`` (setting-change propagation)

Centralising the logic ensures every Writer-bound previous-chapter
context goes through the same verbatim-overlap guard, so a future caller
cannot accidentally reintroduce raw prior-chapter text to the prompt.
"""

from __future__ import annotations

import logging
from typing import Any

from src.llm.llm_client import LLMResponse

log = logging.getLogger(__name__)


_PREV_TAIL_SUMMARY_SYSTEM = (
    "你是小说大纲助手。只输出摘要，不含任何解释、前缀、Markdown 代码块或元信息。"
)

_PREV_TAIL_SUMMARY_USER = """\
请用不超过 150 字概括以下章节结尾段落的"叙事状态"，供下一章作者承接使用。

必须包含以下要素（缺失的可省略）：
- 时间/地点（当前场景在哪）
- 在场角色及其即时处境（情绪/行动/关系）
- 悬而未决的冲突或行动（尚未完成的事）
- 留下的钩子（暗示或悬念）

【禁止】
- 禁止复制原文任何完整句子或短语
- 禁止续写或推测下一步
- 必须是结构化的状态描述，不是故事讲述

【原文】
{previous_tail}

【输出】一段结构化摘要，150 字以内。"""


def has_long_verbatim_overlap(
    summary: str, source: str, min_len: int = 15
) -> bool:
    """Return True iff ``summary`` contains any ``source`` substring of
    length ``>= min_len``.

    Used to sanity-check LLM-produced "tail summaries": the prompt forbids
    copying, but models sometimes cheat. A single 15-char Chinese run
    carried over from the prior chapter is enough to seed cross-chapter
    verbatim repetition, which is exactly the failure mode this guard
    targets.
    """
    if not summary or not source:
        return False
    if len(summary) < min_len or len(source) < min_len:
        return False
    for i in range(len(summary) - min_len + 1):
        if summary[i : i + min_len] in source:
            return True
    return False


def summarize_previous_tail(
    llm: Any,
    previous_tail: str,
    *,
    max_chars: int = 200,
    min_overlap_len: int = 15,
) -> str:
    """Compress the previous chapter tail into a structured summary.

    The summary replaces the raw text in any downstream Writer / Reviewer
    prompt so the model cannot verbatim-copy prior chapter content.

    Args:
        llm: Sync ``LLMClient`` exposing ``chat(messages, temperature,
            json_mode, max_tokens) -> LLMResponse``.
        previous_tail: Raw tail string, typically the last ~500 chars of
            the prior chapter.
        max_chars: Hard cap on the returned summary length, regardless
            of what the LLM emits. Default 200.
        min_overlap_len: Minimum substring length that triggers the
            verbatim-overlap guard. Default 15. Setting this lower hurts
            naturally-recurring noun phrases; setting higher lets longer
            verbatim runs through.

    Returns:
        A non-verbatim summary (``<= max_chars``) or ``""`` when:
            * input is empty / whitespace-only
            * the input is short enough (<80 chars) that summarisation
              has no value — the stripped input is returned (truncated
              to ``max_chars``)
            * the LLM call fails or returns empty
            * a verbatim run of ``>= min_overlap_len`` chars is detected
              between the summary and the source (safer to return ``""``
              than a laundered copy of the prior text)
    """
    if not previous_tail:
        return ""
    stripped = previous_tail.strip()
    if not stripped:
        return ""
    if len(stripped) < 80:
        return stripped[:max_chars]

    messages = [
        {"role": "system", "content": _PREV_TAIL_SUMMARY_SYSTEM},
        {
            "role": "user",
            "content": _PREV_TAIL_SUMMARY_USER.format(previous_tail=stripped),
        },
    ]
    try:
        response: LLMResponse = llm.chat(
            messages, temperature=0.3, json_mode=False, max_tokens=300
        )
    except Exception as exc:
        log.warning("previous_tail 摘要 LLM 调用失败: %s", exc)
        return ""

    if not response or not response.content:
        return ""
    result = response.content.strip()[:max_chars]
    if not result:
        return ""
    if has_long_verbatim_overlap(result, stripped, min_len=min_overlap_len):
        log.warning(
            "summarize_previous_tail: detected >=%d-char verbatim overlap "
            "with source, discarding summary",
            min_overlap_len,
        )
        return ""
    return result


__all__ = [
    "summarize_previous_tail",
    "has_long_verbatim_overlap",
]
