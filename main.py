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


if __name__ == "__main__":
    cli()
