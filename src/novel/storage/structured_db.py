"""SQLite 结构化数据库 - 角色状态、时间线、专有名词、力量追踪、事实、章节摘要"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from src.novel.models.memory import ChapterSummary, Fact


class StructuredDB:
    """SQLite 结构化数据库管理

    单连接 + 线程锁保证线程安全。
    支持 context manager 自动关闭。
    """

    _SCHEMA = """
    -- 角色状态追踪表
    CREATE TABLE IF NOT EXISTS character_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        character_id TEXT NOT NULL,
        chapter INTEGER NOT NULL,
        health TEXT,
        location TEXT,
        power_level TEXT,
        emotional_state TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(character_id, chapter)
    );

    -- 时间线表
    CREATE TABLE IF NOT EXISTS timeline (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chapter INTEGER NOT NULL,
        scene INTEGER NOT NULL,
        absolute_time TEXT,
        relative_time TEXT,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(chapter, scene)
    );

    -- 专有名词表
    CREATE TABLE IF NOT EXISTS terms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term TEXT NOT NULL UNIQUE,
        definition TEXT NOT NULL,
        first_chapter INTEGER NOT NULL,
        category TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 力量等级追踪表
    CREATE TABLE IF NOT EXISTS power_tracking (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        character_id TEXT NOT NULL,
        chapter INTEGER NOT NULL,
        level TEXT NOT NULL,
        change_reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(character_id, chapter)
    );

    -- 事实表
    CREATE TABLE IF NOT EXISTS facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fact_id TEXT NOT NULL UNIQUE,
        chapter INTEGER NOT NULL,
        type TEXT NOT NULL,
        content TEXT NOT NULL,
        storage_layer TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 章节摘要表
    CREATE TABLE IF NOT EXISTS chapter_summaries (
        chapter INTEGER PRIMARY KEY,
        summary TEXT NOT NULL,
        key_events TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 索引
    CREATE INDEX IF NOT EXISTS idx_character_states_chapter
        ON character_states(chapter);
    CREATE INDEX IF NOT EXISTS idx_timeline_chapter
        ON timeline(chapter);
    CREATE INDEX IF NOT EXISTS idx_facts_chapter
        ON facts(chapter);
    CREATE INDEX IF NOT EXISTS idx_facts_type
        ON facts(type);
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._connect()
        self._init_schema()

    def _connect(self) -> None:
        """建立 SQLite 连接"""
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def _init_schema(self) -> None:
        """初始化表结构"""
        with self.transaction() as cur:
            cur.executescript(self._SCHEMA)

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """事务上下文管理器，自动 commit/rollback"""
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
        """关闭数据库连接"""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> "StructuredDB":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ========== character_states CRUD ==========

    def insert_character_state(
        self,
        character_id: str,
        chapter: int,
        health: str | None = None,
        location: str | None = None,
        power_level: str | None = None,
        emotional_state: str | None = None,
    ) -> None:
        """插入或更新角色状态"""
        with self.transaction() as cur:
            cur.execute(
                """INSERT INTO character_states
                   (character_id, chapter, health, location, power_level, emotional_state)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(character_id, chapter)
                   DO UPDATE SET
                       health = COALESCE(excluded.health, health),
                       location = COALESCE(excluded.location, location),
                       power_level = COALESCE(excluded.power_level, power_level),
                       emotional_state = COALESCE(excluded.emotional_state, emotional_state)
                """,
                (character_id, chapter, health, location, power_level, emotional_state),
            )

    def get_character_state(
        self, character_id: str, chapter: int | None = None
    ) -> dict[str, Any] | None:
        """查询角色状态，不指定章节则返回最新"""
        with self._lock:
            assert self._conn is not None, "Database connection is closed"
            cur = self._conn.cursor()
            if chapter is not None:
                cur.execute(
                    "SELECT * FROM character_states WHERE character_id=? AND chapter=?",
                    (character_id, chapter),
                )
            else:
                cur.execute(
                    "SELECT * FROM character_states WHERE character_id=? ORDER BY chapter DESC LIMIT 1",
                    (character_id,),
                )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_character_history(
        self, character_id: str
    ) -> list[dict[str, Any]]:
        """查询角色状态历史"""
        with self._lock:
            assert self._conn is not None, "Database connection is closed"
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM character_states WHERE character_id=? ORDER BY chapter ASC",
                (character_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    # ========== timeline CRUD ==========

    def insert_timeline(
        self,
        chapter: int,
        scene: int,
        absolute_time: str | None = None,
        relative_time: str | None = None,
        description: str | None = None,
    ) -> None:
        """插入或更新时间线事件"""
        with self.transaction() as cur:
            cur.execute(
                """INSERT INTO timeline
                   (chapter, scene, absolute_time, relative_time, description)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(chapter, scene)
                   DO UPDATE SET
                       absolute_time = COALESCE(excluded.absolute_time, absolute_time),
                       relative_time = COALESCE(excluded.relative_time, relative_time),
                       description = COALESCE(excluded.description, description)
                """,
                (chapter, scene, absolute_time, relative_time, description),
            )

    def get_timeline(
        self, chapter: int | None = None
    ) -> list[dict[str, Any]]:
        """查询时间线，可按章节过滤"""
        with self._lock:
            assert self._conn is not None, "Database connection is closed"
            cur = self._conn.cursor()
            if chapter is not None:
                cur.execute(
                    "SELECT * FROM timeline WHERE chapter=? ORDER BY scene ASC",
                    (chapter,),
                )
            else:
                cur.execute(
                    "SELECT * FROM timeline ORDER BY chapter ASC, scene ASC"
                )
            return [dict(row) for row in cur.fetchall()]

    # ========== terms CRUD ==========

    def insert_term(
        self,
        term: str,
        definition: str,
        first_chapter: int,
        category: str | None = None,
    ) -> None:
        """插入专有名词（忽略重复）"""
        with self.transaction() as cur:
            cur.execute(
                """INSERT INTO terms (term, definition, first_chapter, category)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(term) DO UPDATE SET
                       definition = excluded.definition
                """,
                (term, definition, first_chapter, category),
            )

    def get_term(self, term: str) -> dict[str, Any] | None:
        """查询单个术语"""
        with self._lock:
            assert self._conn is not None, "Database connection is closed"
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM terms WHERE term=?", (term,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_all_terms(self) -> list[dict[str, Any]]:
        """查询所有术语"""
        with self._lock:
            assert self._conn is not None, "Database connection is closed"
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM terms ORDER BY first_chapter ASC")
            return [dict(row) for row in cur.fetchall()]

    # ========== power_tracking CRUD ==========

    def insert_power_tracking(
        self,
        character_id: str,
        chapter: int,
        level: str,
        change_reason: str | None = None,
    ) -> None:
        """插入力量等级变化"""
        with self.transaction() as cur:
            cur.execute(
                """INSERT INTO power_tracking
                   (character_id, chapter, level, change_reason)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(character_id, chapter)
                   DO UPDATE SET level = excluded.level,
                       change_reason = excluded.change_reason
                """,
                (character_id, chapter, level, change_reason),
            )

    def get_power_level(
        self, character_id: str, chapter: int | None = None
    ) -> dict[str, Any] | None:
        """查询角色力量等级，不指定章节则返回最新"""
        with self._lock:
            assert self._conn is not None, "Database connection is closed"
            cur = self._conn.cursor()
            if chapter is not None:
                cur.execute(
                    "SELECT * FROM power_tracking WHERE character_id=? AND chapter=?",
                    (character_id, chapter),
                )
            else:
                cur.execute(
                    "SELECT * FROM power_tracking WHERE character_id=? ORDER BY chapter DESC LIMIT 1",
                    (character_id,),
                )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_power_history(
        self, character_id: str
    ) -> list[dict[str, Any]]:
        """查询力量等级变化历史"""
        with self._lock:
            assert self._conn is not None, "Database connection is closed"
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM power_tracking WHERE character_id=? ORDER BY chapter ASC",
                (character_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    # ========== facts CRUD ==========

    def insert_fact(self, fact: Fact) -> None:
        """插入事实"""
        with self.transaction() as cur:
            cur.execute(
                """INSERT INTO facts (fact_id, chapter, type, content, storage_layer)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(fact_id) DO NOTHING
                """,
                (fact.fact_id, fact.chapter, fact.type, fact.content, fact.storage_layer),
            )

    def get_facts(
        self,
        chapter: int | None = None,
        fact_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """查询事实，支持按章节和类型过滤"""
        with self._lock:
            assert self._conn is not None, "Database connection is closed"
            cur = self._conn.cursor()
            conditions: list[str] = []
            params: list[Any] = []
            if chapter is not None:
                conditions.append("chapter=?")
                params.append(chapter)
            if fact_type is not None:
                conditions.append("type=?")
                params.append(fact_type)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            cur.execute(
                f"SELECT * FROM facts {where} ORDER BY chapter ASC",
                params,
            )
            return [dict(row) for row in cur.fetchall()]

    # ========== chapter_summaries CRUD ==========

    def insert_summary(self, summary: ChapterSummary) -> None:
        """插入章节摘要"""
        with self.transaction() as cur:
            cur.execute(
                """INSERT INTO chapter_summaries (chapter, summary, key_events)
                   VALUES (?, ?, ?)
                   ON CONFLICT(chapter) DO UPDATE SET
                       summary = excluded.summary,
                       key_events = excluded.key_events
                """,
                (
                    summary.chapter,
                    summary.summary,
                    json.dumps(summary.key_events, ensure_ascii=False),
                ),
            )

    def get_summary(self, chapter: int) -> dict[str, Any] | None:
        """查询单章摘要"""
        with self._lock:
            assert self._conn is not None, "Database connection is closed"
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM chapter_summaries WHERE chapter=?", (chapter,)
            )
            row = cur.fetchone()
            if row is None:
                return None
            result = dict(row)
            result["key_events"] = json.loads(result["key_events"])
            return result

    def get_summaries(
        self, from_chapter: int = 1, to_chapter: int | None = None
    ) -> list[dict[str, Any]]:
        """查询章节摘要范围"""
        with self._lock:
            assert self._conn is not None, "Database connection is closed"
            cur = self._conn.cursor()
            if to_chapter is not None:
                cur.execute(
                    "SELECT * FROM chapter_summaries WHERE chapter >= ? AND chapter <= ? ORDER BY chapter ASC",
                    (from_chapter, to_chapter),
                )
            else:
                cur.execute(
                    "SELECT * FROM chapter_summaries WHERE chapter >= ? ORDER BY chapter ASC",
                    (from_chapter,),
                )
            rows = [dict(row) for row in cur.fetchall()]
            for row in rows:
                row["key_events"] = json.loads(row["key_events"])
            return rows
