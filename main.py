"""AI 小说推文自动化 - CLI 入口"""

import click
from pathlib import Path
from rich.table import Table
from src.logger import console, log


@click.group()
def cli():
    """AI 小说推文自动化工具 - 小说一键转短视频"""
    pass


@cli.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option("--config", "-c", type=click.Path(), default=None, help="配置文件路径")
@click.option("--output", "-o", type=click.Path(), default=None, help="输出目录")
@click.option("--workspace", "-w", type=click.Path(), default=None, help="工作目录")
@click.option("--resume", "-r", is_flag=True, help="断点续传")
@click.option("--mode", type=click.Choice(["classic", "agent"]), default="classic",
              help="运行模式: classic(传统) | agent(智能Agent)")
@click.option("--budget-mode", is_flag=True, help="省钱模式（仅Agent模式有效）")
@click.option("--quality-threshold", type=float, default=None,
              help="图片质量阈值 0-10（仅Agent模式有效）")
def run(input_file: str, config: str | None, output: str | None,
        workspace: str | None, resume: bool, mode: str,
        budget_mode: bool, quality_threshold: float | None):
    """全流程: 小说 → 短视频"""
    try:
        if mode == "agent":
            from src.agent_pipeline import AgentPipeline

            pipe = AgentPipeline(
                input_file=Path(input_file),
                config_path=Path(config) if config else None,
                output_dir=Path(output) if output else None,
                workspace=Path(workspace) if workspace else None,
                resume=resume,
                budget_mode=budget_mode,
                quality_threshold=quality_threshold,
            )
        else:
            from src.pipeline import Pipeline

            pipe = Pipeline(
                input_file=Path(input_file),
                config_path=Path(config) if config else None,
                output_dir=Path(output) if output else None,
                workspace=Path(workspace) if workspace else None,
                resume=resume,
            )

        result = pipe.run()
        console.print(f"\n[bold green]视频生成完成: {result}[/]")
    except Exception as e:
        log.error("处理失败: %s", e)
        raise click.Abort()


@cli.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option("--config", "-c", type=click.Path(), default=None, help="配置文件路径")
@click.option("--method", "-m", type=click.Choice(["simple", "llm"]), default=None,
              help="分段方法")
def segment(input_file: str, config: str | None, method: str | None):
    """仅执行文本分段"""
    from src.config_manager import load_config
    from src.segmenter.text_segmenter import create_segmenter

    cfg = load_config(Path(config) if config else None)
    if method:
        cfg["segmenter"]["method"] = method

    text = Path(input_file).read_text(encoding="utf-8")
    segmenter = create_segmenter(cfg["segmenter"])
    segments = segmenter.segment(text)

    for i, seg in enumerate(segments):
        console.print(f"\n[bold cyan]--- 段 {i+1} ---[/]")
        console.print(seg["text"])

    console.print(f"\n[bold green]共 {len(segments)} 段[/]")


@cli.command()
@click.argument("workspace_dir", type=click.Path(exists=True))
@click.option("--decisions", is_flag=True, help="显示 Agent 决策日志")
def status(workspace_dir: str, decisions: bool):
    """查看项目处理进度"""
    from src.checkpoint import Checkpoint

    ckpt = Checkpoint(Path(workspace_dir))
    data = ckpt.data

    table = Table(title="项目进度")
    table.add_column("阶段", style="cyan")
    table.add_column("状态", style="green")

    stage_names = {
        "segment": "文本分段",
        "prompt": "Prompt 生成",
        "image": "图片生成",
        "tts": "语音合成",
        "video": "视频合成",
    }

    for key, name in stage_names.items():
        info = data.get("stages", {}).get(key, {})
        done = info.get("done", False)
        status_str = "[green]完成[/]" if done else "[yellow]待处理[/]"
        table.add_row(name, status_str)

    seg_count = len(data.get("segments", []))
    table.add_row("总段数", str(seg_count))

    console.print(table)

    if decisions:
        _show_decisions(Path(workspace_dir))


def _show_decisions(workspace: Path) -> None:
    """显示 Agent 决策日志摘要。"""
    from src.agents.utils import load_decisions_from_file
    from collections import defaultdict

    decisions_file = workspace / "agent_decisions.json"
    decisions = load_decisions_from_file(decisions_file)

    if not decisions:
        console.print("\n[yellow]未找到决策日志（agent_decisions.json 不存在或为空）[/]")
        return

    # Group by agent
    by_agent: dict[str, list] = defaultdict(list)
    for d in decisions:
        by_agent[d.get("agent", "unknown")].append(d)

    # Decision table
    dec_table = Table(title="Agent 决策日志")
    dec_table.add_column("Agent", style="cyan")
    dec_table.add_column("步骤", style="white")
    dec_table.add_column("决策", style="green")
    dec_table.add_column("原因", style="dim")

    for agent, decs in by_agent.items():
        for i, d in enumerate(decs):
            dec_table.add_row(
                agent if i == 0 else "",
                d.get("step", ""),
                d.get("decision", ""),
                d.get("reason", ""),
            )

    console.print()
    console.print(dec_table)

    # Per-agent summary
    summary_table = Table(title="决策统计")
    summary_table.add_column("Agent", style="cyan")
    summary_table.add_column("决策数", style="white")
    for agent, decs in by_agent.items():
        summary_table.add_row(agent, str(len(decs)))
    summary_table.add_row("[bold]总计[/]", f"[bold]{len(decisions)}[/]")
    console.print(summary_table)

    # Quality scores summary
    all_scores = []
    for d in decisions:
        data = d.get("data") or {}
        if "score" in data:
            try:
                all_scores.append(float(data["score"]))
            except (ValueError, TypeError):
                pass
    if all_scores:
        q_table = Table(title="质量评分摘要")
        q_table.add_column("指标", style="cyan")
        q_table.add_column("值", style="white")
        q_table.add_row("平均分", f"{sum(all_scores) / len(all_scores):.2f}")
        q_table.add_row("最低分", f"{min(all_scores):.2f}")
        q_table.add_row("最高分", f"{max(all_scores):.2f}")
        q_table.add_row("评分数", str(len(all_scores)))
        console.print(q_table)

    # Retry statistics
    retry_decisions = [
        d for d in decisions
        if "retry" in d.get("decision", "").lower()
        or "重试" in d.get("decision", "")
    ]
    if retry_decisions:
        r_table = Table(title="重试统计")
        r_table.add_column("Agent", style="cyan")
        r_table.add_column("重试次数", style="yellow")
        retry_by_agent: dict[str, int] = defaultdict(int)
        for d in retry_decisions:
            retry_by_agent[d.get("agent", "unknown")] += 1
        for agent, count in retry_by_agent.items():
            r_table.add_row(agent, str(count))
        r_table.add_row("[bold]总计[/]", f"[bold]{len(retry_decisions)}[/]")
        console.print(r_table)


