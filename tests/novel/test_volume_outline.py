"""Tests for volume-based outline generation (long novel support).

Covers:
1. NovelDirector.generate_volume_outline — generates chapter outlines for a
   specific volume given overall framework and previous content summary.
2. NovelPipeline._extend_outline — automatically extends the outline when
   requested chapters exceed the current outline range.
3. Large novel creation — verifies that novels > 30 chapters only produce
   first-volume chapter outlines at creation time.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake-model"
    usage: dict | None = None


def _make_volume_outline_response(start_ch: int, end_ch: int) -> str:
    """Return a JSON string that mimics LLM output for volume outline."""
    chapters = []
    for i in range(start_ch, end_ch + 1):
        chapters.append({
            "chapter_number": i,
            "title": f"第{i}章测试",
            "goal": f"目标{i}",
            "key_events": [f"事件{i}"],
            "involved_characters": [],
            "plot_threads": [],
            "estimated_words": 2500,
            "mood": "蓄力",
            "storyline_progress": f"推进主线{i}",
            "chapter_summary": f"第{i}章摘要",
            "chapter_brief": {
                "main_conflict": f"冲突{i}",
                "payoff": f"爽点{i}",
                "character_arc_step": f"变化{i}",
                "foreshadowing_plant": [],
                "foreshadowing_collect": [],
                "end_hook_type": "悬疑",
            },
        })
    return json.dumps({"chapters": chapters}, ensure_ascii=False)


def _make_outline_dict(total_chapters: int = 5) -> dict:
    """Create a minimal outline dict."""
    return {
        "template": "cyclic_upgrade",
        "main_storyline": {
            "protagonist": "张三",
            "protagonist_goal": "成为最强",
            "core_conflict": "天赋不足",
            "character_arc": "从弱小到强大",
            "stakes": "失去生命",
            "theme_statement": "坚持就是胜利",
        },
        "acts": [
            {
                "name": "第一幕",
                "description": "开端",
                "start_chapter": 1,
                "end_chapter": total_chapters,
            }
        ],
        "volumes": [
            {
                "volume_number": 1,
                "title": "第一卷",
                "core_conflict": "矛盾1",
                "resolution": "解决1",
                "chapters": list(range(1, total_chapters + 1)),
            }
        ],
        "chapters": [
            {
                "chapter_number": i,
                "title": f"第{i}章测试",
                "goal": f"目标{i}",
                "key_events": [f"事件{i}"],
                "estimated_words": 2500,
                "mood": "蓄力",
            }
            for i in range(1, total_chapters + 1)
        ],
    }


def _make_long_outline_dict(
    first_volume_chapters: int = 30,
    volume_count: int = 4,
) -> dict:
    """Create an outline for a long novel with only first-volume chapters."""
    volumes = []
    cpv = first_volume_chapters
    for v in range(1, volume_count + 1):
        start = (v - 1) * cpv + 1
        end = v * cpv
        volumes.append({
            "volume_number": v,
            "title": f"第{v}卷",
            "core_conflict": f"矛盾{v}",
            "resolution": f"解决{v}",
            "chapters": list(range(start, end + 1)),
        })

    # Only first volume has detailed chapter outlines
    chapters = [
        {
            "chapter_number": i,
            "title": f"第{i}章",
            "goal": f"目标{i}",
            "key_events": [f"事件{i}"],
            "estimated_words": 2500,
            "mood": "蓄力",
        }
        for i in range(1, first_volume_chapters + 1)
    ]

    return {
        "template": "cyclic_upgrade",
        "main_storyline": {
            "protagonist": "张三",
            "protagonist_goal": "成为最强",
            "core_conflict": "天赋不足",
            "character_arc": "从弱小到强大",
            "stakes": "失去生命",
        },
        "acts": [
            {
                "name": "第一幕",
                "description": "开端",
                "start_chapter": 1,
                "end_chapter": first_volume_chapters * volume_count,
            }
        ],
        "volumes": volumes,
        "chapters": chapters,
    }


def _make_world_setting_dict() -> dict:
    return {
        "era": "上古时代",
        "location": "九州大陆",
        "rules": [],
        "terms": {},
        "power_system": None,
    }


# ---------------------------------------------------------------------------
# Test: generate_volume_outline
# ---------------------------------------------------------------------------


class TestGenerateVolumeOutline:
    """Test NovelDirector.generate_volume_outline."""

    def test_generates_chapters_for_specified_volume(self):
        """Should generate chapter outlines for the requested volume."""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        # Volume 2 should be chapters 31-60
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(31, 60)
        )

        director = NovelDirector(mock_llm)
        novel_data = {
            "genre": "玄幻",
            "theme": "少年修炼",
            "outline": _make_long_outline_dict(30, 4),
            "world_setting": _make_world_setting_dict(),
            "characters": [
                {"name": "张三", "role": "主角"},
                {"name": "李四", "role": "反派"},
            ],
        }

        result = director.generate_volume_outline(
            novel_data=novel_data,
            volume_number=2,
            previous_summary="第1卷：张三觉醒天赋...",
        )

        assert len(result) == 30
        assert result[0]["chapter_number"] == 31
        assert result[-1]["chapter_number"] == 60
        mock_llm.chat.assert_called_once()

    def test_fallback_for_missing_volume(self):
        """When volume_number is not in outline.volumes, should still work."""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        # No volume 5 exists in the outline, so it should compute range from existing chapters
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(31, 60)
        )

        director = NovelDirector(mock_llm)
        novel_data = {
            "genre": "玄幻",
            "theme": "少年修炼",
            "outline": _make_long_outline_dict(30, 2),  # only 2 volumes defined
            "world_setting": {},
            "characters": [],
        }

        result = director.generate_volume_outline(
            novel_data=novel_data,
            volume_number=5,
            previous_summary="",
        )

        # Should still produce valid chapters (fallback uses existing_max + 1)
        assert len(result) >= 1
        assert all("chapter_number" in ch for ch in result)

    def test_fills_placeholder_on_missing_chapters(self):
        """If LLM returns fewer chapters than expected, placeholders are filled."""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        # Return only 2 of the expected 30 chapters
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(31, 32)
        )

        director = NovelDirector(mock_llm)
        novel_data = {
            "genre": "玄幻",
            "theme": "少年修炼",
            "outline": _make_long_outline_dict(30, 4),
            "world_setting": {},
            "characters": [],
        }

        result = director.generate_volume_outline(
            novel_data=novel_data,
            volume_number=2,
            previous_summary="",
        )

        # Should have all 30 chapters filled (2 real + 28 placeholder)
        assert len(result) == 30
        # First 2 have real goals, rest are placeholders
        assert result[0]["goal"] == "目标31"
        assert result[2]["goal"] == "待规划"

    def test_retries_on_llm_failure(self):
        """Should retry up to MAX_OUTLINE_RETRIES on LLM errors."""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            RuntimeError("API error"),
            RuntimeError("API error"),
            FakeLLMResponse(content=_make_volume_outline_response(31, 60)),
        ]

        director = NovelDirector(mock_llm)
        novel_data = {
            "genre": "玄幻",
            "theme": "少年修炼",
            "outline": _make_long_outline_dict(30, 4),
            "world_setting": {},
            "characters": [],
        }

        result = director.generate_volume_outline(
            novel_data=novel_data,
            volume_number=2,
            previous_summary="",
        )

        assert len(result) == 30
        assert mock_llm.chat.call_count == 3

    def test_raises_after_max_retries(self):
        """Should raise RuntimeError if all retries fail."""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("API error")

        director = NovelDirector(mock_llm)
        novel_data = {
            "genre": "玄幻",
            "theme": "少年修炼",
            "outline": _make_long_outline_dict(30, 4),
            "world_setting": {},
            "characters": [],
        }

        with pytest.raises(RuntimeError, match="大纲生成失败"):
            director.generate_volume_outline(
                novel_data=novel_data,
                volume_number=2,
                previous_summary="",
            )

    def test_invalid_json_response(self):
        """Should retry on non-JSON LLM responses."""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            FakeLLMResponse(content="这不是JSON"),
            FakeLLMResponse(content="still not json"),
            FakeLLMResponse(content=_make_volume_outline_response(31, 60)),
        ]

        director = NovelDirector(mock_llm)
        novel_data = {
            "genre": "玄幻",
            "theme": "少年修炼",
            "outline": _make_long_outline_dict(30, 4),
            "world_setting": {},
            "characters": [],
        }

        result = director.generate_volume_outline(
            novel_data=novel_data,
            volume_number=2,
            previous_summary="",
        )

        assert len(result) == 30
        assert mock_llm.chat.call_count == 3

    def test_d2_fallback_uses_volumes_not_polluted_chapters_max(self):
        """D2 regression: 当 target_volume.chapters 空（被错误覆盖）+ outline.chapters
        被污染（含远超本卷的幽灵章节号）时，必须从 outline.volumes 上一卷推断起点，
        而不是从 outline.chapters max+1 算（事故源头：ch201-235 凭空冒出）。

        场景模拟：
        - outline.volumes 正常：vol1[1-30]、vol2[31-60]
        - vol2.chapters 被某次 accept_proposal 错误清空 → []
        - outline.chapters 被先前坏路径污染：含 ch200 的幽灵记录
        - 调用 generate_volume_outline(volume_number=2)

        预期：start_ch=31（从 vol1.chapters max+1 推断），不是 201。
        """
        from src.novel.agents.novel_director import NovelDirector

        captured_prompts: list[str] = []

        def _capture(messages, **kwargs):
            captured_prompts.append(messages[1]["content"])
            # 返回 31-60 章，让测试不会因 LLM 内容失败
            return FakeLLMResponse(content=_make_volume_outline_response(31, 60))

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = _capture

        # 构造受污染的 outline：vol1 正常，vol2.chapters 空，outline.chapters 含幽灵 ch200
        outline = {
            "template": "cyclic_upgrade",
            "main_storyline": {"protagonist_goal": "G", "core_conflict": "C"},
            "acts": [{"name": "幕1", "description": "开端", "start_chapter": 1, "end_chapter": 60}],
            "volumes": [
                {
                    "volume_number": 1,
                    "title": "第一卷",
                    "core_conflict": "矛盾1",
                    "resolution": "解决1",
                    "chapters": list(range(1, 31)),
                },
                {
                    "volume_number": 2,
                    "title": "第二卷",
                    "core_conflict": "矛盾2",
                    "resolution": "解决2",
                    "chapters": [],  # ← 被错误清空
                },
            ],
            # outline.chapters 含 vol1 全部 30 章 + 一条 ch200 幽灵记录
            "chapters": [
                {
                    "chapter_number": i,
                    "title": f"第{i}章",
                    "goal": f"G{i}",
                    "key_events": [f"E{i}"],
                    "estimated_words": 2500,
                    "mood": "蓄力",
                }
                for i in list(range(1, 31)) + [200]
            ],
        }
        director = NovelDirector(mock_llm)
        novel_data = {
            "genre": "玄幻",
            "theme": "少年修炼",
            "outline": outline,
            "world_setting": {},
            "characters": [],
        }

        director.generate_volume_outline(
            novel_data=novel_data,
            volume_number=2,
            previous_summary="",
        )

        assert captured_prompts, "LLM 应被调用至少一次"
        prompt = captured_prompts[0]
        # 起点必须是 31（vol1 max+1），绝不是 201（污染 max+1）
        # chapters_count 走 genre 推（玄幻 35 章/卷）→ end_ch=65
        assert "第31章" in prompt, (
            f"prompt 中卷起点应为 31（vol1 max+1），实际片段:\n{prompt[:1500]}"
        )
        assert "第201章" not in prompt and "第230章" not in prompt, (
            "fallback 不该从 outline.chapters max+1=201 起算，应从 vol1 推断"
        )
        # 玄幻 35 章/卷 → vol2 范围 31-65
        assert "第31章 - 第65章" in prompt, (
            f"玄幻 vol2 应按 35 章/卷算 31-65，实际:\n{prompt[:1500]}"
        )

    def test_d2_fallback_volume1_uses_ordinal_when_no_prior_volume(self):
        """D2 边界：volume_number=1 且 chapters 空时，上一卷不存在，
        应按卷号序数从 ch1 起算（不从 outline.chapters max+1）。"""
        from src.novel.agents.novel_director import NovelDirector

        captured: list[str] = []

        def _capture(messages, **kwargs):
            captured.append(messages[1]["content"])
            return FakeLLMResponse(content=_make_volume_outline_response(1, 30))

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = _capture

        outline = {
            "template": "cyclic_upgrade",
            "main_storyline": {"protagonist_goal": "G", "core_conflict": "C"},
            "acts": [{"name": "幕1", "description": "x", "start_chapter": 1, "end_chapter": 30}],
            "volumes": [
                {
                    "volume_number": 1,
                    "title": "第一卷",
                    "core_conflict": "矛盾1",
                    "resolution": "解决1",
                    "chapters": [],  # ← 空
                },
            ],
            # 即使 outline.chapters 含幽灵记录也不应影响 vol1 起点
            "chapters": [
                {
                    "chapter_number": 999,
                    "title": "幽灵",
                    "goal": "G",
                    "key_events": ["E"],
                    "estimated_words": 2500,
                    "mood": "蓄力",
                }
            ],
        }
        director = NovelDirector(mock_llm)
        director.generate_volume_outline(
            novel_data={
                "genre": "玄幻", "theme": "x", "outline": outline,
                "world_setting": {}, "characters": [],
            },
            volume_number=1,
            previous_summary="",
        )

        prompt = captured[0]
        # 玄幻 35 章/卷 → vol1 范围 1-35
        assert "第1章 - 第35章" in prompt, f"vol1 起点应为 1，prompt 片段:\n{prompt[:1500]}"
        assert "第1000章" not in prompt and "第999章" not in prompt

    def test_d2_fallback_strict_prev_volume_no_skip_over_empty(self):
        """D2 H2: vol3 请求时，必须严格找 vol2 (volume_number-1)。
        即使 vol2.chapters 空，也不应跨过 vol2 取 vol1.max+1=31 当作起点。
        正确行为：走 ordinal fallback 算 (3-1)*30+1=61。"""
        from src.novel.agents.novel_director import NovelDirector

        captured: list[str] = []

        def _capture(messages, **kwargs):
            captured.append(messages[1]["content"])
            return FakeLLMResponse(content=_make_volume_outline_response(61, 90))

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = _capture

        outline = {
            "template": "cyclic_upgrade",
            "main_storyline": {"protagonist_goal": "G", "core_conflict": "C"},
            "acts": [{"name": "幕1", "description": "x", "start_chapter": 1, "end_chapter": 90}],
            "volumes": [
                {"volume_number": 1, "title": "vol1", "core_conflict": "x",
                 "resolution": "x", "chapters": list(range(1, 31))},
                {"volume_number": 2, "title": "vol2", "core_conflict": "x",
                 "resolution": "x", "chapters": []},  # 中间空卷
                {"volume_number": 3, "title": "vol3", "core_conflict": "x",
                 "resolution": "x", "chapters": []},
            ],
            "chapters": [
                {"chapter_number": i, "title": f"第{i}章", "goal": f"G{i}",
                 "key_events": [f"E{i}"], "estimated_words": 2500, "mood": "蓄力"}
                for i in range(1, 31)
            ],
        }
        director = NovelDirector(mock_llm)
        director.generate_volume_outline(
            novel_data={"genre": "玄幻", "theme": "x", "outline": outline,
                        "world_setting": {}, "characters": []},
            volume_number=3,
            previous_summary="",
        )
        prompt = captured[0]
        # 玄幻 _GENRE_CHAPTERS_PER_VOLUME=35 → vol3 ordinal=(3-1)*35+1=71，不是 31
        assert "第71章" in prompt, f"应按 genre 35 章/卷算 vol3=71-105，实际:\n{prompt[:1500]}"
        assert "第31章 - 第60章" not in prompt, "vol3 不该挑 vol1 max+1=31 当起点"

    def test_d2_fallback_uses_genre_chapters_per_volume(self):
        """D2 H1: ordinal fallback 应按 genre 推 chapters_count，不是硬编码 30。
        修仙 _GENRE_CHAPTERS_PER_VOLUME=40 → vol2 ordinal=(2-1)*40+1=41。"""
        from src.novel.agents.novel_director import NovelDirector

        captured: list[str] = []

        def _capture(messages, **kwargs):
            captured.append(messages[1]["content"])
            return FakeLLMResponse(content=_make_volume_outline_response(41, 80))

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = _capture

        # 全空 prior chapters → 走 ordinal
        outline = {
            "template": "cyclic_upgrade",
            "main_storyline": {"protagonist_goal": "G", "core_conflict": "C"},
            "acts": [{"name": "幕1", "description": "x", "start_chapter": 1, "end_chapter": 80}],
            "volumes": [
                {"volume_number": 1, "title": "vol1", "core_conflict": "x",
                 "resolution": "x", "chapters": []},
                {"volume_number": 2, "title": "vol2", "core_conflict": "x",
                 "resolution": "x", "chapters": []},
            ],
            "chapters": [],
        }
        director = NovelDirector(mock_llm)
        director.generate_volume_outline(
            novel_data={"genre": "修仙", "theme": "x", "outline": outline,
                        "world_setting": {}, "characters": []},
            volume_number=2,
            previous_summary="",
        )
        prompt = captured[0]
        assert "第41章" in prompt and "第80章" in prompt, (
            f"修仙体裁 vol2 应用 40 章/卷算 41-80，实际:\n{prompt[:1500]}"
        )

    def test_d2_fallback_respects_outline_default_chapters_per_volume(self):
        """D2 H1 优先级：outline.default_chapters_per_volume > genre 表 > 30。"""
        from src.novel.agents.novel_director import NovelDirector

        captured: list[str] = []
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = lambda messages, **kw: (
            captured.append(messages[1]["content"])
            or FakeLLMResponse(content=_make_volume_outline_response(16, 30))
        )

        outline = {
            "template": "custom",
            "default_chapters_per_volume": 15,  # outline 自带配置覆盖 genre 表
            "main_storyline": {"protagonist_goal": "G", "core_conflict": "C"},
            "acts": [{"name": "幕1", "description": "x", "start_chapter": 1, "end_chapter": 60}],
            "volumes": [
                {"volume_number": 1, "title": "vol1", "core_conflict": "x",
                 "resolution": "x", "chapters": []},
                {"volume_number": 2, "title": "vol2", "core_conflict": "x",
                 "resolution": "x", "chapters": []},
            ],
            "chapters": [],
        }
        director = NovelDirector(mock_llm)
        director.generate_volume_outline(
            novel_data={"genre": "修仙", "theme": "x", "outline": outline,
                        "world_setting": {}, "characters": []},
            volume_number=2,
            previous_summary="",
        )
        prompt = captured[0]
        # outline.default_chapters_per_volume=15 应胜过修仙 genre 的 40
        assert "第16章 - 第30章" in prompt, (
            f"应按 outline.default_chapters_per_volume=15 算 vol2=16-30，实际:\n{prompt[:1500]}"
        )

    def test_d3_batches_when_volume_exceeds_batch_size(self):
        """D3: 单卷 50 章超过 BATCH_MAX_CHAPTERS=30 时，应分批 LLM call。

        原 8192 max_tokens 单次 call 35+ 章会被 JSON 截断，丢失尾部章节。
        分批后每批 ≤ 30 章，token 余量充裕；50 章近似均衡切 25+25。
        """
        from src.novel.agents.novel_director import NovelDirector

        # vol1.chapters=[1..50] → 50 章，应分批 (20+20+10)
        outline = _make_outline_dict(50)
        outline["volumes"][0]["chapters"] = list(range(1, 51))
        # outline.chapters 也补齐到 50
        outline["chapters"] = [
            {
                "chapter_number": i, "title": f"第{i}章", "goal": f"G{i}",
                "key_events": [f"E{i}"], "estimated_words": 2500, "mood": "蓄力",
            }
            for i in range(1, 51)
        ]

        # 每次 LLM call 模拟"按本批 chapter_number range 返回"
        # NovelDirector 应在每次 call 里把 batch 的 start_ch/end_ch 写进 prompt
        captured_ranges: list[tuple[int, int]] = []

        def _by_batch(messages, **kwargs):
            prompt = messages[1]["content"]
            # 解析"章节号从 X 开始，到 Y 结束"
            import re
            m = re.search(r"章节号从\s*(\d+)\s*开始，到\s*(\d+)\s*结束", prompt)
            if not m:
                raise AssertionError(f"prompt 缺 batch range:\n{prompt[:600]}")
            s, e = int(m.group(1)), int(m.group(2))
            captured_ranges.append((s, e))
            return FakeLLMResponse(content=_make_volume_outline_response(s, e))

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = _by_batch

        director = NovelDirector(mock_llm)
        result = director.generate_volume_outline(
            novel_data={
                "genre": "玄幻", "theme": "x", "outline": outline,
                "world_setting": _make_world_setting_dict(),
                "characters": [{"name": "张三", "role": "主角"}],
            },
            volume_number=1,
            previous_summary="",
        )

        # 应至少 2 次 call（50 章按 ≤ 30/批切 → 30+20）
        assert mock_llm.chat.call_count >= 2, (
            f"50 章应分批至少 2 次 LLM call，实际 {mock_llm.chat.call_count}"
        )
        # 各批 range 应完整覆盖 1-50 且无重叠
        covered = set()
        for s, e in captured_ranges:
            assert e - s + 1 <= 30, f"单批不应超 30 章（BATCH_MAX_CHAPTERS）实际 {s}-{e}"
            for n in range(s, e + 1):
                assert n not in covered, f"批次重叠：ch{n}"
                covered.add(n)
        assert covered == set(range(1, 51)), f"未覆盖完整 1-50，实际 {sorted(covered)}"
        # 最终输出 50 章
        assert len(result) == 50
        nums = sorted(c["chapter_number"] for c in result)
        assert nums == list(range(1, 51))

    def test_d3_no_batching_when_below_threshold(self):
        """D3 兼容：≤ BATCH_MAX_CHAPTERS 单次 call，保持原行为。"""
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(1, 15)
        )
        outline = _make_outline_dict(15)
        outline["volumes"][0]["chapters"] = list(range(1, 16))
        director = NovelDirector(mock_llm)
        director.generate_volume_outline(
            novel_data={
                "genre": "玄幻", "theme": "x", "outline": outline,
                "world_setting": {}, "characters": [],
            },
            volume_number=1,
            previous_summary="",
        )
        assert mock_llm.chat.call_count == 1, (
            f"15 章应单次 call，实际 {mock_llm.chat.call_count}"
        )

    def test_d3_batch_failure_only_retries_failing_batch(self, monkeypatch):
        """D3：分批模式下某批失败 retry 不影响其他批。"""
        import time as time_mod
        from src.novel.agents.novel_director import NovelDirector

        # L3：mock sleep 避免重试 backoff 真睡
        monkeypatch.setattr(time_mod, "sleep", lambda *a, **kw: None)

        outline = _make_outline_dict(40)
        outline["volumes"][0]["chapters"] = list(range(1, 41))
        outline["chapters"] = [
            {"chapter_number": i, "title": f"第{i}章", "goal": f"G{i}",
             "key_events": [f"E{i}"], "estimated_words": 2500, "mood": "蓄力"}
            for i in range(1, 41)
        ]

        # 40 章近似均衡切 20+20。第一批成功，第二批前两次 fail，第三次成功
        call_count = {"n": 0, "second_batch": 0}

        def _flaky(messages, **kwargs):
            call_count["n"] += 1
            prompt = messages[1]["content"]
            import re
            m = re.search(r"章节号从\s*(\d+)\s*开始，到\s*(\d+)\s*结束", prompt)
            s, e = int(m.group(1)), int(m.group(2))
            if s >= 21:  # 40 章 → batches=(1,20)+(21,40)，第二批 s=21
                call_count["second_batch"] += 1
                if call_count["second_batch"] < 3:
                    raise RuntimeError("API timeout")
            return FakeLLMResponse(content=_make_volume_outline_response(s, e))

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = _flaky

        director = NovelDirector(mock_llm)
        result = director.generate_volume_outline(
            novel_data={
                "genre": "玄幻", "theme": "x", "outline": outline,
                "world_setting": {}, "characters": [],
            },
            volume_number=1,
            previous_summary="",
        )
        # 第一批 1 次 + 第二批 3 次 = 4 次
        assert call_count["n"] == 4, f"实际 LLM call={call_count['n']}"
        assert len(result) == 40

    def test_d3_balanced_batch_split_avoids_singleton_tail(self):
        """D3 H2：31 章应均衡切 16+15，不切 30+1（末批单章 prompt 质量差）。"""
        from src.novel.agents.novel_director import NovelDirector

        captured: list[tuple[int, int]] = []

        def _by_batch(messages, **kwargs):
            import re
            prompt = messages[1]["content"]
            m = re.search(r"章节号从\s*(\d+)\s*开始，到\s*(\d+)\s*结束", prompt)
            s, e = int(m.group(1)), int(m.group(2))
            captured.append((s, e))
            return FakeLLMResponse(content=_make_volume_outline_response(s, e))

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = _by_batch

        outline = _make_outline_dict(31)
        outline["volumes"][0]["chapters"] = list(range(1, 32))
        outline["chapters"] = [
            {"chapter_number": i, "title": f"第{i}章", "goal": f"G{i}",
             "key_events": [f"E{i}"], "estimated_words": 2500, "mood": "蓄力"}
            for i in range(1, 32)
        ]

        director = NovelDirector(mock_llm)
        director.generate_volume_outline(
            novel_data={
                "genre": "玄幻", "theme": "x", "outline": outline,
                "world_setting": {}, "characters": [],
            },
            volume_number=1,
            previous_summary="",
        )
        # 31 章 → math.ceil(31/30)=2 批，divmod(31,2)=(15,1) → 16+15
        assert len(captured) == 2, f"31 章应分 2 批，实际 {captured}"
        sizes = sorted([e - s + 1 for s, e in captured])
        assert sizes == [15, 16], f"近似均衡切分应为 15+16，实际 {sizes}"

    def test_d3_injects_prev_batch_tail_into_next_batch_prompt(self):
        """D3 H1：分批时下一批 prompt 必须包含上一批最后 2-3 章 summary 衔接。"""
        from src.novel.agents.novel_director import NovelDirector

        prompts: list[str] = []

        def _by_batch(messages, **kwargs):
            import re
            prompt = messages[1]["content"]
            prompts.append(prompt)
            m = re.search(r"章节号从\s*(\d+)\s*开始，到\s*(\d+)\s*结束", prompt)
            s, e = int(m.group(1)), int(m.group(2))
            return FakeLLMResponse(content=_make_volume_outline_response(s, e))

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = _by_batch

        outline = _make_outline_dict(50)
        outline["volumes"][0]["chapters"] = list(range(1, 51))
        outline["chapters"] = [
            {"chapter_number": i, "title": f"第{i}章", "goal": f"G{i}",
             "key_events": [f"E{i}"], "estimated_words": 2500, "mood": "蓄力"}
            for i in range(1, 51)
        ]

        director = NovelDirector(mock_llm)
        director.generate_volume_outline(
            novel_data={
                "genre": "玄幻", "theme": "x", "outline": outline,
                "world_setting": {}, "characters": [],
            },
            volume_number=1,
            previous_summary="第0卷收尾",
        )
        # 至少 2 批
        assert len(prompts) >= 2
        first, *rest = prompts
        # 第一批不该看到 "上一批已生成"
        assert "上一批已生成章节" not in first
        # 后续每批都应注入上一批 tail
        for p in rest:
            assert "上一批已生成章节" in p, (
                f"分批模式后续批 prompt 缺 prev_batch_tail 注入:\n{p[:1000]}"
            )

    def test_d3_drops_out_of_range_chapter_numbers(self, caplog):
        """D3 M2：LLM 越界返回 chapter_number 应被丢弃 + 触发 warning。"""
        import logging
        from src.novel.agents.novel_director import NovelDirector

        # batch1 LLM 错回 ch1-5（应该是 ch1-25），batch2 正常返回 ch26-50
        def _by_batch(messages, **kwargs):
            import re
            prompt = messages[1]["content"]
            m = re.search(r"章节号从\s*(\d+)\s*开始，到\s*(\d+)\s*结束", prompt)
            s, e = int(m.group(1)), int(m.group(2))
            if s == 1:
                # 故意越界：返回的 chapter_number 都是 100+ (越界)
                return FakeLLMResponse(content=_make_volume_outline_response(100, 105))
            return FakeLLMResponse(content=_make_volume_outline_response(s, e))

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = _by_batch

        outline = _make_outline_dict(50)
        outline["volumes"][0]["chapters"] = list(range(1, 51))
        outline["chapters"] = [
            {"chapter_number": i, "title": f"第{i}章", "goal": f"G{i}",
             "key_events": [f"E{i}"], "estimated_words": 2500, "mood": "蓄力"}
            for i in range(1, 51)
        ]

        director = NovelDirector(mock_llm)
        with caplog.at_level(logging.WARNING, logger="novel"):
            result = director.generate_volume_outline(
                novel_data={
                    "genre": "玄幻", "theme": "x", "outline": outline,
                    "world_setting": {}, "characters": [],
                },
                volume_number=1,
                previous_summary="",
            )
        # 越界章节应被丢弃 → batch1 章节全靠 placeholder 兜底
        assert any("越界章号" in rec.message for rec in caplog.records), (
            "越界章号应触发 warning"
        )
        # 总章数仍为 50（兜底 placeholder 补齐）
        assert len(result) == 50
        nums = sorted(c["chapter_number"] for c in result)
        assert nums == list(range(1, 51))

    def test_d3_batched_prompt_contains_batch_note(self):
        """D3 L2: 分批模式下 prompt 应注入"批次说明"文本，让 LLM 知道全局位置。"""
        from src.novel.agents.novel_director import NovelDirector

        prompts: list[str] = []

        def _by_batch(messages, **kwargs):
            import re
            prompt = messages[1]["content"]
            prompts.append(prompt)
            m = re.search(r"章节号从\s*(\d+)\s*开始，到\s*(\d+)\s*结束", prompt)
            s, e = int(m.group(1)), int(m.group(2))
            return FakeLLMResponse(content=_make_volume_outline_response(s, e))

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = _by_batch

        outline = _make_outline_dict(50)
        outline["volumes"][0]["chapters"] = list(range(1, 51))
        outline["chapters"] = [
            {"chapter_number": i, "title": f"第{i}章", "goal": f"G{i}",
             "key_events": [f"E{i}"], "estimated_words": 2500, "mood": "蓄力"}
            for i in range(1, 51)
        ]
        director = NovelDirector(mock_llm)
        director.generate_volume_outline(
            novel_data={"genre": "玄幻", "theme": "x", "outline": outline,
                        "world_setting": {}, "characters": []},
            volume_number=1,
            previous_summary="",
        )
        # 每批 prompt 必须含"批次说明"+"本卷共 50 章"+"按 ≤30 章分批"
        for p in prompts:
            assert "【批次说明】" in p, f"分批 prompt 缺批次说明:\n{p[:600]}"
            assert "本卷共50章" in p, f"批次说明缺整卷章数:\n{p[:600]}"
            assert "≤30 章" in p, f"批次说明缺批阈值:\n{p[:600]}"

    def test_d3_no_batch_note_when_single_batch(self):
        """D3 L2 反向：≤ BATCH_MAX_CHAPTERS 单批时 prompt 不应有批次说明（避免误导）。"""
        from src.novel.agents.novel_director import NovelDirector

        prompts: list[str] = []

        def _capture(messages, **kwargs):
            prompts.append(messages[1]["content"])
            return FakeLLMResponse(content=_make_volume_outline_response(1, 20))

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = _capture

        outline = _make_outline_dict(20)
        outline["volumes"][0]["chapters"] = list(range(1, 21))
        director = NovelDirector(mock_llm)
        director.generate_volume_outline(
            novel_data={"genre": "玄幻", "theme": "x", "outline": outline,
                        "world_setting": {}, "characters": []},
            volume_number=1,
            previous_summary="",
        )
        assert len(prompts) == 1
        assert "【批次说明】" not in prompts[0]

    def test_d3_partial_recovery_logs_succeeded_batches_on_failure(
        self, monkeypatch, caplog
    ):
        """D3 M1: 中间批失败时，error log 应记录已成功批章号区间，方便手术修复。"""
        import logging
        import time as time_mod
        from src.novel.agents.novel_director import NovelDirector

        # mock sleep 避免 retry backoff 真睡
        monkeypatch.setattr(time_mod, "sleep", lambda *a, **kw: None)

        # 60 章 → math.ceil(60/30)=2 → 30+30；让第二批连续 RuntimeError 直至 max retry
        call_count = {"n": 0, "second_batch_fails": 0}

        def _flaky(messages, **kwargs):
            call_count["n"] += 1
            import re
            prompt = messages[1]["content"]
            m = re.search(r"章节号从\s*(\d+)\s*开始，到\s*(\d+)\s*结束", prompt)
            s, e = int(m.group(1)), int(m.group(2))
            if s >= 31:  # 第二批
                call_count["second_batch_fails"] += 1
                raise RuntimeError("LLM API down")
            return FakeLLMResponse(content=_make_volume_outline_response(s, e))

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = _flaky

        outline = _make_outline_dict(60)
        outline["volumes"][0]["chapters"] = list(range(1, 61))
        outline["chapters"] = [
            {"chapter_number": i, "title": f"第{i}章", "goal": f"G{i}",
             "key_events": [f"E{i}"], "estimated_words": 2500, "mood": "蓄力"}
            for i in range(1, 61)
        ]

        director = NovelDirector(mock_llm)
        with caplog.at_level(logging.ERROR, logger="novel"):
            with pytest.raises(RuntimeError):
                director.generate_volume_outline(
                    novel_data={"genre": "玄幻", "theme": "x", "outline": outline,
                                "world_setting": {}, "characters": []},
                    volume_number=1,
                    previous_summary="",
                )
        # 必须在抛 RuntimeError 前打印已成功批列表 [(1, 30)]
        partial_logs = [
            rec.message for rec in caplog.records
            if "已成功批" in rec.message and "(1, 30)" in rec.message
        ]
        assert partial_logs, (
            f"M1 partial recovery 日志应记录 succeeded_batches=[(1,30)]；实际:\n"
            + "\n".join(rec.message for rec in caplog.records)
        )

    def test_d3_first_batch_failure_logs_no_recoverable_data(
        self, monkeypatch, caplog
    ):
        """D3 M1 反向：首批即失败时，应明确记录"无可恢复数据"。"""
        import logging
        import time as time_mod
        from src.novel.agents.novel_director import NovelDirector

        monkeypatch.setattr(time_mod, "sleep", lambda *a, **kw: None)

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("LLM down")

        outline = _make_outline_dict(50)
        outline["volumes"][0]["chapters"] = list(range(1, 51))
        director = NovelDirector(mock_llm)
        with caplog.at_level(logging.ERROR, logger="novel"):
            with pytest.raises(RuntimeError):
                director.generate_volume_outline(
                    novel_data={"genre": "玄幻", "theme": "x", "outline": outline,
                                "world_setting": {}, "characters": []},
                    volume_number=1,
                    previous_summary="",
                )
        assert any(
            "首批" in rec.message and "无可恢复数据" in rec.message
            for rec in caplog.records
        ), (
            "首批失败应记录无可恢复数据；实际:\n"
            + "\n".join(rec.message for rec in caplog.records)
        )

    def test_d3_milestone_generation_works_with_batched_outline(self):
        """D3 L2 联动：分批生成的 chapter_outlines 喂给 generate_volume_milestones
        应正常产出 milestone，验证两个 LLM call 链路无字段不兼容。"""
        from src.novel.agents.novel_director import NovelDirector

        # 阶段 1: 分批生成 50 章 outline
        def _outline_by_batch(messages, **kwargs):
            import re
            prompt = messages[1]["content"]
            m = re.search(r"章节号从\s*(\d+)\s*开始，到\s*(\d+)\s*结束", prompt)
            if m:
                s, e = int(m.group(1)), int(m.group(2))
                return FakeLLMResponse(content=_make_volume_outline_response(s, e))
            # 阶段 2: milestone 生成
            return FakeLLMResponse(content=(
                '{"milestones": [{"milestone_id": "vol1_m1", '
                '"description": "主角觉醒灵根，进入修真界", '
                '"target_chapter_range": [1, 25], '
                '"verification_type": "auto_keyword", '
                '"verification_criteria": ["觉醒", "灵根"], '
                '"priority": "critical"}, {"milestone_id": "vol1_m2", '
                '"description": "主角拜师入门，建立人脉", '
                '"target_chapter_range": [25, 50], '
                '"verification_type": "auto_keyword", '
                '"verification_criteria": ["拜师"], "priority": "high"}]}'
            ))

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = _outline_by_batch

        outline = _make_outline_dict(50)
        outline["volumes"][0]["chapters"] = list(range(1, 51))
        outline["chapters"] = [
            {"chapter_number": i, "title": f"第{i}章", "goal": f"G{i}",
             "key_events": [f"E{i}"], "estimated_words": 2500, "mood": "蓄力"}
            for i in range(1, 51)
        ]
        director = NovelDirector(mock_llm)
        chapter_outlines = director.generate_volume_outline(
            novel_data={"genre": "玄幻", "theme": "x", "outline": outline,
                        "world_setting": {}, "characters": []},
            volume_number=1,
            previous_summary="",
        )
        assert len(chapter_outlines) == 50

        # 直接喂分批结果给 milestone 生成
        milestones = director.generate_volume_milestones(
            volume={"volume_number": 1, "title": "vol1",
                    "core_conflict": "x", "resolution": "x"},
            chapter_outlines=chapter_outlines,
            genre="玄幻",
        )
        assert len(milestones) >= 1, "milestone 生成不应空"
        # critical milestone 章号范围应在卷 [1, 50] 内
        for m in milestones:
            tcr = m.get("target_chapter_range") or [1, 50]
            assert 1 <= tcr[0] <= tcr[1] <= 50, f"milestone 章号越界: {m}"

    def test_d2_fallback_warns_on_overlap_with_existing_volume(self, caplog):
        """D2 H2 防御：fallback 推算范围若与现有卷 chapters 重叠，应告警。"""
        import logging
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(31, 60)
        )

        # 制造重叠：vol2.chapters 空 → fallback 算到 31-60；同时 vol3 已有 chapters [50..80]
        outline = {
            "template": "cyclic_upgrade",
            "main_storyline": {"protagonist_goal": "G", "core_conflict": "C"},
            "acts": [{"name": "幕1", "description": "x", "start_chapter": 1, "end_chapter": 80}],
            "volumes": [
                {"volume_number": 1, "title": "vol1", "core_conflict": "x",
                 "resolution": "x", "chapters": list(range(1, 31))},
                {"volume_number": 2, "title": "vol2", "core_conflict": "x",
                 "resolution": "x", "chapters": []},
                {"volume_number": 3, "title": "vol3", "core_conflict": "x",
                 "resolution": "x", "chapters": list(range(50, 81))},
            ],
            "chapters": [],
        }
        director = NovelDirector(mock_llm)
        with caplog.at_level(logging.WARNING, logger="novel"):
            director.generate_volume_outline(
                novel_data={"genre": "玄幻", "theme": "x", "outline": outline,
                            "world_setting": {}, "characters": []},
                volume_number=2,
                previous_summary="",
            )
        assert any("重叠" in rec.message for rec in caplog.records), (
            "重叠卷 chapters 应触发 warning"
        )

    def test_d2_fallback_logs_polluted_outline_chapters_max(self, caplog):
        """L2 取证：fallback 路径下日志应记录原 D2 修前会作起点的污染值。"""
        import logging
        from src.novel.agents.novel_director import NovelDirector

        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(31, 60)
        )

        # vol2 空 → fallback；outline.chapters 含幽灵 ch201（D2 修前会拿来作起点）
        outline = {
            "template": "cyclic_upgrade",
            "main_storyline": {"protagonist_goal": "G", "core_conflict": "C"},
            "acts": [{"name": "幕1", "description": "x", "start_chapter": 1, "end_chapter": 60}],
            "volumes": [
                {"volume_number": 1, "title": "vol1", "core_conflict": "x",
                 "resolution": "x", "chapters": list(range(1, 31))},
                {"volume_number": 2, "title": "vol2", "core_conflict": "x",
                 "resolution": "x", "chapters": []},
            ],
            "chapters": [
                {"chapter_number": i, "title": f"第{i}章", "goal": f"G{i}",
                 "key_events": [f"E{i}"], "estimated_words": 2500, "mood": "蓄力"}
                for i in range(1, 31)
            ] + [
                # 幽灵高号章节（来自先前坏路径）
                {"chapter_number": 201, "title": "幽灵章", "goal": "幽灵",
                 "key_events": ["x"], "estimated_words": 2500, "mood": "蓄力"}
            ],
        }
        director = NovelDirector(mock_llm)
        with caplog.at_level(logging.INFO, logger="novel"):
            director.generate_volume_outline(
                novel_data={"genre": "玄幻", "theme": "x", "outline": outline,
                            "world_setting": {}, "characters": []},
                volume_number=2,
                previous_summary="",
            )
        # 取证日志必须含 polluted max=201（明确表明 D2 已忽略它）
        assert any(
            "polluted" in rec.message.lower() and "201" in rec.message
            for rec in caplog.records
        ), (
            f"fallback 日志应记录 polluted outline.chapters max=201；实际:\n"
            + "\n".join(rec.message for rec in caplog.records)
        )


# ---------------------------------------------------------------------------
# Test: _extend_outline
# ---------------------------------------------------------------------------


class TestExtendOutline:
    """Test NovelPipeline._extend_outline."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_project(self, outline: dict, target_words: int = 300000) -> str:
        """Create a minimal project structure on disk."""
        novel_id = "novel_test1234"
        novel_dir = Path(self.tmpdir) / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)
        (novel_dir / "chapters").mkdir(exist_ok=True)

        novel_data = {
            "novel_id": novel_id,
            "title": "Test Novel",
            "genre": "玄幻",
            "theme": "测试主题",
            "target_words": target_words,
            "outline": outline,
            "characters": [{"name": "张三", "role": "主角"}],
            "world_setting": _make_world_setting_dict(),
            "status": "initialized",
            "current_chapter": 0,
        }
        with open(novel_dir / "novel.json", "w", encoding="utf-8") as f:
            json.dump(novel_data, f, ensure_ascii=False, indent=2)

        checkpoint = {
            "outline": outline,
            "config": {"llm": {}},
            "chapters": [],
        }
        with open(novel_dir / "checkpoint.json", "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)

        return novel_id

    @patch("src.llm.llm_client.create_llm_client")
    def test_extends_outline_to_cover_target(self, mock_create_llm):
        """_extend_outline should add chapters until target_chapter is covered."""
        from src.novel.pipeline import NovelPipeline
        from src.novel.config import load_novel_config

        outline = _make_long_outline_dict(30, 4)
        novel_id = self._create_project(outline)

        # Mock the LLM to return volume 2 chapters
        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(31, 60)
        )
        mock_create_llm.return_value = mock_llm

        pipe = NovelPipeline(workspace=self.tmpdir)

        state = {
            "outline": outline,
            "config": {"llm": {}},
            "chapters": [],
        }

        pipe._extend_outline(novel_id, state, target_chapter=45)

        # State should now have 60 chapters (30 original + 30 new)
        chapters = state["outline"]["chapters"]
        chapter_nums = sorted(ch["chapter_number"] for ch in chapters)
        assert max(chapter_nums) >= 45
        assert len(chapters) == 60

    @patch("src.llm.llm_client.create_llm_client")
    def test_extends_multiple_volumes(self, mock_create_llm):
        """Should extend across multiple volumes if needed."""
        from src.novel.pipeline import NovelPipeline

        outline = _make_long_outline_dict(30, 4)
        novel_id = self._create_project(outline)

        # Each volume expansion triggers: generate_volume_outline + generate_volume_milestones
        _milestone_resp = FakeLLMResponse(content='{"milestones": []}')
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            FakeLLMResponse(content=_make_volume_outline_response(31, 60)),  # vol 2 outline
            _milestone_resp,  # vol 2 milestones
            FakeLLMResponse(content=_make_volume_outline_response(61, 90)),  # vol 3 outline
            _milestone_resp,  # vol 3 milestones
        ]
        mock_create_llm.return_value = mock_llm

        pipe = NovelPipeline(workspace=self.tmpdir)

        state = {
            "outline": outline,
            "config": {"llm": {}},
            "chapters": [],
        }

        pipe._extend_outline(novel_id, state, target_chapter=75)

        chapters = state["outline"]["chapters"]
        chapter_nums = sorted(ch["chapter_number"] for ch in chapters)
        assert max(chapter_nums) >= 75
        assert len(chapters) == 90  # 30 + 30 + 30

    @patch("src.llm.llm_client.create_llm_client")
    def test_no_duplicate_chapters(self, mock_create_llm):
        """Should not add duplicate chapter numbers."""
        from src.novel.pipeline import NovelPipeline

        outline = _make_long_outline_dict(30, 4)
        novel_id = self._create_project(outline)

        # Return chapters that partially overlap with existing ones
        response_content = _make_volume_outline_response(25, 60)
        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(content=response_content)
        mock_create_llm.return_value = mock_llm

        pipe = NovelPipeline(workspace=self.tmpdir)

        state = {
            "outline": outline,
            "config": {"llm": {}},
            "chapters": [],
        }

        pipe._extend_outline(novel_id, state, target_chapter=50)

        chapters = state["outline"]["chapters"]
        chapter_nums = [ch["chapter_number"] for ch in chapters]
        # No duplicates
        assert len(chapter_nums) == len(set(chapter_nums))

    @patch("src.llm.llm_client.create_llm_client")
    def test_saves_checkpoint_and_novel(self, mock_create_llm):
        """Should persist changes to checkpoint.json and novel.json."""
        from src.novel.pipeline import NovelPipeline

        outline = _make_long_outline_dict(30, 4)
        novel_id = self._create_project(outline)

        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(31, 60)
        )
        mock_create_llm.return_value = mock_llm

        pipe = NovelPipeline(workspace=self.tmpdir)

        state = {
            "outline": outline,
            "config": {"llm": {}},
            "chapters": [],
        }

        pipe._extend_outline(novel_id, state, target_chapter=45)

        # Verify checkpoint was saved
        ckpt_path = Path(self.tmpdir) / "novels" / novel_id / "checkpoint.json"
        with open(ckpt_path, encoding="utf-8") as f:
            saved_ckpt = json.load(f)
        assert len(saved_ckpt["outline"]["chapters"]) == 60

        # Verify novel.json was saved
        novel_path = Path(self.tmpdir) / "novels" / novel_id / "novel.json"
        with open(novel_path, encoding="utf-8") as f:
            saved_novel = json.load(f)
        assert len(saved_novel["outline"]["chapters"]) == 60


