"""Narrative control REST endpoints.

Exposes narrative debts, story arcs, chapter briefs, and the knowledge graph
for the frontend narrative dashboard.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.helpers import validate_id, get_workspace, submit_to_queue, extract_api_keys

log = logging.getLogger("api.narrative")

router = APIRouter(
    prefix="/api/novels/{novel_id}/narrative", tags=["narrative"]
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class AddDebtRequest(BaseModel):
    source_chapter: int = Field(..., ge=1)
    debt_type: str = Field(
        ..., description="must_pay_next | pay_within_3 | long_tail_payoff"
    )
    description: str = Field(..., min_length=1)
    target_chapter: Optional[int] = Field(None, ge=1)
    urgency_level: str = Field("normal")


class FulfillDebtRequest(BaseModel):
    chapter_number: int = Field(..., ge=1)
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _novels_dir() -> Path:
    return Path(get_workspace()) / "novels"


def _project_path(novel_id: str) -> Path:
    validate_id(novel_id)
    p = _novels_dir() / novel_id
    if not (p / "novel.json").exists():
        raise HTTPException(404, f"Novel not found: {novel_id}")
    return p


def _load_novel_json(project: Path) -> dict[str, Any]:
    with open(project / "novel.json", encoding="utf-8") as f:
        return json.load(f)


def _get_outline(project: Path) -> dict[str, Any]:
    """Load outline dict from novel.json."""
    data = _load_novel_json(project)
    return data.get("outline", {})


def _load_debts_from_db(project: Path) -> list[dict[str, Any]]:
    """Load debts from the SQLite structured DB (memory.db)."""
    db_path = project / "memory.db"
    if not db_path.exists():
        return []
    try:
        from src.novel.storage.structured_db import StructuredDB

        db = StructuredDB(db_path)
        try:
            return db.query_debts()
        finally:
            db.close()
    except Exception as exc:
        log.warning("Failed to load debts from DB for %s: %s", project.name, exc)
        return []


def _load_debts_from_json(project: Path) -> list[dict[str, Any]]:
    """Load debts from debts.json fallback file."""
    debts_path = project / "debts.json"
    if not debts_path.exists():
        return []
    try:
        with open(debts_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception as exc:
        log.warning("Failed to load debts.json for %s: %s", project.name, exc)
        return []


def _load_all_debts(project: Path) -> list[dict[str, Any]]:
    """Load debts from DB first, fall back to debts.json."""
    debts = _load_debts_from_db(project)
    if debts:
        return debts
    return _load_debts_from_json(project)


def _load_arcs_from_db(project: Path) -> list[dict[str, Any]]:
    """Load story units from the SQLite structured DB."""
    db_path = project / "memory.db"
    if not db_path.exists():
        return []
    try:
        from src.novel.storage.structured_db import StructuredDB

        db = StructuredDB(db_path)
        try:
            units = db.query_story_units()
            # Parse chapters JSON string into list
            for unit in units:
                if isinstance(unit.get("chapters"), str):
                    try:
                        unit["chapters"] = json.loads(unit["chapters"])
                    except (json.JSONDecodeError, TypeError):
                        unit["chapters"] = []
            return units
        finally:
            db.close()
    except Exception as exc:
        log.warning("Failed to load arcs from DB for %s: %s", project.name, exc)
        return []


def _load_arcs_from_json(project: Path) -> list[dict[str, Any]]:
    """Load arcs from arcs.json fallback file."""
    arcs_path = project / "arcs.json"
    if not arcs_path.exists():
        return []
    try:
        with open(arcs_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception as exc:
        log.warning("Failed to load arcs.json for %s: %s", project.name, exc)
        return []


def _load_all_arcs(project: Path) -> list[dict[str, Any]]:
    """Load arcs from DB first, fall back to arcs.json."""
    arcs = _load_arcs_from_db(project)
    if arcs:
        return arcs
    return _load_arcs_from_json(project)


def _load_knowledge_graph(project: Path) -> dict[str, Any]:
    """Load knowledge graph data (nodes + edges) from graph.json."""
    graph_json = project / "graph.json"
    if not graph_json.exists():
        return {"nodes": [], "edges": []}
    try:
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph.load(str(graph_json))
        try:
            nodes = []
            for node_id, attrs in kg.graph.nodes(data=True):
                nodes.append({"id": node_id, **attrs})

            edges = []
            for u, v, key, attrs in kg.graph.edges(data=True, keys=True):
                edges.append({"source": u, "target": v, "key": key, **attrs})

            return {"nodes": nodes, "edges": edges}
        finally:
            kg.close()
    except Exception as exc:
        log.warning("Failed to load knowledge graph for %s: %s", project.name, exc)
        return {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/overview")
def narrative_overview(novel_id: str):
    """Overall narrative status: debt stats, arc counts, graph summary."""
    project = _project_path(novel_id)
    novel_data = _load_novel_json(project)

    debts = _load_all_debts(project)
    arcs = _load_all_arcs(project)
    graph_data = _load_knowledge_graph(project)

    # Debt statistics
    pending = sum(1 for d in debts if d.get("status") == "pending")
    fulfilled = sum(1 for d in debts if d.get("status") == "fulfilled")
    overdue = sum(1 for d in debts if d.get("status") == "overdue")
    abandoned = sum(1 for d in debts if d.get("status") == "abandoned")

    # Arc statistics
    active_arcs = sum(
        1 for a in arcs
        if a.get("status") in ("active", "planning", "in_progress")
    )
    completed_arcs = sum(1 for a in arcs if a.get("status") == "completed")

    # Outline info
    outline = novel_data.get("outline") or {}
    total_chapters = len(outline.get("chapters", []))
    current_chapter = novel_data.get("current_chapter", 0)

    return {
        "novel_id": novel_id,
        "title": novel_data.get("title", ""),
        "current_chapter": current_chapter,
        "total_chapters": total_chapters,
        "debts": {
            "total": len(debts),
            "pending": pending,
            "fulfilled": fulfilled,
            "overdue": overdue,
            "abandoned": abandoned,
        },
        "arcs": {
            "total": len(arcs),
            "active": active_arcs,
            "completed": completed_arcs,
        },
        "graph": {
            "node_count": len(graph_data["nodes"]),
            "edge_count": len(graph_data["edges"]),
        },
    }


@router.get("/debts")
def list_debts(novel_id: str, status: Optional[str] = None):
    """List all narrative debts, with optional status filter."""
    project = _project_path(novel_id)
    debts = _load_all_debts(project)

    if status:
        debts = [d for d in debts if d.get("status") == status]

    return {"debts": debts, "count": len(debts)}


@router.post("/debts", status_code=201)
def add_debt(novel_id: str, req: AddDebtRequest):
    """Manually add a narrative debt."""
    project = _project_path(novel_id)

    valid_types = ("must_pay_next", "pay_within_3", "long_tail_payoff")
    if req.debt_type not in valid_types:
        raise HTTPException(400, f"debt_type must be one of {valid_types}")

    valid_urgency = ("normal", "high", "critical")
    if req.urgency_level not in valid_urgency:
        raise HTTPException(400, f"urgency_level must be one of {valid_urgency}")

    from src.novel.services.obligation_tracker import ObligationTracker

    # Try to use DB, fall back to in-memory + JSON export
    db_path = project / "memory.db"
    db = None
    tracker: ObligationTracker
    if db_path.exists():
        try:
            from src.novel.storage.structured_db import StructuredDB

            db = StructuredDB(db_path)
            tracker = ObligationTracker(db)
        except Exception:
            tracker = ObligationTracker(None)
    else:
        tracker = ObligationTracker(None)

    from uuid import uuid4

    debt_id = f"debt_{req.source_chapter}_manual_{uuid4().hex[:8]}"

    try:
        tracker.add_debt(
            debt_id=debt_id,
            source_chapter=req.source_chapter,
            debt_type=req.debt_type,
            description=req.description,
            target_chapter=req.target_chapter,
            urgency_level=req.urgency_level,
        )
    finally:
        if db is not None:
            db.close()

    # If using in-memory tracker, persist to debts.json
    if tracker._mem_store is not None:
        existing = _load_debts_from_json(project)
        existing.append(tracker._mem_store[debt_id])
        debts_path = project / "debts.json"
        with open(debts_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

    return {"debt_id": debt_id, "status": "created"}


@router.post("/debts/{debt_id}/fulfill")
def fulfill_debt(novel_id: str, debt_id: str, req: FulfillDebtRequest):
    """Mark a debt as fulfilled."""
    project = _project_path(novel_id)

    from src.novel.services.obligation_tracker import ObligationTracker

    db_path = project / "memory.db"
    db = None
    fulfilled_via_db = False

    if db_path.exists():
        try:
            from src.novel.storage.structured_db import StructuredDB

            db = StructuredDB(db_path)
            # Verify debt exists
            rows = db.query_debts()
            debt_exists = any(r.get("debt_id") == debt_id for r in rows)
            if debt_exists:
                tracker = ObligationTracker(db)
                tracker.mark_debt_fulfilled(
                    debt_id, req.chapter_number, req.note
                )
                fulfilled_via_db = True
        except Exception as exc:
            log.warning("DB fulfill failed for %s: %s", debt_id, exc)
        finally:
            if db is not None:
                db.close()

    if not fulfilled_via_db:
        # Try debts.json fallback
        debts = _load_debts_from_json(project)
        found = False
        for d in debts:
            if d.get("debt_id") == debt_id:
                d["status"] = "fulfilled"
                d["fulfilled_at"] = str(req.chapter_number)
                d["fulfillment_note"] = req.note
                found = True
                break

        if not found:
            raise HTTPException(404, f"Debt not found: {debt_id}")

        debts_path = project / "debts.json"
        with open(debts_path, "w", encoding="utf-8") as f:
            json.dump(debts, f, ensure_ascii=False, indent=2)

    return {"debt_id": debt_id, "status": "fulfilled"}


@router.get("/arcs")
def list_arcs(novel_id: str):
    """List all story arcs/units."""
    project = _project_path(novel_id)
    arcs = _load_all_arcs(project)
    return {"arcs": arcs, "count": len(arcs)}


@router.get("/briefs/{chapter_number}")
def get_chapter_brief(novel_id: str, chapter_number: int):
    """Get the chapter brief (task list from outline) for a given chapter."""
    project = _project_path(novel_id)
    novel_data = _load_novel_json(project)

    outline = novel_data.get("outline") or {}
    chapters_outline = outline.get("chapters", [])

    # Find the chapter in the outline (1-indexed)
    brief: dict[str, Any] = {}
    chapter_outline: dict[str, Any] = {}
    for ch in chapters_outline:
        ch_num = ch.get("chapter_number", ch.get("number", 0))
        if ch_num == chapter_number:
            chapter_outline = ch
            brief = ch.get("chapter_brief", ch.get("brief", {}))
            break

    if not chapter_outline:
        raise HTTPException(
            404, f"Chapter {chapter_number} not found in outline"
        )

    return {
        "chapter_number": chapter_number,
        "title": chapter_outline.get("title", f"Chapter {chapter_number}"),
        "summary": chapter_outline.get("summary", ""),
        "brief": brief,
    }


@router.get("/graph")
def get_knowledge_graph(novel_id: str):
    """Get knowledge graph data (nodes + edges) for visualization."""
    project = _project_path(novel_id)
    graph_data = _load_knowledge_graph(project)
    return graph_data


@router.post("/rebuild", status_code=201)
def rebuild_narrative(novel_id: str, request: Request):
    """Rebuild narrative control data from existing chapters.

    Scans all chapters, extracts debts, detects fulfilled debts,
    and optionally analyzes story arcs.  Submitted as an async task.
    """
    project = _project_path(novel_id)  # validates novel exists
    keys = extract_api_keys(request)
    task_id = submit_to_queue("novel_narrative_rebuild", {
        "workspace": get_workspace(),
        "project_path": str(project),
        "method": "hybrid",
    }, keys=keys)
    return {"task_id": task_id}


@router.get("/settlement")
def get_settlement(novel_id: str, chapter: int = 1):
    """Get volume settlement status for a chapter."""
    project = _project_path(novel_id)
    db_path = project / "memory.db"

    db = None
    try:
        if db_path.exists():
            from src.novel.storage.structured_db import StructuredDB

            db = StructuredDB(db_path)

        from src.novel.services.volume_settlement import VolumeSettlement

        outline = _get_outline(project)
        vs = VolumeSettlement(db=db, outline=outline)
        return vs.get_settlement_brief(chapter)
    finally:
        if db is not None:
            db.close()


@router.get("/volumes")
def get_volumes(novel_id: str):
    """Get all volumes with settlement statistics."""
    project = _project_path(novel_id)
    db_path = project / "memory.db"

    db = None
    try:
        if db_path.exists():
            from src.novel.storage.structured_db import StructuredDB

            db = StructuredDB(db_path)

        from src.novel.services.volume_settlement import VolumeSettlement

        outline = _get_outline(project)
        vs = VolumeSettlement(db=db, outline=outline)
        return vs.get_volume_summary()
    finally:
        if db is not None:
            db.close()
