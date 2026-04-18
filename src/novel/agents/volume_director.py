"""VolumeDirector — 卷级导演 Agent（Phase 2-α，架构重构 2026-04）

职责：
    1. **进卷规划** (``propose_volume_outline``) — 进入新卷时生成"本卷 N 章 +
       伏笔规划 + chapter_type 分布"，返回 ``VolumeOutlineProposal``，需作者
       accept() 后才落到 Volume 模型。
    2. **出卷结算** (``settle_volume``) — 卷末汇总应兑现/未兑现伏笔、章节统计、
       留下卷钩子，返回 ``VolumeSettlementReport``。
    3. **卷划分规划** (``plan_volume_breakdown``) — 根据 ``target_length_class``
       + ``genre`` 推荐卷数/每卷章数。从 ``NovelDirector.analyze_input`` 剥离。

设计约束：
    * **SYNC only**（与 LLMClient 一致）。
    * 不替换 ``src.novel.services.volume_settlement.VolumeSettlement`` — 出卷
      结算 **消费** 该服务，不重写底层计算。
    * ``novel_director.NovelDirector.generate_volume_outline`` 保留为 legacy
      shim（现有测试/pipeline 直接依赖），本模块的 ``propose_volume_outline``
      是其"返回结构化 proposal"的升级版本。
    * ``dynamic_outline.py`` 本质是章节级修订，**不是卷级别**逻辑，因此本档
      不吸收其内容（保留原文件为 shim）。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.novel.models.novel import (
    BASE_CHAPTER_WORDS,
    CHAPTER_TYPE_WORD_MULTIPLIER,
    ChapterOutline,
    Novel,
    Volume,
)
from src.novel.utils.json_extract import extract_json_obj

if TYPE_CHECKING:  # pragma: no cover
    from src.novel.services.ledger_store import LedgerStore

log = logging.getLogger("novel.agents.volume_director")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

MAX_RETRIES: int = 3

# 题材 → 推荐每卷章数 (used by plan_volume_breakdown)
_GENRE_CHAPTERS_PER_VOLUME: dict[str, int] = {
    "玄幻": 35,
    "修仙": 40,
    "都市": 30,
    "系统流": 30,
    "宫斗": 25,
    "群像": 25,
    "悬疑": 20,
    "权谋": 30,
    "武侠": 25,
    "仙侠": 30,
    "言情": 20,
    "科幻": 20,
    "轻小说": 20,
}

# target_length_class → (min_chapters_total, typical_chapters_per_volume)
_LENGTH_CLASS_HINTS: dict[str, tuple[int, int]] = {
    "short": (10, 10),       # 短篇：单卷 ~10 章
    "novel": (40, 25),       # 传统长篇：40+ 章，每卷 25 章
    "webnovel": (300, 40),   # 网文：300+ 章，每卷 40 章
    "epic": (500, 50),       # 长卷：500+ 章，每卷 50 章
}

_DEFAULT_CHAPTER_TYPE_DIST_PATTERN: dict[str, float] = {
    "setup": 0.15,
    "buildup": 0.55,
    "climax": 0.15,
    "resolution": 0.10,
    "interlude": 0.05,
}


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class VolumeOutlineProposal:
    """进卷规划 proposal（未 accept 前不落盘）。

    Attributes:
        volume_number: 卷号。
        title: 卷名（继承自 VolumeOutline 或新生成）。
        volume_goal: 本卷核心目标（一句话）。
        chapter_numbers: 本卷章节号列表（如 [31, 32, …, 60]）。
        chapter_outlines: 本卷详细章节大纲 list[dict]（ChapterOutline 格式）。
        chapter_type_dist: chapter_type 配额 ``{'setup':2,'buildup':…}``。
        foreshadowing_plan: 本卷伏笔规划：
            ``{"to_plant": [{"description": "…", "planted_chapter": N,
            "target_chapter": M}], "to_collect_from_previous": […]}``.
        raw_llm_data: 原始 LLM JSON（调试/审计用）。
    """

    volume_number: int
    title: str
    volume_goal: str
    chapter_numbers: list[int]
    chapter_outlines: list[dict]
    chapter_type_dist: dict[str, int] = field(default_factory=dict)
    foreshadowing_plan: dict[str, list[dict]] = field(default_factory=dict)
    raw_llm_data: dict[str, Any] | None = None

    def accept(self, volume: Volume) -> Volume:
        """将 proposal 吸收到一个 ``Volume`` 实例（in-place mutation）。

        Args:
            volume: 目标 Volume（通常为 pipeline 已创建的空/半空卷）。

        Returns:
            同一个 Volume 实例（链式调用方便）。
        """
        if volume.volume_number != self.volume_number:
            raise ValueError(
                f"Volume number mismatch: proposal={self.volume_number}, "
                f"volume={volume.volume_number}"
            )
        volume.volume_goal = self.volume_goal or volume.volume_goal
        volume.volume_outline = list(self.chapter_numbers)
        # 保持 Volume.chapters 与 volume_outline 同步（向后兼容）
        if not volume.chapters:
            volume.chapters = list(self.chapter_numbers)
        volume.chapter_type_dist = dict(self.chapter_type_dist)
        if not volume.title and self.title:
            volume.title = self.title
        if volume.status == "planning":
            volume.status = "writing"
        return volume

    def to_dict(self) -> dict[str, Any]:
        """序列化到 plain dict（pipeline / changelog 持久化用）。"""
        return {
            "volume_number": self.volume_number,
            "title": self.title,
            "volume_goal": self.volume_goal,
            "chapter_numbers": list(self.chapter_numbers),
            "chapter_outlines": list(self.chapter_outlines),
            "chapter_type_dist": dict(self.chapter_type_dist),
            "foreshadowing_plan": dict(self.foreshadowing_plan),
        }


@dataclass
class VolumeSettlementReport:
    """出卷结算报告。

    Attributes:
        volume_number: 卷号。
        chapter_count: 本卷实际章节数。
        fulfilled_foreshadowings: 已兑现伏笔列表（dict）。
        unfulfilled_foreshadowings: 未兑现伏笔列表（应兑现但没兑现的）。
        foreshadowing_recovery_rate: 回收率 (0.0 ~ 1.0)。
        pending_debts: 仍未了结的债务（从 LedgerStore 读）。
        next_volume_hook: 留给下一卷的钩子（文字描述）。
        notes: 其它警告/观察（字符串列表）。
    """

    volume_number: int
    chapter_count: int
    fulfilled_foreshadowings: list[dict] = field(default_factory=list)
    unfulfilled_foreshadowings: list[dict] = field(default_factory=list)
    foreshadowing_recovery_rate: float = 0.0
    pending_debts: list[dict] = field(default_factory=list)
    next_volume_hook: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化（写入 Volume.settlement 字段）。"""
        return {
            "volume_number": self.volume_number,
            "chapter_count": self.chapter_count,
            "fulfilled_foreshadowings": list(self.fulfilled_foreshadowings),
            "unfulfilled_foreshadowings": list(self.unfulfilled_foreshadowings),
            "foreshadowing_recovery_rate": self.foreshadowing_recovery_rate,
            "pending_debts": list(self.pending_debts),
            "next_volume_hook": self.next_volume_hook,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# VolumeDirector
# ---------------------------------------------------------------------------


class VolumeDirector:
    """卷级导演：进卷规划 + 出卷结算 + 卷划分规划。

    与 ``NovelDirector`` 的关系：
        * NovelDirector 负责"全书三层大纲"初始化（一次性）；
        * VolumeDirector 负责"每卷进/出"的动态规划（每卷一次）。

    Args:
        llm: LLM client（实现 ``chat(messages, temperature, json_mode,
            max_tokens)``）。
        workspace: 项目 workspace 路径（仅用于定位文件/日志上下文）。
        config: 可选 NovelConfig；当前实现未使用但保留以兼容未来扩展。
    """

    def __init__(
        self,
        llm: Any,
        workspace: str | Path | None = None,
        config: Any | None = None,
    ) -> None:
        self.llm = llm
        self.workspace = Path(workspace) if workspace is not None else None
        self.config = config

    # ==================================================================
    # 1. 进卷规划
    # ==================================================================

    def propose_volume_outline(
        self,
        novel: Novel | dict,
        volume_number: int,
        previous_settlement: dict | None = None,
    ) -> VolumeOutlineProposal:
        """生成本卷章节列表草案 + chapter_type 分布 + 伏笔规划。

        本方法 **只生成 proposal**，不 mutate ``novel``。作者/pipeline 决定
        accept 后才落到 Volume。

        Args:
            novel: Novel 模型或其 dict 表示。
            volume_number: 要规划的卷号（从 1 开始）。
            previous_settlement: 上一卷的 ``VolumeSettlementReport.to_dict()``；
                为 ``None`` 时表示首卷或无上卷信息。

        Returns:
            ``VolumeOutlineProposal``。

        Raises:
            ValueError: volume_number 在 outline.volumes 中找不到，且也无法
                从 outline 推断。
            RuntimeError: LLM 连续 MAX_RETRIES 次返回无效 JSON。
        """
        novel_data = (
            novel.model_dump() if isinstance(novel, Novel) else dict(novel)
        )
        outline = novel_data.get("outline", {}) or {}
        volumes = outline.get("volumes", []) or []

        target_volume = next(
            (v for v in volumes if v.get("volume_number") == volume_number),
            None,
        )
        if target_volume is None:
            raise ValueError(
                f"卷 {volume_number} 在 outline.volumes 中不存在，无法规划"
            )

        # 本卷章节范围
        vol_chapters = target_volume.get("chapters") or []
        if vol_chapters:
            chapter_numbers = sorted(int(c) for c in vol_chapters)
        else:
            # 按 per-volume 推断（从题材 hint）
            per_vol = _GENRE_CHAPTERS_PER_VOLUME.get(novel_data.get("genre", ""), 30)
            # 用前面卷最大章号推下一段
            existing_max = 0
            for ch in outline.get("chapters", []) or []:
                if isinstance(ch, dict):
                    existing_max = max(existing_max, int(ch.get("chapter_number", 0) or 0))
            start = existing_max + 1
            chapter_numbers = list(range(start, start + per_vol))

        start_ch, end_ch = chapter_numbers[0], chapter_numbers[-1]
        chapters_count = len(chapter_numbers)

        # ---- 构造 prompt ----
        prompt = self._build_propose_prompt(
            novel_data=novel_data,
            target_volume=target_volume,
            chapter_numbers=chapter_numbers,
            previous_settlement=previous_settlement,
        )

        # ---- 调 LLM + 重试 ----
        result: dict | None = None
        last_error = ""
        for attempt in range(MAX_RETRIES):
            try:
                response = self.llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是小说卷级规划总导演，熟悉网文节奏曲线、伏笔回收、"
                                "章节类型分布。请严格按 JSON 格式返回本卷规划。"
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                    json_mode=True,
                    max_tokens=8192,
                )
                result = extract_json_obj(response.content)
                if result is not None:
                    break
                last_error = f"LLM 返回无法解析为 JSON: {response.content[:200]}"
            except Exception as exc:
                last_error = f"LLM 调用失败: {exc}"
                log.warning(
                    "卷%d propose 第%d次重试: %s",
                    volume_number, attempt + 1, last_error,
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)

        if result is None:
            # 兜底：LLM 完全无法产出，用纯规则生成 proposal
            log.error(
                "卷%d LLM 规划完全失败（%s），回退到规则兜底",
                volume_number, last_error,
            )
            return self._fallback_proposal(
                target_volume=target_volume,
                chapter_numbers=chapter_numbers,
                volume_number=volume_number,
            )

        return self._parse_propose_result(
            result=result,
            target_volume=target_volume,
            chapter_numbers=chapter_numbers,
            volume_number=volume_number,
        )

    # ------------------------------------------------------------------
    # Propose helpers
    # ------------------------------------------------------------------

    def _build_propose_prompt(
        self,
        novel_data: dict,
        target_volume: dict,
        chapter_numbers: list[int],
        previous_settlement: dict | None,
    ) -> str:
        genre = novel_data.get("genre", "")
        theme = novel_data.get("theme", "")
        start_ch = chapter_numbers[0]
        end_ch = chapter_numbers[-1]
        n = len(chapter_numbers)

        # 默认 chapter_type 配额推荐
        recommended_dist = self._recommend_chapter_type_dist(n)

        previous_block: str
        if previous_settlement:
            unf = previous_settlement.get("unfulfilled_foreshadowings") or []
            debts = previous_settlement.get("pending_debts") or []
            hook = previous_settlement.get("next_volume_hook", "")
            lines = ["【上一卷结算】"]
            if hook:
                lines.append(f"- 下卷钩子：{hook}")
            if unf:
                lines.append(f"- 未兑现伏笔（{len(unf)}）:")
                for f in unf[:8]:
                    desc = (
                        f.get("description", "") if isinstance(f, dict) else str(f)
                    )
                    lines.append(f"  · {desc}")
            if debts:
                lines.append(f"- 未了结债务（{len(debts)}）:")
                for d in debts[:5]:
                    desc = (
                        d.get("description", "") if isinstance(d, dict) else str(d)
                    )
                    lines.append(f"  · {desc}")
            previous_block = "\n".join(lines)
        else:
            previous_block = "【上一卷结算】无（首卷或无上卷信息）"

        # 角色信息
        chars_info = ""
        chars = novel_data.get("characters", []) or []
        if chars:
            names = []
            for c in chars[:6]:
                if isinstance(c, dict) and c.get("name"):
                    names.append(
                        f"{c.get('name')}"
                        + (f"({c.get('role')})" if c.get('role') else "")
                    )
            if names:
                chars_info = f"主要角色：{'、'.join(names)}"

        return f"""请为小说的第{target_volume.get('volume_number')}卷生成完整的卷级规划。

题材：{genre}
主题：{theme}
{chars_info}

【本卷基本信息】
卷号：第{target_volume.get('volume_number')}卷
卷名：{target_volume.get('title', '')}
核心矛盾：{target_volume.get('core_conflict', '')}
解决方向：{target_volume.get('resolution', '')}
章节范围：第{start_ch} - 第{end_ch}章（共 {n} 章）

{previous_block}

请严格按以下 JSON 格式返回：
{{
  "volume_goal": "本卷核心目标（一句话，例：主角开启修炼之路并结识队友）",
  "chapter_type_dist": {{
    "setup": {recommended_dist['setup']},
    "buildup": {recommended_dist['buildup']},
    "climax": {recommended_dist['climax']},
    "resolution": {recommended_dist['resolution']},
    "interlude": {recommended_dist['interlude']}
  }},
  "foreshadowing_plan": {{
    "to_plant": [
      {{
        "description": "伏笔描述",
        "planted_chapter": {start_ch},
        "target_chapter": {end_ch}
      }}
    ],
    "to_collect_from_previous": [
      {{"description": "承接上卷伏笔的描述", "target_chapter": {start_ch}}}
    ]
  }},
  "chapters": [
    {{
      "chapter_number": {start_ch},
      "title": "章节标题",
      "goal": "本章目标",
      "key_events": ["事件1", "事件2"],
      "involved_characters": [],
      "plot_threads": [],
      "estimated_words": 2500,
      "chapter_type": "setup",
      "mood": "蓄力",
      "storyline_progress": "本章如何推进主线",
      "chapter_summary": "本章内容2-3句话摘要",
      "chapter_brief": {{
        "main_conflict": "本章主冲突",
        "payoff": "本章爽点",
        "character_arc_step": "主角变化",
        "foreshadowing_plant": [],
        "foreshadowing_collect": [],
        "end_hook_type": "悬疑"
      }}
    }}
  ]
}}

要求：
1. chapters 数组必须覆盖 [{start_ch}, {end_ch}] 共 {n} 章，章节号连续递增。
2. chapter_type_dist 各项数值之和应等于 {n}。
3. chapter_type 可选：setup / buildup / climax / resolution / interlude。
4. 开头 1-2 章可用 setup，中段主要 buildup，倒数 2-3 章进入 climax，末 1 章 resolution。
5. to_plant 为本卷新埋伏笔，to_collect_from_previous 用于承接上卷未兑现伏笔。
6. mood 可选：蓄力、小爽、大爽、过渡、虐心、反转、日常。
"""

    def _recommend_chapter_type_dist(self, chapter_count: int) -> dict[str, int]:
        """按默认比例把 chapter_count 分配到 5 类 chapter_type。"""
        if chapter_count <= 0:
            return {k: 0 for k in _DEFAULT_CHAPTER_TYPE_DIST_PATTERN}
        raw = {
            k: max(0, int(round(chapter_count * ratio)))
            for k, ratio in _DEFAULT_CHAPTER_TYPE_DIST_PATTERN.items()
        }
        # 调整总和等于 chapter_count
        diff = chapter_count - sum(raw.values())
        if diff != 0:
            # 把差额加到 buildup（主体类型）
            raw["buildup"] = max(0, raw.get("buildup", 0) + diff)
        return raw

    def _parse_propose_result(
        self,
        result: dict,
        target_volume: dict,
        chapter_numbers: list[int],
        volume_number: int,
    ) -> VolumeOutlineProposal:
        """将 LLM JSON 解析为 ``VolumeOutlineProposal``，对字段做兜底。"""
        start_ch, end_ch = chapter_numbers[0], chapter_numbers[-1]
        n = len(chapter_numbers)

        volume_goal = str(result.get("volume_goal") or "").strip()
        if not volume_goal:
            volume_goal = target_volume.get("core_conflict", "") or (
                f"第{volume_number}卷核心任务"
            )

        # chapter_type_dist —— 兜底 + 校正到 n
        raw_dist = result.get("chapter_type_dist") or {}
        if not isinstance(raw_dist, dict):
            raw_dist = {}
        dist: dict[str, int] = {}
        for k in CHAPTER_TYPE_WORD_MULTIPLIER.keys():
            try:
                dist[k] = max(0, int(raw_dist.get(k, 0) or 0))
            except (TypeError, ValueError):
                dist[k] = 0
        total = sum(dist.values())
        if total != n:
            # 回退到推荐分布
            dist = self._recommend_chapter_type_dist(n)

        # foreshadowing_plan —— 保留 to_plant / to_collect_from_previous
        raw_fp = result.get("foreshadowing_plan") or {}
        if not isinstance(raw_fp, dict):
            raw_fp = {}
        to_plant_raw = raw_fp.get("to_plant") or []
        to_collect_raw = raw_fp.get("to_collect_from_previous") or []
        foreshadowing_plan = {
            "to_plant": [f for f in to_plant_raw if isinstance(f, dict)],
            "to_collect_from_previous": [
                f for f in to_collect_raw if isinstance(f, dict)
            ],
        }

        # chapters
        raw_chapters = result.get("chapters") or []
        if not isinstance(raw_chapters, list):
            raw_chapters = []
        parsed_chapters: list[dict] = []
        seen: set[int] = set()
        for ch_data in raw_chapters:
            if not isinstance(ch_data, dict):
                continue
            # 兜底字段
            if "chapter_brief" not in ch_data or not isinstance(
                ch_data.get("chapter_brief"), dict
            ):
                ch_data["chapter_brief"] = {}
            # chapter_type 兜底
            ct = ch_data.get("chapter_type")
            if ct not in CHAPTER_TYPE_WORD_MULTIPLIER:
                ch_data["chapter_type"] = "buildup"
            try:
                co = ChapterOutline(**ch_data)
                if co.chapter_number in seen:
                    continue
                parsed_chapters.append(co.model_dump())
                seen.add(co.chapter_number)
            except Exception:
                log.warning("卷%d 跳过无效 chapter 数据", volume_number)

        # 补齐缺失章节
        for ch_num in chapter_numbers:
            if ch_num in seen:
                continue
            parsed_chapters.append(
                ChapterOutline(
                    chapter_number=ch_num,
                    title=f"第{ch_num}章",
                    goal="待规划",
                    key_events=["待规划"],
                    estimated_words=BASE_CHAPTER_WORDS,
                    chapter_type="buildup",
                    mood="蓄力",
                ).model_dump()
            )
            seen.add(ch_num)

        parsed_chapters.sort(key=lambda c: c["chapter_number"])
        # 只保留本卷范围内的章节
        parsed_chapters = [
            c for c in parsed_chapters
            if start_ch <= c["chapter_number"] <= end_ch
        ]

        return VolumeOutlineProposal(
            volume_number=volume_number,
            title=target_volume.get("title", f"第{volume_number}卷"),
            volume_goal=volume_goal,
            chapter_numbers=chapter_numbers,
            chapter_outlines=parsed_chapters,
            chapter_type_dist=dist,
            foreshadowing_plan=foreshadowing_plan,
            raw_llm_data=result,
        )

    def _fallback_proposal(
        self,
        target_volume: dict,
        chapter_numbers: list[int],
        volume_number: int,
    ) -> VolumeOutlineProposal:
        """LLM 完全失败时的纯规则兜底 proposal。"""
        n = len(chapter_numbers)
        dist = self._recommend_chapter_type_dist(n)

        # 为每章分配 chapter_type（按分布顺序：setup → buildup → climax → resolution → interlude）
        chapter_types: list[str] = []
        for ctype in ("setup", "buildup", "climax", "resolution", "interlude"):
            chapter_types.extend([ctype] * dist.get(ctype, 0))
        # 兜底长度（理论上应等于 n）
        while len(chapter_types) < n:
            chapter_types.append("buildup")
        chapter_types = chapter_types[:n]

        parsed: list[dict] = []
        for idx, ch_num in enumerate(chapter_numbers):
            ctype = chapter_types[idx]
            parsed.append(
                ChapterOutline(
                    chapter_number=ch_num,
                    title=f"第{ch_num}章",
                    goal="待规划",
                    key_events=["待规划"],
                    estimated_words=BASE_CHAPTER_WORDS,
                    chapter_type=ctype,  # type: ignore[arg-type]
                    mood="蓄力",
                ).model_dump()
            )

        return VolumeOutlineProposal(
            volume_number=volume_number,
            title=target_volume.get("title", f"第{volume_number}卷"),
            volume_goal=target_volume.get("core_conflict", "")
            or f"第{volume_number}卷核心任务",
            chapter_numbers=list(chapter_numbers),
            chapter_outlines=parsed,
            chapter_type_dist=dist,
            foreshadowing_plan={"to_plant": [], "to_collect_from_previous": []},
            raw_llm_data=None,
        )

    # ==================================================================
    # 2. 出卷结算
    # ==================================================================

    def settle_volume(
        self,
        novel: Novel | dict,
        volume_number: int,
        ledger: "LedgerStore | None" = None,
    ) -> VolumeSettlementReport:
        """生成卷结算报告。

        优先通过 ``ledger.snapshot_for_chapter`` + ``list_foreshadowings``
        汇总 ledger 事实；``ledger=None`` 时降级到只看 ``novel.chapters`` /
        ``novel.outline`` 的轻量统计。

        Args:
            novel: Novel 模型或其 dict。
            volume_number: 要结算的卷号。
            ledger: 可选 ``LedgerStore`` 实例。

        Returns:
            ``VolumeSettlementReport``。
        """
        novel_data = (
            novel.model_dump() if isinstance(novel, Novel) else dict(novel)
        )
        outline = novel_data.get("outline", {}) or {}
        volumes = outline.get("volumes", []) or []
        target_volume = next(
            (v for v in volumes if v.get("volume_number") == volume_number),
            None,
        )
        if target_volume is None:
            # 降级：构造空报告
            return VolumeSettlementReport(
                volume_number=volume_number,
                chapter_count=0,
                notes=[f"卷 {volume_number} 在 outline 中不存在"],
            )

        vol_chapters = [int(c) for c in (target_volume.get("chapters") or [])]
        if vol_chapters:
            start_ch, end_ch = min(vol_chapters), max(vol_chapters)
        else:
            start_ch = end_ch = 0

        # 统计本卷实际已写章节数
        chapters_all = novel_data.get("chapters", []) or []
        written = [
            ch for ch in chapters_all
            if isinstance(ch, dict)
            and start_ch <= int(ch.get("chapter_number", 0) or 0) <= end_ch
        ]
        chapter_count = len(written)

        fulfilled: list[dict] = []
        unfulfilled: list[dict] = []
        pending_debts: list[dict] = []
        notes: list[str] = []

        if ledger is not None:
            # Ledger 模式：从 foreshadowing 图 + obligation tracker 取
            try:
                snapshot = ledger.snapshot_for_chapter(end_ch or 1)
                pending_debts = list(snapshot.get("pending_debts") or [])
            except Exception as exc:
                notes.append(f"ledger.snapshot_for_chapter 失败: {exc}")
                pending_debts = []

            try:
                all_fs = ledger.list_foreshadowings(
                    chapter_range=(start_ch or 1, end_ch or 10**9),
                ) if start_ch and end_ch else ledger.list_foreshadowings()
            except Exception as exc:
                notes.append(f"ledger.list_foreshadowings 失败: {exc}")
                all_fs = []

            for fs in all_fs:
                if not isinstance(fs, dict):
                    continue
                status = (fs.get("status") or "").lower()
                target_ch = int(fs.get("target_chapter", 0) or 0)
                if status == "collected":
                    fulfilled.append(fs)
                elif target_ch and target_ch <= end_ch:
                    # 应兑现但未兑现
                    unfulfilled.append(fs)
                # 其余的是长尾（target > end_ch），不算 unfulfilled
        else:
            # 降级：扫描章节 chapter_brief 里的伏笔标记
            for ch in written:
                brief = ch.get("chapter_brief") or {}
                if not isinstance(brief, dict):
                    continue
                for item in brief.get("foreshadowing_collect", []) or []:
                    desc = item if isinstance(item, str) else item.get(
                        "description", ""
                    )
                    fulfilled.append({"description": desc, "source": "chapter_brief"})

            notes.append("ledger=None, 降级模式：仅统计 chapter_brief 中的回收伏笔")

        total_fs = len(fulfilled) + len(unfulfilled)
        recovery_rate = (
            round(len(fulfilled) / total_fs, 3) if total_fs > 0 else 0.0
        )

        # 生成下卷钩子：首选未兑现伏笔最前一个，其次本卷 resolution 字段
        next_hook = ""
        if unfulfilled:
            first = unfulfilled[0]
            if isinstance(first, dict):
                next_hook = (
                    first.get("description", "") or first.get("content", "") or ""
                )
        if not next_hook:
            next_hook = target_volume.get("resolution", "") or ""

        return VolumeSettlementReport(
            volume_number=volume_number,
            chapter_count=chapter_count,
            fulfilled_foreshadowings=fulfilled,
            unfulfilled_foreshadowings=unfulfilled,
            foreshadowing_recovery_rate=recovery_rate,
            pending_debts=pending_debts,
            next_volume_hook=next_hook,
            notes=notes,
        )

    # ==================================================================
    # 3. 卷划分规划
    # ==================================================================

    def plan_volume_breakdown(
        self,
        novel: Novel | dict,
        target_length_class: str = "novel",
    ) -> list[dict]:
        """根据 ``target_length_class`` + ``genre`` 推荐卷数 & 每卷章数。

        纯规则计算，不调 LLM。

        Args:
            novel: Novel 模型或其 dict（只读 genre / target_words）。
            target_length_class: ``short`` / ``novel`` / ``webnovel`` /
                ``epic``，未知值回退到 ``novel``。

        Returns:
            每卷规划 dict 列表：
            ``[{"volume_number": 1, "start_chapter": 1, "end_chapter": 25,
            "chapters_count": 25}, ...]``。
        """
        novel_data = (
            novel.model_dump() if isinstance(novel, Novel) else dict(novel)
        )
        genre = novel_data.get("genre", "")
        target_words = int(novel_data.get("target_words") or 0)

        min_total, per_vol = _LENGTH_CLASS_HINTS.get(
            target_length_class, _LENGTH_CLASS_HINTS["novel"]
        )

        # 每卷章数：题材优先，其次 length_class hint
        per_vol = _GENRE_CHAPTERS_PER_VOLUME.get(genre, per_vol)

        # 总章数：target_words / BASE_CHAPTER_WORDS，但至少 min_total
        if target_words > 0:
            by_words = max(1, target_words // BASE_CHAPTER_WORDS)
            total_chapters = max(by_words, min_total)
        else:
            total_chapters = min_total

        # 划分
        volume_count = max(1, (total_chapters + per_vol - 1) // per_vol)
        breakdown: list[dict] = []
        cursor = 1
        for i in range(volume_count):
            end = min(cursor + per_vol - 1, total_chapters)
            breakdown.append(
                {
                    "volume_number": i + 1,
                    "start_chapter": cursor,
                    "end_chapter": end,
                    "chapters_count": end - cursor + 1,
                }
            )
            cursor = end + 1
            if cursor > total_chapters:
                break

        return breakdown


__all__ = [
    "VolumeDirector",
    "VolumeOutlineProposal",
    "VolumeSettlementReport",
]
