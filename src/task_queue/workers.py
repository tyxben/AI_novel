"""Task workers — execute pipeline tasks in threads."""

import json
import os
import traceback
from pathlib import Path

from .models import TaskType, TaskStatus
from .db import TaskDB


class TaskCancelled(Exception):
    """Raised when a task is cancelled via progress callback."""


def run_task(task_id: str, task_type: TaskType, params: dict, db: TaskDB):
    """Execute a task. Called in a thread by the server."""
    keys = params.pop("_keys", {})
    injected = []
    for k, v in keys.items():
        if v:
            os.environ[k] = v
            injected.append(k)

    db.update_status(task_id, TaskStatus.running)

    def progress_cb(pct, msg=""):
        # Cooperative cancellation: check DB status
        task = db.get_task(task_id)
        if task and task.status == TaskStatus.cancelled:
            raise TaskCancelled("Task cancelled by user")
        db.update_progress(task_id, pct, msg)

    try:
        result = _dispatch(task_type, params, progress_cb)
        result_str = json.dumps(result, ensure_ascii=False, default=str) if result else ""
        db.update_progress(task_id, 1.0, "完成")
        db.update_status(task_id, TaskStatus.completed, result=result_str)
    except TaskCancelled:
        db.update_status(task_id, TaskStatus.cancelled)
    except Exception as e:
        error_msg = f"{e}\n\n{traceback.format_exc()}"
        db.update_status(task_id, TaskStatus.failed, error=error_msg)
    finally:
        for k in injected:
            os.environ.pop(k, None)


def _dispatch(task_type: TaskType, params: dict, progress_cb) -> dict:
    if task_type == TaskType.novel_create:
        return _run_novel_create(params, progress_cb)
    elif task_type == TaskType.novel_generate:
        return _run_novel_generate(params, progress_cb)
    elif task_type == TaskType.novel_polish:
        return _run_novel_polish(params, progress_cb)
    elif task_type == TaskType.novel_feedback:
        return _run_novel_feedback(params, progress_cb)
    elif task_type == TaskType.director_generate:
        return _run_director_generate(params, progress_cb)
    elif task_type == TaskType.video_generate:
        return _run_video_generate(params, progress_cb)
    elif task_type == TaskType.ppt_generate:
        return _run_ppt_generate(params, progress_cb)
    elif task_type == TaskType.ppt_outline:
        return _run_ppt_outline(params, progress_cb)
    elif task_type == TaskType.ppt_continue:
        return _run_ppt_continue(params, progress_cb)
    elif task_type == TaskType.ppt_render_html:
        return _run_ppt_render_html(params, progress_cb)
    elif task_type == TaskType.ppt_export:
        return _run_ppt_export(params, progress_cb)
    elif task_type == TaskType.novel_rewrite_affected:
        return _run_novel_rewrite_affected(params, progress_cb)
    elif task_type == TaskType.novel_resize:
        return _run_novel_resize(params, progress_cb)
    elif task_type == TaskType.novel_agent_chat:
        return _run_novel_agent_chat(params, progress_cb)
    else:
        raise ValueError(f"Unknown task type: {task_type}")


def _run_novel_create(params: dict, progress_cb) -> dict:
    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline(workspace=params.get("workspace", "workspace"))
    return pipe.create_novel(
        genre=params["genre"],
        theme=params["theme"],
        target_words=params.get("target_words", 100000),
        style=params.get("style", "webnovel.shuangwen"),
        template=params.get("template", "cyclic_upgrade"),
        custom_ideas=params.get("custom_ideas", ""),
        author_name=params.get("author_name", ""),
        target_audience=params.get("target_audience", "通用"),
        progress_callback=progress_cb,
    )


def _run_novel_generate(params: dict, progress_cb) -> dict:
    from src.novel.pipeline import NovelPipeline
    from src.novel.storage.file_manager import FileManager

    pipe = NovelPipeline(workspace=params.get("workspace", "workspace"))
    project_path = params["project_path"]

    # Auto-detect start chapter
    novel_id = Path(project_path).name
    fm = FileManager(pipe.workspace)
    completed = fm.list_chapters(novel_id)
    start_ch = params.get("start_chapter") or ((max(completed) + 1) if completed else 1)

    # Auto-detect end chapter from outline (or user-specified target)
    end_ch = params.get("end_chapter")
    if end_ch is None:
        ckpt = pipe._load_checkpoint(novel_id)
        if ckpt:
            outlined = len(ckpt.get("outline", {}).get("chapters", []))
            target_total = params.get("target_total")  # user override
            total = max(outlined, target_total) if target_total else outlined
            batch = params.get("batch_size", 20)
            end_ch = min(start_ch + batch - 1, total)

    return pipe.generate_chapters(
        project_path=project_path,
        start_chapter=start_ch,
        end_chapter=end_ch,
        silent=params.get("silent", False),
        progress_callback=progress_cb,
        react_mode=params.get("react_mode", False),
        budget_mode=params.get("budget_mode", False),
    )


