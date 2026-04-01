"""断点续传 - 跟踪流水线各阶段完成状态"""

import json
from pathlib import Path
from typing import Any

CHECKPOINT_FILE = "checkpoint.json"


class Checkpoint:
    def __init__(self, workspace: Path):
        self.path = workspace / CHECKPOINT_FILE
        self.data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"stages": {}, "segments": []}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(self.data, ensure_ascii=False, indent=2)
        # Atomic write: write to temp file then rename
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(self.path)  # Atomic on POSIX
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def is_done(self, stage: str) -> bool:
        return self.data["stages"].get(stage, {}).get("done", False)

    def mark_done(self, stage: str, meta: dict | None = None) -> None:
        self.data["stages"][stage] = {"done": True, **(meta or {})}
        self.save()

    def get_segment_status(self, idx: int) -> dict:
        segs = self.data.get("segments", [])
        if idx < len(segs):
            return segs[idx]
        return {}

    def update_segment(self, idx: int, key: str, value: Any) -> None:
        segs = self.data.setdefault("segments", [])
        while len(segs) <= idx:
            segs.append({})
        segs[idx][key] = value
        self.save()

    def total_segments(self) -> int:
        return len(self.data.get("segments", []))
