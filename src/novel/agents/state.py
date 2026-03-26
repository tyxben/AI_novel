"""NovelState - LangGraph 状态定义

小说创作流水线的共享状态，所有 Agent 节点通过该 TypedDict 传递数据。
累积字段（decisions / errors / completed_nodes）使用 operator.add reducer，
LangGraph 会自动合并各节点返回的列表。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class Decision(TypedDict, total=False):
    """决策记录"""

    agent: str
    step: str
    decision: str
    reason: str
    data: dict | None
    timestamp: str


class NovelState(TypedDict, total=False):
    # === 输入 ===
    genre: str  # 题材
    theme: str  # 主题
    target_words: int  # 目标字数
    style_name: str  # 风格预设名 (e.g. "webnovel.shuangwen")
    custom_style_reference: str | None  # 自定义风格参考
    template: str  # 大纲模板名称

    # === 导入模式 ===
    import_mode: bool  # 是否导入已有稿件
    import_file_path: str | None

    # === 项目状态 ===
    novel_id: str
    workspace: str
    config: dict

    # === 创作流程控制 ===
    current_chapter: int  # 当前进度
    total_chapters: int
    review_interval: int  # 审核间隔（每 N 章暂停）
    silent_mode: bool  # 静默模式（仅质量不达标时暂停）
    auto_approve_threshold: float  # 自动通过阈值

    # === 核心数据 ===
    outline: dict | None  # Outline.model_dump()
    world_setting: dict | None  # WorldSetting.model_dump()
    characters: list[dict]  # list[CharacterProfile.model_dump()]
    main_storyline: dict  # {protagonist_goal, core_conflict, character_arc, stakes, theme_statement}
    chapters: list[dict]  # list[Chapter.model_dump()]
    volume_snapshots: list[dict]  # list[VolumeSnapshot.model_dump()]

    # === 当前章节工作区 ===
    current_chapter_outline: dict | None
    current_scenes: list[dict] | None
    current_chapter_mood: str | None
    current_rhythm_instruction: str | None
    current_chapter_text: str | None
    current_chapter_quality: dict | None

    # === 质量控制 ===
    retry_counts: dict[int, int]  # {chapter_number: retry_count}
    max_retries: int  # 最大重试次数

    # === 决策日志（累积） ===
    decisions: Annotated[list[Decision], operator.add]

    # === 错误日志（累积） ===
    errors: Annotated[list[dict], operator.add]

    # === 流程控制 ===
    should_continue: bool

    # === 读者反馈 ===
    feedback_entries: list[dict]
    feedback_analysis: dict | None
    rewrite_queue: list[int]
    rewrite_instructions: dict

    # === 断点续传 ===
    completed_nodes: Annotated[list[str], operator.add]
    resume: bool

    # === Writer 模式控制 ===
    react_mode: bool  # Enable ReAct writer mode
    budget_mode: bool  # Budget mode for writer
    feedback_prompt: str  # Feedback injection prompt
    debt_summary: str  # Debt summary for writer

    # === 质量反馈注入 ===
    feedback_injector: Any  # FeedbackInjector instance (bridges QualityReviewer → Writer)
