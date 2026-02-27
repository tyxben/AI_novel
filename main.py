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
def run(input_file: str, config: str | None, output: str | None,
        workspace: str | None, resume: bool):
    """全流程: 小说 → 短视频"""
    from src.pipeline import Pipeline

    try:
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
def status(workspace_dir: str):
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


if __name__ == "__main__":
    cli()
