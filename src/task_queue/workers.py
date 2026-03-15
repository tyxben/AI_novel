"""Task workers — execute pipeline tasks in threads."""

import json
import os
import traceback
from pathlib import Path

from .models import TaskType, TaskStatus
from .db import TaskDB


def run_task(task_id: str, task_type: TaskType, params: dict, db: TaskDB):
    """Execute a task. Called in a thread by the server."""
    keys = params.pop("_keys", {})
    for k, v in keys.items():
        if v:
            os.environ[k] = v

    db.update_status(task_id, TaskStatus.running)

    def progress_cb(pct, msg=""):
        db.update_progress(task_id, pct, msg)

    try:
        result = _dispatch(task_type, params, progress_cb)
        result_str = json.dumps(result, ensure_ascii=False, default=str) if result else ""
        db.update_status(task_id, TaskStatus.completed, result=result_str)
    except Exception as e:
        error_msg = f"{e}\n\n{traceback.format_exc()}"
        db.update_status(task_id, TaskStatus.failed, error=error_msg)


def _dispatch(task_type: TaskType, params: dict, progress_cb) -> dict:
    if task_type == TaskType.novel_create:
        return _run_novel_create(params, progress_cb)
    elif task_type == TaskType.novel_generate:
        return _run_novel_generate(params, progress_cb)
    elif task_type == TaskType.novel_polish:
        return _run_novel_polish(params)
    elif task_type == TaskType.novel_feedback:
        return _run_novel_feedback(params)
    elif task_type == TaskType.director_generate:
        return _run_director_generate(params, progress_cb)
    elif task_type == TaskType.video_generate:
        return _run_video_generate(params, progress_cb)
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

    # Auto-detect end chapter from outline
    end_ch = params.get("end_chapter")
    if end_ch is None:
        ckpt = pipe._load_checkpoint(novel_id)
        if ckpt:
            total = len(ckpt.get("outline", {}).get("chapters", []))
            batch = params.get("batch_size", 20)
            end_ch = min(start_ch + batch - 1, total)

    return pipe.generate_chapters(
        project_path=project_path,
        start_chapter=start_ch,
        end_chapter=end_ch,
        silent=params.get("silent", False),
        progress_callback=progress_cb,
    )


def _run_novel_polish(params: dict) -> dict:
    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline(workspace=params.get("workspace", "workspace"))
    return pipe.polish_chapters(
        project_path=params["project_path"],
        start_chapter=params.get("start_chapter", 1),
        end_chapter=params.get("end_chapter"),
    )


def _run_novel_feedback(params: dict) -> dict:
    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline(workspace=params.get("workspace", "workspace"))
    return pipe.apply_feedback(
        project_path=params["project_path"],
        feedback_text=params["feedback_text"],
        chapter_number=params.get("chapter_number"),
        dry_run=params.get("dry_run", False),
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

        pipe = Pipeline(input_file=input_file, config=config, resume=False)
        output = pipe.run(progress_callback=progress_cb)

    if isinstance(output, dict):
        return output
    return {"output": str(output)} if output else {}