# ---------------------------------------------------------------------------
# novel 命令组 - AI 长篇小说写作
# ---------------------------------------------------------------------------


@cli.group()
def novel():
    """AI 长篇小说写作"""
    pass


@novel.command("write")
# Phase 0 架构重构：零默认体裁。立项必须显式选体裁，不给 fallback。
@click.option("--genre", required=True, help="题材（玄幻/都市/武侠/悬疑等），必填")
@click.option("--theme", required=True, help="主题（如：商战复仇、修仙逆袭）")
@click.option("--target-words", type=int, default=100000, help="目标字数")
@click.option("--style", default="", help="风格预设名称")
@click.option("--template", default="", help="大纲模板名称")
@click.option("--silent", is_flag=True, help="静默模式（不暂停审核）")
@click.option("--workspace", "-w", type=click.Path(), default=None, help="工作目录")
def write_novel(genre: str, theme: str, target_words: int,
                style: str, template: str, silent: bool,
                workspace: str | None):
    """创建并生成小说"""
    try:
        from src.novel.pipeline import NovelPipeline

        pipe = NovelPipeline(workspace=workspace)

        console.print(f"\n[bold cyan]创建小说项目...[/]")
        console.print(f"  题材: {genre}")
        console.print(f"  主题: {theme}")
        console.print(f"  目标字数: {target_words:,}")

        result = pipe.create_novel(
            genre=genre,
            theme=theme,
            target_words=target_words,
            style=style,
            template=template,
        )

        novel_id = result["novel_id"]
        project_path = result["workspace"]
        total = result.get("total_chapters", 0)

        console.print(f"\n[green]项目创建成功: {project_path}[/]")
        console.print(f"  总章节数: {total}")
        console.print(f"  角色数: {len(result.get('characters', []))}")

        if result.get("errors"):
            for err in result["errors"]:
                console.print(f"  [yellow]警告: {err.get('message', '')}[/]")

        if total > 0:
            console.print(f"\n[bold cyan]开始生成章节...[/]")
            gen_result = pipe.generate_chapters(
                project_path, silent=silent
            )
            console.print(
                f"\n[bold green]生成完成: {gen_result['total_generated']} 章[/]"
            )
    except Exception as e:
        log.error("小说创建失败: %s", e)
        raise click.Abort()


@novel.command("resume")
@click.argument("project_path", type=click.Path(exists=True))
def resume_novel(project_path: str):
    """恢复小说创作"""
    try:
        from src.novel.pipeline import NovelPipeline

        pipe = NovelPipeline(workspace=str(Path(project_path).parent.parent))
        result = pipe.resume_novel(project_path)

        console.print(f"\n[bold green]恢复生成完成: {result.get('total_generated', 0)} 章[/]")
        if result.get("errors"):
            for err in result["errors"]:
                console.print(f"  [yellow]警告: {err.get('message', '')}[/]")
    except Exception as e:
        log.error("恢复失败: %s", e)
        raise click.Abort()


@novel.command("export")
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="输出文件路径")
def export_novel(project_path: str, output: str | None):
    """导出小说为文本文件"""
    try:
        from src.novel.pipeline import NovelPipeline

        pipe = NovelPipeline(workspace=str(Path(project_path).parent.parent))
        result = pipe.export_novel(project_path, output)

        console.print(f"\n[bold green]导出完成: {result}[/]")
    except Exception as e:
        log.error("导出失败: %s", e)
        raise click.Abort()


@novel.command("status")
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="显示详细信息（角色列表、世界观摘要、最近决策）")
def novel_status(project_path: str, verbose: bool):
    """查看小说项目状态"""
    try:
        from src.novel.pipeline import NovelPipeline

        pipe = NovelPipeline(workspace=str(Path(project_path).parent.parent))
        info = pipe.get_status(project_path)

        table = Table(title="小说项目状态")
        table.add_column("项目", style="cyan")
        table.add_column("值", style="green")

        table.add_row("小说 ID", info.get("novel_id", ""))
        table.add_row("标题", info.get("title", ""))
        table.add_row("状态", info.get("status", ""))
        table.add_row("当前章节", str(info.get("current_chapter", 0)))
        table.add_row("总章节数", str(info.get("total_chapters", 0)))
        table.add_row("已生成字数", f"{info.get('total_words', 0):,}")
        table.add_row("目标字数", f"{info.get('target_words', 0):,}")

        if "characters_count" in info:
            table.add_row("角色数", str(info["characters_count"]))
        if "has_world_setting" in info:
            table.add_row("世界观", "已创建" if info["has_world_setting"] else "未创建")
        if "errors_count" in info:
            table.add_row("错误数", str(info["errors_count"]))

        # Progress percentage
        total_ch = info.get("total_chapters", 0)
        current_ch = info.get("current_chapter", 0)
        if total_ch > 0:
            pct = current_ch / total_ch * 100
            table.add_row("完成度", f"{pct:.1f}%")

        console.print(table)

        # Verbose output: characters, world setting, decisions
        if verbose:
            import json as _json

            novel_json = Path(project_path) / "novel.json"
            if novel_json.exists():
                with open(novel_json, encoding="utf-8") as f:
                    novel_data = _json.load(f)

                # Character list
                characters = novel_data.get("characters", [])
                if characters:
                    ch_table = Table(title="角色列表")
                    ch_table.add_column("名字", style="cyan")
                    ch_table.add_column("角色", style="green")
                    ch_table.add_column("描述", style="dim")
                    for ch in characters[:10]:
                        name = ch.get("name", "?")
                        role = ch.get("role", ch.get("occupation", "?"))
                        desc = ch.get("description", ch.get("background", ""))
                        ch_table.add_row(name, str(role), str(desc)[:50])
                    console.print(ch_table)

                # World setting summary
                ws = novel_data.get("world_setting")
                if ws and isinstance(ws, dict):
                    ws_table = Table(title="世界观摘要")
                    ws_table.add_column("项目", style="cyan")
                    ws_table.add_column("值", style="green")
                    ws_table.add_row("时代", ws.get("era", "?"))
                    ws_table.add_row("地域", ws.get("location", "?"))
                    rules = ws.get("rules", [])
                    if rules:
                        ws_table.add_row("规则", "; ".join(str(r) for r in rules[:3]))
                    console.print(ws_table)

            # Recent decisions from checkpoint
            ckpt_path = Path(project_path) / "checkpoint.json"
            if ckpt_path.exists():
                with open(ckpt_path, encoding="utf-8") as f:
                    ckpt = _json.load(f)
                decisions = ckpt.get("decisions", [])
                if decisions:
                    dec_table = Table(title="最近决策")
                    dec_table.add_column("Agent", style="cyan")
                    dec_table.add_column("步骤", style="white")
                    dec_table.add_column("决策", style="green")
                    for d in decisions[-5:]:
                        dec_table.add_row(
                            d.get("agent", "?"),
                            d.get("step", "?"),
                            d.get("decision", "?"),
                        )
                    console.print(dec_table)
    except Exception as e:
        log.error("状态查询失败: %s", e)
        raise click.Abort()


