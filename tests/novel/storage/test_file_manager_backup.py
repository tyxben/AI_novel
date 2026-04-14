"""测试 FileManager 备份和变更日志功能"""

from __future__ import annotations

import json
import time

import pytest

from src.novel.storage.file_manager import FileManager


# ========== Fixtures ==========


@pytest.fixture
def fm(tmp_path):
    """创建临时 FileManager 实例"""
    return FileManager(str(tmp_path))


@pytest.fixture
def novel_id():
    return "test_novel_001"


@pytest.fixture
def fm_with_novel(fm, novel_id):
    """带有已保存 novel.json 的 FileManager"""
    novel_data = {
        "novel_id": novel_id,
        "title": "测试小说",
        "genre": "玄幻",
        "characters": [{"name": "李明", "character_id": "char_1"}],
        "current_chapter": 5,
    }
    fm.save_novel(novel_id, novel_data)
    return fm


# ========== save_backup 测试 ==========


class TestSaveBackup:
    def test_creates_backup_file(self, fm_with_novel, novel_id):
        """备份文件应被正确创建"""
        backup_path = fm_with_novel.save_backup(novel_id)

        assert backup_path.exists()
        assert "novel_backup_" in backup_path.name
        assert backup_path.suffix == ".json"
        assert backup_path.parent.name == "revisions"

    def test_backup_content_matches_original(self, fm_with_novel, novel_id):
        """备份内容应与原始 novel.json 一致"""
        backup_path = fm_with_novel.save_backup(novel_id)

        original = fm_with_novel.load_novel(novel_id)
        with open(backup_path, encoding="utf-8") as f:
            backup = json.load(f)

        assert backup == original

    def test_backup_timestamp_format(self, fm_with_novel, novel_id):
        """备份文件名应包含 YYYYMMDD_HHMMSS 格式的时间戳"""
        backup_path = fm_with_novel.save_backup(novel_id)

        # 文件名: novel_backup_20260324_123456.json
        stem = backup_path.stem
        assert stem.startswith("novel_backup_")
        ts_part = stem.replace("novel_backup_", "")
        # 验证格式合法（不会抛异常）
        from datetime import datetime

        datetime.strptime(ts_part, "%Y%m%d_%H%M%S_%f")

    def test_multiple_backups_coexist(self, fm_with_novel, novel_id):
        """多次备份应共存"""
        p1 = fm_with_novel.save_backup(novel_id)
        p2 = fm_with_novel.save_backup(novel_id)

        assert p1.exists()
        assert p2.exists()
        assert p1.name != p2.name

    def test_raises_if_novel_not_exists(self, fm):
        """novel.json 不存在时应抛出 FileNotFoundError"""
        with pytest.raises(FileNotFoundError, match="novel.json 不存在"):
            fm.save_backup("nonexistent_novel")


# ========== _cleanup_old_backups 测试 ==========


