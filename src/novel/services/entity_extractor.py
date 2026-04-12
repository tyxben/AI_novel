"""实体提取器 - 规则优先 + LLM Fallback（知识图谱 P0）"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.novel.models.entity import Entity, EntityType

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 正则模式
# ---------------------------------------------------------------------------

_LOCATION_PATTERNS = [
    re.compile(
        r"([\u4e00-\u9fa5]{2,6})"
        r"(山|峰|谷|洞|林|城|镇|村|岛|海|河|湖|宫|殿|阁|院|楼|台|域|界|国)"
    ),
    re.compile(
        r"([\u4e00-\u9fa5]{2,4})(宗|门|派|教|帮|会|盟|族)"
    ),
]

_SKILL_PATTERNS = [
    re.compile(r"《([\u4e00-\u9fa5]{2,8})》"),
    re.compile(
        r"([\u4e00-\u9fa5]{2,6})"
        r"(功|诀|法|术|式|掌|拳|剑法|刀法|枪法)"
    ),
]

_TITLE_PATTERNS = [
    re.compile(
        r"([\u4e00-\u9fa5]{2,4})"
        r"(仙|魔|神|王|帝|尊|圣|祖|宗主|长老|掌门|弟子|境|期)"
    ),
]

_ARTIFACT_PATTERNS = [
    re.compile(
        r"([\u4e00-\u9fa5]{2,6})"
        r"(剑|刀|枪|戟|鼎|炉|印|塔|珠|镜|环|钟|符|丹|甲|袍)"
    ),
]

# 匹配名称中可能出现的动词/虚词/介词，说明匹配跨越了词边界
# 出现在实体名称内部/前部时应截断
_BOUNDARY_CHARS = set(
    "了的在到是把被将向从和与有又也都还去来过着"
    "为用做让给叫称使得成跟比按此那这自"
    "持拿握挥举取收放拔抽拉推"  # 手持/手握等动词
    "修炼练习学"  # 修炼/练习/学习
    "出入进回上下开关"  # 方位动词
)

# ---------------------------------------------------------------------------
# 黑名单（常用词 + 网文高频词）
# ---------------------------------------------------------------------------

_BLACKLIST: set[str] = {
    # 代词/助词
    "他", "她", "它", "我", "你", "这", "那", "什么", "哪里",
    "如何", "为何", "不是", "可以", "不能", "已经", "就是",
    "一个", "一种", "许多", "所有", "大家", "众人",
    # 网文高频词
    "这里", "那里", "此刻", "现在", "当时", "如今", "此时",
    "自己", "对方", "别人", "没有", "不过", "但是", "因为",
    "虽然", "然而", "而且", "所以", "于是", "不知", "只是",
    "顿时", "忽然", "突然", "居然", "竟然", "果然", "当然",
    # 单字扩展（防止两字黑名单遗漏）
    "说道", "心中", "之中", "之上", "之下", "身上", "眼中",
    "手中", "心想", "看着", "笑道", "问道", "听到", "看到",
}

# 纯数字/标点正则
_INVALID_RE = re.compile(r"[\d\W]+")


# =========================================================================
# 规则提取器
# =========================================================================


class RuleBasedExtractor:
    """基于正则的实体提取器（零 LLM 成本）"""

    def extract_entities(self, text: str, chapter: int) -> list[Entity]:
        """从文本提取实体

        Args:
            text: 章节正文
            chapter: 章节号

        Returns:
            提取到的实体列表（未去重）
        """
        entities: list[Entity] = []

        # 地名 / 势力
        for pattern in _LOCATION_PATTERNS:
            for match in pattern.finditer(text):
                name = self._clean_name(match.group(0))
                if name and self._is_valid(name):
                    entities.append(Entity(
                        canonical_name=name,
                        entity_type=EntityType.LOCATION,
                        first_mention_chapter=chapter,
                    ))

        # 功法 / 技能
        for pattern in _SKILL_PATTERNS:
            for match in pattern.finditer(text):
                full = match.group(0)
                if full.startswith("《"):
                    # 书名号模式：取括号内的内容 (group 1)
                    name = match.group(1)
                else:
                    # 后缀模式：取完整匹配并清理前缀
                    name = self._clean_name(full)
                if name and self._is_valid(name):
                    entities.append(Entity(
                        canonical_name=name,
                        entity_type=EntityType.SKILL,
                        first_mention_chapter=chapter,
                    ))

        # 称号 / 境界
        for pattern in _TITLE_PATTERNS:
            for match in pattern.finditer(text):
                name = self._clean_name(match.group(0))
                if name and self._is_valid(name):
                    entities.append(Entity(
                        canonical_name=name,
                        entity_type=EntityType.TITLE,
                        first_mention_chapter=chapter,
                    ))

        # 器物 / 宝物
        for pattern in _ARTIFACT_PATTERNS:
            for match in pattern.finditer(text):
                name = self._clean_name(match.group(0))
                if name and self._is_valid(name):
                    entities.append(Entity(
                        canonical_name=name,
                        entity_type=EntityType.ARTIFACT,
                        first_mention_chapter=chapter,
                    ))

        return entities

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_name(name: str) -> str:
        """去除匹配名称中混入的动词/虚词/介词前缀

        正则贪婪匹配可能将"来到了青云山"整体匹配，
        需要从右侧的实体后缀反向截取有意义的名词部分。
        策略：找到名称中最后一个边界字符的位置，取其后部分+后缀。
        """
        # 从后往前扫描，找到最后一个边界字符（动词/助词）的位置
        last_boundary = -1
        for i, ch in enumerate(name):
            if ch in _BOUNDARY_CHARS:
                last_boundary = i
        # 如果边界字符在前半段（说明前缀包含了非实体内容），截取其后部分
        if last_boundary >= 0 and last_boundary < len(name) - 1:
            name = name[last_boundary + 1:]
        return name

    @staticmethod
    def _is_valid(name: str) -> bool:
        """过滤无效实体（常用词、代词、过短/过长）"""
        if name in _BLACKLIST:
            return False
        if len(name) < 2 or len(name) > 8:
            return False
        if _INVALID_RE.fullmatch(name):
            return False
        return True


# =========================================================================
# LLM 提取器
# =========================================================================


class LLMEntityExtractor:
    """LLM 实体提取器（Fallback，仅关键章节使用）"""

    _SYSTEM_PROMPT = (
        "你是一个网络小说实体提取专家。从给定章节文本中提取所有重要实体。\n\n"
        "返回严格 JSON 格式：\n"
        '{\n'
        '  "entities": [\n'
        '    {"name": "青云山", "type": "location", "definition": "主角修炼的山脉"},\n'
        '    {"name": "碎星剑法", "type": "skill", "definition": "主角习得的剑术"}\n'
        '  ]\n'
        '}\n\n'
        "实体类型：character, location, faction, skill, artifact, race, "
        "title, formation, term, other\n"
        "只返回 JSON，不要其他文字。"
    )

    def __init__(self, llm_client: Any) -> None:
        self.llm = llm_client

    def extract_entities(
        self, text: str, chapter: int, max_tokens: int = 1024
    ) -> list[Entity]:
        """通过 LLM 提取实体

        Args:
            text: 章节正文（会截断到 3000 字）
            chapter: 章节号
            max_tokens: LLM 输出限制

        Returns:
            提取到的实体列表
        """
        import json as _json

        user_prompt = f"## 第{chapter}章文本\n\n{text[:3000]}"

        try:
            response = self.llm.chat(
                messages=[
                    {"role": "system", "content": self._SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                json_mode=True,
                max_tokens=max_tokens,
            )

            data = _json.loads(response.content)
            entities: list[Entity] = []
            for item in data.get("entities", []):
                name = item.get("name", "").strip()
                if not name or len(name) < 2:
                    continue
                entities.append(Entity(
                    canonical_name=name,
                    entity_type=item.get("type", EntityType.OTHER),
                    first_mention_chapter=chapter,
                    definition=item.get("definition", ""),
                ))
            return entities
        except Exception as exc:
            log.warning("LLM 实体提取失败: %s", exc)
            return []
