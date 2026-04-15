"""角色生成服务

通过 LLM 提取角色列表和生成完整角色档案。
"""

from __future__ import annotations

import logging
from typing import Any

from src.novel.models.character import (
    Appearance,
    CharacterArc,
    CharacterProfile,
    Personality,
    TurningPoint,
)
from src.novel.utils.json_extract import extract_json_array, extract_json_obj

log = logging.getLogger("novel")


# Backward-compat aliases — canonical implementation in
# ``src.novel.utils.json_extract``. Kept so legacy imports continue to work.
def _extract_json_obj(text: str | None) -> dict | None:
    """Deprecated: use :func:`src.novel.utils.json_extract.extract_json_obj`."""
    return extract_json_obj(text)


def _extract_json_array(text: str | None) -> list | None:
    """Deprecated: use :func:`src.novel.utils.json_extract.extract_json_array`.

    Historical behaviour only unwrapped ``{"characters": [...]}``; we preserve
    that by restricting ``unwrap_keys``.
    """
    return extract_json_array(text, unwrap_keys=("characters",))


class CharacterService:
    """角色生成服务 - 封装 LLM 交互逻辑。"""

    MAX_RETRIES = 3

    def __init__(self, llm_client: Any):
        """
        Args:
            llm_client: 实现 ``chat(messages, temperature, json_mode)`` 的 LLMClient。
        """
        self.llm = llm_client

    def extract_characters(
        self, outline_summary: str, genre: str
    ) -> list[dict]:
        """从大纲摘要中提取角色名单及角色类型。

        Args:
            outline_summary: 大纲摘要文本。
            genre: 小说题材。

        Returns:
            角色列表，每项包含 name 和 role。
            例如: [{"name": "张三", "role": "主角"}, ...]

        Raises:
            RuntimeError: LLM 连续返回无效数据。
        """
        prompt = f"""请从以下小说大纲中提取所有主要角色：

题材：{genre}
大纲摘要：{outline_summary}

请严格按以下 JSON 格式返回：
{{
  "characters": [
    {{"name": "角色姓名", "role": "主角/反派/配角/导师/爱情线"}},
    {{"name": "角色姓名", "role": "主角/反派/配角/导师/爱情线"}}
  ]
}}

要求：
1. 至少提取 3 个角色
2. 必须有 1 个主角
3. role 从以下选择：主角、反派、配角、导师、爱情线
4. name 必须是具体的人名（2-3个字的姓名），不能用描述性短语、头衔、职位或群体称呼
   - 正确示例：陈风、楚云霄、燕飞雪（具体的2-3字人名）
   - 错误示例：村中土匪头目、宗门盟主、第一批追随者、分封制下的贵族
5. 如果大纲中某个角色没有具体人名，你必须为其创造一个符合题材风格的人名
6. 群体（如"追随者"、"贵族"）不是角色，不要提取
"""

        last_error = ""
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": "你是一位资深小说角色设计师。请严格按照 JSON 格式返回角色列表。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                    json_mode=True,
                )
                characters = extract_json_array(
                    response.content, unwrap_keys=("characters",)
                )
                if characters is not None and len(characters) > 0:
                    # 验证每个角色有 name 和 role
                    valid = []
                    for ch in characters:
                        if isinstance(ch, dict) and ch.get("name"):
                            valid.append(
                                {
                                    "name": ch["name"],
                                    "role": ch.get("role", "配角"),
                                }
                            )
                    if valid:
                        return valid
                last_error = f"LLM 返回角色列表无效: {response.content[:200]}"
            except Exception as exc:
                last_error = f"LLM 调用失败: {exc}"
                log.warning(
                    "角色提取第 %d 次尝试失败: %s", attempt + 1, last_error
                )

        raise RuntimeError(
            f"角色提取失败，已重试 {self.MAX_RETRIES} 次。最后错误: {last_error}"
        )

    def generate_profile(
        self, name: str, role: str, genre: str, outline_context: str
    ) -> CharacterProfile:
        """为指定角色生成完整档案。

        Args:
            name: 角色名称。
            role: 角色类型（主角/反派/配角/导师/爱情线）。
            genre: 小说题材。
            outline_context: 大纲上下文。

        Returns:
            CharacterProfile 模型实例。

        Raises:
            RuntimeError: LLM 连续返回无效数据。
        """
        prompt = f"""请为以下小说角色生成完整档案：

角色姓名：{name}
角色类型：{role}
题材：{genre}
故事背景：{outline_context}

请严格按以下 JSON 格式返回：
{{
  "name": "{name}",
  "alias": ["别名1"],
  "gender": "男/女/其他",
  "age": 25,
  "occupation": "职业描述",
  "appearance": {{
    "height": "175cm",
    "build": "体型描述（瘦削/魁梧/匀称/纤细/修长）",
    "hair": "发型和颜色",
    "eyes": "眼睛特征",
    "clothing_style": "穿衣风格",
    "distinctive_features": ["特征1", "特征2"]
  }},
  "personality": {{
    "traits": ["性格1", "性格2", "性格3"],
    "core_belief": "核心信念",
    "motivation": "动机",
    "flaw": "缺陷",
    "speech_style": "语言风格描述",
    "catchphrases": ["口头禅1"]
  }},
  "character_arc": {{
    "initial_state": "初始状态描述",
    "turning_points": [
      {{"chapter": 10, "event": "关键事件", "change": "变化描述"}}
    ],
    "final_state": "最终状态描述"
  }}
}}

要求：
1. gender 只能是 "男"、"女" 或 "其他"
2. age 在 0-200 之间
3. personality.traits 必须有 3-7 个
4. speech_style 要具体，如"冷淡简短"、"文绉绉"、"江湖豪爽"
5. 符合 {genre} 题材特色
"""

        last_error = ""
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": "你是一位资深小说角色设计师。请严格按照 JSON 格式返回角色档案。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.8,
                    json_mode=True,
                )
                data = extract_json_obj(response.content)
                if data is not None:
                    return self._parse_character_profile(data, name, role)
                last_error = f"LLM 返回内容无法解析为 JSON: {response.content[:200]}"
            except Exception as exc:
                last_error = f"LLM 调用失败: {exc}"
                log.warning(
                    "角色档案生成第 %d 次尝试失败: %s",
                    attempt + 1,
                    last_error,
                )

        raise RuntimeError(
            f"角色档案生成失败，已重试 {self.MAX_RETRIES} 次。最后错误: {last_error}"
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _parse_character_profile(
        self, data: dict, fallback_name: str, fallback_role: str
    ) -> CharacterProfile:
        """将 LLM 返回的 JSON 解析为 CharacterProfile。"""
        name = data.get("name", fallback_name)
        if not name or not name.strip():
            name = fallback_name

        # 基础属性
        gender = data.get("gender", "男")
        if gender not in ("男", "女", "其他"):
            gender = "男"

        age = data.get("age", 25)
        if not isinstance(age, int) or age < 0 or age > 200:
            age = 25

        occupation = data.get("occupation", "无业")
        if not occupation or not occupation.strip():
            occupation = "无业"

        # 外貌
        app_data = data.get("appearance", {})
        if not isinstance(app_data, dict):
            app_data = {}
        appearance = Appearance(
            height=app_data.get("height", "170cm") or "170cm",
            build=app_data.get("build", "匀称") or "匀称",
            hair=app_data.get("hair", "黑色短发") or "黑色短发",
            eyes=app_data.get("eyes", "黑色") or "黑色",
            clothing_style=app_data.get("clothing_style", "普通") or "普通",
            distinctive_features=app_data.get("distinctive_features", []),
        )

        # 性格
        pers_data = data.get("personality", {})
        if not isinstance(pers_data, dict):
            pers_data = {}
        raw_traits = pers_data.get("traits", ["坚毅", "聪慧", "善良"])
        if not isinstance(raw_traits, list) or len(raw_traits) < 3:
            raw_traits = ["坚毅", "聪慧", "善良"]
        if len(raw_traits) > 7:
            raw_traits = raw_traits[:7]
        # 确保每个 trait 是非空字符串
        traits = [str(t) for t in raw_traits if t and str(t).strip()]
        if len(traits) < 3:
            traits = ["坚毅", "聪慧", "善良"]

        personality = Personality(
            traits=traits,
            core_belief=pers_data.get("core_belief", "正义必胜") or "正义必胜",
            motivation=pers_data.get("motivation", "变强") or "变强",
            flaw=pers_data.get("flaw", "冲动") or "冲动",
            speech_style=pers_data.get("speech_style", "沉稳内敛")
            or "沉稳内敛",
            catchphrases=pers_data.get("catchphrases", []),
        )

        # 成长弧线
        arc_data = data.get("character_arc")
        character_arc = None
        if isinstance(arc_data, dict):
            turning_points: list[TurningPoint] = []
            for tp in arc_data.get("turning_points", []):
                if isinstance(tp, dict):
                    try:
                        turning_points.append(
                            TurningPoint(
                                chapter=tp.get("chapter", 1),
                                event=tp.get("event", "关键事件"),
                                change=tp.get("change", "成长变化"),
                            )
                        )
                    except Exception:
                        pass

            initial = arc_data.get("initial_state", "平凡普通")
            final = arc_data.get("final_state", "蜕变成长")
            if initial and final:
                character_arc = CharacterArc(
                    initial_state=initial or "平凡普通",
                    turning_points=turning_points,
                    final_state=final or "蜕变成长",
                )

        return CharacterProfile(
            name=name,
            alias=data.get("alias", []) or [],
            gender=gender,
            age=age,
            occupation=occupation,
            role=data.get("role") or fallback_role or "配角",
            appearance=appearance,
            personality=personality,
            character_arc=character_arc,
        )
