"""Writer post-processing helpers (extracted from Writer agent).

Pure post-processing functions that take raw chapter / scene text and
return cleaned text. None of these touch LLM or state — they're string
transforms only. Centralised here so:

* Writer.generate_chapter / rewrite_chapter / polish_chapter call them
  in the inner write loop (per-scene + chapter-level)
* The ``post_writer`` graph node calls ``sanitize_chapter_text`` as a
  chapter-level safety pass after Writer emits raw text
* Tests can import them directly without instantiating Writer

Functions:

* :func:`sanitize_chapter_text` — strip game-UI brackets / stat changes
* :func:`dedup_paragraphs` — three-tier paragraph dedup against earlier scenes
* :func:`check_character_names` — placeholder substitution + unknown-name warnings
* :func:`trim_to_hard_cap` — last-resort length enforcement at sentence boundaries

Backward compatibility:
    ``src/novel/agents/writer.py`` keeps thin wrappers
    (``_sanitize_chapter_text`` module alias and ``_deduplicate_paragraphs``
    / ``_check_character_names`` / ``_trim_to_hard_cap`` instance/static
    methods) so the ~30 existing tests that hit them via ``Writer`` /
    ``writer.X`` keep working.
"""

from __future__ import annotations

import logging
import re as _re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from src.novel.models.character import CharacterProfile

log = logging.getLogger("novel")


# ---------------------------------------------------------------------------
# Sanitize: strip game-UI elements
# ---------------------------------------------------------------------------

# Patterns for system UI elements that should not appear in narrative text
SYSTEM_UI_PATTERNS = [
    # Bracketed system messages: 【...】
    _re.compile(r"【[^】]{1,80}】"),
    # Loyalty/stat changes: 忠诚度：71→79, 兵煞值+8
    _re.compile(r"[一-龥]{2,8}[:：]\s*\d+\s*[→\-+]\s*\d+"),
    _re.compile(r"[一-龥]{2,8}\s*[+\-]\s*\d+\s*$", _re.MULTILINE),
]

# Allowlist of system messages that ARE part of the story (system-cultivation novel)
# These get kept; everything else gets stripped
SYSTEM_UI_ALLOWLIST = {
    "【叮！】",  # iconic system notification
}


def sanitize_chapter_text(text: str) -> str:
    """Strip game-UI elements from generated chapter text.

    The Writer sometimes leaks system messages, stat displays, and other
    game-UI elements into the narrative. This filter removes them while
    preserving allowlisted iconic markers like 【叮！】.
    """
    if not text:
        return text

    cleaned_lines = []
    for line in text.split("\n"):
        original = line

        def _strip_brackets(m: _re.Match) -> str:
            return m.group() if m.group() in SYSTEM_UI_ALLOWLIST else ""

        line = SYSTEM_UI_PATTERNS[0].sub(_strip_brackets, line)
        line = SYSTEM_UI_PATTERNS[1].sub("", line)
        line = SYSTEM_UI_PATTERNS[2].sub("", line)
        if line.strip() or not original.strip():
            cleaned_lines.append(line)

    result = "\n".join(cleaned_lines)
    result = _re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


# ---------------------------------------------------------------------------
# Hard-cap trimming: last-resort length enforcement
# ---------------------------------------------------------------------------


