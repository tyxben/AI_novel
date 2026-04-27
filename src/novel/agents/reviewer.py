"""Reviewer — 合并后的审稿编辑 Agent（Phase 2-β）。

取代以下三个 Agent：

* ``QualityReviewer``：打分 + 规则硬指标 → **删除** 打分维度，保留批评
* ``ConsistencyChecker``：LLM 事实提取/三层矛盾 → **退化**为 Ledger 快照对读
* ``StyleKeeper``：风格预设对比 + AI 黑名单 → **退化**为 StyleProfile.detect_overuse

核心理念（``specs/architecture-rework-2026/DESIGN.md`` Part 2 A5）：

1. **不打分** — 只标问题 / 给建议 / 写总评
2. **不触发自动重写** — ``need_rewrite`` 退化为信息标签
3. watchlist 来自 **StyleProfile**（本书自己的口头禅）+ 用户显式 config
4. 可选接 **LedgerStore**，缺时优雅降级（仍可只跑 LLM 批评 + StyleProfile）

ChapterCritic 旧职责完全并入此处；``src/novel/agents/chapter_critic.py``
删除，老调用路径（``agent_chat._tool_critique_chapter`` / ``refine_chapter`` /
``refine_loop``）改 import ``Reviewer`` 并用其 ``review()`` 方法。

LangGraph 节点：``reviewer_node`` 是 chapter graph 的唯一审稿节点，
替代 ``consistency_checker + style_keeper + quality_reviewer`` 三节点并行/串行。
"""

from __future__ import annotations

import logging
import re as _re
from datetime import datetime, timezone
from typing import Any

from src.llm.llm_client import LLMClient
from src.novel.agents.state import Decision, NovelState
from src.novel.models.critique_result import (
    ConsistencyFlag,
    CritiqueIssue,
    CritiqueResult,
    Revision,
)
from src.novel.utils.json_extract import extract_json_obj

log = logging.getLogger("novel.reviewer")


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT_TEMPLATE = """你是一位资深小说编辑，正在给一本中文长篇小说做结构化审稿。

你的任务是给出**可执行的修改建议**，不是泛泛打分。

审稿维度：
- pacing（节奏）：拖沓、信息堆叠、转场生硬
- characterization（人物）：动机不清、性格漂移、配角脸谱化
- world_consistency（世界观）：与已建立设定矛盾、突然引入无铺垫的新元素
- dialogue（对话）：所有人语气雷同、独白过长、对白不推进剧情
- trope_overuse（套路化表达）：**根据场景判断**是否滥用，不要机械数次数。
  下面是本书的观察名单（watchlist，不是禁用名单）：{watchlist_block}
  判断准则：
    · 单次出现 + 场景匹配（如"瞳孔骤缩"用在惊愕反转处）→ 不算 issue
    · 同一短语在本章 ≥3 次，或用在不需要强烈情绪的场景 → 标 issue
    · 全章弥漫套话堆砌 → 标 high
- transition（衔接）：与上章脱节、首句重复、悬念断裂
- logic（逻辑）：情节矛盾、时间线错乱、动作不合理
- consistency（一致性）：与前文事实/角色状态/伏笔承诺冲突（附 ledger 快照参考）

严格输出 JSON：
{{
  "strengths": ["..."],
  "issues": [
    {{"type": "pacing|characterization|...", "severity": "low|medium|high",
     "quote": "原文引用，≤80字", "reason": "问题描述"}}
  ],
  "specific_revisions": [
    {{"target": "原文引用，≤80字", "suggestion": "改成什么样"}}
  ],
  "overall_assessment": "≤200字总评"
}}

要求：
- 不要输出 JSON 之外的任何文字（不要 markdown 代码块）
- issues 至少 1 条，严重的标 high
- specific_revisions 至少 2 条，针对最严重的问题
- 引用原文要精确，不要意译
- 章节质量好就少标 issues，但 strengths 必须填
"""


