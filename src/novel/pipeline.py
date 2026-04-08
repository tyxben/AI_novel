"""NovelPipeline - 小说创作流水线编排

编排 init graph 和 chapter graph，管理 workspace、checkpoint、文件持久化。
所有方法均为 SYNC。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable

from src.novel.agents.graph import build_chapter_graph, _merge_state
from src.novel.config import NovelConfig, load_novel_config
from src.novel.llm_utils import get_stage_llm_config
from src.novel.storage.file_manager import FileManager
from src.novel.utils import count_words

log = logging.getLogger("novel")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_title(title: str, ch_num: int) -> str:
    """Sanitize a chapter title, rejecting garbage and prompt fragments.

    Applied to both extracted and outline-provided titles so that no
    garbage leaks into saved chapter metadata.
    """
    # Strip raw escape sequences that sometimes appear in LLM output
    title = title.replace("\\n", "").replace("\\t", "").replace("\\r", "")
    # Also strip actual whitespace / newlines
    title = title.strip().strip("\n\r\t ")

    # Strip leading/trailing quotation marks (Chinese & ASCII)
    _QUOTE_CHARS = '"\'\u201c\u201d\u2018\u2019\u300c\u300d\u300e\u300f\u3010\u3011'
    title = title.strip(_QUOTE_CHARS)
    title = title.strip()

    # Reject titles that look like prompt instructions or meta-text
    _BAD_PATTERNS = [
        "字数", "场景", "目标", "要求", "注意", "提示", "格式",
        "左右", "以上", "以下", "不超过", "大约",
    ]
    if any(p in title for p in _BAD_PATTERNS):
        return f"第{ch_num}章"

    # Reject if still contains control-ish characters
    if "\n" in title or "\t" in title or "\r" in title:
        return f"第{ch_num}章"

    # Reject overly long titles (likely a full sentence leaked through)
    if len(title) > 15:
        return f"第{ch_num}章"

    # Reject too short or empty
    if not title or len(title) < 2:
        return f"第{ch_num}章"

    return title


def _extract_title_from_text(chapter_text: str, ch_num: int) -> str:
    """Extract a short, meaningful title from chapter text.

    Uses heuristics: finds the most "interesting" short phrase from the
    first few paragraphs — a character action, a location reveal, or a
    key event.  Falls back to first sentence truncated to 10 chars.

    Skips markdown headers (lines starting with ``#``) and lines that
    look like chapter-number headers (``第N章 ...``) to avoid picking up
    wrong chapter numbers or ``#`` prefixes in the title.
    """
    import re

    lines = [ln.strip() for ln in chapter_text.split("\n") if ln.strip()]
    if not lines:
        return f"第{ch_num}章"

    # Try to find a short, punchy sentence in the first 5 lines
    for line in lines[:5]:
        # Skip markdown headers
        if line.startswith("#"):
            continue
        # Skip lines that look like chapter number headers
        if re.match(r'^第\d+章', line):
            continue

        # Split into sentences
        sentences = re.split(r'[。！？]', line)
        for sent in sentences:
            sent = sent.strip().strip('""\'\"\'')
            # Good title: 4-12 chars, contains character action or place
            if 4 <= len(sent) <= 12:
                candidate = _sanitize_title(sent, ch_num)
                if candidate != f"第{ch_num}章":
                    return candidate

    # Fallback: first non-header line truncated
    for line in lines[:5]:
        if line.startswith("#") or re.match(r'^第\d+章', line):
            continue
        if len(line) > 10:
            # Cut at a natural boundary
            for sep in ("，", "。", "！", "？", "、"):
                idx = line.find(sep)
                if 3 <= idx <= 12:
                    candidate = _sanitize_title(line[:idx], ch_num)
                    if candidate != f"第{ch_num}章":
                        return candidate
            candidate = _sanitize_title(line[:10], ch_num)
            if candidate != f"第{ch_num}章":
                return candidate
        if len(line) >= 4:
            candidate = _sanitize_title(line, ch_num)
            if candidate != f"第{ch_num}章":
                return candidate

    return f"第{ch_num}章"


# ---------------------------------------------------------------------------
# 默认工作目录
# ---------------------------------------------------------------------------

_DEFAULT_WORKSPACE = "workspace"

# 审稿意见类型图标
_ISSUE_ICONS: dict[str, str] = {
    "重复": "🔁",
    "对话": "💬",
    "逻辑": "🧩",
    "节奏": "⏱️",
    "细节": "🔍",
    "AI味": "🤖",
    "转折": "↪️",
    "角色": "👤",
    "风格": "🎨",
    "其他": "📝",
}


def _parse_critique_issues(critique: str) -> list[dict]:
    """Parse Writer.self_critique() plain-text output into structured issues.

    Expected format per issue:
        【问题N】类型：X / 位置：Y / 问题：Z / 建议：W
    Also handles multi-line variants and partial matches.
    """
    if not critique:
        return []

    issues: list[dict] = []

    # Split by 【问题...】 markers
    blocks = re.split(r"【问题\d*】", critique)
    for block in blocks[1:]:  # skip preamble before first marker
        block = block.strip()
        if not block:
            continue

        issue: dict[str, str] = {}

        # Extract structured fields: 类型：X / 位置：Y / ...
        for field, key in [("类型", "type"), ("位置", "location"),
                           ("问题", "problem"), ("建议", "suggestion")]:
            m = re.search(rf"{field}[：:]\s*(.+?)(?:\s*/\s*|\n|$)", block)
            if m:
                issue[key] = m.group(1).strip()

        # Fallback: if no structured fields, use the whole block as problem
        if not issue:
            issue["problem"] = block[:200]
            issue["type"] = "其他"

        # Normalize type to known categories
        raw_type = issue.get("type", "其他")
        matched = False
        for known in _ISSUE_ICONS:
            if known in raw_type:
                issue["type"] = known
                matched = True
                break
        if not matched:
            issue["type"] = "其他"

        issues.append(issue)

    return issues


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

        # Strip full_text from chapters before saving (content lives in .txt files)
        if "chapters" in serializable:
            serializable["chapters"] = [
                {k: v for k, v in ch.items() if k != "full_text"}
                for ch in serializable["chapters"]
            ]

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
    # Refresh state from novel.json (canonical source of truth)
    # ------------------------------------------------------------------

    @staticmethod
    def _refresh_state_from_novel(state: dict, novel_data: dict | None) -> dict:
        """Merge authoritative fields from novel.json into runtime state.

        Edit operations (via edit_service) write to novel.json only.
        The checkpoint may still contain stale data.  This method brings
        outline / characters / world_setting / style_name up-to-date so
        that generate_chapters() and apply_feedback() see the latest edits.

        Args:
            state: Runtime state loaded from checkpoint.json.
            novel_data: Dict loaded from novel.json (may be None).

        Returns:
            The *same* state dict, mutated in-place for convenience.
        """
        if not novel_data:
            return state

        for key in ("outline", "characters", "world_setting"):
            if key in novel_data:
                state[key] = novel_data[key]

        # Refresh main_storyline from outline
        if "outline" in novel_data and isinstance(novel_data["outline"], dict):
            if "main_storyline" in novel_data["outline"]:
                state["main_storyline"] = novel_data["outline"]["main_storyline"]

        # Refresh style_name
        if "style_name" in novel_data:
            state["style_name"] = novel_data["style_name"]

        return state

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
        try:
            result = nodes["novel_director"](state)
            state = _merge_state(state, result)
        except Exception as e:
            log.error("大纲生成失败: %s", e)
            raise RuntimeError(f"大纲生成失败: {e}") from e

        # 校验大纲是否有效
        outline = state.get("outline")
        if not outline or not isinstance(outline, dict) or not outline.get("chapters"):
            errors = state.get("errors", [])
            err_msg = f"大纲生成结果为空。errors={errors}" if errors else "大纲生成结果为空，请检查 LLM 配置和 API Key"
            log.error(err_msg)
            raise RuntimeError(err_msg)

        # 提取主线信息
        state["main_storyline"] = outline.get("main_storyline", {})

        if progress_callback:
            progress_callback(0.4, "正在构建世界观...")
        try:
            result = nodes["world_builder"](state)
            state = _merge_state(state, result)
        except Exception as e:
            log.warning("世界观构建失败，继续: %s", e)

        if progress_callback:
            progress_callback(0.7, "正在设计角色...")
        try:
            result = nodes["character_designer"](state)
            state = _merge_state(state, result)
        except Exception as e:
            log.warning("角色设计失败，继续: %s", e)

        # 校验角色
        if not state.get("characters"):
            log.warning("角色列表为空，项目仍可继续但质量可能受影响")

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

        # --- Story Arc Generation (optional) ---
        try:
            from src.novel.agents.novel_director import NovelDirector
            from src.llm.llm_client import create_llm_client as _create_llm

            _llm_config = get_stage_llm_config(state, "outline_generation")
            _llm = _create_llm(_llm_config)
            director = NovelDirector(_llm)

            outline_data = state.get("outline", {})
            chapters = outline_data.get("chapters", []) if isinstance(outline_data, dict) else []
            if chapters and hasattr(director, 'generate_story_arcs'):
                arcs = director.generate_story_arcs(
                    volume_outline=outline_data,
                    chapter_outlines=chapters,
                    genre=genre,
                )
                if arcs:
                    state.setdefault("story_arcs", []).extend(arcs)
                    # Update chapter arc_ids
                    for arc in arcs:
                        for ch_num in arc.get("chapters", []):
                            for ch in chapters:
                                if ch.get("chapter_number") == ch_num:
                                    ch["arc_id"] = arc.get("arc_id")
                    log.info("Generated %d story arcs", len(arcs))
        except Exception as e:
            log.warning("Story arc generation failed (non-critical): %s", e)

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

        if progress_callback:
            progress_callback(1.0, "项目创建完成!")

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
    # plan_chapters (outline-only, no text generation)
    # ------------------------------------------------------------------

    def plan_chapters(
        self,
        project_path: str,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> dict:
        """Generate/revise outlines for a range of chapters WITHOUT writing text.

        For each chapter:
        1. Load or create placeholder outline
        2. Run dynamic_outline revision (considers previous chapters, debts, arcs, character states)
        3. Save revised outline to checkpoint

        Returns dict with planned outlines for review.
        """
        from src.novel.agents.dynamic_outline import dynamic_outline_node

        novel_id = Path(project_path).name
        fm = self._get_file_manager()

        # Load checkpoint
        state = self._load_checkpoint(novel_id)
        if state is None:
            raise FileNotFoundError(f"找不到项目检查点: {project_path}")

        # Refresh settings from novel.json
        self._refresh_state_from_novel(state, fm.load_novel(novel_id))

        outline = state.get("outline")
        if not outline:
            raise ValueError("项目大纲不存在，请先运行 create_novel")

        total_chapters = len(outline.get("chapters", []))

        # Auto-detect start chapter if not specified
        if start_chapter is None:
            completed = fm.list_chapters(novel_id)
            start_chapter = (max(completed) + 1) if completed else 1

        if end_chapter is None:
            end_chapter = start_chapter + 3  # Default: plan 4 chapters

        # Extend outline if needed
        if end_chapter > total_chapters:
            log.info(
                "章节 %d-%d 超出当前大纲范围 (max=%d)，自动扩展大纲...",
                start_chapter, end_chapter, total_chapters,
            )
            self._extend_outline(novel_id, state, end_chapter, progress_callback)
            outline = state.get("outline", {})
            total_chapters = len(outline.get("chapters", []))

        # Ensure main_storyline exists
        if not state.get("main_storyline"):
            outline_data = state.get("outline", {})
            if isinstance(outline_data, dict):
                state["main_storyline"] = outline_data.get("main_storyline", {})
            else:
                state["main_storyline"] = {}

        # Initialize chapters_text from existing chapters on disk
        if "chapters_text" not in state:
            state["chapters_text"] = {}
        chapters_text = state["chapters_text"]
        if not chapters_text:
            from src.novel.storage.file_manager import FileManager as _FM
            fm_load = _FM(self.workspace)
            existing_nums = fm_load.list_chapters(novel_id)
            for ch_n in existing_nums:
                if ch_n not in chapters_text:
                    try:
                        chapters_dir = fm_load._chapters_dir(novel_id)
                        txt_path = chapters_dir / f"chapter_{ch_n:03d}.txt"
                        if txt_path.exists():
                            chapters_text[ch_n] = txt_path.read_text(encoding="utf-8")
                    except Exception:
                        pass
            state["chapters_text"] = chapters_text

        # Initialize NovelMemory (for continuity service + obligation tracker)
        try:
            from src.novel.storage.novel_memory import NovelMemory
            self.memory = NovelMemory(novel_id, self.workspace)
        except Exception as exc:
            log.warning("NovelMemory 初始化失败: %s", exc)
            self.memory = None

        # Initialize narrative control services
        obligation_tracker = None
        try:
            from src.novel.services.obligation_tracker import ObligationTracker
            if hasattr(self, 'memory') and self.memory and hasattr(self.memory, 'structured_db'):
                obligation_tracker = ObligationTracker(self.memory.structured_db)
            else:
                obligation_tracker = ObligationTracker(db=None)
        except Exception as e:
            log.warning("ObligationTracker init failed: %s", e)

        planned_chapters = []
        overdue_debts = 0
        active_arcs = 0

        # Collect debt/arc stats
        if obligation_tracker:
            try:
                stats = obligation_tracker.get_debt_statistics()
                overdue_debts = stats.get("overdue_count", 0)
            except Exception:
                pass
        try:
            story_arcs = state.get("story_arcs", [])
            active_arcs = sum(
                1 for a in story_arcs
                if a.get("status") in ("active", "in_progress", "planning")
            )
        except Exception:
            pass

        # Track events planned in this batch to prevent repetition
        batch_planned_events = []

        for ch_num in range(start_chapter, end_chapter + 1):
            if progress_callback:
                total_in_batch = end_chapter - start_chapter + 1
                done_in_batch = ch_num - start_chapter
                pct = done_in_batch / total_in_batch
                progress_callback(pct, f"正在规划第{ch_num}章大纲...")

            # Get or create chapter outline entry
            ch_outline = self._get_chapter_outline(outline, ch_num)
            if ch_outline is None:
                log.warning("第%d章大纲条目不存在，跳过", ch_num)
                continue

            # plan_chapters is an explicit user action — always re-plan
            log.info("第%d章大纲重新规划中...", ch_num)
            state["_batch_planned_context"] = batch_planned_events
            ch_outline = self._fill_placeholder_outline(state, ch_outline, ch_num)
            for i, existing_ch in enumerate(outline.get("chapters", [])):
                if existing_ch.get("chapter_number") == ch_num:
                    outline["chapters"][i] = ch_outline
                    break

            # Set up state context for dynamic_outline_node
            state["current_chapter"] = ch_num
            state["current_chapter_outline"] = ch_outline

            # Generate debt summary
            if obligation_tracker:
                try:
                    obligation_tracker.escalate_debts(ch_num)
                    state["debt_summary"] = obligation_tracker.get_summary_for_writer(ch_num)
                except Exception:
                    state["debt_summary"] = ""
            else:
                state["debt_summary"] = ""

            # Generate continuity brief
            try:
                from src.novel.services.continuity_service import ContinuityService as _ContinuityService
                _mem = getattr(self, "memory", None)
                continuity_svc = _ContinuityService(
                    db=getattr(_mem, "structured_db", None) if _mem else None,
                    obligation_tracker=obligation_tracker,
                )
                continuity_brief = continuity_svc.generate_brief(
                    chapter_number=ch_num,
                    chapters=state.get("chapters") or [],
                    chapter_brief=ch_outline.get("chapter_brief", {}),
                    story_arcs=state.get("story_arcs", []),
                    characters=state.get("characters", []),
                )
                state["continuity_brief"] = continuity_svc.format_for_prompt(continuity_brief)
            except Exception as exc:
                log.warning("连续性摘要生成失败: %s", exc)
                state["continuity_brief"] = ""

            # Run dynamic_outline_node to revise
            revision_reason = ""
            try:
                result = dynamic_outline_node(state)
                revised = result.get("current_chapter_outline")
                if revised:
                    ch_outline = revised
                    # Update outline in state
                    for i, existing_ch in enumerate(outline.get("chapters", [])):
                        if existing_ch.get("chapter_number") == ch_num:
                            outline["chapters"][i] = ch_outline
                            break

                # Extract revision reason from decisions
                for d in result.get("decisions", []):
                    if d.get("step") == "revise_outline":
                        revision_reason = d.get("reason", "")
                        break
            except Exception as exc:
                log.warning("第%d章动态大纲修订失败: %s", ch_num, exc)

            # Track this chapter's planned events for dedup in next iteration
            batch_planned_events.append(
                f"第{ch_num}章「{ch_outline.get('title', '')}」: {ch_outline.get('goal', '')}"
            )

            # Build planned chapter entry
            planned_entry = {
                "chapter_number": ch_num,
                "title": ch_outline.get("title", f"第{ch_num}章"),
                "goal": ch_outline.get("goal", ""),
                "key_events": ch_outline.get("key_events", []),
                "mood": ch_outline.get("mood", ""),
                "involved_characters": ch_outline.get("involved_characters", []),
                "chapter_brief": ch_outline.get("chapter_brief", {}),
                "revision_reason": revision_reason,
            }
            planned_chapters.append(planned_entry)

        # Save updated outlines to checkpoint and novel.json
        state["outline"] = outline
        self._save_checkpoint(novel_id, state)

        # Also update novel.json
        novel_data = fm.load_novel(novel_id) or {}
        novel_data["outline"] = outline
        fm.save_novel(novel_id, novel_data)

        if progress_callback:
            progress_callback(1.0, f"大纲规划完成，共规划 {len(planned_chapters)} 章")

        return {
            "novel_id": novel_id,
            "planned_chapters": planned_chapters,
            "context": {
                "overdue_debts": overdue_debts,
                "active_arcs": active_arcs,
                "total_planned": len(planned_chapters),
            },
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
        react_mode: bool = False,
        budget_mode: bool = False,
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

        # ★ Refresh settings from novel.json (edit_service writes there)
        self._refresh_state_from_novel(state, fm.load_novel(novel_id))

        outline = state.get("outline")
        if not outline:
            raise ValueError("项目大纲不存在，请先运行 create_novel")

        total_chapters = len(outline.get("chapters", []))
        if end_chapter is None:
            end_chapter = total_chapters

        # 超长篇支持：当请求的章节范围超出当前大纲时，自动扩展大纲
        if end_chapter > total_chapters:
            log.info(
                "章节 %d-%d 超出当前大纲范围 (max=%d)，自动扩展大纲...",
                start_chapter, end_chapter, total_chapters,
            )
            self._extend_outline(novel_id, state, end_chapter, progress_callback)
            # 重新获取 total_chapters
            outline = state.get("outline", {})
            total_chapters = len(outline.get("chapters", []))

        # --- Pre-check: ensure all target chapters have valid outlines ---
        outline_chapters = outline.get("chapters", [])
        outlined_nums = {ch.get("chapter_number") for ch in outline_chapters}
        placeholder_nums = []

        for ch_num in range(start_chapter, end_chapter + 1):
            if ch_num not in outlined_nums:
                placeholder_nums.append(ch_num)
            else:
                # Check if it's a placeholder
                ch = self._get_chapter_outline(outline, ch_num)
                if ch and self._is_placeholder_outline(ch):
                    placeholder_nums.append(ch_num)

        if placeholder_nums:
            log.info(
                "发现 %d 个占位符大纲 (章节 %s)，生成前先补全...",
                len(placeholder_nums),
                placeholder_nums[:5],
            )
            filled_count = 0
            for ch_num in placeholder_nums:
                ch = self._get_chapter_outline(outline, ch_num)
                if ch is None:
                    # Chapter doesn't exist in outline at all — need to extend
                    continue
                if self._is_placeholder_outline(ch):
                    try:
                        filled = self._fill_placeholder_outline(state, ch, ch_num)
                        # Update outline in state
                        for i, existing_ch in enumerate(outline.get("chapters", [])):
                            if existing_ch.get("chapter_number") == ch_num:
                                outline["chapters"][i] = filled
                                break
                        filled_count += 1
                        log.info("第%d章大纲已补全: %s", ch_num, filled.get("title", "?"))
                    except Exception as exc:
                        log.warning("第%d章大纲补全失败: %s", ch_num, exc)

            if filled_count > 0:
                # Save the updated outline to checkpoint
                state["outline"] = outline
                self._save_checkpoint(novel_id, state)
                log.info("已补全 %d/%d 个占位符大纲", filled_count, len(placeholder_nums))

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

        # Pass writer mode flags into state
        state["react_mode"] = react_mode
        state["budget_mode"] = budget_mode

        # Initialize chapters_text from existing chapters in state
        if "chapters_text" not in state:
            state["chapters_text"] = {}
            for ch in state.get("chapters") or []:
                ch_n = ch.get("chapter_number")
                ch_t = ch.get("full_text", "")
                if ch_n and ch_t:
                    state["chapters_text"][ch_n] = ch_t

        # --- Initialize NovelMemory for vector indexing + character snapshots ---
        try:
            from src.novel.storage.novel_memory import NovelMemory
            self.memory = NovelMemory(novel_id, self.workspace)
        except Exception as exc:
            log.warning("NovelMemory 初始化失败: %s", exc)
            self.memory = None

        chapters_generated = []
        consecutive_failures = 0
        chapter_graph = build_chapter_graph()

        # --- Narrative Control (optional) ---
        obligation_tracker = None
        debt_extractor = None
        brief_validator = None
        try:
            from src.novel.services.obligation_tracker import ObligationTracker
            from src.novel.services.debt_extractor import DebtExtractor
            from src.novel.tools.brief_validator import BriefValidator
            from src.llm.llm_client import create_llm_client

            llm_config = get_stage_llm_config(state, "quality_review")
            llm = create_llm_client(llm_config)

            # Use memory's structured_db if available
            if hasattr(self, 'memory') and self.memory and hasattr(self.memory, 'structured_db'):
                obligation_tracker = ObligationTracker(self.memory.structured_db)
            else:
                obligation_tracker = ObligationTracker(db=None)  # in-memory fallback

            debt_extractor = DebtExtractor(llm)
            brief_validator = BriefValidator(llm)
            log.info("Narrative control services initialized")
        except Exception as e:
            log.warning("Narrative control initialization failed (non-critical): %s", e)

        # Auto-backfill actual_summary for chapters that don't have it yet
        try:
            from src.novel.storage.file_manager import FileManager
            fm_bf = FileManager(self.workspace)
            outline_chapters = outline.get("chapters", [])
            chapters_needing_summary = []
            for ch in outline_chapters:
                ch_n = ch.get("chapter_number", 0)
                if ch_n < 1 or ch_n >= start_chapter:
                    continue
                if ch.get("actual_summary"):
                    continue
                # Check if chapter text exists on disk
                txt = fm_bf.load_chapter_text(novel_id, ch_n)
                if txt and len(txt) > 100:
                    chapters_needing_summary.append((ch_n, ch, txt))

            if chapters_needing_summary:
                log.info("发现 %d 章需要补全 actual_summary", len(chapters_needing_summary))
                for ch_n, ch, txt in chapters_needing_summary:
                    try:
                        title = ch.get("title", f"第{ch_n}章")
                        summary = self._generate_actual_summary(txt, ch_n, title, state=state)
                        if summary:
                            ch["actual_summary"] = summary
                            log.info("第%d章 actual_summary 已补全", ch_n)
                    except Exception as exc:
                        log.warning("第%d章 actual_summary 补全失败: %s", ch_n, exc)

                # Save back to novel.json
                novel_data = fm_bf.load_novel(novel_id) or {}
                novel_data["outline"] = outline
                fm_bf.save_novel(novel_id, novel_data)
        except Exception as exc:
            log.warning("自动补全 actual_summary 失败: %s", exc)

        for ch_num in range(start_chapter, end_chapter + 1):
            log.info("=== 生成第 %d/%d 章 ===", ch_num, total_chapters)

            # Report progress
            if progress_callback:
                total_in_batch = end_chapter - start_chapter + 1
                done_in_batch = ch_num - start_chapter
                pct = done_in_batch / total_in_batch
                progress_callback(pct, f"正在生成第{ch_num}/{total_chapters}章...")

            # --- Narrative Control: escalate overdue debts ---
            if obligation_tracker:
                try:
                    escalated = obligation_tracker.escalate_debts(ch_num)
                    if escalated > 0:
                        log.info("Escalated %d overdue debts for chapter %d", escalated, ch_num)
                except Exception:
                    pass

            # Set up current chapter in state
            ch_outline = self._get_chapter_outline(outline, ch_num)
            if ch_outline is None:
                log.warning("第%d章大纲不存在，跳过", ch_num)
                continue

            # Detect placeholder outline and fill it via LLM before proceeding
            if self._is_placeholder_outline(ch_outline):
                log.info("第%d章大纲为占位符，自动补全中...", ch_num)
                ch_outline = self._fill_placeholder_outline(state, ch_outline, ch_num)
                # Update outline in state so downstream nodes see the filled version
                for i, ch in enumerate(outline.get("chapters", [])):
                    if ch.get("chapter_number") == ch_num:
                        outline["chapters"][i] = ch_outline
                        break

            # After fill attempt, verify the outline is no longer a placeholder
            if self._is_placeholder_outline(ch_outline):
                log.error(
                    "第%d章大纲补全失败且仍为占位符，跳过生成以避免低质量输出",
                    ch_num,
                )
                state.setdefault("errors", []).append({
                    "agent": "pipeline",
                    "message": f"第{ch_num}章大纲为占位符且补全失败，已跳过",
                })
                continue

            state["current_chapter"] = ch_num
            state["current_chapter_outline"] = ch_outline
            state["current_chapter_text"] = None
            state["current_chapter_quality"] = None
            state["current_scenes"] = None

            # --- Narrative Control: pass services to state ---
            state["obligation_tracker"] = obligation_tracker
            state["brief_validator"] = brief_validator
            state["debt_extractor"] = debt_extractor
            # Pass memory info for state_writeback (not the object itself — unpicklable)
            state["novel_id"] = novel_id
            state["workspace"] = self.workspace

            # --- Narrative Control: generate debt summary for Writer ---
            if obligation_tracker:
                try:
                    state["debt_summary"] = obligation_tracker.get_summary_for_writer(ch_num)
                except Exception:
                    state["debt_summary"] = ""
            else:
                state["debt_summary"] = ""

            # --- Narrative Control: volume settlement + arc progression ---
            if obligation_tracker:
                try:
                    from src.novel.services.volume_settlement import VolumeSettlement

                    outline_data = state.get("outline", {})
                    vs = VolumeSettlement(
                        db=self.memory.structured_db if getattr(self, "memory", None) and getattr(self.memory, "structured_db", None) else None,
                        outline=outline_data if isinstance(outline_data, dict) else {},
                    )

                    # Advance arc phases
                    arc_changes = vs.advance_arc_phases(ch_num)
                    if arc_changes:
                        log.info(
                            "弧线推进: %s",
                            [f"{a['name']}: {a['old_phase']}→{a['new_phase']}" for a in arc_changes],
                        )

                    # Check volume settlement
                    settlement = vs.get_settlement_brief(ch_num)
                    if settlement.get("is_settlement_zone"):
                        # Append settlement prompt to debt_summary
                        existing_debt = state.get("debt_summary", "")
                        arc_prompt = vs.get_arc_prompt(ch_num)
                        state["debt_summary"] = "\n\n".join(
                            filter(None, [existing_debt, settlement["settlement_prompt"], arc_prompt])
                        )
                        log.info(
                            "卷末收束模式: %d个必须解决, %d个建议解决",
                            len(settlement.get("must_resolve", [])),
                            len(settlement.get("should_resolve", [])),
                        )
                    else:
                        # Still add arc prompt even outside settlement zone
                        arc_prompt = vs.get_arc_prompt(ch_num)
                        if arc_prompt:
                            existing_debt = state.get("debt_summary", "")
                            state["debt_summary"] = "\n\n".join(
                                filter(None, [existing_debt, arc_prompt])
                            )
                except Exception as exc:
                    log.warning("叙事控制扩展失败: %s", exc)

            # --- Narrative Control: add chapter_brief to state (Task 6.3) ---
            if ch_outline:
                state["current_chapter_brief"] = ch_outline.get("chapter_brief", {})
            else:
                state["current_chapter_brief"] = {}

            # --- Narrative Control: generate continuity brief ---
            try:
                from src.novel.services.continuity_service import ContinuityService as _ContinuityService

                _mem = getattr(self, "memory", None)
                continuity_svc = _ContinuityService(
                    db=getattr(_mem, "structured_db", None) if _mem else None,
                    obligation_tracker=obligation_tracker,
                )
                # Ensure chapters have full_text for continuity extraction
                _chapters_for_brief = []
                _chapters_text = state.get("chapters_text", {})
                for _bch in (state.get("chapters") or []):
                    _bch_copy = dict(_bch)
                    if not _bch_copy.get("full_text"):
                        _bch_copy["full_text"] = _chapters_text.get(
                            _bch_copy.get("chapter_number", 0), ""
                        )
                    _chapters_for_brief.append(_bch_copy)

                continuity_brief = continuity_svc.generate_brief(
                    chapter_number=ch_num,
                    chapters=_chapters_for_brief,
                    chapter_brief=ch_outline.get("chapter_brief", {}),
                    story_arcs=state.get("story_arcs", []),
                    characters=state.get("characters", []),
                )
                state["continuity_brief"] = continuity_svc.format_for_prompt(continuity_brief)
            except Exception as exc:
                log.warning("连续性摘要生成失败: %s", exc)
                state["continuity_brief"] = ""

            # --- Global Director: whole-book directorial guidance ---
            try:
                from src.novel.services.global_director import GlobalDirector
                novel_data_for_dir = fm.load_novel(novel_id) or {}
                director = GlobalDirector(novel_data_for_dir, outline)
                # Build recent_summaries for repetition detection
                recent_summaries = []
                for _och in outline.get("chapters", []):
                    _ocn = _och.get("chapter_number", 0)
                    if _ocn > 0 and _ocn < ch_num:
                        recent_summaries.append({
                            "chapter_number": _ocn,
                            "title": _och.get("title", ""),
                            "actual_summary": _och.get("actual_summary", ""),
                        })
                director_brief = director.analyze(ch_num, recent_summaries[-5:])
                director_prompt = director.format_for_prompt(director_brief)
                if director_prompt:
                    # Append to continuity_brief so Writer sees it
                    existing = state.get("continuity_brief", "")
                    state["continuity_brief"] = (
                        existing + "\n\n" + director_prompt if existing else director_prompt
                    )
            except Exception as exc:
                log.warning("全局导演分析失败: %s", exc)

            # --- Character Arc Tracker: per-character growth state ---
            try:
                from src.novel.services.character_arc_tracker import CharacterArcTracker
                arc_tracker = state.get("_arc_tracker")
                if arc_tracker is None:
                    arc_tracker = CharacterArcTracker()
                    # Restore from outline if persisted
                    persisted = (fm.load_novel(novel_id) or {}).get("character_arc_states", {})
                    if persisted:
                        arc_tracker.from_dict({"states": persisted})
                    state["_arc_tracker"] = arc_tracker

                # Get characters that will appear in this chapter
                involved_names = ch_outline.get("involved_characters", []) if ch_outline else []
                if not involved_names:
                    involved_names = [c.get("name", "") for c in state.get("characters", [])]
                arc_prompt = arc_tracker.format_for_prompt(involved_names, ch_num)
                if arc_prompt:
                    existing = state.get("continuity_brief", "")
                    state["continuity_brief"] = (
                        existing + "\n\n" + arc_prompt if existing else arc_prompt
                    )
            except Exception as exc:
                log.warning("角色弧线追踪失败: %s", exc)

            # Run chapter graph
            try:
                graph_result = chapter_graph.invoke(state)
                # Merge graph result back, preserving non-graph-managed fields
                # (obligation_tracker, brief_validator, debt_extractor, memory,
                #  chapters_text, novel_id, workspace, etc.)
                for key, value in graph_result.items():
                    state[key] = value
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
            # Guard: reject chapter text that is raw tool-call JSON
            if chapter_text and chapter_text.strip().startswith(
                ('{"thinking"', '{"tool"', '{"draft_preview"')
            ):
                log.error(
                    "第%d章文本包含原始工具调用JSON，跳过保存", ch_num
                )
                chapter_text = ""
            if chapter_text:
                # Get title: prefer revised outline title, fallback to extraction
                revised_outline = state.get("current_chapter_outline", ch_outline)
                ch_title = revised_outline.get("title", "") if isinstance(revised_outline, dict) else ch_outline.get("title", "")
                # Always sanitize outline-provided titles
                ch_title = _sanitize_title(ch_title, ch_num) if ch_title else ""
                if not ch_title or ch_title == f"第{ch_num}章":
                    ch_title = _extract_title_from_text(chapter_text, ch_num)

                # --- Hook Generator: evaluate and improve chapter ending ---
                try:
                    from src.novel.services.hook_generator import HookGenerator
                    from src.llm.llm_client import create_llm_client

                    hook_gen = HookGenerator(
                        llm_client=create_llm_client(get_stage_llm_config(state, "scene_writing"))
                    )
                    eval_result = hook_gen.evaluate(chapter_text)
                    if eval_result["needs_improvement"]:
                        log.info(
                            "第%d章结尾较弱 (评分%d, 类型%s)，尝试重写",
                            ch_num, eval_result["score"], eval_result["hook_type"]
                        )
                        new_ending = hook_gen.generate_hook(
                            chapter_text=chapter_text,
                            chapter_number=ch_num,
                            chapter_goal=ch_outline.get("goal", "") if ch_outline else "",
                        )
                        if new_ending:
                            chapter_text = hook_gen.replace_ending(chapter_text, new_ending)
                            log.info("第%d章结尾已优化", ch_num)
                except Exception as exc:
                    log.warning("钩子生成失败 (非关键): %s", exc)

                ch_data = {
                    "chapter_number": ch_num,
                    "title": ch_title,
                    "full_text": chapter_text,
                    "word_count": count_words(chapter_text),
                    "status": "draft",
                }
                fm.save_chapter(novel_id, ch_num, ch_data)

                # Backfill outline for placeholder chapters
                self._backfill_outline_entry(state, ch_num, chapter_text)

                # Validate transition from previous chapter
                if ch_num > 1:
                    try:
                        prev_text = state.get("chapters_text", {}).get(ch_num - 1, "")
                        if not prev_text:
                            from src.novel.storage.file_manager import FileManager
                            _fm_t = FileManager(self.workspace)
                            prev_text = _fm_t.load_chapter_text(novel_id, ch_num - 1) or ""

                        if prev_text and chapter_text:
                            prev_ending = prev_text.strip()[-200:]
                            cur_opening = chapter_text.strip()[:200]
                            # Simple heuristic: check if opening references previous ending
                            # Extract key nouns from prev_ending (3+ char Chinese words)
                            import re
                            prev_keywords = set(re.findall(r'[\u4e00-\u9fa5]{3,}', prev_ending))
                            cur_keywords = set(re.findall(r'[\u4e00-\u9fa5]{3,}', cur_opening))
                            common = prev_keywords & cur_keywords
                            if not common and len(prev_keywords) > 3:
                                log.warning(
                                    "第%d章衔接警告: 开头与上章结尾无共同关键词 (上章末尾: %s...)",
                                    ch_num, prev_ending[:50]
                                )
                                state.setdefault("decisions", []).append({
                                    "step": "transition_check",
                                    "decision": f"第{ch_num}章可能存在衔接问题",
                                    "reason": f"开头未引用上章结尾的关键元素",
                                })
                    except Exception as exc:
                        log.debug("衔接验证失败 (非关键): %s", exc)

                # Backfill actual_summary to outline for future planning
                actual_summary = ""
                try:
                    actual_summary = self._generate_actual_summary(
                        chapter_text, ch_num, ch_title, state=state
                    )
                    if actual_summary:
                        for i, och in enumerate(outline.get("chapters", [])):
                            if och.get("chapter_number") == ch_num:
                                outline["chapters"][i]["actual_summary"] = actual_summary
                                break
                except Exception as exc:
                    log.warning("第%d章实际摘要生成失败: %s", ch_num, exc)

                # Update character arc tracker from this chapter's events
                try:
                    arc_tracker = state.get("_arc_tracker")
                    if arc_tracker is not None and actual_summary:
                        arc_tracker.update_from_chapter(
                            chapter_number=ch_num,
                            actual_summary=actual_summary,
                            characters=state.get("characters", []),
                        )
                        # Persist arc states to novel.json
                        try:
                            novel_persist = fm.load_novel(novel_id) or {}
                            novel_persist["character_arc_states"] = arc_tracker.to_dict()["states"]
                            fm.save_novel(novel_id, novel_persist)
                        except Exception:
                            pass
                except Exception as exc:
                    log.warning("第%d章角色弧线更新失败: %s", ch_num, exc)

                # Update chapters list in state (replace stale entry or append)
                chapters = state.get("chapters") or []
                replaced = False
                for i, existing_ch in enumerate(chapters):
                    if existing_ch.get("chapter_number") == ch_num:
                        chapters[i] = ch_data
                        replaced = True
                        break
                if not replaced:
                    chapters.append(ch_data)
                state["chapters"] = chapters

                # Maintain chapters_text for consistency checker
                chapters_text = state.get("chapters_text", {})
                chapters_text[ch_num] = chapter_text
                state["chapters_text"] = chapters_text

                # Note: character snapshots, world updates, foreshadowing marking
                # are now handled by the state_writeback node inside the graph.

                # --- Narrative Control: persist state_writeback changes ---
                # Save updated characters/world_setting back to novel.json
                try:
                    novel_persist = fm.load_novel(novel_id) or {}
                    if state.get("characters"):
                        novel_persist["characters"] = state["characters"]
                    if state.get("world_setting"):
                        novel_persist["world_setting"] = state["world_setting"]
                    fm.save_novel(novel_id, novel_persist)
                except Exception as exc:
                    log.debug("状态回写持久化失败: %s", exc)

                # --- Narrative Control: index chapter for vector consistency check ---
                if getattr(self, "memory", None):
                    try:
                        from src.novel.models.memory import ChapterSummary
                        from src.novel.tools.chapter_digest import create_digest

                        digest = create_digest(chapter_text)
                        summary_text = digest.get("digest_text", "") or chapter_text[:500]
                        # Ensure summary meets ChapterSummary validation (min 50 chars)
                        if len(summary_text) < 50:
                            summary_text = chapter_text[:500] if len(chapter_text) >= 50 else chapter_text + "。" * (50 - len(chapter_text))

                        # Extract key events from digest
                        key_events = digest.get("key_sentences", [])[:5]
                        if not key_events:
                            key_events = [summary_text[:100]]

                        summary = ChapterSummary(
                            chapter=ch_num,
                            summary=summary_text,
                            key_events=key_events,
                        )
                        self.memory.add_chapter_summary(summary)
                        self.memory.save()
                    except Exception as exc:
                        log.debug("章节向量索引失败: %s", exc)

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

        if progress_callback:
            progress_callback(1.0, f"章节生成完成 ({len(chapters_generated)}章)")

        result = {
            "novel_id": novel_id,
            "chapters_generated": chapters_generated,
            "total_generated": len(chapters_generated),
            "errors": state.get("errors", []),
        }

        # --- Narrative Control: include debt statistics ---
        if obligation_tracker:
            try:
                result["debt_statistics"] = obligation_tracker.get_debt_statistics()
            except Exception:
                pass

        # --- Cleanup: close NovelMemory ---
        if getattr(self, "memory", None):
            try:
                self.memory.close()
            except Exception:
                pass
            self.memory = None

        return result

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
        from src.novel.tools.style_analysis_tool import StyleAnalysisTool
        from src.novel.tools.quality_check_tool import QualityCheckTool

        novel_id = Path(project_path).name
        fm = self._get_file_manager()
        style_tool = StyleAnalysisTool()
        quality_tool = QualityCheckTool()

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
        llm_config = get_stage_llm_config(state, "scene_writing")
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
                # Step 0: 改前指标（零成本，纯规则）
                before_style = style_tool.analyze(chapter_text)
                before_rules = quality_tool.rule_check(chapter_text)

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

                # Step 3: 改后指标（零成本，纯规则）
                after_style = style_tool.analyze(polished_text)
                after_rules = quality_tool.rule_check(polished_text)

                # 解析审稿意见分类
                issues = _parse_critique_issues(critique)

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
                    "critique_full": critique,
                    "issues": issues,
                    "before_style": before_style.model_dump(),
                    "after_style": after_style.model_dump(),
                    "before_rules": before_rules.model_dump(),
                    "after_rules": after_rules.model_dump(),
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
        rewrite_instructions: dict | None = None,
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
        fm = self._get_file_manager()
        state = self._load_checkpoint(novel_id)
        if state is None:
            raise FileNotFoundError(f"找不到项目检查点: {project_path}")

        # ★ Refresh settings from novel.json (edit_service writes there)
        self._refresh_state_from_novel(state, fm.load_novel(novel_id))

        # Initialize LLM (quality_review for analysis, scene_writing for rewrite)
        llm_config = get_stage_llm_config(state, "quality_review")
        llm = create_llm_client(llm_config)

        # Analyze feedback (or use pre-computed instructions)
        outline_chapters = state.get("outline", {}).get("chapters", [])
        characters = state.get("characters", [])

        if rewrite_instructions:
            # Skip LLM analysis — use user-approved instructions directly
            log.info("使用预设重写指令，跳过 LLM 分析")
            # Parse chapter numbers from instruction keys
            target_chs = sorted(int(k) for k in rewrite_instructions.keys() if str(k).isdigit())
            analysis = {
                "feedback_type": "user_approved",
                "severity": "medium",
                "target_chapters": target_chs,
                "propagation_chapters": [],
                "rewrite_instructions": rewrite_instructions,
                "summary": feedback_text,
            }
        else:
            if progress_callback:
                progress_callback(0.1, "正在分析反馈...")
            analyzer = FeedbackAnalyzer(llm)
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

        # Prepare writer (with scene_writing model)
        writer_llm_config = get_stage_llm_config(state, "scene_writing")
        writer_llm = create_llm_client(writer_llm_config)
        writer = Writer(writer_llm)

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
        chapters_done = state.get("chapters") or []
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

        # Filter out published chapters — they must not be auto-rewritten
        _novel_data = fm.load_novel(novel_id) or {}
        published_chapters = set(_novel_data.get("published_chapters", []))
        skipped_published = [ch for ch in rewrite_queue if ch in published_chapters]
        if skipped_published:
            log.warning(
                "跳过已发布章节的重写: %s（如需修改请先取消发布）",
                skipped_published,
            )
            result.setdefault("skipped_published", skipped_published)
            rewrite_queue = [ch for ch in rewrite_queue if ch not in published_chapters]

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

                # Save rewritten chapter (text + json metadata)
                raw_title = ch_outline_data.get("title", f"第{ch_num}章")
                ch_json = {
                    "chapter_number": ch_num,
                    "title": _sanitize_title(raw_title, ch_num),
                    "full_text": new_text,
                    "word_count": len(new_text),
                    "status": "draft",
                }
                # Extract better title if current is placeholder
                if ch_json["title"] == f"第{ch_num}章":
                    ch_json["title"] = _extract_title_from_text(new_text, ch_num)
                fm.save_chapter(novel_id, ch_num, ch_json)
                chapter_texts[ch_num] = new_text  # update for subsequent chapters' context

                # Also update state chapters list
                for ch_data in state.get("chapters") or []:
                    if ch_data.get("chapter_number") == ch_num:
                        ch_data["full_text"] = new_text
                        ch_data["word_count"] = len(new_text)
                        ch_data["title"] = ch_json["title"]
                        break

                result["rewritten_chapters"].append(
                    {
                        "chapter_number": ch_num,
                        "title": ch_json["title"],
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

        # Save updated state to checkpoint after rewrites
        if result.get("rewritten_chapters"):
            try:
                self._save_checkpoint(novel_id, state)
            except Exception:
                pass

        return result

    # ------------------------------------------------------------------
    # Chapter editing & AI proofreading
    # ------------------------------------------------------------------

    def proofread_chapter(
        self,
        project_path: str,
        chapter_number: int,
        text: str | None = None,
    ) -> list[dict]:
        """AI 校对章节，返回问题列表（不修改文本）。

        Args:
            project_path: 项目路径
            chapter_number: 章节号
            text: 如果提供则校对此文本，否则从文件加载

        Returns:
            问题列表（dict 格式，Gradio 友好）
        """
        from src.llm.llm_client import create_llm_client
        from src.novel.services.proofreader import Proofreader

        novel_id = Path(project_path).name
        fm = self._get_file_manager()

        if text is None:
            text = fm.load_chapter_text(novel_id, chapter_number)
            if not text:
                return []

        # 从 checkpoint 获取 LLM 配置，fallback 到 auto
        state = self._load_checkpoint(novel_id)
        llm_config = (
            get_stage_llm_config(state, "quality_review") if state else {}
        )
        llm = create_llm_client(llm_config)

        proofreader = Proofreader(llm)
        issues = proofreader.proofread(text)

        # 转为 dict 格式（Gradio 友好）
        return [
            {
                "index": i,
                "issue_type": issue.issue_type.value,
                "original": issue.original,
                "correction": issue.correction,
                "explanation": issue.explanation,
            }
            for i, issue in enumerate(issues)
        ]

    def apply_proofreading_fixes(
        self,
        project_path: str,
        chapter_number: int,
        text: str,
        issues: list[dict],
        selected_indices: list[int],
    ) -> tuple[str, list[str]]:
        """应用校对修正。

        Args:
            project_path: 项目路径
            chapter_number: 章节号
            text: 当前文本
            issues: 问题列表（dict 格式）
            selected_indices: 用户选中的问题索引

        Returns:
            (修正后的文本, 失败的修正描述列表)
        """
        from src.novel.models.refinement import (
            ProofreadingIssue,
            ProofreadingIssueType,
        )
        from src.novel.services.proofreader import Proofreader

        parsed_issues: list[ProofreadingIssue] = []
        for item in issues:
            parsed_issues.append(
                ProofreadingIssue(
                    issue_type=ProofreadingIssueType(item["issue_type"]),
                    original=item["original"],
                    correction=item["correction"],
                    explanation=item.get("explanation", ""),
                )
            )

        return Proofreader.apply_fixes(text, parsed_issues, selected_indices)

    def save_edited_chapter(
        self,
        project_path: str,
        chapter_number: int,
        text: str,
    ) -> dict:
        """保存人工编辑的章节文本（自动备份旧版本）。

        Args:
            project_path: 项目路径
            chapter_number: 章节号
            text: 新的章节文本

        Returns:
            保存结果信息
        """
        novel_id = Path(project_path).name
        fm = self._get_file_manager()

        # 备份当前版本
        old_text = fm.load_chapter_text(novel_id, chapter_number)
        if old_text:
            fm.save_chapter_revision(
                novel_id,
                chapter_number,
                old_text,
                metadata={"source": "before_human_edit"},
            )

        # 保存新文本
        fm.save_chapter_text(novel_id, chapter_number, text)

        return {
            "saved": True,
            "chapter_number": chapter_number,
            "char_count": len(text),
            "old_char_count": len(old_text) if old_text else 0,
        }

    # ------------------------------------------------------------------
    # Setting revision (影响分析 / 保存 / 重写)
    # ------------------------------------------------------------------

    def analyze_setting_impact(
        self,
        project_path: str,
        modified_field: str,
        new_value_json: str,
    ) -> dict:
        """分析设定修改对已写章节的影响。

        Args:
            project_path: 项目路径
            modified_field: "world_setting" | "characters" | "outline"
            new_value_json: 新值的 JSON 字符串
        """
        from src.llm.llm_client import create_llm_client
        from src.novel.services.setting_impact_analyzer import (
            SettingImpactAnalyzer,
        )

        novel_id = Path(project_path).name
        fm = self._get_file_manager()
        novel_data = fm.load_novel(novel_id)
        if novel_data is None:
            return {"error": f"找不到项目: {project_path}"}

        # 获取旧值
        if modified_field == "world_setting":
            old_value = json.dumps(
                novel_data.get("world_setting", {}),
                ensure_ascii=False,
                indent=2,
            )
        elif modified_field == "characters":
            old_value = json.dumps(
                novel_data.get("characters", []),
                ensure_ascii=False,
                indent=2,
            )
        elif modified_field == "outline":
            old_value = json.dumps(
                novel_data.get("outline", {}),
                ensure_ascii=False,
                indent=2,
            )
        else:
            return {"error": f"未知的设定字段: {modified_field}"}

        # 从 checkpoint 获取 LLM 配置，fallback 到 auto
        state = self._load_checkpoint(novel_id)
        llm_config = (
            get_stage_llm_config(state, "consistency_check") if state else {}
        )
        llm = create_llm_client(llm_config)

        analyzer = SettingImpactAnalyzer(llm, fm)
        return analyzer.analyze_impact(
            novel_id, novel_data, modified_field, old_value, new_value_json
        )

    def save_setting(
        self,
        project_path: str,
        modified_field: str,
        new_value_json: str,
    ) -> dict:
        """保存设定修改（自动备份旧版本）。

        Args:
            project_path: 项目路径
            modified_field: "world_setting" | "characters" | "outline"
            new_value_json: 新值的 JSON 字符串
        """
        import shutil
        from datetime import datetime

        novel_id = Path(project_path).name
        fm = self._get_file_manager()
        novel_data = fm.load_novel(novel_id)
        if novel_data is None:
            return {"error": f"找不到项目: {project_path}"}

        # 备份当前 novel.json
        novel_json_path = fm._novel_dir(novel_id) / "novel.json"
        backup_path_str: str | None = None
        if novel_json_path.exists():
            backup_dir = fm._novel_dir(novel_id) / "revisions"
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"novel_backup_{timestamp}.json"
            shutil.copy2(novel_json_path, backup_path)
            backup_path_str = str(backup_path)

        # 应用修改
        new_data = json.loads(new_value_json)

        if modified_field == "world_setting":
            novel_data["world_setting"] = new_data
        elif modified_field == "characters":
            novel_data["characters"] = new_data
        elif modified_field == "outline":
            novel_data["outline"] = new_data
        else:
            return {"error": f"未知的设定字段: {modified_field}"}

        # 更新时间戳
        novel_data["updated_at"] = datetime.now().isoformat()

        # 保存
        fm.save_novel(novel_id, novel_data)

        return {
            "saved": True,
            "modified_field": modified_field,
            "backup_path": backup_path_str,
        }

    def rewrite_affected_chapters(
        self,
        project_path: str,
        impact: dict,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> dict:
        """根据影响评估结果，重写受影响的章节。"""
        from src.llm.llm_client import create_llm_client
        from src.novel.agents.writer import Writer
        from src.novel.models.character import CharacterProfile
        from src.novel.models.novel import ChapterOutline
        from src.novel.models.world import WorldSetting

        novel_id = Path(project_path).name
        fm = self._get_file_manager()
        novel_data = fm.load_novel(novel_id)
        if novel_data is None:
            return {"rewritten": [], "errors": [f"找不到项目: {project_path}"]}

        affected = impact.get("affected_chapters", [])
        if not affected:
            return {"rewritten": [], "errors": []}

        # 从 checkpoint 获取 LLM 配置
        state = self._load_checkpoint(novel_id)
        llm_config = (
            get_stage_llm_config(state, "scene_writing") if state else {}
        )
        llm = create_llm_client(llm_config)
        writer = Writer(llm)

        # 构建冲突信息 map
        conflict_map: dict[int, list[dict]] = {}
        for c in impact.get("conflicts", []):
            ch = c.get("chapter_number")
            if ch:
                conflict_map.setdefault(ch, []).append(c)

        # 大纲 chapter map
        outline = novel_data.get("outline", {})
        outline_chapters = {
            co["chapter_number"]: co
            for co in outline.get("chapters", [])
            if isinstance(co, dict) and "chapter_number" in co
        }

        # 角色 / 世界观
        char_profiles: list[CharacterProfile] = []
        for c in novel_data.get("characters", []):
            try:
                char_profiles.append(
                    CharacterProfile(**c) if isinstance(c, dict) else c
                )
            except Exception:
                pass

        world_data = novel_data.get("world_setting")
        if world_data and isinstance(world_data, dict):
            try:
                world_setting = WorldSetting(**world_data)
            except Exception:
                world_setting = WorldSetting(era="未知", location="未知")
        else:
            world_setting = WorldSetting(era="未知", location="未知")

        style_name = novel_data.get(
            "style_name", "webnovel.shuangwen"
        )

        rewritten: list[dict] = []
        errors: list[str] = []

        for i, ch_num in enumerate(affected):
            if progress_callback:
                progress_callback(i / len(affected), f"重写第{ch_num}章...")

            try:
                old_text = fm.load_chapter_text(novel_id, ch_num)
                if not old_text:
                    errors.append(f"第{ch_num}章: 文本不存在")
                    continue

                # 备份
                fm.save_chapter_revision(
                    novel_id,
                    ch_num,
                    old_text,
                    metadata={"source": "before_setting_rewrite"},
                )

                # 构建重写指令
                conflicts = conflict_map.get(ch_num, [])
                instruction = f"设定已修改（{impact.get('summary', '')}）。"
                if conflicts:
                    for c in conflicts:
                        instruction += (
                            f"\n- 矛盾: {c['reason']}。"
                            f"建议: {c.get('suggested_fix', '按新设定调整')}"
                        )

                co_data = outline_chapters.get(ch_num)
                if not co_data:
                    errors.append(f"第{ch_num}章: 大纲不存在")
                    continue

                try:
                    co = ChapterOutline(**co_data)
                except Exception:
                    errors.append(f"第{ch_num}章: 大纲解析失败")
                    continue

                # 获取上下文
                context = ""
                if ch_num > 1:
                    prev_text = fm.load_chapter_text(novel_id, ch_num - 1)
                    if prev_text:
                        context = prev_text[-2000:]

                new_text = writer.rewrite_chapter(
                    original_text=old_text,
                    rewrite_instruction=instruction,
                    chapter_outline=co,
                    characters=char_profiles,
                    world_setting=world_setting,
                    context=context,
                    style_name=style_name,
                    is_propagation=True,
                )

                fm.save_chapter_text(novel_id, ch_num, new_text)
                rewritten.append(
                    {
                        "chapter_number": ch_num,
                        "old_chars": len(old_text),
                        "new_chars": len(new_text),
                    }
                )
            except Exception as e:
                log.error("重写第%d章失败: %s", ch_num, e)
                errors.append(f"第{ch_num}章: {e}")

        return {"rewritten": rewritten, "errors": errors}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_chapter_outline(self, outline: dict, chapter_number: int) -> dict | None:
        """Get chapter outline by chapter number."""
        for ch in outline.get("chapters", []):
            if ch.get("chapter_number") == chapter_number:
                return ch
        return None

    @staticmethod
    @staticmethod
    def _is_placeholder_outline(ch_outline: dict) -> bool:
        """Check if a chapter outline is a placeholder (not yet planned)."""
        goal = ch_outline.get("goal", "")
        key_events = ch_outline.get("key_events", [])
        title = ch_outline.get("title", "")
        # Placeholder patterns: goal is "待规划", key_events is ["待规划"], or title is just "第N章"
        if goal == "待规划":
            return True
        if key_events == ["待规划"]:
            return True
        if not goal and not key_events:
            return True
        # Generic title + no actual_summary + no meaningful goal = placeholder
        import re
        if (re.match(r"^第\d+章\s*$", title.strip())
                and not ch_outline.get("actual_summary")
                and not goal):
            return True
        return False

    def _fill_placeholder_outline(self, state: dict, ch_outline: dict, ch_num: int) -> dict:
        """Use LLM to fill in a placeholder chapter outline with proper details.

        Generates title, goal, key_events, mood based on the overall story arc,
        previous chapters, and main storyline.
        """
        from src.llm.llm_client import create_llm_client
        from src.novel.llm_utils import get_stage_llm_config

        try:
            llm_config = get_stage_llm_config(state, "outline_generation")
            llm = create_llm_client(llm_config)
        except Exception as exc:
            log.warning("LLM 不可用，无法补全大纲: %s", exc)
            return ch_outline

        outline_data = state.get("outline", {})
        main_storyline = outline_data.get("main_storyline", {}) or state.get("main_storyline", {})
        total_chapters = len(outline_data.get("chapters", []))

        # Gather previous chapter context — prefer actual text over outline goals
        prev_summaries = []
        novel_id = state.get("novel_id")
        fm = None
        if novel_id:
            try:
                from src.novel.storage.file_manager import FileManager
                ws = state.get("workspace") or getattr(self, "workspace", None)
                if ws:
                    fm = FileManager(ws)
            except Exception:
                fm = None

        for ch in outline_data.get("chapters", []):
            ch_n = ch.get("chapter_number", 0)
            if ch_n >= ch_num or (ch.get("goal", "") == "待规划" and ch_n < ch_num):
                continue

            # Try to load actual chapter text for recent chapters (last 5)
            if fm and novel_id and ch_n >= ch_num - 5:
                try:
                    txt = fm.load_chapter_text(novel_id, ch_n)
                    if txt and len(txt) > 100:
                        # Extract ending (last 300 chars) for continuity
                        ending = txt[-300:].strip()
                        prev_summaries.append(
                            f"第{ch_n}章「{ch.get('title', '')}」\n"
                            f"  大纲目标: {ch.get('goal', '')[:60]}\n"
                            f"  实际结尾: ...{ending}"
                        )
                        continue
                except Exception:
                    pass

            # Fallback: use outline goal or actual_summary
            actual = ch.get("actual_summary", "")
            goal = ch.get("goal", "")
            summary_text = actual if actual else goal
            if summary_text:
                label = "实际发生" if actual else "计划目标"
                prev_summaries.append(
                    f"第{ch_n}章「{ch.get('title', '')}」({label}): {summary_text}"
                )

        recent_context = "\n\n".join(prev_summaries[-5:]) if prev_summaries else "暂无前文"

        # Volume info
        volume_info = ""
        for vol in outline_data.get("volumes", []):
            vol_chapters = vol.get("chapters", [])
            if ch_num in vol_chapters:
                volume_info = (
                    f"当前卷: {vol.get('title', '')} "
                    f"(核心冲突: {vol.get('core_conflict', '')})"
                )
                break

        # Anti-repetition: events already planned in this batch
        batch_ctx = state.get("_batch_planned_context", [])
        batch_section = ""
        if batch_ctx:
            batch_section = "\n已规划章节（不要重复这些事件）:\n" + "\n".join(batch_ctx)

        prompt = f"""请为第{ch_num}章（共{total_chapters}章）补全详细大纲。

{f"主线信息: 主角目标={main_storyline.get('protagonist_goal', '')}, 核心冲突={main_storyline.get('core_conflict', '')}" if main_storyline else ""}
{volume_info}

前文概要（注意区分"大纲目标"和"实际结尾"——以实际结尾为准）:
{recent_context}
{batch_section}

【重要约束】
1. 仔细阅读上方"实际结尾"部分，本章必须从那里接续，推进到新的情节
2. 前面章节已经完成的事件（如制度落地、内鬼抓获、矿道封锁等）不要重复
3. 本章必须让故事产生实质性进展，不能停留在同一个场景重复同样的事
4. 标题必须具体，不能用"第N章"这种格式

请严格按 JSON 格式返回:
{{
  "title": "具体的章节标题（不要用'第N章'这种格式）",
  "goal": "本章要推进的核心目标（一句话）",
  "key_events": ["关键事件1", "关键事件2", "关键事件3"],
  "mood": "蓄力/小爽/大爽/过渡/虐心/反转/日常（选一个）",
  "chapter_summary": "本章概要（2-3句话）"
}}"""

        try:
            response = llm.chat(
                messages=[
                    {"role": "system", "content": "你是一位专业的网文大纲规划师。根据前文和主线信息，为指定章节补全详细大纲。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                json_mode=True,
                max_tokens=1024,
            )

            from src.novel.agents.utils import extract_json_obj
            result = extract_json_obj(response.content)
            if result:
                title = result.get("title") or ch_outline.get("title") or f"第{ch_num}章"
                goal = result.get("goal") or ch_outline.get("goal") or "承接前文，推进主线"
                key_events = result.get("key_events") or ch_outline.get("key_events") or ["承接前文"]
                mood = result.get("mood") or ch_outline.get("mood") or "蓄力"
                # Validate: ChapterOutline requires min_length=1 for title/goal, and key_events non-empty
                if not title or title == f"第{ch_num}章":
                    title = goal[:20] if goal else f"第{ch_num}章·续"
                if isinstance(key_events, list) and len(key_events) == 0:
                    key_events = [goal or "推进主线"]
                # Validate mood is a valid literal
                valid_moods = {"蓄力", "小爽", "大爽", "过渡", "虐心", "反转", "日常"}
                if mood not in valid_moods:
                    mood = "蓄力"
                ch_outline["title"] = title
                ch_outline["goal"] = goal
                ch_outline["key_events"] = key_events
                ch_outline["mood"] = mood
                ch_outline["chapter_summary"] = result.get("chapter_summary", "")
                log.info("第%d章大纲补全成功: 「%s」", ch_num, ch_outline["title"])
            else:
                log.warning("第%d章大纲补全失败: LLM 返回无法解析", ch_num)
                # Set safe defaults so pipeline can still proceed
                if not ch_outline.get("goal") or ch_outline["goal"] == "待规划":
                    ch_outline["goal"] = "承接前文，推进主线"
                if not ch_outline.get("key_events") or ch_outline["key_events"] == ["待规划"]:
                    ch_outline["key_events"] = ["承接前文"]
        except Exception as exc:
            log.warning("第%d章大纲补全异常: %s", ch_num, exc)

        return ch_outline

    # ------------------------------------------------------------------
    # resize_novel — change total chapter count
    # ------------------------------------------------------------------

    def resize_novel(
        self,
        project_path: str,
        new_total: int,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> dict:
        """Resize a novel's outline to *new_total* chapters.

        - **Expand** (new_total > current): uses ``_extend_outline()`` to
          generate additional volume outlines via LLM.
        - **Shrink** (new_total < current): truncates the outline, keeping
          only the first *new_total* chapter entries.  Already-written
          chapter files are **not** deleted (they remain on disk for safety).

        Returns a summary dict with old/new counts.
        """
        novel_id = Path(project_path).name
        fm = self._get_file_manager()
        state = self._load_checkpoint(novel_id)
        if state is None:
            raise FileNotFoundError(f"找不到项目检查点: {project_path}")

        outline = state.get("outline")
        if not outline:
            raise ValueError("项目大纲不存在")

        chapters = outline.get("chapters", [])
        old_total = len(chapters)

        if new_total < 1:
            raise ValueError("目标章节数必须 >= 1")

        if new_total == old_total:
            return {"novel_id": novel_id, "old_total": old_total, "new_total": old_total, "action": "none"}

        if new_total > old_total:
            # Expand
            self._extend_outline(novel_id, state, new_total, progress_callback)
            action = "expanded"
        else:
            # Shrink — truncate outline entries beyond new_total
            outline["chapters"] = chapters[:new_total]
            state["outline"] = outline
            action = "shrunk"

        # Update novel.json
        novel_data = fm.load_novel_json(novel_id)
        novel_data["outline"] = state["outline"]
        novel_data["total_chapters"] = len(state["outline"].get("chapters", []))
        fm.save_novel_json(novel_id, novel_data)

        # Save checkpoint
        self._save_checkpoint(novel_id, state)

        final_total = len(state["outline"].get("chapters", []))
        log.info("小说 %s 章节数调整: %d → %d (%s)", novel_id, old_total, final_total, action)

        return {
            "novel_id": novel_id,
            "old_total": old_total,
            "new_total": final_total,
            "action": action,
        }

    # ------------------------------------------------------------------
    # Outline extension (volume-based generation for long novels)
    # ------------------------------------------------------------------

    def _extend_outline(
        self,
        novel_id: str,
        state: dict,
        target_chapter: int,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> None:
        """Extend the outline to cover up to *target_chapter*.

        For long novels whose initial outline only covers the first volume,
        this method dynamically generates chapter outlines for subsequent
        volumes using ``NovelDirector.generate_volume_outline``.

        The *state* dict is mutated in-place (outline.chapters extended) and
        the checkpoint + novel.json are saved after each volume expansion.
        """
        from src.novel.agents.novel_director import NovelDirector, _CHAPTERS_PER_VOLUME
        from src.llm.llm_client import create_llm_client

        llm_config = get_stage_llm_config(state, "outline_generation")
        llm = create_llm_client(llm_config)
        director = NovelDirector(llm)
        fm = self._get_file_manager()

        outline = state.get("outline", {})
        chapters = outline.get("chapters", [])
        outline_max = max(
            (ch.get("chapter_number", 0) for ch in chapters), default=0
        )
        chapters_per_volume = _CHAPTERS_PER_VOLUME

        while outline_max < target_chapter:
            # Determine which volume to generate next.
            # outline_max is the highest chapter number we already have.
            # E.g. outline_max=30 with 30 chapters/vol means volume 1 is
            # complete, so the next volume is 2.
            current_volume = ((outline_max - 1) // chapters_per_volume) + 1 if outline_max > 0 else 0
            next_volume = current_volume + 1

            if progress_callback:
                progress_callback(
                    0.0,
                    f"正在生成第{next_volume}卷大纲 (第{outline_max + 1}章起)...",
                )

            # Build a summary of previously written content
            previous_summary = self._build_previous_summary(
                novel_id, fm, outline_max
            )

            # Load full novel data so the director can see world/character info
            novel_data = fm.load_novel(novel_id) or {}
            # Ensure the latest outline is in novel_data (state may be more recent)
            novel_data["outline"] = outline

            # Generate new volume outline
            new_chapters = director.generate_volume_outline(
                novel_data=novel_data,
                volume_number=next_volume,
                previous_summary=previous_summary,
            )

            # Append to outline chapters
            existing_nums = {ch.get("chapter_number", 0) for ch in chapters}
            for ch_data in new_chapters:
                ch_num = ch_data.get("chapter_number", 0)
                if ch_num not in existing_nums:
                    chapters.append(ch_data)
                    existing_nums.add(ch_num)

            # Re-sort
            chapters.sort(key=lambda c: c.get("chapter_number", 0))
            outline["chapters"] = chapters
            state["outline"] = outline

            outline_max = max(
                (ch.get("chapter_number", 0) for ch in chapters), default=0
            )

            # Persist
            self._save_checkpoint(novel_id, state)
            novel_data["outline"] = outline
            fm.save_novel(novel_id, novel_data)

            log.info("大纲已扩展至第 %d 章 (卷%d)", outline_max, next_volume)

    def _build_previous_summary(
        self, novel_id: str, fm: "FileManager", up_to_chapter: int
    ) -> str:
        """Build a concise summary of previously written chapters.

        Reads chapter texts (up to *up_to_chapter*) and condenses each into
        a short excerpt to stay within reasonable token limits.
        """
        summaries: list[str] = []
        written_chapters = fm.list_chapters(novel_id)
        for ch_num in sorted(written_chapters):
            if ch_num > up_to_chapter:
                break
            text = fm.load_chapter_text(novel_id, ch_num)
            if text:
                # Take the first ~200 chars as a summary
                preview = text.replace("\n", " ").strip()[:200]
                summaries.append(f"第{ch_num}章: {preview}")
            if len(summaries) >= 30:
                # Cap to avoid token explosion
                summaries.append("...（更早章节省略）")
                break

        if not summaries:
            return "（尚未生成任何章节）"
        return "\n".join(summaries)

    @staticmethod
    def _extract_character_snapshot(char_name: str, text: str) -> dict[str, str]:
        """Heuristic: extract character state (location, health, emotion) from chapter text.

        Scans sentences containing *char_name* and matches keyword lists.
        Prefers later occurrences (closer to chapter end = more current state).
        """
        import re

        sentences = re.split(r'[。！？\n]', text)
        # Collect sentences that mention the character (reversed = last first)
        relevant = [s for s in reversed(sentences) if char_name in s]

        result: dict[str, str] = {
            "location": "",
            "health": "",
            "emotional_state": "",
            "power_level": "",
        }

        _LOCATION_KW = (
            "客栈", "酒楼", "山洞", "广场", "大殿", "密室", "街道", "城门",
            "书房", "卧室", "花园", "市集", "学院", "宫殿", "战场", "森林",
            "河边", "山顶", "谷底", "码头", "府邸", "府中", "院中", "门口",
            "城中", "城外", "山下", "洞中", "阵前", "殿中", "房间", "帐篷",
            "城池", "村庄", "小巷", "客房", "厅堂", "密道", "湖边", "崖边",
        )
        _INJURY_KW = (
            "重伤", "轻伤", "受伤", "吐血", "昏迷", "中毒", "虚弱",
            "伤势", "断臂", "失血", "濒死", "瘫倒",
        )
        _HEALTHY_KW = ("痊愈", "恢复", "无恙", "康复", "好转")
        _EMOTION_KW = {
            "愤怒": ("怒", "暴怒", "愤怒", "恼怒", "大怒"),
            "悲伤": ("悲", "痛哭", "泪", "哀", "悲伤", "悲痛", "哭泣"),
            "恐惧": ("恐惧", "害怕", "惊恐", "颤抖", "胆寒"),
            "喜悦": ("喜", "笑", "高兴", "欣慰", "开心", "大喜"),
            "焦虑": ("焦虑", "不安", "忧虑", "担忧", "焦急"),
            "坚定": ("坚定", "决心", "下定决心", "毅然", "义无反顾"),
            "震惊": ("震惊", "惊讶", "愕然", "大惊", "骇然"),
            "平静": ("平静", "淡然", "冷静", "从容"),
        }
        _POWER_KW = (
            "突破", "晋级", "进阶", "升级", "觉醒", "领悟", "化神",
            "筑基", "金丹", "元婴", "渡劫", "飞升", "凝气", "结丹",
        )

        for sent in relevant:
            # Location (first match wins since we iterate latest-first)
            if not result["location"]:
                for kw in _LOCATION_KW:
                    if kw in sent:
                        result["location"] = kw
                        break

            # Health
            if not result["health"]:
                for kw in _INJURY_KW:
                    if kw in sent:
                        result["health"] = kw
                        break
                if not result["health"]:
                    for kw in _HEALTHY_KW:
                        if kw in sent:
                            result["health"] = kw
                            break

            # Emotional state
            if not result["emotional_state"]:
                for emotion, keywords in _EMOTION_KW.items():
                    if any(kw in sent for kw in keywords):
                        result["emotional_state"] = emotion
                        break

            # Power level changes
            if not result["power_level"]:
                for kw in _POWER_KW:
                    if kw in sent:
                        result["power_level"] = kw
                        break

            # Stop early if all filled
            if all(result.values()):
                break

        return result

    def _generate_actual_summary(self, chapter_text: str, chapter_number: int, title: str, state: dict | None = None) -> str:
        """Generate a brief summary of what actually happened in a chapter.

        Used to backfill the outline so future planning has accurate context
        instead of relying on the planned goal which may diverge from reality.
        """
        if not chapter_text or len(chapter_text) < 50:
            return ""

        from src.llm.llm_client import create_llm_client
        from src.novel.llm_utils import get_stage_llm_config

        try:
            llm_config = get_stage_llm_config(state or {}, "outline_generation")
            llm = create_llm_client(llm_config)
        except Exception:
            # Fallback: use last 200 chars as summary
            return chapter_text[-200:].strip()

        # Use the ending portion for efficiency
        text_for_summary = chapter_text[-2000:] if len(chapter_text) > 2000 else chapter_text

        try:
            response = llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一位小说编辑助手。请用2-3句话总结本章实际发生的关键事件、"
                            "解决了什么问题、留下了什么悬念。重点描述结果而非过程。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"第{chapter_number}章「{title}」内容:\n{text_for_summary}\n\n"
                            f"请总结本章实际发生了什么（2-3句话）:"
                        ),
                    },
                ],
                temperature=0.3,
                max_tokens=256,
            )
            return response.content.strip() if response.content else ""
        except Exception:
            # Fallback
            return chapter_text[-200:].strip()

    @staticmethod
    def _backfill_outline_entry(state: dict, ch_num: int, chapter_text: str) -> None:
        """Update placeholder outline entries with data from generated chapter.

        When the LLM returns fewer chapters than requested during outline
        generation, missing slots are filled with placeholder data (title=
        "第N章", goal="待规划"). After a chapter is actually written, this
        method patches the outline entry so it reflects real content.

        IMPORTANT: Only patches title and chapter_summary. Does NOT overwrite
        goal or key_events with raw chapter text — doing so would pollute the
        outline and cause subsequent chapters to repeat the same content.
        """
        outline = state.get("outline")
        if not outline or not isinstance(outline, dict):
            return
        chapters = outline.get("chapters", [])
        for ch in chapters:
            if ch.get("chapter_number") != ch_num:
                continue
            # Only patch if it's still a placeholder
            if ch.get("goal") not in ("待规划", ""):
                return

            # Title: prefer current_chapter_outline's title (from dynamic_outline/PlotPlanner)
            cur_outline = state.get("current_chapter_outline", {})
            title = cur_outline.get("title", "")
            # Always sanitize outline-provided titles
            title = _sanitize_title(title, ch_num) if title else ""
            if not title or title == f"第{ch_num}章":
                # Extract a short title from the chapter text
                title = _extract_title_from_text(chapter_text, ch_num)
            ch["title"] = title

            # chapter_summary: short preview for display purposes only
            preview = chapter_text.replace("\n", " ").strip()[:100]
            ch["chapter_summary"] = preview + ("..." if len(chapter_text) > 100 else "")

            # goal: generate a functional goal, NOT raw text
            # Use current_chapter_outline goal if available (from _fill_placeholder)
            cur_goal = cur_outline.get("goal", "")
            if cur_goal and cur_goal != "待规划":
                ch["goal"] = cur_goal
            else:
                ch["goal"] = f"第{ch_num}章剧情推进"

            # key_events: keep existing if valid, otherwise minimal fallback
            existing_events = ch.get("key_events", [])
            if not existing_events or existing_events == ["待规划"]:
                cur_events = cur_outline.get("key_events", [])
                if cur_events and cur_events != ["待规划"]:
                    ch["key_events"] = cur_events
                else:
                    ch["key_events"] = [f"第{ch_num}章核心事件"]
            return
