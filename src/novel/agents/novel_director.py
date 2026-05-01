"""NovelDirector - 卷级大纲 + 里程碑生成 Agent

Phase 3-B3 之后只剩两块职责：
1. ``generate_volume_outline`` —— 超长篇按需生成指定卷的章节大纲
2. ``generate_volume_milestones`` —— 为一卷自动生成叙事里程碑
3. ``plan_next_chapter`` —— 根据现有 outline + state 规划下一章

立项 / 三层大纲 / 输入分析 等职责已迁到 ``ProjectArchitect``。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from src.novel.agents.state import Decision, NovelState
from src.novel.models.novel import ChapterOutline, Outline
from src.novel.utils.json_extract import extract_json_obj

log = logging.getLogger("novel")

# pipeline 侧按此分卷的兜底常量；优先级低于 outline_templates 的
# default_chapters_per_volume 和 volume_director 的 _GENRE_CHAPTERS_PER_VOLUME。
_CHAPTERS_PER_VOLUME = 30


def _resolve_chapters_per_volume(novel_data: dict, outline: dict) -> int:
    """按优先级推导每卷章数：outline.default_chapters_per_volume → genre 表 → 30。

    用于 fallback 路径（target_volume.chapters 为空时），让 ordinal 兜底
    与项目实际配置对齐，避免 30 硬编码与修仙(40)/言情(20) 等体裁冲突。
    """
    # 1) outline 自带（来自 outline_templates 的 default_chapters_per_volume）
    val = outline.get("default_chapters_per_volume")
    if isinstance(val, int) and val > 0:
        return val
    # 2) 体裁推荐表（与 volume_director 同源）
    try:
        from src.novel.agents.volume_director import _GENRE_CHAPTERS_PER_VOLUME
        genre = novel_data.get("genre", "")
        if genre in _GENRE_CHAPTERS_PER_VOLUME:
            return _GENRE_CHAPTERS_PER_VOLUME[genre]
    except Exception:  # pragma: no cover - defensive
        pass
    # 3) 全局兜底
    return _CHAPTERS_PER_VOLUME


def _make_decision(
    step: str,
    decision: str,
    reason: str,
    data: dict[str, Any] | None = None,
) -> Decision:
    """创建 NovelDirector 的决策记录。"""
    return Decision(
        agent="NovelDirector",
        step=step,
        decision=decision,
        reason=reason,
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# NovelDirector
# ---------------------------------------------------------------------------


class NovelDirector:
    """卷级大纲 + 里程碑生成 Agent。"""

    MAX_OUTLINE_RETRIES = 3
    # D3：单次 LLM call 最多生成的章数。30 章历史实测正常 (DeepSeek 8192
    # max_tokens 边缘内)；35+ 章 JSON 会被截断。超过此阈值的卷分批生成。
    BATCH_MAX_CHAPTERS = 30

    def __init__(self, llm_client: Any):
        """
        Args:
            llm_client: 实现 ``chat(messages, temperature, json_mode)`` 的 LLMClient。
        """
        self.llm = llm_client

    # ------------------------------------------------------------------
    # 规划下一章
    # ------------------------------------------------------------------

    def plan_next_chapter(self, state: NovelState) -> dict[str, Any]:
        """根据当前状态确定下一个要写的章节。

        Returns:
            dict 包含 current_chapter, current_chapter_outline 等字段。
        """
        current = state.get("current_chapter", 0)
        outline_data = state.get("outline")
        chapters_done = state.get("chapters") or []

        if not outline_data:
            return {"errors": [{"agent": "NovelDirector", "message": "大纲不存在，无法规划下一章"}]}

        # 找到下一个未完成的章节
        completed_numbers = {ch.get("chapter_number", 0) for ch in chapters_done}
        outline = Outline(**outline_data)
        next_chapter = None

        for ch_outline in sorted(outline.chapters, key=lambda c: c.chapter_number):
            if ch_outline.chapter_number not in completed_numbers:
                next_chapter = ch_outline
                break

        if next_chapter is None:
            # 所有章节已完成
            return {
                "should_continue": False,
                "decisions": [
                    _make_decision(
                        step="plan_next_chapter",
                        decision="所有章节已完成",
                        reason=f"已完成 {len(completed_numbers)} 章",
                    )
                ],
            }

        return {
            "current_chapter": next_chapter.chapter_number,
            "current_chapter_outline": next_chapter.model_dump(),
            "should_continue": True,
            "decisions": [
                _make_decision(
                    step="plan_next_chapter",
                    decision=f"下一章: 第 {next_chapter.chapter_number} 章 - {next_chapter.title}",
                    reason=f"已完成 {len(completed_numbers)} 章，按序推进",
                )
            ],
        }

    # ------------------------------------------------------------------
    # 4. 分卷大纲生成（超长篇支持）
    # ------------------------------------------------------------------

    def generate_volume_outline(
        self,
        novel_data: dict,
        volume_number: int,
        previous_summary: str = "",
    ) -> list[dict]:
        """为指定卷生成章节大纲（基于已有内容和整体框架）。

        当目标字数超过 75000 字（约30章）时，创建项目只生成第1卷的详细
        章节大纲。后续卷的章节大纲在需要时通过此方法动态生成，避免一次性
        生成过多章节导致 token 爆炸。

        Args:
            novel_data: Novel dict（包含 outline.acts, outline.volumes 等整体框架）
            volume_number: 要生成大纲的卷号（从1开始）
            previous_summary: 前面各卷的内容摘要

        Returns:
            list[dict]: 章节大纲列表（ChapterOutline 格式的 dict）
        """
        outline = novel_data.get("outline", {})
        volumes = outline.get("volumes", [])
        main_storyline = outline.get("main_storyline", {})

        # 找到目标卷的信息
        target_volume = None
        for vol in volumes:
            if vol.get("volume_number") == volume_number:
                target_volume = vol
                break

        if target_volume is None:
            log.warning("卷 %d 在整体框架中不存在，使用默认信息", volume_number)
            target_volume = {
                "volume_number": volume_number,
                "title": f"第{volume_number}卷",
                "core_conflict": "待规划",
                "resolution": "待规划",
                "chapters": [],
            }

        # 计算本卷的章节范围
        vol_chapters = target_volume.get("chapters", [])
        if vol_chapters:
            start_ch = min(vol_chapters)
            end_ch = max(vol_chapters)
            chapters_count = len(vol_chapters)
        else:
            # D2 修复：fallback 不再从 outline.chapters max+1 算起点（会被
            # 幽灵章节污染，导致 ch201-235 类事故）。优先级：
            #   1. outline.volumes 中"严格紧邻"上一卷 (volume_number-1) 的
            #      chapters max+1 → 本卷起点；不允许跨过中间空卷取更早的卷
            #   2. (volume_number-1) × chapters_count + 1 → 按卷号序数算
            # chapters_count 也按 outline/genre 配置推，不再硬编码 30。
            chapters_count = _resolve_chapters_per_volume(novel_data, outline)
            prev_vol_max = 0
            source = "卷号序数"
            for vol in volumes:
                if not isinstance(vol, dict):
                    continue
                if vol.get("volume_number") != volume_number - 1:
                    continue
                vc = vol.get("chapters") or []
                ints = [int(c) for c in vc if isinstance(c, (int, str)) and str(c).lstrip("-").isdigit()]
                if ints:
                    prev_vol_max = max(ints)
                    source = f"上一卷 vol{volume_number - 1} max+1"
                break
            if prev_vol_max > 0:
                start_ch = prev_vol_max + 1
            else:
                start_ch = max(1, (volume_number - 1) * chapters_count + 1)
            end_ch = start_ch + chapters_count - 1
            # 防御：扫现有卷检测重叠，不静默产冲突
            for vol in volumes:
                if not isinstance(vol, dict):
                    continue
                vn = vol.get("volume_number", 0)
                if vn == volume_number:
                    continue
                other = vol.get("chapters") or []
                other_ints = {int(c) for c in other if isinstance(c, (int, str)) and str(c).lstrip("-").isdigit()}
                if other_ints and not other_ints.isdisjoint(range(start_ch, end_ch + 1)):
                    log.warning(
                        "卷%d fallback 推断范围 [%d, %d] 与卷%d 现有 chapters 重叠：%s",
                        volume_number, start_ch, end_ch, vn,
                        sorted(other_ints & set(range(start_ch, end_ch + 1)))[:5],
                    )
                    break
            log.info(
                "卷%d 章节范围 fallback 推断: 第%d-%d章 (来源: %s, 每卷章数=%d)",
                volume_number, start_ch, end_ch, source, chapters_count,
            )

        # 提取世界观和角色信息
        world_setting = novel_data.get("world_setting", {})
        characters = novel_data.get("characters", [])
        # Phase 0 架构重构：零默认体裁。项目数据必须带 genre。
        genre = novel_data.get("genre")
        if not genre:
            raise ValueError(
                "novel_data 缺少 genre 字段（Phase 0 架构重构：禁止默认回退到玄幻）"
            )
        theme = novel_data.get("theme", "")

        world_info = ""
        if world_setting:
            era = world_setting.get("era", "")
            location = world_setting.get("location", "")
            if era or location:
                world_info = f"世界观：{era}，{location}"

        char_info = ""
        if characters:
            char_names = []
            for c in characters[:5]:  # 最多取5个主要角色
                if isinstance(c, dict):
                    name = c.get("name", "")
                    role = c.get("role", "")
                    if name:
                        char_names.append(f"{name}({role})" if role else name)
            if char_names:
                char_info = f"主要角色：{'、'.join(char_names)}"

        # 构建整体框架摘要
        acts_info = ""
        for act in outline.get("acts", []):
            if isinstance(act, dict):
                acts_info += f"  - {act.get('name', '')}: {act.get('description', '')} (第{act.get('start_chapter', '?')}-{act.get('end_chapter', '?')}章)\n"

        volumes_info = ""
        for vol in volumes:
            if isinstance(vol, dict):
                vol_num = vol.get("volume_number", "?")
                vol_title = vol.get("title", "")
                vol_conflict = vol.get("core_conflict", "")
                vol_resolution = vol.get("resolution", "")
                marker = " [当前卷]" if vol_num == volume_number else ""
                volumes_info += f"  - 第{vol_num}卷「{vol_title}」: 核心矛盾={vol_conflict}, 解决方向={vol_resolution}{marker}\n"

        # 主线信息
        storyline_info = ""
        if main_storyline:
            storyline_info = f"""
