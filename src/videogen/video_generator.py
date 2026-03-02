"""视频生成抽象接口与工厂函数。

定义 VideoGenerator 基类，所有视频生成后端均需实现 generate() 方法。
通过 create_video_generator() 工厂函数根据配置实例化具体后端。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VideoResult:
    """视频生成结果。"""

    video_path: Path  # 下载后的本地视频文件路径
    duration: float  # 视频时长（秒）
    width: int  # 视频宽度
    height: int  # 视频高度


class VideoGenerator(ABC):
    """视频生成器抽象基类。"""

    @abstractmethod
    def generate(
        self, prompt: str, image_path: Path | None = None, duration: float = 5.0
    ) -> VideoResult:
        """根据文本提示词（可选配合图片）生成视频。

        Args:
            prompt: 视频生成的文本提示词。
            image_path: 可选的首帧图片路径（图生视频模式）。
            duration: 视频时长（秒），默认 5.0。

        Returns:
            VideoResult 包含本地视频路径和元信息。
        """
        ...

    def close(self) -> None:
        """释放资源（子类可覆盖）。"""

    def __del__(self) -> None:
        self.close()


def create_video_generator(config: dict) -> VideoGenerator:
    """根据配置创建视频生成器实例。

    Args:
        config: videogen 配置字典，必须包含 backend 字段。

    Returns:
        对应后端的 VideoGenerator 实例。

    Raises:
        ValueError: 未知的后端名称。
    """
    backend = config.get("backend", "kling")
    if backend == "kling":
        from src.videogen.kling_backend import KlingBackend

        return KlingBackend(config)
    elif backend == "seedance":
        from src.videogen.seedance_backend import SeedanceBackend

        return SeedanceBackend(config)
    elif backend == "minimax":
        from src.videogen.minimax_backend import MinimaxBackend

        return MinimaxBackend(config)
    elif backend == "sora":
        from src.videogen.sora_backend import SoraBackend

        return SoraBackend(config)
    else:
        raise ValueError(f"Unknown video backend: {backend}")
