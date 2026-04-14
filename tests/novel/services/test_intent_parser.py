"""测试 IntentParser 意图解析器"""

from __future__ import annotations

import json

import pytest
from unittest.mock import MagicMock

from src.llm.llm_client import LLMResponse
from src.novel.services.intent_parser import IntentParser


# ========== Fixtures ==========


@pytest.fixture
def mock_llm():
    """创建 Mock LLM 客户端"""
    return MagicMock()


@pytest.fixture
def parser(mock_llm):
    """创建 IntentParser 实例"""
    return IntentParser(llm_client=mock_llm)


@pytest.fixture
def novel_context():
    """示例小说上下文"""
    return {
        "genre": "玄幻",
        "current_chapter": 10,
        "characters": [
            {
                "character_id": "char_001",
                "name": "萧炎",
                "role": "主角",
            },
            {
                "character_id": "char_002",
                "name": "药老",
                "role": "导师",
            },
        ],
    }


def _make_response(content: str) -> LLMResponse:
    """构造 LLMResponse"""
    return LLMResponse(content=content, model="mock-model", usage=None)


# ========== 添加角色测试 ==========


class TestParseAddCharacter:
    def test_add_character_basic(self, parser, mock_llm, novel_context):
        """应正确解析添加角色指令"""
        llm_output = json.dumps(
            {
                "change_type": "add",
                "entity_type": "character",
                "data": {
                    "name": "柳青鸾",
                    "gender": "女",
                    "age": 30,
                    "occupation": "剑客",
                    "role": "反派",
                    "appearance": {
                        "height": "170cm",
                        "build": "修长",
                        "hair": "白色长发",
                        "eyes": "冰蓝色",
                        "clothing_style": "黑色劲装",
                    },
                    "personality": {
                        "traits": ["冷酷", "果断"],
                        "core_belief": "实力决定一切",
                        "motivation": "复仇",
                        "flaw": "不信任他人",
                        "speech_style": "冷淡简短",
                    },
                },
                "effective_from_chapter": 10,
                "reasoning": "用户要求添加反派角色柳青鸾",
            },
            ensure_ascii=False,
        )
        mock_llm.chat.return_value = _make_response(llm_output)

        result = parser.parse("添加一个30岁女剑客反派，名叫柳青鸾", novel_context)

        assert result["change_type"] == "add"
        assert result["entity_type"] == "character"
        assert result["data"]["name"] == "柳青鸾"
        assert result["data"]["gender"] == "女"
        assert result["data"]["age"] == 30
        assert result["data"]["role"] == "反派"
        assert result["effective_from_chapter"] == 10
        assert result["data"]["appearance"]["hair"] == "白色长发"
        assert "冷酷" in result["data"]["personality"]["traits"]

    def test_add_character_fills_defaults(self, parser, mock_llm, novel_context):
        """缺失字段应被自动补全"""
        llm_output = json.dumps(
            {
                "change_type": "add",
                "entity_type": "character",
                "data": {"name": "小明"},
                "effective_from_chapter": None,
                "reasoning": "添加简单角色",
            },
            ensure_ascii=False,
        )
        mock_llm.chat.return_value = _make_response(llm_output)

        result = parser.parse("添加角色小明", novel_context)

        data = result["data"]
        assert data["name"] == "小明"
        # 默认值被填充
        assert data["gender"] == "未知"
        assert data["age"] == 25
        assert data["occupation"] == "未知"
        assert data["role"] == "配角"
        # appearance 默认值
        assert "appearance" in data
        assert data["appearance"]["height"] == "中等身高"
        assert data["appearance"]["hair"] == "黑色短发"
        # personality 默认值
        assert "personality" in data
        assert data["personality"]["traits"] == ["沉稳"]
        assert data["personality"]["core_belief"] == "未知"


# ========== 更新操作测试 ==========


