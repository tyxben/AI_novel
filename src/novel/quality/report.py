"""质量评估报告数据结构。

Phase 5 (``specs/architecture-rework-2026/PHASE5.md`` 第 2.3 节) 交付：

- :class:`DimensionScore` — 单个维度的评分载体
- :class:`ChapterQualityReport` — 单章完整评估报告
- :class:`ABComparisonResult` — 两个版本的成对比较结果

所有类都是纯 dataclass（不引入新依赖），都提供 ``to_dict()`` 便于落盘成 JSON。
``ChapterQualityReport`` 额外提供 ``avg_llm_score()`` / ``save_json()``。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DimensionScore:
    """单维度评估结果。

    ``scale`` 指示 ``score`` 的取值范围/语义：

    - ``"1-5"``   — LLM rubric 打分（1=很差，5=很好）
    - ``"0-100"`` — 统计指标映射到 0-100（e.g. AI 味指数，越高越差）
    - ``"percent"`` — 百分比 0-100（e.g. 伏笔兑现率，越高越好）

    ``method`` 标识评估手段，便于报告层区分哪些维度参与平均分：

    - ``"llm_judge"`` — 纯 LLM 评判
    - ``"rule"``      — 纯规则统计
    - ``"mixed"``     — LLM + 规则混合
    """

    key: str
    score: float
    scale: str = "1-5"
    method: str = "llm_judge"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "score": self.score,
            "scale": self.scale,
            "method": self.method,
            "details": dict(self.details),
        }


@dataclass
class ChapterQualityReport:
    """单章完整评估报告。"""

    chapter_number: int
    genre: str
    commit_hash: str = ""
    scores: list[DimensionScore] = field(default_factory=list)
    overall_summary: str = ""
    generated_at: str = ""
    judge_model: str = ""
    judge_token_usage: int = 0

    def avg_llm_score(self) -> float:
        """仅计算 ``scale == "1-5"`` 的维度平均分。

        这是 LLM rubric 维度的综合指标——百分比 / 0-100 维度不在同一刻度，
        不参与平均。当没有任何 1-5 维度时返回 ``0.0``（防除零）。
        """
        llm_dims = [s for s in self.scores if s.scale == "1-5"]
        if not llm_dims:
            return 0.0
        return sum(s.score for s in llm_dims) / len(llm_dims)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_number": self.chapter_number,
            "genre": self.genre,
            "commit_hash": self.commit_hash,
            "scores": [s.to_dict() for s in self.scores],
            "overall_summary": self.overall_summary,
            "generated_at": self.generated_at,
            "judge_model": self.judge_model,
            "judge_token_usage": self.judge_token_usage,
        }

    def save_json(self, path: str) -> None:
        """把报告落盘成 UTF-8 JSON 文件。自动创建父目录。"""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as fp:
            json.dump(self.to_dict(), fp, ensure_ascii=False, indent=2)


@dataclass
class ABComparisonResult:
    """A/B 成对比较结果（同体裁同章节两个 commit 的对比）。"""

    genre: str
    chapter_number: int
    commit_a: str
    commit_b: str
    winner: str
    judge_reasoning: str
    dimension_preferences: dict[str, str] = field(default_factory=dict)
    judge_model: str = ""
    judge_token_usage: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "genre": self.genre,
            "chapter_number": self.chapter_number,
            "commit_a": self.commit_a,
            "commit_b": self.commit_b,
            "winner": self.winner,
            "judge_reasoning": self.judge_reasoning,
            "dimension_preferences": dict(self.dimension_preferences),
            "judge_model": self.judge_model,
            "judge_token_usage": self.judge_token_usage,
        }
