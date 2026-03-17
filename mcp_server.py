"""MCP Server for AI Novel/Video pipelines — FastMCP (streamable-http + stdio)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

log = logging.getLogger("novel.mcp")

mcp = FastMCP("AI Creative Workshop")

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


# ===========================================================================
# PPT pipeline tools
# ===========================================================================

_ppt_pipeline_instance = None


def _get_ppt_pipeline():
    """Return a lazily-initialized PPTPipeline singleton."""
    global _ppt_pipeline_instance
    if _ppt_pipeline_instance is None:
        from src.ppt.pipeline import PPTPipeline

        _ppt_pipeline_instance = PPTPipeline(workspace=_DEFAULT_WORKSPACE)
    return _ppt_pipeline_instance


@mcp.tool()
def ppt_generate(
    text: str,
    theme: str = "modern",
    max_pages: int = 0,
    generate_images: bool = True,
    auto_continue: bool = True,
) -> dict[str, Any]:
    """Generate a PPT presentation from text.

    When auto_continue=True (default), generates the PPT in one step.
    When auto_continue=False, returns an editable outline first — call
    ppt_confirm_outline() to finish generation.

    Args:
        text: Input document text (plain text or Markdown).
        theme: Theme style — "modern", "business", "creative", "tech",
            "education" (default "modern").
        max_pages: Maximum number of pages, 0 means auto (default 0).
        generate_images: Whether to generate AI images (default True).
        auto_continue: If True, generate PPT in one step; if False, return
            an editable outline for review first (default True).

    Returns:
        Dict with output file path and generation info, or an editable
        outline when auto_continue=False.
    """
    try:
        if not text or not text.strip():
            return {"error": "输入文本不能为空"}

        # Two-step mode: generate outline only, then confirm later
        if not auto_continue:
            from src.config_manager import load_config
            from src.ppt.pipeline import PPTPipeline

            config = load_config("config.yaml")
            pipe = PPTPipeline(workspace=_DEFAULT_WORKSPACE, config=config)

            project_id, editable_outline = pipe.generate_outline_only(
                document_text=text,
                theme=theme,
                target_pages=max_pages if max_pages > 0 else None,
            )

            return {
                "project_id": project_id,
                "status": "outline_ready",
                "outline": editable_outline.model_dump(),
                "next_step": "Call ppt_confirm_outline() to generate the PPT",
            }

        # One-step mode (default): generate PPT directly
        pipe = _get_ppt_pipeline()
        max_p = max_pages if max_pages > 0 else None
        output_path = pipe.generate(
            text=text,
            theme=theme,
            max_pages=max_p,
            generate_images=generate_images,
        )
        return {"output_path": str(output_path), "status": "success"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def ppt_get_status(project_path: str) -> dict[str, Any]:
    """Get the status of a PPT generation project.

    Args:
        project_path: Path to the PPT project directory.

    Returns:
        Project status information.
    """
    try:
        pipe = _get_ppt_pipeline()
        return pipe.get_status(project_path=project_path)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def ppt_list_themes() -> dict[str, Any]:
    """List available PPT themes.

    Returns:
        Dict with list of available theme names.
    """
    try:
        from src.ppt.theme_manager import ThemeManager

        tm = ThemeManager()
        themes = tm.list_themes()
        return {"themes": themes}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def ppt_create_from_topic(
    topic: str,
    audience: str = "business",
    scenario: str = "quarterly_review",
    theme: str = "modern",
    target_pages: int = 15,
) -> dict[str, Any]:
    """Create PPT outline from topic (step 1 of 2-step generation).

    Generates a PPT outline based on topic, audience, and scenario.
    Returns an editable outline that can be modified before generating the final PPT.
    Use ppt_confirm_outline() to continue after reviewing/editing the outline.

    Available scenarios: quarterly_review, product_launch, tech_share,
    course_lecture, pitch_deck, workshop, status_update

    Args:
        topic: PPT topic/title (e.g. "2024 Q1 Product Review").
        audience: Target audience — business/technical/educational/creative/general
            (default "business").
        scenario: Use case scenario (default "quarterly_review").
        theme: Visual theme — modern/business/creative/tech/education
            (default "modern").
        target_pages: Target number of pages, 5-50 (default 15).

    Returns:
        Dict with project_id, editable outline, and next-step instructions.
    """
    try:
        from src.config_manager import load_config
        from src.ppt.pipeline import PPTPipeline

        config = load_config("config.yaml")
        pipe = PPTPipeline(workspace=_DEFAULT_WORKSPACE, config=config)

        project_id, editable_outline = pipe.generate_outline_only(
            topic=topic,
            audience=audience,
            scenario=scenario,
            theme=theme,
            target_pages=target_pages,
        )

        return {
            "project_id": project_id,
            "status": "outline_ready",
            "total_pages": editable_outline.total_pages,
            "estimated_duration": editable_outline.estimated_duration,
            "outline": editable_outline.model_dump(),
            "next_step": "Review the outline and call ppt_confirm_outline() to generate the PPT",
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def ppt_confirm_outline(
    project_id: str,
    edited_outline: dict | None = None,
    generate_images: bool = True,
) -> dict[str, Any]:
    """Confirm outline and generate PPT (step 2 of 2-step generation).

    After reviewing the outline from ppt_create_from_topic() or
    ppt_generate(auto_continue=False), call this to generate the final PPT.
    You can pass a modified outline or use the original.

    Args:
        project_id: Project ID from ppt_create_from_topic() or ppt_generate().
        edited_outline: Modified outline dict (optional, uses original if None).
        generate_images: Whether to generate AI images for slides (default True).

    Returns:
        Dict with project_id, output file path, and status.
    """
    try:
        from src.config_manager import load_config
        from src.ppt.models import EditableOutline
        from src.ppt.pipeline import PPTPipeline

        config = load_config("config.yaml")
        pipe = PPTPipeline(workspace=_DEFAULT_WORKSPACE, config=config)

        # Load outline
        if edited_outline is not None:
            outline = EditableOutline(**edited_outline)
        else:
            # Load original outline from checkpoint
            import yaml

            yaml_path = Path(_DEFAULT_WORKSPACE) / "ppt" / project_id / "outline_editable.yaml"
            if not yaml_path.exists():
                return {"error": f"找不到大纲文件: {yaml_path}", "status": "failed"}
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            outline = EditableOutline(**data)

        pptx_path = pipe.continue_from_outline(
            project_id=project_id,
            edited_outline=outline,
            generate_images=generate_images,
        )

        return {
            "project_id": project_id,
            "status": "completed",
            "output_path": str(pptx_path),
            "message": f"PPT generated: {pptx_path}",
        }
    except Exception as e:
        return {"error": str(e)}


# ===========================================================================
# Video pipeline tools
# ===========================================================================


@mcp.tool()
def video_generate(
    input_file: str,
    style: str = "anime",
    voice: str = "zh-CN-YunxiNeural",
    rate: str = "+0%",
    mode: str = "classic",
    resume: bool = False,
) -> dict[str, Any]:
    """Generate a short video from a novel/story text file.

    Runs the full pipeline: text segmentation → prompt generation →
    image generation → TTS voiceover → FFmpeg video assembly.

    Args:
        input_file: Path to the input text file (e.g. "input/novel.txt").
        style: Image style — "anime", "realistic", "watercolor",
            "chinese_ink", "cyberpunk" (default "anime").
        voice: TTS voice name (default "zh-CN-YunxiNeural").
        rate: Speech rate like "+0%", "+20%", "-20%" (default "+0%").
        mode: Pipeline mode — "classic" or "agent" (default "classic").
        resume: Whether to resume from checkpoint (default False).

    Returns:
        Dict with output video path and stage info.
    """
    try:
        input_path = Path(input_file)
        if not input_path.exists():
            return {"error": f"输入文件不存在: {input_file}"}

        config_overrides: dict[str, Any] = {}
        if style:
            config_overrides.setdefault("promptgen", {})["style"] = style
        if voice:
            config_overrides.setdefault("tts", {})["voice"] = voice
        if rate:
            config_overrides.setdefault("tts", {})["rate"] = rate

        if mode == "agent":
            from src.agent_pipeline import AgentPipeline

            pipe = AgentPipeline(
                input_file=input_path,
                resume=resume,
            )
        else:
            from src.pipeline import Pipeline

            pipe = Pipeline(
                input_file=input_path,
                resume=resume,
                config=config_overrides if config_overrides else None,
            )

        output = pipe.run()
        return {"output_path": str(output), "status": "success"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def video_segment(
    input_file: str,
    method: str = "llm",
) -> dict[str, Any]:
    """Segment a text file into scenes/paragraphs for video production.

    Args:
        input_file: Path to the input text file.
        method: Segmentation method — "simple" (rule-based) or "llm"
            (AI-powered, default).

    Returns:
        Dict with segment count and segment texts.
    """
    try:
        from src.config_manager import load_config
        from src.segmenter.text_segmenter import create_segmenter

        input_path = Path(input_file)
        if not input_path.exists():
            return {"error": f"输入文件不存在: {input_file}"}

        cfg = load_config()
        cfg["segmenter"]["method"] = method
        # Merge global llm config
        global_llm = cfg.get("llm", {})
        module_llm = cfg["segmenter"].get("llm", {})
        cfg["segmenter"]["llm"] = {**global_llm, **module_llm}

        text = input_path.read_text(encoding="utf-8")
        segmenter = create_segmenter(cfg["segmenter"])
        segments = segmenter.segment(text)

        return {
            "count": len(segments),
            "segments": [
                {"index": i, "text": seg["text"][:200] + ("..." if len(seg["text"]) > 200 else "")}
                for i, seg in enumerate(segments)
            ],
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def video_status(workspace_dir: str) -> dict[str, Any]:
    """Check the progress of a video generation project.

    Args:
        workspace_dir: Path to the workspace directory
            (e.g. "workspace/novel").

    Returns:
        Dict with stage completion status and segment count.
    """
    try:
        from src.checkpoint import Checkpoint

        ws = Path(workspace_dir)
        if not ws.exists():
            return {"error": f"工作目录不存在: {workspace_dir}"}

        ckpt = Checkpoint(ws)
        data = ckpt.data

        stages = {}
        for key in ["segment", "prompt", "image", "tts", "video"]:
            info = data.get("stages", {}).get(key, {})
            stages[key] = info.get("done", False)

        return {
            "workspace": workspace_dir,
            "stages": stages,
            "segment_count": len(data.get("segments", [])),
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def video_list_projects() -> list[dict[str, Any]]:
    """List all video projects in the workspace.

    Scans workspace/ for directories with checkpoint.json (excluding novels/).

    Returns:
        List of video project summaries.
    """
    try:
        ws = Path(_DEFAULT_WORKSPACE)
        if not ws.exists():
            return []

        projects: list[dict[str, Any]] = []
        for d in sorted(ws.iterdir()):
            if not d.is_dir() or d.name == "novels":
                continue
            ckpt_file = d / "checkpoint.json"
            if not ckpt_file.exists():
                continue
            try:
                with open(ckpt_file, encoding="utf-8") as f:
                    data = json.load(f)
                stages = data.get("stages", {})
                done_stages = [k for k, v in stages.items() if v.get("done")]
                projects.append({
                    "project": d.name,
                    "path": str(d),
                    "done_stages": done_stages,
                    "segment_count": len(data.get("segments", [])),
                    "completed": stages.get("video", {}).get("done", False),
                })
            except (json.JSONDecodeError, OSError):
                projects.append({"project": d.name, "path": str(d), "error": "无法读取检查点"})
        return projects
    except Exception as e:
        return [{"error": str(e)}]


# ---------------------------------------------------------------------------
# Entry point — supports both stdio and streamable-http
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    transport = "stdio"
    for arg in sys.argv[1:]:
        if arg in ("--http", "--streamable-http", "http"):
            transport = "streamable-http"
            break
        if arg in ("--sse", "sse"):
            transport = "sse"
            break

    if transport == "streamable-http":
        mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
    elif transport == "sse":
        mcp.run(transport="sse", host="0.0.0.0", port=8000)
    else:
        mcp.run(transport="stdio")