主线信息：
  - 主角：{main_storyline.get('protagonist', '未知')}
  - 目标：{main_storyline.get('protagonist_goal', '未知')}
  - 核心冲突：{main_storyline.get('core_conflict', '未知')}
  - 角色弧线：{main_storyline.get('character_arc', '未知')}
  - 赌注：{main_storyline.get('stakes', '未知')}
"""

        # D3 批处理：长卷分批 LLM call，避免 8192 max_tokens JSON 截断
        # 用"近似均衡"切批避免末批畸形（H2）：31 章切 16+15 而非 30+1
        batches: list[tuple[int, int]] = []
        if chapters_count <= self.BATCH_MAX_CHAPTERS:
            batches.append((start_ch, end_ch))
        else:
            import math
            n_batches = math.ceil(chapters_count / self.BATCH_MAX_CHAPTERS)
            base, extra = divmod(chapters_count, n_batches)
            _cur = start_ch
            for i in range(n_batches):
                size = base + (1 if i < extra else 0)
                batches.append((_cur, _cur + size - 1))
                _cur += size
        is_batched = len(batches) > 1
        if is_batched:
            log.info(
                "卷%d 共%d章超过单批阈值 %d，分%d批生成: %s",
                volume_number, chapters_count, self.BATCH_MAX_CHAPTERS,
                len(batches), batches,
            )

        # 全局上下文（每批共享）
        ctx = {
            "volume_number": volume_number,
            "genre": genre,
            "theme": theme,
            "world_info": world_info,
            "char_info": char_info,
            "storyline_info": storyline_info,
            "acts_info": acts_info,
            "volumes_info": volumes_info,
            "target_volume_title": target_volume.get("title", ""),
            "target_volume_conflict": target_volume.get("core_conflict", ""),
            "target_volume_resolution": target_volume.get("resolution", ""),
            "vol_start_ch": start_ch,
            "vol_end_ch": end_ch,
            "vol_chapters_count": chapters_count,
            "previous_summary": previous_summary,
        }

        all_chapters_data: list[dict] = []
        for _b_start, _b_end in batches:
            batch_count = _b_end - _b_start + 1
            # H1：跨批衔接 — 把上一批已产出的最后 2-3 章 summary 注入下一批
            ctx_for_batch = dict(ctx)
            if all_chapters_data:
                tail = sorted(
                    all_chapters_data, key=lambda c: c.get("chapter_number", 0)
                )[-3:]
                tail_lines = []
                for ch in tail:
                    cn = ch.get("chapter_number", "?")
                    title = ch.get("title", "")
                    summary = (
                        ch.get("chapter_summary", "")
                        or ch.get("goal", "")
                    )
                    hook = (ch.get("chapter_brief") or {}).get("end_hook_type", "")
                    tail_lines.append(
                        f"  - 第{cn}章「{title}」: {summary[:80]}"
                        + (f" [钩子: {hook}]" if hook else "")
                    )
                tail_block = "\n【上一批已生成章节（衔接此处）】\n" + "\n".join(tail_lines)
                # 把 tail 拼到 previous_summary 后，让 LLM 看到分批边界
                ctx_for_batch["previous_summary"] = (
                    (ctx["previous_summary"] or "") + tail_block
                ).strip()
            prompt = self._render_volume_outline_prompt(
                ctx_for_batch, _b_start, _b_end, batch_count, is_batched
            )
            batch_chapters = self._llm_chat_for_volume_batch(
                prompt, volume_number, _b_start, _b_end
            )
            # M2：丢弃 LLM 越界返回的 chapter_number（防 batch1 LLM 错回 ch1-5 占位 batch2 真号）
            for ch in batch_chapters:
                cn = ch.get("chapter_number", 0)
                if not isinstance(cn, int) or cn < _b_start or cn > _b_end:
                    log.warning(
                        "卷%d 批次 [%d-%d] LLM 返回越界章号 %s，已丢弃",
                        volume_number, _b_start, _b_end, cn,
                    )
                    continue
                all_chapters_data.append(ch)

        # 解析章节
        chapters_data = all_chapters_data
        parsed_chapters: list[dict] = []

        for ch_data in chapters_data:
            try:
                if "chapter_brief" not in ch_data or not isinstance(ch_data.get("chapter_brief"), dict):
                    ch_data["chapter_brief"] = {}
                # Validate by constructing a ChapterOutline
                co = ChapterOutline(**ch_data)
                parsed_chapters.append(co.model_dump())
            except Exception:
                log.warning("跳过无效卷大纲 chapter 数据: %s", ch_data)

        # 兜底：填充缺失的章节
        existing_nums = {ch["chapter_number"] for ch in parsed_chapters}
        for i in range(start_ch, end_ch + 1):
            if i not in existing_nums:
                parsed_chapters.append(
                    ChapterOutline(
                        chapter_number=i,
                        title=f"第{i}章",
                        goal="待规划",
                        key_events=["待规划"],
                        estimated_words=2500,
                        mood="蓄力",
                    ).model_dump()
                )

        parsed_chapters.sort(key=lambda c: c["chapter_number"])
        log.info("卷%d大纲生成完成: %d章 (第%d-%d章)", volume_number, len(parsed_chapters), start_ch, end_ch)
        return parsed_chapters

    # ------------------------------------------------------------------
    # 4a. D3 helpers — 分批 prompt 构建 + LLM 重试封装
    # ------------------------------------------------------------------

    def _render_volume_outline_prompt(
        self,
        ctx: dict,
        batch_start: int,
        batch_end: int,
        batch_count: int,
        is_batched: bool,
    ) -> str:
        """渲染单批 prompt。当卷被分批时，prompt 强调"本批章号范围"
        且明确告知整卷范围，让 LLM 仍知道全局位置。"""
        vol_n = ctx["volume_number"]
        vol_total = ctx["vol_chapters_count"]
        vol_start = ctx["vol_start_ch"]
        vol_end = ctx["vol_end_ch"]
        prev_summary = ctx["previous_summary"]
        batch_note = ""
        if is_batched:
            batch_note = (
                f"\n【批次说明】本卷共{vol_total}章 (第{vol_start}-{vol_end}章)，"
                f"为避免单次响应被截断，按 ≤{self.BATCH_MAX_CHAPTERS} 章分批生成。"
                f"本批仅生成第{batch_start}-{batch_end}章 (共{batch_count}章)。\n"
            )
        return f"""请为小说的第{vol_n}卷生成详细的章节大纲。

