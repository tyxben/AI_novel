"""MCP Server for AI Novel Writing - exposes novel pipeline tools via FastMCP (stdio)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

log = logging.getLogger("novel.mcp")

mcp = FastMCP("AI Novel Writing")

# ---------------------------------------------------------------------------
# Lazy singleton for NovelPipeline
# ---------------------------------------------------------------------------

_pipeline_instance = None
_DEFAULT_WORKSPACE = "workspace"


def _get_pipeline():
    """Return a lazily-initialized NovelPipeline singleton."""
    global _pipeline_instance
    if _pipeline_instance is None:
        from src.novel.pipeline import NovelPipeline

        _pipeline_instance = NovelPipeline(workspace=_DEFAULT_WORKSPACE)
    return _pipeline_instance


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def novel_list_projects() -> list[dict[str, Any]]:
    """List all novel projects in the workspace.

    Scans workspace/novels/ for directories containing novel.json.

    Returns:
        List of project summaries with novel_id, title, status,
        current_chapter, and total_chapters.
    """
    try:
        novels_dir = Path(_DEFAULT_WORKSPACE) / "novels"
        if not novels_dir.exists():
            return []

        projects: list[dict[str, Any]] = []
        for d in sorted(novels_dir.iterdir()):
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
                projects.append(
                    {
                        "novel_id": data.get("novel_id", d.name),
                        "title": data.get("title", ""),
                        "status": data.get("status", "unknown"),
                        "current_chapter": data.get("current_chapter", 0),
                        "total_chapters": total_chapters,
                    }
                )
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("跳过无效项目目录 %s: %s", d.name, exc)
        return projects
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
def novel_create(
    genre: str,
    theme: str,
    target_words: int = 100000,
    style: str = "",
    template: str = "",
    custom_ideas: str = "",
    author_name: str = "",
    target_audience: str = "",
) -> dict[str, Any]:
    """Create a new novel project with outline, world-building, and characters.

    Args:
        genre: Novel genre (e.g. "玄幻", "都市", "科幻").
        theme: Core theme or premise of the novel.
        target_words: Target total word count (default 100000).
        style: Style preset key (e.g. "webnovel.shuangwen").
        template: Outline template name.
        custom_ideas: Additional creative ideas or references.
        author_name: Author pen name.
        target_audience: Target reader demographic.

    Returns:
        Project info dict with novel_id, workspace path, outline, characters, etc.
    """
    try:
        pipe = _get_pipeline()
        return pipe.create_novel(
            genre=genre,
            theme=theme,
            target_words=target_words,
            style=style,
            template=template,
            custom_ideas=custom_ideas,
            author_name=author_name,
            target_audience=target_audience,
        )
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def novel_generate_chapters(
    project_path: str,
    batch_size: int = 5,
) -> dict[str, Any]:
    """Generate chapters in batch for an existing novel project.

    Automatically detects the next unwritten chapter and generates up to
    batch_size chapters from that point.

    Args:
        project_path: Path to the novel project directory
            (e.g. "workspace/novels/novel_abc12345").
        batch_size: Number of chapters to generate in this batch (default 5).

    Returns:
        Generation summary with chapters_generated list and error info.
    """
    try:
        pipe = _get_pipeline()
        fm = pipe._get_file_manager()
        novel_id = Path(project_path).name

        # Determine start chapter from existing chapters
        completed = fm.list_chapters(novel_id)
        start_chapter = max(completed) + 1 if completed else 1

        # Determine total chapters from outline
        novel_data = fm.load_novel(novel_id)
        if novel_data is None:
            return {"error": f"项目不存在: {project_path}"}

        outline = novel_data.get("outline", {})
        total_chapters = (
            len(outline.get("chapters", []))
            if isinstance(outline, dict)
            else 0
        )

        if start_chapter > total_chapters:
            return {
                "novel_id": novel_id,
                "message": "所有章节已生成完成",
                "chapters_generated": [],
                "total_generated": 0,
            }

        end_chapter = min(start_chapter + batch_size - 1, total_chapters)

        return pipe.generate_chapters(
            project_path=project_path,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            silent=True,
        )
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def novel_get_status(project_path: str) -> dict[str, Any]:
    """Get detailed status of a novel project.

    Args:
        project_path: Path to the novel project directory.

    Returns:
        Status dict with title, current/total chapters, word counts, etc.
    """
    try:
        pipe = _get_pipeline()
        return pipe.get_status(project_path)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def novel_read_chapter(
    project_path: str,
    chapter_number: int,
) -> dict[str, Any]:
    """Read a specific chapter's text and metadata.

    Args:
        project_path: Path to the novel project directory.
        chapter_number: The chapter number to read (1-based).

    Returns:
        Dict with chapter_number, title, text, and word_count.
    """
    try:
        pipe = _get_pipeline()
        fm = pipe._get_file_manager()
        novel_id = Path(project_path).name

        text = fm.load_chapter_text(novel_id, chapter_number)
        metadata = fm.load_chapter(novel_id, chapter_number)

        if text is None and metadata is None:
            return {"error": f"第{chapter_number}章不存在"}

        result: dict[str, Any] = {
            "chapter_number": chapter_number,
            "title": metadata.get("title", f"第{chapter_number}章") if metadata else f"第{chapter_number}章",
            "text": text or metadata.get("full_text", "") if metadata else (text or ""),
            "word_count": len(text) if text else (metadata.get("word_count", 0) if metadata else 0),
        }
        if metadata:
            result["status"] = metadata.get("status", "unknown")
        return result
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def novel_apply_feedback(
    project_path: str,
    feedback_text: str,
    chapter_number: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply reader feedback to rewrite affected chapters.

    Analyzes the feedback, identifies affected chapters, and optionally
    rewrites them. Use dry_run=True to preview the analysis without changes.

    Args:
        project_path: Path to the novel project directory.
        feedback_text: The reader feedback or revision instruction.
        chapter_number: Specific chapter the feedback targets (None for global).
        dry_run: If True, only analyze without rewriting (default False).

    Returns:
        Dict with analysis results and list of rewritten chapters.
    """
    try:
        pipe = _get_pipeline()
        return pipe.apply_feedback(
            project_path=project_path,
            feedback_text=feedback_text,
            chapter_number=chapter_number,
            dry_run=dry_run,
        )
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def novel_export(project_path: str) -> dict[str, Any]:
    """Export the complete novel as a single TXT file.

    Args:
        project_path: Path to the novel project directory.

    Returns:
        Dict with the output file path.
    """
    try:
        pipe = _get_pipeline()
        output_path = pipe.export_novel(project_path)
        return {"output_path": output_path}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
