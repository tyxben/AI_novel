"""Cross-product project center endpoint."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from src.api.helpers import get_workspace

log = logging.getLogger("api.projects")

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _stat_mtime(path: Path) -> str:
    """Return ISO timestamp of a path's modification time."""
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts).isoformat()
    except Exception:
        return ""


@router.get("")
def list_all_projects():
    """Return all projects across novel/video/ppt with unified format."""
    workspace = Path(get_workspace())
    projects: list[dict[str, Any]] = []

    # --- Novels ---
    novels_dir = workspace / "novels"
    if novels_dir.exists():
        for d in sorted(novels_dir.iterdir()):
            if not d.is_dir():
                continue
            novel_json = d / "novel.json"
            if not novel_json.exists():
                continue
            try:
                data = json.loads(novel_json.read_text(encoding="utf-8"))
                outline = data.get("outline") or {}
                total_ch = len(outline.get("chapters", []))
                current_ch = data.get("current_chapter", 0)
                progress = current_ch / total_ch if total_ch > 0 else 0

                projects.append({
                    "id": d.name,
                    "name": data.get("title", d.name),
                    "kind": "novel",
                    "status": data.get("status", "unknown"),
                    "updatedAt": _stat_mtime(novel_json),
                    "progress": round(progress, 3),
                    "summary": data.get("synopsis", "")[:200],
                })
            except Exception:
                projects.append({
                    "id": d.name,
                    "name": d.name,
                    "kind": "novel",
                    "status": "error",
                    "updatedAt": _stat_mtime(d),
                    "progress": 0,
                    "summary": "",
                })

    # --- Videos ---
    videos_dir = workspace / "videos"
    if videos_dir.exists():
        for d in sorted(videos_dir.iterdir()):
            if not d.is_dir():
                continue
            name = d.name
            status = "unknown"
            summary = ""

            concept_file = d / "concept.json"
            if concept_file.exists():
                try:
                    concept = json.loads(concept_file.read_text(encoding="utf-8"))
                    name = concept.get("title", d.name)
                    summary = concept.get("inspiration", "")[:200]
                except Exception:
                    pass

            for ext in ("mp4", "mkv", "avi"):
                if (d / f"final.{ext}").exists():
                    status = "completed"
                    break

            projects.append({
                "id": d.name,
                "name": name,
                "kind": "video",
                "status": status,
                "updatedAt": _stat_mtime(d),
                "progress": 1.0 if status == "completed" else 0,
                "summary": summary,
            })

    # --- PPT ---
    ppt_dir = workspace / "ppt"
    if ppt_dir.exists():
        for d in sorted(ppt_dir.iterdir()):
            if not d.is_dir():
                continue
            name = d.name
            status = "unknown"
            progress = 0.0
            summary = ""

            ckpt_file = d / "checkpoint.json"
            if ckpt_file.exists():
                try:
                    ckpt = json.loads(ckpt_file.read_text(encoding="utf-8"))
                    data = ckpt.get("data", ckpt)
                    stages = data.get("stages", {})
                    if stages.get("design"):
                        status = "completed"
                        progress = 1.0
                    elif stages.get("outline"):
                        status = "outline_ready"
                        progress = 0.3

                    outline_data = stages.get("outline", {}).get("data", [])
                    if outline_data and isinstance(outline_data, list) and len(outline_data) > 0:
                        first_page = outline_data[0]
                        if isinstance(first_page, dict):
                            name = first_page.get("title", d.name)
                except Exception:
                    pass

            # Check for pptx output
            if list(d.glob("*.pptx")):
                status = "completed"
                progress = 1.0

            projects.append({
                "id": d.name,
                "name": name,
                "kind": "ppt",
                "status": status,
                "updatedAt": _stat_mtime(d),
                "progress": progress,
                "summary": summary,
            })

    # Sort by updatedAt descending
    projects.sort(key=lambda p: p.get("updatedAt", ""), reverse=True)
    return projects
