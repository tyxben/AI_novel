"""A/B 成对比较 — Phase 5 E3 交付。

对应设计文档：``specs/architecture-rework-2026/PHASE5.md`` 第 3.2.3 节。

用法
----
1. :func:`pairwise_judge` — 让 judge LLM 对比两段同体裁同章节号的文本，
   返回 :class:`~src.novel.quality.report.ABComparisonResult`。
2. :func:`load_baseline` — 从 ``workspace/quality_baselines/<phase>/<genre>/``
   加载基线章节文本，供回归脚本做 A/B 对比。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from src.llm import create_llm_client
from src.novel.quality import AB_DIMENSIONS
from src.novel.quality.judge import (
    JudgeConfig,
    _build_llm_config,
    _parse_json_response,
    _safe_token_usage,
    _sanitize_chapter_text,
    _SYSTEM_PREFIX,
)
from src.novel.quality.report import ABComparisonResult

log = logging.getLogger("novel.quality.ab_compare")


# H6 fix: 维度列表从 src.novel.quality 模块常量引用，不再此处硬编码。
# 保留 ``_AB_DIMENSIONS`` 别名以兼容现有测试（test_ab_compare.py 已导入）。
_AB_DIMENSIONS: tuple[str, ...] = AB_DIMENSIONS

_VALID_VERDICTS: frozenset[str] = frozenset({"a", "b", "tie"})


def _normalize_verdict(raw: Any) -> str:
    """把 ``"A"``/``"B"``/``"Tie"``/``"相同"`` 等归一为 ``a``/``b``/``tie``。"""
    if raw is None:
        return "tie"
    text = str(raw).strip().lower()
    if text in _VALID_VERDICTS:
        return text
    if text in {"相同", "平", "平手", "equal", "draw"}:
        return "tie"
    if text in {"version_a", "a 版", "a版"}:
        return "a"
    if text in {"version_b", "b 版", "b版"}:
        return "b"
    return "tie"


def pairwise_judge(
    text_a: str,
    text_b: str,
    genre: str,
    chapter_number: int,
    commit_a: str,
    commit_b: str,
    config: JudgeConfig,
    *,
    max_chars: int = 6000,
) -> ABComparisonResult:
    """A/B 成对比较。

    Args:
        text_a: 版本 A 的章节正文。
        text_b: 版本 B 的章节正文。
        genre: 体裁（如 ``"玄幻"``）。
        chapter_number: 章节号。
        commit_a: 版本 A 的 git commit hash（人读/溯源用）。
        commit_b: 版本 B 的 git commit hash。
        config: :class:`JudgeConfig`。
        max_chars: A/B 比较单段文本截断上限（H4 fix: single/multi judge 的 4000
            对 A/B 两段同时塞入上下文太紧，默认放宽到 6000；测试时可精确指定）。

    Returns:
        :class:`ABComparisonResult`。LLM 解析失败时 winner="tie"，
        ``judge_reasoning`` 带 ``parse_error`` 前缀。
    """
    sanitized_a = _sanitize_chapter_text(text_a, max_chars=max_chars)
    sanitized_b = _sanitize_chapter_text(text_b, max_chars=max_chars)

    dim_list = "、".join(_AB_DIMENSIONS)
    dim_json = ", ".join(f'"{d}": "a" | "b" | "tie"' for d in _AB_DIMENSIONS)

    user_prompt = (
        "下面是同一体裁、同一章节号的两个版本。请判断哪个版本整体质量更好。\n\n"
        f"## 体裁: {genre}\n"
        f"## 章节号: {chapter_number}\n\n"
        f"## 版本 A\n{sanitized_a}\n\n"
        f"## 版本 B\n{sanitized_b}\n\n"
        "评判要求：\n"
        f"- 从 {dim_list} 五个维度逐一对比\n"
        "- 给出每个维度的偏好 (\"a\" / \"b\" / \"tie\")\n"
        "- 给出整体胜者 (\"a\" / \"b\" / \"tie\")\n"
        "- 不要被文本长度影响判断——更长不等于更好\n"
        "- 如果两者质量接近，坦诚给 \"tie\"\n\n"
        "严格输出 JSON:\n"
        "{\n"
        '  "winner": "a" | "b" | "tie",\n'
        '  "reasoning": "<200字以内>",\n'
        '  "dimension_preferences": {' + dim_json + "}\n"
        "}"
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PREFIX},
        {"role": "user", "content": user_prompt},
    ]

    # 调 LLM（两次尝试）
    total_tokens = 0
    parsed: dict[str, Any] | None = None
    last_raw = ""
    for attempt in range(2):
        try:
            client = create_llm_client(_build_llm_config(config))
            resp = client.chat(
                messages=messages,
                temperature=config.temperature,
                json_mode=True,
                max_tokens=config.max_tokens,
            )
            last_raw = resp.content
            total_tokens += _safe_token_usage(resp.usage)
        except Exception as exc:  # pragma: no cover
            log.warning("pairwise_judge LLM 调用失败 attempt=%d err=%s", attempt, exc)
            continue
        parsed = _parse_json_response(last_raw)
        if parsed is not None:
            break
        log.warning("pairwise_judge 非 JSON attempt=%d, 重试...", attempt)

    if parsed is None:
        return ABComparisonResult(
            genre=genre,
            chapter_number=chapter_number,
            commit_a=commit_a,
            commit_b=commit_b,
            winner="tie",
            judge_reasoning=f"parse_error: 两次重试后仍无法解析 JSON. raw={last_raw[:200]}",
            dimension_preferences={dim: "tie" for dim in _AB_DIMENSIONS},
            judge_model=config.model,
            judge_token_usage=total_tokens,
        )

    winner = _normalize_verdict(parsed.get("winner"))
    reasoning = str(parsed.get("reasoning", "") or "")
    dim_prefs_raw = parsed.get("dimension_preferences") or {}
    dim_prefs: dict[str, str] = {}
    for dim in _AB_DIMENSIONS:
        dim_prefs[dim] = _normalize_verdict(dim_prefs_raw.get(dim) if isinstance(dim_prefs_raw, dict) else None)

    return ABComparisonResult(
        genre=genre,
        chapter_number=chapter_number,
        commit_a=commit_a,
        commit_b=commit_b,
        winner=winner,
        judge_reasoning=reasoning,
        dimension_preferences=dim_prefs,
        judge_model=config.model,
        judge_token_usage=total_tokens,
    )


# ---------------------------------------------------------------------------
# 基线加载
# ---------------------------------------------------------------------------


_CHAPTER_FILENAME_RE = re.compile(r"chapter[_-]?(\d+)\.txt$", re.IGNORECASE)


def _extract_chapter_number(filename: str) -> int | None:
    """从 ``chapter_001.txt`` / ``chapter_1.txt`` 等文件名提取章节号。"""
    match = _CHAPTER_FILENAME_RE.search(filename)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def load_baseline(baseline_dir: str, genre: str) -> dict[int, str]:
    """从 ``<baseline_dir>/<genre>/chapter_*.txt`` 加载章节正文。

    Args:
        baseline_dir: 基线根目录，如 ``workspace/quality_baselines/phase4``。
        genre: 体裁 key，如 ``"xuanhuan"``。

    Returns:
        ``{chapter_number: text}``；目录不存在或无章节文件时返回 ``{}``。
    """
    root = Path(baseline_dir) / genre
    if not root.exists() or not root.is_dir():
        log.info("baseline 目录不存在: %s", root)
        return {}

    result: dict[int, str] = {}
    for txt_path in sorted(root.glob("chapter_*.txt")):
        ch_num = _extract_chapter_number(txt_path.name)
        if ch_num is None:
            continue
        try:
            result[ch_num] = txt_path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover
            log.warning("读取 baseline 章节失败 %s: %s", txt_path, exc)
    return result


__all__ = [
    "pairwise_judge",
    "load_baseline",
]
