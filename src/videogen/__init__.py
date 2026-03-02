"""视频生成统一接口层。"""

from src.videogen.video_generator import VideoGenerator, VideoResult, create_video_generator

__all__ = ["VideoGenerator", "VideoResult", "create_video_generator"]
