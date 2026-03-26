# ReAct Agent Framework + Prompt Registry - 技术设计

## 1. 系统架构

### 1.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         AI 创意工坊平台                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │  小说生成     │  │  视频制作     │  │  PPT生成     │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    ReAct Agent Framework                             │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  ReactAgent (基类)                                            │  │
│  │  - run() 循环调度                                             │  │
│  │  - register_tool() 工具注册                                   │  │
│  │  - _execute_action() 工具执行                                 │  │
│  │  - _format_tools_for_prompt() 工具描述生成                    │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  具体 Agent 实现                                              │  │
│  │  - WriterReactAgent (generate/check/revise/submit)           │  │
│  │  - QualityReviewerReactAgent (check_rules/score/submit)      │  │
│  │  - PlotPlannerReactAgent (outline/validate/submit)           │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Prompt Registry                                 │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  PromptRegistry (核心类)                                      │  │
│  │  - get_prompt(agent, scenario, context)                      │  │
│  │  - create_block() / update_block() / get_block()             │  │
│  │  - create_template() / get_template()                        │  │
│  │  - record_usage() / update_quality_score()                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Quality Tracker (质量追踪)                                   │  │
│  │  - analyze_prompt_performance()                               │  │
│  │  - mark_low_quality_blocks()                                  │  │
│  │  - get_block_statistics()                                     │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Prompt Optimizer (自动优化)                                  │  │
│  │  - generate_improved_block()                                  │  │
│  │  - approve_improved_block()                                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    StructuredDB (SQLite)                             │
│  - prompt_blocks                                                     │
│  - prompt_templates                                                  │
│  - prompt_usage                                                      │
│  - feedback_records                                                  │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 模块职责

#### A. ReAct Agent Framework (`src/react/`)

**职责**：提供通用的 Thought → Action → Observe 循环引擎。

**核心类**：
- `ReactAgent`（基类）：循环调度逻辑
- `ReactToolRegistry`：工具注册和描述生成
- `ReactExecutor`：工具执行和异常处理

**不负责**：
- 具体工具的实现（由各 agent 自己实现）
- Prompt 内容（由 Prompt Registry 提供）

#### B. Prompt Registry (`src/prompt_registry/`)

**职责**：动态管理所有 prompt，支持模块化组装、版本控制、质量追踪。

**核心类**：
- `PromptRegistry`：CRUD 操作和 prompt 组装
- `QualityTracker`：质量统计和低分 block 标记
- `PromptOptimizer`：LLM 自动生成改进版
- `FeedbackInjector`：即时反馈注入

**不负责**：
- LLM 调用（使用 `create_llm_client` 工厂函数）
- 业务逻辑（由各 agent 处理）

#### C. Agent Tools (`src/novel/tools/react_tools/`)

**职责**：为 ReAct Agent 提供可调用的工具函数。

**核心工具**：
- `WriterTools`：generate_scene / check_repetition / check_logic / revise_scene / submit
- `QualityReviewerTools`：check_rules / check_style / llm_score / submit
- `PlotPlannerTools`：generate_outline / validate_structure / submit

**不负责**：
- 工具调度（由 ReactAgent 处理）
- Prompt 管理（由 Prompt Registry 处理）

---

## 2. 数据模型

### 2.1 数据库表设计

#### prompt_blocks 表

```sql
CREATE TABLE IF NOT EXISTS prompt_blocks (
    block_id TEXT PRIMARY KEY,              -- 含版本号，如 anti_ai_flavor_v2
    base_id TEXT NOT NULL,                  -- 不含版本号，如 anti_ai_flavor
    version INTEGER NOT NULL,               -- 版本号
    block_type TEXT NOT NULL,               -- system_instruction / craft_technique / anti_pattern / scene_specific / feedback_injection / few_shot_example
    content TEXT NOT NULL,                  -- Block 文本内容
    active BOOLEAN NOT NULL DEFAULT 1,      -- 是否启用（同一 base_id 只有一个 active=1）
    needs_optimization BOOLEAN NOT NULL DEFAULT 0, -- 是否需要优化
    metadata TEXT,                          -- JSON 元数据 {"author": "...", "description": "..."}
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (block_type IN (
        'system_instruction',
        'craft_technique',
        'anti_pattern',
        'scene_specific',
        'feedback_injection',
        'few_shot_example'
    ))
);

CREATE INDEX idx_prompt_blocks_base_id ON prompt_blocks(base_id);
CREATE INDEX idx_prompt_blocks_active ON prompt_blocks(active);
CREATE INDEX idx_prompt_blocks_type ON prompt_blocks(block_type);
CREATE UNIQUE INDEX idx_prompt_blocks_active_per_base
    ON prompt_blocks(base_id) WHERE active=1; -- 同一 base_id 只有一个 active
```

#### prompt_templates 表

```sql
CREATE TABLE IF NOT EXISTS prompt_templates (
    template_id TEXT PRIMARY KEY,           -- 如 writer_battle_template
    agent_name TEXT NOT NULL,               -- Writer / QualityReviewer / PlotPlanner
    scenario TEXT NOT NULL DEFAULT 'default', -- default / battle / dialogue / emotional / strategy
    block_order TEXT NOT NULL,              -- JSON 列表，如 ["system_instruction", "craft_technique", "anti_pattern"]
    active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_prompt_templates_agent ON prompt_templates(agent_name);
CREATE INDEX idx_prompt_templates_scenario ON prompt_templates(scenario);
CREATE INDEX idx_prompt_templates_active ON prompt_templates(active);
```

#### prompt_usage 表

```sql
CREATE TABLE IF NOT EXISTS prompt_usage (
    usage_id TEXT PRIMARY KEY,              -- UUID
    template_id TEXT NOT NULL,              -- 使用的 template
    block_ids TEXT NOT NULL,                -- 实际使用的 block 列表 JSON，如 ["anti_ai_flavor_v2", "battle_craft_v1"]
    agent_name TEXT NOT NULL,               -- Writer / QualityReviewer
    scenario TEXT NOT NULL,                 -- battle / dialogue
    context_summary TEXT,                   -- 上下文摘要（可选，用于调试）
    generated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    quality_score REAL,                     -- 质量评分（0-10，初始为 null）
    feedback_summary TEXT                   -- 简短反馈摘要，如 "重复使用比喻"
);

CREATE INDEX idx_prompt_usage_template ON prompt_usage(template_id);
CREATE INDEX idx_prompt_usage_agent ON prompt_usage(agent_name);
CREATE INDEX idx_prompt_usage_generated_at ON prompt_usage(generated_at);
CREATE INDEX idx_prompt_usage_quality_score ON prompt_usage(quality_score);
```

#### feedback_records 表

```sql
CREATE TABLE IF NOT EXISTS feedback_records (
    record_id TEXT PRIMARY KEY,             -- UUID
    novel_id TEXT NOT NULL,                 -- 小说 ID
    chapter_number INTEGER NOT NULL,        -- 章节号
    strengths TEXT,                         -- 优点列表 JSON，如 ["节奏紧凑", "心理描写细腻"]
    weaknesses TEXT,                        -- 问题列表 JSON，如 ["重复使用比喻", "对话雷同"]
    overall_score REAL,                     -- 总体评分（0-10）
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_feedback_records_novel ON feedback_records(novel_id);
CREATE INDEX idx_feedback_records_chapter ON feedback_records(chapter_number);
```

### 2.2 核心数据结构

#### PromptBlock（Pydantic 模型）

```python
from pydantic import BaseModel, Field
from typing import Literal

class PromptBlock(BaseModel):
    """Prompt Block 数据模型"""
    block_id: str                           # 含版本号
    base_id: str                            # 不含版本号
    version: int
    block_type: Literal[
        "system_instruction",
        "craft_technique",
        "anti_pattern",
        "scene_specific",
        "feedback_injection",
        "few_shot_example"
    ]
    content: str
    active: bool = True
    needs_optimization: bool = False
    metadata: dict = Field(default_factory=dict)
    created_at: str                         # ISO format timestamp
```

#### PromptTemplate（Pydantic 模型）

