"""Main FastAPI application — unified REST API for the Next.js frontend.

Mounts all route modules and includes the task queue server routes.
Serves on port 8000. Run with: python -m src.api.app
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

# Load .env file (same as web.py / Gradio frontend)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.task_queue.db import TaskDB
from src.task_queue.models import TaskType, TaskStatus
from src.task_queue.workers import run_task
from src.api.helpers import configure_task_queue

MAX_WORKERS = int(os.environ.get("TASK_QUEUE_WORKERS", "1"))


# ---------------------------------------------------------------------------
# Task queue shared instances
# ---------------------------------------------------------------------------

db = TaskDB()
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.api.helpers import _task_db
    # Only set defaults if not already configured (e.g. by tests)
    if _task_db is None:
        configure_task_queue(db, executor)
    yield
    executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="AI Creative Workshop API",
        description="Unified REST API for novel, video, and PPT creation",
        version="1.0.0",
        lifespan=lifespan,
    )

    # ---- CORS (allow Next.js dev server) ----
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- Mount task queue routes from existing server ----
    # We re-implement the task endpoints here instead of importing the
    # existing app to avoid duplicate DB/executor instances.
    _register_task_routes(app)

    # ---- Include domain routers ----
    from src.api.novel_routes import router as novel_router
    from src.api.video_routes import router as video_router
    from src.api.ppt_routes import router as ppt_router
    from src.api.project_routes import router as project_router
    from src.api.settings_routes import router as settings_router
    from src.api.prompts_routes import router as prompts_router
    from src.api.narrative_routes import router as narrative_router

    app.include_router(novel_router)
    app.include_router(video_router)
    app.include_router(ppt_router)
    app.include_router(project_router)
    app.include_router(settings_router)
    app.include_router(prompts_router)
    app.include_router(narrative_router)

    return app


# ---------------------------------------------------------------------------
# Task queue endpoints (same API as src/task_queue/server.py)
# ---------------------------------------------------------------------------

from pydantic import BaseModel


class SubmitRequest(BaseModel):
    task_type: TaskType
    params: dict = {}


def _register_task_routes(app: FastAPI):
    """Register task CRUD endpoints on the app.

    All endpoints read from helpers._task_db / _task_executor so that
    tests can inject mocks via configure_task_queue().
    """
    from src.api import helpers as _h

    @app.post("/api/tasks", status_code=201, tags=["tasks"])
    def submit_task(req: SubmitRequest):
        persist_params = {k: v for k, v in req.params.items() if k != "_keys"}
        task = _h._task_db.create_task(req.task_type, persist_params)
        _h._task_executor.submit(run_task, task.task_id, task.task_type, dict(req.params), _h._task_db)
        return {"task_id": task.task_id}

    @app.get("/api/tasks", tags=["tasks"])
    def list_tasks(limit: int = 50):
        tasks = _h._task_db.list_tasks(limit=limit)
        return [t.model_dump() for t in tasks]

    @app.get("/api/tasks/{task_id}", tags=["tasks"])
    def get_task(task_id: str):
        from fastapi import HTTPException
        task = _h._task_db.get_task(task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        return task.model_dump()

    @app.post("/api/tasks/{task_id}/cancel", tags=["tasks"])
    def cancel_task(task_id: str):
        from fastapi import HTTPException
        task = _h._task_db.get_task(task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        if task.status in (TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled):
            return {"msg": "Task already finished"}
        _h._task_db.update_status(task_id, TaskStatus.cancelled)
        return {"msg": "Cancelled"}

    @app.delete("/api/tasks/{task_id}", status_code=204, tags=["tasks"])
    def delete_task(task_id: str):
        from fastapi import HTTPException
        if not _h._task_db.delete_task(task_id):
            raise HTTPException(404, "Task not found")

    @app.get("/api/health", tags=["system"])
    def health():
        return {"status": "ok"}


# ---------------------------------------------------------------------------
# Singleton app instance
# ---------------------------------------------------------------------------

app = create_app()


# ---------------------------------------------------------------------------
# Entry point: python -m src.api.app
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
