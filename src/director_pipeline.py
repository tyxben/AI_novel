"""DirectorPipeline - AI短视频导演流水线

新流程：灵感 → 视频方案 → 结构化脚本 → 逐段生成素材 → 合成视频

与旧 Pipeline 的区别：
- 旧流程：文本 → 分段 → prompt → 图 → 音 → 合成（pipeline.py）
- 新流程：灵感 → 视频方案 → 结构化脚本 → 逐段素材 → 合成
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("director")


class DirectorPipeline:
    """AI短视频导演流水线。

    用法::

        pipe = DirectorPipeline(config_path="config.yaml")
        result = pipe.run("一个关于时间旅行者的悬疑故事")
        print(result["video_path"])
    """

    def __init__(
        self,
        config_path: Path | str | None = None,
        workspace: Path | str | None = None,
        config: dict | None = None,
    ):
        """初始化导演流水线。

        Args:
            config_path: YAML 配置文件路径
            workspace: 工作目录，默认 workspace/videos
            config: 直接传入配置字典（优先于 config_path）
        """
        if config:
            self.config = config
        else:
            from src.config_manager import load_config
            self.config = load_config(config_path)

        self.workspace = Path(workspace or "workspace/videos")
        self.workspace.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        inspiration: str,
        target_duration: int = 45,
        budget: str = "low",
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> dict[str, Any]:
        """完整流程：灵感 → 视频。

        Args:
            inspiration: 用户灵感/创意/故事梗概
            target_duration: 目标时长(秒)，默认 45
            budget: 预算档位 (free/low/medium/high)
            progress_callback: 进度回调 (progress_pct, description)

        Returns:
            包含 video_path, script, idea, segments, duration, run_dir 的字典
        """
        run_id = uuid.uuid4().hex[:8]
        run_dir = self.workspace / f"run_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)

        def _notify(pct: float, desc: str) -> None:
            if progress_callback:
                progress_callback(pct, desc)

        # 初始化 LLM
        from src.llm.llm_client import create_llm_client
        llm = create_llm_client(self.config.get("llm", {}))

        # === Stage 1: 视频方案 ===
        _notify(0.05, "正在策划视频方案...")
        idea = self._plan_idea(llm, inspiration, target_duration)
        log.info(
            "视频方案: type=%s, duration=%ds, segments=%d",
            idea.video_type, idea.target_duration, idea.segment_count,
        )

        # === Stage 2: 结构化脚本 ===
        _notify(0.10, "正在生成脚本...")
        script = self._plan_script(llm, idea, inspiration)
        log.info(
            "脚本生成: title=%s, segments=%d, duration=%.1fs",
            script.title, len(script.segments), script.total_duration,
        )

        # === Stage 3: 素材策略 ===
        _notify(0.15, "正在规划素材...")
        script = self._assign_assets(script, budget)

        # 保存脚本
        script_path = run_dir / "script.json"
        script_path.write_text(
            script.model_dump_json(indent=2), encoding="utf-8",
        )

        # === Stage 4: 逐段生成配音 ===
        _notify(0.20, "正在生成配音...")
        self._generate_voices(script, run_dir, progress_callback)

        # === Stage 5: 逐段生成画面 ===
        _notify(0.50, "正在生成画面...")
        self._generate_visuals(script, run_dir, budget, progress_callback)

        # === Stage 6: 合成视频 ===
        _notify(0.85, "正在合成视频...")
        output_path = run_dir / f"{script.title or 'video'}_{run_id}.mp4"
        final_path = self._assemble_video(script, run_dir, output_path)

        _notify(1.0, "完成!")

        return {
            "video_path": str(final_path),
            "script": script.model_dump(),
            "idea": idea.model_dump(),
            "segments": [s.model_dump() for s in script.segments],
            "duration": script.total_duration,
            "run_dir": str(run_dir),
        }

    # ------------------------------------------------------------------
    # Stage 1: 视频方案
    # ------------------------------------------------------------------

    @staticmethod
    def _plan_idea(llm, inspiration: str, target_duration: int):
        """调用 IdeaPlanner 生成视频方案。"""
        from src.scriptplan.idea_planner import IdeaPlanner
        return IdeaPlanner(llm).plan(inspiration, target_duration)

    # ------------------------------------------------------------------
    # Stage 2: 结构化脚本
    # ------------------------------------------------------------------

    @staticmethod
    def _plan_script(llm, idea, inspiration: str):
        """调用 ScriptPlanner 生成结构化脚本。"""
        from src.scriptplan.script_planner import ScriptPlanner
        return ScriptPlanner(llm).plan(idea, inspiration)

    # ------------------------------------------------------------------
    # Stage 3: 素材策略
    # ------------------------------------------------------------------

    @staticmethod
    def _assign_assets(script, budget: str):
        """调用 AssetStrategy 为每段分配素材类型。"""
        from src.scriptplan.asset_strategy import AssetStrategy
        return AssetStrategy().assign(script, budget)

    # ------------------------------------------------------------------
    # Stage 4: 逐段配音
    # ------------------------------------------------------------------

    def _generate_voices(
        self,
        script,
        run_dir: Path,
        progress_callback: Callable | None = None,
    ) -> None:
        """为每段生成配音和字幕。

        结果写入 seg.audio_path / seg.srt_path。
        """
        from src.tts.tts_engine import TTSEngine
        from src.tts.subtitle_generator import SubtitleGenerator

        tts_config = self.config.get("tts", {})
        sub_gen = SubtitleGenerator()

        total = len(script.segments)
        for i, seg in enumerate(script.segments):
            if not seg.voiceover:
                continue

            if progress_callback:
                pct = 0.20 + 0.30 * (i / max(total, 1))
                progress_callback(pct, f"配音 {i + 1}/{total}...")

            # 为每段创建独立 TTS（段落可能有不同语速）
            seg_tts_config = dict(tts_config)
            if seg.voice_params and seg.voice_params.speed:
                seg_tts_config["rate"] = seg.voice_params.speed

            engine = TTSEngine(seg_tts_config)
            audio_path = run_dir / f"audio_{seg.id:03d}.mp3"
            srt_path = run_dir / f"sub_{seg.id:03d}.srt"

            try:
                audio_file, boundaries = engine.synthesize(
                    seg.voiceover, audio_path,
                )
                srt_file = sub_gen.generate_srt(
                    boundaries, seg.voiceover, srt_path,
                )
                seg.audio_path = str(audio_file)
                seg.srt_path = str(srt_file)
            except Exception as exc:
                log.error("配音生成失败 segment %d: %s", seg.id, exc)

    # ------------------------------------------------------------------
    # Stage 5: 逐段画面
    # ------------------------------------------------------------------

    def _generate_visuals(
        self,
        script,
        run_dir: Path,
        budget: str,
        progress_callback: Callable | None = None,
    ) -> None:
        """为每段生成画面素材（图片或视频）。

        结果写入 seg.asset_path / seg.image_prompt / seg.video_prompt。
        如果视频生成器不可用，自动降级为静图。
        """
        from src.scriptplan.models import AssetType
        from src.promptgen.prompt_generator import PromptGenerator
        from src.imagegen.image_generator import create_image_generator

        prompt_gen = PromptGenerator(self.config.get("promptgen", {}))
        image_gen = create_image_generator(self.config.get("imagegen", {}))

        # 初始化视频生成器（如果需要且可用）
        video_gen = None
        needs_video = any(
            s.asset_type in (AssetType.IMAGE2VIDEO, AssetType.VIDEO)
            for s in script.segments
        )
        if needs_video:
            video_gen = self._try_create_video_generator()

        total = len(script.segments)
        for i, seg in enumerate(script.segments):
            if progress_callback:
                pct = 0.50 + 0.35 * (i / max(total, 1))
                progress_callback(pct, f"画面 {i + 1}/{total}...")

            try:
                self._generate_segment_visual(
                    seg, run_dir, prompt_gen, image_gen, video_gen,
                )
            except Exception as exc:
                log.error("素材生成失败 segment %d: %s", seg.id, exc)
                seg.asset_path = ""

        # 清理视频生成器
        if video_gen:
            try:
                video_gen.close()
            except Exception:
                pass

    def _try_create_video_generator(self):
        """尝试创建视频生成器，失败则返回 None。"""
        try:
            from src.videogen.video_generator import create_video_generator
            videogen_config = self.config.get("videogen", {})
            if videogen_config.get("backend"):
                return create_video_generator(videogen_config)
        except Exception as exc:
            log.warning("视频生成器初始化失败，降级为静图: %s", exc)
        return None

    def _generate_segment_visual(
        self, seg, run_dir: Path, prompt_gen, image_gen, video_gen,
    ) -> None:
        """为单个段落生成画面素材。"""
        from src.scriptplan.models import AssetType

        # 所有类型都需要先生成图片
        image_prompt = prompt_gen.generate(seg.visual, seg.id)
        seg.image_prompt = image_prompt

        image = image_gen.generate(image_prompt)
        image_path = run_dir / f"img_{seg.id:03d}.png"
        image.save(str(image_path))

        if seg.asset_type == AssetType.IMAGE or video_gen is None:
            # 纯静图 或 视频生成器不可用时降级
            seg.asset_path = str(image_path)
            if video_gen is None and seg.asset_type != AssetType.IMAGE:
                log.info(
                    "segment %d: 视频生成器不可用，降级为静图", seg.id,
                )
                seg.asset_type = AssetType.IMAGE

        elif seg.asset_type == AssetType.IMAGE2VIDEO:
            # 图生视频
            video_prompt = prompt_gen.generate_video_prompt(
                seg.visual, seg.id,
            )
            seg.video_prompt = video_prompt
            result = video_gen.generate(
                prompt=video_prompt,
                image_path=image_path,
                duration=seg.duration_sec,
            )
            seg.asset_path = str(result.video_path)

        elif seg.asset_type == AssetType.VIDEO:
            # 纯文生视频
            video_prompt = prompt_gen.generate_video_prompt(
                seg.visual, seg.id,
            )
            seg.video_prompt = video_prompt
            result = video_gen.generate(
                prompt=video_prompt,
                duration=seg.duration_sec,
            )
            seg.asset_path = str(result.video_path)

    # ------------------------------------------------------------------
    # Stage 6: 合成视频
    # ------------------------------------------------------------------

    def _assemble_video(
        self,
        script,
        run_dir: Path,
        output_path: Path,
    ) -> Path:
        """按脚本合成最终视频。"""
        from src.scriptplan.models import AssetType
        from src.video.video_assembler import VideoAssembler

        video_config = self.config.get("video", {
            "resolution": [1080, 1920],
            "fps": 30,
            "codec": "libx265",
        })
        assembler = VideoAssembler(video_config, run_dir)

        images: list[Path] = []
        audio_srt: list[dict] = []
        video_clips: list[Path | None] = []
        has_video_clips = False

        for seg in script.segments:
            if not seg.asset_path:
                log.warning("segment %d 无素材，跳过", seg.id)
                continue

            asset_path = Path(seg.asset_path)
            audio_path = Path(seg.audio_path) if seg.audio_path else None
            srt_path = Path(seg.srt_path) if seg.srt_path else None

            if seg.asset_type in (AssetType.IMAGE2VIDEO, AssetType.VIDEO):
                has_video_clips = True
                video_clips.append(asset_path)
                images.append(asset_path)  # 占位，assembler 需要对齐
            else:
                images.append(asset_path)
                video_clips.append(None)  # 占位

            audio_srt.append({
                "audio": audio_path,
                "srt": srt_path,
            })

        if not images:
            raise RuntimeError("没有可用素材，无法合成视频")

        final_path = assembler.assemble(
            images=images,
            audio_srt=audio_srt,
            output_path=output_path,
            video_clips=video_clips if has_video_clips else None,
        )

        log.info("视频合成完成: %s", final_path)
        return final_path