def trim_to_hard_cap(text: str, hard_cap: int, target: int) -> str:
    """超过 hard_cap 时，回退到 hard_cap 内最近的句末标点处截断。

    DeepSeek 实测对 prompt 字数约束完全无视（见 memory novel-length-control-floor），
    soft_max_chars 只能阻止续写扩张，但首轮就超长时无能为力。本函数是最后一道
    执行层。

    策略：从 hard_cap 位置向前扫，找到最后一个句末标点（。！？!?）。命中后顺带
    把紧随其后的闭合引号/括号 ("'」』）】) 一起带出，最多带 4 个（避免极端连续
    闭合标点导致 cut 越过 hard_cap 太多）。若窗口内没有句末标点（极少），硬切到
    hard_cap。下界 floor = hard_cap // 2，保证至少保留半数硬上限的内容。

    Note: 中文 "……"（省略号）刻意排除在 sentence_end 之外，因为它常用作句中
    悬念（"至于林炎……"），切在那里会留下明显残句。

    防御性：hard_cap <= 0 或空输入直接原样返回（避免数值误配传播）。
    """
    if hard_cap <= 0 or not text:
        return text

    if len(text) <= hard_cap:
        return text

    sentence_end = "。！？!?"
    closing = "\"'」』）】"
    floor = hard_cap // 2
    cut = -1
    i = hard_cap
    while i > floor:
        if text[i - 1] in sentence_end:
            j = i
            while j < len(text) and j - i < 4 and text[j] in closing:
                j += 1
            cut = j
            break
        i -= 1

    if cut == -1:
        cut = hard_cap

    trimmed = text[:cut].rstrip()
    log.info(
        "[trim] 文本超长裁剪：%d 字 → %d 字 (target=%d, hard_cap=%d)",
        len(text), len(trimmed), target, hard_cap,
    )
    return trimmed


# ---------------------------------------------------------------------------
# Paragraph deduplication: three-tier dedup against earlier scenes
# ---------------------------------------------------------------------------

DEDUP_HARD_DELETE = 0.6   # ≥60% 句子完全相同 → 删除整段（确定是照搬）
DEDUP_STRIP_OVERLAP = 0.4  # ≥40% → 只删重复句，保留独有句（混合段）


def dedup_paragraphs(new_text: str, previous_texts: list[str]) -> str:
    """分级去重：区分"照搬"和"正常承接"。

    三级处理：
    - ≥60% 句子完全相同 → 删除整段（确定是照搬废段）
    - ≥40% 句子重复 → 只剥离重复句，保留独有内容（混合段）
    - <40% → 不处理（正常的叙事呼应和承接）
    """
    if not previous_texts:
        return new_text

    all_previous = "\n\n".join(previous_texts)

    prev_sentences: set[str] = set()
    for sent in _re.split(r"[。！？!?\n]", all_previous):
        s = sent.strip()
        if len(s) >= 6:
            prev_sentences.add(s)

    if not prev_sentences:
        return new_text

    paragraphs = new_text.split("\n\n")
    kept: list[str] = []
    hard_deleted = 0
    stripped = 0

    for para in paragraphs:
        raw_sentences = _re.split(r"(?<=[。！？!?\n])", para)
        para_sentences = {
            s.strip()
            for s in _re.split(r"[。！？!?\n]", para)
            if len(s.strip()) >= 6
        }

        if not para_sentences:
            kept.append(para)
            continue

        overlap = para_sentences & prev_sentences
        ratio = len(overlap) / len(para_sentences)

        if ratio >= DEDUP_HARD_DELETE:
            hard_deleted += 1
            log.warning(
                "去重[删除]：整段照搬前文（%d/%d句重复，%.0f%%）",
                len(overlap), len(para_sentences), ratio * 100,
            )
            continue

        elif ratio >= DEDUP_STRIP_OVERLAP:
            unique_parts: list[str] = []
            for raw_sent in raw_sentences:
                clean = raw_sent.strip()
                sent_core = _re.sub(r"[。！？!?\n]", "", clean).strip()
                if len(sent_core) >= 6 and sent_core in overlap:
                    continue
                if clean:
                    unique_parts.append(clean)
            if unique_parts:
                stripped += 1
                kept.append("".join(unique_parts))
                log.info(
                    "去重[剥离]：保留独有内容，移除%d句重复",
                    len(overlap),
                )
            else:
                hard_deleted += 1
            continue

        else:
            kept.append(para)

    if hard_deleted > 0 or stripped > 0:
        log.info(
            "场景去重完成：删除%d段，剥离%d段",
            hard_deleted, stripped,
        )

    return "\n\n".join(kept)


# ---------------------------------------------------------------------------
# Character name check: placeholder substitution + unknown-name warnings
# ---------------------------------------------------------------------------

_PLACEHOLDER_PATTERN = _re.compile(
    r"(?:角色|人物|女学生|男学生|学生|老人|男子|女子|男人|女人|少年|少女|青年)"
    r"[A-Za-z0-9甲乙丙丁]"
)

