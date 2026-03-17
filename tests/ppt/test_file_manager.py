"""tests/ppt/test_file_manager.py - FileManager 测试"""

import json

import pytest

from src.ppt.file_manager import FileManager


@pytest.fixture
def fm(tmp_path):
    """使用临时目录的 FileManager"""
    return FileManager(workspace=str(tmp_path))


@pytest.fixture
def project_id():
    return "ppt_test123"


class TestCreateProject:

    def test_creates_subdirectories(self, fm, project_id):
        project_dir = fm.create_project(project_id)
        assert project_dir.exists()
        assert (project_dir / "images").is_dir()
        assert (project_dir / "output").is_dir()
        assert (project_dir / "checkpoints").is_dir()

    def test_returns_correct_path(self, fm, project_id):
        project_dir = fm.create_project(project_id)
        assert project_dir.name == project_id
        assert project_dir.parent.name == "ppt"

    def test_idempotent(self, fm, project_id):
        """重复调用不报错"""
        fm.create_project(project_id)
        fm.create_project(project_id)  # should not raise

    def test_different_projects(self, fm):
        p1 = fm.create_project("ppt_aaa")
        p2 = fm.create_project("ppt_bbb")
        assert p1 != p2
        assert p1.exists()
        assert p2.exists()


class TestCheckpoint:

    def test_save_and_load(self, fm, project_id):
        fm.create_project(project_id)
        data = {"status": "analyzing", "progress": 0.5}
        fm.save_checkpoint(project_id, stage="analyzing", data=data)

        loaded = fm.load_checkpoint(project_id)
        assert loaded is not None
        assert loaded["stage"] == "analyzing"
        assert loaded["data"]["progress"] == 0.5
        assert "timestamp" in loaded

    def test_load_nonexistent(self, fm, project_id):
        result = fm.load_checkpoint(project_id)
        assert result is None

    def test_overwrite_checkpoint(self, fm, project_id):
        fm.create_project(project_id)
        fm.save_checkpoint(project_id, stage="analyzing", data={"v": 1})
        fm.save_checkpoint(project_id, stage="outlining", data={"v": 2})

        loaded = fm.load_checkpoint(project_id)
        assert loaded["stage"] == "outlining"
        assert loaded["data"]["v"] == 2

    def test_save_creates_dir_if_missing(self, fm, project_id):
        """即使未先 create_project 也能保存"""
        fm.save_checkpoint(project_id, stage="test", data={"x": 1})
        loaded = fm.load_checkpoint(project_id)
        assert loaded is not None
        assert loaded["data"]["x"] == 1

    def test_checkpoint_is_valid_json(self, fm, project_id):
        fm.create_project(project_id)
        fm.save_checkpoint(project_id, stage="s", data={"k": "v"})
        ckpt_path = fm.get_checkpoint_path(project_id)
        raw = ckpt_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert "stage" in parsed
        assert "timestamp" in parsed
        assert "data" in parsed


class TestPaths:

    def test_get_image_path(self, fm, project_id):
        path = fm.get_image_path(project_id, 3)
        assert path.name == "slide_3.png"
        assert "images" in str(path)

    def test_get_image_dir(self, fm, project_id):
        d = fm.get_image_dir(project_id)
        assert d.name == "images"

    def test_get_output_path(self, fm, project_id):
        path = fm.get_output_path(project_id)
        assert path.suffix == ".pptx"
        assert project_id in path.name
        assert "output" in str(path)

    def test_get_checkpoint_path(self, fm, project_id):
        path = fm.get_checkpoint_path(project_id)
        assert path.name == "latest.json"
        assert "checkpoints" in str(path)

    def test_paths_under_workspace(self, fm, project_id):
        """所有路径都在 workspace 下"""
        workspace = fm.workspace
        assert str(fm.get_image_path(project_id, 1)).startswith(str(workspace))
        assert str(fm.get_output_path(project_id)).startswith(str(workspace))
        assert str(fm.get_checkpoint_path(project_id)).startswith(str(workspace))
