"""ReflexionMemory — 跨章反思日志。

每章写完后，让 LLM 写一条 ≤200 字反思，回答：
- what_worked: 这章哪里写得对（保留）
- what_failed: 哪里写砸了（避免再犯）
- lesson: 学到的通用经验
- next_action: 下章该做的具体动作

存到 JSON 文件（``{project_path}/reflexion.json``），用户可手编。
下章生成时由 ``ContinuityService`` 调 ``get_recent_lessons()`` 注入 Writer prompt。

零依赖（不需要 SQLite/向量库），简单可靠。
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.llm.llm_client import LLMClient
from src.novel.utils.json_extract import extract_json_obj

log = logging.getLogger("novel.reflexion")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ReflexionEntry:
    """单条反思日志。"""

    chapter_number: int
    what_worked: str = ""
    what_failed: str = ""
    lesson: str = ""
    next_action: str = ""
    chapter_type: str = ""  # setup/buildup/climax/...，用于按类匹配
    created_at: str = ""
    user_edited: bool = False  # 标记是否被用户手编过

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        # 字段长度兜底（防止 LLM 跑题写 1000 字）
        for k in ("what_worked", "what_failed", "lesson", "next_action"):
            v = getattr(self, k) or ""
            if len(v) > 300:
                setattr(self, k, v[:300])


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


_REFLEXION_FILENAME = "reflexion.json"


class ReflexionMemory:
    """跨章反思日志的存取与注入。

    ``project_path`` 指向小说目录（如 ``workspace/novels/novel_xxx``）。
    日志文件在 ``{project_path}/reflexion.json``。

    线程安全：用模块级锁串行化磁盘读写（每项目锁太重，简化处理）。
    """

    _disk_lock = threading.Lock()

    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)
        self._file = self.project_path / _REFLEXION_FILENAME

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def append(self, entry: ReflexionEntry) -> None:
        """追加一条反思日志（同章覆盖）。"""
        with self._disk_lock:
            entries = self._load_all()
            # 同章覆盖，保证唯一
            entries = [e for e in entries if e.get("chapter_number") != entry.chapter_number]
            entries.append(asdict(entry))
            entries.sort(key=lambda e: e.get("chapter_number", 0))
            self._save_all(entries)
        log.info(
            "Reflexion logged for chapter %d (lesson: %s)",
            entry.chapter_number,
            entry.lesson[:60],
        )

    def get_all(self) -> list[ReflexionEntry]:
        """返回所有反思日志，按章节号升序。"""
        with self._disk_lock:
            return [self._dict_to_entry(d) for d in self._load_all()]

    def get_recent(self, before_chapter: int, k: int = 5) -> list[ReflexionEntry]:
        """返回 ``before_chapter`` 之前的最近 k 条反思（按章节号倒序取，再正序返回）。"""
        all_entries = self.get_all()
        prior = [e for e in all_entries if e.chapter_number < before_chapter]
        prior.sort(key=lambda e: e.chapter_number)
        return prior[-k:] if k > 0 else []

    def get_by_type(
        self, chapter_type: str, before_chapter: int, k: int = 3
    ) -> list[ReflexionEntry]:
        """按 chapter_type 取最近 k 条（同类经验）。"""
        all_entries = self.get_all()
        same = [
            e
            for e in all_entries
            if e.chapter_number < before_chapter and e.chapter_type == chapter_type
        ]
        same.sort(key=lambda e: e.chapter_number)
        return same[-k:] if k > 0 else []

    def update(self, chapter_number: int, **fields: Any) -> bool:
        """部分更新指定章节的反思（用户介入入口）。返回是否找到。

        会自动设置 ``user_edited=True``。
        """
        with self._disk_lock:
            entries = self._load_all()
            found = False
            for e in entries:
                if e.get("chapter_number") == chapter_number:
                    for k, v in fields.items():
                        if k in {
                            "what_worked", "what_failed", "lesson",
                            "next_action", "chapter_type",
                        }:
                            e[k] = str(v)[:300]
                    e["user_edited"] = True
                    found = True
                    break
            if found:
                self._save_all(entries)
        return found

    # ------------------------------------------------------------------
    # Prompt injection helpers
    # ------------------------------------------------------------------

    def format_for_prompt(
        self, before_chapter: int, *, k_recent: int = 5,
        chapter_type: str | None = None, k_typed: int = 3,
    ) -> str:
        """格式化为 Writer 系统提示的 "## 历史教训" 段落。

        组合：最近 k_recent 条 + 同类型 k_typed 条（去重）。
        无日志时返回空字符串，调用方应据此跳过整段注入。
        """
        recent = self.get_recent(before_chapter, k_recent)
        seen = {(e.chapter_number, e.lesson) for e in recent}
        typed: list[ReflexionEntry] = []
        if chapter_type:
            for e in self.get_by_type(chapter_type, before_chapter, k_typed):
                if (e.chapter_number, e.lesson) not in seen:
                    typed.append(e)
                    seen.add((e.chapter_number, e.lesson))

        if not recent and not typed:
            return ""

        lines = ["## 📚 历史教训（避免重复犯错）"]
        for e in recent:
            tag = "👤" if e.user_edited else "🤖"
            line = f"- 第{e.chapter_number}章 {tag}：{e.lesson or e.what_failed or '—'}"
            if e.next_action:
                line += f"（下次：{e.next_action}）"
            lines.append(line)
        if typed:
            lines.append("\n### 同类章节经验")
            for e in typed:
                tag = "👤" if e.user_edited else "🤖"
                lines.append(
                    f"- 第{e.chapter_number}章 [{e.chapter_type}] {tag}：{e.lesson or '—'}"
                )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # File IO
    # ------------------------------------------------------------------

    def _load_all(self) -> list[dict]:
        if not self._file.exists():
            return []
        try:
            with open(self._file, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to load reflexion file %s: %s", self._file, exc)
            return []

    def _save_all(self, entries: list[dict]) -> None:
        self.project_path.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        tmp.replace(self._file)

    @staticmethod
    def _dict_to_entry(d: dict) -> ReflexionEntry:
        # 容错：缺字段时用默认
        return ReflexionEntry(
            chapter_number=int(d.get("chapter_number", 0)),
            what_worked=str(d.get("what_worked", "")),
            what_failed=str(d.get("what_failed", "")),
            lesson=str(d.get("lesson", "")),
            next_action=str(d.get("next_action", "")),
            chapter_type=str(d.get("chapter_type", "")),
            created_at=str(d.get("created_at", "")),
            user_edited=bool(d.get("user_edited", False)),
        )


# ---------------------------------------------------------------------------
# LLM-driven reflection generation (optional helper)
# ---------------------------------------------------------------------------


_REFLECT_PROMPT = """你是小说作者本人，刚写完一章，正在做事后复盘。

