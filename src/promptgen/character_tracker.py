"""角色追踪器 - 维护角色外观描述以保持视觉一致性"""

import re
import logging
from typing import Any

log = logging.getLogger("novel")

# 常见单字动词（出现在名字后面，用于识别「姓名+动作」结构）
_VERB_CHARS = frozenset(
    "说道想看见听笑哭走跑站坐来去回答问喊叫叹摇点"
    "抬低转起望知把将被从在向对给用拿拉推打举落飞倒停"
    "扶握抱放开关入出到过"
)

# 常见多字动词/副词前缀（紧跟在名字后面）
_VERB_PREFIXES = [
    "觉得", "起身", "微微", "忽然", "突然", "缓缓", "默默",
    "轻轻", "慢慢", "连忙", "赶紧", "急忙", "一把", "一声",
]

# 句首/标点后的位置标记
_BOUNDARY = r"(?:^|(?<=[，。！？；：、\s\"\"''「」\n]))"

# 从英文 prompt 中提取角色描述的模式
_DESCRIPTION_PATTERN = re.compile(
    r"(?:a |the )?"
    r"(?:young |old |beautiful |handsome |tall |short )?"
    r"(?:man|woman|girl|boy|person|warrior|scholar|maiden|elder|child)"
    r"[^,]*",
    re.IGNORECASE,
)

# 需要排除的常见非姓名词语（代词、副词、连词、常见词等）
_EXCLUDED_WORDS = frozenset({
    # 代词
    "这个", "那个", "什么", "怎么", "一个", "自己", "他们", "她们",
    "我们", "你们", "大家", "所有", "这些", "那些", "某个", "每个",
    # 副词/连词
    "已经", "现在", "然后", "但是", "因为", "所以", "如果", "虽然",
    "不过", "而且", "只是", "可是", "还是", "就是", "终于", "突然",
    "忽然", "于是", "不禁", "居然", "竟然", "原来", "果然", "毕竟",
    "一直", "一起", "一样", "不要", "不能", "可以", "应该", "必须",
    "连忙", "赶紧", "急忙", "慌忙", "立刻", "马上", "随即", "随后",
    # 常见名词（非人名）
    "这里", "那里", "哪里", "时候", "地方", "东西", "事情", "今天",
    "明天", "昨天", "还好", "不好", "很好", "没有", "知道", "以为",
    "觉得", "认为", "希望", "害怕", "担心", "高兴", "难过", "生气",
    # 亲属/称呼词（非独立角色名）
    "哥哥", "姐姐", "弟弟", "妹妹", "爸爸", "妈妈", "爷爷", "奶奶",
    "叔叔", "阿姨", "伯伯", "婶婶", "公公", "婆婆", "丫鬟", "小姐",
    "公子", "先生", "夫人", "老爷", "太太", "师父", "徒弟", "师兄",
    "师姐", "师弟", "师妹", "朋友", "兄弟", "姑娘", "少年", "老人",
    "孩子", "女子", "男子", "少女", "老者", "此人", "那人", "众人",
})

# 匹配引号中的称呼（对话中提到的人名，如 "黛玉" ）
_QUOTED_NAME_PATTERN = re.compile(
    r"[\"\"'「]"           # 开引号
    r"([\u4e00-\u9fff]{2,4})"  # 2-4 个汉字的名字
    r"[\"\"'」]"           # 闭引号
)


def _is_verb_at(text: str, pos: int) -> bool:
    """检查 text[pos] 位置是否是动词/副词的开头。"""
    if pos >= len(text):
        return False
    # 先检查多字动词前缀
    for vp in _VERB_PREFIXES:
        if text[pos:pos + len(vp)] == vp:
            return True
    # 再检查单字动词
    return text[pos] in _VERB_CHARS


