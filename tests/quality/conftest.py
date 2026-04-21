"""质量评估测试套件的共享 fixtures。

Phase 5 / E2 交付。所有 fixture 都是零 LLM / 零 IO，可重复安全。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.novel.models.style_profile import OverusedPhrase, StyleProfile


@pytest.fixture
def mock_ledger_store() -> MagicMock:
    """返回一个 MagicMock 版 LedgerStore，默认 snapshot_for_chapter 返空。

    测试可通过 ``mock_ledger_store.snapshot_for_chapter.return_value = {...}``
    覆写。
    """
    m = MagicMock()
    m.snapshot_for_chapter.return_value = {
        "pending_debts": [],
        "plantable_foreshadowings": [],
        "collectable_foreshadowings": [],
        "active_characters": [],
        "world_facts": [],
        "pending_milestones": [],
    }
    return m


@pytest.fixture
def sample_style_profile() -> StyleProfile:
    """构造一个含典型高频短语的 StyleProfile，供 D4 AI 味检测用。

    三条 overused_phrases 均 coverage=0.5 > 默认阈值 0.3；
    phrase 选取故意包含"夜幕降临"/"剑眉一挑"/"心头一震" 这类小说熟语。
    """
    return StyleProfile(
        novel_id="test_novel_001",
        overused_phrases=[
            OverusedPhrase(phrase="夜幕降临", chapter_coverage=0.5, total_occurrences=6),
            OverusedPhrase(phrase="剑眉一挑", chapter_coverage=0.5, total_occurrences=5),
            OverusedPhrase(phrase="心头一震", chapter_coverage=0.5, total_occurrences=4),
        ],
        avg_sentence_len=25.0,
        sentence_len_std=10.0,
        sample_size=10,
    )


@pytest.fixture
def human_style_text() -> str:
    """3 段贴近人类写作的小说文本（不含通用 AI 指示词 + 高频短语命中极少）。"""
    return (
        "清晨的风从窗缝里钻进来，带着一点沙尘和柴烟味。"
        "陆明靠在床沿上发了会儿呆，直到院子里传来母亲切菜的声音，他才起身。"
        "灶台边的铁锅早已烧开，蒸汽把窗纸熏得发黄。母亲回头看了他一眼，没多说什么。\n\n"
        "他蹲到井边舀水洗脸。水面照出一个还带着困意的少年，眼眶有些发青——昨夜翻来覆去到天亮。"
        "母亲端上一碗粟米粥，又摆了半块糙饼。他闷头吃，饼屑掉在衣襟上也没顾得上掸。\n\n"
        "吃到一半，他忽然放下筷子，望着堂屋那柄靠墙的旧剑出神。"
        "那是父亲留下的，剑鞘边缘磨得发亮。母亲看见了，手上的动作顿了顿，却依旧没开口。"
    )


@pytest.fixture
def ai_flavor_text() -> str:
    """明显 AI 味的文本：通用指示词堆叠 + profile 高频短语命中 + 句首重复。"""
    return (
        "夜幕降临，他不禁一惊。"
        "夜幕降临，他竟然还能这样。"
        "夜幕降临，他忍不住咽了口唾沫。"
        "与此同时，远处传来一声低吟。"
        "剑眉一挑，他不禁皱眉。"
        "剑眉一挑，他竟然毫不犹豫地出手。"
        "心头一震，他忍不住后退一步。"
        "心头一震，他不禁感到一阵寒意。"
    )


@pytest.fixture
def sample_chapter_text() -> str:
    """中等长度的通用章节文本（用于 D6/D7 规则测试）。"""
    return (
        "陆明推开门，院子里静得出奇。"
        "“师父？”他低声喊了一句，没有回应。"
        "他绕过石桌，走到后堂门口。"
        "“你来了。”一个声音从屋里传出，沙哑而缓慢。"
        "陆明推门进去，看见师父背对着他，盘膝坐在蒲团上。"
        "“我想问您一件事。”他说。"
        "师父沉默了很久，才缓缓开口：“问吧。”"
    )