请对刚写完的章节进行**简短、具体、可执行**的反思。不要客套话。

严格输出 JSON：
{
  "what_worked": "≤80字，本章成功之处（具体到手法/选择）",
  "what_failed": "≤80字，本章失败/遗憾之处（具体到段落/选择）",
  "lesson": "≤80字，从本章提炼的可复用教训",
  "next_action": "≤80字，下一章应当采取的具体动作"
}

要求：
- 每个字段都要写，不能空
- 要具体（"对话过长"而不是"节奏不好"；"应用环境细节代替形容词"而不是"提升文笔"）
- 不要 markdown 代码块
"""


def reflect(
    llm: LLMClient,
    *,
    chapter_text: str,
    chapter_number: int,
    chapter_type: str = "",
    chapter_goal: str = "",
    critique_summary: str = "",
) -> ReflexionEntry:
    """让 LLM 对单章进行反思，返回 ``ReflexionEntry``。失败时返回空条目。"""
    user = f"## 第{chapter_number}章\n"
    if chapter_type:
        user += f"类型：{chapter_type}\n"
    if chapter_goal:
        user += f"目标：{chapter_goal}\n"
    if critique_summary:
        user += f"\n【本章批注总评】\n{critique_summary[:500]}\n"
    user += f"\n【章节正文（节选 1500 字）】\n{chapter_text[:1500]}"

    try:
        resp = llm.chat(
            messages=[
                {"role": "system", "content": _REFLECT_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.4,
            json_mode=True,
            max_tokens=600,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Reflexion LLM call failed: %s", exc)
        return ReflexionEntry(
            chapter_number=chapter_number, chapter_type=chapter_type
        )

    raw = (resp.content or "").strip()
    if not raw:
        return ReflexionEntry(
            chapter_number=chapter_number, chapter_type=chapter_type
        )
    try:
        data = extract_json_obj(raw)
    except Exception:
        return ReflexionEntry(
            chapter_number=chapter_number, chapter_type=chapter_type
        )
    if not isinstance(data, dict):
        return ReflexionEntry(
            chapter_number=chapter_number, chapter_type=chapter_type
        )
    return ReflexionEntry(
        chapter_number=chapter_number,
        chapter_type=chapter_type,
        what_worked=str(data.get("what_worked", ""))[:300],
        what_failed=str(data.get("what_failed", ""))[:300],
        lesson=str(data.get("lesson", ""))[:300],
        next_action=str(data.get("next_action", ""))[:300],
    )
