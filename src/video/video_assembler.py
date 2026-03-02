"""视频合成器 - 基于 FFmpeg 的视频组装流水线

将静态图片、语音音频和 SRT 字幕合成为最终 MP4 视频。
主要流程:
  1. 每组素材（图片 + 音频 + 字幕）按 SRT 条目拆分为子片段，
     每个子片段只显示对应时间点的字幕文本
  2. Ken Burns 特效在子片段间保持连续（按时间比例分配 zoom 范围）
  3. 使用 FFmpeg concat demuxer 拼接所有片段
  4. 可选混入背景音乐
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.logger import log
from src.utils.ffmpeg_helper import ensure_ffmpeg
from src.video.effects import ken_burns_filter


def _find_cjk_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """跨平台查找 CJK 字体。

    按平台依次尝试常见中文字体路径，全部失败则返回默认字体。
    """
    system = platform.system()

    candidates: list[str] = []
    if system == "Darwin":
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
    elif system == "Linux":
        candidates = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        ]
        # 尝试 fc-match 自动查找
        try:
            result = subprocess.run(
                ["fc-match", "-f", "%{file}", ":lang=zh"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                candidates.append(result.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    elif system == "Windows":
        candidates = [
            "C:\\Windows\\Fonts\\msyh.ttc",     # Microsoft YaHei
            "C:\\Windows\\Fonts\\simsun.ttc",    # SimSun
            "C:\\Windows\\Fonts\\simhei.ttf",    # SimHei
        ]

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue

    log.warning("未找到 CJK 字体，字幕可能无法正确显示中文。请安装 Noto Sans CJK 或其他中文字体。")
    return ImageFont.load_default()


def _parse_srt_time(time_str: str) -> float:
    """解析 SRT 时间码 ``HH:MM:SS,mmm`` 为秒数。"""
    time_str = time_str.replace(",", ".")
    parts = time_str.split(":")
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])


class VideoAssembler:
    """FFmpeg 视频合成器。

    Args:
        config: 视频配置字典（对应 config.yaml 中的 ``video`` 段）。
        workspace: 工作目录，用于存放临时文件。
    """

    def _codec_flags(self) -> list[str]:
        """编码器相关的 FFmpeg 参数。"""
        flags = ["-c:v", self.codec, "-crf", str(self.crf)]
        if self.codec == "libx265":
            # hvc1 tag 确保 Apple/抖音/小红书兼容
            flags += ["-tag:v", "hvc1"]
        return flags

    @staticmethod
    def _default_crf(codec: str) -> int:
        """不同编码器的默认 CRF（同等画质）。"""
        # H.265 同画质下 CRF 比 H.264 高 ~4-6
        return {"libx264": 18, "libx265": 23, "libsvtav1": 28}.get(codec, 18)

    def __init__(self, config: dict, workspace: Path) -> None:
        self.width: int = config["resolution"][0]
        self.height: int = config["resolution"][1]
        self.fps: int = config.get("fps", 30)
        self.codec: str = config.get("codec", "libx265")
        self.crf: int = config.get("crf", self._default_crf(self.codec))

        # Ken Burns 参数
        kb_cfg = config.get("ken_burns", {})
        zr = kb_cfg.get("zoom_range", [1.0, 1.15])
        self.zoom_range: tuple[float, float] = (float(zr[0]), float(zr[1]))

        # 转场参数
        tr_cfg = config.get("transition", {})
        self.transition_duration: float = float(tr_cfg.get("duration", 0.5))

        # 背景音乐参数
        bgm_cfg = config.get("bgm", {})
        bgm_path = bgm_cfg.get("path", "")
        self.bgm_path: Path | None = Path(bgm_path) if bgm_path else None
        self.bgm_volume: float = float(bgm_cfg.get("volume", 0.15))

        # 临时文件目录
        self.tmp_dir: Path = Path(workspace) / "tmp_video"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assemble(
        self,
        images: list[Path],
        audio_srt: list[dict],
        output_path: Path,
        video_clips: list[Path] | None = None,
    ) -> Path:
        """执行完整的视频组装流水线。

        Args:
            images:      与各段对应的图片路径列表。
            audio_srt:   每段的音频和字幕信息列表，每个元素为
                         ``{"audio": Path, "srt": Path}``。
            output_path: 最终输出的 MP4 文件路径。
            video_clips: 可选的 AI 生成视频片段列表。当提供时，使用视频片段
                         替代静态图 + Ken Burns 特效，仅做音频替换和字幕叠加。

        Returns:
            输出文件路径。
        """
        if len(images) != len(audio_srt):
            raise ValueError(
                f"图片数量 ({len(images)}) 与音频/字幕数量 "
                f"({len(audio_srt)}) 不匹配"
            )

        use_video_clips = (
            video_clips is not None
            and len(video_clips) == len(audio_srt)
        )
        if video_clips and not use_video_clips:
            log.warning(
                "视频片段数量 (%d) 与音频/字幕数量 (%d) 不匹配，回退到静态图模式",
                len(video_clips), len(audio_srt),
            )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        mode_desc = "AI 视频片段" if use_video_clips else "静态图"
        log.info("开始视频合成 (%s模式): %d 个片段", mode_desc, len(images))

        # -- 第 1 步: 为每段素材创建片段视频 --
        clips: list[Path] = []
        for idx, (img, entry) in enumerate(zip(images, audio_srt)):
            audio_path = Path(entry["audio"])
            srt_path = Path(entry["srt"])
            duration = self._get_audio_duration(audio_path)

            if use_video_clips:
                clip = self._make_video_clip_segment(
                    idx=idx,
                    video=video_clips[idx],
                    audio=audio_path,
                    srt=srt_path,
                    target_duration=duration,
                )
            else:
                clip = self._make_segment_clip(
                    idx=idx,
                    image=img,
                    audio=audio_path,
                    srt=srt_path,
                    duration=duration,
                )
            clips.append(clip)
            log.info("片段 %d/%d 完成", idx + 1, len(images))

        # -- 第 2 步: 拼接所有片段 --
        if len(clips) == 1:
            concat_out = clips[0]
        else:
            concat_out = self.tmp_dir / "concat_output.mp4"
            self._concatenate(clips, concat_out)

        # -- 第 3 步: 混入背景音乐（可选）--
        if self.bgm_path and self.bgm_path.exists():
            log.info("混入背景音乐: %s (音量 %.2f)", self.bgm_path, self.bgm_volume)
            self._add_bgm(concat_out, self.bgm_path, self.bgm_volume, output_path)
        else:
            # 无 BGM，直接复制/移动到输出路径
            self._ffmpeg_copy(concat_out, output_path)

        log.info("视频合成完成: %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # 探针: 获取音频时长
    # ------------------------------------------------------------------

    def _get_audio_duration(self, audio_path: Path) -> float:
        """使用 ffprobe 获取音频文件时长（秒）。

        Args:
            audio_path: 音频文件路径。

        Returns:
            时长（秒），浮点数。

        Raises:
            FileNotFoundError: ffprobe 未安装。
            RuntimeError: ffprobe 执行失败或输出解析异常。
        """
        ensure_ffmpeg()

        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(audio_path),
        ]
        log.debug("ffprobe 命令: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"ffprobe 执行失败 (exit code {exc.returncode}): {audio_path}\n"
                f"stderr: {exc.stderr[:500] if exc.stderr else '(empty)'}"
            ) from exc

        try:
            info = json.loads(result.stdout)
            duration = float(info["format"]["duration"])
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"ffprobe 输出解析失败: {audio_path}\n"
                f"原始输出: {result.stdout[:500]}"
            ) from exc

        log.debug("音频时长: %.2fs - %s", duration, audio_path.name)
        return duration

    # ------------------------------------------------------------------
    # SRT 解析
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_srt_entries(srt_path: Path) -> list[dict]:
        """解析 SRT 文件，返回带时间信息的字幕条目列表。

        Returns:
            [{"start": float, "end": float, "text": str}, ...]
        """
        if not srt_path.exists():
            return []
        text = srt_path.read_text(encoding="utf-8").strip()
        if not text:
            return []

        entries: list[dict] = []
        current_entry: dict = {}
        text_lines: list[str] = []

        for line in text.splitlines():
            line = line.strip()
            if not line:
                # 空行 = 条目结束
                if text_lines and "start" in current_entry:
                    current_entry["text"] = "".join(text_lines)
                    if current_entry["end"] > current_entry["start"]:
                        entries.append(current_entry)
                    else:
                        log.warning(
                            "跳过无效 SRT 条目: end (%.3fs) <= start (%.3fs)",
                            current_entry["end"], current_entry["start"],
                        )
                current_entry = {}
                text_lines = []
            elif "-->" in line:
                # 时间码行: 00:00:01,000 --> 00:00:03,500
                parts = line.split("-->")
                current_entry["start"] = _parse_srt_time(parts[0].strip())
                current_entry["end"] = _parse_srt_time(parts[1].strip())
            elif line.isdigit():
                # 序号行，跳过
                pass
            else:
                text_lines.append(line)

        # 处理末尾无空行的最后一条
        if text_lines and "start" in current_entry:
            current_entry["text"] = "".join(text_lines)
            if current_entry["end"] > current_entry["start"]:
                entries.append(current_entry)

        return entries

    # ------------------------------------------------------------------
    # 子片段构建（处理 SRT 条目间隙）
    # ------------------------------------------------------------------

    @staticmethod
    def _build_sub_segments(
        entries: list[dict], segment_duration: float
    ) -> list[dict]:
        """构建子片段列表，处理 SRT 条目间的间隙。

        策略:
        - 间隙 < 0.3s: 延伸前一条目的 end（或首条目的 start）
        - 间隙 >= 0.3s: 插入无字幕子片段
        """
        if not entries:
            return [{"start": 0.0, "end": segment_duration, "text": ""}]

        entries = sorted(entries, key=lambda e: e["start"])
        result: list[dict] = []
        current_time = 0.0

        for entry in entries:
            entry_start = entry["start"]
            entry_end = entry["end"]
            text = entry.get("text", "")

            gap = entry_start - current_time
            if gap >= 0.3:
                # 大间隙: 插入无字幕子片段
                result.append({
                    "start": current_time,
                    "end": entry_start,
                    "text": "",
                })
            elif gap > 0:
                # 小间隙: 延伸前一条目或调整当前条目
                if result:
                    result[-1]["end"] = entry_start
                else:
                    entry_start = current_time

            result.append({
                "start": entry_start,
                "end": entry_end,
                "text": text,
            })
            current_time = entry_end

        # 处理尾部间隙
        gap = segment_duration - current_time
        if gap >= 0.3:
            result.append({
                "start": current_time,
                "end": segment_duration,
                "text": "",
            })
        elif gap > 0 and result:
            result[-1]["end"] = segment_duration

        return result

    # ------------------------------------------------------------------
    # 单段片段制作
    # ------------------------------------------------------------------

    def _make_segment_clip(
        self,
        idx: int,
        image: Path,
        audio: Path,
        srt: Path,
        duration: float,
    ) -> Path:
        """创建单个片段视频: 按 SRT 条目拆分子片段，动态显示字幕。

        每个 SRT 条目对应一个独立的子片段视频，只显示当前时间点的
        字幕文本。Ken Burns 特效在子片段间保持连续。

        Args:
            idx:      片段序号（从 0 开始）。
            image:    图片路径。
            audio:    音频路径。
            srt:      SRT 字幕路径。
            duration: 片段时长（秒），与音频时长匹配。

        Returns:
            临时片段视频文件路径。
        """
        clip_path = self.tmp_dir / f"clip_{idx:04d}.mp4"

        # 解析 SRT 条目
        entries = self._parse_srt_entries(srt)

        if not entries:
            log.debug("片段 %d: SRT 无有效条目，使用无字幕模式", idx)
            return self._make_single_image_clip(idx, image, audio, duration)

        # 构建子片段列表（处理间隙）
        sub_segments = self._build_sub_segments(entries, duration)

        if len(sub_segments) <= 1:
            # 单条字幕，走简单路径
            seg = sub_segments[0] if sub_segments else {
                "start": 0, "end": duration, "text": "",
            }
            text = seg.get("text", "")
            if text:
                sub_img = self._render_subtitle_image(image, text, idx, 0)
            else:
                sub_img = image
            return self._make_single_image_clip(idx, sub_img, audio, duration)

        # 多个子片段: 逐个创建子视频
        sub_clips: list[Path] = []
        for sub_idx, seg in enumerate(sub_segments):
            seg_duration = seg["end"] - seg["start"]
            if seg_duration < 0.05:
                continue  # 跳过极短片段

            text = seg.get("text", "")
            if text:
                sub_img = self._render_subtitle_image(
                    image, text, idx, sub_idx,
                )
            else:
                sub_img = image  # 无字幕间隙用原图

            # 计算 Ken Burns zoom 子区间（保持连续性）
            progress_start = seg["start"] / duration if duration > 0 else 0
            progress_end = seg["end"] / duration if duration > 0 else 1
            z_start = (
                self.zoom_range[0]
                + (self.zoom_range[1] - self.zoom_range[0]) * progress_start
            )
            z_end = (
                self.zoom_range[0]
                + (self.zoom_range[1] - self.zoom_range[0]) * progress_end
            )

            kb_filter = ken_burns_filter(
                duration=seg_duration,
                width=self.width,
                height=self.height,
                zoom_range=self.zoom_range,
                direction=idx,
                fps=self.fps,
                zoom_start=z_start,
                zoom_end=z_end,
            )

            # 创建无音频子片段视频
            sub_clip_path = self.tmp_dir / f"sub_{idx:04d}_{sub_idx:04d}.mp4"
            filter_complex = (
                f"[0:v]scale={self.width * 2}:{self.height * 2},"
                f"setsar=1,"
                f"{kb_filter}[vout]"
            )

            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", str(sub_img),
                "-filter_complex", filter_complex,
                "-map", "[vout]",
                "-an",
                *self._codec_flags(),
                "-preset", "medium",
                "-t", str(seg_duration),
                "-pix_fmt", "yuv420p",
                str(sub_clip_path),
            ]

            self._run_ffmpeg(cmd, f"子片段 {idx}-{sub_idx}")
            sub_clips.append(sub_clip_path)

        if not sub_clips:
            return self._make_single_image_clip(idx, image, audio, duration)

        # 拼接所有子片段（无音频）
        if len(sub_clips) == 1:
            concat_video = sub_clips[0]
        else:
            concat_video = self.tmp_dir / f"concat_seg_{idx:04d}.mp4"
            self._concatenate(sub_clips, concat_video)

        # 混入音频
        cmd = [
            "ffmpeg", "-y",
            "-i", str(concat_video),
            "-i", str(audio),
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(duration),
            "-movflags", "+faststart",
            str(clip_path),
        ]

        self._run_ffmpeg(cmd, f"混音片段 {idx}")
        return clip_path

    def _make_single_image_clip(
        self,
        idx: int,
        image: Path,
        audio: Path,
        duration: float,
    ) -> Path:
        """从单张图片 + 音频创建片段视频（简单路径，无子片段拆分）。"""
        clip_path = self.tmp_dir / f"clip_{idx:04d}.mp4"

        kb_filter = ken_burns_filter(
            duration=duration,
            width=self.width,
            height=self.height,
            zoom_range=self.zoom_range,
            direction=idx,
            fps=self.fps,
        )

        filter_complex = (
            f"[0:v]scale={self.width * 2}:{self.height * 2},"
            f"setsar=1,"
            f"{kb_filter}[vout]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(image),
            "-i", str(audio),
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "1:a",
            *self._codec_flags(),
            "-preset", "medium",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(clip_path),
        ]

        self._run_ffmpeg(cmd, f"片段 {idx}")
        return clip_path

    # ------------------------------------------------------------------
    # AI 视频片段合成（跳过 Ken Burns）
    # ------------------------------------------------------------------

    def _make_video_clip_segment(
        self,
        idx: int,
        video: Path,
        audio: Path,
        srt: Path,
        target_duration: float,
    ) -> Path:
        """从 AI 生成的视频片段 + TTS 音频 + 字幕创建最终片段。

        与静态图模式的区别:
        - 不使用 Ken Burns 特效（AI 视频已自带动态）
        - 视频时长与音频对齐:
          - 视频比音频长: 裁剪视频到音频时长
          - 视频比音频短: 冻结最后一帧延长至音频时长
        - 字幕通过 FFmpeg drawtext 滤镜叠加（而非 Pillow 渲染到图片）

        Args:
            idx:             片段序号。
            video:           AI 生成的视频片段路径。
            audio:           TTS 音频路径。
            srt:             SRT 字幕路径。
            target_duration: 目标时长（秒），与音频时长匹配。

        Returns:
            最终片段视频文件路径。
        """
        clip_path = self.tmp_dir / f"clip_{idx:04d}.mp4"

        # 获取 AI 视频片段的实际时长
        video_duration = self._get_video_duration(video)

        # 根据时长差异选择处理策略
        if video_duration >= target_duration:
            # 视频足够长: 裁剪到目标时长，替换音频，叠加字幕
            self._trim_replace_audio_subtitle(
                idx, video, audio, srt, target_duration, clip_path,
            )
        else:
            # 视频太短: 冻结最后一帧延长，替换音频，叠加字幕
            extended = self._extend_video_freeze(idx, video, target_duration)
            self._trim_replace_audio_subtitle(
                idx, extended, audio, srt, target_duration, clip_path,
            )

        return clip_path

    def _get_video_duration(self, video_path: Path) -> float:
        """使用 ffprobe 获取视频文件时长（秒）。"""
        ensure_ffmpeg()
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(video_path),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True,
            )
            info = json.loads(result.stdout)
            return float(info["format"]["duration"])
        except (subprocess.CalledProcessError, json.JSONDecodeError,
                KeyError, ValueError) as exc:
            raise RuntimeError(
                f"无法获取视频时长: {video_path}"
            ) from exc

    def _extend_video_freeze(
        self, idx: int, video: Path, target_duration: float,
    ) -> Path:
        """冻结视频最后一帧，延长到目标时长。

        使用 tpad 滤镜在视频末尾填充最后一帧。
        """
        extended_path = self.tmp_dir / f"extended_{idx:04d}.mp4"
        video_dur = self._get_video_duration(video)
        pad_duration = target_duration - video_dur
        if pad_duration <= 0:
            return video

        # tpad: stop_mode=clone 克隆最后一帧，stop_duration 为填充时长
        filter_v = (
            f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
            f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1,"
            f"tpad=stop_mode=clone:stop_duration={pad_duration}"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video),
            "-vf", filter_v,
            "-an",
            *self._codec_flags(),
            "-preset", "medium",
            "-pix_fmt", "yuv420p",
            str(extended_path),
        ]
        self._run_ffmpeg(cmd, f"延长视频 {idx}")
        return extended_path

    def _trim_replace_audio_subtitle(
        self,
        idx: int,
        video: Path,
        audio: Path,
        srt: Path,
        duration: float,
        output: Path,
    ) -> None:
        """裁剪视频到指定时长，替换音频，叠加 SRT 字幕。"""
        # 构建视频滤镜: 缩放 + 字幕叠加
        filter_parts = [
            f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease",
            f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2",
            "setsar=1",
        ]

        # 如果有 SRT 字幕，使用 subtitles 滤镜叠加
        srt_path = Path(srt)
        if srt_path.exists() and srt_path.stat().st_size > 0:
            # FFmpeg subtitles 滤镜需要转义路径中的特殊字符
            escaped_srt = str(srt_path.resolve()).replace("\\", "/").replace(":", "\\:")
            filter_parts.append(
                f"subtitles='{escaped_srt}'"
                f":force_style='FontSize=20,PrimaryColour=&HFFFFFF,"
                f"OutlineColour=&H000000,Outline=2,Shadow=1,"
                f"Alignment=2,MarginV=60'"
            )

        filter_v = ",".join(filter_parts)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video),
            "-i", str(audio),
            "-vf", filter_v,
            "-map", "0:v",
            "-map", "1:a",
            *self._codec_flags(),
            "-preset", "medium",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output),
        ]
        self._run_ffmpeg(cmd, f"视频片段合成 {idx}")

    # ------------------------------------------------------------------
    # 字幕渲染
    # ------------------------------------------------------------------

    def _render_subtitle_image(
        self, image_path: Path, text: str, idx: int, sub_idx: int,
    ) -> Path:
        """渲染单条字幕到图片上，返回新图片路径。

        样式: 大字号、半透明黑色背景条、3px 描边、最多 2 行、居中偏下。

        Args:
            image_path: 原始图片路径。
            text:       单条字幕文本。
            idx:        片段序号。
            sub_idx:    子片段序号。

        Returns:
            烧录字幕后的新图片路径。
        """
        if not text:
            return image_path

        img = Image.open(image_path).convert("RGBA")

        # 字号增大: ~60px @ 1080w
        font_size = max(36, img.width // 18)
        font = _find_cjk_font(font_size)

        # 自动换行，最多 2 行
        max_chars = max(1, (img.width - 120) // font_size)
        if len(text) <= max_chars:
            lines = [text]
        elif len(text) <= max_chars * 2:
            mid = (len(text) + 1) // 2
            lines = [text[:mid], text[mid:]]
        else:
            lines = [text[:max_chars], text[max_chars:max_chars * 2]]

        # 计算文本尺寸
        line_height = font_size + 12
        total_text_height = len(lines) * line_height

        # 居中偏下，底部留 80px 边距
        y_start = img.height - total_text_height - 80

        # 半透明背景条
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        bg_pad_x = 40
        bg_pad_y = 16
        draw_overlay.rectangle(
            [
                (bg_pad_x, y_start - bg_pad_y),
                (img.width - bg_pad_x, y_start + total_text_height + bg_pad_y),
            ],
            fill=(0, 0, 0, 160),
        )
        img = Image.alpha_composite(img, overlay)

        draw = ImageDraw.Draw(img)

        # 描边 + 白字
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (img.width - text_width) // 2
            y = y_start + i * line_height

            # 3px 黑色描边
            for dx in range(-3, 4):
                for dy in range(-3, 4):
                    if dx == 0 and dy == 0:
                        continue
                    draw.text(
                        (x + dx, y + dy), line,
                        fill=(0, 0, 0, 255), font=font,
                    )
            # 白色正文
            draw.text((x, y), line, fill=(255, 255, 255, 255), font=font)

        # 转回 RGB 保存
        out_path = self.tmp_dir / f"subtitled_{idx:04d}_{sub_idx:04d}.png"
        img.convert("RGB").save(str(out_path))
        return out_path

    # ------------------------------------------------------------------
    # 拼接
    # ------------------------------------------------------------------

    def _concatenate(self, clips: list[Path], output: Path) -> Path:
        """使用 FFmpeg concat demuxer 拼接多个视频片段。

        Args:
            clips:  片段视频路径列表（格式和编码必须一致）。
            output: 输出文件路径。

        Returns:
            输出文件路径。
        """
        concat_list = self.tmp_dir / f"concat_{output.stem}.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for clip in clips:
                # concat demuxer 需要绝对路径
                f.write(f"file '{clip.resolve()}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output),
        ]

        self._run_ffmpeg(cmd, "拼接片段")
        log.info("拼接完成: %d 个片段 -> %s", len(clips), output.name)
        return output

    # ------------------------------------------------------------------
    # 背景音乐混音
    # ------------------------------------------------------------------

    def _add_bgm(
        self,
        video: Path,
        bgm: Path,
        volume: float,
        output: Path,
    ) -> Path:
        """在视频中混入背景音乐。

        BGM 会循环播放至视频结束，音量按 ``volume`` 缩放。
        原始人声音频保持不变。

        Args:
            video:  输入视频路径。
            bgm:    背景音乐文件路径。
            volume: BGM 音量系数（0.0 - 1.0），如 0.15 表示 15%。
            output: 输出文件路径。

        Returns:
            输出文件路径。
        """
        # 滤镜: 将 BGM 音量调低，然后与原声混合
        filter_audio = (
            f"[1:a]aloop=loop=-1:size=2e+09,volume={volume}[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video),
            "-stream_loop", "-1",
            "-i", str(bgm),
            "-filter_complex", filter_audio,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output),
        ]

        self._run_ffmpeg(cmd, "混入 BGM")
        return output

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _ffmpeg_copy(self, src: Path, dst: Path) -> None:
        """使用 FFmpeg 无损复制（重封装）到输出路径。"""
        cmd = [
            "ffmpeg", "-y",
            "-i", str(src),
            "-c", "copy",
            "-movflags", "+faststart",
            str(dst),
        ]
        self._run_ffmpeg(cmd, "复制输出")

    def _run_ffmpeg(self, cmd: list[str], description: str) -> None:
        """执行 FFmpeg 命令并处理错误。

        Args:
            cmd:         完整命令行参数列表。
            description: 操作描述，用于日志和错误消息。
        """
        ensure_ffmpeg()
        log.debug("FFmpeg 命令 [%s]: %s", description, " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
            if result.stderr:
                # FFmpeg 正常输出也会写到 stderr
                log.debug("FFmpeg stderr [%s]: %s", description, result.stderr[-500:])
        except subprocess.CalledProcessError as exc:
            log.error(
                "FFmpeg 失败 [%s] (exit code %d)\nstderr: %s",
                description,
                exc.returncode,
                exc.stderr[-2000:] if exc.stderr else "(empty)",
            )
            raise RuntimeError(
                f"FFmpeg 操作失败: {description} (exit code {exc.returncode})"
            ) from exc
        except FileNotFoundError:
            log.error("找不到 ffmpeg 可执行文件，请确认已安装 FFmpeg 并添加到 PATH")
            raise
