from src.tools.evaluate_quality_tool import EvaluateQualityTool
from src.tools.image_gen_tool import ImageGenTool
from src.tools.prompt_gen_tool import PromptGenTool
from src.tools.segment_tool import SegmentTool
from src.tools.tts_tool import TTSTool
from src.tools.video_assemble_tool import VideoAssembleTool

__all__ = [
    "EvaluateQualityTool",
    "SegmentTool",
    "PromptGenTool",
    "ImageGenTool",
    "TTSTool",
    "VideoAssembleTool",
    "create_tools",
]


def create_tools(config: dict) -> dict:
    """统一初始化所有 Tool，返回 {name: tool_instance} 字典。"""
    return {
        "segment": SegmentTool(config),
        "prompt_gen": PromptGenTool(config),
        "image_gen": ImageGenTool(config),
        "tts": TTSTool(config),
        "video_assemble": VideoAssembleTool(config),
        "evaluate_quality": EvaluateQualityTool(config),
    }
