"""精修工作台数据模型：校对问题、设定冲突、设定影响"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ProofreadingIssueType(str, Enum):
    PUNCTUATION = "punctuation"      # 标点错误
    GRAMMAR = "grammar"              # 语法问题
    TYPO = "typo"                    # 错别字
    WORD_CHOICE = "word_choice"      # 用词不当
    REDUNDANCY = "redundancy"        # 冗余/重复用词


class ProofreadingIssue(BaseModel):
    """单条校对问题"""
    issue_type: ProofreadingIssueType
    original: str = Field(..., min_length=1, description="原文片段")
    correction: str = Field(..., min_length=1, description="修正后片段")
    explanation: str = Field("", description="问题说明")


class SettingConflict(BaseModel):
    """设定修改导致的章节冲突"""
    chapter_number: int = Field(..., ge=1)
    conflict_text: str = Field(..., min_length=1, description="冲突的原文片段")
    reason: str = Field(..., min_length=1, description="为什么冲突")
    suggested_fix: str = Field("", description="建议的修改方向")


class SettingImpact(BaseModel):
    """设定修改的影响评估结果"""
    modified_field: str = Field(..., description="修改的设定字段")
    old_summary: str = Field("", description="原设定摘要")
    new_summary: str = Field("", description="新设定摘要")
    affected_chapters: list[int] = Field(default_factory=list)
    conflicts: list[SettingConflict] = Field(default_factory=list)
    severity: Literal["low", "medium", "high"] = "medium"
    summary: str = Field("", description="影响评估总结")
