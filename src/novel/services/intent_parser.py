"""意图解析器 -- 将自然语言编辑指令解析为结构化变更。"""

from __future__ import annotations

import copy
import logging
from collections import OrderedDict
from typing import Any

from src.llm.llm_client import LLMClient
from src.novel.utils import extract_json_from_llm

log = logging.getLogger("novel")

# ---------------------------------------------------------------------------
# Prompt 模板
# ---------------------------------------------------------------------------

_PARSER_SYSTEM_PROMPT = """\
你是小说编辑助手，负责解析用户的设定修改指令。

输出格式（严格 JSON）：
{
  "change_type": "add | update | delete",
  "entity_type": "character | outline | world_setting",
  "entity_id": "实体 ID（update/delete 时必须提供，从现有实体列表中匹配；add 时不要包含）",
  "data": { ... 具体变更内容 ... },
  "effective_from_chapter": 10,
  "reasoning": "你的解析推理过程"
}

注意：
1. 如果用户未指定生效章节，effective_from_chapter 返回 null，系统会自动推断
2. 添加角色时，必须生成完整的角色信息，包括 appearance 和 personality 子对象
3. 缺失字段应根据小说类型和设定智能推断（如玄幻小说的角色命名风格）
4. entity_id 仅在 update/delete 时需要，从现有实体列表中匹配
5. 添加角色时 data 中需包含: name, gender, age, occupation, role, appearance, personality
6. appearance 包含: height, build, hair, eyes, clothing_style
7. personality 包含: traits(列表), core_belief, motivation, flaw, speech_style
"""

_PARSER_USER_TEMPLATE = """\
当前小说设定：
- 题材：{genre}
- 现有角色：{character_list}
- 当前写到第 {current_chapter} 章
{effective_hint}
用户指令：
{instruction}

请解析为结构化变更。"""


