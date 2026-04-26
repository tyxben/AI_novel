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
from src.novel.services.prev_tail_summarizer import summarize_previous_tail
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
    # Check the raw input (pre-strip) for dialogue openers so we don't
    # accidentally sanitize a stripped dialogue fragment into a "title".
    # Uses the module-level _DIALOGUE_OPENERS (left quotes only).
    _raw = title if isinstance(title, str) else ""
    _raw_stripped = _raw.strip()
    if _raw_stripped and _raw_stripped[0] in _DIALOGUE_OPENERS:
        return f"第{ch_num}章"

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

    # Reject overly long titles (likely a full sentence leaked through).
    # Relaxed from 15 to 25 chars: legitimate Chinese chapter titles can run
    # up to 15-20 chars (e.g. "林辰首战定州之——群山开疆始"). Anything beyond
    # 25 chars is almost certainly a full sentence leak.
    if len(title) > 25:
        return f"第{ch_num}章"

    # Reject titles that are just punctuation
    import re as _re_san
    if _re_san.fullmatch(r"[\s\W_]+", title):
        return f"第{ch_num}章"

    # Reject too short or empty
    if not title or len(title) < 2:
        return f"第{ch_num}章"

    return title


# Only LEFT-quote openers count as "start of a dialogue line".  U+201D (right
# double quote) and U+300D/U+300F (right corner brackets) at the start of a
# paragraph usually mean a closing quote got orphaned by a line break —
# typically a dialogue attribution fragment, not a new dialogue line.
_DIALOGUE_OPENERS = ('"', "\u201c", "\u300c", "\u300e")


def _is_dialogue_line(line: str) -> bool:
    """Return True if the line looks like pure dialogue (starts with a quote)."""
    s = line.strip()
    if not s:
        return False
    if s[0] in _DIALOGUE_OPENERS:
        return True
    return False


def _is_onomatopoeia(line: str) -> bool:
    """Return True if the line is a short sound effect / exclamation.

    e.g. "轰！", "咔嚓——", "砰！" — single/double Chinese char followed by
    onomatopoeia-style punctuation, no narrative content.

    NB: ``。`` (Chinese full stop) and ``…`` (ellipsis) are NOT sound-effect
    punctuation — every narrative sentence ends in ``。``.  Including them
    in the trigger set would misclassify short narrative lines like
    "启程。" or "林辰死了。" as onomatopoeia.  Only ``！`` / ``!`` / ``——``
    qualify.
    """
    import re as _re_o

    s = line.strip().strip("——!！？?。.…\u3000 ")
    if not s:
        return False
    # 1-3 Chinese chars only, plus trailing punctuation in the original
    if len(s) <= 3 and _re_o.fullmatch(r"[\u4e00-\u9fa5]+", s):
        # And the original line had trailing exclamation / dash punctuation
        orig = line.strip()
        if any(p in orig for p in ("！", "!", "——")):
            return True
    return False


def _extract_title_from_text(
    chapter_text: str, ch_num: int, ch_outline: dict | None = None
) -> str:
    """Extract a short, meaningful title from chapter text.

    Uses heuristics: finds the most "interesting" short phrase from the
    first few paragraphs — a character action, a location reveal, or a
    key event.

    Skips:
    - markdown headers (lines starting with ``#``)
    - chapter-number headers (``第N章 ...``)
    - pure dialogue lines (start with ``"``, ``"``, ``「``, ``『``)
    - short onomatopoeia / sound-effect lines (e.g. ``轰！``)

    Fallback chain:
    1. Narrative phrase from first ~5 lines (4-15 chars).
    2. Phrase derived from ``ch_outline["goal"]`` or ``key_events[0]``.
    3. Placeholder ``第N章`` as absolute last resort.
    """
    import re

    if not chapter_text or not chapter_text.strip():
        return _title_from_outline(ch_outline, ch_num)

    lines = [ln.strip() for ln in chapter_text.split("\n") if ln.strip()]
    if not lines:
        return _title_from_outline(ch_outline, ch_num)

    # Pass 1: pick a narrative phrase from first 5 non-skipped lines.
    narrative_lines: list[str] = []
    for line in lines[:8]:
        if line.startswith("#"):
            continue
        if re.match(r"^第\d+章", line):
            continue
        if _is_dialogue_line(line):
            continue
        if _is_onomatopoeia(line):
            continue
        if len(line) < 2:
            continue
        narrative_lines.append(line)
        if len(narrative_lines) >= 5:
            break

    for line in narrative_lines:
        # Split into sentences
        sentences = re.split(r"[。！？]", line)
        for sent in sentences:
            sent = sent.strip().strip("\"'\u201c\u201d\u300c\u300d\u300e\u300f")
            # Good narrative title candidate: 4-15 chars
            if 4 <= len(sent) <= 15:
                candidate = _sanitize_title(sent, ch_num)
                if candidate != f"第{ch_num}章":
                    return candidate

    # Pass 2: narrative line truncated at natural boundary.
    for line in narrative_lines:
        if len(line) > 10:
            for sep in ("，", "。", "！", "？", "、"):
                idx = line.find(sep)
                if 3 <= idx <= 15:
                    candidate = _sanitize_title(line[:idx], ch_num)
                    if candidate != f"第{ch_num}章":
                        return candidate
            candidate = _sanitize_title(line[:12], ch_num)
            if candidate != f"第{ch_num}章":
                return candidate
        if len(line) >= 4:
            candidate = _sanitize_title(line, ch_num)
            if candidate != f"第{ch_num}章":
                return candidate

    # Pass 3: outline-derived fallback.
    return _title_from_outline(ch_outline, ch_num)