```python
class PromptTemplate(BaseModel):
    """Prompt Template 数据模型"""
    template_id: str
    agent_name: str                         # Writer / QualityReviewer / PlotPlanner
    scenario: str = "default"               # default / battle / dialogue / emotional / strategy
    block_order: list[str]                  # ["system_instruction", "craft_technique", ...]
    active: bool = True
    created_at: str
```

#### PromptUsage（Pydantic 模型）

```python
class PromptUsage(BaseModel):
    """Prompt 使用记录数据模型"""
    usage_id: str
    template_id: str
    block_ids: list[str]                    # 实际使用的 block 列表
    agent_name: str
    scenario: str
    context_summary: str | None = None
    generated_at: str
    quality_score: float | None = None
    feedback_summary: str | None = None
```

#### FeedbackRecord（Pydantic 模型）

```python
class FeedbackRecord(BaseModel):
    """反馈记录数据模型"""
    record_id: str
    novel_id: str
    chapter_number: int
    strengths: list[str] | None = None
    weaknesses: list[str] | None = None
    overall_score: float | None = None
    created_at: str
```

---

## 3. 核心模块设计

### 3.1 Prompt Registry 核心类

#### 文件：`src/prompt_registry/registry.py`

```python
"""Prompt Registry - 动态 Prompt 管理核心类"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path

from src.novel.storage.structured_db import StructuredDB
from src.prompt_registry.models import (
    PromptBlock, PromptTemplate, PromptUsage
)


class PromptRegistry:
    """Prompt Registry 核心类 - 管理所有 prompt 的 CRUD 操作"""

    def __init__(self, db: StructuredDB):
        """
        Args:
            db: StructuredDB 实例（复用现有存储层）
        """
        self.db = db
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """确保所有表存在"""
        with self.db.transaction() as cur:
            cur.executescript("""
                -- prompt_blocks 表 SQL（见 2.1 节）
                -- prompt_templates 表 SQL（见 2.1 节）
                -- prompt_usage 表 SQL（见 2.1 节）
            """)

    # ========== Prompt Block CRUD ==========

    def create_block(
        self,
        base_id: str,
        block_type: str,
        content: str,
        metadata: dict | None = None,
    ) -> PromptBlock:
        """创建新 block（自动生成 v1 或递增版本号）

        Args:
            base_id: Block 基础 ID（不含版本号）
            block_type: Block 类型
            content: Block 文本内容
            metadata: 可选元数据

        Returns:
            创建的 PromptBlock 对象
        """
        # 查询当前最大版本号
        with self.db._lock:
            cur = self.db._conn.cursor()
            cur.execute(
                "SELECT MAX(version) FROM prompt_blocks WHERE base_id=?",
                (base_id,)
            )
            row = cur.fetchone()
            max_version = row[0] if row[0] else 0

        new_version = max_version + 1
        block_id = f"{base_id}_v{new_version}"

        # 将旧版本设为 inactive
        with self.db.transaction() as cur:
            cur.execute(
                "UPDATE prompt_blocks SET active=0 WHERE base_id=? AND active=1",
                (base_id,)
            )
            # 插入新版本
            cur.execute(
                """INSERT INTO prompt_blocks
                   (block_id, base_id, version, block_type, content, active, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    block_id, base_id, new_version, block_type, content,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat()
                )
            )

        return self.get_block(block_id)

    def get_block(self, block_id: str) -> PromptBlock | None:
        """查询单个 block"""
        with self.db._lock:
            cur = self.db._conn.cursor()
            cur.execute(
                "SELECT * FROM prompt_blocks WHERE block_id=?",
                (block_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return PromptBlock(
                block_id=row["block_id"],
                base_id=row["base_id"],
                version=row["version"],
                block_type=row["block_type"],
                content=row["content"],
                active=bool(row["active"]),
                needs_optimization=bool(row["needs_optimization"]),
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                created_at=row["created_at"],
            )

    def get_active_block(self, base_id: str) -> PromptBlock | None:
        """查询当前启用的 block（同一 base_id 只有一个 active=1）"""
        with self.db._lock:
            cur = self.db._conn.cursor()
            cur.execute(
                "SELECT * FROM prompt_blocks WHERE base_id=? AND active=1",
                (base_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return PromptBlock(
                block_id=row["block_id"],
                base_id=row["base_id"],
                version=row["version"],
                block_type=row["block_type"],
                content=row["content"],
                active=bool(row["active"]),
                needs_optimization=bool(row["needs_optimization"]),
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                created_at=row["created_at"],
            )

    def get_block_versions(self, base_id: str) -> list[PromptBlock]:
        """查询 block 的所有版本（按版本号降序）"""
        with self.db._lock:
            cur = self.db._conn.cursor()
            cur.execute(
                "SELECT * FROM prompt_blocks WHERE base_id=? ORDER BY version DESC",
                (base_id,)
            )
            rows = cur.fetchall()
            return [
                PromptBlock(
                    block_id=row["block_id"],
                    base_id=row["base_id"],
                    version=row["version"],
                    block_type=row["block_type"],
                    content=row["content"],
                    active=bool(row["active"]),
                    needs_optimization=bool(row["needs_optimization"]),
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    def rollback_block(self, base_id: str, target_version: int) -> None:
        """回滚 block 到指定版本"""
        with self.db.transaction() as cur:
            # 将所有版本设为 inactive
            cur.execute(
                "UPDATE prompt_blocks SET active=0 WHERE base_id=?",
                (base_id,)
            )
            # 将目标版本设为 active
            cur.execute(
                "UPDATE prompt_blocks SET active=1 WHERE base_id=? AND version=?",
                (base_id, target_version)
            )

    # ========== Prompt Template CRUD ==========

    def create_template(
        self,
        template_id: str,
        agent_name: str,
        scenario: str,
        block_order: list[str],
    ) -> PromptTemplate:
        """创建 prompt template"""
        with self.db.transaction() as cur:
            cur.execute(
                """INSERT INTO prompt_templates
                   (template_id, agent_name, scenario, block_order, active, created_at)
                   VALUES (?, ?, ?, ?, 1, ?)
                """,
                (
                    template_id, agent_name, scenario,
                    json.dumps(block_order, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat()
                )
            )
        return self.get_template(template_id)

    def get_template(self, template_id: str) -> PromptTemplate | None:
        """查询单个 template"""
        with self.db._lock:
            cur = self.db._conn.cursor()
            cur.execute(
                "SELECT * FROM prompt_templates WHERE template_id=?",
                (template_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return PromptTemplate(
                template_id=row["template_id"],
                agent_name=row["agent_name"],
                scenario=row["scenario"],
                block_order=json.loads(row["block_order"]),
                active=bool(row["active"]),
                created_at=row["created_at"],
            )

    def get_template_by_agent_scenario(
        self, agent_name: str, scenario: str = "default"
    ) -> PromptTemplate | None:
        """根据 agent 和 scenario 查询 template（优先匹配 scenario，否则 fallback 到 default）"""
        with self.db._lock:
            cur = self.db._conn.cursor()
            # 先尝试精确匹配
            cur.execute(
                "SELECT * FROM prompt_templates WHERE agent_name=? AND scenario=? AND active=1",
                (agent_name, scenario)
            )
            row = cur.fetchone()
            if row:
                return PromptTemplate(
                    template_id=row["template_id"],
                    agent_name=row["agent_name"],
                    scenario=row["scenario"],
                    block_order=json.loads(row["block_order"]),
                    active=bool(row["active"]),
                    created_at=row["created_at"],
                )
            # Fallback 到 default
            if scenario != "default":
                cur.execute(
                    "SELECT * FROM prompt_templates WHERE agent_name=? AND scenario='default' AND active=1",
                    (agent_name,)
                )
                row = cur.fetchone()
                if row:
                    return PromptTemplate(
                        template_id=row["template_id"],
                        agent_name=row["agent_name"],
                        scenario=row["scenario"],
                        block_order=json.loads(row["block_order"]),
                        active=bool(row["active"]),
                        created_at=row["created_at"],
                    )
            return None

    # ========== Prompt 组装 ==========

    def get_prompt(
        self,
        agent_name: str,
        scenario: str = "default",
        context: dict | None = None,
    ) -> tuple[str, str, list[str]]:
        """根据 agent 和 scenario 组装完整 prompt

        Args:
            agent_name: Agent 名称
            scenario: 场景类型
            context: 上下文参数（用于 feedback_injection 等动态 block）

        Returns:
            (prompt_text, template_id, block_ids) 元组
            - prompt_text: 拼接后的完整 prompt
            - template_id: 使用的 template ID
            - block_ids: 实际使用的 block ID 列表
        """
        context = context or {}

        # 1. 查找 template
        template = self.get_template_by_agent_scenario(agent_name, scenario)
        if not template:
            raise ValueError(f"未找到 agent={agent_name}, scenario={scenario} 的 template")

        # 2. 按 block_order 查找所有 active block
        blocks = []
        block_ids = []
        for block_type in template.block_order:
            # 尝试场景特化 block（如 battle_craft）
            specialized_base_id = f"{scenario}_{block_type}"
            block = self.get_active_block(specialized_base_id)
            if not block:
                # Fallback 到通用 block
                block = self.get_active_block(block_type)
            if block:
                blocks.append(block)
                block_ids.append(block.block_id)

        # 3. 拼接 prompt（支持 context 变量插值）
        prompt_parts = []
        for block in blocks:
            content = block.content
            # 简单的变量替换（如 {last_weaknesses}）
            for key, value in context.items():
                placeholder = "{" + key + "}"
                if placeholder in content:
                    if isinstance(value, list):
                        content = content.replace(placeholder, "\n".join(f"- {v}" for v in value))
                    else:
                        content = content.replace(placeholder, str(value))
            prompt_parts.append(content)

        prompt_text = "\n\n".join(prompt_parts)
        return prompt_text, template.template_id, block_ids

    # ========== Prompt 使用记录 ==========

    def record_usage(
        self,
        template_id: str,
        block_ids: list[str],
        agent_name: str,
        scenario: str,
        context_summary: str | None = None,
    ) -> str:
        """记录 prompt 使用

        Returns:
            usage_id（供后续回填质量评分使用）
        """
        usage_id = str(uuid4())
        with self.db.transaction() as cur:
            cur.execute(
                """INSERT INTO prompt_usage
                   (usage_id, template_id, block_ids, agent_name, scenario, context_summary, generated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usage_id, template_id, json.dumps(block_ids, ensure_ascii=False),
                    agent_name, scenario, context_summary,
                    datetime.now(timezone.utc).isoformat()
                )
            )
        return usage_id

    def update_quality_score(
        self,
        usage_id: str,
        quality_score: float,
        feedback_summary: str | None = None,
    ) -> None:
        """回填质量评分"""
        with self.db.transaction() as cur:
            cur.execute(
                """UPDATE prompt_usage
                   SET quality_score=?, feedback_summary=?
                   WHERE usage_id=?
                """,
                (quality_score, feedback_summary, usage_id)
            )
```

