"""Rebuild narrative control data from existing chapter content.

Scans all chapters of a novel project, extracts narrative debts using
DebtExtractor, optionally analyzes story arcs with LLM, and populates
the StructuredDB with the results.

Example::

    service = NarrativeRebuildService("workspace/novels/novel_xxx")
    result = service.rebuild_all(method="hybrid")
    print(result["debts_extracted"])
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from uuid import uuid4

log = logging.getLogger("novel.services")


class NarrativeRebuildService:
    """Rebuild narrative debts and story arcs from existing chapters.

    Args:
        project_path: Path to novel project directory
            (e.g. ``workspace/novels/novel_xxx``).
        llm_client: Optional ``LLMClient`` for LLM-based extraction.
    """

    def __init__(
        self,
        project_path: str,
        llm_client=None,
        progress_cb=None,
    ) -> None:
        self.project_path = Path(project_path)
        self.llm = llm_client
        self._progress_cb = progress_cb or (lambda pct, msg="": None)

        # Load StructuredDB
        from src.novel.storage.structured_db import StructuredDB

        db_path = self.project_path / "memory.db"
        self.db = StructuredDB(db_path)

        # Initialize helpers
        from src.novel.services.debt_extractor import DebtExtractor
        from src.novel.services.obligation_tracker import ObligationTracker

        self.extractor = DebtExtractor(llm_client=llm_client)
        self.tracker = ObligationTracker(db=self.db)

        # Load novel metadata (outline, characters, world_setting)
        self.novel_data = self._load_novel_json()
        self.outline = self.novel_data.get("outline", {})
        self.characters = self.novel_data.get("characters", [])
        self.world_setting = self.novel_data.get("world_setting", {})
        self.published_chapters: set[int] = set(
            self.novel_data.get("published_chapters", [])
        )

    def _load_novel_json(self) -> dict:
        """Load novel.json metadata from the project directory.

        Returns:
            Parsed dict from novel.json, or empty dict on failure.
        """
        novel_json = self.project_path / "novel.json"
        if not novel_json.exists():
            log.warning("novel.json not found at %s", novel_json)
            return {}
        try:
            return json.loads(novel_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load novel.json: %s", exc)
            return {}

    def rebuild_all(self, method: str = "hybrid") -> dict:
        """Full rebuild: extract debts from all chapters + analyze arcs.

        Args:
            method: ``"rule_based"``, ``"llm"``, or ``"hybrid"``
                (for DebtExtractor).

        Returns:
            Summary dict with keys ``chapters_scanned``,
            ``debts_extracted``, ``debts_auto_fulfilled``,
            ``arcs_detected``, and ``details``.
        """
        self._progress_cb(0.1, "提取叙事债务...")
        debt_result = self.rebuild_debts(method=method)

        self._progress_cb(0.8, "分析故事弧线...")
        arc_result = self.rebuild_arcs()

        self._progress_cb(0.9, "重建角色关系图谱...")
        graph_result = self._rebuild_character_graph()

        debt_result["arcs_detected"] = arc_result.get("arcs_detected", 0)
        debt_result["character_nodes"] = graph_result.get("nodes", 0)
        debt_result["character_edges"] = graph_result.get("edges", 0)

        self._progress_cb(0.95, "完成")
        return debt_result

    def rebuild_debts(self, method: str = "hybrid") -> dict:
        """Rebuild only narrative debts from all chapters.

        Clears existing debts in the database first, then extracts
        debts from each chapter and attempts auto-fulfillment detection
        across chapters.

        Args:
            method: Extraction method for DebtExtractor.

        Returns:
            Summary dict.
        """
        # Clear existing debts
        self._clear_debts()

        chapters = self._load_chapters()
        if not chapters:
            return {
                "chapters_scanned": 0,
                "chapters_published": 0,
                "chapters_local": 0,
                "debts_extracted": 0,
                "debts_from_chapters": 0,
                "debts_from_outline": 0,
                "debts_auto_fulfilled": 0,
                "arcs_detected": 0,
                "details": [],
            }

        all_debts: list[dict] = []
        details: list[dict] = []

        total = len(chapters)
        for idx, ch in enumerate(chapters):
            chapter_number = ch["chapter_number"]
            # Progress: 0.1 ~ 0.75 for debt extraction across chapters
            pct = 0.1 + 0.65 * (idx / max(total, 1))
            self._progress_cb(pct, f"分析第{chapter_number}章 ({idx+1}/{total})...")

            text = ch.get("full_text", "") or ch.get("text", "")
            is_published = chapter_number in self.published_chapters
            if not text:
                details.append({
                    "chapter": chapter_number,
                    "published": is_published,
                    "debts_found": 0,
                    "debts_fulfilled": 0,
                })
                continue

            # Extract debts
            result = self.extractor.extract_from_chapter(
                chapter_text=text,
                chapter_number=chapter_number,
                method=method,
            )
            debts = result.get("debts", [])

            # Save debts to DB via tracker
            status_tag = "[已发布]" if is_published else "[本地]"
            for debt in debts:
                debt["_published"] = is_published
                desc = f"{status_tag} {debt['description']}"
                self.tracker.add_debt(
                    debt_id=debt["debt_id"],
                    source_chapter=debt["source_chapter"],
                    debt_type=debt["type"],
                    description=desc,
                    urgency_level=debt.get("urgency_level", "normal"),
                    target_chapter=debt.get("target_chapter"),
                    character_pending=debt.get("character_pending_actions"),
                    emotional_debt=debt.get("emotional_debt"),
                )

            all_debts.extend(debts)
            details.append({
                "chapter": chapter_number,
                "published": is_published,
                "debts_found": len(debts),
                "debts_fulfilled": 0,  # Updated below
            })

        # Extract debts from outline foreshadowing and planned events
        outline_debts = self._extract_outline_debts()
        for debt in outline_debts:
            self.tracker.add_debt(
                debt_id=debt["debt_id"],
                source_chapter=debt["source_chapter"],
                debt_type=debt["type"],
                description=debt["description"],
                urgency_level=debt.get("urgency_level", "normal"),
            )
        all_debts.extend(outline_debts)

        # Auto-fulfill detection across chapters
        self._progress_cb(0.75, "AI判定债务兑现状态...")
        auto_fulfilled = self._auto_fulfill_debts(all_debts, chapters)

        # Update detail counts with fulfillment info
        fulfilled_chapters: dict[int, int] = {}
        for debt in all_debts:
            if debt.get("_fulfilled_in"):
                ch_num = debt["_fulfilled_in"]
                fulfilled_chapters[ch_num] = fulfilled_chapters.get(ch_num, 0) + 1

        for detail in details:
            detail["debts_fulfilled"] = fulfilled_chapters.get(
                detail["chapter"], 0
            )

        published_count = sum(
            1 for d in details if d.get("published")
        )
        local_count = len(details) - published_count

        log.info(
            "叙事重建完成: %d 章扫描 (%d 已发布, %d 本地), "
            "%d 个债务 (%d 来自大纲), %d 个自动标记完成",
            len(chapters),
            published_count,
            local_count,
            len(all_debts),
            len(outline_debts),
            auto_fulfilled,
        )

        return {
            "chapters_scanned": len(chapters),
            "chapters_published": published_count,
            "chapters_local": local_count,
            "debts_extracted": len(all_debts),
            "debts_from_chapters": len(all_debts) - len(outline_debts),
            "debts_from_outline": len(outline_debts),
            "debts_auto_fulfilled": auto_fulfilled,
            "arcs_detected": 0,
            "details": details,
        }

    def rebuild_arcs(self) -> dict:
        """Detect and rebuild story arcs from chapter summaries.

        Uses LLM to analyze chapter progression and detect 3-7 chapter
        arc patterns.  Falls back to an empty result when no LLM is
        available.

        Returns:
            Dict with ``arcs_detected`` count and ``arcs`` list.
        """
        arcs = self._detect_arcs_with_llm(self._load_chapters())
        return {"arcs_detected": len(arcs), "arcs": arcs}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_outline_debts(self) -> list[dict]:
        """Extract narrative debts from outline foreshadowing and planned events.

        Scans the outline chapters for foreshadowing hints and key events
        that imply continuation, but only for chapters that have actually
        been written.

        Returns:
            List of debt dicts with keys ``debt_id``, ``source_chapter``,
            ``type``, ``description``, ``urgency_level``, ``source``.
        """
        debts: list[dict] = []
        outline_chapters = self.outline.get("chapters", [])
        if not outline_chapters:
            return debts

        written_chapters = {ch["chapter_number"] for ch in self._load_chapters()}

        for ch_outline in outline_chapters:
            ch_num = ch_outline.get("chapter_number", 0)
            if ch_num not in written_chapters:
                continue  # Only process written chapters

            # Foreshadowing -> long_tail_payoff debts
            for foreshadow in ch_outline.get("foreshadowing", []):
                if foreshadow and isinstance(foreshadow, str):
                    debt_id = f"debt_outline_{ch_num}_{uuid4().hex[:6]}"
                    debts.append({
                        "debt_id": debt_id,
                        "source_chapter": ch_num,
                        "type": "long_tail_payoff",
                        "description": f"大纲伏笔: {foreshadow}",
                        "urgency_level": "normal",
                        "source": "outline",
                    })

            # Key events that imply continuation
            for event in ch_outline.get("key_events", []):
                if event and isinstance(event, str) and any(
                    kw in event for kw in ("开始", "准备", "发现", "得知", "引发", "埋下", "留下")
                ):
                    debt_id = f"debt_outline_{ch_num}_{uuid4().hex[:6]}"
                    debts.append({
                        "debt_id": debt_id,
                        "source_chapter": ch_num,
                        "type": "pay_within_3",
                        "description": f"大纲事件: {event}",
                        "urgency_level": "normal",
                        "source": "outline",
                    })

        return debts

    def _rebuild_character_graph(self) -> dict:
        """Build character knowledge graph from character definitions.

        Reads character data from novel.json and stores character facts
        and relationship edges in the StructuredDB facts table.

        Returns:
            Dict with ``nodes`` and ``edges`` counts.
        """
        if not self.characters:
            return {"nodes": 0, "edges": 0}

        nodes = 0
        edges = 0

        for char in self.characters:
            name = char.get("name", "")
            if not name:
                continue

            # Build character fact text
            role = char.get("role", "unknown")
            goals = char.get("goals", [])
            personality = char.get("personality", "")

            fact_text = f"{name}({role})"
            if personality:
                fact_text += f", 性格: {personality[:50]}"
            if goals:
                fact_text += f", 目标: {'、'.join(goals[:3])}"

            # Use raw SQL for upsert since Fact model requires chapter >= 1
            # and type is constrained; we use chapter=1 and type="character_state"
            with self.db.transaction() as cur:
                cur.execute(
                    """INSERT INTO facts (fact_id, chapter, type, content, storage_layer)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(fact_id) DO UPDATE SET
                           content = excluded.content
                    """,
                    (f"char_{name}", 1, "character_state", fact_text, "structured"),
                )
            nodes += 1

            # Add relationships as edges
            for rel in char.get("relationships", []):
                target = rel.get("target", "")
                rel_type = rel.get("type", "关联")
                rel_desc = rel.get("description", "")

                if target:
                    content = (
                        f"{name} → {target}: {rel_type} ({rel_desc[:50]})"
                        if rel_desc
                        else f"{name} → {target}: {rel_type}"
                    )
                    with self.db.transaction() as cur:
                        cur.execute(
                            """INSERT INTO facts (fact_id, chapter, type, content, storage_layer)
                               VALUES (?, ?, ?, ?, ?)
                               ON CONFLICT(fact_id) DO UPDATE SET
                                   content = excluded.content
                            """,
                            (f"rel_{name}_{target}", 1, "relationship", content, "structured"),
                        )
                    edges += 1

        log.info("角色知识图谱重建: %d 节点, %d 边", nodes, edges)
        return {"nodes": nodes, "edges": edges}

    def _load_chapters(self) -> list[dict]:
        """Load all chapter JSON files sorted by chapter number.

        Returns:
            List of chapter dicts, each containing at least
            ``chapter_number`` and ``full_text``.
        """
        chapters_dir = self.project_path / "chapters"
        if not chapters_dir.exists():
            return []

        chapters: list[dict] = []
        for p in sorted(chapters_dir.glob("chapter_*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                # Ensure chapter_number is present
                if "chapter_number" not in data:
                    # Extract from filename: chapter_001.json -> 1
                    match = re.search(r"chapter_(\d+)", p.stem)
                    if match:
                        data["chapter_number"] = int(match.group(1))
                    else:
                        continue
                chapters.append(data)
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("跳过无法读取的章节文件 %s: %s", p, exc)
                continue

        chapters.sort(key=lambda c: c["chapter_number"])
        return chapters

    def _clear_debts(self) -> None:
        """Delete all existing debts from the database."""
        with self.db.transaction() as cur:
            cur.execute("DELETE FROM chapter_debts")
        log.info("已清除所有现有债务")

    def _auto_fulfill_debts(
        self, all_debts: list[dict], chapters: list[dict]
    ) -> int:
        """Detect which debts were fulfilled in later chapters.

        Uses LLM when available for accurate semantic matching,
        falls back to keyword heuristic otherwise.

        Args:
            all_debts: All extracted debts (may be mutated with
                ``_fulfilled_in`` key).
            chapters: All loaded chapters.

        Returns:
            Number of debts auto-fulfilled.
        """
        if not all_debts or not chapters:
            return 0

        if self.llm:
            return self._auto_fulfill_with_llm(all_debts, chapters)
        return self._auto_fulfill_with_keywords(all_debts, chapters)

    def _auto_fulfill_with_llm(
        self, all_debts: list[dict], chapters: list[dict]
    ) -> int:
        """Use LLM to determine which debts have been fulfilled.

        Sends batches of debts along with chapter summaries to the LLM
        and asks it to judge which debts have been resolved.

        Args:
            all_debts: All extracted debts (may be mutated with
                ``_fulfilled_in`` key).
            chapters: All loaded chapters.

        Returns:
            Number of debts auto-fulfilled.
        """
        # Build chapter summaries for context (use first 300 chars of each)
        chapter_summaries: dict[int, str] = {}
        for ch in chapters:
            ch_num = ch["chapter_number"]
            text = ch.get("full_text", "") or ch.get("text", "")
            chapter_summaries[ch_num] = text[:300] if text else ""

        # Only check pending debts (not already fulfilled)
        pending = [d for d in all_debts if not d.get("_fulfilled_in")]
        if not pending:
            return 0

        # Process in batches of 10 debts at a time to avoid token limits
        auto_fulfilled = 0
        batch_size = 10

        for i in range(0, len(pending), batch_size):
            batch = pending[i:i + batch_size]

            # Build debt descriptions for the prompt
            debt_lines = []
            for j, debt in enumerate(batch):
                debt_lines.append(
                    f"{j + 1}. [第{debt['source_chapter']}章] "
                    f"{debt.get('description', '未描述')}"
                )

            # Collect relevant chapter summaries (chapters after the earliest debt source)
            min_source = min(d["source_chapter"] for d in batch)
            relevant_summaries = []
            for ch_num in sorted(chapter_summaries.keys()):
                if ch_num > min_source:
                    summary = chapter_summaries[ch_num]
                    if summary:
                        relevant_summaries.append(f"第{ch_num}章: {summary}")

            if not relevant_summaries:
                continue

            prompt = (
                "判断以下叙事债务是否已在后续章节中被兑现（resolved）。\n\n"
                "## 叙事债务列表\n"
                + "\n".join(debt_lines)
                + "\n\n## 后续章节摘要\n"
                + "\n".join(relevant_summaries[:15])
                + "\n\n"
                "对每个债务判断：是否已兑现？在哪一章兑现的？\n"
                "返回严格 JSON：\n"
                '{\n'
                '  "results": [\n'
                '    {"index": 1, "fulfilled": true, '
                '"fulfilled_in_chapter": 5, "reason": "简短理由"},\n'
                '    {"index": 2, "fulfilled": false, "reason": "尚未提及"}\n'
                '  ]\n'
                '}'
            )

            batch_end = min(i + batch_size, len(pending))
            self._progress_cb(
                0.75 + 0.1 * (i / max(len(pending), 1)),
                f"AI判定债务兑现 ({i + 1}-{batch_end}/{len(pending)})...",
            )

            try:
                resp = self.llm.chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "你是专业网文叙事分析师。"
                                "精准判断叙事债务是否已在后续章节中兑现。"
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    json_mode=True,
                    max_tokens=2048,
                )
                parsed = _parse_json_response(resp.content)
                results = parsed.get("results", [])

                for r in results:
                    idx = r.get("index", 0) - 1  # 1-indexed -> 0-indexed
                    if 0 <= idx < len(batch) and r.get("fulfilled"):
                        debt = batch[idx]
                        ch_num = r.get("fulfilled_in_chapter", 0)
                        reason = r.get("reason", "")
                        note = f"AI判定: 在第{ch_num}章兑现"
                        if reason:
                            note += f" ({reason})"

                        self.tracker.mark_debt_fulfilled(
                            debt["debt_id"],
                            chapter_num=ch_num,
                            note=note,
                        )
                        debt["_fulfilled_in"] = ch_num
                        auto_fulfilled += 1

            except Exception as exc:
                log.warning(
                    "LLM 债务兑现判定失败 (batch %d): %s",
                    i // batch_size, exc,
                )
                # Fall back to keyword matching for this batch
                auto_fulfilled += self._auto_fulfill_with_keywords(
                    batch, chapters
                )

        return auto_fulfilled

    def _auto_fulfill_with_keywords(
        self, all_debts: list[dict], chapters: list[dict]
    ) -> int:
        """Keyword-based heuristic for auto-fulfillment detection.

        Extract 3-5 distinctive terms from each debt description, then
        search subsequent chapters for those terms.  If found, mark the
        debt as fulfilled.  Used as fallback when LLM is unavailable.

        Args:
            all_debts: Debts to check (may be mutated with
                ``_fulfilled_in`` key).
            chapters: All loaded chapters.

        Returns:
            Number of debts auto-fulfilled.
        """
        if not all_debts or not chapters:
            return 0

        # Build chapter text lookup: {chapter_number: text}
        chapter_texts: dict[int, str] = {}
        for ch in chapters:
            ch_num = ch["chapter_number"]
            text = ch.get("full_text", "") or ch.get("text", "")
            if text:
                chapter_texts[ch_num] = text

        auto_fulfilled = 0

        for debt in all_debts:
            if debt.get("_fulfilled_in"):
                continue

            source_ch = debt["source_chapter"]
            description = debt.get("description", "")

            # Extract key terms from description (Chinese chars, skip common labels)
            key_terms = _extract_key_terms(description)
            if not key_terms:
                continue

            # Search subsequent chapters
            for ch_num in sorted(chapter_texts.keys()):
                if ch_num <= source_ch:
                    continue

                text = chapter_texts[ch_num]
                # Check if enough key terms appear in the chapter
                matches = sum(1 for term in key_terms if term in text)
                if matches >= max(1, len(key_terms) // 2):
                    # Mark as fulfilled
                    note = f"自动检测: 在第{ch_num}章发现相关内容"
                    self.tracker.mark_debt_fulfilled(
                        debt["debt_id"],
                        chapter_num=ch_num,
                        note=note,
                    )
                    debt["_fulfilled_in"] = ch_num
                    auto_fulfilled += 1
                    break  # Only fulfill once

        return auto_fulfilled

    def _detect_arcs_with_llm(self, chapters: list[dict]) -> list[dict]:
        """Use LLM to detect story arcs spanning multiple chapters.

        Args:
            chapters: Loaded chapter data.

        Returns:
            List of arc dicts saved to the story_units table.
        """
        if not self.llm or not chapters:
            return []

        # Build chapter summaries: use DB summaries if available,
        # otherwise first 200 chars of each chapter
        summaries: list[str] = []
        for ch in chapters:
            ch_num = ch["chapter_number"]
            db_summary = self.db.get_summary(ch_num)
            if db_summary and db_summary.get("summary"):
                summaries.append(
                    f"第{ch_num}章: {db_summary['summary'][:200]}"
                )
            else:
                text = ch.get("full_text", "") or ch.get("text", "")
                excerpt = text[:200] if text else "(空)"
                summaries.append(f"第{ch_num}章: {excerpt}")

        summaries_text = "\n".join(summaries)

        # Add outline context if available
        outline_context = ""
        if self.outline:
            main_story = self.outline.get("main_storyline", "")
            if main_story:
                outline_context += f"\n主线故事: {main_story[:200]}\n"

            acts = self.outline.get("acts", [])
            if acts:
                act_lines: list[str] = []
                for act in acts[:5]:
                    if isinstance(act, dict):
                        act_lines.append(
                            f"- {act.get('name', '未命名')}: "
                            f"{act.get('description', '')[:80]}"
                        )
                    elif isinstance(act, str):
                        act_lines.append(f"- {act[:80]}")
                if act_lines:
                    outline_context += (
                        "幕结构:\n" + "\n".join(act_lines) + "\n"
                    )

        prompt = f"""\
