"""ConsistencyChecker - 一致性检查官 Agent

负责：
1. 从章节文本提取关键事实
2. 执行三层混合一致性检查（SQLite / NetworkX / Vector）
3. 对模糊矛盾进行 LLM 裁决
4. 生成一致性报告

所有方法均为同步（SYNC），与 LLMClient.chat() 保持一致。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.novel.agents.state import Decision, NovelState
from src.novel.tools.consistency_tool import ConsistencyTool

log = logging.getLogger("novel")


def _make_decision(
    step: str,
    decision: str,
    reason: str,
    data: dict[str, Any] | None = None,
) -> Decision:
    """创建 ConsistencyChecker 的决策记录。"""
    return Decision(
        agent="ConsistencyChecker",
        step=step,
        decision=decision,
        reason=reason,
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


class ConsistencyChecker:
    """一致性检查官 Agent

    通过 ConsistencyTool 执行三层矛盾检测，
    对 confidence 在 [0.4, 0.8) 区间的模糊矛盾进行 LLM 裁决。
    """

    LLM_JUDGE_THRESHOLD_LOW = 0.4
    LLM_JUDGE_THRESHOLD_HIGH = 0.8

    def __init__(self, llm_client: Any) -> None:
        self.llm = llm_client
        self.tool = ConsistencyTool(llm_client)

    def check_chapter(
        self,
        chapter_text: str,
        chapter_number: int,
        memory: Any,
    ) -> dict[str, Any]:
        """完整一致性检查流程。

        步骤：
        1. 从章节文本提取事实
        2. 执行三层一致性检查
        3. 对模糊矛盾进行 LLM 裁决
        4. 汇总报告

        Args:
            chapter_text: 章节文本
            chapter_number: 章节号
            memory: NovelMemory 实例

        Returns:
            dict 包含:
            - facts: 提取的事实列表
            - contradictions: 确认的矛盾列表
            - dismissed: 被排除的假矛盾列表
            - passed: 是否通过一致性检查
        """
        # Step 1: 提取事实
        facts = self.tool.extract_facts(chapter_text, chapter_number)
        log.info("第%d章事实提取完成: %d 个事实", chapter_number, len(facts))

        # Step 2: 三层检查
        raw_contradictions = self.tool.check_consistency(facts, memory)
        log.info(
            "第%d章三层检查完成: %d 个潜在矛盾",
            chapter_number,
            len(raw_contradictions),
        )

        # Step 3: LLM 裁决模糊矛盾
        confirmed: list[dict] = []
        dismissed: list[dict] = []

        for contradiction in raw_contradictions:
            confidence = contradiction.get("confidence", 0)

            if confidence >= self.LLM_JUDGE_THRESHOLD_HIGH:
                # 高 confidence 直接确认
                confirmed.append(contradiction)
            elif confidence >= self.LLM_JUDGE_THRESHOLD_LOW:
                # 模糊区间，LLM 裁决
                is_real, reason = self.tool.service.llm_judge(contradiction)
                if is_real:
                    contradiction["llm_judgment"] = reason
                    contradiction["confidence"] = max(
                        confidence, 0.8
                    )
                    confirmed.append(contradiction)
                else:
                    contradiction["dismissed_reason"] = reason
                    dismissed.append(contradiction)
            else:
                # 低 confidence 直接排除
                dismissed.append(contradiction)

        passed = len(confirmed) == 0

        return {
            "facts": [f.model_dump() for f in facts],
            "contradictions": confirmed,
            "dismissed": dismissed,
            "passed": passed,
            "chapter_number": chapter_number,
        }

    def check_narrative_logic(
        self,
        chapter_text: str,
        chapter_number: int,
        previous_summary: str,
        chapter_outline_hint: str = "",
    ) -> list[dict[str, Any]]:
        """LLM-based narrative logic check for the current chapter.

        Detects:
        - Plot thread continuity (foreshadowing / setups must be followed up)
        - Dangling threads (missions, tasks, plans left unaddressed)
        - Character whereabouts (characters cannot vanish mid-action)
        - Character resurrection / disappearance
        - Event duplication
        - Data inconsistency (numbers, distances, times)

        Args:
            chapter_text: Current chapter text
            chapter_number: Current chapter number
            previous_summary: Summary of previous chapters for context
            chapter_outline_hint: Optional outline info for this chapter
                (goal, key events) so the checker can verify they are addressed

        Returns:
            List of narrative logic issues found
        """
        if not previous_summary:
            return []

        # Build optional outline section
        outline_section = ""
        if chapter_outline_hint:
            outline_section = (
                f"\n【第{chapter_number}章大纲要求】\n"
                f"{chapter_outline_hint}\n"
            )

        prompt = (
            f"请检查以下第{chapter_number}章内容是否存在叙事逻辑问题。\n\n"
            f"【前文摘要（最近1-2章的关键情节）】\n{previous_summary[:3000]}\n"
            f"{outline_section}\n"
            f"【第{chapter_number}章正文】\n{chapter_text[:3000]}\n\n"
            "请逐项检查以下问题：\n\n"
            "## A. 情节线索连贯性（最重要）\n"
            "1. **伏笔/铺垫延续**：前文设置的伏笔、铺垫、悬念，本章是否合理延续或至少提及？"
            "如果前文提到了某个重要线索（如派人去某地、发现某个秘密、收到某个消息），"
            "本章不能完全忽略它。\n"
            "2. **悬挂线索**：前文中角色被指派的任务、做出的承诺、出发去执行的行动，"
            "本章是否有交代进展？如果角色A在上一章说'我去铁剑门谈判'，"
            "本章必须提到这件事的进展或结果，不能当它没发生过。\n"
            "3. **角色去向**：上一章末尾某角色正在做某事或去某地，"
            "本章该角色不能毫无交代地消失或出现在完全无关的地方。\n\n"
            "## B. 基础一致性\n"
            "4. 角色生死状态：是否有已死角色复活或正常对话的情况？\n"
            "5. 事件重复：是否有同一个事件（战斗、会议、发现）被描写了两次以上？\n"
            "6. 数据一致：距离、时间、数量等具体数字是否前后矛盾？\n"
            "7. 方案闭环：是否有提出的计划/方案没有交代结果？\n\n"
            "**判断标准**：只报告确实存在的问题。"
            "如果前文只是轻微提及某事而非重要铺垫，不算问题。"
            "只有明确的、读者会注意到的断裂才需要报告。\n\n"
            "请以 JSON 格式返回：\n"
            '{"issues": [{"type": "问题类型", "description": "具体描述", '
            '"severity": "high/medium/low"}]}\n'
            '类型可选值：伏笔断裂、悬挂线索、角色失踪、角色复活、'
            '事件重复、数据矛盾、方案未闭环\n'
            "如果没有发现问题，返回：{\"issues\": []}"
        )

        try:
            response = self.llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一位严谨的小说编辑，专门检查章节间的叙事连贯性。"
                            "你特别关注情节线索是否在章节间断裂——"
                            "即前文铺垫的事件、任务、承诺是否在后续章节中被遗忘。"
                            "只报告确实存在的问题，不要捏造问题。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                json_mode=True,
            )

            from src.novel.utils import extract_json_from_llm

            parsed = extract_json_from_llm(response.content)
            issues = parsed.get("issues", [])
            if not isinstance(issues, list):
                return []

            # Convert to contradiction-compatible format
            results: list[dict[str, Any]] = []
            severity_confidence = {"high": 0.8, "medium": 0.6, "low": 0.4}
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                severity = issue.get("severity", "medium")
                results.append({
                    "layer": "narrative_logic",
                    "type": issue.get("type", "unknown"),
                    "fact": {
                        "chapter": chapter_number,
                        "content": issue.get("description", ""),
                    },
                    "conflicting_fact": {
                        "chapter": chapter_number,
                        "content": "叙事逻辑检查",
                    },
                    "confidence": severity_confidence.get(severity, 0.6),
                    "reason": issue.get("description", ""),
                })
            return results
        except Exception as exc:
            log.warning("叙事逻辑检查失败: %s", exc)
            return []


# ---------------------------------------------------------------------------
# LangGraph 节点函数
# ---------------------------------------------------------------------------


def consistency_checker_node(state: NovelState) -> dict[str, Any]:
    """LangGraph 节点：ConsistencyChecker。

    检查当前章节草稿的一致性。

    从 state 中读取:
    - current_chapter_text: 当前章节文本
    - current_chapter: 当前章节号
    - config.llm: LLM 配置

    更新 state:
    - current_chapter_quality: 添加一致性检查结果
    - decisions: 添加决策记录
    - errors: 添加错误信息（如有）
    - completed_nodes: 添加 "consistency_checker"
    """
    from src.llm.llm_client import create_llm_client

    decisions: list[Decision] = []
    errors: list[dict] = []

    chapter_text = state.get("current_chapter_text", "")
    chapter_number = state.get("current_chapter", 0)

    if not chapter_text:
        errors.append(
            {
                "agent": "ConsistencyChecker",
                "message": "当前章节文本为空，无法检查一致性",
            }
        )
        return {
            "errors": errors,
            "completed_nodes": ["consistency_checker"],
        }

    # 省 token：前3章跳过完整一致性检查（还没有足够上下文产生矛盾）
    # 之后每3章做一次完整检查，其余章节仅标记通过
    if chapter_number <= 3 or (chapter_number > 3 and chapter_number % 3 != 0):
        log.info("第%d章跳过完整一致性检查（省 token）", chapter_number)
        existing_quality = state.get("current_chapter_quality") or {}
        return {
            "current_chapter_quality": {
                **existing_quality,
                "consistency_check": {"passed": True, "contradictions": [], "skipped": True},
            },
            "decisions": [_make_decision(
                step="skip_check",
                decision="跳过完整检查",
                reason=f"第{chapter_number}章：降频策略",
            )],
            "errors": [],
            "completed_nodes": ["consistency_checker"],
        }

    # 每9章做一次完整 LLM 检查，其余用 BM25 轻量检查
    use_bm25 = chapter_number % 9 != 0

    # Build narrative context (shared by BM25 + full LLM paths)
    previous_summary, chapter_outline_hint = _build_narrative_context(
        state, chapter_number
    )

    # ---- BM25 lightweight check ----
    if use_bm25:
        bm25_report = _bm25_check(state, chapter_text, chapter_number)
        decisions.append(
            _make_decision(
                step="bm25_check",
                decision="通过" if bm25_report["passed"] else "发现潜在矛盾",
                reason=f"BM25 轻量检查，{len(bm25_report['contradictions'])} 个潜在矛盾",
                data={"contradictions_count": len(bm25_report["contradictions"])},
            )
        )

        # Run narrative logic check alongside BM25 (1 LLM call) to catch
        # plot thread breaks that keyword matching cannot detect.
        narrative_issues = _run_narrative_logic_check(
            state, chapter_text, chapter_number,
            previous_summary, chapter_outline_hint,
            decisions, errors,
        )

        all_contradictions = bm25_report["contradictions"] + narrative_issues
        overall_passed = bm25_report["passed"] and len(narrative_issues) == 0

        existing_quality = state.get("current_chapter_quality") or {}
        return {
            "current_chapter_quality": {
                **existing_quality,
                "consistency_check": {
                    **bm25_report,
                    "contradictions": all_contradictions,
                    "passed": overall_passed,
                    "narrative_issues_count": len(narrative_issues),
                },
            },
            "decisions": decisions,
            "errors": errors,
            "completed_nodes": ["consistency_checker"],
        }

    # ---- Full LLM check (every 9th chapter) ----

    # 初始化 LLM
    llm_config = state.get("config", {}).get("llm", {})
    try:
        llm = create_llm_client(llm_config)
    except Exception as exc:
        errors.append(
            {
                "agent": "ConsistencyChecker",
                "message": f"LLM 初始化失败: {exc}",
            }
        )
        return {
            "errors": errors,
            "completed_nodes": ["consistency_checker"],
        }

    checker = ConsistencyChecker(llm)

    # 初始化 NovelMemory（简化：从 state 的 workspace 获取）
    novel_id = state.get("novel_id", "unknown")
    workspace = state.get("workspace", "/tmp")

    try:
        from src.novel.storage.novel_memory import NovelMemory

        memory = NovelMemory(novel_id, workspace)
    except Exception as exc:
        log.warning("记忆系统初始化失败，使用空检查: %s", exc)
        errors.append(
            {
                "agent": "ConsistencyChecker",
                "message": f"记忆系统初始化失败: {exc}",
            }
        )
        return {
            "errors": errors,
            "completed_nodes": ["consistency_checker"],
        }

    # 执行检查
    try:
        report = checker.check_chapter(chapter_text, chapter_number, memory)
        decisions.append(
            _make_decision(
                step="check_chapter",
                decision="通过" if report["passed"] else "发现矛盾",
                reason=f"提取{len(report['facts'])}个事实，发现{len(report['contradictions'])}个矛盾",
                data={
                    "contradictions_count": len(report["contradictions"]),
                    "dismissed_count": len(report["dismissed"]),
                },
            )
        )
    except Exception as exc:
        log.error("一致性检查失败: %s", exc)
        errors.append(
            {
                "agent": "ConsistencyChecker",
                "message": f"一致性检查失败: {exc}",
            }
        )
        return {
            "decisions": decisions,
            "errors": errors,
            "completed_nodes": ["consistency_checker"],
        }
    finally:
        try:
            memory.close()
        except Exception:
            pass

    # 叙事逻辑检查（在完整 LLM 检查时额外执行）
    narrative_issues = _run_narrative_logic_check(
        state, chapter_text, chapter_number,
        previous_summary, chapter_outline_hint,
        decisions, errors,
        checker=checker,
    )

    # Merge narrative issues into report contradictions
    all_contradictions = report["contradictions"] + narrative_issues
    overall_passed = report["passed"] and len(narrative_issues) == 0

    # 合并质量信息
    existing_quality = state.get("current_chapter_quality") or {}
    updated_quality = {
        **existing_quality,
        "consistency_check": {
            "passed": overall_passed,
            "contradictions": all_contradictions,
            "facts_count": len(report["facts"]),
            "narrative_issues_count": len(narrative_issues),
        },
    }

    return {
        "current_chapter_quality": updated_quality,
        "decisions": decisions,
        "errors": errors,
        "completed_nodes": ["consistency_checker"],
    }


def _build_narrative_context(
    state: NovelState,
    chapter_number: int,
) -> tuple[str, str]:
    """Build previous-chapter summary and chapter outline hint from state.

    Returns:
        (previous_summary, chapter_outline_hint) tuple.
    """
    # -- Previous summary: last 2 chapters, 1000 chars each (enough to
    #    capture plot threads, missions, foreshadowing at chapter end) --
    previous_summary = ""
    chapters_done = state.get("chapters", [])
    if chapters_done:
        recent_chapters = chapters_done[-2:]
        summary_parts = []
        for ch in recent_chapters:
            ch_num = ch.get("chapter_number", "?")
            ch_text = ch.get("full_text", "")
            if ch_text:
                # Use first 500 chars (setup) + last 500 chars (conclusions/hooks)
                head = ch_text[:500]
                tail = ch_text[-500:] if len(ch_text) > 500 else ""
                separator = "\n...\n" if tail else ""
                summary_parts.append(
                    f"第{ch_num}章：{head}{separator}{tail}"
                )
        previous_summary = "\n\n".join(summary_parts)

    # -- Chapter outline hint: what this chapter is supposed to accomplish --
    chapter_outline_hint = ""
    ch_outline = state.get("current_chapter_outline")
    if ch_outline and isinstance(ch_outline, dict):
        hint_parts = []
        if ch_outline.get("title"):
            hint_parts.append(f"标题：{ch_outline['title']}")
        if ch_outline.get("goal"):
            hint_parts.append(f"目标：{ch_outline['goal']}")
        if ch_outline.get("key_events"):
            events = ch_outline["key_events"]
            if isinstance(events, list):
                events = "、".join(events)
            hint_parts.append(f"关键事件：{events}")
        chapter_outline_hint = "\n".join(hint_parts)

    return previous_summary, chapter_outline_hint


def _run_narrative_logic_check(
    state: NovelState,
    chapter_text: str,
    chapter_number: int,
    previous_summary: str,
    chapter_outline_hint: str,
    decisions: list,
    errors: list,
    checker: ConsistencyChecker | None = None,
) -> list[dict[str, Any]]:
    """Run narrative logic check, creating a ConsistencyChecker if needed.

    This is factored out so both BM25 and full-LLM paths can call it.
    Returns the list of narrative issues found (may be empty).
    """
    if not previous_summary:
        return []

    # Create checker if not provided (BM25 path)
    if checker is None:
        from src.llm.llm_client import create_llm_client

        llm_config = state.get("config", {}).get("llm", {})
        try:
            llm = create_llm_client(llm_config)
        except Exception as exc:
            log.warning("叙事逻辑检查 LLM 初始化失败: %s", exc)
            errors.append({
                "agent": "ConsistencyChecker",
                "message": f"叙事逻辑检查 LLM 初始化失败: {exc}",
            })
            return []
        checker = ConsistencyChecker(llm)

    try:
        narrative_issues = checker.check_narrative_logic(
            chapter_text, chapter_number, previous_summary,
            chapter_outline_hint=chapter_outline_hint,
        )
        if narrative_issues:
            decisions.append(
                _make_decision(
                    step="narrative_logic_check",
                    decision=f"发现{len(narrative_issues)}个叙事逻辑问题",
                    reason="叙事逻辑检查：情节线索连贯性/角色去向/悬挂线索",
                    data={"issues_count": len(narrative_issues)},
                )
            )
        return narrative_issues
    except Exception as exc:
        log.warning("叙事逻辑检查异常: %s", exc)
        return []


def _bm25_check(
    state: NovelState,
    chapter_text: str,
    chapter_number: int,
) -> dict[str, Any]:
    """BM25-based lightweight consistency check (no LLM).

    Builds a BM25 index from previous chapters, then for each character
    queries relevant passages and does simple rule-based contradiction
    detection (e.g. "X died" vs "X appeared").

    Returns a dict compatible with the consistency_check quality shape.
    """
    from src.novel.tools.bm25_retriever import BM25Retriever

    retriever = BM25Retriever()

    # Load previous chapters from state
    chapters_text: dict[int, str] = state.get("chapters_text") or {}
    for ch_num in sorted(chapters_text):
        if ch_num < chapter_number:
            retriever.add_chapter(ch_num, chapters_text[ch_num])

    # Also index the current chapter
    retriever.add_chapter(chapter_number, chapter_text)

    # Extract character names from state
    characters: list[dict] = state.get("characters") or []
    char_names = [c.get("name", "") for c in characters if c.get("name")]

    contradictions: list[dict[str, Any]] = []

    # Death / disappearance keywords that signal permanent state
    _DEATH_KEYWORDS = ("死", "亡", "殒命", "丧命", "身亡", "去世", "陨落")
    _ALIVE_KEYWORDS = ("出现", "说道", "笑道", "走", "拿", "站", "坐")
    # Departure keywords — character leaves to do something
    _DEPARTURE_KEYWORDS = ("我去", "前去", "出发", "赶往", "动身", "启程", "去执行")

    for name in char_names:
        passages = retriever.query_by_entity(name, top_k=10)
        death_refs: list[dict] = []
        alive_refs: list[dict] = []
        departure_refs: list[dict] = []

        for p in passages:
            text = p["text"]
            if name not in text:
                continue
            if any(kw in text for kw in _DEATH_KEYWORDS):
                death_refs.append(p)
            if any(kw in text for kw in _ALIVE_KEYWORDS):
                alive_refs.append(p)
            if any(kw in text for kw in _DEPARTURE_KEYWORDS):
                departure_refs.append(p)

        # Check 1: Dead character reappearing alive
        for d_ref in death_refs:
            for a_ref in alive_refs:
                if a_ref["chapter"] > d_ref["chapter"]:
                    contradictions.append({
                        "layer": "bm25",
                        "character": name,
                        "type": "character_resurrection",
                        "fact": {
                            "chapter": a_ref["chapter"],
                            "content": a_ref["text"][:100],
                        },
                        "conflicting_fact": {
                            "chapter": d_ref["chapter"],
                            "content": d_ref["text"][:100],
                        },
                        "confidence": 0.5,
                        "reason": f"{name}在第{d_ref['chapter']}章疑似死亡，但在第{a_ref['chapter']}章再次出现",
                    })

        # Check 2: Character departed but never followed up
        # If a character departed in an earlier chapter but has no further
        # mentions in any subsequent chapter, flag as potential missing follow-up
        if departure_refs and chapter_number > 1:
            for dep_ref in departure_refs:
                dep_ch = dep_ref["chapter"]
                if dep_ch >= chapter_number:
                    continue
                # Check if character has any mention in chapters after departure
                has_followup = any(
                    p["chapter"] > dep_ch
                    for p in passages
                    if name in p["text"]
                )
                if not has_followup:
                    contradictions.append({
                        "layer": "bm25",
                        "character": name,
                        "type": "character_disappeared",
                        "fact": {
                            "chapter": dep_ch,
                            "content": dep_ref["text"][:100],
                        },
                        "conflicting_fact": {
                            "chapter": chapter_number,
                            "content": f"第{dep_ch}章后{name}再无出现",
                        },
                        "confidence": 0.4,
                        "reason": f"{name}在第{dep_ch}章说要去执行任务后消失，后续无任何交代",
                    })

    # Check 3: Event duplication — detect highly similar passages across chapters
    _EVENT_KEYWORDS = (
        "发布会", "会议", "战斗", "攻击", "爆炸", "仪式", "典礼",
        "审判", "宣布", "签署", "演讲", "庆典",
    )
    event_passages: dict[str, list[dict]] = {}
    all_chapters_text = dict(chapters_text)
    all_chapters_text[chapter_number] = chapter_text
    for ch_num in sorted(all_chapters_text):
        retriever_temp = BM25Retriever()
        retriever_temp.add_chapter(ch_num, all_chapters_text[ch_num])
        for kw in _EVENT_KEYWORDS:
            hits = retriever_temp.query(kw, top_k=3)
            for h in hits:
                if kw in h.get("text", ""):
                    event_passages.setdefault(kw, []).append(h)

    for kw, hits in event_passages.items():
        # Group by chapter — if same event keyword appears in multiple chapters
        chapters_with_event: dict[int, str] = {}
        for h in hits:
            ch = h["chapter"]
            if ch not in chapters_with_event:
                chapters_with_event[ch] = h["text"][:100]
        if len(chapters_with_event) >= 2:
            ch_list = sorted(chapters_with_event.keys())
            contradictions.append({
                "layer": "bm25",
                "type": "event_duplication",
                "fact": {
                    "chapter": ch_list[-1],
                    "content": chapters_with_event[ch_list[-1]],
                },
                "conflicting_fact": {
                    "chapter": ch_list[0],
                    "content": chapters_with_event[ch_list[0]],
                },
                "confidence": 0.35,
                "reason": f"「{kw}」事件在第{ch_list[0]}章和第{ch_list[-1]}章重复出现，可能是重复描写",
            })

    return {
        "passed": len(contradictions) == 0,
        "contradictions": contradictions,
        "method": "bm25",
    }