---

### 3.2 Quality Tracker（质量追踪）

#### 文件：`src/prompt_registry/quality_tracker.py`

```python
"""Quality Tracker - Prompt 质量追踪和低分 block 标记"""

from __future__ import annotations
import json
from collections import defaultdict

from src.novel.storage.structured_db import StructuredDB


class QualityTracker:
    """质量追踪器 - 统计 prompt 效果并标记低分 block"""

    def __init__(self, db: StructuredDB):
        self.db = db

    def get_block_statistics(self, base_id: str) -> dict:
        """查询 block 的统计数据

        Returns:
            {
                "usage_count": 使用次数,
                "avg_score": 平均质量分,
                "scores": [所有评分列表],
                "needs_optimization": 是否需要优化
            }
        """
        with self.db._lock:
            cur = self.db._conn.cursor()
            # 查询所有使用记录（JSON 列表中包含该 base_id 的任意版本）
            cur.execute(
                """SELECT quality_score, feedback_summary
                   FROM prompt_usage
                   WHERE block_ids LIKE ?
                   AND quality_score IS NOT NULL
                """,
                (f'%{base_id}%',)  # 简单的 LIKE 查询（生产环境可优化为 JSON 函数）
            )
            rows = cur.fetchall()

            scores = [row["quality_score"] for row in rows if row["quality_score"] is not None]
            usage_count = len(scores)
            avg_score = sum(scores) / len(scores) if scores else 0.0

            # 查询当前 needs_optimization 状态
            cur.execute(
                "SELECT needs_optimization FROM prompt_blocks WHERE base_id=? AND active=1",
                (base_id,)
            )
            row = cur.fetchone()
            needs_optimization = bool(row["needs_optimization"]) if row else False

            return {
                "usage_count": usage_count,
                "avg_score": avg_score,
                "scores": scores,
                "needs_optimization": needs_optimization,
            }

    def analyze_prompt_performance(
        self,
        threshold: float = 6.0,
        min_usage_count: int = 20,
    ) -> dict:
        """分析所有 prompt block 的性能，标记低分 block

        Args:
            threshold: 低分阈值（平均分 < threshold 标记为需要优化）
            min_usage_count: 最小使用次数（样本量不足不统计）

        Returns:
            {
                "low_quality_blocks": [低分 block 列表],
                "high_quality_blocks": [高分 block 列表],
                "total_blocks_analyzed": 分析的 block 总数
            }
        """
        with self.db._lock:
            cur = self.db._conn.cursor()
            # 查询所有 active block 的 base_id
            cur.execute("SELECT DISTINCT base_id FROM prompt_blocks WHERE active=1")
            base_ids = [row["base_id"] for row in cur.fetchall()]

        low_quality_blocks = []
        high_quality_blocks = []

        for base_id in base_ids:
            stats = self.get_block_statistics(base_id)
            if stats["usage_count"] < min_usage_count:
                continue  # 样本量不足，跳过

            if stats["avg_score"] < threshold:
                low_quality_blocks.append({
                    "base_id": base_id,
                    "avg_score": stats["avg_score"],
                    "usage_count": stats["usage_count"],
                })
                # 标记为需要优化
                with self.db.transaction() as cur:
                    cur.execute(
                        "UPDATE prompt_blocks SET needs_optimization=1 WHERE base_id=? AND active=1",
                        (base_id,)
                    )
            elif stats["avg_score"] >= 7.0:
                high_quality_blocks.append({
                    "base_id": base_id,
                    "avg_score": stats["avg_score"],
                    "usage_count": stats["usage_count"],
                })
                # 清除优化标记
                with self.db.transaction() as cur:
                    cur.execute(
                        "UPDATE prompt_blocks SET needs_optimization=0 WHERE base_id=? AND active=1",
                        (base_id,)
                    )

        return {
            "low_quality_blocks": low_quality_blocks,
            "high_quality_blocks": high_quality_blocks,
            "total_blocks_analyzed": len(base_ids),
        }

    def get_block_weaknesses(self, base_id: str, limit: int = 50) -> list[str]:
        """查询 block 的历史 weaknesses（用于生成改进建议）

        Args:
            base_id: Block 基础 ID
            limit: 最多返回多少条 feedback

        Returns:
            weakness 列表（去重）
        """
        with self.db._lock:
            cur = self.db._conn.cursor()
            cur.execute(
                """SELECT feedback_summary
                   FROM prompt_usage
                   WHERE block_ids LIKE ?
                   AND feedback_summary IS NOT NULL
                   ORDER BY generated_at DESC
                   LIMIT ?
                """,
                (f'%{base_id}%', limit)
            )
            rows = cur.fetchall()

        weaknesses = []
        for row in rows:
            summary = row["feedback_summary"]
            if summary:
                # 简单按行分割（假设 feedback_summary 是多行文本）
                weaknesses.extend(line.strip() for line in summary.split('\n') if line.strip())

        # 去重
        return list(set(weaknesses))
```

---

### 3.3 Prompt Optimizer（自动优化）

#### 文件：`src/prompt_registry/optimizer.py`

