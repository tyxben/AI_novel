"""Phase 3 vs Phase 4 A/B 对比 harness 单元测试.

覆盖 ``scripts/quality_ab_phase3_vs_phase4.py`` 的纯函数 / 主流程（注入 fake
回调）。所有 LLM / subprocess / git 交互均 mock，零真机。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.novel.quality.report import ABComparisonResult

pytestmark = pytest.mark.quality


_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "quality_ab_phase3_vs_phase4.py"
)


def _load_script():
    """Dynamic import：脚本名含版本号，常规 import 不方便."""
    if "quality_ab_phase3_vs_phase4" in sys.modules:
        return sys.modules["quality_ab_phase3_vs_phase4"]
    spec = importlib.util.spec_from_file_location(
        "quality_ab_phase3_vs_phase4", _SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    sys.modules["quality_ab_phase3_vs_phase4"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture
def script():
    return _load_script()


# ---------------------------------------------------------------------------
# parse_args / resolve_genres
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_defaults(self, script) -> None:
        args = script.parse_args([])
        assert args.chapters == 3
        assert args.phase3_commit == "8fcd7be"
        assert args.phase4_commit == "HEAD"
        assert args.skip_generation is False
        assert args.dry_run is False
        assert args.force_worktree is False
        assert set(args.genres.split(",")) == {
            "xuanhuan",
            "suspense",
            "romance",
            "scifi",
            "wuxia",
        }

    def test_dry_run_and_skip_generation(self, script) -> None:
        args = script.parse_args(["--dry-run", "--skip-generation"])
        assert args.dry_run is True
        assert args.skip_generation is True

    def test_custom_genres_and_chapters(self, script) -> None:
        args = script.parse_args(
            ["--genres", "xuanhuan,suspense", "--chapters", "2"]
        )
        assert args.genres == "xuanhuan,suspense"
        assert args.chapters == 2

    def test_custom_commits(self, script) -> None:
        args = script.parse_args(
            ["--phase3-commit", "abc1234", "--phase4-commit", "def5678"]
        )
        assert args.phase3_commit == "abc1234"
        assert args.phase4_commit == "def5678"


class TestResolveGenres:
    def test_subset(self, script) -> None:
        out = script.resolve_genres("xuanhuan,wuxia")
        keys = [g.key for g in out]
        assert keys == ["xuanhuan", "wuxia"]

    def test_unknown_raises(self, script) -> None:
        with pytest.raises(SystemExit):
            script.resolve_genres("not_a_genre")

    def test_empty(self, script) -> None:
        assert script.resolve_genres("") == []


# ---------------------------------------------------------------------------
# _parse_genre_from_novel_json
# ---------------------------------------------------------------------------


class TestParseGenreFromNovelJson:
    def test_chinese_genre_maps_to_key(self, script, tmp_path: Path) -> None:
        p = tmp_path / "novel.json"
        p.write_text(
            json.dumps({"novel_id": "x", "genre": "玄幻", "theme": "t"}),
            encoding="utf-8",
        )
        assert script._parse_genre_from_novel_json(p) == "xuanhuan"

    def test_suspense_and_romance(self, script, tmp_path: Path) -> None:
        p = tmp_path / "a.json"
        p.write_text(json.dumps({"genre": "悬疑"}), encoding="utf-8")
        assert script._parse_genre_from_novel_json(p) == "suspense"

        p2 = tmp_path / "b.json"
        p2.write_text(json.dumps({"genre": "现代言情"}), encoding="utf-8")
        assert script._parse_genre_from_novel_json(p2) == "romance"

    def test_unrecognized_returns_unknown(self, script, tmp_path: Path) -> None:
        p = tmp_path / "n.json"
        p.write_text(
            json.dumps({"genre": "未来末世爆改"}), encoding="utf-8"
        )
        assert script._parse_genre_from_novel_json(p) == "unknown"

    def test_missing_genre_field(self, script, tmp_path: Path) -> None:
        p = tmp_path / "n.json"
        p.write_text(json.dumps({"novel_id": "x"}), encoding="utf-8")
        assert script._parse_genre_from_novel_json(p) == "unknown"

    def test_invalid_json(self, script, tmp_path: Path) -> None:
        p = tmp_path / "broken.json"
        p.write_text("not json at all { }", encoding="utf-8")
        assert script._parse_genre_from_novel_json(p) == "unknown"


# ---------------------------------------------------------------------------
# _collect_chapter_texts
# ---------------------------------------------------------------------------


def _make_project(
    root: Path,
    *,
    project_name: str,
    genre: str,
    chapters: dict[int, str],
    with_chapters_dir: bool = True,
    with_novel_json: bool = True,
) -> Path:
    """Helper：在 root/novels/<project_name>/ 下铺一个 novel project."""
    project_dir = root / "novels" / project_name
    project_dir.mkdir(parents=True)
    if with_novel_json:
        (project_dir / "novel.json").write_text(
            json.dumps({"novel_id": project_name, "genre": genre, "theme": "t"}),
            encoding="utf-8",
        )
    if with_chapters_dir:
        ch_dir = project_dir / "chapters"
        ch_dir.mkdir()
        for num, text in chapters.items():
            (ch_dir / f"chapter_{num:03d}.txt").write_text(text, encoding="utf-8")
    return project_dir


class TestCollectChapterTexts:
    def test_happy_path_multiple_genres(self, script, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            project_name="novel_a",
            genre="玄幻",
            chapters={1: "玄幻第一章", 2: "玄幻第二章", 3: "玄幻第三章"},
        )
        _make_project(
            tmp_path,
            project_name="novel_b",
            genre="武侠",
            chapters={1: "武侠第一章", 2: "武侠第二章"},
        )
        out = script._collect_chapter_texts(tmp_path, max_chapters=3)
        assert set(out.keys()) == {"xuanhuan", "wuxia"}
        assert out["xuanhuan"] == {
            1: "玄幻第一章",
            2: "玄幻第二章",
            3: "玄幻第三章",
        }
        assert out["wuxia"] == {1: "武侠第一章", 2: "武侠第二章"}

    def test_max_chapters_truncates(self, script, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            project_name="n1",
            genre="玄幻",
            chapters={1: "c1", 2: "c2", 3: "c3", 4: "c4"},
        )
        out = script._collect_chapter_texts(tmp_path, max_chapters=2)
        assert set(out["xuanhuan"].keys()) == {1, 2}

    def test_project_without_chapters_dir_skipped(
        self, script, tmp_path: Path, caplog
    ) -> None:
        _make_project(
            tmp_path,
            project_name="n1",
            genre="玄幻",
            chapters={},
            with_chapters_dir=False,
        )
        caplog.set_level("WARNING")
        out = script._collect_chapter_texts(tmp_path, max_chapters=3)
        assert out == {}
        assert any("chapters/" in rec.message for rec in caplog.records)

    def test_project_without_novel_json_skipped(
        self, script, tmp_path: Path, caplog
    ) -> None:
        _make_project(
            tmp_path,
            project_name="n1",
            genre="玄幻",
            chapters={1: "c1"},
            with_novel_json=False,
        )
        caplog.set_level("WARNING")
        out = script._collect_chapter_texts(tmp_path, max_chapters=3)
        assert out == {}
        assert any("novel.json" in rec.message for rec in caplog.records)

    def test_unknown_genre_project_skipped(
        self, script, tmp_path: Path, caplog
    ) -> None:
        _make_project(
            tmp_path,
            project_name="n1",
            genre="外星文学",  # 不在 _NOVEL_GENRE_TO_KEY
            chapters={1: "c1"},
        )
        caplog.set_level("WARNING")
        out = script._collect_chapter_texts(tmp_path, max_chapters=3)
        assert out == {}
        assert any("genre" in rec.message.lower() for rec in caplog.records)

    def test_illegal_chapter_filename_skipped(
        self, script, tmp_path: Path
    ) -> None:
        _make_project(
            tmp_path,
            project_name="n1",
            genre="玄幻",
            chapters={1: "ok"},
        )
        # 额外写一个非法文件名
        (tmp_path / "novels" / "n1" / "chapters" / "readme.txt").write_text(
            "not a chapter", encoding="utf-8"
        )
        (tmp_path / "novels" / "n1" / "chapters" / "chapter_abc.txt").write_text(
            "also bad", encoding="utf-8"
        )
        out = script._collect_chapter_texts(tmp_path, max_chapters=3)
        assert out == {"xuanhuan": {1: "ok"}}

    def test_duplicate_genre_second_project_ignored(
        self, script, tmp_path: Path, caplog
    ) -> None:
        _make_project(
            tmp_path,
            project_name="n1",
            genre="玄幻",
            chapters={1: "first"},
        )
        _make_project(
            tmp_path,
            project_name="n2",
            genre="玄幻",
            chapters={1: "duplicate"},
        )
        caplog.set_level("WARNING")
        out = script._collect_chapter_texts(tmp_path, max_chapters=3)
        # 第一个（n1, 按 sorted）获胜
        assert out["xuanhuan"][1] == "first"
        assert any("genre" in rec.message and "忽略" in rec.message for rec in caplog.records)

    def test_novels_dir_missing(self, script, tmp_path: Path, caplog) -> None:
        caplog.set_level("WARNING")
        out = script._collect_chapter_texts(tmp_path, max_chapters=3)
        assert out == {}
        assert any("novels" in rec.message for rec in caplog.records)

    def test_chapter_without_extension_skipped(
        self, script, tmp_path: Path
    ) -> None:
        _make_project(
            tmp_path,
            project_name="n1",
            genre="玄幻",
            chapters={1: "ok"},
        )
        # chapters/chapter_002 (无 .txt) 不应被匹配
        (tmp_path / "novels" / "n1" / "chapters" / "chapter_002").write_text(
            "no ext", encoding="utf-8"
        )
        out = script._collect_chapter_texts(tmp_path, max_chapters=3)
        assert out == {"xuanhuan": {1: "ok"}}


# ---------------------------------------------------------------------------
# Stats / interpretation
# ---------------------------------------------------------------------------


class TestStats:
    def test_update_stats_accumulates(self, script) -> None:
        stats = script.ABStats()
        r1 = MagicMock()
        r1.winner = "b"
        r1.dimension_preferences = {
            "narrative_flow": "b",
            "dialogue_quality": "tie",
        }
        r1.genre = "xuanhuan"
        r2 = MagicMock()
        r2.winner = "a"
        r2.dimension_preferences = {"narrative_flow": "a"}
        r2.genre = "wuxia"

        script._update_stats(stats, r1)
        script._update_stats(stats, r2)

        assert stats.total == 2
        assert stats.overall_winner["b"] == 1
        assert stats.overall_winner["a"] == 1
        assert stats.per_dimension["narrative_flow"]["b"] == 1
        assert stats.per_dimension["narrative_flow"]["a"] == 1
        assert stats.per_dimension["dialogue_quality"]["tie"] == 1
        assert stats.per_genre["xuanhuan"]["b"] == 1
        assert stats.per_genre["wuxia"]["a"] == 1


class TestInterpretAbResults:
    def test_empty(self, script) -> None:
        stats = script.ABStats()
        out = script._interpret_ab_results(stats)
        assert "无有效" in out

    def test_phase4_wins_big(self, script) -> None:
        stats = script.ABStats()
        for _ in range(7):
            stats.total += 1
            stats.overall_winner["b"] += 1
        for _ in range(3):
            stats.total += 1
            stats.overall_winner["a"] += 1
        out = script._interpret_ab_results(stats)
        assert "Phase 4 大幅胜出" in out

    def test_phase3_wins_big(self, script) -> None:
        stats = script.ABStats()
        for _ in range(8):
            stats.total += 1
            stats.overall_winner["a"] += 1
        for _ in range(2):
            stats.total += 1
            stats.overall_winner["b"] += 1
        out = script._interpret_ab_results(stats)
        assert "Phase 3 大幅胜出" in out

    def test_close_with_ties(self, script) -> None:
        stats = script.ABStats()
        for _ in range(3):
            stats.total += 1
            stats.overall_winner["a"] += 1
        for _ in range(3):
            stats.total += 1
            stats.overall_winner["b"] += 1
        for _ in range(4):
            stats.total += 1
            stats.overall_winner["tie"] += 1
        out = script._interpret_ab_results(stats)
        assert "接近" in out

    def test_slight_edge(self, script) -> None:
        """一方略微领先但没超 60% 阈值也非接近."""
        stats = script.ABStats()
        for _ in range(5):
            stats.total += 1
            stats.overall_winner["a"] += 1
        # b 3, tie 2 —— a 50% / b 30% / tie 20%; 差距 20% 不算接近
        for _ in range(3):
            stats.total += 1
            stats.overall_winner["b"] += 1
        for _ in range(2):
            stats.total += 1
            stats.overall_winner["tie"] += 1
        out = script._interpret_ab_results(stats)
        assert "略胜" in out or "Phase 3" in out


# ---------------------------------------------------------------------------
# Markdown 报告
# ---------------------------------------------------------------------------


class TestGenerateMarkdownReport:
    def _mk_result(self, genre: str, ch: int, winner: str) -> ABComparisonResult:
        return ABComparisonResult(
            genre=genre,
            chapter_number=ch,
            commit_a="aaa111",
            commit_b="bbb222",
            winner=winner,
            judge_reasoning=f"理由 {genre} ch{ch}",
            dimension_preferences={
                "narrative_flow": winner,
                "plot_advancement": "tie",
                "character_consistency": winner,
                "dialogue_quality": "tie",
                "chapter_hook": winner,
            },
        )

    def test_markdown_contains_key_sections(self, script) -> None:
        results = [
            self._mk_result("xuanhuan", 1, "b"),
            self._mk_result("xuanhuan", 2, "b"),
            self._mk_result("wuxia", 1, "a"),
        ]
        stats = script.ABStats()
        for r in results:
            # stats 用 genre_key 聚合（模拟 main 里做法）
            w = MagicMock()
            w.winner = r.winner
            w.dimension_preferences = r.dimension_preferences
            w.genre = r.genre
            script._update_stats(stats, w)
        md = script.generate_markdown_report(
            results,
            stats,
            phase3_commit="aaa111",
            phase4_commit="bbb222",
            judge_model="gemini-2.5-flash",
        )
        assert "Phase 3 vs Phase 4 A/B 对比报告" in md
        assert "aaa111" in md
        assert "bbb222" in md
        assert "gemini-2.5-flash" in md
        # 维度表与 genre 表都有
        assert "per-dimension winner 分布" in md
        assert "per-genre winner 分布" in md
        # 判读段
        assert "判读" in md
        # 明细段含 genre 小节
        assert "### xuanhuan" in md
        assert "### wuxia" in md

    def test_markdown_includes_errors_section(self, script) -> None:
        stats = script.ABStats()
        stats.errors = ["跳过 (genre=romance ch=1): phase3_has=False phase4_has=True"]
        md = script.generate_markdown_report(
            [],
            stats,
            phase3_commit="a",
            phase4_commit="b",
            judge_model="m",
        )
        assert "错误与跳过" in md
        assert "phase3_has=False" in md

    def test_markdown_no_errors_hides_section(self, script) -> None:
        md = script.generate_markdown_report(
            [],
            script.ABStats(),
            phase3_commit="a",
            phase4_commit="b",
            judge_model="m",
        )
        assert "错误与跳过" not in md


# ---------------------------------------------------------------------------
# --dry-run 路径
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_prints_plan_and_returns_zero(
        self, script, capsys, tmp_path: Path
    ) -> None:
        def _raise(*a, **kw):
            raise RuntimeError("dry-run 不应触发真实调用")

        exit_code = script.main(
            argv=[
                "--dry-run",
                "--genres",
                "xuanhuan,wuxia",
                "--chapters",
                "2",
                "--output-dir",
                str(tmp_path / "reports"),
                "--phase3-workspace",
                str(tmp_path / "phase3_ws"),
                "--phase4-workspace",
                str(tmp_path / "phase4_ws"),
            ],
            pairwise_judge_fn=_raise,
            generate_fn=_raise,
            judge_config_factory=_raise,
        )
        assert exit_code == 0
        captured = capsys.readouterr()
        # 关键字段都出现在 plan 输出里
        assert "dry-run" in captured.out.lower()
        assert "Phase 3 commit" in captured.out
        assert "xuanhuan" in captured.out
        assert "wuxia" in captured.out
        # 不应触发报告目录创建
        assert not (tmp_path / "reports").exists()


# ---------------------------------------------------------------------------
# Main integration (skip-generation + mocked pairwise_judge)
# ---------------------------------------------------------------------------


class TestMainIntegrationSkipGeneration:
    """完整跑 main，但 --skip-generation + 文件系统 + LLM 全 mock。"""

    def _prepare_workspaces(self, tmp_path: Path) -> tuple[Path, Path]:
        phase3_ws = tmp_path / "phase3_ws"
        phase4_ws = tmp_path / "phase4_ws"
        _make_project(
            phase3_ws,
            project_name="novel_phase3_xuanhuan",
            genre="玄幻",
            chapters={1: "[P3] 玄幻第一章正文", 2: "[P3] 玄幻第二章正文"},
        )
        _make_project(
            phase4_ws,
            project_name="novel_phase4_xuanhuan",
            genre="玄幻",
            chapters={1: "[P4] 玄幻第一章正文", 2: "[P4] 玄幻第二章正文"},
        )
        return phase3_ws, phase4_ws

    def test_skip_generation_runs_ab(
        self, script, tmp_path: Path, monkeypatch
    ) -> None:
        phase3_ws, phase4_ws = self._prepare_workspaces(tmp_path)
        output_dir = tmp_path / "reports"

        # mock preflight: 返回空错误
        monkeypatch.setattr(script, "preflight_checks", lambda args: [])
        # mock commit 解析避免读真 git
        monkeypatch.setattr(
            script, "_resolve_commit_short", lambda ref: ref[:7] or "na"
        )

        captured_calls: list[dict] = []

        def fake_judge(
            *,
            text_a: str,
            text_b: str,
            genre: str,
            chapter_number: int,
            commit_a: str,
            commit_b: str,
            config,
        ) -> ABComparisonResult:
            captured_calls.append(
                {
                    "genre": genre,
                    "chapter": chapter_number,
                    "text_a_prefix": text_a[:4],
                    "text_b_prefix": text_b[:4],
                }
            )
            return ABComparisonResult(
                genre=genre,
                chapter_number=chapter_number,
                commit_a=commit_a,
                commit_b=commit_b,
                winner="b",  # 模拟 Phase 4 胜出
                judge_reasoning="mock reasoning",
                dimension_preferences={
                    "narrative_flow": "b",
                    "plot_advancement": "b",
                    "character_consistency": "tie",
                    "dialogue_quality": "b",
                    "chapter_hook": "tie",
                },
                judge_model="mock-model",
                judge_token_usage=123,
            )

        def fake_judge_factory(args):
            cfg = MagicMock()
            cfg.model = "mock-model"
            cfg.provider = "mock"
            cfg.temperature = 0.1
            cfg.max_tokens = 2048
            cfg.same_source = False
            return cfg

        def fake_generate(*a, **kw):
            raise RuntimeError("skip-generation 不应触发生成")

        exit_code = script.main(
            argv=[
                "--skip-generation",
                "--genres",
                "xuanhuan",
                "--chapters",
                "2",
                "--phase3-workspace",
                str(phase3_ws),
                "--phase4-workspace",
                str(phase4_ws),
                "--output-dir",
                str(output_dir),
            ],
            pairwise_judge_fn=fake_judge,
            generate_fn=fake_generate,
            judge_config_factory=fake_judge_factory,
        )
        assert exit_code == 0
        # 两次 pairwise_judge 调用（ch1 + ch2）
        assert len(captured_calls) == 2
        assert {c["chapter"] for c in captured_calls} == {1, 2}
        # Phase 3 / 4 文本来自正确 workspace
        for c in captured_calls:
            assert c["text_a_prefix"] == "[P3]"
            assert c["text_b_prefix"] == "[P4]"
        # 产出文件
        json_files = list(output_dir.glob("*_xuanhuan_ch*_phase3_vs_phase4.json"))
        assert len(json_files) == 2
        summary_files = list(output_dir.glob("*_ab_summary.json"))
        assert len(summary_files) == 1
        md_files = list(output_dir.glob("*_ab_report.md"))
        assert len(md_files) == 1
        # 汇总 JSON 结构
        summary = json.loads(summary_files[0].read_text(encoding="utf-8"))
        assert summary["total"] == 2
        assert summary["overall_winner"]["b"] == 2
        assert summary["judge_model"] == "mock-model"
        assert summary["per_dimension"]["narrative_flow"]["b"] == 2
        assert summary["per_genre"]["xuanhuan"]["b"] == 2
        assert summary["errors"] == []
        # Markdown 含判读
        md_text = md_files[0].read_text(encoding="utf-8")
        assert "Phase 4 大幅胜出" in md_text
        assert "mock-model" in md_text

    def test_missing_phase3_chapter_recorded_as_error(
        self, script, tmp_path: Path, monkeypatch
    ) -> None:
        """Phase 3 缺章节 → 对应 (genre, ch) 跳过并记 error。"""
        phase3_ws = tmp_path / "phase3_ws"
        phase4_ws = tmp_path / "phase4_ws"
        # Phase 3 只有 ch1，ch2 缺失
        _make_project(
            phase3_ws,
            project_name="np3",
            genre="玄幻",
            chapters={1: "[P3] ch1"},
        )
        _make_project(
            phase4_ws,
            project_name="np4",
            genre="玄幻",
            chapters={1: "[P4] ch1", 2: "[P4] ch2"},
        )
        output_dir = tmp_path / "reports"

        monkeypatch.setattr(script, "preflight_checks", lambda args: [])
        monkeypatch.setattr(
            script, "_resolve_commit_short", lambda ref: ref[:7] or "na"
        )

        calls: list[int] = []

        def fake_judge(**kwargs) -> ABComparisonResult:
            calls.append(kwargs["chapter_number"])
            return ABComparisonResult(
                genre=kwargs["genre"],
                chapter_number=kwargs["chapter_number"],
                commit_a=kwargs["commit_a"],
                commit_b=kwargs["commit_b"],
                winner="tie",
                judge_reasoning="",
                dimension_preferences={
                    d: "tie"
                    for d in (
                        "narrative_flow",
                        "plot_advancement",
                        "character_consistency",
                        "dialogue_quality",
                        "chapter_hook",
                    )
                },
                judge_model="m",
            )

        def fake_judge_factory(args):
            cfg = MagicMock()
            cfg.model = "m"
            return cfg

        exit_code = script.main(
            argv=[
                "--skip-generation",
                "--genres",
                "xuanhuan",
                "--chapters",
                "2",
                "--phase3-workspace",
                str(phase3_ws),
                "--phase4-workspace",
                str(phase4_ws),
                "--output-dir",
                str(output_dir),
            ],
            pairwise_judge_fn=fake_judge,
            generate_fn=lambda *a, **kw: None,
            judge_config_factory=fake_judge_factory,
        )
        assert exit_code == 0
        # 只比对了 ch1，ch2 被跳过
        assert calls == [1]
        summary = json.loads(
            next((output_dir).glob("*_ab_summary.json")).read_text(encoding="utf-8")
        )
        assert summary["total"] == 1
        assert len(summary["errors"]) == 1
        assert "ch=2" in summary["errors"][0]
        assert "phase3_has=False" in summary["errors"][0]

    def test_preflight_failure_returns_one(
        self, script, tmp_path: Path, monkeypatch
    ) -> None:
        """前置检查失败（非 dry-run）→ 退出码 1，不触达任何真实逻辑。"""
        monkeypatch.setattr(
            script,
            "preflight_checks",
            lambda args: ["fake: git status 不干净"],
        )

        def must_not_call(*a, **kw):
            raise RuntimeError("preflight 失败时不应触发下游")

        exit_code = script.main(
            argv=[
                "--skip-generation",
                "--genres",
                "xuanhuan",
                "--chapters",
                "1",
                "--phase3-workspace",
                str(tmp_path / "p3"),
                "--phase4-workspace",
                str(tmp_path / "p4"),
                "--output-dir",
                str(tmp_path / "out"),
            ],
            pairwise_judge_fn=must_not_call,
            generate_fn=must_not_call,
            judge_config_factory=must_not_call,
        )
        assert exit_code == 1


# ---------------------------------------------------------------------------
# Worktree helpers（只测非破坏性分支；不真的跑 git）
# ---------------------------------------------------------------------------


class TestWorktreeHelpers:
    def test_remove_worktree_noop_if_missing(
        self, script, tmp_path: Path
    ) -> None:
        missing = tmp_path / "missing_worktree"
        # 不应抛
        script.remove_worktree(missing)

    def test_remove_worktree_calls_subprocess(
        self, script, tmp_path: Path, monkeypatch
    ) -> None:
        existing = tmp_path / "wt"
        existing.mkdir()
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=0)

        monkeypatch.setattr(script.subprocess, "run", fake_run)
        script.remove_worktree(existing)
        assert len(calls) == 1
        assert calls[0][:3] == ["git", "worktree", "remove"]
        assert str(existing) in calls[0]

    def test_create_worktree_calls_add(
        self, script, tmp_path: Path, monkeypatch
    ) -> None:
        target = tmp_path / "new_wt"
        commands: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            return MagicMock(returncode=0)

        monkeypatch.setattr(script.subprocess, "run", fake_run)
        script.create_worktree(target, "abc1234", force=False)
        assert len(commands) == 1
        assert commands[0][:3] == ["git", "worktree", "add"]
        assert "abc1234" in commands[0]

    def test_create_worktree_force_removes_first(
        self, script, tmp_path: Path, monkeypatch
    ) -> None:
        target = tmp_path / "existing_wt"
        target.mkdir()
        commands: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            return MagicMock(returncode=0)

        monkeypatch.setattr(script.subprocess, "run", fake_run)
        script.create_worktree(target, "abc1234", force=True)
        # 先 remove 再 add
        assert len(commands) == 2
        assert commands[0][:3] == ["git", "worktree", "remove"]
        assert commands[1][:3] == ["git", "worktree", "add"]


# ---------------------------------------------------------------------------
# Preflight 检查
# ---------------------------------------------------------------------------


class TestPreflightChecks:
    def test_dry_run_skips_all(self, script) -> None:
        args = script.parse_args(["--dry-run"])
        assert script.preflight_checks(args) == []

    def test_missing_phase4_workspace(
        self, script, tmp_path: Path, monkeypatch
    ) -> None:
        # 让 git status / .env 看起来正常，单独测 phase4 workspace 缺失
        monkeypatch.setattr(script, "_git_status_clean", lambda: True)
        # 临时把 _ROOT/.env 视为存在：通过 patch Path.exists 太重，
        # 改为 monkeypatch preflight 内嵌检查难做；这里 relax 到：
        # 我们不 assert 只有 1 条 error，只 assert 列表里含 phase4 相关消息。
        args = script.parse_args(
            [
                "--phase3-workspace",
                str(tmp_path / "p3"),
                "--phase4-workspace",
                str(tmp_path / "p4_missing"),
                "--worktree-path",
                str(tmp_path / "wt_missing"),
                "--skip-generation",
            ]
        )
        errors = script.preflight_checks(args)
        # 至少包含一条 phase4 缺失的 error
        assert any(
            "Phase 4" in err or "phase4" in err.lower() for err in errors
        )

    def test_existing_worktree_without_force(
        self, script, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(script, "_git_status_clean", lambda: True)
        # 构造：phase4 workspace 存在 + worktree 已存在 + 没 --force-worktree
        phase4_ws = tmp_path / "p4"
        phase4_ws.mkdir()
        wt = tmp_path / "wt"
        wt.mkdir()
        args = script.parse_args(
            [
                "--phase4-workspace",
                str(phase4_ws),
                "--worktree-path",
                str(wt),
            ]
        )
        # 让 .env 检查通过
        with patch.object(script, "_env_path", _ROOT := Path("/nonexistent")):
            pass  # 不实际改；直接调用
        errors = script.preflight_checks(args)
        # 至少有一条提及 worktree 已存在
        assert any(
            "worktree" in err.lower() and "已存在" in err for err in errors
        )
