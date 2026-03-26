"""Tests for the Prompt Registry API endpoints (src/api/prompts_routes.py).

Uses FastAPI TestClient with a temporary database.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.prompt_registry import PromptRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def override_registry(tmp_path, monkeypatch):
    """Replace the module-level registry singleton with one backed by a temp DB."""
    reg = PromptRegistry(str(tmp_path / "test_prompts.db"))
    import src.api.prompts_routes as prompts_mod

    monkeypatch.setattr(prompts_mod, "_registry", reg)
    yield reg
    reg.close()


@pytest.fixture()
def client(override_registry):
    """Create a TestClient bound to the app (registry already overridden)."""
    from src.api.app import create_app

    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helper: seed a block directly so tests don't depend on /seed
# ---------------------------------------------------------------------------


def _create_test_block(reg: PromptRegistry, base_id: str = "test_block", **kwargs):
    defaults = dict(
        base_id=base_id,
        block_type="craft_technique",
        content="Test content for " + base_id,
        agent="writer",
    )
    defaults.update(kwargs)
    return reg.create_block(**defaults)


# ---------------------------------------------------------------------------
# POST /api/prompts/seed
# ---------------------------------------------------------------------------


def test_seed_prompts(client):
    resp = client.post("/api/prompts/seed")
    assert resp.status_code == 200
    data = resp.json()
    assert "blocks_count" in data
    assert "templates_count" in data
    assert data["blocks_count"] >= 0
    assert data["templates_count"] >= 0


def test_seed_prompts_idempotent(client):
    """Seeding twice should not fail."""
    resp1 = client.post("/api/prompts/seed")
    assert resp1.status_code == 200
    resp2 = client.post("/api/prompts/seed")
    assert resp2.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/prompts/blocks
# ---------------------------------------------------------------------------


def test_list_blocks_empty(client):
    resp = client.get("/api/prompts/blocks")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_blocks_returns_items(client, override_registry):
    _create_test_block(override_registry)
    resp = client.get("/api/prompts/blocks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["base_id"] == "test_block"
    assert data[0]["agent"] == "writer"


def test_list_blocks_filter_by_agent(client, override_registry):
    _create_test_block(override_registry, base_id="b1", agent="writer")
    _create_test_block(override_registry, base_id="b2", agent="reviewer")
    resp = client.get("/api/prompts/blocks?agent=writer")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["base_id"] == "b1"


def test_list_blocks_filter_by_block_type(client, override_registry):
    _create_test_block(override_registry, base_id="b1", block_type="craft_technique")
    _create_test_block(override_registry, base_id="b2", block_type="anti_pattern")
    resp = client.get("/api/prompts/blocks?block_type=anti_pattern")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["base_id"] == "b2"


# ---------------------------------------------------------------------------
# GET /api/prompts/blocks/{base_id}
# ---------------------------------------------------------------------------


def test_get_block(client, override_registry):
    _create_test_block(override_registry, base_id="my_block")
    resp = client.get("/api/prompts/blocks/my_block")
    assert resp.status_code == 200
    data = resp.json()
    assert data["base_id"] == "my_block"
    assert data["version"] == 1
    assert data["active"] is True
    assert "created_at" in data
    assert "updated_at" in data


def test_get_block_not_found(client):
    resp = client.get("/api/prompts/blocks/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/prompts/blocks
# ---------------------------------------------------------------------------


def test_create_block(client):
    resp = client.post(
        "/api/prompts/blocks",
        json={
            "base_id": "new_block",
            "block_type": "system_instruction",
            "content": "You are a helpful writer.",
            "agent": "writer",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["base_id"] == "new_block"
    assert data["version"] == 1
    assert data["block_type"] == "system_instruction"
    assert data["content"] == "You are a helpful writer."
    assert data["agent"] == "writer"
    assert data["active"] is True


def test_create_block_with_optional_fields(client):
    resp = client.post(
        "/api/prompts/blocks",
        json={
            "base_id": "genre_block",
            "block_type": "scene_specific",
            "content": "Write a battle scene.",
            "agent": "writer",
            "genre": "wuxia",
            "scene_type": "battle",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["genre"] == "wuxia"
    assert data["scene_type"] == "battle"


# ---------------------------------------------------------------------------
# PUT /api/prompts/blocks/{base_id}
# ---------------------------------------------------------------------------


def test_update_block_creates_new_version(client, override_registry):
    _create_test_block(override_registry, base_id="evolving")
    resp = client.put(
        "/api/prompts/blocks/evolving",
        json={"content": "Updated content v2"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["base_id"] == "evolving"
    assert data["version"] == 2
    assert data["content"] == "Updated content v2"
    assert data["active"] is True


def test_update_block_not_found(client):
    resp = client.put(
        "/api/prompts/blocks/ghost",
        json={"content": "Updated content"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/prompts/blocks/{base_id}/rollback
# ---------------------------------------------------------------------------


def test_rollback_block(client, override_registry):
    _create_test_block(override_registry, base_id="rb")
    override_registry.update_block("rb", "v2 content")
    override_registry.update_block("rb", "v3 content")

    resp = client.post(
        "/api/prompts/blocks/rb/rollback",
        json={"version": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["base_id"] == "rb"
    assert data["version"] == 1
    assert data["active"] is True


def test_rollback_block_bad_version(client, override_registry):
    _create_test_block(override_registry, base_id="rb2")
    resp = client.post(
        "/api/prompts/blocks/rb2/rollback",
        json={"version": 999},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/prompts/blocks/{base_id}/versions
# ---------------------------------------------------------------------------


def test_get_block_versions(client, override_registry):
    _create_test_block(override_registry, base_id="versioned")
    override_registry.update_block("versioned", "v2 content")

    resp = client.get("/api/prompts/blocks/versioned/versions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["version"] == 1
    assert data[1]["version"] == 2


def test_get_block_versions_not_found(client):
    resp = client.get("/api/prompts/blocks/nope/versions")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/prompts/templates
# ---------------------------------------------------------------------------


def test_list_templates_empty(client):
    resp = client.get("/api/prompts/templates")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_templates(client, override_registry):
    override_registry.create_template(
        template_id="tpl_writer",
        agent_name="writer",
        block_refs=["block_a", "block_b"],
    )
    resp = client.get("/api/prompts/templates")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["template_id"] == "tpl_writer"
    assert data[0]["block_refs"] == ["block_a", "block_b"]


def test_list_templates_filter_by_agent(client, override_registry):
    override_registry.create_template(
        template_id="tpl_w", agent_name="writer", block_refs=["a"]
    )
    override_registry.create_template(
        template_id="tpl_r", agent_name="reviewer", block_refs=["b"]
    )
    resp = client.get("/api/prompts/templates?agent_name=reviewer")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["agent_name"] == "reviewer"


# ---------------------------------------------------------------------------
# GET /api/prompts/templates/{template_id}
# ---------------------------------------------------------------------------


def test_get_template(client, override_registry):
    override_registry.create_template(
        template_id="tpl_fetch",
        agent_name="writer",
        block_refs=["x"],
    )
    resp = client.get("/api/prompts/templates/tpl_fetch")
    assert resp.status_code == 200
    data = resp.json()
    assert data["template_id"] == "tpl_fetch"
    assert data["agent_name"] == "writer"


def test_get_template_not_found(client):
    resp = client.get("/api/prompts/templates/missing")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/prompts/templates
# ---------------------------------------------------------------------------


def test_create_template(client):
    resp = client.post(
        "/api/prompts/templates",
        json={
            "template_id": "tpl_new",
            "agent_name": "writer",
            "block_refs": ["block_1", "block_2"],
            "scenario": "battle",
            "genre": "wuxia",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["template_id"] == "tpl_new"
    assert data["agent_name"] == "writer"
    assert data["scenario"] == "battle"
    assert data["genre"] == "wuxia"
    assert data["block_refs"] == ["block_1", "block_2"]
    assert data["active"] is True


# ---------------------------------------------------------------------------
# POST /api/prompts/build
# ---------------------------------------------------------------------------


def test_build_prompt(client, override_registry):
    # Create a block and a template that references it
    _create_test_block(override_registry, base_id="intro_block", content="Hello, writer!")
    override_registry.create_template(
        template_id="writer:default",
        agent_name="writer",
        block_refs=["intro_block"],
        scenario="default",
    )
    resp = client.post(
        "/api/prompts/build",
        json={"agent_name": "writer", "scenario": "default"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "Hello, writer!" in data["prompt"]
    assert data["length"] > 0


def test_build_prompt_no_template(client):
    """Building a prompt with no matching template returns empty string."""
    resp = client.post(
        "/api/prompts/build",
        json={"agent_name": "nonexistent"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["prompt"] == ""
    assert data["length"] == 0


# ---------------------------------------------------------------------------
# GET /api/prompts/stats/{base_id}
# ---------------------------------------------------------------------------


def test_get_stats(client, override_registry):
    _create_test_block(override_registry, base_id="stat_block")
    resp = client.get("/api/prompts/stats/stat_block")
    assert resp.status_code == 200
    data = resp.json()
    assert "avg_score" in data
    assert "usage_count" in data
    assert "needs_optimization" in data
    assert data["usage_count"] == 0
    assert data["needs_optimization"] is False


def test_get_stats_nonexistent_block(client):
    """Stats for a nonexistent block returns default values (not 404)."""
    resp = client.get("/api/prompts/stats/no_such_block")
    assert resp.status_code == 200
    data = resp.json()
    assert data["avg_score"] is None
    assert data["usage_count"] == 0
    assert data["needs_optimization"] is False