题材：{ctx['genre']}
主题：{ctx['theme']}
{ctx['world_info']}
{ctx['char_info']}
{ctx['storyline_info']}

【整体故事框架】
幕结构：
{ctx['acts_info']}
卷结构：
{ctx['volumes_info']}

【当前卷信息】
卷号：第{vol_n}卷「{ctx['target_volume_title']}」
核心矛盾：{ctx['target_volume_conflict']}
解决方向：{ctx['target_volume_resolution']}
章节范围：第{vol_start}章 - 第{vol_end}章（共{vol_total}章）
{batch_note}
【前情摘要】
{prev_summary if prev_summary else '（这是第一卷，无前情）'}

请严格按以下 JSON 格式返回：
{{
  "chapters": [
    {{
      "chapter_number": {batch_start},
      "title": "章节标题",
      "goal": "本章目标",
      "key_events": ["事件1", "事件2"],
      "involved_characters": [],
      "plot_threads": [],
      "estimated_words": 2500,
      "mood": "蓄力",
      "storyline_progress": "本章如何推进主线",
      "chapter_summary": "本章内容2-3句话摘要",
      "chapter_brief": {{
        "main_conflict": "本章主冲突",
        "payoff": "本章爽点/情绪回报",
        "character_arc_step": "主角变化",
        "foreshadowing_plant": ["要埋的伏笔"],
        "foreshadowing_collect": ["要回收的伏笔"],
        "end_hook_type": "悬疑|危机|反转|情感|发现|无"
      }}
    }}
  ]
}}