@novel.command("list")
@click.option("--workspace", "-w", type=click.Path(), default=None, help="工作目录")
def list_novels(workspace: str | None):
    """列出所有小说项目"""
    try:
        ws = Path(workspace) if workspace else Path("workspace")
        novels_dir = ws / "novels"
        if not novels_dir.exists():
            console.print("[yellow]没有找到任何小说项目[/]")
            return

        import json

        projects: list[dict] = []
        for d in novels_dir.iterdir():
            if not d.is_dir():
                continue
            novel_json = d / "novel.json"
            if not novel_json.exists():
                continue
            try:
                with open(novel_json, encoding="utf-8") as f:
                    data = json.load(f)
                outline = data.get("outline", {})
                total_chapters = (
                    len(outline.get("chapters", []))
                    if isinstance(outline, dict)
                    else 0
                )
                projects.append({
                    "novel_id": data.get("novel_id", d.name),
                    "title": data.get("title", ""),
                    "status": data.get("status", "unknown"),
                    "current_chapter": data.get("current_chapter", 0),
                    "total_chapters": total_chapters,
                    "updated_at": data.get("updated_at", ""),
                    "target_words": data.get("target_words", 0),
                    "path": str(d),
                })
            except (json.JSONDecodeError, OSError):
                continue

        # Sort by updated_at descending (most recent first)
        projects.sort(key=lambda p: p.get("updated_at", ""), reverse=True)

        if not projects:
            console.print("[yellow]没有找到任何小说项目[/]")
            return

        table = Table(title="小说项目列表")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("标题", style="white")
        table.add_column("状态", style="green")
        table.add_column("进度", style="yellow")
        table.add_column("目标字数", style="dim")
        table.add_column("路径", style="dim")

        for p in projects:
            progress = f"{p['current_chapter']}/{p['total_chapters']}"
            table.add_row(
                p["novel_id"],
                p["title"][:30],
                p["status"],
                progress,
                f"{p['target_words']:,}",
                p["path"],
            )

        console.print(table)
        console.print(f"\n共 {len(projects)} 个项目")
    except Exception as e:
        log.error("列表查询失败: %s", e)
        raise click.Abort()


@novel.command("health")
@click.argument("project_path", type=click.Path(exists=True))
def novel_health(project_path: str):
    """显示小说项目健康度报告"""
    try:
        from src.novel.pipeline import NovelPipeline

        pipe = NovelPipeline(workspace=str(Path(project_path).parent.parent))
        result = pipe.get_health_report(project_path)

        report = result.get("report", "")
        if report:
            # Use plain print — report is pre-formatted Unicode text
            print(report)
        else:
            console.print("[yellow]健康度报告不可用[/]")
    except Exception as e:
        log.error("健康度报告失败: %s", e)
        raise click.Abort()


def _edit_result_field(result, key: str, default=None):
    """Safely read a field from an EditResult (dataclass) or dict-like result."""
    if result is None:
        return default
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


@novel.command("edit")
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--instruction", "-i", required=True, help="自然语言编辑指令")
@click.option("--effective-from", "-e", type=int, default=None,
              help="从第几章起生效（可选）")
@click.option("--dry-run", "-n", is_flag=True, help="预览模式，不实际修改")
def novel_edit(project_path: str, instruction: str,
               effective_from: int | None, dry_run: bool):
    """编辑小说设定（角色/世界观/大纲）"""
    try:
        from src.novel.services.edit_service import NovelEditService

        workspace = str(Path(project_path).parent.parent)
        svc = NovelEditService(workspace=workspace)
        result = svc.edit(
            project_path=project_path,
            instruction=instruction,
            effective_from_chapter=effective_from,
            dry_run=dry_run,
        )

        status = _edit_result_field(result, "status", "")
        change_id = _edit_result_field(result, "change_id", "")
        change_type = _edit_result_field(result, "change_type", "")
        entity_type = _edit_result_field(result, "entity_type", "")
        entity_id = _edit_result_field(result, "entity_id")
        effective_from_chapter = _edit_result_field(
            result, "effective_from_chapter"
        )
        reasoning = _edit_result_field(result, "reasoning", "")
        error = _edit_result_field(result, "error")
        impact_report = _edit_result_field(result, "impact_report")

        if status == "failed":
            console.print(f"\n[bold red]❌ 编辑失败[/]")
            if error:
                console.print(f"  错误: {error}")
            if change_id:
                console.print(f"  变更 ID: {change_id}")
            raise click.Abort()

        # Success / Preview
        if status == "preview" or dry_run:
            console.print(f"\n[bold yellow]🔍 PREVIEW (dry-run)[/]")
        else:
            console.print(f"\n[bold green]✅ 编辑成功[/]")

        table = Table(title="编辑结果")
        table.add_column("项目", style="cyan")
        table.add_column("值", style="green")

        table.add_row("变更 ID", str(change_id))
        table.add_row("状态", str(status))
        table.add_row("变更类型", str(change_type))
        table.add_row("实体类型", str(entity_type))
        if entity_id:
            table.add_row("实体 ID", str(entity_id))
        if effective_from_chapter is not None:
            table.add_row("生效章节", f"第 {effective_from_chapter} 章起")
        if reasoning:
            table.add_row("推理", str(reasoning)[:120])

        console.print(table)

        # Impact analysis (only shown if present)
        if impact_report:
            imp_table = Table(title="影响分析")
            imp_table.add_column("项目", style="cyan")
            imp_table.add_column("值", style="yellow")
            if isinstance(impact_report, dict):
                affected = impact_report.get("affected_chapters", [])
                if affected:
                    imp_table.add_row(
                        "受影响章节",
                        ", ".join(str(c) for c in affected[:20]),
                    )
                summary = impact_report.get("summary")
                if summary:
                    imp_table.add_row("摘要", str(summary)[:200])
                severity = impact_report.get("severity")
                if severity:
                    imp_table.add_row("风险等级", str(severity))
                conflicts = impact_report.get("conflicts", [])
                if conflicts:
                    imp_table.add_row(
                        "冲突",
                        "; ".join(str(c) for c in conflicts[:5]),
                    )
                warnings = impact_report.get("warnings", [])
                if warnings:
                    imp_table.add_row(
                        "警告",
                        "; ".join(str(w) for w in warnings[:5]),
                    )
            else:
                imp_table.add_row("详情", str(impact_report)[:200])
            console.print(imp_table)
    except click.Abort:
        raise
    except Exception as e:
        log.error("编辑失败: %s", e)
        raise click.Abort()


