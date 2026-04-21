"""质量评估模块 — Phase 5 交付。

对应设计文档：``specs/architecture-rework-2026/PHASE5.md``

对外导出：

- :class:`DimensionScore` / :class:`ChapterQualityReport` / :class:`ABComparisonResult`
  — 报告数据结构
- 纯规则维度函数（D3 伏笔兑现率 / D4 AI 味指数 / D6 对话统计 / D7 章节勾连规则部分）
- 维度分组常量（见下方 H6 fix 注释）

LLM 维度（D1/D5 rubric judge）和 A/B 比较在 ``judge.py`` / ``ab_compare.py``
由 E3 executor 实现。
"""

from __future__ import annotations

from src.novel.quality.dimensions import (
    evaluate_ai_flavor,
    evaluate_chapter_hook_rules,
    evaluate_dialogue_quality_rules,
    evaluate_foreshadow_payoff,
)
from src.novel.quality.report import (
    ABComparisonResult,
    ChapterQualityReport,
    DimensionScore,
)

# ---------------------------------------------------------------------------
# H6 fix: 维度分组常量（消除命名歧义）
#
# 三组维度：
# - MULTI_JUDGE_DIMENSIONS: multi_dimension_judge 一次 LLM call 同时打分的 3 维
#   (D2/D6/D7)
# - SINGLE_JUDGE_DIMENSIONS: 独立 LLM call 的 2 维 (D1/D5)
# - AB_DIMENSIONS: A/B 成对比较回答的 5 维 = MULTI + SINGLE
#
# judge.py / ab_compare.py 不再硬编码字符串列表，统一从此处引用。
# ---------------------------------------------------------------------------

MULTI_JUDGE_DIMENSIONS: tuple[str, ...] = (
    "character_consistency",
    "dialogue_quality",
    "chapter_hook",
)

SINGLE_JUDGE_DIMENSIONS: tuple[str, ...] = (
    "narrative_flow",
    "plot_advancement",
)

AB_DIMENSIONS: tuple[str, ...] = (
    "narrative_flow",
    "character_consistency",
    "plot_advancement",
    "dialogue_quality",
    "chapter_hook",
)

__all__ = [
    "AB_DIMENSIONS",
    "ABComparisonResult",
    "ChapterQualityReport",
    "DimensionScore",
    "MULTI_JUDGE_DIMENSIONS",
    "SINGLE_JUDGE_DIMENSIONS",
    "evaluate_ai_flavor",
    "evaluate_chapter_hook_rules",
    "evaluate_dialogue_quality_rules",
    "evaluate_foreshadow_payoff",
]
