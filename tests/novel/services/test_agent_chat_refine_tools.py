"""Tests for the 4 self-refine / reflexion tools added to agent_chat."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.services.agent_chat import AgentToolExecutor, TOOLS


def _seed_novel(workspace: Path, novel_id: str = "novel_refine_test") -> dict:
    d = workspace / "novels" / novel_id
    d.mkdir(parents=True)
    novel_data = {
        "novel_id": novel_id,
        "title": "refine 工具测试",
        "genre": "玄幻",
        "current_chapter": 3,
        "outline": {
            "chapters": [
                {"chapter_number": 1, "title": "第一章", "goal": "开篇", "estimated_words": 2500},
                {"chapter_number": 2, "title": "第二章", "goal": "推进", "estimated_words": 2500},
            ]
        },
        "characters": [],
        "config": {"llm": {"provider": "auto"}},
    }
    (d / "novel.json").write_text(
        json.dumps(novel_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    chapters_dir = d / "chapters"
    chapters_dir.mkdir()
    for n in (1, 2):
        ch = {
            "chapter_number": n,
            "title": f"第{n}章",
            "full_text": f"林辰睁眼，第{n}章正文。" * 30,
            "word_count": 200,
        }
        (chapters_dir / f"chapter_{n:03d}.json").write_text(
            json.dumps(ch, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return novel_data


@pytest.fixture
def workspace(tmp_path):
    nid = "novel_refine_test"
    _seed_novel(tmp_path, nid)
    return tmp_path, nid


@pytest.fixture
def executor(workspace):
    ws, nid = workspace
    return AgentToolExecutor(str(ws), nid)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_all_four_registered(self):
        names = {t["name"] for t in TOOLS}
        for n in (
            "verify_chapter",
            "critique_chapter",
            "refine_chapter",
            "get_reflexion_log",
        ):
            assert n in names

    def test_methods_implemented(self):
        for n in (
            "verify_chapter",
            "critique_chapter",
            "refine_chapter",
            "get_reflexion_log",
        ):
            assert hasattr(AgentToolExecutor, f"_tool_{n}")


# ---------------------------------------------------------------------------
# verify_chapter (no LLM)
# ---------------------------------------------------------------------------


class TestVerifyChapter:
    def test_unknown_chapter_error(self, executor):
        r = executor.execute("verify_chapter", {"chapter_number": 99})
        assert "error" in r

    def test_clean_chapter_passes(self, executor, workspace):
        ws, nid = workspace
        from src.novel.storage.file_manager import FileManager

        FileManager(str(ws)).save_chapter(
            nid,
            1,
            {
                "chapter_number": 1,
                "title": "测试",
                "full_text": "林辰站在矿场前，目光扫过远处。" * 50,
            },
        )

        r = executor.execute("verify_chapter", {"chapter_number": 1})
        assert "passed" in r
        assert r["passed"] is True
        assert r["high_severity_count"] == 0

    def test_banned_word_detected(self, executor, workspace):
        """ai_flavor_hard_ban 里的"莫名的力量"出现 → 失败。

        watchlist 里的词（如"不由得"、"瞳孔骤缩"）由 critic 按场景判断，
        不在 verifier hard-fail 范围内。
        """
        ws, nid = workspace
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(ws))
        fm.save_chapter(
            nid,
            1,
            {
                "chapter_number": 1,
                "title": "测试",
                "full_text": "一股莫名的力量涌上心头。" * 3,
            },
        )
        r = executor.execute("verify_chapter", {"chapter_number": 1})
        assert r["passed"] is False
        assert any(f["rule"] == "banned_phrase" for f in r["failures"])

    def test_extra_banned_appended(self, executor, workspace):
        ws, nid = workspace
        from src.novel.storage.file_manager import FileManager

        FileManager(str(ws)).save_chapter(
            nid,
            1,
            {
                "chapter_number": 1,
                "title": "测试",
                "full_text": "林辰自定义禁词出现自定义禁词出现。",
            },
        )

        r = executor.execute(
            "verify_chapter",
            {"chapter_number": 1, "extra_banned": ["自定义禁词"]},
        )
        assert any(
            "自定义禁词" in f["detail"] for f in r["failures"]
        )

    def test_target_words_check(self, executor):
        r = executor.execute(
            "verify_chapter",
            {"chapter_number": 1, "target_words": 100000},
        )
        # 现有章节远短于 10万字
        assert any(f["rule"] == "length" for f in r["failures"])


# ---------------------------------------------------------------------------
# critique_chapter (mocked LLM)
# ---------------------------------------------------------------------------


class TestCritiqueChapter:
    def test_unknown_chapter_error(self, executor):
        r = executor.execute("critique_chapter", {"chapter_number": 99})
        assert "error" in r

    def test_critic_returns_structured(self, executor):
        critic_payload = {
            "strengths": ["开篇紧凑"],
            "issues": [
                {"type": "trope_overuse", "severity": "high", "quote": "x", "reason": "y"}
            ],
            "specific_revisions": [{"target": "x", "suggestion": "y"}],
            "overall_assessment": "OK",
        }
        fake_llm = MagicMock()
        fake_llm.chat.return_value = LLMResponse(
            content=json.dumps(critic_payload, ensure_ascii=False),
            model="m",
            usage=None,
        )

        with patch.object(
            AgentToolExecutor, "_llm_for_critic", return_value=fake_llm
        ):
            r = executor.execute("critique_chapter", {"chapter_number": 1})

        assert r["needs_refine"] is True
        assert r["high_severity_count"] == 1
        assert "开篇紧凑" in r["strengths"]
        assert len(r["issues"]) == 1
        assert r["issues"][0]["type"] == "trope_overuse"

    def test_llm_error_returned(self, executor):
        fake_llm = MagicMock()
        fake_llm.chat.side_effect = RuntimeError("LLM down")

        with patch.object(
            AgentToolExecutor, "_llm_for_critic", return_value=fake_llm
        ):
            r = executor.execute("critique_chapter", {"chapter_number": 1})
        # 不抛异常，返回空 issues
        assert r.get("needs_refine") is False
        assert r.get("issues") == []


# ---------------------------------------------------------------------------
# refine_chapter (mocked LLM full loop)
# ---------------------------------------------------------------------------


class TestRefineChapter:
    def test_published_chapter_refused(self, executor, workspace):
        ws, nid = workspace
        novel_path = ws / "novels" / nid / "novel.json"
        nd = json.loads(novel_path.read_text("utf-8"))
        nd["published_chapters"] = [1]
        novel_path.write_text(
            json.dumps(nd, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        r = executor.execute("refine_chapter", {"chapter_number": 1})
        assert r.get("status") == "refused"
        assert "已发布" in r.get("error", "")

    def test_refine_no_change_when_clean(self, executor, workspace):
        """干净的章节，verify pass + critic pass → final 与原文相同 → not changed.

        seed 时 estimated_words=2500，所以正文要写够 2500 字以避免长度检查失败。
        """
        ws, nid = workspace
        from src.novel.storage.file_manager import FileManager

        FileManager(str(ws)).save_chapter(
            nid,
            1,
            {
                "chapter_number": 1,
                "title": "测试",
                # 写到 ~2500 字符避免长度检查 fail
                "full_text": "林辰站在矿场前目光扫过远处。" * 200,
            },
        )

        fake_llm = MagicMock()
        fake_llm.chat.return_value = LLMResponse(
            content='{"strengths": ["clean"], "issues": []}',
            model="m",
            usage=None,
        )

        with patch.object(
            AgentToolExecutor, "_llm_for_critic", return_value=fake_llm
        ):
            r = executor.execute("refine_chapter", {"chapter_number": 1})

        assert r["changed"] is False
        assert r["verify_passed"] is True
        assert r["critic_passed"] is True

    def test_refine_changes_text_when_dirty(self, executor, workspace):
        """有 hard-ban 禁词 → verify 触发 rewrite → 落盘新文本."""
        ws, nid = workspace
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(str(ws))
        fm.save_chapter(
            nid,
            1,
            {
                "chapter_number": 1,
                "title": "测试",
                "full_text": "一股莫名的力量袭来。" * 10,
            },
        )

        new_text = "他眯起眼皱眉看向远方山峦上的浮云。" * 200

        fake_llm = MagicMock()
        responses = [
            LLMResponse(content=new_text, model="m", usage=None),
            LLMResponse(content='{"strengths": ["改进"], "issues": []}', model="m", usage=None),
        ]
        fake_llm.chat.side_effect = responses

        with patch.object(
            AgentToolExecutor, "_llm_for_critic", return_value=fake_llm
        ):
            r = executor.execute("refine_chapter", {"chapter_number": 1})

        assert r["changed"] is True
        reloaded = fm.load_chapter(nid, 1)
        assert "莫名的力量" not in reloaded["full_text"]
        assert reloaded["word_count"] > 0

    def test_unknown_chapter_error(self, executor):
        r = executor.execute("refine_chapter", {"chapter_number": 99})
        assert "error" in r


# ---------------------------------------------------------------------------
# get_reflexion_log
# ---------------------------------------------------------------------------


class TestGetReflexionLog:
    def test_empty_initially(self, executor):
        r = executor.execute("get_reflexion_log", {})
        assert r["total"] == 0
        assert r["entries"] == []

    def test_returns_entries_after_write(self, executor, workspace):
        ws, nid = workspace
        from src.novel.services.reflexion_memory import (
            ReflexionEntry,
            ReflexionMemory,
        )

        m = ReflexionMemory(ws / "novels" / nid)
        m.append(ReflexionEntry(chapter_number=1, lesson="开篇紧凑"))
        m.append(ReflexionEntry(chapter_number=5, lesson="对白过长"))

        r = executor.execute("get_reflexion_log", {})
        assert r["total"] == 2
        assert {e["chapter_number"] for e in r["entries"]} == {1, 5}

    def test_range_filter(self, executor, workspace):
        ws, nid = workspace
        from src.novel.services.reflexion_memory import (
            ReflexionEntry,
            ReflexionMemory,
        )

        m = ReflexionMemory(ws / "novels" / nid)
        for n in range(1, 11):
            m.append(ReflexionEntry(chapter_number=n, lesson=f"l{n}"))

        r = executor.execute(
            "get_reflexion_log", {"start_chapter": 3, "end_chapter": 6}
        )
        nums = sorted(e["chapter_number"] for e in r["entries"])
        assert nums == [3, 4, 5, 6]

    def test_invalid_range_ignored(self, executor):
        r = executor.execute(
            "get_reflexion_log", {"start_chapter": "abc", "end_chapter": None}
        )
        assert "entries" in r  # not crashing
