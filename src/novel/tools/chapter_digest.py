"""Chapter digest -- rule-based compression for quality scoring.

Extracts key elements from a chapter to create a compact digest (~500 chars)
that can be sent to LLM for scoring instead of the full text (saves 80%+ tokens).
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Internal regex helpers
# ---------------------------------------------------------------------------

_PARA_SPLIT_RE = re.compile(r"\n\s*\n|\n")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?\n])")
_DIALOGUE_LINE_RE = re.compile(
    r'^["\u201c\u300c]|[\u201c\u300c].*[\u201d\u300d]|'
    r".{0,6}(?:\u8bf4|\u9053|\u558a|\u7b11\u9053|\u51b7\u7b11\u9053|\u53f9\u9053|\u6012\u9053|\u4f4e\u58f0\u9053|\u9ad8\u58f0\u9053|\u51b7\u58f0\u9053)"
)
# Characters for dialogue verb detection: 说 道 喊 笑道 冷笑道 叹道 怒道 低声道 高声道 冷声道

_ACTION_VERBS_RE = re.compile(
    r"[\u62d4\u63e1\u6325\u51fa\u653b\u51fb\u8e0f\u8df3\u8d70\u8dd1\u98de\u8ffd\u8d76\u62ff\u6254\u7834\u6740\u6253\u8e22\u523a\u780d\u5c04\u6478]"
)
# Action verbs: 拔握挥出攻击踏跳走跑飞追赶拿扔破杀打踢刺砍射摸


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARA_SPLIT_RE.split(text) if p.strip()]


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_digest(
    chapter_text: str,
    characters: list[str] | None = None,
) -> dict[str, Any]:
    """Create a compact digest of *chapter_text* for LLM scoring.

    All operations are pure regex / string -- zero LLM calls.

    Args:
        chapter_text: Full chapter text.
        characters: Optional list of character names for key-sentence
            extraction.

    Returns:
        Dict with keys: ``opening``, ``closing``, ``dialogue_samples``,
        ``key_sentences``, ``action_summary``, ``stats``, ``digest_text``.
    """
    if not chapter_text or not chapter_text.strip():
        return {
            "opening": "",
            "closing": "",
            "dialogue_samples": [],
            "key_sentences": [],
            "action_summary": "",
            "stats": {
                "total_chars": 0,
                "paragraph_count": 0,
                "dialogue_ratio": 0.0,
                "unique_characters_mentioned": [],
            },
            "digest_text": "",
        }

    paragraphs = _split_paragraphs(chapter_text)
    sentences = _split_sentences(chapter_text)
    characters = characters or []

    # --- opening / closing ---
    opening_paras = paragraphs[:2]
    closing_paras = paragraphs[-4:] if len(paragraphs) > 4 else paragraphs
    opening = _truncate("\n".join(opening_paras), 200)
    closing = _truncate("\n".join(closing_paras), 500)

    # --- dialogue samples ---
    dialogue_lines: list[str] = []
    for sent in sentences:
        if _DIALOGUE_LINE_RE.search(sent):
            dialogue_lines.append(sent)
    dialogue_samples = dialogue_lines[:5]

    # --- key sentences (mentioning character names) ---
    key_sentences: list[str] = []
    if characters:
        for sent in sentences:
            for name in characters:
                if name in sent:
                    key_sentences.append(sent)
                    break
            if len(key_sentences) >= 10:
                break

    # --- action summary ---
    action_sentences: list[str] = []
    for sent in sentences:
        if _ACTION_VERBS_RE.search(sent):
            action_sentences.append(sent)
    action_summary = _truncate("".join(action_sentences[:5]), 200)

    # --- stats ---
    dialogue_char_count = sum(len(d) for d in dialogue_lines)
    total_chars = len(chapter_text)
    dialogue_ratio = dialogue_char_count / total_chars if total_chars > 0 else 0.0

    mentioned_chars: list[str] = []
    for name in characters:
        if name in chapter_text:
            mentioned_chars.append(name)

    stats = {
        "total_chars": total_chars,
        "paragraph_count": len(paragraphs),
        "dialogue_ratio": round(dialogue_ratio, 3),
        "unique_characters_mentioned": mentioned_chars,
    }

    # --- digest_text ---
    digest_parts: list[str] = [opening]
    if key_sentences:
        digest_parts.append("...")
        digest_parts.extend(key_sentences[:3])
    digest_parts.append("...")
    digest_parts.append(closing)
    digest_text = _truncate("\n".join(digest_parts), 800)

    return {
        "opening": opening,
        "closing": closing,
        "dialogue_samples": dialogue_samples,
        "key_sentences": key_sentences,
        "action_summary": action_summary,
        "stats": stats,
        "digest_text": digest_text,
    }
