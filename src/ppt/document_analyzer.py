"""文档分析器 - 阶段1：分析文档主题、结构、受众"""

from __future__ import annotations

import logging
import re

from src.agents.utils import extract_json_obj
from src.llm.llm_client import LLMClient, create_llm_client
from src.ppt.models import Audience, DocumentAnalysis, DocumentType, Tone

log = logging.getLogger("ppt")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 送给 LLM 的文本最大字符数（约 12k tokens for 中文）
_MAX_INPUT_CHARS = 24000

# 建议页数的参考标准
_SHORT_DOC_THRESHOLD = 2000  # 字符
_MEDIUM_DOC_THRESHOLD = 8000
_SHORT_DOC_PAGES = (8, 12)
_MEDIUM_DOC_PAGES = (12, 20)
_LONG_DOC_PAGES = (20, 30)

_SYSTEM_PROMPT = """\
你是一位资深演讲教练和 PPT 策划专家。你的任务是深度分析用户提供的文档，提取关键信息，
为后续的 PPT 生成提供精准的分析结果。

分析时请重点关注：
1. 这篇文档的核心观点是什么？用1-2句话概括主题
2. 文档类型：是工作汇报、产品介绍、技术分享、教学内容还是创意提案？
3. 目标受众最关心什么？他们的知识水平如何？
4. 语言风格应该是专业正式、轻松随意、创意活泼、技术严谨还是温暖亲切？
5. 提取5-10个关键信息点（核心观点、重要数据、关键案例、核心结论）
6. 文档是否有明确的章节划分？是否包含数据表格？是否有引用内容？
7. 根据内容密度和复杂度，建议生成多少页 PPT？

请以 JSON 格式返回分析结果，严格遵循以下字段：
{
  "theme": "核心主题（1-2句话）",
  "doc_type": "business_report|product_intro|tech_share|teaching|creative_pitch|other",
  "audience": "business|technical|educational|creative|general",
  "tone": "professional|casual|creative|technical|warm",
  "key_points": ["关键信息点1", "关键信息点2", ...],
  "has_sections": true/false,
  "has_data": true/false,
  "has_quotes": true/false,
  "suggested_pages": 15
}

注意：
- key_points 至少包含 3 个，最多 10 个
- suggested_pages 必须是 5-50 之间的整数
- doc_type、audience、tone 必须使用上面列出的枚举值
"""


# ---------------------------------------------------------------------------
# 文档适配性预检（轻量规则，不调 LLM）
# ---------------------------------------------------------------------------

# 代码块标识符
_CODE_FENCE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE = re.compile(r"`[^`]+`")
# curl / http / bash 命令行
_CMD_LINE = re.compile(r"^\s*(curl |wget |pip |npm |git |docker |kubectl |brew )", re.MULTILINE)
# JSON/YAML 块
_JSON_BLOCK = re.compile(r'^\s*[\[{]', re.MULTILINE)
_YAML_KEY = re.compile(r"^\s*\w[\w\-]*:\s", re.MULTILINE)
# URL 行
_URL_LINE = re.compile(r"https?://\S+")


class SuitabilityResult:
    """文档适配性检查结果。"""

    def __init__(
        self,
        suitable: bool,
        score: int,
        reasons: list[str],
        suggestion: str = "",
    ):
        self.suitable = suitable
        self.score = score  # 0-100, >=40 算适合
        self.reasons = reasons
        self.suggestion = suggestion  # LLM 生成的改进建议

    @property
    def message(self) -> str:
        if self.suitable:
            return ""
        parts = ["该文档可能不太适合生成 PPT："]
        parts.extend(f"• {r}" for r in self.reasons)
        if self.suggestion:
            parts.append(f"\n💡 建议：{self.suggestion}")
        return "\n".join(parts)


