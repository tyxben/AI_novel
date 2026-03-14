"""NovelPipeline - 小说创作流水线编排

编排 init graph 和 chapter graph，管理 workspace、checkpoint、文件持久化。
所有方法均为 SYNC。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable

from src.novel.agents.graph import build_chapter_graph, build_init_graph, _merge_state
from src.novel.config import NovelConfig, load_novel_config
from src.novel.storage.file_manager import FileManager

log = logging.getLogger("novel")

# ---------------------------------------------------------------------------
# 默认工作目录
# ---------------------------------------------------------------------------

_DEFAULT_WORKSPACE = "workspace"


# ---------------------------------------------------------------------------
# NovelPipeline
# ---------------------------------------------------------------------------


class NovelPipeline:
    """小说创作流水线 - 编排 init / chapter 两阶段图执行。"""

    def __init__(
        self,
        config: NovelConfig | None = None,
        workspace: str | None = None,
    ) -> None:
        self.config = config or load_novel_config()
        self.workspace = workspace or _DEFAULT_WORKSPACE
        self.file_manager: FileManager | None = None

    # ------------------------------------------------------------------
    # Lazy init helpers
    # ------------------------------------------------------------------

    def _get_file_manager(self) -> FileManager:
        if self.file_manager is None:
            self.file_manager = FileManager(self.workspace)
        return self.file_manager

    def _novel_dir(self, novel_id: str) -> Path:
        return Path(self.workspace) / "novels" / novel_id

    def _checkpoint_path(self, novel_id: str) -> Path:
        return self._novel_dir(novel_id) / "checkpoint.json"

    # ------------------------------------------------------------------
    # Checkpoint
    # ------------------------------------------------------------------

    def _save_checkpoint(self, novel_id: str, state: dict) -> None:
        """Save pipeline state as checkpoint JSON (atomic write)."""
        ckpt_path = self._checkpoint_path(novel_id)
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)

        # Filter out non-serializable fields
        serializable = {}
        skip_keys = {"memory"}
        for k, v in state.items():
            if k in skip_keys:
                continue
            try:
                json.dumps(v, ensure_ascii=False)
                serializable[k] = v
            except (TypeError, ValueError):
                log.debug("跳过不可序列化字段: %s", k)

        # Atomic write: temp file + rename to prevent corruption on crash
        fd, tmp_path = tempfile.mkstemp(
            dir=str(ckpt_path.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(ckpt_path))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load_checkpoint(self, novel_id: str) -> dict | None:
        """Load checkpoint JSON. Returns None if not found."""
        ckpt_path = self._checkpoint_path(novel_id)
        if not ckpt_path.exists():
            return None
        with open(ckpt_path, encoding="utf-8") as f:
            data = json.load(f)
        # JSON round-trip converts int dict keys to strings; restore retry_counts
        if "retry_counts" in data and isinstance(data["retry_counts"], dict):
            data["retry_counts"] = {
                int(k): v for k, v in data["retry_counts"].items()
            }
        return data

    # ------------------------------------------------------------------
    # create_novel
    # ------------------------------------------------------------------

    def create_novel(
        self,
        genre: str,
        theme: str,
        target_words: int,
        style: str = "",
        template: str = "",
        custom_ideas: str = "",
        author_name: str = "",
        target_audience: str = "",
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> dict:
        """Create a new novel project.

        1. Initialize workspace (FileManager)
        2. Run init graph (outline + world + characters)
        3. Save initial state to checkpoint

        Returns:
            Project info dict with keys: novel_id, workspace, outline, characters, world_setting
        """
        novel_id = f"novel_{uuid.uuid4().hex[:8]}"
        fm = self._get_file_manager()

        log.info("创建小说项目: %s (题材=%s, 主题=%s, 目标字数=%d)", novel_id, genre, theme, target_words)

        # Build initial state
        state: dict[str, Any] = {
            "genre": genre,
            "theme": theme,
            "target_words": target_words,
            "style_name": style,
            "template": template,
            "custom_style_reference": custom_ideas if custom_ideas else None,
            "novel_id": novel_id,
            "workspace": self.workspace,
            "config": self.config.model_dump(),
            "current_chapter": 0,
            "total_chapters": 0,
            "review_interval": self.config.human_in_loop.review_interval,
            "silent_mode": self.config.human_in_loop.silent_mode,
            "auto_approve_threshold": self.config.quality.auto_approve_threshold,
            "max_retries": self.config.quality.max_retries,
            "outline": None,
            "world_setting": None,
            "characters": [],
            "main_storyline": {},
            "chapters": [],
            "decisions": [],
            "errors": [],
            "completed_nodes": [],
            "retry_counts": {},
            "should_continue": True,
        }

        # Run init graph nodes one by one with progress callbacks
        from src.novel.agents.graph import _get_node_functions

        nodes = _get_node_functions()

        if progress_callback:
            progress_callback(0.1, "正在生成大纲（可能需要1-2分钟）...")
        result = nodes["novel_director"](state)
        state = _merge_state(state, result)

        # 提取主线信息
        outline = state.get("outline", {})
        if isinstance(outline, dict):
            state["main_storyline"] = outline.get("main_storyline", {})
        else:
            state["main_storyline"] = {}

        if progress_callback:
            progress_callback(0.4, "正在构建世界观...")
        result = nodes["world_builder"](state)
        state = _merge_state(state, result)

        if progress_callback:
            progress_callback(0.7, "正在设计角色...")
        result = nodes["character_designer"](state)
        state = _merge_state(state, result)

        # Extract protagonist names from characters
        protagonist_names = []
        for c in state.get("characters", []):
            if isinstance(c, dict):
                role = c.get("role", "")
                if "主角" in role or "protagonist" in role.lower():
                    protagonist_names.append(c.get("name", ""))
        # If no explicit protagonist found, take first character
        if not protagonist_names and state.get("characters"):
            first = state["characters"][0]
            if isinstance(first, dict):
                protagonist_names.append(first.get("name", ""))

        # Generate synopsis from outline
        outline = state.get("outline", {})
        synopsis = outline.get("synopsis", "") if isinstance(outline, dict) else ""
        if not synopsis:
            # Build from theme + first few chapter goals
            chapters_list = outline.get("chapters", []) if isinstance(outline, dict) else []
            ch_goals = [ch.get("goal", "") for ch in chapters_list[:3] if ch.get("goal")]
            synopsis = f"{theme}。" + "；".join(ch_goals) if ch_goals else theme

        # Generate tags from genre + theme
        tags = [genre]
        if target_audience:
            tags.append(target_audience)
        # Extract mood types from outline chapters as tags
        moods: set[str] = set()
        outline_chapters = outline.get("chapters", []) if isinstance(outline, dict) else []
        for ch in outline_chapters:
            m = ch.get("mood")
            if m:
                moods.add(m)
        if moods:
            tags.extend(list(moods)[:3])

        # Save novel metadata
        novel_data = {
            "novel_id": novel_id,
            "title": f"{genre} - {theme}",
            "genre": genre,
            "theme": theme,
            "target_words": target_words,
            "status": "initialized",
            "current_chapter": 0,
            "outline": state.get("outline"),
            "characters": state.get("characters", []),
            "world_setting": state.get("world_setting"),
            "style_name": state.get("style_name", style),
            "template": state.get("template", template),
            "author_name": author_name,
            "target_audience": target_audience,
            "protagonist_names": protagonist_names,
            "synopsis": synopsis,
            "tags": tags,
        }
        fm.save_novel(novel_id, novel_data)

        # Save checkpoint
        self._save_checkpoint(novel_id, state)

        project_path = str(self._novel_dir(novel_id))
        log.info("项目创建完成: %s", project_path)

        return {
            "novel_id": novel_id,
            "workspace": project_path,
            "outline": state.get("outline"),
            "characters": state.get("characters", []),
            "world_setting": state.get("world_setting"),
            "total_chapters": state.get("total_chapters", 0),
            "errors": state.get("errors", []),
            "author_name": author_name,
            "target_audience": target_audience,
            "protagonist_names": protagonist_names,
            "synopsis": synopsis,
            "tags": tags,
        }

    # ------------------------------------------------------------------
    # generate_chapters
    # ------------------------------------------------------------------

    def generate_chapters(
        self,
        project_path: str,
        start_chapter: int = 1,
        end_chapter: int | None = None,
        silent: bool = False,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> dict:
        """Generate chapters for an existing project.

        1. Load checkpoint
        2. For each chapter: run chapter graph
        3. After each chapter: save checkpoint, save chapter text
        4. Every N chapters: pause for review (unless silent mode)

        Returns:
            Generation summary dict.
        """
        novel_id = Path(project_path).name
        fm = self._get_file_manager()

        # Load checkpoint
        state = self._load_checkpoint(novel_id)
        if state is None:
            raise FileNotFoundError(f"找不到项目检查点: {project_path}")

        outline = state.get("outline")
        if not outline:
            raise ValueError("项目大纲不存在，请先运行 create_novel")

        total_chapters = len(outline.get("chapters", []))
        if end_chapter is None:
            end_chapter = total_chapters

        # Determine effective silent mode
        effective_silent = silent or state.get("silent_mode", False)
        review_interval = state.get("review_interval", self.config.human_in_loop.review_interval)

        # 确保主线信息存在（从 checkpoint 恢复时可能缺失）
        if not state.get("main_storyline"):
            outline_data = state.get("outline", {})
            if isinstance(outline_data, dict):
                state["main_storyline"] = outline_data.get("main_storyline", {})
            else:
                state["main_storyline"] = {}

        chapters_generated = []
        consecutive_failures = 0
        chapter_graph = build_chapter_graph()

        for ch_num in range(start_chapter, end_chapter + 1):
            log.info("=== 生成第 %d/%d 章 ===", ch_num, total_chapters)

            # Report progress
            if progress_callback:
                total_in_batch = end_chapter - start_chapter + 1
                done_in_batch = ch_num - start_chapter
                pct = done_in_batch / total_in_batch
                progress_callback(pct, f"正在生成第{ch_num}/{total_chapters}章...")

            # Set up current chapter in state
            ch_outline = self._get_chapter_outline(outline, ch_num)
            if ch_outline is None:
                log.warning("第%d章大纲不存在，跳过", ch_num)
                continue

            state["current_chapter"] = ch_num
            state["current_chapter_outline"] = ch_outline
            state["current_chapter_text"] = None
            state["current_chapter_quality"] = None
            state["current_scenes"] = None

            # Run chapter graph
            try:
                state = chapter_graph.invoke(state)
            except Exception as exc:
                log.error("第%d章生成失败: %s", ch_num, exc)
                state.setdefault("errors", []).append(
                    {"agent": "pipeline", "message": f"第{ch_num}章生成失败: {exc}"}
                )
                # Save checkpoint even on failure
                self._save_checkpoint(novel_id, state)
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    log.error("连续 %d 章生成失败，中止批量生成", consecutive_failures)
                    break
                continue

            # Reset consecutive failure counter on success
            consecutive_failures = 0

            # Save chapter
            chapter_text = state.get("current_chapter_text", "")
            if chapter_text:
                ch_data = {
                    "chapter_number": ch_num,
                    "title": ch_outline.get("title", f"第{ch_num}章"),
                    "full_text": chapter_text,
                    "word_count": len(chapter_text),
                    "status": "draft",
                }
                fm.save_chapter(novel_id, ch_num, ch_data)
                fm.save_chapter_text(novel_id, ch_num, chapter_text)

                # Append to chapters list in state
                chapters = state.get("chapters", [])
                chapters.append(ch_data)
                state["chapters"] = chapters

                chapters_generated.append(ch_num)

            # Update novel metadata
            novel_data = fm.load_novel(novel_id) or {}
            novel_data["current_chapter"] = ch_num
            novel_data["status"] = "generating"
            fm.save_novel(novel_id, novel_data)

            # Save checkpoint
            self._save_checkpoint(novel_id, state)

            # Review pause
            if (
                not effective_silent
                and review_interval > 0
                and ch_num % review_interval == 0
                and ch_num < end_chapter
            ):
                log.info("已生成 %d 章，暂停审核（静默模式可跳过）", ch_num)
                # In CLI mode, the caller decides whether to pause
                # For now, just log and continue

        # Mark complete if all chapters done
        if end_chapter >= total_chapters:
            novel_data = fm.load_novel(novel_id) or {}
            novel_data["status"] = "completed"
            fm.save_novel(novel_id, novel_data)

        return {
            "novel_id": novel_id,
            "chapters_generated": chapters_generated,
            "total_generated": len(chapters_generated),
            "errors": state.get("errors", []),
        }

    # ------------------------------------------------------------------
    # resume_novel
    # ------------------------------------------------------------------

    def resume_novel(self, project_path: str) -> dict:
        """Resume from checkpoint. Loads state and continues generation.

        Returns:
            Generation summary dict.
        """
        novel_id = Path(project_path).name
        fm = self._get_file_manager()

        state = self._load_checkpoint(novel_id)
        if state is None:
            raise FileNotFoundError(f"找不到项目检查点: {project_path}")

        outline = state.get("outline")
        if not outline:
            raise ValueError("项目大纲不存在")

        total_chapters = len(outline.get("chapters", []))
        completed_chapters = fm.list_chapters(novel_id)
        if completed_chapters:
            start_chapter = max(completed_chapters) + 1
        else:
            start_chapter = 1

        if start_chapter > total_chapters:
            return {
                "novel_id": novel_id,
                "message": "所有章节已生成完成",
                "chapters_generated": [],
                "total_generated": 0,
            }

        log.info("从第%d章恢复生成（共%d章）", start_chapter, total_chapters)
        return self.generate_chapters(
            project_path, start_chapter=start_chapter, silent=True
        )

    # ------------------------------------------------------------------
    # export_novel
    # ------------------------------------------------------------------

    def export_novel(
        self, project_path: str, output_path: str | None = None
    ) -> str:
        """Export all chapters as a single text file.

        Returns:
            Output file path.
        """
        novel_id = Path(project_path).name
        fm = self._get_file_manager()
        result = fm.export_novel_txt(novel_id, output_path)
        return str(result)

    # ------------------------------------------------------------------
    # get_status
    # ------------------------------------------------------------------

    def get_status(self, project_path: str) -> dict:
        """Get project status (current chapter, total, word count, etc.)."""
        novel_id = Path(project_path).name
        fm = self._get_file_manager()
        status = fm.load_status(novel_id)

        # Enrich with checkpoint data
        ckpt = self._load_checkpoint(novel_id)
        if ckpt:
            status["characters_count"] = len(ckpt.get("characters", []))
            status["has_world_setting"] = ckpt.get("world_setting") is not None
            status["errors_count"] = len(ckpt.get("errors", []))
            status["decisions_count"] = len(ckpt.get("decisions", []))

        return status

    # ------------------------------------------------------------------
    # polish_chapters
    # ------------------------------------------------------------------

    def polish_chapters(
        self,
        project_path: str,
        start_chapter: int = 1,
        end_chapter: int | None = None,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> dict:
        """精修章节：AI 自审自改，提升章节质量。

        与 apply_feedback 的区别：
        - apply_feedback 需要人工输入反馈文本
        - polish_chapters 是 AI 自己当编辑，自动发现问题并修改

        流程：自审(self_critique) → 精修(polish_chapter)

        Args:
            project_path: 项目路径
            start_chapter: 起始章节号
            end_chapter: 结束章节号（None=所有章节）
            progress_callback: 进度回调

        Returns:
            dict with polished_chapters, skipped_chapters, errors
        """
        from src.llm.llm_client import create_llm_client
        from src.novel.agents.writer import Writer
        from src.novel.models.character import CharacterProfile
        from src.novel.models.novel import ChapterOutline
        from src.novel.models.world import WorldSetting

        novel_id = Path(project_path).name
        fm = self._get_file_manager()

        # Load checkpoint
        state = self._load_checkpoint(novel_id)
        if state is None:
            raise FileNotFoundError(f"找不到项目检查点: {project_path}")

        outline = state.get("outline")
        if not outline:
            raise ValueError("项目大纲不存在")

        outline_chapters = outline.get("chapters", [])
        total_chapters = len(outline_chapters)
        if end_chapter is None:
            end_chapter = total_chapters

        # Initialize LLM + Writer
        llm_config = state.get("config", {}).get("llm", {})
        llm = create_llm_client(llm_config)
        writer = Writer(llm)

        # 设置主线上下文
        main_storyline = state.get("main_storyline", {})
        if not main_storyline and isinstance(outline, dict):
            main_storyline = outline.get("main_storyline", {})

        # 恢复角色和世界观
        characters: list[CharacterProfile] = []
        for c_data in state.get("characters", []):
            try:
                characters.append(
                    CharacterProfile(**c_data) if isinstance(c_data, dict) else c_data
                )
            except Exception:
                pass

        world_data = state.get("world_setting")
        if world_data:
            try:
                world_setting = (
                    WorldSetting(**world_data)
                    if isinstance(world_data, dict)
                    else world_data
                )
            except Exception:
                world_setting = WorldSetting(era="未知", location="未知")
        else:
            world_setting = WorldSetting(era="未知", location="未知")

        style_name = state.get("style_name", "webnovel.shuangwen")

        # 加载所有章节文本
        chapter_texts: dict[int, str] = {}
        for ch_num in range(1, total_chapters + 1):
            text = fm.load_chapter_text(novel_id, ch_num)
            if text:
                chapter_texts[ch_num] = text

        # 构建各章摘要（用于跨章重复检测）
        def build_chapter_summaries(exclude_chapter: int) -> str:
            """构建除当前章外的所有章节摘要"""
            summaries = []
            for ch_num in sorted(chapter_texts.keys()):
                if ch_num == exclude_chapter:
                    continue
                text = chapter_texts[ch_num]
                # 取前150字+后150字
                if len(text) > 300:
                    summary = text[:150] + "…" + text[-150:]
                else:
                    summary = text
                ch_title = ""
                for ch_outline in outline_chapters:
                    if ch_outline.get("chapter_number") == ch_num:
                        ch_title = ch_outline.get("title", "")
                        break
                summaries.append(f"第{ch_num}章「{ch_title}」: {summary}")
            return "\n\n".join(summaries)

        # 精修结果
        result: dict = {
            "novel_id": novel_id,
            "polished_chapters": [],
            "skipped_chapters": [],
            "errors": [],
        }

        total_in_batch = end_chapter - start_chapter + 1

        for ch_num in range(start_chapter, end_chapter + 1):
            if progress_callback:
                done = ch_num - start_chapter
                pct = done / total_in_batch
                progress_callback(pct, f"正在精修第{ch_num}/{total_chapters}章...")

            chapter_text = chapter_texts.get(ch_num)
            if not chapter_text:
                log.warning("第%d章无文本，跳过精修", ch_num)
                result["skipped_chapters"].append(ch_num)
                continue

            # 获取章节大纲
            ch_outline_data = next(
                (ch for ch in outline_chapters if ch.get("chapter_number") == ch_num),
                None,
            )
            if not ch_outline_data:
                log.warning("第%d章无大纲，跳过精修", ch_num)
                result["skipped_chapters"].append(ch_num)
                continue

            try:
                ch_outline = ChapterOutline(**ch_outline_data)
            except Exception:
                log.warning("第%d章大纲解析失败，跳过", ch_num)
                result["skipped_chapters"].append(ch_num)
                continue

            # 设置主线上下文
            if main_storyline:
                storyline_progress = ch_outline_data.get(
                    "storyline_progress", ""
                ) or ch_outline_data.get("goal", "")
                writer.set_storyline_context(
                    main_storyline=main_storyline,
                    current_chapter=ch_num,
                    total_chapters=total_chapters,
                    storyline_progress=storyline_progress,
                )

            # 前文上下文
            context = ""
            if ch_num > 1 and (ch_num - 1) in chapter_texts:
                context = chapter_texts[ch_num - 1][-2000:]  # 取上一章结尾

            log.info("=== 精修第 %d/%d 章 ===", ch_num, total_chapters)

            try:
                # Step 1: 自审
                log.info("第%d章：自审中...", ch_num)
                all_summaries = build_chapter_summaries(ch_num)
                critique = writer.self_critique(
                    chapter_text=chapter_text,
                    chapter_outline=ch_outline,
                    context=context,
                    all_chapter_summaries=all_summaries,
                )

                log.info("第%d章审稿意见:\n%s", ch_num, critique[:200])

                # Step 2: 精修
                if "审稿通过" in critique and "无需修改" in critique:
                    log.info("第%d章审稿通过，跳过精修", ch_num)
                    result["skipped_chapters"].append(ch_num)
                    continue

                log.info("第%d章：精修中...", ch_num)
                polished_text = writer.polish_chapter(
                    chapter_text=chapter_text,
                    critique=critique,
                    chapter_outline=ch_outline,
                    characters=characters,
                    world_setting=world_setting,
                    context=context,
                    style_name=style_name,
                )

                # 备份原文，保存精修版
                fm.save_chapter_revision(novel_id, ch_num, chapter_text)
                fm.save_chapter_text(novel_id, ch_num, polished_text)

                # 更新内存中的章节文本（后续章节的上下文会用到）
                chapter_texts[ch_num] = polished_text

                result["polished_chapters"].append({
                    "chapter_number": ch_num,
                    "original_chars": len(chapter_text),
                    "polished_chars": len(polished_text),
                    "critique_summary": critique[:200],
                })

                log.info(
                    "第%d章精修完成: %d → %d 字",
                    ch_num,
                    len(chapter_text),
                    len(polished_text),
                )

            except Exception as exc:
                log.error("第%d章精修失败: %s", ch_num, exc)
                result["errors"].append({
                    "chapter": ch_num,
                    "error": str(exc),
                })

        # 更新小说状态
        novel_data = fm.load_novel(novel_id) or {}
        novel_data["status"] = "polished"
        fm.save_novel(novel_id, novel_data)

        if progress_callback:
            progress_callback(1.0, "精修完成!")

        return result

    # ------------------------------------------------------------------
    # apply_feedback
    # ------------------------------------------------------------------

    def apply_feedback(
        self,
        project_path: str,
        feedback_text: str,
        chapter_number: int | None = None,
        max_propagation: int = 10,
        dry_run: bool = False,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> dict:
        """应用读者反馈，重写受影响章节。

        Args:
            project_path: 项目路径
            feedback_text: 反馈文本
            chapter_number: 针对的章节号（None=全局）
            max_propagation: 最大传播章节数
            dry_run: 仅分析不重写

        Returns:
            dict with analysis, rewritten_chapters, etc.
        """
        from src.llm.llm_client import create_llm_client
        from src.novel.agents.feedback_analyzer import FeedbackAnalyzer
        from src.novel.agents.writer import Writer
        from src.novel.models.character import CharacterProfile
        from src.novel.models.novel import ChapterOutline
        from src.novel.models.world import WorldSetting
        from src.novel.utils import truncate_text

        # Load state
        novel_id = Path(project_path).name
        state = self._load_checkpoint(novel_id)
        if state is None:
            raise FileNotFoundError(f"找不到项目检查点: {project_path}")

        # Initialize LLM
        llm_config = state.get("config", {}).get("llm", {})
        llm = create_llm_client(llm_config)

        # Analyze feedback
        if progress_callback:
            progress_callback(0.1, "正在分析反馈...")
        analyzer = FeedbackAnalyzer(llm)
        outline_chapters = state.get("outline", {}).get("chapters", [])
        characters = state.get("characters", [])

        analysis = analyzer.analyze(
            feedback_text=feedback_text,
            chapter_number=chapter_number,
            outline_chapters=outline_chapters,
            characters=characters,
            max_propagation=max_propagation,
        )

        log.info(
            "反馈分析完成: 类型=%s, 严重度=%s, 直接修改%d章, 传播%d章",
            analysis.get("feedback_type"),
            analysis.get("severity"),
            len(analysis.get("target_chapters", [])),
            len(analysis.get("propagation_chapters", [])),
        )

        result: dict = {
            "analysis": analysis,
            "rewritten_chapters": [],
            "dry_run": dry_run,
        }

        if dry_run:
            if progress_callback:
                progress_callback(1.0, "分析完成!")
            return result

        # Prepare writer
        writer = Writer(llm)
        fm = self._get_file_manager()

        # Restore models
        char_profiles: list[CharacterProfile] = []
        for c in characters:
            try:
                char_profiles.append(
                    CharacterProfile(**c) if isinstance(c, dict) else c
                )
            except Exception:
                pass

        world_data = state.get("world_setting")
        if world_data:
            try:
                world_setting = (
                    WorldSetting(**world_data)
                    if isinstance(world_data, dict)
                    else world_data
                )
            except Exception:
                world_setting = WorldSetting(era="未知", location="未知")
        else:
            world_setting = WorldSetting(era="未知", location="未知")

        style_name = state.get("style_name", "webnovel.shuangwen")

        # Build chapter map for context
        chapters_done = state.get("chapters", [])
        chapter_texts: dict[int, str] = {}
        for ch_data in chapters_done:
            ch_num = ch_data.get("chapter_number")
            ch_text = ch_data.get("full_text", "")
            if ch_num and ch_text:
                chapter_texts[ch_num] = ch_text
        # Also load from files
        for ch_num in range(1, len(outline_chapters) + 1):
            if ch_num not in chapter_texts:
                text = fm.load_chapter_text(novel_id, ch_num)
                if text:
                    chapter_texts[ch_num] = text

        # --- Diagnosis chain: locate evidence + plan precise fix ---
        diagnosis = analysis.get("diagnosis")
        if diagnosis and analysis.get("target_chapters"):
            if progress_callback:
                progress_callback(0.2, "正在正文中定位问题...")
            # Collect texts for target + propagation chapters
            affected_chs = set(
                analysis.get("target_chapters", [])
                + analysis.get("propagation_chapters", [])
            )
            texts_subset = {
                ch: chapter_texts[ch]
                for ch in affected_chs
                if ch in chapter_texts
            }
            evidence = analyzer.locate_evidence(
                diagnosis=diagnosis,
                chapter_texts=texts_subset,
                chapter_number=chapter_number,
            )

            if evidence:
                if progress_callback:
                    progress_callback(0.25, "基于证据生成精准修改方案...")
                enhanced = analyzer.plan_fix(
                    diagnosis=diagnosis,
                    evidence=evidence,
                    outline_chapters=outline_chapters,
                )
                # Merge enhanced instructions into analysis
                if enhanced.get("rewrite_instructions"):
                    analysis["rewrite_instructions"] = enhanced[
                        "rewrite_instructions"
                    ]
                if enhanced.get("target_chapters"):
                    analysis["target_chapters"] = enhanced["target_chapters"]
                if enhanced.get("propagation_chapters"):
                    analysis["propagation_chapters"] = enhanced[
                        "propagation_chapters"
                    ]
                analysis["evidence"] = evidence
                log.info(
                    "诊断链完成: 找到%d条证据，已增强修改指令",
                    len(evidence),
                )
            else:
                log.info("诊断链: 未在正文中找到确切证据，使用原始分析结果")

        # Rewrite chapters in order
        target_set = set(analysis.get("target_chapters", []))
        rewrite_queue = sorted(
            set(
                analysis.get("target_chapters", [])
                + analysis.get("propagation_chapters", [])
            )
        )

        rewrite_instructions = analysis.get("rewrite_instructions", {})

        for rw_idx, ch_num in enumerate(rewrite_queue):
            if progress_callback:
                pct = 0.3 + 0.7 * (rw_idx / max(len(rewrite_queue), 1))
                progress_callback(pct, f"正在重写第{ch_num}章...")
            original_text = chapter_texts.get(ch_num)
            if not original_text:
                log.warning("第%d章无原文，跳过重写", ch_num)
                continue

            # Save revision backup
            fm.save_chapter_revision(novel_id, ch_num, original_text)

            # Get outline for this chapter
            ch_outline_data = next(
                (
                    ch
                    for ch in outline_chapters
                    if ch.get("chapter_number") == ch_num
                ),
                None,
            )
            if not ch_outline_data:
                log.warning("第%d章无大纲，跳过重写", ch_num)
                continue

            try:
                ch_outline = ChapterOutline(**ch_outline_data)
            except Exception:
                log.warning("第%d章大纲解析失败，跳过", ch_num)
                continue

            # Context from previous chapter
            context = ""
            if ch_num > 1 and (ch_num - 1) in chapter_texts:
                context = truncate_text(chapter_texts[ch_num - 1], 2000)

            # Get instruction
            instruction = rewrite_instructions.get(
                str(ch_num), rewrite_instructions.get(ch_num, feedback_text)
            )
            is_propagation = ch_num not in target_set

            log.info(
                "重写第%d章 (%s)...",
                ch_num,
                "传播调整" if is_propagation else "直接修改",
            )

            try:
                new_text = writer.rewrite_chapter(
                    original_text=original_text,
                    rewrite_instruction=instruction,
                    chapter_outline=ch_outline,
                    characters=char_profiles,
                    world_setting=world_setting,
                    context=context,
                    style_name=style_name,
                    is_propagation=is_propagation,
                )

                # Save rewritten chapter
                fm.save_chapter_text(novel_id, ch_num, new_text)
                chapter_texts[ch_num] = new_text  # update for subsequent chapters' context

                result["rewritten_chapters"].append(
                    {
                        "chapter_number": ch_num,
                        "original_chars": len(original_text),
                        "new_chars": len(new_text),
                        "is_propagation": is_propagation,
                    }
                )

                log.info(
                    "第%d章重写完成: %d → %d 字",
                    ch_num,
                    len(original_text),
                    len(new_text),
                )

            except Exception as exc:
                log.error("第%d章重写失败: %s", ch_num, exc)
                result.setdefault("errors", []).append(
                    {
                        "chapter": ch_num,
                        "error": str(exc),
                    }
                )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_chapter_outline(self, outline: dict, chapter_number: int) -> dict | None:
        """Get chapter outline by chapter number."""
        for ch in outline.get("chapters", []):
            if ch.get("chapter_number") == chapter_number:
                return ch
        return None