class IntentParser:
    """将自然语言指令解析为结构化编辑变更。"""

    def __init__(
        self,
        llm_client: LLMClient,
        enable_cache: bool = False,
        cache_size: int = 32,
    ):
        self.llm = llm_client
        self._enable_cache = enable_cache
        self._cache_size = max(1, cache_size) if enable_cache else 0
        self._cache: OrderedDict[tuple, dict[str, Any]] = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0

    @staticmethod
    def _cache_key(
        instruction: str,
        novel_context: dict[str, Any],
        effective_from_chapter: int | None,
    ) -> tuple:
        """缓存键：仅包含稳定输入（不含角色列表），避免频繁失效。"""
        return (
            instruction.strip(),
            novel_context.get("genre", ""),
            novel_context.get("current_chapter", 0),
            effective_from_chapter,
        )

    def cache_stats(self) -> dict[str, int]:
        """返回缓存命中/未命中/当前大小。"""
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "size": len(self._cache),
            "capacity": self._cache_size,
        }

    def clear_cache(self) -> None:
        self._cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0

    def parse(
        self,
        instruction: str,
        novel_context: dict[str, Any],
        effective_from_chapter: int | None = None,
    ) -> dict[str, Any]:
        """解析自然语言指令为结构化变更。

        Args:
            instruction: 用户自然语言指令
            novel_context: 小说上下文（genre, characters, outline 等）
            effective_from_chapter: 指定生效章节（None 则让 LLM 推断）

        Returns:
            结构化变更 dict：
            {
                "change_type": "add" | "update" | "delete",
                "entity_type": "character" | "outline" | "world_setting",
                "entity_id": "xxx" (update/delete 时),
                "data": { ... },
                "effective_from_chapter": 10,
                "reasoning": "解析推理过程"
            }

        Raises:
            ValueError: 无法解析指令时
        """
        cache_key = None
        if self._enable_cache:
            cache_key = self._cache_key(
                instruction, novel_context, effective_from_chapter
            )
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache_hits += 1
                self._cache.move_to_end(cache_key)
                return copy.deepcopy(cached)
            self._cache_misses += 1

        user_prompt = self._build_user_prompt(
            instruction, novel_context, effective_from_chapter
        )

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.llm.chat(
                    messages=[
                        {"role": "system", "content": _PARSER_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                    json_mode=True,
                    max_tokens=4096,
                )

                parsed = extract_json_from_llm(response.content)
                self._validate(parsed)
                result = self._postprocess(parsed, novel_context)
                if self._enable_cache and cache_key is not None:
                    self._cache[cache_key] = copy.deepcopy(result)
                    self._cache.move_to_end(cache_key)
                    while len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
                return result

            except (ValueError, KeyError) as exc:
                last_error = exc
                log.warning(
                    "IntentParser 解析失败 (第%d次): %s", attempt + 1, exc
                )

        raise ValueError(
            f"解析指令失败（已重试3次）: {last_error}"
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        instruction: str,
        novel_context: dict[str, Any],
        effective_from_chapter: int | None,
    ) -> str:
        """构建用户 prompt。"""
        # 格式化角色列表
        characters = novel_context.get("characters", [])
        if characters:
            char_lines = []
            for c in characters:
                cid = c.get("character_id", "?")
                name = c.get("name", "?")
                role = c.get("role", "")
                char_lines.append(f"  - {name} (ID: {cid}, 角色: {role})")
            character_list = "\n".join(char_lines)
        else:
            character_list = "  （暂无角色）"

        # 生效章节提示
        if effective_from_chapter is not None:
            effective_hint = (
                f"- 用户指定生效章节：第 {effective_from_chapter} 章\n"
            )
        else:
            effective_hint = ""

        genre = novel_context.get("genre", "未知")
        current_chapter = novel_context.get("current_chapter", 0)

        return _PARSER_USER_TEMPLATE.format(
            genre=genre,
            character_list=character_list,
            current_chapter=current_chapter,
            effective_hint=effective_hint,
            instruction=instruction,
        )

    def _validate(self, parsed: dict[str, Any]) -> None:
        """校验 LLM 返回的 JSON 结构。

        Raises:
            ValueError: 缺少必需字段或字段值不合法
        """
        change_type = parsed.get("change_type")
        if change_type not in ("add", "update", "delete"):
            raise ValueError(
                f"change_type 必须为 add/update/delete，得到: {change_type}"
            )

        entity_type = parsed.get("entity_type")
        if entity_type not in ("character", "outline", "world_setting"):
            raise ValueError(
                f"entity_type 不合法: {entity_type}"
            )

        if change_type in ("update", "delete") and not parsed.get("entity_id"):
            raise ValueError(
                f"change_type={change_type} 时必须提供 entity_id"
            )

        if change_type in ("add", "update") and not parsed.get("data"):
            raise ValueError(
                f"change_type={change_type} 时必须提供 data"
            )

    def _postprocess(
        self,
        parsed: dict[str, Any],
        novel_context: dict[str, Any],
    ) -> dict[str, Any]:
        """后处理：补全缺失字段、验证引用。"""
        entity_type = parsed["entity_type"]
        change_type = parsed["change_type"]

        # 角色添加时补全缺失字段
        if entity_type == "character" and change_type == "add":
            data = parsed.get("data", {})
            self._fill_character_defaults(data)
            parsed["data"] = data

        # 确保 reasoning 字段存在
        if "reasoning" not in parsed:
            parsed["reasoning"] = ""

        return parsed

    def _fill_character_defaults(self, data: dict[str, Any]) -> None:
        """为新角色补全缺失的默认字段。"""
        data.setdefault("gender", "未知")
        data.setdefault("age", 25)
        data.setdefault("occupation", "未知")
        data.setdefault("role", "配角")

        # appearance 子对象
        appearance = data.setdefault("appearance", {})
        appearance.setdefault("height", "中等身高")
        appearance.setdefault("build", "匀称")
        appearance.setdefault("hair", "黑色短发")
        appearance.setdefault("eyes", "黑色")
        appearance.setdefault("clothing_style", "普通")

        # personality 子对象
        personality = data.setdefault("personality", {})
        personality.setdefault("traits", ["沉稳"])
        personality.setdefault("core_belief", "未知")
        personality.setdefault("motivation", "未知")
        personality.setdefault("flaw", "未知")
        personality.setdefault("speech_style", "普通")
