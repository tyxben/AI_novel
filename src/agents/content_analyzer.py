"""内容分析 Agent - 分析小说类型、角色、风格"""
from __future__ import annotations

import re

from src.agents.state import AgentState, Decision
from src.agents.utils import make_decision, extract_json_obj, extract_json_array
from src.tools.segment_tool import SegmentTool
from src.logger import log


# 风格映射
STYLE_MAP = {
    ("武侠", "古代"): "chinese_ink",
    ("玄幻", "架空"): "anime",
    ("都市", "现代"): "realistic",
    ("科幻", "未来"): "cyberpunk",
    ("言情", "现代"): "watercolor",
}

# 规则分类
GENRE_RULES = [
    (r"修炼|法宝|灵气|宗门|渡劫|仙|丹药", "玄幻", "架空"),
    (r"江湖|剑气|武功|内力|掌门|侠客", "武侠", "古代"),
    (r"公司|手机|互联网|地铁|外卖|办公室", "都市", "现代"),
    (r"星际|宇宙飞船|机器人|AI|赛博", "科幻", "未来"),
    (r"爱情|恋爱|男朋友|女朋友|心动|甜蜜", "言情", "现代"),
    (r"皇上|朕|太后|将军|丫鬟|府邸", "历史", "古代"),
]


class ContentAnalyzerAgent:
    def __init__(self, config: dict, budget_mode: bool = False):
        self.config = config
        self.budget_mode = budget_mode
        self._llm = None

    def _get_llm(self):
        """懒加载 LLM"""
        if self._llm is None:
            from src.llm.llm_client import create_llm_client

            llm_cfg = dict(self.config.get("llm", {}))
            self._llm = create_llm_client(llm_cfg)
        return self._llm

    def classify_genre(self, text: str) -> dict:
        if self.budget_mode:
            return self._classify_by_rules(text)
        return self._classify_by_llm(text)

    def _classify_by_rules(self, text: str) -> dict:
        sample = text[:2000]
        for pattern, genre, era in GENRE_RULES:
            if re.search(pattern, sample):
                return {"genre": genre, "era": era, "confidence": 0.8}
        return {"genre": "其他", "era": "现代", "confidence": 0.5}

    def _classify_by_llm(self, text: str) -> dict:
        sample = text[:1000]
        prompt = (
            "你是小说类型分析专家。分析以下文本，判断类型和时代背景。\n"
            "可选类型：武侠、玄幻、都市、言情、科幻、悬疑、历史、其他\n"
            "可选时代：古代、现代、未来、架空\n\n"
            f"文本：\n{sample}\n\n"
            '输出 JSON：{{"genre": "类型", "era": "时代", "confidence": 0.0-1.0}}'
        )
        try:
            result = self._get_llm().chat(
                messages=[{"role": "user", "content": prompt}],
                json_mode=True,
            )
            data = extract_json_obj(result.content)
            if data and "genre" in data:
                return data
        except Exception as e:
            log.warning("LLM 分类失败 (%s)，回退到规则", e)
        return self._classify_by_rules(text)

    def extract_characters(self, text: str) -> list[dict]:
        if self.budget_mode:
            return self._extract_characters_by_rules(text)
        return self._extract_characters_by_llm(text)

    def _extract_characters_by_rules(self, text: str) -> list[dict]:
        # 使用非贪婪匹配，确保提取人名而非"人名+动词"
        matches = re.findall(
            r"([\u4e00-\u9fa5]{2,4}?)(?:说道|问道|笑道|喊道|道|说)", text[:3000]
        )
        names = list(dict.fromkeys(matches))[:5]
        return [{"name": n, "desc": ""} for n in names]

    def _extract_characters_by_llm(self, text: str) -> list[dict]:
        prompt = (
            "分析以下小说片段，提取主要角色（最多5个）。\n\n"
            f"文本：\n{text[:2000]}\n\n"
            '输出 JSON 数组：[{{"name": "姓名", "desc": "外貌/服装/特征简述"}}]'
        )
        try:
            result = self._get_llm().chat(
                messages=[{"role": "user", "content": prompt}],
                json_mode=True,
            )
            data = extract_json_array(result.content)
            if data:
                return data
        except Exception as e:
            log.warning("LLM 角色提取失败 (%s)，回退到规则", e)
        return self._extract_characters_by_rules(text)

    def suggest_style(self, genre: str, era: str) -> str:
        return STYLE_MAP.get((genre, era), "anime")


def content_analyzer_node(state: AgentState) -> dict:
    """ContentAnalyzer 节点"""
    config = state["config"]
    budget_mode = state.get("budget_mode", False)
    agent = ContentAnalyzerAgent(config, budget_mode)
    decisions: list[Decision] = []

    # 1. 分段
    seg_tool = SegmentTool(config)
    segments = seg_tool.run(state["full_text"])

    decisions.append(make_decision(
        "ContentAnalyzer", "segment",
        f"分段完成：{len(segments)} 段",
        f"方法={config.get('segmenter', {}).get('method', 'simple')}",
    ))

    # 2. 类型分析
    genre_info = agent.classify_genre(state["full_text"])

    decisions.append(make_decision(
        "ContentAnalyzer", "classify",
        f"类型={genre_info['genre']}, 时代={genre_info.get('era', '未知')}",
        f"置信度={genre_info.get('confidence', 0)}",
    ))

    # 3. 角色提取
    characters = agent.extract_characters(state["full_text"])
    decisions.append(make_decision(
        "ContentAnalyzer", "extract_characters",
        f"提取 {len(characters)} 个角色",
        f"角色: {[c['name'] for c in characters]}",
    ))

    # 4. 风格推荐
    style = agent.suggest_style(genre_info["genre"], genre_info.get("era", "现代"))
    decisions.append(make_decision(
        "ContentAnalyzer", "suggest_style",
        f"推荐风格={style}",
        f"基于类型={genre_info['genre']}, 时代={genre_info.get('era')}",
    ))

    log.info(
        "[ContentAnalyzer] %s/%s风格, %d段, %d角色",
        genre_info["genre"],
        style,
        len(segments),
        len(characters),
    )

    return {
        "segments": segments,
        "genre": genre_info["genre"],
        "era": genre_info.get("era"),
        "characters": characters,
        "suggested_style": style,
        "decisions": decisions,
    }