@novel.command("history")
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--limit", "-n", type=int, default=20, help="返回条数上限（默认 20）")
@click.option("--change-type", "-t", default=None,
              help="按变更类型过滤（如 add_character）")
def novel_history(project_path: str, limit: int,
                  change_type: str | None):
    """查询小说项目变更历史"""
    try:
        from src.novel.services.edit_service import NovelEditService

        workspace = str(Path(project_path).parent.parent)
        svc = NovelEditService(workspace=workspace)
        entries = svc.get_history(
            project_path=project_path, limit=limit, change_type=change_type
        )

        if not entries:
            console.print("[yellow]该项目暂无变更历史[/]")
            return

        table = Table(title="变更历史")
        table.add_column("时间", style="cyan", no_wrap=True)
        table.add_column("类型", style="green")
        table.add_column("实体", style="yellow")
        table.add_column("描述", style="white")
        table.add_column("作者", style="dim")

        for e in entries:
            ts = str(e.get("timestamp", ""))[:19]  # trim to second
            ctype = str(e.get("change_type", ""))
            etype = str(e.get("entity_type", ""))
            desc = e.get("description") or e.get("instruction") or ""
            author = str(e.get("author", ""))
            table.add_row(ts, ctype, etype, str(desc)[:60], author)

        console.print(table)
        console.print(f"\n共 {len(entries)} 条记录")
    except Exception as e:
        log.error("历史查询失败: %s", e)
        raise click.Abort()


@novel.command("rollback")
@click.argument("project_path", type=click.Path(exists=True))
@click.argument("change_id")
@click.option("--force", "-f", is_flag=True,
              help="忽略后续依赖变更强制回滚")
def novel_rollback(project_path: str, change_id: str, force: bool):
    """回滚指定变更 ID 的编辑操作"""
    try:
        from src.novel.services.edit_service import NovelEditService

        workspace = str(Path(project_path).parent.parent)
        svc = NovelEditService(workspace=workspace)
        result = svc.rollback(
            project_path=project_path,
            change_id=change_id,
            force=force,
        )

        status = _edit_result_field(result, "status", "")
        new_change_id = _edit_result_field(result, "change_id", "")
        entity_type = _edit_result_field(result, "entity_type", "")
        entity_id = _edit_result_field(result, "entity_id")
        error = _edit_result_field(result, "error")

        if status == "failed":
            console.print("\n[bold red]❌ 回滚失败[/]")
            if error:
                console.print(f"  错误: {error}")
            raise click.Abort()

        console.print("\n[bold green]✅ 回滚成功[/]")
        table = Table(title="回滚结果")
        table.add_column("项目", style="cyan")
        table.add_column("值", style="green")
        table.add_row("新变更 ID", str(new_change_id))
        table.add_row("被回滚的 ID", change_id)
        table.add_row("实体类型", str(entity_type))
        if entity_id:
            table.add_row("实体 ID", str(entity_id))
        console.print(table)
    except click.Abort:
        raise
    except Exception as e:
        log.error("回滚失败: %s", e)
        raise click.Abort()


# ---------------------------------------------------------------------------
# novel propose / accept / regenerate 三段式命令组 (Phase 4)
# ---------------------------------------------------------------------------


_OUTPUT_CHOICES = click.Choice(["json", "yaml", "table"])


def _novel_workspace_from_project(project_path: str) -> str:
    """Infer the workspace root from ``project_path``.

    Used by the propose/accept/regenerate subcommands so the facade points
    at the same workspace the user's project lives in. Mirrors the
    convention used by the existing ``novel edit`` / ``novel history``
    subcommands (``Path(project_path).parent.parent``).
    """
    return str(Path(project_path).parent.parent)


def _make_facade(workspace: str):
    """Import-and-instantiate helper.

    Kept as a thin wrapper so tests can ``patch`` the facade constructor
    at one well-known symbol.
    """
    from src.novel.services.tool_facade import NovelToolFacade

    return NovelToolFacade(workspace=workspace)


def _envelope_is_failed(payload: dict) -> bool:
    """Return True if the envelope dict looks like an error envelope.

    We treat either a populated ``errors`` list or a top-level ``error``
    key (for exception fallbacks) as a failure signal for --auto-accept.
    """
    if payload.get("error"):
        return True
    errs = payload.get("errors") or []
    return bool(errs)


def _load_proposal_file(path: str) -> dict:
    """Load a proposal JSON file previously captured via ``--output json``.

    Accepts either an envelope dict (``{proposal_id, data, ...}``) or a
    raw ``data`` dict (in which case the caller supplied ``--proposal-id``
    and ``--type`` separately).

    Raises ``click.UsageError`` if the file is not valid JSON or is not
    a JSON object (dict). Envelope-schema validation (``proposal_id`` /
    ``proposal_type`` present) is performed by the caller — raw ``data``
    files are allowed and have no such fields.
    """
    import json as _json

    try:
        with open(path, encoding="utf-8") as f:
            payload = _json.load(f)
    except _json.JSONDecodeError as exc:
        raise click.UsageError(
            f"proposal file 不是合法 JSON: {path} ({exc})"
        ) from exc
    except OSError as exc:
        raise click.UsageError(
            f"proposal file 读取失败: {path} ({exc})"
        ) from exc
    if not isinstance(payload, dict):
        raise click.UsageError(
            f"proposal file 必须是 JSON object (dict)，实际为 "
            f"{type(payload).__name__}: {path}"
        )
    return payload


@novel.group("propose")
def novel_propose_grp():
    """生成草案（三段式 propose）。不落盘；之后需 ``novel accept`` 确认。"""
    pass


