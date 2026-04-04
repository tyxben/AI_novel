"""Defensive tests for novel services — verifying bug fixes and edge cases.

Covers:
1. StructuredDB connection caching (Bug #9)
2. Chapter search reads .txt files (Bug #10)
3. novel_exists doesn't create directories (Bug #11)
4. mark_debt_fulfilled uses real chapter number (Bug #26)
5. NovelMemory close without save
6. Agent chat executor cleanup on exception
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. StructuredDB connection caching (Bug #9)
# ---------------------------------------------------------------------------


class TestStructuredDBCaching:
    """Verify AgentToolExecutor caches the StructuredDB instance."""

    def test_get_structured_db_returns_same_instance(self, tmp_path: Path) -> None:
        """Calling _get_structured_db() twice must return the exact same object."""
        from src.novel.services.agent_chat import AgentToolExecutor

        workspace = str(tmp_path)
        novel_id = "test_novel"
        project_dir = tmp_path / "novels" / novel_id
        project_dir.mkdir(parents=True)

        # Create a minimal memory.db so StructuredDB can open it
        db_path = project_dir / "memory.db"
        db_path.touch()

        executor = AgentToolExecutor(workspace, novel_id)
        try:
            db1 = executor._get_structured_db()
            db2 = executor._get_structured_db()

            assert db1 is not None, "First call should return a StructuredDB instance"
            assert db2 is not None, "Second call should return a StructuredDB instance"
            assert db1 is db2, "Both calls must return the exact same cached instance"
        finally:
            executor.close()

    def test_close_clears_cached_structured_db(self, tmp_path: Path) -> None:
        """After close(), _cached_structured_db must be None."""
        from src.novel.services.agent_chat import AgentToolExecutor

        workspace = str(tmp_path)
        novel_id = "test_novel"
        project_dir = tmp_path / "novels" / novel_id
        project_dir.mkdir(parents=True)
        (project_dir / "memory.db").touch()

        executor = AgentToolExecutor(workspace, novel_id)
        executor._get_structured_db()  # populate cache
        assert executor._cached_structured_db is not None

        executor.close()
        assert executor._cached_structured_db is None, (
            "close() must set _cached_structured_db to None"
        )

    def test_get_structured_db_returns_none_when_no_db_file(
        self, tmp_path: Path
    ) -> None:
        """If memory.db doesn't exist, _get_structured_db returns None."""
        from src.novel.services.agent_chat import AgentToolExecutor

        workspace = str(tmp_path)
        novel_id = "test_novel"
        project_dir = tmp_path / "novels" / novel_id
        project_dir.mkdir(parents=True)
        # No memory.db created

        executor = AgentToolExecutor(workspace, novel_id)
        try:
            result = executor._get_structured_db()
            assert result is None
        finally:
            executor.close()

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        """Calling close() multiple times must not raise."""
        from src.novel.services.agent_chat import AgentToolExecutor

        workspace = str(tmp_path)
        novel_id = "test_novel"
        project_dir = tmp_path / "novels" / novel_id
        project_dir.mkdir(parents=True)
        (project_dir / "memory.db").touch()

        executor = AgentToolExecutor(workspace, novel_id)
        executor._get_structured_db()

        executor.close()
        executor.close()  # second close must not raise
        assert executor._cached_structured_db is None


# ---------------------------------------------------------------------------
# 2. Chapter search reads .txt files (Bug #10)
# ---------------------------------------------------------------------------