要求：
1. 章节号从 {batch_start} 开始，到 {batch_end} 结束，共 {batch_count} 章
2. 承接前情，自然过渡
3. 围绕本卷核心矛盾展开
4. 每章必须推进主线
5. 情节有起伏，节奏合理
6. mood 可选：蓄力、小爽、大爽、过渡、虐心、反转、日常
"""

    def _llm_chat_for_volume_batch(
        self,
        prompt: str,
        volume_number: int,
        batch_start: int,
        batch_end: int,
    ) -> list[dict]:
        """单批 LLM 调用 + retry + JSON 解析，返回 chapter dict 列表。

        失败 MAX_OUTLINE_RETRIES 次后 raise RuntimeError；不影响其他批。
        """
        result_data: dict | None = None
        last_error = ""
        for attempt in range(self.MAX_OUTLINE_RETRIES):
            try:
                response = self.llm.chat(
                    messages=[
                        {"role": "system", "content": "你是一位资深网络小说策划编辑。请严格按照 JSON 格式返回章节大纲。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.8,
                    json_mode=True,
                    max_tokens=8192,
                )
                result_data = extract_json_obj(response.content)
                if result_data is not None:
                    break
                last_error = f"LLM 返回内容无法解析为 JSON: {response.content[:200]}"
            except Exception as exc:
                last_error = f"LLM 调用失败: {exc}"
                log.warning(
                    "卷%d 批次 [%d-%d] 第 %d 次尝试失败: %s",
                    volume_number, batch_start, batch_end, attempt + 1, last_error,
                )
                if attempt < self.MAX_OUTLINE_RETRIES - 1:
                    time.sleep(2 ** attempt)
        if result_data is None:
            raise RuntimeError(
                f"卷{volume_number} 批次 [{batch_start}-{batch_end}] 大纲生成失败，"
                f"已重试 {self.MAX_OUTLINE_RETRIES} 次。最后错误: {last_error}"
            )
        return result_data.get("chapters", []) or []

    # ------------------------------------------------------------------
    # 4b. 里程碑自动生成（Intervention A 补全）
    # ------------------------------------------------------------------

    def generate_volume_milestones(
        self,
        volume: dict,
        chapter_outlines: list[dict],
        genre: str = "",
    ) -> list[dict]:
        """为一卷自动生成叙事里程碑。

        Args:
            volume: Volume dict with volume_number, title, core_conflict, resolution.
            chapter_outlines: Chapter outlines belonging to this volume.
            genre: Novel genre for context.

        Returns:
            list[dict]: NarrativeMilestone-shaped dicts ready for storage.
        """
        vol_num = volume.get("volume_number", 1)
        vol_title = volume.get("title", f"第{vol_num}卷")
        core_conflict = volume.get("core_conflict", "")
        resolution = volume.get("resolution", "")
        start_ch = volume.get("start_chapter") or (
            min((c.get("chapter_number", 999) for c in chapter_outlines), default=1)
        )
        end_ch = volume.get("end_chapter") or (
            max((c.get("chapter_number", 0) for c in chapter_outlines), default=start_ch)
        )

        # Summarise chapter goals for context
        ch_goals = []
        for ch in sorted(chapter_outlines, key=lambda c: c.get("chapter_number", 0)):
            cn = ch.get("chapter_number", 0)
            goal = ch.get("goal", "")
            if goal and goal != "待规划":
                ch_goals.append(f"第{cn}章: {goal}")
        ch_goals_text = "\n".join(ch_goals[:15]) or "（章节目标暂无）"

        prompt = f"""请为小说的第{vol_num}卷「{vol_title}」生成 3-5 个叙事里程碑。

