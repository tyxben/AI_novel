"""ChapterSanitizer — 正文清洗管线。

去除 LLM 输出的 markdown 头、元注释、字数注释、首句与上章重复等噪声。
所有规则纯本地 (regex/SequenceMatcher)，零 LLM 成本。

集成点：在 Writer 输出落盘前调用 ``sanitize_chapter()``。
真实 bug case 见 ``tests/novel/utils/test_chapter_sanitizer.py``。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

log = logging.getLogger("novel.sanitizer")


# ---------------------------------------------------------------------------
# Regex patterns (compiled once)
# ---------------------------------------------------------------------------

# Markdown 标题: "# 第27章 三队布防", "## 章节" — 只删 *章节级* 标题，正文 ## 不动
_RE_MD_CHAPTER_HEAD = re.compile(
    r"^\s*#{1,3}\s*(?:第\s*[\d一二三四五六七八九十百零]+\s*章|Chapter\s*\d+).*$",
    re.MULTILINE,
)

# 元注释: "（全文约2350字）" / "（约2500字）" / "(全文约 1900 字)"
_RE_WORDCOUNT_NOTE = re.compile(
    r"[（(][^（()）]{0,8}约\s*[\d,]+\s*字[^（()）]{0,8}[)）]"
)

# 元注释: "【作者注：xxx】" / "（注：xxx）"
_RE_AUTHOR_NOTE = re.compile(
    r"[【（(](?:作者注|编者注|注)[：:][^】)）]{1,200}[】)）]"
)

# 元注释: "（待续）" / "(未完待续)"
_RE_TBC_NOTE = re.compile(r"[（(](?:待续|未完待续|to be continued)[)）]", re.IGNORECASE)

# 代码块围栏: ```...```
_RE_CODE_FENCE = re.compile(r"^\s*```[a-zA-Z0-9]*\s*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class SanitizeResult:
    """清洗结果。``cleaned`` 是处理后的文本，``actions`` 记录改动用于审计。"""

    cleaned: str
    actions: list[str] = field(default_factory=list)
    opening_duplicate: bool = False  # 与上章首句过于相似 — 上层应触发重写

    @property
    def changed(self) -> bool:
        return bool(self.actions)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


# 与上章开头相似度阈值。> 阈值 → 视为重复，标记给上层
_OPENING_DUP_THRESHOLD = 0.80
# 用于比较的开头长度
_OPENING_COMPARE_CHARS = 50


def sanitize_chapter(
    text: str,
    prev_chapter_text: str | None = None,
) -> SanitizeResult:
    """清洗章节正文。

    Args:
        text: Writer 输出的原始章节文本。
        prev_chapter_text: 上一章正文（用于检测首句重复）。可为 None。

    Returns:
        ``SanitizeResult``，``cleaned`` 字段是清洗后的文本。
    """
    if not text:
        return SanitizeResult(cleaned="")

    actions: list[str] = []
    out = text

    # 1. 删 markdown 章节标题
    new = _RE_MD_CHAPTER_HEAD.sub("", out)
    if new != out:
        actions.append("strip_markdown_chapter_head")
        out = new

    # 2. 删字数注释
    new = _RE_WORDCOUNT_NOTE.sub("", out)
    if new != out:
        actions.append("strip_wordcount_note")
        out = new

    # 3. 删作者注/编者注
    new = _RE_AUTHOR_NOTE.sub("", out)
    if new != out:
        actions.append("strip_author_note")
        out = new

    # 4. 删 "待续/未完待续"
    new = _RE_TBC_NOTE.sub("", out)
    if new != out:
        actions.append("strip_tbc_note")
        out = new

    # 5. 删代码块围栏（保留内容）
    new = _RE_CODE_FENCE.sub("", out)
    if new != out:
        actions.append("strip_code_fence")
        out = new

    # 6. 折叠多余空行（连续 3+ 空行 → 2 个）
    new = re.sub(r"(?:\n[ \t]*){3,}", "\n\n", out)
    if new != out:
        actions.append("collapse_blank_lines")
        out = new

    # 7. 头尾空白
    out = out.strip()

    # 8. 检测与上章开头相似
    opening_dup = False
    if prev_chapter_text:
        opening_dup = _opening_too_similar(out, prev_chapter_text)
        if opening_dup:
            actions.append("opening_duplicate_flagged")

    if actions:
        log.debug("ChapterSanitizer applied: %s", actions)

    return SanitizeResult(
        cleaned=out, actions=actions, opening_duplicate=opening_dup
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _opening_too_similar(curr: str, prev: str) -> bool:
    """比较 curr 开头与 prev 开头/结尾的相似度。

    覆盖三种 bug：
    - ch18 ↔ ch19 首句完全相同（curr_start vs prev_start，SequenceMatcher）
    - ch21 ↔ ch22 同（同上）
    - ch31 → ch32 叙事粘连（更松的 substring-overlap 检测）
    """
    curr_start = _normalize_for_compare(curr[:_OPENING_COMPARE_CHARS])
    if len(curr_start) < 10:
        return False
    prev_start = _normalize_for_compare(prev[:_OPENING_COMPARE_CHARS])
    prev_end = _normalize_for_compare(prev[-_OPENING_COMPARE_CHARS:])

    for candidate in (prev_start, prev_end):
        if not candidate or len(candidate) < 10:
            continue
        ratio = SequenceMatcher(None, curr_start, candidate).ratio()
        if ratio >= _OPENING_DUP_THRESHOLD:
            return True
        # Looser fallback: longest common substring of >= 12 chars
        # catches narrative continuation where author/LLM echoes the same
        # phrase but interleaves new words.
        match = SequenceMatcher(
            None, curr_start, candidate
        ).find_longest_match(0, len(curr_start), 0, len(candidate))
        if match.size >= 12:
            return True
        # Even looser: bigram Jaccard >= 0.4 catches paraphrased
        # continuations like ch31→ch32 (shares "林辰睁/倒悬/星辰/瞳孔/视野"
        # but interleaved with different words).
        if _bigram_jaccard(curr_start, candidate) >= 0.4:
            return True
    return False


def _bigrams(s: str) -> set[str]:
    return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else set()


def _bigram_jaccard(a: str, b: str) -> float:
    """Jaccard similarity over character bigrams."""
    sa, sb = _bigrams(a), _bigrams(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


_RE_WS = re.compile(r"\s+")
_RE_PUNCT = re.compile(
    r"[，。、！？；：…\u201c\u201d\u2018\u2019\"\.\,\!\?\;\:\(\)（）【】\[\]——\-]"
)


def _normalize_for_compare(s: str) -> str:
    """去标点、空白后再比较，避免标点差异影响判定。"""
    if not s:
        return ""
    s = _RE_PUNCT.sub("", s)
    s = _RE_WS.sub("", s)
    return s
