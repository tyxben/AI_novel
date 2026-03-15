"""SQLite-based task persistence."""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .models import TaskRecord, TaskStatus, TaskType

_DB_DIR = Path.home() / ".novel-video"
_DB_PATH = _DB_DIR / "tasks.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id     TEXT PRIMARY KEY,
    task_type   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    progress    REAL NOT NULL DEFAULT 0.0,
    progress_msg TEXT NOT NULL DEFAULT '',
    params      TEXT NOT NULL DEFAULT '{}',
    result      TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT
)
"""


class TaskDB:
    """Thread-safe SQLite task store (connection-per-call)."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or _DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ---- internal helpers ----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(_CREATE_TABLE)
            # Recover orphaned running tasks from prior crash
            conn.execute(
                "UPDATE tasks SET status = ?, error = ? WHERE status = ?",
                (
                    TaskStatus.failed.value,
                    "Server restarted — task interrupted",
                    TaskStatus.running.value,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt else None

    @staticmethod
    def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
        return datetime.fromisoformat(s) if s else None

    def _row_to_record(self, row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            task_id=row["task_id"],
            task_type=TaskType(row["task_type"]),
            status=TaskStatus(row["status"]),
            progress=row["progress"],
            progress_msg=row["progress_msg"],
            params=json.loads(row["params"]),
            result=row["result"],
            error=row["error"],
            created_at=self._str_to_dt(row["created_at"]),  # type: ignore[arg-type]
            started_at=self._str_to_dt(row["started_at"]),
            finished_at=self._str_to_dt(row["finished_at"]),
        )

    # ---- public API ----

    def create_task(self, task_type: TaskType, params: dict) -> TaskRecord:
        """Insert a new pending task and return the record."""
        task_id = uuid.uuid4().hex[:12]
        now = datetime.now()
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO tasks
                   (task_id, task_type, status, progress, progress_msg,
                    params, result, error, created_at, started_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    task_type.value,
                    TaskStatus.pending.value,
                    0.0,
                    "",
                    json.dumps(params, ensure_ascii=False),
                    None,
                    None,
                    self._dt_to_str(now),
                    None,
                    None,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return TaskRecord(
            task_id=task_id,
            task_type=task_type,
            params=params,
            created_at=now,
        )

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Look up a task by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return self._row_to_record(row) if row else None
        finally:
            conn.close()

    def update_progress(self, task_id: str, progress: float, msg: str = "") -> None:
        """Update progress value and message."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE tasks SET progress = ?, progress_msg = ? WHERE task_id = ?",
                (progress, msg, task_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Transition task status and set timestamps / result / error."""
        now = datetime.now()
        sets = ["status = ?"]
        vals: list = [status.value]

        if status == TaskStatus.running:
            sets.append("started_at = ?")
            vals.append(self._dt_to_str(now))
        if status in (TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled):
            sets.append("finished_at = ?")
            vals.append(self._dt_to_str(now))
        if result is not None:
            sets.append("result = ?")
            vals.append(result)
        if error is not None:
            sets.append("error = ?")
            vals.append(error)

        vals.append(task_id)
        conn = self._connect()
        try:
            conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE task_id = ?", vals
            )
            conn.commit()
        finally:
            conn.close()

    def list_tasks(self, limit: int = 50) -> list[TaskRecord]:
        """Return recent tasks ordered by created_at DESC."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._row_to_record(r) for r in rows]
        finally:
            conn.close()

    def delete_task(self, task_id: str) -> bool:
        """Delete a task row. Returns True if it existed."""
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def cleanup_old(self, days: int = 7) -> int:
        """Delete finished tasks older than *days*. Returns count deleted."""
        cutoff = datetime.now() - timedelta(days=days)
        conn = self._connect()
        try:
            cur = conn.execute(
                """DELETE FROM tasks
                   WHERE status IN (?, ?, ?)
                     AND finished_at IS NOT NULL
                     AND finished_at < ?""",
                (
                    TaskStatus.completed.value,
                    TaskStatus.failed.value,
                    TaskStatus.cancelled.value,
                    self._dt_to_str(cutoff),
                ),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()
