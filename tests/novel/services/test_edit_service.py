"""NovelEditService 单元测试"""

from __future__ import annotations

import copy
from unittest.mock import MagicMock, patch

import pytest

from src.novel.services.edit_service import EditResult, NovelEditService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_novel_data(**overrides) -> dict:
    """构建一个标准的 novel_data fixture。"""
    base = {
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
                {
                    "chapter_number": 2,
                    "title": "第一次战斗",
                    "goal": "展示主角潜力",
                    "key_events": ["与反派初遇"],
                },
            ],
        },
        "config": {"llm": {"provider": "auto"}},
    }
    base.update(overrides)
    return base


@pytest.fixture
def mock_file_manager():
    """Mock FileManager。"""
    fm = MagicMock()
    fm.load_novel.return_value = _make_novel_data()
    fm.save_novel.return_value = None
    fm.save_backup.return_value = "/tmp/backup.json"
    fm.save_change_log.return_value = "/tmp/changelog.json"
    fm.list_change_logs.return_value = [
        {"change_id": "log_1", "change_type": "update"},
        {"change_id": "log_2", "change_type": "add"},
    ]
    return fm


@pytest.fixture
def service(mock_file_manager):
    """构建使用 mock FileManager 的 service。"""
    svc = NovelEditService(workspace="workspace")
    svc.file_manager = mock_file_manager
    return svc


# ---------------------------------------------------------------------------
# novel_id 提取
# ---------------------------------------------------------------------------

class TestExtractNovelId:
    """测试 project_path -> novel_id 提取。"""

    def test_relative_path(self):
        assert NovelEditService._extract_novel_id(
            "workspace/novels/novel_001"
        ) == "novel_001"

    def test_absolute_path(self):
        assert NovelEditService._extract_novel_id(
            "/home/user/workspace/novels/novel_xyz"
        ) == "novel_xyz"

    def test_trailing_slash(self):
        # Path("workspace/novels/novel_001/").name == "novel_001"
        assert NovelEditService._extract_novel_id(
            "workspace/novels/novel_001/"
        ) == "novel_001"

    def test_single_segment(self):
        assert NovelEditService._extract_novel_id("novel_001") == "novel_001"


# ---------------------------------------------------------------------------
# 结构化编辑流程
# ---------------------------------------------------------------------------

class TestStructuredEdit:
    """structured_change 直接编辑。"""

    def test_update_character_success(self, service, mock_file_manager):
        """正常更新角色。"""
        change = {
            "change_type": "update",
            "entity_type": "character",
            "entity_id": "char_001",
            "data": {"age": 20},
        }

        result = service.edit(
            project_path="workspace/novels/novel_001",
            structured_change=change,
            effective_from_chapter=6,
        )

        assert isinstance(result, EditResult)
        assert result.status == "success"
        assert result.change_type == "update"
        assert result.entity_type == "character"
        assert result.effective_from_chapter == 6

        # FileManager 交互验证
        mock_file_manager.load_novel.assert_called_once_with("novel_001")
        mock_file_manager.save_backup.assert_called_once_with("novel_001")
        mock_file_manager.save_novel.assert_called_once()
        mock_file_manager.save_change_log.assert_called_once()

    def test_add_character_success(self, service, mock_file_manager):
        """添加角色。"""
        change = {
            "change_type": "add",
            "entity_type": "character",
            "data": {
                "name": "李四",
                "gender": "男",
                "age": 25,
                "occupation": "剑客",
                "role": "配角",
                "appearance": {
                    "height": "175cm",
                    "build": "瘦削",
                    "hair": "白发",
                    "eyes": "蓝色",
                    "clothing_style": "白衣",
                },
                "personality": {
                    "traits": ["冷酷", "果断", "孤傲"],
                    "core_belief": "力量至上",
                    "motivation": "复仇",
                    "flaw": "孤僻",
                    "speech_style": "简短",
                },
            },
        }

        result = service.edit(
            project_path="workspace/novels/novel_001",
            structured_change=change,
        )

        assert result.status == "success"
        assert result.change_type == "add"
        assert result.entity_type == "character"
        # add 操作后 entity_id 应从 new_value 中提取
        assert result.entity_id is not None
        assert result.new_value is not None
        assert result.new_value["name"] == "李四"

    def test_update_world_setting(self, service, mock_file_manager):
        """更新世界观。"""
        change = {
            "change_type": "update",
            "entity_type": "world_setting",
            "data": {"era": "远古洪荒", "location": "混沌之地"},
        }

        result = service.edit(
            project_path="workspace/novels/novel_001",
            structured_change=change,
        )

        assert result.status == "success"
        assert result.entity_type == "world_setting"

    def test_update_outline(self, service, mock_file_manager):
        """更新大纲。"""
        change = {
            "change_type": "update",
            "entity_type": "outline",
            "data": {
                "chapter_number": 1,
                "title": "修炼起源",
                "goal": "揭示修炼体系",
                "key_events": ["发现灵根"],
            },
        }

        result = service.edit(
            project_path="workspace/novels/novel_001",
            structured_change=change,
        )

        assert result.status == "success"
        assert result.entity_type == "outline"


