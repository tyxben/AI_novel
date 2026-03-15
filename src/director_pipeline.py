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

# 画面描述 → 图片 prompt 的系统提示词（专用于导演流水线）
_VISUAL_TO_IMAGE_PROMPT = """\
你是一个中英翻译专家，负责将中文画面描述翻译为 Stable Diffusion 图片生成 prompt。

规则：
1. 直接翻译画面描述，保留所有细节
2. 角色性别是最重要的信息，必须明确翻译：
   - 男人/男性/男孩 → man/male/boy
   - 女人/女性/女孩 → woman/female/girl
   - 如果原文有多个角色，每个角色的性别和外观必须分别翻译
3. 翻译角色的外观：年龄、发型、发色、服装、体型、表情
4. 翻译场景：环境、光线、氛围
5. 输出格式：英文关键词短语，逗号分隔
6. 末尾添加：highly detailed, cinematic composition, dramatic lighting, 4K

输出：仅输出英文 prompt，不要任何解释。
"""

# 画面描述 → 视频 prompt 的系统提示词
_VISUAL_TO_VIDEO_PROMPT = """\
你是一个中英翻译专家，负责将中文画面描述翻译为 AI 视频生成 prompt。

规则：
1. 直接翻译画面描述为 2-3 句英文自然语言句子
2. 角色性别必须明确：
   - 男人/男性 → a man/male figure
   - 女人/女性 → a woman/female figure
   - 多个角色必须分别描述性别和外观
3. 包含角色外观（年龄、发型、服装）、动作、场景、光线
4. 添加合适的运镜描述（dolly in, pan, tracking shot 等）
5. 末尾添加：stable character appearance, natural smooth movements, cinematic quality, 4K
6. 视频只有5-10秒，聚焦一个核心画面变化

输出：仅输出英文 prompt，不要任何解释。
"""


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
        self._llm_cached = None  # 懒初始化 LLM client

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
        llm = self._get_llm()

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
        import re as _re
        safe_title = _re.sub(r'[^\w\u4e00-\u9fff-]', '_', script.title or 'video')[:50]
        output_path = run_dir / f"{safe_title}_{run_id}.mp4"
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

    def _get_llm(self):
        """获取或创建缓存的 LLM client。"""
        if self._llm_cached is None:
            from src.llm.llm_client import create_llm_client
            self._llm_cached = create_llm_client(self.config.get("llm", {}))
        return self._llm_cached

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
        from src.imagegen.image_generator import create_image_generator

        image_gen = create_image_generator(self.config.get("imagegen", {}))

        # 提取 visual_bible 用于全片一致性
        visual_bible = getattr(script, "visual_bible", None)

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
                    seg, run_dir, image_gen, video_gen,
                    visual_bible=visual_bible,
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
        self, seg, run_dir: Path, image_gen, video_gen,
        visual_bible=None,
    ) -> None:
        """为单个段落生成画面素材。"""
        from src.scriptplan.models import AssetType

        # 使用专用的视觉描述翻译，注入 visual_bible 保持全片一致性
        image_prompt = self._visual_to_prompt(seg.visual, seg.id, visual_bible)
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
            video_prompt = self._visual_to_video_prompt(seg.visual, seg.id, visual_bible)
            seg.video_prompt = video_prompt
            result = video_gen.generate(
                prompt=video_prompt,
                image_path=image_path,
                duration=seg.duration_sec,
            )
            seg.asset_path = str(result.video_path)

        elif seg.asset_type == AssetType.VIDEO:
            # 纯文生视频
            video_prompt = self._visual_to_video_prompt(seg.visual, seg.id, visual_bible)
            seg.video_prompt = video_prompt
            result = video_gen.generate(
                prompt=video_prompt,
                duration=seg.duration_sec,
            )
            seg.asset_path = str(result.video_path)

    # ------------------------------------------------------------------
    # 视觉描述 → 英文 Prompt 翻译（专用于导演流水线）
    # ------------------------------------------------------------------

    def _visual_to_prompt(self, visual: str, seg_id: int, visual_bible=None) -> str:
        """将中文画面描述直接翻译为英文图片生成 prompt。

        如果有 visual_bible，会将角色锚点和风格标签注入 prompt，
        确保全片角色外观和画面风格一致。
        """
        if not visual or not visual.strip():
            style = ""
            if visual_bible and visual_bible.style_tags:
                style = visual_bible.style_tags + ", "
            return f"{style}a cinematic scene, highly detailed, 4K"

        # 构建角色锚点上下文（如果有 visual_bible）
        bible_context = ""
        if visual_bible:
            if visual_bible.characters:
                char_lines = []
                for ch in visual_bible.characters:
                    name = ch.get("name", "")
                    anchor = ch.get("prompt_anchor", "")
                    if name and anchor:
                        char_lines.append(f"- {name} → {anchor}")
                if char_lines:
                    bible_context += (
                        "【角色锚点 - 翻译时必须使用以下固定外观描述】\n"
                        + "\n".join(char_lines) + "\n"
                        "如果画面描述中提到以上角色，必须使用对应的英文锚点描述，不能自由发挥。\n\n"
                    )
            if visual_bible.style_tags:
                bible_context += f"【全片风格标签（必须附加到末尾）】{visual_bible.style_tags}\n\n"

        try:
            llm = self._get_llm()
            system = _VISUAL_TO_IMAGE_PROMPT
            if bible_context:
                system = bible_context + system
            response = llm.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": visual},
                ],
                temperature=0.5,
            )
            prompt = response.content.strip()
            if prompt:
                return prompt
        except Exception as exc:
            log.warning("LLM 视觉翻译失败 seg %d: %s，使用规则翻译", seg_id, exc)

        return self._visual_to_prompt_local(visual, visual_bible)

    def _visual_to_video_prompt(self, visual: str, seg_id: int, visual_bible=None) -> str:
        """将中文画面描述翻译为英文视频生成 prompt。"""
        if not visual or not visual.strip():
            return ""

        # 注入角色锚点
        bible_context = ""
        if visual_bible and visual_bible.characters:
            char_lines = []
            for ch in visual_bible.characters:
                name = ch.get("name", "")
                anchor = ch.get("prompt_anchor", "")
                if name and anchor:
                    char_lines.append(f"- {name} → {anchor}")
            if char_lines:
                bible_context = (
                    "【角色锚点 - 必须使用固定外观描述】\n"
                    + "\n".join(char_lines) + "\n\n"
                )

        try:
            llm = self._get_llm()
            system = _VISUAL_TO_VIDEO_PROMPT
            if bible_context:
                system = bible_context + system
            response = llm.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": visual},
                ],
                temperature=0.5,
            )
            prompt = response.content.strip()
            if prompt:
                return prompt
        except Exception as exc:
            log.warning("LLM 视频prompt翻译失败 seg %d: %s", seg_id, exc)

        return self._visual_to_prompt_local(visual, visual_bible)

    @staticmethod
    def _visual_to_prompt_local(visual: str, visual_bible=None) -> str:
        """规则翻译兜底：从中文画面描述提取关键词 + 角色锚点注入。"""
        import re
        parts = []

        # 如果有 visual_bible，尝试注入角色锚点
        if visual_bible and visual_bible.characters:
            for ch in visual_bible.characters:
                name = ch.get("name", "")
                anchor = ch.get("prompt_anchor", "")
                if name and anchor and name in visual:
                    parts.append(anchor)

        # 性别检测（仅在未通过角色锚点匹配时）
        if not parts:
            if re.search(r'女人|女性|女孩|少女|女子|姑娘|她', visual):
                parts.append("a young woman")
            elif re.search(r'男人|男性|男孩|少年|男子|他', visual):
                parts.append("a young man")

        # 外观关键词
        appearance_map = [
            (r'西装|正装', 'wearing a suit'),
            (r'黑色', 'black'),
            (r'白色', 'white'),
            (r'红色', 'red'),
            (r'长发', 'long hair'),
            (r'短发', 'short hair'),
            (r'眼镜', 'wearing glasses'),
            (r'帽子', 'wearing a hat'),
        ]
        for pattern, desc in appearance_map:
            if re.search(pattern, visual):
                parts.append(desc)

        # 动作关键词
        action_map = [
            (r'站|站着|站立', 'standing'),
            (r'坐|坐着', 'sitting'),
            (r'跑|奔跑', 'running'),
            (r'走|行走|走路', 'walking'),
            (r'回头|转身', 'turning around'),
            (r'微笑|笑', 'smiling'),
            (r'哭|流泪', 'crying'),
            (r'俯瞰|俯视', 'looking down from above'),
        ]
        for pattern, desc in action_map:
            if re.search(pattern, visual):
                parts.append(desc)

        # 场景关键词
        scene_map = [
            (r'城市|都市|高楼', 'modern city'),
            (r'夜景|夜晚|深夜', 'night scene, city lights'),
            (r'办公室|工位', 'modern office'),
            (r'窗前|落地窗|窗户', 'standing by window'),
            (r'沙发|客厅', 'living room, sofa'),
            (r'厨房|做饭', 'kitchen'),
            (r'卧室|床', 'bedroom'),
            (r'街道|马路', 'city street'),
            (r'森林|树林', 'forest'),
            (r'海边|海滩|大海', 'beach, ocean'),
            (r'太空|宇宙|星空', 'outer space, stars'),
            (r'雨|下雨', 'rain'),
            (r'雪|下雪', 'snow'),
            (r'咖啡|咖啡店', 'coffee shop'),
            (r'医院|病房', 'hospital'),
            (r'学校|教室', 'school, classroom'),
            (r'车|汽车', 'car'),
        ]
        for pattern, desc in scene_map:
            if re.search(pattern, visual):
                parts.append(desc)
        if not parts:
            parts.append("a cinematic scene")

        # 注入全片风格标签
        if visual_bible and visual_bible.style_tags:
            parts.append(visual_bible.style_tags)

        parts.append("highly detailed, cinematic lighting, 4K")
        return ", ".join(parts)

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
            if not seg.asset_path or not seg.audio_path:
                log.warning("segment %d 缺少素材或配音，跳过", seg.id)
                continue

            asset_path = Path(seg.asset_path)
            audio_path = Path(seg.audio_path)
            srt_path = Path(seg.srt_path) if seg.srt_path else None

            images.append(asset_path)

            if seg.asset_type in (AssetType.IMAGE2VIDEO, AssetType.VIDEO):
                has_video_clips = True
                video_clips.append(asset_path)
            else:
                video_clips.append(asset_path)  # 静图也传路径，assembler 会用 Ken Burns

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
