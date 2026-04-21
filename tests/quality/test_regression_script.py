"""质量回归脚本的单元测试 (Phase 5 E3).

覆盖 ``scripts/quality_regression.py`` 的纯函数 / 主流程 (注入 fake 回调):
- parse_args / resolve_genres
- --dry-run 走 print_plan 分支, 不调任何 LLM
- --eval-only 跳过生成
- detect_regressions 1-5/0-100/percent 三种 scale 分支 + ai_flavor_index 倒转
- generate_markdown_report 包含关键字段
- render_rich_table 返回文本表示
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.novel.quality.report import (
    ABComparisonResult,
    ChapterQualityReport,
    DimensionScore,
)

pytestmark = pytest.mark.quality

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "quality_regression.py"
)


def _load_script():
    import sys as _sys

    if "quality_regression" in _sys.modules:
        return _sys.modules["quality_regression"]
    spec = importlib.util.spec_from_file_location("quality_regression", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    # 关键: 先注册到 sys.modules, 避免 dataclass 内部 lookup module 失败
    _sys.modules["quality_regression"] = mod
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
        assert args.repeat == 1
        assert args.dry_run is False
        assert args.eval_only is False
        assert args.workspace == "workspace_quality"
        # 默认 5 个体裁
        assert set(args.genres.split(",")) == {
            "xuanhuan", "suspense", "romance", "scifi", "wuxia",
        }

    def test_dry_run_flag(self, script) -> None:
        args = script.parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_custom_genres(self, script) -> None:
        args = script.parse_args(["--genres", "xuanhuan,wuxia", "--chapters", "2"])
        assert args.genres == "xuanhuan,wuxia"
        assert args.chapters == 2

    def test_compare_and_judge_model(self, script) -> None:
        args = script.parse_args(["--compare", "phase4", "--judge-model", "deepseek"])
        assert args.compare == "phase4"
        assert args.judge_model == "deepseek"


class TestResolveGenres:
    def test_two_genres(self, script) -> None:
        out = script.resolve_genres("xuanhuan,wuxia")
        keys = [g.key for g in out]
        assert keys == ["xuanhuan", "wuxia"]

    def test_unknown_raises(self, script) -> None:
        with pytest.raises(SystemExit):
            script.resolve_genres("mystery_genre")

    def test_empty_returns_empty(self, script) -> None:
        assert script.resolve_genres("") == []

    def test_strip_whitespace(self, script) -> None:
        out = script.resolve_genres(" xuanhuan , wuxia ")
        keys = [g.key for g in out]
        assert keys == ["xuanhuan", "wuxia"]


# ---------------------------------------------------------------------------
# --dry-run 路径
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_no_llm_call(self, script, capsys, tmp_path: Path) -> None:
        # generate_fn / evaluate_fn / ab_fn 全传 raise-on-call — dry-run 不应触达它们
        def _raise(*a, **kw):
            raise RuntimeError("dry-run 不应调用此函数")

        exit_code = script.main(
            argv=[
                "--dry-run",
                "--genres", "xuanhuan,wuxia",
                "--chapters", "2",
                "--workspace", str(tmp_path),
                "--output-dir", str(tmp_path / "reports"),
            ],
            generate_fn=_raise,
            evaluate_fn=_raise,
            ab_fn=_raise,
        )
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "dry-run" in captured.out.lower()
        assert "xuanhuan" in captured.out
        assert "wuxia" in captured.out
        # 没有实际写出报告目录
        assert not (tmp_path / "reports").exists()


# ---------------------------------------------------------------------------
# --eval-only 跳过生成
# ---------------------------------------------------------------------------


class TestEvalOnly:
    def test_eval_only_skips_generate(self, script, tmp_path: Path) -> None:
        """--eval-only 时 generate_fn 不应被调."""
        # 准备 input-dir: tmp_path/inputs/xuanhuan/chapters/chapter_001.txt
        input_root = tmp_path / "inputs"
        ch_dir = input_root / "xuanhuan" / "chapters"
        ch_dir.mkdir(parents=True)
        (ch_dir / "chapter_001.txt").write_text("章节正文", encoding="utf-8")

        gen_mock = MagicMock()
        eval_mock = MagicMock(return_value=ChapterQualityReport(
            chapter_number=1,
            genre="xuanhuan",
            scores=[
                DimensionScore(key="narrative_flow", score=4.0, scale="1-5"),
            ],
        ))

        exit_code = script.main(
            argv=[
                "--eval-only",
                "--input-dir", str(input_root),
                "--genres", "xuanhuan",
                "--chapters", "1",
                "--output-dir", str(tmp_path / "reports"),
            ],
            generate_fn=gen_mock,
            evaluate_fn=eval_mock,
            ab_fn=lambda *a, **kw: None,
        )
        # generate_fn 不应被调
        assert gen_mock.call_count == 0
        # eval_fn 应被调 1 次
        assert eval_mock.call_count == 1
        # 输出目录创建
        assert (tmp_path / "reports" / "single").exists()
        assert (tmp_path / "reports" / "summary").exists()
        # 退出码 0 (没 baseline, 没 regression)
        assert exit_code == 0


# ---------------------------------------------------------------------------
# detect_regressions
# ---------------------------------------------------------------------------


def _report(genre: str, ch: int, scores: list[tuple[str, float, str]]) -> ChapterQualityReport:
    return ChapterQualityReport(
        chapter_number=ch,
        genre=genre,
        scores=[DimensionScore(key=k, score=s, scale=sc) for k, s, sc in scores],
    )


class TestDetectRegressions:
    def test_empty_baseline_no_regressions(self, script) -> None:
        current = [_report("xuanhuan", 1, [("narrative_flow", 3.0, "1-5")])]
        assert script.detect_regressions(current, None) == []
        assert script.detect_regressions(current, []) == []

    def test_1_5_scale_drop_triggers_regression(self, script) -> None:
        baseline = [_report("xuanhuan", 1, [("narrative_flow", 4.0, "1-5")])]
        current = [_report("xuanhuan", 1, [("narrative_flow", 2.8, "1-5")])]
        regs = script.detect_regressions(current, baseline)
        assert len(regs) == 1
        assert regs[0].dimension == "narrative_flow"
        assert regs[0].baseline_score == pytest.approx(4.0)
        assert regs[0].current_score == pytest.approx(2.8)
        assert regs[0].delta == pytest.approx(-1.2)
        line = regs[0].as_line()
        assert "REGRESSION" in line
        assert "xuanhuan" in line

    def test_1_5_scale_small_drop_no_regression(self, script) -> None:
        baseline = [_report("xuanhuan", 1, [("narrative_flow", 4.0, "1-5")])]
        current = [_report("xuanhuan", 1, [("narrative_flow", 3.5, "1-5")])]
        # delta=-0.5 < 1.0 threshold, 不算退化
        assert script.detect_regressions(current, baseline) == []

    def test_percent_scale_drop(self, script) -> None:
        baseline = [_report("scifi", 1, [("foreshadow_payoff", 80.0, "percent")])]
        current = [_report("scifi", 1, [("foreshadow_payoff", 60.0, "percent")])]
        # delta=-20 >= 15 threshold
        regs = script.detect_regressions(current, baseline)
        assert len(regs) == 1
        assert regs[0].dimension == "foreshadow_payoff"
        assert regs[0].delta == pytest.approx(-20.0)

    def test_ai_flavor_inverted_direction(self, script) -> None:
        """AI 味指数越低越好：上升超阈值才算退化."""
        baseline = [_report("xuanhuan", 1, [("ai_flavor_index", 30.0, "0-100")])]
        # 上升 20 分 → 退化
        current = [_report("xuanhuan", 1, [("ai_flavor_index", 50.0, "0-100")])]
        regs = script.detect_regressions(current, baseline)
        assert len(regs) == 1
        assert regs[0].dimension == "ai_flavor_index"
        assert regs[0].delta == pytest.approx(20.0)

    def test_ai_flavor_drop_not_regression(self, script) -> None:
        """AI 味指数下降是好事, 不算退化."""
        baseline = [_report("xuanhuan", 1, [("ai_flavor_index", 60.0, "0-100")])]
        current = [_report("xuanhuan", 1, [("ai_flavor_index", 40.0, "0-100")])]
        assert script.detect_regressions(current, baseline) == []

    def test_no_matching_baseline_chapter(self, script) -> None:
        baseline = [_report("xuanhuan", 1, [("narrative_flow", 4.0, "1-5")])]
        current = [_report("xuanhuan", 2, [("narrative_flow", 2.0, "1-5")])]
        assert script.detect_regressions(current, baseline) == []


# ---------------------------------------------------------------------------
# exit code when regression
# ---------------------------------------------------------------------------


class TestExitCodeWithRegression:
    def test_regression_returns_1(self, script, tmp_path: Path) -> None:
        # 预置 baseline: workspace/quality_baselines/phase4/xuanhuan/quality_report.json
        base_root = tmp_path / "workspace" / "quality_baselines" / "phase4" / "xuanhuan"
        base_root.mkdir(parents=True)
        baseline_report = ChapterQualityReport(
            chapter_number=1,
            genre="xuanhuan",
            scores=[DimensionScore(key="narrative_flow", score=4.2, scale="1-5")],
        )
        (base_root / "quality_report.json").write_text(
            json.dumps(baseline_report.to_dict(), ensure_ascii=False),
            encoding="utf-8",
        )
        # 准备 input
        input_dir = tmp_path / "inputs"
        ch_dir = input_dir / "xuanhuan" / "chapters"
        ch_dir.mkdir(parents=True)
        (ch_dir / "chapter_001.txt").write_text("章节正文", encoding="utf-8")

        eval_mock = MagicMock(return_value=ChapterQualityReport(
            chapter_number=1,
            genre="xuanhuan",
            scores=[DimensionScore(key="narrative_flow", score=2.5, scale="1-5")],
        ))

        # 切到 tmp_path 作为 cwd 让 workspace/quality_baselines/phase4 能找到
        with patch("quality_regression.Path", wraps=Path) as _mock_path:
            # 切换 cwd
            import os as _os
            prev = _os.getcwd()
            _os.chdir(tmp_path)
            try:
                exit_code = script.main(
                    argv=[
                        "--eval-only",
                        "--input-dir", str(input_dir),
                        "--genres", "xuanhuan",
                        "--chapters", "1",
                        "--compare", "phase4",
                        "--output-dir", str(tmp_path / "reports"),
                    ],
                    generate_fn=lambda *a, **kw: None,
                    evaluate_fn=eval_mock,
                    ab_fn=lambda *a, **kw: ABComparisonResult(
                        genre="xuanhuan",
                        chapter_number=1,
                        commit_a="base",
                        commit_b="cur",
                        winner="b",
                        judge_reasoning="ok",
                    ),
                )
            finally:
                _os.chdir(prev)

        assert exit_code == 1
        # markdown 报告已写
        md_files = list((tmp_path / "reports" / "summary").glob("*.md"))
        assert len(md_files) == 1
        md_text = md_files[0].read_text(encoding="utf-8")
        assert "Quality Regression Report" in md_text
        assert "REGRESSION" in md_text or "退化" in md_text


# ---------------------------------------------------------------------------
# generate_markdown_report
# ---------------------------------------------------------------------------


class TestMarkdown:
    def test_includes_commit_and_genres(self, script) -> None:
        reports = [
            _report("xuanhuan", 1, [
                ("narrative_flow", 4.0, "1-5"),
                ("plot_advancement", 3.5, "1-5"),
                ("foreshadow_payoff", 75.0, "percent"),
                ("ai_flavor_index", 42.0, "0-100"),
            ]),
        ]
        md = script.generate_markdown_report(
            reports=reports,
            regressions=[],
            ab_results=[],
            baseline_name="phase4",
            commit_hash="deadbeef",
        )
        assert "deadbeef" in md
        assert "phase4" in md
        assert "xuanhuan" in md
        # 四种维度都出现
        assert "4.0" in md
        assert "3.5" in md
        assert "75" in md
        assert "42" in md

    def test_ab_section_rendered(self, script) -> None:
        ab = ABComparisonResult(
            genre="xuanhuan",
            chapter_number=1,
            commit_a="a",
            commit_b="b",
            winner="b",
            judge_reasoning="版本 B 更好",
        )
        md = script.generate_markdown_report([], [], [ab], "", "")
        assert "A/B 对比" in md
        assert "版本 B 更好" in md
        assert "xuanhuan" in md

    def test_no_regressions_no_warning_section(self, script) -> None:
        md = script.generate_markdown_report([], [], [], "", "")
        # 没有 regression 时不出现 "⚠ 退化维度" 章节标题
        assert "⚠ 退化维度" not in md
        # 元信息行 "退化维度数" 仍存在 (值为 0)
        assert "退化维度数: 0" in md


# ---------------------------------------------------------------------------
# render_rich_table
# ---------------------------------------------------------------------------


class TestRichTable:
    def test_renders_rows_with_scores(self, script, capsys) -> None:
        reports = [
            _report("xuanhuan", 1, [
                ("narrative_flow", 3.5, "1-5"),
                ("foreshadow_payoff", 78.0, "percent"),
            ]),
            _report("wuxia", 1, [
                ("narrative_flow", 4.0, "1-5"),
                ("ai_flavor_index", 35.0, "0-100"),
            ]),
        ]
        text = script.render_rich_table(reports, baseline_index=None)
        assert "xuanhuan" in text
        assert "wuxia" in text
        assert "3.5" in text
        assert "4.0" in text

    def test_baseline_delta_display(self, script) -> None:
        reports = [_report("xuanhuan", 1, [("narrative_flow", 3.5, "1-5")])]
        baseline_index = {("xuanhuan", 1): {"narrative_flow": 3.0}}
        text = script.render_rich_table(reports, baseline_index)
        assert "+0.5" in text or "(=)" in text