class TestCleanupOldBackups:
    def test_cleanup_keeps_recent(self, fm_with_novel, novel_id):
        """清理应保留最近 keep 个备份"""
        rev_dir = fm_with_novel._novel_dir(novel_id) / "revisions"
        rev_dir.mkdir(parents=True, exist_ok=True)

        # 手动创建 25 个备份文件
        for i in range(25):
            ts = f"20260101_{i:06d}"
            path = rev_dir / f"novel_backup_{ts}.json"
            path.write_text("{}", encoding="utf-8")

        fm_with_novel._cleanup_old_backups(novel_id, keep=20)

        remaining = sorted(rev_dir.glob("novel_backup_*.json"))
        assert len(remaining) == 20
        # 应保留最新的 20 个（排序后最后 20 个）
        assert remaining[0].name == "novel_backup_20260101_000005.json"

    def test_cleanup_noop_if_under_limit(self, fm_with_novel, novel_id):
        """不足 keep 个时不删除"""
        rev_dir = fm_with_novel._novel_dir(novel_id) / "revisions"
        rev_dir.mkdir(parents=True, exist_ok=True)

        for i in range(5):
            path = rev_dir / f"novel_backup_20260101_{i:06d}.json"
            path.write_text("{}", encoding="utf-8")

        fm_with_novel._cleanup_old_backups(novel_id, keep=20)

        remaining = list(rev_dir.glob("novel_backup_*.json"))
        assert len(remaining) == 5

    def test_cleanup_empty_dir(self, fm_with_novel, novel_id):
        """空目录时不报错"""
        fm_with_novel._cleanup_old_backups(novel_id, keep=20)

    def test_cleanup_nonexistent_dir(self, fm, novel_id):
        """revisions 目录不存在时不报错"""
        fm._cleanup_old_backups(novel_id, keep=20)

    def test_does_not_delete_chapter_revisions(self, fm_with_novel, novel_id):
        """不应删除章节修订文件（仅删除 novel_backup_*）"""
        rev_dir = fm_with_novel._novel_dir(novel_id) / "revisions"
        rev_dir.mkdir(parents=True, exist_ok=True)

        # 创建章节修订文件
        chapter_rev = rev_dir / "chapter_001_rev1.txt"
        chapter_rev.write_text("章节内容", encoding="utf-8")

        # 创建 25 个备份
        for i in range(25):
            path = rev_dir / f"novel_backup_20260101_{i:06d}.json"
            path.write_text("{}", encoding="utf-8")

        fm_with_novel._cleanup_old_backups(novel_id, keep=20)

        # 章节修订文件不受影响
        assert chapter_rev.exists()
        # 备份被清理到 20 个
        assert len(list(rev_dir.glob("novel_backup_*.json"))) == 20


# ========== save_change_log 测试 ==========


class TestSaveChangeLog:
    def test_saves_changelog_file(self, fm, novel_id):
        """变更日志应被正确保存"""
        entry = {
            "change_id": "chg_001",
            "change_type": "add",
            "entity_type": "character",
            "data": {"name": "柳青鸾"},
        }
        path = fm.save_change_log(novel_id, entry)

        assert path.exists()
        assert path.name == "chg_001.json"
        assert path.parent.name == "changelogs"

    def test_saved_content_correct(self, fm, novel_id):
        """保存的 JSON 内容应正确"""
        entry = {
            "change_id": "chg_002",
            "change_type": "update",
            "entity_type": "outline",
            "data": {"chapter_number": 5, "mood": "大爽"},
        }
        path = fm.save_change_log(novel_id, entry)

        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded["change_id"] == "chg_002"
        assert loaded["change_type"] == "update"
        assert loaded["data"]["mood"] == "大爽"

    def test_creates_changelogs_dir(self, fm, novel_id):
        """应自动创建 changelogs/ 目录"""
        entry = {"change_id": "chg_003", "change_type": "delete"}
        path = fm.save_change_log(novel_id, entry)

        assert path.parent.exists()
        assert path.parent.name == "changelogs"

    def test_missing_change_id_uses_unknown(self, fm, novel_id):
        """缺少 change_id 时使用 'unknown'"""
        entry = {"change_type": "add"}
        path = fm.save_change_log(novel_id, entry)

        assert path.name == "unknown.json"

    def test_overwrites_existing(self, fm, novel_id):
        """相同 change_id 应覆盖"""
        entry_v1 = {"change_id": "chg_dup", "version": 1}
        entry_v2 = {"change_id": "chg_dup", "version": 2}

        fm.save_change_log(novel_id, entry_v1)
        path = fm.save_change_log(novel_id, entry_v2)

        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["version"] == 2


# ========== list_change_logs 测试 ==========


