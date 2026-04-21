"""Phase 3 vs Phase 4 A/B 对比 harness — Phase 5 扩展交付.

本脚本回答一个单一问题：**架构重构 2026 Phase 0-4 是否改善了生成质量？**

背景
----
T7 基线结果显示 gpt-4o-mini 判分偏松（4-5 分集中），Phase 5 唯一能稳定回答
"重构是否改善"的工具是 **A/B pairwise**（见 ``PHASE5.md`` 3.2.3 + 4.3）。

本脚本用 ``git worktree`` 把 **Phase 3 终点 commit**（默认 ``8fcd7be``）checkout
到独立路径，纯只读运行其 ``NovelPipeline.create_novel`` + ``generate_chapters``
生成一组 5 体裁 × 3 章 的章节文本；然后从 **当前 HEAD** 导入 :func:`pairwise_judge`
把 Phase 3 产物与 **Phase 4 产物**（已存在于 ``workspace_quality_baseline/``）
成对比较，汇总 per-dimension winner 分布与判读建议。

为什么用 worktree 而不是 ``git checkout``
---------------------------------------
``git checkout 8fcd7be`` 会污染当前工作目录、影响 IDE、打断并行测试。
``git worktree add`` 把 commit 在 **另一个路径** 下 checkout，源目录不动，
A/B 结束 ``git worktree remove`` 即彻底清理。

先决条件
--------
1. 当前 ``git status`` 必须干净（无 uncommitted），否则脚本拒绝运行。
2. ``.env`` 已配置 LLM API key（Writer + Judge 两条链路）。
3. Phase 4 产物 ``workspace_quality_baseline/novels/`` 已存在（已由 T7 生成）。
4. ``--worktree-path`` 不存在或可被覆盖（默认 ``/tmp/ai_novel_phase3_worktree``）。

运行示例
--------
Dry run (不跑任何 LLM, 只打印计划)::

    python scripts/quality_ab_phase3_vs_phase4.py --dry-run

全量真机 A/B (5 体裁 × 3 章)::

    python scripts/quality_ab_phase3_vs_phase4.py

仅跑一个体裁::

    python scripts/quality_ab_phase3_vs_phase4.py --genres xuanhuan

跳过 Phase 3 生成（复用 ``workspace_quality_phase3/``）::

    python scripts/quality_ab_phase3_vs_phase4.py --skip-generation

指定 Phase 3 commit::

    python scripts/quality_ab_phase3_vs_phase4.py --phase3-commit <hash>

产出
----
``workspace/quality_reports/phase3_vs_phase4/`` 下：

- ``<date>_<genre>_ch<n>_phase3_vs_phase4.json`` — 每章一个
  :class:`ABComparisonResult` 序列化
- ``<date>_ab_summary.json`` — 全局统计（winner 分布 + per-dimension 统计）
- ``<date>_ab_report.md`` — markdown 报告（含 per-genre 表 + 汇总 + 判读建议）

Phase 3 的章节文本产物保留在 ``workspace_quality_phase3/novels/``；下次再跑可用
``--skip-generation`` 复用。

判读
----
- ``winner=b`` 大幅胜出 → Phase 4 架构重构改善了生成质量
- ``winner=a/b/tie`` 接近 → 架构重构未影响质量（预期：Writer 本身未改）
- ``winner=a`` 大幅胜出 → Phase 4 引入 regression，需排查

设计文档：``specs/architecture-rework-2026/PHASE5.md``。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# 路径与环境
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Manually load .env (与 quality_regression.py 一致，不依赖 python-dotenv)
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

log = logging.getLogger("quality_ab_phase3_vs_phase4")


# ---------------------------------------------------------------------------
# 体裁配置 — 复用 quality_regression 的 GenreConfig 以保证一致性
# ---------------------------------------------------------------------------

# 避免循环导入 / 避免对 quality_regression 脚本加载产生副作用：本脚本内嵌副本。
# 与 quality_regression.py GENRES 完全一致，修改时请同步。


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


# Novel.json 的 "genre" 字段（中文）→ 我们的 GenreConfig.key
_NOVEL_GENRE_TO_KEY: dict[str, str] = {
    "玄幻": "xuanhuan",
    "悬疑": "suspense",
    "现代言情": "romance",
    "言情": "romance",
    "科幻": "scifi",
    "武侠": "wuxia",
}


# ---------------------------------------------------------------------------
# 默认参数
# ---------------------------------------------------------------------------

_DEFAULT_PHASE3_COMMIT = "8fcd7be"
_DEFAULT_WORKTREE_PATH = Path("/tmp/ai_novel_phase3_worktree")
_DEFAULT_PHASE3_WORKSPACE = Path("workspace_quality_phase3")
_DEFAULT_PHASE4_WORKSPACE = Path("workspace_quality_baseline")
_DEFAULT_OUTPUT_DIR = Path("workspace/quality_reports/phase3_vs_phase4")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 3 vs Phase 4 A/B 对比 harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--genres",
        default=",".join(GENRES.keys()),
        help="逗号分隔的体裁 key 列表 (默认全部 5 个)",
    )
    parser.add_argument("--chapters", type=int, default=3, help="每体裁 A/B 章节数")
    parser.add_argument(
        "--phase3-commit",
        default=_DEFAULT_PHASE3_COMMIT,
        help=f"Phase 3 基准 commit (默认 {_DEFAULT_PHASE3_COMMIT})",
    )
    parser.add_argument(
        "--phase4-commit",
        default="HEAD",
        help="Phase 4 commit (写入 JSON；默认当前 HEAD 短 hash)",
    )
    parser.add_argument(
        "--phase3-workspace",
        default=str(_DEFAULT_PHASE3_WORKSPACE),
        help=f"Phase 3 产物 workspace (默认 {_DEFAULT_PHASE3_WORKSPACE})",
    )
    parser.add_argument(
        "--phase4-workspace",
        default=str(_DEFAULT_PHASE4_WORKSPACE),
        help=f"Phase 4 产物 workspace (默认 {_DEFAULT_PHASE4_WORKSPACE})",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_DEFAULT_OUTPUT_DIR),
        help=f"报告输出根目录 (默认 {_DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--worktree-path",
        default=str(_DEFAULT_WORKTREE_PATH),
        help=f"Phase 3 worktree checkout 路径 (默认 {_DEFAULT_WORKTREE_PATH})",
    )
    parser.add_argument(
        "--judge-model",
        default="",
        help="覆盖 judge 模型 (异源自动选择的结果)",
    )
    parser.add_argument(
        "--skip-generation",
        action="store_true",
        help="跳过 Phase 3 生成 (复用现有 --phase3-workspace 下产物)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="不真机跑 LLM / git worktree, 只打印计划",
    )
    parser.add_argument(
        "--force-worktree",
        action="store_true",
        help="worktree 路径已存在时强制清理 (否则报错退出)",
    )
    return parser.parse_args(argv)


def resolve_genres(genres_arg: str) -> list[GenreConfig]:
    keys = [k.strip() for k in (genres_arg or "").split(",") if k.strip()]
    resolved: list[GenreConfig] = []
    for k in keys:
        cfg = GENRES.get(k)
        if cfg is None:
            raise SystemExit(f"未知体裁 key: {k} (可选: {sorted(GENRES.keys())})")
        resolved.append(cfg)
    return resolved


# ---------------------------------------------------------------------------
# 前置检查
# ---------------------------------------------------------------------------


def _git_status_clean() -> bool:
    """当前工作目录 git status 是否干净."""
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=str(_ROOT),
            stderr=subprocess.DEVNULL,
        )
        return not out.decode("utf-8").strip()
    except (subprocess.CalledProcessError, OSError, FileNotFoundError):
        return False


def _resolve_commit_short(commit_ref: str) -> str:
    """``HEAD`` / 长 hash → 短 hash；失败返回原值."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", commit_ref],
            cwd=str(_ROOT),
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8").strip() or commit_ref
    except (subprocess.CalledProcessError, OSError, FileNotFoundError):
        return commit_ref


