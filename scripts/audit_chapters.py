"""审核已生成章节 — 用项目重构后的服务跑纯规则 + 可选 LLM judge.

用法::

    # 纯规则审计（无 LLM 调用）
    python scripts/audit_chapters.py --novel-id novel_12e1c974 --start 18 --end 32

    # + Reviewer Agent LLM 批评（每章 1 次 LLM）
    python scripts/audit_chapters.py --novel-id novel_12e1c974 --start 18 --end 32 \\
        --with-reviewer

    # + Phase 5 LLM judge 完整七维（每章 3 次 LLM call）
    python scripts/audit_chapters.py --novel-id novel_12e1c974 --start 18 --end 32 \\
        --with-reviewer --with-llm-judge

输出
----
- workspace/quality_reports/audit/<novel_id>_ch<start>-<end>.json
- workspace/quality_reports/audit/<novel_id>_ch<start>-<end>.md
- 控制台 Rich Table 摘要
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# .env 手动加载（与 verify_novel_fixes.py / quality_regression.py 一致）
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

from src.novel.config import NovelConfig
from src.novel.storage.file_manager import FileManager
from src.novel.storage.novel_memory import NovelMemory
from src.novel.services.ledger_store import LedgerStore
from src.novel.services.style_profile_service import StyleProfileService
from src.novel.models.style_profile import StyleProfile
from src.novel.quality.dimensions import (
    evaluate_ai_flavor,
    evaluate_chapter_hook_rules,
    evaluate_dialogue_quality_rules,
    evaluate_foreshadow_payoff,
)
from src.novel.agents.reviewer import Reviewer

log = logging.getLogger("audit_chapters")


@dataclass
class ChapterAudit:
    chapter_number: int
    word_count: int
    title_in_outline: str
    chapter_goal: str
    actual_summary_present: bool
    chapter_brief_present: bool
    pure_rule: dict[str, Any] = field(default_factory=dict)
    ledger_snapshot: dict[str, Any] = field(default_factory=dict)
    reviewer: dict[str, Any] = field(default_factory=dict)
    llm_judge: dict[str, Any] = field(default_factory=dict)
    structural_issues: list[str] = field(default_factory=list)


def _load_style_profile(fm: FileManager, novel_id: str) -> StyleProfile | None:
    raw = fm.load_style_profile(novel_id)
    if not raw:
        return None
    try:
        return StyleProfile.model_validate(raw)
    except Exception as exc:
        log.warning("style profile parse failed: %s", exc)
        return None


def _build_ledger(
    project_path: Path, novel_data: dict, workspace: str
) -> tuple[LedgerStore, NovelMemory]:
    """构造 LedgerStore — 复用项目现有 memory.db / kg / vectors."""
    novel_id = project_path.name
    mem = NovelMemory(novel_id=novel_id, workspace_dir=workspace)
    ledger = LedgerStore(
        project_path=project_path,
        db=mem.structured_db,
        kg=mem.knowledge_graph,
        vector_store=mem.vector_store,
        novel_data=novel_data,
    )
    return ledger, mem


def _structural_check(
    novel_data: dict,
    chapter_number: int,
    text: str,
) -> tuple[str, str, bool, bool, list[str]]:
    """Outline / brief 覆盖 + 结构异常硬指标."""
    issues: list[str] = []
    outline = novel_data.get("outline", {}) or {}
    chapters = outline.get("chapters", []) or []
    target = next(
        (c for c in chapters if int(c.get("chapter_number") or 0) == chapter_number),
        None,
    )
    if target is None:
        issues.append("outline_missing")
        return "", "", False, False, issues

    title = str(target.get("title") or "")
    goal = str(target.get("goal") or "")
    actual_summary_present = bool(str(target.get("actual_summary") or "").strip())
    chapter_brief_present = bool(target.get("chapter_brief") or {})

    if not title:
        issues.append("outline_title_empty")
    if not goal:
        issues.append("outline_goal_empty")
    if not actual_summary_present:
        issues.append("actual_summary_missing")
    if not chapter_brief_present:
        issues.append("chapter_brief_missing")

    word_count = sum(1 for c in text if c.strip())
    if word_count < 1500:
        issues.append(f"too_short:{word_count}")
    if word_count > 6000:
        issues.append(f"too_long:{word_count}")

    return title, goal, actual_summary_present, chapter_brief_present, issues


def _ledger_snapshot(ledger: LedgerStore, chapter_number: int) -> dict[str, Any]:
    try:
        snap = ledger.snapshot_for_chapter(chapter_number)
    except Exception as exc:
        return {"error": str(exc)}
    summary: dict[str, Any] = {
        "active_obligations": len(snap.get("active_obligations") or []),
        "overdue_obligations": len(snap.get("overdue_obligations") or []),
        "collectable_foreshadowings": len(snap.get("collectable_foreshadowings") or []),
        "due_milestones": len(snap.get("due_milestones") or []),
        "overdue_milestones": len(snap.get("overdue_milestones") or []),
        "active_arcs_count": len(snap.get("active_arcs") or []),
    }
    overdue_titles = [
        m.get("description") or m.get("milestone_id")
        for m in (snap.get("overdue_milestones") or [])[:5]
    ]
    if overdue_titles:
        summary["overdue_milestone_samples"] = overdue_titles
    return summary


def _pure_rule_dimensions(
    text: str,
    chapter_number: int,
    previous_tail: str,
    ledger: LedgerStore,
    style_profile: StyleProfile | None,
    chapters_text: dict[int, str],
    genre: str,
) -> dict[str, Any]:
    fp = evaluate_foreshadow_payoff(
        ledger=ledger,
        chapter_number=chapter_number,
        chapters_text=chapters_text,
    )
    af = evaluate_ai_flavor(text=text, style_profile=style_profile, genre=genre)
    dq = evaluate_dialogue_quality_rules(text)
    ch = evaluate_chapter_hook_rules(text, previous_tail)

    return {
        "D3_foreshadow_payoff": {
            "score": fp.score,
            "scale": fp.scale,
            "details": fp.details,
        },
        "D4_ai_flavor": {
            "score": af.score,
            "scale": af.scale,
            "details": {
                k: v
                for k, v in af.details.items()
                if k
                in {
                    "overuse_count",
                    "cliche_hits",
                    "repetition_score",
                    "warnings",
                    "profile_missing",
                }
            },
        },
        "D6_dialogue_rules": dq,
        "D7_hook_rules": ch,
    }


def _run_reviewer(
    text: str,
    chapter_number: int,
    title: str,
    goal: str,
    previous_tail: str,
    ledger: LedgerStore,
    style_profile: StyleProfile | None,
    llm_cfg: dict,
    active_characters: list[str],
    chapter_brief: dict | None,
) -> dict[str, Any]:
    from src.llm.llm_client import create_llm_client

    llm = create_llm_client(llm_cfg) if llm_cfg else None
    reviewer = Reviewer(
        llm=llm,
        ledger=ledger,
        style_profile=style_profile,
    )
    result = reviewer.review(
        chapter_text=text,
        chapter_number=chapter_number,
        chapter_title=title,
        chapter_goal=goal,
        previous_tail=previous_tail,
        chapter_brief=chapter_brief,
        active_characters=active_characters,
    )
    return {
        "high_severity_count": result.high_severity_count,
        "medium_severity_count": result.medium_severity_count,
        "issue_count": len(result.issues),
        "consistency_flag_count": len(result.consistency_flags),
        "high_consistency_flags": [
            {"type": f.type, "detail": f.detail}
            for f in result.consistency_flags
            if f.severity == "high"
        ][:5],
        "issues_top": [
            {
                "type": iss.type,
                "severity": iss.severity,
                "quote": iss.quote[:60],
                "reason": iss.reason[:200],
            }
            for iss in sorted(
                result.issues,
                key=lambda i: {"high": 0, "medium": 1, "low": 2}.get(i.severity, 3),
            )[:8]
        ],
        "overall_assessment": (result.overall_assessment or "")[:500],
        "style_overuse_hits": result.style_overuse_hits[:8],
        "need_rewrite_flag": result.need_rewrite,
        "strengths_top": (result.strengths or [])[:3],
    }


def _run_llm_judge(
    text: str,
    previous_tail: str,
    chapter_number: int,
    chapter_goal: str,
    genre: str,
    character_names: list[str],
    judge_cfg: Any,
) -> dict[str, Any]:
    from src.novel.quality.judge import (
        evaluate_multi_dimension_llm,
        evaluate_narrative_flow_llm,
        evaluate_plot_advancement_llm,
    )

    ctx = {
        "genre": genre,
        "chapter_goal": chapter_goal,
        "previous_tail": previous_tail,
        "character_names": character_names,
    }
    out: dict[str, Any] = {}
    d1 = evaluate_narrative_flow_llm(text, ctx, judge_cfg)
    out["D1_narrative_flow"] = {"score": d1.score, "reason": d1.details.get("judge_reasoning", "")[:300]}
    d5 = evaluate_plot_advancement_llm(text, ctx, judge_cfg)
    out["D5_plot_advancement"] = {"score": d5.score, "reason": d5.details.get("judge_reasoning", "")[:300]}
    multi = evaluate_multi_dimension_llm(text, ctx, judge_cfg)
    for dim in multi:
        out[f"multi_{dim.key}"] = {
            "score": dim.score,
            "reason": dim.details.get("judge_reasoning", "")[:300],
        }
    return out


def _judge_config(novel_data: dict) -> Any:
    """异源原则：writer 用啥，judge 切到对侧；强制 gemini 优先以省钱."""
    from src.novel.quality.judge import JudgeConfig, auto_select_judge

    writer_provider = (
        (novel_data.get("config") or {}).get("llm", {}).get("provider", "deepseek")
    )
    return auto_select_judge(writer_provider)


def _build_chapter_audits(
    fm: FileManager,
    novel_id: str,
    novel_data: dict,
    ledger: LedgerStore,
    style_profile: StyleProfile | None,
    start: int,
    end: int,
    with_reviewer: bool,
    with_llm_judge: bool,
    llm_cfg: dict,
) -> list[ChapterAudit]:
    chapters_text: dict[int, str] = {}
    for ch_num in range(1, end + 1):
        txt = fm.load_chapter_text(novel_id, ch_num)
        if txt:
            chapters_text[ch_num] = txt

    judge_cfg = _judge_config(novel_data) if with_llm_judge else None

    audits: list[ChapterAudit] = []
    genre = str(novel_data.get("genre") or "")
    main_chars = [
        c.get("name", "") for c in (novel_data.get("characters") or []) if c.get("name")
    ]

    for ch_num in range(start, end + 1):
        text = chapters_text.get(ch_num)
        if not text:
            audits.append(
                ChapterAudit(
                    chapter_number=ch_num,
                    word_count=0,
                    title_in_outline="",
                    chapter_goal="",
                    actual_summary_present=False,
                    chapter_brief_present=False,
                    structural_issues=["chapter_text_missing"],
                )
            )
            continue

        title, goal, has_summary, has_brief, struct_issues = _structural_check(
            novel_data, ch_num, text
        )
        word_count = sum(1 for c in text if c.strip())
        previous_tail = (chapters_text.get(ch_num - 1) or "")[-1500:]

        outline = novel_data.get("outline", {}) or {}
        target_outline = next(
            (
                c
                for c in (outline.get("chapters") or [])
                if int(c.get("chapter_number") or 0) == ch_num
            ),
            None,
        )
        chapter_brief = (target_outline or {}).get("chapter_brief") or {}

        audit = ChapterAudit(
            chapter_number=ch_num,
            word_count=word_count,
            title_in_outline=title,
            chapter_goal=goal,
            actual_summary_present=has_summary,
            chapter_brief_present=has_brief,
            structural_issues=struct_issues,
        )

        try:
            audit.pure_rule = _pure_rule_dimensions(
                text=text,
                chapter_number=ch_num,
                previous_tail=previous_tail,
                ledger=ledger,
                style_profile=style_profile,
                chapters_text=chapters_text,
                genre=genre,
            )
        except Exception as exc:
            log.exception("D3/D4/D6/D7 failed at ch%d: %s", ch_num, exc)
            audit.pure_rule = {"error": str(exc)}

        try:
            audit.ledger_snapshot = _ledger_snapshot(ledger, ch_num)
        except Exception as exc:
            audit.ledger_snapshot = {"error": str(exc)}

        if with_reviewer:
            try:
                audit.reviewer = _run_reviewer(
                    text=text,
                    chapter_number=ch_num,
                    title=title,
                    goal=goal,
                    previous_tail=previous_tail,
                    ledger=ledger,
                    style_profile=style_profile,
                    llm_cfg=llm_cfg,
                    active_characters=main_chars,
                    chapter_brief=chapter_brief,
                )
            except Exception as exc:
                log.exception("Reviewer failed at ch%d: %s", ch_num, exc)
                audit.reviewer = {"error": str(exc)}

        if with_llm_judge and judge_cfg is not None:
            try:
                audit.llm_judge = _run_llm_judge(
                    text=text,
                    previous_tail=previous_tail,
                    chapter_number=ch_num,
                    chapter_goal=goal,
                    genre=genre,
                    character_names=main_chars,
                    judge_cfg=judge_cfg,
                )
            except Exception as exc:
                log.exception("LLM judge failed at ch%d: %s", ch_num, exc)
                audit.llm_judge = {"error": str(exc)}

        audits.append(audit)
        log.info("Audited ch%d: words=%d issues=%d", ch_num, word_count, len(struct_issues))

    return audits


def _render_markdown(novel_data: dict, audits: list[ChapterAudit]) -> str:
    lines: list[str] = []
    title = novel_data.get("title", "?")
    novel_id = novel_data.get("novel_id", "?")
    lines.append(f"# 章节审计报告 — {title} ({novel_id})")
    lines.append("")
    lines.append(f"审计章节范围: ch{audits[0].chapter_number}–ch{audits[-1].chapter_number}")
    lines.append("")
    lines.append("## 摘要表")
    lines.append("")
    lines.append(
        "| 章 | 字数 | 大纲标题 | actual_summary | brief | D3兑现率 | D4 AI味 | rev高/中 | 结构异常 |"
    )
    lines.append("|---|---:|---|:-:|:-:|---:|---:|---:|---|")
    for a in audits:
        d3 = a.pure_rule.get("D3_foreshadow_payoff", {}).get("score")
        d4 = a.pure_rule.get("D4_ai_flavor", {}).get("score")
        rev_h = a.reviewer.get("high_severity_count", "-")
        rev_m = a.reviewer.get("medium_severity_count", "-")
        d3s = "-" if d3 is None else f"{d3:.0f}%"
        d4s = "-" if d4 is None else f"{d4:.1f}"
        title_short = (a.title_in_outline or "")[:18]
        struct = ",".join(a.structural_issues) or "-"
        lines.append(
            f"| {a.chapter_number} | {a.word_count} | {title_short} | "
            f"{'✓' if a.actual_summary_present else '✗'} | "
            f"{'✓' if a.chapter_brief_present else '✗'} | {d3s} | {d4s} | "
            f"{rev_h}/{rev_m} | {struct} |"
        )
    lines.append("")

    for a in audits:
        lines.append(f"## 第{a.chapter_number}章 详细")
        lines.append("")
        lines.append(f"- **大纲标题**: {a.title_in_outline}")
        lines.append(f"- **大纲目标**: {a.chapter_goal}")
        lines.append(f"- **字数**: {a.word_count}")
        if a.structural_issues:
            lines.append(f"- **结构异常**: {', '.join(a.structural_issues)}")
        if a.ledger_snapshot:
            lines.append(f"- **Ledger 快照**: `{json.dumps(a.ledger_snapshot, ensure_ascii=False)}`")
        if a.reviewer:
            lines.append("")
            lines.append("### Reviewer")
            if a.reviewer.get("error"):
                lines.append(f"- 错误: {a.reviewer['error']}")
            else:
                lines.append(
                    f"- 严重度统计: high={a.reviewer.get('high_severity_count')} medium={a.reviewer.get('medium_severity_count')}"
                )
                lines.append(f"- 总评: {a.reviewer.get('overall_assessment','')}")
                if a.reviewer.get("issues_top"):
                    lines.append("- 问题 top:")
                    for iss in a.reviewer["issues_top"]:
                        lines.append(
                            f"  - **[{iss['severity']} / {iss['type']}]** "
                            f"`{iss['quote']}` — {iss['reason']}"
                        )
                if a.reviewer.get("high_consistency_flags"):
                    lines.append("- 高严重度一致性 flag:")
                    for f in a.reviewer["high_consistency_flags"]:
                        lines.append(f"  - [{f['type']}] {f['detail']}")
                if a.reviewer.get("style_overuse_hits"):
                    lines.append(
                        f"- 本书口头禅命中 (overuse): {', '.join(a.reviewer['style_overuse_hits'])}"
                    )
        if a.llm_judge:
            lines.append("")
            lines.append("### LLM Judge (Phase 5)")
            for k, v in a.llm_judge.items():
                if not isinstance(v, dict):
                    continue
                sc = v.get("score")
                lines.append(
                    f"- **{k}**: {sc} — {v.get('reason','')[:200]}"
                )
        lines.append("")

    return "\n".join(lines)


def _print_table(audits: list[ChapterAudit]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
    except Exception:
        for a in audits:
            print(
                f"ch{a.chapter_number} words={a.word_count} "
                f"issues={a.structural_issues} "
                f"rev_high={a.reviewer.get('high_severity_count','-')} "
                f"D4={a.pure_rule.get('D4_ai_flavor',{}).get('score','-')}"
            )
        return

    table = Table(title="章节审计结果")
    table.add_column("Ch", justify="right")
    table.add_column("字数", justify="right")
    table.add_column("大纲标题")
    table.add_column("D3", justify="right")
    table.add_column("D4 AI味", justify="right")
    table.add_column("rev high")
    table.add_column("rev medium")
    table.add_column("结构异常", overflow="fold", max_width=30)
    table.add_column("总评", overflow="fold", max_width=40)
    for a in audits:
        d3 = a.pure_rule.get("D3_foreshadow_payoff", {}).get("score")
        d4 = a.pure_rule.get("D4_ai_flavor", {}).get("score")
        d3s = "-" if d3 is None else f"{d3:.0f}%"
        d4s = "-" if d4 is None else f"{d4:.1f}"
        table.add_row(
            str(a.chapter_number),
            str(a.word_count),
            (a.title_in_outline or "")[:14],
            d3s,
            d4s,
            str(a.reviewer.get("high_severity_count", "-")),
            str(a.reviewer.get("medium_severity_count", "-")),
            ",".join(a.structural_issues) or "-",
            (a.reviewer.get("overall_assessment", "") or "")[:80],
        )
    Console().print(table)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="workspace")
    parser.add_argument("--novel-id", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--with-reviewer", action="store_true")
    parser.add_argument("--with-llm-judge", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    fm = FileManager(args.workspace)
    novel_data = fm.load_novel(args.novel_id)
    if novel_data is None:
        print(f"找不到项目: {args.novel_id}", file=sys.stderr)
        return 2

    project_path = Path(args.workspace) / "novels" / args.novel_id
    ledger, _mem = _build_ledger(project_path, novel_data, args.workspace)
    style_profile = _load_style_profile(fm, args.novel_id)
    if style_profile is None and (args.with_reviewer or args.with_llm_judge):
        log.info("StyleProfile 不存在，尝试从 chapters 重建...")
        try:
            from src.novel.models.novel import Novel
            novel = Novel.model_validate(novel_data)
            style_profile = StyleProfileService().build(novel)
        except Exception as exc:
            log.warning("StyleProfile rebuild failed: %s", exc)

    cfg = NovelConfig()
    llm_cfg = {
        "provider": "auto",
        "model": cfg.llm.quality_review,
        "temperature": 0.3,
        "max_tokens": 2048,
    }

    audits = _build_chapter_audits(
        fm=fm,
        novel_id=args.novel_id,
        novel_data=novel_data,
        ledger=ledger,
        style_profile=style_profile,
        start=args.start,
        end=args.end,
        with_reviewer=args.with_reviewer,
        with_llm_judge=args.with_llm_judge,
        llm_cfg=llm_cfg,
    )

    out_dir = Path(args.workspace) / "quality_reports" / "audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.novel_id}_ch{args.start}-{args.end}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"

    json_path.write_text(
        json.dumps(
            {
                "novel_id": args.novel_id,
                "title": novel_data.get("title"),
                "range": [args.start, args.end],
                "audits": [asdict(a) for a in audits],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    md_path.write_text(_render_markdown(novel_data, audits), encoding="utf-8")

    print(f"\nJSON: {json_path}")
    print(f"MD:   {md_path}")
    print()
    _print_table(audits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