```python
"""Prompt Optimizer - LLM 自动生成改进版 prompt"""

from __future__ import annotations
import logging

from src.llm.llm_client import create_llm_client, LLMClient
from src.novel.storage.structured_db import StructuredDB
from src.prompt_registry.registry import PromptRegistry
from src.prompt_registry.quality_tracker import QualityTracker

log = logging.getLogger("prompt_registry")


class PromptOptimizer:
    """Prompt 自动优化器 - LLM 生成改进版 block"""

    def __init__(
        self,
        db: StructuredDB,
        registry: PromptRegistry,
        tracker: QualityTracker,
        llm_client: LLMClient | None = None,
    ):
        self.db = db
        self.registry = registry
        self.tracker = tracker
        self.llm = llm_client or create_llm_client({})

    def generate_improved_block(self, base_id: str) -> dict:
        """为低分 block 生成改进版

        Args:
            base_id: Block 基础 ID

        Returns:
            {
                "status": "success" / "failed",
                "improved_block_id": 新 block ID（状态为 pending_review）,
                "original_content": 原版内容,
                "improved_content": 改进版内容,
                "improvement_reason": 改进理由,
            }
        """
        # 1. 查询当前 block
        current_block = self.registry.get_active_block(base_id)
        if not current_block:
            return {"status": "failed", "error": f"Block {base_id} 不存在"}

        # 2. 查询统计数据和 weaknesses
        stats = self.tracker.get_block_statistics(base_id)
        weaknesses = self.tracker.get_block_weaknesses(base_id, limit=50)

        # 3. 调用 LLM 生成改进版
        prompt = f"""你是一个 prompt 优化专家。请根据以下信息改进 prompt block：

## 当前 Block 内容
```
{current_block.content}
```

## Block 类型
{current_block.block_type}

## 统计数据
- 使用次数: {stats['usage_count']}
- 平均质量分: {stats['avg_score']:.2f} / 10
- 优化状态: {"需要优化" if stats['needs_optimization'] else "正常"}

## 历史反馈问题（weaknesses）
{chr(10).join(f"- {w}" for w in weaknesses[:20])}

## 任务
1. 分析当前 block 存在的问题（结合统计数据和历史反馈）
2. 生成改进版 block 内容（保持原有结构和风格，但针对性解决问题）
3. 说明改进的理由

## 输出格式（JSON）
{{
    "improved_content": "改进后的 block 文本内容",
    "improvement_reason": "改进理由说明（1-3 句话）"
}}
"""

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                json_mode=True,
                max_tokens=2048,
            )
            import json
            result = json.loads(response.content)
            improved_content = result["improved_content"]
            improvement_reason = result["improvement_reason"]
        except Exception as e:
            log.exception("LLM 生成改进版失败")
            return {"status": "failed", "error": str(e)}

        # 4. 创建新 block（状态为 pending_review，不自动激活）
        # 这里我们创建一个新版本但 active=False，需要人工审核后才能激活
        new_block = self._create_pending_block(
            base_id=base_id,
            block_type=current_block.block_type,
            content=improved_content,
            metadata={
                "status": "pending_review",
                "improvement_reason": improvement_reason,
                "original_block_id": current_block.block_id,
            }
        )

        return {
            "status": "success",
            "improved_block_id": new_block.block_id,
            "original_content": current_block.content,
            "improved_content": improved_content,
            "improvement_reason": improvement_reason,
        }

    def _create_pending_block(
        self, base_id: str, block_type: str, content: str, metadata: dict
    ):
        """创建待审核的 block（active=False）"""
        # 查询当前最大版本号
        with self.db._lock:
            cur = self.db._conn.cursor()
            cur.execute(
                "SELECT MAX(version) FROM prompt_blocks WHERE base_id=?",
                (base_id,)
            )
            row = cur.fetchone()
            max_version = row[0] if row[0] else 0

        new_version = max_version + 1
        block_id = f"{base_id}_v{new_version}_pending"

        from datetime import datetime, timezone
        with self.db.transaction() as cur:
            cur.execute(
                """INSERT INTO prompt_blocks
                   (block_id, base_id, version, block_type, content, active, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    block_id, base_id, new_version, block_type, content,
                    json.dumps(metadata, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat()
                )
            )

        return self.registry.get_block(block_id)

    def approve_improved_block(self, block_id: str) -> None:
        """批准改进版 block 上线（激活该版本，停用旧版本）"""
        block = self.registry.get_block(block_id)
        if not block:
            raise ValueError(f"Block {block_id} 不存在")

        with self.db.transaction() as cur:
            # 停用所有同 base_id 的旧版本
            cur.execute(
                "UPDATE prompt_blocks SET active=0 WHERE base_id=?",
                (block.base_id,)
            )
            # 激活当前版本
            cur.execute(
                "UPDATE prompt_blocks SET active=1 WHERE block_id=?",
                (block_id,)
            )

    def reject_improved_block(self, block_id: str) -> None:
        """拒绝改进版 block（标记为已拒绝，但保留记录）"""
        with self.db.transaction() as cur:
            cur.execute(
                """UPDATE prompt_blocks
                   SET metadata=json_set(metadata, '$.status', 'rejected')
                   WHERE block_id=?
                """,
                (block_id,)
            )
```

---

### 3.4 Feedback Injector（即时反馈注入）

#### 文件：`src/prompt_registry/feedback_injector.py`

```python
"""Feedback Injector - 即时反馈注入（上一章问题注入下次生成）"""

from __future__ import annotations
import json
from uuid import uuid4
from datetime import datetime, timezone

from src.novel.storage.structured_db import StructuredDB


class FeedbackInjector:
    """反馈注入器 - 管理章节反馈记录并注入到下次生成"""

    def __init__(self, db: StructuredDB):
        self.db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保 feedback_records 表存在"""
        with self.db.transaction() as cur:
            cur.executescript("""
                CREATE TABLE IF NOT EXISTS feedback_records (
                    record_id TEXT PRIMARY KEY,
                    novel_id TEXT NOT NULL,
                    chapter_number INTEGER NOT NULL,
                    strengths TEXT,
                    weaknesses TEXT,
                    overall_score REAL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_records_novel
                    ON feedback_records(novel_id);
                CREATE INDEX IF NOT EXISTS idx_feedback_records_chapter
                    ON feedback_records(chapter_number);
            """)

    def save_feedback(
        self,
        novel_id: str,
        chapter_number: int,
        strengths: list[str] | None = None,
        weaknesses: list[str] | None = None,
        overall_score: float | None = None,
    ) -> str:
        """保存章节反馈

        Returns:
            record_id
        """
        record_id = str(uuid4())
        with self.db.transaction() as cur:
            cur.execute(
                """INSERT INTO feedback_records
                   (record_id, novel_id, chapter_number, strengths, weaknesses, overall_score, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id, novel_id, chapter_number,
                    json.dumps(strengths or [], ensure_ascii=False),
                    json.dumps(weaknesses or [], ensure_ascii=False),
                    overall_score,
                    datetime.now(timezone.utc).isoformat()
                )
            )
        return record_id

    def get_last_feedback(self, novel_id: str, chapter_number: int) -> dict | None:
        """获取上一章的反馈（用于注入下次生成）

        Args:
            novel_id: 小说 ID
            chapter_number: 当前章节号（会查询 chapter_number - 1 的反馈）

        Returns:
            {
                "strengths": [...],
                "weaknesses": [...],
                "overall_score": 7.5
            }
        """
        prev_chapter = chapter_number - 1
        if prev_chapter < 1:
            return None

        with self.db._lock:
            cur = self.db._conn.cursor()
            cur.execute(
                """SELECT strengths, weaknesses, overall_score
                   FROM feedback_records
                   WHERE novel_id=? AND chapter_number=?
                   ORDER BY created_at DESC
                   LIMIT 1
                """,
                (novel_id, prev_chapter)
            )
            row = cur.fetchone()
            if not row:
                return None

            return {
                "strengths": json.loads(row["strengths"]) if row["strengths"] else [],
                "weaknesses": json.loads(row["weaknesses"]) if row["weaknesses"] else [],
                "overall_score": row["overall_score"],
            }

    def format_feedback_for_prompt(self, feedback: dict | None) -> str:
        """将反馈格式化为可注入 prompt 的文本

        Args:
            feedback: get_last_feedback() 返回的字典

        Returns:
            格式化后的反馈文本（用于注入 feedback_injection block）
        """
        if not feedback:
            return ""

        parts = []

        if feedback.get("strengths"):
            parts.append("【上一章亮点】")
            for s in feedback["strengths"]:
                parts.append(f"- {s}")
            parts.append("\n请继续保持这些优点。")

        if feedback.get("weaknesses"):
            parts.append("\n【上一章需要注意的问题】")
            for w in feedback["weaknesses"]:
                parts.append(f"- {w}")
            parts.append("\n本章请避免以上问题。")

        return "\n".join(parts)
```