def preflight_checks(args: argparse.Namespace) -> list[str]:
    """前置检查；返回错误列表（空列表表示通过）。

    Dry-run 模式跳过所有破坏性检查，仅用于打印计划。
    """
    errors: list[str] = []
    if args.dry_run:
        return errors
    if not _git_status_clean():
        errors.append(
            "git status 不干净：请先 commit / stash 本地变更再运行。"
            " (worktree 操作本身不污染源目录，但前置干净便于溯源 commit。)"
        )
    if not (_ROOT / ".env").exists():
        errors.append(
            ".env 不存在：脚本需要 LLM API key (至少 Gemini/DeepSeek 之一)。"
        )
    phase4_root = Path(args.phase4_workspace)
    if not phase4_root.exists() or not phase4_root.is_dir():
        errors.append(
            f"Phase 4 workspace 目录不存在: {phase4_root}。"
            " 请先跑 scripts/quality_regression.py 生成 Phase 4 基线产物，或修改"
            " --phase4-workspace。"
        )
    worktree_path = Path(args.worktree_path)
    if not args.skip_generation and worktree_path.exists() and not args.force_worktree:
        errors.append(
            f"worktree 路径 {worktree_path} 已存在；"
            f"加 --force-worktree 自动清理，或手动 git worktree remove {worktree_path}。"
        )
    return errors


