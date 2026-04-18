"""Phase 1-B: v2 → v3 迁移脚本测试。

覆盖：
- 补齐缺失字段（ChapterOutline.chapter_type / target_words，Volume 新字段）
- target_words 从 estimated_words 继承（若可用）
- 幂等：已是 v3 不再修改
- 备份：首次迁移落 novel.v2.json，已有备份不覆盖
- dry-run：不写盘但返回 True
- 空 workspace / 缺失 novels 目录的错误处理
- file_manager.load_novel 的内存兜底
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.migrate_novel_v2_to_v3 import (
    _apply_chapter_outline_defaults,
    _apply_volume_defaults,
    _needs_v3_migration,
    migrate_novel,
    migrate_workspace,
)


def _make_v2_novel() -> dict:
    """构造一个 v2 novel.json（已有 v1→v2 迁移过的版本字段，缺 v3 新字段）。"""
    return {
        "novel_id": "abc",
        "title": "test",
        "genre": "玄幻",
        "theme": "test",
        "target_words": 100000,
        "outline": {
            "template": "cyclic_upgrade",
            "main_storyline": {},
            "acts": [],
            "volumes": [],
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "第一章",
                    "goal": "G",
                    "key_events": ["E"],
                    "estimated_words": 2200,
                    "effective_from_chapter": 1,
                    "deprecated_at_chapter": None,
                    "version": 1,
                },
                {
                    "chapter_number": 2,
                    "title": "第二章",
                    "goal": "G",
                    "key_events": ["E"],
                    # 无 estimated_words → target_words 应为 None
                    "effective_from_chapter": 1,
                    "deprecated_at_chapter": None,
                    "version": 1,
                },
            ],
        },
        "volumes": [
            {
                "volume_number": 1,
                "title": "卷一",
                "chapters": [1, 2],
                "status": "writing",
            }
        ],
        "world_setting": {
            "era": "古代",
            "locations": [],
            "rules": [],
            "terminology": {},
            "effective_from_chapter": 1,
            "deprecated_at_chapter": None,
            "version": 1,
        },
        "characters": [],
    }


def _write_novel(tmp_path: Path, novel: dict, novel_id: str = "test") -> Path:
    novel_dir = tmp_path / "novels" / novel_id
    novel_dir.mkdir(parents=True, exist_ok=True)
    path = novel_dir / "novel.json"
    path.write_text(json.dumps(novel, ensure_ascii=False), encoding="utf-8")
    return path


class TestChapterOutlineDefaults:
    def test_adds_chapter_type_when_missing(self):
        ch = {"chapter_number": 1, "title": "x", "goal": "g", "key_events": ["e"]}
        assert _apply_chapter_outline_defaults(ch) is True
        assert ch["chapter_type"] == "buildup"

    def test_copies_target_words_from_estimated(self):
        ch = {
            "chapter_number": 1,
            "title": "x",
            "goal": "g",
            "key_events": ["e"],
            "estimated_words": 2200,
        }
        _apply_chapter_outline_defaults(ch)
        assert ch["target_words"] == 2200

    def test_out_of_range_estimated_falls_back_to_none(self):
        ch = {
            "chapter_number": 1,
            "title": "x",
            "goal": "g",
            "key_events": ["e"],
            "estimated_words": 50,  # out of 500-10000 range
        }
        _apply_chapter_outline_defaults(ch)
        assert ch["target_words"] is None

    def test_missing_estimated_words_defaults_to_none(self):
        ch = {"chapter_number": 1, "title": "x", "goal": "g", "key_events": ["e"]}
        _apply_chapter_outline_defaults(ch)
        assert ch["target_words"] is None

    def test_already_migrated_not_modified(self):
        ch = {
            "chapter_number": 1,
            "title": "x",
            "goal": "g",
            "key_events": ["e"],
            "chapter_type": "climax",
            "target_words": 3800,
        }
        assert _apply_chapter_outline_defaults(ch) is False
        assert ch["chapter_type"] == "climax"
        assert ch["target_words"] == 3800


class TestVolumeDefaults:
    def test_adds_all_new_fields(self):
        vol = {"volume_number": 1, "title": "卷一", "chapters": [1, 2, 3]}
        assert _apply_volume_defaults(vol) is True
        assert vol["volume_goal"] == ""
        assert vol["volume_outline"] == [1, 2, 3]  # 复制自 chapters
        assert vol["settlement"] is None
        assert vol["chapter_type_dist"] == {}

    def test_volume_outline_empty_when_chapters_missing(self):
        vol = {"volume_number": 1, "title": "卷一"}
        _apply_volume_defaults(vol)
        assert vol["volume_outline"] == []

    def test_already_migrated_not_modified(self):
        vol = {
            "volume_number": 1,
            "title": "卷一",
            "chapters": [1, 2],
            "volume_goal": "已设定",
            "volume_outline": [1, 2],
            "settlement": None,
            "chapter_type_dist": {"buildup": 2},
        }
        assert _apply_volume_defaults(vol) is False
        assert vol["volume_goal"] == "已设定"


class TestNeedsV3:
    def test_detects_missing_fields(self):
        novel = _make_v2_novel()
        assert _needs_v3_migration(novel) is True

    def test_returns_false_when_all_present(self):
        novel = _make_v2_novel()
        # 手动把字段补齐（模拟已迁移过）
        for ch in novel["outline"]["chapters"]:
            ch["chapter_type"] = "buildup"
            ch["target_words"] = None
        for v in novel["volumes"]:
            v["volume_goal"] = ""
            v["volume_outline"] = []
            v["settlement"] = None
            v["chapter_type_dist"] = {}
        assert _needs_v3_migration(novel) is False


class TestMigrateNovel:
    def test_migrates_chapter_outlines(self, tmp_path):
        novel = _make_v2_novel()
        path = _write_novel(tmp_path, novel)
        assert migrate_novel(path) is True

        data = json.loads(path.read_text(encoding="utf-8"))
        ch1 = data["outline"]["chapters"][0]
        ch2 = data["outline"]["chapters"][1]
        assert ch1["chapter_type"] == "buildup"
        assert ch1["target_words"] == 2200  # from estimated_words
        assert ch2["chapter_type"] == "buildup"
        assert ch2["target_words"] is None

    def test_migrates_volumes(self, tmp_path):
        novel = _make_v2_novel()
        path = _write_novel(tmp_path, novel)
        migrate_novel(path)

        data = json.loads(path.read_text(encoding="utf-8"))
        v = data["volumes"][0]
        assert v["volume_goal"] == ""
        assert v["volume_outline"] == [1, 2]
        assert v["settlement"] is None
        assert v["chapter_type_dist"] == {}

    def test_creates_v2_backup_on_first_run(self, tmp_path):
        novel = _make_v2_novel()
        path = _write_novel(tmp_path, novel)
        migrate_novel(path)

        backup = path.with_name("novel.v2.json")
        assert backup.exists()
        backup_data = json.loads(backup.read_text(encoding="utf-8"))
        # 备份是迁移前的原始内容（无 chapter_type 字段）
        assert "chapter_type" not in backup_data["outline"]["chapters"][0]

    def test_backup_not_overwritten_on_second_run(self, tmp_path):
        novel = _make_v2_novel()
        path = _write_novel(tmp_path, novel)
        migrate_novel(path)

        backup = path.with_name("novel.v2.json")
        first_mtime = backup.stat().st_mtime

        # 用"更新后"的 novel.json 再迁移一次（idempotent - 不应修改）
        # 但我们要确认：即使强制修改一个字段，备份也不会被二次覆盖
        data = json.loads(path.read_text(encoding="utf-8"))
        data["outline"]["chapters"][0].pop("chapter_type")
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        migrate_novel(path)

        second_mtime = backup.stat().st_mtime
        assert first_mtime == second_mtime

    def test_idempotent_second_run_no_changes(self, tmp_path):
        novel = _make_v2_novel()
        path = _write_novel(tmp_path, novel)
        assert migrate_novel(path) is True
        # 第二次：已 v3，返回 False
        assert migrate_novel(path) is False

    def test_dry_run_does_not_write(self, tmp_path):
        novel = _make_v2_novel()
        path = _write_novel(tmp_path, novel)
        original = path.read_text(encoding="utf-8")

        assert migrate_novel(path, dry_run=True) is True

        # 文件内容未改变
        assert path.read_text(encoding="utf-8") == original
        # 备份不创建
        assert not path.with_name("novel.v2.json").exists()

    def test_corrupted_json_recorded_as_error(self, tmp_path):
        novel_dir = tmp_path / "novels" / "bad"
        novel_dir.mkdir(parents=True)
        (novel_dir / "novel.json").write_text("{not valid json", encoding="utf-8")

        stats = migrate_workspace(tmp_path)
        assert len(stats.errors) >= 1
        assert "读取失败" in stats.errors[0]


class TestMigrateWorkspace:
    def test_missing_novels_dir_records_error(self, tmp_path):
        stats = migrate_workspace(tmp_path)
        assert stats.projects_scanned == 0
        assert any("novels 目录不存在" in e for e in stats.errors)

    def test_empty_workspace_no_errors(self, tmp_path):
        (tmp_path / "novels").mkdir()
        stats = migrate_workspace(tmp_path)
        assert stats.projects_scanned == 0
        assert stats.errors == []

    def test_multiple_novels_migrated(self, tmp_path):
        _write_novel(tmp_path, _make_v2_novel(), novel_id="a")
        _write_novel(tmp_path, _make_v2_novel(), novel_id="b")

        stats = migrate_workspace(tmp_path)
        assert stats.projects_scanned == 2
        assert stats.projects_migrated == 2
        assert stats.chapter_outlines_updated == 4  # 2 projects × 2 chapters
        assert stats.volumes_updated == 2

    def test_mixed_v2_and_v3_workspace(self, tmp_path):
        # 一个旧项目
        _write_novel(tmp_path, _make_v2_novel(), novel_id="old")

        # 一个已迁移的 v3 项目
        v3_novel = _make_v2_novel()
        for ch in v3_novel["outline"]["chapters"]:
            ch["chapter_type"] = "buildup"
            ch["target_words"] = None
        for v in v3_novel["volumes"]:
            v["volume_goal"] = ""
            v["volume_outline"] = []
            v["settlement"] = None
            v["chapter_type_dist"] = {}
        _write_novel(tmp_path, v3_novel, novel_id="new")

        stats = migrate_workspace(tmp_path)
        assert stats.projects_scanned == 2
        assert stats.projects_migrated == 1
        assert stats.projects_already_v3 == 1


class TestFileManagerMemoryBackfill:
    """验证 file_manager.load_novel 的内存兜底，不改动文件。"""

    def test_load_novel_backfills_missing_fields_in_memory(self, tmp_path):
        from src.novel.storage.file_manager import FileManager

        novel = _make_v2_novel()
        novel_dir = tmp_path / "novels" / "test"
        novel_dir.mkdir(parents=True)
        path = novel_dir / "novel.json"
        raw = json.dumps(novel, ensure_ascii=False)
        path.write_text(raw, encoding="utf-8")

        fm = FileManager(str(tmp_path))
        loaded = fm.load_novel("test")
        assert loaded is not None

        # 内存中已补齐
        ch = loaded["outline"]["chapters"][0]
        assert ch["chapter_type"] == "buildup"
        assert "target_words" in ch

        vol = loaded["volumes"][0]
        assert vol["volume_goal"] == ""
        assert vol["settlement"] is None
        assert vol["chapter_type_dist"] == {}
        assert vol["volume_outline"] == []

        # 磁盘文件未改动
        assert path.read_text(encoding="utf-8") == raw

    def test_load_nonexistent_returns_none(self, tmp_path):
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(tmp_path))
        assert fm.load_novel("nope") is None

    def test_different_volumes_do_not_share_default_containers(self, tmp_path):
        """内存兜底时两个 volume 应各自获得独立的默认容器（非共享引用）。"""
        from src.novel.storage.file_manager import FileManager

        novel = _make_v2_novel()
        novel["volumes"].append(
            {"volume_number": 2, "title": "卷二", "chapters": [3, 4]}
        )
        _write_novel(tmp_path, novel, novel_id="multi")

        fm = FileManager(str(tmp_path))
        loaded = fm.load_novel("multi")
        assert loaded is not None
        v1, v2 = loaded["volumes"]
        v1["chapter_type_dist"]["climax"] = 1
        v1["volume_outline"].append(999)
        assert v2["chapter_type_dist"] == {}
        assert v2["volume_outline"] == []


@pytest.mark.parametrize("dry_run", [True, False])
def test_main_exit_code_ok_on_empty_workspace(tmp_path, dry_run, monkeypatch, capsys):
    from scripts.migrate_novel_v2_to_v3 import main

    (tmp_path / "novels").mkdir()
    args = ["--workspace", str(tmp_path)]
    if dry_run:
        args.append("--dry-run")
    rc = main(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "扫描项目: 0" in out
