"""CharacterDesigner Agent 单元测试

覆盖：
- CharacterService: 角色提取、档案生成、错误处理
- CharacterTool: 薄包装正确委托
- CharacterDesigner: 完整角色创建、OOC 验证
- character_designer_node: 状态更新、resume 模式、LLM 故障
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.novel.agents.character_designer import (
    CharacterDesigner,
    _make_decision,
    character_designer_node,
)
from src.novel.models.character import (
    Appearance,
    CharacterArc,
    CharacterProfile,
    Personality,
    TurningPoint,
)
from src.novel.services.character_service import CharacterService
from src.novel.tools.character_tool import CharacterTool


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake-model"
    usage: dict | None = None


def _make_characters_json() -> dict:
    """返回一份合法的角色列表 JSON。"""
    return {
        "characters": [
            {"name": "林风", "role": "主角"},
            {"name": "苏瑶", "role": "爱情线"},
            {"name": "陈魔", "role": "反派"},
        ]
    }


def _make_profile_json(name: str = "林风") -> dict:
    """返回一份合法的角色档案 JSON。"""
    return {
        "name": name,
        "alias": ["疯子林"],
        "gender": "男",
        "age": 22,
        "occupation": "散修",
        "appearance": {
            "height": "180cm",
            "build": "修长",
            "hair": "黑色长发",
            "eyes": "深邃黑瞳",
            "clothing_style": "青色长袍",
            "distinctive_features": ["左眉一道疤"],
        },
        "personality": {
            "traits": ["坚毅", "沉稳", "聪慧", "重情义"],
            "core_belief": "守护身边的人",
            "motivation": "为师门报仇",
            "flaw": "过于信任他人",
            "speech_style": "冷淡简短",
            "catchphrases": ["哼", "无聊"],
        },
        "character_arc": {
            "initial_state": "懦弱自卑",
            "turning_points": [
                {"chapter": 5, "event": "师门被灭", "change": "决心复仇"},
                {"chapter": 15, "event": "突破结丹", "change": "自信增强"},
            ],
            "final_state": "自信坚毅",
        },
    }


def _make_llm_client(
    response_json: dict | list | None = None, error: Exception | None = None
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
                "description": "主角林风加入九霄门修炼",
                "start_chapter": 1,
                "end_chapter": 5,
            }
        ],
        "volumes": [
            {
                "volume_number": 1,
                "title": "第一卷：初入修仙界",
                "core_conflict": "争夺灵石矿脉",
                "resolution": "林风获得灵石",
                "chapters": [1, 2, 3, 4, 5],
            }
        ],
        "chapters": [],
    }


def _make_character_profile(
    name: str = "林风", speech_style: str = "冷淡简短"
) -> CharacterProfile:
    """创建一个测试用 CharacterProfile。"""
    return CharacterProfile(
        name=name,
        gender="男",
        age=22,
        occupation="散修",
        appearance=Appearance(
            height="180cm",
            build="修长",
            hair="黑色长发",
            eyes="深邃黑瞳",
            clothing_style="青色长袍",
        ),
        personality=Personality(
            traits=["坚毅", "沉稳", "聪慧"],
            core_belief="守护",
            motivation="复仇",
            flaw="信任",
            speech_style=speech_style,
            catchphrases=["哼"],
        ),
    )


# ---------------------------------------------------------------------------
# CharacterService 测试
# ---------------------------------------------------------------------------


class TestCharacterService:
    def test_extract_characters_valid(self):
        """正常 LLM 返回提取角色列表。"""
        client = _make_llm_client(response_json=_make_characters_json())
        service = CharacterService(client)

        result = service.extract_characters("修仙冒险大纲", "玄幻")

        assert len(result) == 3
        assert result[0]["name"] == "林风"
        assert result[0]["role"] == "主角"
        assert result[1]["name"] == "苏瑶"

    def test_extract_characters_array_format(self):
        """LLM 直接返回数组格式。"""
        raw_array = [
            {"name": "张三", "role": "主角"},
            {"name": "李四", "role": "反派"},
        ]
        client = MagicMock()
        client.chat.return_value = FakeLLMResponse(
            content=json.dumps(raw_array, ensure_ascii=False)
        )
        service = CharacterService(client)

        result = service.extract_characters("大纲摘要", "都市")

        assert len(result) == 2

    def test_extract_characters_missing_role_defaults(self):
        """角色缺少 role 字段时默认为配角。"""
        client = _make_llm_client(
            response_json={"characters": [{"name": "王五"}]}
        )
        service = CharacterService(client)

        result = service.extract_characters("大纲", "玄幻")

        assert len(result) == 1
        assert result[0]["role"] == "配角"

    def test_extract_characters_retries_on_garbage(self):
        """LLM 返回垃圾后重试。"""
        client = MagicMock()
        client.chat.side_effect = [
            FakeLLMResponse(content="not json"),
            FakeLLMResponse(
                content=json.dumps(_make_characters_json(), ensure_ascii=False)
            ),
        ]
        service = CharacterService(client)

        result = service.extract_characters("大纲", "玄幻")

        assert len(result) == 3
        assert client.chat.call_count == 2

    def test_extract_characters_raises_after_max_retries(self):
        """LLM 一直返回垃圾，抛出 RuntimeError。"""
        client = MagicMock()
        client.chat.return_value = FakeLLMResponse(content="garbage")
        service = CharacterService(client)

        with pytest.raises(RuntimeError, match="角色提取失败"):
            service.extract_characters("大纲", "玄幻")

    def test_extract_characters_llm_exception(self):
        """LLM 调用异常。"""
        client = _make_llm_client(error=ConnectionError("timeout"))
        service = CharacterService(client)

        with pytest.raises(RuntimeError, match="角色提取失败"):
            service.extract_characters("大纲", "玄幻")

    def test_generate_profile_valid(self):
        """生成有效角色档案。"""
        client = _make_llm_client(response_json=_make_profile_json())
        service = CharacterService(client)

        result = service.generate_profile("林风", "主角", "玄幻", "修仙大纲")

        assert isinstance(result, CharacterProfile)
        assert result.name == "林风"
        assert result.gender == "男"
        assert result.age == 22
        assert len(result.personality.traits) >= 3
        assert result.personality.speech_style == "冷淡简短"
        assert result.character_arc is not None
        assert result.character_arc.initial_state == "懦弱自卑"

    def test_generate_profile_missing_fields_use_defaults(self):
        """LLM 返回缺少字段时使用默认值。"""
        client = _make_llm_client(response_json={"name": "张三"})
        service = CharacterService(client)

        result = service.generate_profile("张三", "主角", "都市", "都市大纲")

        assert isinstance(result, CharacterProfile)
        assert result.name == "张三"
        assert result.gender == "男"  # 默认
        assert result.age == 25  # 默认
        assert len(result.personality.traits) >= 3

    def test_generate_profile_invalid_gender_defaults(self):
        """无效性别使用默认值。"""
        client = _make_llm_client(
            response_json={**_make_profile_json(), "gender": "unknown"}
        )
        service = CharacterService(client)

        result = service.generate_profile("林风", "主角", "玄幻", "大纲")

        assert result.gender == "男"

    def test_generate_profile_traits_too_few(self):
        """性格标签不足 3 个时使用默认。"""
        profile_json = _make_profile_json()
        profile_json["personality"]["traits"] = ["单一"]
        client = _make_llm_client(response_json=profile_json)
        service = CharacterService(client)

        result = service.generate_profile("林风", "主角", "玄幻", "大纲")

        assert len(result.personality.traits) >= 3

    def test_generate_profile_traits_too_many_truncated(self):
        """性格标签超过 7 个时截断。"""
        profile_json = _make_profile_json()
        profile_json["personality"]["traits"] = [
            "a", "b", "c", "d", "e", "f", "g", "h", "i"
        ]
        client = _make_llm_client(response_json=profile_json)
        service = CharacterService(client)

        result = service.generate_profile("林风", "主角", "玄幻", "大纲")

        assert len(result.personality.traits) <= 7

    def test_generate_profile_retries_on_garbage(self):
        """档案生成重试。"""
        client = MagicMock()
        client.chat.side_effect = [
            FakeLLMResponse(content="not json"),
            FakeLLMResponse(
                content=json.dumps(_make_profile_json(), ensure_ascii=False)
            ),
        ]
        service = CharacterService(client)

        result = service.generate_profile("林风", "主角", "玄幻", "大纲")

        assert result.name == "林风"
        assert client.chat.call_count == 2


# ---------------------------------------------------------------------------
# CharacterTool 测试
# ---------------------------------------------------------------------------


class TestCharacterTool:
    def test_extract_delegates_to_service(self):
        """extract 正确委托给 CharacterService。"""
        client = _make_llm_client(response_json=_make_characters_json())
        tool = CharacterTool(client)

        result = tool.extract("修仙大纲", "玄幻")

        assert len(result) == 3

    def test_generate_profile_delegates(self):
        """generate_profile 正确委托给 CharacterService。"""
        client = _make_llm_client(response_json=_make_profile_json("苏瑶"))
        tool = CharacterTool(client)

        result = tool.generate_profile("苏瑶", "爱情线", "玄幻", "大纲")

        assert isinstance(result, CharacterProfile)


# ---------------------------------------------------------------------------
# CharacterDesigner Agent 测试
# ---------------------------------------------------------------------------


class TestCharacterDesigner:
    def test_create_characters_complete(self):
        """从大纲提取并生成所有角色档案。"""
        characters_json = _make_characters_json()
        profile1 = _make_profile_json("林风")
        profile2 = _make_profile_json("苏瑶")
        profile2["gender"] = "女"
        profile3 = _make_profile_json("陈魔")

        client = MagicMock()
        client.chat.side_effect = [
            # 第一次调用: extract_characters
            FakeLLMResponse(
                content=json.dumps(characters_json, ensure_ascii=False)
            ),
            # 后续调用: generate_profile (每个角色一次)
            FakeLLMResponse(
                content=json.dumps(profile1, ensure_ascii=False)
            ),
            FakeLLMResponse(
                content=json.dumps(profile2, ensure_ascii=False)
            ),
            FakeLLMResponse(
                content=json.dumps(profile3, ensure_ascii=False)
            ),
        ]
        designer = CharacterDesigner(client)

        result = designer.create_characters(_make_outline(), "玄幻")

        assert len(result) == 3
        assert all(isinstance(p, CharacterProfile) for p in result)
        names = {p.name for p in result}
        assert "林风" in names

    def test_create_characters_partial_failure(self):
        """部分角色档案生成失败，其余继续。"""
        characters_json = _make_characters_json()

        client = MagicMock()
        client.chat.side_effect = [
            # extract_characters
            FakeLLMResponse(
                content=json.dumps(characters_json, ensure_ascii=False)
            ),
            # 第一个角色成功
            FakeLLMResponse(
                content=json.dumps(_make_profile_json("林风"), ensure_ascii=False)
            ),
            # 第二个角色失败（连续垃圾）
            FakeLLMResponse(content="garbage"),
            FakeLLMResponse(content="garbage"),
            FakeLLMResponse(content="garbage"),
            # 第三个角色成功
            FakeLLMResponse(
                content=json.dumps(_make_profile_json("陈魔"), ensure_ascii=False)
            ),
        ]
        designer = CharacterDesigner(client)

        result = designer.create_characters(_make_outline(), "玄幻")

        # 只有 2 个成功
        assert len(result) == 2

    def test_validate_character_consistency_clean(self):
        """无 OOC 行为通过验证。"""
        client = _make_llm_client()
        designer = CharacterDesigner(client)
        characters = [_make_character_profile("林风", "冷淡简短")]

        is_ok, violations = designer.validate_character_consistency(
            "林风冷冷地看了一眼，说道\u201c走。\u201d", characters
        )

        assert is_ok is True
        assert violations == []

    def test_validate_character_consistency_ooc_long_dialogue(self):
        """冷淡简短风格角色出现长对话触发警告。"""
        client = _make_llm_client()
        designer = CharacterDesigner(client)
        characters = [_make_character_profile("林风", "冷淡简短")]

        long_dialogue = "这是一段非常非常长的对话内容，" * 10
        text = f"林风激动地说道\u201c{long_dialogue}\u201d"

        is_ok, violations = designer.validate_character_consistency(
            text, characters
        )

        assert is_ok is False
        assert len(violations) >= 1
        assert "冷淡简短" in violations[0]

    def test_validate_character_consistency_empty_text(self):
        """空文本通过验证。"""
        client = _make_llm_client()
        designer = CharacterDesigner(client)

        is_ok, violations = designer.validate_character_consistency(
            "", [_make_character_profile()]
        )

        assert is_ok is True

    def test_validate_character_consistency_no_matching_character(self):
        """角色未出现在文本中，跳过检查。"""
        client = _make_llm_client()
        designer = CharacterDesigner(client)
        characters = [_make_character_profile("林风")]

        is_ok, violations = designer.validate_character_consistency(
            "这段文本没有提到任何角色。", characters
        )

        assert is_ok is True

    def test_validate_classical_style_modern_words(self):
        """文绉绉风格角色使用现代用语触发警告。"""
        client = _make_llm_client()
        designer = CharacterDesigner(client)
        characters = [_make_character_profile("林风", "文绉绉")]

        text = '林风微微一笑说道\u201cOK搞定了\u201d'

        is_ok, violations = designer.validate_character_consistency(
            text, characters
        )

        assert is_ok is False
        assert any("OK" in v for v in violations)

    def test_extract_outline_summary(self):
        """大纲摘要提取。"""
        client = _make_llm_client()
        designer = CharacterDesigner(client)

        summary = designer._extract_outline_summary(_make_outline())

        assert "入门" in summary

    def test_extract_outline_summary_empty(self):
        """空大纲返回默认摘要。"""
        client = _make_llm_client()
        designer = CharacterDesigner(client)

        summary = designer._extract_outline_summary({})

        assert summary == "暂无大纲摘要"


# ---------------------------------------------------------------------------
# character_designer_node 测试
# ---------------------------------------------------------------------------


class TestCharacterDesignerNode:
    def test_generates_characters_for_new_project(self):
        """新项目提取并生成角色。"""
        characters_json = _make_characters_json()
        profile_json = _make_profile_json()

        mock_client = MagicMock()
        mock_client.chat.side_effect = [
            FakeLLMResponse(
                content=json.dumps(characters_json, ensure_ascii=False)
            ),
            FakeLLMResponse(
                content=json.dumps(profile_json, ensure_ascii=False)
            ),
            FakeLLMResponse(
                content=json.dumps(
                    {**profile_json, "name": "苏瑶", "gender": "女"},
                    ensure_ascii=False,
                )
            ),
            FakeLLMResponse(
                content=json.dumps(
                    {**profile_json, "name": "陈魔"},
                    ensure_ascii=False,
                )
            ),
        ]

        state = {
            "genre": "玄幻",
            "outline": _make_outline(),
            "characters": [],
            "config": {},
        }

        with patch(
            "src.novel.agents.character_designer.create_llm_client",
            return_value=mock_client,
        ):
            result = character_designer_node(state)

        assert result["characters"] is not None
        assert len(result["characters"]) == 3
        assert "character_designer" in result["completed_nodes"]
        assert len(result["decisions"]) >= 1

    def test_skips_when_characters_exist(self):
        """已有角色数据时跳过。"""
        state = {
            "genre": "玄幻",
            "characters": [{"name": "existing"}],
            "config": {},
        }

        result = character_designer_node(state)

        assert "character_designer" in result["completed_nodes"]
        assert result.get("characters") is None  # 不覆盖
        assert any("跳过" in d["decision"] for d in result["decisions"])

    def test_llm_init_failure(self):
        """LLM 初始化失败。"""
        state = {"genre": "玄幻", "outline": {}, "characters": [], "config": {}}

        with patch(
            "src.novel.agents.character_designer.create_llm_client",
            side_effect=RuntimeError("No LLM available"),
        ):
            result = character_designer_node(state)

        assert len(result["errors"]) >= 1
        assert "LLM 初始化失败" in result["errors"][0]["message"]

    def test_character_generation_failure(self):
        """角色生成失败时返回错误。"""
        mock_client = MagicMock()
        mock_client.chat.return_value = FakeLLMResponse(content="not json")

        state = {
            "genre": "玄幻",
            "outline": {},
            "characters": [],
            "config": {},
        }

        with patch(
            "src.novel.agents.character_designer.create_llm_client",
            return_value=mock_client,
        ):
            result = character_designer_node(state)

        assert len(result["errors"]) >= 1
        assert "角色生成失败" in result["errors"][-1]["message"]
        assert "character_designer" in result["completed_nodes"]

    def test_missing_genre_raises(self):
        """Phase 0 架构重构：state 缺少 genre 时直接抛 ValueError，不再 fallback 到 '玄幻'。"""
        import pytest

        mock_client = MagicMock()
        state = {"outline": _make_outline(), "characters": [], "config": {}}

        with patch(
            "src.novel.agents.character_designer.create_llm_client",
            return_value=mock_client,
        ):
            with pytest.raises(ValueError, match="genre"):
                character_designer_node(state)


class TestMakeDecision:
    def test_creates_decision(self):
        d = _make_decision(step="test", decision="do it", reason="why not")
        assert d["agent"] == "CharacterDesigner"
        assert d["step"] == "test"
        assert "timestamp" in d