class TestParseUpdate:
    def test_update_character(self, parser, mock_llm, novel_context):
        """应正确解析修改角色指令"""
        llm_output = json.dumps(
            {
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {
                    "personality": {
                        "traits": ["暴躁", "冲动"],
                        "core_belief": "力量至上",
                        "motivation": "变强",
                        "flaw": "鲁莽",
                        "speech_style": "粗犷",
                    }
                },
                "effective_from_chapter": 15,
                "reasoning": "修改萧炎性格为暴躁",
            },
            ensure_ascii=False,
        )
        mock_llm.chat.return_value = _make_response(llm_output)

        result = parser.parse("把萧炎的性格改为暴躁冲动", novel_context)

        assert result["change_type"] == "update"
        assert result["entity_type"] == "character"
        assert result["entity_id"] == "char_001"
        assert "暴躁" in result["data"]["personality"]["traits"]

    def test_update_outline(self, parser, mock_llm, novel_context):
        """应正确解析修改大纲指令"""
        llm_output = json.dumps(
            {
                "change_type": "update",
                "entity_type": "outline",
                "entity_id": "chapter_10",
                "data": {"mood": "大爽", "chapter_number": 10},
                "effective_from_chapter": 10,
                "reasoning": "修改第10章情绪为大爽",
            },
            ensure_ascii=False,
        )
        mock_llm.chat.return_value = _make_response(llm_output)

        result = parser.parse("第10章改为大爽", novel_context)

        assert result["change_type"] == "update"
        assert result["entity_type"] == "outline"
        assert result["data"]["mood"] == "大爽"

    def test_update_world_setting(self, parser, mock_llm, novel_context):
        """应正确解析修改世界观指令"""
        llm_output = json.dumps(
            {
                "change_type": "update",
                "entity_type": "world_setting",
                "entity_id": "power_system",
                "data": {"description": "修仙体系改为武道体系"},
                "effective_from_chapter": 1,
                "reasoning": "修改功法体系",
            },
            ensure_ascii=False,
        )
        mock_llm.chat.return_value = _make_response(llm_output)

        result = parser.parse("把功法体系改为武道体系", novel_context)

        assert result["change_type"] == "update"
        assert result["entity_type"] == "world_setting"
        assert result["entity_id"] == "power_system"


# ========== 删除操作测试 ==========


class TestParseDelete:
    def test_delete_character(self, parser, mock_llm, novel_context):
        """应正确解析删除角色指令"""
        llm_output = json.dumps(
            {
                "change_type": "delete",
                "entity_type": "character",
                "entity_id": "char_002",
                "effective_from_chapter": 11,
                "reasoning": "用户要求删除药老",
            },
            ensure_ascii=False,
        )
        mock_llm.chat.return_value = _make_response(llm_output)

        result = parser.parse("删除药老这个角色", novel_context)

        assert result["change_type"] == "delete"
        assert result["entity_type"] == "character"
        assert result["entity_id"] == "char_002"
        assert result["effective_from_chapter"] == 11


# ========== effective_from_chapter 测试 ==========


class TestEffectiveFromChapter:
    def test_user_specified_chapter(self, parser, mock_llm, novel_context):
        """用户指定 effective_from_chapter 应传入 prompt"""
        llm_output = json.dumps(
            {
                "change_type": "add",
                "entity_type": "character",
                "data": {"name": "新角色"},
                "effective_from_chapter": 20,
                "reasoning": "从第20章开始",
            },
            ensure_ascii=False,
        )
        mock_llm.chat.return_value = _make_response(llm_output)

        result = parser.parse(
            "添加一个新角色",
            novel_context,
            effective_from_chapter=20,
        )

        # 验证 prompt 中包含了用户指定的章节
        call_args = mock_llm.chat.call_args
        messages = call_args[1].get("messages") or call_args[0][0]
        user_msg = messages[1]["content"]
        assert "第 20 章" in user_msg

        assert result["effective_from_chapter"] == 20

    def test_null_effective_from_chapter(self, parser, mock_llm, novel_context):
        """LLM 返回 null 生效章节时保留 None"""
        llm_output = json.dumps(
            {
                "change_type": "add",
                "entity_type": "character",
                "data": {"name": "某角色"},
                "effective_from_chapter": None,
                "reasoning": "未指定章节",
            },
            ensure_ascii=False,
        )
        mock_llm.chat.return_value = _make_response(llm_output)

        result = parser.parse("添加角色", novel_context)

        assert result["effective_from_chapter"] is None


# ========== 错误处理和重试测试 ==========