---

### 3.5 ReAct Agent Framework 核心类

#### 文件：`src/react/agent.py`

```python
"""ReAct Agent Framework - 通用推理循环引擎"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Callable, Any

from src.llm.llm_client import LLMClient, create_llm_client

log = logging.getLogger("react")

# 最大迭代次数（防止无限循环）
MAX_ITERATIONS = 10


class ReactAgent:
    """ReAct Agent 基类 - 提供 Thought → Action → Observe 循环"""

    def __init__(self, llm_client: LLMClient | None = None):
        """
        Args:
            llm_client: LLM 客户端（可选，不提供则自动创建）
        """
        self.llm = llm_client or create_llm_client({})
        self._tools: dict[str, Callable] = {}
        self._tool_descriptions: list[dict] = []

    def register_tool(
        self,
        name: str,
        func: Callable,
        description: str,
        parameters: dict | None = None,
    ) -> None:
        """注册工具

        Args:
            name: 工具名称
            func: 工具函数（必须是同步函数）
            description: 工具描述
            parameters: 参数描述字典（格式：{"param_name": {"type": "string", "description": "..."}}）
        """
        self._tools[name] = func
        self._tool_descriptions.append({
            "name": name,
            "description": description,
            "parameters": parameters or {},
        })

    def _format_tools_for_prompt(self) -> str:
        """将注册的工具格式化为 LLM 可理解的文本"""
        lines = []
        for tool in self._tool_descriptions:
            params = ", ".join(
                f'{k}: {v.get("type", "any")}'
                for k, v in tool["parameters"].items()
            )
            lines.append(f'- {tool["name"]}({params}): {tool["description"]}')
        return "\n".join(lines)

    def _execute_action(self, action: dict) -> dict:
        """执行 action 对应的工具

        Args:
            action: {"tool": "工具名", "args": {参数字典}}

        Returns:
            {"success": True/False, "result": ..., "error": ...}
        """
        tool_name = action.get("tool", "")
        tool_args = action.get("args", {})

        if tool_name not in self._tools:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}",
            }

        try:
            result = self._tools[tool_name](**tool_args)
            return {
                "success": True,
                "result": result,
            }
        except Exception as e:
            log.exception("Tool %s execution failed", tool_name)
            return {
                "success": False,
                "error": str(e),
            }

    def run(
        self,
        initial_prompt: str,
        max_iterations: int = MAX_ITERATIONS,
        budget_mode: bool = False,
    ) -> dict:
        """运行 ReAct 循环

        Args:
            initial_prompt: 初始任务描述
            max_iterations: 最大迭代次数
            budget_mode: 省钱模式（跳过自检/修改，只执行 generate 和 submit）

        Returns:
            {
                "status": "success" / "failed" / "max_iterations_reached",
                "final_result": 最终结果,
                "loop_log": [每一步的日志],
                "total_iterations": 迭代次数,
            }
        """
        # 1. 构建系统 prompt
        system_prompt = f"""你是一个 ReAct Agent。你需要通过"思考-行动-观察"循环来完成任务。

## 可用工具
{self._format_tools_for_prompt()}

## 工作方式
1. 分析当前任务，思考下一步应该做什么
2. 选择合适的工具并提供参数
3. 观察工具执行结果
4. 根据结果决定下一步行动
5. 完成所有操作后，必须调用 submit 工具提交最终结果

## 回复格式（JSON）
每次回复必须是一个 JSON 对象：
{{
    "thinking": "你的思考过程",
    "action": {{
        "tool": "工具名",
        "args": {{参数字典}}
    }}
}}

{'【省钱模式】只执行必要的生成和提交操作，跳过所有检查和修改工具。' if budget_mode else ''}
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": initial_prompt},
        ]

        loop_log = []
        final_result = None

        # 2. 进入循环
        for iteration in range(1, max_iterations + 1):
            # 调用 LLM
            try:
                response = self.llm.chat(
                    messages=messages,
                    temperature=0.2,
                    json_mode=True,
                    max_tokens=2048,
                )
                agent_action = json.loads(response.content)
            except json.JSONDecodeError as e:
                log.error("LLM 返回非 JSON 格式: %s", response.content[:500])
                # 尝试提示 LLM 重试一次
                messages.append({
                    "role": "user",
                    "content": "你的回复格式错误，必须是 JSON 格式。请重新回复。",
                })
                continue
            except Exception as e:
                log.exception("LLM 调用失败")
                return {
                    "status": "failed",
                    "error": str(e),
                    "loop_log": loop_log,
                    "total_iterations": iteration - 1,
                }

            thinking = agent_action.get("thinking", "")
            action = agent_action.get("action", {})
            tool_name = action.get("tool", "")
            tool_args = action.get("args", {})

            log.info("[%d] Thinking: %s", iteration, thinking)
            log.info("[%d] Action: %s(%s)", iteration, tool_name, tool_args)

            # 省钱模式：跳过非必要工具
            if budget_mode:
                skip_tools = ["check_repetition", "check_logic", "check_character_names", "revise_scene"]
                if tool_name in skip_tools:
                    log.info("[%d] Budget mode: skipping %s", iteration, tool_name)
                    # 伪造一个成功的 observation
                    observation = {
                        "success": True,
                        "result": "Skipped in budget mode",
                    }
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({
                        "role": "user",
                        "content": f"[工具结果] {tool_name}: {json.dumps(observation, ensure_ascii=False)}",
                    })
                    loop_log.append({
                        "iteration": iteration,
                        "thinking": thinking,
                        "action": action,
                        "observation": observation,
                        "skipped": True,
                    })
                    continue

            # 执行工具
            observation = self._execute_action(action)

            log.info("[%d] Observation: %s", iteration, observation)

            # 记录日志
            loop_log.append({
                "iteration": iteration,
                "thinking": thinking,
                "action": action,
                "observation": observation,
            })

            # 检查是否提交
            if tool_name == "submit":
                final_result = observation.get("result")
                return {
                    "status": "success",
                    "final_result": final_result,
                    "loop_log": loop_log,
                    "total_iterations": iteration,
                }

            # 将 observation 注入下一轮消息
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": f"[工具结果] {tool_name}: {json.dumps(observation, ensure_ascii=False)[:2000]}",
            })

        # 3. 达到最大迭代次数，强制结束
        log.warning("达到最大迭代次数 %d，强制结束", max_iterations)
        return {
            "status": "max_iterations_reached",
            "final_result": final_result,
            "loop_log": loop_log,
            "total_iterations": max_iterations,
        }
```

---

### 3.6 Writer React Agent 实现示例

#### 文件：`src/novel/agents/writer_react.py`

