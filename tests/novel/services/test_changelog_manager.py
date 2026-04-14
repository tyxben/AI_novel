"""ChangeLogManager 单元测试"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.novel.models.changelog import ChangeLogEntry
from src.novel.services.changelog_manager import ChangeLogManager
from src.novel.services.edit_service import NovelEditService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_workspace(tmp_path: Path) -> str:
    """Create a temporary workspace directory."""
    ws = tmp_path / "test_workspace"
    ws.mkdir()
    return str(ws)


@pytest.fixture
def manager(tmp_workspace: str) -> ChangeLogManager:
    """Create a ChangeLogManager with a temp workspace."""
    return ChangeLogManager(workspace=tmp_workspace)


# ---------------------------------------------------------------------------
# ChangeLogEntry 模型
# ---------------------------------------------------------------------------

class TestChangeLogEntry:
    """ChangeLogEntry Pydantic 模型。"""

    def test_defaults(self):
        """默认字段自动生成。"""
        entry = ChangeLogEntry(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="添加角色李明",
        )
        assert entry.change_id  # UUID auto-generated
        assert entry.timestamp is not None
        assert entry.novel_id == "novel_001"
        assert entry.change_type == "add_character"
        assert entry.entity_type == "character"
        assert entry.description == "添加角色李明"
        assert entry.old_value is None
        assert entry.new_value is None
        assert entry.entity_id is None
        assert entry.effective_from_chapter == 1
        assert entry.author == "ai"

    def test_all_fields(self):
        """所有字段赋值。"""
        entry = ChangeLogEntry(
            change_id="custom_id",
            novel_id="novel_002",
            change_type="modify_character",
            entity_type="character",
            entity_id="char_001",
            description="修改角色年龄",
            old_value={"age": 18},
            new_value={"age": 25},
            effective_from_chapter=5,
            author="user",
        )
        assert entry.change_id == "custom_id"
        assert entry.entity_id == "char_001"
        assert entry.old_value == {"age": 18}
        assert entry.new_value == {"age": 25}
        assert entry.effective_from_chapter == 5
        assert entry.author == "user"

    def test_unique_change_ids(self):
        """每次创建的 change_id 唯一。"""
        e1 = ChangeLogEntry(
            novel_id="n", change_type="t", entity_type="e", description="d"
        )
        e2 = ChangeLogEntry(
            novel_id="n", change_type="t", entity_type="e", description="d"
        )
        assert e1.change_id != e2.change_id


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------

class TestRecord:
    """record 方法。"""

    def test_record_returns_entry(self, manager: ChangeLogManager):
        """record 返回 ChangeLogEntry。"""
        entry = manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="添加角色张三",
        )
        assert isinstance(entry, ChangeLogEntry)
        assert entry.novel_id == "novel_001"
        assert entry.change_type == "add_character"
        assert entry.entity_type == "character"
        assert entry.description == "添加角色张三"
        assert entry.change_id  # non-empty UUID
        assert entry.timestamp is not None

    def test_record_with_all_params(self, manager: ChangeLogManager):
        """record 传入所有参数。"""
        entry = manager.record(
            novel_id="novel_001",
            change_type="modify_character",
            entity_type="character",
            description="修改角色年龄",
            old_value={"age": 18},
            new_value={"age": 25},
            entity_id="char_001",
            effective_from_chapter=10,
            author="user",
        )
        assert entry.entity_id == "char_001"
        assert entry.old_value == {"age": 18}
        assert entry.new_value == {"age": 25}
        assert entry.effective_from_chapter == 10
        assert entry.author == "user"

    def test_record_persists_to_file(self, tmp_workspace: str):
        """record 后 JSON 文件存在且可加载。"""
        mgr = ChangeLogManager(workspace=tmp_workspace)
        mgr.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="test",
        )
        changelog_path = Path(tmp_workspace) / "changelog.json"
        assert changelog_path.exists()

    def test_record_multiple_entries(self, manager: ChangeLogManager):
        """连续记录多条。"""
        for i in range(5):
            manager.record(
                novel_id="novel_001",
                change_type="add_character",
                entity_type="character",
                description=f"添加角色{i}",
            )
        entries = manager.list_changes("novel_001", limit=100)
        assert len(entries) == 5


# ---------------------------------------------------------------------------
# list_changes
# ---------------------------------------------------------------------------

class TestListChanges:
    """list_changes 方法。"""

    def test_empty_history(self, manager: ChangeLogManager):
        """空历史返回空列表。"""
        result = manager.list_changes("novel_001")
        assert result == []

    def test_reverse_chronological_order(self, manager: ChangeLogManager):
        """结果按时间倒序。"""
        e1 = manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="第一条",
        )
        # Ensure distinct timestamps
        time.sleep(0.01)
        e2 = manager.record(
            novel_id="novel_001",
            change_type="modify_outline",
            entity_type="outline",
            description="第二条",
        )
        time.sleep(0.01)
        e3 = manager.record(
            novel_id="novel_001",
            change_type="modify_world",
            entity_type="world",
            description="第三条",
        )

        result = manager.list_changes("novel_001")
        assert len(result) == 3
        # 最新的在前面
        assert result[0].change_id == e3.change_id
        assert result[1].change_id == e2.change_id
        assert result[2].change_id == e1.change_id

    def test_limit(self, manager: ChangeLogManager):
        """limit 限制返回数量。"""
        for i in range(10):
            manager.record(
                novel_id="novel_001",
                change_type="add_character",
                entity_type="character",
                description=f"变更{i}",
            )
        result = manager.list_changes("novel_001", limit=3)
        assert len(result) == 3

    def test_filter_by_change_type(self, manager: ChangeLogManager):
        """按 change_type 过滤。"""
        manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="添加角色",
        )
        manager.record(
            novel_id="novel_001",
            change_type="modify_outline",
            entity_type="outline",
            description="修改大纲",
        )
        manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="再添加角色",
        )

        result = manager.list_changes("novel_001", change_type="add_character")
        assert len(result) == 2
        for e in result:
            assert e.change_type == "add_character"

    def test_filter_by_entity_type(self, manager: ChangeLogManager):
        """按 entity_type 过滤。"""
        manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="添加角色",
        )
        manager.record(
            novel_id="novel_001",
            change_type="modify_world",
            entity_type="world",
            description="修改世界观",
        )

        result = manager.list_changes("novel_001", entity_type="world")
        assert len(result) == 1
        assert result[0].entity_type == "world"

    def test_filter_by_novel_id(self, manager: ChangeLogManager):
        """只返回指定 novel_id 的变更。"""
        manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="小说1角色",
        )
        manager.record(
            novel_id="novel_002",
            change_type="add_character",
            entity_type="character",
            description="小说2角色",
        )

        result = manager.list_changes("novel_001")
        assert len(result) == 1
        assert result[0].novel_id == "novel_001"

    def test_nonexistent_novel_id(self, manager: ChangeLogManager):
        """不存在的 novel_id 返回空列表。"""
        manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="test",
        )
        result = manager.list_changes("nonexistent")
        assert result == []

    def test_combined_filters(self, manager: ChangeLogManager):
        """同时按 change_type 和 entity_type 过滤。"""
        manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="a",
        )
        manager.record(
            novel_id="novel_001",
            change_type="modify_character",
            entity_type="character",
            description="b",
        )
        manager.record(
            novel_id="novel_001",
            change_type="modify_outline",
            entity_type="outline",
            description="c",
        )

        result = manager.list_changes(
            "novel_001",
            change_type="modify_character",
            entity_type="character",
        )
        assert len(result) == 1
        assert result[0].description == "b"


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

class TestGet:
    """get 方法。"""

    def test_get_existing(self, manager: ChangeLogManager):
        """通过 change_id 获取已存在的记录。"""
        entry = manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="test",
        )
        found = manager.get(entry.change_id)
        assert found is not None
        assert found.change_id == entry.change_id
        assert found.novel_id == "novel_001"
        assert found.description == "test"

    def test_get_nonexistent(self, manager: ChangeLogManager):
        """不存在的 change_id 返回 None。"""
        result = manager.get("nonexistent_id")
        assert result is None

    def test_get_from_empty(self, manager: ChangeLogManager):
        """空历史中查找返回 None。"""
        result = manager.get("any_id")
        assert result is None


# ---------------------------------------------------------------------------
# get_changes_since
# ---------------------------------------------------------------------------

class TestGetChangesSince:
    """get_changes_since 方法。"""

    def test_time_filter(self, manager: ChangeLogManager):
        """过滤指定时间之后的变更。"""
        manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="早期变更",
        )
        # 获取当前时间作为分界点
        cutoff = datetime.now(timezone.utc)
        time.sleep(0.01)

        manager.record(
            novel_id="novel_001",
            change_type="modify_outline",
            entity_type="outline",
            description="后期变更",
        )

        result = manager.get_changes_since("novel_001", since=cutoff)
        assert len(result) == 1
        assert result[0].description == "后期变更"

    def test_since_future_returns_empty(self, manager: ChangeLogManager):
        """未来时间点返回空。"""
        manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="test",
        )
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        result = manager.get_changes_since("novel_001", since=future)
        assert result == []

    def test_since_filters_by_novel_id(self, manager: ChangeLogManager):
        """时间过滤同时按 novel_id 过滤。"""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="小说1",
        )
        manager.record(
            novel_id="novel_002",
            change_type="add_character",
            entity_type="character",
            description="小说2",
        )

        result = manager.get_changes_since("novel_001", since=past)
        assert len(result) == 1
        assert result[0].novel_id == "novel_001"

    def test_since_empty_history(self, manager: ChangeLogManager):
        """空历史返回空列表。"""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        result = manager.get_changes_since("novel_001", since=past)
        assert result == []


# ---------------------------------------------------------------------------
# get_changes_for_entity
# ---------------------------------------------------------------------------

class TestGetChangesForEntity:
    """get_changes_for_entity 方法。"""

    def test_entity_filter(self, manager: ChangeLogManager):
        """按 entity_id 过滤。"""
        manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            entity_id="char_001",
            description="添加角色A",
        )
        manager.record(
            novel_id="novel_001",
            change_type="modify_character",
            entity_type="character",
            entity_id="char_001",
            description="修改角色A",
        )
        manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            entity_id="char_002",
            description="添加角色B",
        )

        result = manager.get_changes_for_entity("novel_001", "char_001")
        assert len(result) == 2
        for e in result:
            assert e.entity_id == "char_001"

    def test_entity_not_found(self, manager: ChangeLogManager):
        """不存在的 entity_id 返回空列表。"""
        manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            entity_id="char_001",
            description="test",
        )
        result = manager.get_changes_for_entity("novel_001", "nonexistent")
        assert result == []

    def test_entity_filter_by_novel_id(self, manager: ChangeLogManager):
        """实体过滤同时按 novel_id 过滤。"""
        manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            entity_id="char_001",
            description="小说1角色",
        )
        manager.record(
            novel_id="novel_002",
            change_type="add_character",
            entity_type="character",
            entity_id="char_001",
            description="小说2同ID角色",
        )

        result = manager.get_changes_for_entity("novel_001", "char_001")
        assert len(result) == 1
        assert result[0].novel_id == "novel_001"

    def test_entity_empty_history(self, manager: ChangeLogManager):
        """空历史返回空列表。"""
        result = manager.get_changes_for_entity("novel_001", "char_001")
        assert result == []

    def test_entity_results_reverse_order(self, manager: ChangeLogManager):
        """实体变更按时间倒序。"""
        e1 = manager.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            entity_id="char_001",
            description="创建",
        )
        time.sleep(0.01)
        e2 = manager.record(
            novel_id="novel_001",
            change_type="modify_character",
            entity_type="character",
            entity_id="char_001",
            description="修改",
        )

        result = manager.get_changes_for_entity("novel_001", "char_001")
        assert len(result) == 2
        assert result[0].change_id == e2.change_id
        assert result[1].change_id == e1.change_id


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------

class TestPersistence:
    """持久化验证：重新创建实例后数据仍在。"""

    def test_reload_after_record(self, tmp_workspace: str):
        """record 后重新创建 ChangeLogManager，数据仍在。"""
        mgr1 = ChangeLogManager(workspace=tmp_workspace)
        entry = mgr1.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="持久化测试",
            old_value={"name": "旧名"},
            new_value={"name": "新名"},
            entity_id="char_001",
            effective_from_chapter=3,
            author="user",
        )

        # 创建新实例
        mgr2 = ChangeLogManager(workspace=tmp_workspace)
        found = mgr2.get(entry.change_id)

        assert found is not None
        assert found.change_id == entry.change_id
        assert found.novel_id == "novel_001"
        assert found.description == "持久化测试"
        assert found.old_value == {"name": "旧名"}
        assert found.new_value == {"name": "新名"}
        assert found.entity_id == "char_001"
        assert found.effective_from_chapter == 3
        assert found.author == "user"

    def test_reload_preserves_all_entries(self, tmp_workspace: str):
        """多条记录重载后全部保留。"""
        mgr1 = ChangeLogManager(workspace=tmp_workspace)
        for i in range(5):
            mgr1.record(
                novel_id="novel_001",
                change_type="add_character",
                entity_type="character",
                description=f"变更{i}",
            )

        mgr2 = ChangeLogManager(workspace=tmp_workspace)
        result = mgr2.list_changes("novel_001", limit=100)
        assert len(result) == 5

    def test_reload_preserves_timestamp(self, tmp_workspace: str):
        """重载后 timestamp 保留。"""
        mgr1 = ChangeLogManager(workspace=tmp_workspace)
        entry = mgr1.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="时间戳测试",
        )
        original_ts = entry.timestamp

        mgr2 = ChangeLogManager(workspace=tmp_workspace)
        found = mgr2.get(entry.change_id)
        assert found is not None
        # Timestamps should be equal (allowing for serialization rounding)
        assert abs((found.timestamp - original_ts).total_seconds()) < 1


# ---------------------------------------------------------------------------
# 边界条件
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """边界条件。"""

    def test_workspace_created_if_not_exists(self, tmp_path: Path):
        """workspace 目录不存在时自动创建。"""
        ws = str(tmp_path / "nonexistent" / "deep" / "path")
        mgr = ChangeLogManager(workspace=ws)
        mgr.record(
            novel_id="novel_001",
            change_type="add_character",
            entity_type="character",
            description="test",
        )
        assert Path(ws).exists()
        assert (Path(ws) / "changelog.json").exists()

    def test_corrupted_json_file(self, tmp_workspace: str):
        """损坏的 JSON 文件不崩溃，返回空列表。"""
        changelog_path = Path(tmp_workspace) / "changelog.json"
        changelog_path.write_text("not valid json {{{", encoding="utf-8")

        mgr = ChangeLogManager(workspace=tmp_workspace)
        result = mgr.list_changes("novel_001")
        assert result == []

    def test_empty_json_array(self, tmp_workspace: str):
        """空 JSON 数组文件正常工作。"""
        changelog_path = Path(tmp_workspace) / "changelog.json"
        changelog_path.write_text("[]", encoding="utf-8")

        mgr = ChangeLogManager(workspace=tmp_workspace)
        result = mgr.list_changes("novel_001")
        assert result == []

    def test_record_with_none_values(self, manager: ChangeLogManager):
        """old_value 和 new_value 为 None。"""
        entry = manager.record(
            novel_id="novel_001",
            change_type="delete_character",
            entity_type="character",
            description="删除角色",
            old_value=None,
            new_value=None,
            entity_id=None,
        )
        found = manager.get(entry.change_id)
        assert found is not None
        assert found.old_value is None
        assert found.new_value is None
        assert found.entity_id is None

    def test_record_with_nested_dict_values(self, manager: ChangeLogManager):
        """嵌套 dict 作为 old_value/new_value。"""
        nested = {
            "character": {
                "name": "张三",
                "appearance": {"height": "180cm", "eyes": "黑色"},
                "relationships": [{"target": "李四", "type": "友好"}],
            }
        }
        entry = manager.record(
            novel_id="novel_001",
            change_type="modify_character",
            entity_type="character",
            description="修改角色详情",
            new_value=nested,
        )
        found = manager.get(entry.change_id)
        assert found is not None
        assert found.new_value == nested
        assert found.new_value["character"]["appearance"]["height"] == "180cm"


# ---------------------------------------------------------------------------
# NovelEditService 集成
# ---------------------------------------------------------------------------

class TestEditServiceIntegration:
    """NovelEditService 与 ChangeLogManager 的集成。"""

    def _make_novel_data(self) -> dict:
        """构建标准 novel_data fixture。"""
        return {
            "novel_id": "novel_001",
            "title": "测试小说",
            "genre": "玄幻",
            "current_chapter": 5,
            "characters": [
                {
                    "character_id": "char_001",
                    "name": "张三",
                    "gender": "男",
                    "age": 18,
                    "occupation": "修炼者",
                    "role": "主角",
                    "appearance": {
                        "height": "180cm",
                        "build": "健硕",
                        "hair": "黑色长发",
                        "eyes": "黑色",
                        "clothing_style": "青衣",
                    },
                    "personality": {
                        "traits": ["坚毅", "善良", "勇敢"],
                        "core_belief": "正义",
                        "motivation": "变强",
                        "flaw": "冲动",
                        "speech_style": "直率",
                    },
                }
            ],
            "world_setting": {
                "era": "古代仙侠",
                "location": "九州大陆",
                "rules": ["天道轮回"],
                "terms": {"灵气": "修炼基础能量"},
            },
            "outline": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "初入修炼界",
                        "goal": "介绍主角背景",
                        "key_events": ["入门测试"],
                    },
                ],
            },
            "config": {"llm": {"provider": "auto"}},
        }

    def test_edit_records_to_changelog_manager(self, tmp_path: Path):
        """edit 成功后自动记录到 ChangeLogManager。"""
        ws = str(tmp_path / "ws")
        changelog_mgr = ChangeLogManager(workspace=ws)

        svc = NovelEditService(workspace="workspace", changelog_manager=changelog_mgr)
        # Mock file_manager
        mock_fm = MagicMock()
        mock_fm.load_novel.return_value = self._make_novel_data()
        mock_fm.save_novel.return_value = None
        mock_fm.save_backup.return_value = "/tmp/backup.json"
        mock_fm.save_change_log.return_value = "/tmp/changelog.json"
        svc.file_manager = mock_fm

        change = {
            "change_type": "update",
            "entity_type": "character",
            "entity_id": "char_001",
            "data": {"age": 25},
        }

        result = svc.edit(
            project_path="workspace/novels/novel_001",
            structured_change=change,
            effective_from_chapter=6,
        )

        assert result.status == "success"

        # 验证 ChangeLogManager 收到记录
        entries = changelog_mgr.list_changes("novel_001")
        assert len(entries) == 1
        entry = entries[0]
        assert entry.novel_id == "novel_001"
        assert entry.change_type == "update_character"
        assert entry.entity_type == "character"
        assert entry.entity_id == "char_001"
        assert entry.effective_from_chapter == 6

    def test_edit_without_changelog_manager(self):
        """没有 changelog_manager 时不报错。"""
        svc = NovelEditService(workspace="workspace", changelog_manager=None)

        mock_fm = MagicMock()
        mock_fm.load_novel.return_value = self._make_novel_data()
        mock_fm.save_novel.return_value = None
        mock_fm.save_backup.return_value = "/tmp/backup.json"
        mock_fm.save_change_log.return_value = "/tmp/changelog.json"
        svc.file_manager = mock_fm

        change = {
            "change_type": "update",
            "entity_type": "character",
            "entity_id": "char_001",
            "data": {"age": 25},
        }

        result = svc.edit(
            project_path="workspace/novels/novel_001",
            structured_change=change,
        )
        assert result.status == "success"

    def test_changelog_manager_failure_does_not_break_edit(self, tmp_path: Path):
        """ChangeLogManager 失败不影响 edit 返回 success。"""
        changelog_mgr = MagicMock()
        changelog_mgr.record.side_effect = OSError("disk full")

        svc = NovelEditService(workspace="workspace", changelog_manager=changelog_mgr)

        mock_fm = MagicMock()
        mock_fm.load_novel.return_value = self._make_novel_data()
        mock_fm.save_novel.return_value = None
        mock_fm.save_backup.return_value = "/tmp/backup.json"
        mock_fm.save_change_log.return_value = "/tmp/changelog.json"
        svc.file_manager = mock_fm

        change = {
            "change_type": "update",
            "entity_type": "character",
            "entity_id": "char_001",
            "data": {"age": 25},
        }

        result = svc.edit(
            project_path="workspace/novels/novel_001",
            structured_change=change,
        )
        # edit 仍然成功
        assert result.status == "success"

    def test_instruction_edit_records_author_user(self, tmp_path: Path):
        """通过 instruction 编辑时 author 为 'user'。"""
        ws = str(tmp_path / "ws")
        changelog_mgr = ChangeLogManager(workspace=ws)

        svc = NovelEditService(workspace="workspace", changelog_manager=changelog_mgr)

        mock_fm = MagicMock()
        mock_fm.load_novel.return_value = self._make_novel_data()
        mock_fm.save_novel.return_value = None
        mock_fm.save_backup.return_value = "/tmp/backup.json"
        mock_fm.save_change_log.return_value = "/tmp/changelog.json"
        svc.file_manager = mock_fm

        # Mock IntentParser
        with pytest.importorskip("unittest.mock").patch(
            "src.novel.services.edit_service.IntentParser"
        ) as MockParser, pytest.importorskip("unittest.mock").patch(
            "src.novel.services.edit_service.create_llm_client"
        ):
            parser_instance = MockParser.return_value
            parser_instance.parse.return_value = {
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 22},
                "reasoning": "用户要求更新年龄",
            }

            result = svc.edit(
                project_path="workspace/novels/novel_001",
                instruction="把张三的年龄改为22岁",
            )

        assert result.status == "success"

        entries = changelog_mgr.list_changes("novel_001")
        assert len(entries) == 1
        assert entries[0].author == "user"
        assert entries[0].description == "把张三的年龄改为22岁"

    def test_dry_run_does_not_record(self, tmp_path: Path):
        """dry_run 模式不记录到 ChangeLogManager。"""
        ws = str(tmp_path / "ws")
        changelog_mgr = ChangeLogManager(workspace=ws)

        svc = NovelEditService(workspace="workspace", changelog_manager=changelog_mgr)

        mock_fm = MagicMock()
        mock_fm.load_novel.return_value = self._make_novel_data()
        svc.file_manager = mock_fm

        change = {
            "change_type": "update",
            "entity_type": "character",
            "entity_id": "char_001",
            "data": {"age": 25},
        }

        result = svc.edit(
            project_path="workspace/novels/novel_001",
            structured_change=change,
            dry_run=True,
        )
        assert result.status == "preview"

        entries = changelog_mgr.list_changes("novel_001")
        assert len(entries) == 0