class TestChapterSearchReadsTxt:
    """Verify _tool_search_chapters reads text from .txt files."""

    def _setup_chapters_dir(
        self, tmp_path: Path, novel_id: str, chapter_text: str
    ) -> Path:
        """Create chapters dir with a .json (no full_text) and a .txt (with text)."""
        chapters_dir = tmp_path / "novels" / novel_id / "chapters"
        chapters_dir.mkdir(parents=True)

        # JSON without full_text
        json_data = {
            "chapter_number": 1,
            "title": "第一章",
            "word_count": len(chapter_text),
            "status": "completed",
        }
        (chapters_dir / "chapter_001.json").write_text(
            json.dumps(json_data, ensure_ascii=False), encoding="utf-8"
        )

        # TXT with the actual chapter text
        (chapters_dir / "chapter_001.txt").write_text(
            chapter_text, encoding="utf-8"
        )

        return chapters_dir

    def test_search_finds_keyword_in_txt_file(self, tmp_path: Path) -> None:
        """Keyword present in .txt file must be found."""
        from src.novel.services.agent_chat import AgentToolExecutor

        novel_id = "search_novel"
        chapter_text = "少年萧炎站在悬崖边，望着远方的云海翻涌。"
        self._setup_chapters_dir(tmp_path, novel_id, chapter_text)

        executor = AgentToolExecutor(str(tmp_path), novel_id)
        try:
            result = executor._tool_search_chapters(keyword="萧炎")
            matches = result.get("matches", [])
            assert len(matches) == 1, f"Expected 1 match, got {len(matches)}"
            assert matches[0]["chapter_number"] == 1
            assert "萧炎" in matches[0]["context"]
        finally:
            executor.close()

    def test_search_returns_empty_for_missing_keyword(
        self, tmp_path: Path
    ) -> None:
        """Keyword not in any chapter must return empty matches."""
        from src.novel.services.agent_chat import AgentToolExecutor

        novel_id = "search_novel2"
        chapter_text = "少年萧炎站在悬崖边，望着远方的云海翻涌。"
        self._setup_chapters_dir(tmp_path, novel_id, chapter_text)

        executor = AgentToolExecutor(str(tmp_path), novel_id)
        try:
            result = executor._tool_search_chapters(keyword="不存在的关键词")
            matches = result.get("matches", [])
            assert len(matches) == 0, f"Expected 0 matches, got {len(matches)}"
        finally:
            executor.close()

    def test_search_does_not_match_json_metadata(
        self, tmp_path: Path
    ) -> None:
        """Keywords only in JSON metadata (not in text) must not match."""
        from src.novel.services.agent_chat import AgentToolExecutor

        novel_id = "search_novel3"
        chapters_dir = tmp_path / "novels" / novel_id / "chapters"
        chapters_dir.mkdir(parents=True)

        # JSON with a word that is NOT in the txt
        json_data = {
            "chapter_number": 1,
            "title": "宝藏之章",
            "word_count": 10,
            "status": "completed",
        }
        (chapters_dir / "chapter_001.json").write_text(
            json.dumps(json_data, ensure_ascii=False), encoding="utf-8"
        )
        # TXT with different content
        (chapters_dir / "chapter_001.txt").write_text(
            "天空湛蓝，白云悠悠。", encoding="utf-8"
        )

        executor = AgentToolExecutor(str(tmp_path), novel_id)
        try:
            # Search for a keyword that only appears in the JSON title
            # but the json full_text is absent and the txt doesn't have it
            result = executor._tool_search_chapters(keyword="宝藏")
            matches = result.get("matches", [])
            assert len(matches) == 0, (
                "Should not match keywords only present in JSON metadata, "
                f"but got {matches}"
            )
        finally:
            executor.close()

    def test_search_with_multiple_chapters(self, tmp_path: Path) -> None:
        """Search across multiple chapters should find all matches."""
        from src.novel.services.agent_chat import AgentToolExecutor

        novel_id = "search_multi"
        chapters_dir = tmp_path / "novels" / novel_id / "chapters"
        chapters_dir.mkdir(parents=True)

        texts = {
            1: "萧炎在学院里苦练功法。",
            2: "萧炎突破三段斗气。",
            3: "纳兰嫣然出现在比武场上。",
        }
        for ch_num, text in texts.items():
            json_data = {"chapter_number": ch_num, "title": f"第{ch_num}章"}
            (chapters_dir / f"chapter_{ch_num:03d}.json").write_text(
                json.dumps(json_data, ensure_ascii=False), encoding="utf-8"
            )
            (chapters_dir / f"chapter_{ch_num:03d}.txt").write_text(
                text, encoding="utf-8"
            )

        executor = AgentToolExecutor(str(tmp_path), novel_id)
        try:
            result = executor._tool_search_chapters(keyword="萧炎")
            matches = result.get("matches", [])
            assert len(matches) == 2, f"Expected 2 matches, got {len(matches)}"
            chapter_nums = {m["chapter_number"] for m in matches}
            assert chapter_nums == {1, 2}
        finally:
            executor.close()


# ---------------------------------------------------------------------------
# 3. novel_exists doesn't create directories (Bug #11)
# ---------------------------------------------------------------------------


