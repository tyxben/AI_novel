"""配音导演 Agent - 情感分析 + TTS"""
from __future__ import annotations

import re
from pathlib import Path

from src.agents.state import AgentState, Decision
from src.agents.utils import make_decision
from src.tools.tts_tool import TTSTool
from src.logger import log


EMOTION_TTS_PARAMS = {
    "平静": {"rate": "+0%", "volume": "+0%"},
    "紧张": {"rate": "+10%", "volume": "+5%"},
    "悲伤": {"rate": "-15%", "volume": "-5%"},
    "欢快": {"rate": "+20%", "volume": "+10%"},
    "激动": {"rate": "+15%", "volume": "+10%"},
}

EMOTION_RULES = [
    (r"危险|杀|血|恐怖|紧张|心跳|战斗", "紧张"),
    (r"哭|泪|悲|伤心|难过|死|离别", "悲伤"),
    (r"笑|高兴|快乐|欢|喜|开心", "欢快"),
    (r"怒|吼|爆发|愤怒|激动|震撼", "激动"),
]


class VoiceDirectorAgent:
    def __init__(self, config: dict, budget_mode: bool = False):
        self.config = config
        self.budget_mode = budget_mode
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from src.llm.llm_client import create_llm_client

            self._llm = create_llm_client(self.config.get("llm", {}))
        return self._llm

    def analyze_emotion(self, text: str) -> str:
        if self.budget_mode:
            return self._analyze_by_rules(text)
        return self._analyze_by_llm(text)

    def _analyze_by_rules(self, text: str) -> str:
        for pattern, emotion in EMOTION_RULES:
            if re.search(pattern, text):
                return emotion
        return "平静"

    def _analyze_by_llm(self, text: str) -> str:
        prompt = (
            "分析以下文本的情感基调，从选项中选一个：平静、紧张、悲伤、欢快、激动\n\n"
            f"文本：{text[:500]}\n\n仅输出一个词。"
        )
        try:
            result = self._get_llm().chat(
                messages=[{"role": "user", "content": prompt}],
            )
            emotion = result.content.strip()
            if emotion in EMOTION_TTS_PARAMS:
                return emotion
        except Exception as e:
            log.warning("LLM 情感分析失败 (%s)，回退到规则", e)
        return self._analyze_by_rules(text)

    def get_tts_params(self, emotion: str) -> dict:
        return EMOTION_TTS_PARAMS.get(emotion, EMOTION_TTS_PARAMS["平静"])


def voice_director_node(state: AgentState) -> dict:
    """VoiceDirector 节点"""
    config = state["config"]
    budget_mode = state.get("budget_mode", False)
    workspace = Path(state["workspace"])
    agent = VoiceDirectorAgent(config, budget_mode)
    tts_tool = TTSTool(config)
    decisions: list[Decision] = []

    segments = state["segments"]
    audio_files: list[str] = []
    srt_files: list[str] = []

    audio_dir = workspace / "audio"
    srt_dir = workspace / "subtitles"
    audio_dir.mkdir(parents=True, exist_ok=True)
    srt_dir.mkdir(parents=True, exist_ok=True)

    for i, seg in enumerate(segments):
        emotion = agent.analyze_emotion(seg["text"])
        params = agent.get_tts_params(emotion)

        decisions.append(make_decision(
            "VoiceDirector",
            f"emotion_seg{i}",
            f"情感={emotion}, rate={params['rate']}, volume={params['volume']}",
            f"文本: {seg['text'][:50]}...",
        ))

        audio_path = audio_dir / f"{i:04d}.mp3"
        srt_path = srt_dir / f"{i:04d}.srt"

        tts_tool.run(
            seg["text"],
            audio_path,
            srt_path,
            rate=params["rate"],
            volume=params["volume"],
        )

        audio_files.append(str(audio_path))
        srt_files.append(str(srt_path))

    log.info("[VoiceDirector] TTS 完成: %d 段音频", len(audio_files))

    return {
        "audio_files": audio_files,
        "srt_files": srt_files,
        "decisions": decisions,
    }