class TestErrorHandling:
    def test_retries_on_invalid_json(self, parser, mock_llm, novel_context):
        """LLM 返回无效 JSON 时应重试"""
        # 前两次返回无效 JSON，第三次返回有效结果
        valid_output = json.dumps(
            {
                "change_type": "add",
                "entity_type": "character",
                "data": {"name": "测试"},
                "effective_from_chapter": None,
                "reasoning": "重试成功",
            },
            ensure_ascii=False,
        )
        mock_llm.chat.side_effect = [
            _make_response("这不是有效的JSON"),
            _make_response("{invalid json}}}"),
            _make_response(valid_output),
        ]

        result = parser.parse("添加角色测试", novel_context)

        assert result["change_type"] == "add"
        assert mock_llm.chat.call_count == 3

    def test_raises_after_max_retries(self, parser, mock_llm, novel_context):
        """3次都失败后应抛出 ValueError"""
        mock_llm.chat.return_value = _make_response("无法解析的内容")

        with pytest.raises(ValueError, match="解析指令失败"):
            parser.parse("完全无法理解的指令", novel_context)

        assert mock_llm.chat.call_count == 3

    def test_retries_on_missing_change_type(self, parser, mock_llm, novel_context):
        """缺少 change_type 应触发重试"""
        invalid = json.dumps({"entity_type": "character", "data": {}})
        valid = json.dumps(
            {
                "change_type": "add",
                "entity_type": "character",
                "data": {"name": "某角色"},
                "effective_from_chapter": None,
                "reasoning": "ok",
            },
            ensure_ascii=False,
        )
        mock_llm.chat.side_effect = [
            _make_response(invalid),
            _make_response(valid),
        ]

        result = parser.parse("添加角色", novel_context)
        assert result["change_type"] == "add"
        assert mock_llm.chat.call_count == 2

    def test_retries_on_invalid_entity_type(self, parser, mock_llm, novel_context):
        """非法 entity_type 应触发重试"""
        invalid = json.dumps(
            {
                "change_type": "add",
                "entity_type": "weapon",  # 不在允许列表
                "data": {"name": "某武器"},
            }
        )
        valid = json.dumps(
            {
                "change_type": "add",
                "entity_type": "character",
                "data": {"name": "某角色"},
                "effective_from_chapter": None,
                "reasoning": "ok",
            },
            ensure_ascii=False,
        )
        mock_llm.chat.side_effect = [
            _make_response(invalid),
            _make_response(valid),
        ]

        result = parser.parse("添加角色", novel_context)
        assert result["entity_type"] == "character"

    def test_retries_on_update_without_entity_id(
        self, parser, mock_llm, novel_context
    ):
        """update 操作缺少 entity_id 应触发重试"""
        invalid = json.dumps(
            {
                "change_type": "update",
                "entity_type": "character",
                "data": {"name": "修改"},
            }
        )
        valid = json.dumps(
            {
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"name": "萧炎改"},
                "effective_from_chapter": 10,
                "reasoning": "ok",
            },
            ensure_ascii=False,
        )
        mock_llm.chat.side_effect = [
            _make_response(invalid),
            _make_response(valid),
        ]

        result = parser.parse("修改萧炎名字", novel_context)
        assert result["entity_id"] == "char_001"


# ========== Prompt 构建测试 ==========


