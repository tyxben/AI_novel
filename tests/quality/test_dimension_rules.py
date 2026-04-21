"""Phase 5 / E2 — 纯规则维度单元测试。

覆盖 D3 伏笔兑现率 / D4 AI 味指数 / D6 对话规则 / D7 章节勾连规则四个函数，
禁止乐观测试：每条断言都指向具体字段/数值。
"""

from __future__ import annotations

import pytest

from src.novel.quality.dimensions import (
    evaluate_ai_flavor,
    evaluate_chapter_hook_rules,
    evaluate_dialogue_quality_rules,
    evaluate_foreshadow_payoff,
)
from src.novel.quality.report import DimensionScore

pytestmark = pytest.mark.quality


# ---------------------------------------------------------------------------
# D3 伏笔兑现率
# ---------------------------------------------------------------------------


class TestForeshadowPayoff:
    def test_all_collected_returns_100(self, mock_ledger_store):
        """三条伏笔 detail 全部在已写文本中出现 → 100%。"""
        mock_ledger_store.snapshot_for_chapter.return_value = {
            "collectable_foreshadowings": [
                {"detail": "神秘令牌会在关键时刻亮起", "target_chapter": 3},
                {"detail": "老者留下一封密信", "target_chapter": 4},
                {"detail": "地下密室藏有古籍", "target_chapter": 5},
            ],
        }
        chapters_text = {
            3: "在最紧要处，神秘令牌会在关键时刻亮起，救了他一命。",
            4: "他拆开那封老者留下一封密信。",
            5: "他终于进入地下密室藏有古籍的深处。",
        }
        result = evaluate_foreshadow_payoff(
            mock_ledger_store, chapter_number=5, chapters_text=chapters_text
        )
        assert isinstance(result, DimensionScore)
        assert result.key == "foreshadow_payoff"
        assert result.scale == "percent"
        assert result.method == "rule"
        assert result.score == 100.0
        assert result.details["collected"] == 3
        assert result.details["total"] == 3
        assert result.details["missed"] == []

    def test_partial_collected_3_of_5(self, mock_ledger_store):
        """5 条伏笔只有 3 条出现 → 60%。"""
        mock_ledger_store.snapshot_for_chapter.return_value = {
            "collectable_foreshadowings": [
                {"detail": "神秘令牌会在关键时刻亮起", "target_chapter": 3},
                {"detail": "老者留下一封密信", "target_chapter": 4},
                {"detail": "地下密室藏有古籍", "target_chapter": 5},
                {"detail": "红衣女子的身份之谜", "target_chapter": 5},
                {"detail": "第七座高塔的传说", "target_chapter": 5},
            ],
        }
        chapters_text = {
            3: "神秘令牌会在关键时刻亮起，救了他一命。",
            4: "老者留下一封密信，他拆开一看。",
            5: "他来到地下密室藏有古籍的门口。",
        }
        result = evaluate_foreshadow_payoff(
            mock_ledger_store, chapter_number=5, chapters_text=chapters_text
        )
        assert result.score == 60.0
        assert result.details["collected"] == 3
        assert result.details["total"] == 5
        assert len(result.details["missed"]) == 2
        missed_keywords = {item["keyword"] for item in result.details["missed"]}
        assert "红衣女子的身份之谜" in missed_keywords
        assert "第七座高塔的传说" in missed_keywords

    def test_no_due_foreshadowings_returns_100(self, mock_ledger_store):
        """无到期伏笔 → 100%（0/0 防除零）。"""
        mock_ledger_store.snapshot_for_chapter.return_value = {
            "collectable_foreshadowings": [],
        }
        result = evaluate_foreshadow_payoff(
            mock_ledger_store, chapter_number=1, chapters_text={1: "开篇第一章。"}
        )
        assert result.score == 100.0
        assert result.details["collected"] == 0
        assert result.details["total"] == 0

    def test_empty_snapshot_returns_100(self, mock_ledger_store):
        """snapshot 返回空 dict → 100%。"""
        mock_ledger_store.snapshot_for_chapter.return_value = {}
        result = evaluate_foreshadow_payoff(
            mock_ledger_store, chapter_number=1, chapters_text={}
        )
        assert result.score == 100.0
        assert result.details["total"] == 0

    def test_ledger_exception_returns_100(self, mock_ledger_store):
        """ledger 抛异常 → 兜底 100%（不崩）。"""
        mock_ledger_store.snapshot_for_chapter.side_effect = RuntimeError("db broken")
        result = evaluate_foreshadow_payoff(
            mock_ledger_store, chapter_number=1, chapters_text={1: "abc"}
        )
        assert result.score == 100.0
        assert result.details["total"] == 0
        assert result.scale == "percent"

    def test_uses_description_fallback(self, mock_ledger_store):
        """detail 缺失时退化到 description / title。"""
        mock_ledger_store.snapshot_for_chapter.return_value = {
            "collectable_foreshadowings": [
                {"description": "银色面具的秘密", "target_chapter": 2},
                {"title": "森林深处的守墓人", "target_chapter": 2},
                {"detail": "", "description": "", "title": ""},  # 空 → 跳过
            ],
        }
        chapters_text = {2: "银色面具的秘密浮现，森林深处的守墓人出现。"}
        result = evaluate_foreshadow_payoff(
            mock_ledger_store, chapter_number=2, chapters_text=chapters_text
        )
        # 只 2 条有效，全兑现
        assert result.details["total"] == 2
        assert result.details["collected"] == 2
        assert result.score == 100.0

    def test_keyword_truncated_to_12_chars(self, mock_ledger_store):
        """detail > 12 字，关键词取前 12 字。兑现判断用该前缀。"""
        long_detail = "藏在北海冰原下的远古神兵将会重现人间发出剑鸣"
        mock_ledger_store.snapshot_for_chapter.return_value = {
            "collectable_foreshadowings": [
                {"detail": long_detail, "target_chapter": 3},
            ],
        }
        # 本章文本只包含前 12 字 → 应判定兑现
        chapters_text = {3: "果然，藏在北海冰原下的远古神兵重新出世。"}
        result = evaluate_foreshadow_payoff(
            mock_ledger_store, chapter_number=3, chapters_text=chapters_text
        )
        assert result.details["collected"] == 1
        assert result.score == 100.0


