"""PPT workspace REST endpoints."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.api.helpers import validate_id, get_workspace, submit_to_queue, extract_api_keys

log = logging.getLogger("api.ppt")

router = APIRouter(prefix="/api/ppt", tags=["ppt"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class PPTCreateRequest(BaseModel):
    """Create PPT — submits an outline task (V2 stage 1)."""
    topic: Optional[str] = None
    document_text: Optional[str] = None
    audience: str = "business"
    scenario: str = "quarterly_review"
    theme: str = "modern"
    target_pages: Optional[int] = None


class PPTContinueRequest(BaseModel):
    """Continue from outline (V2 stage 2)."""
    edited_outline: dict
    generate_images: bool = True
    theme: str = "modern"


class PPTRenderRequest(BaseModel):
    """Render HTML preview."""
    theme: str = "modern"


class PPTExportRequest(BaseModel):
    """Export to PPTX."""
    html_path: str
    extract_text: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ppt_dir() -> Path:
    return Path(get_workspace()) / "ppt"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def create_ppt(req: PPTCreateRequest, request: Request):
    """Create PPT: submit outline generation task. Returns task_id."""
    if not req.topic and not req.document_text:
        raise HTTPException(400, "Either 'topic' or 'document_text' is required")

    keys = extract_api_keys(request)
    task_id = submit_to_queue("ppt_outline", {
        "workspace": get_workspace(),
        "topic": req.topic,
        "document_text": req.document_text,
        "audience": req.audience,
        "scenario": req.scenario,
        "theme": req.theme,
        "target_pages": req.target_pages,
    }, keys=keys)
    return {"task_id": task_id}


@router.get("")
def list_ppt():
    """List PPT projects from workspace/ppt/."""
    ppt_dir = _ppt_dir()
    if not ppt_dir.exists():
        return []

    projects = []
    for d in sorted(ppt_dir.iterdir()):
        if not d.is_dir():
            continue

        info: dict[str, Any] = {
            "id": d.name,
            "name": d.name,
            "status": "unknown",
        }

        # Load checkpoint for metadata
        ckpt_file = d / "checkpoint.json"
        if ckpt_file.exists():
            try:
                ckpt = json.loads(ckpt_file.read_text(encoding="utf-8"))
                data = ckpt.get("data", ckpt)
                stages = data.get("stages", {})

                # Determine status from stages
                if stages.get("design"):
                    info["status"] = "completed"
                elif stages.get("outline"):
                    info["status"] = "outline_ready"
                else:
                    info["status"] = "in_progress"

                # Extract title from outline
                outline_data = stages.get("outline", {}).get("data", [])
                if outline_data and isinstance(outline_data, list) and len(outline_data) > 0:
                    first_page = outline_data[0]
                    if isinstance(first_page, dict):
                        info["name"] = first_page.get("title", d.name)

                info["total_pages"] = len(outline_data) if isinstance(outline_data, list) else 0

            except Exception:
                pass

        # Check for output file
        for ext in ("pptx", "html"):
            for f in d.glob(f"*.{ext}"):
                info["status"] = "completed"
                info[f"output_{ext}"] = str(f)
                break

        projects.append(info)

    return projects


@router.get("/{project_id}")
def get_ppt(project_id: str):
    """Get PPT project details."""
    validate_id(project_id)
    project_dir = _ppt_dir() / project_id
    if not project_dir.exists():
        raise HTTPException(404, f"PPT project not found: {project_id}")

    info: dict[str, Any] = {
        "id": project_id,
        "name": project_id,
        "status": "unknown",
        "outline": None,
        "quality_report": None,
        "files": [],
    }

    # List files
    for f in sorted(project_dir.rglob("*")):
        if f.is_file():
            info["files"].append({
                "name": f.name,
                "path": str(f.relative_to(project_dir)),
                "size": f.stat().st_size,
            })

    # Load checkpoint
    ckpt_file = project_dir / "checkpoint.json"
    if ckpt_file.exists():
        try:
            ckpt = json.loads(ckpt_file.read_text(encoding="utf-8"))
            data = ckpt.get("data", ckpt)
            stages = data.get("stages", {})

            info["outline"] = stages.get("outline", {}).get("data")
            info["quality_report"] = data.get("quality_report")

            if stages.get("design"):
                info["status"] = "completed"
            elif stages.get("outline"):
                info["status"] = "outline_ready"
        except Exception:
            pass

    # Check for outputs
    for f in project_dir.glob("*.pptx"):
        info["output_pptx"] = str(f)
    for f in project_dir.glob("*.html"):
        info["output_html"] = str(f)

    return info


@router.post("/{project_id}/generate", status_code=201)
def continue_from_outline(project_id: str, req: PPTContinueRequest, request: Request):
    """Continue PPT generation from edited outline. Submits to task queue."""
    validate_id(project_id)
    keys = extract_api_keys(request)
    project_dir = _ppt_dir() / project_id
    if not project_dir.exists():
        raise HTTPException(404, f"PPT project not found: {project_id}")

    task_id = submit_to_queue("ppt_continue", {
        "workspace": get_workspace(),
        "project_id": project_id,
        "edited_outline": req.edited_outline,
        "generate_images": req.generate_images,
        "theme": req.theme,
    }, keys=keys)
    return {"task_id": task_id}


@router.post("/{project_id}/render", status_code=201)
def render_html(project_id: str, req: PPTRenderRequest, request: Request):
    """Render HTML preview. Submits to task queue."""
    validate_id(project_id)
    keys = extract_api_keys(request)
    project_dir = _ppt_dir() / project_id
    if not project_dir.exists():
        raise HTTPException(404, f"PPT project not found: {project_id}")

    task_id = submit_to_queue("ppt_render_html", {
        "workspace": get_workspace(),
        "project_id": project_id,
        "theme": req.theme,
    }, keys=keys)
    return {"task_id": task_id}


@router.post("/{project_id}/export", status_code=201)
def export_pptx(project_id: str, request: Request):
    """Export PPT as PPTX. Submits to task queue."""
    validate_id(project_id)
    keys = extract_api_keys(request)
    project_dir = _ppt_dir() / project_id
    if not project_dir.exists():
        raise HTTPException(404, f"PPT project not found: {project_id}")

    # Find the HTML file
    html_files = list(project_dir.glob("*.html"))
    if not html_files:
        raise HTTPException(400, "No HTML preview found. Render first.")

    task_id = submit_to_queue("ppt_export", {
        "workspace": get_workspace(),
        "project_id": project_id,
        "html_path": str(html_files[0]),
    }, keys=keys)
    return {"task_id": task_id}
