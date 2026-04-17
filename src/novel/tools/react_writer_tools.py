"""Writer ReAct 工具集。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.llm.llm_client import LLMClient
from src.novel.utils import count_words

log = logging.getLogger("novel.react_writer")


class WriterToolkit:
    """Writer 在 ReAct 模式下的工具集合。

    持有内部 _draft 状态，各工具围绕草稿的生成、检查、修改和提交展开。
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self._draft: str = ""
        self._context: dict[str, Any] = {}

    def set_context(self, **kwargs: Any) -> None:
        """更新上下文信息（target_words, characters, previous_text 等）。"""
        self._context.update(kwargs)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def generate_draft(self, scene_prompt: str) -> dict:
        """调用 LLM 生成场景初稿。"""
        messages = [
            {"role": "system", "content": scene_prompt},
            {"role": "user", "content": "请直接输出场景正文，不要标题序号。"},
        ]
        target = self._context.get("target_words", 800)
        # 与 Writer 主路径统一：min(4096, max(900, target*1.4))
        max_tokens = min(4096, max(900, int(target * 1.4)))
        resp = self.llm.chat(messages, temperature=0.85, max_tokens=max_tokens)
        self._draft = resp.content.strip()
        wc = count_words(self._draft)
        return {
            "draft_preview": (
                self._draft[:500] + ("..." if len(self._draft) > 500 else "")
            ),
            "word_count": wc,
            "target_words": target,
        }

    def check_repetition(self) -> dict:
        """检查与前文的句级重复。"""
        prev = self._context.get("previous_text", "")
        if not prev or not self._draft:
            return {"has_issues": False, "details": "无前文可比较"}

        def split_sents(t: str) -> set[str]:
            return {
                s.strip()
                for s in re.split(r"[。！？\n]", t)
                if len(s.strip()) > 5
            }

        cur = split_sents(self._draft)
        prv = split_sents(prev)
        if not cur:
            return {"has_issues": False, "details": "句子不足"}
        overlap = cur & prv
        ratio = len(overlap) / len(cur)
        return {
            "has_issues": ratio > 0.3,
            "overlap_ratio": round(ratio, 2),
            "repeated_sentences": list(overlap)[:5],
        }

    def check_character_names(self) -> dict:
        """检测占位符名称。"""
        chars = self._context.get("characters", [])
        if not chars or not self._draft:
            return {"has_issues": False}
        valid: set[str] = set()
        for c in chars:
            name = c.name if hasattr(c, "name") else c.get("name", "")
            if name:
                valid.add(name)
            alias = c.alias if hasattr(c, "alias") else c.get("alias", [])
            if alias:
                valid.update(alias)
        placeholders = re.findall(
            r"[角色人物][A-Z]|[男女老少][子人]?[甲乙丙丁A-Z]", self._draft
        )
        issues: list[str] = []
        if placeholders:
            issues.append(f"占位符: {placeholders[:5]}")
        return {
            "has_issues": bool(issues),
            "valid_names": list(valid),
            "issues": issues,
        }

    def check_narrative_logic(self) -> dict:
        """LLM 检查叙事逻辑。"""
        if not self._draft:
            return {"has_issues": False}
        ctx = self._context.get("previous_text", "")[:500]
        prompt = (
            "检查小说场景的叙事逻辑：\n"
            "1. 事件是否有头无尾？2. 角色是否突然消失？"
            "3. 前后矛盾？4. 不合理巧合？\n\n"
            f"前文：{ctx}\n\n当前：{self._draft[:1500]}\n\n"
            '返回 JSON: {"issues": ["问题1"], "score": 8.5}'
        )
        resp = self.llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            json_mode=True,
            max_tokens=512,
        )
        try:
            data = json.loads(resp.content)
            return {
                "has_issues": bool(data.get("issues")),
                "issues": data.get("issues", []),
                "score": data.get("score", 7.0),
            }
        except Exception:
            return {"has_issues": False, "issues": [], "score": 7.0}

    def revise_draft(self, issues: str, focus: str = "") -> dict:
        """根据问题修改草稿。"""
        if not self._draft:
            return {"error": "无草稿"}
        prompt = (
            f"修改以下小说正文，解决问题：\n{issues}\n"
            f"{f'重点：{focus}' if focus else ''}\n\n"
            f"原文：\n{self._draft}\n\n"
            "只改有问题的部分，直接输出完整正文。"
        )
        target = self._context.get("target_words", 800)
        # 与 Writer 主路径统一：min(4096, max(900, target*1.4))
        resp = self.llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=min(4096, max(900, int(target * 1.4))),
        )
        self._draft = resp.content.strip()
        return {
            "word_count": count_words(self._draft),
            "revised_preview": self._draft[:500],
        }

    def get_current_draft(self) -> dict:
        """获取当前草稿及字数。"""
        return {
            "draft": self._draft,
            "word_count": count_words(self._draft) if self._draft else 0,
        }

    def submit_final(self, text: str = "") -> str:
        """提交终稿。优先使用传入文本，否则使用当前草稿。

        如果传入的 text 看起来像原始 tool-call JSON，忽略并回退到草稿。
        """
        if text and text.strip().startswith(
            ('{"thinking"', '{"tool"', '{"draft_preview"')
        ):
            log.warning("submit_final 收到原始 JSON，回退到内部草稿")
            text = ""
        return text or self._draft