def _run_propose(
    facade_method,
    facade_args: tuple,
    facade_kwargs: dict,
    *,
    project_path: str | None,
    proposal_type_for_accept: str,
    output: str,
    auto_accept: bool,
) -> None:
    """Shared implementation for every ``novel propose <sub>`` subcommand."""
    from src.novel.cli.render import render_accept_result, render_envelope

    envelope = facade_method(*facade_args, **facade_kwargs)
    payload = render_envelope(envelope, output=output, console=console)

    if not auto_accept:
        return

    if _envelope_is_failed(payload):
        if output == "table":
            console.print(
                "[yellow]检测到 errors/error，--auto-accept 已跳过 accept 步骤[/]"
            )
        return

    if project_path is None:
        # project_setup 立项 propose 暂不支持 --auto-accept（accept 需要
        # project_path，但立项时项目尚不存在）。
        if output == "table":
            console.print(
                "[yellow]project-setup 的 --auto-accept 需要项目路径，暂不支持[/]"
            )
        return

    workspace = _novel_workspace_from_project(project_path)
    facade = _make_facade(workspace)
    result = facade.accept_proposal(
        project_path,
        payload.get("proposal_id", ""),
        proposal_type_for_accept,
        payload.get("data") or {},
    )
    render_accept_result(result, output=output, console=console)


@novel_propose_grp.command("project-setup")
@click.argument("inspiration")
@click.option("--genre", default=None, help="题材提示（覆盖推断值）")
@click.option("--theme", default=None, help="主题提示")
@click.option("--target-words", type=int, default=None, help="目标字数提示")
@click.option("--style-name", default=None, help="风格预设 key，如 webnovel.shuangwen")
@click.option("--narrative-template", default=None, help="叙事模板名")
@click.option("--workspace", "-w", default="workspace", help="工作目录")
@click.option("--output", type=_OUTPUT_CHOICES, default="table")
def propose_project_setup_cmd(
    inspiration: str,
    genre: str | None,
    theme: str | None,
    target_words: int | None,
    style_name: str | None,
    narrative_template: str | None,
    workspace: str,
    output: str,
):
    """从灵感起草项目立项参数（不落盘）。"""
    try:
        hints = {
            k: v
            for k, v in {
                "genre": genre,
                "theme": theme,
                "target_words": target_words,
                "style_name": style_name,
                "narrative_template": narrative_template,
            }.items()
            if v is not None
        }
        facade = _make_facade(workspace)
        _run_propose(
            facade.propose_project_setup,
            (),
            {"inspiration": inspiration, "hints": hints or None},
            project_path=None,
            proposal_type_for_accept="project_setup",
            output=output,
            auto_accept=False,
        )
    except Exception as e:
        log.error("propose project-setup 失败: %s", e)
        raise click.Abort()


@novel_propose_grp.command("synopsis")
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--output", type=_OUTPUT_CHOICES, default="table")
@click.option("--auto-accept", is_flag=True, default=False, help="propose 后直接 accept")
def propose_synopsis_cmd(project_path: str, output: str, auto_accept: bool):
    """为项目起草故事梗概（不落盘）。"""
    try:
        workspace = _novel_workspace_from_project(project_path)
        facade = _make_facade(workspace)
        _run_propose(
            facade.propose_synopsis,
            (project_path,),
            {},
            project_path=project_path,
            proposal_type_for_accept="synopsis",
            output=output,
            auto_accept=auto_accept,
        )
    except Exception as e:
        log.error("propose synopsis 失败: %s", e)
        raise click.Abort()


@novel_propose_grp.command("main-outline")
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--custom-ideas", default=None, help="作者额外要求")
@click.option("--output", type=_OUTPUT_CHOICES, default="table")
@click.option("--auto-accept", is_flag=True, default=False)
def propose_main_outline_cmd(
    project_path: str,
    custom_ideas: str | None,
    output: str,
    auto_accept: bool,
):
    """起草三层主大纲（不落盘）。"""
    try:
        workspace = _novel_workspace_from_project(project_path)
        facade = _make_facade(workspace)
        _run_propose(
            facade.propose_main_outline,
            (project_path,),
            {"custom_ideas": custom_ideas},
            project_path=project_path,
            proposal_type_for_accept="main_outline",
            output=output,
            auto_accept=auto_accept,
        )
    except Exception as e:
        log.error("propose main-outline 失败: %s", e)
        raise click.Abort()


@novel_propose_grp.command("characters")
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--synopsis-file", type=click.Path(exists=True), default=None,
              help="从文件读取 synopsis 作为上下文")
@click.option("--synopsis", default=None, help="直接传 synopsis 字符串")
@click.option("--output", type=_OUTPUT_CHOICES, default="table")
@click.option("--auto-accept", is_flag=True, default=False)
def propose_characters_cmd(
    project_path: str,
    synopsis_file: str | None,
    synopsis: str | None,
    output: str,
    auto_accept: bool,
):
    """起草主要角色列表（不落盘）。"""
    try:
        if synopsis_file and not synopsis:
            synopsis = Path(synopsis_file).read_text(encoding="utf-8")
        workspace = _novel_workspace_from_project(project_path)
        facade = _make_facade(workspace)
        _run_propose(
            facade.propose_characters,
            (project_path,),
            {"synopsis": synopsis},
            project_path=project_path,
            proposal_type_for_accept="characters",
            output=output,
            auto_accept=auto_accept,
        )
    except Exception as e:
        log.error("propose characters 失败: %s", e)
        raise click.Abort()


@novel_propose_grp.command("world-setting")
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--synopsis-file", type=click.Path(exists=True), default=None)
@click.option("--synopsis", default=None)
@click.option("--output", type=_OUTPUT_CHOICES, default="table")
@click.option("--auto-accept", is_flag=True, default=False)
def propose_world_setting_cmd(
    project_path: str,
    synopsis_file: str | None,
    synopsis: str | None,
    output: str,
    auto_accept: bool,
):
    """起草世界观（不落盘）。"""
    try:
        if synopsis_file and not synopsis:
            synopsis = Path(synopsis_file).read_text(encoding="utf-8")
        workspace = _novel_workspace_from_project(project_path)
        facade = _make_facade(workspace)
        _run_propose(
            facade.propose_world_setting,
            (project_path,),
            {"synopsis": synopsis},
            project_path=project_path,
            proposal_type_for_accept="world_setting",
            output=output,
            auto_accept=auto_accept,
        )
    except Exception as e:
        log.error("propose world-setting 失败: %s", e)
        raise click.Abort()


@novel_propose_grp.command("story-arcs")
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--output", type=_OUTPUT_CHOICES, default="table")
@click.option("--auto-accept", is_flag=True, default=False)
def propose_story_arcs_cmd(project_path: str, output: str, auto_accept: bool):
    """起草跨卷故事弧线（不落盘）。"""
    try:
        workspace = _novel_workspace_from_project(project_path)
        facade = _make_facade(workspace)
        _run_propose(
            facade.propose_story_arcs,
            (project_path,),
            {},
            project_path=project_path,
            proposal_type_for_accept="story_arcs",
            output=output,
            auto_accept=auto_accept,
        )
    except Exception as e:
        log.error("propose story-arcs 失败: %s", e)
        raise click.Abort()