def _build_system_prompt(watchlist: dict[str, int] | list[str] | None) -> str:
    """Render the watchlist block.

    Accepts the two common shapes in this codebase:

    - ``dict[phrase, threshold]`` — legacy ``ai_flavor_watchlist`` config
    - ``list[phrase]`` — StyleProfile-derived overused phrases (no threshold)
    """
    if not watchlist:
        block = "（本次未提供观察名单）"
    elif isinstance(watchlist, dict):
        items = [f"{p}(≥{n}次需关注)" for p, n in watchlist.items()]
        block = "、".join(items) if items else "（空）"
    else:
        items = list(watchlist)
        block = "、".join(items) if items else "（空）"
    return _SYSTEM_PROMPT_TEMPLATE.format(watchlist_block=block)


# ---------------------------------------------------------------------------
# 跨章 verbatim 兜底维度（C 阶段 P2，2026-04-28）
# ---------------------------------------------------------------------------
#
# P0 (commit ffffda2) + C3 (commit 15095b3) 物理切断了 Writer 直读上章原文
# 的所有路径，但万一未来有新通道把生原文塞进 Writer prompt（e.g. 新加的
# pipeline 入口忘走 summarizer），本维度作为兜底网立刻报警。纯规则，零 LLM。
#
# 算法：char-level 5-gram Jaccard。比 sentence-level 更敏感——能抓"换标点
# 改一字"的浅改写抄袭。计算量 O(N+M) 对 N=2500 章节 + M=500 prev_tail 不
# 影响 review 性能（~ms 级）。

_CROSS_CHAPTER_NGRAM = 5
"""char n-gram length for cross-chapter verbatim detection."""

_CROSS_CHAPTER_JACCARD_THRESHOLD = 0.6
"""Jaccard ≥ 此值 → 视为跨章 verbatim 复读，加 high severity issue。

阈值 0.6 经验值：normal 续写衔接（"他点了点头" 类微量重叠）远低于 0.1；
P0 ch32 复读 ch31 末段 6000 字的事故 case 实测 5-gram Jaccard ≈ 0.85+。
0.6 是清晰分界线，false-positive 风险低。
"""


def _char_ngrams(text: str, n: int = _CROSS_CHAPTER_NGRAM) -> set[str]:
    """Char n-gram set。空白标准化后切，过滤 < n 字的输入。"""
    if not text:
        return set()
    # 压缩连续空白：保留汉字/字母/数字 + 标点都按字符算
    cleaned = _re.sub(r"\s+", "", text)
    if len(cleaned) < n:
        return set()
    return {cleaned[i : i + n] for i in range(len(cleaned) - n + 1)}


def _ngram_jaccard(a: str, b: str, n: int = _CROSS_CHAPTER_NGRAM) -> float:
    """Char n-gram Jaccard 相似度。两侧任一 n-gram set 为空 → 0.0。"""
    set_a = _char_ngrams(a, n)
    set_b = _char_ngrams(b, n)
    if not set_a or not set_b:
        return 0.0
    inter = set_a & set_b
    union = set_a | set_b
    return len(inter) / len(union) if union else 0.0


# ---------------------------------------------------------------------------
# Reviewer
# ---------------------------------------------------------------------------