# ---------------------------------------------------------------------------
# 自然语言编辑流程
# ---------------------------------------------------------------------------

class TestInstructionEdit:
    """instruction 自然语言编辑。"""

    @patch("src.novel.services.edit_service.create_llm_client")
    @patch("src.novel.services.edit_service.IntentParser")
    def test_instruction_edit_success(
        self, MockParser, mock_create_llm, service, mock_file_manager
    ):
        """自然语言编辑流程。"""
        # 模拟 IntentParser 返回
        parser_instance = MockParser.return_value
        parser_instance.parse.return_value = {
            "change_type": "update",
            "entity_type": "character",
            "entity_id": "char_001",
            "data": {"age": 22},
            "effective_from_chapter": 7,
            "reasoning": "用户要求更新年龄",
        }

        result = service.edit(
            project_path="workspace/novels/novel_001",
            instruction="把张三的年龄改为22岁",
        )

        assert result.status == "success"
        assert result.change_type == "update"
        assert result.entity_type == "character"
        assert result.entity_id == "char_001"
        assert result.reasoning == "用户要求更新年龄"

        # 验证 LLM client 创建
        mock_create_llm.assert_called_once()
        # 验证 IntentParser 调用
        parser_instance.parse.assert_called_once()

    @patch("src.novel.services.edit_service.create_llm_client")
    @patch("src.novel.services.edit_service.IntentParser")
    def test_instruction_parse_failure(
        self, MockParser, mock_create_llm, service, mock_file_manager
    ):
        """IntentParser 解析失败时返回 failed。"""
        parser_instance = MockParser.return_value
        parser_instance.parse.side_effect = ValueError("解析失败")

        result = service.edit(
            project_path="workspace/novels/novel_001",
            instruction="乱七八糟的输入",
        )

        assert result.status == "failed"
        assert "解析失败" in result.error


# ---------------------------------------------------------------------------
# dry_run 模式
# ---------------------------------------------------------------------------

class TestDryRun:
    """dry_run 模式不保存、不备份。"""

    def test_dry_run_returns_preview(self, service, mock_file_manager):
        """dry_run 返回 preview 状态。"""
        change = {
            "change_type": "update",
            "entity_type": "character",
            "entity_id": "char_001",
            "data": {"age": 30},
        }

        result = service.edit(
            project_path="workspace/novels/novel_001",
            structured_change=change,
            dry_run=True,
        )

        assert result.status == "preview"
        assert result.change_type == "update"
        assert result.entity_type == "character"
        assert result.entity_id == "char_001"

        # 不应调用保存/备份
        mock_file_manager.save_backup.assert_not_called()
        mock_file_manager.save_novel.assert_not_called()
        mock_file_manager.save_change_log.assert_not_called()

    def test_dry_run_with_effective_from(self, service, mock_file_manager):
        """dry_run 包含推断的 effective_from_chapter。"""
        change = {
            "change_type": "add",
            "entity_type": "character",
            "data": {"name": "王五"},
        }

        result = service.edit(
            project_path="workspace/novels/novel_001",
            structured_change=change,
            effective_from_chapter=10,
            dry_run=True,
        )

        assert result.effective_from_chapter == 10


