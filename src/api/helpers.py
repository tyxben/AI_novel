"""Shared helpers for API routes."""

from __future__ import annotations

import os
import re

from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

_WORKSPACE = os.environ.get("API_WORKSPACE", "workspace")


def get_workspace() -> str:
    """Return the workspace root directory."""
    return _WORKSPACE


def set_workspace(path: str) -> None:
    """Override the workspace root (used in tests)."""
    global _WORKSPACE
    _WORKSPACE = path


# ---------------------------------------------------------------------------
# ID validation (prevent path traversal)
# ---------------------------------------------------------------------------

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def validate_id(value: str) -> str:
    """Validate that a project/novel ID is safe (no path traversal).

    Raises HTTPException 400 if invalid. Returns the value unchanged.
    """
    if not value or not _SAFE_ID_RE.match(value):
        raise HTTPException(400, f"Invalid ID: {value!r}")
    return value


# ---------------------------------------------------------------------------
# Task queue integration
# ---------------------------------------------------------------------------

# These are set at app startup by app.py
_task_db = None
_task_executor = None


def configure_task_queue(db, executor):
    """Called once at app startup to inject task queue dependencies."""
    global _task_db, _task_executor
    _task_db = db
    _task_executor = executor


def extract_api_keys(request) -> dict:
    """Extract API keys from request headers (X-Api-Keys JSON header).

    The frontend stores keys in localStorage and sends them as a JSON-encoded
    header. The worker injects them as environment variables during execution.
    """
    raw = request.headers.get("x-api-keys", "")
    if not raw:
        return {}
    try:
        import json
        keys = json.loads(raw)
        if isinstance(keys, dict):
            # Only allow known key names
            allowed = {
                "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
                "SILICONFLOW_API_KEY", "DASHSCOPE_API_KEY",
                "KLING_API_KEY", "JIMENG_API_KEY", "SEEDANCE_API_KEY",
                "MINIMAX_API_KEY", "TOGETHER_API_KEY",
            }
            return {k: v for k, v in keys.items() if k in allowed and v}
        return {}
    except Exception:
        return {}


def submit_to_queue(task_type: str, params: dict, keys: dict | None = None) -> str:
    """Create a task record and submit it to the thread pool.

    Returns the task_id string.
    """
    from src.task_queue.models import TaskType
    from src.task_queue.workers import run_task

    if _task_db is None or _task_executor is None:
        raise HTTPException(503, "Task queue not initialized")

    # Inject API keys for the worker (stripped from DB persistence by workers.py)
    worker_params = dict(params)
    if keys:
        worker_params["_keys"] = keys

    tt = TaskType(task_type)
    # Persist params without keys
    task = _task_db.create_task(tt, params)
    _task_executor.submit(run_task, task.task_id, task.task_type, worker_params, _task_db)
    return task.task_id