class Reviewer:
    """审稿编辑：只标问题不打分，不触发自动重写。

    Args:
        llm: LLMClient。必须传入，空则 :meth:`review` 只能返回纯规则部分。
        ledger: 可选 :class:`LedgerStore`。接入后 :meth:`review` 会
            根据章节号拉 snapshot 做一致性比对。缺失时 ``consistency_flags``
            返回空。
        style_profile: 可选 :class:`StyleProfile`（本书的用词指纹）。
            接入后 :meth:`review` 会用 ``detect_overuse`` 检查新文本里的
            本书口头禅。
        style_profile_service: 可选 :class:`StyleProfileService`。
            缺省时会按需 lazy 构造（用于 ``detect_overuse``）。
        watchlist: 用户显式配置的观察名单（``{phrase: threshold}``）。
            与 StyleProfile 的 overused_phrases 合并后送进系统提示。
    """

    def __init__(
        self,
        llm: LLMClient | None,
        *,
        ledger: Any | None = None,
        style_profile: Any | None = None,
        style_profile_service: Any | None = None,
        watchlist: dict[str, int] | None = None,
    ) -> None:
        self.llm = llm
        self.ledger = ledger
        self.style_profile = style_profile
        self.watchlist = dict(watchlist or {})
        self._style_service = style_profile_service

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    def review(
        self,
        chapter_text: str,
        *,
        chapter_number: int = 0,
        chapter_title: str = "",
        chapter_goal: str = "",
        previous_tail: str = "",
        prior_critiques: list[CritiqueResult] | None = None,
        chapter_brief: dict | None = None,
        active_characters: list[str] | None = None,
    ) -> CritiqueResult:
        """对章节执行审稿。

        内部顺序：

        1. 质量维度（LLM 批评）— 取代 QualityReviewer 的非打分部分
        2. 风格维度 — StyleProfile.detect_overuse 命中（本书自己的口头禅）
        3. 一致性维度 — 对 LedgerStore.snapshot_for_chapter 做规则对读

        Args:
            chapter_text: 已 sanitize 过的章节正文。
            chapter_number: 本章章节号（用于 ledger 查询与报告标识）。
            chapter_title: 本章标题（可选，注入 LLM prompt）。
            chapter_goal: 本章目标（可选，注入 LLM prompt）。
            previous_tail: 上一章末尾若干字（用于检查衔接）。
            prior_critiques: 同章节之前批评轮次（避免重复指出已修复）。
            chapter_brief: 章节任务书（可选，用于 ledger 对读）。
            active_characters: 本章活跃角色名（可选，用于 ledger 对读）。

        Returns:
            CritiqueResult。LLM 失败时返回仅含规则部分的 result（raw_response
            标注错误）。
        """
        # ---- 1. LLM 批评维度（可选）----
        llm_result = self._run_llm_critique(
            chapter_text=chapter_text,
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            chapter_goal=chapter_goal,
            previous_tail=previous_tail,
            prior_critiques=prior_critiques or [],
        )

        # ---- 2. StyleProfile overuse 维度（纯规则）----
        overuse_hits = self._detect_style_overuse(chapter_text)
        # 命中≥3个且每个在本章至少出现2次 → 额外加一条 style_overuse issue
        if overuse_hits:
            dense = self._dense_overuse_hits(chapter_text, overuse_hits)
            if dense:
                llm_result.issues.append(
                    CritiqueIssue(
                        type="style_overuse",
                        severity="medium" if len(dense) < 5 else "high",
                        quote="、".join(dense[:8]),
                        reason=(
                            f"本章命中 {len(dense)} 个本书高频短语（口头禅），"
                            "考虑用更个性化的表达替换部分出现点"
                        ),
                    )
                )

        # ---- 3. Ledger 一致性维度（纯规则）----
        consistency_flags = self._check_ledger_consistency(
            chapter_text=chapter_text,
            chapter_number=chapter_number,
            chapter_brief=chapter_brief,
            active_characters=active_characters,
        )
        # 任一 high-severity consistency flag → 加条 issue，便于作者看总结时注意
        for flag in consistency_flags:
            if flag.severity == "high":
                llm_result.issues.append(
                    CritiqueIssue(
                        type="consistency",
                        severity="high",
                        quote="",
                        reason=f"[{flag.type}] {flag.detail}",
                    )
                )

        # ---- 4. 跨章 verbatim 兜底维度（纯规则，C 阶段 P2 加）----
        # P0/C3 已物理切断 Writer 直读上章原文的所有通道。万一未来新加的
        # pipeline 入口忘走 summarizer，本兜底网立刻报警。
        cross_issue = self._check_cross_chapter_verbatim(
            chapter_text=chapter_text,
            previous_tail=previous_tail,
        )
        if cross_issue is not None:
            llm_result.issues.append(cross_issue)

        llm_result.chapter_number = chapter_number
        llm_result.style_overuse_hits = overuse_hits
        llm_result.consistency_flags = consistency_flags
        llm_result.need_rewrite = bool(
            llm_result.high_severity_count > 0
            or llm_result.medium_severity_count >= 2
            or any(f.severity == "high" for f in consistency_flags)
        )
        return llm_result

    # Backwards-compat alias for old ChapterCritic callers.
    critique = review

    # ------------------------------------------------------------------
    # LLM critique
    # ------------------------------------------------------------------

    def _run_llm_critique(
        self,
        *,
        chapter_text: str,
        chapter_number: int,
        chapter_title: str,
        chapter_goal: str,
        previous_tail: str,
        prior_critiques: list[CritiqueResult],
    ) -> CritiqueResult:
        if self.llm is None:
            return CritiqueResult(
                chapter_number=chapter_number,
                raw_response="LLM 不可用，仅运行规则维度",
            )

        user_prompt = self._build_user_prompt(
            chapter_text=chapter_text,
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            chapter_goal=chapter_goal,
            prev_chapter_tail=previous_tail,
            prior_critiques=prior_critiques,
        )
        # watchlist 合并：用户 config + StyleProfile 的 top-N overused
        effective_watchlist: dict[str, int] | list[str]
        if self.style_profile and getattr(self.style_profile, "overused_phrases", None):
            # list form (no threshold)
            sp_list = [
                p.phrase
                for p in self.style_profile.overused_phrases[:20]
                if getattr(p, "phrase", "")
            ]
            if self.watchlist:
                # mix both shapes: dict takes precedence, append phrases
                merged_list = list(self.watchlist.keys()) + [
                    w for w in sp_list if w not in self.watchlist
                ]
                effective_watchlist = merged_list
            else:
                effective_watchlist = sp_list
        else:
            effective_watchlist = self.watchlist

        messages = [
            {"role": "system", "content": _build_system_prompt(effective_watchlist)},
            {"role": "user", "content": user_prompt},
        ]
        try:
            resp = self.llm.chat(
                messages,
                temperature=0.3,
                json_mode=True,
                max_tokens=2048,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Reviewer LLM call failed: %s", exc)
            return CritiqueResult(
                chapter_number=chapter_number,
                raw_response=f"LLM 调用失败: {exc}",
            )

        raw = (resp.content or "").strip()
        return self._parse_response(raw, chapter_number=chapter_number)

    # ------------------------------------------------------------------
    # StyleProfile overuse
    # ------------------------------------------------------------------

    def _detect_style_overuse(self, text: str) -> list[str]:
        """用 StyleProfile 检测本章命中的本书口头禅。缺失时返回 []。"""
        if not self.style_profile or not text:
            return []
        try:
            if self._style_service is None:
                from src.novel.services.style_profile_service import (
                    StyleProfileService,
                )

                self._style_service = StyleProfileService()
            return list(
                self._style_service.detect_overuse(text, self.style_profile)
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("Reviewer detect_overuse failed: %s", exc)
            return []

    @staticmethod
    def _dense_overuse_hits(text: str, phrases: list[str]) -> list[str]:
        """从命中短语里筛出"本章出现 >= 2 次"的那些。"""
        dense: list[str] = []
        for p in phrases:
            if not p:
                continue
            # 粗略计数（本书 phrase 是 bi/tri-gram，直接 count 就行）
            try:
                if text.count(p) >= 2:
                    dense.append(p)
            except Exception:
                continue
        return dense

    # ------------------------------------------------------------------
    # 跨章 verbatim 兜底（C 阶段 P2，2026-04-28）
    # ------------------------------------------------------------------

    @staticmethod
    def _check_cross_chapter_verbatim(
        chapter_text: str,
        previous_tail: str,
        threshold: float = _CROSS_CHAPTER_JACCARD_THRESHOLD,
    ) -> CritiqueIssue | None:
        """检查当前章节 vs 上一章末段的 char-5gram Jaccard 相似度。

        C 阶段 P2 兜底网：P0/C3 已物理切断 Writer 直读上章原文的所有通道，
        但万一未来新加的 pipeline 入口忘走 summarizer，本规则立刻报警。

        Args:
            chapter_text: 当前章节正文。
            previous_tail: 上一章末尾若干字（C3 修复后是 500 字原文）。
            threshold: Jaccard 阈值，默认 0.6。命中即报 high severity。

        Returns:
            ``CritiqueIssue`` 当 Jaccard >= threshold；否则 ``None``。

            空文本 / previous_tail 为空 / 任一 n-gram set 为空 → 静默返回
            ``None``（既不是问题也不是错误）。
        """
        if not chapter_text or not previous_tail:
            return None
        # 5-gram set 至少要有交集才计算（小输入早退）
        score = _ngram_jaccard(
            chapter_text, previous_tail, n=_CROSS_CHAPTER_NGRAM
        )
        if score < threshold:
            return None
        return CritiqueIssue(
            type="cross_chapter_verbatim",
            severity="high",
            quote="",
            reason=(
                f"本章与上一章末段 char-5gram Jaccard={score:.2f}"
                f"（阈值 {threshold:.2f}），疑似跨章 verbatim 复读。"
                f"检查 ChapterPlanner / Writer 通道是否绕过 summarize_previous_tail。"
            ),
        )

    # ------------------------------------------------------------------
    # Ledger consistency
    # ------------------------------------------------------------------

    def _check_ledger_consistency(
        self,
        *,
        chapter_text: str,
        chapter_number: int,
        chapter_brief: dict | None,
        active_characters: list[str] | None,
    ) -> list[ConsistencyFlag]:
        """规则化的 ledger 快照比对，替代旧 ConsistencyChecker 的三层 LLM 检查。

        只做四种低成本检查：

        1. **伏笔到期未兑现**：``collectable_foreshadowings`` 里的 detail
           未在 chapter_text 中出现
        2. **债务应兑现未兑现**：``pending_debts`` 里 urgency=high/urgent
           的描述未出现
        3. **角色状态冲突**：``active_characters`` 中的角色若 ledger 显示
           ``health=dead`` 但本章正文出现其姓名 + 行动词
        4. **里程碑未达**：``pending_milestones`` 里 target_chapter_range
           含当前章号但未在文中显式出现描述关键字
        """
        if self.ledger is None:
            return []

        try:
            snap = self.ledger.snapshot_for_chapter(chapter_number)
        except Exception as exc:  # noqa: BLE001
            log.debug("Reviewer ledger snapshot failed: %s", exc)
            return []

        flags: list[ConsistencyFlag] = []

        # ---- 1. 伏笔应兑现 ----
        for f in (snap.get("collectable_foreshadowings") or [])[:10]:
            detail = str(
                f.get("detail")
                or f.get("description")
                or f.get("title")
                or ""
            ).strip()
            if not detail:
                continue
            # 核心词命中检查：取 detail 中长度 >=3 的关键子串做近似匹配
            keyword = detail[:12]
            if keyword and keyword not in chapter_text:
                flags.append(
                    ConsistencyFlag(
                        type="foreshadowing",
                        severity="medium",
                        detail=f"应回收的伏笔未在本章兑现：{detail[:80]}",
                        ref_chapter=f.get("planted_chapter"),
                    )
                )

        # ---- 2. 债务应兑现 ----
        for d in (snap.get("pending_debts") or [])[:10]:
            urgency = str(d.get("urgency_level") or d.get("urgency") or "").lower()
            if urgency not in {"high", "urgent", "critical"}:
                continue
            desc = str(d.get("description") or "").strip()
            if not desc:
                continue
            keyword = desc[:12]
            if keyword and keyword not in chapter_text:
                flags.append(
                    ConsistencyFlag(
                        type="debt",
                        severity="high" if urgency in {"urgent", "critical"} else "medium",
                        detail=f"应兑现的叙事债务未体现：{desc[:80]}",
                        ref_chapter=d.get("source_chapter"),
                    )
                )

        # ---- 3. 角色状态冲突（死人复活）----
        names = active_characters or []
        # 如果 caller 没传，从 ledger active_characters 提取
        if not names:
            names = [
                a.get("name", "")
                for a in (snap.get("active_characters") or [])
                if a.get("name")
            ]
        for name in names[:20]:
            if not name or name not in chapter_text:
                continue
            try:
                state = self.ledger.get_character_state(name, chapter_number)
            except Exception:
                state = None
            if not state:
                continue
            health = str(state.get("health") or "").lower()
            if health in {"dead", "死", "已死亡", "deceased"}:
                # 本章正文里出现了该角色，但 ledger 显示已死
                flags.append(
                    ConsistencyFlag(
                        type="character_state",
                        severity="high",
                        detail=(
                            f"角色 {name} 在前文已标记为死亡，"
                            "但本章仍出现其姓名，请复核是否需要铺垫"
                        ),
                    )
                )

        # ---- 4. 里程碑未达（低优先级信息）----
        for m in (snap.get("pending_milestones") or [])[:5]:
            desc = str(m.get("description") or "").strip()
            if not desc:
                continue
            keyword = desc[:10]
            if keyword and keyword not in chapter_text:
                flags.append(
                    ConsistencyFlag(
                        type="milestone",
                        severity="low",
                        detail=f"本章期望达成的里程碑似未提及：{desc[:80]}",
                    )
                )

        return flags

    # ------------------------------------------------------------------
    # Prompt building + parsing (adapted from ChapterCritic)
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        *,
        chapter_text: str,
        chapter_number: int,
        chapter_title: str,
        chapter_goal: str,
        prev_chapter_tail: str,
        prior_critiques: list[CritiqueResult],
    ) -> str:
        parts = [f"## 第{chapter_number}章 {chapter_title}".rstrip()]
        if chapter_goal:
            parts.append(f"\n本章目标：{chapter_goal}")
        if prev_chapter_tail:
            parts.append(
                f"\n【上一章结尾节选】\n{prev_chapter_tail[:500]}"
            )
        if prior_critiques:
            past_issues: list[str] = []
            for c in prior_critiques[-2:]:
                for i in c.issues:
                    past_issues.append(f"- [{i.type}/{i.severity}] {i.reason}")
            if past_issues:
                parts.append(
                    "\n【先前批注（已尝试修复，不要重复指出已解决的问题）】\n"
                    + "\n".join(past_issues[:10])
                )
        parts.append(f"\n【待审章节正文】\n{chapter_text}")
        return "\n".join(parts)

    def _parse_response(self, raw: str, *, chapter_number: int) -> CritiqueResult:
        if not raw:
            return CritiqueResult(
                chapter_number=chapter_number,
                raw_response="LLM 返回空响应",
            )
        try:
            data = extract_json_obj(raw)
        except Exception as exc:  # noqa: BLE001
            log.warning("Reviewer JSON parse failed: %s", exc)
            return CritiqueResult(chapter_number=chapter_number, raw_response=raw)
        if not isinstance(data, dict):
            return CritiqueResult(chapter_number=chapter_number, raw_response=raw)
        try:
            # Build the result manually — pydantic won't coerce lists of plain
            # dicts without the right field names, and we want to preserve the
            # schema's defaults for everything the LLM omitted.
            result = CritiqueResult(
                chapter_number=chapter_number,
                strengths=[str(s) for s in (data.get("strengths") or []) if s],
                issues=[
                    CritiqueIssue.model_validate(i)
                    for i in (data.get("issues") or [])
                    if isinstance(i, dict)
                ],
                specific_revisions=[
                    Revision.model_validate(r)
                    for r in (data.get("specific_revisions") or [])
                    if isinstance(r, dict)
                ],
                overall_assessment=str(data.get("overall_assessment") or "")[:500],
                raw_response=raw,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Reviewer schema validation failed: %s", exc)
            return CritiqueResult(chapter_number=chapter_number, raw_response=raw)
        return result


# ---------------------------------------------------------------------------
# Decision helper
# ---------------------------------------------------------------------------


def _make_decision(
    step: str,
    decision: str,
    reason: str,
    data: dict[str, Any] | None = None,
) -> Decision:
    return Decision(
        agent="Reviewer",
        step=step,
        decision=decision,
        reason=reason,
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------


def reviewer_node(state: NovelState) -> dict[str, Any]:
    """LangGraph 节点：Reviewer。

    取代旧 ``consistency_checker + style_keeper + quality_reviewer`` 三节点。

    行为：
    - 从 state 里拉 chapter_text / chapter_outline / ledger / style_profile
    - 跑 :meth:`Reviewer.review`
    - 把 CritiqueResult 写回 ``state["current_chapter_quality"]``（保持旧字段名
      给 state_writeback 继续用，但内容结构已换）
    - 不修改正文、不回调 writer（零自动重写）
    """
    from src.llm.llm_client import create_llm_client

    from src.novel.llm_utils import get_stage_llm_config

    decisions: list[Decision] = []
    errors: list[dict] = []

    chapter_text = state.get("current_chapter_text") or ""
    chapter_number = state.get("current_chapter", 0)

    if not chapter_text:
        return {
            "errors": [
                {"agent": "Reviewer", "message": "当前章节文本为空，跳过审稿"}
            ],
            "completed_nodes": ["reviewer"],
        }

    # --- LLM (可选) ---
    llm = None
    try:
        llm_config = get_stage_llm_config(state, "quality_review")
        llm = create_llm_client(llm_config)
    except Exception:
        log.info("LLM 不可用，Reviewer 仅跑规则维度")

    # --- LedgerStore (可选) ---
    ledger = state.get("ledger_store")

    # --- StyleProfile (可选) ---
    style_profile = state.get("style_profile")

    # --- watchlist (来自 config) ---
    quality_cfg = (state.get("config", {}) or {}).get("quality", {}) or {}
    watchlist = quality_cfg.get("ai_flavor_watchlist") or None

    reviewer = Reviewer(
        llm,
        ledger=ledger,
        style_profile=style_profile,
        watchlist=watchlist,
    )

    ch_outline = state.get("current_chapter_outline") or {}
    if not isinstance(ch_outline, dict):
        ch_outline = {}

    chapters_done = state.get("chapters") or []
    prev_tail = ""
    if chapters_done:
        prev = chapters_done[-1]
        if isinstance(prev, dict):
            prev_tail = str(prev.get("full_text") or "")[-500:]

    active_chars: list[str] = []
    characters_state = state.get("characters") or []
    if isinstance(characters_state, list):
        active_chars = [
            c.get("name", "")
            for c in characters_state
            if isinstance(c, dict) and c.get("name")
        ][:10]

    try:
        result = reviewer.review(
            chapter_text,
            chapter_number=chapter_number,
            chapter_title=str(ch_outline.get("title") or ""),
            chapter_goal=str(ch_outline.get("goal") or ""),
            previous_tail=prev_tail,
            chapter_brief=ch_outline.get("chapter_brief"),
            active_characters=active_chars,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Reviewer.review 异常: %s", exc)
        errors.append({"agent": "Reviewer", "message": str(exc)})
        result = CritiqueResult(
            chapter_number=chapter_number,
            raw_response=f"Reviewer error: {exc}",
        )

    decisions.append(
        _make_decision(
            step="review_chapter",
            decision=(
                "标记需修订(仅报告)" if result.need_rewrite else "审稿通过"
            ),
            reason=(
                f"issues={len(result.issues)}, "
                f"overuse={len(result.style_overuse_hits)}, "
                f"consistency_flags={len(result.consistency_flags)}"
            ),
            data={
                "high_severity_count": result.high_severity_count,
                "medium_severity_count": result.medium_severity_count,
                "overuse_hits": result.style_overuse_hits[:10],
            },
        )
    )

    # Persist to the same state slot as the old trio so state_writeback /
    # _build_chapter_record keep working without schema changes. The shape is
    # dict-of-dict-compatible (no scores field, but rule_passed stays True).
    quality_payload: dict[str, Any] = {
        "chapter_number": chapter_number,
        "need_rewrite": result.need_rewrite,
        "strengths": list(result.strengths),
        "issues": [i.model_dump() for i in result.issues],
        "specific_revisions": [r.model_dump() for r in result.specific_revisions],
        "overall_assessment": result.overall_assessment,
        "style_overuse_hits": result.style_overuse_hits,
        "consistency_flags": [f.model_dump() for f in result.consistency_flags],
        # Back-compat keys expected by _build_chapter_record (always empty/trivial now):
        "rule_check": {"passed": True},
        "scores": {},
        "retention_scores": {},
        "suggestions": [r.suggestion for r in result.specific_revisions if r.suggestion],
    }

    return {
        "current_chapter_quality": quality_payload,
        "decisions": decisions,
        "errors": errors,
        "completed_nodes": ["reviewer"],
        # Clear rewrite prompt slot so stale feedback doesn't leak into next chapter.
        "current_chapter_rewrite_prompt": "",
    }
