"""流水线调度器 - 编排所有阶段"""

import shutil
from pathlib import Path
from typing import Any, Callable

from src.checkpoint import Checkpoint
from src.config_manager import load_config
from src.logger import log, get_progress
from src.segmenter.text_segmenter import create_segmenter
from src.promptgen.prompt_generator import PromptGenerator
from src.imagegen.image_generator import create_image_generator
from src.tts.tts_engine import TTSEngine
from src.tts.subtitle_generator import SubtitleGenerator
from src.video.video_assembler import VideoAssembler
from src.videogen.video_generator import create_video_generator


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个字典，override 中的值覆盖 base 中的值。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Pipeline:
    def __init__(self, input_file: Path, config_path: Path | None = None,
                 output_dir: Path | None = None, workspace: Path | None = None,
                 resume: bool = False, config: dict | None = None):
        self.input_file = Path(input_file)
        if not self.input_file.exists():
            raise FileNotFoundError(f"输入文件不存在: {self.input_file}")

        base_cfg = load_config(config_path)
        self.cfg = _deep_merge(base_cfg, config) if config else base_cfg
        proj_name = self.input_file.stem

        base = Path(self.cfg.get("project", {}).get("default_workspace", "workspace"))
        self.workspace = (workspace or base) / proj_name
        self.workspace.mkdir(parents=True, exist_ok=True)

        self.output_dir = Path(output_dir) if output_dir else Path(
            self.cfg.get("project", {}).get("default_output", "output"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.ckpt = Checkpoint(self.workspace)
        self.resume = resume

        # 子目录
        self.seg_dir = self.workspace / "segments"
        self.img_dir = self.workspace / "images"
        self.audio_dir = self.workspace / "audio"
        self.srt_dir = self.workspace / "subtitles"
        self.video_clip_dir = self.workspace / "videos"
        for d in [self.seg_dir, self.img_dir, self.audio_dir, self.srt_dir,
                  self.video_clip_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # 是否启用 AI 视频片段生成
        self._videogen_enabled: bool = "videogen" in self.cfg and bool(
            self.cfg["videogen"].get("backend")
        )

    def run(self, progress_callback: Callable[[int, int, str], None] | None = None) -> Path:
        """运行完整流水线。

        Args:
            progress_callback: 进度回调函数，签名为 (stage_num, total_stages, description)。
                             可选，默认 None 表示不回调。
        """
        log.info("开始处理: %s", self.input_file.name)
        total_stages = 6 if self._videogen_enabled else 5

        def _notify(stage: int, desc: str) -> None:
            if progress_callback:
                progress_callback(stage, total_stages, desc)

        _notify(1, "文本分段")
        segments = self._stage_segment()
        _notify(2, "生成图片 Prompt")
        prompts = self._stage_prompt(segments)
        _notify(3, "生成图片")
        images = self._stage_image(prompts)

        # Stage 3.5 (可选): AI 视频片段生成
        video_clips: list[Path] | None = None
        if self._videogen_enabled:
            _notify(4, "AI 视频片段生成")
            video_clips = self._stage_videogen(segments, images)
            _notify(5, "语音合成")
            audio_srt = self._stage_tts(segments)
            _notify(6, "视频合成")
        else:
            _notify(4, "语音合成")
            audio_srt = self._stage_tts(segments)
            _notify(5, "视频合成")

        output = self._stage_video(segments, images, audio_srt,
                                   video_clips=video_clips)

        log.info("完成! 输出文件: %s", output)
        return output

    # -- Stage 1: 分段 --
    def _stage_segment(self) -> list[dict[str, Any]]:
        if self.resume and self.ckpt.is_done("segment"):
            log.info("[断点续传] 跳过分段")
            return self._load_segments()

        log.info("阶段 1/5: 文本分段")
        text = self.input_file.read_text(encoding="utf-8")
        seg_cfg = dict(self.cfg["segmenter"])
        # 全局 llm 配置与模块级 llm 配置合并（模块级覆盖全局）
        global_llm = self.cfg.get("llm", {})
        module_llm = seg_cfg.get("llm", {})
        seg_cfg["llm"] = {**global_llm, **module_llm}
        segmenter = create_segmenter(seg_cfg)
        segments = segmenter.segment(text)

        for i, seg in enumerate(segments):
            out = self.seg_dir / f"{i:04d}.txt"
            out.write_text(seg["text"], encoding="utf-8")
            self.ckpt.update_segment(i, "text", str(out))

        self.ckpt.mark_done("segment", {"count": len(segments)})
        log.info("分段完成: %d 段", len(segments))
        return segments

    def _load_segments(self) -> list[dict[str, Any]]:
        segments = []
        for f in sorted(self.seg_dir.glob("*.txt")):
            segments.append({"text": f.read_text(encoding="utf-8")})
        return segments

    # -- Stage 2: Prompt 生成 --
    def _stage_prompt(self, segments: list[dict]) -> list[str]:
        if self.resume and self.ckpt.is_done("prompt"):
            log.info("[断点续传] 跳过 prompt 生成")
            return self._load_prompts()

        log.info("阶段 2/5: 生成图片 Prompt")
        prompt_cfg = dict(self.cfg.get("promptgen", {}))
        # 全局 llm 配置与模块级 llm 配置合并（模块级覆盖全局）
        global_llm = self.cfg.get("llm", {})
        module_llm = prompt_cfg.get("llm", {})
        prompt_cfg["llm"] = {**global_llm, **module_llm}
        gen = PromptGenerator(prompt_cfg)

        # 用全文帮助判断时代背景（现代 vs 古风）
        full_text = self.input_file.read_text(encoding="utf-8")
        gen.set_full_text(full_text)

        prompts = []

        with get_progress() as progress:
            task = progress.add_task("生成 Prompt", total=len(segments))
            for i, seg in enumerate(segments):
                prompt = gen.generate(seg["text"], segment_index=i)
                prompts.append(prompt)
                out = self.seg_dir / f"{i:04d}.prompt"
                out.write_text(prompt, encoding="utf-8")
                self.ckpt.update_segment(i, "prompt", str(out))
                progress.advance(task)

        self.ckpt.mark_done("prompt")
        return prompts

    def _load_prompts(self) -> list[str]:
        prompts = []
        for f in sorted(self.seg_dir.glob("*.prompt")):
            prompts.append(f.read_text(encoding="utf-8"))
        return prompts

    # -- Stage 3: 生图 --
    def _stage_image(self, prompts: list[str]) -> list[Path]:
        if self.resume and self.ckpt.is_done("image"):
            log.info("[断点续传] 跳过图片生成")
            return sorted(self.img_dir.glob("*.png"))

        log.info("阶段 3/5: 生成图片")
        gen = create_image_generator(self.cfg["imagegen"])
        images = []

        with get_progress() as progress:
            task = progress.add_task("生成图片", total=len(prompts))
            for i, prompt in enumerate(prompts):
                # 断点续传：跳过已生成的图片
                out = self.img_dir / f"{i:04d}.png"
                if self.resume and out.exists():
                    images.append(out)
                    progress.advance(task)
                    continue

                img = gen.generate(prompt)
                img.save(str(out))
                images.append(out)
                self.ckpt.update_segment(i, "image", str(out))
                progress.advance(task)

        self.ckpt.mark_done("image")
        return images

    # -- Stage 3.5: AI 视频片段生成 (可选) --
    def _stage_videogen(self, segments: list[dict], images: list[Path]) -> list[Path]:
        if self.resume and self.ckpt.is_done("videogen"):
            log.info("[断点续传] 跳过 AI 视频片段生成")
            return sorted(self.video_clip_dir.glob("*.mp4"))

        log.info("阶段 3.5: AI 视频片段生成")
        videogen_cfg = dict(self.cfg["videogen"])

        # 创建视频生成器
        gen = create_video_generator(videogen_cfg)

        # 创建 prompt 生成器（用于生成视频 prompt）
        prompt_cfg = dict(self.cfg.get("promptgen", {}))
        global_llm = self.cfg.get("llm", {})
        module_llm = prompt_cfg.get("llm", {})
        prompt_cfg["llm"] = {**global_llm, **module_llm}
        prompt_gen = PromptGenerator(prompt_cfg)

        full_text = self.input_file.read_text(encoding="utf-8")
        prompt_gen.set_full_text(full_text)

        use_first_frame = videogen_cfg.get("use_image_as_first_frame", True)
        duration = videogen_cfg.get("duration", 5)
        video_clips: list[Path] = []

        with get_progress() as progress:
            task = progress.add_task("AI 视频生成", total=len(segments))
            for i, seg in enumerate(segments):
                out = self.video_clip_dir / f"{i:04d}.mp4"

                # 段级断点续传: 跳过已生成的视频文件
                if self.resume and out.exists():
                    video_clips.append(out)
                    progress.advance(task)
                    continue

                # 生成视频 prompt
                video_prompt = prompt_gen.generate_video_prompt(
                    seg["text"], segment_index=i,
                )

                # 可选使用 Stage 3 图片作为首帧
                image_path = images[i] if use_first_frame and i < len(images) else None

                result = gen.generate(
                    prompt=video_prompt,
                    image_path=image_path,
                    duration=float(duration),
                )

                # 将生成的视频复制到 workspace
                shutil.copy2(str(result.video_path), str(out))
                video_clips.append(out)

                self.ckpt.update_segment(i, "video_clip", str(out))
                progress.advance(task)

        gen.close()
        self.ckpt.mark_done("videogen")
        return video_clips

    # -- Stage 4: TTS + 字幕 --
    def _stage_tts(self, segments: list[dict]) -> list[dict]:
        if self.resume and self.ckpt.is_done("tts"):
            log.info("[断点续传] 跳过 TTS")
            return self._load_audio_srt()

        log.info("阶段 4/5: 语音合成 + 字幕")
        tts = TTSEngine(self.cfg["tts"])
        sub_gen = SubtitleGenerator()
        results = []

        with get_progress() as progress:
            task = progress.add_task("语音合成", total=len(segments))
            for i, seg in enumerate(segments):
                audio_path = self.audio_dir / f"{i:04d}.mp3"
                srt_path = self.srt_dir / f"{i:04d}.srt"

                if self.resume and audio_path.exists() and srt_path.exists():
                    results.append({"audio": audio_path, "srt": srt_path})
                    progress.advance(task)
                    continue

                audio, word_boundaries = tts.synthesize(seg["text"], audio_path)
                sub_gen.generate_srt(word_boundaries, seg["text"], srt_path)
                results.append({"audio": audio, "srt": srt_path})
                self.ckpt.update_segment(i, "audio", str(audio_path))
                self.ckpt.update_segment(i, "srt", str(srt_path))
                progress.advance(task)

        self.ckpt.mark_done("tts")
        return results

    def _load_audio_srt(self) -> list[dict]:
        results = []
        audios = sorted(self.audio_dir.glob("*.mp3"))
        srts = sorted(self.srt_dir.glob("*.srt"))
        for a, s in zip(audios, srts):
            results.append({"audio": a, "srt": s})
        return results

    # -- Stage 5/6: 视频合成 --
    def _stage_video(self, segments: list[dict], images: list[Path],
                     audio_srt: list[dict],
                     video_clips: list[Path] | None = None) -> Path:
        log.info("最终阶段: 视频合成")
        output_path = self.output_dir / f"{self.input_file.stem}.mp4"

        assembler = VideoAssembler(self.cfg["video"], self.workspace)
        assembler.assemble(
            images=images,
            audio_srt=audio_srt,
            output_path=output_path,
            video_clips=video_clips,
        )
        return output_path

    def get_status(self) -> dict:
        stages = ["segment", "prompt", "image"]
        if self._videogen_enabled:
            stages.append("videogen")
        stages.extend(["tts", "video"])
        status = {}
        for s in stages:
            status[s] = "done" if self.ckpt.is_done(s) else "pending"
        status["segments_total"] = self.ckpt.total_segments()
        return status
