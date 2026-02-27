"""图片生成抽象接口与工厂函数。

定义 ImageGenerator 基类，所有图片生成后端均需实现 generate() 方法。
通过 create_image_generator() 工厂函数根据配置实例化具体后端。
"""

from abc import ABC, abstractmethod

from PIL import Image


class ImageGenerator(ABC):
    """图片生成器抽象基类。"""

    @abstractmethod
    def generate(self, prompt: str) -> Image.Image:
        """根据文本提示词生成一张图片。

        Args:
            prompt: 用于图片生成的文本提示词。

        Returns:
            生成的 PIL Image 对象。
        """
        ...


def create_image_generator(config: dict) -> ImageGenerator:
    """根据配置创建图片生成器实例。

    Args:
        config: imagegen 配置字典，必须包含 backend 字段。

    Returns:
        对应后端的 ImageGenerator 实例。

    Raises:
        ValueError: 未知的后端名称。
    """
    backend = config.get("backend", "diffusers")
    if backend == "diffusers":
        from src.imagegen.diffusers_backend import DiffusersBackend

        return DiffusersBackend(config)
    elif backend == "together":
        from src.imagegen.together_backend import TogetherBackend

        return TogetherBackend(config)
    elif backend == "siliconflow":
        from src.imagegen.siliconflow_backend import SiliconFlowBackend

        return SiliconFlowBackend(config)
    elif backend == "pollinations":
        from src.imagegen.pollinations_backend import PollinationsBackend

        return PollinationsBackend(config)
    elif backend == "dashscope":
        from src.imagegen.dashscope_backend import DashScopeBackend

        return DashScopeBackend(config)
    else:
        raise ValueError(f"Unknown image backend: {backend}")