class TestNovelExistsNoCreate:
    """Verify FileManager.novel_exists never creates directories on disk."""

    def test_novel_exists_returns_false_without_creating_dir(
        self, tmp_path: Path
    ) -> None:
        """novel_exists for a nonexistent novel must return False and NOT
        create the directory."""
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(tmp_path))
        novel_id = "nonexistent_novel"
        expected_dir = tmp_path / "novels" / novel_id

        assert not fm.novel_exists(novel_id)
        assert not expected_dir.exists(), (
            f"novel_exists must NOT create directory, but {expected_dir} exists"
        )

    def test_novel_dir_with_create_true_creates_directory(
        self, tmp_path: Path
    ) -> None:
        """_novel_dir(create=True) must create the directory."""
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(tmp_path))
        novel_id = "create_me"
        d = fm._novel_dir(novel_id, create=True)

        assert d.exists(), "_novel_dir(create=True) should create directory"
        assert d == tmp_path / "novels" / novel_id

    def test_novel_exists_returns_true_for_existing_novel(
        self, tmp_path: Path
    ) -> None:
        """novel_exists must return True when novel.json exists."""
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(tmp_path))
        novel_id = "existing_novel"

        # Manually create the directory and novel.json
        novel_dir = tmp_path / "novels" / novel_id
        novel_dir.mkdir(parents=True)
        (novel_dir / "novel.json").write_text(
            json.dumps({"title": "Test"}), encoding="utf-8"
        )

        assert fm.novel_exists(novel_id) is True

    def test_novel_exists_false_when_dir_exists_but_no_json(
        self, tmp_path: Path
    ) -> None:
        """Directory exists but novel.json is missing => False."""
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(tmp_path))
        novel_id = "dir_only"

        novel_dir = tmp_path / "novels" / novel_id
        novel_dir.mkdir(parents=True)
        # No novel.json

        assert fm.novel_exists(novel_id) is False


# ---------------------------------------------------------------------------
# 4. mark_debt_fulfilled uses real chapter number (Bug #26)
# ---------------------------------------------------------------------------


class TestManageDebtChapterNumber:
    """Verify _tool_manage_debt reads current_chapter from novel.json."""

    def _make_executor_with_novel(
        self, tmp_path: Path, novel_id: str, current_chapter: int
    ) -> "AgentToolExecutor":
        """Helper: create executor with a novel.json containing current_chapter."""
        from src.novel.services.agent_chat import AgentToolExecutor

        project_dir = tmp_path / "novels" / novel_id
        project_dir.mkdir(parents=True)

        novel_data = {
            "title": "测试小说",
            "current_chapter": current_chapter,
            "status": "in_progress",
        }
        (project_dir / "novel.json").write_text(
            json.dumps(novel_data, ensure_ascii=False), encoding="utf-8"
        )

        return AgentToolExecutor(str(tmp_path), novel_id)

    def test_fulfill_uses_current_chapter_from_novel_json(
        self, tmp_path: Path
    ) -> None:
        """Without explicit chapter_number, fulfill should use novel's
        current_chapter (15), not 0."""
        executor = self._make_executor_with_novel(
            tmp_path, "debt_novel", current_chapter=15
        )

        # Mock the obligation tracker to avoid needing a real DB
        mock_tracker = MagicMock()
        mock_tracker.mark_debt_fulfilled = MagicMock()

        with patch.object(
            executor, "_get_obligation_tracker", return_value=mock_tracker
        ):
            result = executor._tool_manage_debt(
                action="fulfill", debt_id="debt_5_0_abc"
            )

        assert result["status"] == "fulfilled"
        assert result["chapter_num"] == 15, (
            f"Expected chapter_num=15, got {result['chapter_num']}"
        )
        mock_tracker.mark_debt_fulfilled.assert_called_once_with(
            "debt_5_0_abc", chapter_num=15, note="Agent Chat 手动标记"
        )

    def test_fulfill_with_explicit_chapter_number(
        self, tmp_path: Path
    ) -> None:
        """Explicit chapter_number=20 should be used even if novel's
        current_chapter is 15."""
        executor = self._make_executor_with_novel(
            tmp_path, "debt_novel2", current_chapter=15
        )

        mock_tracker = MagicMock()
        mock_tracker.mark_debt_fulfilled = MagicMock()

        with patch.object(
            executor, "_get_obligation_tracker", return_value=mock_tracker
        ):
            result = executor._tool_manage_debt(
                action="fulfill",
                debt_id="debt_10_0_xyz",
                chapter_number=20,
            )

        assert result["status"] == "fulfilled"
        assert result["chapter_num"] == 20, (
            f"Expected chapter_num=20, got {result['chapter_num']}"
        )
        mock_tracker.mark_debt_fulfilled.assert_called_once_with(
            "debt_10_0_xyz", chapter_num=20, note="Agent Chat 手动标记"
        )

    def test_fulfill_without_novel_json_falls_back_to_zero(
        self, tmp_path: Path
    ) -> None:
        """If novel.json is missing, chapter_num should fall back to 0."""
        from src.novel.services.agent_chat import AgentToolExecutor

        novel_id = "no_novel"
        project_dir = tmp_path / "novels" / novel_id
        project_dir.mkdir(parents=True)
        # No novel.json

        executor = AgentToolExecutor(str(tmp_path), novel_id)
        mock_tracker = MagicMock()
        mock_tracker.mark_debt_fulfilled = MagicMock()

        with patch.object(
            executor, "_get_obligation_tracker", return_value=mock_tracker
        ):
            result = executor._tool_manage_debt(
                action="fulfill", debt_id="debt_1_0_zzz"
            )

        assert result["chapter_num"] == 0

    def test_manage_debt_add_requires_description(
        self, tmp_path: Path
    ) -> None:
        """add action without description must return error."""
        from src.novel.services.agent_chat import AgentToolExecutor

        executor = AgentToolExecutor(str(tmp_path), "any_novel")
        mock_tracker = MagicMock()

        with patch.object(
            executor, "_get_obligation_tracker", return_value=mock_tracker
        ):
            result = executor._tool_manage_debt(
                action="add", source_chapter=5
            )

        assert "error" in result

    def test_manage_debt_fulfill_requires_debt_id(
        self, tmp_path: Path
    ) -> None:
        """fulfill action without debt_id must return error."""
        from src.novel.services.agent_chat import AgentToolExecutor

        executor = AgentToolExecutor(str(tmp_path), "any_novel")
        mock_tracker = MagicMock()

        with patch.object(
            executor, "_get_obligation_tracker", return_value=mock_tracker
        ):
            result = executor._tool_manage_debt(action="fulfill")

        assert "error" in result

    def test_manage_debt_unknown_action(self, tmp_path: Path) -> None:
        """Unknown action must return error."""
        from src.novel.services.agent_chat import AgentToolExecutor

        executor = AgentToolExecutor(str(tmp_path), "any_novel")
        mock_tracker = MagicMock()

        with patch.object(
            executor, "_get_obligation_tracker", return_value=mock_tracker
        ):
            result = executor._tool_manage_debt(action="delete")

        assert "error" in result
        assert "delete" in result["error"]


