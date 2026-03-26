"""Prompt Registry - Core CRUD + prompt assembly engine.

SQLite-backed storage with version control, modular assembly, and quality tracking.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

from src.prompt_registry.models import (
    FeedbackRecord,
    PromptBlock,
    PromptTemplate,
    PromptUsage,
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompt_blocks (
    block_id TEXT PRIMARY KEY,
    base_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    block_type TEXT NOT NULL,
    agent TEXT NOT NULL DEFAULT 'universal',
    genre TEXT,
    scene_type TEXT,
    content TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    needs_optimization INTEGER NOT NULL DEFAULT 0,
    avg_score REAL,
    usage_count INTEGER NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_blocks_base_id ON prompt_blocks(base_id);
CREATE INDEX IF NOT EXISTS idx_blocks_active ON prompt_blocks(active);
CREATE INDEX IF NOT EXISTS idx_blocks_agent ON prompt_blocks(agent);
CREATE INDEX IF NOT EXISTS idx_blocks_type ON prompt_blocks(block_type);

CREATE TABLE IF NOT EXISTS prompt_templates (
    template_id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    scenario TEXT NOT NULL DEFAULT 'default',
    genre TEXT,
    block_refs TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_templates_agent ON prompt_templates(agent_name);
CREATE INDEX IF NOT EXISTS idx_templates_active ON prompt_templates(active);

CREATE TABLE IF NOT EXISTS prompt_usages (
    usage_id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    block_ids TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    scenario TEXT NOT NULL,
    novel_id TEXT,
    chapter_number INTEGER,
    quality_score REAL,
    strengths TEXT NOT NULL DEFAULT '[]',
    weaknesses TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_usages_template ON prompt_usages(template_id);
CREATE INDEX IF NOT EXISTS idx_usages_agent ON prompt_usages(agent_name);

CREATE TABLE IF NOT EXISTS feedback_records (
    record_id TEXT PRIMARY KEY,
    novel_id TEXT NOT NULL,
    chapter_number INTEGER NOT NULL,
    strengths TEXT NOT NULL DEFAULT '[]',
    weaknesses TEXT NOT NULL DEFAULT '[]',
    overall_score REAL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_novel ON feedback_records(novel_id);
CREATE INDEX IF NOT EXISTS idx_feedback_chapter ON feedback_records(novel_id, chapter_number);
"""


