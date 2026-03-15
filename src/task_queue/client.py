"""HTTP client for task queue server."""
import httpx

DEFAULT_BASE = "http://127.0.0.1:8632"
TIMEOUT = 5.0


class TaskClient:
    def __init__(self, base_url: str = DEFAULT_BASE):
        self.base_url = base_url

    def is_server_running(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/health", timeout=2.0)
            return r.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    def submit_task(self, task_type: str, params: dict) -> str:
        """Submit a task. Returns task_id."""
        r = httpx.post(
            f"{self.base_url}/api/tasks",
            json={"task_type": task_type, "params": params},
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()["task_id"]

    def get_task(self, task_id: str) -> dict:
        r = httpx.get(f"{self.base_url}/api/tasks/{task_id}", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    def list_tasks(self, limit: int = 50) -> list[dict]:
        r = httpx.get(
            f"{self.base_url}/api/tasks", params={"limit": limit}, timeout=TIMEOUT
        )
        r.raise_for_status()
        return r.json()

    def cancel_task(self, task_id: str) -> dict:
        r = httpx.post(
            f"{self.base_url}/api/tasks/{task_id}/cancel", timeout=TIMEOUT
        )
        r.raise_for_status()
        return r.json()

    def delete_task(self, task_id: str) -> None:
        r = httpx.delete(
            f"{self.base_url}/api/tasks/{task_id}", timeout=TIMEOUT
        )
        r.raise_for_status()