# ---------------------------------------------------------------------------
# D4 AI 味指数
# ---------------------------------------------------------------------------


class TestAiFlavorIndex:
    def test_heavy_ai_text_scores_high(self, sample_style_profile, ai_flavor_text):
        """堆叠通用指示词 + 高频短语 + 句首重复 → score >= 70。"""
        result = evaluate_ai_flavor(ai_flavor_text, sample_style_profile, genre="武侠")
        assert isinstance(result, DimensionScore)
        assert result.key == "ai_flavor_index"
        assert result.scale == "0-100"
        assert result.method == "rule"
        assert result.score >= 70.0, (
            f"AI 味文本打分 {result.score} 低于预期 70，components={result.details['components']}"
        )
        # 三个来源都应非零
        components = result.details["components"]
        assert components["overuse"] > 0
        assert components["cliche"] > 0
        assert components["repetition"] > 0
        # hits 含我们塞的三条高频短语
        assert "夜幕降临" in result.details["overuse_hits"]
        assert "剑眉一挑" in result.details["overuse_hits"]
        assert "心头一震" in result.details["overuse_hits"]

    def test_human_style_text_scores_low(self, sample_style_profile, human_style_text):
        """人类风格文本 → score <= 30。"""
        result = evaluate_ai_flavor(
            human_style_text, sample_style_profile, genre="现实"
        )
        assert result.score <= 30.0, (
            f"人类文本打分 {result.score} 高于预期 30，components={result.details['components']}"
        )
        # 通用指示词应几乎未命中
        assert result.details["cliche_count"] == 0

    def test_empty_text_returns_zero(self, sample_style_profile):
        """空文本 → score=0，所有组件为 0。"""
        result = evaluate_ai_flavor("", sample_style_profile)
        assert result.score == 0.0
        assert result.details["cliche_count"] == 0
        assert result.details["overuse_hits"] == []
        assert result.details["repetition_rate"] == 0.0

    def test_whitespace_only_text_returns_zero(self, sample_style_profile):
        """纯空白 → score=0。"""
        result = evaluate_ai_flavor("   \n\n\t  ", sample_style_profile)
        assert result.score == 0.0

    def test_missing_style_profile_still_works(self):
        """无 style_profile 时仅规则层打分，不崩。"""
        text = "他不禁一惊，竟然还能这样。他忍不住咽了口唾沫。" * 3
        result = evaluate_ai_flavor(text, None, genre="玄幻")
        assert isinstance(result, DimensionScore)
        # overuse 必为 0（没 profile）
        assert result.details["components"]["overuse"] == 0.0
        assert result.details["overuse_hits"] == []
        # cliche 非 0
        assert result.details["cliche_count"] > 0
        # 整体 score 仍可打出
        assert 0 < result.score <= 100

    def test_genre_recorded_in_details(self, sample_style_profile):
        """genre 参数应被记录到 details 以便调试。"""
        result = evaluate_ai_flavor("随便一段", sample_style_profile, genre="科幻")
        assert result.details["genre"] == "科幻"

    def test_score_capped_at_100(self, sample_style_profile):
        """极端文本也不该超过 100。"""
        # 每千字 1000 个指示词 → 应被封顶
        text = "不禁" * 1000
        result = evaluate_ai_flavor(text, sample_style_profile)
        assert result.score <= 100.0


