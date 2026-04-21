"""跨体裁质量回归脚本 — Phase 5 E3 交付.

对应设计文档: ``specs/architecture-rework-2026/PHASE5.md`` 附录 B。

职责
----
1. 对每个配置的体裁 run ``create_novel`` + ``generate_chapters(1..N)``；
2. 对每章跑 7 个维度质量评估 (D1/D5 单 LLM call + D2+D6+D7 联合 LLM call
   + D3/D4 纯规则)；
3. 可选 ``--compare`` 与 baseline 做 A/B 对比；
4. 终端 Rich Table + markdown 报告；
5. 检测回归 (soft alert) —— 退出码 1 不阻断。

用法示例
----------
全量回归 (5 体裁 x 3 章)::

    python scripts/quality_regression.py

Dry run (不调真 LLM, 只打印计划)::

    python scripts/quality_regression.py --dry-run

指定体裁::

    python scripts/quality_regression.py --genres xuanhuan,suspense

只评估已有章节::

    python scripts/quality_regression.py --eval-only \
        --input-dir workspace/quality_baselines/phase4

"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Callable

# Make project root importable when invoked directly
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Manually load .env (不依赖 python-dotenv，与 verify_novel_fixes.py 一致)
_env_path = _ROOT / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            _k = _k.strip()
            _v = _v.strip().strip("'\"")
            if _k and _k not in os.environ:
                os.environ[_k] = _v

log = logging.getLogger("quality_regression")


# ---------------------------------------------------------------------------
# 体裁配置 (PHASE5.md 4.1)
# ---------------------------------------------------------------------------


@dataclass
class GenreConfig:
    key: str
    genre: str
    theme: str
    target_words: int = 10000


GENRES: dict[str, GenreConfig] = {
    "xuanhuan": GenreConfig(
        key="xuanhuan",
        genre="玄幻",
        theme="少年觉醒血脉在宗门逆境成长",
        target_words=10000,
    ),
    "suspense": GenreConfig(
        key="suspense",
        genre="悬疑",
        theme="深夜来电揭开小镇连环失踪案",
        target_words=8000,
    ),
    "romance": GenreConfig(
        key="romance",
        genre="现代言情",
        theme="青梅竹马重逢后的误会与和解",
        target_words=8000,
    ),
    "scifi": GenreConfig(
        key="scifi",
        genre="科幻",
        theme="太空殖民船上的 AI 觉醒事件",
        target_words=10000,
    ),
    "wuxia": GenreConfig(
        key="wuxia",
        genre="武侠",
        theme="落魄剑客在江湖寻找灭门真相",
        target_words=10000,
    ),
}


# ---------------------------------------------------------------------------
# Regression 阈值 (PHASE5.md 4.5)
# ---------------------------------------------------------------------------


_REGRESSION_THRESHOLD_1_5 = 1.0        # 1-5 scale 下降 >= 1.0 即 regression
_REGRESSION_THRESHOLD_PERCENT = 15.0   # percent / 0-100 scale 下降 >= 15 pp


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="跨体裁质量回归脚本 (Phase 5 E3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--genres",
        default=",".join(GENRES.keys()),
        help="逗号分隔的体裁 key 列表 (默认全部 5 个)",
    )
    parser.add_argument("--chapters", type=int, default=3, help="每体裁生成章节数")
    parser.add_argument(
        "--compare",
        default="",
        help="基线名 (对应 workspace/quality_baselines/<name> 目录)",
    )
    parser.add_argument(
        "--judge-model",
        default="",
        help="覆盖 judge 模型 (异源自动选择的结果)",
    )
    parser.add_argument(
        "--eval-only",
        action="store_true",
        help="不生成,只评估 --input-dir 下已有章节",
    )
    parser.add_argument(
        "--input-dir",
        default="",
        help="eval-only 时从哪里读章节 (<input-dir>/<genre>/chapter_*.txt)",
    )
    parser.add_argument(
        "--workspace",
        default="workspace_quality",
        help="生成 workspace (默认 workspace_quality)",
    )
    parser.add_argument(
        "--output-dir",
        default="workspace/quality_reports",
        help="输出根目录",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="每章 judge 重复次数 (取中位数, 默认 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="不真机跑,只打印执行计划",
    )
    return parser.parse_args(argv)


def resolve_genres(genres_arg: str) -> list[GenreConfig]:
    """``xuanhuan,suspense`` → [GenreConfig, ...]"""
    keys = [k.strip() for k in (genres_arg or "").split(",") if k.strip()]
    resolved: list[GenreConfig] = []
    for k in keys:
        cfg = GENRES.get(k)
        if cfg is None:
            raise SystemExit(f"未知体裁 key: {k} (可选: {sorted(GENRES.keys())})")
        resolved.append(cfg)
    return resolved


def get_current_commit() -> str:
    """返回 HEAD commit 的短 hash；失败返回空字符串。"""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            cwd=str(_ROOT),
        )
        return out.decode("utf-8").strip()
    except (subprocess.CalledProcessError, OSError, FileNotFoundError):
        return ""


def auto_select_judge_from_env(override_model: str = "") -> "Any":
    """根据环境变量(writer provider) + 可选 override 决定 judge 配置."""
    from src.novel.quality.judge import JudgeConfig, auto_select_judge

    # 推断 writer provider（遵循 llm_client._detect_provider 的优先级）
    writer_provider = "gemini"
    if os.environ.get("DEEPSEEK_API_KEY"):
        writer_provider = "deepseek"
    elif os.environ.get("GEMINI_API_KEY"):
        writer_provider = "gemini"
    elif os.environ.get("OPENAI_API_KEY"):
        writer_provider = "openai"

    config: JudgeConfig = auto_select_judge(writer_provider)
    if override_model:
        config.model = override_model
    if config.same_source:
        log.warning(
            "=" * 68
            + "\n  [JUDGE 同源警告] judge 与 writer 使用同一 provider (%s)。\n"
            "  缺少异源 API key（如 GEMINI_API_KEY），质量分数会有同模型 bias，\n"
            "  LLM 维度分数仅供参考，切勿作为 A/B 对比依据。\n"
            "  建议：设置其他 provider 的 API key 或通过 --judge-model 指定。\n"
            + "=" * 68,
            config.provider,
        )
    return config


# ---------------------------------------------------------------------------
# 评估单章
# ---------------------------------------------------------------------------


@dataclass
class ChapterContext:
    genre_cfg: GenreConfig
    chapter_number: int
    text: str
    previous_tail: str = ""
    chapter_goal: str = ""
    character_names: str = ""
    # LedgerStore / StyleProfile 等可选上下文
    ledger: Any | None = None
    style_profile: Any | None = None


def _aggregate_repeat(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(median(values))


def evaluate_chapter(
    ctx: ChapterContext,
    judge_config: Any,
    commit_hash: str,
    repeat: int = 1,
    chapters_text: dict[int, str] | None = None,
) -> "Any":
    """对单章跑 7 维度评估, 返回 ChapterQualityReport.

    Args:
        ctx: 章节上下文，含 ``ledger`` / ``style_profile`` 用于 D3/D4 规则评估。
            C1 fix 前这两个字段从未被 main 填入，导致 D3/D4 永不执行。
        judge_config: judge LLM 配置。
        commit_hash: 当前 git HEAD 短 hash。
        repeat: judge LLM 重复次数（默认 1，用 median 聚合）。
        chapters_text: 累计已评章节正文 ``{chapter_number: text}``，D3 伏笔
            兑现率搜索需要。C1 fix 前未传该参数导致 evaluate_foreshadow_payoff
            漏 required kwarg 崩溃。

    Returns:
        :class:`ChapterQualityReport`。
    """
    from src.novel.quality.dimensions import (
        evaluate_chapter_hook_rules,
        evaluate_dialogue_quality_rules,
    )
    from src.novel.quality.judge import (
        evaluate_multi_dimension_llm,
        evaluate_narrative_flow_llm,
        evaluate_plot_advancement_llm,
    )
    from src.novel.quality.report import ChapterQualityReport, DimensionScore

    llm_context = {
        "genre": ctx.genre_cfg.genre,
        "chapter_goal": ctx.chapter_goal,
        "previous_tail": ctx.previous_tail,
        "character_names": ctx.character_names,
    }

    # chapters_text 至少包含本章自己（首章也不例外）
    chapters_text_local: dict[int, str] = dict(chapters_text or {})
    if ctx.text:
        chapters_text_local.setdefault(ctx.chapter_number, ctx.text)

    scores: list[DimensionScore] = []
    token_usage = 0

    # D1 narrative_flow (1-5) —— repeat 取中位数
    d1_values: list[DimensionScore] = [
        evaluate_narrative_flow_llm(ctx.text, llm_context, judge_config)
        for _ in range(max(1, repeat))
    ]
    # H5 fix: 从 DimensionScore.details["_own_token_usage"] 读 D1 成本
    token_usage += sum(
        int(d.details.get("_own_token_usage", 0) or 0) for d in d1_values
    )
    d1_final = DimensionScore(
        key="narrative_flow",
        score=_aggregate_repeat([d.score for d in d1_values]),
        scale="1-5",
        method="llm_judge",
        details={
            "judge_reasoning": d1_values[-1].details.get("judge_reasoning", ""),
            "samples": [d.score for d in d1_values],
            "judge_model": judge_config.model,
        },
    )
    scores.append(d1_final)

    # D5 plot_advancement
    d5_values = [
        evaluate_plot_advancement_llm(ctx.text, llm_context, judge_config)
        for _ in range(max(1, repeat))
    ]
    token_usage += sum(
        int(d.details.get("_own_token_usage", 0) or 0) for d in d5_values
    )
    d5_final = DimensionScore(
        key="plot_advancement",
        score=_aggregate_repeat([d.score for d in d5_values]),
        scale="1-5",
        method="llm_judge",
        details={
            "judge_reasoning": d5_values[-1].details.get("judge_reasoning", ""),
            "samples": [d.score for d in d5_values],
            "judge_model": judge_config.model,
        },
    )
    scores.append(d5_final)

    # D2+D6+D7 joint
    multi_samples: list[list[DimensionScore]] = [
        evaluate_multi_dimension_llm(ctx.text, llm_context, judge_config)
        for _ in range(max(1, repeat))
    ]
    # H5 fix: multi 合并 call 只产一个 combined token usage（在每次采样的第一条 details 里）
    token_usage += sum(
        int(sample[0].details.get("_combined_token_usage", 0) or 0)
        for sample in multi_samples
    )

    # C2 fix: D6/D7 规则层与 LLM 合并，method="mixed"
    # 先跑规则层（输入与 LLM 共享的 ctx.text / ctx.previous_tail）
    d6_rules = evaluate_dialogue_quality_rules(ctx.text) if ctx.text else None
    d7_rules = (
        evaluate_chapter_hook_rules(ctx.text, ctx.previous_tail)
        if ctx.text is not None
        else None
    )

    if multi_samples:
        keys = [s.key for s in multi_samples[0]]
        for k_idx, key in enumerate(keys):
            samples = [sample[k_idx].score for sample in multi_samples]
            last = multi_samples[-1][k_idx]
            details: dict[str, Any] = {
                "judge_reasoning": last.details.get("judge_reasoning", ""),
                "samples": samples,
                "judge_model": judge_config.model,
            }
            method = "llm_judge"
            # C2: D6 合并 dialogue rules
            if key == "dialogue_quality" and d6_rules is not None:
                details.update(
                    {
                        "dialogue_ratio": d6_rules.get("dialogue_ratio", 0.0),
                        "max_single_line": d6_rules.get("max_single_line", 0),
                        "line_count": d6_rules.get("line_count", 0),
                        "warnings": list(d6_rules.get("warnings", [])),
                    }
                )
                method = "mixed"
            # C2: D7 合并 chapter hook rules
            elif key == "chapter_hook" and d7_rules is not None:
                details.update(
                    {
                        "opening_match_rate": d7_rules.get(
                            "opening_match_rate", 0.0
                        ),
                        "ending_has_hook": d7_rules.get("ending_has_hook", False),
                        "ending_indicator": d7_rules.get("ending_indicator", ""),
                        "warnings": list(d7_rules.get("warnings", [])),
                    }
                )
                method = "mixed"
            scores.append(
                DimensionScore(
                    key=key,
                    score=_aggregate_repeat(samples),
                    scale="1-5",
                    method=method,
                    details=details,
                )
            )

    # D3/D4 纯规则
    # C1 fix: evaluate_foreshadow_payoff 需要 chapters_text kwarg；
    # ledger/style_profile 缺失 → 产出 score=None + status 字段，不崩
    try:
        from src.novel.quality import evaluate_ai_flavor, evaluate_foreshadow_payoff

        if ctx.ledger is not None:
            scores.append(
                evaluate_foreshadow_payoff(
                    ledger=ctx.ledger,
                    chapter_number=ctx.chapter_number,
                    chapters_text=chapters_text_local,
                )
            )
        else:
            log.info(
                "ctx.ledger 为 None, 跳过 D3 伏笔兑现率 (genre=%s ch=%d)",
                ctx.genre_cfg.key,
                ctx.chapter_number,
            )
            scores.append(
                DimensionScore(
                    key="foreshadow_payoff",
                    score=None,
                    scale="percent",
                    method="rule",
                    details={
                        "status": "ledger_missing",
                        "warnings": ["ledger_missing: LedgerStore 未加载"],
                    },
                )
            )

        # D4 总是跑（StyleProfile 缺失时 overuse 分量为 0，仍然有 cliche/repetition）
        d4 = evaluate_ai_flavor(
            text=ctx.text,
            style_profile=ctx.style_profile,
            genre=ctx.genre_cfg.genre,
        )
        if ctx.style_profile is None:
            # 标记 profile 缺失情形，details 里追加标识便于报告层渲染
            d4.details.setdefault("profile_missing", True)
            d4.details.setdefault(
                "warnings", []
            ).append("profile_missing: StyleProfile 未加载 (overuse 分量=0)")
        scores.append(d4)
    except ImportError:
        log.warning("规则维度 (D3/D4) 尚未由 E2 提供, 跳过")
    except Exception as exc:  # pragma: no cover - 规则计算软失败不阻断 LLM 评估
        log.warning("规则维度计算失败: %s", exc)

    return ChapterQualityReport(
        chapter_number=ctx.chapter_number,
        genre=ctx.genre_cfg.key,
        commit_hash=commit_hash,
        scores=scores,
        generated_at=_dt.datetime.now(tz=_dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        judge_model=judge_config.model,
        judge_token_usage=token_usage,
    )


# ---------------------------------------------------------------------------
# 生成 / 加载章节
# ---------------------------------------------------------------------------


def _load_chapter_text(project_dir: Path, chapter_number: int) -> str:
    """尝试从 ``<project_dir>/chapters/chapter_<n>.txt`` 或
    ``<project_dir>/chapter_<n>.txt`` 读章节正文。"""
    candidates = [
        project_dir / "chapters" / f"chapter_{chapter_number:03d}.txt",
        project_dir / f"chapter_{chapter_number:03d}.txt",
    ]
    for c in candidates:
        if c.exists():
            return c.read_text(encoding="utf-8")
    return ""


def _previous_tail(text: str, n: int = 500) -> str:
    if not text:
        return ""
    return text[-n:]


def generate_for_genre(
    genre_cfg: GenreConfig,
    chapters: int,
    workspace: str,
) -> tuple[Path, list[str]]:
    """真机跑 create_novel + generate_chapters(1..N), 返回 (project_dir, chapter_texts)."""
    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline(workspace=workspace)
    create_result = pipe.create_novel(
        genre=genre_cfg.genre,
        theme=genre_cfg.theme,
        target_words=genre_cfg.target_words,
    )
    project_path = create_result.get("project_path") or ""
    pipe.generate_chapters(
        project_path=project_path,
        start_chapter=1,
        end_chapter=chapters,
        silent=True,
    )
    project_dir = Path(project_path)
    texts = [_load_chapter_text(project_dir, i) for i in range(1, chapters + 1)]
    return project_dir, texts


# ---------------------------------------------------------------------------
# Regression 检测
# ---------------------------------------------------------------------------


@dataclass
class Regression:
    genre: str
    chapter_number: int
    dimension: str
    baseline_score: float
    current_score: float
    delta: float
    scale: str

    def as_line(self) -> str:
        return (
            f"[REGRESSION] genre={self.genre} ch={self.chapter_number} "
            f"dim={self.dimension} baseline={self.baseline_score:.2f} "
            f"current={self.current_score:.2f} delta={self.delta:+.2f} ({self.scale})"
        )


def detect_regressions(
    reports: list[Any],
    baseline_reports: list[Any] | None,
) -> list[Regression]:
    """对比当前 reports 与 baseline_reports, 返回退化记录.

    H1/H2 fix: ``score is None``（无数据维度，如无到期伏笔、空文本）既不
    参与 baseline 索引，也不参与 regression 对比；遇到 None 产 info 日志
    并跳过。
    """
    if not baseline_reports:
        return []

    # 构造 baseline 索引 (genre, chapter) → {dim: (score, scale)}；None 跳过
    baseline_index: dict[tuple[str, int], dict[str, tuple[float, str]]] = {}
    for br in baseline_reports:
        key = (br.genre, br.chapter_number)
        baseline_index[key] = {
            s.key: (s.score, s.scale) for s in br.scores if s.score is not None
        }

    regressions: list[Regression] = []
    for rep in reports:
        base = baseline_index.get((rep.genre, rep.chapter_number))
        if not base:
            continue
        for s in rep.scores:
            if s.score is None:
                log.info(
                    "regression: 跳过 %s.%s (current score=None, status=%s)",
                    rep.genre,
                    s.key,
                    s.details.get("status") if isinstance(s.details, dict) else "",
                )
                continue
            base_entry = base.get(s.key)
            if not base_entry:
                continue
            base_score, base_scale = base_entry
            delta = s.score - base_score
            threshold = (
                _REGRESSION_THRESHOLD_1_5
                if s.scale == "1-5"
                else _REGRESSION_THRESHOLD_PERCENT
            )
            # 注意: AI 味指数 (0-100) 是越低越好 —— 上升 threshold 才算退化
            inverted = s.key == "ai_flavor_index"
            regressed = (delta <= -threshold) if not inverted else (delta >= threshold)
            if regressed:
                regressions.append(
                    Regression(
                        genre=rep.genre,
                        chapter_number=rep.chapter_number,
                        dimension=s.key,
                        baseline_score=base_score,
                        current_score=s.score,
                        delta=delta,
                        scale=s.scale,
                    )
                )
    return regressions


# ---------------------------------------------------------------------------
# 报告输出 (Rich Table + Markdown)
# ---------------------------------------------------------------------------


def _try_rich() -> Any | None:
    try:
        from rich.console import Console
        from rich.table import Table

        return (Console, Table)
    except ImportError:  # pragma: no cover - rich 在项目依赖中, 缺失走降级
        return None


def render_rich_table(
    reports: list[Any],
    baseline_index: dict[tuple[str, int], dict[str, float]] | None,
) -> str:
    """渲染 rich table。无 rich 时退化为纯文本。返回文本表示 (供测试捕获)。"""
    rich_mod = _try_rich()
    headers = [
        "Genre",
        "Ch",
        "Flow(1-5)",
        "Plot(1-5)",
        "Char(1-5)",
        "Dial(1-5)",
        "Hook(1-5)",
        "Payoff%",
        "AI(0-100)",
    ]
    rows: list[list[str]] = []
    for rep in reports:
        s_by_key = {s.key: s for s in rep.scores}

        def cell(key: str, scale_hint: str) -> str:
            s = s_by_key.get(key)
            if s is None:
                return "-"
            # H1/H2 fix: score=None 时显示 "-" (不是 0 也不是 100)
            if s.score is None:
                return "-"
            base = (baseline_index or {}).get((rep.genre, rep.chapter_number), {}).get(key)
            suffix = ""
            if base is not None:
                delta = s.score - base
                if scale_hint == "1-5":
                    if abs(delta) < 0.05:
                        suffix = " (=)"
                    else:
                        suffix = f" ({delta:+.1f})"
                else:
                    if abs(delta) < 0.5:
                        suffix = " (=)"
                    else:
                        suffix = f" ({delta:+.0f})"
            if scale_hint == "1-5":
                return f"{s.score:.1f}{suffix}"
            return f"{s.score:.0f}{suffix}"

        rows.append([
            rep.genre,
            str(rep.chapter_number),
            cell("narrative_flow", "1-5"),
            cell("plot_advancement", "1-5"),
            cell("character_consistency", "1-5"),
            cell("dialogue_quality", "1-5"),
            cell("chapter_hook", "1-5"),
            cell("foreshadow_payoff", "percent"),
            cell("ai_flavor_index", "0-100"),
        ])

    if rich_mod is None:
        # 纯文本降级
        lines = [" | ".join(headers)]
        lines.append("-" * (sum(len(h) for h in headers) + 3 * len(headers)))
        for row in rows:
            lines.append(" | ".join(row))
        text = "\n".join(lines)
        print(text)
        return text

    Console, Table = rich_mod
    console = Console()
    table = Table(title="Quality Regression Report", show_header=True, header_style="bold")
    for h in headers:
        table.add_column(h, justify="center")
    for row in rows:
        table.add_row(*row)
    console.print(table)
    # 近似文本表示供测试 / markdown
    return "\n".join(" | ".join(row) for row in [headers, *rows])


def generate_markdown_report(
    reports: list[Any],
    regressions: list[Regression],
    ab_results: list[Any],
    baseline_name: str,
    commit_hash: str,
) -> str:
    """组装 markdown 报告文本。"""
    # L3 fix: datetime.utcnow() 已 deprecated，用 timezone-aware now(tz=utc)
    now = (
        _dt.datetime.now(tz=_dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    lines: list[str] = []
    lines.append(f"# Quality Regression Report\n")
    lines.append(f"- 生成时间: {now}")
    lines.append(f"- commit: `{commit_hash or 'unknown'}`")
    lines.append(f"- baseline: `{baseline_name or '(none)'}`")
    lines.append(f"- 章节总数: {len(reports)}")
    lines.append(f"- 退化维度数: {len(regressions)}")
    lines.append("")

    # 按 genre 聚合
    lines.append("## 各体裁维度分数\n")
    lines.append("| Genre | Ch | Flow | Plot | Char | Dial | Hook | Payoff% | AI |")
    lines.append("|-------|----|------|------|------|------|------|---------|----|")
    for rep in reports:
        s_by_key = {s.key: s for s in rep.scores}

        def num(key: str, fmt: str = ".1f") -> str:
            s = s_by_key.get(key)
            # H1/H2 fix: score=None 显示 N/A（语义上与"维度缺失"区分）
            if s is None:
                return "-"
            if s.score is None:
                return "N/A"
            return f"{s.score:{fmt}}"

        lines.append(
            f"| {rep.genre} | {rep.chapter_number} | "
            f"{num('narrative_flow')} | {num('plot_advancement')} | "
            f"{num('character_consistency')} | {num('dialogue_quality')} | "
            f"{num('chapter_hook')} | {num('foreshadow_payoff', '.0f')} | "
            f"{num('ai_flavor_index', '.0f')} |"
        )
    lines.append("")

    if regressions:
        lines.append("## ⚠ 退化维度\n")
        for reg in regressions:
            lines.append(f"- {reg.as_line()}")
        lines.append("")

    if ab_results:
        lines.append("## A/B 对比结果\n")
        lines.append("| Genre | Ch | Winner | Reasoning |")
        lines.append("|-------|----|--------|-----------|")
        for ab in ab_results:
            reasoning = (ab.judge_reasoning or "").replace("|", " ").replace("\n", " ")
            lines.append(
                f"| {ab.genre} | {ab.chapter_number} | {ab.winner} | "
                f"{reasoning[:120]} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("_由 scripts/quality_regression.py 生成._")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def print_plan(args: argparse.Namespace, genres: list[GenreConfig]) -> None:
    print("=" * 68)
    print("Quality Regression 计划 (dry-run)")
    print("=" * 68)
    print(f"  workspace      : {args.workspace}")
    print(f"  output-dir     : {args.output_dir}")
    print(f"  eval-only      : {args.eval_only}")
    print(f"  input-dir      : {args.input_dir or '(n/a)'}")
    print(f"  compare        : {args.compare or '(不做 A/B 对比)'}")
    print(f"  judge-model    : {args.judge_model or '(异源自动选择)'}")
    print(f"  chapters/genre : {args.chapters}")
    print(f"  repeat         : {args.repeat}")
    print(f"  genres ({len(genres)}):")
    for g in genres:
        print(
            f"    - {g.key:10s} | {g.genre:6s} | target={g.target_words:>6d} | "
            f"theme={g.theme}"
        )
    if not args.eval_only:
        total_llm_calls = len(genres) * args.chapters * 3 * args.repeat
        print(f"  预估 judge LLM 调用: {total_llm_calls} (每章 3 次 * {args.repeat})")
    print("=" * 68)


def _try_load_ledger(project_dir: Path) -> Any | None:
    """C1 fix 辅助：尝试从 project_dir 加载 LedgerStore；失败返回 None。

    典型 project_dir 结构 (NovelPipeline 产出)::

        workspace_quality/novels/novel_xxx/
        ├── novel.json
        ├── .cache/style_profile.json
        └── chapters/chapter_001.txt ...

    NovelMemory 需要 ``novel_id`` + ``workspace_dir``，由 project_dir 推断：
    ``novel_id = project_dir.name`` / ``workspace_dir = project_dir.parent.parent``.
    """
    try:
        from src.novel.services.ledger_store import LedgerStore
        from src.novel.storage.file_manager import FileManager
        from src.novel.storage.novel_memory import NovelMemory

        if not project_dir.exists():
            return None
        novel_id = project_dir.name
        # novels 目录是 project_dir.parent，workspace 是 parent.parent
        workspace_dir = str(project_dir.parent.parent)
        fm = FileManager(workspace_dir)
        novel_data = fm.load_novel(novel_id) if hasattr(fm, "load_novel") else None
        try:
            memory = NovelMemory(novel_id, workspace_dir)
        except Exception:  # noqa: BLE001 - memory 初始化失败也允许降级
            memory = None
        ledger = LedgerStore(
            project_path=str(project_dir),
            db=getattr(memory, "structured_db", None) if memory else None,
            kg=getattr(memory, "knowledge_graph", None) if memory else None,
            vector_store=getattr(memory, "vector_store", None) if memory else None,
            novel_data=novel_data or {},
        )
        return ledger
    except Exception as exc:  # noqa: BLE001
        log.warning("LedgerStore 加载失败 (project=%s): %s", project_dir, exc)
        return None


def _try_load_style_profile(project_dir: Path) -> Any | None:
    """C1 fix 辅助：从 project_dir/.cache/style_profile.json 加载 StyleProfile。

    优先读取已缓存的 profile JSON；失败返回 None。
    """
    try:
        from src.novel.models.style_profile import StyleProfile
        from src.novel.storage.file_manager import FileManager

        if not project_dir.exists():
            return None
        novel_id = project_dir.name
        workspace_dir = str(project_dir.parent.parent)
        fm = FileManager(workspace_dir)
        data = fm.load_style_profile(novel_id)
        if not data:
            return None
        return StyleProfile(**data)
    except Exception as exc:  # noqa: BLE001
        log.warning("StyleProfile 加载失败 (project=%s): %s", project_dir, exc)
        return None


def _load_report_json(path: Path) -> Any | None:
    """从 JSON 读 ChapterQualityReport (尝试重构 dataclass)."""
    from src.novel.quality.report import ChapterQualityReport, DimensionScore

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    scores = [
        DimensionScore(
            key=s.get("key", ""),
            score=float(s.get("score", 0.0) or 0.0),
            scale=s.get("scale", "1-5"),
            method=s.get("method", "llm_judge"),
            details=dict(s.get("details") or {}),
        )
        for s in (data.get("scores") or [])
    ]
    return ChapterQualityReport(
        chapter_number=int(data.get("chapter_number", 0)),
        genre=data.get("genre", ""),
        commit_hash=data.get("commit_hash", ""),
        scores=scores,
        overall_summary=data.get("overall_summary", ""),
        generated_at=data.get("generated_at", ""),
        judge_model=data.get("judge_model", ""),
        judge_token_usage=int(data.get("judge_token_usage", 0) or 0),
    )


def _load_baseline_reports(baseline_name: str) -> list[Any]:
    """从 ``workspace/quality_baselines/<name>/<genre>/quality_report.json`` 读."""
    if not baseline_name:
        return []
    root = Path("workspace/quality_baselines") / baseline_name
    if not root.exists():
        return []
    reports: list[Any] = []
    for genre_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        report_path = genre_dir / "quality_report.json"
        if not report_path.exists():
            continue
        rep = _load_report_json(report_path)
        if rep is not None:
            reports.append(rep)
    return reports


def main(
    argv: list[str] | None = None,
    *,
    generate_fn: Callable | None = None,
    evaluate_fn: Callable | None = None,
    ab_fn: Callable | None = None,
) -> int:
    """主入口. ``generate_fn``/``evaluate_fn``/``ab_fn`` 用于测试注入.

    Returns:
        退出码: 0 = 无退化, 1 = 检测到退化 (soft alert, 非 hard block).
    """
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    genres = resolve_genres(args.genres)

    if args.dry_run:
        print_plan(args, genres)
        return 0

    commit_hash = get_current_commit()
    judge_config = auto_select_judge_from_env(args.judge_model)

    output_root = Path(args.output_dir)
    single_dir = output_root / "single"
    ab_dir = output_root / "ab_compare"
    summary_dir = output_root / "summary"
    for d in (single_dir, ab_dir, summary_dir):
        d.mkdir(parents=True, exist_ok=True)

    # A/B baseline 章节正文加载
    ab_baseline_texts: dict[str, dict[int, str]] = {}
    if args.compare:
        from src.novel.quality.ab_compare import load_baseline

        base_dir = Path("workspace/quality_baselines") / args.compare
        for g in genres:
            ab_baseline_texts[g.key] = load_baseline(str(base_dir), g.key)

    baseline_reports = _load_baseline_reports(args.compare)

    # 准备章节文本
    all_reports: list[Any] = []
    ab_results: list[Any] = []

    _generate = generate_fn or generate_for_genre
    _evaluate = evaluate_fn or evaluate_chapter
    if ab_fn is None:
        from src.novel.quality.ab_compare import pairwise_judge as _ab_default
        _ab_fn = _ab_default
    else:
        _ab_fn = ab_fn

    start_ts = time.time()

    for g in genres:
        log.info("=== genre=%s ===", g.key)
        if args.eval_only:
            input_root = Path(args.input_dir) if args.input_dir else Path(".")
            project_dir = input_root / g.key
            chapter_texts = [
                _load_chapter_text(project_dir, i) for i in range(1, args.chapters + 1)
            ]
        else:
            try:
                project_dir, chapter_texts = _generate(
                    g, args.chapters, args.workspace
                )
            except Exception as exc:
                log.error("genre=%s 生成失败: %s", g.key, exc)
                continue

        # C1 fix: 加载 LedgerStore + StyleProfile 到 ctx（失败 warn 继续，不崩）
        ledger_for_genre = _try_load_ledger(project_dir)
        style_profile_for_genre = _try_load_style_profile(project_dir)
        if ledger_for_genre is None:
            log.warning(
                "genre=%s 未能加载 LedgerStore → D3 伏笔兑现率将返回 None", g.key
            )
        if style_profile_for_genre is None:
            log.warning(
                "genre=%s 未能加载 StyleProfile → D4 AI 味 overuse 分量为 0 (cliche/repetition 仍生效)",
                g.key,
            )

        prev_tail = ""
        # C1 fix: 累计本 genre 已评章节正文，供 D3 伏笔兑现率搜索
        genre_chapters_text: dict[int, str] = {}
        for ch_idx, text in enumerate(chapter_texts, start=1):
            if not text:
                log.warning("genre=%s ch=%d 正文为空, 跳过评估", g.key, ch_idx)
                continue
            genre_chapters_text[ch_idx] = text
            ctx = ChapterContext(
                genre_cfg=g,
                chapter_number=ch_idx,
                text=text,
                previous_tail=prev_tail,
                ledger=ledger_for_genre,
                style_profile=style_profile_for_genre,
            )
            try:
                rep = _evaluate(
                    ctx,
                    judge_config,
                    commit_hash,
                    args.repeat,
                    genre_chapters_text,
                )
            except Exception as exc:  # pragma: no cover
                log.error("genre=%s ch=%d 评估失败: %s", g.key, ch_idx, exc)
                continue
            all_reports.append(rep)
            rep.save_json(
                str(
                    single_dir
                    / f"{_dt.date.today().isoformat()}_{g.key}_ch{ch_idx}_{commit_hash or 'na'}.json"
                )
            )
            prev_tail = _previous_tail(text)

            # A/B 对比
            if args.compare:
                baseline_text = ab_baseline_texts.get(g.key, {}).get(ch_idx)
                if baseline_text:
                    ab = _ab_fn(
                        baseline_text,
                        text,
                        g.genre,
                        ch_idx,
                        args.compare,
                        commit_hash or "current",
                        judge_config,
                    )
                    ab_results.append(ab)
                    ab_path = (
                        ab_dir
                        / f"{_dt.date.today().isoformat()}_{g.key}_ch{ch_idx}_{args.compare}_vs_{commit_hash or 'current'}.json"
                    )
                    ab_path.write_text(
                        json.dumps(ab.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

    elapsed = time.time() - start_ts
    log.info("评估完成, 耗时 %.1fs, 总章节 %d", elapsed, len(all_reports))

    # baseline 索引 (用于 rich table delta)
    # H1/H2 fix: score is None 的维度不入索引 (显示 "-"，不算 delta)
    baseline_index: dict[tuple[str, int], dict[str, float]] = {
        (br.genre, br.chapter_number): {
            s.key: s.score for s in br.scores if s.score is not None
        }
        for br in baseline_reports
    }

    render_rich_table(all_reports, baseline_index)
    regressions = detect_regressions(all_reports, baseline_reports)
    for reg in regressions:
        print(reg.as_line())

    md = generate_markdown_report(
        all_reports, regressions, ab_results, args.compare, commit_hash
    )
    md_path = summary_dir / f"{_dt.date.today().isoformat()}_regression_report.md"
    md_path.write_text(md, encoding="utf-8")
    log.info("markdown 报告写入: %s", md_path)

    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
