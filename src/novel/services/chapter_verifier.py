"""ChapterVerifier — 章节硬约束验证。

纯规则验证，零 LLM 成本。检查：
- 必须兑现的债务（在文本中关键词出现）
- 必须回收的伏笔（同上）
- 禁用词（AI 味黑名单）
- 字数偏离（>=20% 算失败）

返回结构化 ``VerifyReport``，上层 SelfRefineLoop / Writer 据此决定是否重写。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable

log = logging.getLogger("novel.verifier")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class Failure:
    """单条验证失败。"""

    rule: str  # "debt" | "foreshadowing" | "banned_phrase" | "length"
    severity: str  # "low" | "medium" | "high"
    detail: str  # 给 Writer 看的可读说明，会拼到重写 prompt 里


@dataclass
class VerifyReport:
    """完整验证结果。"""

    passed: bool
    failures: list[Failure] = field(default_factory=list)
    word_count: int = 0

    @property
    def high_severity_count(self) -> int:
        return sum(1 for f in self.failures if f.severity == "high")

    def to_writer_feedback(self) -> str:
        """格式化失败原因，作为 Writer 重写 prompt 的输入。"""
        if not self.failures:
            return ""
        lines = ["上一稿未达硬性要求，请按下列具体反馈重写："]
        for f in self.failures:
            tag = {"high": "🔴", "medium": "🟠", "low": "🟡"}.get(f.severity, "•")
            lines.append(f"  {tag} [{f.rule}] {f.detail}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# ChapterVerifier
# ---------------------------------------------------------------------------


# 字数偏离阈值: 超过 target_words 的 20% 算 medium，超过 50% 算 high
_LENGTH_TOL_MEDIUM = 0.20
_LENGTH_TOL_HIGH = 0.50


class ChapterVerifier:
    """章节硬约束验证器。无状态、可复用。"""

    def verify(
        self,
        text: str,
        *,
        must_fulfill_debts: list[dict] | None = None,
        must_collect_foreshadowings: list[dict] | None = None,
        banned_phrases: Iterable[str] | None = None,
        target_words: int | None = None,
    ) -> VerifyReport:
        """验证章节文本。

        Args:
            text: 章节正文（已清洗）。
            must_fulfill_debts: ``ObligationTracker`` 返回的债务 dict 列表。
                每项至少含 ``debt_id`` 和 ``description``。
            must_collect_foreshadowings: ``KnowledgeGraph.get_pending_foreshadowings``
                返回的伏笔 dict 列表。每项至少含 ``foreshadowing_id`` 和 ``content``。
            banned_phrases: 禁用短语集合（AI 味黑名单）。
            target_words: 目标字数。None 表示不检查长度。

        Returns:
            ``VerifyReport``。
        """
        failures: list[Failure] = []
        word_count = len(text)

        if must_fulfill_debts:
            failures.extend(self._check_debts(text, must_fulfill_debts))
        if must_collect_foreshadowings:
            failures.extend(
                self._check_foreshadowings(text, must_collect_foreshadowings)
            )
        if banned_phrases:
            failures.extend(self._check_banned(text, banned_phrases))
        if target_words is not None and target_words > 0:
            failures.extend(self._check_length(word_count, target_words))

        return VerifyReport(
            passed=len(failures) == 0,
            failures=failures,
            word_count=word_count,
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_debts(
        self, text: str, debts: list[dict]
    ) -> list[Failure]:
        """检查每条债务的关键短语是否出现在文本中。

        策略：从 ``description`` 提取 4-12 字关键短语（去除前缀如"角色承诺:"、
        "[已发布]"），任意一条命中即算兑现。
        """
        out: list[Failure] = []
        for debt in debts:
            desc = str(debt.get("description", "")).strip()
            phrases = _extract_keywords(desc)
            if not phrases:
                continue
            if not any(p in text for p in phrases):
                debt_id = debt.get("debt_id", "?")
                preview = desc[:80]
                out.append(
                    Failure(
                        rule="debt",
                        severity="high",
                        detail=(
                            f"债务 [{debt_id}] 未兑现: {preview} "
                            f"— 本章正文里至少要出现 {phrases[:3]} 之一并实际推进。"
                        ),
                    )
                )
        return out

    def _check_foreshadowings(
        self, text: str, foreshadowings: list[dict]
    ) -> list[Failure]:
        """检查每条伏笔的核心内容是否在文本中被回收/呼应。"""
        out: list[Failure] = []
        for fs in foreshadowings:
            content = str(fs.get("content", "")).strip()
            phrases = _extract_keywords(content)
            if not phrases:
                continue
            if not any(p in text for p in phrases):
                fid = fs.get("foreshadowing_id", "?")
                preview = content[:80]
                out.append(
                    Failure(
                        rule="foreshadowing",
                        severity="high",
                        detail=(
                            f"伏笔 [{fid}] 未回收/未呼应: {preview} "
                            f"— 本章至少要提及 {phrases[:3]} 之一。"
                        ),
                    )
                )
        return out

    def _check_banned(
        self, text: str, banned: Iterable[str]
    ) -> list[Failure]:
        """禁用短语：出现即失败。重复出现按次数升级 severity。"""
        out: list[Failure] = []
        for phrase in banned:
            phrase = str(phrase).strip()
            if not phrase:
                continue
            count = text.count(phrase)
            if count == 0:
                continue
            severity = "high" if count >= 3 else ("medium" if count == 2 else "low")
            out.append(
                Failure(
                    rule="banned_phrase",
                    severity=severity,
                    detail=(
                        f"禁用词「{phrase}」出现 {count} 次。请用更具象的"
                        f"动作/感官描写替换，避免 AI 套路化表达。"
                    ),
                )
            )
        return out

    def _check_length(
        self, word_count: int, target: int
    ) -> list[Failure]:
        """字数偏离 >=20% medium，>=50% high；偏短偏长都算。"""
        if target <= 0:
            return []
        deviation = abs(word_count - target) / target
        if deviation < _LENGTH_TOL_MEDIUM:
            return []
        severity = "high" if deviation >= _LENGTH_TOL_HIGH else "medium"
        direction = "偏长" if word_count > target else "偏短"
        return [
            Failure(
                rule="length",
                severity=severity,
                detail=(
                    f"字数 {word_count}（目标 {target}，{direction} "
                    f"{deviation * 100:.0f}%）。请{'压缩' if word_count > target else '扩写'}。"
                ),
            )
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# 债务/伏笔 description 常见的元数据前缀，提关键词时跳过
_META_PREFIXES = (
    "[已发布]", "[未发布]",
    "角色承诺:", "角色承诺：", "待完成动作:", "待完成动作：",
    "未解决冲突:", "未解决冲突：", "悬念:", "悬念：",
)


# 高频通用词，拒绝作为关键词（命中无意义）
_STOPWORDS = frozenset({
    "可能", "必须", "应该", "已经", "正在", "或者", "以及", "因此", "但是",
    "如果", "由于", "包括", "继续", "还是", "什么", "怎么", "为何", "为什么",
    "需要", "可以", "无法", "不能", "没有", "有人", "他们", "她们", "我们",
    "之间", "之中", "之后", "之前", "其中", "其他", "什么", "这个", "那个",
    "本章", "本节", "全文", "上一", "下一", "目前", "现在", "之后",
})


def _extract_keywords(desc: str, max_keywords: int = 12) -> list[str]:
    """从描述里抽出短关键词（2-6 字），用于在章节文本中做 substring 命中判定。

    策略：
    1. 去掉元数据前缀
    2. 按标点切片得到子句
    3. 每个子句产出 2/3/4 字的滑动窗口，过滤停用词
    4. 再加入子句首尾的 4-6 字短语（捕捉专有名词组合）

    保证候选词足够细粒度，能匹配真实正文的多种表达形式。
    """
    if not desc:
        return []
    s = desc
    for prefix in _META_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):].lstrip()
            break

    parts = re.split(r"[，。、！？；：…\u201c\u201d\u2018\u2019\"\.\,\!\?\;\:\(\)（）【】]+", s)
    out: list[str] = []
    seen: set[str] = set()

    def _add(word: str) -> None:
        word = word.strip()
        if not word or word in seen or word in _STOPWORDS:
            return
        # 至少 2 字，且必须含中文（避免纯标点/数字）
        if len(word) < 2 or not re.search(r"[\u4e00-\u9fff]", word):
            return
        out.append(word)
        seen.add(word)

    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 子句首尾的 4-6 字短语（专有名词）
        if 4 <= len(part) <= 12:
            _add(part)
        if len(part) > 6:
            _add(part[:6])
            _add(part[-6:])
        # 2/3 字滑动窗口（短词如"灵石"、"伏击"、"林辰"）
        for n in (3, 2):
            for i in range(len(part) - n + 1):
                _add(part[i:i + n])
                if len(out) >= max_keywords * 3:
                    break
        if len(out) >= max_keywords * 3:
            break

    return out[:max_keywords]
