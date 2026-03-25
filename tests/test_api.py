"""Tests for the REST API layer (src/api/).

Uses FastAPI TestClient for synchronous endpoint testing.
All external dependencies (task queue, file system, LLM) are mocked.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.helpers import set_workspace, configure_task_queue, _SAFE_ID_RE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _workspace(tmp_path):
    """Set workspace to a temp dir for every test."""
    set_workspace(str(tmp_path))
    yield tmp_path
    set_workspace("workspace")  # restore default


@pytest.fixture()
def mock_db():
    """Mock TaskDB that tracks created tasks."""
    db = MagicMock()
    _tasks = {}

    def _create_task(task_type, params):
        record = MagicMock()
        record.task_id = f"test_{len(_tasks):04d}"
        record.task_type = task_type
        record.params = params
        _tasks[record.task_id] = record
        return record

    def _get_task(task_id):
        return _tasks.get(task_id)

    def _list_tasks(limit=50):
        items = list(_tasks.values())[:limit]
        for item in items:
            item.model_dump = MagicMock(return_value={
                "task_id": item.task_id,
                "task_type": str(item.task_type),
                "status": "pending",
                "progress": 0.0,
                "progress_msg": "",
                "params": item.params,
                "result": None,
                "error": None,
                "created_at": "2025-01-01T00:00:00",
                "started_at": None,
                "finished_at": None,
            })
        return items

    def _delete_task(task_id):
        return _tasks.pop(task_id, None) is not None

    db.create_task = MagicMock(side_effect=_create_task)
    db.get_task = MagicMock(side_effect=_get_task)
    db.list_tasks = MagicMock(side_effect=_list_tasks)
    db.delete_task = MagicMock(side_effect=_delete_task)
    db.update_status = MagicMock()
    db.update_progress = MagicMock()
    return db


@pytest.fixture()
def mock_executor():
    """Mock executor that records submitted tasks but does not run them."""
    ex = MagicMock()
    ex.submit = MagicMock()
    return ex


@pytest.fixture()
def client(mock_db, mock_executor):
    """Create a TestClient with mocked task queue."""
    configure_task_queue(mock_db, mock_executor)
    # Import app after configuring task queue
    from src.api.app import create_app
    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helper: create a novel project on disk
# ---------------------------------------------------------------------------

def _create_novel_on_disk(workspace: Path, novel_id: str = "novel_test001",
                          title: str = "Test Novel", genre: str = "玄幻",
                          chapters: int = 0, outline_chapters: int = 10) -> str:
    """Create a minimal novel project directory structure."""
    novel_dir = workspace / "novels" / novel_id
    novel_dir.mkdir(parents=True, exist_ok=True)

    outline_chs = [{"title": f"Chapter {i+1}", "summary": f"Summary {i+1}"}
                   for i in range(outline_chapters)]

    novel_data = {
        "title": title,
        "genre": genre,
        "status": "generating",
        "style_name": "webnovel.shuangwen",
        "author_name": "TestAuthor",
        "target_audience": "通用",
        "target_words": 100000,
        "current_chapter": chapters,
        "synopsis": "A test novel synopsis.",
        "tags": ["test"],
        "protagonist_names": ["Hero"],
        "outline": {"chapters": outline_chs, "main_storyline": "Test story"},
        "characters": [{"character_id": "char_001", "name": "Hero"}],
        "world_setting": {"era": "ancient"},
    }
    (novel_dir / "novel.json").write_text(
        json.dumps(novel_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Create chapters
    chapters_dir = novel_dir / "chapters"
    chapters_dir.mkdir(exist_ok=True)
    for i in range(1, chapters + 1):
        ch_data = {
            "title": f"Chapter {i}",
            "word_count": 2500,
            "full_text": f"Content of chapter {i}. " * 100,
            "quality_score": 7.5,
        }
        (chapters_dir / f"chapter_{i:03d}.json").write_text(
            json.dumps(ch_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (chapters_dir / f"chapter_{i:03d}.txt").write_text(
            ch_data["full_text"], encoding="utf-8"
        )

    # Create checkpoint
    ckpt = {
        "outline": {"chapters": outline_chs},
        "characters": novel_data["characters"],
        "config": {"llm": {"provider": "auto"}},
    }
    (novel_dir / "checkpoint.json").write_text(
        json.dumps(ckpt, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return novel_id


# ---------------------------------------------------------------------------
# Tests: Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Tests: Novels — CRUD
# ---------------------------------------------------------------------------

class TestNovelList:
    def test_list_empty(self, client):
        r = client.get("/api/novels")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_with_projects(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_aaa", title="Novel A")
        _create_novel_on_disk(_workspace, "novel_bbb", title="Novel B")
        r = client.get("/api/novels")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        ids = {p["id"] for p in data}
        assert "novel_aaa" in ids
        assert "novel_bbb" in ids
        # Verify fields
        for p in data:
            assert "title" in p
            assert "genre" in p
            assert "status" in p


class TestNovelDetail:
    def test_get_novel_not_found(self, client):
        r = client.get("/api/novels/nonexistent")
        assert r.status_code == 404

    def test_get_novel_detail(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_xyz", title="My Novel", chapters=3)
        r = client.get("/api/novels/novel_xyz")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "novel_xyz"
        assert data["title"] == "My Novel"
        assert data["genre"] == "玄幻"
        assert len(data["chapters"]) == 3
        assert data["total_chapters"] == 10
        assert data["current_chapter"] == 3
        assert "outline" in data
        assert "characters" in data
        assert "world_setting" in data
        assert data["progress"] == 3 / 10

    def test_get_novel_invalid_id(self, client):
        # Path traversal via slashes is resolved by the HTTP layer before routing,
        # so ../../etc becomes a different URL path (404 or redirected to list).
        r = client.get("/api/novels/../../etc")
        assert r.status_code in (400, 404)
        # Direct invalid chars (no slashes) should be caught by validate_id
        r2 = client.get("/api/novels/a%20b")  # space in URL-encoded form
        assert r2.status_code == 400


class TestNovelCreate:
    def test_create_novel(self, client, mock_db):
        r = client.post("/api/novels", json={
            "genre": "玄幻",
            "theme": "少年修炼逆天改命",
            "target_words": 50000,
        })
        assert r.status_code == 201
        data = r.json()
        assert "task_id" in data
        mock_db.create_task.assert_called_once()

    def test_create_novel_empty_theme(self, client):
        r = client.post("/api/novels", json={
            "genre": "玄幻",
            "theme": "",
        })
        assert r.status_code == 400

    def test_create_novel_with_all_fields(self, client, mock_db):
        r = client.post("/api/novels", json={
            "genre": "都市",
            "theme": "重生商战",
            "target_words": 200000,
            "style": "wuxia.classical",
            "template": "hero_journey",
            "custom_ideas": "主角是程序员",
            "author_name": "Test Author",
            "target_audience": "18-25",
        })
        assert r.status_code == 201
        assert "task_id" in r.json()


class TestNovelGenerate:
    def test_generate_chapters(self, client, _workspace, mock_db):
        _create_novel_on_disk(_workspace, "novel_gen", chapters=3)
        r = client.post("/api/novels/novel_gen/generate", json={
            "start_chapter": 4,
            "end_chapter": 10,
        })
        assert r.status_code == 201
        assert "task_id" in r.json()

    def test_generate_novel_not_found(self, client):
        r = client.post("/api/novels/nonexistent/generate", json={})
        assert r.status_code == 404

    def test_generate_with_batch(self, client, _workspace, mock_db):
        _create_novel_on_disk(_workspace, "novel_batch")
        r = client.post("/api/novels/novel_batch/generate", json={
            "batch_size": 5,
            "target_total": 40,
        })
        assert r.status_code == 201


class TestNovelPolish:
    def test_polish(self, client, _workspace, mock_db):
        _create_novel_on_disk(_workspace, "novel_pol", chapters=5)
        r = client.post("/api/novels/novel_pol/polish", json={
            "start_chapter": 1,
            "end_chapter": 5,
        })
        assert r.status_code == 201
        assert "task_id" in r.json()


class TestNovelFeedback:
    def test_analyze_feedback(self, client, _workspace, mock_db):
        _create_novel_on_disk(_workspace, "novel_fb")
        r = client.post("/api/novels/novel_fb/feedback/analyze", json={
            "feedback_text": "第5章主角性格突然变了",
            "chapter_number": 5,
        })
        assert r.status_code == 201
        assert "task_id" in r.json()

    def test_apply_feedback(self, client, _workspace, mock_db):
        _create_novel_on_disk(_workspace, "novel_fb2")
        r = client.post("/api/novels/novel_fb2/feedback/apply", json={
            "feedback_text": "节奏太慢",
        })
        assert r.status_code == 201

    def test_feedback_empty_text(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_fb3")
        r = client.post("/api/novels/novel_fb3/feedback/analyze", json={
            "feedback_text": "",
        })
        assert r.status_code == 400


class TestNovelEdit:
    def test_edit_missing_instruction(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_edit")
        r = client.post("/api/novels/novel_edit/edit", json={
            "instruction": "",
        })
        assert r.status_code == 400

    @patch("src.novel.services.edit_service.NovelEditService")
    def test_edit_success(self, mock_cls, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_edit2")
        mock_svc = MagicMock()
        mock_cls.return_value = mock_svc
        mock_svc.edit.return_value = MagicMock(
            change_id="chg_001",
            status="success",
            change_type="update",
            entity_type="character",
            entity_id="char_001",
            old_value={"name": "Old"},
            new_value={"name": "New"},
            effective_from_chapter=5,
            reasoning="Name change",
            error=None,
        )
        r = client.post("/api/novels/novel_edit2/edit", json={
            "instruction": "修改主角名字为New",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["change_type"] == "update"


class TestNovelReadChapter:
    def test_read_chapter(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_ch", chapters=3)
        r = client.get("/api/novels/novel_ch/chapters/1")
        assert r.status_code == 200
        data = r.json()
        assert data["number"] == 1
        assert data["title"] == "Chapter 1"
        assert data["word_count"] == 2500
        assert "text" in data
        assert len(data["text"]) > 0

    def test_read_chapter_not_found(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_ch2", chapters=1)
        r = client.get("/api/novels/novel_ch2/chapters/99")
        assert r.status_code == 404


class TestNovelExport:
    @patch("src.novel.pipeline.NovelPipeline")
    def test_export(self, mock_pipe_cls, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_exp", chapters=2)
        mock_pipe = MagicMock()
        mock_pipe_cls.return_value = mock_pipe
        output = _workspace / "novels" / "novel_exp" / "output.txt"
        output.write_text("exported content", encoding="utf-8")
        mock_pipe.export_novel.return_value = str(output)

        r = client.get("/api/novels/novel_exp/export")
        assert r.status_code == 200
        data = r.json()
        assert data["text"] == "exported content"
        assert "path" in data


class TestNovelDelete:
    def test_delete(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_del")
        assert (_workspace / "novels" / "novel_del").exists()
        r = client.delete("/api/novels/novel_del")
        assert r.status_code == 204
        assert not (_workspace / "novels" / "novel_del").exists()

    def test_delete_not_found(self, client):
        r = client.delete("/api/novels/nonexistent")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tests: Chapter Save
# ---------------------------------------------------------------------------

class TestChapterSave:
    @patch("src.novel.pipeline.NovelPipeline")
    def test_save_chapter(self, mock_pipe_cls, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_save", chapters=3)
        mock_pipe = MagicMock()
        mock_pipe_cls.return_value = mock_pipe
        mock_pipe.save_edited_chapter.return_value = {
            "saved": True,
            "chapter_number": 1,
            "char_count": 1500,
            "old_char_count": 2500,
        }

        r = client.put("/api/novels/novel_save/chapters/1", json={
            "text": "New chapter content here.",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["saved"] is True
        assert data["chapter_number"] == 1
        assert data["char_count"] == 1500
        mock_pipe.save_edited_chapter.assert_called_once()

    def test_save_chapter_empty_text(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_save2", chapters=1)
        r = client.put("/api/novels/novel_save2/chapters/1", json={
            "text": "",
        })
        assert r.status_code == 400

    def test_save_chapter_whitespace_text(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_save3", chapters=1)
        r = client.put("/api/novels/novel_save3/chapters/1", json={
            "text": "   ",
        })
        assert r.status_code == 400

    def test_save_chapter_novel_not_found(self, client):
        r = client.put("/api/novels/nonexistent/chapters/1", json={
            "text": "Some text",
        })
        assert r.status_code == 404

    @patch("src.novel.pipeline.NovelPipeline")
    def test_save_chapter_pipeline_error(self, mock_pipe_cls, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_save4", chapters=1)
        mock_pipe = MagicMock()
        mock_pipe_cls.return_value = mock_pipe
        mock_pipe.save_edited_chapter.side_effect = RuntimeError("Disk full")

        r = client.put("/api/novels/novel_save4/chapters/1", json={
            "text": "Some text",
        })
        assert r.status_code == 500
        assert "Disk full" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Tests: Chapter Proofread
# ---------------------------------------------------------------------------

class TestChapterProofread:
    @patch("src.novel.pipeline.NovelPipeline")
    def test_proofread_chapter(self, mock_pipe_cls, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_proof", chapters=3)
        mock_pipe = MagicMock()
        mock_pipe_cls.return_value = mock_pipe
        mock_pipe.proofread_chapter.return_value = [
            {
                "index": 0,
                "issue_type": "typo",
                "original": "错别字",
                "correction": "正确字",
                "explanation": "拼写错误",
            },
        ]

        r = client.post("/api/novels/novel_proof/chapters/1/proofread")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        assert len(data["issues"]) == 1
        assert data["issues"][0]["issue_type"] == "typo"

    @patch("src.novel.pipeline.NovelPipeline")
    def test_proofread_no_issues(self, mock_pipe_cls, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_proof2", chapters=1)
        mock_pipe = MagicMock()
        mock_pipe_cls.return_value = mock_pipe
        mock_pipe.proofread_chapter.return_value = []

        r = client.post("/api/novels/novel_proof2/chapters/1/proofread")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 0
        assert data["issues"] == []

    def test_proofread_novel_not_found(self, client):
        r = client.post("/api/novels/nonexistent/chapters/1/proofread")
        assert r.status_code == 404

    @patch("src.novel.pipeline.NovelPipeline")
    def test_proofread_error(self, mock_pipe_cls, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_proof3", chapters=1)
        mock_pipe = MagicMock()
        mock_pipe_cls.return_value = mock_pipe
        mock_pipe.proofread_chapter.side_effect = RuntimeError("LLM error")

        r = client.post("/api/novels/novel_proof3/chapters/1/proofread")
        assert r.status_code == 500
        assert "LLM error" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Tests: Apply Proofread Fixes
# ---------------------------------------------------------------------------

class TestApplyProofreadFixes:
    @patch("src.novel.pipeline.NovelPipeline")
    def test_apply_fixes(self, mock_pipe_cls, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_fix", chapters=1)
        mock_pipe = MagicMock()
        mock_pipe_cls.return_value = mock_pipe
        mock_pipe.apply_proofreading_fixes.return_value = (
            "Fixed text content",
            [],  # no failures
        )

        r = client.post("/api/novels/novel_fix/chapters/1/apply-fixes", json={
            "text": "Original text content",
            "issues": [
                {"index": 0, "issue_type": "typo", "original": "X", "correction": "Y", "explanation": "fix"},
            ],
            "selected_indices": [0],
        })
        assert r.status_code == 200
        data = r.json()
        assert data["text"] == "Fixed text content"
        assert data["applied"] == 1
        assert data["total"] == 1
        assert data["failures"] == []

    @patch("src.novel.pipeline.NovelPipeline")
    def test_apply_fixes_with_failures(self, mock_pipe_cls, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_fix2", chapters=1)
        mock_pipe = MagicMock()
        mock_pipe_cls.return_value = mock_pipe
        mock_pipe.apply_proofreading_fixes.return_value = (
            "Partial fix",
            ["Could not find 'abc' in text"],
        )

        r = client.post("/api/novels/novel_fix2/chapters/1/apply-fixes", json={
            "text": "Some text",
            "issues": [
                {"index": 0, "issue_type": "typo", "original": "abc", "correction": "def", "explanation": "fix"},
                {"index": 1, "issue_type": "grammar", "original": "xyz", "correction": "xyz2", "explanation": "fix"},
            ],
            "selected_indices": [0, 1],
        })
        assert r.status_code == 200
        data = r.json()
        assert data["applied"] == 1
        assert data["total"] == 2
        assert len(data["failures"]) == 1

    def test_apply_fixes_empty_text(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_fix3", chapters=1)
        r = client.post("/api/novels/novel_fix3/chapters/1/apply-fixes", json={
            "text": "",
            "issues": [{"index": 0, "issue_type": "typo", "original": "a", "correction": "b", "explanation": ""}],
            "selected_indices": [0],
        })
        assert r.status_code == 400

    def test_apply_fixes_empty_issues(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_fix4", chapters=1)
        r = client.post("/api/novels/novel_fix4/chapters/1/apply-fixes", json={
            "text": "Some text",
            "issues": [],
            "selected_indices": [0],
        })
        assert r.status_code == 400

    def test_apply_fixes_empty_indices(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_fix5", chapters=1)
        r = client.post("/api/novels/novel_fix5/chapters/1/apply-fixes", json={
            "text": "Some text",
            "issues": [{"index": 0, "issue_type": "typo", "original": "a", "correction": "b", "explanation": ""}],
            "selected_indices": [],
        })
        assert r.status_code == 400

    def test_apply_fixes_novel_not_found(self, client):
        r = client.post("/api/novels/nonexistent/chapters/1/apply-fixes", json={
            "text": "text",
            "issues": [{"index": 0, "issue_type": "typo", "original": "a", "correction": "b", "explanation": ""}],
            "selected_indices": [0],
        })
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tests: Polish Diff
# ---------------------------------------------------------------------------

class TestPolishDiff:
    def test_polish_diff_no_revisions(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_pd", chapters=1)
        # No revisions directory exists
        r = client.get("/api/novels/novel_pd/chapters/1/polish-diff")
        assert r.status_code == 404

    def test_polish_diff_with_revision(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_pd2", chapters=1)
        # Create a revision file (FileManager stores revisions in novels/{id}/revisions/)
        rev_dir = _workspace / "novels" / "novel_pd2" / "revisions"
        rev_dir.mkdir(parents=True, exist_ok=True)
        (rev_dir / "chapter_001_rev1.txt").write_text(
            "Original chapter text before polishing.", encoding="utf-8"
        )
        r = client.get("/api/novels/novel_pd2/chapters/1/polish-diff")
        assert r.status_code == 200
        data = r.json()
        assert "original_text" in data
        assert "polished_text" in data
        assert data["revision"] == 1
        assert data["original_chars"] > 0
        assert data["polished_chars"] > 0

    def test_polish_diff_novel_not_found(self, client):
        r = client.get("/api/novels/nonexistent/chapters/1/polish-diff")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tests: Novel Settings CRUD
# ---------------------------------------------------------------------------

class TestNovelSettings:
    def test_get_settings(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_set", chapters=2)
        r = client.get("/api/novels/novel_set/settings")
        assert r.status_code == 200
        data = r.json()
        assert "world_setting" in data
        assert "characters" in data
        assert "outline" in data
        assert data["world_setting"]["era"] == "ancient"
        assert len(data["characters"]) == 1
        assert data["characters"][0]["name"] == "Hero"

    def test_get_settings_not_found(self, client):
        r = client.get("/api/novels/nonexistent/settings")
        assert r.status_code == 404

    def test_save_settings_world(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_set2")
        r = client.put("/api/novels/novel_set2/settings", json={
            "world_setting": {"era": "modern", "location": "Earth"},
        })
        assert r.status_code == 200
        data = r.json()
        assert data["saved"] is True
        assert "world_setting" in data["updated_fields"]

        # Verify the data was actually saved
        novel_data = json.loads(
            (_workspace / "novels" / "novel_set2" / "novel.json").read_text(encoding="utf-8")
        )
        assert novel_data["world_setting"]["era"] == "modern"
        assert novel_data["world_setting"]["location"] == "Earth"

    def test_save_settings_characters(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_set3")
        r = client.put("/api/novels/novel_set3/settings", json={
            "characters": [
                {"character_id": "char_001", "name": "UpdatedHero"},
                {"character_id": "char_002", "name": "Villain"},
            ],
        })
        assert r.status_code == 200
        data = r.json()
        assert "characters" in data["updated_fields"]

        novel_data = json.loads(
            (_workspace / "novels" / "novel_set3" / "novel.json").read_text(encoding="utf-8")
        )
        assert len(novel_data["characters"]) == 2
        assert novel_data["characters"][0]["name"] == "UpdatedHero"

    def test_save_settings_creates_backup(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_set4")
        r = client.put("/api/novels/novel_set4/settings", json={
            "world_setting": {"era": "future"},
        })
        assert r.status_code == 200
        # Check that a backup file was created
        rev_dir = _workspace / "novels" / "novel_set4" / "revisions"
        assert rev_dir.exists()
        backups = list(rev_dir.glob("novel_backup_*.json"))
        assert len(backups) >= 1

    def test_save_settings_not_found(self, client):
        r = client.put("/api/novels/nonexistent/settings", json={
            "world_setting": {"era": "modern"},
        })
        assert r.status_code == 404

    def test_save_settings_empty_body(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_set5")
        # All fields None, should still return 200 with no updates
        r = client.put("/api/novels/novel_set5/settings", json={})
        assert r.status_code == 200
        data = r.json()
        assert data["saved"] is True
        assert data["updated_fields"] == []

    def test_save_settings_outline(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_set6")
        new_outline = {
            "main_storyline": {"protagonist_goal": "Save the world"},
            "chapters": [{"chapter_number": 1, "title": "Beginning"}],
        }
        r = client.put("/api/novels/novel_set6/settings", json={
            "outline": new_outline,
        })
        assert r.status_code == 200
        data = r.json()
        assert "outline" in data["updated_fields"]


# ---------------------------------------------------------------------------
# Tests: Setting Impact Analysis
# ---------------------------------------------------------------------------

class TestSettingImpact:
    @patch("src.novel.pipeline.NovelPipeline")
    def test_analyze_impact(self, mock_pipe_cls, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_imp", chapters=5)
        mock_pipe = MagicMock()
        mock_pipe_cls.return_value = mock_pipe
        mock_pipe.analyze_setting_impact.return_value = {
            "affected_chapters": [3, 5],
            "conflicts": [
                {"chapter_number": 3, "reason": "Era mismatch"},
            ],
            "severity": "medium",
            "summary": "2 chapters affected by era change",
        }

        r = client.post("/api/novels/novel_imp/settings/analyze-impact", json={
            "modified_field": "world_setting",
            "new_value": {"era": "modern", "location": "New York"},
        })
        assert r.status_code == 200
        data = r.json()
        assert data["affected_chapters"] == [3, 5]
        assert data["severity"] == "medium"
        assert len(data["conflicts"]) == 1

    def test_analyze_impact_invalid_field(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_imp2")
        r = client.post("/api/novels/novel_imp2/settings/analyze-impact", json={
            "modified_field": "invalid_field",
            "new_value": {},
        })
        assert r.status_code == 400

    def test_analyze_impact_not_found(self, client):
        r = client.post("/api/novels/nonexistent/settings/analyze-impact", json={
            "modified_field": "world_setting",
            "new_value": {},
        })
        assert r.status_code == 404

    @patch("src.novel.pipeline.NovelPipeline")
    def test_analyze_impact_pipeline_error(self, mock_pipe_cls, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_imp3", chapters=1)
        mock_pipe = MagicMock()
        mock_pipe_cls.return_value = mock_pipe
        mock_pipe.analyze_setting_impact.return_value = {
            "error": "LLM unavailable",
        }

        r = client.post("/api/novels/novel_imp3/settings/analyze-impact", json={
            "modified_field": "world_setting",
            "new_value": {"era": "future"},
        })
        assert r.status_code == 500
        assert "LLM unavailable" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Tests: Rewrite Affected Chapters
# ---------------------------------------------------------------------------

class TestRewriteAffected:
    def test_rewrite_affected(self, client, _workspace, mock_db):
        _create_novel_on_disk(_workspace, "novel_rw", chapters=5)
        r = client.post("/api/novels/novel_rw/settings/rewrite-affected", json={
            "impact": {
                "affected_chapters": [3, 5],
                "conflicts": [{"chapter_number": 3, "reason": "test"}],
                "severity": "medium",
            },
        })
        assert r.status_code == 201
        data = r.json()
        assert "task_id" in data
        mock_db.create_task.assert_called_once()

    def test_rewrite_affected_no_chapters(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_rw2")
        r = client.post("/api/novels/novel_rw2/settings/rewrite-affected", json={
            "impact": {
                "affected_chapters": [],
                "conflicts": [],
            },
        })
        assert r.status_code == 400

    def test_rewrite_affected_not_found(self, client):
        r = client.post("/api/novels/nonexistent/settings/rewrite-affected", json={
            "impact": {"affected_chapters": [1]},
        })
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tests: ID Validation / Path Traversal
# ---------------------------------------------------------------------------

class TestIDValidation:
    @pytest.mark.parametrize("bad_id", [
        # IDs with slashes are resolved by URL path normalization, not by our validator.
        # We test direct invalid characters that DO reach the endpoint.
        "foo\\bar", "a b c", "a;b", "a&b", "hello!world", "test@id",
    ])
    def test_invalid_ids(self, client, bad_id):
        r = client.get(f"/api/novels/{bad_id}")
        assert r.status_code in (400, 404, 422)

    @pytest.mark.parametrize("bad_path", [
        # IDs containing slashes or dots are resolved by the HTTP layer
        # and never reach the detail endpoint with the original value.
        "../etc", "../../passwd", "foo/bar",
    ])
    def test_path_traversal_ids(self, client, bad_path):
        """Path traversal attempts are handled by HTTP path normalization."""
        r = client.get(f"/api/novels/{bad_path}")
        # These resolve to different routes (list or 404), which is safe
        assert r.status_code in (200, 400, 404)

    def test_valid_ids(self, client, _workspace):
        _create_novel_on_disk(_workspace, "novel_valid-123")
        r = client.get("/api/novels/novel_valid-123")
        assert r.status_code == 200

    def test_safe_id_regex(self):
        assert _SAFE_ID_RE.match("novel_001")
        assert _SAFE_ID_RE.match("my-project-v2")
        assert not _SAFE_ID_RE.match("../bad")
        assert not _SAFE_ID_RE.match("a/b")
        assert not _SAFE_ID_RE.match("")


# ---------------------------------------------------------------------------
# Tests: Videos
# ---------------------------------------------------------------------------

class TestVideoEndpoints:
    def test_list_videos_empty(self, client):
        r = client.get("/api/videos")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_videos(self, client, _workspace):
        vid_dir = _workspace / "videos" / "vid_001"
        vid_dir.mkdir(parents=True)
        concept = {"title": "My Video", "inspiration": "cats"}
        (vid_dir / "concept.json").write_text(
            json.dumps(concept), encoding="utf-8"
        )
        r = client.get("/api/videos")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["name"] == "My Video"

    def test_create_video_director(self, client, mock_db):
        r = client.post("/api/videos", json={
            "inspiration": "A cat saves the world",
            "target_duration": 30,
        })
        assert r.status_code == 201
        assert "task_id" in r.json()

    def test_create_video_classic(self, client, mock_db):
        r = client.post("/api/videos", json={
            "input_file": "input/test.txt",
            "run_mode": "classic",
        })
        assert r.status_code == 201

    def test_create_video_no_input(self, client):
        r = client.post("/api/videos", json={})
        assert r.status_code == 400

    def test_get_video_not_found(self, client):
        r = client.get("/api/videos/nonexistent")
        assert r.status_code == 404

    def test_get_video(self, client, _workspace):
        vid_dir = _workspace / "videos" / "vid_002"
        vid_dir.mkdir(parents=True)
        (vid_dir / "concept.json").write_text(
            json.dumps({"title": "Test Vid"}), encoding="utf-8"
        )
        r = client.get("/api/videos/vid_002")
        assert r.status_code == 200
        assert r.json()["name"] == "Test Vid"


# ---------------------------------------------------------------------------
# Tests: PPT
# ---------------------------------------------------------------------------

class TestPPTEndpoints:
    def test_list_ppt_empty(self, client):
        r = client.get("/api/ppt")
        assert r.status_code == 200
        assert r.json() == []

    def test_create_ppt(self, client, mock_db):
        r = client.post("/api/ppt", json={
            "topic": "AI in Healthcare",
            "audience": "medical",
            "theme": "modern",
        })
        assert r.status_code == 201
        assert "task_id" in r.json()

    def test_create_ppt_no_input(self, client):
        r = client.post("/api/ppt", json={})
        assert r.status_code == 400

    def test_list_ppt_with_projects(self, client, _workspace):
        ppt_dir = _workspace / "ppt" / "ppt_001"
        ppt_dir.mkdir(parents=True)
        ckpt = {
            "data": {
                "stages": {
                    "outline": {
                        "data": [{"title": "My Presentation", "content": "..."}]
                    }
                }
            }
        }
        (ppt_dir / "checkpoint.json").write_text(
            json.dumps(ckpt), encoding="utf-8"
        )
        r = client.get("/api/ppt")
        data = r.json()
        assert len(data) == 1
        assert data[0]["id"] == "ppt_001"
        assert data[0]["status"] == "outline_ready"

    def test_get_ppt_not_found(self, client):
        r = client.get("/api/ppt/nonexistent")
        assert r.status_code == 404

    def test_get_ppt(self, client, _workspace):
        ppt_dir = _workspace / "ppt" / "ppt_002"
        ppt_dir.mkdir(parents=True)
        ckpt = {
            "data": {
                "stages": {
                    "outline": {"data": [{"title": "Slide 1"}]},
                    "design": {"data": [{"layout": "default"}]},
                }
            }
        }
        (ppt_dir / "checkpoint.json").write_text(
            json.dumps(ckpt), encoding="utf-8"
        )
        r = client.get("/api/ppt/ppt_002")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "ppt_002"
        assert data["status"] == "completed"

    def test_ppt_continue(self, client, _workspace, mock_db):
        ppt_dir = _workspace / "ppt" / "ppt_003"
        ppt_dir.mkdir(parents=True)
        (ppt_dir / "checkpoint.json").write_text("{}", encoding="utf-8")
        r = client.post("/api/ppt/ppt_003/generate", json={
            "edited_outline": {"slides": []},
            "theme": "dark",
        })
        assert r.status_code == 201

    def test_ppt_render(self, client, _workspace, mock_db):
        ppt_dir = _workspace / "ppt" / "ppt_004"
        ppt_dir.mkdir(parents=True)
        (ppt_dir / "checkpoint.json").write_text("{}", encoding="utf-8")
        r = client.post("/api/ppt/ppt_004/render", json={"theme": "modern"})
        assert r.status_code == 201

    def test_ppt_export_no_html(self, client, _workspace):
        ppt_dir = _workspace / "ppt" / "ppt_005"
        ppt_dir.mkdir(parents=True)
        (ppt_dir / "checkpoint.json").write_text("{}", encoding="utf-8")
        r = client.post("/api/ppt/ppt_005/export")
        assert r.status_code == 400

    def test_ppt_export(self, client, _workspace, mock_db):
        ppt_dir = _workspace / "ppt" / "ppt_006"
        ppt_dir.mkdir(parents=True)
        (ppt_dir / "checkpoint.json").write_text("{}", encoding="utf-8")
        (ppt_dir / "presentation.html").write_text("<html></html>", encoding="utf-8")
        r = client.post("/api/ppt/ppt_006/export")
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# Tests: Projects (cross-product)
# ---------------------------------------------------------------------------

class TestProjectEndpoints:
    def test_list_all_empty(self, client):
        r = client.get("/api/projects")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_all_mixed(self, client, _workspace):
        # Create a novel
        _create_novel_on_disk(_workspace, "novel_proj")

        # Create a video
        vid_dir = _workspace / "videos" / "vid_proj"
        vid_dir.mkdir(parents=True)
        (vid_dir / "concept.json").write_text(
            json.dumps({"title": "My Video"}), encoding="utf-8"
        )

        # Create a PPT
        ppt_dir = _workspace / "ppt" / "ppt_proj"
        ppt_dir.mkdir(parents=True)
        (ppt_dir / "checkpoint.json").write_text(
            json.dumps({"data": {"stages": {"outline": {"data": [{"title": "PPT"}]}}}}),
            encoding="utf-8",
        )

        r = client.get("/api/projects")
        data = r.json()
        assert len(data) == 3
        kinds = {p["kind"] for p in data}
        assert kinds == {"novel", "video", "ppt"}

        # Verify fields on each project
        for p in data:
            assert "id" in p
            assert "name" in p
            assert "kind" in p
            assert "status" in p
            assert "updatedAt" in p
            assert "progress" in p


# ---------------------------------------------------------------------------
# Tests: Settings
# ---------------------------------------------------------------------------

class TestSettingsEndpoints:
    def test_get_settings(self, client, _workspace):
        # Create a config.yaml
        config_path = Path("config.yaml")
        # Settings routes use the project root config.yaml
        r = client.get("/api/settings")
        assert r.status_code == 200
        data = r.json()
        assert "config" in data
        assert "env_keys" in data

    def test_update_settings(self, client, tmp_path):
        # Patch the config path to avoid modifying real config
        with patch("src.api.settings_routes._CONFIG_PATH", tmp_path / "config.yaml"):
            (tmp_path / "config.yaml").write_text("llm:\n  provider: auto\n")
            r = client.put("/api/settings", json={
                "llm": {"provider": "gemini"},
            })
            assert r.status_code == 200
            data = r.json()
            assert data["config"]["llm"]["provider"] == "gemini"

    def test_test_key_empty(self, client):
        r = client.post("/api/settings/test-key", json={
            "provider": "openai",
            "api_key": "",
        })
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Tests: Tasks (task queue endpoints)
# ---------------------------------------------------------------------------

class TestTaskEndpoints:
    def test_submit_task(self, client, mock_db, mock_executor):
        r = client.post("/api/tasks", json={
            "task_type": "novel_create",
            "params": {"genre": "玄幻", "theme": "test"},
        })
        assert r.status_code == 201
        assert "task_id" in r.json()

    def test_list_tasks(self, client, mock_db):
        r = client.get("/api/tasks")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_task_not_found(self, client, mock_db):
        r = client.get("/api/tasks/nonexistent")
        assert r.status_code == 404

    def test_delete_task_not_found(self, client, mock_db):
        r = client.delete("/api/tasks/nonexistent")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tests: CORS
# ---------------------------------------------------------------------------

class TestCORS:
    def test_cors_headers(self, client):
        r = client.options("/api/health", headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        })
        assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_cors_rejected_origin(self, client):
        r = client.options("/api/health", headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "GET",
        })
        # Should not include the evil origin
        assert r.headers.get("access-control-allow-origin") != "http://evil.com"
