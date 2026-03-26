"""Prompt Registry REST endpoints.

CRUD for prompt blocks, templates, prompt assembly, and seeding defaults.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.prompt_registry import PromptRegistry
from src.prompt_registry.seed_data import seed_default_prompts

log = logging.getLogger("api.prompts")

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

_registry: PromptRegistry | None = None


def _get_registry() -> PromptRegistry:
    global _registry
    if _registry is None:
        _registry = PromptRegistry("workspace/prompt_registry.db")
    return _registry


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateBlockRequest(BaseModel):
    base_id: str
    block_type: str
    content: str
    agent: str = "universal"
    genre: str | None = None
    scene_type: str | None = None


class UpdateBlockRequest(BaseModel):
    content: str


class RollbackRequest(BaseModel):
    version: int


class CreateTemplateRequest(BaseModel):
    template_id: str
    agent_name: str
    block_refs: list[str]
    scenario: str = "default"
    genre: str | None = None


class BuildPromptRequest(BaseModel):
    agent_name: str
    scenario: str = "default"
    genre: str | None = None
    context: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Block endpoints
# ---------------------------------------------------------------------------


@router.get("/blocks")
def list_blocks(
    agent: str | None = None,
    block_type: str | None = None,
    active_only: bool = True,
):
    reg = _get_registry()
    blocks = reg.list_blocks(agent=agent, block_type=block_type, active_only=active_only)
    return [_block_to_dict(b) for b in blocks]


@router.get("/blocks/{base_id}")
def get_block(base_id: str):
    reg = _get_registry()
    block = reg.get_active_block(base_id)
    if block is None:
        raise HTTPException(404, f"Block '{base_id}' not found")
    return _block_to_dict(block)


@router.get("/blocks/{base_id}/versions")
def get_block_versions(base_id: str):
    reg = _get_registry()
    versions = reg.get_block_versions(base_id)
    if not versions:
        raise HTTPException(404, f"Block '{base_id}' not found")
    return [_block_to_dict(b) for b in versions]


@router.post("/blocks", status_code=201)
def create_block(req: CreateBlockRequest):
    reg = _get_registry()
    block = reg.create_block(
        base_id=req.base_id,
        block_type=req.block_type,
        content=req.content,
        agent=req.agent,
        genre=req.genre,
        scene_type=req.scene_type,
    )
    return _block_to_dict(block)


@router.put("/blocks/{base_id}")
def update_block(base_id: str, req: UpdateBlockRequest):
    reg = _get_registry()
    try:
        block = reg.update_block(base_id, req.content)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _block_to_dict(block)


@router.post("/blocks/{base_id}/rollback")
def rollback_block(base_id: str, req: RollbackRequest):
    reg = _get_registry()
    try:
        block = reg.rollback_block(base_id, req.version)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _block_to_dict(block)


# ---------------------------------------------------------------------------
# Template endpoints
# ---------------------------------------------------------------------------


@router.get("/templates")
def list_templates(agent_name: str | None = None):
    reg = _get_registry()
    templates = reg.list_templates(agent_name=agent_name)
    return [_template_to_dict(t) for t in templates]


@router.get("/templates/{template_id}")
def get_template(template_id: str):
    reg = _get_registry()
    tpl = reg.get_template(template_id)
    if tpl is None:
        raise HTTPException(404, f"Template '{template_id}' not found")
    return _template_to_dict(tpl)


@router.post("/templates", status_code=201)
def create_template(req: CreateTemplateRequest):
    reg = _get_registry()
    tpl = reg.create_template(
        template_id=req.template_id,
        agent_name=req.agent_name,
        block_refs=req.block_refs,
        scenario=req.scenario,
        genre=req.genre,
    )
    return _template_to_dict(tpl)


# ---------------------------------------------------------------------------
# Build & Stats
# ---------------------------------------------------------------------------


@router.post("/build")
def build_prompt(req: BuildPromptRequest):
    reg = _get_registry()
    prompt = reg.build_prompt(
        agent_name=req.agent_name,
        scenario=req.scenario,
        genre=req.genre,
        context=req.context,
    )
    return {"prompt": prompt, "length": len(prompt)}


@router.get("/stats/{base_id}")
def get_stats(base_id: str):
    reg = _get_registry()
    return reg.get_block_stats(base_id)


@router.post("/seed")
def seed_prompts():
    reg = _get_registry()
    seed_default_prompts(reg)
    blocks = reg.list_blocks()
    templates = reg.list_templates()
    return {"blocks_count": len(blocks), "templates_count": len(templates)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _block_to_dict(block) -> dict:
    return {
        "block_id": block.block_id,
        "base_id": block.base_id,
        "version": block.version,
        "block_type": block.block_type,
        "agent": block.agent,
        "genre": block.genre,
        "scene_type": block.scene_type,
        "content": block.content,
        "active": block.active,
        "needs_optimization": block.needs_optimization,
        "avg_score": block.avg_score,
        "usage_count": block.usage_count,
        "metadata": block.metadata,
        "created_at": block.created_at.isoformat() if block.created_at else None,
        "updated_at": block.updated_at.isoformat() if block.updated_at else None,
    }


def _template_to_dict(tpl) -> dict:
    return {
        "template_id": tpl.template_id,
        "agent_name": tpl.agent_name,
        "scenario": tpl.scenario,
        "genre": tpl.genre,
        "block_refs": tpl.block_refs,
        "active": tpl.active,
        "created_at": tpl.created_at.isoformat() if tpl.created_at else None,
    }
