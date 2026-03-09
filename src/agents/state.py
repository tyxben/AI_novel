from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class Decision(TypedDict, total=False):
    agent: str
    step: str
    decision: str
    reason: str
    data: dict | None
    timestamp: str


class QualityEvaluation(TypedDict, total=False):
    score: float
    composition: float
    clarity: float
    text_match: float
    color: float
    consistency: float
    feedback: str
    passed: bool


class AgentState(TypedDict, total=False):
    # 输入
    input_file: str  # 用 str 而非 Path，方便 JSON 序列化
    config: dict[str, Any]
    workspace: str

    # 流程控制
    mode: str  # "agent"
    budget_mode: bool
    resume: bool

    # 内容分析
    full_text: str
    genre: str | None
    era: str | None
    characters: list[dict] | None
    suggested_style: str | None

    # 各阶段结果
    segments: list[dict]
    prompts: list[str]
    images: list[str]  # 路径字符串
    video_clips: list[str] | None
    audio_files: list[str]
    srt_files: list[str]
    final_video: str | None

    # 质量控制
    quality_scores: list[float]
    retry_counts: dict[int, int]

    # 决策日志 — 使用 operator.add reducer，LangGraph 自动合并各节点的 decisions
    decisions: Annotated[list[Decision], operator.add]

    # 错误 — 同样使用 add reducer 累积
    errors: Annotated[list[dict], operator.add]

    # 断点续传 — 已完成节点列表，使用 add reducer 累积
    completed_nodes: Annotated[list[str], operator.add]

    # 流水线计划
    pipeline_plan: dict | None