# ---------------------------------------------------------------------------
# 5. NovelMemory close without save
# ---------------------------------------------------------------------------


class TestNovelMemoryCloseWithoutSave:
    """Verify NovelMemory.close() properly cleans up resources."""

    def test_close_without_save_clears_graph(self, tmp_path: Path) -> None:
        """Closing NovelMemory without save() should clear the graph."""
        from src.novel.storage.knowledge_graph import KnowledgeGraph
        from src.novel.storage.novel_memory import NovelMemory

        memory = NovelMemory("test_close", str(tmp_path))
        # Add some graph data
        memory.knowledge_graph.add_character("char1", "萧炎")
        memory.knowledge_graph.add_character("char2", "药老")
        assert memory.knowledge_graph.graph.number_of_nodes() == 2

        memory.close()

        # After close, the graph should be cleared
        assert memory.knowledge_graph.graph.number_of_nodes() == 0

    def test_close_via_context_manager(self, tmp_path: Path) -> None:
        """__exit__ should call close()."""
        from src.novel.storage.novel_memory import NovelMemory

        with NovelMemory("test_ctx", str(tmp_path)) as memory:
            memory.knowledge_graph.add_character("char1", "萧炎")
            assert memory.knowledge_graph.graph.number_of_nodes() == 1

        # After exiting the context, graph should be cleared
        assert memory.knowledge_graph.graph.number_of_nodes() == 0

    def test_save_then_close_persists_graph(self, tmp_path: Path) -> None:
        """Calling save() before close() should persist the graph."""
        from src.novel.storage.knowledge_graph import KnowledgeGraph
        from src.novel.storage.novel_memory import NovelMemory

        memory = NovelMemory("test_persist", str(tmp_path))
        memory.knowledge_graph.add_character("char1", "萧炎")
        memory.save()
        memory.close()

        # Verify the graph was persisted to disk
        graph_path = (
            tmp_path / "novels" / "test_persist" / "graph.json"
        )
        assert graph_path.exists(), "graph.json should be saved after save()"

        # Re-open and verify data is there
        memory2 = NovelMemory("test_persist", str(tmp_path))
        assert memory2.knowledge_graph.graph.number_of_nodes() == 1
        memory2.close()

    def test_close_closes_structured_db(self, tmp_path: Path) -> None:
        """close() should close the StructuredDB connection."""
        from src.novel.storage.novel_memory import NovelMemory

        memory = NovelMemory("test_db_close", str(tmp_path))
        # Verify DB is alive
        assert memory.structured_db._conn is not None

        memory.close()

        # After close, the StructuredDB connection should be None
        assert memory.structured_db._conn is None