```python
"""Writer React Agent - 基于 ReAct 框架的章节生成"""

from __future__ import annotations
import logging

from src.react.agent import ReactAgent
from src.llm.llm_client import LLMClient
from src.prompt_registry.registry import PromptRegistry
from src.prompt_registry.feedback_injector import FeedbackInjector
from src.novel.tools.react_tools.writer_tools import WriterTools

log = logging.getLogger("novel")


class WriterReactAgent(ReactAgent):
    """Writer ReAct Agent - 支持多轮自检和修改的章节生成"""

    def __init__(
        self,
        llm_client: LLMClient,
        prompt_registry: PromptRegistry,
        feedback_injector: FeedbackInjector,
        novel_id: str,
        chapter_number: int,
    ):
        super().__init__(llm_client)
        self.registry = prompt_registry
        self.feedback_injector = feedback_injector
        self.novel_id = novel_id
        self.chapter_number = chapter_number

        # 注册工具
        tools = WriterTools(llm_client, prompt_registry)
        self.register_tool(
            "generate_scene",
            tools.generate_scene,
            "根据大纲和设定生成场景初稿",
            {
                "outline": {"type": "dict", "description": "场景大纲"},
                "characters": {"type": "list", "description": "角色列表"},
                "world": {"type": "dict", "description": "世界观设定"},
                "context": {"type": "str", "description": "上文内容"},
            }
        )
        self.register_tool(
            "check_repetition",
            tools.check_repetition,
            "检查与前文的重复度",
            {
                "text": {"type": "str", "description": "待检查文本"},
                "previous_texts": {"type": "list", "description": "前文列表"},
            }
        )
        self.register_tool(
            "check_logic",
            tools.check_logic,
            "检查叙事逻辑（事件闭环、角色去向等）",
            {
                "text": {"type": "str", "description": "待检查文本"},
                "context": {"type": "dict", "description": "上下文信息"},
            }
        )
        self.register_tool(
            "check_character_names",
            tools.check_character_names,
            "检查角色名称一致性",
            {
                "text": {"type": "str", "description": "待检查文本"},
                "character_list": {"type": "list", "description": "角色名单"},
            }
        )
        self.register_tool(
            "revise_scene",
            tools.revise_scene,
            "根据问题列表修改文本",
            {
                "text": {"type": "str", "description": "原文本"},
                "issues": {"type": "list", "description": "问题列表"},
            }
        )
        self.register_tool(
            "submit",
            lambda text: text,  # submit 直接返回文本
            "提交最终结果",
            {"text": {"type": "str", "description": "最终文本"}}
        )

    def generate_chapter(
        self,
        chapter_outline: dict,
        characters: list[dict],
        world: dict,
        previous_chapters: list[str],
        react_mode: bool = True,
        budget_mode: bool = False,
    ) -> dict:
        """生成章节

        Args:
            chapter_outline: 章节大纲
            characters: 角色列表
            world: 世界观设定
            previous_chapters: 前文章节列表（用于去重检查）
            react_mode: 是否启用 ReAct 模式（False 则退化为 one-shot）
            budget_mode: 省钱模式（跳过自检/修改）

        Returns:
            {
                "status": "success" / "failed",
                "chapter_text": 生成的章节文本,
                "usage_id": prompt 使用记录 ID,
                "loop_log": ReAct 循环日志（仅 react_mode=True）,
            }
        """
        # 1. 获取上一章反馈
        last_feedback = self.feedback_injector.get_last_feedback(
            self.novel_id, self.chapter_number
        )
        feedback_text = self.feedback_injector.format_feedback_for_prompt(last_feedback)

        # 2. 从 Prompt Registry 获取 prompt
        scenario = self._detect_scenario(chapter_outline)  # battle / dialogue / emotional / default
        prompt_text, template_id, block_ids = self.registry.get_prompt(
            agent_name="Writer",
            scenario=scenario,
            context={"feedback": feedback_text}
        )

        # 3. 记录 prompt 使用
        usage_id = self.registry.record_usage(
            template_id=template_id,
            block_ids=block_ids,
            agent_name="Writer",
            scenario=scenario,
            context_summary=f"Chapter {self.chapter_number}",
        )

        # 4. 生成章节
        if not react_mode:
            # One-shot 模式（向后兼容）
            chapter_text = self._generate_one_shot(
                prompt_text, chapter_outline, characters, world
            )
            return {
                "status": "success",
                "chapter_text": chapter_text,
                "usage_id": usage_id,
            }
        else:
            # ReAct 模式
            initial_prompt = f"""{prompt_text}

## 任务
生成以下章节的正文内容：

章节大纲：
{chapter_outline}

角色列表：
{characters}

世界观设定：
{world}

前文章节数：{len(previous_chapters)}

## 要求
1. 先调用 generate_scene 生成初稿
2. 调用 check_repetition 检查与前文的重复度
3. 如有问题，调用 revise_scene 修改
4. 调用 check_logic 检查叙事逻辑
5. 调用 check_character_names 检查角色名称一致性
6. 完成后调用 submit 提交最终结果
"""
            result = self.run(
                initial_prompt=initial_prompt,
                max_iterations=10,
                budget_mode=budget_mode,
            )
            return {
                "status": result["status"],
                "chapter_text": result.get("final_result", ""),
                "usage_id": usage_id,
                "loop_log": result.get("loop_log", []),
            }

    def _detect_scenario(self, chapter_outline: dict) -> str:
        """根据章节大纲检测场景类型（简单规则，可优化为 LLM 判断）"""
        title = chapter_outline.get("title", "").lower()
        summary = chapter_outline.get("summary", "").lower()

        if any(keyword in title + summary for keyword in ["战斗", "打斗", "厮杀", "攻击"]):
            return "battle"
        if any(keyword in title + summary for keyword in ["对话", "交谈", "会议", "谈判"]):
            return "dialogue"
        if any(keyword in title + summary for keyword in ["悲伤", "感动", "泪水", "回忆"]):
            return "emotional"
        if any(keyword in title + summary for keyword in ["计划", "策略", "部署", "准备"]):
            return "strategy"

        return "default"

    def _generate_one_shot(
        self, prompt_text: str, chapter_outline: dict, characters: list, world: dict
    ) -> str:
        """One-shot 模式生成（向后兼容）"""
        messages = [
            {"role": "system", "content": prompt_text},
            {"role": "user", "content": f"章节大纲：{chapter_outline}"},
        ]
        response = self.llm.chat(messages, temperature=0.7, max_tokens=4096)
        return response.content
```

---

## 4. 与现有代码的集成方案

### 4.1 迁移路径

#### Phase 1: Prompt Registry 上线（Week 1-2）

**目标**：将现有硬编码 prompt 迁移到数据库，但不改变 agent 行为。

**步骤**：
1. 在 `src/novel/storage/structured_db.py` 中添加 prompt_blocks / prompt_templates / prompt_usage 表
2. 创建 `src/prompt_registry/` 模块
3. 编写迁移脚本 `scripts/migrate_prompts.py`：
   - 读取 `writer.py` 的 `_ANTI_AI_FLAVOR` 等常量，创建 prompt block
   - 读取 `style_presets.py` 的预设，创建 prompt block
   - 为 Writer / QualityReviewer / PlotPlanner 创建默认 template

**兼容性**：
- Writer 等 agent 增加一个可选参数 `use_prompt_registry=False`
- 默认仍使用硬编码 prompt，设置为 True 时从数据库读取
- Gradio Web UI 增加开关控制是否启用 Prompt Registry

#### Phase 2: ReAct 框架上线（Week 3-4）

**目标**：Writer 支持 ReAct 模式，但默认仍为 one-shot。

**步骤**：
1. 创建 `src/react/` 模块，实现 `ReactAgent` 基类
2. 创建 `src/novel/tools/react_tools/` 模块，实现 `WriterTools`
3. 创建 `WriterReactAgent`，继承 `ReactAgent`
4. 修改 `Writer` 类，增加 `react_mode` 参数：
   ```python
   def generate_chapter(..., react_mode=False, budget_mode=False):
       if react_mode:
           agent = WriterReactAgent(...)
           return agent.generate_chapter(...)
       else:
           # 原有 one-shot 逻辑
           return self._generate_one_shot(...)
   ```

**兼容性**：
- 默认 `react_mode=False`，行为与现在完全一致
- Gradio Web UI 增加 "ReAct 模式" 开关

#### Phase 3: 质量闭环上线（Week 5-6）

**目标**：prompt_usage 记录和即时反馈注入。

**步骤**：
1. 修改 `QualityReviewer`，评审完成后调用 `FeedbackInjector.save_feedback()`
2. 修改 `Writer`，生成前调用 `FeedbackInjector.get_last_feedback()` 获取上一章反馈
3. 实现 `QualityTracker.analyze_prompt_performance()` 定时任务（每周运行一次）

