"""图片质量评估工具 - 使用 Vision LLM 评分"""
from __future__ import annotations

import base64
from pathlib import Path

from src.agents.state import QualityEvaluation
from src.agents.utils import extract_json_obj
from src.logger import log


class EvaluateQualityTool:
    """使用 GPT-4V/Gemini Vision 评估图片质量。"""

    def __init__(self, config: dict):
        self.config = config
        self._vision_llm = None

    def _get_vision_llm(self):
        if self._vision_llm is not None:
            return self._vision_llm

        agent_cfg = self.config.get("agent", {})
        quality_cfg = agent_cfg.get("quality_check", {})
        provider = quality_cfg.get("vision_provider", "openai")

        if provider == "gemini":
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI

                self._vision_llm = ChatGoogleGenerativeAI(
                    model="gemini-2.0-flash-exp"
                )
                return self._vision_llm
            except ImportError:
                log.warning("langchain-google-genai 未安装，回退到 openai")

        try:
            from langchain_openai import ChatOpenAI

            self._vision_llm = ChatOpenAI(model="gpt-4o", temperature=0)
        except Exception as e:
            log.warning("OpenAI 视觉模型不可用: %s", e)
            self._vision_llm = None
        return self._vision_llm

    def run(self, image_path: Path, text: str, prompt: str) -> QualityEvaluation:
        """评估图片质量，返回 QualityEvaluation。"""
        vision_llm = self._get_vision_llm()
        if vision_llm is None:
            return QualityEvaluation(
                score=5.0,
                feedback="视觉模型不可用，跳过评估",
                passed=False,
                composition=0,
                clarity=0,
                text_match=0,
                color=0,
                consistency=0,
            )

        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode()

        eval_prompt = (
            "你是图片质量评估专家。评估这张 AI 生成的图片。\n\n"
            f"原文：{text[:200]}\n"
            f"Prompt：{prompt[:200]}\n\n"
            "评分维度（总分10分）：\n"
            "1. 构图(0-2) 2. 清晰度(0-2) 3. 文本匹配(0-3) 4. 色彩(0-2) 5. 一致性(0-1)\n\n"
            '输出 JSON：{{"score": 总分, "composition": 构图, "clarity": 清晰度, '
            '"text_match": 匹配度, "color": 色彩, "consistency": 一致性, "feedback": "反馈"}}'
        )

        try:
            from langchain_core.messages import HumanMessage

            message = HumanMessage(
                content=[
                    {"type": "text", "text": eval_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}"
                        },
                    },
                ]
            )
            result = vision_llm.invoke([message])
            data = extract_json_obj(result.content)
            if data:
                score = float(data.get("score", 5.0))
                threshold = (
                    self.config.get("agent", {})
                    .get("quality_check", {})
                    .get("threshold", 6.0)
                )
                return QualityEvaluation(
                    score=score,
                    composition=float(data.get("composition", 0)),
                    clarity=float(data.get("clarity", 0)),
                    text_match=float(data.get("text_match", 0)),
                    color=float(data.get("color", 0)),
                    consistency=float(data.get("consistency", 0)),
                    feedback=data.get("feedback", ""),
                    passed=score >= threshold,
                )
        except Exception as e:
            log.warning("质量评估失败: %s", e)

        return QualityEvaluation(
            score=5.0,
            feedback="评估失败，使用默认分数",
            passed=False,
            composition=0,
            clarity=0,
            text_match=0,
            color=0,
            consistency=0,
        )
