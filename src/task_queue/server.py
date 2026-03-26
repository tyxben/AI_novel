"""Task queue server — runs as independent process."""
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .models import TaskType, TaskStatus, TaskRecord
from .db import TaskDB
from .workers import run_task

MAX_WORKERS = int(os.environ.get("TASK_QUEUE_WORKERS", "3"))

db = TaskDB()
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    executor.shutdown(wait=False)


app = FastAPI(title="Task Queue Server", lifespan=lifespan)


class SubmitRequest(BaseModel):
    task_type: TaskType
    params: dict = {}


@app.post("/api/tasks", status_code=201)
def submit_task(req: SubmitRequest):
    # Strip _keys from persisted params — only pass to worker in memory
    persist_params = {k: v for k, v in req.params.items() if k != "_keys"}
    task = db.create_task(req.task_type, persist_params)
    executor.submit(run_task, task.task_id, task.task_type, req.params, db)
    return {"task_id": task.task_id}


@app.get("/api/tasks")
def list_tasks(limit: int = 50):
    tasks = db.list_tasks(limit=limit)
    return [t.model_dump() for t in tasks]


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task.model_dump()


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status in (TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled):
        return {"msg": "Task already finished"}
    db.update_status(task_id, TaskStatus.cancelled)
    return {"msg": "Cancelled"}


@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: str):
    if not db.delete_task(task_id):
        raise HTTPException(404, "Task not found")


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Entry point: python -m src.task_queue.server
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8632, log_level="info")