# ---------------------------------------------------------------------------
# git worktree 管理
# ---------------------------------------------------------------------------


def create_worktree(
    worktree_path: Path,
    commit: str,
    *,
    force: bool = False,
) -> None:
    """在 ``worktree_path`` 下 checkout ``commit``。

    若路径已存在且 ``force=True``，先 ``git worktree remove --force``；
    否则 ``git worktree add`` 自己会抛 "already exists" 错误。
    """
    if force and worktree_path.exists():
        log.info("强制清理已存在 worktree: %s", worktree_path)
        remove_worktree(worktree_path)

    log.info("git worktree add %s %s", worktree_path, commit)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree_path), commit],
        cwd=str(_ROOT),
        check=True,
    )


def remove_worktree(worktree_path: Path) -> None:
    """清理 worktree；失败记 warning 不抛."""
    if not worktree_path.exists():
        return
    try:
        subprocess.run(
            ["git", "worktree", "remove", str(worktree_path), "--force"],
            cwd=str(_ROOT),
            check=True,
        )
        log.info("git worktree removed: %s", worktree_path)
    except subprocess.CalledProcessError as exc:
        log.warning("git worktree remove 失败: %s (手动清理: rm -rf %s)", exc, worktree_path)


# ---------------------------------------------------------------------------
# Phase 3 生成（在 worktree 里起子进程跑）
# ---------------------------------------------------------------------------


_PHASE3_GEN_SNIPPET = """
import os, sys, json, pathlib
sys.path.insert(0, {worktree_path!r})
# 确保 worktree 的 src/ 优先于任何其他路径
from src.novel.pipeline import NovelPipeline
pipe = NovelPipeline(workspace={workspace!r})
result = pipe.create_novel(
    genre={genre!r},
    theme={theme!r},
    target_words={target_words},
)
project_path = result.get("project_path") or ""
pipe.generate_chapters(
    project_path=project_path,
    start_chapter=1,
    end_chapter={chapters},
    silent=True,
)
print(json.dumps({{"project_path": project_path}}))
"""