**验证**：
- 生成 20 章后，查看 prompt_usage 表有记录
- 查看低分 block 被标记 `needs_optimization=True`

#### Phase 4: 自动优化上线（Week 7-8）

**目标**：LLM 自动生成改进版 prompt，人工审核后上线。

**步骤**：
1. 实现 `PromptOptimizer.generate_improved_block()`
2. 创建 Gradio 管理界面（或 FastAPI + 前端）：
   - Prompt Block 管理页面
   - 质量分析看板
   - 改进版审核页面

**灰度发布**：
- 10% 流量使用 ReAct 模式，监控成本和质量
- 质量提升 >= 1.0 分，成本 < 3x one-shot 时，扩大到 50%
- 最终全量切换（budget_mode 作为降级开关）

---

### 4.2 代码改动点

#### 修改 `src/novel/agents/writer.py`

```python
class Writer:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        # 新增：Prompt Registry 和 Feedback Injector（可选）
        self.prompt_registry: PromptRegistry | None = None
        self.feedback_injector: FeedbackInjector | None = None

    def enable_prompt_registry(
        self, registry: PromptRegistry, feedback_injector: FeedbackInjector
    ) -> None:
        """启用 Prompt Registry（向后兼容）"""
        self.prompt_registry = registry
        self.feedback_injector = feedback_injector

    def generate_scene(
        self,
        outline: dict,
        characters: list,
        world: dict,
        context: str,
        react_mode: bool = False,
        budget_mode: bool = False,
    ) -> str:
        """生成场景（支持 one-shot 和 ReAct 两种模式）"""
        if react_mode and self.prompt_registry:
            # ReAct 模式
            agent = WriterReactAgent(
                llm_client=self.llm,
                prompt_registry=self.prompt_registry,
                feedback_injector=self.feedback_injector,
                novel_id=...,  # 从外部传入
                chapter_number=...,
            )
            result = agent.generate_chapter(
                chapter_outline=outline,
                characters=characters,
                world=world,
                previous_chapters=...,
                react_mode=True,
                budget_mode=budget_mode,
            )
            return result["chapter_text"]
        else:
            # One-shot 模式（原有逻辑）
            return self._generate_one_shot(outline, characters, world, context)
```

#### 修改 `src/novel/agents/quality_reviewer.py`

```python
class QualityReviewer:
    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client
        # 新增：Feedback Injector 和 Prompt Registry（可选）
        self.feedback_injector: FeedbackInjector | None = None
        self.prompt_registry: PromptRegistry | None = None

    def enable_feedback_loop(
        self, feedback_injector: FeedbackInjector, prompt_registry: PromptRegistry
    ) -> None:
        """启用反馈闭环"""
        self.feedback_injector = feedback_injector
        self.prompt_registry = prompt_registry

    def review_chapter(self, chapter_text: str, ...) -> dict:
        """质量评审（评审完成后保存反馈）"""
        result = self._do_review(chapter_text, ...)

        # 保存反馈到数据库（如果启用了反馈闭环）
        if self.feedback_injector:
            self.feedback_injector.save_feedback(
                novel_id=...,
                chapter_number=...,
                strengths=result.get("strengths", []),
                weaknesses=result.get("weaknesses", []),
                overall_score=result.get("overall_score"),
            )

        # 回填质量评分到 prompt_usage（如果有 usage_id）
        if self.prompt_registry and "usage_id" in result:
            self.prompt_registry.update_quality_score(
                usage_id=result["usage_id"],
                quality_score=result["overall_score"],
                feedback_summary="\n".join(result.get("weaknesses", [])),
            )

        return result
```

#### 修改 `src/novel/pipeline.py`

```python
class NovelPipeline:
    def __init__(self, workspace: str):
        self.workspace = workspace
        # 新增：初始化 Prompt Registry 和 Feedback Injector
        db_path = Path(workspace) / "novels" / "prompt_registry.db"
        self.db = StructuredDB(db_path)
        self.prompt_registry = PromptRegistry(self.db)
        self.feedback_injector = FeedbackInjector(self.db)

    def generate_chapters(
        self,
        project_path: str,
        start_chapter: int,
        end_chapter: int,
        react_mode: bool = False,  # 新增参数
        budget_mode: bool = False,  # 新增参数
    ) -> dict:
        """生成章节"""
        # 为 Writer 和 QualityReviewer 启用 Prompt Registry
        writer = Writer(llm_client)
        writer.enable_prompt_registry(self.prompt_registry, self.feedback_injector)

        reviewer = QualityReviewer(llm_client)
        reviewer.enable_feedback_loop(self.feedback_injector, self.prompt_registry)

        for chapter_num in range(start_chapter, end_chapter + 1):
            # 生成章节
            result = writer.generate_scene(
                outline=...,
                characters=...,
                world=...,
                context=...,
                react_mode=react_mode,
                budget_mode=budget_mode,
            )

            # 评审章节
            review_result = reviewer.review_chapter(
                chapter_text=result,
                usage_id=result.get("usage_id"),  # 传递 usage_id
                ...
            )

            # ... 保存章节
```

---

## 5. API 设计

### 5.1 Prompt Registry API

#### `PromptRegistry.get_prompt(agent_name, scenario, context) -> (str, str, list[str])`

**描述**：根据 agent 和 scenario 组装完整 prompt。

**参数**：
- `agent_name` (str): Agent 名称（Writer / QualityReviewer / PlotPlanner）
- `scenario` (str): 场景类型（default / battle / dialogue / emotional / strategy）
- `context` (dict): 上下文参数（用于动态 block 变量替换）

**返回**：
- `prompt_text` (str): 拼接后的完整 prompt
- `template_id` (str): 使用的 template ID
- `block_ids` (list[str]): 实际使用的 block ID 列表

**示例**：
```python
prompt_text, template_id, block_ids = registry.get_prompt(
    agent_name="Writer",
    scenario="battle",
    context={"last_weaknesses": ["重复使用比喻", "对话雷同"]}
)
```

---

#### `PromptRegistry.create_block(base_id, block_type, content, metadata) -> PromptBlock`

**描述**：创建新 block（自动生成版本号）。

**参数**：
- `base_id` (str): Block 基础 ID（不含版本号，如 `anti_ai_flavor`）
- `block_type` (str): Block 类型（`system_instruction` / `craft_technique` / `anti_pattern` / `scene_specific` / `feedback_injection` / `few_shot_example`）
- `content` (str): Block 文本内容
- `metadata` (dict, optional): 元数据（作者、描述等）

**返回**：
- `PromptBlock` 对象

**示例**：
```python
block = registry.create_block(
    base_id="anti_ai_flavor",
    block_type="anti_pattern",
    content="【重要】禁止使用：内心翻涌、莫名的力量...",
    metadata={"author": "admin", "description": "反 AI 味指令"}
)
```

---

#### `PromptRegistry.record_usage(template_id, block_ids, agent_name, scenario, context_summary) -> str`

**描述**：记录 prompt 使用（供后续回填质量评分）。

**参数**：
- `template_id` (str): 使用的 template ID
- `block_ids` (list[str]): 实际使用的 block ID 列表
- `agent_name` (str): 生成内容的 agent
- `scenario` (str): 场景类型
- `context_summary` (str, optional): 上下文摘要（用于调试）

**返回**：
- `usage_id` (str): 使用记录 ID

---

#### `PromptRegistry.update_quality_score(usage_id, quality_score, feedback_summary) -> None`

**描述**：回填质量评分（由 QualityReviewer 调用）。

**参数**：
- `usage_id` (str): 使用记录 ID
- `quality_score` (float): 质量评分（0-10）
- `feedback_summary` (str, optional): 简短反馈摘要

---

### 5.2 Quality Tracker API

#### `QualityTracker.analyze_prompt_performance(threshold, min_usage_count) -> dict`

**描述**：分析所有 prompt block 的性能，标记低分 block。

**参数**：
- `threshold` (float): 低分阈值（默认 6.0）
- `min_usage_count` (int): 最小使用次数（默认 20）