# ---------------------------------------------------------------------------
# effective_from_chapter 推断逻辑
# ---------------------------------------------------------------------------

class TestEffectiveFromInference:
    """effective_from_chapter 推断优先级。"""

    def test_explicit_value_takes_priority(self):
        """显式传入的值优先。"""
        change = {"effective_from_chapter": 10}
        novel_data = {"current_chapter": 5}
        result = NovelEditService._resolve_effective_from(change, 15, novel_data)
        assert result == 15

    def test_change_value_second(self):
        """change 中的值次优先。"""
        change = {"effective_from_chapter": 10}
        novel_data = {"current_chapter": 5}
        result = NovelEditService._resolve_effective_from(change, None, novel_data)
        assert result == 10

    def test_default_from_current_chapter(self):
        """默认为 current_chapter + 1。"""
        change = {}
        novel_data = {"current_chapter": 5}
        result = NovelEditService._resolve_effective_from(change, None, novel_data)
        assert result == 6

    def test_default_when_no_current_chapter(self):
        """current_chapter 不存在时默认为 1。"""
        change = {}
        novel_data = {}
        result = NovelEditService._resolve_effective_from(change, None, novel_data)
        assert result == 1


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """错误路径测试。"""

    def test_novel_not_found(self, service, mock_file_manager):
        """小说项目不存在。"""
        mock_file_manager.load_novel.return_value = None

        result = service.edit(
            project_path="workspace/novels/nonexistent",
            structured_change={"change_type": "update", "entity_type": "character"},
        )

        assert result.status == "failed"
        assert "不存在" in result.error

    def test_no_input_provided(self, service, mock_file_manager):
        """既没有 instruction 也没有 structured_change。"""
        result = service.edit(
            project_path="workspace/novels/novel_001",
        )

        assert result.status == "failed"
        assert "instruction" in result.error

    def test_unsupported_entity_type(self, service, mock_file_manager):
        """不支持的 entity_type。"""
        change = {
            "change_type": "update",
            "entity_type": "magic_system",
            "data": {"name": "test"},
        }

        result = service.edit(
            project_path="workspace/novels/novel_001",
            structured_change=change,
        )

        assert result.status == "failed"
        assert "不支持" in result.error

    def test_editor_raises_exception(self, service, mock_file_manager):
        """编辑器抛出异常时返回 failed。"""
        change = {
            "change_type": "update",
            "entity_type": "character",
            "entity_id": "nonexistent_char",
            "data": {"age": 30},
        }

        result = service.edit(
            project_path="workspace/novels/novel_001",
            structured_change=change,
        )

        # CharacterEditor.apply 会因为找不到角色而抛出 ValueError
        assert result.status == "failed"
        assert "不存在" in result.error

    def test_save_backup_failure(self, service, mock_file_manager):
        """备份失败时返回 failed。"""
        mock_file_manager.save_backup.side_effect = FileNotFoundError("novel.json 不存在")

        change = {
            "change_type": "update",
            "entity_type": "character",
            "entity_id": "char_001",
            "data": {"age": 30},
        }

        result = service.edit(
            project_path="workspace/novels/novel_001",
            structured_change=change,
        )

        assert result.status == "failed"
        assert result.error is not None


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------

