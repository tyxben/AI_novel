"""质量评估——纯规则维度。

Phase 5 / E2 交付（``specs/architecture-rework-2026/PHASE5.md`` 附录 A）。

包含四个规则层评估函数：

* :func:`evaluate_foreshadow_payoff` — D3 伏笔兑现率（纯规则，DimensionScore 输出）
* :func:`evaluate_ai_flavor` — D4 AI 味指数（纯规则，DimensionScore 输出）
* :func:`evaluate_dialogue_quality_rules` — D6 对话自然度规则部分（dict 输出，
  由 E3 合并 LLM 分数成完整 DimensionScore）
* :func:`evaluate_chapter_hook_rules` — D7 章节勾连规则部分（dict 输出，同上）

实现原则
--------
- 不引入新重依赖：只用标准库正则 + 项目已有的 jieba（懒加载）
- 接口稳定：签名严格按 PHASE5.md 约定
- 评分可复现：纯规则无随机性
- 空输入兜底：空文本 / 空 ledger / 缺失 profile 均不崩
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from src.novel.quality.report import DimensionScore

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查
    from src.novel.models.style_profile import StyleProfile
    from src.novel.services.ledger_store import LedgerStore

log = logging.getLogger("novel.quality.dimensions")


# ---------------------------------------------------------------------------
# D3 伏笔兑现率
# ---------------------------------------------------------------------------


def evaluate_foreshadow_payoff(
    ledger: "LedgerStore",
    chapter_number: int,
    chapters_text: dict[int, str],
) -> DimensionScore:
    """D3 伏笔兑现率。纯规则。

    算法：
    1. ``ledger.snapshot_for_chapter(chapter_number)`` 拉
       ``collectable_foreshadowings``（已到期应兑现的伏笔）
    2. 对每条伏笔的 ``detail``（或 description/title 兜底）取前 12 字为关键词
    3. 在 ``chapters_text`` 全部章节的文本中搜索该关键词是否出现
    4. ``payoff_rate = collected / total_collectable``（百分比，0-100）

    "命中即兑现"是保守近似——不做语义判断，只看是否显式提及。无到期伏笔 /
    空 snapshot / 缺失 ledger 均返回 100%（没东西可违反）。

    Args:
        ledger: LedgerStore 实例；内部已做 None-safe 兜底，这里不额外判空
        chapter_number: 当前章节号（判断"到期"的边界）
        chapters_text: 已写章节的全文，形如 ``{1: "第一章文本...", 2: "..."}``

    Returns:
        :class:`DimensionScore`，``scale="percent"`` / ``method="rule"``。
        ``details`` 含 ``collected`` / ``total`` / ``missed``（详细 list）。
    """
    try:
        snap = ledger.snapshot_for_chapter(chapter_number)
    except Exception as exc:  # noqa: BLE001 - 兜底：ledger 异常视作空
        log.debug("foreshadow_payoff snapshot failed: %s", exc)
        snap = {}

    collectable_raw = snap.get("collectable_foreshadowings") or []

    # 合并全部章节文本做关键词搜索（保守命中判定）
    full_text = "\n".join(
        chapters_text[k] for k in sorted(chapters_text.keys()) if chapters_text[k]
    )

    total = 0
    collected = 0
    missed: list[dict[str, Any]] = []

    for entry in collectable_raw:
        if not isinstance(entry, dict):
            continue
        detail = str(
            entry.get("detail")
            or entry.get("description")
            or entry.get("title")
            or ""
        ).strip()
        if not detail:
            continue
        total += 1
        keyword = detail[:12]
        if keyword and keyword in full_text:
            collected += 1
        else:
            missed.append(
                {
                    "detail": detail,
                    "keyword": keyword,
                    "target_chapter": entry.get("target_chapter"),
                }
            )

    if total == 0:
        payoff_rate = 100.0
    else:
        payoff_rate = round(collected / total * 100.0, 2)

    return DimensionScore(
        key="foreshadow_payoff",
        score=payoff_rate,
        scale="percent",
        method="rule",
        details={
            "collected": collected,
            "total": total,
            "missed": missed,
        },
    )


# ---------------------------------------------------------------------------
# D4 AI 味指数
# ---------------------------------------------------------------------------


#: 通用 AI 写作指示词（体裁无关）——来自 PHASE5.md 第 2.2 节 D4
_AI_INDICATORS_UNIVERSAL: tuple[str, ...] = (
    "不禁",
    "竟然",
    "忍不住",
    "与此同时",
    "毫不犹豫",
)

#: 句末切分（用于句首 bigram 重复度）
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?\n]+")

#: D4 公式权重（overuse / cliche / repetition = 40/30/30）
_AI_WEIGHT_OVERUSE = 40.0
_AI_WEIGHT_CLICHE = 30.0
_AI_WEIGHT_REPETITION = 30.0


def evaluate_ai_flavor(
    text: str,
    style_profile: "StyleProfile | None" = None,
    genre: str = "",
) -> DimensionScore:
    """D4 AI 味指数。纯规则。

    综合三个来源：

    1. **本书口头禅过度使用**（overuse_hit_density）：调用
       ``StyleProfileService.detect_overuse(text, profile)``，没 profile 时
       退化为 0。密度 = 命中短语总次数 / (text 长度 / 1000)，封顶 10。
    2. **通用 AI 陈词滥调**（cliche_density）：匹配
       :data:`_AI_INDICATORS_UNIVERSAL`，每千字密度，封顶 10。
    3. **句式重复度**（repetition_rate）：相邻 5 句窗口里句首 bigram（前 2 字）
       相同的比例，0-1。

    综合公式::

        ai_index = (overuse_density * 40 + cliche_density * 30
                    + repetition_rate * 30) / 10

    归一到 0-100，越高越"AI 味重"。空文本返回 0。

    Args:
        text: 待评估章节文本
        style_profile: 可选 :class:`StyleProfile`；缺失则只用通用指示词 +
            句式重复度（AI 味计算仍可正常工作）
        genre: 体裁标签（目前仅记录到 details 便于调试；体裁差异化阈值由
            上层报告消费时处理，评估函数自身保持体裁无关）

    Returns:
        :class:`DimensionScore`，``scale="0-100"`` / ``method="rule"``。
    """
    if not text or not text.strip():
        return DimensionScore(
            key="ai_flavor_index",
            score=0.0,
            scale="0-100",
            method="rule",
            details={
                "overuse_hits": [],
                "cliche_count": 0,
                "repetition_rate": 0.0,
                "components": {"overuse": 0.0, "cliche": 0.0, "repetition": 0.0},
                "genre": genre,
            },
        )

    text_length = len(text)
    per_thousand = max(text_length / 1000.0, 1e-6)

    # 1. 本书口头禅命中
    overuse_hits: list[str] = []
    if style_profile is not None and getattr(style_profile, "overused_phrases", None):
        try:
            from src.novel.services.style_profile_service import StyleProfileService

            svc = StyleProfileService()
            overuse_hits = svc.detect_overuse(text, style_profile)
        except Exception as exc:  # noqa: BLE001
            log.debug("ai_flavor overuse detection failed: %s", exc)
            overuse_hits = []

    overuse_hit_count = 0
    for phrase in overuse_hits:
        if phrase:
            overuse_hit_count += text.count(phrase)
    overuse_density = min(overuse_hit_count / per_thousand, 10.0)

    # 2. 通用陈词滥调命中
    cliche_count = 0
    for indicator in _AI_INDICATORS_UNIVERSAL:
        cliche_count += text.count(indicator)
    cliche_density = min(cliche_count / per_thousand, 10.0)

    # 3. 句首 bigram 重复度（相邻 5 句窗口）
    repetition_rate = _compute_opening_bigram_repetition(text)

    # 综合：各来源归一到 0-1 后加权
    # overuse_density / cliche_density 范围 0-10 → 除 10 → 0-1
    overuse_norm = overuse_density / 10.0
    cliche_norm = cliche_density / 10.0
    rep_norm = repetition_rate  # 已经是 0-1

    components = {
        "overuse": round(overuse_norm * _AI_WEIGHT_OVERUSE, 2),
        "cliche": round(cliche_norm * _AI_WEIGHT_CLICHE, 2),
        "repetition": round(rep_norm * _AI_WEIGHT_REPETITION, 2),
    }
    score = components["overuse"] + components["cliche"] + components["repetition"]
    score = max(0.0, min(100.0, round(score, 2)))

    return DimensionScore(
        key="ai_flavor_index",
        score=score,
        scale="0-100",
        method="rule",
        details={
            "overuse_hits": overuse_hits,
            "overuse_hit_count": overuse_hit_count,
            "cliche_count": cliche_count,
            "repetition_rate": round(repetition_rate, 4),
            "components": components,
            "genre": genre,
        },
    )


def _compute_opening_bigram_repetition(text: str) -> float:
    """句首 bigram 重复度：相邻 5 句窗口里开头 2 字相同的对数 / 对数总数。

    返回 0-1 之间的 float；句子不足 2 则返回 0.0。
    """
    raw_sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if len(raw_sentences) < 2:
        return 0.0

    # 取句首 2 字作为 bigram 标识（不足 2 字的句子忽略）
    openers: list[str] = []
    for sent in raw_sentences:
        # 去掉开头引号/空白
        trimmed = sent.lstrip("“”\"'「」 \t")
        if len(trimmed) >= 2:
            openers.append(trimmed[:2])

    if len(openers) < 2:
        return 0.0

    window = 5
    repeat_pairs = 0
    total_pairs = 0
    for i in range(len(openers)):
        for j in range(i + 1, min(i + window, len(openers))):
            total_pairs += 1
            if openers[i] == openers[j]:
                repeat_pairs += 1

    if total_pairs == 0:
        return 0.0
    return repeat_pairs / total_pairs


# ---------------------------------------------------------------------------
# D6 对话自然度（规则部分）
# ---------------------------------------------------------------------------


#: 对话引号对（成对匹配；中英文混排都要覆盖）
_DIALOGUE_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ("“", "”"),
    ("「", "」"),
    ("‘", "’"),
    ('"', '"'),
    ("'", "'"),
)

#: 单条对话超长警告阈值（字符数）
_DIALOGUE_LONG_THRESHOLD = 200


def evaluate_dialogue_quality_rules(text: str) -> dict[str, Any]:
    """D6 对话自然度——规则层（E3 负责合并 LLM 分数形成完整 DimensionScore）。

    统计项：

    - ``dialogue_ratio``: 引号内文字长度 / 全文长度
    - ``max_single_line``: 最长单条对话字符数（超过 200 标 warning）
    - ``line_count``: 对话条数（所有引号对匹配出的内容段）
    - ``warnings``: 问题列表（空文本无 warning）

    中文「」""、英文 ""/'' 都支持（pair-based 匹配；未成对的尾引号忽略）。
    空文本返回全 0 字段 + 空 warnings。

    Returns:
        dict（非 :class:`DimensionScore`）。E3 LLM 层合并后再组装。
    """
    if not text:
        return {
            "dialogue_ratio": 0.0,
            "max_single_line": 0,
            "line_count": 0,
            "warnings": [],
        }

    total_length = len(text)
    dialogue_segments: list[str] = []

    # 简单 pair-based 提取：遍历每种成对引号，贪心匹配最近的闭合
    for open_q, close_q in _DIALOGUE_QUOTE_PAIRS:
        if open_q == close_q:
            # 同字符引号（如英文 " / '）—— 用成对规则：奇数位开，偶数位闭
            positions = [i for i, ch in enumerate(text) if ch == open_q]
            # 两两组队
            for i in range(0, len(positions) - 1, 2):
                start = positions[i] + 1
                end = positions[i + 1]
                seg = text[start:end]
                if seg:
                    dialogue_segments.append(seg)
        else:
            # 异字符引号：用栈式匹配
            cursor = 0
            while True:
                start_idx = text.find(open_q, cursor)
                if start_idx == -1:
                    break
                end_idx = text.find(close_q, start_idx + len(open_q))
                if end_idx == -1:
                    break
                seg = text[start_idx + len(open_q) : end_idx]
                if seg:
                    dialogue_segments.append(seg)
                cursor = end_idx + len(close_q)

    dialogue_length = sum(len(s) for s in dialogue_segments)
    dialogue_ratio = (
        round(dialogue_length / total_length, 4) if total_length > 0 else 0.0
    )
    max_line = max((len(s) for s in dialogue_segments), default=0)
    line_count = len(dialogue_segments)

    warnings: list[str] = []
    if max_line > _DIALOGUE_LONG_THRESHOLD:
        warnings.append(
            f"dialogue_too_long: 最长单条 {max_line} 字 > 阈值 {_DIALOGUE_LONG_THRESHOLD}"
        )

    return {
        "dialogue_ratio": dialogue_ratio,
        "max_single_line": max_line,
        "line_count": line_count,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# D7 章节勾连（规则部分）
# ---------------------------------------------------------------------------


#: 本章结尾 hook 正则模式（疑问 / 省略 / 转折 / 突发）
_HOOK_ENDING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("疑问句", re.compile(r"[？?][”」\"']?\s*$")),
    ("省略号", re.compile(r"(?:……|\.{3,})[”」\"']?\s*$")),
    # 转折/突发词作为本章最后一句开头
    (
        "转折词",
        re.compile(
            r"(?:但是|然而|突然|忽然|不料|谁知|怎料)[^。！？!?\n]{0,50}[。！？!?][”」\"']?\s*$"
        ),
    ),
)

#: 从前文提取关键词的正则：保留中英日韩文字段（去标点/数字/空白）
_TOKEN_CLEAN_RE = re.compile(
    r"[^一-鿿A-Za-z぀-ヿ가-힯]+"
)


def evaluate_chapter_hook_rules(
    current_text: str,
    previous_tail: str,
) -> dict[str, Any]:
    """D7 章节勾连——规则层。

    规则 1：**上章末尾 → 本章开头命中率**。从 ``previous_tail``（上章末尾
    约 200 字）提取 2 字 bigram 候选关键词，在 ``current_text`` 前 500 字
    里搜索命中率。

    规则 2：**本章是否抛出 hook**。末尾若以疑问句 / 省略号 / 转折词结尾，
    标 ``ending_has_hook = True``，并返回命中的 ``ending_indicator`` 名。

    Args:
        current_text: 本章全文
        previous_tail: 上章末尾 ~200 字。若为 ``""`` 则 opening_match_rate 退为 1.0
            （第一章无上文，不扣分）

    Returns:
        dict: ``{opening_match_rate, ending_has_hook, ending_indicator, warnings}``
    """
    result: dict[str, Any] = {
        "opening_match_rate": 0.0,
        "ending_has_hook": False,
        "ending_indicator": "",
        "warnings": [],
    }

    if not current_text:
        result["warnings"].append("empty_chapter_text")
        return result

    # -------- 规则 1: 上章末尾 → 本章开头命中率 --------
    if not previous_tail:
        # 第一章不扣分
        result["opening_match_rate"] = 1.0
    else:
        keywords = _extract_bigrams(previous_tail)
        opening = current_text[:500]
        if not keywords:
            # 上章末尾没有有效 bigram（纯标点/过短）
            result["opening_match_rate"] = 1.0
        else:
            hits = sum(1 for kw in keywords if kw in opening)
            result["opening_match_rate"] = round(hits / len(keywords), 4)
            if result["opening_match_rate"] < 0.1:
                result["warnings"].append(
                    f"opening_mismatch: 上章关键词命中率 {result['opening_match_rate']:.2%}"
                )

    # -------- 规则 2: 本章结尾 hook 检测 --------
    tail_segment = current_text[-200:] if len(current_text) > 200 else current_text
    for name, pattern in _HOOK_ENDING_PATTERNS:
        if pattern.search(tail_segment):
            result["ending_has_hook"] = True
            result["ending_indicator"] = name
            break

    if not result["ending_has_hook"]:
        result["warnings"].append("ending_flat: 章节末尾无明显 hook")

    return result


def _extract_bigrams(text: str) -> list[str]:
    """从文本里抽 2 字 bigram 候选（去标点/数字/空白），去重保序。"""
    if not text:
        return []
    cleaned = _TOKEN_CLEAN_RE.sub(" ", text)
    bigrams: list[str] = []
    seen: set[str] = set()
    # 只对连续文字段做 bigram（不跨空格）
    for segment in cleaned.split():
        for i in range(len(segment) - 1):
            bg = segment[i : i + 2]
            if len(bg) == 2 and bg not in seen:
                seen.add(bg)
                bigrams.append(bg)
    return bigrams