def generate_phase3_for_genre(
    worktree_path: Path,
    genre_cfg: GenreConfig,
    chapters: int,
    workspace: Path,
) -> str | None:
    """在 worktree 里用 Phase 3 代码生成一个 genre 的 1..chapters 章。

    Returns:
        project_path (worktree 内的绝对路径；章节读取时转到 workspace 即可) 或 None。
    """
    # workspace 必须是绝对路径才能在 worktree cwd 下也正确指向
    ws_abs = workspace.resolve()
    snippet = _PHASE3_GEN_SNIPPET.format(
        worktree_path=str(worktree_path),
        workspace=str(ws_abs),
        genre=genre_cfg.genre,
        theme=genre_cfg.theme,
        target_words=genre_cfg.target_words,
        chapters=chapters,
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", snippet],
            cwd=str(worktree_path),
            env={**os.environ, "PYTHONPATH": str(worktree_path)},
            capture_output=True,
            text=True,
            timeout=60 * 30,  # 30 分钟超时
        )
    except subprocess.TimeoutExpired:
        log.error("genre=%s Phase 3 生成超时 (30 分钟)", genre_cfg.key)
        return None

    if proc.returncode != 0:
        log.error(
            "genre=%s Phase 3 生成失败 returncode=%d stderr=%s",
            genre_cfg.key,
            proc.returncode,
            proc.stderr[-500:],
        )
        return None

    # 解析 stdout 最后一行 JSON
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip().startswith("{")]
    if not lines:
        log.error(
            "genre=%s Phase 3 生成子进程未返回 JSON: stdout=%s",
            genre_cfg.key,
            proc.stdout[-500:],
        )
        return None
    try:
        data = json.loads(lines[-1])
    except ValueError as exc:
        log.error("genre=%s Phase 3 子进程 JSON 解析失败: %s", genre_cfg.key, exc)
        return None
    project_path = data.get("project_path") or ""
    if not project_path:
        log.error("genre=%s Phase 3 生成未返回 project_path", genre_cfg.key)
        return None
    return project_path


# ---------------------------------------------------------------------------
# 章节文本收集
# ---------------------------------------------------------------------------


_CHAPTER_FILE_RE = __import__("re").compile(r"chapter_(\d+)\.txt$")