@novel_propose_grp.command("volume-breakdown")
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--synopsis", default=None)
@click.option("--output", type=_OUTPUT_CHOICES, default="table")
@click.option("--auto-accept", is_flag=True, default=False)
def propose_volume_breakdown_cmd(
    project_path: str,
    synopsis: str | None,
    output: str,
    auto_accept: bool,
):
    """起草全书卷骨架（不落盘）。"""
    try:
        workspace = _novel_workspace_from_project(project_path)
        facade = _make_facade(workspace)
        _run_propose(
            facade.propose_volume_breakdown,
            (project_path,),
            {"synopsis": synopsis},
            project_path=project_path,
            proposal_type_for_accept="volume_breakdown",
            output=output,
            auto_accept=auto_accept,
        )
    except Exception as e:
        log.error("propose volume-breakdown 失败: %s", e)
        raise click.Abort()


@novel_propose_grp.command("volume-outline")
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--volume", "volume_number", type=int, required=True, help="卷号（1 开始）")
@click.option("--output", type=_OUTPUT_CHOICES, default="table")
@click.option("--auto-accept", is_flag=True, default=False)
def propose_volume_outline_cmd(
    project_path: str,
    volume_number: int,
    output: str,
    auto_accept: bool,
):
    """起草单卷细纲（不落盘）。"""
    try:
        workspace = _novel_workspace_from_project(project_path)
        facade = _make_facade(workspace)
        _run_propose(
            facade.propose_volume_outline,
            (project_path, volume_number),
            {},
            project_path=project_path,
            proposal_type_for_accept="volume_outline",
            output=output,
            auto_accept=auto_accept,
        )
    except Exception as e:
        log.error("propose volume-outline 失败: %s", e)
        raise click.Abort()


@novel_propose_grp.command("chapter-brief")
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--chapter", "chapter_number", type=int, required=True,
              help="章节号（1 开始）")
@click.option("--output", type=_OUTPUT_CHOICES, default="table")
@click.option("--auto-accept", is_flag=True, default=False)
def propose_chapter_brief_cmd(
    project_path: str,
    chapter_number: int,
    output: str,
    auto_accept: bool,
):
    """起草单章 brief（不落盘）。"""
    try:
        workspace = _novel_workspace_from_project(project_path)
        facade = _make_facade(workspace)
        _run_propose(
            facade.propose_chapter_brief,
            (project_path, chapter_number),
            {},
            project_path=project_path,
            proposal_type_for_accept="chapter_brief",
            output=output,
            auto_accept=auto_accept,
        )
    except Exception as e:
        log.error("propose chapter-brief 失败: %s", e)
        raise click.Abort()


@novel.command("accept")
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--proposal-file", type=click.Path(exists=True), default=None,
              help="propose 输出（--output json）存下来的 envelope JSON 文件")
@click.option("--proposal-id", default=None, help="proposal_id（与 --proposal-file 二选一）")
@click.option("--type", "proposal_type", default=None,
              help="proposal_type（与 --proposal-id 成对使用）")
@click.option("--data-file", type=click.Path(exists=True), default=None,
              help="proposal 的 data 字段 JSON 文件")
@click.option("--output", type=_OUTPUT_CHOICES, default="table")
def novel_accept_cmd(
    project_path: str,
    proposal_file: str | None,
    proposal_id: str | None,
    proposal_type: str | None,
    data_file: str | None,
    output: str,
):
    """确认接受一个 propose 草案并写入 novel.json。"""
    try:
        from src.novel.cli.render import render_accept_result

        if proposal_file:
            envelope = _load_proposal_file(proposal_file)
            # envelope 必须携带 proposal_id + proposal_type（即使命令行也
            # 传了 --proposal-id/--type，envelope 是 source-of-truth；缺
            # 字段视为 schema 破损，直接拒绝而非静默回退）
            if "proposal_id" not in envelope or "proposal_type" not in envelope:
                raise click.UsageError(
                    "proposal file 缺少 proposal_id 或 proposal_type 字段"
                )
            pid = str(envelope.get("proposal_id") or "")
            ptype = str(envelope.get("proposal_type") or "")
            payload_data = envelope.get("data") or {}
            if not isinstance(payload_data, dict):
                raise click.UsageError(
                    "proposal file 的 data 字段必须是 JSON object"
                )
        elif proposal_id and proposal_type and data_file:
            pid = proposal_id
            ptype = proposal_type
            payload_data = _load_proposal_file(data_file)
        else:
            console.print(
                "[red]需要 --proposal-file 或 "
                "(--proposal-id + --type + --data-file)[/]"
            )
            raise click.Abort()

        if not pid or not ptype:
            raise click.UsageError("缺少 proposal_id 或 proposal_type")

        workspace = _novel_workspace_from_project(project_path)
        facade = _make_facade(workspace)
        result = facade.accept_proposal(project_path, pid, ptype, payload_data)
        render_accept_result(result, output=output, console=console)
    except (click.Abort, click.UsageError):
        # UsageError 负责自渲染（show()）；Abort 上层自处理。都不要吞。
        raise
    except Exception as e:
        log.error("accept 失败: %s", e)
        raise click.Abort()


@novel.command("regenerate")
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--section", required=True,
              help="synopsis/characters/world_setting/story_arcs/"
                   "volume_breakdown/main_outline/volume_outline")
@click.option("--hints", default="", help="作者提示——想改什么")
@click.option("--volume", "volume_number", type=int, default=None,
              help="卷号（仅 volume_outline 需要）")
@click.option("--output", type=_OUTPUT_CHOICES, default="table")
def novel_regenerate_cmd(
    project_path: str,
    section: str,
    hints: str,
    volume_number: int | None,
    output: str,
):
    """对已有草案重新生成（新 proposal_id，不落盘）。"""
    try:
        from src.novel.cli.render import render_envelope

        workspace = _novel_workspace_from_project(project_path)
        facade = _make_facade(workspace)
        envelope = facade.regenerate_section(
            project_path,
            section=section,
            hints=hints,
            volume_number=volume_number,
        )
        render_envelope(envelope, output=output, console=console)
    except Exception as e:
        log.error("regenerate 失败: %s", e)
        raise click.Abort()


# ---------------------------------------------------------------------------
# ppt 命令组 - AI PPT 生成
# ---------------------------------------------------------------------------


@cli.group()
def ppt():
    """AI PPT 生成工具"""
    pass


