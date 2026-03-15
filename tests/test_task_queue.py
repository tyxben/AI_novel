"""Tests for src/task_queue — db, workers, server, client."""

import json
import threading
import time
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.task_queue.models import TaskType, TaskStatus, TaskRecord
from src.task_queue.db import TaskDB


# ==========================================================================
# Fixtures
# ==========================================================================


@pytest.fixture()
def db(tmp_path):
    """TaskDB backed by a temp file — isolated per test."""
    return TaskDB(db_path=tmp_path / "test_tasks.db")


@pytest.fixture()
def _populated_db(db):
    """Create 3 tasks with different statuses."""
    t1 = db.create_task(TaskType.novel_create, {"theme": "修仙"})
    db.update_status(t1.task_id, TaskStatus.completed, result='{"ok":true}')

    t2 = db.create_task(TaskType.novel_generate, {"project_path": "/p"})
    db.update_status(t2.task_id, TaskStatus.running)

    t3 = db.create_task(TaskType.director_generate, {"inspiration": "猫"})
    # stays pending
    return t1, t2, t3


# ==========================================================================
# TaskDB tests
# ==========================================================================


class TestTaskDB:
    """Core CRUD + edge cases."""

    def test_create_and_get(self, db):
        task = db.create_task(TaskType.novel_create, {"theme": "修仙"})
        assert len(task.task_id) == 12
        assert task.status == TaskStatus.pending
        assert task.progress == 0.0

        fetched = db.get_task(task.task_id)
        assert fetched is not None
        assert fetched.task_id == task.task_id
        assert fetched.task_type == TaskType.novel_create
        assert fetched.params == {"theme": "修仙"}

    def test_get_nonexistent_returns_none(self, db):
        assert db.get_task("does_not_exist") is None

    def test_update_progress(self, db):
        task = db.create_task(TaskType.novel_generate, {})
        db.update_progress(task.task_id, 0.5, "生成中...")
        fetched = db.get_task(task.task_id)
        assert fetched.progress == 0.5
        assert fetched.progress_msg == "生成中..."

    def test_update_status_completed(self, db):
        task = db.create_task(TaskType.novel_create, {})
        db.update_status(task.task_id, TaskStatus.running)
        running = db.get_task(task.task_id)
        assert running.status == TaskStatus.running
        assert running.started_at is not None

        db.update_status(task.task_id, TaskStatus.completed, result='{"done":true}')
        done = db.get_task(task.task_id)
        assert done.status == TaskStatus.completed
        assert done.finished_at is not None
        assert done.result == '{"done":true}'

    def test_update_status_failed(self, db):
        task = db.create_task(TaskType.novel_create, {})
        db.update_status(task.task_id, TaskStatus.failed, error="boom\ntraceback...")
        fetched = db.get_task(task.task_id)
        assert fetched.status == TaskStatus.failed
        assert "boom" in fetched.error
        assert fetched.finished_at is not None

    def test_list_tasks_ordered_desc(self, db, _populated_db):
        tasks = db.list_tasks()
        assert len(tasks) == 3
        # most recent first
        assert tasks[0].task_type == TaskType.director_generate

    def test_list_tasks_limit(self, db, _populated_db):
        tasks = db.list_tasks(limit=1)
        assert len(tasks) == 1

    def test_delete_existing(self, db):
        task = db.create_task(TaskType.novel_create, {})
        assert db.delete_task(task.task_id) is True
        assert db.get_task(task.task_id) is None

    def test_delete_nonexistent(self, db):
        assert db.delete_task("nope") is False

    def test_large_params(self, db):
        big = {"data": "x" * 100_000}
        task = db.create_task(TaskType.novel_create, big)
        fetched = db.get_task(task.task_id)
        assert fetched.params["data"] == "x" * 100_000

    def test_cleanup_old(self, db):
        task = db.create_task(TaskType.novel_create, {})
        db.update_status(task.task_id, TaskStatus.completed, result="{}")

        # manually backdate finished_at to 10 days ago
        conn = db._connect()
        old_dt = (datetime.now() - timedelta(days=10)).isoformat()
        conn.execute(
            "UPDATE tasks SET finished_at = ? WHERE task_id = ?",
            (old_dt, task.task_id),
        )
        conn.commit()
        conn.close()

        deleted = db.cleanup_old(days=7)
        assert deleted == 1
        assert db.get_task(task.task_id) is None

    def test_cleanup_keeps_recent(self, db):
        task = db.create_task(TaskType.novel_create, {})
        db.update_status(task.task_id, TaskStatus.completed, result="{}")
        deleted = db.cleanup_old(days=7)
        assert deleted == 0
        assert db.get_task(task.task_id) is not None

    def test_concurrent_writes(self, db):
        """Multiple threads writing to same DB should not deadlock."""
        errors = []

        def writer(i):
            try:
                t = db.create_task(TaskType.novel_create, {"i": i})
                db.update_progress(t.task_id, i / 10, f"step {i}")
                db.update_status(t.task_id, TaskStatus.completed, result=f'{{"i":{i}}}')
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Concurrent write errors: {errors}"
        assert len(db.list_tasks(limit=100)) == 10

    def test_orphaned_running_tasks_recovered(self, tmp_path):
        """Tasks stuck in 'running' should be marked failed on DB init."""
        db1 = TaskDB(db_path=tmp_path / "orphan_test.db")
        task = db1.create_task(TaskType.novel_create, {})
        db1.update_status(task.task_id, TaskStatus.running)

        # Simulate server restart — create new TaskDB instance
        db2 = TaskDB(db_path=tmp_path / "orphan_test.db")
        fetched = db2.get_task(task.task_id)
        assert fetched.status == TaskStatus.failed
        assert "Server restarted" in fetched.error


