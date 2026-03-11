"""WorldBuilder Agent 单元测试

覆盖：
- WorldService: 世界观生成、力量体系生成、错误处理
- WorldSettingTool: 薄包装正确委托
- WorldBuilder: 完整世界观创建、一致性验证
- world_builder_node: 状态更新、resume 模式、LLM 故障
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.novel.agents.world_builder import (
    WorldBuilder,
    _make_decision,
    world_builder_node,
)
from src.novel.models.world import PowerSystem, WorldSetting
from src.novel.services.world_service import WorldService
from src.novel.tools.world_setting_tool import WorldSettingTool


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake-model"
    usage: dict | None = None


def _make_world_json() -> dict:
    """返回一份合法的世界观 JSON。"""
    return {
        "era": "架空古代修仙世界",
        "location": "九州大陆，山川河流纵横",
        "terms": {
            "九霄门": "主角所属门派",
            "灵石": "修炼货币",
            "天道": "世界最高法则",
        },
        "rules": [
            "修炼需要灵气",
            "凡人不能飞行",
            "杀人者必受天罚",
        ],
    }


def _make_power_system_json(levels: int = 10) -> dict:
    """返回一份合法的力量体系 JSON。"""
    level_list = []
    names = [
        "炼气期", "筑基期", "结丹期", "元婴期", "化神期",
        "合体期", "大乘期", "渡劫期", "地仙", "天仙",
    ]
    for i in range(1, min(levels + 1, len(names) + 1)):
        level_list.append(
            {
                "rank": i,
                "name": names[i - 1],
                "description": f"修仙第{i}层境界",
                "typical_abilities": [f"能力{i}A", f"能力{i}B"],
            }
        )
    return {"name": "修炼境界", "levels": level_list}


def _make_llm_client(
    response_json: dict | None = None, error: Exception | None = None
) -> MagicMock:
    """创建一个 Mock LLM 客户端。"""
    client = MagicMock()
    if error:
        client.chat.side_effect = error
    elif response_json is not None:
        client.chat.return_value = FakeLLMResponse(
            content=json.dumps(response_json, ensure_ascii=False)
        )
    else:
        client.chat.return_value = FakeLLMResponse(content="{}")
    return client


def _make_outline() -> dict:
    """返回一份简单的大纲 dict。"""
    return {
        "template": "cyclic_upgrade",
        "acts": [
            {
                "name": "第一幕：入门",
                "description": "主角加入九霄门",
                "start_chapter": 1,
                "end_chapter": 5,
            }
        ],
        "volumes": [
            {
                "volume_number": 1,
                "title": "第一卷：初入修仙界",
                "core_conflict": "争夺灵石矿脉",
                "resolution": "主角获得灵石矿脉",
                "chapters": [1, 2, 3, 4, 5],
            }
        ],
        "chapters": [],
    }


# ---------------------------------------------------------------------------
# WorldService 测试
# ---------------------------------------------------------------------------


class TestWorldService:
    def test_create_world_setting_valid(self):
        """正常 LLM 返回生成有效 WorldSetting。"""
        client = _make_llm_client(response_json=_make_world_json())
        service = WorldService(client)

        result = service.create_world_setting("玄幻", "修仙冒险")

        assert isinstance(result, WorldSetting)
        assert result.era == "架空古代修仙世界"
        assert result.location == "九州大陆，山川河流纵横"
        assert len(result.terms) == 3
        assert len(result.rules) == 3
        assert "九霄门" in result.terms

    def test_create_world_setting_missing_fields_use_defaults(self):
        """LLM 返回缺少字段时使用默认值。"""
        client = _make_llm_client(response_json={})
        service = WorldService(client)

        result = service.create_world_setting("都市", "商战")

        assert isinstance(result, WorldSetting)
        assert result.era == "架空世界"
        assert result.location == "未知之地"
        assert result.terms == {}
        assert result.rules == []

    def test_create_world_setting_retries_on_garbage(self):
        """LLM 第一次返回垃圾，第二次返回有效数据。"""
        client = MagicMock()
        client.chat.side_effect = [
            FakeLLMResponse(content="not json at all"),
            FakeLLMResponse(
                content=json.dumps(_make_world_json(), ensure_ascii=False)
            ),
        ]
        service = WorldService(client)

        result = service.create_world_setting("玄幻", "修仙")

        assert isinstance(result, WorldSetting)
        assert client.chat.call_count == 2

    def test_create_world_setting_raises_after_max_retries(self):
        """LLM 一直返回垃圾，抛出 RuntimeError。"""
        client = MagicMock()
        client.chat.return_value = FakeLLMResponse(content="garbage")
        service = WorldService(client)

        with pytest.raises(RuntimeError, match="世界观生成失败"):
            service.create_world_setting("玄幻", "修仙")

        assert client.chat.call_count == WorldService.MAX_RETRIES

    def test_create_world_setting_llm_exception(self):
        """LLM 调用抛出异常，重试后失败。"""
        client = _make_llm_client(error=ConnectionError("network down"))
        service = WorldService(client)

        with pytest.raises(RuntimeError, match="世界观生成失败"):
            service.create_world_setting("玄幻", "修仙")

    def test_define_power_system_xuanhuan(self):
        """玄幻题材生成力量体系。"""
        client = _make_llm_client(response_json=_make_power_system_json())
        service = WorldService(client)

        result = service.define_power_system("玄幻", "架空修仙世界")

        assert isinstance(result, PowerSystem)
        assert result.name == "修炼境界"
        assert len(result.levels) == 10
        assert result.levels[0].rank == 1
        assert result.levels[0].name == "炼气期"

    def test_define_power_system_modern_returns_none(self):
        """都市题材返回 None。"""
        client = _make_llm_client()
        service = WorldService(client)

        result = service.define_power_system("都市", "现代都市")

        assert result is None
        client.chat.assert_not_called()

    def test_define_power_system_romance_returns_none(self):
        """言情题材返回 None。"""
        client = _make_llm_client()
        service = WorldService(client)

        result = service.define_power_system("言情", "校园背景")

        assert result is None

    def test_define_power_system_empty_levels_fallback(self):
        """LLM 返回空 levels，创建默认层级。"""
        client = _make_llm_client(response_json={"name": "武学境界", "levels": []})
        service = WorldService(client)

        result = service.define_power_system("武侠", "江湖世界")

        assert isinstance(result, PowerSystem)
        assert len(result.levels) >= 1

    def test_define_power_system_retries_on_failure(self):
        """力量体系生成重试。"""
        client = MagicMock()
        client.chat.return_value = FakeLLMResponse(content="not json")
        service = WorldService(client)

        with pytest.raises(RuntimeError, match="力量体系生成失败"):
            service.define_power_system("玄幻", "修仙世界")


# ---------------------------------------------------------------------------
# WorldSettingTool 测试
# ---------------------------------------------------------------------------


class TestWorldSettingTool:
    def test_generate_delegates_to_service(self):
        """generate 正确委托给 WorldService。"""
        client = _make_llm_client(response_json=_make_world_json())
        tool = WorldSettingTool(client)

        result = tool.generate("玄幻", "修仙冒险")

        assert isinstance(result, WorldSetting)
        assert result.era == "架空古代修仙世界"

    def test_generate_power_system_delegates(self):
        """generate_power_system 正确委托给 WorldService。"""
        client = _make_llm_client(response_json=_make_power_system_json(5))
        tool = WorldSettingTool(client)

        result = tool.generate_power_system("玄幻", "修仙世界")

        assert isinstance(result, PowerSystem)
        assert len(result.levels) == 5


# ---------------------------------------------------------------------------
# WorldBuilder Agent 测试
# ---------------------------------------------------------------------------


class TestWorldBuilder:
    def test_create_world_complete(self):
        """创建完整世界观（含力量体系）。"""
        world_json = _make_world_json()
        power_json = _make_power_system_json()
        client = MagicMock()
        client.chat.side_effect = [
            FakeLLMResponse(content=json.dumps(world_json, ensure_ascii=False)),
            FakeLLMResponse(content=json.dumps(power_json, ensure_ascii=False)),
        ]
        builder = WorldBuilder(client)

        result = builder.create_world("玄幻", _make_outline())

        assert isinstance(result, WorldSetting)
        assert result.power_system is not None
        assert result.power_system.name == "修炼境界"

    def test_create_world_no_power_system_for_modern(self):
        """都市题材不生成力量体系。"""
        world_json = _make_world_json()
        world_json["era"] = "现代都市"
        client = _make_llm_client(response_json=world_json)
        builder = WorldBuilder(client)

        result = builder.create_world("都市", _make_outline())

        assert isinstance(result, WorldSetting)
        assert result.power_system is None

    def test_validate_consistency_clean_text(self):
        """无违规文本通过验证。"""
        client = _make_llm_client()
        builder = WorldBuilder(client)
        world = WorldSetting(
            era="修仙世界",
            location="九州大陆",
            rules=["凡人不能飞行", "修炼需要灵气"],
        )

        is_ok, violations = builder.validate_consistency(
            "主角在山中修炼，感受天地灵气。", world
        )

        assert is_ok is True
        assert violations == []

    def test_validate_consistency_detects_violation(self):
        """检测到违反世界规则。"""
        client = _make_llm_client()
        builder = WorldBuilder(client)
        world = WorldSetting(
            era="修仙世界",
            location="九州大陆",
            rules=["凡人不能飞行"],
        )

        is_ok, violations = builder.validate_consistency(
            "凡人张三飞行到了天空之上。", world
        )

        assert is_ok is False
        assert len(violations) >= 1
        assert "飞行" in violations[0]

    def test_validate_consistency_empty_text(self):
        """空文本通过验证。"""
        client = _make_llm_client()
        builder = WorldBuilder(client)
        world = WorldSetting(era="x", location="y", rules=["不能飞行"])

        is_ok, violations = builder.validate_consistency("", world)

        assert is_ok is True
        assert violations == []

    def test_validate_consistency_no_rules(self):
        """无规则时通过验证。"""
        client = _make_llm_client()
        builder = WorldBuilder(client)
        world = WorldSetting(era="x", location="y", rules=[])

        is_ok, violations = builder.validate_consistency(
            "任何内容都可以。", world
        )

        assert is_ok is True

    def test_extract_outline_summary(self):
        """大纲摘要提取。"""
        client = _make_llm_client()
        builder = WorldBuilder(client)
        outline = _make_outline()

        summary = builder._extract_outline_summary(outline)

        assert "入门" in summary
        assert "九霄门" in summary

    def test_extract_outline_summary_empty(self):
        """空大纲返回默认摘要。"""
        client = _make_llm_client()
        builder = WorldBuilder(client)

        summary = builder._extract_outline_summary({})

        assert summary == "暂无大纲摘要"


# ---------------------------------------------------------------------------
# world_builder_node 测试
# ---------------------------------------------------------------------------


class TestWorldBuilderNode:
    def test_generates_world_for_new_project(self):
        """新项目生成世界观。"""
        world_json = _make_world_json()
        mock_client = MagicMock()
        mock_client.chat.return_value = FakeLLMResponse(
            content=json.dumps(world_json, ensure_ascii=False)
        )

        state = {
            "genre": "都市",
            "outline": _make_outline(),
            "config": {},
        }

        with patch(
            "src.novel.agents.world_builder.create_llm_client",
            return_value=mock_client,
        ):
            result = world_builder_node(state)

        assert result["world_setting"] is not None
        assert "world_builder" in result["completed_nodes"]
        assert len(result["decisions"]) >= 1

    def test_skips_when_world_exists(self):
        """已有世界观时跳过。"""
        state = {
            "genre": "玄幻",
            "world_setting": {"era": "already exists", "location": "somewhere"},
            "config": {},
        }

        result = world_builder_node(state)

        assert "world_builder" in result["completed_nodes"]
        assert result.get("world_setting") is None  # 不覆盖
        assert any("跳过" in d["decision"] for d in result["decisions"])

    def test_llm_init_failure(self):
        """LLM 初始化失败。"""
        state = {"genre": "玄幻", "outline": {}, "config": {}}

        with patch(
            "src.novel.agents.world_builder.create_llm_client",
            side_effect=RuntimeError("No LLM available"),
        ):
            result = world_builder_node(state)

        assert len(result["errors"]) >= 1
        assert "LLM 初始化失败" in result["errors"][0]["message"]

    def test_world_generation_failure(self):
        """世界观生成失败时返回错误。"""
        mock_client = MagicMock()
        mock_client.chat.return_value = FakeLLMResponse(content="not json")

        state = {"genre": "玄幻", "outline": {}, "config": {}}

        with patch(
            "src.novel.agents.world_builder.create_llm_client",
            return_value=mock_client,
        ):
            result = world_builder_node(state)

        assert len(result["errors"]) >= 1
        assert "世界观生成失败" in result["errors"][-1]["message"]
        assert "world_builder" in result["completed_nodes"]

    def test_default_genre_when_missing(self):
        """state 缺少 genre 时使用默认值。"""
        world_json = _make_world_json()
        mock_client = MagicMock()
        mock_client.chat.return_value = FakeLLMResponse(
            content=json.dumps(world_json, ensure_ascii=False)
        )

        state = {"outline": {}, "config": {}}

        with patch(
            "src.novel.agents.world_builder.create_llm_client",
            return_value=mock_client,
        ):
            result = world_builder_node(state)

        assert result["world_setting"] is not None


class TestMakeDecision:
    def test_creates_decision(self):
        d = _make_decision(step="test", decision="do it", reason="why not")
        assert d["agent"] == "WorldBuilder"
        assert d["step"] == "test"
        assert "timestamp" in d