# ---------------------------------------------------------------------------
# Test: _build_previous_summary
# ---------------------------------------------------------------------------


class TestBuildPreviousSummary:
    """Test NovelPipeline._build_previous_summary."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_written_chapters(self):
        """Should return placeholder when no chapters are written."""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=self.tmpdir)
        fm = FileManager(self.tmpdir)

        # Create project dir with no chapters
        novel_id = "novel_test1234"
        novel_dir = Path(self.tmpdir) / "novels" / novel_id / "chapters"
        novel_dir.mkdir(parents=True, exist_ok=True)

        result = pipe._build_previous_summary(novel_id, fm, up_to_chapter=30)
        assert "尚未生成" in result

    def test_summarizes_written_chapters(self):
        """Should include excerpts from written chapters."""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=self.tmpdir)
        fm = FileManager(self.tmpdir)

        novel_id = "novel_test1234"
        chapters_dir = Path(self.tmpdir) / "novels" / novel_id / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)

        # Write some chapter files
        for i in range(1, 4):
            fm.save_chapter(novel_id, i, {"chapter_number": i, "title": f"Ch{i}"})
            fm.save_chapter_text(novel_id, i, f"这是第{i}章的内容，讲述了主角的冒险故事。")

        result = pipe._build_previous_summary(novel_id, fm, up_to_chapter=10)
        assert "第1章" in result
        assert "第2章" in result
        assert "第3章" in result

    def test_respects_up_to_chapter_limit(self):
        """Should not include chapters beyond up_to_chapter."""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=self.tmpdir)
        fm = FileManager(self.tmpdir)

        novel_id = "novel_test1234"
        chapters_dir = Path(self.tmpdir) / "novels" / novel_id / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)

        for i in range(1, 6):
            fm.save_chapter(novel_id, i, {"chapter_number": i, "title": f"Ch{i}"})
            fm.save_chapter_text(novel_id, i, f"第{i}章内容")

        result = pipe._build_previous_summary(novel_id, fm, up_to_chapter=3)
        assert "第1章" in result
        assert "第3章" in result
        assert "第4章" not in result
        assert "第5章" not in result


# ---------------------------------------------------------------------------
# Test: Large novel creation (first_volume_only mode)
# ---------------------------------------------------------------------------


class TestLargeNovelOutlineGeneration:
    """Test that ProjectArchitect._generate_outline (Phase 3-B3 从 NovelDirector 迁入)
    produces only first-volume chapters for large novels."""

    def test_long_novel_only_generates_first_volume(self):
        """For 100k+ words, should only generate first volume chapters."""
        from src.novel.agents.novel_director import _CHAPTERS_PER_VOLUME
        from src.novel.agents.project_architect import ProjectArchitect

        mock_llm = MagicMock()

        # Simulate LLM returning a proper outline with only first volume chapters
        first_vol_chapters = _CHAPTERS_PER_VOLUME  # 30
        llm_response = {
            "main_storyline": {
                "protagonist": "张三",
                "protagonist_goal": "修炼成仙",
                "core_conflict": "天赋不足",
                "character_arc": "弱小到强大",
                "stakes": "身死道消",
                "theme_statement": "逆天改命",
            },
            "acts": [
                {"name": "第一幕", "description": "觉醒", "start_chapter": 1, "end_chapter": 100},
                {"name": "第二幕", "description": "崛起", "start_chapter": 101, "end_chapter": 200},
                {"name": "第三幕", "description": "称霸", "start_chapter": 201, "end_chapter": 300},
                {"name": "第四幕", "description": "飞升", "start_chapter": 301, "end_chapter": 400},
            ],
            "volumes": [
                {"volume_number": v, "title": f"第{v}卷", "core_conflict": f"矛盾{v}", "resolution": f"解决{v}",
                 "chapters": list(range((v-1)*first_vol_chapters + 1, v*first_vol_chapters + 1))}
                for v in range(1, 14)  # ~13 volumes for 1M words
            ],
            "chapters": [
                {
                    "chapter_number": i,
                    "title": f"第{i}章",
                    "goal": f"目标{i}",
                    "key_events": [f"事件{i}"],
                    "estimated_words": 2500,
                    "mood": "蓄力",
                    "storyline_progress": f"推进{i}",
                    "chapter_summary": f"摘要{i}",
                    "chapter_brief": {},
                }
                for i in range(1, first_vol_chapters + 1)
            ],
        }
        mock_llm.chat.return_value = FakeLLMResponse(
            content=json.dumps(llm_response, ensure_ascii=False)
        )

        architect = ProjectArchitect(mock_llm)
        outline = architect._generate_outline(
            genre="玄幻",
            theme="少年修炼逆天改命",
            target_words=1000000,  # 100万字
            template_name="cyclic_upgrade",
        )

        # Should only have first volume chapters (30), not all 400
        assert len(outline.chapters) == first_vol_chapters
        assert outline.chapters[0].chapter_number == 1
        assert outline.chapters[-1].chapter_number == first_vol_chapters

        # But should have all volumes in the framework
        assert len(outline.volumes) >= 10

        # And should have acts covering the full novel
        assert len(outline.acts) >= 2

    def test_small_novel_generates_all_chapters(self):
        """For <75k words, should generate all chapters at once."""
        from src.novel.agents.project_architect import ProjectArchitect

        mock_llm = MagicMock()

        total_ch = 20  # 50000 words / 2500 = 20 chapters
        llm_response = {
            "main_storyline": {
                "protagonist": "张三",
                "protagonist_goal": "修炼",
                "core_conflict": "障碍",
                "character_arc": "成长",
                "stakes": "失败",
                "theme_statement": "主题",
            },
            "acts": [
                {"name": "第一幕", "description": "开端", "start_chapter": 1, "end_chapter": total_ch},
            ],
            "volumes": [
                {"volume_number": 1, "title": "第一卷", "core_conflict": "矛盾", "resolution": "解决",
                 "chapters": list(range(1, total_ch + 1))},
            ],
            "chapters": [
                {
                    "chapter_number": i,
                    "title": f"第{i}章",
                    "goal": f"目标{i}",
                    "key_events": [f"事件{i}"],
                    "estimated_words": 2500,
                    "mood": "蓄力",
                    "chapter_brief": {},
                }
                for i in range(1, total_ch + 1)
            ],
        }
        mock_llm.chat.return_value = FakeLLMResponse(
            content=json.dumps(llm_response, ensure_ascii=False)
        )

        architect = ProjectArchitect(mock_llm)
        outline = architect._generate_outline(
            genre="玄幻",
            theme="少年冒险",
            target_words=50000,
            template_name="cyclic_upgrade",
        )

        # All 20 chapters should be present
        assert len(outline.chapters) == total_ch

    def test_first_volume_only_prompt_contains_instruction(self):
        """For long novels, prompt should include first_volume_only instruction."""
        from src.novel.agents.project_architect import ProjectArchitect

        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(
            content=json.dumps({
                "main_storyline": {},
                "acts": [{"name": "幕1", "description": "d", "start_chapter": 1, "end_chapter": 400}],
                "volumes": [{"volume_number": 1, "title": "V1", "core_conflict": "c", "resolution": "r", "chapters": list(range(1, 31))}],
                "chapters": [
                    {"chapter_number": i, "title": f"Ch{i}", "goal": f"G{i}", "key_events": [f"E{i}"],
                     "estimated_words": 2500, "mood": "蓄力", "chapter_brief": {}}
                    for i in range(1, 31)
                ],
            }, ensure_ascii=False)
        )

        architect = ProjectArchitect(mock_llm)
        architect._generate_outline(
            genre="玄幻",
            theme="测试",
            target_words=1000000,
            template_name="cyclic_upgrade",
        )

        # Check that the prompt sent to LLM contains the first_volume_only instruction
        call_args = mock_llm.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args[0][0] if call_args[0] else call_args.kwargs["messages"]
        user_msg = messages[-1]["content"]
        assert "超长篇模式" in user_msg
        assert "仅第1卷" in user_msg


# ---------------------------------------------------------------------------
# Test: generate_chapters with outline extension
# ---------------------------------------------------------------------------


class TestGenerateChaptersWithExtension:
    """Integration test: generate_chapters triggers _extend_outline."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("src.novel.pipeline.build_chapter_graph")
    @patch("src.llm.llm_client.create_llm_client")
    def test_generate_chapters_extends_outline_when_needed(
        self, mock_create_llm, mock_build_graph
    ):
        """generate_chapters should extend outline if end_chapter > outlined chapters."""
        from src.novel.pipeline import NovelPipeline

        # Setup: project with 30 chapters outlined
        outline = _make_long_outline_dict(30, 4)
        novel_id = "novel_test_ext"
        novel_dir = Path(self.tmpdir) / "novels" / novel_id
        novel_dir.mkdir(parents=True, exist_ok=True)
        (novel_dir / "chapters").mkdir(exist_ok=True)

        novel_data = {
            "novel_id": novel_id,
            "title": "Test",
            "genre": "玄幻",
            "theme": "测试",
            "target_words": 300000,
            "outline": outline,
            "characters": [],
            "world_setting": _make_world_setting_dict(),
            "status": "initialized",
            "current_chapter": 0,
        }
        with open(novel_dir / "novel.json", "w", encoding="utf-8") as f:
            json.dump(novel_data, f, ensure_ascii=False, indent=2)

        checkpoint = {
            "outline": outline,
            "config": {"llm": {}},
            "chapters": [],
        }
        with open(novel_dir / "checkpoint.json", "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)

        # Mock LLM for outline extension
        mock_llm = MagicMock()
        mock_llm.chat.return_value = FakeLLMResponse(
            content=_make_volume_outline_response(31, 60)
        )
        mock_create_llm.return_value = mock_llm

        # Mock chapter graph to simulate successful chapter generation
        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = lambda state: {
            **state,
            "current_chapter_text": f"第{state['current_chapter']}章正文内容",
        }
        mock_build_graph.return_value = mock_graph

        pipe = NovelPipeline(workspace=self.tmpdir)
        project_path = str(novel_dir)

        # Request chapters 31-35 which are beyond the current outline
        result = pipe.generate_chapters(
            project_path=project_path,
            start_chapter=31,
            end_chapter=35,
        )

        # Outline should have been extended
        ckpt_path = novel_dir / "checkpoint.json"
        with open(ckpt_path, encoding="utf-8") as f:
            saved_ckpt = json.load(f)
        assert len(saved_ckpt["outline"]["chapters"]) == 60

        # Chapters 31-35 should have been generated
        assert len(result["chapters_generated"]) == 5
