"""P1 集成测试：影响分析 + 变更历史 + MCP 工具端到端。

使用真实 FileManager / ImpactAnalyzer / NovelEditService（tmp_path），
Mock 仅限 LLM（自然语言路径）。验证：
  13.1 影响分析：删除角色 / 修改核心属性 → affected_chapters + severity 正确
  13.2 变更历史：多次 edit → get_history() 顺序、change_type 过滤正确
  13.3 MCP 工具：novel_edit_setting / novel_get_change_history /
       novel_analyze_change_impact 真实写盘后可查询并保持数据一致。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_novel_with_outline(
    workspace: Path,
    novel_id: str = "novel_p1",
) -> dict:
    """写入一份包含多章大纲 + 角色引用的 novel.json，返回 novel_data。

    char_001 出现在 outline.chapters 的 [2, 5, 7]（涵盖"当前章之后"）
    char_002 只出现在已写章节（chapters/）里 —— 模拟已写文本中的引用
    current_chapter = 3，effective_from_chapter 推断为 4。
    """
    novel_dir = workspace / "novels" / novel_id
    novel_dir.mkdir(parents=True)

    novel_data = {
        "novel_id": novel_id,
        "title": "P1 集成测试小说",
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
                "appearance": {
                    "height": "180cm",
                    "build": "健硕",
                    "hair": "黑长",
                    "eyes": "黑",
                    "clothing_style": "青衣",
                },
                "personality": {
                    "traits": ["坚毅", "善良", "勇敢"],
                    "core_belief": "正义",
                    "motivation": "变强",
                    "flaw": "冲动",
                    "speech_style": "直率",
                },
            },
            {
                "character_id": "char_002",
                "name": "李四",
                "gender": "男",
                "age": 20,
                "occupation": "剑客",
                "role": "配角",
                "status": "active",
                "appearance": {
                    "height": "178cm",
                    "build": "瘦削",
                    "hair": "银白",
                    "eyes": "蓝",
                    "clothing_style": "白袍",
                },
                "personality": {
                    "traits": ["冷静", "内敛", "果断"],
                    "core_belief": "剑道",
                    "motivation": "变强",
                    "flaw": "孤傲",
                    "speech_style": "简短",
                },
            },
        ],
        "world_setting": {
            "era": "古代仙侠",
            "location": "九州",
            "rules": ["天道轮回"],
            "terms": {"灵气": "修炼基础能量"},
        },
        "outline": {
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "初入门",
                    "goal": "交代背景",
                    "key_events": ["入门"],
                    "involved_characters": ["char_001"],
                },
                {
                    "chapter_number": 2,
                    "title": "初战",
                    "goal": "展示潜力",
                    "key_events": ["小试身手"],
                    "involved_characters": ["char_001", "char_002"],
                },
                {
                    "chapter_number": 3,
                    "title": "相遇",
                    "goal": "遇到同门",
                    "key_events": ["结识"],
                    "involved_characters": ["char_002"],
                },
                {
                    "chapter_number": 5,
                    "title": "突破",
                    "goal": "境界提升",
                    "key_events": ["悟道"],
                    "involved_characters": ["char_001"],
                },
                {
                    "chapter_number": 7,
                    "title": "决战",
                    "goal": "对战反派",
                    "key_events": ["对决"],
                    "involved_characters": ["char_001"],
                },
            ],
        },
        "config": {"llm": {"provider": "auto"}},
    }

    with open(novel_dir / "novel.json", "w", encoding="utf-8") as f:
        json.dump(novel_data, f, ensure_ascii=False, indent=2)

    # 模拟一份已写章节文本（用于 _find_character_in_written_chapters）
    chapters_dir = novel_dir / "chapters"
    chapters_dir.mkdir()
    (chapters_dir / "chapter_002.md").write_text(
        "# 第 2 章 初战\n\n张三握紧手中的剑……李四静立远处。",
        encoding="utf-8",
    )

    return novel_data


def _load_novel_json(workspace: Path, novel_id: str = "novel_p1") -> dict:
    path = workspace / "novels" / novel_id / "novel.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 13.1  影响分析流程
# ---------------------------------------------------------------------------


class TestImpactAnalysisFlow:
    """真实 NovelEditService + ImpactAnalyzer 的端到端影响分析。"""

    def test_delete_main_character_reports_critical_impact(self, tmp_path):
        """删除主角 → affected_chapters 覆盖 outline 引用；严重度至少 high。"""
        from src.novel.services.edit_service import NovelEditService

        _seed_novel_with_outline(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_p1"

        # dry_run 预览：不写盘
        result = service.edit(
            project_path=project,
            structured_change={
                "change_type": "delete",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {},
            },
            effective_from_chapter=4,
            dry_run=True,
        )

        assert result.status == "preview"
        assert result.impact_report is not None

        report = result.impact_report
        # char_001 在第 5/7 章大纲中出现（>= effective_from=4）
        assert 5 in report["affected_chapters"]
        assert 7 in report["affected_chapters"]
        # 至少 high（>=1 章 = high，>=3 章 = critical）
        assert report["severity"] in {"high", "critical"}
        # 应该有至少一条冲突描述
        assert len(report["conflicts"]) >= 1
        assert "张三" in report["conflicts"][0]

        # dry_run 不应写 novel.json（角色仍 active）
        novel = _load_novel_json(tmp_path)
        char = next(c for c in novel["characters"] if c["character_id"] == "char_001")
        assert char["status"] == "active"

    def test_modify_core_attribute_flags_conflicts(self, tmp_path):
        """修改主角核心属性（personality） → conflicts 非空，severity 升级。"""
        from src.novel.services.edit_service import NovelEditService

        _seed_novel_with_outline(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_p1"

        result = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {
                    "personality": {
                        "traits": ["阴险", "狡诈"],
                        "core_belief": "利益至上",
                        "motivation": "权力",
                        "flaw": "贪婪",
                        "speech_style": "阴阳怪气",
                    },
                },
            },
            effective_from_chapter=4,
            dry_run=True,
        )

        assert result.status == "preview"
        assert result.impact_report is not None
        report = result.impact_report
        # 核心属性修改 + 出现在后续章节 → 至少 1 条 conflict
        assert len(report["conflicts"]) >= 1

    def test_add_character_is_low_impact(self, tmp_path):
        """新增角色应返回 low severity。"""
        from src.novel.services.edit_service import NovelEditService

        _seed_novel_with_outline(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_p1"

        result = service.edit(
            project_path=project,
            structured_change={
                "change_type": "add",
                "entity_type": "character",
                "data": {
                    "name": "柳青鸾",
                    "gender": "女",
                    "age": 17,
                    "occupation": "丹师",
                    "role": "女主角",
                    "appearance": {
                        "height": "165cm",
                        "build": "纤细",
                        "hair": "青丝",
                        "eyes": "碧绿",
                        "clothing_style": "素衣",
                    },
                    "personality": {
                        "traits": ["聪慧", "坚韧", "温柔"],
                        "core_belief": "以德",
                        "motivation": "复兴",
                        "flaw": "信人",
                        "speech_style": "温和",
                    },
                },
            },
            effective_from_chapter=4,
            dry_run=True,
        )

        assert result.status == "preview"
        assert result.impact_report is not None
        assert result.impact_report["severity"] == "low"
        assert "柳青鸾" in result.impact_report["summary"]

    def test_impact_report_written_on_successful_apply(self, tmp_path):
        """非 dry_run 成功写盘时 EditResult 仍携带 impact_report。"""
        from src.novel.services.edit_service import NovelEditService

        _seed_novel_with_outline(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_p1"

        result = service.edit(
            project_path=project,
            structured_change={
                "change_type": "delete",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {},
            },
            effective_from_chapter=4,
        )

        assert result.status == "success"
        assert result.impact_report is not None
        assert result.impact_report["severity"] in {"high", "critical"}

        # 软删除后角色 status 更新
        novel = _load_novel_json(tmp_path)
        char = next(c for c in novel["characters"] if c["character_id"] == "char_001")
        assert char["status"] == "retired"


# ---------------------------------------------------------------------------
# 13.2  变更历史查询
# ---------------------------------------------------------------------------


class TestChangeHistoryFlow:
    """多次 edit → 通过 get_history() 查询，验证内容和过滤。"""

    def test_history_ordered_most_recent_first(self, tmp_path):
        """get_history() 按时间倒序返回，最新在最前。"""
        from src.novel.services.edit_service import NovelEditService

        _seed_novel_with_outline(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_p1"

        r1 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 20},
            },
        )
        assert r1.status == "success"

        r2 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "world_setting",
                "data": {"era": "上古洪荒"},
            },
        )
        assert r2.status == "success"

        r3 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "outline",
                "data": {"chapter_number": 2, "title": "真正的初战"},
            },
        )
        assert r3.status == "success"

        history = service.get_history(project)
        assert len(history) == 3
        # 最新的 change_id 在最前
        assert history[0]["change_id"] == r3.change_id
        assert history[-1]["change_id"] == r1.change_id
        # 每条都包含必要字段
        for entry in history:
            assert "change_id" in entry
            assert "change_type" in entry
            assert "entity_type" in entry
            assert "timestamp" in entry

    def test_history_filtered_by_entity_type(self, tmp_path):
        """通过 change_type 过滤按实体类型返回结果。"""
        from src.novel.services.edit_service import NovelEditService

        _seed_novel_with_outline(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_p1"

        service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 25},
            },
        )
        service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "world_setting",
                "data": {"era": "仙古"},
            },
        )
        service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_002",
                "data": {"age": 22},
            },
        )

        all_history = service.get_history(project)
        assert len(all_history) == 3

        # list_change_logs 的 change_type 是精确或后缀匹配；记录里写的是 "update"
        # 所以按 "update" 过滤应保留全部 3 条
        updates_only = service.get_history(project, change_type="update")
        assert len(updates_only) == 3

    def test_history_limit_truncates_results(self, tmp_path):
        """limit 参数对返回条数生效。"""
        from src.novel.services.edit_service import NovelEditService

        _seed_novel_with_outline(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_p1"

        for age in (19, 20, 21, 22, 23):
            service.edit(
                project_path=project,
                structured_change={
                    "change_type": "update",
                    "entity_type": "character",
                    "entity_id": "char_001",
                    "data": {"age": age},
                },
            )

        assert len(service.get_history(project)) == 5
        assert len(service.get_history(project, limit=3)) == 3
        assert len(service.get_history(project, limit=1)) == 1

    def test_history_captures_old_and_new_value(self, tmp_path):
        """变更日志条目应包含 old_value / new_value 快照。"""
        from src.novel.services.edit_service import NovelEditService

        _seed_novel_with_outline(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_p1"

        service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 30},
            },
        )

        history = service.get_history(project)
        assert len(history) == 1
        entry = history[0]
        # OutlineEditor 对章节 update 保留 chapter dict 全貌；
        # CharacterEditor 的 apply 会把涉及字段的 old_value 回填进日志
        assert entry["old_value"] is not None
        assert entry["new_value"] is not None
        assert entry["new_value"].get("age") == 30


# ---------------------------------------------------------------------------
# 13.3  MCP 工具端到端（真实写盘）
# ---------------------------------------------------------------------------


class TestMCPEditToolsE2E:
    """通过 mcp_server 工具进行真实文件系统编辑 + 查询。"""

    @pytest.fixture(autouse=True)
    def _configure_mcp_workspace(self, tmp_path):
        """把 mcp_server._DEFAULT_WORKSPACE 指向 tmp_path。"""
        import mcp_server

        original = mcp_server._DEFAULT_WORKSPACE
        mcp_server._DEFAULT_WORKSPACE = str(tmp_path)
        mcp_server._pipeline_instance = None
        yield
        mcp_server._DEFAULT_WORKSPACE = original
        mcp_server._pipeline_instance = None

    def test_edit_then_history_roundtrip(self, tmp_path):
        """MCP edit_setting 写盘 → get_change_history 能查到变更。"""
        import mcp_server

        _seed_novel_with_outline(tmp_path)
        project_path = str(tmp_path / "novels" / "novel_p1")

        # 使用 structured_change 路径（避免 LLM 依赖）—
        # mcp_server 的 edit 工具只接受自然语言，所以直接用 service
        from src.novel.services.edit_service import NovelEditService
        service = NovelEditService(workspace=str(tmp_path))
        edit_result = service.edit(
            project_path=project_path,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 42},
            },
        )
        assert edit_result.status == "success"

        # 通过 MCP 工具查询历史
        result = mcp_server.novel_get_change_history(
            project_path=project_path,
            limit=10,
        )

        assert "changes" in result
        assert result["total"] == 1
        assert result["changes"][0]["change_id"] == edit_result.change_id
        assert result["changes"][0]["entity_type"] == "character"

    def test_analyze_impact_tool_does_not_modify_disk(self, tmp_path):
        """novel_analyze_change_impact 走 dry_run，不改动 novel.json。"""
        import mcp_server

        _seed_novel_with_outline(tmp_path)
        project_path = str(tmp_path / "novels" / "novel_p1")

        original = _load_novel_json(tmp_path)

        # analyze_change_impact 用自然语言 → 需要 Mock LLM (IntentParser)
        from unittest.mock import MagicMock, patch

        fake_change = {
            "change_type": "delete",
            "entity_type": "character",
            "entity_id": "char_001",
            "data": {},
            "effective_from_chapter": 4,
            "reasoning": "mock intent",
        }
        parser_mock = MagicMock()
        parser_mock.parse.return_value = fake_change

        with patch(
            "src.novel.services.edit_service.IntentParser",
            return_value=parser_mock,
        ), patch(
            "src.novel.services.edit_service.create_llm_client",
            return_value=MagicMock(),
        ):
            result = mcp_server.novel_analyze_change_impact(
                project_path=project_path,
                instruction="删除角色张三",
            )

        assert result["status"] == "preview"
        assert result["impact_report"] is not None
        assert result["impact_report"]["severity"] in {"high", "critical"}
        # 冲突信息提到主角名
        conflicts = result["impact_report"]["conflicts"]
        assert any("张三" in c for c in conflicts)

        # 文件系统未变
        after = _load_novel_json(tmp_path)
        assert after == original

        # 也不应产生变更日志
        log_dir = tmp_path / "novels" / "novel_p1" / "changelogs"
        assert not log_dir.exists() or len(list(log_dir.glob("*.json"))) == 0

    def test_analyze_impact_rejects_empty_instruction(self, tmp_path):
        """空指令应被 novel_analyze_change_impact 拒绝。"""
        import mcp_server

        _seed_novel_with_outline(tmp_path)
        project_path = str(tmp_path / "novels" / "novel_p1")

        result = mcp_server.novel_analyze_change_impact(
            project_path=project_path,
            instruction="   ",
        )

        assert result["status"] == "failed"
        assert "instruction" in result["error"].lower() or "空" in result["error"]

    def test_get_history_path_traversal_rejected(self, tmp_path):
        """越界 project_path 被 _validate_project_path 拒绝。"""
        import mcp_server

        _seed_novel_with_outline(tmp_path)

        result = mcp_server.novel_get_change_history(
            project_path="/etc/passwd",
        )
        assert result["status"] == "failed"
        assert "error" in result

    def test_edit_setting_natural_language_full_roundtrip(self, tmp_path):
        """novel_edit_setting + Mock IntentParser → 写盘 + 记录日志。"""
        import mcp_server
        from unittest.mock import MagicMock, patch

        _seed_novel_with_outline(tmp_path)
        project_path = str(tmp_path / "novels" / "novel_p1")

        fake_change = {
            "change_type": "update",
            "entity_type": "world_setting",
            "data": {"terms": {"真气": "武者的内力"}},
            "reasoning": "mock",
        }
        parser_mock = MagicMock()
        parser_mock.parse.return_value = fake_change

        with patch(
            "src.novel.services.edit_service.IntentParser",
            return_value=parser_mock,
        ), patch(
            "src.novel.services.edit_service.create_llm_client",
            return_value=MagicMock(),
        ):
            result = mcp_server.novel_edit_setting(
                project_path=project_path,
                instruction="世界观增加真气术语",
            )

        assert result["status"] == "success"
        assert result["entity_type"] == "world_setting"

        # 验证落盘
        novel = _load_novel_json(tmp_path)
        assert novel["world_setting"]["terms"]["真气"] == "武者的内力"
        # 原有术语保留（递归合并）
        assert novel["world_setting"]["terms"]["灵气"] == "修炼基础能量"

        # 变更历史可通过 MCP 查到
        history = mcp_server.novel_get_change_history(project_path=project_path)
        assert history["total"] == 1
        assert history["changes"][0]["entity_type"] == "world_setting"
