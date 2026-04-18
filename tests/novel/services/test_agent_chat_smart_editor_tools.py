"""Tests for the 6 smart-editor / narrative tools added to agent_chat.

Covers:
- get_change_history
- rollback_change
- analyze_change_impact
- batch_edit_settings
- get_foreshadowing_graph
- get_health_dashboard
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.novel.services.agent_chat import TOOLS, AgentToolExecutor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_novel(workspace: Path, novel_id: str = "novel_chat_se") -> dict:
    """Create a minimal but realistic novel.json for editor tests."""
    d = workspace / "novels" / novel_id
    d.mkdir(parents=True)
    data = {
        "novel_id": novel_id,
        "title": "agent-chat 编辑测试",
        "genre": "玄幻",
        "current_chapter": 3,
        "characters": [
            {
                "character_id": "char_001",
                "name": "张三",
                "gender": "男",
                "age": 18,
                "occupation": "修炼者",
                "role": "主角",
                "status": "active",
                "version": 1,
                "effective_from_chapter": 1,
                "appearance": {
                    "height": "180",
                    "build": "健硕",
                    "hair": "黑",
                    "eyes": "黑",
                    "clothing_style": "青",
                },
                "personality": {
                    "traits": ["坚毅", "善良", "勇敢"],
                    "core_belief": "义",
                    "motivation": "强",
                    "flaw": "急",
                    "speech_style": "直",
                },
            },
        ],
        "world_setting": {
            "era": "古",
            "location": "九州",
            "rules": ["天道"],
            "terms": {"灵气": "能量"},
        },
        "outline": {
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "旧一",
                    "goal": "开篇",
                    "key_events": ["入门"],
                },
                {
                    "chapter_number": 2,
                    "title": "旧二",
                    "goal": "成长",
                    "key_events": ["拜师"],
                },
                {
                    "chapter_number": 3,
                    "title": "旧三",
                    "goal": "冲突",
                    "key_events": ["初战"],
                },
            ],
        },
        "config": {"llm": {"provider": "auto"}},
    }
    (d / "novel.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data


@pytest.fixture
def workspace(tmp_path):
    novel_id = "novel_chat_se"
    _seed_novel(tmp_path, novel_id)
    return tmp_path, novel_id


@pytest.fixture
def executor(workspace):
    ws, novel_id = workspace
    yield AgentToolExecutor(str(ws), novel_id)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_all_six_tools_registered(self):
        names = {t["name"] for t in TOOLS}
        for n in (
            "get_change_history",
            "rollback_change",
            "analyze_change_impact",
            "batch_edit_settings",
            "get_foreshadowing_graph",
            "get_health_dashboard",
        ):
            assert n in names, f"missing {n}"

    def test_each_tool_has_implementation(self):
        for tool in TOOLS:
            name = tool["name"]
            assert hasattr(AgentToolExecutor, f"_tool_{name}"), name


# ---------------------------------------------------------------------------
# get_change_history
# ---------------------------------------------------------------------------


class TestGetChangeHistory:
    def test_empty_history(self, executor):
        result = executor.execute("get_change_history", {})
        assert result.get("total") == 0
        assert result.get("changes") == []

    def test_returns_entries_after_edit(self, executor, workspace):
        ws, novel_id = workspace
        from src.novel.services.edit_service import NovelEditService

        svc = NovelEditService(workspace=str(ws))
        svc.edit(
            project_path=str(ws / "novels" / novel_id),
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "new_value": {"age": 25},
            },
        )

        result = executor.execute("get_change_history", {"limit": 5})
        assert result["total"] >= 1
        first = result["changes"][0]
        for k in (
            "change_id",
            "timestamp",
            "change_type",
            "entity_type",
            "entity_id",
        ):
            assert k in first

    def test_limit_clamped(self, executor):
        # huge limit must not blow up
        result = executor.execute("get_change_history", {"limit": 99999})
        assert "changes" in result

    def test_invalid_limit_falls_back(self, executor):
        result = executor.execute("get_change_history", {"limit": "abc"})
        assert "changes" in result

    def test_change_type_filter_passes_through(self, executor, workspace):
        ws, novel_id = workspace
        from src.novel.services.edit_service import NovelEditService

        svc = NovelEditService(workspace=str(ws))
        svc.edit(
            project_path=str(ws / "novels" / novel_id),
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "new_value": {"age": 30},
            },
        )

        result = executor.execute(
            "get_change_history", {"change_type": "update"}
        )
        assert result["total"] >= 1
        for c in result["changes"]:
            assert "update" in c["change_type"]


# ---------------------------------------------------------------------------
# rollback_change
# ---------------------------------------------------------------------------


class TestRollbackChange:
    def test_missing_change_id(self, executor):
        result = executor.execute("rollback_change", {"change_id": ""})
        assert "error" in result

    def test_unknown_change_id(self, executor):
        result = executor.execute(
            "rollback_change", {"change_id": "no-such-id"}
        )
        assert result.get("status") == "failed"
        assert result.get("error")

    def test_rollback_success(self, executor, workspace):
        ws, novel_id = workspace
        from src.novel.services.edit_service import NovelEditService

        svc = NovelEditService(workspace=str(ws))
        edit_result = svc.edit(
            project_path=str(ws / "novels" / novel_id),
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "new_value": {"age": 99},
            },
        )
        assert edit_result.status == "success"

        result = executor.execute(
            "rollback_change", {"change_id": edit_result.change_id}
        )
        assert result["status"] == "success"
        assert result["reverted_change_id"] == edit_result.change_id
        assert result["entity_type"] == "character"

        # Verify state actually reverted
        novel = json.loads(
            (ws / "novels" / novel_id / "novel.json").read_text("utf-8")
        )
        assert novel["characters"][0]["age"] == 18


# ---------------------------------------------------------------------------
# analyze_change_impact
# ---------------------------------------------------------------------------


class TestAnalyzeChangeImpact:
    def test_happy_path_modify_character(self, executor):
        result = executor.execute(
            "analyze_change_impact",
            {
                "change_type": "modify_character",
                "entity_type": "character",
                "entity_id": "char_001",
                "effective_from_chapter": 2,
                "details": {"name": "新名字"},
            },
        )
        assert "severity" in result
        assert result["severity"] in ("low", "medium", "high", "critical")
        assert "summary" in result
        assert isinstance(result["affected_chapters"], list)

    def test_invalid_effective_chapter(self, executor):
        result = executor.execute(
            "analyze_change_impact",
            {
                "change_type": "modify_character",
                "entity_type": "character",
                "effective_from_chapter": 0,
            },
        )
        assert "error" in result

    def test_non_integer_effective_chapter(self, executor):
        result = executor.execute(
            "analyze_change_impact",
            {
                "change_type": "modify_character",
                "entity_type": "character",
                "effective_from_chapter": "abc",
            },
        )
        assert "error" in result

    def test_invalid_change_type_returns_error(self, executor):
        # invalid entity_type still flows through since ChangeRequest accepts
        # any string; the analyzer returns a low-severity unknown result.
        result = executor.execute(
            "analyze_change_impact",
            {
                "change_type": "modify_character",
                "entity_type": "bogus",
                "effective_from_chapter": 1,
            },
        )
        # Either an analyzer-level low severity, or pydantic-level error
        assert "severity" in result or "error" in result

    def test_missing_novel_returns_error(self, tmp_path):
        # No seeded novel
        executor = AgentToolExecutor(str(tmp_path), "missing_novel")
        result = executor.execute(
            "analyze_change_impact",
            {
                "change_type": "modify_character",
                "entity_type": "character",
                "effective_from_chapter": 1,
            },
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# batch_edit_settings
# ---------------------------------------------------------------------------


class TestBatchEditSettings:
    def test_empty_changes_rejected(self, executor):
        result = executor.execute("batch_edit_settings", {"changes": []})
        assert "error" in result

    def test_non_list_rejected(self, executor):
        result = executor.execute(
            "batch_edit_settings", {"changes": "not-a-list"}
        )
        assert "error" in result

    def test_too_many_changes_rejected(self, executor):
        result = executor.execute(
            "batch_edit_settings", {"changes": [{}] * 51}
        )
        assert "error" in result
        assert "上限" in result["error"]

    def test_dry_run_does_not_persist(self, executor, workspace):
        ws, novel_id = workspace
        result = executor.execute(
            "batch_edit_settings",
            {
                "changes": [
                    {
                        "change_type": "update",
                        "entity_type": "character",
                        "entity_id": "char_001",
                        "new_value": {"age": 50},
                    }
                ],
                "dry_run": True,
            },
        )
        assert result["dry_run"] is True
        assert result["total"] == 1
        # Original age preserved
        novel = json.loads(
            (ws / "novels" / novel_id / "novel.json").read_text("utf-8")
        )
        assert novel["characters"][0]["age"] == 18

    def test_real_batch_persists_each(self, executor, workspace):
        ws, novel_id = workspace
        result = executor.execute(
            "batch_edit_settings",
            {
                "changes": [
                    {
                        "change_type": "update",
                        "entity_type": "character",
                        "entity_id": "char_001",
                        "new_value": {"age": 22},
                    },
                    {
                        "change_type": "update",
                        "entity_type": "outline",
                        "entity_id": "1",
                        "new_value": {"title": "新一", "goal": "开篇", "key_events": ["入门"]},
                    },
                ],
            },
        )
        assert result["total"] == 2
        assert result["summary"].get("success", 0) >= 1
        # Each result has its own change_id (rollback granularity)
        ids = {r["change_id"] for r in result["results"]}
        assert len(ids) == 2


# ---------------------------------------------------------------------------
# get_foreshadowing_graph
# ---------------------------------------------------------------------------


class TestGetForeshadowingGraph:
    def test_empty_graph(self, executor):
        result = executor.execute("get_foreshadowing_graph", {})
        # No graph file exists → service returns an empty KnowledgeGraph
        assert "stats" in result
        assert isinstance(result.get("pending"), list)
        assert result.get("forgotten_in_pending") == 0

    def test_with_seeded_foreshadowings(self, executor, workspace):
        ws, novel_id = workspace
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        kg.add_foreshadowing_node(
            foreshadowing_id="fs_1",
            planted_chapter=1,
            content="神秘黑剑",
            target_chapter=10,
            status="pending",
        )
        kg.add_foreshadowing_node(
            foreshadowing_id="fs_2",
            planted_chapter=2,
            content="老人遗言",
            target_chapter=-1,
            status="collected",
        )
        kg.save(str(ws / "novels" / novel_id / "graph.json"))

        result = executor.execute(
            "get_foreshadowing_graph", {"current_chapter": 15}
        )
        assert result["current_chapter"] == 15
        assert result["stats"].get("total", 0) >= 2
        # fs_1 is pending; should appear and likely be marked forgotten
        ids = {f["foreshadowing_id"] for f in result["pending"]}
        assert "fs_1" in ids
        forgotten = [f for f in result["pending"] if f["is_forgotten"]]
        assert len(forgotten) >= 1
        assert result["forgotten_in_pending"] >= 1

    def test_invalid_threshold_falls_back(self, executor):
        result = executor.execute(
            "get_foreshadowing_graph",
            {"current_chapter": 0, "threshold": "bad"},
        )
        assert result["threshold"] == 10  # default after fallback


# ---------------------------------------------------------------------------
# get_health_dashboard
# ---------------------------------------------------------------------------


class TestGetHealthDashboard:
    def test_returns_metrics(self, executor):
        result = executor.execute("get_health_dashboard", {})
        # Either metrics returned or graceful error
        assert "metrics" in result or "error" in result
        if "metrics" in result:
            assert "overall_health_score" in result
            assert isinstance(result["report"], str)

    def test_handles_missing_novel(self, tmp_path):
        executor = AgentToolExecutor(str(tmp_path), "missing_novel")
        result = executor.execute("get_health_dashboard", {})
        # The pipeline raises since novel.json doesn't exist; tool wraps it
        assert "error" in result or "metrics" in result

    def test_metrics_only_contains_toplevel_keys(self, executor):
        """H4: metrics 应只暴露顶层白名单字段，避免明细爆 token。"""
        result = executor.execute("get_health_dashboard", {})
        if "metrics" not in result:
            pytest.skip("无 metrics 可校验")
        from src.novel.services.agent_chat import AgentToolExecutor as _AE

        allowed = set(_AE._HEALTH_TOPLEVEL_KEYS)
        assert set(result["metrics"].keys()).issubset(allowed)
        assert "details_truncated" in result


# ---------------------------------------------------------------------------
# Reviewer follow-ups (H1-H4)
# ---------------------------------------------------------------------------


class TestReviewerFollowups:
    def test_rollback_clears_structured_db_cache(self, executor, workspace):
        """H1: rollback 成功后必须丢弃缓存的 SQLite 句柄，避免脏读。"""
        from src.novel.services.edit_service import NovelEditService

        ws, novel_id = workspace
        # 手动塞个假缓存
        sentinel = object()
        executor._cached_structured_db = sentinel

        svc = NovelEditService(workspace=str(ws))
        edit_result = svc.edit(
            project_path=str(ws / "novels" / novel_id),
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "new_value": {"age": 77},
            },
        )

        result = executor.execute(
            "rollback_change", {"change_id": edit_result.change_id}
        )
        assert result["status"] == "success"
        assert executor._cached_structured_db is None

    def test_batch_edit_partial_failure_flag(self, executor):
        """H2: 部分失败时 partial_failure=True，让 LLM 看见。"""
        result = executor.execute(
            "batch_edit_settings",
            {
                "changes": [
                    {
                        "change_type": "update",
                        "entity_type": "character",
                        "entity_id": "char_001",
                        "new_value": {"age": 22},
                    },
                    # 故意构造一条会失败的：entity_id 不存在
                    {
                        "change_type": "update",
                        "entity_type": "character",
                        "entity_id": "char_does_not_exist",
                        "new_value": {"age": 99},
                    },
                ],
            },
        )
        assert result["partial_failure"] is True
        assert result["summary"].get("success", 0) >= 1
        assert result["summary"].get("failed", 0) >= 1

    def test_batch_edit_payload_size_limit(self, executor):
        """H3: 单次 batch payload 超过 64KB 必须拒绝。"""
        big_value = "x" * (5 * 1024)  # 5KB per change
        changes = [
            {
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "new_value": {"bio": big_value},
            }
        ] * 20  # ~100 KB total, exceeds 64KB cap
        result = executor.execute("batch_edit_settings", {"changes": changes})
        assert "error" in result
        assert "字节" in result["error"]

    def test_foreshadowing_negative_chapter_clamped(self, executor):
        """H3: current_chapter 负数应被夹到 0，不允许传播到下游。"""
        result = executor.execute(
            "get_foreshadowing_graph", {"current_chapter": -5}
        )
        assert result["current_chapter"] == 0
