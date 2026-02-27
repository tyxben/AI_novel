"""Diffusers 后端 - 基于 HuggingFace diffusers 的本地 Stable Diffusion 图片生成。

支持 MPS (Apple Silicon) / CUDA / CPU 三种设备，默认针对竖屏 9:16
短视频格式 (1024x1792) 生成图片。模型采用懒加载策略，首次调用
generate() 时才加载到显存，避免启动时的长时间等待。
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from src.imagegen.image_generator import ImageGenerator
from src.logger import log


def _detect_device(requested: str) -> str:
    """自动检测最佳可用设备。

    Args:
        requested: 用户请求的设备，``"auto"`` 时自动选择。

    Returns:
        实际使用的设备字符串: ``"cuda"`` / ``"mps"`` / ``"cpu"``。
    """
    if requested != "auto":
        return requested

    import torch

    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class DiffusersBackend(ImageGenerator):
    """基于 HuggingFace diffusers 的 Stable Diffusion 图片生成后端。

    Args:
        config: imagegen 配置字典，支持以下字段:
            model          - 模型 ID 或本地路径 (默认 stabilityai/stable-diffusion-2-1)
            width          - 输出图片宽度 (默认 1024)
            height         - 输出图片高度 (默认 1792，竖屏 9:16)
            steps          - 推理步数 (默认 30)
            guidance_scale - CFG 引导系数 (默认 7.5)
            device         - 运行设备: auto / cuda / mps / cpu (默认 auto)
            seed           - 随机种子，设为固定值可复现结果 (默认 None，随机)
            style          - 风格预设名称，用于附加正/负面提示词 (默认 None)
    """

    def __init__(self, config: dict) -> None:
        self.model_id: str = config.get("model", "stabilityai/stable-diffusion-2-1")
        self.width: int = int(config.get("width", 1024))
        self.height: int = int(config.get("height", 1792))
        self.steps: int = int(config.get("steps", 30))
        self.guidance_scale: float = float(config.get("guidance_scale", 7.5))
        self.device: str = _detect_device(config.get("device", "auto"))
        self.seed: int | None = config.get("seed")
        self.style: str | None = config.get("style")

        # Pipeline 延迟加载
        self._pipe: Any = None

        log.info(
            "DiffusersBackend 初始化: model=%s, size=%dx%d, steps=%d, device=%s",
            self.model_id,
            self.width,
            self.height,
            self.steps,
            self.device,
        )

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        """懒加载 Stable Diffusion pipeline 到指定设备。

        首次调用时执行模型下载（如未缓存）和加载，后续调用直接跳过。
        针对 MPS 设备启用特定优化以降低显存占用。
        """
        if self._pipe is not None:
            return

        import torch
        from diffusers import StableDiffusionPipeline

        log.info("正在加载 Stable Diffusion 模型: %s ...", self.model_id)

        # MPS 上 float16 容易出现黑图或类型冲突，统一用 float32 更稳定
        # M2 Max 32GB 跑 float32 完全没问题
        if self.device in ("cpu", "mps"):
            dtype = torch.float32
        else:
            dtype = torch.float16

        self._pipe = StableDiffusionPipeline.from_pretrained(
            self.model_id,
            torch_dtype=dtype,
            safety_checker=None,
            requires_safety_checker=False,
        )

        self._pipe = self._pipe.to(self.device)

        # 通用内存优化: attention slicing 降低峰值显存
        self._pipe.enable_attention_slicing()

        # MPS 特定优化
        if self.device == "mps":
            log.info("已启用 MPS 优化 (float32 + attention slicing)")

        # CUDA 特定优化
        if self.device == "cuda":
            try:
                self._pipe.enable_xformers_memory_efficient_attention()
                log.info("已启用 xformers 内存高效注意力")
            except Exception:
                log.debug("xformers 不可用，使用默认注意力机制")

        log.info("模型加载完成，设备: %s, 精度: %s", self.device, dtype)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, prompt: str) -> Image.Image:
        """根据文本提示词生成图片。

        首次调用时自动加载模型。支持风格预设的正/负面提示词叠加。

        Args:
            prompt: 图片生成的文本提示词。

        Returns:
            生成的 PIL Image (RGB)，尺寸为 width x height。

        Raises:
            RuntimeError: 模型加载或推理失败。
        """
        import torch

        # 懒加载模型
        self._load_model()

        # 构建最终提示词（叠加风格预设）
        final_prompt, negative_prompt = self._build_prompts(prompt)

        log.info(
            "开始生成图片: %dx%d, steps=%d, guidance=%.1f",
            self.width,
            self.height,
            self.steps,
            self.guidance_scale,
        )
        log.debug("Prompt: %s", final_prompt[:120])
        if negative_prompt:
            log.debug("Negative: %s", negative_prompt[:120])

        # 构建随机数生成器以确保可复现性
        generator = None
        if self.seed is not None:
            generator = torch.Generator(device=self.device)
            generator.manual_seed(self.seed)
            log.debug("使用固定种子: %d", self.seed)

        try:
            with torch.no_grad():
                result = self._pipe(
                    prompt=final_prompt,
                    negative_prompt=negative_prompt or None,
                    width=self.width,
                    height=self.height,
                    num_inference_steps=self.steps,
                    guidance_scale=self.guidance_scale,
                    generator=generator,
                )
        except Exception as exc:
            log.error("图片生成失败: %s", exc)
            raise RuntimeError(f"Stable Diffusion 推理失败: {exc}") from exc

        image: Image.Image = result.images[0]

        # 确保输出为 RGB 模式
        if image.mode != "RGB":
            image = image.convert("RGB")

        log.info("图片生成完成: %dx%d", image.width, image.height)
        return image

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_prompts(self, prompt: str) -> tuple[str, str]:
        """构建最终的正面和负面提示词。

        如果配置了风格预设，将预设的 prefix 添加到提示词前，positive
        关键词追加到末尾，negative 关键词作为负面提示词。

        Args:
            prompt: 用户原始提示词。

        Returns:
            (final_prompt, negative_prompt) 元组。
        """
        negative_prompt = ""

        if not self.style:
            return prompt, negative_prompt

        try:
            from src.promptgen.style_presets import get_preset

            preset = get_preset(self.style)
        except (KeyError, ImportError) as exc:
            log.warning("风格预设 '%s' 加载失败: %s，使用原始 prompt", self.style, exc)
            return prompt, negative_prompt

        # 用 prefix 包装提示词，追加 positive 关键词
        prefix = preset.get("prefix", "")
        positive = preset.get("positive", "")
        negative_prompt = preset.get("negative", "")

        parts = []
        if prefix:
            parts.append(prefix)
        parts.append(prompt)
        if positive:
            parts.append(positive)

        final_prompt = ", ".join(parts)
        return final_prompt, negative_prompt