def check_ppt_suitability(text: str) -> SuitabilityResult:
    """快速检查文档是否适合生成 PPT（纯规则，不调 LLM）。

    检查维度：
    1. 内容长度是否足够
    2. 代码占比是否过高
    3. 是否主要是命令行/API 文档
    4. 是否有足够的散文内容

    Returns:
        SuitabilityResult（suitable=True 表示可以生成）
    """
    if not text or not text.strip():
        return SuitabilityResult(False, 0, ["文档为空"])

    text = text.strip()
    total_len = len(text)
    reasons: list[str] = []
    score = 100

    # 1. 长度检查
    if total_len < 100:
        return SuitabilityResult(False, 5, ["文档内容太短（不足100字），无法生成有意义的 PPT"])
    if total_len < 300:
        score -= 20
        reasons.append("文档内容较短，生成的 PPT 可能信息量不足")

    # 2. 代码块占比
    code_blocks = _CODE_FENCE.findall(text)
    code_chars = sum(len(b) for b in code_blocks)
    # 内联代码：先去掉代码块区域再统计，避免重复计算
    text_no_fences = _CODE_FENCE.sub("", text)
    inline_codes = _INLINE_CODE.findall(text_no_fences)
    code_chars += sum(len(c) for c in inline_codes)

    code_ratio = code_chars / total_len if total_len > 0 else 0
    if code_ratio > 0.5:
        score -= 45
        reasons.append(f"代码占比过高（{code_ratio:.0%}），PPT 不适合展示大量代码")
    elif code_ratio > 0.3:
        score -= 25
        reasons.append(f"代码占比较高（{code_ratio:.0%}），建议精简代码部分")

    # 3. 命令行 / API 文档特征
    cmd_count = len(_CMD_LINE.findall(text))
    url_count = len(_URL_LINE.findall(text))
    lines = text.split("\n")
    non_empty_lines = [l for l in lines if l.strip()]
    total_lines = max(len(non_empty_lines), 1)

    cmd_url_ratio = (cmd_count + url_count) / total_lines
    if cmd_url_ratio > 0.3:
        score -= 25
        reasons.append("大量命令行/URL 内容，更像是技术文档或 README，不太适合做 PPT")

    # 4. JSON/YAML 占比
    json_matches = len(_JSON_BLOCK.findall(text))
    yaml_matches = len(_YAML_KEY.findall(text))
    config_ratio = (json_matches + yaml_matches) / total_lines
    if config_ratio > 0.3:
        score -= 20
        reasons.append("包含大量配置/数据格式内容，不适合直接做 PPT")

    # 5. 散文内容检查（去掉代码后的实际文字量）
    prose = _CODE_FENCE.sub("", text)
    prose = _INLINE_CODE.sub("", prose)
    # 去掉纯符号行
    prose_lines = [l.strip() for l in prose.split("\n") if l.strip()]
    prose_lines = [l for l in prose_lines if len(l) > 10 and not l.startswith("```")]
    prose_chars = sum(len(l) for l in prose_lines)

    if prose_chars < 200:
        score -= 30
        reasons.append("去掉代码后，可展示的文字内容不足200字")

    # 6. 纯变更日志 / diff 检查
    changelog_indicators = sum(
        1 for l in non_empty_lines
        if re.match(r"^\s*[-+✅❌•]|^\s*\d+\.", l)
    )
    if changelog_indicators / total_lines > 0.5:
        score -= 15
        reasons.append("文档以列表/清单为主，可能更适合直接阅读而非演示")

    score = max(0, min(100, score))
    suitable = score >= 40

    return SuitabilityResult(suitable, score, reasons)


def check_ppt_suitability_with_llm(
    text: str, config: dict | None = None
) -> SuitabilityResult:
    """带 LLM 建议的适配性检查。

    先做规则预检，不适合时调 LLM 给出具体建议（什么样的文档更适合）。
    LLM 失败时静默降级为纯规则结果。
    """
    result = check_ppt_suitability(text)
    if result.suitable:
        return result

    # 不适合时，调 LLM 给建议
    try:
        llm_config = (config or {}).get("llm", {})
        llm = create_llm_client(llm_config)

        truncated = text[:2000] if len(text) > 2000 else text
        reasons_text = "\n".join(f"- {r}" for r in result.reasons)

        messages = [
            {
                "role": "system",
                "content": (
                    "你是一位 PPT 制作顾问。用户上传了一份文档想生成 PPT，"
                    "但系统检测到这份文档可能不太适合。\n"
                    "请根据文档内容和检测原因，用2-3句话给出建议：\n"
                    "1. 简要说明为什么这类文档不适合做 PPT\n"
                    "2. 建议用户改用什么样的文档（比如总结报告、"
                    "产品介绍、培训讲义等）\n"
                    "3. 如果用户坚持用这份文档，可以怎样调整内容\n\n"
                    "回复简洁直接，不要用 markdown 格式。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## 检测结果\n{reasons_text}\n\n"
                    f"## 文档内容（前2000字）\n{truncated}"
                ),
            },
        ]

        response = llm.chat(messages, temperature=0.5, max_tokens=300)
        suggestion = response.content.strip()
        if suggestion:
            result.suggestion = suggestion

    except Exception as e:
        log.debug("LLM 建议生成失败: %s", e)
        # 静默降级，不影响规则检查结果

    return result


