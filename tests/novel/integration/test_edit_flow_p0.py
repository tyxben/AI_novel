"""P0 集成测试：编辑服务端到端流程。

使用真实 FileManager（tmp_path），Mock LLM，验证完整编辑链路：
  创建项目数据 → 编辑 → 验证文件系统状态。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.novel.services.edit_service import EditResult, NovelEditService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_novel(workspace: Path, novel_id: str = "novel_test") -> dict:
    """在 workspace/novels/{novel_id}/ 下写入一份最小 novel.json，
    返回 novel_data dict。"""
    novel_dir = workspace / "novels" / novel_id
    novel_dir.mkdir(parents=True)

    novel_data = {
        "novel_id": novel_id,
        "title": "集成测试小说",
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
                "status": "active",
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
            },
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
                {
                    "chapter_number": 5,
                    "title": "突破关键",
                    "goal": "主角突破瓶颈",
                    "key_events": ["领悟剑意", "与师兄切磋"],
                    "involved_characters": ["char_001"],
                },
            ],
        },
        "config": {"llm": {"provider": "auto"}},
    }

    with open(novel_dir / "novel.json", "w", encoding="utf-8") as f:
        json.dump(novel_data, f, ensure_ascii=False, indent=2)

    return novel_data


def _load_novel_json(workspace: Path, novel_id: str = "novel_test") -> dict:
    """从文件系统重新加载 novel.json。"""
    path = workspace / "novels" / novel_id / "novel.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 7.1  端到端：添加角色
# ---------------------------------------------------------------------------

class TestAddCharacterE2E:
    """创建项目 → 通过 NovelEditService 添加角色 → 验证文件系统。"""

    def test_add_character_persisted(self, tmp_path):
        """添加角色后 novel.json 中应包含新角色。"""
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))

        result = service.edit(
            project_path=f"{tmp_path}/novels/novel_test",
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
                        "hair": "青丝及腰",
                        "eyes": "碧绿",
                        "clothing_style": "素衣",
                    },
                    "personality": {
                        "traits": ["聪慧", "坚韧", "温柔"],
                        "core_belief": "以德报怨",
                        "motivation": "复兴家族",
                        "flaw": "过于信任他人",
                        "speech_style": "温和有礼",
                    },
                },
            },
            effective_from_chapter=6,
        )

        assert result.status == "success"
        assert result.change_type == "add"
        assert result.entity_type == "character"
        assert result.new_value is not None
        assert result.new_value["name"] == "柳青鸾"
        assert result.effective_from_chapter == 6

        # 验证文件系统持久化
        novel = _load_novel_json(tmp_path)
        names = [c["name"] for c in novel["characters"]]
        assert "柳青鸾" in names
        assert "张三" in names  # 原有角色仍在

        # 新角色应有版本字段
        new_char = next(c for c in novel["characters"] if c["name"] == "柳青鸾")
        assert new_char["effective_from_chapter"] == 6
        assert new_char["version"] >= 1
        assert "character_id" in new_char

    def test_add_character_creates_backup(self, tmp_path):
        """添加操作前应创建备份。"""
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))

        service.edit(
            project_path=f"{tmp_path}/novels/novel_test",
            structured_change={
                "change_type": "add",
                "entity_type": "character",
                "data": {
                    "name": "王五",
                    "gender": "男",
                    "age": 30,
                    "occupation": "剑客",
                    "role": "配角",
                    "appearance": {
                        "height": "185cm",
                        "build": "魁梧",
                        "hair": "灰白短发",
                        "eyes": "灰色",
                        "clothing_style": "铁甲",
                    },
                    "personality": {
                        "traits": ["沉默", "忠诚", "果断"],
                        "core_belief": "守护",
                        "motivation": "赎罪",
                        "flaw": "不善言辞",
                        "speech_style": "简短",
                    },
                },
            },
        )

        rev_dir = tmp_path / "novels" / "novel_test" / "revisions"
        backups = list(rev_dir.glob("novel_backup_*.json"))
        assert len(backups) >= 1

    def test_add_character_creates_changelog(self, tmp_path):
        """添加操作应记录变更日志。"""
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))

        result = service.edit(
            project_path=f"{tmp_path}/novels/novel_test",
            structured_change={
                "change_type": "add",
                "entity_type": "character",
                "data": {
                    "name": "赵六",
                    "gender": "男",
                    "age": 45,
                    "occupation": "长老",
                    "role": "配角",
                    "appearance": {
                        "height": "170cm",
                        "build": "干瘦",
                        "hair": "花白",
                        "eyes": "浑浊",
                        "clothing_style": "道袍",
                    },
                    "personality": {
                        "traits": ["阴险", "多疑", "精明"],
                        "core_belief": "利益至上",
                        "motivation": "权力",
                        "flaw": "贪婪",
                        "speech_style": "阴阳怪气",
                    },
                },
            },
        )

        log_dir = tmp_path / "novels" / "novel_test" / "changelogs"
        logs = list(log_dir.glob("*.json"))
        assert len(logs) == 1

        with open(logs[0], encoding="utf-8") as f:
            entry = json.load(f)
        assert entry["change_id"] == result.change_id
        assert entry["change_type"] == "add"
        assert entry["entity_type"] == "character"
        assert entry["new_value"]["name"] == "赵六"


# ---------------------------------------------------------------------------
# 7.2  端到端：修改大纲
# ---------------------------------------------------------------------------

class TestModifyOutlineE2E:
    """修改章节大纲 → 验证持久化。"""

    def test_update_chapter_mood(self, tmp_path):
        """修改章节 title/goal 后 novel.json 应更新。"""
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))

        result = service.edit(
            project_path=f"{tmp_path}/novels/novel_test",
            structured_change={
                "change_type": "update",
                "entity_type": "outline",
                "data": {
                    "chapter_number": 1,
                    "title": "命运的起点",
                    "goal": "揭示主角隐藏血脉",
                },
            },
            effective_from_chapter=1,
        )

        assert result.status == "success"
        assert result.entity_type == "outline"

        # 验证文件系统
        novel = _load_novel_json(tmp_path)
        ch1 = next(
            c for c in novel["outline"]["chapters"]
            if c["chapter_number"] == 1
        )
        assert ch1["title"] == "命运的起点"
        assert ch1["goal"] == "揭示主角隐藏血脉"
        # 原有字段保留
        assert ch1["key_events"] == ["入门测试"]

    def test_add_new_chapter_outline(self, tmp_path):
        """新增章节大纲 → 插入并排序。"""
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))

        result = service.edit(
            project_path=f"{tmp_path}/novels/novel_test",
            structured_change={
                "change_type": "add",
                "entity_type": "outline",
                "data": {
                    "chapter_number": 3,
                    "title": "暗流涌动",
                    "goal": "引入反派势力",
                    "key_events": ["反派联盟成立"],
                },
            },
        )

        assert result.status == "success"

        novel = _load_novel_json(tmp_path)
        chapters = novel["outline"]["chapters"]
        numbers = [c["chapter_number"] for c in chapters]
        # 应按 chapter_number 排序
        assert numbers == sorted(numbers)
        assert 3 in numbers

    def test_update_nonexistent_chapter_fails(self, tmp_path):
        """修改不存在的章节号应失败。"""
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))

        result = service.edit(
            project_path=f"{tmp_path}/novels/novel_test",
            structured_change={
                "change_type": "update",
                "entity_type": "outline",
                "data": {
                    "chapter_number": 99,
                    "title": "不存在的章节",
                },
            },
        )

        assert result.status == "failed"
        assert "不存在" in result.error


# ---------------------------------------------------------------------------
# 7.3  端到端：删除角色（软删除）
# ---------------------------------------------------------------------------

class TestDeleteCharacterE2E:
    """软删除角色 → 验证 status + deprecated_at_chapter。"""

    def test_soft_delete_character(self, tmp_path):
        """软删除角色后 status=retired，角色仍在列表中。"""
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))

        result = service.edit(
            project_path=f"{tmp_path}/novels/novel_test",
            structured_change={
                "change_type": "delete",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {},
            },
            effective_from_chapter=6,
        )

        assert result.status == "success"
        assert result.change_type == "delete"

        # 验证文件系统
        novel = _load_novel_json(tmp_path)
        char = next(
            c for c in novel["characters"] if c["character_id"] == "char_001"
        )
        assert char["status"] == "retired"
        assert char["deprecated_at_chapter"] == 6

    def test_soft_delete_custom_status(self, tmp_path):
        """软删除时可指定自定义 status（如 deceased）。"""
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))

        result = service.edit(
            project_path=f"{tmp_path}/novels/novel_test",
            structured_change={
                "change_type": "delete",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"status": "deceased"},
            },
            effective_from_chapter=5,
        )

        assert result.status == "success"

        novel = _load_novel_json(tmp_path)
        char = next(
            c for c in novel["characters"] if c["character_id"] == "char_001"
        )
        assert char["status"] == "deceased"

    def test_delete_nonexistent_character_fails(self, tmp_path):
        """删除不存在的角色应失败。"""
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))

        result = service.edit(
            project_path=f"{tmp_path}/novels/novel_test",
            structured_change={
                "change_type": "delete",
                "entity_type": "character",
                "entity_id": "char_nonexistent",
                "data": {},
            },
        )

        assert result.status == "failed"
        assert "不存在" in result.error


# ---------------------------------------------------------------------------
# 额外：多步操作 + 历史查询
# ---------------------------------------------------------------------------

class TestMultiStepEditFlow:
    """多次编辑 → 查询历史 → 验证状态一致性。"""

    def test_sequential_edits_all_persisted(self, tmp_path):
        """连续 3 次编辑后 novel.json 包含所有变更。"""
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_test"

        # 1. 添加角色
        r1 = service.edit(
            project_path=project,
            structured_change={
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
            },
        )
        assert r1.status == "success"

        # 2. 更新世界观
        r2 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "world_setting",
                "data": {
                    "terms": {"真气": "武者内力来源"},
                },
            },
        )
        assert r2.status == "success"

        # 3. 修改大纲
        r3 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "outline",
                "data": {
                    "chapter_number": 2,
                    "title": "剑意初悟",
                },
            },
        )
        assert r3.status == "success"

        # 验证最终状态
        novel = _load_novel_json(tmp_path)
        names = [c["name"] for c in novel["characters"]]
        assert "李四" in names
        assert novel["world_setting"]["terms"]["真气"] == "武者内力来源"
        # 原有 terms 保留（递归合并）
        assert novel["world_setting"]["terms"]["灵气"] == "修炼基础能量"
        ch2 = next(
            c for c in novel["outline"]["chapters"] if c["chapter_number"] == 2
        )
        assert ch2["title"] == "剑意初悟"

    def test_history_reflects_all_edits(self, tmp_path):
        """变更历史应包含所有操作记录。"""
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_test"

        # 执行 2 次编辑
        service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 20},
            },
        )
        service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "world_setting",
                "data": {"era": "上古洪荒"},
            },
        )

        history = service.get_history(project)
        assert len(history) == 2
        types = {h["entity_type"] for h in history}
        assert types == {"character", "world_setting"}

    def test_dry_run_does_not_modify_file(self, tmp_path):
        """dry_run 不应改变文件系统状态。"""
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_test"

        original = _load_novel_json(tmp_path)

        result = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 99},
            },
            dry_run=True,
        )

        assert result.status == "preview"

        after = _load_novel_json(tmp_path)
        assert after == original

        # 不应产生备份和日志
        rev_dir = tmp_path / "novels" / "novel_test" / "revisions"
        assert not rev_dir.exists() or len(list(rev_dir.glob("*"))) == 0

    def test_edit_nonexistent_project_fails(self, tmp_path):
        """编辑不存在的项目应返回 failed。"""
        service = NovelEditService(workspace=str(tmp_path))

        result = service.edit(
            project_path=f"{tmp_path}/novels/ghost_project",
            structured_change={
                "change_type": "add",
                "entity_type": "character",
                "data": {"name": "幽灵"},
            },
        )

        assert result.status == "failed"
        assert "不存在" in result.error
