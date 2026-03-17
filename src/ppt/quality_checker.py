"""PPT 质量检查器 - 检测并修复排版问题"""

from __future__ import annotations

import logging
from copy import deepcopy

from src.ppt.models import (
    LayoutType,
    QualityIssue,
    QualityReport,
    SlideSpec,
)

log = logging.getLogger("ppt")

# ---------------------------------------------------------------------------
# 阈值常量
# ---------------------------------------------------------------------------

_TITLE_WARN_LEN = 20
_TITLE_ERROR_LEN = 30
_BULLET_WARN_LEN = 50
_MAX_BULLETS = 6
_MAX_CONSECUTIVE_SAME_LAYOUT = 3
_FIX_MAX_BULLETS = 5
_MIN_BULLET_LEN = 8
_MIN_BULLETS_FOR_CONTENT_PAGE = 2
_REDUNDANT_TITLE_THRESHOLD = 0.8  # 标题与要点重复度阈值

# 需要图片的布局
_IMAGE_LAYOUTS = frozenset(
    {
        LayoutType.TITLE_HERO,
        LayoutType.TEXT_LEFT_IMAGE_RIGHT,
        LayoutType.IMAGE_LEFT_TEXT_RIGHT,
        LayoutType.FULL_IMAGE_OVERLAY,
    }
)