@ppt.command("create")
@click.argument("topic")
@click.option("--audience", "-a", default="business",
              type=click.Choice(["business", "technical", "educational", "creative", "general"]),
              help="目标受众")
@click.option("--scenario", "-s", default="quarterly_review",
              type=click.Choice([
                  "quarterly_review", "product_launch", "tech_share",
                  "course_lecture", "pitch_deck", "workshop", "status_update",
              ]),
              help="使用场景")
@click.option("--theme", "-t", default="modern", help="视觉主题")
@click.option("--target-pages", "-p", default=None, type=int, help="目标页数")
@click.option("--config", "config_path", default="config.yaml", help="配置文件路径")
def ppt_create(topic, audience, scenario, theme, target_pages, config_path):
    """从主题创建 PPT（V2：先生成大纲，审核后继续）。

    示例：python main.py ppt create "2024年度产品规划" --scenario quarterly_review
    """
    from src.config_manager import load_config
    from src.ppt.pipeline import PPTPipeline

    config = load_config(config_path)
    pipe = PPTPipeline(workspace="workspace", config=config)

    try:
        project_id, outline = pipe.generate_outline_only(
            topic=topic,
            audience=audience,
            scenario=scenario,
            theme=theme,
            target_pages=target_pages,
        )

        project_dir = f"workspace/ppt/{project_id}"
        yaml_path = f"{project_dir}/outline_editable.yaml"

        click.echo(f"\n✅ 大纲生成完成！")
        click.echo(f"   项目 ID: {project_id}")
        click.echo(f"   大纲文件: {yaml_path}")
        click.echo(f"   共 {outline.total_pages} 页 | 预计时长 {outline.estimated_duration}")
        click.echo(f"\n📝 请编辑大纲文件后运行：")
        click.echo(f"   python main.py ppt continue {project_dir}")

    except Exception as e:
        log.error("PPT 大纲生成失败: %s", e)
        raise click.ClickException(str(e))


@ppt.command("continue")
@click.argument("project_path")
@click.option("--no-images", is_flag=True, default=False, help="跳过配图生成")
@click.option("--config", "config_path", default="config.yaml", help="配置文件路径")
def ppt_continue(project_path, no_images, config_path):
    """从已审核的大纲继续生成 PPT。

    示例：python main.py ppt continue workspace/ppt/ppt_20240317_abc123
    """
    import yaml

    from src.config_manager import load_config
    from src.ppt.models import EditableOutline
    from src.ppt.pipeline import PPTPipeline

    config = load_config(config_path)
    pipe = PPTPipeline(workspace="workspace", config=config)

    # 加载编辑后的大纲
    project_dir = Path(project_path)
    yaml_path = project_dir / "outline_editable.yaml"

    if not yaml_path.exists():
        raise click.ClickException(f"找不到大纲文件: {yaml_path}")

    with open(yaml_path, encoding="utf-8") as f:
        outline_data = yaml.safe_load(f)

    edited_outline = EditableOutline(**outline_data)
    project_id = project_dir.name

    try:
        click.echo(f"🚀 从大纲继续生成 PPT（{edited_outline.total_pages} 页）...")

        pptx_path = pipe.continue_from_outline(
            project_id=project_id,
            edited_outline=edited_outline,
            generate_images=not no_images,
        )

        click.echo(f"\n✅ PPT 生成完成！")
        click.echo(f"   输出文件: {pptx_path}")

    except Exception as e:
        log.error("PPT 生成失败: %s", e)
        raise click.ClickException(str(e))


@ppt.command("generate")
@click.argument("input_file", type=click.Path(exists=True))
@click.option("--theme", "-t", default="modern",
              type=click.Choice(["modern", "business", "creative", "tech", "education"]),
              help="主题风格")
@click.option("--max-pages", "-p", type=int, default=None, help="最大页数")
@click.option("--no-images", is_flag=True, help="跳过配图生成（更快）")
@click.option("--output", "-o", type=click.Path(), default=None, help="输出文件路径")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None,
              help="配置文件路径")
@click.option("--deck-type",
              type=click.Choice(["auto", "business_report", "course_lecture", "product_intro"]),
              default="auto", help="PPT 类型（auto=自动检测）")
@click.option("--auto-continue/--no-auto-continue", default=True,
              help="自动继续（不暂停审核大纲）")
def ppt_generate(input_file: str, theme: str, max_pages: int | None,
                 no_images: bool, output: str | None, config_path: str | None,
                 deck_type: str, auto_continue: bool):
    """从文档生成 PPT"""
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

    try:
        text = Path(input_file).read_text(encoding="utf-8")
        if not text.strip():
            console.print("[red]输入文件为空[/]")
            raise click.Abort()

        config = {}
        if config_path:
            from src.config_manager import load_config
            config = load_config(Path(config_path))

        from src.ppt.pipeline import PPTPipeline

        pipeline = PPTPipeline(workspace="workspace", config=config)

        resolved_deck_type = None if deck_type == "auto" else deck_type

        console.print(f"\n[bold cyan]PPT 生成[/]")
        console.print(f"  输入: {input_file}")
        console.print(f"  主题: {theme}")
        console.print(f"  PPT 类型: {deck_type}")
        if max_pages:
            console.print(f"  最大页数: {max_pages}")
        console.print(f"  配图: {'是' if not no_images else '否'}")
        console.print(f"  自动继续: {'是' if auto_continue else '否'}")

        # --no-auto-continue: 仅生成大纲后暂停，让用户编辑
        if not auto_continue:
            try:
                project_id, outline = pipeline.generate_outline_only(
                    document_text=text,
                    theme=theme,
                    target_pages=max_pages,
                )

                project_dir = f"workspace/ppt/{project_id}"
                yaml_path = f"{project_dir}/outline_editable.yaml"

                click.echo(f"\n✅ 大纲生成完成！")
                click.echo(f"   项目 ID: {project_id}")
                click.echo(f"   大纲文件: {yaml_path}")
                click.echo(f"   共 {outline.total_pages} 页 | 预计时长 {outline.estimated_duration}")
                click.echo(f"\n📝 请编辑大纲文件后运行：")
                click.echo(f"   python main.py ppt continue {project_dir}")
            except Exception as e:
                log.error("PPT 大纲生成失败: %s", e)
                raise click.ClickException(str(e))
            return

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            task = progress.add_task("初始化...", total=100)

            def on_progress(stage: str, pct: float, msg: str):
                progress.update(task, completed=int(pct * 100), description=f"[cyan]{msg}")

            result = pipeline.generate(
                text=text,
                theme=theme,
                max_pages=max_pages,
                generate_images=not no_images,
                output_path=output,
                progress_callback=on_progress,
                deck_type=resolved_deck_type,
            )

        console.print(f"\n[bold green]PPT 生成完成: {result}[/]")
    except click.Abort:
        raise
    except click.ClickException:
        raise
    except Exception as e:
        log.error("PPT 生成失败: %s", e)
        raise click.Abort()


