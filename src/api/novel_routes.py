"""Novel workspace REST endpoints."""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.helpers import validate_id, get_workspace, submit_to_queue, extract_api_keys

log = logging.getLogger("api.novel")

router = APIRouter(prefix="/api/novels", tags=["novels"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class NovelCreateRequest(BaseModel):
    genre: str = "玄幻"
    theme: str
    target_words: int = 100000
    style: str = "webnovel.shuangwen"
    template: str = "cyclic_upgrade"
    custom_ideas: str = ""
    author_name: str = ""
    target_audience: str = "通用"


class NovelGenerateRequest(BaseModel):
    start_chapter: Optional[int] = None
    end_chapter: Optional[int] = None
    batch_size: Optional[int] = None
    target_total: Optional[int] = None
    silent: bool = False
    react_mode: bool = False


class NovelPolishRequest(BaseModel):
    start_chapter: Optional[int] = None
    end_chapter: Optional[int] = None


class FeedbackAnalyzeRequest(BaseModel):
    feedback_text: str
    chapter_number: Optional[int] = None


class FeedbackApplyRequest(BaseModel):
    feedback_text: str
    chapter_number: Optional[int] = None
    rewrite_instructions: Optional[dict] = None


class NovelPlanRequest(BaseModel):
    start_chapter: Optional[int] = None
    end_chapter: Optional[int] = None
    num_chapters: int = 4  # Default: plan 4 chapters ahead


class NovelEditRequest(BaseModel):
    instruction: str
    effective_from_chapter: Optional[int] = None


class NovelResizeRequest(BaseModel):
    new_total: int


class ChapterPublishRequest(BaseModel):
    """Mark chapters as published/unpublished."""
    chapters: list[int]
    published: bool = True


class AgentChatRequest(BaseModel):
    """Natural language instruction to the novel agent."""
    message: str
    context_chapters: Optional[list[int]] = None
    history: Optional[list[dict]] = None
    session_id: Optional[str] = None


class CreateConversationRequest(BaseModel):
    title: str = "新对话"


class ChapterMetadataUpdate(BaseModel):
    title: str | None = None


class ChapterSaveRequest(BaseModel):
    text: str


class ApplyFixesRequest(BaseModel):
    issues: list[dict] = Field(default_factory=list)
    text: str
    selected_indices: list[int] = Field(default_factory=list)


class SettingsSaveRequest(BaseModel):
    world_setting: Optional[dict] = None
    characters: Optional[list] = None
    outline: Optional[dict] = None


class SettingImpactRequest(BaseModel):
    modified_field: str = Field(..., description="world_setting | characters | outline")
    new_value: Any = Field(..., description="New value for the modified field")


class RewriteAffectedRequest(BaseModel):
    impact: dict = Field(..., description="Impact analysis result from analyze-impact")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _novels_dir() -> Path:
    return Path(get_workspace()) / "novels"


def _load_novel_json(novel_id: str) -> dict[str, Any]:
    """Load novel.json for a validated novel_id, raise 404 if missing."""
    validate_id(novel_id)
    path = _novels_dir() / novel_id / "novel.json"
    if not path.exists():
        raise HTTPException(404, f"Novel not found: {novel_id}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _project_path(novel_id: str) -> str:
    """Return the canonical project_path string."""
    return str(_novels_dir() / novel_id)


def _get_structured_db(novel_id: str):
    """Return a StructuredDB instance for the given novel."""
    import os
    from src.novel.storage.structured_db import StructuredDB
    project_path = _project_path(novel_id)
    db_path = os.path.join(project_path, "memory.db")
    return StructuredDB(db_path)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def create_novel(req: NovelCreateRequest, request: Request):
    """Create a novel project. Submits to task queue, returns task_id."""
    if not req.theme or not req.theme.strip():
        raise HTTPException(400, "theme is required")

    keys = extract_api_keys(request)
    task_id = submit_to_queue("novel_create", {
        "workspace": get_workspace(),
        "genre": req.genre,
        "theme": req.theme.strip(),
        "target_words": req.target_words,
        "style": req.style,
        "template": req.template,
        "custom_ideas": req.custom_ideas,
        "author_name": req.author_name,
        "target_audience": req.target_audience,
    }, keys=keys)
    return {"task_id": task_id}


@router.get("")
def list_novels():
    """List all novel projects from workspace/novels/."""
    novels_dir = _novels_dir()
    if not novels_dir.exists():
        return []

    projects = []
    for d in sorted(novels_dir.iterdir()):
        if not d.is_dir() or not (d / "novel.json").exists():
            continue
        try:
            data = json.loads((d / "novel.json").read_text(encoding="utf-8"))
            # Count chapters
            chapters_dir = d / "chapters"
            chapter_count = 0
            if chapters_dir.exists():
                chapter_count = len(list(chapters_dir.glob("chapter_*.json")))

            # Total chapters from outline
            outline = data.get("outline") or {}
            total_chapters = len(outline.get("chapters", []))

            published = data.get("published_chapters", [])
            projects.append({
                "id": d.name,
                "title": data.get("title", d.name),
                "genre": data.get("genre", ""),
                "status": data.get("status", "unknown"),
                "current_chapter": data.get("current_chapter", 0),
                "total_chapters": total_chapters,
                "completed_chapters": chapter_count,
                "published_count": len(published),
                "target_words": data.get("target_words", 0),
                "style_name": data.get("style_name", ""),
                "author_name": data.get("author_name", ""),
                "synopsis": data.get("synopsis", ""),
            })
        except Exception as exc:
            log.warning("Failed to read novel %s: %s", d.name, exc)
            projects.append({"id": d.name, "title": d.name, "status": "error"})

    return projects


@router.get("/{novel_id}")
def get_novel(novel_id: str):
    """Get full novel project detail."""
    validate_id(novel_id)
    data = _load_novel_json(novel_id)
    novel_dir = _novels_dir() / novel_id

    # Enumerate chapters
    published_chapters = set(data.get("published_chapters", []))
    chapters_info = []
    chapters_dir = novel_dir / "chapters"
    if chapters_dir.exists():
        for p in sorted(chapters_dir.glob("chapter_*.json")):
            try:
                ch_data = json.loads(p.read_text(encoding="utf-8"))
                num = int(p.stem.split("_")[1])
                chapters_info.append({
                    "chapter_number": num,
                    "title": ch_data.get("title", f"第{num}章"),
                    "word_count": ch_data.get("word_count", 0),
                    "published": num in published_chapters,
                })
            except Exception:
                continue

    outline = data.get("outline") or {}
    total_chapters = len(outline.get("chapters", []))
    characters = data.get("characters", [])

    return {
        "id": novel_id,
        "title": data.get("title", ""),
        "genre": data.get("genre", ""),
        "theme": data.get("theme", ""),
        "status": data.get("status", "unknown"),
        "style_name": data.get("style_name", ""),
        "author_name": data.get("author_name", ""),
        "target_audience": data.get("target_audience", ""),
        "target_words": data.get("target_words", 0),
        "current_chapter": data.get("current_chapter", 0),
        "total_chapters": total_chapters,
        "synopsis": data.get("synopsis", ""),
        "tags": data.get("tags", []),
        "protagonist_names": data.get("protagonist_names", []),
        "outline": outline,
        "characters": characters,
        "world_setting": data.get("world_setting"),
        "chapters": chapters_info,
        "published_chapters": sorted(published_chapters),
        "progress": len(chapters_info) / total_chapters if total_chapters > 0 else 0,
        "created_at": data.get("created_at", ""),
        "updated_at": data.get("updated_at", ""),
    }


@router.post("/{novel_id}/generate", status_code=201)
def generate_chapters(novel_id: str, req: NovelGenerateRequest, request: Request):
    """Generate chapters. Submits to task queue, returns task_id."""
    validate_id(novel_id)
    _load_novel_json(novel_id)
    keys = extract_api_keys(request)

    params: dict[str, Any] = {
        "workspace": get_workspace(),
        "project_path": _project_path(novel_id),
        "silent": req.silent,
    }
    if req.start_chapter is not None:
        params["start_chapter"] = req.start_chapter
    if req.end_chapter is not None:
        params["end_chapter"] = req.end_chapter
    if req.batch_size is not None:
        params["batch_size"] = req.batch_size
    if req.target_total is not None:
        params["target_total"] = req.target_total
    if req.react_mode:
        params["react_mode"] = True

    task_id = submit_to_queue("novel_generate", params, keys=keys)
    return {"task_id": task_id}


@router.post("/{novel_id}/plan-chapters", status_code=201)
def plan_chapters(novel_id: str, req: NovelPlanRequest, request: Request):
    """Plan chapter outlines without generating text. Submits to task queue, returns task_id."""
    validate_id(novel_id)
    _load_novel_json(novel_id)
    keys = extract_api_keys(request)

    params: dict[str, Any] = {
        "workspace": get_workspace(),
        "project_path": _project_path(novel_id),
    }
    if req.start_chapter is not None:
        params["start_chapter"] = req.start_chapter
    if req.end_chapter is not None:
        params["end_chapter"] = req.end_chapter
    if req.num_chapters:
        params["num_chapters"] = req.num_chapters

    task_id = submit_to_queue("novel_plan", params, keys=keys)
    return {"task_id": task_id}


@router.post("/{novel_id}/polish", status_code=201)
def polish_chapters(novel_id: str, req: NovelPolishRequest, request: Request):
    """Polish chapters. Submits to task queue, returns task_id."""
    validate_id(novel_id)
    _load_novel_json(novel_id)
    keys = extract_api_keys(request)

    params: dict[str, Any] = {
        "workspace": get_workspace(),
        "project_path": _project_path(novel_id),
    }
    if req.start_chapter is not None:
        params["start_chapter"] = req.start_chapter
    if req.end_chapter is not None:
        params["end_chapter"] = req.end_chapter

    task_id = submit_to_queue("novel_polish", params, keys=keys)
    return {"task_id": task_id}


@router.post("/{novel_id}/feedback/analyze", status_code=201)
def analyze_feedback(novel_id: str, req: FeedbackAnalyzeRequest, request: Request):
    """Analyze feedback (dry_run=True). Submits to task queue, returns task_id."""
    validate_id(novel_id)
    _load_novel_json(novel_id)
    keys = extract_api_keys(request)

    if not req.feedback_text or not req.feedback_text.strip():
        raise HTTPException(400, "feedback_text is required")

    params: dict[str, Any] = {
        "workspace": get_workspace(),
        "project_path": _project_path(novel_id),
        "feedback_text": req.feedback_text.strip(),
        "dry_run": True,
    }
    if req.chapter_number is not None:
        params["chapter_number"] = req.chapter_number

    task_id = submit_to_queue("novel_feedback", params, keys=keys)
    return {"task_id": task_id}


@router.post("/{novel_id}/feedback/apply", status_code=201)
def apply_feedback(novel_id: str, req: FeedbackApplyRequest, request: Request):
    """Apply feedback. Submits to task queue, returns task_id."""
    validate_id(novel_id)
    _load_novel_json(novel_id)
    keys = extract_api_keys(request)

    if not req.feedback_text or not req.feedback_text.strip():
        raise HTTPException(400, "feedback_text is required")

    params: dict[str, Any] = {
        "workspace": get_workspace(),
        "project_path": _project_path(novel_id),
        "feedback_text": req.feedback_text.strip(),
        "dry_run": False,
    }
    if req.chapter_number is not None:
        params["chapter_number"] = req.chapter_number
    if req.rewrite_instructions is not None:
        params["rewrite_instructions"] = req.rewrite_instructions

    task_id = submit_to_queue("novel_feedback", params, keys=keys)
    return {"task_id": task_id}


@router.post("/{novel_id}/edit")
def edit_novel(novel_id: str, req: NovelEditRequest):
    """AI edit settings. Runs synchronously, returns result."""
    validate_id(novel_id)
    _load_novel_json(novel_id)

    if not req.instruction or not req.instruction.strip():
        raise HTTPException(400, "instruction is required")

    from src.novel.services.edit_service import NovelEditService

    svc = NovelEditService(workspace=get_workspace())
    result = svc.edit(
        project_path=_project_path(novel_id),
        instruction=req.instruction.strip(),
        effective_from_chapter=req.effective_from_chapter,
    )

    if result.status == "failed":
        raise HTTPException(500, result.error or "Edit failed")

    return {
        "change_id": result.change_id,
        "status": result.status,
        "change_type": result.change_type,
        "entity_type": result.entity_type,
        "entity_id": result.entity_id,
        "old_value": result.old_value,
        "new_value": result.new_value,
        "effective_from_chapter": result.effective_from_chapter,
        "reasoning": result.reasoning,
    }


@router.post("/{novel_id}/resize")
def resize_novel(novel_id: str, req: NovelResizeRequest, request: Request):
    """Resize novel outline (expand or shrink). Submits to task queue for expansion."""
    validate_id(novel_id)
    _load_novel_json(novel_id)

    if req.new_total < 1:
        raise HTTPException(400, "new_total must be >= 1")

    # Check current total
    data = _load_novel_json(novel_id)
    outline = data.get("outline") or {}
    current_total = len(outline.get("chapters", []))

    if req.new_total == current_total:
        return {"old_total": current_total, "new_total": current_total, "action": "none"}

    if req.new_total > current_total:
        # Expansion needs LLM — submit to task queue
        keys = extract_api_keys(request)
        task_id = submit_to_queue("novel_resize", {
            "workspace": get_workspace(),
            "project_path": _project_path(novel_id),
            "new_total": req.new_total,
        }, keys=keys)
        return {"task_id": task_id, "action": "expanding", "old_total": current_total, "new_total": req.new_total}
    else:
        # Shrink is fast — do it synchronously
        from src.novel.pipeline import NovelPipeline
        pipe = NovelPipeline(workspace=get_workspace())
        result = pipe.resize_novel(_project_path(novel_id), req.new_total)
        return result


@router.post("/{novel_id}/chapters/publish")
def publish_chapters(novel_id: str, req: ChapterPublishRequest):
    """Mark chapters as published or unpublished."""
    validate_id(novel_id)
    novel_dir = _novels_dir() / novel_id
    if not (novel_dir / "novel.json").exists():
        raise HTTPException(404, f"Novel not found: {novel_id}")

    # Load novel.json and update published list
    data = _load_novel_json(novel_id)
    published_set = set(data.get("published_chapters", []))

    for ch in req.chapters:
        if req.published:
            published_set.add(ch)
        else:
            published_set.discard(ch)

    data["published_chapters"] = sorted(published_set)

    # Save
    path = _novels_dir() / novel_id / "novel.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return {"published_chapters": data["published_chapters"]}


# ---------------------------------------------------------------------------
# Conversation endpoints (Agent Chat session persistence)
# ---------------------------------------------------------------------------

@router.get("/{novel_id}/conversations")
def list_conversations(novel_id: str):
    """List all chat conversations for a novel."""
    validate_id(novel_id)
    db = _get_structured_db(novel_id)
    return db.list_conversations(novel_id)


@router.post("/{novel_id}/conversations", status_code=201)
def create_conversation(novel_id: str, req: CreateConversationRequest):
    """Create a new chat conversation."""
    validate_id(novel_id)
    db = _get_structured_db(novel_id)
    return db.create_conversation(novel_id, title=req.title)


@router.get("/{novel_id}/conversations/{session_id}/messages")
def get_conversation_messages(novel_id: str, session_id: str):
    """Get all messages in a conversation."""
    validate_id(novel_id)
    db = _get_structured_db(novel_id)
    return db.get_conversation_messages(session_id)


@router.delete("/{novel_id}/conversations/{session_id}")
def delete_conversation(novel_id: str, session_id: str):
    """Delete a conversation and its messages."""
    validate_id(novel_id)
    db = _get_structured_db(novel_id)
    db.delete_conversation(session_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Agent Chat
# ---------------------------------------------------------------------------

@router.post("/{novel_id}/agent-chat", status_code=201)
def agent_chat(novel_id: str, req: AgentChatRequest, request: Request):
    """Natural language agent chat — interpret user instruction and execute.

    Works like Claude Code: user sends a message, agent figures out what to do
    (edit settings, modify chapters, adjust outline, etc.) and returns results.
    """
    validate_id(novel_id)
    _load_novel_json(novel_id)
    keys = extract_api_keys(request)

    if not req.message or not req.message.strip():
        raise HTTPException(400, "message is required")

    # Session persistence: create or reuse conversation
    db = _get_structured_db(novel_id)
    session_id = req.session_id
    if not session_id:
        title = req.message[:20].strip() + ("..." if len(req.message) > 20 else "")
        conv = db.create_conversation(novel_id, title=title)
        session_id = conv["session_id"]

    # Save user message immediately
    db.add_message(session_id, "user", req.message.strip())

    task_id = submit_to_queue("novel_agent_chat", {
        "workspace": get_workspace(),
        "project_path": _project_path(novel_id),
        "message": req.message.strip(),
        "context_chapters": req.context_chapters,
        "history": req.history,
        "session_id": session_id,
    }, keys=keys)
    return {"task_id": task_id, "session_id": session_id}


@router.get("/{novel_id}/chapters/{chapter_num}")
def read_chapter(novel_id: str, chapter_num: int):
    """Read a specific chapter's text and metadata."""
    validate_id(novel_id)
    novel_dir = _novels_dir() / novel_id
    if not (novel_dir / "novel.json").exists():
        raise HTTPException(404, f"Novel not found: {novel_id}")

    from src.novel.storage.file_manager import FileManager

    fm = FileManager(get_workspace())
    ch_data = fm.load_chapter(novel_id, chapter_num)
    if ch_data is None:
        raise HTTPException(404, f"Chapter {chapter_num} not found")

    text = ch_data.get("full_text", "")
    if not text:
        text = fm.load_chapter_text(novel_id, chapter_num) or ""

    # Check published status
    novel_data = _load_novel_json(novel_id)
    published_chapters = novel_data.get("published_chapters", [])

    return {
        "number": chapter_num,
        "title": ch_data.get("title", f"Chapter {chapter_num}"),
        "word_count": ch_data.get("word_count", 0),
        "text": text,
        "quality_score": ch_data.get("quality_score"),
        "style_score": ch_data.get("style_score"),
        "published": chapter_num in published_chapters,
    }


@router.patch("/{novel_id}/chapters/{chapter_num}")
def update_chapter_metadata(novel_id: str, chapter_num: int, req: ChapterMetadataUpdate):
    """Update chapter metadata (title, etc.) without modifying content."""
    validate_id(novel_id)
    novel_dir = _novels_dir() / novel_id
    json_path = novel_dir / "chapters" / f"chapter_{chapter_num:03d}.json"

    if not json_path.exists():
        raise HTTPException(404, f"Chapter {chapter_num} not found")

    data = json.loads(json_path.read_text(encoding="utf-8"))

    if req.title is not None:
        data["title"] = req.title

    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Also update outline in novel.json
    try:
        novel_data = _load_novel_json(novel_id)
        outline = novel_data.get("outline", {})
        for ch in outline.get("chapters", []):
            if ch.get("chapter_number") == chapter_num:
                if req.title is not None:
                    ch["title"] = req.title
                break
        novel_json_path = novel_dir / "novel.json"
        novel_json_path.write_text(
            json.dumps(novel_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass

    return {"success": True, "chapter_number": chapter_num, "title": req.title}


@router.get("/{novel_id}/export")
def export_novel(novel_id: str):
    """Export novel as TXT. Returns file path and text content."""
    validate_id(novel_id)
    _load_novel_json(novel_id)

    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline(workspace=get_workspace())
    try:
        output_path = pipe.export_novel(_project_path(novel_id))
    except Exception as exc:
        raise HTTPException(500, f"Export failed: {exc}")

    # Read exported text
    text = ""
    try:
        text = Path(output_path).read_text(encoding="utf-8")
    except Exception:
        pass

    return {
        "path": output_path,
        "text": text,
    }


@router.delete("/{novel_id}", status_code=204)
def delete_novel(novel_id: str):
    """Delete a novel project directory."""
    validate_id(novel_id)
    novel_dir = _novels_dir() / novel_id
    if not novel_dir.exists():
        raise HTTPException(404, f"Novel not found: {novel_id}")

    shutil.rmtree(novel_dir)


# ---------------------------------------------------------------------------
# Chapter Save
# ---------------------------------------------------------------------------

@router.put("/{novel_id}/chapters/{chapter_num}")
def save_chapter(novel_id: str, chapter_num: int, req: ChapterSaveRequest):
    """Save edited chapter text (auto-backs up old version)."""
    validate_id(novel_id)
    _load_novel_json(novel_id)

    if not req.text or not req.text.strip():
        raise HTTPException(400, "text is required")

    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline(workspace=get_workspace())
    try:
        result = pipe.save_edited_chapter(
            _project_path(novel_id), chapter_num, req.text
        )
    except Exception as exc:
        raise HTTPException(500, f"Save failed: {exc}")

    return result


# ---------------------------------------------------------------------------
# Chapter Proofread
# ---------------------------------------------------------------------------

@router.post("/{novel_id}/chapters/{chapter_num}/proofread")
def proofread_chapter(novel_id: str, chapter_num: int):
    """AI proofread a chapter. Returns list of issues."""
    validate_id(novel_id)
    _load_novel_json(novel_id)

    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline(workspace=get_workspace())
    try:
        issues = pipe.proofread_chapter(_project_path(novel_id), chapter_num)
    except Exception as exc:
        raise HTTPException(500, f"Proofread failed: {exc}")

    return {"issues": issues, "count": len(issues)}


# ---------------------------------------------------------------------------
# Apply Proofread Fixes
# ---------------------------------------------------------------------------

@router.post("/{novel_id}/chapters/{chapter_num}/apply-fixes")
def apply_proofread_fixes(
    novel_id: str, chapter_num: int, req: ApplyFixesRequest
):
    """Apply selected proofread fixes to chapter text."""
    validate_id(novel_id)
    _load_novel_json(novel_id)

    if not req.text or not req.text.strip():
        raise HTTPException(400, "text is required")
    if not req.issues:
        raise HTTPException(400, "issues list is required")
    if not req.selected_indices:
        raise HTTPException(400, "selected_indices is required")

    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline(workspace=get_workspace())
    try:
        fixed_text, failures = pipe.apply_proofreading_fixes(
            _project_path(novel_id),
            chapter_num,
            req.text,
            req.issues,
            req.selected_indices,
        )
    except Exception as exc:
        raise HTTPException(500, f"Apply fixes failed: {exc}")

    applied = len(req.selected_indices) - len(failures)
    return {
        "text": fixed_text,
        "applied": applied,
        "total": len(req.selected_indices),
        "failures": failures,
    }


# ---------------------------------------------------------------------------
# Polish Diff
# ---------------------------------------------------------------------------

@router.get("/{novel_id}/chapters/{chapter_num}/polish-diff")
def get_polish_diff(novel_id: str, chapter_num: int):
    """Get before/after text for a polished chapter."""
    validate_id(novel_id)
    _load_novel_json(novel_id)

    from src.novel.storage.file_manager import FileManager

    fm = FileManager(get_workspace())

    revisions = fm.list_chapter_revisions(novel_id, chapter_num)
    if not revisions:
        raise HTTPException(404, f"Chapter {chapter_num} has no revision history")

    latest_rev = max(revisions)
    original_text = fm.load_chapter_revision(novel_id, chapter_num, latest_rev) or ""
    polished_text = fm.load_chapter_text(novel_id, chapter_num) or ""

    return {
        "original_text": original_text,
        "polished_text": polished_text,
        "revision": latest_rev,
        "original_chars": len(original_text),
        "polished_chars": len(polished_text),
    }


# ---------------------------------------------------------------------------
# Novel Settings CRUD
# ---------------------------------------------------------------------------

@router.get("/{novel_id}/settings")
def get_novel_settings(novel_id: str):
    """Load all editable settings (world, characters, outline, main storyline)."""
    validate_id(novel_id)
    data = _load_novel_json(novel_id)

    world_setting = data.get("world_setting", {})
    characters = data.get("characters", [])
    outline = data.get("outline", {})
    main_storyline = outline.get("main_storyline", {})
    outline_chapters = outline.get("chapters", [])

    return {
        "world_setting": world_setting,
        "characters": characters,
        "outline": {
            "main_storyline": main_storyline,
            "chapters": outline_chapters,
        },
    }


@router.put("/{novel_id}/settings")
def save_novel_settings(novel_id: str, req: SettingsSaveRequest):
    """Save settings changes (world_setting, characters, outline).

    Only provided fields are updated; missing fields are left unchanged.
    Creates a backup of novel.json before saving.
    """
    validate_id(novel_id)
    novel_dir = _novels_dir() / novel_id
    novel_json_path = novel_dir / "novel.json"
    if not novel_json_path.exists():
        raise HTTPException(404, f"Novel not found: {novel_id}")

    from datetime import datetime

    data = json.loads(novel_json_path.read_text(encoding="utf-8"))

    # Backup
    backup_dir = novel_dir / "revisions"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(novel_json_path, backup_dir / f"novel_backup_{timestamp}.json")

    updated_fields = []

    if req.world_setting is not None:
        data["world_setting"] = req.world_setting
        updated_fields.append("world_setting")

    if req.characters is not None:
        data["characters"] = req.characters
        updated_fields.append("characters")

    if req.outline is not None:
        data["outline"] = req.outline
        updated_fields.append("outline")

    data["updated_at"] = datetime.now().isoformat()
    novel_json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "saved": True,
        "updated_fields": updated_fields,
    }


# ---------------------------------------------------------------------------
# Setting Impact Analysis
# ---------------------------------------------------------------------------

@router.post("/{novel_id}/settings/analyze-impact")
def analyze_setting_impact(novel_id: str, req: SettingImpactRequest):
    """Analyze impact of setting changes on existing chapters."""
    validate_id(novel_id)
    _load_novel_json(novel_id)

    valid_fields = ("world_setting", "characters", "outline")
    if req.modified_field not in valid_fields:
        raise HTTPException(
            400, f"modified_field must be one of {valid_fields}"
        )

    new_value_json = json.dumps(req.new_value, ensure_ascii=False, indent=2)

    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline(workspace=get_workspace())
    try:
        impact = pipe.analyze_setting_impact(
            _project_path(novel_id), req.modified_field, new_value_json
        )
    except Exception as exc:
        raise HTTPException(500, f"Impact analysis failed: {exc}")

    if "error" in impact:
        raise HTTPException(500, impact["error"])

    return impact


@router.post("/{novel_id}/settings/rewrite-affected", status_code=201)
def rewrite_affected_chapters(
    novel_id: str, req: RewriteAffectedRequest, request: Request
):
    """Rewrite chapters affected by setting changes. Submits to task queue."""
    validate_id(novel_id)
    _load_novel_json(novel_id)

    affected = req.impact.get("affected_chapters", [])
    if not affected:
        raise HTTPException(400, "No affected chapters to rewrite")

    keys = extract_api_keys(request)
    task_id = submit_to_queue("novel_rewrite_affected", {
        "workspace": get_workspace(),
        "project_path": _project_path(novel_id),
        "impact": req.impact,
    }, keys=keys)
    return {"task_id": task_id}