class QualityChecker:
    """PPT 质量检查器，检测并修复排版问题。"""

    def check(self, slides: list[SlideSpec]) -> QualityReport:
        """检查所有页面的质量问题。

        检查项：
        1. 文本溢出：标题/内容是否超出预期长度
        2. 内容过多：bullet 数量过多
        3. 布局多样性：连续相同布局
        4. 空内容检查：标题或内容为空
        5. 图片缺失：需要图片但无图片路径

        Returns:
            QualityReport 对象。
        """
        issues: list[QualityIssue] = []

        for idx, slide in enumerate(slides):
            page = slide.page_number
            issues.extend(self._check_text_overflow(slide, page))
            issues.extend(self._check_content_density(slide, page))
            issues.extend(self._check_empty_content(slide, page))
            issues.extend(self._check_image_missing(slide, page))
            issues.extend(self._check_content_completeness(slide, page))
            issues.extend(self._check_info_density(slide, page))
            issues.extend(self._check_redundant_title(slide, page))

        issues.extend(self._check_layout_diversity(slides))
        issues.extend(self._check_duplicate_titles(slides))

        # 计算分数：满分 10，每个 high 扣 1.5，medium 扣 0.8，low 扣 0.3
        deductions = 0.0
        for issue in issues:
            if issue.severity == "high":
                deductions += 1.5
            elif issue.severity == "medium":
                deductions += 0.8
            else:
                deductions += 0.3
        score = max(0.0, min(10.0, 10.0 - deductions))

        # 摘要
        error_count = sum(1 for i in issues if i.severity == "high")
        warn_count = sum(1 for i in issues if i.severity == "medium")
        low_count = sum(1 for i in issues if i.severity == "low")
        if not issues:
            summary = "质量检查通过，未发现问题"
        else:
            summary = (
                f"发现 {len(issues)} 个问题"
                f"（严重 {error_count}，警告 {warn_count}，轻微 {low_count}）"
            )

        return QualityReport(
            total_pages=len(slides),
            issues=issues,
            score=round(score, 1),
            summary=summary,
        )

    def fix(
        self, slides: list[SlideSpec], report: QualityReport
    ) -> list[SlideSpec]:
        """自动修复可修复的问题。

        - 标题过长 -> 截断 + 省略号
        - bullet 过长 -> 截断
        - 内容过多 -> 截取前5条
        - 空标题 -> 用 "第X页" 替代

        Returns:
            修复后的 SlideSpec 列表（深拷贝，不修改原始数据）。
        """
        fixed = deepcopy(slides)

        # Build page_number -> index lookup
        page_to_idx: dict[int, int] = {
            s.page_number: i for i, s in enumerate(fixed)
        }

        for issue in report.issues:
            if not issue.auto_fixable:
                continue

            idx = page_to_idx.get(issue.page_number)
            if idx is None:
                continue

            slide = fixed[idx]

            if issue.issue_type == "title_overflow":
                slide.content.title = (
                    slide.content.title[:_TITLE_WARN_LEN] + "..."
                )

            elif issue.issue_type == "bullet_overflow":
                slide.content.bullet_points = [
                    bp
                    if len(bp) <= _BULLET_WARN_LEN
                    else bp[:_BULLET_WARN_LEN] + "..."
                    for bp in slide.content.bullet_points
                ]

            elif issue.issue_type == "content_too_dense":
                slide.content.bullet_points = slide.content.bullet_points[
                    :_FIX_MAX_BULLETS
                ]

            elif issue.issue_type == "empty_title":
                slide.content.title = f"第{issue.page_number}页"

        return fixed

    # ------------------------------------------------------------------
    # 检查方法
    # ------------------------------------------------------------------

    def _check_text_overflow(
        self, slide: SlideSpec, page: int
    ) -> list[QualityIssue]:
        """检测文本溢出。"""
        issues: list[QualityIssue] = []
        title = slide.content.title or ""

        if len(title) > _TITLE_ERROR_LEN:
            issues.append(
                QualityIssue(
                    page_number=page,
                    issue_type="title_overflow",
                    severity="high",
                    description=(
                        f"标题过长（{len(title)}字，"
                        f"超过{_TITLE_ERROR_LEN}字限制）"
                    ),
                    auto_fixable=True,
                )
            )
        elif len(title) > _TITLE_WARN_LEN:
            issues.append(
                QualityIssue(
                    page_number=page,
                    issue_type="title_overflow",
                    severity="medium",
                    description=(
                        f"标题偏长（{len(title)}字，"
                        f"建议不超过{_TITLE_WARN_LEN}字）"
                    ),
                    auto_fixable=True,
                )
            )

        for i, bp in enumerate(slide.content.bullet_points):
            if len(bp) > _BULLET_WARN_LEN:
                issues.append(
                    QualityIssue(
                        page_number=page,
                        issue_type="bullet_overflow",
                        severity="medium",
                        description=(
                            f"第{i + 1}条要点过长（{len(bp)}字，"
                            f"建议不超过{_BULLET_WARN_LEN}字）"
                        ),
                        auto_fixable=True,
                    )
                )

        return issues

    def _check_content_density(
        self, slide: SlideSpec, page: int
    ) -> list[QualityIssue]:
        """检测内容密度。"""
        issues: list[QualityIssue] = []
        bullet_count = len(slide.content.bullet_points)

        if bullet_count > _MAX_BULLETS:
            issues.append(
                QualityIssue(
                    page_number=page,
                    issue_type="content_too_dense",
                    severity="medium",
                    description=(
                        f"要点过多（{bullet_count}条，"
                        f"建议不超过{_MAX_BULLETS}条）"
                    ),
                    auto_fixable=True,
                )
            )

        return issues

    def _check_layout_diversity(
        self, slides: list[SlideSpec]
    ) -> list[QualityIssue]:
        """检测布局多样性：连续3个相同布局发出警告。"""
        issues: list[QualityIssue] = []

        if len(slides) < _MAX_CONSECUTIVE_SAME_LAYOUT:
            return issues

        for i in range(2, len(slides)):
            if (
                slides[i].design.layout == slides[i - 1].design.layout
                and slides[i].design.layout == slides[i - 2].design.layout
            ):
                issues.append(
                    QualityIssue(
                        page_number=i + 1,
                        issue_type="layout_monotony",
                        severity="low",
                        description=(
                            f"连续3页使用相同布局"
                            f"（{slides[i].design.layout.value}）"
                        ),
                        auto_fixable=False,
                    )
                )

        return issues

    def _check_empty_content(
        self, slide: SlideSpec, page: int
    ) -> list[QualityIssue]:
        """检测空内容。"""
        issues: list[QualityIssue] = []
        title = (slide.content.title or "").strip()

        if not title:
            issues.append(
                QualityIssue(
                    page_number=page,
                    issue_type="empty_title",
                    severity="high",
                    description="页面标题为空",
                    auto_fixable=True,
                )
            )

        # 检查内容是否完全为空（无要点、无正文、无特殊内容）
        has_content = bool(
            slide.content.bullet_points
            or slide.content.body_text
            or slide.content.quote
            or slide.content.data_value
            or slide.content.columns
            or slide.content.steps
            or slide.content.icon_items
            or slide.content.left_items
            or slide.content.right_items
            or slide.content.contact_info
            or slide.content.subtitle
        )
        if not has_content and not title:
            issues.append(
                QualityIssue(
                    page_number=page,
                    issue_type="empty_content",
                    severity="high",
                    description="页面内容完全为空",
                    auto_fixable=False,
                )
            )

        return issues

    def _check_image_missing(
        self, slide: SlideSpec, page: int
    ) -> list[QualityIssue]:
        """检测需要图片但无图片路径。"""
        issues: list[QualityIssue] = []

        if slide.needs_image and not slide.image_path:
            issues.append(
                QualityIssue(
                    page_number=page,
                    issue_type="image_missing",
                    severity="low",
                    description="需要配图但未提供图片（将使用占位色块）",
                    auto_fixable=False,
                )
            )

        return issues

    def _check_content_completeness(
        self, slide: SlideSpec, page: int
    ) -> list[QualityIssue]:
        """检查内容页至少有足够的要点。

        跳过特殊页面（封面、分隔页、结束页、引用页、数据页）。
        """
        issues: list[QualityIssue] = []
        layout = slide.design.layout

        # 这些布局不需要 bullet_points
        skip_layouts = frozenset({
            LayoutType.TITLE_HERO,
            LayoutType.SECTION_DIVIDER,
            LayoutType.CLOSING,
            LayoutType.QUOTE_PAGE,
            LayoutType.DATA_HIGHLIGHT,
            LayoutType.FULL_IMAGE_OVERLAY,
            LayoutType.THREE_COLUMNS,
            LayoutType.TIMELINE,
        })
        if layout in skip_layouts:
            return issues

        bp_count = len(slide.content.bullet_points)
        # 对于 bullet_with_icons，检查 icon_items
        icon_count = len(slide.content.icon_items) if slide.content.icon_items else 0

        if bp_count < _MIN_BULLETS_FOR_CONTENT_PAGE and icon_count < _MIN_BULLETS_FOR_CONTENT_PAGE:
            issues.append(
                QualityIssue(
                    page_number=page,
                    issue_type="content_incomplete",
                    severity="medium",
                    description=(
                        f"内容页要点不足（{max(bp_count, icon_count)}条，"
                        f"建议至少{_MIN_BULLETS_FOR_CONTENT_PAGE}条）"
                    ),
                    auto_fixable=False,
                )
            )

        return issues

    def _check_info_density(
        self, slide: SlideSpec, page: int
    ) -> list[QualityIssue]:
        """检查要点是否太短（信息量不足）。"""
        issues: list[QualityIssue] = []

        for i, bp in enumerate(slide.content.bullet_points):
            if 0 < len(bp.strip()) < _MIN_BULLET_LEN:
                issues.append(
                    QualityIssue(
                        page_number=page,
                        issue_type="info_too_sparse",
                        severity="medium",
                        description=(
                            f"第{i + 1}条要点信息量不足（{len(bp)}字，"
                            f"建议至少{_MIN_BULLET_LEN}字）"
                        ),
                        auto_fixable=False,
                    )
                )

        return issues

    def _check_redundant_title(
        self, slide: SlideSpec, page: int
    ) -> list[QualityIssue]:
        """检查标题与要点是否高度重复。"""
        issues: list[QualityIssue] = []
        title = (slide.content.title or "").strip()
        if not title or not slide.content.bullet_points:
            return issues

        title_chars = set(title)
        for i, bp in enumerate(slide.content.bullet_points):
            bp_stripped = bp.strip()
            if not bp_stripped:
                continue
            bp_chars = set(bp_stripped)
            # 检查字符集重叠度
            overlap = len(title_chars & bp_chars)
            union = len(title_chars | bp_chars)
            if union > 0 and overlap / union >= _REDUNDANT_TITLE_THRESHOLD:
                issues.append(
                    QualityIssue(
                        page_number=page,
                        issue_type="redundant_title",
                        severity="low",
                        description=(
                            f"标题「{title[:15]}」与第{i + 1}条要点高度重复"
                        ),
                        auto_fixable=False,
                    )
                )
                break  # 只报告一次

        return issues

    def _check_duplicate_titles(
        self, slides: list[SlideSpec]
    ) -> list[QualityIssue]:
        """检查标题是否有重复。"""
        issues: list[QualityIssue] = []
        seen: dict[str, int] = {}

        for slide in slides:
            title = (slide.content.title or "").strip()
            if not title:
                continue
            if title in seen:
                issues.append(
                    QualityIssue(
                        page_number=slide.page_number,
                        issue_type="duplicate_title",
                        severity="medium",
                        description=(
                            f"标题「{title[:15]}」与第{seen[title]}页重复"
                        ),
                        auto_fixable=False,
                    )
                )
            else:
                seen[title] = slide.page_number

        return issues
