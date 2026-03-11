"""质量评估数据模型"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StyleMetrics(BaseModel):
    """风格特征指标"""

    avg_sentence_length: float = Field(..., ge=0, description="平均句长")
    dialogue_ratio: float = Field(..., ge=0.0, le=1.0, description="对话占比")
    exclamation_ratio: float = Field(
        ..., ge=0.0, le=1.0, description="感叹句占比"
    )
    paragraph_length: float = Field(..., ge=0, description="平均段落长度")
    classical_word_ratio: float | None = Field(
        None, ge=0.0, le=1.0, description="古风用词占比"
    )
    description_ratio: float | None = Field(
        None, ge=0.0, le=1.0, description="描写占比"
    )
    first_person_ratio: float | None = Field(
        None, ge=0.0, le=1.0, description="第一人称占比"
    )


class RuleCheckResult(BaseModel):
    """规则硬指标检查结果"""

    passed: bool
    repetition_issues: list[str] = Field(default_factory=list)
    dialogue_tag_issues: list[str] = Field(default_factory=list)
    paragraph_length_issues: list[str] = Field(default_factory=list)
    ai_flavor_issues: list[str] = Field(default_factory=list)
    dialogue_distinction_issues: list[str] = Field(default_factory=list)


class PairwiseResult(BaseModel):
    """对比式评估结果"""

    winner: Literal["A", "B", "TIE"] = Field(..., description="获胜方")
    reason: str = Field(..., min_length=1)


class QualityReport(BaseModel):
    """综合质量报告"""

    chapter_number: int = Field(..., ge=1)
    rule_check: RuleCheckResult
    scores: dict[str, float] = Field(
        default_factory=dict,
        description="各维度评分: plot_coherence, writing_quality, character_portrayal, ai_flavor_score",
    )
    need_rewrite: bool = Field(False, description="是否需要重写")
    rewrite_reason: str | None = None
    suggestions: list[str] = Field(default_factory=list, description="改进建议")
