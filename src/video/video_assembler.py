"""视频合成器 - 基于 FFmpeg 的视频组装流水线

将静态图片、语音音频和 SRT 字幕合成为最终 MP4 视频。
主要流程:
  1. 每组素材（图片 + 音频 + 字幕）创建一个带 Ken Burns 特效的片段
  2. 使用 FFmpeg concat demuxer 拼接所有片段
  3. 可选混入背景音乐
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.logger import log
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


class VideoAssembler:
    """FFmpeg 视频合成器。

    Args:
        config: 视频配置字典（对应 config.yaml 中的 ``video`` 段）。
        workspace: 工作目录，用于存放临时文件。
    """

    def __init__(self, config: dict, workspace: Path) -> None:
        self.width: int = config["resolution"][0]
        self.height: int = config["resolution"][1]
        self.fps: int = config.get("fps", 30)
        self.codec: str = config.get("codec", "libx264")
        self.crf: int = config.get("crf", 18)

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
    ) -> Path:
        """执行完整的视频组装流水线。

        Args:
            images:      与各段对应的图片路径列表。
            audio_srt:   每段的音频和字幕信息列表，每个元素为
                         ``{"audio": Path, "srt": Path}``。
            output_path: 最终输出的 MP4 文件路径。

        Returns:
            输出文件路径。
        """
        if len(images) != len(audio_srt):
            raise ValueError(
                f"图片数量 ({len(images)}) 与音频/字幕数量 "
                f"({len(audio_srt)}) 不匹配"
            )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        log.info("开始视频合成: %d 个片段", len(images))

        # -- 第 1 步: 为每段素材创建片段视频 --
        clips: list[Path] = []
        for idx, (img, entry) in enumerate(zip(images, audio_srt)):
            audio_path = Path(entry["audio"])
            srt_path = Path(entry["srt"])
            duration = self._get_audio_duration(audio_path)

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
        if not shutil.which("ffprobe"):
            raise FileNotFoundError(
                "未找到 ffprobe，请安装 FFmpeg (https://ffmpeg.org/)。\n"
                "  macOS: brew install ffmpeg\n"
                "  Ubuntu/Debian: sudo apt install ffmpeg\n"
                "  Windows: winget install ffmpeg"
            )

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
        """创建单个片段视频: 图片 + Ken Burns 特效 + 字幕 + 音频。

        使用 Pillow 将字幕文本烧录到图片上（避免依赖 libass），
        然后用 FFmpeg 创建 Ken Burns 动态视频并混入音频。

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

        # 将字幕文本烧录到图片上
        subtitled_image = self._burn_subtitles_on_image(image, srt, idx)

        # 构建 Ken Burns 滤镜
        kb_filter = ken_burns_filter(
            duration=duration,
            width=self.width,
            height=self.height,
            zoom_range=self.zoom_range,
            direction=idx,
            fps=self.fps,
        )

        # 滤镜链: 缩放 → Ken Burns
        filter_complex = (
            f"[0:v]scale={self.width * 2}:{self.height * 2},"
            f"setsar=1,"
            f"{kb_filter}[vout]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(subtitled_image),
            "-i", str(audio),
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "1:a",
            "-c:v", self.codec,
            "-crf", str(self.crf),
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

    def _burn_subtitles_on_image(
        self, image_path: Path, srt_path: Path, idx: int
    ) -> Path:
        """使用 Pillow 将 SRT 字幕文本烧录到图片底部。

        将所有字幕行合并为一段文字，以描边白字绘制在图片底部区域。

        Args:
            image_path: 原始图片路径。
            srt_path:   SRT 字幕文件路径。
            idx:        片段序号。

        Returns:
            烧录字幕后的新图片路径。
        """
        # 解析 SRT，提取纯文本
        subtitle_text = self._extract_srt_text(srt_path)
        if not subtitle_text:
            return image_path  # 无字幕，直接使用原图

        img = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(img)

        # 字体大小根据图片宽度自适应
        font_size = max(28, img.width // 25)
        font = _find_cjk_font(font_size)

        # 自动换行
        max_chars_per_line = max(1, (img.width - 80) // font_size)
        lines = []
        for i in range(0, len(subtitle_text), max_chars_per_line):
            lines.append(subtitle_text[i:i + max_chars_per_line])

        # 计算文本区域
        line_height = font_size + 8
        total_text_height = len(lines) * line_height
        y_start = img.height - total_text_height - 60  # 底部留 60px 边距

        # 绘制描边 + 白字
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (img.width - text_width) // 2
            y = y_start + i * line_height

            # 描边（黑色）
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if dx == 0 and dy == 0:
                        continue
                    draw.text((x + dx, y + dy), line, fill=(0, 0, 0), font=font)
            # 正文（白色）
            draw.text((x, y), line, fill=(255, 255, 255), font=font)

        out_path = self.tmp_dir / f"subtitled_{idx:04d}.png"
        img.save(str(out_path))
        return out_path

    @staticmethod
    def _extract_srt_text(srt_path: Path) -> str:
        """从 SRT 文件中提取纯文本（合并所有字幕条目）。"""
        if not srt_path.exists():
            return ""
        text = srt_path.read_text(encoding="utf-8").strip()
        if not text:
            return ""
        lines = []
        for line in text.splitlines():
            line = line.strip()
            # 跳过序号、时间码、空行
            if not line or line.isdigit() or "-->" in line:
                continue
            lines.append(line)
        return "".join(lines)

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
        concat_list = self.tmp_dir / "concat.txt"
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
