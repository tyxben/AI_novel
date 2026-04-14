"""NovelEditService.rollback() 测试。

覆盖：
- add / update / delete character 的回滚
- add / update outline 的回滚
- update world_setting 的回滚
- 依赖检查 + force=True 覆盖
- 错误路径：找不到变更、不支持的类型、回滚 rollback 自身
- 回滚本身被记录为新日志条目
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.novel.services.edit_service import NovelEditService


# ---------------------------------------------------------------------------
# Shared seed (与 integration/test_edit_flow_p1.py 独立但结构一致)
# ---------------------------------------------------------------------------


def _seed_novel(workspace: Path, novel_id: str = "novel_rb") -> dict:
    novel_dir = workspace / "novels" / novel_id
    novel_dir.mkdir(parents=True)

    novel_data = {
        "novel_id": novel_id,
        "title": "回滚测试",
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
                    "hair": "黑",
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
        ],
        "world_setting": {
            "era": "古代",
            "location": "九州",
            "rules": ["天道"],
            "terms": {"灵气": "能量"},
        },
        "outline": {
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "初入门",
                    "goal": "背景",
                    "key_events": ["入门"],
                },
            ],
        },
        "config": {"llm": {"provider": "auto"}},
    }

    with open(novel_dir / "novel.json", "w", encoding="utf-8") as f:
        json.dump(novel_data, f, ensure_ascii=False, indent=2)

    return novel_data


def _load_novel(workspace: Path, novel_id: str = "novel_rb") -> dict:
    with open(
        workspace / "novels" / novel_id / "novel.json", encoding="utf-8"
    ) as f:
        return json.load(f)


def _new_char_data(name: str, age: int = 20) -> dict:
    return {
        "name": name,
        "gender": "女",
        "age": age,
        "occupation": "剑客",
        "role": "配角",
        "appearance": {
            "height": "170cm",
            "build": "纤细",
            "hair": "长",
            "eyes": "蓝",
            "clothing_style": "白",
        },
        "personality": {
            "traits": ["聪慧", "坚韧", "温柔"],
            "core_belief": "友",
            "motivation": "护家",
            "flaw": "信人",
            "speech_style": "温和",
        },
    }


# ---------------------------------------------------------------------------
# Character rollback
# ---------------------------------------------------------------------------


class TestRollbackCharacter:
    def test_rollback_add_character_removes_entity(self, tmp_path):
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_rb"

        r1 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "add",
                "entity_type": "character",
                "data": _new_char_data("柳青鸾"),
            },
        )
        assert r1.status == "success"
        assert any(
            c["name"] == "柳青鸾"
            for c in _load_novel(tmp_path)["characters"]
        )

        rb = service.rollback(project, r1.change_id)

        assert rb.status == "success"
        assert rb.change_type == "rollback"
        assert rb.entity_type == "character"

        novel = _load_novel(tmp_path)
        names = [c["name"] for c in novel["characters"]]
        assert "柳青鸾" not in names
        assert "张三" in names  # 未波及原角色

    def test_rollback_update_character_restores_old_values(self, tmp_path):
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_rb"

        r1 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 99, "occupation": "长老"},
            },
        )
        assert r1.status == "success"

        # 确认修改生效
        char = next(
            c for c in _load_novel(tmp_path)["characters"]
            if c["character_id"] == "char_001"
        )
        assert char["age"] == 99
        assert char["occupation"] == "长老"

        rb = service.rollback(project, r1.change_id)
        assert rb.status == "success"

        char_after = next(
            c for c in _load_novel(tmp_path)["characters"]
            if c["character_id"] == "char_001"
        )
        assert char_after["age"] == 18
        assert char_after["occupation"] == "修炼者"

    def test_rollback_delete_character_restores_active(self, tmp_path):
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_rb"

        r1 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "delete",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {},
            },
            effective_from_chapter=4,
        )
        assert r1.status == "success"

        char = next(
            c for c in _load_novel(tmp_path)["characters"]
            if c["character_id"] == "char_001"
        )
        assert char["status"] == "retired"

        rb = service.rollback(project, r1.change_id)
        assert rb.status == "success"

        char_after = next(
            c for c in _load_novel(tmp_path)["characters"]
            if c["character_id"] == "char_001"
        )
        assert char_after["status"] == "active"


# ---------------------------------------------------------------------------
# Outline rollback
# ---------------------------------------------------------------------------


class TestRollbackOutline:
    def test_rollback_add_chapter_removes_it(self, tmp_path):
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_rb"

        r1 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "add",
                "entity_type": "outline",
                "data": {
                    "chapter_number": 5,
                    "title": "突破",
                    "goal": "境界提升",
                    "key_events": ["悟道"],
                },
            },
        )
        assert r1.status == "success"

        nums_before = [
            c["chapter_number"]
            for c in _load_novel(tmp_path)["outline"]["chapters"]
        ]
        assert 5 in nums_before

        rb = service.rollback(project, r1.change_id)
        assert rb.status == "success"

        nums_after = [
            c["chapter_number"]
            for c in _load_novel(tmp_path)["outline"]["chapters"]
        ]
        assert 5 not in nums_after
        assert 1 in nums_after  # 原有章节保留

    def test_rollback_update_chapter_restores_old(self, tmp_path):
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_rb"

        r1 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "outline",
                "data": {
                    "chapter_number": 1,
                    "title": "新的起点",
                    "goal": "新的目标",
                },
            },
        )
        assert r1.status == "success"

        ch_mod = next(
            c for c in _load_novel(tmp_path)["outline"]["chapters"]
            if c["chapter_number"] == 1
        )
        assert ch_mod["title"] == "新的起点"

        rb = service.rollback(project, r1.change_id)
        assert rb.status == "success"

        ch_after = next(
            c for c in _load_novel(tmp_path)["outline"]["chapters"]
            if c["chapter_number"] == 1
        )
        assert ch_after["title"] == "初入门"
        assert ch_after["goal"] == "背景"


# ---------------------------------------------------------------------------
# World setting rollback
# ---------------------------------------------------------------------------


class TestRollbackWorldSetting:
    def test_rollback_update_world_restores_full_snapshot(self, tmp_path):
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_rb"

        r1 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "world_setting",
                "data": {
                    "era": "上古",
                    "terms": {"真气": "内力"},
                },
            },
        )
        assert r1.status == "success"

        ws_mod = _load_novel(tmp_path)["world_setting"]
        assert ws_mod["era"] == "上古"
        assert ws_mod["terms"]["真气"] == "内力"

        rb = service.rollback(project, r1.change_id)
        assert rb.status == "success"

        ws_after = _load_novel(tmp_path)["world_setting"]
        assert ws_after["era"] == "古代"
        # terms 回到旧快照 —— 新添加的键被撤销
        assert "真气" not in ws_after["terms"]
        assert ws_after["terms"]["灵气"] == "能量"


# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------


class TestRollbackDependencyCheck:
    def test_rollback_blocked_by_subsequent_character_change(self, tmp_path):
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_rb"

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
        # 确保时间戳不同（日志按修改时间排序）
        time.sleep(0.01)

        r2 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 25},
            },
        )
        assert r2.status == "success"

        # 回滚 r1 应被 r2 依赖阻塞
        rb = service.rollback(project, r1.change_id)
        assert rb.status == "failed"
        assert rb.error is not None
        assert r2.change_id in rb.error

        # 文件系统未变（age 仍为 25）
        char = next(
            c for c in _load_novel(tmp_path)["characters"]
            if c["character_id"] == "char_001"
        )
        assert char["age"] == 25

    def test_rollback_force_bypasses_dependency_check(self, tmp_path):
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_rb"

        r1 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 20},
            },
        )
        time.sleep(0.01)
        service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 25},
            },
        )

        rb = service.rollback(project, r1.change_id, force=True)
        assert rb.status == "success"

        # force 后 age 恢复为 r1 的 old_value = 18
        char = next(
            c for c in _load_novel(tmp_path)["characters"]
            if c["character_id"] == "char_001"
        )
        assert char["age"] == 18

    def test_rollback_different_entity_not_blocked(self, tmp_path):
        """后续变更是别的 entity_id → 不阻塞当前回滚。"""
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_rb"

        r_add = service.edit(
            project_path=project,
            structured_change={
                "change_type": "add",
                "entity_type": "character",
                "data": _new_char_data("柳青鸾"),
            },
        )
        assert r_add.status == "success"
        new_id = r_add.new_value["character_id"]

        time.sleep(0.01)
        # 后续变更 -> 改的是 char_001，不是新增的 new_id
        service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 22},
            },
        )

        # 回滚 add 应成功（针对 new_id，与 char_001 无关）
        rb = service.rollback(project, r_add.change_id)
        assert rb.status == "success"

        names = [c["name"] for c in _load_novel(tmp_path)["characters"]]
        assert "柳青鸾" not in names


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestRollbackErrors:
    def test_rollback_nonexistent_change_id_fails(self, tmp_path):
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_rb"

        rb = service.rollback(project, "ghost_change_id")
        assert rb.status == "failed"
        assert "ghost_change_id" in rb.error

    def test_rollback_nonexistent_project_fails(self, tmp_path):
        service = NovelEditService(workspace=str(tmp_path))

        rb = service.rollback(
            project_path=f"{tmp_path}/novels/ghost_project",
            change_id="x",
        )
        assert rb.status == "failed"
        assert rb.error is not None

    def test_rollback_of_rollback_is_rejected(self, tmp_path):
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_rb"

        r1 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 30},
            },
        )
        assert r1.status == "success"

        rb1 = service.rollback(project, r1.change_id)
        assert rb1.status == "success"

        # 尝试回滚 rollback 本身 → 拒绝
        rb2 = service.rollback(project, rb1.change_id)
        assert rb2.status == "failed"
        assert "rollback" in rb2.error.lower()


# ---------------------------------------------------------------------------
# Rollback is itself a logged change
# ---------------------------------------------------------------------------


class TestRollbackIsLogged:
    def test_rollback_appends_changelog_entry(self, tmp_path):
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_rb"

        r1 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 30},
            },
        )
        assert r1.status == "success"
        time.sleep(0.01)

        rb = service.rollback(project, r1.change_id)
        assert rb.status == "success"

        history = service.get_history(project, limit=50)
        assert len(history) == 2

        # 最新条目是 rollback
        rollback_entry = history[0]
        assert rollback_entry["change_type"] == "rollback"
        assert rollback_entry["reverted_change_id"] == r1.change_id
        assert rollback_entry["change_id"] == rb.change_id
        # rollback 后的 new_value 是 r1 的 old_value
        assert rollback_entry["new_value"]["age"] == 18

    def test_rollback_creates_backup(self, tmp_path):
        _seed_novel(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_rb"

        r1 = service.edit(
            project_path=project,
            structured_change={
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 30},
            },
        )
        assert r1.status == "success"

        rev_dir = tmp_path / "novels" / "novel_rb" / "revisions"
        backups_before = list(rev_dir.glob("novel_backup_*.json"))
        service.rollback(project, r1.change_id)
        backups_after = list(rev_dir.glob("novel_backup_*.json"))

        assert len(backups_after) > len(backups_before)