# ---------------------------------------------------------------------------
# D6 对话自然度（规则层）
# ---------------------------------------------------------------------------


class TestDialogueQualityRules:
    def test_mixed_chinese_english_quotes(self):
        """混合中英文引号都应计入对话占比。"""
        text = (
            "他说：“你来了。”"
            "She replied: \"I missed you.\""
            "他又说：「下次再聊」。"
        )
        result = evaluate_dialogue_quality_rules(text)
        assert result["line_count"] == 3
        assert result["dialogue_ratio"] > 0
        assert result["max_single_line"] < 50
        assert result["warnings"] == []

    def test_long_dialogue_triggers_warning(self):
        """单条超过 200 字 → warning。"""
        long_line = "这是一段非常长的独白内容" * 30  # 约 330 字
        text = f"他开始讲述：“{long_line}”他停了下来。"
        result = evaluate_dialogue_quality_rules(text)
        assert result["max_single_line"] > 200
        assert len(result["warnings"]) == 1
        assert "dialogue_too_long" in result["warnings"][0]

    def test_empty_text_returns_zero_fields(self):
        """空文本 → 所有字段为 0，无 warning。"""
        result = evaluate_dialogue_quality_rules("")
        assert result["dialogue_ratio"] == 0.0
        assert result["max_single_line"] == 0
        assert result["line_count"] == 0
        assert result["warnings"] == []

    def test_no_dialogue_returns_zero_ratio(self):
        """全是叙述无对话 → dialogue_ratio=0。"""
        text = "清晨的风吹进院子。他站起身，揉了揉太阳穴，朝井边走去。"
        result = evaluate_dialogue_quality_rules(text)
        assert result["dialogue_ratio"] == 0.0
        assert result["line_count"] == 0
        assert result["max_single_line"] == 0

    def test_dialogue_ratio_calculation(self):
        """验证 dialogue_ratio 分子是"引号内字符数"，分母是全文长度。"""
        text = "他说：“你好”。"  # 引号内 2 字
        result = evaluate_dialogue_quality_rules(text)
        assert result["line_count"] == 1
        # 2 / 8 = 0.25
        assert abs(result["dialogue_ratio"] - (2 / len(text))) < 1e-4

    def test_unclosed_quote_is_skipped(self):
        """未闭合引号不应抛异常也不应产生虚假 line。"""
        text = "他喊道：“你怎么还不来"  # 缺闭合
        result = evaluate_dialogue_quality_rules(text)
        assert result["line_count"] == 0
        assert result["dialogue_ratio"] == 0.0