_DIALOGUE_NAME_PATTERN = _re.compile(
    r'(?:^|[。！？!?\n""\s])([^\s。！？!?\n""]{1,4})'
    r"(?:说|问|喊|叫|答|道|笑|哭|吼|嚷|叹|骂|低声|冷笑|咬牙|"
    r"转身|走|站|蹲|跑|看|盯|抬头|回头)"
)

_NOT_NAMES = {
    "他", "她", "它", "我", "你", "谁", "这", "那", "什么",
    "大家", "所有人", "众人", "两人", "三人", "几个人",
    "对方", "自己", "彼此", "有人", "没人", "别人",
    "然后", "突然", "忽然", "于是", "但是", "因为",
    "一个", "两个", "这个", "那个",
}

_PRONOUN_PREFIXES = {"他", "她", "它", "我", "你"}

# Unicode 弯引号 + ASCII 直引号 + CJK 括号
_QUOTE_STRIP = (
    "\"'"
    "“”‘’"
    "「」『』【】"
)

_PROFESSION_PATTERN = _re.compile(
    r"^(?:收银员|保安|老板|司机|医生|护士|警察|服务员|店员|摊主|老头|中年|年轻)"
)


def check_character_names(
    text: str, characters: "list[CharacterProfile]"
) -> str:
    """检测并修复场景文本中的角色名称问题。

    三层校验：
    1. 检测占位符（角色A、女学生B、老人C 等），替换为已知角色名
    2. 扫描对话引语中的未知人名，记录警告
    3. 检测中文人名模式，发现白名单外的新名字时警告
    """
    if not text or not characters:
        return text

    known_names: set[str] = set()
    for c in characters:
        known_names.add(c.name)
        if c.alias:
            known_names.update(c.alias)

    # --- 层1: 占位符检测与替换 ---
    placeholders_found = _PLACEHOLDER_PATTERN.findall(text)
    if placeholders_found:
        log.warning(
            "角色名校验：检测到占位符称呼 %s，应使用具体角色名",
            placeholders_found,
        )
        for ph in set(placeholders_found):
            type_keyword = _re.sub(r"[A-Za-z0-9甲乙丙丁]$", "", ph)
            candidates: list[str] = []
            for c in characters:
                if type_keyword in ("女学生", "学生", "少女") and c.gender == "女":
                    candidates.append(c.name)
                elif type_keyword in ("男学生", "学生", "少年") and c.gender == "男":
                    candidates.append(c.name)
                elif type_keyword in ("老人",) and c.age >= 55:
                    candidates.append(c.name)
                elif type_keyword in ("男子", "男人", "青年") and c.gender == "男":
                    candidates.append(c.name)
                elif type_keyword in ("女子", "女人") and c.gender == "女":
                    candidates.append(c.name)
            if len(candidates) == 1:
                text = text.replace(ph, candidates[0])
                log.info("角色名校验：占位符「%s」→「%s」", ph, candidates[0])

    # --- 层2: 未知人名检测 ---
    matches = _DIALOGUE_NAME_PATTERN.findall(text)
    unknown_names: set[str] = set()
    for name_candidate in matches:
        name_candidate = name_candidate.strip(_QUOTE_STRIP)
        if not name_candidate or len(name_candidate) < 2:
            continue
        if name_candidate in _NOT_NAMES:
            continue
        # 代词前缀剥离：若候选以单字代词开头，整体跳过
        if name_candidate[0] in _PRONOUN_PREFIXES:
            continue
        is_known = False
        for kn in known_names:
            if name_candidate == kn or name_candidate in kn or kn in name_candidate:
                is_known = True
                break
        if not is_known:
            if not _PROFESSION_PATTERN.match(name_candidate):
                unknown_names.add(name_candidate)

    if unknown_names:
        log.warning(
            "角色名校验：检测到白名单外的角色名 %s（合法名单：%s）",
            unknown_names, known_names,
        )

    return text


__all__ = [
    "sanitize_chapter_text",
    "trim_to_hard_cap",
    "dedup_paragraphs",
    "check_character_names",
    "SYSTEM_UI_PATTERNS",
    "SYSTEM_UI_ALLOWLIST",
    "DEDUP_HARD_DELETE",
    "DEDUP_STRIP_OVERLAP",
]
