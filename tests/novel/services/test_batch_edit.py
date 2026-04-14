"""NovelEditService.batch_edit() 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.novel.services.edit_service import NovelEditService


def _seed(workspace: Path, novel_id: str = "novel_bt") -> dict:
    d = workspace / "novels" / novel_id
    d.mkdir(parents=True)
    data = {
        "novel_id": novel_id,
        "title": "批量测试",
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
                {"chapter_number": 1, "title": "旧一", "goal": "开篇", "key_events": ["入门"]},
                {"chapter_number": 2, "title": "旧二", "goal": "成长", "key_events": ["拜师"]},
                {"chapter_number": 3, "title": "旧三", "goal": "冲突", "key_events": ["初战"]},
            ],
        },
        "config": {"llm": {"provider": "auto"}},
    }
    with open(d / "novel.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def _load(workspace: Path, novel_id: str = "novel_bt") -> dict:
    with open(workspace / "novels" / novel_id / "novel.json", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestBatchEditHappyPath:
    def test_all_success_persisted(self, tmp_path):
        _seed(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_bt"

        changes = [
            {
                "change_type": "update",
                "entity_type": "outline",
                "data": {"chapter_number": 1, "title": "新一"},
            },
            {
                "change_type": "update",
                "entity_type": "outline",
                "data": {"chapter_number": 2, "title": "新二"},
            },
            {
                "change_type": "update",
                "entity_type": "outline",
                "data": {"chapter_number": 3, "title": "新三"},
            },
        ]
        results = service.batch_edit(project, changes)

        assert len(results) == 3
        assert all(r.status == "success" for r in results)

        novel = _load(tmp_path)
        titles = {c["chapter_number"]: c["title"] for c in novel["outline"]["chapters"]}
        assert titles == {1: "新一", 2: "新二", 3: "新三"}

    def test_returns_independent_change_ids(self, tmp_path):
        _seed(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_bt"

        changes = [
            {
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 20},
            },
            {
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 22},
            },
        ]
        results = service.batch_edit(project, changes)
        assert results[0].change_id != results[1].change_id
        assert all(r.status == "success" for r in results)

    def test_each_change_logged_separately(self, tmp_path):
        _seed(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_bt"

        changes = [
            {
                "change_type": "update",
                "entity_type": "outline",
                "data": {"chapter_number": 1, "title": "A"},
            },
            {
                "change_type": "update",
                "entity_type": "outline",
                "data": {"chapter_number": 2, "title": "B"},
            },
        ]
        service.batch_edit(project, changes)

        history = service.get_history(project, limit=10)
        assert len(history) == 2


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


class TestBatchEditDryRun:
    def test_dry_run_does_not_modify_disk(self, tmp_path):
        _seed(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_bt"
        before = _load(tmp_path)

        changes = [
            {
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 99},
            },
            {
                "change_type": "update",
                "entity_type": "world_setting",
                "data": {"era": "上古"},
            },
        ]
        results = service.batch_edit(project, changes, dry_run=True)

        assert all(r.status == "preview" for r in results)
        after = _load(tmp_path)
        assert before == after


# ---------------------------------------------------------------------------
# Partial failure
# ---------------------------------------------------------------------------


class TestBatchEditPartialFailure:
    def test_bad_entity_type_does_not_abort_others(self, tmp_path):
        _seed(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_bt"

        changes = [
            # 1 ok
            {
                "change_type": "update",
                "entity_type": "outline",
                "data": {"chapter_number": 1, "title": "好的"},
            },
            # 2 bad entity_type
            {
                "change_type": "update",
                "entity_type": "ghost_type",
                "data": {"x": 1},
            },
            # 3 ok
            {
                "change_type": "update",
                "entity_type": "outline",
                "data": {"chapter_number": 2, "title": "好的二"},
            },
        ]
        results = service.batch_edit(project, changes)

        assert results[0].status == "success"
        assert results[1].status == "failed"
        assert "ghost_type" in results[1].error
        assert results[2].status == "success"

        # 成功的两条都已落盘
        novel = _load(tmp_path)
        titles = {c["chapter_number"]: c["title"] for c in novel["outline"]["chapters"]}
        assert titles[1] == "好的"
        assert titles[2] == "好的二"

    def test_stop_on_failure_skips_remaining(self, tmp_path):
        _seed(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_bt"

        changes = [
            {
                "change_type": "update",
                "entity_type": "outline",
                "data": {"chapter_number": 1, "title": "A"},
            },
            # 失败：不存在的章节
            {
                "change_type": "update",
                "entity_type": "outline",
                "data": {"chapter_number": 999, "title": "不存在"},
            },
            {
                "change_type": "update",
                "entity_type": "outline",
                "data": {"chapter_number": 2, "title": "C"},
            },
        ]
        results = service.batch_edit(project, changes, stop_on_failure=True)

        assert results[0].status == "success"
        assert results[1].status == "failed"
        assert results[2].status == "skipped"

        # 第三条未生效
        novel = _load(tmp_path)
        titles = {c["chapter_number"]: c["title"] for c in novel["outline"]["chapters"]}
        assert titles[1] == "A"
        assert titles[2] == "旧二"  # 保持原值

    def test_non_dict_item_reported_as_failed(self, tmp_path):
        _seed(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_bt"

        changes = [
            "不是字典",
            {
                "change_type": "update",
                "entity_type": "outline",
                "data": {"chapter_number": 1, "title": "OK"},
            },
        ]
        results = service.batch_edit(project, changes)
        assert results[0].status == "failed"
        assert "不是 dict" in results[0].error
        assert results[1].status == "success"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestBatchEditEdgeCases:
    def test_empty_changes_returns_empty_list(self, tmp_path):
        _seed(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_bt"
        assert service.batch_edit(project, []) == []

    def test_nonexistent_project_each_entry_fails(self, tmp_path):
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/ghost"
        changes = [
            {
                "change_type": "update",
                "entity_type": "outline",
                "data": {"chapter_number": 1, "title": "X"},
            },
            {
                "change_type": "update",
                "entity_type": "outline",
                "data": {"chapter_number": 2, "title": "Y"},
            },
        ]
        results = service.batch_edit(project, changes)
        assert len(results) == 2
        assert all(r.status == "failed" for r in results)

    def test_effective_from_chapter_passed_through(self, tmp_path):
        _seed(tmp_path)
        service = NovelEditService(workspace=str(tmp_path))
        project = f"{tmp_path}/novels/novel_bt"

        changes = [
            {
                "change_type": "delete",
                "entity_type": "character",
                "entity_id": "char_001",
                "effective_from_chapter": 8,
                "data": {},
            },
        ]
        results = service.batch_edit(project, changes)
        assert results[0].status == "success"
        assert results[0].effective_from_chapter == 8

        novel = _load(tmp_path)
        char = next(c for c in novel["characters"] if c["character_id"] == "char_001")
        assert char["deprecated_at_chapter"] == 8