def _run_novel_polish(params: dict, progress_cb=None) -> dict:
    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline(workspace=params.get("workspace", "workspace"))
    return pipe.polish_chapters(
        project_path=params["project_path"],
        start_chapter=params.get("start_chapter", 1),
        end_chapter=params.get("end_chapter"),
        progress_callback=progress_cb,
    )


def _run_novel_feedback(params: dict, progress_cb=None) -> dict:
    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline(workspace=params.get("workspace", "workspace"))
    return pipe.apply_feedback(
        project_path=params["project_path"],
        feedback_text=params["feedback_text"],
        chapter_number=params.get("chapter_number"),
        dry_run=params.get("dry_run", False),
        progress_callback=progress_cb,
        rewrite_instructions=params.get("rewrite_instructions"),
    )


def _run_novel_rewrite_affected(params: dict, progress_cb=None) -> dict:
    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline(workspace=params.get("workspace", "workspace"))
    return pipe.rewrite_affected_chapters(
        project_path=params["project_path"],
        impact=params["impact"],
        progress_callback=progress_cb,
    )


def _run_director_generate(params: dict, progress_cb) -> dict:
    from src.director_pipeline import DirectorPipeline

    config = params.get("config", {})
    pipeline = DirectorPipeline(config=config, workspace="workspace/videos")
    return pipeline.run(
        inspiration=params["inspiration"],
        target_duration=params.get("target_duration", 60),
        budget=params.get("budget", "low"),
        progress_callback=progress_cb,
    )


def _run_video_generate(params: dict, progress_cb) -> dict:
    input_file = Path(params["input_file"])
    config = params.get("config", {})
    run_mode = params.get("run_mode", "classic")

    if run_mode == "agent":
        from src.agent_pipeline import AgentPipeline

        _stage_map = {
            "segment": (0.0, 0.2),
            "prompt": (0.2, 0.4),
            "image": (0.4, 0.6),
            "tts": (0.6, 0.8),
            "video": (0.8, 1.0),
        }

        def progress_cb_agent(stage, total, desc):
            lo, hi = _stage_map.get(stage, (0.0, 1.0))
            pct = lo + (hi - lo) * 0.5
            progress_cb(pct, f"[{stage}] {desc}")

        pipe = AgentPipeline(
            input_file=input_file,
            config=config,
            resume=False,
            budget_mode=params.get("budget_mode", False),
            quality_threshold=params.get("quality_threshold"),
        )
        output = pipe.run(progress_callback=progress_cb_agent)
    else:
        from src.pipeline import Pipeline

        def progress_cb_classic(stage, total, desc):
            pct = stage / total if total else 0
            progress_cb(pct, f"[{stage}/{total}] {desc}")

        pipe = Pipeline(input_file=input_file, config=config, resume=False)
        output = pipe.run(progress_callback=progress_cb_classic)

    if isinstance(output, dict):
        return output
    return {"output": str(output)} if output else {}


def _run_ppt_generate(params: dict, progress_cb) -> dict:
    from src.ppt.pipeline import PPTPipeline

    pipeline = PPTPipeline(
        workspace=params.get("workspace", "workspace"),
        config=params.get("config", {}),
    )

    def ppt_progress(stage, progress, message):
        progress_cb(progress, message)

    deck_type = params.get("deck_type")
    output_path = pipeline.generate(
        text=params["text"],
        theme=params.get("theme", "modern"),
        max_pages=params.get("max_pages"),
        generate_images=params.get("generate_images", True),
        progress_callback=ppt_progress,
        deck_type=deck_type,
    )

    # Read outline, extraction, and quality report from checkpoint
    result = {"output_path": output_path}
    try:
        project_id = getattr(pipeline, "last_project_id", None)
        if project_id:
            ckpt = pipeline.file_manager.load_checkpoint(project_id)
            if ckpt:
                data = ckpt.get("data", ckpt)
                stages = data.get("stages", {})
                outline_data = stages.get("outline", {}).get("data", [])
                extraction_data = stages.get("extraction", {}).get("data")
                planning_data = stages.get("planning", {}).get("data")
                quality_data = data.get("quality_report", {})
                result["outline"] = outline_data
                result["extraction"] = extraction_data
                result["planning"] = planning_data
                result["quality_report"] = quality_data
                result["project_id"] = project_id
    except Exception:
        pass  # Non-critical: outline/extraction/quality are nice-to-have

    return result


