"""质量评估模块 — Phase 5 交付。

对应设计文档：``specs/architecture-rework-2026/PHASE5.md``

对外导出：

- :class:`DimensionScore` / :class:`ChapterQualityReport` / :class:`ABComparisonResult`
  — 报告数据结构
- 纯规则维度函数（D3 伏笔兑现率 / D4 AI 味指数 / D6 对话统计 / D7 章节勾连规则部分）

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

__all__ = [
    "ABComparisonResult",
    "ChapterQualityReport",
    "DimensionScore",
    "evaluate_ai_flavor",
    "evaluate_chapter_hook_rules",
    "evaluate_dialogue_quality_rules",
    "evaluate_foreshadow_payoff",
]
