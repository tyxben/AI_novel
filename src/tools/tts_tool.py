from __future__ import annotations

from pathlib import Path
from typing import Any


class TTSTool:
    """封装 TTS 配音 + 字幕模块，供 Agent 节点调用。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._engine: Any = None
        self._sub_gen: Any = None

    def _get_engine(self) -> Any:
        if self._engine is None:
            from src.tts.tts_engine import TTSEngine

            self._engine = TTSEngine(self.config["tts"])
        return self._engine

    def _get_sub_gen(self) -> Any:
        if self._sub_gen is None:
            from src.tts.subtitle_generator import SubtitleGenerator

            self._sub_gen = SubtitleGenerator()
        return self._sub_gen

    def run(
        self,
        text: str,
        audio_path: Path,
        srt_path: Path,
        rate: str | None = None,
        volume: str | None = None,
    ) -> tuple[Path, Path]:
        engine = self._get_engine()
        # 动态 TTS 参数
        if rate or volume:
            tts_cfg = dict(self.config["tts"])
            if rate:
                tts_cfg["rate"] = rate
            if volume:
                tts_cfg["volume"] = volume
            from src.tts.tts_engine import TTSEngine

            engine = TTSEngine(tts_cfg)

        audio, word_boundaries = engine.synthesize(text, audio_path)
        self._get_sub_gen().generate_srt(word_boundaries, text, srt_path)
        return audio_path, srt_path