def _run_ppt_outline(params: dict, progress_cb) -> dict:
    """Generate PPT outline only (V2 stage 1)."""
    from src.ppt.pipeline import PPTPipeline

    pipeline = PPTPipeline(
        workspace=params.get("workspace", "workspace"),
        config=params.get("config", {}),
    )

    def ppt_progress(stage, progress, message):
        progress_cb(progress, message)

    project_id, outline = pipeline.generate_outline_only(
        topic=params.get("topic"),
        document_text=params.get("document_text"),
        audience=params.get("audience", "business"),
        scenario=params.get("scenario", "quarterly_review"),
        theme=params.get("theme", "modern"),
        target_pages=params.get("target_pages"),
        progress_callback=ppt_progress,
    )

    return {
        "project_id": project_id,
        "outline": outline.model_dump(),
    }


def _run_ppt_continue(params: dict, progress_cb) -> dict:
    """Continue PPT generation from a user-edited outline."""
    from src.ppt.pipeline import PPTPipeline
    from src.ppt.models import EditableOutline

    pipeline = PPTPipeline(
        workspace=params.get("workspace", "workspace"),
        config=params.get("config", {}),
    )

    def ppt_progress(stage, progress, message):
        # Scale pipeline progress to 0-0.7
        progress_cb(progress * 0.7, message)

    edited_outline = EditableOutline(**params["edited_outline"])

    output_path = pipeline.continue_from_outline(
        project_id=params["project_id"],
        edited_outline=edited_outline,
        generate_images=params.get("generate_images", True),
        progress_callback=ppt_progress,
    )

    # After pipeline completes, also render HTML preview
    progress_cb(0.75, "渲染 HTML 预览...")
    html_path = None
    slides = []
    try:
        from src.ppt.html_renderer import HTMLRenderer
        from src.ppt.theme_manager import ThemeManager
        from src.ppt.models import SlideSpec, SlideContent, SlideDesign

        project_id = params["project_id"]
        ckpt = pipeline.file_manager.load_checkpoint(project_id)
        if ckpt:
            data = ckpt.get("data", ckpt)
            stages = data.get("stages", {})
            design_data = stages.get("design", {}).get("data", [])
            content_data = stages.get("content", {}).get("data", [])
            outline_data = stages.get("outline", {}).get("data", [])

            slides = []
            for i, design_d in enumerate(design_data):
                content_d = content_data[i] if i < len(content_data) else {}
                outline_d = outline_data[i] if i < len(outline_data) else {}
                slide = SlideSpec(
                    page_number=i + 1,
                    content=SlideContent(**content_d) if content_d else SlideContent(title=f"第 {i+1} 页"),
                    design=SlideDesign(**design_d),
                    needs_image=outline_d.get("needs_image", False),
                    image_path=outline_d.get("image_path"),
                )
                slides.append(slide)

            theme_name = params.get("theme", "modern")
            theme_mgr = ThemeManager()
            theme = theme_mgr.get_theme(theme_name)

            renderer = HTMLRenderer(theme)
            html_path = renderer.render(
                slides,
                output_path=str(pipeline.file_manager.get_html_path(project_id)),
            )
    except Exception:
        import logging
        logging.getLogger("ppt").warning("HTML preview rendering failed", exc_info=True)
        html_path = None

    progress_cb(1.0, "PPT 生成完成！")

    # Build result
    result = {"output_path": output_path, "project_id": params["project_id"]}
    if html_path:
        result["html_path"] = html_path
        result["total_pages"] = len(slides) if slides else 0

    # Read outline/quality from checkpoint (existing logic)
    try:
        ckpt = pipeline.file_manager.load_checkpoint(params["project_id"])
        if ckpt:
            data = ckpt.get("data", ckpt)
            stages = data.get("stages", {})
            outline_data = stages.get("outline", {}).get("data", [])
            planning_data = stages.get("planning", {}).get("data")
            quality_data = data.get("quality_report", {})
            result["outline"] = outline_data
            result["planning"] = planning_data
            result["quality_report"] = quality_data
    except Exception:
        pass

    return result


