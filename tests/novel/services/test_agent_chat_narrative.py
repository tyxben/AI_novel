"""Tests for narrative control tools in Agent Chat."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.novel.services.agent_chat import AgentToolExecutor, TOOLS, _tools_description


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temp workspace with a fake novel project."""
    novel_dir = tmp_path / "novels" / "novel_test"
    novel_dir.mkdir(parents=True)

    novel_json = {
        "novel_id": "novel_test",
        "title": "测试小说",
        "genre": "玄幻",
        "status": "generating",
        "current_chapter": 5,
        "target_words": 50000,
        "outline": {
            "chapters": [
                {
                    "chapter_number": i,
                    "title": f"第{i}章",
                    "chapter_brief": {
                        "main_conflict": f"第{i}章的主冲突",
                        "payoff": f"第{i}章的爽点",
                        "character_arc_step": f"角色成长{i}",
                    } if i <= 3 else {},
                }
                for i in range(1, 11)
            ],
            "story_units": [
                {
                    "arc_id": "arc_1",
                    "volume_id": "1",
                    "name": "起源篇",
                    "chapters": [1, 2, 3, 4],
                    "phase": "escalation",
                    "status": "in_progress",
                    "completion_rate": 0.5,
                    "hook": "主角觉醒",
                    "residual_question": "师父为何消失？",
                },
                {
                    "arc_id": "arc_2",
                    "volume_id": "2",
                    "name": "试炼篇",
                    "chapters": [5, 6, 7],
                    "phase": "setup",
                    "status": "planning",
                    "completion_rate": 0.0,
                    "hook": "进入试炼场",
                    "residual_question": "试炼的真正目的是什么？",
                },
            ],
        },
        "characters": [{"name": "张三", "role": "protagonist"}],
    }
    (novel_dir / "novel.json").write_text(
        json.dumps(novel_json, ensure_ascii=False), encoding="utf-8"
    )

    # Chapters directory with some chapter JSON files
    chapters_dir = novel_dir / "chapters"
    chapters_dir.mkdir()
    for ch_num in [1, 2, 3]:
        ch_path = chapters_dir / f"chapter_{ch_num:03d}.json"
        ch_path.write_text(
            json.dumps(
                {
                    "chapter_number": ch_num,
                    "title": f"第{ch_num}章",
                    "full_text": f"这是第{ch_num}章的正文内容。" * 50,
                    "word_count": 500,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    return tmp_path


@pytest.fixture
def executor(tmp_workspace):
    """Create an AgentToolExecutor pointing at the temp workspace."""
    return AgentToolExecutor(workspace=str(tmp_workspace), novel_id="novel_test")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


class TestToolDefinitions:
    """Verify new tools are registered in the TOOLS list."""

    def test_new_tools_present(self):
        names = {t["name"] for t in TOOLS}
        assert "get_narrative_debts" in names
        assert "manage_debt" in names
        assert "get_story_arcs" in names
        assert "get_chapter_brief" in names
        assert "get_knowledge_graph" in names
        assert "get_narrative_overview" in names

    def test_total_tool_count(self):
        # 9 original + 6 narrative + 1 rebuild = 16
        assert len(TOOLS) == 16

    def test_tools_description_includes_new(self):
        desc = _tools_description()
        assert "get_narrative_debts" in desc
        assert "manage_debt" in desc
        assert "get_story_arcs" in desc
        assert "get_chapter_brief" in desc
        assert "get_knowledge_graph" in desc
        assert "get_narrative_overview" in desc


# ---------------------------------------------------------------------------
# get_narrative_debts
# ---------------------------------------------------------------------------


class TestGetNarrativeDebts:
    def test_no_debts(self, executor):
        """When no memory.db exists, tracker uses in-memory store — empty."""
        result = executor.execute("get_narrative_debts", {})
        assert result["total"] == 0
        assert result["debts"] == []
        assert "statistics" in result

    def test_with_debts_in_memory(self, executor):
        """Add debts to in-memory tracker, then query them."""
        tracker = executor._get_obligation_tracker()
        assert tracker is not None
        tracker.add_debt(
            debt_id="debt_1",
            source_chapter=3,
            debt_type="must_pay_next",
            description="主角答应师妹明天一起探索密林",
        )
        tracker.add_debt(
            debt_id="debt_2",
            source_chapter=5,
            debt_type="long_tail_payoff",
            description="神秘老人留下的预言",
        )

        # Patch _get_obligation_tracker to return our populated tracker
        with patch.object(executor, "_get_obligation_tracker", return_value=tracker):
            result = executor.execute("get_narrative_debts", {})

        assert result["total"] == 2
        assert len(result["debts"]) == 2

    def test_filter_by_status(self, executor):
        tracker = executor._get_obligation_tracker()
        tracker.add_debt(
            debt_id="d1", source_chapter=1,
            debt_type="must_pay_next", description="pending debt",
        )
        tracker.add_debt(
            debt_id="d2", source_chapter=2,
            debt_type="pay_within_3", description="will be fulfilled",
        )
        tracker.mark_debt_fulfilled("d2", chapter_num=4, note="done")

        with patch.object(executor, "_get_obligation_tracker", return_value=tracker):
            result_pending = executor.execute(
                "get_narrative_debts", {"status": "pending"}
            )
            result_fulfilled = executor.execute(
                "get_narrative_debts", {"status": "fulfilled"}
            )

        assert result_pending["total"] == 1
        assert result_pending["debts"][0]["debt_id"] == "d1"

        assert result_fulfilled["total"] == 1
        assert result_fulfilled["debts"][0]["debt_id"] == "d2"

    def test_filter_by_chapter(self, executor):
        tracker = executor._get_obligation_tracker()
        tracker.add_debt(
            debt_id="d_ch3", source_chapter=3,
            debt_type="must_pay_next", description="from ch3",
        )
        tracker.add_debt(
            debt_id="d_ch5", source_chapter=5,
            debt_type="pay_within_3", description="from ch5",
            target_chapter=8,
        )

        with patch.object(executor, "_get_obligation_tracker", return_value=tracker):
            result = executor.execute(
                "get_narrative_debts", {"chapter": 3}
            )

        assert result["total"] == 1
        assert result["debts"][0]["debt_id"] == "d_ch3"

    def test_filter_by_target_chapter(self, executor):
        tracker = executor._get_obligation_tracker()
        tracker.add_debt(
            debt_id="d_target", source_chapter=2,
            debt_type="pay_within_3", description="targets ch5",
            target_chapter=5,
        )

        with patch.object(executor, "_get_obligation_tracker", return_value=tracker):
            result = executor.execute(
                "get_narrative_debts", {"chapter": 5}
            )

        assert result["total"] == 1
        assert result["debts"][0]["debt_id"] == "d_target"

    def test_tracker_none_returns_error(self, executor):
        with patch.object(executor, "_get_obligation_tracker", return_value=None):
            result = executor.execute("get_narrative_debts", {})
        assert "error" in result
        assert result["debts"] == []


# ---------------------------------------------------------------------------
# manage_debt
# ---------------------------------------------------------------------------


class TestManageDebt:
    def test_add_debt(self, executor):
        tracker = executor._get_obligation_tracker()
        with patch.object(executor, "_get_obligation_tracker", return_value=tracker):
            result = executor.execute("manage_debt", {
                "action": "add",
                "description": "新增的叙事债务",
                "source_chapter": 3,
                "debt_type": "must_pay_next",
            })

        assert result["status"] == "added"
        assert "debt_id" in result
        assert result["description"] == "新增的叙事债务"

        # Verify it was actually added
        assert len(tracker._mem_store) == 1

    def test_add_debt_default_type(self, executor):
        tracker = executor._get_obligation_tracker()
        with patch.object(executor, "_get_obligation_tracker", return_value=tracker):
            result = executor.execute("manage_debt", {
                "action": "add",
                "description": "默认类型债务",
                "source_chapter": 1,
            })

        assert result["status"] == "added"
        # Default type should be pay_within_3
        debt = list(tracker._mem_store.values())[0]
        assert debt["type"] == "pay_within_3"

    def test_add_debt_missing_fields(self, executor):
        tracker = executor._get_obligation_tracker()
        with patch.object(executor, "_get_obligation_tracker", return_value=tracker):
            result = executor.execute("manage_debt", {
                "action": "add",
            })
        assert "error" in result

    def test_fulfill_debt(self, executor):
        tracker = executor._get_obligation_tracker()
        tracker.add_debt(
            debt_id="to_fulfill",
            source_chapter=1,
            debt_type="must_pay_next",
            description="需要完成的债务",
        )

        with patch.object(executor, "_get_obligation_tracker", return_value=tracker):
            result = executor.execute("manage_debt", {
                "action": "fulfill",
                "debt_id": "to_fulfill",
            })

        assert result["status"] == "fulfilled"
        assert tracker._mem_store["to_fulfill"]["status"] == "fulfilled"

    def test_fulfill_missing_id(self, executor):
        tracker = executor._get_obligation_tracker()
        with patch.object(executor, "_get_obligation_tracker", return_value=tracker):
            result = executor.execute("manage_debt", {
                "action": "fulfill",
            })
        assert "error" in result

    def test_escalate(self, executor):
        tracker = executor._get_obligation_tracker()
        tracker.add_debt(
            debt_id="escalate_me",
            source_chapter=1,
            debt_type="must_pay_next",
            description="should be escalated",
        )

        with patch.object(executor, "_get_obligation_tracker", return_value=tracker):
            result = executor.execute("manage_debt", {
                "action": "escalate",
                "debt_id": "escalate_me",
            })

        assert result["status"] == "escalated"
        assert result["total_escalated"] >= 1

    def test_escalate_missing_id(self, executor):
        tracker = executor._get_obligation_tracker()
        with patch.object(executor, "_get_obligation_tracker", return_value=tracker):
            result = executor.execute("manage_debt", {
                "action": "escalate",
            })
        assert "error" in result

    def test_unknown_action(self, executor):
        tracker = executor._get_obligation_tracker()
        with patch.object(executor, "_get_obligation_tracker", return_value=tracker):
            result = executor.execute("manage_debt", {
                "action": "unknown_action",
            })
        assert "error" in result
        assert "未知操作" in result["error"]

    def test_tracker_none(self, executor):
        with patch.object(executor, "_get_obligation_tracker", return_value=None):
            result = executor.execute("manage_debt", {
                "action": "add",
                "description": "test",
                "source_chapter": 1,
            })
        assert "error" in result


# ---------------------------------------------------------------------------
# get_story_arcs
# ---------------------------------------------------------------------------


class TestGetStoryArcs:
    def test_arcs_from_outline(self, executor):
        """Story units come from novel.json outline.story_units."""
        result = executor.execute("get_story_arcs", {})
        assert result["total"] == 2
        assert result["arcs"][0]["name"] == "起源篇"
        assert result["arcs"][1]["name"] == "试炼篇"

    def test_arcs_filter_by_volume(self, executor):
        result = executor.execute("get_story_arcs", {"volume": 1})
        assert result["total"] == 1
        assert result["arcs"][0]["name"] == "起源篇"

    def test_arcs_filter_nonexistent_volume(self, executor):
        result = executor.execute("get_story_arcs", {"volume": 99})
        assert result["total"] == 0
        assert result["arcs"] == []

    def test_arcs_from_arcs_json(self, tmp_workspace):
        """When DB and outline have no arcs, fall back to arcs.json."""
        novel_dir = tmp_workspace / "novels" / "novel_arcs"
        novel_dir.mkdir(parents=True)
        (novel_dir / "novel.json").write_text(
            json.dumps({"outline": {"chapters": []}}, ensure_ascii=False),
            encoding="utf-8",
        )
        arcs_data = [
            {
                "arc_id": "a1",
                "volume_id": "1",
                "name": "序章",
                "chapters": [1, 2, 3],
                "phase": "setup",
                "status": "active",
                "completion_rate": 0.3,
                "hook": "hook1",
                "residual_question": "q1",
            }
        ]
        (novel_dir / "arcs.json").write_text(
            json.dumps(arcs_data, ensure_ascii=False), encoding="utf-8"
        )

        ex = AgentToolExecutor(str(tmp_workspace), "novel_arcs")
        result = ex.execute("get_story_arcs", {})
        assert result["total"] == 1
        assert result["arcs"][0]["name"] == "序章"

    def test_empty_arcs(self, tmp_workspace):
        """Novel with no story_units and no arcs.json."""
        novel_dir = tmp_workspace / "novels" / "novel_empty"
        novel_dir.mkdir(parents=True)
        (novel_dir / "novel.json").write_text(
            json.dumps({"outline": {"chapters": []}}, ensure_ascii=False),
            encoding="utf-8",
        )

        ex = AgentToolExecutor(str(tmp_workspace), "novel_empty")
        result = ex.execute("get_story_arcs", {})
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# get_chapter_brief
# ---------------------------------------------------------------------------


class TestGetChapterBrief:
    def test_get_brief_with_text(self, executor):
        result = executor.execute("get_chapter_brief", {"chapter_number": 1})
        assert result["chapter_number"] == 1
        assert "chapter_brief" in result
        assert result["chapter_brief"]["main_conflict"] == "第1章的主冲突"
        assert result["has_text"] is True
        assert "brief_items" in result

    def test_get_brief_no_text(self, executor):
        """Chapter in outline but not written yet."""
        result = executor.execute("get_chapter_brief", {"chapter_number": 5})
        assert result["chapter_number"] == 5
        assert result["has_text"] is False

    def test_get_brief_not_in_outline(self, executor):
        result = executor.execute("get_chapter_brief", {"chapter_number": 99})
        assert "error" in result

    def test_get_brief_empty_brief(self, executor):
        """Chapter 5 has empty chapter_brief dict."""
        result = executor.execute("get_chapter_brief", {"chapter_number": 5})
        assert result["chapter_brief"] == {}

    def test_novel_not_found(self, tmp_workspace):
        ex = AgentToolExecutor(str(tmp_workspace), "nonexistent_novel")
        result = ex.execute("get_chapter_brief", {"chapter_number": 1})
        assert "error" in result


# ---------------------------------------------------------------------------
# get_knowledge_graph
# ---------------------------------------------------------------------------


class TestGetKnowledgeGraph:
    def test_empty_graph(self, executor):
        """No graph.json exists — returns empty KnowledgeGraph."""
        result = executor.execute("get_knowledge_graph", {})
        assert result["characters"] == []
        assert result["total_edges"] == 0

    def test_graph_with_data(self, executor, tmp_workspace):
        """Create a graph.json and load it."""
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        kg.add_character("char_1", "张三", role="protagonist")
        kg.add_character("char_2", "李四", role="mentor")
        kg.add_relationship("char_1", "char_2", "师徒", intensity=8, chapter=1)
        kg.add_faction("faction_1", "天剑宗")
        kg.add_affiliation("char_1", "faction_1", role="弟子", chapter=1)

        graph_path = tmp_workspace / "novels" / "novel_test" / "graph.json"
        kg.save(str(graph_path))

        result = executor.execute("get_knowledge_graph", {})
        assert len(result["characters"]) == 2
        assert len(result["factions"]) == 1
        assert result["total_edges"] >= 2

    def test_graph_filter_by_character(self, executor, tmp_workspace):
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        kg.add_character("c1", "张三")
        kg.add_character("c2", "李四")
        kg.add_character("c3", "王五")
        kg.add_relationship("c1", "c2", "朋友", intensity=5, chapter=1)
        kg.add_relationship("c1", "c3", "对手", intensity=7, chapter=2)

        graph_path = tmp_workspace / "novels" / "novel_test" / "graph.json"
        kg.save(str(graph_path))

        result = executor.execute("get_knowledge_graph", {"character": "张三"})
        assert result["character"] == "张三"
        assert len(result["edges"]) == 2
        # Should include all related nodes
        node_ids = {n["id"] for n in result["nodes"]}
        assert "c1" in node_ids
        assert "c2" in node_ids
        assert "c3" in node_ids

    def test_graph_character_not_found(self, executor):
        result = executor.execute("get_knowledge_graph", {"character": "不存在"})
        assert "error" in result
        assert result["nodes"] == []

    def test_graph_none(self, executor):
        with patch.object(executor, "_get_knowledge_graph", return_value=None):
            result = executor.execute("get_knowledge_graph", {})
        assert "error" in result


# ---------------------------------------------------------------------------
# get_narrative_overview
# ---------------------------------------------------------------------------


class TestGetNarrativeOverview:
    def test_overview_basic(self, executor):
        result = executor.execute("get_narrative_overview", {})
        assert "debt_statistics" in result
        assert "arc_progress" in result
        assert "novel_progress" in result
        assert "knowledge_graph" in result

    def test_overview_novel_progress(self, executor):
        result = executor.execute("get_narrative_overview", {})
        np = result["novel_progress"]
        assert np["current_chapter"] == 5
        assert np["total_chapters"] == 10
        assert np["completion_pct"] == 50.0

    def test_overview_arc_progress(self, executor):
        result = executor.execute("get_narrative_overview", {})
        ap = result["arc_progress"]
        assert ap["total"] == 2
        assert ap["in_progress"] == 1
        assert ap["planning"] == 1

    def test_overview_with_debts(self, executor):
        tracker = executor._get_obligation_tracker()
        tracker.add_debt(
            debt_id="ov_d1", source_chapter=1,
            debt_type="must_pay_next", description="test debt",
        )

        with patch.object(executor, "_get_obligation_tracker", return_value=tracker):
            result = executor.execute("get_narrative_overview", {})

        ds = result["debt_statistics"]
        assert ds["pending_count"] == 1

    def test_overview_nonexistent_novel(self, tmp_workspace):
        ex = AgentToolExecutor(str(tmp_workspace), "nonexistent")
        result = ex.execute("get_narrative_overview", {})
        assert result["novel_progress"]["total_chapters"] == 0
        assert result["arc_progress"]["total"] == 0


# ---------------------------------------------------------------------------
# Helper methods
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_get_obligation_tracker_no_db(self, executor):
        """When no memory.db exists, returns in-memory tracker."""
        tracker = executor._get_obligation_tracker()
        assert tracker is not None
        assert tracker._mem_store is not None  # in-memory mode

    def test_get_obligation_tracker_with_db(self, executor, tmp_workspace):
        """When memory.db exists, returns DB-backed tracker."""
        from src.novel.storage.structured_db import StructuredDB

        db_path = tmp_workspace / "novels" / "novel_test" / "memory.db"
        db = StructuredDB(db_path)
        db.close()
        # Now memory.db exists
        tracker = executor._get_obligation_tracker()
        assert tracker is not None
        assert tracker.db is not None

    def test_get_structured_db_no_file(self, executor):
        assert executor._get_structured_db() is None

    def test_get_structured_db_with_file(self, executor, tmp_workspace):
        from src.novel.storage.structured_db import StructuredDB

        db_path = tmp_workspace / "novels" / "novel_test" / "memory.db"
        db = StructuredDB(db_path)
        db.close()
        result = executor._get_structured_db()
        assert result is not None

    def test_get_knowledge_graph_empty(self, executor):
        kg = executor._get_knowledge_graph()
        assert kg is not None
        assert kg.graph.number_of_nodes() == 0

    def test_get_knowledge_graph_from_file(self, executor, tmp_workspace):
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        kg.add_character("c1", "TestChar")
        graph_path = tmp_workspace / "novels" / "novel_test" / "graph.json"
        kg.save(str(graph_path))

        loaded = executor._get_knowledge_graph()
        assert loaded is not None
        assert loaded.graph.number_of_nodes() == 1


# ---------------------------------------------------------------------------
# Integration: execute dispatcher
# ---------------------------------------------------------------------------


class TestExecuteDispatcher:
    def test_unknown_tool(self, executor):
        result = executor.execute("nonexistent_tool", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_tool_exception_handling(self, executor):
        """Tool methods that raise exceptions are caught."""
        with patch.object(
            executor, "_tool_get_narrative_debts",
            side_effect=RuntimeError("boom"),
        ):
            result = executor.execute("get_narrative_debts", {})
        assert "error" in result
        assert "boom" in result["error"]