@ppt.command("resume")
@click.argument("project_path", type=click.Path(exists=True))
def ppt_resume(project_path: str):
    """断点续传 PPT 生成"""
    try:
        from src.ppt.pipeline import PPTPipeline

        pipeline = PPTPipeline(workspace="workspace")
        result = pipeline.resume(project_path=project_path)

        console.print(f"\n[bold green]PPT 续传完成: {result}[/]")
    except Exception as e:
        log.error("PPT 续传失败: %s", e)
        raise click.Abort()


@ppt.command("status")
@click.argument("project_path", type=click.Path(exists=True))
def ppt_status(project_path: str):
    """查看 PPT 项目状态"""
    try:
        from src.ppt.pipeline import PPTPipeline

        pipeline = PPTPipeline(workspace="workspace")
        info = pipeline.get_status(project_path=project_path)

        table = Table(title="PPT 项目状态")
        table.add_column("项目", style="cyan")
        table.add_column("值", style="green")

        for key, value in info.items():
            table.add_row(str(key), str(value))

        console.print(table)
    except Exception as e:
        log.error("PPT 状态查询失败: %s", e)
        raise click.Abort()


@ppt.command("themes")
def ppt_themes():
    """列出可用 PPT 主题"""
    try:
        from src.ppt.theme_manager import ThemeManager

        tm = ThemeManager()
        themes = tm.list_themes()

        table = Table(title="可用 PPT 主题")
        table.add_column("主题名称", style="cyan")

        for name in themes:
            table.add_row(name)

        console.print(table)
    except Exception as e:
        log.error("主题列表获取失败: %s", e)
        raise click.Abort()


@cli.command("create-video")
@click.argument("inspiration")
@click.option("--duration", "-d", default=45, help="目标视频时长(秒)")
@click.option("--budget", "-b", default="low", type=click.Choice(["free", "low", "medium", "high"]), help="预算档位")
@click.option("--config", "-c", "config_path", default=None, help="配置文件路径")
@click.option("--workspace", "-w", default=None, help="工作目录")
def create_video(inspiration, duration, budget, config_path, workspace):
    """从灵感一键生成短视频。

    INSPIRATION: 视频灵感/创意描述

    示例:
        python main.py create-video "凌晨三点外卖员接到一单送往废弃医院的外卖"
        python main.py create-video "一个人发现自己的影子会独立行动" -d 60 -b medium
    """
    from src.director_pipeline import DirectorPipeline
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

    console = Console()
    console.print(f"\n[bold blue]🎬 AI短视频导演[/bold blue]")
    console.print(f"灵感: {inspiration}")
    console.print(f"时长: {duration}s | 预算: {budget}\n")

    pipeline = DirectorPipeline(
        config_path=config_path,
        workspace=workspace,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("初始化...", total=100)

        def on_progress(pct: float, desc: str):
            progress.update(task, completed=int(pct * 100), description=desc)

        try:
            result = pipeline.run(
                inspiration=inspiration,
                target_duration=duration,
                budget=budget,
                progress_callback=on_progress,
            )

            console.print(f"\n[bold green]✅ 视频生成完成！[/bold green]")
            console.print(f"标题: {result['script'].get('title', '未命名')}")
            console.print(f"时长: {result['duration']:.1f}s")
            console.print(f"段数: {len(result['segments'])}")
            console.print(f"路径: {result['video_path']}")
            console.print(f"工作目录: {result['run_dir']}")

        except Exception as exc:
            console.print(f"\n[bold red]❌ 生成失败: {exc}[/bold red]")
            raise click.Abort()


@cli.command()
@click.option("--api-port", type=int, default=8000, help="后端 API 端口")
@click.option("--frontend-port", type=int, default=3000, help="前端端口")
@click.option("--no-frontend", is_flag=True, help="仅启动后端 API")
def serve(api_port: int, frontend_port: int, no_frontend: bool):
    """一键启动 Web 服务（后端 API + Next.js 前端）"""
    import os
    import signal
    import subprocess
    import sys
    import time

    project_root = Path(__file__).parent
    frontend_dir = project_root / "frontend"
    procs: list[subprocess.Popen] = []

    def _cleanup(sig=None, frame=None):
        console.print("\n[yellow]正在停止服务...[/yellow]")
        for p in procs:
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                p.kill()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    # Kill stale processes on target ports
    for port in ([api_port] if no_frontend else [api_port, frontend_port]):
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"], capture_output=True, text=True
            )
            if result.stdout.strip():
                for pid in result.stdout.strip().split("\n"):
                    os.kill(int(pid), signal.SIGTERM)
                time.sleep(0.5)
        except Exception:
            pass

    # Start backend API
    console.print(f"[bold blue]🚀 启动后端 API (port {api_port})...[/bold blue]")
    env = {**os.environ, "API_PORT": str(api_port)}
    api_proc = subprocess.Popen(
        [sys.executable, "-m", "src.api.app"],
        cwd=str(project_root),
        env=env,
    )
    procs.append(api_proc)

    # Start frontend
    if not no_frontend:
        if not frontend_dir.exists():
            console.print("[red]❌ frontend/ 目录不存在[/red]")
            _cleanup()

        node_modules = frontend_dir / "node_modules"
        if not node_modules.exists():
            console.print("[yellow]📦 安装前端依赖...[/yellow]")
            subprocess.run(["npm", "install"], cwd=str(frontend_dir), check=True)

        console.print(f"[bold blue]🚀 启动前端 (port {frontend_port})...[/bold blue]")
        fe_env = {**os.environ, "PORT": str(frontend_port)}
        fe_proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(frontend_dir),
            env=fe_env,
        )
        procs.append(fe_proc)

    time.sleep(2)

    console.print()
    console.print("[bold green]✅ 服务已启动[/bold green]")
    console.print(f"   后端 API:  http://localhost:{api_port}")
    if not no_frontend:
        console.print(f"   前端页面:  http://localhost:{frontend_port}")
    console.print("   按 Ctrl+C 停止所有服务")
    console.print()

    # Wait for any process to exit
    try:
        while True:
            for p in procs:
                ret = p.poll()
                if ret is not None:
                    console.print(f"[red]服务进程退出 (PID {p.pid}, code {ret})[/red]")
                    _cleanup()
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    cli()
