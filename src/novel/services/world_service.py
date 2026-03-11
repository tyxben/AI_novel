"""世界观生成服务

通过 LLM 生成世界观设定和力量体系。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.novel.models.world import PowerLevel, PowerSystem, WorldSetting

log = logging.getLogger("novel")

# 需要力量体系的题材
_POWER_SYSTEM_GENRES = {"玄幻", "修仙", "仙侠", "武侠", "奇幻", "魔幻"}


def _extract_json_obj(text: str | None) -> dict | None:
    """从 LLM 输出中稳健提取 JSON 对象。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


class WorldService:
    """世界观生成服务 - 封装 LLM 交互逻辑。"""

    MAX_RETRIES = 3

    def __init__(self, llm_client: Any):
        """
        Args:
            llm_client: 实现 ``chat(messages, temperature, json_mode)`` 的 LLMClient。
        """
        self.llm = llm_client

    def create_world_setting(
        self, genre: str, outline_summary: str
    ) -> WorldSetting:
        """根据题材和大纲摘要生成世界观设定。

        Args:
            genre: 小说题材，如 "玄幻" / "都市" / "武侠"。
            outline_summary: 大纲的简短摘要。

        Returns:
            WorldSetting 模型实例。

        Raises:
            RuntimeError: LLM 连续返回无效数据。
        """
        prompt = f"""请为以下小说生成世界观设定：

题材：{genre}
大纲摘要：{outline_summary}

请严格按以下 JSON 格式返回：
{{
  "era": "时代背景（古代/现代/未来/架空）",
  "location": "地域背景描述",
  "terms": {{"专有名词1": "定义1", "专有名词2": "定义2"}},
  "rules": ["世界规则1", "世界规则2", "世界规则3"]
}}

要求：
1. era 必须是具体描述，如"架空古代修仙世界"
2. location 必须描述主要地理环境
3. terms 至少包含 3 个专有名词
4. rules 至少包含 3 条世界规则
"""

        last_error = ""
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": "你是一位资深小说世界观设计师。请严格按照 JSON 格式返回世界观设定。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.8,
                    json_mode=True,
                )
                data = _extract_json_obj(response.content)
                if data is not None:
                    return self._parse_world_setting(data)
                last_error = f"LLM 返回内容无法解析为 JSON: {response.content[:200]}"
            except Exception as exc:
                last_error = f"LLM 调用失败: {exc}"
                log.warning(
                    "世界观生成第 %d 次尝试失败: %s", attempt + 1, last_error
                )

        raise RuntimeError(
            f"世界观生成失败，已重试 {self.MAX_RETRIES} 次。最后错误: {last_error}"
        )

    def define_power_system(
        self, genre: str, world_context: str, levels: int = 10
    ) -> PowerSystem | None:
        """生成力量体系（仅适用于玄幻/武侠等题材）。

        Args:
            genre: 小说题材。
            world_context: 世界观上下文描述。
            levels: 力量层级数量，默认 10。

        Returns:
            PowerSystem 模型实例，现代/言情等题材返回 None。

        Raises:
            RuntimeError: LLM 连续返回无效数据。
        """
        if genre not in _POWER_SYSTEM_GENRES:
            return None

        prompt = f"""请为以下小说设计力量体系：

题材：{genre}
世界观：{world_context}
层级数量：{levels}

请严格按以下 JSON 格式返回：
{{
  "name": "力量体系名称（如'修炼境界'、'武学境界'）",
  "levels": [
    {{
      "rank": 1,
      "name": "第一层级名称",
      "description": "该层级描述",
      "typical_abilities": ["能力1", "能力2"]
    }},
    {{
      "rank": 2,
      "name": "第二层级名称",
      "description": "该层级描述",
      "typical_abilities": ["能力1", "能力2"]
    }}
  ]
}}

要求：
1. rank 从 1 开始连续递增到 {levels}
2. 每个层级有具体名称和至少 1 个典型能力
3. 层级之间有明显的实力递进关系
"""

        last_error = ""
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": "你是一位资深小说力量体系设计师。请严格按照 JSON 格式返回力量体系。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                    json_mode=True,
                )
                data = _extract_json_obj(response.content)
                if data is not None:
                    return self._parse_power_system(data)
                last_error = f"LLM 返回内容无法解析为 JSON: {response.content[:200]}"
            except Exception as exc:
                last_error = f"LLM 调用失败: {exc}"
                log.warning(
                    "力量体系生成第 %d 次尝试失败: %s", attempt + 1, last_error
                )

        raise RuntimeError(
            f"力量体系生成失败，已重试 {self.MAX_RETRIES} 次。最后错误: {last_error}"
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _parse_world_setting(self, data: dict) -> WorldSetting:
        """将 LLM 返回的 JSON 解析为 WorldSetting。"""
        era = data.get("era", "架空世界")
        location = data.get("location", "未知之地")
        terms = data.get("terms", {})
        rules = data.get("rules", [])

        # 确保 era 和 location 非空
        if not era or not era.strip():
            era = "架空世界"
        if not location or not location.strip():
            location = "未知之地"

        # 确保 terms 是 dict
        if not isinstance(terms, dict):
            terms = {}

        # 确保 rules 是 list[str]
        if not isinstance(rules, list):
            rules = []
        rules = [str(r) for r in rules if r]

        return WorldSetting(
            era=era,
            location=location,
            terms=terms,
            rules=rules,
        )

    def _parse_power_system(self, data: dict) -> PowerSystem:
        """将 LLM 返回的 JSON 解析为 PowerSystem。"""
        name = data.get("name", "修炼境界")
        if not name or not name.strip():
            name = "修炼境界"

        raw_levels = data.get("levels", [])
        levels: list[PowerLevel] = []

        for lv_data in raw_levels:
            try:
                levels.append(
                    PowerLevel(
                        rank=lv_data.get("rank", len(levels) + 1),
                        name=lv_data.get("name", f"第{len(levels) + 1}层"),
                        description=lv_data.get("description", "待定"),
                        typical_abilities=lv_data.get("typical_abilities", []),
                    )
                )
            except Exception:
                log.warning("跳过无效力量等级数据: %s", lv_data)

        if not levels:
            # 至少创建一个层级保证模型验证通过
            levels = [
                PowerLevel(
                    rank=1,
                    name="初始境界",
                    description="最基础的境界",
                    typical_abilities=["基础能力"],
                )
            ]

        return PowerSystem(name=name, levels=levels)