class TestPromptBuilding:
    def test_prompt_contains_genre(self, parser, mock_llm, novel_context):
        """prompt 应包含小说题材"""
        valid = json.dumps(
            {
                "change_type": "add",
                "entity_type": "character",
                "data": {"name": "x"},
                "effective_from_chapter": None,
                "reasoning": "ok",
            }
        )
        mock_llm.chat.return_value = _make_response(valid)

        parser.parse("添加角色", novel_context)

        call_args = mock_llm.chat.call_args
        messages = call_args[1].get("messages") or call_args[0][0]
        user_msg = messages[1]["content"]
        assert "玄幻" in user_msg

    def test_prompt_contains_character_list(self, parser, mock_llm, novel_context):
        """prompt 应包含现有角色列表"""
        valid = json.dumps(
            {
                "change_type": "add",
                "entity_type": "character",
                "data": {"name": "x"},
                "effective_from_chapter": None,
                "reasoning": "ok",
            }
        )
        mock_llm.chat.return_value = _make_response(valid)

        parser.parse("添加角色", novel_context)

        call_args = mock_llm.chat.call_args
        messages = call_args[1].get("messages") or call_args[0][0]
        user_msg = messages[1]["content"]
        assert "萧炎" in user_msg
        assert "char_001" in user_msg
        assert "药老" in user_msg

    def test_prompt_contains_current_chapter(self, parser, mock_llm, novel_context):
        """prompt 应包含当前章节号"""
        valid = json.dumps(
            {
                "change_type": "add",
                "entity_type": "character",
                "data": {"name": "x"},
                "effective_from_chapter": None,
                "reasoning": "ok",
            }
        )
        mock_llm.chat.return_value = _make_response(valid)

        parser.parse("添加角色", novel_context)

        call_args = mock_llm.chat.call_args
        messages = call_args[1].get("messages") or call_args[0][0]
        user_msg = messages[1]["content"]
        assert "第 10 章" in user_msg

    def test_prompt_empty_characters(self, parser, mock_llm):
        """没有角色时 prompt 应显示"暂无角色"""
        context = {"genre": "科幻", "current_chapter": 0, "characters": []}
        valid = json.dumps(
            {
                "change_type": "add",
                "entity_type": "character",
                "data": {"name": "x"},
                "effective_from_chapter": None,
                "reasoning": "ok",
            }
        )
        mock_llm.chat.return_value = _make_response(valid)

        parser.parse("添加角色", context)

        call_args = mock_llm.chat.call_args
        messages = call_args[1].get("messages") or call_args[0][0]
        user_msg = messages[1]["content"]
        assert "暂无角色" in user_msg

    def test_llm_called_with_correct_params(self, parser, mock_llm, novel_context):
        """应使用正确的 LLM 参数调用"""
        valid = json.dumps(
            {
                "change_type": "add",
                "entity_type": "character",
                "data": {"name": "x"},
                "effective_from_chapter": None,
                "reasoning": "ok",
            }
        )
        mock_llm.chat.return_value = _make_response(valid)

        parser.parse("添加角色", novel_context)

        call_kwargs = mock_llm.chat.call_args[1]
        assert call_kwargs["temperature"] == 0.2
        assert call_kwargs["json_mode"] is True
        assert call_kwargs["max_tokens"] == 4096
        assert len(call_kwargs["messages"]) == 2
        assert call_kwargs["messages"][0]["role"] == "system"
        assert call_kwargs["messages"][1]["role"] == "user"


# ========== 边界条件测试 ==========


class TestEdgeCases:
    def test_reasoning_field_added_if_missing(self, parser, mock_llm, novel_context):
        """LLM 未返回 reasoning 字段时应补上空字符串"""
        llm_output = json.dumps(
            {
                "change_type": "add",
                "entity_type": "character",
                "data": {"name": "无理由角色"},
                "effective_from_chapter": 5,
            },
            ensure_ascii=False,
        )
        mock_llm.chat.return_value = _make_response(llm_output)

        result = parser.parse("添加角色", novel_context)
        assert "reasoning" in result
        assert result["reasoning"] == ""

    def test_json_in_markdown_code_block(self, parser, mock_llm, novel_context):
        """LLM 用 markdown 代码块包裹 JSON 时应正确提取"""
        raw = """```json
{
    "change_type": "add",
    "entity_type": "character",
    "data": {"name": "代码块角色"},
    "effective_from_chapter": null,
    "reasoning": "markdown wrapped"
}
```"""
        mock_llm.chat.return_value = _make_response(raw)

        result = parser.parse("添加角色", novel_context)
        assert result["data"]["name"] == "代码块角色"

    def test_delete_does_not_require_data(self, parser, mock_llm, novel_context):
        """delete 操作可以不包含 data 字段"""
        llm_output = json.dumps(
            {
                "change_type": "delete",
                "entity_type": "character",
                "entity_id": "char_002",
                "effective_from_chapter": 11,
                "reasoning": "删除角色",
            },
            ensure_ascii=False,
        )
        mock_llm.chat.return_value = _make_response(llm_output)

        result = parser.parse("删除药老", novel_context)
        assert result["change_type"] == "delete"
        assert result["entity_id"] == "char_002"