# ---------------------------------------------------------------------------
# D7 章节勾连（规则层）
# ---------------------------------------------------------------------------


class TestChapterHookRules:
    def test_opening_match_high_when_tail_keywords_appear(self):
        """上章末尾关键词在本章开头出现 → opening_match_rate > 0."""
        previous_tail = (
            "陆明握紧剑柄，心中暗暗发誓：定要查清真相。"
            "他推开房门，走向深夜的长街。"
        )
        current_text = (
            "陆明站在长街上，心中暗暗发誓：今夜必须查清真相。"
            "他握紧剑柄，深吸一口气。"
        ) + "无关段落。" * 50
        result = evaluate_chapter_hook_rules(current_text, previous_tail)
        # 多个 bigram 如"陆明"/"剑柄"/"长街"/"暗暗"/"发誓" 命中
        assert result["opening_match_rate"] > 0.1
        assert "opening_mismatch" not in str(result["warnings"])

    def test_opening_mismatch_adds_warning(self):
        """上章末尾关键词几乎不命中 → 加 warning。"""
        previous_tail = "陆明握紧剑柄，心中暗暗发誓：定要查清真相。"
        current_text = "春日里百花齐放，孩童在田埂嬉戏。" * 30
        result = evaluate_chapter_hook_rules(current_text, previous_tail)
        assert result["opening_match_rate"] < 0.1
        assert any("opening_mismatch" in w for w in result["warnings"])

    def test_question_mark_ending_is_hook(self):
        """以疑问句结尾 → ending_has_hook=True。"""
        current_text = "他走上山顶，眺望远方。" * 20 + "难道这就是命运的安排？"
        result = evaluate_chapter_hook_rules(current_text, "")
        assert result["ending_has_hook"] is True
        assert result["ending_indicator"] == "疑问句"

    def test_ellipsis_ending_is_hook(self):
        """以省略号结尾 → ending_has_hook=True。"""
        current_text = "他点了点头，陷入沉思……"
        result = evaluate_chapter_hook_rules(current_text, "")
        assert result["ending_has_hook"] is True
        assert result["ending_indicator"] == "省略号"

    def test_transition_word_ending_is_hook(self):
        """末句以转折词开头 → ending_has_hook=True。"""
        current_text = (
            "他平静地喝了口茶。" * 10
            + "但是，门外突然传来一声惨叫。"
        )
        result = evaluate_chapter_hook_rules(current_text, "")
        assert result["ending_has_hook"] is True
        assert result["ending_indicator"] == "转折词"

    def test_flat_ending_no_hook(self):
        """平铺直叙结尾 → ending_has_hook=False + warning。"""
        current_text = "他走进房间，坐到桌前开始喝茶。他慢慢地喝着，什么也没说。"
        result = evaluate_chapter_hook_rules(current_text, "")
        assert result["ending_has_hook"] is False
        assert result["ending_indicator"] == ""
        assert any("ending_flat" in w for w in result["warnings"])

    def test_empty_current_text_returns_warning(self):
        """空本章 → warning + 所有字段为初值。"""
        result = evaluate_chapter_hook_rules("", "上章结尾")
        assert result["ending_has_hook"] is False
        assert result["opening_match_rate"] == 0.0
        assert "empty_chapter_text" in result["warnings"]

    def test_empty_previous_tail_gives_full_match(self):
        """第一章（无 previous_tail）→ opening_match_rate=1.0（不扣分）。"""
        current_text = "楔子：一切都从这里开始。" * 10 + "他缓缓抬起头。"
        result = evaluate_chapter_hook_rules(current_text, "")
        assert result["opening_match_rate"] == 1.0