class TestGetHistory:
    """变更历史查询。"""

    def test_get_history_returns_logs(self, service, mock_file_manager):
        """正常查询历史。"""
        result = service.get_history("workspace/novels/novel_001")

        assert len(result) == 2
        assert result[0]["change_id"] == "log_1"
        mock_file_manager.list_change_logs.assert_called_once_with("novel_001", 20)

    def test_get_history_with_limit(self, service, mock_file_manager):
        """带 limit 参数查询。"""
        service.get_history("workspace/novels/novel_001", limit=5)

        mock_file_manager.list_change_logs.assert_called_once_with("novel_001", 5)

    def test_get_history_extracts_novel_id(self, service, mock_file_manager):
        """从绝对路径提取 novel_id。"""
        service.get_history("/home/user/workspace/novels/novel_xyz")

        mock_file_manager.list_change_logs.assert_called_once_with("novel_xyz", 20)


# ---------------------------------------------------------------------------
# 变更日志记录验证
# ---------------------------------------------------------------------------

class TestChangeLogRecording:
    """验证变更日志的内容是否正确。"""

    def test_change_log_contains_required_fields(self, service, mock_file_manager):
        """日志包含所有必需字段。"""
        change = {
            "change_type": "update",
            "entity_type": "character",
            "entity_id": "char_001",
            "data": {"age": 25},
        }

        service.edit(
            project_path="workspace/novels/novel_001",
            structured_change=change,
            effective_from_chapter=8,
        )

        # 提取保存的日志
        call_args = mock_file_manager.save_change_log.call_args
        novel_id_arg = call_args[0][0]
        entry = call_args[0][1]

        assert novel_id_arg == "novel_001"
        assert "change_id" in entry
        assert "timestamp" in entry
        assert entry["change_type"] == "update"
        assert entry["entity_type"] == "character"
        assert entry["entity_id"] == "char_001"
        assert entry["effective_from_chapter"] == 8
        assert "old_value" in entry
        assert "new_value" in entry

    def test_change_log_records_instruction(self, service, mock_file_manager):
        """日志记录原始自然语言指令。"""
        change = {
            "change_type": "update",
            "entity_type": "character",
            "entity_id": "char_001",
            "data": {"age": 30},
        }

        service.edit(
            project_path="workspace/novels/novel_001",
            instruction=None,
            structured_change=change,
        )

        entry = mock_file_manager.save_change_log.call_args[0][1]
        assert entry["instruction"] is None


# ---------------------------------------------------------------------------
# build_novel_context
# ---------------------------------------------------------------------------

class TestBuildNovelContext:
    """_build_novel_context 辅助方法。"""

    def test_extracts_relevant_fields(self):
        """提取 genre, characters, current_chapter。"""
        novel_data = _make_novel_data()
        ctx = NovelEditService._build_novel_context(novel_data)

        assert ctx["genre"] == "玄幻"
        assert len(ctx["characters"]) == 1
        assert ctx["characters"][0]["name"] == "张三"
        assert ctx["current_chapter"] == 5

    def test_missing_fields_default(self):
        """缺失字段使用默认值。"""
        ctx = NovelEditService._build_novel_context({})

        assert ctx["genre"] == ""
        assert ctx["characters"] == []
        assert ctx["current_chapter"] == 0


# ---------------------------------------------------------------------------
# EditResult dataclass
# ---------------------------------------------------------------------------

class TestEditResult:
    """EditResult 数据类基本检查。"""

    def test_default_values(self):
        """默认值正确。"""
        r = EditResult(
            change_id="test",
            status="success",
            change_type="add",
            entity_type="character",
        )
        assert r.entity_id is None
        assert r.old_value is None
        assert r.new_value is None
        assert r.effective_from_chapter is None
        assert r.reasoning == ""
        assert r.error is None

    def test_all_fields(self):
        """所有字段赋值正确。"""
        r = EditResult(
            change_id="id_1",
            status="failed",
            change_type="delete",
            entity_type="character",
            entity_id="char_1",
            old_value={"name": "old"},
            new_value={"name": "new"},
            effective_from_chapter=10,
            reasoning="test reason",
            error="something broke",
        )
        assert r.change_id == "id_1"
        assert r.status == "failed"
        assert r.error == "something broke"
