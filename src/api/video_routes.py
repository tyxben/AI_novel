"""Video workspace REST endpoints."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.api.helpers import validate_id, get_workspace, submit_to_queue, extract_api_keys

log = logging.getLogger("api.video")

router = APIRouter(prefix="/api/videos", tags=["videos"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class VideoCreateRequest(BaseModel):
    """Create a video project (director mode or classic mode)."""
    # Director mode fields
    inspiration: Optional[str] = None
    target_duration: int = 60
    budget: str = "low"

    # Classic mode fields
    input_file: Optional[str] = None
    run_mode: str = "classic"  # "classic" | "agent"
    budget_mode: bool = False
    quality_threshold: Optional[float] = None

    # Shared
    config: dict = {}


class VideoGenerateRequest(BaseModel):
    """Generate / regenerate a video."""
    config: dict = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _videos_dir() -> Path:
    return Path(get_workspace()) / "videos"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def create_video(req: VideoCreateRequest, request: Request):
    """Create a video project. Submits to task queue, returns task_id."""
    keys = extract_api_keys(request)
    if req.inspiration:
        # Director mode
        task_id = submit_to_queue("director_generate", {
            "inspiration": req.inspiration.strip(),
            "target_duration": req.target_duration,
            "budget": req.budget,
            "config": req.config,
        }, keys=keys)
    elif req.input_file:
        # Classic / Agent mode
        task_id = submit_to_queue("video_generate", {
            "input_file": req.input_file,
            "run_mode": req.run_mode,
            "budget_mode": req.budget_mode,
            "quality_threshold": req.quality_threshold,
            "config": req.config,
        }, keys=keys)
    else:
        raise HTTPException(400, "Either 'inspiration' (director) or 'input_file' (classic) is required")

    return {"task_id": task_id}


@router.get("")
def list_videos():
    """List video projects from workspace/videos/."""
    videos_dir = _videos_dir()
    if not videos_dir.exists():
        return []

    projects = []
    for d in sorted(videos_dir.iterdir()):
        if not d.is_dir():
            continue

        info: dict[str, Any] = {
            "id": d.name,
            "name": d.name,
            "status": "unknown",
        }

        # Check for concept.json (director mode)
        concept_file = d / "concept.json"
        if concept_file.exists():
            try:
                concept = json.loads(concept_file.read_text(encoding="utf-8"))
                info["name"] = concept.get("title", d.name)
                info["status"] = "completed" if (d / "final.mp4").exists() else "in_progress"
                info["inspiration"] = concept.get("inspiration", "")
            except Exception:
                pass

        # Check for final video
        for ext in ("mp4", "mkv", "avi"):
            final = d / f"final.{ext}"
            if final.exists():
                info["status"] = "completed"
                info["output_path"] = str(final)
                break

        projects.append(info)

    return projects


@router.get("/{video_id}")
def get_video(video_id: str):
    """Get video project details."""
    validate_id(video_id)
    video_dir = _videos_dir() / video_id
    if not video_dir.exists():
        raise HTTPException(404, f"Video project not found: {video_id}")

    info: dict[str, Any] = {
        "id": video_id,
        "name": video_id,
        "status": "unknown",
        "files": [],
    }

    # List files
    for f in sorted(video_dir.rglob("*")):
        if f.is_file():
            info["files"].append({
                "name": f.name,
                "path": str(f.relative_to(video_dir)),
                "size": f.stat().st_size,
            })

    # Load concept if exists
    concept_file = video_dir / "concept.json"
    if concept_file.exists():
        try:
            info["concept"] = json.loads(concept_file.read_text(encoding="utf-8"))
            info["name"] = info["concept"].get("title", video_id)
        except Exception:
            pass

    # Check for output
    for ext in ("mp4", "mkv", "avi"):
        final = video_dir / f"final.{ext}"
        if final.exists():
            info["status"] = "completed"
            info["output_path"] = str(final)
            break

    return info


@router.post("/{video_id}/generate", status_code=201)
def generate_video(video_id: str, req: VideoGenerateRequest, request: Request):
    """Generate video for an existing project. Submits to task queue."""
    validate_id(video_id)
    keys = extract_api_keys(request)
    video_dir = _videos_dir() / video_id
    if not video_dir.exists():
        raise HTTPException(404, f"Video project not found: {video_id}")

    # Try to detect mode from concept.json
    concept_file = video_dir / "concept.json"
    if concept_file.exists():
        try:
            concept = json.loads(concept_file.read_text(encoding="utf-8"))
            task_id = submit_to_queue("director_generate", {
                "inspiration": concept.get("inspiration", ""),
                "target_duration": concept.get("target_duration", 60),
                "budget": concept.get("budget", "low"),
                "config": req.config,
            }, keys=keys)
            return {"task_id": task_id}
        except Exception:
            pass

    raise HTTPException(400, "Cannot determine video generation mode for this project")