def _extract_names_from_text(text: str) -> list[tuple[str, int]]:
    """从文本中提取「姓名+动词」模式的角色名。

    使用正向扫描策略: 找到句首/标点后的 2-3 个汉字序列，
    然后检查紧随其后的字符是否为动词。优先尝试 2 字匹配
    （因为中文姓名绝大多数为 2-3 字，且 2 字名+单字动词更常见）。

    Returns:
        (角色名, 文本位置) 的列表。
    """
    # 找到所有可能的名字起始位置（句首/标点后的汉字序列）
    pattern = re.compile(
        _BOUNDARY + r"([\u4e00-\u9fff]{2,3})",
    )

    results: list[tuple[str, int]] = []
    for match in pattern.finditer(text):
        full = match.group(1)
        start = match.start()

        if len(full) == 3:
            # 计算 2 字名和 3 字名之后的位置
            pos_after_2 = match.start() + len(full[:2])  # absolute pos after 2-char name
            pos_after_3 = match.end()                      # absolute pos after 3-char name

            # 检查「2字名 + 动词」是否成立（优先：更常见的模式）
            if _is_verb_at(text, pos_after_2):
                # "宝玉笑道" -> "宝玉" + "笑道"
                results.append((full[:2], start))
            elif _is_verb_at(text, pos_after_3):
                # "李云飞拔" -> "李云飞" + "拔" (3字名成立)
                results.append((full, start))
            # else: 既不是 2 字名也不是 3 字名，跳过

        elif len(full) == 2:
            # 2 字名: 检查紧随其后是否为动词
            end2 = match.end()
            if _is_verb_at(text, end2):
                results.append((full, start))

    return results


class CharacterTracker:
    """角色视觉描述追踪器。

    维护一个「角色名 -> 外观描述」的映射表，用于在多段文本的
    Prompt 生成中保持同一角色的视觉一致性。
    """

    def __init__(self) -> None:
        self._characters: dict[str, str] = {}
        self._mention_count: dict[str, int] = {}

    @property
    def known_characters(self) -> dict[str, str]:
        """返回当前已知角色及其描述的副本。"""
        return dict(self._characters)

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def extract_characters(self, text: str) -> list[str]:
        """从中文文本中提取角色名。

        使用正则匹配「汉字 + 动词」模式和引号中的称呼来识别角色名。
        通过出现频率过滤误匹配。

        Args:
            text: 中文小说文本片段。

        Returns:
            去重后的角色名列表。
        """
        if not text or not text.strip():
            return []

        candidates: dict[str, int] = {}

        # 模式 1: 姓名 + 动词
        for name, _pos in _extract_names_from_text(text):
            # 排除完整名和名字的 2 字前缀都在排除列表中的情况
            if name in _EXCLUDED_WORDS:
                continue
            if len(name) == 3 and name[:2] in _EXCLUDED_WORDS:
                continue
            candidates[name] = candidates.get(name, 0) + 1

        # 模式 2: 引号中的名字（对话中出现的称呼，限 2-3 字）
        for match in _QUOTED_NAME_PATTERN.finditer(text):
            name = match.group(1)
            if name not in _EXCLUDED_WORDS and len(name) <= 3:
                candidates[name] = candidates.get(name, 0) + 1

        # 更新全局出现次数
        for name, count in candidates.items():
            self._mention_count[name] = self._mention_count.get(name, 0) + count

        # 在本段出现至少 1 次即视为角色名
        characters = list(candidates.keys())
        return characters

    def get_character_prompt(self, characters: list[str]) -> str:
        """为已知角色生成描述性 prompt 片段。

        Args:
            characters: 角色名列表。

        Returns:
            英文描述字符串，用于拼接到 SD prompt 中。
            如果没有任何已知角色信息，返回空字符串。
        """
        descriptions: list[str] = []
        seen: set[str] = set()

        for name in characters:
            if name in self._characters and self._characters[name]:
                desc = self._characters[name]
                if desc not in seen:
                    descriptions.append(desc)
                    seen.add(desc)

        return ", ".join(descriptions)

    def update(self, text: str, prompt: str) -> None:
        """从生成的 prompt 中学习角色外观描述。

        将文本中出现的角色名与 prompt 中的人物描述关联起来。
        仅在角色尚无描述时更新（首次描述优先，保持一致性）。

        Args:
            text: 原始中文文本片段。
            prompt: 已生成的英文 SD prompt。
        """
        characters = self.extract_characters(text)
        if not characters:
            return

        # 从 prompt 中提取人物描述片段
        desc_matches = _DESCRIPTION_PATTERN.findall(prompt)
        if not desc_matches:
            return

        # 将描述按顺序分配给本段出现的角色
        # 只更新尚无描述的角色，保持首次描述的一致性
        desc_queue = list(desc_matches)
        for char_name in characters:
            if char_name not in self._characters and desc_queue:
                description = desc_queue.pop(0).strip().rstrip(",").strip()
                if description:
                    self._characters[char_name] = description
                    log.debug("角色描述更新: %s -> %s", char_name, description)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（用于存储/恢复状态）。"""
        return {
            "characters": dict(self._characters),
            "mention_count": dict(self._mention_count),
        }

    def from_dict(self, data: dict[str, Any]) -> None:
        """从字典恢复状态。"""
        self._characters = dict(data.get("characters", {}))
        self._mention_count = dict(data.get("mention_count", {}))
