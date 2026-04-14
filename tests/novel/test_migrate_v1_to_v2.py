"""scripts/migrate_novel_v1_to_v2.py 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.migrate_novel_v1_to_v2 import (
    MigrationStats,
    migrate_novel,
    migrate_workspace,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_v1_novel(
    ws: Path,
    novel_id: str,
    characters: list[dict] | None = None,
    outline_chapters: list[dict] | None = None,
    world_setting: dict | None = None,
) -> Path:
    novel_dir = ws / "novels" / novel_id
    novel_dir.mkdir(parents=True)
    data = {
        "novel_id": novel_id,
        "title": f"{novel_id}标题",
        "genre": "玄幻",
        "characters": characters or [],
        "outline": {"chapters": outline_chapters or []},
        "world_setting": world_setting if world_setting is not None else {},
    }
    path = novel_dir / "novel.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# migrate_novel (single file)
# ---------------------------------------------------------------------------


class TestMigrateNovelSingle:
    def test_adds_version_fields_to_characters(self, tmp_path):
        stats = MigrationStats()
        path = _write_v1_novel(
            tmp_path,
            "n1",
            characters=[
                {"character_id": "c1", "name": "张三"},
                {"character_id": "c2", "name": "李四", "version": 2},
            ],
        )

        changed = migrate_novel(path, stats=stats)
        assert changed is True

        data = _load(path)
        # c1 缺的全补齐
        c1 = data["characters"][0]
        assert c1["effective_from_chapter"] == 1
        assert c1["deprecated_at_chapter"] is None
        assert c1["version"] == 1

        # c2 已有 version=2，保留；补 other
        c2 = data["characters"][1]
        assert c2["version"] == 2
        assert c2["effective_from_chapter"] == 1
        assert c2["deprecated_at_chapter"] is None

        assert stats.characters_updated == 2

    def test_adds_version_fields_to_outline_chapters(self, tmp_path):
        stats = MigrationStats()
        path = _write_v1_novel(
            tmp_path,
            "n1",
            outline_chapters=[
                {"chapter_number": 1, "title": "一"},
                {"chapter_number": 2, "title": "二"},
            ],
        )

        migrate_novel(path, stats=stats)
        data = _load(path)
        for ch in data["outline"]["chapters"]:
            assert ch["version"] == 1
            assert ch["effective_from_chapter"] == 1
            assert ch["deprecated_at_chapter"] is None
        assert stats.outlines_updated == 2

    def test_adds_version_fields_to_world_setting(self, tmp_path):
        stats = MigrationStats()
        path = _write_v1_novel(
            tmp_path,
            "n1",
            world_setting={"era": "古", "terms": {"灵气": "X"}},
        )

        migrate_novel(path, stats=stats)
        data = _load(path)
        ws = data["world_setting"]
        assert ws["version"] == 1
        assert ws["effective_from_chapter"] == 1
        assert ws["deprecated_at_chapter"] is None
        assert stats.world_updated == 1

    def test_creates_v1_backup_on_migrate(self, tmp_path):
        path = _write_v1_novel(
            tmp_path, "n1", characters=[{"character_id": "c1"}]
        )
        migrate_novel(path)
        backup = path.with_name("novel.v1.json")
        assert backup.exists()

        # 备份保留原始 v1 数据（无版本字段）
        v1_data = _load(backup)
        assert "version" not in v1_data["characters"][0]

    def test_idempotent_no_changes_on_v2_data(self, tmp_path):
        """已是 v2 数据二次运行应 no-op。"""
        path = _write_v1_novel(
            tmp_path,
            "n1",
            characters=[
                {
                    "character_id": "c1",
                    "effective_from_chapter": 1,
                    "deprecated_at_chapter": None,
                    "version": 1,
                }
            ],
            outline_chapters=[
                {
                    "chapter_number": 1,
                    "effective_from_chapter": 1,
                    "deprecated_at_chapter": None,
                    "version": 1,
                }
            ],
            world_setting={
                "effective_from_chapter": 1,
                "deprecated_at_chapter": None,
                "version": 1,
            },
        )
        stats = MigrationStats()
        changed = migrate_novel(path, stats=stats)
        assert changed is False
        assert stats.characters_updated == 0
        assert stats.outlines_updated == 0
        assert stats.world_updated == 0
        # 无备份产生
        assert not path.with_name("novel.v1.json").exists()

    def test_dry_run_does_not_modify(self, tmp_path):
        path = _write_v1_novel(
            tmp_path, "n1", characters=[{"character_id": "c1"}]
        )
        stats = MigrationStats()

        before = _load(path)
        changed = migrate_novel(path, dry_run=True, stats=stats)

        assert changed is True
        assert stats.characters_updated == 1
        # 文件未变
        after = _load(path)
        assert after == before
        assert not path.with_name("novel.v1.json").exists()

    def test_backup_not_duplicated_on_rerun(self, tmp_path):
        """v1 备份已存在时不再覆盖（保留最初快照）。"""
        path = _write_v1_novel(
            tmp_path, "n1", characters=[{"character_id": "c1"}]
        )
        migrate_novel(path)

        backup = path.with_name("novel.v1.json")
        original_mtime = backup.stat().st_mtime
        original_content = _load(backup)

        # 修改主文件并再迁移一次（当前已是 v2，no-op 不会创建备份）
        # 但如果我们手动重置为无版本然后再迁移，备份应保留首版本
        data = _load(path)
        for c in data["characters"]:
            c.pop("effective_from_chapter", None)
            c.pop("version", None)
            c["name"] = "modified"  # 标记
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        migrate_novel(path)
        # 备份内容仍是最早版本，不是含 "modified" 的版本
        assert _load(backup) == original_content

    def test_invalid_json_captured_in_errors(self, tmp_path):
        novel_dir = tmp_path / "novels" / "bad"
        novel_dir.mkdir(parents=True)
        path = novel_dir / "novel.json"
        path.write_text("not json{{{", encoding="utf-8")

        stats = MigrationStats()
        changed = migrate_novel(path, stats=stats)
        assert changed is False
        assert len(stats.errors) == 1
        assert "bad" in stats.errors[0]

    def test_non_dict_characters_ignored(self, tmp_path):
        """characters 列表中的非 dict 项跳过，不崩溃。"""
        path = _write_v1_novel(
            tmp_path,
            "n1",
            characters=[None, "garbage", {"character_id": "c1"}],
        )
        stats = MigrationStats()
        migrate_novel(path, stats=stats)
        assert stats.characters_updated == 1


# ---------------------------------------------------------------------------
# migrate_workspace
# ---------------------------------------------------------------------------


class TestMigrateWorkspace:
    def test_walks_multiple_projects(self, tmp_path):
        _v2_defaults = {
            "effective_from_chapter": 1,
            "deprecated_at_chapter": None,
            "version": 1,
        }
        _write_v1_novel(tmp_path, "a", characters=[{"character_id": "c1"}])
        _write_v1_novel(tmp_path, "b", characters=[{"character_id": "c2"}])
        # 已是 v2（所有实体 + world_setting 都有版本字段）
        _write_v1_novel(
            tmp_path,
            "c",
            characters=[{"character_id": "c3", **_v2_defaults}],
            world_setting={"era": "古", **_v2_defaults},
        )

        stats = migrate_workspace(tmp_path)
        assert stats.projects_scanned == 3
        assert stats.projects_migrated == 2
        assert stats.projects_already_v2 == 1
        assert stats.characters_updated == 2

    def test_missing_novels_dir_reports_error(self, tmp_path):
        stats = migrate_workspace(tmp_path)
        assert stats.projects_scanned == 0
        assert len(stats.errors) == 1
        assert "novels 目录不存在" in stats.errors[0]

    def test_skips_dirs_without_novel_json(self, tmp_path):
        (tmp_path / "novels" / "empty_dir").mkdir(parents=True)
        _write_v1_novel(
            tmp_path, "valid", characters=[{"character_id": "c1"}]
        )

        stats = migrate_workspace(tmp_path)
        assert stats.projects_scanned == 1
        assert stats.projects_migrated == 1

    def test_dry_run_across_workspace(self, tmp_path):
        path = _write_v1_novel(
            tmp_path, "a", characters=[{"character_id": "c1"}]
        )
        before = _load(path)
        stats = migrate_workspace(tmp_path, dry_run=True)
        after = _load(path)

        assert stats.projects_migrated == 1
        assert before == after
        assert not path.with_name("novel.v1.json").exists()
