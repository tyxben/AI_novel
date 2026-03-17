"""文档改写器 — 将不适合 PPT 的原始文档改写为演示友好版本

流程：
1. 分析原文档的核心信息和价值点
2. 去除代码、命令行、配置等技术细节
3. 提炼关键论点、数据、案例
4. 重构为适合演示的叙事结构
5. 输出一份全新的"PPT 就绪"文档

这个模块在 pipeline 最前端运行，输出替代原始文本进入后续阶段。
"""

from __future__ import annotations

import logging
import re

from src.llm.llm_client import LLMClient, create_llm_client

log = logging.getLogger("ppt")

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
你是一位资深内容策划师，擅长将各种文档改写为适合制作 PPT 演示的内容。

## 你的任务

用户给你一份原始文档（可能是技术文档、API 说明、代码教程、改进方案等），
你需要将它改写为一份**适合做 PPT 的演示文档**。

## 改写原则

1. **提炼核心价值**：找出文档真正想传达的信息，去掉技术细节
2. **去除代码**：所有代码块、命令行、API 调用都不要保留，改为用自然语言描述其作用
3. **保留数据和事实**：具体的数字、百分比、对比数据是 PPT 的好素材，务必保留
4. **重构叙事**：按照 "背景 → 问题 → 方案 → 价值 → 下一步" 的结构重新组织
5. **添加观点**：原文可能只是罗列事实，你需要提炼出观点和结论
6. **人话表达**：不要用技术术语堆砌，用受众能理解的语言
7. **适当扩展**：如果原文信息密度不够，可以基于你的知识适当补充背景和趋势

## 输出格式

输出一份结构化的中文文档，包含：
- 清晰的标题
- 3-5 个章节，每个章节有小标题
- 每个章节 2-4 段文字，每段 50-150 字
- 关键数据用粗体标注
- 总字数 800-2000 字

## 禁止

- 不要保留任何代码块（```...```）
- 不要保留 curl 命令、API 端点等技术细节
- 不要使用 markdown 的代码格式
- 不要输出"以下是改写后的文档"之类的元描述，直接输出文档内容
"""


class DocumentRewriter:
    """将原始文档改写为 PPT 友好的演示文档。"""

    def __init__(self, config: dict):
        self._llm: LLMClient = create_llm_client(config.get("llm", {}))

    def rewrite(self, text: str) -> str:
        """改写文档为 PPT 友好版本。

        Args:
            text: 原始文档文本。

        Returns:
            改写后的文档文本。如果改写失败，返回原文。
        """
        if not text or not text.strip():
            return text

        # 截断过长文档
        truncated = text[:16000] if len(text) > 16000 else text

        # 提取原文的基本特征，帮助 LLM 理解上下文
        doc_profile = self._profile_document(truncated)

        user_prompt = (
            f"{doc_profile}\n\n"
            f"## 原始文档\n\n{truncated}\n\n"
            f"请将以上文档改写为适合制作 PPT 演示的内容。直接输出改写后的文档。"
        )

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._llm.chat(
                messages,
                temperature=0.6,
                max_tokens=4096,
            )
            rewritten = response.content.strip()

            # 基本校验：改写结果不能太短
            if len(rewritten) < 200:
                log.warning("改写结果过短（%d字），使用原文", len(rewritten))
                return text

            # 去掉可能残留的代码块
            rewritten = re.sub(r"```[\s\S]*?```", "", rewritten)

            log.info(
                "文档改写完成：原文 %d 字 → 改写 %d 字",
                len(text), len(rewritten),
            )
            return rewritten

        except Exception as e:
            log.warning("文档改写失败: %s，使用原文", e)
            return text

    @staticmethod
    def _profile_document(text: str) -> str:
        """快速分析文档特征，生成 profile 描述。"""
        parts: list[str] = ["## 文档特征分析"]

        # 代码占比
        code_blocks = re.findall(r"```[\s\S]*?```", text)
        code_ratio = sum(len(b) for b in code_blocks) / max(len(text), 1)
        if code_ratio > 0.3:
            parts.append(f"- 代码占比较高（{code_ratio:.0%}），需要将代码逻辑转化为自然语言描述")

        # 关键词提取（标题行）
        titles = re.findall(r"^#{1,3}\s+(.+)$", text, re.MULTILINE)
        if titles:
            parts.append(f"- 文档章节：{', '.join(titles[:8])}")

        # URL / API 特征
        urls = re.findall(r"https?://\S+", text)
        if len(urls) > 3:
            parts.append(f"- 包含 {len(urls)} 个 URL，属于技术/API 文档")

        # curl 命令
        curls = re.findall(r"curl\s+", text)
        if curls:
            parts.append(f"- 包含 {len(curls)} 个 curl 命令，需转化为功能描述")

        return "\n".join(parts)
