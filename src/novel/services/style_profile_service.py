"""StyleProfileService — 按项目学习的用词/节奏指纹。

Phase 1-A（架构重构方案 ``specs/architecture-rework-2026/DESIGN.md`` Part 3 B2）：
取代已 stub 化的 ``src/novel/templates/ai_flavor_blacklist``。核心理念：
**本书自己的口头禅**，而不是全局写死的词表。

职责：

- :meth:`build` 从 Novel + 已写章节构建 :class:`StyleProfile`
- :meth:`update_incremental` 追加单章节到已有 profile（简单触发重建）
- :meth:`detect_overuse` 检测新文本里是否大量命中本书自己的高频短语

实现要点：

- 分词用 ``jieba``（项目已依赖），ngram 取 bi/tri-gram
- 覆盖率 >= 30% 章节的短语才算 overused
- 章节样本 < 3 时仅返回最基本的统计（overused 必然不稳定，直接返回空）
- ``action_density`` 基于动作动词 / (动作动词 + 描写词) 粗估
- jieba 失败或文本为空时兜底返回空结果，不抛异常

Phase 1-A 不 wire 进 Verifier/Reviewer，集成留给 Phase 2。
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable

from src.novel.models.style_profile import (
    OverusedPhrase,
    PacingPoint,
    StyleProfile,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.novel.models.chapter import Chapter
    from src.novel.models.novel import Novel

log = logging.getLogger("novel.style_profile")


# ---------------------------------------------------------------------------
# 常量：阈值与分词参数
# ---------------------------------------------------------------------------

#: 默认覆盖率阈值：>= 30% 章节出现 → 算 overused
DEFAULT_COVERAGE_THRESHOLD: float = 0.30

#: ngram 范围（bi/tri-gram）
_NGRAM_SIZES: tuple[int, ...] = (2, 3)

#: ngram 中单 token 长度上限（避免整段抽成 ngram 的噪声）
_MAX_TOKEN_LEN: int = 6

#: 最少章节数，少于该值 overused 判定不可靠，直接返回空
_MIN_SAMPLE_FOR_OVERUSE: int = 3

#: overused 至少出现的绝对次数（避免稀有短语被放大）
_MIN_OCCURRENCE: int = 3

#: 结果最多返回多少条
_TOP_N_OVERUSED: int = 50

#: 句子切分正则（与 style_analysis_tool 一致）
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?\.\n]+")

#: 常见虚词/停用词（不参与 ngram 构建）
_STOPWORDS: frozenset[str] = frozenset(
    {
        "的",
        "了",
        "和",
        "与",
        "是",
        "在",
        "也",
        "就",
        "都",
        "而",
        "及",
        "或",
        "但",
        "一个",
        "一些",
        "这个",
        "那个",
        "这种",
        "那种",
        "这样",
        "那样",
        "什么",
        "怎么",
        "我",
        "你",
        "他",
        "她",
        "它",
        "我们",
        "你们",
        "他们",
        "她们",
        "它们",
        " ",
        "",
        "，",
        "。",
        "！",
        "？",
        "：",
        "；",
        "、",
        "（",
        "）",
        "“",
        "”",
        "‘",
        "’",
        "《",
        "》",
        "\n",
        "\t",
    }
)

#: 动作动词（粗粒度，用于 pacing 估算）
_ACTION_WORDS: frozenset[str] = frozenset(
    {
        "冲",
        "跳",
        "扑",
        "踢",
        "打",
        "砍",
        "刺",
        "射",
        "抓",
        "推",
        "拉",
        "拽",
        "撞",
        "奔",
        "跑",
        "闪",
        "避",
        "挥",
        "劈",
        "斩",
        "击",
        "轰",
        "爆",
        "炸",
        "吼",
        "喊",
        "吓",
        "追",
        "逃",
        "挡",
        "破",
        "裂",
        "碎",
        "翻",
        "滚",
        "跃",
        "掠",
        "夺",
        "抢",
        "咬",
        "踩",
        "踏",
    }
)

#: 描写词（粗粒度，用于 pacing 估算）
_DESCRIPTION_WORDS: frozenset[str] = frozenset(
    {
        "阳光",
        "月光",
        "夜色",
        "风",
        "雨",
        "雪",
        "花",
        "草",
        "树",
        "山",
        "水",
        "天空",
        "大地",
        "寂静",
        "沉默",
        "空气",
        "气氛",
        "色彩",
        "光芒",
        "光线",
        "温度",
        "声音",
        "远处",
        "近处",
        "周围",
        "四周",
        "笼罩",
        "弥漫",
        "飘荡",
        "回荡",
        "静谧",
        "安静",
        "幽静",
        "朦胧",
        "温柔",
        "柔和",
        "皎洁",
        "皑皑",
        "苍茫",
        "辽阔",
    }
)


# ---------------------------------------------------------------------------
# jieba 懒加载
# ---------------------------------------------------------------------------

_jieba = None


def _ensure_jieba() -> bool:
    """懒加载 jieba；返回是否可用。"""
    global _jieba  # noqa: PLW0603
    if _jieba is not None:
        return True
    try:
        import jieba  # type: ignore[import-untyped]

        _jieba = jieba
        return True
    except ImportError:  # pragma: no cover - 项目已依赖 jieba
        log.warning("jieba 未安装，StyleProfileService 功能受限")
        return False


def _tokenize(text: str) -> list[str]:
    """中文分词，返回去空 token 列表；jieba 不可用或空文本返回 []。"""
    if not text or not text.strip():
        return []
    if not _ensure_jieba():
        return []
    try:
        tokens = _jieba.lcut(text)  # type: ignore[union-attr]
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("jieba 分词失败: %s", exc)
        return []
    return [t for t in tokens if t and t.strip()]


def _iter_ngrams(tokens: list[str]) -> Iterable[str]:
    """从 token 序列产出 bi/tri-gram；跳过含停用词或过长 token 的组合。"""
    if not tokens:
        return
    for n in _NGRAM_SIZES:
        if len(tokens) < n:
            continue
        for i in range(len(tokens) - n + 1):
            window = tokens[i : i + n]
            # 过滤：任何 token 是停用词 or 长度过大
            if any(
                (w in _STOPWORDS) or (len(w) > _MAX_TOKEN_LEN) for w in window
            ):
                continue
            phrase = "".join(window)
            # ngram 自身也不能是纯标点/单字噪声
            if len(phrase) < 2:
                continue
            yield phrase


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class StyleProfileService:
    """构建与查询本书的 StyleProfile。

    用法::

        svc = StyleProfileService()
        profile = svc.build(novel)
        file_manager.save_style_profile(novel.novel_id, profile.model_dump())

        # 检测一段新文本是否大量命中本书口头禅
        hits = svc.detect_overuse(new_chapter_text, profile)
    """

    def __init__(
        self,
        coverage_threshold: float = DEFAULT_COVERAGE_THRESHOLD,
    ) -> None:
        if not 0.0 < coverage_threshold <= 1.0:
            raise ValueError(
                f"coverage_threshold 必须在 (0, 1]，收到 {coverage_threshold}"
            )
        self.coverage_threshold = coverage_threshold

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def build(self, novel: "Novel") -> StyleProfile:
        """从 Novel 的 chapters 全量重建 StyleProfile。

        Args:
            novel: Novel 对象，必须至少有 ``novel_id`` 字段；
                ``chapters`` 可以为空（返回空 profile）。

        Returns:
            StyleProfile 实例，``sample_size`` 反映实际参与统计的章节数。
        """
        chapters = list(getattr(novel, "chapters", None) or [])
        # 只用有正文的章节
        non_empty = [
            ch
            for ch in chapters
            if getattr(ch, "full_text", None) and ch.full_text.strip()
        ]
        sample_size = len(non_empty)

        if sample_size == 0:
            return StyleProfile(
                novel_id=novel.novel_id,
                updated_at=datetime.now(timezone.utc).isoformat(),
                sample_size=0,
            )

        # 逐章分词，收集每章 token + ngram 集合
        per_chapter_tokens: list[list[str]] = []
        per_chapter_ngram_set: list[set[str]] = []
        per_chapter_ngram_count: list[Counter[str]] = []
        pacing_points: list[PacingPoint] = []
        all_sentence_lens: list[int] = []

        for ch in non_empty:
            text = ch.full_text
            tokens = _tokenize(text)
            per_chapter_tokens.append(tokens)

            ngram_counter: Counter[str] = Counter(_iter_ngrams(tokens))
            per_chapter_ngram_count.append(ngram_counter)
            per_chapter_ngram_set.append(set(ngram_counter.keys()))

            pacing_points.append(
                PacingPoint(
                    chapter_number=ch.chapter_number,
                    action_density=_compute_action_density(tokens),
                )
            )

            sentences = [
                s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()
            ]
            all_sentence_lens.extend(len(s) for s in sentences)

        avg_sentence_len, sentence_len_std = _mean_std(all_sentence_lens)

        overused = _aggregate_overused(
            per_chapter_ngram_count=per_chapter_ngram_count,
            per_chapter_ngram_set=per_chapter_ngram_set,
            sample_size=sample_size,
            threshold=self.coverage_threshold,
        )

        return StyleProfile(
            novel_id=novel.novel_id,
            updated_at=datetime.now(timezone.utc).isoformat(),
            overused_phrases=overused,
            avg_sentence_len=round(avg_sentence_len, 2),
            sentence_len_std=round(sentence_len_std, 2),
            pacing_curve=pacing_points,
            sample_size=sample_size,
        )

    def update_incremental(
        self, profile: StyleProfile, chapter: "Chapter"
    ) -> StyleProfile:
        """把一个新章节追加到 profile（简单实现：只更新 pacing + sample_size）。

        完整 overused 重算需要全量章节文本，推荐上层在足够章节累积后重跑
        :meth:`build`。这里提供轻量增量版本，保证 pacing 曲线与样本数同步。

        Args:
            profile: 现有 StyleProfile
            chapter: 新章节

        Returns:
            **新的** StyleProfile（不修改传入对象）
        """
        text = (getattr(chapter, "full_text", None) or "").strip()
        if not text:
            return profile.model_copy(
                update={"updated_at": datetime.now(timezone.utc).isoformat()}
            )

        tokens = _tokenize(text)
        new_point = PacingPoint(
            chapter_number=chapter.chapter_number,
            action_density=_compute_action_density(tokens),
        )

        # 避免重复插入同一章号
        existing_points = [
            p for p in profile.pacing_curve if p.chapter_number != chapter.chapter_number
        ]
        existing_points.append(new_point)
        existing_points.sort(key=lambda p: p.chapter_number)

        return profile.model_copy(
            update={
                "pacing_curve": existing_points,
                "sample_size": profile.sample_size + 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    # ------------------------------------------------------------------
    # 检测
    # ------------------------------------------------------------------

    def detect_overuse(
        self,
        text: str,
        profile: StyleProfile,
        threshold: float = DEFAULT_COVERAGE_THRESHOLD,
    ) -> list[str]:
        """检测 text 里命中 profile.overused_phrases 的短语。

        Args:
            text: 待检查文本（通常是新生成的章节）
            profile: 已构建好的 StyleProfile
            threshold: 覆盖率阈值，仅筛选 profile 里 chapter_coverage >=
                该阈值的短语参与匹配。默认 30%。

        Returns:
            命中的短语列表（按出现顺序去重）；空文本/空 profile 返回 []。
        """
        if not text or not text.strip():
            return []
        if not profile.overused_phrases:
            return []

        watchlist = [
            p.phrase
            for p in profile.overused_phrases
            if p.chapter_coverage >= threshold
        ]
        if not watchlist:
            return []

        hits: list[str] = []
        seen: set[str] = set()
        for phrase in watchlist:
            if phrase and phrase in text and phrase not in seen:
                hits.append(phrase)
                seen.add(phrase)
        return hits


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _compute_action_density(tokens: list[str]) -> float:
    """动作密度：action / (action + description)；两者皆 0 时返回 0.5（中性）。"""
    if not tokens:
        return 0.5
    action = sum(1 for t in tokens if t in _ACTION_WORDS)
    desc = sum(1 for t in tokens if t in _DESCRIPTION_WORDS)
    total = action + desc
    if total == 0:
        return 0.5
    return round(action / total, 4)


def _mean_std(values: list[int]) -> tuple[float, float]:
    """返回 (mean, std)；空列表返回 (0.0, 0.0)。"""
    if not values:
        return 0.0, 0.0
    n = len(values)
    mean = sum(values) / n
    if n == 1:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in values) / n
    return mean, math.sqrt(var)


def _aggregate_overused(
    *,
    per_chapter_ngram_count: list[Counter[str]],
    per_chapter_ngram_set: list[set[str]],
    sample_size: int,
    threshold: float,
) -> list[OverusedPhrase]:
    """聚合每章 ngram，筛选出覆盖率 >= threshold 的短语。"""
    if sample_size < _MIN_SAMPLE_FOR_OVERUSE:
        # 样本过少，overused 判定不稳定
        return []

    # 覆盖率（出现在多少章）
    doc_freq: Counter[str] = Counter()
    for ngram_set in per_chapter_ngram_set:
        for phrase in ngram_set:
            doc_freq[phrase] += 1

    # 总出现次数
    total_freq: Counter[str] = Counter()
    for counter in per_chapter_ngram_count:
        total_freq.update(counter)

    candidates: list[OverusedPhrase] = []
    for phrase, df in doc_freq.items():
        coverage = df / sample_size
        if coverage < threshold:
            continue
        total = total_freq.get(phrase, 0)
        if total < _MIN_OCCURRENCE:
            continue
        candidates.append(
            OverusedPhrase(
                phrase=phrase,
                chapter_coverage=round(coverage, 4),
                total_occurrences=total,
            )
        )

    # 先按 coverage 降，再按 total 降，截断 top-N
    candidates.sort(
        key=lambda p: (p.chapter_coverage, p.total_occurrences),
        reverse=True,
    )
    return candidates[:_TOP_N_OVERUSED]
