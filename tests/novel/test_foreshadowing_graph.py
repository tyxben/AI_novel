"""Tests for P1 Foreshadowing Graph: models, KnowledgeGraph extensions,
ForeshadowingService, and ContinuityService integration."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.novel.models.foreshadowing import (
    DetailEntry,
    Foreshadowing,
    ForeshadowingEdge,
    ForeshadowingStatus,
)
from src.novel.services.foreshadowing_service import ForeshadowingService
from src.novel.storage.knowledge_graph import KnowledgeGraph


# =====================================================================
# A. Pydantic model tests
# =====================================================================


class TestForeshadowingEdge:
    def test_defaults(self):
        edge = ForeshadowingEdge(
            from_foreshadowing_id="fs1",
            to_foreshadowing_id="fs2",
            relation_type="trigger",
        )
        assert edge.edge_id  # auto-generated UUID
        assert edge.from_foreshadowing_id == "fs1"
        assert edge.to_foreshadowing_id == "fs2"
        assert edge.relation_type == "trigger"
        assert edge.description == ""

    def test_all_relation_types(self):
        for rtype in ("trigger", "collect", "parallel", "conflict"):
            edge = ForeshadowingEdge(
                from_foreshadowing_id="a",
                to_foreshadowing_id="b",
                relation_type=rtype,
            )
            assert edge.relation_type == rtype

    def test_invalid_relation_type_rejected(self):
        with pytest.raises(Exception):
            ForeshadowingEdge(
                from_foreshadowing_id="a",
                to_foreshadowing_id="b",
                relation_type="invalid",
            )

    def test_with_description(self):
        edge = ForeshadowingEdge(
            from_foreshadowing_id="a",
            to_foreshadowing_id="b",
            relation_type="collect",
            description="回收伏笔",
        )
        assert edge.description == "回收伏笔"


class TestForeshadowingStatus:
    def test_required_fields(self):
        status = ForeshadowingStatus(
            foreshadowing_id="fs1",
            planted_chapter=3,
            target_chapter=10,
            status="pending",
            chapters_since_plant=7,
        )
        assert status.foreshadowing_id == "fs1"
        assert status.planted_chapter == 3
        assert status.target_chapter == 10
        assert status.status == "pending"
        assert status.chapters_since_plant == 7
        assert status.last_mentioned_chapter is None
        assert status.is_forgotten is False
        assert status.content == ""

    def test_with_all_fields(self):
        status = ForeshadowingStatus(
            foreshadowing_id="fs2",
            planted_chapter=1,
            target_chapter=20,
            status="collected",
            content="伏笔内容",
            chapters_since_plant=19,
            last_mentioned_chapter=15,
            is_forgotten=True,
        )
        assert status.content == "伏笔内容"
        assert status.last_mentioned_chapter == 15
        assert status.is_forgotten is True

    def test_invalid_status_rejected(self):
        with pytest.raises(Exception):
            ForeshadowingStatus(
                foreshadowing_id="fs1",
                planted_chapter=1,
                target_chapter=5,
                status="unknown",
                chapters_since_plant=4,
            )


# =====================================================================
# B. KnowledgeGraph foreshadowing extension tests
# =====================================================================


class TestKnowledgeGraphForeshadowing:
    def setup_method(self):
        self.kg = KnowledgeGraph()

    def test_add_foreshadowing_node(self):
        self.kg.add_foreshadowing_node(
            "fs1", planted_chapter=1, content="神秘珠子"
        )
        node = self.kg.get_node("fs1")
        assert node is not None
        assert node["type"] == "foreshadowing"
        assert node["planted_chapter"] == 1
        assert node["content"] == "神秘珠子"
        assert node["target_chapter"] == -1
        assert node["status"] == "pending"
        assert node["last_mentioned_chapter"] == 1

    def test_add_foreshadowing_node_with_target(self):
        self.kg.add_foreshadowing_node(
            "fs2",
            planted_chapter=3,
            content="封印线索",
            target_chapter=15,
        )
        node = self.kg.get_node("fs2")
        assert node["target_chapter"] == 15

    def test_add_foreshadowing_node_custom_last_mentioned(self):
        self.kg.add_foreshadowing_node(
            "fs3",
            planted_chapter=1,
            content="old hint",
            last_mentioned_chapter=5,
        )
        node = self.kg.get_node("fs3")
        assert node["last_mentioned_chapter"] == 5

    def test_add_foreshadowing_node_extra_attrs(self):
        self.kg.add_foreshadowing_node(
            "fs4",
            planted_chapter=2,
            content="extra",
            importance="high",
        )
        node = self.kg.get_node("fs4")
        assert node["importance"] == "high"

    def test_add_foreshadowing_edge(self):
        self.kg.add_foreshadowing_node("fs_a", planted_chapter=1, content="a")
        self.kg.add_foreshadowing_node("fs_b", planted_chapter=2, content="b")
        self.kg.add_foreshadowing_edge("fs_a", "fs_b", "trigger", chapter=2)

        edges = list(self.kg.graph.edges(data=True, keys=True))
        assert len(edges) == 1
        _, _, key, data = edges[0]
        assert data["edge_type"] == "foreshadowing_relation"
        assert data["relation_type"] == "trigger"
        assert data["chapter"] == 2

    def test_get_pending_foreshadowings_empty(self):
        result = self.kg.get_pending_foreshadowings(10)
        assert result == []

    def test_get_pending_foreshadowings_filters_non_foreshadowing(self):
        self.kg.add_character("char1", "角色A")
        self.kg.add_foreshadowing_node("fs1", planted_chapter=1, content="伏笔")
        result = self.kg.get_pending_foreshadowings(5)
        assert len(result) == 1
        assert result[0]["foreshadowing_id"] == "fs1"

    def test_get_pending_foreshadowings_filters_collected(self):
        self.kg.add_foreshadowing_node("fs1", planted_chapter=1, content="A")
        self.kg.add_foreshadowing_node("fs2", planted_chapter=2, content="B")
        self.kg.mark_foreshadowing_collected("fs1", 5)

        result = self.kg.get_pending_foreshadowings(6)
        assert len(result) == 1
        assert result[0]["foreshadowing_id"] == "fs2"

    def test_get_pending_foreshadowings_forgotten_flag(self):
        self.kg.add_foreshadowing_node("fs1", planted_chapter=1, content="old")
        self.kg.add_foreshadowing_node(
            "fs2", planted_chapter=8, content="recent"
        )
        result = self.kg.get_pending_foreshadowings(12)
        # fs1: last_mentioned=1, current=12, diff=11 >= 10 -> forgotten
        # fs2: last_mentioned=8, current=12, diff=4 < 10 -> not forgotten
        fs1 = next(r for r in result if r["foreshadowing_id"] == "fs1")
        fs2 = next(r for r in result if r["foreshadowing_id"] == "fs2")
        assert fs1["is_forgotten"] is True
        assert fs2["is_forgotten"] is False

    def test_get_pending_foreshadowings_sort_order(self):
        # forgotten items first, then by chapters_since_plant desc
        self.kg.add_foreshadowing_node("fs_old", planted_chapter=1, content="old")
        self.kg.add_foreshadowing_node("fs_mid", planted_chapter=5, content="mid")
        self.kg.add_foreshadowing_node(
            "fs_recent", planted_chapter=10, content="recent"
        )

        result = self.kg.get_pending_foreshadowings(15)
        ids = [r["foreshadowing_id"] for r in result]
        # fs_old: forgotten=True (14 chapters), fs_mid: forgotten=True (10 chapters)
        # fs_recent: forgotten=False (5 chapters)
        assert ids[0] == "fs_old"
        assert ids[1] == "fs_mid"
        assert ids[2] == "fs_recent"

    def test_mark_foreshadowing_collected(self):
        self.kg.add_foreshadowing_node("fs1", planted_chapter=1, content="test")
        self.kg.mark_foreshadowing_collected("fs1", 5)
        node = self.kg.get_node("fs1")
        assert node["status"] == "collected"
        assert node["collected_chapter"] == 5

    def test_mark_foreshadowing_collected_nonexistent(self):
        # Should not raise
        self.kg.mark_foreshadowing_collected("nonexistent", 5)

    def test_update_foreshadowing_mention(self):
        self.kg.add_foreshadowing_node("fs1", planted_chapter=1, content="test")
        self.kg.update_foreshadowing_mention("fs1", 7)
        node = self.kg.get_node("fs1")
        assert node["last_mentioned_chapter"] == 7

    def test_update_foreshadowing_mention_nonexistent(self):
        # Should not raise
        self.kg.update_foreshadowing_mention("nonexistent", 7)

    def test_get_foreshadowing_stats(self):
        self.kg.add_foreshadowing_node("fs1", planted_chapter=1, content="A")
        self.kg.add_foreshadowing_node("fs2", planted_chapter=2, content="B")
        self.kg.add_foreshadowing_node("fs3", planted_chapter=3, content="C")
        self.kg.mark_foreshadowing_collected("fs1", 5)
        # Manually mark abandoned
        self.kg.graph.nodes["fs3"]["status"] = "abandoned"

        stats = self.kg.get_foreshadowing_stats()
        assert stats["total"] == 3
        assert stats["collected"] == 1
        assert stats["pending"] == 1
        assert stats["abandoned"] == 1

    def test_get_foreshadowing_stats_empty(self):
        stats = self.kg.get_foreshadowing_stats()
        assert stats["total"] == 0
        assert stats["collected"] == 0
        assert stats["pending"] == 0
        assert stats["abandoned"] == 0

    def test_get_nodes_by_type_foreshadowing(self):
        self.kg.add_foreshadowing_node("fs1", planted_chapter=1, content="test")
        self.kg.add_character("char1", "角色")
        nodes = self.kg.get_nodes_by_type("foreshadowing")
        assert len(nodes) == 1
        assert nodes[0]["id"] == "fs1"

    def test_save_load_preserves_foreshadowing(self):
        self.kg.add_foreshadowing_node(
            "fs1", planted_chapter=1, content="珠子", target_chapter=10
        )
        self.kg.add_foreshadowing_node(
            "fs2", planted_chapter=3, content="符文"
        )
        self.kg.mark_foreshadowing_collected("fs1", 8)
        self.kg.add_foreshadowing_edge("fs1", "collect_8", "collect", 8)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "kg.json")
            self.kg.save(path)

            kg2 = KnowledgeGraph.load(path)
            assert kg2.get_node("fs1")["status"] == "collected"
            assert kg2.get_node("fs2")["status"] == "pending"
            pending = kg2.get_pending_foreshadowings(10)
            assert len(pending) == 1
            assert pending[0]["foreshadowing_id"] == "fs2"


# =====================================================================
# C. ForeshadowingService tests
# =====================================================================


class TestForeshadowingService:
    def setup_method(self):
        self.kg = KnowledgeGraph()
        self.svc = ForeshadowingService(self.kg)

    def test_register_plants(self):
        brief = {
            "foreshadowing_plant": ["伏笔A", "伏笔B"],
        }
        count = self.svc.register_planned_foreshadowings(brief, 1)
        assert count == 2
        pending = self.kg.get_pending_foreshadowings(2)
        assert len(pending) == 2
        contents = {p["content"] for p in pending}
        assert "伏笔A" in contents
        assert "伏笔B" in contents

    def test_register_plant_string_not_list(self):
        """foreshadowing_plant can be a single string."""
        brief = {"foreshadowing_plant": "单个伏笔"}
        count = self.svc.register_planned_foreshadowings(brief, 1)
        assert count == 1

    def test_register_empty_brief(self):
        count = self.svc.register_planned_foreshadowings({}, 1)
        assert count == 0

    def test_register_with_none_values(self):
        brief = {
            "foreshadowing_plant": [None, "", "有效伏笔"],
            "foreshadowing_collect": [None],
        }
        count = self.svc.register_planned_foreshadowings(brief, 1)
        assert count == 1

    def test_register_collect_marks_collected(self):
        # First plant a foreshadowing
        self.kg.add_foreshadowing_node("fs1", planted_chapter=1, content="主角获得神秘宝剑")

        # Now collect it (similar description, SequenceMatcher >= 0.5)
        brief = {"foreshadowing_collect": ["主角使用神秘宝剑"]}
        self.svc.register_planned_foreshadowings(brief, 5)

        # Should be collected
        node = self.kg.get_node("fs1")
        assert node["status"] == "collected"
        assert node["collected_chapter"] == 5

    def test_register_collect_no_match(self):
        """When no pending foreshadowing matches, nothing happens."""
        self.kg.add_foreshadowing_node("fs1", planted_chapter=1, content="神秘珠子")
        brief = {"foreshadowing_collect": ["完全不相关的内容描述"]}
        self.svc.register_planned_foreshadowings(brief, 5)

        node = self.kg.get_node("fs1")
        assert node["status"] == "pending"

    def test_verify_plants_confirmed(self):
        text = "林辰拿起了那把神秘的宝剑，剑身上的符文闪烁着光芒。"
        result = self.svc.verify_foreshadowings_in_text(
            chapter_text=text,
            chapter_number=1,
            planned_plants=["神秘宝剑上的符文"],
            planned_collects=[],
        )
        assert len(result["plants_confirmed"]) == 1
        assert len(result["plants_missing"]) == 0

    def test_verify_plants_missing(self):
        text = "林辰在房间里静坐修炼。"
        result = self.svc.verify_foreshadowings_in_text(
            chapter_text=text,
            chapter_number=1,
            planned_plants=["神秘宝剑"],
            planned_collects=[],
        )
        assert len(result["plants_missing"]) == 1
        assert result["plants_missing"][0] == "神秘宝剑"

    def test_verify_collects_confirmed(self):
        text = "终于，林辰打开了那个神秘的盒子，里面是一枚戒指。"
        result = self.svc.verify_foreshadowings_in_text(
            chapter_text=text,
            chapter_number=5,
            planned_plants=[],
            planned_collects=["打开神秘盒子"],
        )
        assert len(result["collects_confirmed"]) == 1

    def test_verify_empty_lists(self):
        result = self.svc.verify_foreshadowings_in_text(
            chapter_text="some text",
            chapter_number=1,
            planned_plants=[],
            planned_collects=[],
        )
        assert result["plants_confirmed"] == []
        assert result["plants_missing"] == []
        assert result["collects_confirmed"] == []
        assert result["collects_missing"] == []

    def test_verify_skips_none_and_empty(self):
        result = self.svc.verify_foreshadowings_in_text(
            chapter_text="text",
            chapter_number=1,
            planned_plants=[None, "", "真实伏笔"],
            planned_collects=[None],
        )
        assert len(result["plants_missing"]) == 1
        assert result["plants_missing"][0] == "真实伏笔"

    def test_get_forgotten_foreshadowings(self):
        self.kg.add_foreshadowing_node("fs1", planted_chapter=1, content="old")
        self.kg.add_foreshadowing_node("fs2", planted_chapter=10, content="recent")

        forgotten = self.svc.get_forgotten_foreshadowings(current_chapter=15)
        # fs1: last_mentioned=1, diff=14 >= 10 -> forgotten
        # fs2: last_mentioned=10, diff=5 < 10 -> not forgotten
        assert len(forgotten) == 1
        assert forgotten[0]["foreshadowing_id"] == "fs1"

    def test_get_forgotten_custom_threshold(self):
        self.kg.add_foreshadowing_node("fs1", planted_chapter=1, content="old")
        forgotten = self.svc.get_forgotten_foreshadowings(
            current_chapter=5, threshold=3
        )
        # diff=4 >= 3 -> forgotten
        assert len(forgotten) == 1

    def test_find_matching_foreshadowing_above_threshold(self):
        self.kg.add_foreshadowing_node("fs1", planted_chapter=1, content="主角获得神秘宝剑")
        match = self.svc._find_matching_foreshadowing("主角的神秘宝剑")
        assert match is not None
        assert match["foreshadowing_id"] == "fs1"

    def test_find_matching_foreshadowing_below_threshold(self):
        self.kg.add_foreshadowing_node("fs1", planted_chapter=1, content="AAAA")
        match = self.svc._find_matching_foreshadowing("ZZZZ完全不同")
        assert match is None

    def test_find_matching_no_pending(self):
        match = self.svc._find_matching_foreshadowing("任何描述")
        assert match is None


class TestExtractKeywords:
    def test_with_punctuation(self):
        kw = ForeshadowingService._extract_keywords("主角、宝剑、符文")
        assert "主角" in kw
        assert "宝剑" in kw
        assert "符文" in kw

    def test_long_segment_generates_substrings(self):
        kw = ForeshadowingService._extract_keywords("主角获得神秘戒指")
        # Should have sub-keywords including "神秘", "戒指", "神秘戒指"
        assert any("戒指" in k for k in kw)
        assert any("神秘" in k for k in kw)

    def test_short_segment_stays_as_is(self):
        kw = ForeshadowingService._extract_keywords("宝剑")
        assert "宝剑" in kw

    def test_empty_string(self):
        kw = ForeshadowingService._extract_keywords("")
        assert kw == []

    def test_single_char_filtered(self):
        kw = ForeshadowingService._extract_keywords("我。你")
        # Single char segments should be filtered out
        assert all(len(k) >= 2 for k in kw)

    def test_stop_words_filtered(self):
        kw = ForeshadowingService._extract_keywords("一个，一些，但是，因为")
        assert "一个" not in kw
        assert "一些" not in kw

    def test_top_n_limit(self):
        kw = ForeshadowingService._extract_keywords(
            "主角获得了一把非常强大的神秘宝剑", top_n=3
        )
        assert len(kw) <= 3

    def test_top_n_zero_unlimited(self):
        kw = ForeshadowingService._extract_keywords(
            "主角获得了一把非常强大的神秘宝剑", top_n=0
        )
        # Should return all keywords (no limit)
        assert len(kw) > 3


# =====================================================================
# D. ContinuityService integration tests
# =====================================================================


class TestContinuityServiceForeshadowing:
    def test_generate_brief_injects_foreshadowings(self):
        from src.novel.services.continuity_service import ContinuityService

        kg = KnowledgeGraph()
        kg.add_foreshadowing_node("fs1", planted_chapter=1, content="神秘珠子")
        kg.add_foreshadowing_node("fs2", planted_chapter=8, content="新线索")

        svc = ContinuityService(knowledge_graph=kg)
        brief = svc.generate_brief(chapter_number=10)

        # Both should be in pending (neither forgotten at ch 10)
        pending = brief.get("pending_foreshadowings", [])
        forgotten = brief.get("forgotten_foreshadowings", [])
        assert len(pending) >= 1
        assert len(forgotten) == 0  # fs1 only 9 chapters away, not 10

    def test_generate_brief_forgotten_foreshadowings(self):
        from src.novel.services.continuity_service import ContinuityService

        kg = KnowledgeGraph()
        kg.add_foreshadowing_node("fs1", planted_chapter=1, content="远古伏笔")

        svc = ContinuityService(knowledge_graph=kg)
        brief = svc.generate_brief(chapter_number=15)

        forgotten = brief.get("forgotten_foreshadowings", [])
        assert len(forgotten) == 1
        assert forgotten[0]["content"] == "远古伏笔"

    def test_generate_brief_no_knowledge_graph(self):
        from src.novel.services.continuity_service import ContinuityService

        svc = ContinuityService()  # no knowledge_graph
        brief = svc.generate_brief(chapter_number=5)

        # Should degrade gracefully
        assert brief.get("pending_foreshadowings") is None or brief.get("pending_foreshadowings") == []
        assert brief.get("forgotten_foreshadowings") is None or brief.get("forgotten_foreshadowings") == []

    def test_format_for_prompt_forgotten(self):
        from src.novel.services.continuity_service import ContinuityService

        kg = KnowledgeGraph()
        kg.add_foreshadowing_node("fs1", planted_chapter=1, content="远古秘密")

        svc = ContinuityService(knowledge_graph=kg)
        brief = svc.generate_brief(chapter_number=15)
        prompt = svc.format_for_prompt(brief)

        assert "即将遗忘的伏笔" in prompt
        assert "远古秘密" in prompt
        assert "第1章埋设" in prompt

    def test_format_for_prompt_pending(self):
        from src.novel.services.continuity_service import ContinuityService

        kg = KnowledgeGraph()
        kg.add_foreshadowing_node(
            "fs1", planted_chapter=5, content="线索A", target_chapter=20
        )

        svc = ContinuityService(knowledge_graph=kg)
        brief = svc.generate_brief(chapter_number=10)
        prompt = svc.format_for_prompt(brief)

        assert "待回收伏笔" in prompt
        assert "线索A" in prompt
        assert "第20章" in prompt

    def test_format_for_prompt_no_foreshadowings(self):
        from src.novel.services.continuity_service import ContinuityService

        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=5)
        prompt = svc.format_for_prompt(brief)

        # No foreshadowing sections should appear
        assert "伏笔" not in prompt

    def test_format_for_prompt_pending_no_target(self):
        from src.novel.services.continuity_service import ContinuityService

        kg = KnowledgeGraph()
        kg.add_foreshadowing_node(
            "fs1", planted_chapter=5, content="无目标伏笔"
        )

        svc = ContinuityService(knowledge_graph=kg)
        brief = svc.generate_brief(chapter_number=10)
        prompt = svc.format_for_prompt(brief)

        assert "无目标伏笔" in prompt
        # target_chapter=-1, should NOT show "第-1章"
        assert "第-1章" not in prompt

    def test_limits_pending_and_forgotten(self):
        """Verify that pending is capped at 5 and forgotten at 3."""
        from src.novel.services.continuity_service import ContinuityService

        kg = KnowledgeGraph()
        # 10 forgotten foreshadowings
        for i in range(10):
            kg.add_foreshadowing_node(f"old_{i}", planted_chapter=1, content=f"旧伏笔{i}")
        # 10 normal foreshadowings
        for i in range(10):
            kg.add_foreshadowing_node(f"new_{i}", planted_chapter=45, content=f"新伏笔{i}")

        svc = ContinuityService(knowledge_graph=kg)
        brief = svc.generate_brief(chapter_number=50)

        assert len(brief.get("forgotten_foreshadowings", [])) <= 3
        assert len(brief.get("pending_foreshadowings", [])) <= 5