# ========== 缓存测试 ==========


def _update_char_response() -> LLMResponse:
    return _make_response(
        json.dumps(
            {
                "change_type": "update",
                "entity_type": "character",
                "entity_id": "char_001",
                "data": {"age": 25},
                "effective_from_chapter": 10,
                "reasoning": "user asked to update age",
            },
            ensure_ascii=False,
        )
    )


class TestIntentParserCache:
    def test_cache_disabled_by_default(self, mock_llm, novel_context):
        parser = IntentParser(llm_client=mock_llm)
        mock_llm.chat.return_value = _update_char_response()

        parser.parse("修改萧炎年龄为25", novel_context)
        parser.parse("修改萧炎年龄为25", novel_context)

        assert mock_llm.chat.call_count == 2
        stats = parser.cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["size"] == 0

    def test_cache_hit_avoids_llm_call(self, mock_llm, novel_context):
        parser = IntentParser(llm_client=mock_llm, enable_cache=True)
        mock_llm.chat.return_value = _update_char_response()

        r1 = parser.parse("修改萧炎年龄为25", novel_context)
        r2 = parser.parse("修改萧炎年龄为25", novel_context)

        assert mock_llm.chat.call_count == 1
        assert r1 == r2
        stats = parser.cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_cache_isolates_different_effective_from(
        self, mock_llm, novel_context
    ):
        parser = IntentParser(llm_client=mock_llm, enable_cache=True)
        mock_llm.chat.return_value = _update_char_response()

        parser.parse("修改萧炎", novel_context, effective_from_chapter=5)
        parser.parse("修改萧炎", novel_context, effective_from_chapter=7)

        assert mock_llm.chat.call_count == 2
        assert parser.cache_stats()["size"] == 2

    def test_cache_key_ignores_characters_list(
        self, mock_llm, novel_context
    ):
        """角色列表变化不触发 cache miss（按 instruction+genre+chapter 键）。"""
        parser = IntentParser(llm_client=mock_llm, enable_cache=True)
        mock_llm.chat.return_value = _update_char_response()

        parser.parse("修改萧炎", novel_context)

        ctx2 = dict(novel_context)
        ctx2["characters"] = novel_context["characters"] + [
            {"character_id": "char_003", "name": "新人", "role": "配角"}
        ]
        parser.parse("修改萧炎", ctx2)

        assert mock_llm.chat.call_count == 1
        assert parser.cache_stats()["hits"] == 1

    def test_cache_returns_deepcopy(self, mock_llm, novel_context):
        """缓存命中返回独立副本，修改不污染缓存。"""
        parser = IntentParser(llm_client=mock_llm, enable_cache=True)
        mock_llm.chat.return_value = _update_char_response()

        r1 = parser.parse("修改萧炎", novel_context)
        r1["data"]["age"] = 999  # tamper

        r2 = parser.parse("修改萧炎", novel_context)
        assert r2["data"]["age"] == 25

    def test_cache_eviction_lru(self, mock_llm, novel_context):
        """缓存满后按 LRU 淘汰最旧条目。"""
        parser = IntentParser(
            llm_client=mock_llm, enable_cache=True, cache_size=2
        )
        mock_llm.chat.return_value = _update_char_response()

        parser.parse("A", novel_context)
        parser.parse("B", novel_context)
        parser.parse("C", novel_context)  # evicts A

        stats = parser.cache_stats()
        assert stats["size"] == 2
        assert mock_llm.chat.call_count == 3

        # A 已被淘汰 → 再查 A 是 miss
        parser.parse("A", novel_context)
        assert mock_llm.chat.call_count == 4

    def test_clear_cache(self, mock_llm, novel_context):
        parser = IntentParser(llm_client=mock_llm, enable_cache=True)
        mock_llm.chat.return_value = _update_char_response()

        parser.parse("修改萧炎", novel_context)
        parser.parse("修改萧炎", novel_context)
        assert parser.cache_stats()["hits"] == 1

        parser.clear_cache()
        stats = parser.cache_stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

        parser.parse("修改萧炎", novel_context)
        assert mock_llm.chat.call_count == 2