# ---------------------------------------------------------------------------
# 6. Agent chat executor cleanup on exception
# ---------------------------------------------------------------------------


class TestExecutorCleanupOnException:
    """Verify executor.close() is called even when tool calls raise."""

    def test_executor_close_called_on_tool_exception(
        self, tmp_path: Path
    ) -> None:
        """If a tool raises, executor.close() in run_agent_chat's finally
        block must still execute."""
        from src.novel.services.agent_chat import AgentToolExecutor

        workspace = str(tmp_path)
        novel_id = "cleanup_test"
        project_dir = tmp_path / "novels" / novel_id
        project_dir.mkdir(parents=True)
        (project_dir / "memory.db").touch()

        executor = AgentToolExecutor(workspace, novel_id)
        # Populate cached DB
        executor._get_structured_db()
        assert executor._cached_structured_db is not None

        # Execute a tool that raises
        result = executor.execute("nonexistent_tool", {})
        assert "error" in result

        # Manually close and verify cleanup
        executor.close()
        assert executor._cached_structured_db is None

    def test_run_agent_chat_closes_executor_on_llm_error(
        self, tmp_path: Path
    ) -> None:
        """run_agent_chat must close the executor even when LLM raises."""
        from src.novel.services.agent_chat import AgentToolExecutor

        workspace = str(tmp_path)
        novel_id = "llm_error_test"
        project_dir = tmp_path / "novels" / novel_id
        project_dir.mkdir(parents=True)
        (project_dir / "novel.json").write_text(
            json.dumps({"title": "Test", "status": "in_progress"}),
            encoding="utf-8",
        )

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("LLM connection failed")

        close_called = {"count": 0}
        original_close = AgentToolExecutor.close

        def tracking_close(self_executor):
            close_called["count"] += 1
            original_close(self_executor)

        from src.novel.services import agent_chat

        with (
            patch("src.llm.llm_client.create_llm_client", return_value=mock_llm),
            patch.object(AgentToolExecutor, "close", tracking_close),
        ):
            try:
                agent_chat.run_agent_chat(
                    workspace=workspace,
                    novel_id=novel_id,
                    message="测试消息",
                )
            except RuntimeError:
                pass  # Expected -- LLM error propagates

        assert close_called["count"] >= 1, (
            "executor.close() must be called even when LLM raises"
        )

    def test_execute_returns_error_dict_on_tool_exception(
        self, tmp_path: Path
    ) -> None:
        """AgentToolExecutor.execute() must return an error dict, never
        propagate exceptions to the caller."""
        from src.novel.services.agent_chat import AgentToolExecutor

        executor = AgentToolExecutor(str(tmp_path), "any")

        # A tool that always raises
        def broken_tool(**kwargs: Any) -> dict:
            raise ValueError("Something went wrong")

        executor._tool_broken = broken_tool  # type: ignore[attr-defined]

        result = executor.execute("broken", {})
        assert "error" in result
        assert "Something went wrong" in result["error"]

    def test_execute_retries_on_transient_error(
        self, tmp_path: Path
    ) -> None:
        """Transient errors (connection, timeout) should be retried once."""
        from src.novel.services.agent_chat import AgentToolExecutor

        executor = AgentToolExecutor(str(tmp_path), "retry_test")

        call_count = {"n": 0}

        def flaky_tool(**kwargs: Any) -> dict:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ConnectionError("connection reset")
            return {"ok": True}

        executor._tool_flaky = flaky_tool  # type: ignore[attr-defined]

        with patch("time.sleep"):  # Skip the actual sleep
            result = executor.execute("flaky", {})

        assert result == {"ok": True}
        assert call_count["n"] == 2, "Should have been called twice (1 retry)"

    def test_execute_no_retry_on_non_transient_error(
        self, tmp_path: Path
    ) -> None:
        """Non-transient errors (ValueError, KeyError) should not be retried."""
        from src.novel.services.agent_chat import AgentToolExecutor

        executor = AgentToolExecutor(str(tmp_path), "no_retry_test")

        call_count = {"n": 0}

        def always_fails(**kwargs: Any) -> dict:
            call_count["n"] += 1
            raise ValueError("bad input")

        executor._tool_always_fails = always_fails  # type: ignore[attr-defined]

        result = executor.execute("always_fails", {})
        assert "error" in result
        assert call_count["n"] == 1, "Non-transient error should not be retried"
