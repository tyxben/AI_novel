"""测试 FileManager 章节存储重构: json 仅存元数据, txt 存正文"""

from __future__ import annotations

import json

import pytest

from src.novel.storage.file_manager import FileManager


# ========== Fixtures ==========


@pytest.fixture
def fm(tmp_path):
    """创建临时 FileManager 实例"""
    return FileManager(str(tmp_path))


@pytest.fixture
def novel_id():
    return "test_novel_refactor"


@pytest.fixture
def fm_with_novel(fm, novel_id):
    """带有已保存 novel.json 的 FileManager"""
    novel_data = {
        "novel_id": novel_id,
        "title": "测试小说",
        "genre": "玄幻",
    }
    fm.save_novel(novel_id, novel_data)
    return fm


# ========== save_chapter: json 不包含 full_text ==========


class TestSaveChapterNoFullText:
    def test_json_does_not_contain_full_text(self, fm_with_novel, novel_id):
        """save_chapter 写入的 json 不应包含 full_text 字段"""
        ch_data = {
            "chapter_number": 1,
            "title": "第一章 序幕",
            "full_text": "这是第一章的正文内容。" * 100,
            "word_count": 0,  # should be recalculated
            "status": "draft",
        }
        json_path = fm_with_novel.save_chapter(novel_id, 1, ch_data)

        raw = json.loads(json_path.read_text(encoding="utf-8"))
        assert "full_text" not in raw, "json 文件不应包含 full_text"

    def test_json_has_correct_word_count(self, fm_with_novel, novel_id):
        """word_count 应基于 full_text 长度重新计算"""
        text = "这是正文" * 50
        ch_data = {
            "chapter_number": 2,
            "title": "第二章",
            "full_text": text,
            "word_count": 999,  # intentionally wrong
            "status": "draft",
        }
        json_path = fm_with_novel.save_chapter(novel_id, 2, ch_data)

        raw = json.loads(json_path.read_text(encoding="utf-8"))
        assert raw["word_count"] == len(text)

    def test_save_chapter_writes_txt_file(self, fm_with_novel, novel_id):
        """save_chapter 应该同时写入 .txt 文件"""
        text = "正文内容在这里"
        ch_data = {
            "chapter_number": 3,
            "title": "第三章",
            "full_text": text,
            "status": "draft",
        }
        json_path = fm_with_novel.save_chapter(novel_id, 3, ch_data)

        txt_path = json_path.with_suffix(".txt")
        assert txt_path.exists(), ".txt 文件应存在"
        assert txt_path.read_text(encoding="utf-8") == text

    def test_save_chapter_without_full_text(self, fm_with_novel, novel_id):
        """如果 chapter_data 没有 full_text，也应正常保存 json"""
        ch_data = {
            "chapter_number": 4,
            "title": "第四章",
            "word_count": 100,
            "status": "draft",
        }
        json_path = fm_with_novel.save_chapter(novel_id, 4, ch_data)

        raw = json.loads(json_path.read_text(encoding="utf-8"))
        assert raw["title"] == "第四章"
        assert raw["word_count"] == 100
        assert "full_text" not in raw

    def test_save_chapter_does_not_mutate_input(self, fm_with_novel, novel_id):
        """save_chapter 不应修改传入的 chapter_data dict"""
        ch_data = {
            "chapter_number": 5,
            "title": "第五章",
            "full_text": "不应被删除",
            "word_count": 0,
            "status": "draft",
        }
        fm_with_novel.save_chapter(novel_id, 5, ch_data)

        # Input dict should still have full_text
        assert "full_text" in ch_data
        assert ch_data["full_text"] == "不应被删除"


# ========== load_chapter: 合并 json 元数据 + txt 正文 ==========