# ==========================================================================
# Workers tests
# ==========================================================================


class TestWorkers:
    """Mock all pipelines — test dispatch + error handling."""

    def test_novel_create_success(self, db):
        from src.task_queue.workers import run_task

        task = db.create_task(TaskType.novel_create, {
            "genre": "玄幻", "theme": "修仙",
            "_keys": {"GEMINI_API_KEY": "test123"},
        })

        mock_result = {"outline": {"title": "测试"}, "characters": []}
        with patch("src.task_queue.workers._run_novel_create", return_value=mock_result):
            run_task(task.task_id, task.task_type, task.params.copy(), db)

        fetched = db.get_task(task.task_id)
        assert fetched.status == TaskStatus.completed
        assert "测试" in fetched.result

    def test_progress_callback_updates_db(self, db):
        from src.task_queue.workers import run_task

        task = db.create_task(TaskType.novel_create, {"genre": "玄幻", "theme": "修仙"})
        progress_values = []

        original_run = None

        def mock_create(params, progress_cb):
            progress_cb(0.3, "世界观构建中...")
            progress_cb(0.7, "角色设计中...")
            # verify intermediate state
            mid = db.get_task(task.task_id)
            progress_values.append(mid.progress)
            return {"ok": True}

        with patch("src.task_queue.workers._run_novel_create", side_effect=mock_create):
            run_task(task.task_id, task.task_type, task.params.copy(), db)

        assert 0.7 in progress_values

    def test_pipeline_exception_marks_failed(self, db):
        from src.task_queue.workers import run_task

        task = db.create_task(TaskType.novel_create, {"genre": "玄幻", "theme": "修仙"})

        with patch(
            "src.task_queue.workers._run_novel_create",
            side_effect=RuntimeError("LLM API 挂了"),
        ):
            run_task(task.task_id, task.task_type, task.params.copy(), db)

        fetched = db.get_task(task.task_id)
        assert fetched.status == TaskStatus.failed
        assert "LLM API 挂了" in fetched.error
        assert "Traceback" in fetched.error

    def test_pipeline_returns_none(self, db):
        from src.task_queue.workers import run_task

        task = db.create_task(TaskType.novel_polish, {
            "project_path": "/tmp/fake",
        })

        with patch("src.task_queue.workers._run_novel_polish", return_value=None):
            run_task(task.task_id, task.task_type, task.params.copy(), db)

        fetched = db.get_task(task.task_id)
        assert fetched.status == TaskStatus.completed
        assert fetched.result == ""

    def test_unknown_task_type_fails(self, db):
        from src.task_queue.workers import run_task

        task = db.create_task(TaskType.novel_create, {})
        # Force an unknown type by patching dispatch
        with patch(
            "src.task_queue.workers._dispatch",
            side_effect=ValueError("Unknown task type: ???"),
        ):
            run_task(task.task_id, task.task_type, task.params.copy(), db)

        fetched = db.get_task(task.task_id)
        assert fetched.status == TaskStatus.failed
        assert "Unknown task type" in fetched.error

    def test_keys_injected_and_cleaned_up(self, db):
        from src.task_queue.workers import run_task
        import os

        env_key = "TEST_FAKE_KEY_CLEANUP"
        task = db.create_task(TaskType.novel_create, {
            "genre": "玄幻", "theme": "修仙",
            "_keys": {env_key: "secret_val"},
        })

        captured = {}

        def mock_create(params, progress_cb):
            captured["key"] = os.environ.get(env_key)
            return {}

        with patch("src.task_queue.workers._run_novel_create", side_effect=mock_create):
            run_task(task.task_id, task.task_type, task.params.copy(), db)

        # Key was available during execution
        assert captured["key"] == "secret_val"
        # Key is cleaned up after execution
        assert os.environ.get(env_key) is None

    def test_keys_cleaned_up_on_failure(self, db):
        from src.task_queue.workers import run_task
        import os

        env_key = "TEST_FAKE_KEY_FAIL"
        task = db.create_task(TaskType.novel_create, {
            "genre": "玄幻", "theme": "修仙",
            "_keys": {env_key: "fail_val"},
        })

        with patch("src.task_queue.workers._run_novel_create", side_effect=RuntimeError("boom")):
            run_task(task.task_id, task.task_type, task.params.copy(), db)

        assert db.get_task(task.task_id).status == TaskStatus.failed
        assert os.environ.get(env_key) is None

    def test_cancel_via_progress_callback(self, db):
        from src.task_queue.workers import run_task

        task = db.create_task(TaskType.novel_create, {"genre": "玄幻", "theme": "修仙"})

        def mock_create(params, progress_cb):
            progress_cb(0.2, "step 1")
            # Simulate cancel: update DB status before next progress call
            db.update_status(task.task_id, TaskStatus.cancelled)
            progress_cb(0.5, "step 2")  # should raise TaskCancelled
            return {"should": "not reach here"}

        with patch("src.task_queue.workers._run_novel_create", side_effect=mock_create):
            run_task(task.task_id, task.task_type, task.params.copy(), db)

        fetched = db.get_task(task.task_id)
        assert fetched.status == TaskStatus.cancelled