def _title_from_outline(ch_outline: dict | None, ch_num: int) -> str:
    """Derive a short title from a chapter outline's goal or first key event.

    Used as the final non-placeholder fallback before returning ``第N章``.
    """
    import re as _re_o

    if not isinstance(ch_outline, dict):
        return f"第{ch_num}章"

    # Try goal first
    goal = (ch_outline.get("goal") or "").strip()
    if goal:
        # Cut to first natural phrase
        phrase = _re_o.split(r"[，,。.！!？?；;、]", goal)[0].strip()
        if 2 <= len(phrase) <= 12:
            candidate = _sanitize_title(phrase, ch_num)
            if candidate != f"第{ch_num}章":
                return candidate
        # Or take first 8 chars of goal
        candidate = _sanitize_title(goal[:8], ch_num)
        if candidate != f"第{ch_num}章":
            return candidate

    # Try key_events[0]
    key_events = ch_outline.get("key_events") or []
    if isinstance(key_events, list) and key_events:
        first = str(key_events[0] or "").strip()
        if first:
            phrase = _re_o.split(r"[，,。.！!？?；;、]", first)[0].strip()
            if 2 <= len(phrase) <= 12:
                candidate = _sanitize_title(phrase, ch_num)
                if candidate != f"第{ch_num}章":
                    return candidate
            candidate = _sanitize_title(first[:8], ch_num)
            if candidate != f"第{ch_num}章":
                return candidate

    return f"第{ch_num}章"


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

    def _dedupe_chapters_list(self, chapters: list) -> list:
        """Deduplicate ``state['chapters']`` by ``chapter_number``.

        Background: earlier runs could append regenerated chapter records on
        top of a stale list without upserting, leaving two or three entries
        per chapter number in a single checkpoint file. This helper is the
        single healing pass invoked on every checkpoint load and at the top
        of ``generate_chapters``, so any historical duplication self-heals
        automatically — it is idempotent and safe to run repeatedly.

        Rules:
        - Group entries by ``chapter_number``.
        - When a group has more than one entry, keep the one with the highest
          ``word_count`` (the most complete/most recently regenerated copy).
        - Sort the deduped result by ``chapter_number`` ascending.
        - Entries missing or with ``None`` ``chapter_number`` are preserved
          unchanged at the end of the list (defensive — do not drop weird
          data, just do not dedupe it).
        - The input list is not mutated.
        """
        if not isinstance(chapters, list) or not chapters:
            return list(chapters or [])

        with_num: dict[int, dict] = {}
        without_num: list = []

        for entry in chapters:
            if not isinstance(entry, dict):
                without_num.append(entry)
                continue
            ch_num = entry.get("chapter_number")
            if ch_num is None:
                without_num.append(entry)
                continue
            existing = with_num.get(ch_num)
            if existing is None:
                with_num[ch_num] = entry
                continue
            existing_wc = existing.get("word_count") or 0
            new_wc = entry.get("word_count") or 0
            if new_wc > existing_wc:
                with_num[ch_num] = entry

        deduped = sorted(
            with_num.values(),
            key=lambda c: c.get("chapter_number") or 0,
        )
        result = deduped + without_num

        before = len(chapters)
        after = len(result)
        if after < before:
            log.info("chapters 列表去重：%d → %d 条", before, after)
        return result

    @staticmethod
    def _upsert_rewritten_chapter(
        existing_chapters: list,
        ch_num: int,
        new_text: str,
        new_title: str,
    ) -> list:
        """Upsert a freshly-rewritten chapter into ``state['chapters']``.

        Used by ``apply_feedback`` when a chapter is rewritten from reader
        feedback. Wipes all existing entries for ``ch_num`` (defensively
        handling stale duplicates), builds a canonical new entry with
        invalidated quality fields, and returns a new sorted list.

        If no pre-existing entry is found for ``ch_num`` (e.g. the chapter
        exists on disk but ``state['chapters']`` was cleared/corrupted),
        a fresh entry is still constructed so the rewrite lands in state.

        Quality fields are explicitly nulled because the old scores were
        computed against the old text — ``rule_checked=False`` marks the
        chapter as "needs re-scoring".

        This helper is pure: ``existing_chapters`` is not mutated.
        """
        # Preserve any carry-over fields from the first existing entry
        # (e.g. chapter_id, generated_at), but we'll overwrite all the
        # content/quality fields below.
        new_entry: dict | None = None
        for ch_data in existing_chapters or []:
            if isinstance(ch_data, dict) and ch_data.get("chapter_number") == ch_num:
                new_entry = dict(ch_data)
                break
        if new_entry is None:
            new_entry = {"chapter_number": ch_num, "status": "draft"}
            log.info("第%d章在 state.chapters 中无原记录，新建条目", ch_num)

        new_entry["full_text"] = new_text
        new_entry["word_count"] = len(new_text)
        new_entry["title"] = new_title
        new_entry["quality_score"] = None
        new_entry["quality_scores"] = None
        new_entry["retention_scores"] = None
        new_entry["rule_passed"] = True
        new_entry["rule_checked"] = False
        new_entry["scored_by_llm"] = False

        remaining = [
            ch
            for ch in (existing_chapters or [])
            if not (isinstance(ch, dict) and ch.get("chapter_number") == ch_num)
        ]
        result = remaining + [new_entry]
        result.sort(
            key=lambda c: (c.get("chapter_number") or 0)
            if isinstance(c, dict)
            else 0
        )
        return result

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
        # Heal any historical duplication in the chapters list on every load.
        if "chapters" in data and isinstance(data["chapters"], list):
            data["chapters"] = self._dedupe_chapters_list(data["chapters"])
        # Drop stale LLM provider/model whose API key is no longer available
        # in the current environment.  Without this, every LLM call first
        # tries the stale provider, fails, prints a warning, and falls back
        # to auto-detect — wasting time and polluting logs.
        self._drop_stale_llm_provider(data)
        return data

    @staticmethod
    def _drop_stale_llm_provider(state: dict) -> None:
        """If the checkpoint's LLM provider has no usable API key in env,
        strip ``provider`` / ``model`` / ``api_key`` so ``create_llm_client``
        falls back to current ``config.yaml`` and env-based auto-detection.

        Mutates ``state`` in place.
        """
        import os

        llm_cfg = state.get("config", {}).get("llm")
        if not isinstance(llm_cfg, dict):
            return
        provider = llm_cfg.get("provider")
        if not provider or provider == "auto":
            return
        env_key_map = {
            "openai": "OPENAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "gemini": "GEMINI_API_KEY",
        }
        env_key = env_key_map.get(provider)
        # Unknown providers (e.g. ollama) and explicit api_key entries are
        # left alone — only purge when we *know* the env-key is required
        # and missing.
        if env_key is None:
            return
        if llm_cfg.get("api_key"):
            return
        if os.environ.get(env_key):
            return
        log.info(
            "Checkpoint provider %r has no %s in env; reverting to auto-detect.",
            provider,
            env_key,
        )
        for k in ("provider", "model", "api_key", "api_key_env", "base_url"):
            llm_cfg.pop(k, None)

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

        # Refresh style_bible (Intervention D)
        if "style_bible" in novel_data:
            state["style_bible"] = novel_data["style_bible"]

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
        # Phase 3-B3：outline 由 ProjectArchitect.propose_main_outline 生成，
        # novel_director_node 已删除。
        try:
            from src.novel.agents.project_architect import ProjectArchitect as _PA_Outline
            from src.llm.llm_client import create_llm_client as _create_llm_outline

            _outline_llm_cfg = get_stage_llm_config(state, "outline_generation")
            _outline_llm = _create_llm_outline(_outline_llm_cfg)
            _outline_architect = _PA_Outline(_outline_llm, config=self.config)

            outline_proposal = _outline_architect.propose_main_outline(
                genre=genre,
                theme=theme,
                target_words=target_words,
                template_name=template,
                style_name=style,
                custom_ideas=custom_ideas,
            )
            state["outline"] = outline_proposal.outline
            state["template"] = outline_proposal.template
            state["style_name"] = outline_proposal.style_name
            state["style_bible"] = outline_proposal.style_bible
            state["total_chapters"] = outline_proposal.total_chapters
            state["current_chapter"] = 0
            state["should_continue"] = True
            state.setdefault("decisions", []).extend(outline_proposal.decisions)
            if outline_proposal.errors:
                state.setdefault("errors", []).extend(outline_proposal.errors)
            state.setdefault("completed_nodes", []).append(
                "project_architect.main_outline"
            )
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

        # Phase 2-γ: 替换 world_builder / character_designer 节点调用为
        # ProjectArchitect propose → accept 链路。pipeline 对外 API 不变。
        from src.novel.agents.project_architect import ProjectArchitect
        from src.llm.llm_client import create_llm_client as _create_llm_pa

        architect_meta = {
            "genre": genre,
            "theme": theme,
            "target_words": target_words,
            "target_length_class": (
                "webnovel" if target_words >= 300_000
                else "novel" if target_words >= 80_000
                else "novella" if target_words >= 30_000
                else "short"
            ),
            "custom_ideas": custom_ideas,
        }
        synopsis_for_arch = (
            (state.get("outline") or {}).get("main_storyline", {}).get("protagonist_goal", "")
            if isinstance(state.get("outline"), dict) else ""
        )

        try:
            _arch_llm = _create_llm_pa(get_stage_llm_config(state, "character_design"))
            architect = ProjectArchitect(_arch_llm, config=self.config)
        except Exception as e:  # pragma: no cover - defensive
            log.warning("ProjectArchitect 初始化失败，退回旧 world/character 节点: %s", e)
            architect = None

        if progress_callback:
            progress_callback(0.4, "正在构建世界观...")
        if architect is not None:
            try:
                world_proposal = architect.propose_world_setting(
                    architect_meta, synopsis=synopsis_for_arch
                )
                state["world_setting"] = world_proposal.world.model_dump()
                state.setdefault("decisions", []).append({
                    "agent": "ProjectArchitect",
                    "step": "propose_world_setting",
                    "decision": f"世界观生成完成: {world_proposal.world.era} - {world_proposal.world.location}",
                    "reason": "Phase 2-γ ProjectArchitect propose → accept",
                })
                state.setdefault("completed_nodes", []).append("project_architect.world")
            except Exception as e:
                log.warning("世界观构建失败，继续: %s", e)
                state.setdefault("errors", []).append(
                    {"agent": "ProjectArchitect", "message": f"世界观构建失败: {e}"}
                )
        else:
            try:
                result = nodes["world_builder"](state)
                state = _merge_state(state, result)
            except Exception as e:
                log.warning("世界观构建失败，继续: %s", e)

        if progress_callback:
            progress_callback(0.7, "正在设计角色...")
        if architect is not None:
            try:
                chars_proposal = architect.propose_main_characters(
                    architect_meta, synopsis=synopsis_for_arch
                )
                state["characters"] = [c.model_dump() for c in chars_proposal.characters]
                state.setdefault("decisions", []).append({
                    "agent": "ProjectArchitect",
                    "step": "propose_main_characters",
                    "decision": f"角色生成完成: {len(chars_proposal.characters)} 个",
                    "reason": "Phase 2-γ ProjectArchitect propose → accept",
                })
                state.setdefault("completed_nodes", []).append("project_architect.characters")
            except Exception as e:
                log.warning("角色设计失败，继续: %s", e)
                state.setdefault("errors", []).append(
                    {"agent": "ProjectArchitect", "message": f"角色设计失败: {e}"}
                )
        else:
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
        # Phase 3: drop the direct NovelDirector coupling — ProjectArchitect
        # is the single entry point for立项/骨架 generation. The architect
        # still defers the actual arc LLM call into NovelDirector internally
        # (legacy shim), but callers no longer know or care.
        try:
            from src.novel.agents.project_architect import ProjectArchitect
            from src.llm.llm_client import create_llm_client as _create_llm

            _llm_config = get_stage_llm_config(state, "outline_generation")
            _llm = _create_llm(_llm_config)
            _arch = ProjectArchitect(_llm, config=self.config)

            outline_data = state.get("outline", {})
            chapters = outline_data.get("chapters", []) if isinstance(outline_data, dict) else []
            if chapters:
                _arcs_proposal = _arch.propose_story_arcs(
                    meta={"genre": genre, "outline": outline_data},
                    synopsis=(
                        state.get("main_storyline", {}).get("protagonist_goal", "")
                        or theme
                    ),
                )
                arcs = list(_arcs_proposal.arcs or [])
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
            "style_bible": state.get("style_bible"),
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

        errors = state.get("errors", [])
        return {
            "status": "partial" if errors else "success",
            "novel_id": novel_id,
            "project_path": project_path,
            "workspace": project_path,  # alias for compat
            "outline": state.get("outline"),
            "characters": state.get("characters", []),
            "world_setting": state.get("world_setting"),
            "total_chapters": state.get("total_chapters", 0),
            "errors": errors,
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
        # Phase 2-δ: plan_chapters reuses ChapterPlanner's outline-revision
        # capability through chapter_planner_node (which merges the old
        # dynamic_outline + plot_planner nodes).  We only need the node fn here.
        from src.novel.agents.chapter_planner import chapter_planner_node

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

            # Generate continuity brief via BriefAssembler (Ledger-first +
            # inherited rule-based sections). Phase 3 swap — the returned
            # assembler is stashed on state so ChapterPlanner can reuse it.
            try:
                from src.novel.services.brief_assembler import BriefAssembler
                _mem = getattr(self, "memory", None)
                brief_assembler = BriefAssembler(
                    db=getattr(_mem, "structured_db", None) if _mem else None,
                    obligation_tracker=obligation_tracker,
                    knowledge_graph=getattr(_mem, "knowledge_graph", None) if _mem else None,
                    ledger=state.get("ledger_store"),
                )
                continuity_brief = brief_assembler.generate_brief(
                    chapter_number=ch_num,
                    chapters=state.get("chapters") or [],
                    chapter_brief=ch_outline.get("chapter_brief", {}),
                    story_arcs=state.get("story_arcs", []),
                    characters=state.get("characters", []),
                    style_bible=state.get("style_bible"),
                    current_volume=state.get("current_volume"),
                )
                state["continuity_brief"] = brief_assembler.format_for_prompt(continuity_brief)
            except Exception as exc:
                log.warning("连续性摘要生成失败: %s", exc)
                state["continuity_brief"] = ""

            # Provide real novel_data so ChapterPlanner/BriefAssembler can
            # fall back to the persisted roster when the Ledger lacks active chars.
            try:
                state["novel_data"] = fm.load_novel(novel_id) or {}
            except Exception:
                state["novel_data"] = {}

            # Run chapter_planner_node to revise outline (and plan scenes).
            # We only keep the revised outline + reason; scenes generated here
            # are discarded because plan_chapters does not write text.
            revision_reason = ""
            try:
                result = chapter_planner_node(state)
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
                    if d.get("step") == "propose_chapter_brief":
                        revision_reason = d.get("reason", "")
                        break
            except Exception as exc:
                log.warning("第%d章大纲修订失败: %s", ch_num, exc)

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

        # Heal any duplicates from in-memory state built outside checkpoint.
        if "chapters" in state and isinstance(state["chapters"], list):
            state["chapters"] = self._dedupe_chapters_list(state["chapters"])

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
        state["budget_mode"] = budget_mode

        # Initialize chapters_text from existing chapters in state + disk
        # Must happen BEFORE style bible migration which needs chapter text.
        if "chapters_text" not in state:
            state["chapters_text"] = {}
        _chapters_text_init = state["chapters_text"]
        # Populate from state["chapters"] metadata dicts (if they carry full_text)
        for _ch_init in state.get("chapters") or []:
            _ch_n_init = _ch_init.get("chapter_number")
            _ch_t_init = _ch_init.get("full_text", "")
            if _ch_n_init and _ch_t_init and _ch_n_init not in _chapters_text_init:
                _chapters_text_init[_ch_n_init] = _ch_t_init
        # Populate from disk for chapters not yet in memory
        try:
            _existing_on_disk = fm.list_chapters(novel_id)
            for _ch_disk_n in _existing_on_disk:
                if _ch_disk_n not in _chapters_text_init:
                    _txt = fm.load_chapter_text(novel_id, _ch_disk_n)
                    if _txt:
                        _chapters_text_init[_ch_disk_n] = _txt
        except Exception:
            pass

        # --- Style Bible migration (Intervention D) ---
        # If no style_bible exists yet (legacy project), auto-generate one
        # from the first 5 existing chapters.
        if not state.get("style_bible"):
            try:
                existing_chapters = state.get("chapters") or []
                style_name = state.get("style_name", "webnovel.shuangwen")
                genre = state.get("genre", "")
                # Ensure chapters have full_text
                _chapters_text = state.get("chapters_text", {})
                chapters_with_text = []
                for ch in existing_chapters:
                    ch_copy = dict(ch)
                    if not ch_copy.get("full_text"):
                        ch_copy["full_text"] = _chapters_text.get(
                            ch_copy.get("chapter_number", 0), ""
                        )
                    if ch_copy.get("full_text") and len(ch_copy["full_text"]) > 100:
                        chapters_with_text.append(ch_copy)

                if chapters_with_text:
                    # Use first 5 chapters for baseline
                    sample = sorted(
                        chapters_with_text, key=lambda c: c.get("chapter_number", 0)
                    )[:5]
                    from src.novel.services.style_bible_generator import StyleBibleGenerator
                    from src.llm.llm_client import create_llm_client as _create_llm_sb

                    _llm_cfg = get_stage_llm_config(state, "outline_generation")
                    _llm_sb = _create_llm_sb(_llm_cfg)
                    bible_gen = StyleBibleGenerator(_llm_sb)
                    bible = bible_gen.generate_from_existing_chapters(
                        chapters=sample,
                        style_name=style_name,
                        genre=genre,
                    )
                    state["style_bible"] = bible.model_dump()
                    # Persist to novel.json
                    novel_data_sb = fm.load_novel(novel_id) or {}
                    novel_data_sb["style_bible"] = state["style_bible"]
                    fm.save_novel(novel_id, novel_data_sb)
                    log.info("风格圣经已从现有章节迁移生成 (ch%d-%d)",
                             sample[0]["chapter_number"], sample[-1]["chapter_number"])
                else:
                    log.info("无现有章节，跳过风格圣经迁移（将在新项目创建时生成）")
            except Exception as exc:
                log.warning("风格圣经迁移生成失败（非阻塞）: %s", exc)

        # --- Initialize NovelMemory for vector indexing + character snapshots ---
        try:
            from src.novel.storage.novel_memory import NovelMemory
            self.memory = NovelMemory(novel_id, self.workspace)
        except Exception as exc:
            log.warning("NovelMemory 初始化失败: %s", exc)
            self.memory = None

        # Phase 2-δ: wire LedgerStore into state so ChapterPlanner (and
        # Reviewer, if enabled) can pull a per-chapter ledger snapshot
        # without re-deriving it from the scattered tracker services.
        try:
            from src.novel.services.ledger_store import LedgerStore as _LedgerStore

            _novel_data_for_ledger = fm.load_novel(novel_id) or {}
            state["ledger_store"] = _LedgerStore(
                project_path=str(Path(self.workspace) / "novels" / novel_id),
                db=getattr(self.memory, "structured_db", None) if self.memory else None,
                kg=getattr(self.memory, "knowledge_graph", None) if self.memory else None,
                vector_store=getattr(self.memory, "vector_store", None) if self.memory else None,
                novel_data=_novel_data_for_ledger,
            )
            log.info("LedgerStore 已写入 state (Phase 2-δ)")
        except Exception as exc:
            log.warning("LedgerStore 初始化失败 (非关键): %s", exc)
            state["ledger_store"] = None

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

            # Detect stale outline and regenerate
            if not self._is_placeholder_outline(ch_outline) and self._is_stale_outline(ch_outline, ch_num, state):
                log.info("第%d章大纲已陈旧（引用过时上下文），自动重新规划...", ch_num)
                ch_outline = self._fill_placeholder_outline(state, ch_outline, ch_num)
                for i, ch in enumerate(outline.get("chapters", [])):
                    if ch.get("chapter_number") == ch_num:
                        outline["chapters"][i] = ch_outline
                        break

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

            # --- Narrative Control: generate continuity brief (BriefAssembler) ---
            try:
                from src.novel.services.brief_assembler import BriefAssembler

                _mem = getattr(self, "memory", None)
                continuity_svc = BriefAssembler(
                    db=getattr(_mem, "structured_db", None) if _mem else None,
                    obligation_tracker=obligation_tracker,
                    knowledge_graph=getattr(_mem, "knowledge_graph", None) if _mem else None,
                    ledger=state.get("ledger_store"),
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

                # Compute current_volume from chapter number and outline
                _current_volume = self._chapter_to_volume(ch_num, outline)
                state["current_volume"] = _current_volume

                # Load novel_data for milestone tracking (Intervention A)
                _novel_data_for_milestones = None
                try:
                    _novel_data_for_milestones = fm.load_novel(novel_id)
                except Exception:
                    pass
                # Expose to ChapterPlanner via state (Phase 3: replace stub
                # {"characters": state["characters"]} with real novel_data).
                state["novel_data"] = _novel_data_for_milestones or {}

                # --- Auto-generate milestones if current volume has none ---
                if _novel_data_for_milestones and _current_volume:
                    try:
                        _outline_for_ms = _novel_data_for_milestones.get("outline", {})
                        for _vol_ms in _outline_for_ms.get("volumes", []):
                            if _vol_ms.get("volume_number") == _current_volume:
                                if not _vol_ms.get("narrative_milestones"):
                                    from src.novel.agents.novel_director import NovelDirector as _ND
                                    _llm_ms_cfg = get_stage_llm_config(state, "outline_generation")
                                    from src.llm.llm_client import create_llm_client
                                    _llm_ms = create_llm_client(_llm_ms_cfg)
                                    _nd_ms = _ND(_llm_ms)
                                    _vol_chapters = [
                                        c for c in _outline_for_ms.get("chapters", [])
                                        if c.get("chapter_number", 0) >= _vol_ms.get("start_chapter", 0)
                                        and c.get("chapter_number", 0) <= _vol_ms.get("end_chapter", 999)
                                    ]
                                    _new_ms = _nd_ms.generate_volume_milestones(
                                        volume=_vol_ms,
                                        chapter_outlines=_vol_chapters,
                                        genre=state.get("genre", ""),
                                    )
                                    if _new_ms:
                                        _vol_ms["narrative_milestones"] = _new_ms
                                        fm.save_novel(novel_id, _novel_data_for_milestones)
                                        log.info("卷%d 首章自动生成 %d 个里程碑", _current_volume, len(_new_ms))
                                break
                    except Exception as exc:
                        log.warning("首章里程碑自动生成失败 (非关键): %s", exc)

                continuity_brief = continuity_svc.generate_brief(
                    chapter_number=ch_num,
                    chapters=_chapters_for_brief,
                    chapter_brief=ch_outline.get("chapter_brief", {}),
                    story_arcs=state.get("story_arcs", []),
                    characters=state.get("characters", []),
                    style_bible=state.get("style_bible"),
                    current_volume=_current_volume,
                    novel_data=_novel_data_for_milestones,
                )
                state["continuity_brief"] = continuity_svc.format_for_prompt(continuity_brief)

                # Store structured volume_progress for ChapterPlanner (Intervention A)
                state["volume_progress"] = continuity_brief.get("volume_progress", {})
            except Exception as exc:
                log.warning("连续性摘要生成失败: %s", exc)
                state["continuity_brief"] = ""
                state["volume_progress"] = {}

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

            # --- Milestone enforcement: inject hard constraint before graph runs ---
            _vp = state.get("volume_progress", {})
            if _vp.get("progress_health") == "critical":
                _overdue_descs = _vp.get("milestones_overdue", [])
                if _overdue_descs:
                    _enforce_text = (
                        "\n\n## 【强制里程碑约束 — 系统级，不可忽略】\n"
                        f"以下里程碑已逾期，本章**必须**安排至少一个场景直接推进：\n"
                    )
                    for _od in _overdue_descs[:3]:
                        _enforce_text += f"  - {_od}\n"
                    _enforce_text += (
                        "ChapterPlanner 必须将第一个场景设定为推进上述里程碑。\n"
                        "Writer 必须在该场景中产出实质性进展，不能仅提及。\n"
                    )
                    # Inject into both debt_summary (ChapterPlanner reads) and continuity_brief (Writer reads)
                    state["debt_summary"] = (state.get("debt_summary", "") or "") + _enforce_text
                    state["continuity_brief"] = (state.get("continuity_brief", "") or "") + _enforce_text
                    log.warning(
                        "里程碑强制约束注入: %d 个逾期里程碑写入 ChapterPlanner+Writer 约束",
                        len(_overdue_descs[:3]),
                    )

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
                _outline_for_title = (
                    revised_outline
                    if isinstance(revised_outline, dict)
                    else ch_outline if isinstance(ch_outline, dict) else None
                )
                ch_title = _outline_for_title.get("title", "") if _outline_for_title else ""
                # Always sanitize outline-provided titles
                ch_title = _sanitize_title(ch_title, ch_num) if ch_title else ""
                if not ch_title or ch_title == f"第{ch_num}章":
                    ch_title = _extract_title_from_text(
                        chapter_text, ch_num, _outline_for_title
                    )

                # Uniqueness: avoid identical titles across previously
                # generated chapters in this run. If a collision occurs,
                # append a differentiator derived from the chapter number.
                if ch_title and ch_title != f"第{ch_num}章":
                    existing_titles = {
                        (ch_prev.get("title") or "").strip()
                        for ch_prev in (state.get("chapters") or [])
                        if ch_prev.get("chapter_number") != ch_num
                    }
                    if ch_title in existing_titles:
                        differentiated = f"{ch_title}·续"
                        if differentiated in existing_titles:
                            differentiated = f"{ch_title}·其{ch_num}"
                        log.info(
                            "第%d章标题与已有章节重复，已重命名：%s → %s",
                            ch_num, ch_title, differentiated,
                        )
                        ch_title = differentiated

                # --- Hook evaluation (Phase 2-δ: absorbed into ChapterPlanner) ---
                # Post-hoc rewrite path removed: ChapterPlanner plans the
                # end-hook up-front via ``brief.end_hook`` so the old
                # HookGenerator.generate_hook path is redundant.  We keep
                # a cheap log-only quality signal for observability.
                try:
                    from src.novel.agents.chapter_planner import ChapterPlanner

                    eval_result = ChapterPlanner.evaluate_hook(chapter_text)
                    if eval_result.get("needs_improvement"):
                        log.info(
                            "第%d章结尾较弱 (评分%d, 类型%s)",
                            ch_num,
                            eval_result.get("score", 0),
                            eval_result.get("hook_type", "?"),
                        )
                except Exception as exc:
                    log.warning("钩子评估失败 (非关键): %s", exc)

                # --- Surgical dedup: strip intra-chapter dialogue echo runs ---
                try:
                    from src.novel.services.dedup_dialogue import (
                        strip_intra_chapter_dialogue_repeats,
                        strip_repeated_paragraph_blocks,
                    )
                    chapter_text = strip_intra_chapter_dialogue_repeats(chapter_text)
                    # 段落整块重复（章节收束拼接 bug 导致的"章末复读"）
                    chapter_text = strip_repeated_paragraph_blocks(chapter_text)
                except Exception as exc:
                    log.warning("章内去重失败 (非关键): %s", exc)

                ch_data = self._build_chapter_record(
                    state=state,
                    ch_num=ch_num,
                    ch_title=ch_title,
                    chapter_text=chapter_text,
                )
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

                # --- Entity extraction (P0: Entity Registry) ---
                try:
                    from src.novel.services.entity_service import EntityService
                    _entity_db = self.memory.structured_db if getattr(self, "memory", None) and getattr(self.memory, "structured_db", None) else None
                    if _entity_db:
                        entity_svc = EntityService(_entity_db)
                        _entity_result = entity_svc.extract_and_register(
                            chapter_text=chapter_text,
                            chapter_number=ch_num,
                            use_llm=False,
                        )
                        if _entity_result.get("new_count", 0) > 0:
                            log.info("第%d章实体提取: %d 新实体, %d 更新", ch_num, _entity_result["new_count"], _entity_result["updated_count"])

                        # 每5章做一次别名清理
                        if ch_num % 5 == 0:
                            _merged = entity_svc.merge_aliases(dry_run=False)
                            if _merged > 0:
                                log.info("实体别名合并: %d 组", _merged)
                except Exception as exc:
                    log.debug("实体提取失败（非阻塞）: %s", exc)

                # --- Foreshadowing graph update (P1) ---
                try:
                    if getattr(self, "memory", None) and hasattr(self.memory, "knowledge_graph"):
                        from src.novel.services.foreshadowing_service import ForeshadowingService
                        _fs = ForeshadowingService(self.memory.knowledge_graph)
                        _ch_brief = ch_outline.get("chapter_brief", {}) if ch_outline else {}
                        _fs.register_planned_foreshadowings(_ch_brief, ch_num)

                        _plants = _ch_brief.get("foreshadowing_plant", [])
                        _collects = _ch_brief.get("foreshadowing_collect", [])
                        if _plants or _collects:
                            _verify = _fs.verify_foreshadowings_in_text(
                                chapter_text=chapter_text,
                                chapter_number=ch_num,
                                planned_plants=_plants if isinstance(_plants, list) else [_plants] if _plants else [],
                                planned_collects=_collects if isinstance(_collects, list) else [_collects] if _collects else [],
                            )
                            if _verify.get("plants_missing"):
                                log.warning("第%d章伏笔埋设缺失: %s", ch_num, _verify["plants_missing"])
                            if _verify.get("collects_missing"):
                                log.warning("第%d章伏笔回收缺失: %s", ch_num, _verify["collects_missing"])

                        self.memory.knowledge_graph.save(str(self._novel_dir(novel_id) / "memory" / "knowledge_graph.json"))
                except Exception as exc:
                    log.debug("伏笔图谱更新失败（非阻塞）: %s", exc)

                # --- Milestone Tracking (Intervention A): check completion + overdue ---
                try:
                    from src.novel.services.milestone_tracker import MilestoneTracker

                    _novel_data_mt = fm.load_novel(novel_id) or {}
                    mt = MilestoneTracker(_novel_data_mt)
                    _completed_ms = mt.check_milestone_completion(
                        chapter_num=ch_num,
                        chapter_text=chapter_text,
                        chapter_summary=actual_summary or None,
                    )
                    if _completed_ms:
                        log.info("Completed milestones at ch%d: %s", ch_num, _completed_ms)
                    _overdue_ms = mt.mark_overdue_milestones(ch_num)
                    if _overdue_ms:
                        log.warning("Overdue milestones at ch%d: %s", ch_num, _overdue_ms)

                    # Persist milestone status changes back to novel.json
                    if _completed_ms or _overdue_ms:
                        _novel_data_mt["outline"] = _novel_data_mt.get("outline", {})
                        _novel_data_mt["outline"]["volumes"] = mt.volumes
                        fm.save_novel(novel_id, _novel_data_mt)
                        # Also update in-memory outline so next chapter sees changes
                        outline["volumes"] = mt.volumes

                    # Volume boundary: settle milestones when last chapter of volume
                    _cur_vol = mt._get_volume_by_chapter(ch_num)
                    if _cur_vol and ch_num == _cur_vol.get("end_chapter"):
                        from src.novel.services.volume_settlement import VolumeSettlement as _VS
                        _vs = _VS(
                            db=self.memory.structured_db if getattr(self, "memory", None) and getattr(self.memory, "structured_db", None) else None,
                            outline=outline if isinstance(outline, dict) else {},
                        )
                        _report = _vs.settle_volume_milestones(
                            volume_number=_cur_vol["volume_number"],
                            novel_data=_novel_data_mt,
                        )
                        if _report:
                            log.info(
                                "Volume %d milestone settlement: %s",
                                _cur_vol["volume_number"],
                                _report,
                            )
                            # Persist settlement report
                            fm.save_novel(novel_id, _novel_data_mt)
                            outline["volumes"] = _novel_data_mt.get("outline", {}).get("volumes", outline.get("volumes", []))
                except Exception as exc:
                    log.warning("里程碑追踪失败 (非关键): %s", exc)

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

        errors = state.get("errors", [])
        if errors:
            status = "partial"
        elif chapters_generated:
            status = "success"
        else:
            status = "noop"
        result = {
            "status": status,
            "novel_id": novel_id,
            "project_path": str(self._novel_dir(novel_id)),
            "chapters_generated": chapters_generated,
            "chapters_written": chapters_generated,  # alias
            "total_generated": len(chapters_generated),
            "errors": errors,
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
    # get_health_report
    # ------------------------------------------------------------------

    def get_health_report(self, project_path: str) -> dict:
        """获取项目健康度报告。

        Returns:
            dict with ``metrics`` (HealthMetrics.model_dump()) and
            ``report`` (formatted text string).
        """
        novel_id = Path(project_path).name
        fm = self._get_file_manager()

        # Load checkpoint for novel data
        novel_data = self._load_checkpoint(novel_id) or {}
        status_info = fm.load_status(novel_id) or {}
        current_chapter = status_info.get(
            "current_chapter", novel_data.get("current_chapter", 0)
        )

        # Initialise optional dependencies — each may fail independently
        memory = None
        try:
            from src.novel.storage.novel_memory import NovelMemory

            memory = NovelMemory(novel_id, self.workspace)
        except Exception:
            pass

        obligation_tracker = None
        try:
            from src.novel.services.obligation_tracker import ObligationTracker

            db = getattr(memory, "structured_db", None) if memory else None
            if db is not None:
                obligation_tracker = ObligationTracker(db)
        except Exception:
            pass

        milestone_tracker = None
        try:
            from src.novel.services.milestone_tracker import MilestoneTracker

            milestone_tracker = MilestoneTracker(novel_data)
        except Exception:
            pass

        from src.novel.services.health_service import HealthService

        svc = HealthService(
            structured_db=(
                getattr(memory, "structured_db", None) if memory else None
            ),
            knowledge_graph=(
                getattr(memory, "knowledge_graph", None) if memory else None
            ),
            obligation_tracker=obligation_tracker,
            milestone_tracker=milestone_tracker,
        )
        metrics = svc.compute_health_metrics(current_chapter, novel_data)
        report_text = svc.format_report(metrics)

        # Close memory resources if we opened them
        if memory is not None:
            try:
                memory.close()
            except Exception:
                pass

        return {
            "metrics": metrics.model_dump(),
            "report": report_text,
        }

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

        流程：审稿(Reviewer.review) → 精修(Writer.polish_chapter)

        Args:
            project_path: 项目路径
            start_chapter: 起始章节号
            end_chapter: 结束章节号（None=所有章节）
            progress_callback: 进度回调

        Returns:
            dict with polished_chapters, skipped_chapters, errors
        """
        from src.llm.llm_client import create_llm_client
        from src.novel.agents.reviewer import Reviewer
        from src.novel.agents.writer import Writer
        from src.novel.models.character import CharacterProfile
        from src.novel.models.novel import ChapterOutline
        from src.novel.models.world import WorldSetting
        from src.novel.tools.style_analysis_tool import StyleAnalysisTool

        novel_id = Path(project_path).name
        fm = self._get_file_manager()
        style_tool = StyleAnalysisTool()

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

        # Initialize LLM + Writer + Reviewer
        llm_config = get_stage_llm_config(state, "scene_writing")
        llm = create_llm_client(llm_config)
        writer = Writer(llm)
        # 参考 chapter 生成图里的 Reviewer 构造（src/novel/agents/reviewer.py 的
        # build_and_review_node），把 ledger + watchlist 接进来；
        # 没有这两项 Reviewer 会静默退化（ledger consistency / style_overuse 失效）。
        # TODO(polish): 接 StyleProfile 进一步丰富 watchlist 与节拍命中
        ledger = state.get("ledger_store")
        quality_cfg = (state.get("config") or {}).get("quality", {}) or {}
        watchlist = quality_cfg.get("ai_flavor_watchlist") or None
        reviewer = Reviewer(llm, ledger=ledger, watchlist=watchlist)

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

            # 前章上下文：信息边界分流（C3 真修 + code review H1，2026-04-26）。
            # - Writer (生成侧, context 入 polish_chapter)：拿摘要，避免诱导
            #   跨章 verbatim 复读（P0 同源 bug）。摘要为空时 context 也为空，
            #   绝不 fallback 塞生原文。
            # - Reviewer (评估侧, previous_tail 入 review)：拿原文末 500 字，
            #   评估"上章末有 typo / 衔接错位 / 跨章伏笔"这类需要原始字面量
            #   的判断。摘要会丢失关键字面信息，不能喂给评估侧。
            # summarizer 用调用栈里现成的 llm（这里是 scene_writing 阶段，
            # 与 Writer 同一 client）；每章 +1 LLM call ~300 token。
            raw_tail = ""
            context = ""
            if ch_num > 1 and (ch_num - 1) in chapter_texts:
                raw_tail = chapter_texts[ch_num - 1][-500:]
                context = summarize_previous_tail(llm, raw_tail)

            log.info("=== 精修第 %d/%d 章 ===", ch_num, total_chapters)

            try:
                # Step 0: 改前指标（零成本，纯规则；rule_check 已随 quality_check_tool
                # 一起砍，这里只剩 style 指标）
                before_style = style_tool.analyze(chapter_text)

                # Step 1: 审稿（Reviewer）— 评估侧拿原文，见上方注释
                log.info("第%d章：审稿中...", ch_num)
                critique = reviewer.review(
                    chapter_text=chapter_text,
                    chapter_number=ch_outline.chapter_number,
                    chapter_title=ch_outline.title,
                    chapter_goal=ch_outline.goal,
                    previous_tail=raw_tail,
                )

                log.info(
                    "第%d章审稿意见:\n%s",
                    ch_num,
                    critique.overall_assessment[:200],
                )

                # Step 2: 精修
                # polish_chapters 是用户显式调用的"主动挑刺精修"入口，语义是
                # "只要 Reviewer 挑出任何 issue 就改"。不走 needs_refine（那是
                # refine_loop 更保守的阈值：high>0 or medium>=2）。
                if not critique.issues:
                    log.info("第%d章审稿通过（无 issue），跳过精修", ch_num)
                    result["skipped_chapters"].append(ch_num)
                    continue

                log.info("第%d章：精修中...", ch_num)
                critique_prompt = critique.to_writer_prompt()
                polished_text = writer.polish_chapter(
                    chapter_text=chapter_text,
                    critique=critique_prompt,
                    chapter_outline=ch_outline,
                    characters=characters,
                    world_setting=world_setting,
                    context=context,
                    style_name=style_name,
                )

                # Step 3: 改后指标（零成本，纯规则）
                after_style = style_tool.analyze(polished_text)

                # 审稿意见分类（直接取自 CritiqueResult.issues）
                issues = [
                    {
                        "type": i.type,
                        "severity": i.severity,
                        "quote": i.quote,
                        "reason": i.reason,
                    }
                    for i in critique.issues
                ]

                # 备份原文，保存精修版
                fm.save_chapter_revision(novel_id, ch_num, chapter_text)
                fm.save_chapter_text(novel_id, ch_num, polished_text)

                # 更新内存中的章节文本（后续章节的上下文会用到）
                chapter_texts[ch_num] = polished_text

                result["polished_chapters"].append({
                    "chapter_number": ch_num,
                    "original_chars": len(chapter_text),
                    "polished_chars": len(polished_text),
                    "critique_summary": critique.overall_assessment[:200],
                    "critique_full": critique_prompt,
                    "issues": issues,
                    "before_style": before_style.model_dump(),
                    "after_style": after_style.model_dump(),
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

            # 前章上下文：摘要而非生原文（C3 真修，2026-04-26）。
            # 同 polish_chapters：直接喂上章 500 字会诱导 Writer 跨章 verbatim
            # 复读，走 summarize_previous_tail() 拿 LLM 摘要 + 15-char verbatim
            # 校验。三处都用 [-500:] 取末尾（truncate_text 是从开头切，会喂错
            # 输入到 summarizer——code review M4 抓出）。summarizer 用调用栈里
            # 现成的 llm（apply_feedback 是 quality_review；polish/rewrite_affected
            # 是 scene_writing）；analysis 任务每章 +1 LLM call ~300 token。
            context = ""
            if ch_num > 1 and (ch_num - 1) in chapter_texts:
                raw_tail = chapter_texts[ch_num - 1][-500:]
                context = summarize_previous_tail(llm, raw_tail)

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

                # Surgical dedup: strip intra-chapter dialogue echo runs
                try:
                    from src.novel.services.dedup_dialogue import (
                        strip_intra_chapter_dialogue_repeats,
                    )
                    new_text = strip_intra_chapter_dialogue_repeats(new_text)
                except Exception as exc:
                    log.warning("重写章节对白复读去重失败 (非关键): %s", exc)

                # Save rewritten chapter (text + json metadata)
                raw_title = ch_outline_data.get("title", f"第{ch_num}章")
                ch_json = {
                    "chapter_number": ch_num,
                    "title": _sanitize_title(raw_title, ch_num),
                    "full_text": new_text,
                    "word_count": len(new_text),
                    "status": "draft",
                    # Rewriting invalidates any previous quality scoring — the
                    # old scores were computed against the old text. Explicitly
                    # null them so downstream code knows this chapter needs to
                    # be re-scored, rather than silently dropping the fields
                    # (which would make them look "never scored").
                    "quality_score": None,
                    "quality_scores": None,
                    "retention_scores": None,
                    "rule_passed": True,
                    "rule_checked": False,
                    "scored_by_llm": False,
                }
                # Extract better title if current is placeholder
                if ch_json["title"] == f"第{ch_num}章":
                    ch_json["title"] = _extract_title_from_text(
                        new_text, ch_num, ch_outline_data
                    )
                fm.save_chapter(novel_id, ch_num, ch_json)
                chapter_texts[ch_num] = new_text  # update for subsequent chapters' context

                # Also update state chapters list (keep in sync with disk —
                # stale quality fields here would survive checkpointing).
                # The helper wipes ALL entries for this chapter_number,
                # builds a canonical new entry with quality fields nulled,
                # and handles the zero-entry case defensively.
                state["chapters"] = self._upsert_rewritten_chapter(
                    existing_chapters=state.get("chapters") or [],
                    ch_num=ch_num,
                    new_text=new_text,
                    new_title=ch_json["title"],
                )

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

                # 前章上下文：摘要而非生原文（C3 真修，2026-04-26）。
                # 同 polish_chapters / apply_feedback：直接喂上章原文会诱导
                # 跨章 verbatim 复读。这里旧路径塞 2000 字最危险（其它两处
                # 已经先降到 500 字硬扛），统一走 summarize_previous_tail()。
                # 这是 setting-change 传播路径，没有独立的 Reviewer 步骤，
                # 故只需要喂 Writer 的摘要 context（无评估侧分支）。
                # summarizer 用此函数 scene_writing 阶段 llm（与 Writer 同 client）。
                context = ""
                if ch_num > 1:
                    prev_text = fm.load_chapter_text(novel_id, ch_num - 1)
                    if prev_text:
                        context = summarize_previous_tail(llm, prev_text[-500:])

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
    # VolumeDirector entry points (Phase 2-α, 架构重构 2026-04)
    #
    # 这两个入口提供卷级进/出规划的工具调用，当前 **不自动触发**，
    # 只作为 CLI / MCP / Agent Chat 后续 wire 的预留接口。
    # ``generate_chapters`` 主流程暂未走 VolumeDirector。
    # ------------------------------------------------------------------

    def propose_volume_outline(
        self,
        project_path: str,
        volume_number: int,
        previous_settlement: dict | None = None,
    ) -> dict:
        """进入新卷时生成 proposal（不落盘）。

        Args:
            project_path: 小说项目路径（workspace/novels/novel_xxx）。
            volume_number: 要规划的卷号。
            previous_settlement: 可选，上一卷的 settlement dict。

        Returns:
            ``VolumeOutlineProposal.to_dict()`` — 调用方 accept 后自行落盘。
        """
        from src.llm.llm_client import create_llm_client
        from src.novel.agents.volume_director import VolumeDirector

        novel_id = Path(project_path).name
        fm = self._get_file_manager()
        novel_data = fm.load_novel(novel_id)
        if novel_data is None:
            raise FileNotFoundError(f"找不到项目: {project_path}")

        # 用 outline_generation 阶段的 LLM 配置
        state: dict = {"config": self.config.model_dump()}
        llm_config = get_stage_llm_config(state, "outline_generation")
        llm = create_llm_client(llm_config)
        director = VolumeDirector(
            llm=llm, workspace=self.workspace, config=self.config
        )
        proposal = director.propose_volume_outline(
            novel=novel_data,
            volume_number=volume_number,
            previous_settlement=previous_settlement,
        )
        return proposal.to_dict()

    def settle_volume(
        self,
        project_path: str,
        volume_number: int,
        use_ledger: bool = True,
    ) -> dict:
        """出卷结算。

        Args:
            project_path: 小说项目路径。
            volume_number: 要结算的卷号。
            use_ledger: 是否尝试构造 LedgerStore（需要 db/kg 可达）。

        Returns:
            ``VolumeSettlementReport.to_dict()``。
        """
        from src.llm.llm_client import create_llm_client
        from src.novel.agents.volume_director import VolumeDirector

        novel_id = Path(project_path).name
        fm = self._get_file_manager()
        novel_data = fm.load_novel(novel_id)
        if novel_data is None:
            raise FileNotFoundError(f"找不到项目: {project_path}")

        ledger = None
        if use_ledger:
            try:
                from src.novel.services.ledger_store import LedgerStore
                from src.novel.storage.novel_memory import NovelMemory

                memory = NovelMemory(novel_id, self.workspace)
                ledger = LedgerStore(
                    project_path=project_path,
                    db=getattr(memory, "structured_db", None),
                    kg=getattr(memory, "knowledge_graph", None),
                    vector_store=getattr(memory, "vector_store", None),
                    novel_data=novel_data,
                )
            except Exception as exc:
                log.warning("settle_volume: 无法构造 LedgerStore (%s)，降级", exc)
                ledger = None

        state: dict = {"config": self.config.model_dump()}
        llm_config = get_stage_llm_config(state, "outline_generation")
        try:
            llm = create_llm_client(llm_config)
        except Exception:
            llm = None  # settle_volume 不强依赖 LLM
        director = VolumeDirector(
            llm=llm, workspace=self.workspace, config=self.config
        )
        report = director.settle_volume(
            novel=novel_data,
            volume_number=volume_number,
            ledger=ledger,
        )
        return report.to_dict()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _chapter_to_volume(chapter_number: int, outline: dict) -> int | None:
        """Determine which volume a chapter belongs to.

        Scans ``outline["volumes"]`` for chapter range membership.
        Returns ``None`` if no volume information is available.
        """
        volumes = outline.get("volumes", [])
        if not volumes:
            return None
        for vol in volumes:
            vol_num = vol.get("volume_number", 0)
            ch_start = vol.get("start_chapter", 0)
            ch_end = vol.get("end_chapter", 0)
            if ch_start <= chapter_number <= ch_end:
                return vol_num
        # Fallback: assign based on position
        return None

    def _get_chapter_outline(self, outline: dict, chapter_number: int) -> dict | None:
        """Get chapter outline by chapter number."""
        for ch in outline.get("chapters", []):
            if ch.get("chapter_number") == chapter_number:
                return ch
        return None

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

    @staticmethod
    def _is_stale_outline(ch_outline: dict, ch_num: int, state: dict) -> bool:
        """Check if a chapter outline is stale (references outdated context).

        Detects:
        1. Outline explicitly references chapter numbers far behind current progress
        2. Outline's storyline_progress or goal references events from much earlier
        """
        import re

        # Combine text fields for analysis
        text_fields = " ".join(filter(None, [
            ch_outline.get("goal", ""),
            ch_outline.get("storyline_progress", ""),
            ch_outline.get("chapter_summary", ""),
            str(ch_outline.get("chapter_brief", {}).get("main_conflict", "")),
        ]))

        if not text_fields:
            return False

        # Detect references to chapter numbers far behind
        refs = re.findall(r"(?:承接|接续|延续|紧接|上接|第)(\d+)章", text_fields)
        if refs:
            max_ref = max(int(r) for r in refs)
            # If the outline references a chapter more than 5 chapters behind, it's stale
            if max_ref > 0 and ch_num - max_ref > 5:
                return True

        # Detect if actual_summary exists on prior chapters that contradict outline assumptions
        # (lightweight: just check if outline was never updated after actual writing)

        # If this chapter's outline references the previous chapter but that chapter
        # has actual_summary that diverges significantly, mark as stale
        outline_data = state.get("outline", {})
        prev_ch_outline = None
        for c in outline_data.get("chapters", []):
            if c.get("chapter_number") == ch_num - 1:
                prev_ch_outline = c
                break

        if prev_ch_outline and prev_ch_outline.get("actual_summary"):
            # Previous chapter has been written - check if our outline assumes
            # something about the previous chapter that's contradicted
            prev_goal = prev_ch_outline.get("goal", "")
            prev_actual = prev_ch_outline.get("actual_summary", "")
            # If prev chapter had a goal that's completely different from actual,
            # and our outline references it, it's likely stale
            if prev_goal and prev_actual and ch_outline.get("goal", ""):
                # Simple heuristic: if outline goal starts with "承接" and prev
                # chapter's actual outcome differs from its planned goal
                if any(kw in text_fields for kw in ["承接", "延续", "紧接"]):
                    # Check if the referenced content matches actual or planned
                    if prev_goal not in text_fields and prev_actual not in text_fields:
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

        # GlobalDirector: whole-book directorial guidance
        director_section = ""
        try:
            from src.novel.services.global_director import GlobalDirector
            novel_for_dir = (fm.load_novel(novel_id) if fm and novel_id else {}) or {}
            director = GlobalDirector(novel_for_dir, outline_data)
            recent_for_dir = []
            for _ch in outline_data.get("chapters", []):
                _cn = _ch.get("chapter_number", 0)
                if 0 < _cn < ch_num:
                    recent_for_dir.append({
                        "chapter_number": _cn,
                        "title": _ch.get("title", ""),
                        "actual_summary": _ch.get("actual_summary", ""),
                    })
            d_brief = director.analyze(ch_num, recent_for_dir[-5:])
            d_prompt = director.format_for_prompt(d_brief)
            if d_prompt:
                director_section = "\n" + d_prompt + "\n"
        except Exception as exc:
            log.debug("规划阶段 GlobalDirector 失败 (非关键): %s", exc)

        # Dead characters: from previous chapters' actual_summaries
        dead_chars_section = ""
        try:
            from src.novel.services.continuity_service import ContinuityService
            _svc = ContinuityService()
            _tmp_brief = {"forbidden_breaks": []}
            # Extract protagonist names from novel data to avoid false-positives
            _novel_for_chars = (fm.load_novel(novel_id) if fm and novel_id else {}) or {}
            _all_chars = _novel_for_chars.get("characters", [])
            _proto_names = ContinuityService._extract_protagonist_names(_all_chars)
            _svc._extract_dead_characters(
                _tmp_brief,
                outline_data.get("chapters", []),
                ch_num,
                protagonist_names=_proto_names,
            )
            if _tmp_brief["forbidden_breaks"]:
                dead_chars_section = (
                    "\n## 已死亡/已离场角色（禁止当作活人使用）\n"
                    + "\n".join(f"- {x}" for x in _tmp_brief["forbidden_breaks"])
                    + "\n"
                )
        except Exception as exc:
            log.debug("规划阶段死亡检测失败 (非关键): %s", exc)

        # Anti-repetition: events already planned in this batch
        batch_ctx = state.get("_batch_planned_context", [])
        batch_section = ""
        if batch_ctx:
            batch_section = "\n已规划章节（不要重复这些事件）:\n" + "\n".join(batch_ctx)

        # Detect scene repetition by analyzing recent chapter titles
        scene_repetition_warning = ""
        recent_titles = []
        for ch in outline_data.get("chapters", []):
            cn = ch.get("chapter_number", 0)
            if 0 < cn < ch_num and cn >= ch_num - 5:
                t = ch.get("title", "")
                if t:
                    recent_titles.append(t)
        # Check single-char overlap (e.g., '矿' appearing in 3+ recent titles)
        if len(recent_titles) >= 3:
            from collections import Counter
            char_counts: dict = {}
            for t in recent_titles[-5:]:
                for ch in set(t):
                    if '\u4e00' <= ch <= '\u9fa5':
                        char_counts[ch] = char_counts.get(ch, 0) + 1
            common = [c for c, n in char_counts.items() if n >= 3]
            if common:
                scene_repetition_warning = (
                    f"\n## ⚠️ 场景重复警告 ⚠️\n"
                    f"最近 5 章标题中「{','.join(common)}」相关字符出现 3 次以上。\n"
                    f"本章必须强制切换到完全不同的场景/视角/冲突类型，不允许再写：\n"
                    f"- 包含「{','.join(common)}」相关元素的场景\n"
                    f"- 与前几章相同的事件类型（守矿/立威/查内鬼/迎敌等）\n"
                    f"必须开拓新地点、新角色互动或新势力冲突。\n"
                )

        prompt = f"""请为第{ch_num}章（共{total_chapters}章）补全详细大纲。

{f"主线信息: 主角目标={main_storyline.get('protagonist_goal', '')}, 核心冲突={main_storyline.get('core_conflict', '')}" if main_storyline else ""}
{volume_info}
{director_section}
{dead_chars_section}
{scene_repetition_warning}
前文概要（注意区分"大纲目标"和"实际结尾"——以实际结尾为准）:
{recent_context}
{batch_section}

【重要约束 — 必须严格遵守】
1. 仔细阅读上方"实际结尾"，本章必须从那里接续，推进到新的情节
2. 前面章节已完成的事件（如制度落地、内鬼抓获、矿道封锁等）严禁重复
3. 本章必须让故事产生实质性进展，不能在同一场景重复同样的事
4. 标题必须具体且与最近 5 章不同，不能用"第N章"格式
5. 已死亡角色（见上方列表）严禁作为活人活动；其势力名称作为帮派指代时也应改用"余部/残部/旧部"形式
6. 严格遵守"全局导演视角"中的阶段指引
7. ⚠️ 如果上方有"场景重复警告"，必须强制切换场景，不接受任何借口
8. 当卷已进入新阶段（如从卷一进入卷二），必须开启全新主题，不继续写卷一的残留情节

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

            from src.novel.utils.json_extract import extract_json_obj
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

            # --- Auto-generate milestones for the new volume ---
            try:
                # Find the volume dict for next_volume
                _vol_for_ms = None
                for _v in outline.get("volumes", []):
                    if _v.get("volume_number") == next_volume:
                        _vol_for_ms = _v
                        break
                if _vol_for_ms is None:
                    # Build minimal volume dict from new_chapters
                    _nc_nums = [c.get("chapter_number", 0) for c in new_chapters]
                    _vol_for_ms = {
                        "volume_number": next_volume,
                        "title": f"第{next_volume}卷",
                        "start_chapter": min(_nc_nums) if _nc_nums else outline_max + 1,
                        "end_chapter": max(_nc_nums) if _nc_nums else outline_max + chapters_per_volume,
                    }
                if not _vol_for_ms.get("narrative_milestones"):
                    _ms = director.generate_volume_milestones(
                        volume=_vol_for_ms,
                        chapter_outlines=new_chapters,
                        genre=novel_data.get("genre", ""),
                    )
                    if _ms:
                        _vol_for_ms["narrative_milestones"] = _ms
                        # Update in outline volumes list (or append if not found)
                        _ms_found = False
                        for _vi, _vv in enumerate(outline.get("volumes", [])):
                            if _vv.get("volume_number") == next_volume:
                                outline["volumes"][_vi] = _vol_for_ms
                                _ms_found = True
                                break
                        if not _ms_found:
                            outline.setdefault("volumes", []).append(_vol_for_ms)
                        log.info("卷%d 自动生成 %d 个里程碑", next_volume, len(_ms))
            except Exception as exc:
                log.warning("卷%d 里程碑自动生成失败 (非关键): %s", next_volume, exc)

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
    def _build_chapter_record(
        state: dict,
        ch_num: int,
        ch_title: str,
        chapter_text: str,
    ) -> dict:
        """Build the ch_data dict persisted for a chapter.

        Extracts the quality report from ``state["current_chapter_quality"]`` and
        merges it into the chapter record. Distinguishes four cases via two
        orthogonal flags (``rule_checked``, ``scored_by_llm``):

        +-----------------+--------------+---------------+
        | case            | rule_checked | scored_by_llm |
        +-----------------+--------------+---------------+
        | LLM-scored      | True         | True          |
        | Budget mode     | True         | False         |
        | Reviewer crash  | False        | False         |
        | Non-dict report | False        | False         |
        +-----------------+--------------+---------------+

        ``rule_checked=False`` is the only signal that the reviewer never
        produced a structured report. Downstream code that wants to re-score
        a chapter must check this flag, not ``scored_by_llm``.

        The helper is defensive against malformed reviewer output: any field
        that is not the expected dict type is treated as missing, and the
        ch_data dict is still built without raising.
        """
        raw_report = state.get("current_chapter_quality")
        quality_report = raw_report if isinstance(raw_report, dict) else {}

        scores_raw = quality_report.get("scores")
        scores = scores_raw if isinstance(scores_raw, dict) else {}

        retention_raw = quality_report.get("retention_scores")
        retention = retention_raw if isinstance(retention_raw, dict) else {}

        rule_check_raw = quality_report.get("rule_check")
        rule_check = rule_check_raw if isinstance(rule_check_raw, dict) else {}

        # Average only numeric values; silently drop strings/None/etc. so one
        # bad entry doesn't poison the whole score.
        quality_score: float | None = None
        if scores:
            numeric = [v for v in scores.values() if isinstance(v, (int, float))]
            if numeric:
                quality_score = sum(numeric) / len(numeric)

        scenes_raw = state.get("current_scenes")
        scenes = scenes_raw if isinstance(scenes_raw, list) else []

        return {
            "chapter_number": ch_num,
            "title": ch_title,
            "full_text": chapter_text,
            "word_count": count_words(chapter_text),
            "status": "draft",
            "quality_score": quality_score,
            "quality_scores": scores or None,
            "retention_scores": retention or None,
            "rule_passed": rule_check.get("passed", True),
            "rule_checked": bool(rule_check),
            "scored_by_llm": bool(scores),
            "scenes": scenes,
        }

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

            # Title: prefer current_chapter_outline's title (from ChapterPlanner)
            cur_outline = state.get("current_chapter_outline", {})
            title = cur_outline.get("title", "")
            # Always sanitize outline-provided titles
            title = _sanitize_title(title, ch_num) if title else ""
            if not title or title == f"第{ch_num}章":
                # Extract a short title from the chapter text
                title = _extract_title_from_text(chapter_text, ch_num, cur_outline or ch)
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
