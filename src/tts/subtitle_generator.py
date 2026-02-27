"""字幕生成器 - 根据 TTS 词边界生成 SRT 字幕文件"""

import re
from pathlib import Path

from src.logger import log

# 中文字幕每行理想字符数范围
_MIN_LINE_CHARS = 10
_MAX_LINE_CHARS = 15

# 回退模式下的估算语速（字符/秒）
_FALLBACK_CHARS_PER_SECOND = 5.0

# 中文标点集合，用于判断断句位置
_PUNCTUATION = set("，。！？、；：""''（）《》—…\n")


class SubtitleGenerator:
    """从 TTS 词边界数据生成 SRT 字幕文件。

    支持两种模式:
    1. 精确模式: 利用 edge-tts 返回的 word_boundaries 精确对齐
    2. 回退模式: word_boundaries 为空时，按标点拆分并估算时间
    """

    def generate_srt(
        self,
        word_boundaries: list[dict],
        text: str,
        output_path: Path,
    ) -> Path:
        """生成 SRT 字幕文件。

        Args:
            word_boundaries: TTS 引擎返回的词边界列表，每个元素为
                {"offset": float, "duration": float, "text": str}。
            text: 原始文本（用于回退模式）。
            output_path: SRT 文件输出路径。

        Returns:
            output_path，方便链式调用。
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        text = (text or "").strip()
        if not text:
            log.warning("字幕生成收到空文本，写入空 SRT")
            output_path.write_text("", encoding="utf-8")
            return output_path

        if word_boundaries:
            entries = self._build_from_boundaries(word_boundaries)
        else:
            log.info("无词边界数据，使用回退模式按标点拆分生成字幕")
            entries = self._build_fallback(text)

        srt_content = self._render_srt(entries)
        output_path.write_text(srt_content, encoding="utf-8")
        log.debug("字幕写入: %s (%d 条)", output_path.name, len(entries))
        return output_path

    # ------------------------------------------------------------------
    # 精确模式：从词边界构建字幕
    # ------------------------------------------------------------------

    def _build_from_boundaries(
        self, word_boundaries: list[dict]
    ) -> list[dict]:
        """将词边界按字符数分组为字幕条目。

        每条字幕累积 _MIN_LINE_CHARS ~ _MAX_LINE_CHARS 个字符，
        在标点处优先断行。

        Returns:
            [{"start": float, "end": float, "text": str}, ...]
        """
        entries: list[dict] = []
        group_words: list[dict] = []
        group_text = ""

        for wb in word_boundaries:
            group_words.append(wb)
            group_text += wb["text"]

            should_break = False

            # 达到最大字符数时强制断行
            if len(group_text) >= _MAX_LINE_CHARS:
                should_break = True
            # 达到最小字符数且当前词以标点结尾时优先断行
            elif len(group_text) >= _MIN_LINE_CHARS and self._ends_with_punctuation(
                wb["text"]
            ):
                should_break = True

            if should_break:
                entries.append(self._flush_group(group_words, group_text))
                group_words = []
                group_text = ""

        # 处理尾部剩余
        if group_words:
            entries.append(self._flush_group(group_words, group_text))

        return entries

    @staticmethod
    def _flush_group(group_words: list[dict], group_text: str) -> dict:
        """将一组词边界合并为单条字幕条目。"""
        start = group_words[0]["offset"]
        last = group_words[-1]
        end = last["offset"] + last["duration"]
        # 保证最短显示 0.3 秒，避免闪烁
        if end - start < 0.3:
            end = start + 0.3
        return {"start": start, "end": end, "text": group_text.strip()}

    # ------------------------------------------------------------------
    # 回退模式：按标点拆分 + 估算时间
    # ------------------------------------------------------------------

    def _build_fallback(self, text: str) -> list[dict]:
        """无词边界时的回退策略：按标点拆分，按语速估算时间。

        Returns:
            [{"start": float, "end": float, "text": str}, ...]
        """
        segments = self._split_by_punctuation(text)
        entries: list[dict] = []
        current_time = 0.0

        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            duration = len(seg) / _FALLBACK_CHARS_PER_SECOND
            # 最短 0.5 秒，避免闪烁
            duration = max(duration, 0.5)
            entries.append(
                {
                    "start": current_time,
                    "end": current_time + duration,
                    "text": seg,
                }
            )
            current_time += duration

        return entries

    @staticmethod
    def _split_by_punctuation(text: str) -> list[str]:
        """按中文标点将文本拆分为若干短句。"""
        # 在标点后断开，保留标点在前一段
        parts = re.split(r"(?<=[，。！？、；：\n])", text)
        # 合并过短的片段
        merged: list[str] = []
        current = ""
        for part in parts:
            if not part.strip():
                continue
            current += part
            if len(current) >= _MIN_LINE_CHARS or current.strip()[-1:] in "。！？":
                merged.append(current)
                current = ""
        if current.strip():
            merged.append(current)
        return merged

    # ------------------------------------------------------------------
    # SRT 渲染
    # ------------------------------------------------------------------

    @staticmethod
    def _render_srt(entries: list[dict]) -> str:
        """将字幕条目列表渲染为标准 SRT 格式字符串。"""
        lines: list[str] = []
        for idx, entry in enumerate(entries, start=1):
            start_ts = SubtitleGenerator._format_timestamp(entry["start"])
            end_ts = SubtitleGenerator._format_timestamp(entry["end"])
            lines.append(str(idx))
            lines.append(f"{start_ts} --> {end_ts}")
            lines.append(entry["text"])
            lines.append("")  # SRT 条目之间的空行
        return "\n".join(lines)

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """将秒数转换为 SRT 时间戳格式 HH:MM:SS,mmm。

        Args:
            seconds: 时间（秒），非负。

        Returns:
            格式化后的时间戳字符串，如 "00:01:23,456"。
        """
        seconds = max(0.0, seconds)
        total_ms = int(round(seconds * 1000))
        hours, remainder = divmod(total_ms, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, ms = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"

    @staticmethod
    def _ends_with_punctuation(text: str) -> bool:
        """检查文本是否以中文标点结尾。"""
        return bool(text) and text[-1] in _PUNCTUATION
