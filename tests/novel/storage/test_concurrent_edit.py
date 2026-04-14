"""FileManager 并发写锁测试。

使用 threading 模拟并发场景。"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from src.novel.storage.file_manager import (
    ConcurrentModificationError,
    FileManager,
)


pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="fcntl-based lock is Unix-only",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path) -> FileManager:
    fm = FileManager(str(tmp_path))
    novel_data = {
        "novel_id": "novel_lk",
        "title": "锁测试",
        "characters": [],
    }
    fm.save_novel("novel_lk", novel_data)
    return fm


# ---------------------------------------------------------------------------
# Basic lock behavior
# ---------------------------------------------------------------------------


class TestNovelLock:
    def test_sequential_saves_succeed(self, tmp_path):
        fm = _make_manager(tmp_path)
        for i in range(3):
            fm.save_novel("novel_lk", {"novel_id": "novel_lk", "rev": i})
        data = fm.load_novel("novel_lk")
        assert data["rev"] == 2

    def test_concurrent_save_raises(self, tmp_path):
        """当锁被持有时，第二次 save_novel 立即抛 ConcurrentModificationError。"""
        fm = _make_manager(tmp_path)

        lock_acquired = threading.Event()
        release_lock = threading.Event()

        def holder():
            with fm._novel_lock("novel_lk"):
                lock_acquired.set()
                release_lock.wait(timeout=5.0)

        t = threading.Thread(target=holder)
        t.start()
        try:
            assert lock_acquired.wait(timeout=2.0)

            with pytest.raises(ConcurrentModificationError) as exc_info:
                fm.save_novel("novel_lk", {"novel_id": "novel_lk", "x": 1})
            assert "novel_lk" in str(exc_info.value)

            # save_change_log 也被锁保护
            with pytest.raises(ConcurrentModificationError):
                fm.save_change_log(
                    "novel_lk",
                    {"change_id": "c1", "change_type": "update"},
                )

            # save_backup 同样
            with pytest.raises(ConcurrentModificationError):
                fm.save_backup("novel_lk")
        finally:
            release_lock.set()
            t.join(timeout=3.0)

    def test_lock_released_after_context(self, tmp_path):
        """锁使用完后立即可被下一个持有者获取。"""
        fm = _make_manager(tmp_path)

        with fm._novel_lock("novel_lk"):
            pass  # 进出立即释放

        # 再次 save 应成功（锁未遗留）
        fm.save_novel("novel_lk", {"novel_id": "novel_lk", "ok": True})
        assert fm.load_novel("novel_lk")["ok"] is True

    def test_lock_released_on_exception(self, tmp_path):
        """上下文内抛异常仍释放锁。"""
        fm = _make_manager(tmp_path)

        with pytest.raises(RuntimeError):
            with fm._novel_lock("novel_lk"):
                raise RuntimeError("boom")

        # 下一次调用不应被遗留锁阻塞
        fm.save_novel("novel_lk", {"novel_id": "novel_lk", "recovered": True})
        assert fm.load_novel("novel_lk")["recovered"] is True

    def test_different_novels_do_not_contend(self, tmp_path):
        """不同小说使用独立锁。"""
        fm = FileManager(str(tmp_path))
        fm.save_novel("novel_a", {"novel_id": "novel_a"})
        fm.save_novel("novel_b", {"novel_id": "novel_b"})

        release = threading.Event()
        acquired = threading.Event()

        def holder():
            with fm._novel_lock("novel_a"):
                acquired.set()
                release.wait(timeout=5.0)

        t = threading.Thread(target=holder)
        t.start()
        try:
            assert acquired.wait(timeout=2.0)
            # novel_b 锁未被持有，应立即成功
            fm.save_novel("novel_b", {"novel_id": "novel_b", "ok": True})
        finally:
            release.set()
            t.join(timeout=3.0)

    def test_load_novel_not_blocked_by_write_lock(self, tmp_path):
        """读取（load_novel）不走锁，持锁期间仍可读到上次写入的内容。"""
        fm = _make_manager(tmp_path)
        fm.save_novel("novel_lk", {"novel_id": "novel_lk", "latest": True})

        acquired = threading.Event()
        release = threading.Event()

        def holder():
            with fm._novel_lock("novel_lk"):
                acquired.set()
                release.wait(timeout=5.0)

        t = threading.Thread(target=holder)
        t.start()
        try:
            assert acquired.wait(timeout=2.0)
            data = fm.load_novel("novel_lk")
            assert data["latest"] is True
        finally:
            release.set()
            t.join(timeout=3.0)


# ---------------------------------------------------------------------------
# EditService + lock integration
# ---------------------------------------------------------------------------


class TestEditServiceUnderLock:
    def test_edit_during_concurrent_lock_returns_failed(self, tmp_path):
        """NovelEditService.edit() 遇到锁冲突时返回 status="failed"，
        而不是直接崩溃，因 edit() 内部捕获了底层异常。"""
        from src.novel.services.edit_service import NovelEditService

        # 准备合法的 novel 项目
        novel_dir = tmp_path / "novels" / "novel_lk"
        novel_dir.mkdir(parents=True)
        novel_data = {
            "novel_id": "novel_lk",
            "title": "锁 + edit",
            "genre": "玄幻",
            "current_chapter": 1,
            "characters": [
                {
                    "character_id": "char_001",
                    "name": "A",
                    "gender": "男",
                    "age": 18,
                    "occupation": "X",
                    "role": "主角",
                    "status": "active",
                    "appearance": {
                        "height": "1", "build": "1", "hair": "1",
                        "eyes": "1", "clothing_style": "1",
                    },
                    "personality": {
                        "traits": ["a", "b", "c"],
                        "core_belief": "c", "motivation": "m",
                        "flaw": "f", "speech_style": "s",
                    },
                }
            ],
            "world_setting": {
                "era": "古", "location": "X",
                "rules": ["R"], "terms": {"T": "t"},
            },
            "outline": {"chapters": []},
            "config": {"llm": {"provider": "auto"}},
        }
        with open(novel_dir / "novel.json", "w", encoding="utf-8") as f:
            json.dump(novel_data, f, ensure_ascii=False)

        service = NovelEditService(workspace=str(tmp_path))

        acquired = threading.Event()
        release = threading.Event()

        def holder():
            with service.file_manager._novel_lock("novel_lk"):
                acquired.set()
                release.wait(timeout=5.0)

        t = threading.Thread(target=holder)
        t.start()
        try:
            assert acquired.wait(timeout=2.0)

            result = service.edit(
                project_path=f"{tmp_path}/novels/novel_lk",
                structured_change={
                    "change_type": "update",
                    "entity_type": "character",
                    "entity_id": "char_001",
                    "data": {"age": 99},
                },
            )

            assert result.status == "failed"
            assert "novel_lk" in result.error or "编辑" in result.error
        finally:
            release.set()
            t.join(timeout=3.0)