class TestLoadChapterMerge:
    def test_load_chapter_merges_txt_content(self, fm_with_novel, novel_id):
        """load_chapter 应从 .txt 加载 full_text"""
        text = "章节正文内容"
        fm_with_novel.save_chapter(novel_id, 1, {
            "chapter_number": 1,
            "title": "第一章",
            "full_text": text,
            "status": "draft",
        })

        loaded = fm_with_novel.load_chapter(novel_id, 1)
        assert loaded is not None
        assert loaded["full_text"] == text
        assert loaded["title"] == "第一章"
        assert loaded["word_count"] == len(text)

    def test_load_chapter_no_txt_file(self, fm_with_novel, novel_id):
        """如果没有 .txt 文件，load_chapter 应正常返回（无 full_text 或空）"""
        # Save metadata-only (no full_text)
        ch_data = {
            "chapter_number": 2,
            "title": "第二章",
            "word_count": 0,
            "status": "draft",
        }
        fm_with_novel.save_chapter(novel_id, 2, ch_data)

        loaded = fm_with_novel.load_chapter(novel_id, 2)
        assert loaded is not None
        assert loaded["title"] == "第二章"
        # No txt file means no full_text key added
        assert "full_text" not in loaded

    def test_load_chapter_nonexistent(self, fm_with_novel, novel_id):
        """加载不存在的章节应返回 None"""
        assert fm_with_novel.load_chapter(novel_id, 999) is None


# ========== save_chapter_text: 更新 json word_count 但不写 full_text ==========


