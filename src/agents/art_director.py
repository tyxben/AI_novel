"""美术指导 Agent - 图片生成 + 质量控制"""
from __future__ import annotations

from pathlib import Path

from src.agents.state import AgentState, Decision
from src.agents.utils import make_decision, extract_json_obj
from src.tools.prompt_gen_tool import PromptGenTool
from src.tools.image_gen_tool import ImageGenTool
from src.logger import log


class ArtDirectorAgent:
    MAX_RETRIES = 3
    QUALITY_THRESHOLD = 6.0

    def __init__(self, config: dict, budget_mode: bool = False):
        self.config = config
        self.budget_mode = budget_mode
        self.prompt_gen = PromptGenTool(config)
        self.image_gen = ImageGenTool(config)
        self._vision_llm = None

    def _get_vision_llm(self):
        """懒加载视觉 LLM（质量评估用）"""
        if self._vision_llm is None:
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
                log.warning("OpenAI 视觉模型不可用: %s，禁用质量检查", e)
                self._vision_llm = None
        return self._vision_llm

    def generate_image(
        self,
        text: str,
        index: int,
        workspace: Path,
        full_text: str | None = None,
    ) -> tuple[Path, float, int, list[Decision]]:
        """生成图片，可选质量控制。返回 (path, score, retries, decisions)"""
        img_dir = Path(workspace) / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        decisions: list[Decision] = []

        retry_count = 0
        best_path: Path | None = None
        best_score = 0.0

        threshold = (
            self.config.get("agent", {})
            .get("quality_check", {})
            .get("threshold", self.QUALITY_THRESHOLD)
        )
        max_retries = (
            self.config.get("agent", {})
            .get("quality_check", {})
            .get("max_retries", self.MAX_RETRIES)
        )
        quality_enabled = not self.budget_mode and self.config.get("agent", {}).get(
            "quality_check", {}
        ).get("enabled", False)

        while retry_count <= max_retries:
            # 生成 prompt
            prompt = self.prompt_gen.run(
                text, segment_index=index, full_text=full_text
            )

            # 生成图片
            suffix = f"_r{retry_count}" if retry_count > 0 else ""
            out_path = img_dir / f"{index:04d}{suffix}.png"
            self.image_gen.run(prompt, out_path)

            if not quality_enabled:
                decisions.append(make_decision(
                    "ArtDirector",
                    f"image_seg{index}",
                    f"生成图片（{'省钱模式' if self.budget_mode else '质量检查关闭'}）",
                    f"prompt: {prompt[:80]}...",
                ))
                return out_path, -1.0, 0, decisions

            # 质量评估
            score, feedback = self._evaluate_quality(out_path, text, prompt)

            decisions.append(make_decision(
                "ArtDirector",
                f"quality_seg{index}_try{retry_count}",
                f"评分={score:.1f}/10, {'通过' if score >= threshold else '未通过'}",
                f"反馈: {feedback}",
                data={"score": score, "feedback": feedback},
            ))

            if score > best_score:
                best_path = out_path
                best_score = score

            if score >= threshold:
                return out_path, score, retry_count, decisions

            if retry_count >= max_retries:
                decisions.append(make_decision(
                    "ArtDirector",
                    f"retry_limit_seg{index}",
                    f"达到重试上限，使用最佳结果（评分={best_score:.1f}）",
                    "警告：质量未达标",
                ))
                return best_path, best_score, retry_count, decisions  # type: ignore[return-value]

            retry_count += 1
            log.info(
                "[ArtDirector] 段%d 评分%.1f < %.1f，重试第%d次",
                index,
                score,
                threshold,
                retry_count,
            )

        return best_path, best_score, retry_count, decisions  # type: ignore[return-value]

    def _evaluate_quality(
        self, image_path: Path, text: str, prompt: str
    ) -> tuple[float, str]:
        """GPT-4V/Gemini Vision 评估图片质量"""
        vision_llm = self._get_vision_llm()
        if vision_llm is None:
            return 5.0, "视觉模型不可用，跳过评估"

        import base64

        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode()

        eval_prompt = (
            "你是图片质量评估专家。评估这张 AI 生成的图片。\n\n"
            f"原文：{text[:200]}\n"
            f"Prompt：{prompt[:200]}\n\n"
            "评分维度（总分10分）：\n"
            "1. 构图(0-2) 2. 清晰度(0-2) 3. 文本匹配(0-3) 4. 色彩(0-2) 5. 一致性(0-1)\n\n"
            '输出 JSON：{{"score": 总分, "feedback": "反馈"}}'
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
                return float(data.get("score", 5.0)), data.get("feedback", "")
        except Exception as e:
            log.warning("质量评估失败: %s", e)

        return 5.0, "评估失败，使用默认分数"


def art_director_node(state: AgentState) -> dict:
    """ArtDirector 节点"""
    config = state["config"]
    budget_mode = state.get("budget_mode", False)
    workspace = state["workspace"]
    agent = ArtDirectorAgent(config, budget_mode)

    segments = state["segments"]
    images: list[str] = []
    quality_scores: list[float] = []
    retry_counts: dict[int, int] = {}
    decisions: list[Decision] = []

    decisions.append(make_decision(
        "ArtDirector", "start",
        f"开始生成 {len(segments)} 张图片",
        f"风格={state.get('suggested_style', 'default')}",
    ))

    full_text = state.get("full_text")

    for i, seg in enumerate(segments):
        path, score, retries, seg_decisions = agent.generate_image(
            seg["text"], i, Path(workspace), full_text=full_text
        )
        images.append(str(path))
        quality_scores.append(score)
        decisions.extend(seg_decisions)
        if retries > 0:
            retry_counts[i] = retries

        log.info(
            "[ArtDirector] 段 %d/%d 完成 (评分=%.1f, 重试=%d)",
            i + 1,
            len(segments),
            score,
            retries,
        )

    # 汇总
    valid_scores = [s for s in quality_scores if s >= 0]
    avg_score = sum(valid_scores) / len(valid_scores) if valid_scores else -1

    decisions.append(make_decision(
        "ArtDirector", "summary",
        f"图片生成完成：平均质量={avg_score:.1f}, 总重试={sum(retry_counts.values())}",
        f"{len(images)} 张图片",
    ))

    return {
        "images": images,
        "quality_scores": quality_scores,
        "retry_counts": retry_counts,
        "decisions": decisions,
    }