class DocumentAnalyzer:
    """分析输入文档，提取主题、结构、受众等信息。"""

    def __init__(self, config: dict):
        """创建 LLM client。

        Args:
            config: 项目配置字典，需包含 llm 配置段。
        """
        self._llm: LLMClient = create_llm_client(config.get("llm", {}))

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def analyze(self, text: str) -> DocumentAnalysis:
        """分析文档，返回 DocumentAnalysis 模型。

        流程：
        1. 预处理文本（截断到 max_tokens 限制内，清理无关字符）
        2. 调用 LLM 分析（json_mode=True）
        3. 解析 JSON 返回 DocumentAnalysis

        Args:
            text: 原始文档文本。

        Returns:
            DocumentAnalysis 对象。

        Raises:
            ValueError: 文本为空或过短。
        """
        cleaned = self._preprocess(text)
        if len(cleaned) < 50:
            raise ValueError("文档内容过短，无法进行有效分析（至少需要50个字符）")

        raw_json = self._call_llm(cleaned)
        return self._parse_result(raw_json, cleaned)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _preprocess(self, text: str) -> str:
        """预处理文本：清理无关字符，截断到最大长度。"""
        # 移除连续空白行（保留单个换行）
        cleaned = re.sub(r"\n{3,}", "\n\n", text)
        # 移除行内多余空白
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        # 移除不可见控制字符（保留换行和制表符）
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)
        cleaned = cleaned.strip()

        # 截断到最大长度
        if len(cleaned) > _MAX_INPUT_CHARS:
            # 尝试在句子边界截断
            truncated = cleaned[:_MAX_INPUT_CHARS]
            last_period = max(
                truncated.rfind("。"),
                truncated.rfind("！"),
                truncated.rfind("？"),
                truncated.rfind("\n"),
            )
            if last_period > _MAX_INPUT_CHARS * 0.8:
                truncated = truncated[: last_period + 1]
            cleaned = truncated

        return cleaned

    def _call_llm(self, text: str) -> dict | None:
        """调用 LLM 分析文档，返回解析后的 JSON 字典。"""
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"请分析以下文档：\n\n{text}"},
        ]

        response = self._llm.chat(
            messages,
            temperature=0.3,
            json_mode=True,
            max_tokens=2048,
        )

        return extract_json_obj(response.content)

    def _parse_result(self, raw: dict | None, text: str) -> DocumentAnalysis:
        """将 LLM 返回的 JSON 解析为 DocumentAnalysis，含降级处理。"""
        if raw is None:
            log.warning("LLM 返回无效 JSON，使用 fallback 分析结果")
            return self._fallback_analysis(text)

        try:
            # 映射 suggested_pages -> estimated_pages
            estimated = raw.pop("suggested_pages", None)
            if estimated is not None and "estimated_pages" not in raw:
                raw["estimated_pages"] = estimated

            # 确保 estimated_pages 在合理范围
            pages = raw.get("estimated_pages", 15)
            if not isinstance(pages, int) or pages < 5:
                raw["estimated_pages"] = 5
            elif pages > 50:
                raw["estimated_pages"] = 50

            # 确保 key_points 是列表
            kp = raw.get("key_points")
            if not isinstance(kp, list) or len(kp) == 0:
                raw["key_points"] = self._extract_fallback_key_points(text)

            # 尝试解析枚举值（容错：如果值不在枚举中，用默认值）
            raw["doc_type"] = self._safe_enum(
                raw.get("doc_type"), DocumentType, DocumentType.OTHER
            )
            raw["audience"] = self._safe_enum(
                raw.get("audience"), Audience, Audience.GENERAL
            )
            raw["tone"] = self._safe_enum(
                raw.get("tone"), Tone, Tone.PROFESSIONAL
            )

            return DocumentAnalysis(**raw)

        except Exception as e:
            log.warning(f"解析 LLM 分析结果失败: {e}，使用 fallback")
            return self._fallback_analysis(text)

    def _fallback_analysis(self, text: str) -> DocumentAnalysis:
        """当 LLM 返回无效结果时的降级分析。"""
        text_len = len(text)

        # 简单的页数估算
        if text_len < _SHORT_DOC_THRESHOLD:
            pages = _SHORT_DOC_PAGES[0]
        elif text_len < _MEDIUM_DOC_THRESHOLD:
            pages = _MEDIUM_DOC_PAGES[0]
        else:
            pages = _LONG_DOC_PAGES[0]

        return DocumentAnalysis(
            theme=text[:100].replace("\n", " ").strip() + "...",
            doc_type=DocumentType.OTHER,
            audience=Audience.GENERAL,
            tone=Tone.PROFESSIONAL,
            key_points=self._extract_fallback_key_points(text),
            has_sections="\n#" in text or "\n##" in text,
            has_data=bool(re.search(r"\d+[%％]|\d+\.\d+", text)),
            has_quotes=bool(
                re.search(
                    r'[\u201c\u201d\u300c\u300d\u300e\u300f""]|(?:^|\n)\s*>',
                    text,
                )
            ),
            estimated_pages=pages,
        )

    def _extract_fallback_key_points(self, text: str) -> list[str]:
        """从文本中提取简单的关键点（降级方案）。"""
        # 提取第一个非空行作为可能的标题
        lines = [
            line.strip()
            for line in text.split("\n")
            if line.strip() and len(line.strip()) > 5
        ]
        # 取前5个有意义的行作为关键点
        key_points = []
        for line in lines[:20]:
            # 跳过过短或过长的行
            clean = re.sub(r"^[#\-*\d.、]+\s*", "", line).strip()
            if 5 < len(clean) < 80:
                key_points.append(clean)
            if len(key_points) >= 5:
                break

        if not key_points:
            key_points = ["文档内容待进一步分析"]

        return key_points

    @staticmethod
    def _safe_enum(value: str | None, enum_cls: type, default):
        """安全地将字符串转换为枚举值。"""
        if value is None:
            return default
        try:
            return enum_cls(value)
        except (ValueError, KeyError):
            return default