class TestSaveChapterTextSync:
    def test_updates_json_word_count(self, fm_with_novel, novel_id):
        """save_chapter_text 应更新 json 中的 word_count"""
        # First save a chapter with some text
        fm_with_novel.save_chapter(novel_id, 1, {
            "chapter_number": 1,
            "title": "第一章",
            "full_text": "原始文本",
            "status": "draft",
        })

        # Now update text directly
        new_text = "这是新的更长的文本" * 10
        fm_with_novel.save_chapter_text(novel_id, 1, new_text)

        # Check json
        json_path = fm_with_novel._chapters_dir(novel_id) / "chapter_001.json"
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        assert raw["word_count"] == len(new_text)
        assert "full_text" not in raw, "save_chapter_text 不应在 json 中写入 full_text"

    def test_removes_old_full_text_from_json(self, fm_with_novel, novel_id):
        """如果旧 json 残留 full_text，save_chapter_text 应删除它"""
        # Manually write a json with full_text (simulate old format)
        chapters_dir = fm_with_novel._chapters_dir(novel_id)
        json_path = chapters_dir / "chapter_001.json"
        old_data = {
            "chapter_number": 1,
            "title": "第一章",
            "full_text": "旧的正文内容",
            "word_count": 6,
            "status": "draft",
        }
        json_path.write_text(
            json.dumps(old_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Now save new text
        new_text = "新的正文"
        fm_with_novel.save_chapter_text(novel_id, 1, new_text)

        raw = json.loads(json_path.read_text(encoding="utf-8"))
        assert "full_text" not in raw
        assert raw["word_count"] == len(new_text)

    def test_txt_file_written(self, fm_with_novel, novel_id):
        """save_chapter_text 应写入 .txt 文件"""
        text = "纯文本内容"
        txt_path = fm_with_novel.save_chapter_text(novel_id, 1, text)

        assert txt_path.exists()
        assert txt_path.read_text(encoding="utf-8") == text

    def test_no_json_file_still_saves_txt(self, fm_with_novel, novel_id):
        """即使没有对应 json，save_chapter_text 也应正常保存 txt"""
        text = "独立的文本"
        txt_path = fm_with_novel.save_chapter_text(novel_id, 10, text)

        assert txt_path.exists()
        assert txt_path.read_text(encoding="utf-8") == text


# ========== 向后兼容: 旧 json 含 full_text ==========


class TestBackwardCompatibility:
    def test_old_json_with_full_text_loads_txt_preferentially(
        self, fm_with_novel, novel_id
    ):
        """旧 json 含 full_text 时，.txt 内容应优先"""
        chapters_dir = fm_with_novel._chapters_dir(novel_id)
        json_path = chapters_dir / "chapter_001.json"
        txt_path = chapters_dir / "chapter_001.txt"

        # Write old-format json with full_text
        old_data = {
            "chapter_number": 1,
            "title": "第一章",
            "full_text": "json里的旧正文",
            "word_count": 8,
            "status": "draft",
        }
        json_path.write_text(
            json.dumps(old_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Write newer txt with different content
        txt_path.write_text("txt里的新正文", encoding="utf-8")

        loaded = fm_with_novel.load_chapter(novel_id, 1)
        assert loaded["full_text"] == "txt里的新正文", ".txt 应覆盖 json 中的 full_text"

    def test_old_json_with_full_text_no_txt(self, fm_with_novel, novel_id):
        """旧 json 含 full_text 但没有 .txt 时，json 里的 full_text 会被返回（兼容）"""
        chapters_dir = fm_with_novel._chapters_dir(novel_id)
        json_path = chapters_dir / "chapter_002.json"

        old_data = {
            "chapter_number": 2,
            "title": "第二章",
            "full_text": "旧json里的正文",
            "word_count": 8,
            "status": "draft",
        }
        json_path.write_text(
            json.dumps(old_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        loaded = fm_with_novel.load_chapter(novel_id, 2)
        # No txt file, so json's full_text remains
        assert loaded["full_text"] == "旧json里的正文"


# ========== export_novel_txt 兼容 ==========


class TestExportCompat:
    def test_export_uses_txt_content(self, fm_with_novel, novel_id):
        """export_novel_txt 应通过 load_chapter 正确获取 txt 内容"""
        fm_with_novel.save_chapter(novel_id, 1, {
            "chapter_number": 1,
            "title": "第一章 序幕",
            "full_text": "这是导出测试的正文内容",
            "status": "draft",
        })

        output = fm_with_novel.export_novel_txt(novel_id)
        content = output.read_text(encoding="utf-8")
        assert "这是导出测试的正文内容" in content


# ========== Checkpoint 不含 full_text ==========


class TestCheckpointStrip:
    def test_checkpoint_strips_full_text(self, tmp_path):
        """_save_checkpoint 应从 chapters 中移除 full_text"""
        from src.novel.pipeline import NovelPipeline

        pipe = NovelPipeline(workspace=str(tmp_path))
        novel_id = "ckpt_test"

        # Ensure novel dir exists
        novel_dir = tmp_path / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)

        state = {
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "第一章",
                    "full_text": "不应该出现在 checkpoint 中",
                    "word_count": 15,
                    "status": "draft",
                },
                {
                    "chapter_number": 2,
                    "title": "第二章",
                    "full_text": "也不应该出现",
                    "word_count": 6,
                    "status": "draft",
                },
            ],
            "current_chapter": 2,
        }

        pipe._save_checkpoint(novel_id, state)

        ckpt_path = novel_dir / "checkpoint.json"
        assert ckpt_path.exists()

        saved = json.loads(ckpt_path.read_text(encoding="utf-8"))
        for ch in saved["chapters"]:
            assert "full_text" not in ch, f"chapter {ch['chapter_number']} 不应含 full_text"
            assert "word_count" in ch
            assert "title" in ch

    def test_checkpoint_preserves_other_fields(self, tmp_path):
        """_save_checkpoint 应保留 chapters 中的其他字段"""
        from src.novel.pipeline import NovelPipeline

        pipe = NovelPipeline(workspace=str(tmp_path))
        novel_id = "ckpt_test2"

        novel_dir = tmp_path / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)

        state = {
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "测试章",
                    "full_text": "正文",
                    "word_count": 2,
                    "status": "draft",
                    "quality_score": 8.5,
                },
            ],
        }

        pipe._save_checkpoint(novel_id, state)

        ckpt_path = novel_dir / "checkpoint.json"
        saved = json.loads(ckpt_path.read_text(encoding="utf-8"))
        ch = saved["chapters"][0]
        assert ch["quality_score"] == 8.5
        assert ch["status"] == "draft"
        assert ch["chapter_number"] == 1

    def test_checkpoint_no_chapters_key(self, tmp_path):
        """没有 chapters 的 state 也应正常保存"""
        from src.novel.pipeline import NovelPipeline

        pipe = NovelPipeline(workspace=str(tmp_path))
        novel_id = "ckpt_test3"

        novel_dir = tmp_path / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)

        state = {"current_chapter": 0, "outline": {"chapters": []}}
        pipe._save_checkpoint(novel_id, state)

        ckpt_path = novel_dir / "checkpoint.json"
        saved = json.loads(ckpt_path.read_text(encoding="utf-8"))
        assert saved["current_chapter"] == 0