分析以下小说章节摘要，识别出跨越多个章节的故事弧线（Story Arc）。
{outline_context}
{summaries_text}

请识别 1-5 个主要故事弧线，每个弧线跨越 3-7 章。
返回严格 JSON 格式：
{{
  "arcs": [
    {{
      "name": "弧线名称",
      "chapters": [1, 2, 3],
      "phase": "setup 或 escalation 或 climax 或 resolution",
      "hook": "弧线开头的钩子",
      "turning_point": "转折点描述"
    }}
  ]
}}
"""

        messages = [
            {"role": "system", "content": "你是专业网文叙事分析师。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = self.llm.chat(
                messages,
                temperature=0.3,
                json_mode=True,
                max_tokens=2048,
            )
            parsed = _parse_json_response(response.content)
            raw_arcs = parsed.get("arcs", [])

            saved_arcs: list[dict] = []
            for i, arc in enumerate(raw_arcs):
                arc_id = f"arc_rebuild_{i}_{uuid4().hex[:6]}"
                name = arc.get("name", f"弧线{i + 1}")
                chapters_list = arc.get("chapters", [])
                phase = arc.get("phase", "setup")
                hook = arc.get("hook")
                turning_point = arc.get("turning_point")

                if phase not in (
                    "setup", "escalation", "climax", "resolution"
                ):
                    phase = "setup"

                self.db.insert_story_unit(
                    arc_id=arc_id,
                    volume_id="rebuild",
                    name=name,
                    chapters_json=json.dumps(chapters_list),
                    phase=phase,
                    hook=hook,
                    turning_point=turning_point,
                )

                saved_arcs.append({
                    "arc_id": arc_id,
                    "name": name,
                    "chapters": chapters_list,
                    "phase": phase,
                })

            log.info("检测到 %d 个故事弧线", len(saved_arcs))
            return saved_arcs

        except Exception as exc:
            log.error("LLM 弧线检测失败: %s", exc)
            return []

    def close(self) -> None:
        """Close the underlying database connection."""
        if self.db:
            self.db.close()


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------


def _extract_key_terms(description: str) -> list[str]:
    """Extract 3-5 distinctive Chinese terms from a debt description.

    Strips common labels (like ``角色承诺:``) and splits on punctuation
    to produce 2-char terms from different parts of the description.

    Args:
        description: Debt description text.

    Returns:
        List of key term strings (2 chars each).
    """
    # Remove common label prefixes
    cleaned = re.sub(
        r"^(角色承诺|悬念未解|待完成动作|情感未了|叙事债务)\s*[:：]\s*",
        "",
        description,
    )
    if not cleaned:
        return []

    # Split on any non-Chinese-character boundary to get Chinese segments
    segments = re.findall(r"[\u4e00-\u9fff]{2,}", cleaned)
    if not segments:
        return []

    # Generate 2-char terms from multiple positions within each segment
    # This ensures we capture distinctive words like "报仇", "灵珠" etc.
    terms: list[str] = []
    seen: set[str] = set()
    for seg in segments:
        # Sample 2-char terms: start, middle, end
        positions = set()
        positions.add(0)
        if len(seg) >= 4:
            positions.add(len(seg) // 2)
        if len(seg) >= 4:
            positions.add(len(seg) - 2)

        for pos in sorted(positions):
            if pos + 2 <= len(seg):
                term = seg[pos:pos + 2]
                if term not in seen:
                    seen.add(term)
                    terms.append(term)
                    if len(terms) >= 5:
                        return terms

    return terms


def _parse_json_response(text: str) -> dict:
    """Parse JSON from an LLM response, handling markdown code blocks."""
    if not text or not text.strip():
        return {}

    text = text.strip()

    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Try markdown code block
    code_block = re.search(
        r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL
    )
    if code_block:
        try:
            result = json.loads(code_block.group(1).strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Try to find first { ... } block
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            result = json.loads(text[brace_start:brace_end + 1])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    log.warning("无法从LLM响应中解析JSON: %s", text[:200])
    return {}
