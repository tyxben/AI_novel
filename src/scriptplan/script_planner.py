"""ScriptPlanner - 将视频方案转换为结构化脚本"""
from __future__ import annotations
import json
import logging
import re
from src.llm.llm_client import LLMClient
from src.scriptplan.models import (
    AssetType,
    MotionType,
    ScriptSegment,
    SegmentPurpose,
    VideoIdea,
    VideoScript,
    VoiceParams,
)

log = logging.getLogger("scriptplan")

# 用途 → 默认语音参数映射
_PURPOSE_VOICE_DEFAULTS: dict[str, dict] = {
    "hook": {"speed": "+5%", "emotion": "urgent", "pause_after": 0.3},
    "setup": {"speed": "+0%", "emotion": "neutral", "pause_after": 0.2},
    "develop": {"speed": "+0%", "emotion": "narrative", "pause_after": 0.2},
    "twist": {"speed": "-5%", "emotion": "dramatic", "pause_before": 0.5, "pause_after": 0.5},
    "climax": {"speed": "+5%", "emotion": "intense", "pause_after": 0.3},
    "ending": {"speed": "-5%", "emotion": "reflective", "pause_after": 1.0},
}

# 用途 → 默认镜头运动映射
_PURPOSE_MOTION_DEFAULTS: dict[str, str] = {
    "hook": "push_in",
    "setup": "static",
    "develop": "pan",
    "twist": "zoom",
    "climax": "push_in",
    "ending": "static",
}


class ScriptPlanner:
    """将视频方案转换为结构化脚本（逐段旁白+画面+时长）。"""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def plan(self, idea: VideoIdea, inspiration: str) -> VideoScript:
        """生成结构化视频脚本。

        Args:
            idea: 视频方案
            inspiration: 原始灵感（作为创作素材）

        Returns:
            VideoScript 完整视频脚本
        """
        system_prompt = (
            "你是一位专业的短视频编剧。你的任务是将视频方案落地为逐段脚本。\n\n"
            "【每段必须包含】\n"
            "1. purpose: 段落用途 (hook/setup/develop/twist/climax/ending)\n"
            "2. voiceover: 旁白文本（简短有力，口语化，每段15-30字）\n"
            "3. visual: 画面描述（具体可执行，描述画面内容而非抽象概念）\n"
            "4. duration_sec: 时长（2-6秒，hook段2-3秒，twist段4-5秒）\n\n"
            "【短视频编剧法则】\n"
            "1. 一段只表达一个信息点，一个主画面\n"
            "2. 旁白要能和画面同步，不能旁白说A画面是B\n"
            "3. hook段必须制造悬念或冲突，禁止平铺直叙\n"
            "4. 每段旁白必须简短，一句话说完一个信息\n"
            "5. visual必须是具体画面（人物/场景/物体），不能是抽象概念\n"
            "6. 总时长要接近目标时长\n"
            "7. ending段要有互动感，引导观众评论\n\n"
            "请返回严格的 JSON 格式：\n"
            "{\n"
            '  "title": "视频标题（10字以内，有吸引力）",\n'
            '  "theme": "一句话主题",\n'
            '  "hook": "前3秒钩子的核心文案",\n'
            '  "segments": [\n'
            "    {\n"
            '      "id": 1,\n'
            '      "purpose": "hook",\n'
            '      "voiceover": "旁白文本",\n'
            '      "visual": "画面描述",\n'
            '      "duration_sec": 3.0\n'
            "    }\n"
            "  ],\n"
            '  "ending_hook": "结尾互动文案"\n'
            "}"
        )

        user_prompt = (
            f"【视频方案】\n"
            f"类型：{idea.video_type}\n"
            f"目标时长：{idea.target_duration}秒\n"
            f"分段数：{idea.segment_count}段\n"
            f"节奏：{idea.rhythm}\n"
            f"反转类型：{idea.twist_type}\n"
            f"结尾方式：{idea.ending_type}\n"
            f"调性：{idea.tone}\n\n"
            f"【创作素材/灵感】\n{inspiration}\n\n"
            f"请生成 {idea.segment_count} 段脚本，总时长约 {idea.target_duration} 秒。"
        )

        response = self.llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            json_mode=True,
            max_tokens=2048,
        )

        # 解析 JSON
        data = self._parse_response(response.content)

        # 构建 VideoScript
        segments = []
        for seg_data in data.get("segments", []):
            purpose_str = seg_data.get("purpose", "develop")
            try:
                purpose = SegmentPurpose(purpose_str)
            except ValueError:
                purpose = SegmentPurpose.DEVELOP

            # 默认语音参数
            voice_defaults = _PURPOSE_VOICE_DEFAULTS.get(purpose.value, {})
            voice_params = VoiceParams(**voice_defaults)

            # 默认镜头运动
            motion_str = seg_data.get(
                "motion",
                _PURPOSE_MOTION_DEFAULTS.get(purpose.value, "static"),
            )
            try:
                motion = MotionType(motion_str)
            except ValueError:
                motion = MotionType.STATIC

            segments.append(ScriptSegment(
                id=seg_data.get("id", len(segments) + 1),
                purpose=purpose,
                voiceover=seg_data.get("voiceover", ""),
                visual=seg_data.get("visual", ""),
                motion=motion,
                duration_sec=float(seg_data.get("duration_sec", 3.0)),
                voice_params=voice_params,
            ))

        script = VideoScript(
            title=data.get("title", "未命名视频"),
            theme=data.get("theme", ""),
            hook=data.get("hook", segments[0].voiceover if segments else ""),
            tone=idea.tone,
            segments=segments,
            ending_hook=data.get("ending_hook", ""),
            idea=idea,
        )
        script.compute_duration()

        return script

    def _parse_response(self, content: str) -> dict:
        """健壮的 JSON 解析"""
        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown 代码块提取
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试找 {...} 块
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        log.error("ScriptPlanner 无法解析响应: %s", content[:300])
        return {"title": "解析失败", "segments": [], "ending_hook": ""}