def _parse_genre_from_novel_json(novel_json_path: Path) -> str:
    """从 ``novel.json`` 读 genre 字段并映射到 GenreConfig.key。

    未识别的 genre 返回 ``"unknown"``。
    """
    try:
        data = json.loads(novel_json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("读取 novel.json 失败 %s: %s", novel_json_path, exc)
        return "unknown"
    genre_field = str(data.get("genre", "")).strip()
    return _NOVEL_GENRE_TO_KEY.get(genre_field, "unknown")


def _collect_chapter_texts(
    workspace_root: Path,
    *,
    max_chapters: int,
) -> dict[str, dict[int, str]]:
    """从 ``<workspace>/novels/novel_*/chapters/chapter_*.txt`` 归类成
    ``{genre_key: {chapter_number: text}}``。

    - 每个 ``novels/novel_*/`` 子目录对应一个项目，通过 ``novel.json`` 识别 genre。
    - 未识别 genre 的项目被跳过并记 warning。
    - 某项目存在但无 ``chapters/`` 目录 → 跳过 + warning。
    - 非法章节文件名（无数字）→ 跳过。
    - 同一 genre 重复出现时以第一个被发现的项目为准（后续 warning）。
    """
    result: dict[str, dict[int, str]] = {}
    novels_dir = workspace_root / "novels"
    if not novels_dir.exists() or not novels_dir.is_dir():
        log.warning("novels 目录不存在: %s", novels_dir)
        return result

    for project_dir in sorted(p for p in novels_dir.iterdir() if p.is_dir()):
        novel_json = project_dir / "novel.json"
        if not novel_json.exists():
            log.warning("项目缺 novel.json, 跳过: %s", project_dir)
            continue
        genre_key = _parse_genre_from_novel_json(novel_json)
        if genre_key == "unknown":
            log.warning("无法识别 genre, 跳过项目: %s", project_dir)
            continue

        chapters_dir = project_dir / "chapters"
        if not chapters_dir.exists() or not chapters_dir.is_dir():
            log.warning(
                "项目 %s 无 chapters/ 目录, 跳过 (genre=%s)",
                project_dir,
                genre_key,
            )
            continue

        if genre_key in result:
            log.warning(
                "genre=%s 已有项目 (现项目 %s 被忽略; 若需替换请删除重复项目)",
                genre_key,
                project_dir,
            )
            continue

        texts_for_genre: dict[int, str] = {}
        for txt_path in sorted(chapters_dir.glob("chapter_*.txt")):
            match = _CHAPTER_FILE_RE.search(txt_path.name)
            if not match:
                log.warning("非法章节文件名, 跳过: %s", txt_path)
                continue
            try:
                ch_num = int(match.group(1))
            except ValueError:
                continue
            if ch_num > max_chapters:
                continue
            try:
                texts_for_genre[ch_num] = txt_path.read_text(encoding="utf-8")
            except OSError as exc:
                log.warning("读取章节失败 %s: %s", txt_path, exc)
        if texts_for_genre:
            result[genre_key] = texts_for_genre
        else:
            log.warning(
                "项目 %s 无有效章节 (genre=%s)", project_dir, genre_key
            )
    return result


# ---------------------------------------------------------------------------
# A/B 主流程
# ---------------------------------------------------------------------------


@dataclass
class ABStats:
    """全局统计：winner 分布 + per-dimension 分布 + per-genre 分布."""

    total: int = 0
    overall_winner: Counter = None  # type: ignore[assignment]
    per_dimension: dict[str, Counter] = None  # type: ignore[assignment]
    per_genre: dict[str, Counter] = None  # type: ignore[assignment]
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.overall_winner is None:
            self.overall_winner = Counter()
        if self.per_dimension is None:
            self.per_dimension = {}
        if self.per_genre is None:
            self.per_genre = {}
        if self.errors is None:
            self.errors = []


def _update_stats(stats: ABStats, result: Any) -> None:
    """把一条 :class:`ABComparisonResult` 合并进统计."""
    stats.total += 1
    stats.overall_winner[result.winner] += 1
    for dim, pref in (result.dimension_preferences or {}).items():
        stats.per_dimension.setdefault(dim, Counter())[pref] += 1
    stats.per_genre.setdefault(result.genre, Counter())[result.winner] += 1


def _winner_percentages(counter: Counter) -> dict[str, float]:
    total = sum(counter.values()) or 1
    return {k: round(100.0 * v / total, 1) for k, v in counter.items()}


def _pct_str(counter: Counter) -> str:
    if not counter:
        return "(无数据)"
    pct = _winner_percentages(counter)
    return " / ".join(
        f"{k}:{counter[k]}({pct.get(k, 0):.0f}%)" for k in ("a", "b", "tie") if k in counter
    ) or "(无数据)"


def _interpret_ab_results(stats: ABStats) -> str:
    """基于总体 winner 分布给一句话判读建议 (PHASE5.md 风格)."""
    total = stats.total
    if total == 0:
        return "[判读] 无有效对比结果，无法判断。"
    a = stats.overall_winner.get("a", 0)
    b = stats.overall_winner.get("b", 0)
    tie = stats.overall_winner.get("tie", 0)
    a_pct = 100.0 * a / total
    b_pct = 100.0 * b / total
    tie_pct = 100.0 * tie / total

    # 判读阈值：某一方 >= 60% 视为"大幅胜出"，都在 40% 上下视为"接近"
    if b_pct >= 60.0:
        verdict = (
            f"[判读] Phase 4 大幅胜出 (b={b_pct:.0f}% vs a={a_pct:.0f}% vs tie={tie_pct:.0f}%)"
            "：架构重构 Phase 0-4 改善了生成质量。"
        )
    elif a_pct >= 60.0:
        verdict = (
            f"[判读] Phase 3 大幅胜出 (a={a_pct:.0f}% vs b={b_pct:.0f}% vs tie={tie_pct:.0f}%)"
            "：Phase 4 引入了 regression，需排查。"
        )
    elif abs(a_pct - b_pct) <= 10.0 or tie_pct >= 40.0:
        verdict = (
            f"[判读] 接近 (a={a_pct:.0f}% / b={b_pct:.0f}% / tie={tie_pct:.0f}%)"
            "：架构重构未显著影响生成质量（预期：Writer 本身未改）。"
        )
    else:
        winner = "Phase 4" if b > a else "Phase 3"
        verdict = (
            f"[判读] {winner} 略胜 (a={a_pct:.0f}% / b={b_pct:.0f}% / tie={tie_pct:.0f}%)"
            "；差距不大，建议复跑一轮或换 judge 模型确认。"
        )
    return verdict


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------


def generate_markdown_report(
    ab_results: list[Any],
    stats: ABStats,
    *,
    phase3_commit: str,
    phase4_commit: str,
    judge_model: str,
) -> str:
    """组装 markdown 报告."""
    now = (
        _dt.datetime.now(tz=_dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    lines: list[str] = []
    lines.append("# Phase 3 vs Phase 4 A/B 对比报告\n")
    lines.append(f"- 生成时间: {now}")
    lines.append(f"- Phase 3 commit: `{phase3_commit}`")
    lines.append(f"- Phase 4 commit: `{phase4_commit}`")
    lines.append(f"- judge 模型: `{judge_model or '(未指定)'}`")
    lines.append(f"- A/B 对比总数: {stats.total}")
    lines.append(f"- 错误/跳过数: {len(stats.errors)}")
    lines.append("")

    if stats.errors:
        lines.append("## 错误与跳过\n")
        for err in stats.errors:
            lines.append(f"- {err}")
        lines.append("")

    # 全局 winner 分布
    lines.append("## 全局 winner 分布\n")
    lines.append(f"- {_pct_str(stats.overall_winner)}")
    lines.append("")

    # per-dimension
    lines.append("## per-dimension winner 分布\n")
    lines.append("| 维度 | a (Phase3) | b (Phase4) | tie |")
    lines.append("|------|----------:|----------:|----:|")
    for dim, counter in sorted(stats.per_dimension.items()):
        pct = _winner_percentages(counter)
        a_c = counter.get("a", 0)
        b_c = counter.get("b", 0)
        tie_c = counter.get("tie", 0)
        lines.append(
            f"| {dim} | {a_c} ({pct.get('a', 0):.0f}%) |"
            f" {b_c} ({pct.get('b', 0):.0f}%) |"
            f" {tie_c} ({pct.get('tie', 0):.0f}%) |"
        )
    lines.append("")

    # per-genre
    lines.append("## per-genre winner 分布\n")
    lines.append("| Genre | a (Phase3) | b (Phase4) | tie |")
    lines.append("|-------|----------:|----------:|----:|")
    for genre, counter in sorted(stats.per_genre.items()):
        pct = _winner_percentages(counter)
        a_c = counter.get("a", 0)
        b_c = counter.get("b", 0)
        tie_c = counter.get("tie", 0)
        lines.append(
            f"| {genre} | {a_c} ({pct.get('a', 0):.0f}%) |"
            f" {b_c} ({pct.get('b', 0):.0f}%) |"
            f" {tie_c} ({pct.get('tie', 0):.0f}%) |"
        )
    lines.append("")

    # per-genre 明细（每章 winner + 每维度偏好）
    lines.append("## 明细（按 genre 分组）\n")
    grouped: dict[str, list[Any]] = {}
    for r in ab_results:
        grouped.setdefault(r.genre, []).append(r)
    for genre in sorted(grouped):
        items = sorted(grouped[genre], key=lambda r: r.chapter_number)
        lines.append(f"### {genre}\n")
        lines.append("| Ch | Winner | Reasoning | narrative_flow | plot_advancement | character_consistency | dialogue_quality | chapter_hook |")
        lines.append("|----|--------|-----------|:-:|:-:|:-:|:-:|:-:|")
        for r in items:
            prefs = r.dimension_preferences or {}
            reasoning = (r.judge_reasoning or "").replace("|", " ").replace("\n", " ")
            lines.append(
                f"| {r.chapter_number} | {r.winner} | {reasoning[:80]} |"
                f" {prefs.get('narrative_flow', '-') } |"
                f" {prefs.get('plot_advancement', '-') } |"
                f" {prefs.get('character_consistency', '-') } |"
                f" {prefs.get('dialogue_quality', '-') } |"
                f" {prefs.get('chapter_hook', '-') } |"
            )
        lines.append("")

    # 判读
    lines.append("## 判读\n")
    lines.append(_interpret_ab_results(stats))
    lines.append("")
    lines.append("判读规则:")
    lines.append("- `b` 大幅胜出 (>= 60%) → Phase 4 架构重构改善了生成质量")
    lines.append("- `a/b/tie` 接近 (差距 <= 10% 或 tie >= 40%) → 架构重构未显著影响质量 (预期：Writer 本身未改)")
    lines.append("- `a` 大幅胜出 (>= 60%) → Phase 4 引入 regression，需排查")
    lines.append("")
    lines.append("---")
    lines.append("_由 scripts/quality_ab_phase3_vs_phase4.py 生成._")
    return "\n".join(lines)


def print_plan(args: argparse.Namespace, genres: list[GenreConfig]) -> None:
    print("=" * 72)
    print("Phase 3 vs Phase 4 A/B 对比 计划 (dry-run)")
    print("=" * 72)
    print(f"  Phase 3 commit      : {args.phase3_commit}")
    print(f"  Phase 4 commit      : {args.phase4_commit}")
    print(f"  worktree 路径       : {args.worktree_path}")
    print(f"  Phase 3 workspace   : {args.phase3_workspace}")
    print(f"  Phase 4 workspace   : {args.phase4_workspace}")
    print(f"  output-dir          : {args.output_dir}")
    print(f"  chapters/genre      : {args.chapters}")
    print(f"  skip-generation     : {args.skip_generation}")
    print(f"  judge-model         : {args.judge_model or '(异源自动选择)'}")
    print(f"  genres ({len(genres)}):")
    for g in genres:
        print(
            f"    - {g.key:10s} | {g.genre:6s} | target={g.target_words:>6d}"
        )
    total_ab = len(genres) * args.chapters
    print(f"  预估 A/B pairwise_judge 调用数: {total_ab}")
    print("=" * 72)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    pairwise_judge_fn: Callable | None = None,
    generate_fn: Callable | None = None,
    judge_config_factory: Callable | None = None,
) -> int:
    """主入口。

    ``pairwise_judge_fn`` / ``generate_fn`` / ``judge_config_factory`` 用于测试注入。

    Returns:
        退出码: 0 = 正常, 1 = 前置检查失败 / 无有效对比。
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

    errors = preflight_checks(args)
    if errors:
        for err in errors:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    phase3_commit = _resolve_commit_short(args.phase3_commit)
    phase4_commit = _resolve_commit_short(args.phase4_commit)

    worktree_path = Path(args.worktree_path)
    phase3_workspace = Path(args.phase3_workspace)

    # --- 步骤 1: 创建 worktree + 在 worktree 里跑 Phase 3 生成 -----------------
    worktree_created = False
    try:
        if not args.skip_generation:
            create_worktree(
                worktree_path, phase3_commit, force=args.force_worktree
            )
            worktree_created = True

            _gen = generate_fn or generate_phase3_for_genre
            phase3_workspace.mkdir(parents=True, exist_ok=True)
            for g in genres:
                log.info("Phase 3 生成 genre=%s ...", g.key)
                pp = _gen(worktree_path, g, args.chapters, phase3_workspace)
                if pp is None:
                    log.error("genre=%s Phase 3 生成失败, 跳过该 genre 的 A/B", g.key)
                    continue
                log.info("genre=%s Phase 3 生成完成: %s", g.key, pp)

        # --- 步骤 2: 收集两侧章节文本 -----------------------------------------
        phase3_texts = _collect_chapter_texts(
            phase3_workspace, max_chapters=args.chapters
        )
        phase4_texts = _collect_chapter_texts(
            Path(args.phase4_workspace), max_chapters=args.chapters
        )
        log.info(
            "收集完毕: Phase3 genres=%s / Phase4 genres=%s",
            sorted(phase3_texts.keys()),
            sorted(phase4_texts.keys()),
        )

        # --- 步骤 3: judge 配置 ----------------------------------------------
        if judge_config_factory is None:
            # 复用 quality_regression 的 auto_select_judge_from_env 逻辑
            from src.novel.quality.judge import auto_select_judge

            writer_provider = "gemini"
            if os.environ.get("DEEPSEEK_API_KEY"):
                writer_provider = "deepseek"
            elif os.environ.get("GEMINI_API_KEY"):
                writer_provider = "gemini"
            elif os.environ.get("OPENAI_API_KEY"):
                writer_provider = "openai"
            judge_config = auto_select_judge(writer_provider)
            if args.judge_model:
                judge_config.model = args.judge_model
        else:
            judge_config = judge_config_factory(args)

        # --- 步骤 4: 对每 (genre, ch) 跑 pairwise_judge ----------------------
        if pairwise_judge_fn is None:
            from src.novel.quality.ab_compare import pairwise_judge as _pj

            pairwise_judge_fn = _pj

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        stats = ABStats()
        ab_results: list[Any] = []

        today = _dt.date.today().isoformat()
        for g in genres:
            p3 = phase3_texts.get(g.key, {})
            p4 = phase4_texts.get(g.key, {})
            for ch in range(1, args.chapters + 1):
                text_a = p3.get(ch, "")
                text_b = p4.get(ch, "")
                if not text_a or not text_b:
                    msg = (
                        f"跳过 (genre={g.key} ch={ch}): "
                        f"phase3_has={bool(text_a)} phase4_has={bool(text_b)}"
                    )
                    log.warning(msg)
                    stats.errors.append(msg)
                    continue
                try:
                    result = pairwise_judge_fn(
                        text_a=text_a,
                        text_b=text_b,
                        genre=g.genre,
                        chapter_number=ch,
                        commit_a=phase3_commit,
                        commit_b=phase4_commit,
                        config=judge_config,
                    )
                except Exception as exc:  # pragma: no cover - judge 调用失败软降级
                    msg = f"pairwise_judge 失败 (genre={g.key} ch={ch}): {exc}"
                    log.error(msg)
                    stats.errors.append(msg)
                    continue

                # 兼容 judge 结果：winner 若混入别的，统计层不直接信任
                ab_results.append(result)
                # 统一在 genre_key（英文 key）维度聚合，而不是中文 genre
                # 但 result.genre 本身是中文（体裁参数），重写为 key 以便 per-genre 聚合
                try:
                    result_for_stats = result
                    # 做一个浅层包装覆盖 genre 用于统计（不修改原对象）
                    class _StatWrap:
                        pass

                    w = _StatWrap()
                    w.winner = result.winner
                    w.dimension_preferences = result.dimension_preferences
                    w.genre = g.key
                    _update_stats(stats, w)
                except Exception:  # pragma: no cover - defensive
                    _update_stats(stats, result)

                # 落盘单条 JSON
                per_file = (
                    output_dir
                    / f"{today}_{g.key}_ch{ch}_phase3_vs_phase4.json"
                )
                try:
                    per_file.write_text(
                        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except (OSError, AttributeError) as exc:
                    log.warning("写 JSON 失败 %s: %s", per_file, exc)

        # --- 步骤 5: 汇总报告 ------------------------------------------------
        summary = {
            "phase3_commit": phase3_commit,
            "phase4_commit": phase4_commit,
            "judge_model": judge_config.model,
            "total": stats.total,
            "overall_winner": dict(stats.overall_winner),
            "per_dimension": {k: dict(v) for k, v in stats.per_dimension.items()},
            "per_genre": {k: dict(v) for k, v in stats.per_genre.items()},
            "errors": list(stats.errors),
        }
        summary_path = output_dir / f"{today}_ab_summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        md = generate_markdown_report(
            ab_results,
            stats,
            phase3_commit=phase3_commit,
            phase4_commit=phase4_commit,
            judge_model=judge_config.model,
        )
        md_path = output_dir / f"{today}_ab_report.md"
        md_path.write_text(md, encoding="utf-8")
        log.info("A/B 报告写入: %s", md_path)
        print(_interpret_ab_results(stats))

        return 0 if stats.total > 0 else 1

    finally:
        # 无论 A/B 成功失败，清理 worktree
        if worktree_created:
            remove_worktree(worktree_path)


if __name__ == "__main__":
    raise SystemExit(main())
