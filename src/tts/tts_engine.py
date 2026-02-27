"""TTS 引擎 - 基于 edge-tts 的语音合成"""

import asyncio
from pathlib import Path

from src.logger import log

# 单段文本最大字符数，超过此长度会分块合成后拼接
_MAX_CHUNK_CHARS = 5000


class TTSEngine:
    """Edge-TTS 语音合成引擎。

    将文本转为 MP3 音频，同时收集单词边界事件用于字幕对齐。

    Args:
        config: TTS 配置字典，可包含以下字段:
            voice   - 语音名称，默认 zh-CN-YunxiNeural
            rate    - 语速调节，如 "+0%"、"-10%"
            volume  - 音量调节，如 "+0%"、"+20%"
    """

    def __init__(self, config: dict) -> None:
        self.voice: str = config.get("voice", "zh-CN-YunxiNeural")
        self.rate: str = config.get("rate", "+0%")
        self.volume: str = config.get("volume", "+0%")

    # ------------------------------------------------------------------
    # Public API (synchronous)
    # ------------------------------------------------------------------

    def synthesize(self, text: str, output_path: Path) -> tuple[Path, list[dict]]:
        """将文本合成为 MP3 音频并返回单词边界信息。

        Args:
            text: 待合成的文本。
            output_path: 音频输出路径（.mp3）。

        Returns:
            (output_path, word_boundaries) 元组。
            word_boundaries 列表中每个元素为:
                {"offset": float, "duration": float, "text": str}
            其中 offset 和 duration 单位为秒。
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        text = (text or "").strip()
        if not text:
            log.warning("TTS 收到空文本，生成静音占位文件")
            return self._generate_silent_placeholder(output_path)

        # edge_tts 是纯异步库，在同步上下文中用 asyncio.run 驱动
        try:
            audio_path, boundaries = asyncio.run(
                self._synthesize_async(text, output_path)
            )
        except Exception as exc:
            log.error("TTS 合成失败: %s", exc)
            raise

        log.debug(
            "TTS 完成: %s (词边界 %d 条)", output_path.name, len(boundaries)
        )
        return audio_path, boundaries

    # ------------------------------------------------------------------
    # Async internals
    # ------------------------------------------------------------------

    async def _synthesize_async(
        self, text: str, output_path: Path
    ) -> tuple[Path, list[dict]]:
        """异步执行 edge-tts 合成，收集音频数据与词边界事件。"""
        import edge_tts

        # 对超长文本进行分块处理
        if len(text) > _MAX_CHUNK_CHARS:
            return await self._synthesize_long_text(text, output_path)

        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume,
        )

        word_boundaries: list[dict] = []
        sentence_boundaries: list[dict] = []
        audio_chunks: list[bytes] = []

        async for event in communicate.stream():
            if event["type"] == "audio":
                audio_chunks.append(event["data"])
            elif event["type"] == "WordBoundary":
                word_boundaries.append(
                    {
                        "offset": event["offset"] / 10_000_000,  # 100ns ticks -> seconds
                        "duration": event["duration"] / 10_000_000,
                        "text": event["text"],
                    }
                )
            elif event["type"] == "SentenceBoundary":
                sentence_boundaries.append(
                    {
                        "offset": event["offset"] / 10_000_000,
                        "duration": event["duration"] / 10_000_000,
                        "text": event["text"],
                    }
                )

        if not audio_chunks:
            raise RuntimeError("edge-tts 未返回任何音频数据")

        output_path.write_bytes(b"".join(audio_chunks))
        # 中文 edge-tts 通常只返回 SentenceBoundary，WordBoundary 为空
        boundaries = word_boundaries if word_boundaries else sentence_boundaries
        return output_path, boundaries

    async def _synthesize_long_text(
        self, text: str, output_path: Path
    ) -> tuple[Path, list[dict]]:
        """分块合成超长文本，拼接音频与词边界。

        按中文标点 / 换行拆分为多块，逐块合成后拼接。
        """
        import edge_tts

        chunks = self._split_long_text(text)
        log.info("长文本分 %d 块合成", len(chunks))

        all_audio: list[bytes] = []
        all_boundaries: list[dict] = []
        all_sentence_boundaries: list[dict] = []
        cumulative_offset: float = 0.0

        for chunk in chunks:
            communicate = edge_tts.Communicate(
                text=chunk,
                voice=self.voice,
                rate=self.rate,
                volume=self.volume,
            )

            chunk_audio: list[bytes] = []
            chunk_last_end: float = 0.0

            async for event in communicate.stream():
                if event["type"] == "audio":
                    chunk_audio.append(event["data"])
                elif event["type"] in ("WordBoundary", "SentenceBoundary"):
                    offset_sec = event["offset"] / 10_000_000
                    duration_sec = event["duration"] / 10_000_000
                    entry = {
                        "offset": cumulative_offset + offset_sec,
                        "duration": duration_sec,
                        "text": event["text"],
                    }
                    if event["type"] == "WordBoundary":
                        all_boundaries.append(entry)
                    else:
                        all_sentence_boundaries.append(entry)
                    end_of_word = offset_sec + duration_sec
                    if end_of_word > chunk_last_end:
                        chunk_last_end = end_of_word

            all_audio.extend(chunk_audio)
            # 推进累积偏移：取本块最后一个词边界的结束时间
            cumulative_offset += chunk_last_end

        if not all_audio:
            raise RuntimeError("edge-tts 未返回任何音频数据（长文本模式）")

        output_path.write_bytes(b"".join(all_audio))
        boundaries = all_boundaries if all_boundaries else all_sentence_boundaries
        return output_path, boundaries

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_long_text(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
        """按中文标点或换行将长文本拆分为较短的块。"""
        import re

        # 优先在句号、问号、感叹号、换行处断开
        sentences = re.split(r"(?<=[。！？\n])", text)
        chunks: list[str] = []
        current = ""

        for sentence in sentences:
            if not sentence:
                continue
            if len(current) + len(sentence) > max_chars and current:
                chunks.append(current)
                current = sentence
            else:
                current += sentence

        if current:
            chunks.append(current)

        return chunks if chunks else [text]

    @staticmethod
    def _generate_silent_placeholder(output_path: Path) -> tuple[Path, list[dict]]:
        """为空文本生成一段极短的静音 MP3 占位文件。

        生成最小合规 MP3 帧 (MPEG1 Layer3, 128kbps, 44100Hz, 单声道)。
        """
        # 最小 MP3: 一个有效帧头 + 静音帧数据 (417 bytes for 128kbps 44100Hz)
        # 使用合规的 MPEG1 Layer3 帧头: 0xFFFB9004
        frame_header = bytes([0xFF, 0xFB, 0x90, 0x04])
        silence_frame = frame_header + b"\x00" * 413
        output_path.write_bytes(silence_frame)
        return output_path, []