**返回**：
```python
{
    "low_quality_blocks": [
        {"base_id": "dialogue_craft", "avg_score": 5.2, "usage_count": 25},
        ...
    ],
    "high_quality_blocks": [
        {"base_id": "anti_ai_flavor", "avg_score": 7.8, "usage_count": 30},
        ...
    ],
    "total_blocks_analyzed": 15
}
```

---

### 5.3 Prompt Optimizer API

#### `PromptOptimizer.generate_improved_block(base_id) -> dict`

**描述**：为低分 block 生成改进版（状态为 pending_review）。

**参数**：
- `base_id` (str): Block 基础 ID

**返回**：
```python
{
    "status": "success",
    "improved_block_id": "dialogue_craft_v3_pending",
    "original_content": "原版内容...",
    "improved_content": "改进版内容...",
    "improvement_reason": "增加了角色语言习惯的具体要求..."
}
```

---

#### `PromptOptimizer.approve_improved_block(block_id) -> None`

**描述**：批准改进版 block 上线（激活该版本，停用旧版本）。

---

### 5.4 Feedback Injector API

#### `FeedbackInjector.save_feedback(novel_id, chapter_number, strengths, weaknesses, overall_score) -> str`

**描述**：保存章节反馈。

**返回**：
- `record_id` (str): 反馈记录 ID

---

#### `FeedbackInjector.get_last_feedback(novel_id, chapter_number) -> dict | None`

**描述**：获取上一章的反馈（用于注入下次生成）。

**返回**：
```python
{
    "strengths": ["节奏紧凑", "心理描写细腻"],
    "weaknesses": ["重复使用比喻", "对话雷同"],
    "overall_score": 7.5
}
```

---

## 6. 测试策略

### 6.1 单元测试

**文件**：`tests/prompt_registry/test_registry.py`

测试内容：
- `test_create_block`: 创建 block，验证版本号自动递增
- `test_get_active_block`: 查询 active block，验证只有一个 active=True
- `test_rollback_block`: 回滚到历史版本，验证 active 状态切换
- `test_create_template`: 创建 template，验证 block_order JSON 存储
- `test_get_prompt`: 组装 prompt，验证 block 拼接和变量替换
- `test_record_usage`: 记录 prompt 使用，验证 usage_id 生成
- `test_update_quality_score`: 回填质量评分，验证更新成功

---

**文件**：`tests/prompt_registry/test_quality_tracker.py`

测试内容：
- `test_get_block_statistics`: 查询 block 统计，验证平均分计算
- `test_analyze_prompt_performance`: 分析性能，验证低分 block 标记
- `test_get_block_weaknesses`: 查询历史 weaknesses，验证去重

---

**文件**：`tests/prompt_registry/test_optimizer.py`

测试内容：
- `test_generate_improved_block`: LLM 生成改进版，验证 pending_review 状态
- `test_approve_improved_block`: 批准改进版，验证 active 状态切换
- `test_reject_improved_block`: 拒绝改进版，验证 rejected 标记

---

**文件**：`tests/react/test_agent.py`

测试内容：
- `test_register_tool`: 注册工具，验证 _tool_descriptions 更新
- `test_execute_action`: 执行工具，验证成功/失败返回
- `test_run_loop`: 运行循环，验证 thinking/action/observation 日志
- `test_budget_mode`: 省钱模式，验证跳过 check 工具
- `test_max_iterations`: 达到最大迭代次数，验证强制结束

---

### 6.2 集成测试

**文件**：`tests/novel/test_writer_react.py`

测试内容：
- `test_writer_react_mode`: Writer ReAct 模式生成章节，验证多轮循环
- `test_writer_one_shot_mode`: Writer one-shot 模式，验证向后兼容
- `test_feedback_injection`: 验证上一章反馈注入到 prompt
- `test_quality_score_backfill`: 验证 QualityReviewer 回填质量评分

---

### 6.3 端到端测试

**文件**：`tests/novel/test_pipeline_react.py`

测试内容：
- 完整流程：创建小说 → 生成 5 章（ReAct 模式）→ 评审 → 查看反馈 → 查看 prompt_usage 记录 → 分析 prompt 性能 → 生成改进版 → 批准上线

---

## 7. 性能优化

### 7.1 数据库优化

- **索引**：为 `block_id`、`base_id`、`template_id`、`agent_name`、`scenario`、`generated_at`、`quality_score` 创建索引
- **WAL 模式**：SQLite 开启 WAL 模式，减少锁竞争
- **异步插入**：prompt_usage 记录插入使用异步队列，不阻塞生成流程

### 7.2 Prompt 缓存

- 对于同一 agent + scenario，缓存组装后的 prompt（LRU cache）
- 仅当 block 版本更新时清除缓存

### 7.3 ReAct 循环优化

- 限制每轮 observation 的字符数（最多 2000 字符），避免 context 过长
- Budget mode 跳过所有 check 工具，LLM 调用次数与 one-shot 相同

---

## 8. 安全考虑

### 8.1 SQL 注入防护

- 所有数据库操作使用参数化查询（`?` 占位符）
- 不拼接 SQL 字符串

### 8.2 Prompt Injection 防护

- 用户输入的 context 参数需要过滤特殊字符（如 `{}`、`"`）
- LLM 生成的改进版 prompt 必须经过人工审核才能上线

### 8.3 数据备份

- 每周自动备份 prompt_registry.db
- 提供导出/导入功能（JSON 格式）

---

## 9. 监控和日志

### 9.1 关键指标

- **Prompt 使用量**：每个 block 的使用次数（按 agent / scenario 分组）
- **质量评分趋势**：每个 block 的平均分趋势图
- **ReAct 循环效率**：平均迭代次数、工具调用分布
- **LLM 成本**：ReAct 模式 vs one-shot 模式的成本对比

### 9.2 日志记录

- **Prompt Registry**：所有 CRUD 操作记录日志（操作人、时间、修改内容）
- **ReAct Agent**：每轮循环记录 thinking、action、observation、耗时
- **Prompt Optimizer**：LLM 生成改进版记录日志（原版、改进版、审核结果）

---

## 10. 未来扩展

### 10.1 多模态 Prompt（Phase 5）

- 支持图片 + 文本的 prompt block（如 few-shot example 包含图片）
- 视频和 PPT 产品线使用图片 prompt

### 10.2 A/B 测试（Phase 6）

- 同一章节用两个 prompt 版本生成，对比质量评分
- 自动选择高分版本上线

### 10.3 强化学习优化（Phase 7）

- 将 Prompt Optimizer 升级为强化学习模型
- 根据历史质量分自动调整 prompt 参数（temperature、block 权重等）

---

## 附录：目录结构

```
src/
├── prompt_registry/
│   ├── __init__.py
│   ├── models.py                  # Pydantic 数据模型
│   ├── registry.py                # PromptRegistry 核心类
│   ├── quality_tracker.py         # 质量追踪
│   ├── optimizer.py               # 自动优化
│   └── feedback_injector.py       # 即时反馈注入
├── react/
│   ├── __init__.py
│   ├── agent.py                   # ReactAgent 基类
│   └── tools.py                   # 通用工具函数
├── novel/
│   ├── agents/
│   │   ├── writer.py              # 修改：支持 Prompt Registry
│   │   ├── writer_react.py        # 新增：WriterReactAgent
│   │   ├── quality_reviewer.py    # 修改：支持反馈闭环
│   │   └── ...
│   ├── tools/
│   │   └── react_tools/
│   │       ├── __init__.py
│   │       ├── writer_tools.py    # Writer 工具集
│   │       └── reviewer_tools.py  # QualityReviewer 工具集
│   └── pipeline.py                # 修改：集成 Prompt Registry
└── ...

tests/
├── prompt_registry/
│   ├── test_registry.py
│   ├── test_quality_tracker.py
│   └── test_optimizer.py
├── react/
│   └── test_agent.py
└── novel/
    ├── test_writer_react.py
    └── test_pipeline_react.py

scripts/
├── migrate_prompts.py             # Prompt 迁移脚本
└── analyze_prompt_performance.py  # 定时任务：分析 prompt 性能
```
