"""NarrativeDesigner 单元测试"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.ppt.models import NarrativeStructure, NarrativeSection, PageRole, Scenario
from src.ppt.narrative_designer import NarrativeDesigner


# ---------------------------------------------------------------------------
# Helper: 创建 NarrativeDesigner 实例，跳过真正的 LLM 创建
# ---------------------------------------------------------------------------


def _make_designer() -> NarrativeDesigner:
    """创建 NarrativeDesigner 并替换 _llm 为 MagicMock。"""
    with patch("src.ppt.narrative_designer.create_llm_client"):
        designer = NarrativeDesigner({"llm": {}})
    designer._llm = MagicMock()
    return designer


# ===========================================================================
# TestLoadScenarioTemplate
# ===========================================================================


class TestLoadScenarioTemplate:
    """场景模板加载测试"""

    def test_load_quarterly_review(self):
        """加载季度汇报模板"""
        designer = _make_designer()

        template = designer.load_scenario_template("quarterly_review")
        assert template["narrative_id"] == "quarterly_review"
        assert "structure" in template
        assert len(template["structure"]) >= 5

    def test_load_all_7_scenarios(self):
        """所有 7 个场景模板都能正常加载"""
        designer = _make_designer()

        for scenario in Scenario:
            template = designer.load_scenario_template(scenario.value)
            assert "narrative_id" in template
            assert "structure" in template

    def test_load_nonexistent_falls_back(self):
        """不存在的场景 fallback 到 quarterly_review"""
        designer = _make_designer()

        template = designer.load_scenario_template("nonexistent_scenario")
        assert template["narrative_id"] == "quarterly_review"

    def test_template_caching(self):
        """模板加载有缓存"""
        designer = _make_designer()

        t1 = designer.load_scenario_template("quarterly_review")
        t2 = designer.load_scenario_template("quarterly_review")
        assert t1 is t2  # 同一对象


# ===========================================================================
# TestListScenarios
# ===========================================================================


class TestListScenarios:
    def test_list_returns_7_scenarios(self):
        designer = _make_designer()

        scenarios = designer.list_scenarios()
        assert len(scenarios) == 7
        ids = {s["id"] for s in scenarios}
        assert "quarterly_review" in ids
        assert "pitch_deck" in ids

    def test_scenario_entries_have_required_keys(self):
        """每个场景条目包含 id / name / description"""
        designer = _make_designer()
        scenarios = designer.list_scenarios()
        for s in scenarios:
            assert "id" in s
            assert "name" in s
            assert "description" in s


# ===========================================================================
# TestDesign
# ===========================================================================


class TestDesign:
    def _mock_llm_response(self, sections):
        """构造 LLM 返回的 JSON"""
        return LLMResponse(
            content=json.dumps({"sections": sections}),
            model="test",
        )

    def test_design_with_llm_success(self):
        """LLM 成功生成叙事结构"""
        designer = _make_designer()
        designer._llm.chat.return_value = self._mock_llm_response([
            {"role": "cover", "title_hint": "Q1 汇报", "key_points_hint": []},
            {"role": "executive_summary", "title_hint": "核心亮点", "key_points_hint": ["GMV 增长 30%"]},
            {"role": "progress", "title_hint": "关键进展", "key_points_hint": ["完成3个项目"]},
            {"role": "data_evidence", "title_hint": "数据表现", "key_points_hint": ["用户增长50%"]},
            {"role": "closing", "title_hint": "谢谢", "key_points_hint": []},
        ])

        result = designer.design(
            topic="Q1 产品进展",
            audience="business",
            scenario="quarterly_review",
        )

        assert isinstance(result, NarrativeStructure)
        assert result.scenario == "quarterly_review"
        assert result.topic == "Q1 产品进展"
        assert len(result.sections) == 5
        assert result.sections[0].role == PageRole.COVER
        assert result.sections[-1].role == PageRole.CLOSING

    def test_design_llm_failure_uses_fallback(self):
        """LLM 失败时使用模板 fallback"""
        designer = _make_designer()
        designer._llm.chat.side_effect = Exception("LLM 超时")

        result = designer.design(
            topic="测试主题",
            scenario="quarterly_review",
        )

        assert isinstance(result, NarrativeStructure)
        assert len(result.sections) >= 3  # fallback 至少有 3 个 section

    def test_design_with_target_pages(self):
        """指定目标页数"""
        designer = _make_designer()
        designer._llm.chat.return_value = self._mock_llm_response([
            {"role": "cover", "title_hint": "封面"},
            {"role": "executive_summary", "title_hint": "概要"},
            {"role": "progress", "title_hint": "进展"},
            {"role": "data_evidence", "title_hint": "数据"},
            {"role": "closing", "title_hint": "结束"},
        ])

        result = designer.design(topic="测试", target_pages=8)
        assert isinstance(result, NarrativeStructure)

    def test_design_with_materials(self):
        """传入零散材料"""
        designer = _make_designer()
        designer._llm.chat.return_value = self._mock_llm_response([
            {"role": "cover", "title_hint": "封面"},
            {"role": "executive_summary", "title_hint": "概要"},
            {"role": "progress", "title_hint": "进展"},
            {"role": "data_evidence", "title_hint": "数据"},
            {"role": "closing", "title_hint": "结束"},
        ])

        materials = [{"type": "text", "content": "Q1 销售额 1000万"}]
        result = designer.design(topic="Q1汇报", materials=materials)

        # 验证 LLM 被调用时包含材料信息
        call_args = designer._llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]  # messages[1]["content"]
        assert "1000万" in user_msg

    def test_design_llm_returns_invalid_json(self):
        """LLM 返回无效 JSON 时 fallback"""
        designer = _make_designer()
        designer._llm.chat.return_value = LLMResponse(content="not json", model="test")

        result = designer.design(topic="测试")
        assert isinstance(result, NarrativeStructure)
        assert len(result.sections) >= 3

    def test_design_llm_returns_missing_sections_key(self):
        """LLM 返回 JSON 但缺少 sections 键 -> fallback"""
        designer = _make_designer()
        designer._llm.chat.return_value = LLMResponse(
            content=json.dumps({"pages": []}),
            model="test",
        )

        result = designer.design(topic="测试")
        assert isinstance(result, NarrativeStructure)
        assert len(result.sections) >= 3

    def test_design_default_scenario(self):
        """默认场景为 quarterly_review"""
        designer = _make_designer()
        designer._llm.chat.return_value = self._mock_llm_response([
            {"role": "cover", "title_hint": "封面"},
            {"role": "executive_summary", "title_hint": "概要"},
            {"role": "progress", "title_hint": "进展"},
            {"role": "data_evidence", "title_hint": "数据"},
            {"role": "closing", "title_hint": "结束"},
        ])

        result = designer.design(topic="测试")
        assert result.scenario == "quarterly_review"


# ===========================================================================
# TestParseEdgeCases
# ===========================================================================


class TestParseEdgeCases:
    def test_parse_sections_invalid_role(self):
        """无效 role 应 fallback 到 KNOWLEDGE_POINT"""
        designer = _make_designer()

        sections = designer._parse_sections([
            {"role": "invalid_role", "title_hint": "测试"},
            {"role": "cover", "title_hint": "封面"},
            {"role": "closing", "title_hint": "结束"},
        ])
        assert sections is not None
        # invalid role fallback 到 KNOWLEDGE_POINT
        assert sections[0].role == PageRole.KNOWLEDGE_POINT

    def test_parse_sections_too_few(self):
        """少于 3 个 section 返回 None"""
        designer = _make_designer()

        result = designer._parse_sections([
            {"role": "cover", "title_hint": "封面"},
        ])
        assert result is None

    def test_parse_sections_exactly_two(self):
        """恰好 2 个 section 返回 None"""
        designer = _make_designer()

        result = designer._parse_sections([
            {"role": "cover", "title_hint": "封面"},
            {"role": "closing", "title_hint": "结束"},
        ])
        assert result is None

    def test_parse_sections_empty_list(self):
        designer = _make_designer()
        assert designer._parse_sections([]) is None

    def test_parse_sections_none_input(self):
        """非 list 输入返回 None"""
        designer = _make_designer()
        assert designer._parse_sections(None) is None

    def test_parse_sections_non_dict_items_skipped(self):
        """非 dict 的项被跳过"""
        designer = _make_designer()
        result = designer._parse_sections([
            "not a dict",
            {"role": "cover", "title_hint": "封面"},
            42,
            {"role": "executive_summary", "title_hint": "概要"},
            {"role": "closing", "title_hint": "结束"},
        ])
        # 非 dict 被跳过，只剩 3 个有效项
        assert result is not None
        assert len(result) == 3

    def test_parse_sections_key_points_hint_normalization(self):
        """key_points_hint 中的空值被过滤"""
        designer = _make_designer()
        result = designer._parse_sections([
            {"role": "cover", "title_hint": "封面", "key_points_hint": ["有效", "", None, "另一个"]},
            {"role": "executive_summary", "title_hint": "概要"},
            {"role": "closing", "title_hint": "结束"},
        ])
        assert result is not None
        # None 和空字符串被过滤
        assert result[0].key_points_hint == ["有效", "另一个"]

    def test_parse_sections_key_points_hint_not_list(self):
        """key_points_hint 不是 list 时 fallback 为空列表"""
        designer = _make_designer()
        result = designer._parse_sections([
            {"role": "cover", "title_hint": "封面", "key_points_hint": "not a list"},
            {"role": "executive_summary", "title_hint": "概要"},
            {"role": "closing", "title_hint": "结束"},
        ])
        assert result is not None
        assert result[0].key_points_hint == []