class PromptRegistry:
    """Dynamic prompt management system -- database storage, version control, modular assembly."""

    def __init__(self, db_path: str = "workspace/prompt_registry.db") -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._connect()
        self._init_schema()

    def _connect(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def _init_schema(self) -> None:
        with self._transaction() as cur:
            cur.executescript(_SCHEMA)

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        with self._lock:
            assert self._conn is not None, "Database connection is closed"
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> "PromptRegistry":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # =====================================================================
    # Block CRUD
    # =====================================================================

    def create_block(
        self,
        base_id: str,
        block_type: str,
        content: str,
        agent: str = "universal",
        genre: str | None = None,
        scene_type: str | None = None,
        metadata: dict | None = None,
    ) -> PromptBlock:
        """Create a new prompt block. If base_id already exists, creates a new version."""
        existing_versions = self.get_block_versions(base_id)
        if existing_versions:
            # Deactivate all existing versions
            with self._transaction() as cur:
                cur.execute(
                    "UPDATE prompt_blocks SET active = 0, updated_at = ? WHERE base_id = ?",
                    (_now_iso(), base_id),
                )
            version = max(b.version for b in existing_versions) + 1
        else:
            version = 1

        now = _now_iso()
        block = PromptBlock(
            base_id=base_id,
            version=version,
            block_type=block_type,
            agent=agent,
            genre=genre,
            scene_type=scene_type,
            content=content,
            active=True,
            metadata=metadata or {},
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )
        with self._transaction() as cur:
            cur.execute(
                """INSERT INTO prompt_blocks
                   (block_id, base_id, version, block_type, agent, genre, scene_type,
                    content, active, needs_optimization, avg_score, usage_count,
                    metadata, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    block.block_id,
                    block.base_id,
                    block.version,
                    block.block_type,
                    block.agent,
                    block.genre,
                    block.scene_type,
                    block.content,
                    1,
                    0,
                    block.avg_score,
                    block.usage_count,
                    json.dumps(block.metadata, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return block

    def get_active_block(self, base_id: str) -> PromptBlock | None:
        """Get the currently active version of a block by base_id."""
        with self._lock:
            assert self._conn is not None
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM prompt_blocks WHERE base_id = ? AND active = 1 ORDER BY version DESC LIMIT 1",
                (base_id,),
            )
            row = cur.fetchone()
            return _row_to_block(row) if row else None

    def get_block_versions(self, base_id: str) -> list[PromptBlock]:
        """Get all versions of a block by base_id, ordered by version ascending."""
        with self._lock:
            assert self._conn is not None
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM prompt_blocks WHERE base_id = ? ORDER BY version ASC",
                (base_id,),
            )
            return [_row_to_block(row) for row in cur.fetchall()]

    def update_block(
        self,
        base_id: str,
        content: str,
        metadata: dict | None = None,
    ) -> PromptBlock:
        """Create a new version of a block with updated content. Old version becomes inactive."""
        active = self.get_active_block(base_id)
        if active is None:
            raise ValueError(f"No active block found for base_id '{base_id}'")

        return self.create_block(
            base_id=base_id,
            block_type=active.block_type,
            content=content,
            agent=active.agent,
            genre=active.genre,
            scene_type=active.scene_type,
            metadata=metadata if metadata is not None else active.metadata,
        )

    def rollback_block(self, base_id: str, target_version: int) -> PromptBlock:
        """Rollback to a specific version: deactivate all, reactivate target."""
        versions = self.get_block_versions(base_id)
        target = None
        for v in versions:
            if v.version == target_version:
                target = v
                break
        if target is None:
            raise ValueError(
                f"Version {target_version} not found for base_id '{base_id}'"
            )

        now = _now_iso()
        with self._transaction() as cur:
            # Deactivate all
            cur.execute(
                "UPDATE prompt_blocks SET active = 0, updated_at = ? WHERE base_id = ?",
                (now, base_id),
            )
            # Activate target
            cur.execute(
                "UPDATE prompt_blocks SET active = 1, updated_at = ? WHERE block_id = ?",
                (now, target.block_id),
            )

        # Return refreshed block
        return self.get_active_block(base_id)  # type: ignore[return-value]

    def list_blocks(
        self,
        agent: str | None = None,
        block_type: str | None = None,
        active_only: bool = True,
    ) -> list[PromptBlock]:
        """List blocks with optional filters."""
        conditions: list[str] = []
        params: list[Any] = []
        if active_only:
            conditions.append("active = 1")
        if agent is not None:
            conditions.append("agent = ?")
            params.append(agent)
        if block_type is not None:
            conditions.append("block_type = ?")
            params.append(block_type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._lock:
            assert self._conn is not None
            cur = self._conn.cursor()
            cur.execute(
                f"SELECT * FROM prompt_blocks {where} ORDER BY base_id ASC, version DESC",
                params,
            )
            return [_row_to_block(row) for row in cur.fetchall()]

    # =====================================================================
    # Template CRUD
    # =====================================================================

    def create_template(
        self,
        template_id: str,
        agent_name: str,
        block_refs: list[str],
        scenario: str = "default",
        genre: str | None = None,
    ) -> PromptTemplate:
        """Create a new prompt template."""
        now = _now_iso()
        tpl = PromptTemplate(
            template_id=template_id,
            agent_name=agent_name,
            scenario=scenario,
            genre=genre,
            block_refs=block_refs,
            active=True,
            created_at=datetime.fromisoformat(now),
        )
        with self._transaction() as cur:
            cur.execute(
                """INSERT OR REPLACE INTO prompt_templates
                   (template_id, agent_name, scenario, genre, block_refs, active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    tpl.template_id,
                    tpl.agent_name,
                    tpl.scenario,
                    tpl.genre,
                    json.dumps(tpl.block_refs, ensure_ascii=False),
                    1,
                    now,
                ),
            )
        return tpl

    def get_template(self, template_id: str) -> PromptTemplate | None:
        """Get a template by its ID."""
        with self._lock:
            assert self._conn is not None
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM prompt_templates WHERE template_id = ?",
                (template_id,),
            )
            row = cur.fetchone()
            return _row_to_template(row) if row else None

    def get_template_for(
        self,
        agent_name: str,
        scenario: str = "default",
        genre: str | None = None,
    ) -> PromptTemplate | None:
        """Find best matching template with fallback logic.

        Fallback order:
        1. Exact match: agent_name + scenario + genre
        2. Genre fallback: agent_name + scenario + genre=None
        3. Scenario fallback: agent_name + scenario="default" + genre
        4. Both fallback: agent_name + scenario="default" + genre=None
        """
        with self._lock:
            assert self._conn is not None
            cur = self._conn.cursor()

            # Try exact match
            if genre is not None:
                cur.execute(
                    "SELECT * FROM prompt_templates WHERE agent_name = ? AND scenario = ? AND genre = ? AND active = 1",
                    (agent_name, scenario, genre),
                )
                row = cur.fetchone()
                if row:
                    return _row_to_template(row)

            # Fallback: same scenario, no genre
            cur.execute(
                "SELECT * FROM prompt_templates WHERE agent_name = ? AND scenario = ? AND genre IS NULL AND active = 1",
                (agent_name, scenario),
            )
            row = cur.fetchone()
            if row:
                return _row_to_template(row)

            # Fallback: default scenario with genre
            if scenario != "default" and genre is not None:
                cur.execute(
                    "SELECT * FROM prompt_templates WHERE agent_name = ? AND scenario = 'default' AND genre = ? AND active = 1",
                    (agent_name, genre),
                )
                row = cur.fetchone()
                if row:
                    return _row_to_template(row)

            # Fallback: default scenario, no genre
            if scenario != "default":
                cur.execute(
                    "SELECT * FROM prompt_templates WHERE agent_name = ? AND scenario = 'default' AND genre IS NULL AND active = 1",
                    (agent_name,),
                )
                row = cur.fetchone()
                if row:
                    return _row_to_template(row)

            return None

    def list_templates(self, agent_name: str | None = None) -> list[PromptTemplate]:
        """List templates, optionally filtered by agent name."""
        with self._lock:
            assert self._conn is not None
            cur = self._conn.cursor()
            if agent_name is not None:
                cur.execute(
                    "SELECT * FROM prompt_templates WHERE agent_name = ? AND active = 1 ORDER BY template_id ASC",
                    (agent_name,),
                )
            else:
                cur.execute(
                    "SELECT * FROM prompt_templates WHERE active = 1 ORDER BY template_id ASC"
                )
            return [_row_to_template(row) for row in cur.fetchall()]

    # =====================================================================
    # Prompt Assembly (core method)
    # =====================================================================

    def build_prompt(
        self,
        agent_name: str,
        scenario: str = "default",
        genre: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Assemble a complete prompt from template + blocks.

        1. Find matching template (agent_name + scenario + genre) with fallback
        2. Resolve each block_ref to its active block
        3. If context has feedback (last_strengths / last_weaknesses), inject into feedback_injection block
        4. Concatenate all blocks and return

        Fallback logic:
        - genre-specific template not found -> fall back to genre=None version
        - scenario-specific template not found -> fall back to scenario="default"
        - missing block -> skip (no error)
        """
        template = self.get_template_for(agent_name, scenario, genre)
        if template is None:
            return ""

        context = context or {}
        parts: list[str] = []
        used_block_ids: list[str] = []

        for ref in template.block_refs:
            # Resolve dynamic genre ref: "style_{genre}" -> "style_wuxia_classical"
            resolved_ref = ref
            if "{genre}" in ref and genre:
                resolved_ref = ref.replace("{genre}", genre)

            block = self.get_active_block(resolved_ref)
            if block is None:
                # Try without genre substitution as a last resort
                if resolved_ref != ref:
                    block = self.get_active_block(ref)
                if block is None:
                    continue

            content = block.content

            # Handle feedback_injection block: replace placeholders with context
            if block.block_type == "feedback_injection":
                last_strengths = context.get("last_strengths", [])
                last_weaknesses = context.get("last_weaknesses", [])
                if last_strengths or last_weaknesses:
                    strengths_text = "\n".join(f"- {s}" for s in last_strengths) if last_strengths else "（无）"
                    weaknesses_text = "\n".join(f"- {w}" for w in last_weaknesses) if last_weaknesses else "（无）"
                    content = content.replace("{strengths}", strengths_text)
                    content = content.replace("{weaknesses}", weaknesses_text)
                else:
                    # No feedback to inject, skip this block
                    continue

            parts.append(content)
            used_block_ids.append(block.block_id)

            # Increment usage count
            self._increment_usage_count(block.block_id)

        return "\n\n".join(parts)

    def _increment_usage_count(self, block_id: str) -> None:
        """Increment the usage_count for a block."""
        with self._transaction() as cur:
            cur.execute(
                "UPDATE prompt_blocks SET usage_count = usage_count + 1, updated_at = ? WHERE block_id = ?",
                (_now_iso(), block_id),
            )

    # =====================================================================
    # Usage Recording
    # =====================================================================

    def record_usage(
        self,
        template_id: str,
        block_ids: list[str],
        agent_name: str,
        scenario: str,
        novel_id: str | None = None,
        chapter_number: int | None = None,
    ) -> str:
        """Record a prompt usage event. Returns usage_id."""
        now = _now_iso()
        usage = PromptUsage(
            template_id=template_id,
            block_ids=block_ids,
            agent_name=agent_name,
            scenario=scenario,
            novel_id=novel_id,
            chapter_number=chapter_number,
            created_at=datetime.fromisoformat(now),
        )
        with self._transaction() as cur:
            cur.execute(
                """INSERT INTO prompt_usages
                   (usage_id, template_id, block_ids, agent_name, scenario,
                    novel_id, chapter_number, quality_score, strengths, weaknesses, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    usage.usage_id,
                    usage.template_id,
                    json.dumps(usage.block_ids, ensure_ascii=False),
                    usage.agent_name,
                    usage.scenario,
                    usage.novel_id,
                    usage.chapter_number,
                    usage.quality_score,
                    json.dumps(usage.strengths, ensure_ascii=False),
                    json.dumps(usage.weaknesses, ensure_ascii=False),
                    now,
                ),
            )
            # Increment usage_count on all referenced blocks
            for bid in block_ids:
                cur.execute(
                    "UPDATE prompt_blocks SET usage_count = usage_count + 1, updated_at = ? WHERE block_id = ?",
                    (now, bid),
                )
        return usage.usage_id

    def update_usage_score(
        self,
        usage_id: str,
        quality_score: float,
        strengths: list[str] | None = None,
        weaknesses: list[str] | None = None,
    ) -> None:
        """Update quality score and feedback for a usage record, then propagate to blocks."""
        with self._transaction() as cur:
            cur.execute(
                """UPDATE prompt_usages
                   SET quality_score = ?,
                       strengths = ?,
                       weaknesses = ?
                   WHERE usage_id = ?""",
                (
                    quality_score,
                    json.dumps(strengths or [], ensure_ascii=False),
                    json.dumps(weaknesses or [], ensure_ascii=False),
                    usage_id,
                ),
            )
        # Propagate score to blocks
        self._update_block_avg_scores(usage_id)

    def _update_block_avg_scores(self, usage_id: str) -> None:
        """Recalculate avg_score for all blocks referenced by this usage."""
        with self._lock:
            assert self._conn is not None
            cur = self._conn.cursor()
            cur.execute(
                "SELECT block_ids, quality_score FROM prompt_usages WHERE usage_id = ?",
                (usage_id,),
            )
            row = cur.fetchone()
            if row is None or row["quality_score"] is None:
                return
            block_ids = json.loads(row["block_ids"])

        for block_id in block_ids:
            with self._lock:
                assert self._conn is not None
                cur = self._conn.cursor()
                cur.execute(
                    """SELECT AVG(pu.quality_score) as avg_score
                       FROM prompt_usages pu
                       WHERE pu.quality_score IS NOT NULL
                         AND EXISTS (
                           SELECT 1 WHERE pu.block_ids LIKE ?
                         )""",
                    (f"%{block_id}%",),
                )
                avg_row = cur.fetchone()
                avg_score = avg_row["avg_score"] if avg_row and avg_row["avg_score"] is not None else None

            if avg_score is not None:
                with self._transaction() as cur:
                    cur.execute(
                        "UPDATE prompt_blocks SET avg_score = ?, updated_at = ? WHERE block_id = ?",
                        (avg_score, _now_iso(), block_id),
                    )

    # =====================================================================
    # Feedback Injection
    # =====================================================================

    def save_feedback(
        self,
        novel_id: str,
        chapter_number: int,
        strengths: list[str],
        weaknesses: list[str],
        overall_score: float | None = None,
    ) -> None:
        """Save chapter quality feedback."""
        now = _now_iso()
        record = FeedbackRecord(
            novel_id=novel_id,
            chapter_number=chapter_number,
            strengths=strengths,
            weaknesses=weaknesses,
            overall_score=overall_score,
            created_at=datetime.fromisoformat(now),
        )
        with self._transaction() as cur:
            cur.execute(
                """INSERT INTO feedback_records
                   (record_id, novel_id, chapter_number, strengths, weaknesses, overall_score, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.record_id,
                    record.novel_id,
                    record.chapter_number,
                    json.dumps(record.strengths, ensure_ascii=False),
                    json.dumps(record.weaknesses, ensure_ascii=False),
                    record.overall_score,
                    now,
                ),
            )

    def get_last_feedback(
        self, novel_id: str, current_chapter: int
    ) -> FeedbackRecord | None:
        """Get the feedback record of the chapter immediately before current_chapter."""
        with self._lock:
            assert self._conn is not None
            cur = self._conn.cursor()
            cur.execute(
                """SELECT * FROM feedback_records
                   WHERE novel_id = ? AND chapter_number < ?
                   ORDER BY chapter_number DESC LIMIT 1""",
                (novel_id, current_chapter),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return _row_to_feedback(row)

    # =====================================================================
    # Quality Tracking
    # =====================================================================

    def get_block_stats(self, base_id: str) -> dict:
        """Get statistics for a block: avg_score, usage_count, needs_optimization."""
        block = self.get_active_block(base_id)
        if block is None:
            return {"avg_score": None, "usage_count": 0, "needs_optimization": False}
        return {
            "avg_score": block.avg_score,
            "usage_count": block.usage_count,
            "needs_optimization": block.needs_optimization,
        }

    def analyze_performance(
        self, threshold: float = 6.0, min_usage: int = 10
    ) -> list[PromptBlock]:
        """Find blocks with avg_score below threshold and sufficient usage. Mark them as needs_optimization."""
        with self._lock:
            assert self._conn is not None
            cur = self._conn.cursor()
            cur.execute(
                """SELECT * FROM prompt_blocks
                   WHERE active = 1
                     AND avg_score IS NOT NULL
                     AND avg_score < ?
                     AND usage_count >= ?""",
                (threshold, min_usage),
            )
            rows = cur.fetchall()

        low_blocks = [_row_to_block(row) for row in rows]

        # Mark them as needs_optimization
        if low_blocks:
            now = _now_iso()
            with self._transaction() as cur:
                for block in low_blocks:
                    cur.execute(
                        "UPDATE prompt_blocks SET needs_optimization = 1, updated_at = ? WHERE block_id = ?",
                        (now, block.block_id),
                    )

        # Refresh and return
        return [self.get_active_block(b.base_id) for b in low_blocks if self.get_active_block(b.base_id) is not None]  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now().isoformat()


def _row_to_block(row: sqlite3.Row) -> PromptBlock:
    d = dict(row)
    return PromptBlock(
        block_id=d["block_id"],
        base_id=d["base_id"],
        version=d["version"],
        block_type=d["block_type"],
        agent=d["agent"],
        genre=d.get("genre"),
        scene_type=d.get("scene_type"),
        content=d["content"],
        active=bool(d["active"]),
        needs_optimization=bool(d["needs_optimization"]),
        avg_score=d.get("avg_score"),
        usage_count=d["usage_count"],
        metadata=json.loads(d["metadata"]) if d["metadata"] else {},
        created_at=datetime.fromisoformat(d["created_at"]),
        updated_at=datetime.fromisoformat(d["updated_at"]),
    )


def _row_to_template(row: sqlite3.Row) -> PromptTemplate:
    d = dict(row)
    return PromptTemplate(
        template_id=d["template_id"],
        agent_name=d["agent_name"],
        scenario=d["scenario"],
        genre=d.get("genre"),
        block_refs=json.loads(d["block_refs"]),
        active=bool(d["active"]),
        created_at=datetime.fromisoformat(d["created_at"]),
    )


def _row_to_feedback(row: sqlite3.Row) -> FeedbackRecord:
    d = dict(row)
    return FeedbackRecord(
        record_id=d["record_id"],
        novel_id=d["novel_id"],
        chapter_number=d["chapter_number"],
        strengths=json.loads(d["strengths"]) if d["strengths"] else [],
        weaknesses=json.loads(d["weaknesses"]) if d["weaknesses"] else [],
        overall_score=d.get("overall_score"),
        created_at=datetime.fromisoformat(d["created_at"]),
    )
