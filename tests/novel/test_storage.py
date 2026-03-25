"""存储层完整测试 - StructuredDB / KnowledgeGraph / VectorStore / NovelMemory / FileManager"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.novel.models.foreshadowing import DetailEntry
from src.novel.models.memory import ChapterSummary, Fact


# ============================================================
# StructuredDB 测试
# ============================================================


class TestStructuredDB:
    """SQLite 结构化数据库测试"""

    @pytest.fixture()
    def db(self, tmp_path):
        from src.novel.storage.structured_db import StructuredDB

        db = StructuredDB(tmp_path / "test.db")
        yield db
        db.close()

    # --- character_states ---

    def test_insert_and_get_character_state(self, db):
        db.insert_character_state(
            character_id="char1",
            chapter=1,
            health="健康",
            location="长安城",
            power_level="筑基期",
            emotional_state="冷静",
        )
        result = db.get_character_state("char1", chapter=1)
        assert result is not None
        assert result["character_id"] == "char1"
        assert result["health"] == "健康"
        assert result["location"] == "长安城"
        assert result["power_level"] == "筑基期"
        assert result["emotional_state"] == "冷静"

    def test_get_latest_character_state(self, db):
        db.insert_character_state("char1", 1, health="健康")
        db.insert_character_state("char1", 5, health="重伤")
        result = db.get_character_state("char1")
        assert result is not None
        assert result["chapter"] == 5
        assert result["health"] == "重伤"

    def test_get_character_state_not_found(self, db):
        result = db.get_character_state("nonexistent")
        assert result is None

    def test_upsert_character_state(self, db):
        db.insert_character_state("char1", 1, health="健康")
        db.insert_character_state("char1", 1, health="轻伤")
        result = db.get_character_state("char1", 1)
        assert result["health"] == "轻伤"

    def test_get_character_history(self, db):
        db.insert_character_state("char1", 1, health="健康")
        db.insert_character_state("char1", 3, health="轻伤")
        db.insert_character_state("char1", 7, health="重伤")
        history = db.get_character_history("char1")
        assert len(history) == 3
        assert history[0]["chapter"] == 1
        assert history[2]["chapter"] == 7

    def test_get_character_history_empty(self, db):
        history = db.get_character_history("nonexistent")
        assert history == []

    # --- timeline ---

    def test_insert_and_get_timeline(self, db):
        db.insert_timeline(
            chapter=1,
            scene=1,
            absolute_time="1024年春天",
            relative_time="清晨",
            description="主角初到长安",
        )
        results = db.get_timeline(chapter=1)
        assert len(results) == 1
        assert results[0]["absolute_time"] == "1024年春天"
        assert results[0]["description"] == "主角初到长安"

    def test_get_timeline_all(self, db):
        db.insert_timeline(1, 1, description="事件1")
        db.insert_timeline(2, 1, description="事件2")
        db.insert_timeline(2, 2, description="事件3")
        results = db.get_timeline()
        assert len(results) == 3

    def test_upsert_timeline(self, db):
        db.insert_timeline(1, 1, description="旧描述")
        db.insert_timeline(1, 1, description="新描述")
        results = db.get_timeline(chapter=1)
        assert results[0]["description"] == "新描述"

    # --- terms ---

    def test_insert_and_get_term(self, db):
        db.insert_term("太虚剑", "上古神兵", first_chapter=3, category="法宝")
        result = db.get_term("太虚剑")
        assert result is not None
        assert result["definition"] == "上古神兵"
        assert result["category"] == "法宝"
        assert result["first_chapter"] == 3

    def test_get_term_not_found(self, db):
        assert db.get_term("不存在") is None

    def test_get_all_terms(self, db):
        db.insert_term("术语A", "定义A", 1)
        db.insert_term("术语B", "定义B", 2)
        db.insert_term("术语C", "定义C", 5)
        terms = db.get_all_terms()
        assert len(terms) == 3
        assert terms[0]["term"] == "术语A"

    def test_upsert_term(self, db):
        db.insert_term("太虚剑", "旧定义", 1)
        db.insert_term("太虚剑", "新定义", 1)
        result = db.get_term("太虚剑")
        assert result["definition"] == "新定义"

    # --- power_tracking ---

    def test_insert_and_get_power(self, db):
        db.insert_power_tracking("char1", 1, "筑基期", "初始")
        result = db.get_power_level("char1", 1)
        assert result is not None
        assert result["level"] == "筑基期"

    def test_get_latest_power(self, db):
        db.insert_power_tracking("char1", 1, "筑基期")
        db.insert_power_tracking("char1", 10, "金丹期", "突破")
        result = db.get_power_level("char1")
        assert result["level"] == "金丹期"
        assert result["change_reason"] == "突破"

    def test_get_power_not_found(self, db):
        assert db.get_power_level("nonexistent") is None

    def test_get_power_history(self, db):
        db.insert_power_tracking("char1", 1, "筑基期")
        db.insert_power_tracking("char1", 10, "金丹期")
        db.insert_power_tracking("char1", 50, "元婴期")
        history = db.get_power_history("char1")
        assert len(history) == 3
        assert history[-1]["level"] == "元婴期"

    # --- facts ---

    def test_insert_and_get_facts(self, db):
        fact = Fact(
            chapter=1,
            type="event",
            content="主角拜入宗门",
            storage_layer="structured",
        )
        db.insert_fact(fact)
        facts = db.get_facts(chapter=1)
        assert len(facts) == 1
        assert facts[0]["content"] == "主角拜入宗门"
        assert facts[0]["type"] == "event"

    def test_get_facts_by_type(self, db):
        db.insert_fact(Fact(chapter=1, type="event", content="A", storage_layer="structured"))
        db.insert_fact(Fact(chapter=1, type="time", content="B", storage_layer="structured"))
        db.insert_fact(Fact(chapter=2, type="event", content="C", storage_layer="structured"))
        events = db.get_facts(fact_type="event")
        assert len(events) == 2
        times = db.get_facts(fact_type="time")
        assert len(times) == 1

    def test_get_facts_empty(self, db):
        assert db.get_facts() == []

    def test_insert_duplicate_fact_ignored(self, db):
        fact = Fact(
            fact_id="same-id",
            chapter=1,
            type="event",
            content="事件",
            storage_layer="structured",
        )
        db.insert_fact(fact)
        db.insert_fact(fact)  # 重复插入不报错
        facts = db.get_facts()
        assert len(facts) == 1

    # --- chapter_summaries ---

    def test_insert_and_get_summary(self, db):
        summary = ChapterSummary(
            chapter=1,
            summary="这是第一章的摘要，主角出场并展开冒险之旅，遇到了第一个挑战，经历了激烈的战斗后成功突围，并在途中结识了一位神秘的老者。",
            key_events=["出场", "遇敌"],
        )
        db.insert_summary(summary)
        result = db.get_summary(1)
        assert result is not None
        assert "主角出场" in result["summary"]
        assert result["key_events"] == ["出场", "遇敌"]

    def test_get_summary_not_found(self, db):
        assert db.get_summary(999) is None

    def test_get_summaries_range(self, db):
        for i in range(1, 6):
            db.insert_summary(
                ChapterSummary(
                    chapter=i,
                    summary=f"第{i}章摘要，描述了故事发展的一些重要情节和角色变化。主角在这一章中经历了关键的转折，并且与其他角色产生了深入的互动和冲突。",
                    key_events=[f"事件{i}"],
                )
            )
        summaries = db.get_summaries(from_chapter=2, to_chapter=4)
        assert len(summaries) == 3
        assert summaries[0]["chapter"] == 2
        assert summaries[-1]["chapter"] == 4

    def test_get_summaries_no_upper_bound(self, db):
        for i in range(1, 4):
            db.insert_summary(
                ChapterSummary(
                    chapter=i,
                    summary=f"第{i}章的详细摘要文本，描述故事发展中的重要事件和角色变化，以及关键的情节推进。主角在此章节中面对了新的挑战并做出了重要的抉择。",
                    key_events=[f"e{i}"],
                )
            )
        summaries = db.get_summaries(from_chapter=2)
        assert len(summaries) == 2

    # --- context manager ---

    def test_context_manager(self, tmp_path):
        from src.novel.storage.structured_db import StructuredDB

        with StructuredDB(tmp_path / "ctx.db") as db:
            db.insert_term("测试", "测试定义", 1)
            assert db.get_term("测试") is not None
        # 关闭后连接应该为 None
        assert db._conn is None

    # --- transaction rollback ---

    def test_transaction_rollback_on_error(self, db):
        db.insert_term("ok", "ok定义", 1)
        with pytest.raises(Exception):
            with db.transaction() as cur:
                cur.execute(
                    "INSERT INTO terms (term, definition, first_chapter) VALUES (?, ?, ?)",
                    ("bad", "bad", 2),
                )
                raise ValueError("模拟错误")
        # "bad" 不应被提交
        assert db.get_term("bad") is None
        # "ok" 应该还在
        assert db.get_term("ok") is not None

    def test_close_then_assert_on_operation(self, db):
        db.close()
        with pytest.raises(AssertionError, match="closed"):
            db.get_character_state("char1")


# ============================================================
# KnowledgeGraph 测试
# ============================================================


class TestKnowledgeGraph:
    """NetworkX 知识图谱测试"""

    @pytest.fixture()
    def kg(self):
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        return KnowledgeGraph()

    def test_add_character(self, kg):
        kg.add_character("c1", "张三")
        node = kg.get_node("c1")
        assert node is not None
        assert node["type"] == "character"
        assert node["name"] == "张三"

    def test_add_faction(self, kg):
        kg.add_faction("f1", "天山派")
        node = kg.get_node("f1")
        assert node["type"] == "faction"

    def test_add_location(self, kg):
        kg.add_location("loc1", "长安城")
        node = kg.get_node("loc1")
        assert node["type"] == "location"

    def test_get_node_not_found(self, kg):
        assert kg.get_node("nonexistent") is None

    def test_get_nodes_by_type(self, kg):
        kg.add_character("c1", "张三")
        kg.add_character("c2", "李四")
        kg.add_faction("f1", "天山派")
        chars = kg.get_nodes_by_type("character")
        assert len(chars) == 2
        factions = kg.get_nodes_by_type("faction")
        assert len(factions) == 1

    def test_add_relationship(self, kg):
        kg.add_character("c1", "张三")
        kg.add_character("c2", "李四")
        kg.add_relationship("c1", "c2", "友好", intensity=7, chapter=1)
        rels = kg.get_relationships("c1")
        assert len(rels) == 1
        assert rels[0]["type"] == "友好"
        assert rels[0]["intensity"] == 7

    def test_get_relationships_both_directions(self, kg):
        kg.add_character("c1", "A")
        kg.add_character("c2", "B")
        kg.add_relationship("c1", "c2", "友好", 5, 1)
        kg.add_relationship("c2", "c1", "敌对", 8, 3)
        rels_c1 = kg.get_relationships("c1")
        assert len(rels_c1) == 2  # 1 outgoing + 1 incoming

    def test_get_relationships_not_found(self, kg):
        assert kg.get_relationships("nonexistent") == []

    def test_get_latest_relationship(self, kg):
        kg.add_character("c1", "A")
        kg.add_character("c2", "B")
        kg.add_relationship("c1", "c2", "友好", 5, 1)
        kg.add_relationship("c1", "c2", "敌对", 9, 10)
        latest = kg.get_latest_relationship("c1", "c2")
        assert latest is not None
        assert latest["type"] == "敌对"
        assert latest["chapter"] == 10

    def test_get_latest_relationship_not_found(self, kg):
        kg.add_character("c1", "A")
        kg.add_character("c2", "B")
        assert kg.get_latest_relationship("c1", "c2") is None

    def test_affiliation(self, kg):
        kg.add_character("c1", "张三")
        kg.add_faction("f1", "天山派")
        kg.add_affiliation("c1", "f1", role="弟子", chapter=1)
        members = kg.get_faction_members("f1")
        assert "c1" in members

    def test_faction_members_empty(self, kg):
        kg.add_faction("f1", "空派")
        assert kg.get_faction_members("f1") == []

    def test_faction_not_found(self, kg):
        assert kg.get_faction_members("nonexistent") == []

    def test_location_transition_and_path(self, kg):
        kg.add_location("loc1", "长安")
        kg.add_location("loc2", "洛阳")
        kg.add_location("loc3", "开封")
        kg.add_location_transition("loc1", "loc2", "近", 1)
        kg.add_location_transition("loc2", "loc3", "中", 2)
        path = kg.find_shortest_path("loc1", "loc3")
        assert path == ["loc1", "loc2", "loc3"]

    def test_find_shortest_path_no_path(self, kg):
        kg.add_location("a", "A")
        kg.add_location("b", "B")
        assert kg.find_shortest_path("a", "b") is None

    def test_find_shortest_path_node_not_found(self, kg):
        assert kg.find_shortest_path("x", "y") is None

    def test_save_and_load_json(self, kg, tmp_path):
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        kg.add_character("c1", "张三")
        kg.add_character("c2", "李四")
        kg.add_relationship("c1", "c2", "友好", 7, 1)
        kg.add_faction("f1", "天山派")
        kg.add_affiliation("c1", "f1", chapter=1)

        save_path = str(tmp_path / "graph.json")
        kg.save(save_path)
        assert Path(save_path).exists()

        kg2 = KnowledgeGraph.load(save_path)
        assert kg2.get_node("c1")["name"] == "张三"
        assert len(kg2.get_relationships("c1")) == 1
        assert "c1" in kg2.get_faction_members("f1")

    def test_save_converts_pkl_to_json(self, kg, tmp_path):
        kg.add_character("c1", "A")
        pkl_path = str(tmp_path / "graph.pkl")
        kg.save(pkl_path)
        # 实际存的是 .json
        assert (tmp_path / "graph.json").exists()

    def test_load_pkl_path_reads_json(self, kg, tmp_path):
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        kg.add_character("c1", "A")
        kg.save(str(tmp_path / "graph.pkl"))  # 写 .json

        # 用 .pkl 路径加载也能找到 .json
        kg2 = KnowledgeGraph.load(str(tmp_path / "graph.pkl"))
        assert kg2.get_node("c1") is not None

    def test_load_nonexistent_returns_empty(self, tmp_path):
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph.load(str(tmp_path / "nope.json"))
        assert len(kg.graph.nodes) == 0

    def test_close_clears_graph(self, kg):
        kg.add_character("c1", "A")
        kg.close()
        assert len(kg.graph.nodes) == 0

    def test_context_manager(self):
        from src.novel.storage.knowledge_graph import KnowledgeGraph

        with KnowledgeGraph() as kg:
            kg.add_character("c1", "A")
            assert kg.get_node("c1") is not None
        assert len(kg.graph.nodes) == 0


# ============================================================
# VectorStore 测试（Mock chromadb）
# ============================================================


class TestVectorStore:
    """Chroma 向量存储测试 - 使用 mock"""

    @pytest.fixture()
    def mock_chromadb(self):
        """Mock chromadb 模块"""
        mock_collection = MagicMock()
        mock_collection.add = MagicMock()
        mock_collection.query = MagicMock(
            return_value={
                "ids": [["fact1"]],
                "documents": [["主角出场"]],
                "metadatas": [[{"chapter": 1, "type": "event"}]],
                "distances": [[0.1]],
            }
        )
        mock_collection.count = MagicMock(return_value=5)

        mock_client = MagicMock()
        mock_client.get_or_create_collection = MagicMock(
            return_value=mock_collection
        )

        mock_chromadb_module = MagicMock()
        mock_chromadb_module.PersistentClient = MagicMock(
            return_value=mock_client
        )

        mock_settings = MagicMock()
        mock_settings_module = MagicMock()
        mock_settings_module.Settings = mock_settings

        return mock_chromadb_module, mock_client, mock_collection, mock_settings

    @pytest.fixture()
    def store(self, mock_chromadb, tmp_path):
        mock_module, mock_client, mock_collection, mock_settings = mock_chromadb

        with patch.dict(
            "sys.modules",
            {
                "chromadb": mock_module,
                "chromadb.config": MagicMock(Settings=mock_settings),
            },
        ):
            from src.novel.storage.vector_store import VectorStore

            vs = VectorStore(str(tmp_path / "vectors"))
            # 手动设置 mock client/collection
            vs._client = mock_client
            vs._collection = mock_collection
            yield vs, mock_collection

    def test_add_fact(self, store):
        vs, mock_coll = store
        fact = Fact(
            fact_id="f1",
            chapter=1,
            type="event",
            content="主角出场",
            storage_layer="vector",
        )
        vs.add_fact(fact)
        mock_coll.add.assert_called_once()
        call_kwargs = mock_coll.add.call_args
        assert call_kwargs[1]["documents"] == ["主角出场"]
        assert call_kwargs[1]["ids"] == ["f1"]

    def test_add_detail(self, store):
        vs, mock_coll = store
        detail = DetailEntry(
            detail_id="d1",
            chapter=1,
            content="角落的旧剑",
            context="他注意到角落有一把锈迹斑斑的旧剑",
            category="道具",
        )
        vs.add_detail(detail)
        mock_coll.add.assert_called_once()
        call_kwargs = mock_coll.add.call_args
        assert call_kwargs[1]["metadatas"][0]["type"] == "detail"

    def test_add_chapter_summary(self, store):
        vs, mock_coll = store
        vs.add_chapter_summary(1, "第一章摘要内容", "summary_ch1")
        mock_coll.add.assert_called_once()

    def test_search_similar_facts(self, store):
        vs, mock_coll = store
        results = vs.search_similar_facts("主角", n_results=3)
        assert results["ids"] == [["fact1"]]
        mock_coll.query.assert_called_once()

    def test_search_with_filter(self, store):
        vs, mock_coll = store
        vs.search_similar_facts("主角", filter_type="event")
        call_kwargs = mock_coll.query.call_args
        assert call_kwargs[1]["where"] == {"type": "event"}

    def test_search_potential_details(self, store):
        vs, mock_coll = store
        vs.search_potential_details("剑", category="道具")
        call_kwargs = mock_coll.query.call_args
        assert call_kwargs[1]["where"]["$and"][0]["type"] == "detail"

    def test_count(self, store):
        vs, mock_coll = store
        assert vs.count() == 5

    def test_ensure_collection_raises_without_init(self, tmp_path):
        from src.novel.storage.vector_store import VectorStore

        vs = VectorStore(str(tmp_path / "v"))
        with pytest.raises(RuntimeError, match="未初始化"):
            vs.add_fact(
                Fact(chapter=1, type="event", content="x", storage_layer="vector")
            )

    def test_close(self, store):
        vs, _ = store
        vs.close()
        assert vs._client is None
        assert vs._collection is None

    def test_context_manager(self, store):
        vs, _ = store
        with vs:
            assert vs._collection is not None
        assert vs._client is None

    def test_import_error_friendly_message(self, tmp_path):
        """chromadb 未安装时应给出友好提示"""
        with patch.dict("sys.modules", {"chromadb": None}):
            # 重新导入以触发新的 import 检查
            from src.novel.storage.vector_store import _get_chromadb

            with pytest.raises(ImportError, match="chromadb 未安装"):
                _get_chromadb()


# ============================================================
# NovelMemory 测试
# ============================================================


class TestNovelMemory:
    """三层混合记忆系统测试"""

    @pytest.fixture()
    def memory(self, tmp_path):
        """创建 NovelMemory，mock VectorStore 的 chromadb"""
        mock_collection = MagicMock()
        mock_collection.add = MagicMock()
        mock_collection.query = MagicMock(
            return_value={"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        )
        mock_collection.count = MagicMock(return_value=0)

        mock_client = MagicMock()
        mock_client.get_or_create_collection = MagicMock(
            return_value=mock_collection
        )

        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient = MagicMock(return_value=mock_client)

        with patch.dict(
            "sys.modules",
            {
                "chromadb": mock_chromadb,
                "chromadb.config": MagicMock(Settings=MagicMock()),
            },
        ):
            from src.novel.storage.novel_memory import NovelMemory

            mem = NovelMemory(novel_id="test-novel", workspace_dir=str(tmp_path))
            # 手动注入 mock
            mem.vector_store._client = mock_client
            mem.vector_store._collection = mock_collection
            yield mem
            mem.close()

    def test_workspace_created(self, memory, tmp_path):
        assert (tmp_path / "novels" / "test-novel").is_dir()

    def test_add_fact_structured(self, memory):
        fact = Fact(
            chapter=1,
            type="event",
            content="大事件发生",
            storage_layer="structured",
        )
        memory.add_fact(fact)
        facts = memory.query_facts(chapter=1)
        assert len(facts) == 1
        assert facts[0]["content"] == "大事件发生"

    def test_add_fact_vector(self, memory):
        fact = Fact(
            chapter=2,
            type="location",
            content="主角到达南疆",
            storage_layer="vector",
        )
        memory.add_fact(fact)
        # 应该同时存入 SQLite 和向量存储
        facts = memory.query_facts(chapter=2)
        assert len(facts) == 1
        memory.vector_store._collection.add.assert_called()

    def test_add_fact_character_state(self, memory):
        fact = Fact(
            chapter=1,
            type="character_state",
            content="张三: 健康状态良好",
            storage_layer="structured",
        )
        memory.add_fact(fact)
        # character_state 类型会额外插入 character_states 表
        state = memory.structured_db.get_character_state("张三")
        assert state is not None

    def test_add_fact_time(self, memory):
        fact = Fact(
            chapter=3,
            type="time",
            content="三天后的黄昏",
            storage_layer="structured",
        )
        memory.add_fact(fact)
        timeline = memory.structured_db.get_timeline(chapter=3)
        assert len(timeline) == 1

    def test_query_facts_filter(self, memory):
        memory.add_fact(Fact(chapter=1, type="event", content="A", storage_layer="structured"))
        memory.add_fact(Fact(chapter=1, type="time", content="B", storage_layer="structured"))
        memory.add_fact(Fact(chapter=2, type="event", content="C", storage_layer="structured"))

        events = memory.query_facts(fact_type="event")
        assert len(events) == 2

        ch1 = memory.query_facts(chapter=1)
        assert len(ch1) == 2

    def test_add_chapter_summary(self, memory):
        summary = ChapterSummary(
            chapter=1,
            summary="第一章讲述了主角出生和成长的故事，以及他初次踏入江湖的经历。在这个过程中他遇到了许多困难，但最终凭借自己的努力和勇气克服了所有障碍。",
            key_events=["出生", "入门"],
        )
        memory.add_chapter_summary(summary)
        result = memory.structured_db.get_summary(1)
        assert result is not None
        assert "出生" in result["key_events"]
        # 也应存入向量
        memory.vector_store._collection.add.assert_called()

    def test_get_context_for_chapter(self, memory):
        # 添加一些数据
        for i in range(1, 4):
            memory.structured_db.insert_summary(
                ChapterSummary(
                    chapter=i,
                    summary=f"第{i}章的详细摘要内容，描述了故事在这一章中发展的重要情节和角色的关键变化。主角经历了重大考验并获得了成长。",
                    key_events=[f"事件{i}"],
                )
            )
        memory.structured_db.insert_term("灵石", "修炼货币", 1)

        context = memory.get_context_for_chapter(4, n_recent_summaries=5)
        assert len(context["recent_summaries"]) == 3
        assert len(context["terms"]) == 1

    def test_create_volume_snapshot(self, memory):
        snapshot = memory.create_volume_snapshot(
            volume_number=1,
            main_plot_progress="主角完成筑基",
            main_plot_completion=0.2,
            ending_summary="第一卷结尾主角成功突破筑基期，但师门遭到偷袭，师父重伤，留下悬念。这是一个较长的结尾摘要文本，描述了卷末的关键转折。在最后一刻，神秘人出现拯救了众人，但师父的伤势依然严重，为第二卷埋下了伏笔。主角发誓要找到解药，踏上了前往南疆的旅程，然而前方等待他的是更加凶险的考验和未知的敌人。",
            cliffhanger="师父中毒",
        )
        assert snapshot.volume_number == 1
        assert snapshot.main_plot_completion == 0.2
        assert snapshot.cliffhanger == "师父中毒"

    def test_add_detail(self, memory):
        detail = DetailEntry(
            chapter=1, content="角落旧剑", context="前后文", category="道具"
        )
        memory.add_detail(detail)
        memory.vector_store._collection.add.assert_called()

    def test_knowledge_graph_integration(self, memory):
        memory.add_character_to_graph("c1", "张三")
        memory.add_character_to_graph("c2", "李四")
        memory.add_relationship_to_graph("c1", "c2", "友好", 7, 1)
        rels = memory.get_character_relationships("c1")
        assert len(rels) == 1

    def test_save_and_reload(self, memory, tmp_path):
        memory.add_character_to_graph("c1", "张三")
        memory.save()

        graph_path = tmp_path / "novels" / "test-novel" / "graph.json"
        assert graph_path.exists()

    def test_close_releases_resources(self, memory):
        memory.close()
        assert memory.structured_db._conn is None
        assert memory.vector_store._client is None

    def test_context_manager(self, tmp_path):
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection = MagicMock(return_value=mock_collection)
        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient = MagicMock(return_value=mock_client)

        with patch.dict(
            "sys.modules",
            {
                "chromadb": mock_chromadb,
                "chromadb.config": MagicMock(Settings=MagicMock()),
            },
        ):
            from src.novel.storage.novel_memory import NovelMemory

            with NovelMemory("ctx-test", str(tmp_path)) as mem:
                mem.vector_store._client = mock_client
                mem.vector_store._collection = mock_collection
                mem.add_character_to_graph("c1", "A")
            assert mem.structured_db._conn is None


# ============================================================
# FileManager 测试
# ============================================================


class TestFileManager:
    """文件系统管理测试"""

    @pytest.fixture()
    def fm(self, tmp_path):
        from src.novel.storage.file_manager import FileManager

        return FileManager(str(tmp_path))

    def _make_novel_data(self) -> dict:
        return {
            "novel_id": "test-novel",
            "title": "测试小说",
            "genre": "玄幻",
            "theme": "成长",
            "target_words": 100000,
            "style_name": "webnovel.shuangwen",
            "status": "writing",
            "current_chapter": 3,
            "outline": {
                "template": "cyclic_upgrade",
                "chapters": [{"chapter_number": i} for i in range(1, 11)],
            },
        }

    def _make_chapter_data(self, num: int) -> dict:
        return {
            "chapter_number": num,
            "title": f"第{num}章标题",
            "full_text": f"这是第{num}章的正文内容。" * 10,
            "word_count": 100,
            "status": "draft",
        }

    # --- Novel ---

    def test_save_and_load_novel(self, fm):
        data = self._make_novel_data()
        path = fm.save_novel("test-novel", data)
        assert path.exists()

        loaded = fm.load_novel("test-novel")
        assert loaded is not None
        assert loaded["title"] == "测试小说"
        assert loaded["genre"] == "玄幻"

    def test_load_novel_not_found(self, fm):
        assert fm.load_novel("nonexistent") is None

    def test_novel_exists(self, fm):
        assert not fm.novel_exists("test-novel")
        fm.save_novel("test-novel", self._make_novel_data())
        assert fm.novel_exists("test-novel")

    # --- Chapter ---

    def test_save_and_load_chapter(self, fm):
        data = self._make_chapter_data(1)
        path = fm.save_chapter("test-novel", 1, data)
        assert path.exists()
        assert "chapter_001.json" in str(path)

        loaded = fm.load_chapter("test-novel", 1)
        assert loaded is not None
        assert loaded["title"] == "第1章标题"

    def test_load_chapter_not_found(self, fm):
        assert fm.load_chapter("test-novel", 999) is None

    def test_save_and_load_chapter_text(self, fm):
        text = "这是纯文本章节内容\n包含多行。"
        path = fm.save_chapter_text("test-novel", 1, text)
        assert path.exists()

        loaded = fm.load_chapter_text("test-novel", 1)
        assert loaded == text

    def test_load_chapter_text_not_found(self, fm):
        assert fm.load_chapter_text("test-novel", 999) is None

    def test_list_chapters(self, fm):
        for i in [1, 3, 5]:
            fm.save_chapter("test-novel", i, self._make_chapter_data(i))
        chapters = fm.list_chapters("test-novel")
        assert chapters == [1, 3, 5]

    def test_list_chapters_empty(self, fm):
        assert fm.list_chapters("test-novel") == []

    # --- Export ---

    def test_export_novel_txt(self, fm):
        fm.save_novel("test-novel", self._make_novel_data())
        for i in range(1, 4):
            fm.save_chapter("test-novel", i, self._make_chapter_data(i))

        out_path = fm.export_novel_txt("test-novel")
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "测试小说" in content
        assert "第1章" in content
        assert "第3章" in content

    def test_export_novel_txt_custom_path(self, fm, tmp_path):
        fm.save_novel("test-novel", self._make_novel_data())
        fm.save_chapter("test-novel", 1, self._make_chapter_data(1))

        custom = str(tmp_path / "output" / "my_novel.txt")
        out = fm.export_novel_txt("test-novel", output_path=custom)
        assert out == Path(custom)
        assert out.exists()

    def test_export_novel_not_found(self, fm):
        with pytest.raises(FileNotFoundError, match="不存在"):
            fm.export_novel_txt("nonexistent")

    # --- Status ---

    def test_load_status(self, fm):
        fm.save_novel("test-novel", self._make_novel_data())
        for i in range(1, 4):
            fm.save_chapter("test-novel", i, self._make_chapter_data(i))

        status = fm.load_status("test-novel")
        assert status["title"] == "测试小说"
        assert status["status"] == "writing"
        assert status["current_chapter"] == 3
        assert status["total_chapters"] == 10
        assert status["total_words"] == 300  # 3 * 100

    def test_load_status_not_found(self, fm):
        status = fm.load_status("nonexistent")
        assert status["status"] == "not_found"

    # --- UTF-8 ---

    def test_unicode_content(self, fm):
        data = self._make_novel_data()
        data["title"] = "仙侠奇缘之天地玄黄"
        fm.save_novel("unicode-test", data)

        loaded = fm.load_novel("unicode-test")
        assert loaded["title"] == "仙侠奇缘之天地玄黄"

    # --- Context manager ---

    def test_context_manager(self, tmp_path):
        from src.novel.storage.file_manager import FileManager

        with FileManager(str(tmp_path)) as fm:
            fm.save_novel("test", {"title": "T"})
            assert fm.load_novel("test") is not None

    # --- Edge cases ---

    def test_chapter_numbering_format(self, fm):
        """章节号以 3 位零填充"""
        fm.save_chapter("test-novel", 1, self._make_chapter_data(1))
        fm.save_chapter("test-novel", 99, self._make_chapter_data(99))
        fm.save_chapter("test-novel", 100, self._make_chapter_data(100))
        chapters = fm.list_chapters("test-novel")
        assert chapters == [1, 99, 100]

    def test_export_fallback_to_text_file(self, fm):
        """章节 JSON 中无 full_text 时回退到 .txt 文件"""
        fm.save_novel("test-novel", self._make_novel_data())
        ch_data = self._make_chapter_data(1)
        ch_data["full_text"] = ""
        fm.save_chapter("test-novel", 1, ch_data)
        fm.save_chapter_text("test-novel", 1, "纯文本回退内容")

        out = fm.export_novel_txt("test-novel")
        content = out.read_text(encoding="utf-8")
        assert "纯文本回退内容" in content
