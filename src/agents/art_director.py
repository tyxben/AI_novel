"""美术指导 Agent - 图片生成 + 质量控制"""
from __future__ import annotations

from pathlib import Path

from src.agents.state import AgentState, Decision, QualityEvaluation
from src.agents.utils import make_decision
from src.tools.prompt_gen_tool import PromptGenTool
from src.tools.image_gen_tool import ImageGenTool
from src.tools.evaluate_quality_tool import EvaluateQualityTool
from src.logger import log


class ArtDirectorAgent:
    MAX_RETRIES = 3
    QUALITY_THRESHOLD = 6.0

    def __init__(self, config: dict, budget_mode: bool = False):
        self.config = config
        self.budget_mode = budget_mode
        self.prompt_gen = PromptGenTool(config)
        self.image_gen = ImageGenTool(config)
        self.quality_tool = EvaluateQualityTool(config)

    def _optimize_prompt(
        self,
        original_prompt: str,
        feedback: str,
        evaluation: QualityEvaluation,
    ) -> str:
        """根据质量反馈优化 prompt。"""
        additions = []
        if evaluation.get("clarity", 0) < 1.5:
            additions.append("sharp focus, high detail, 8k resolution")
        if evaluation.get("composition", 0) < 1.5:
            additions.append("well-composed, rule of thirds, balanced layout")
        if evaluation.get("color", 0) < 1.5:
            additions.append("vibrant colors, harmonious color palette")
        if evaluation.get("text_match", 0) < 2.0:
            additions.append("accurate depiction of the scene")

        if additions:
            return f"{original_prompt}, {', '.join(additions)}"
        return original_prompt

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

        last_prompt: str | None = None
        last_evaluation: QualityEvaluation | None = None

        while retry_count <= max_retries:
            # 生成 prompt
            prompt = self.prompt_gen.run(
                text, segment_index=index, full_text=full_text
            )

            # 重试时根据上次评估反馈优化 prompt
            if retry_count > 0 and last_evaluation is not None:
                feedback = last_evaluation.get("feedback", "")
                prompt = self._optimize_prompt(prompt, feedback, last_evaluation)
                log.info(
                    "[ArtDirector] 段%d 重试优化 prompt: %s",
                    index,
                    prompt[:100],
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

            # 质量评估（使用独立工具）
            evaluation = self.quality_tool.run(out_path, text, prompt)
            score = evaluation.get("score", 5.0)
            feedback = evaluation.get("feedback", "")
            last_prompt = prompt
            last_evaluation = evaluation

            decisions.append(make_decision(
                "ArtDirector",
                f"quality_seg{index}_try{retry_count}",
                f"评分={score:.1f}/10, {'通过' if score >= threshold else '未通过'}",
                f"反馈: {feedback}",
                data={
                    "score": score,
                    "feedback": feedback,
                    "composition": evaluation.get("composition", 0),
                    "clarity": evaluation.get("clarity", 0),
                    "text_match": evaluation.get("text_match", 0),
                    "color": evaluation.get("color", 0),
                    "consistency": evaluation.get("consistency", 0),
                },
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