class TestListChangeLogs:
    def test_list_empty_directory(self, fm, novel_id):
        """空目录返回空列表"""
        result = fm.list_change_logs(novel_id)
        assert result == []

    def test_list_nonexistent_directory(self, fm):
        """changelogs 目录不存在时返回空列表"""
        result = fm.list_change_logs("nonexistent_novel")
        assert result == []

    def test_list_returns_entries(self, fm, novel_id):
        """应返回所有变更日志"""
        for i in range(3):
            entry = {"change_id": f"chg_{i}", "index": i}
            fm.save_change_log(novel_id, entry)

        result = fm.list_change_logs(novel_id)
        assert len(result) == 3

    def test_list_respects_limit(self, fm, novel_id):
        """应遵守 limit 参数"""
        for i in range(10):
            entry = {"change_id": f"chg_{i:03d}", "index": i}
            fm.save_change_log(novel_id, entry)

        result = fm.list_change_logs(novel_id, limit=3)
        assert len(result) == 3

    def test_list_ordered_by_mtime_desc(self, fm, novel_id):
        """应按修改时间倒序排列"""
        # 创建3个日志并设置不同的修改时间
        entries = []
        for i in range(3):
            entry = {"change_id": f"chg_order_{i}", "order": i}
            path = fm.save_change_log(novel_id, entry)
            entries.append(path)

        # 手动修改 mtime 使得 chg_order_2 最新, chg_order_0 最旧
        import os

        for i, p in enumerate(entries):
            # 设置 mtime: 第一个文件最旧
            os.utime(p, (1000000 + i * 100, 1000000 + i * 100))

        result = fm.list_change_logs(novel_id)
        assert len(result) == 3
        # 最新的排在前面
        assert result[0]["change_id"] == "chg_order_2"
        assert result[2]["change_id"] == "chg_order_0"

    def test_change_type_filter_applied_before_limit(self, fm, novel_id):
        """过滤必须在截断前执行，否则旧的匹配记录会被新的非匹配记录挤掉。"""
        # 先写 5 条非目标类型（时间较早），再写 2 条目标类型（时间较晚）
        # 然后再写 20 条非目标类型（时间最晚）— 模拟用户记忆中匹配条目更老
        import os

        all_paths = []
        for i in range(5):
            p = fm.save_change_log(
                novel_id, {"change_id": f"old_{i}", "change_type": "update_outline"}
            )
            all_paths.append((p, 1000 + i))
        for i in range(2):
            p = fm.save_change_log(
                novel_id, {"change_id": f"target_{i}", "change_type": "add_character"}
            )
            all_paths.append((p, 2000 + i))
        for i in range(20):
            p = fm.save_change_log(
                novel_id, {"change_id": f"new_{i}", "change_type": "update_outline"}
            )
            all_paths.append((p, 3000 + i))
        for p, t in all_paths:
            os.utime(p, (t, t))

        # limit=5, 不过滤 → 只会看到最新 5 条 update_outline, 目标类型被挤掉
        result_no_filter = fm.list_change_logs(novel_id, limit=5)
        target_in_unfiltered = [
            e for e in result_no_filter if e["change_type"] == "add_character"
        ]
        assert target_in_unfiltered == []

        # limit=5, 过滤 add_character → 必须返回 2 条目标记录
        result = fm.list_change_logs(
            novel_id, limit=5, change_type="add_character"
        )
        assert len(result) == 2
        assert all(e["change_type"] == "add_character" for e in result)

    def test_change_type_suffix_match(self, fm, novel_id):
        """change_type='character' 应匹配 add_character / delete_character 等。"""
        fm.save_change_log(
            novel_id, {"change_id": "c1", "change_type": "add_character"}
        )
        fm.save_change_log(
            novel_id, {"change_id": "c2", "change_type": "delete_character"}
        )
        fm.save_change_log(
            novel_id, {"change_id": "c3", "change_type": "update_outline"}
        )

        result = fm.list_change_logs(novel_id, change_type="character")
        ids = {e["change_id"] for e in result}
        assert ids == {"c1", "c2"}


# ========== load_change_log 测试 ==========


class TestLoadChangeLog:
    def test_load_existing(self, fm, novel_id):
        """应正确加载已保存的变更日志"""
        entry = {
            "change_id": "chg_load_1",
            "change_type": "add",
            "entity_type": "character",
        }
        fm.save_change_log(novel_id, entry)

        loaded = fm.load_change_log(novel_id, "chg_load_1")
        assert loaded is not None
        assert loaded["change_id"] == "chg_load_1"
        assert loaded["change_type"] == "add"
        assert loaded["entity_type"] == "character"

    def test_load_nonexistent_returns_none(self, fm, novel_id):
        """不存在的变更日志应返回 None"""
        result = fm.load_change_log(novel_id, "nonexistent_id")
        assert result is None

    def test_load_from_nonexistent_novel(self, fm):
        """不存在的小说 ID 应返回 None"""
        result = fm.load_change_log("nonexistent_novel", "any_id")
        assert result is None
