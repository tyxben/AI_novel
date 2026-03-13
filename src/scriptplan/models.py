"""短视频脚本数据模型"""
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field


class MotionType(str, Enum):
    """镜头运动类型"""
    STATIC = "static"
    PUSH_IN = "push_in"
    PAN = "pan"
    ZOOM = "zoom"
    ORBIT = "orbit"
    REVEAL = "reveal"


class AssetType(str, Enum):
    """素材类型"""
    IMAGE = "image"               # 静图 + Ken Burns
    IMAGE2VIDEO = "image2video"   # 图生视频
    VIDEO = "video"               # 纯AI视频


class SegmentPurpose(str, Enum):
    """段落用途"""
    HOOK = "hook"             # 开场钩子
    SETUP = "setup"           # 铺垫设定
    DEVELOP = "develop"       # 发展推进
    TWIST = "twist"           # 反转
    CLIMAX = "climax"         # 高潮
    ENDING = "ending"         # 结尾


class VoiceParams(BaseModel):
    """配音参数"""
    speed: str = "+0%"        # edge-tts rate, e.g. "+10%", "-5%"
    emotion: str = "neutral"  # 情绪标签
    pause_before: float = 0.0  # 前置停顿(秒)
    pause_after: float = 0.0  # 后置停顿(秒)


class ScriptSegment(BaseModel):
    """脚本分段"""
    id: int
    purpose: SegmentPurpose
    voiceover: str                          # 旁白文本
    visual: str                             # 画面描述
    motion: MotionType = MotionType.STATIC  # 镜头运动
    duration_sec: float = 3.0               # 目标时长
    asset_type: AssetType = AssetType.IMAGE  # 素材类型
    voice_params: VoiceParams = Field(default_factory=VoiceParams)

    # 生成后填充
    image_prompt: str = ""     # 英文图片生成prompt
    video_prompt: str = ""     # 英文视频生成prompt
    audio_path: str = ""       # 配音文件路径
    srt_path: str = ""         # 字幕文件路径
    asset_path: str = ""       # 素材文件路径（图片或视频）


class VideoIdea(BaseModel):
    """视频方案"""
    video_type: str              # 悬疑反转/情感共鸣/爽文快节奏/知识科普/恐怖...
    target_duration: int = 45    # 目标总时长(秒)
    segment_count: int = 6       # 目标分段数
    rhythm: str = ""             # 节奏描述, e.g. "3秒钩子+3段推进+1段反转+1段收尾"
    twist_type: str = ""         # 反转类型: 身份反转/时间反转/视角反转/无反转
    ending_type: str = ""        # 结尾方式: 评论钩子/悬念留白/情感升华/反问互动
    tone: str = ""               # 整体调性: 悬疑/爽感/温情/恐怖/搞笑


class VideoScript(BaseModel):
    """完整视频脚本"""
    title: str                   # 视频标题
    theme: str                   # 主题
    hook: str                    # 前3秒钩子文案
    tone: str                    # 调性
    segments: list[ScriptSegment] = Field(default_factory=list)
    ending_hook: str = ""        # 结尾互动文案

    # 元数据
    total_duration: float = 0.0  # 总时长(秒)
    idea: VideoIdea | None = None  # 原始方案

    def compute_duration(self) -> float:
        """计算总时长"""
        self.total_duration = sum(s.duration_sec for s in self.segments)
        return self.total_duration