# ==========================================================================
# Server API tests (FastAPI TestClient — no real port)
# ==========================================================================


class TestServerAPI:
    """Test HTTP endpoints via FastAPI TestClient."""

    @pytest.fixture(autouse=True)
    def _setup_server(self, tmp_path):
        """Patch server's global db to use temp DB."""
        test_db = TaskDB(db_path=tmp_path / "server_test.db")

        with patch("src.task_queue.server.db", test_db), \
             patch("src.task_queue.server.run_task"):  # don't actually run tasks
            from starlette.testclient import TestClient
            from src.task_queue.server import app

            self.client = TestClient(app)
            self.db = test_db
            yield

    def test_health(self):
        r = self.client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_submit_returns_201(self):
        r = self.client.post("/api/tasks", json={
            "task_type": "novel_create",
            "params": {"theme": "修仙"},
        })
        assert r.status_code == 201
        assert "task_id" in r.json()

    def test_submit_strips_keys_from_db(self):
        """API keys must not be persisted in SQLite."""
        r = self.client.post("/api/tasks", json={
            "task_type": "novel_create",
            "params": {
                "theme": "修仙",
                "_keys": {"GEMINI_API_KEY": "secret123"},
            },
        })
        assert r.status_code == 201
        task_id = r.json()["task_id"]
        # Check DB directly — _keys should not be stored
        task = self.db.get_task(task_id)
        assert "_keys" not in task.params
        assert task.params["theme"] == "修仙"

    def test_submit_invalid_type_returns_422(self):
        r = self.client.post("/api/tasks", json={
            "task_type": "nonexistent_type",
            "params": {},
        })
        assert r.status_code == 422

    def test_submit_missing_fields_returns_422(self):
        r = self.client.post("/api/tasks", json={})
        assert r.status_code == 422

    def test_get_task(self):
        task = self.db.create_task(TaskType.novel_create, {"theme": "测试"})
        r = self.client.get(f"/api/tasks/{task.task_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["task_id"] == task.task_id
        assert data["status"] == "pending"
        assert data["params"]["theme"] == "测试"

    def test_get_nonexistent_returns_404(self):
        r = self.client.get("/api/tasks/not_a_real_id")
        assert r.status_code == 404

    def test_list_tasks(self):
        self.db.create_task(TaskType.novel_create, {})
        self.db.create_task(TaskType.director_generate, {})
        r = self.client.get("/api/tasks")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_cancel_pending(self):
        task = self.db.create_task(TaskType.novel_create, {})
        r = self.client.post(f"/api/tasks/{task.task_id}/cancel")
        assert r.status_code == 200
        assert self.db.get_task(task.task_id).status == TaskStatus.cancelled

    def test_cancel_already_completed(self):
        task = self.db.create_task(TaskType.novel_create, {})
        self.db.update_status(task.task_id, TaskStatus.completed, result="{}")
        r = self.client.post(f"/api/tasks/{task.task_id}/cancel")
        assert r.status_code == 200
        assert "already finished" in r.json()["msg"]

    def test_cancel_nonexistent_returns_404(self):
        r = self.client.post("/api/tasks/nope/cancel")
        assert r.status_code == 404

    def test_delete_task(self):
        task = self.db.create_task(TaskType.novel_create, {})
        r = self.client.delete(f"/api/tasks/{task.task_id}")
        assert r.status_code == 204
        assert self.db.get_task(task.task_id) is None

    def test_delete_nonexistent_returns_404(self):
        r = self.client.delete("/api/tasks/nope")
        assert r.status_code == 404


# ==========================================================================
# Client tests (mock httpx — no real server)
# ==========================================================================


class TestTaskClient:
    """Test HTTP client with mocked httpx."""

    def test_is_server_running_online(self):
        from src.task_queue.client import TaskClient

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.get", return_value=mock_resp):
            assert TaskClient().is_server_running() is True

    def test_is_server_running_offline(self):
        from src.task_queue.client import TaskClient
        import httpx

        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            assert TaskClient().is_server_running() is False

    def test_submit_task_offline_raises(self):
        from src.task_queue.client import TaskClient
        import httpx

        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(httpx.ConnectError):
                TaskClient().submit_task("novel_create", {})

    def test_get_task_timeout_raises(self):
        from src.task_queue.client import TaskClient
        import httpx

        with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(httpx.TimeoutException):
                TaskClient().get_task("abc123")