def _run_ppt_render_html(params: dict, progress_cb) -> dict:
    """Render HTML preview from existing checkpoint data."""
    from src.ppt.html_renderer import HTMLRenderer
    from src.ppt.pipeline import PPTPipeline
    from src.ppt.theme_manager import ThemeManager
    from src.ppt.models import SlideSpec, SlideContent, SlideDesign

    pipeline = PPTPipeline(
        workspace=params.get("workspace", "workspace"),
        config=params.get("config", {}),
    )

    project_id = params["project_id"]
    theme_name = params.get("theme", "modern")

    progress_cb(0.1, "加载项目数据...")

    # Load checkpoint
    ckpt = pipeline.file_manager.load_checkpoint(project_id)
    if not ckpt:
        raise ValueError(f"项目 {project_id} checkpoint 不存在")

    data = ckpt.get("data", ckpt)
    stages = data.get("stages", {})

    # Rebuild SlideSpec list from checkpoint stages
    slides = []
    design_data = stages.get("design", {}).get("data", [])
    content_data = stages.get("content", {}).get("data", [])
    outline_data = stages.get("outline", {}).get("data", [])

    for i, design_d in enumerate(design_data):
        content_d = content_data[i] if i < len(content_data) else {}
        outline_d = outline_data[i] if i < len(outline_data) else {}

        slide = SlideSpec(
            page_number=i + 1,
            content=SlideContent(**content_d) if content_d else SlideContent(title=f"第 {i+1} 页"),
            design=SlideDesign(**design_d),
            needs_image=outline_d.get("needs_image", False),
            image_path=outline_d.get("image_path"),
        )
        slides.append(slide)

    progress_cb(0.3, "加载主题...")
    theme_mgr = ThemeManager()
    theme = theme_mgr.get_theme(theme_name)

    progress_cb(0.5, "渲染 HTML...")
    renderer = HTMLRenderer(theme)
    html_path = renderer.render(
        slides,
        output_path=str(pipeline.file_manager.get_html_path(project_id)),
    )

    progress_cb(1.0, "HTML 预览生成完成")
    return {
        "html_path": html_path,
        "project_id": project_id,
        "total_pages": len(slides),
    }


def _run_ppt_export(params: dict, progress_cb) -> dict:
    """Export HTML slides to PPTX."""
    from src.ppt.html_to_pptx import HTMLToPPTXConverter
    from src.ppt.file_manager import FileManager

    project_id = params["project_id"]
    html_path = params["html_path"]
    workspace = params.get("workspace", "workspace")

    fm = FileManager(workspace)

    # Security: validate html_path is within the project directory
    expected_dir = str(fm._project_dir(project_id).resolve())
    actual_path = str(Path(html_path).resolve())
    if not actual_path.startswith(expected_dir):
        raise ValueError(
            f"html_path must be within project directory: {expected_dir}"
        )

    output_path = str(fm.get_output_path(project_id))

    progress_cb(0.05, "初始化转换器...")

    def ppt_progress(page_num, total, message):
        # Map page progress to 0.1-0.95 range
        pct = 0.1 + (page_num / total) * 0.85 if total > 0 else 0.5
        progress_cb(pct, message)

    converter = HTMLToPPTXConverter(
        workspace=workspace,
        extract_text=params.get("extract_text", True),
    )

    result_path = converter.convert(
        html_path=html_path,
        output_path=output_path,
        progress_callback=ppt_progress,
    )

    progress_cb(1.0, "PPTX 导出完成")
    return {"output_path": result_path, "project_id": project_id}


def _run_novel_resize(params: dict, progress_cb) -> dict:
    """Resize novel outline (expand chapters via LLM)."""
    from src.novel.pipeline import NovelPipeline

    workspace = params["workspace"]
    project_path = params["project_path"]
    new_total = params["new_total"]

    progress_cb(0.05, f"正在调整章节数至 {new_total}...")

    pipe = NovelPipeline(workspace=workspace)
    result = pipe.resize_novel(project_path, new_total, progress_callback=progress_cb)

    progress_cb(1.0, f"章节数调整完成: {result['old_total']} → {result['new_total']}")
    return result


def _run_novel_agent_chat(params: dict, progress_cb) -> dict:
    """Agent chat — autonomous tool-calling agent that interprets user intent
    and executes multi-step operations on the novel."""
    from src.novel.services.agent_chat import run_agent_chat

    workspace = params["workspace"]
    project_path = params["project_path"]
    message = params["message"]
    context_chapters = params.get("context_chapters")
    history = params.get("history")
    novel_id = Path(project_path).name

    progress_cb(0.05, "启动 Agent...")

    result = run_agent_chat(
        workspace=workspace,
        novel_id=novel_id,
        message=message,
        context_chapters=context_chapters,
        history=history,
        progress_callback=progress_cb,
    )

    progress_cb(1.0, "Agent 完成")
    return result