题材：{genre}
本卷核心矛盾：{core_conflict}
本卷解决方向：{resolution}
章节范围：第{start_ch}章 - 第{end_ch}章

【各章目标概览】
{ch_goals_text}

请严格按以下 JSON 格式返回：
{{
  "milestones": [
    {{
      "milestone_id": "vol{vol_num}_m1",
      "description": "里程碑描述（10-50字，必须是可验证的叙事事件）",
      "target_chapter_range": [{start_ch}, {end_ch}],
      "verification_type": "auto_keyword",
      "verification_criteria": ["关键词1", "关键词2"],
      "priority": "critical"
    }}
  ]
}}

要求：
1. milestone_id 格式: vol{vol_num}_m1, vol{vol_num}_m2, ...
2. 第一个里程碑 priority 必须为 critical（本卷核心事件）
3. target_chapter_range 必须在 [{start_ch}, {end_ch}] 范围内
4. 里程碑应覆盖本卷开头、中段、结尾，确保主线推进可追踪
5. verification_type 优先用 auto_keyword（免费），只有无法用关键词验证时才用 llm_review
6. verification_criteria: auto_keyword 时为关键词列表，llm_review 时为验证问题字符串
7. 里程碑描述必须是具体的叙事事件，不能是抽象目标
"""

        try:
            response = self.llm.chat(
                messages=[
                    {"role": "system", "content": "你是一位资深网络小说策划编辑。请严格按照 JSON 格式返回里程碑。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                json_mode=True,
                max_tokens=2048,
            )
            data = extract_json_obj(response.content)
            if not data:
                log.warning("里程碑生成 LLM 返回无效 JSON，使用空列表")
                return []

            raw_milestones = data.get("milestones", [])
        except Exception as exc:
            log.warning("里程碑自动生成失败: %s", exc)
            return []

        # Validate each milestone via the Pydantic model
        from src.novel.models.narrative_control import NarrativeMilestone

        valid: list[dict] = []
        for m in raw_milestones:
            try:
                # Clamp range to volume boundaries
                rng = m.get("target_chapter_range", [start_ch, end_ch])
                if len(rng) >= 2:
                    rng = [max(rng[0], start_ch), min(rng[1], end_ch)]
                    m["target_chapter_range"] = rng
                obj = NarrativeMilestone(**m)
                valid.append(obj.model_dump())
            except Exception:
                log.warning("跳过无效里程碑: %s", m)

        log.info(
            "卷%d 自动生成 %d 个里程碑 (共 %d 个候选)",
            vol_num, len(valid), len(raw_milestones),
        )
        return valid

