"""Tests for src/ppt/quality_checker.py"""

import pytest

from src.ppt.models import (
    ColorScheme,
    DecorationSpec,
    FontSpec,
    LayoutType,
    QualityReport,
    SlideContent,
    SlideDesign,
    SlideSpec,
)
from src.ppt.quality_checker import (
    QualityChecker,
    _BULLET_WARN_LEN,
    _FIX_MAX_BULLETS,
    _MAX_BULLETS,
    _MIN_BULLET_LEN,
    _TITLE_ERROR_LEN,
    _TITLE_WARN_LEN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_design(layout: LayoutType = LayoutType.BULLET_WITH_ICONS) -> SlideDesign:
    return SlideDesign(
        layout=layout,
        colors=ColorScheme(
            primary="#2D3436",
            secondary="#636E72",
            accent="#0984E3",
            text="#2D3436",
        ),
        title_font=FontSpec(size=28, bold=True, color="#2D3436"),
        body_font=FontSpec(size=18, color="#2D3436"),
        note_font=FontSpec(size=14, color="#757575"),
    )


def _make_slide(
    page: int = 1,
    title: str = "Normal Title",
    bullet_points: list[str] | None = None,
    layout: LayoutType = LayoutType.BULLET_WITH_ICONS,
    needs_image: bool = False,
    image_path: str | None = None,
    subtitle: str | None = None,
    body_text: str | None = None,
) -> SlideSpec:
    return SlideSpec(
        page_number=page,
        content=SlideContent(
            title=title,
            subtitle=subtitle,
            bullet_points=bullet_points or [],
            body_text=body_text,
        ),
        design=_make_design(layout),
        needs_image=needs_image,
        image_path=image_path,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTextOverflow:
    """Test _check_text_overflow."""

    def test_normal_title_no_issue(self):
        checker = QualityChecker()
        slide = _make_slide(title="Short Title")
        report = checker.check([slide])
        overflow_issues = [i for i in report.issues if i.issue_type == "title_overflow"]
        assert overflow_issues == []

    def test_title_warning(self):
        checker = QualityChecker()
        title = "a" * (_TITLE_WARN_LEN + 1)
        slide = _make_slide(title=title)
        report = checker.check([slide])
        overflow = [i for i in report.issues if i.issue_type == "title_overflow"]
        assert len(overflow) == 1
        assert overflow[0].severity == "medium"
        assert overflow[0].auto_fixable is True

    def test_title_error(self):
        checker = QualityChecker()
        title = "a" * (_TITLE_ERROR_LEN + 1)
        slide = _make_slide(title=title)
        report = checker.check([slide])
        overflow = [i for i in report.issues if i.issue_type == "title_overflow"]
        assert len(overflow) == 1
        assert overflow[0].severity == "high"

    def test_bullet_overflow(self):
        checker = QualityChecker()
        long_bullet = "x" * (_BULLET_WARN_LEN + 10)
        slide = _make_slide(bullet_points=[long_bullet, "short"])
        report = checker.check([slide])
        bp_issues = [i for i in report.issues if i.issue_type == "bullet_overflow"]
        assert len(bp_issues) == 1
        assert bp_issues[0].severity == "medium"

    def test_multiple_bullet_overflows(self):
        checker = QualityChecker()
        long1 = "a" * 60
        long2 = "b" * 70
        slide = _make_slide(bullet_points=[long1, "ok", long2])
        report = checker.check([slide])
        bp_issues = [i for i in report.issues if i.issue_type == "bullet_overflow"]
        assert len(bp_issues) == 2


class TestContentDensity:
    """Test _check_content_density."""

    def test_normal_bullet_count(self):
        checker = QualityChecker()
        slide = _make_slide(bullet_points=["a", "b", "c"])
        report = checker.check([slide])
        density = [i for i in report.issues if i.issue_type == "content_too_dense"]
        assert density == []

    def test_too_many_bullets(self):
        checker = QualityChecker()
        slide = _make_slide(bullet_points=["p"] * (_MAX_BULLETS + 1))
        report = checker.check([slide])
        density = [i for i in report.issues if i.issue_type == "content_too_dense"]
        assert len(density) == 1
        assert density[0].auto_fixable is True

    def test_exact_limit_no_issue(self):
        checker = QualityChecker()
        slide = _make_slide(bullet_points=["p"] * _MAX_BULLETS)
        report = checker.check([slide])
        density = [i for i in report.issues if i.issue_type == "content_too_dense"]
        assert density == []


class TestLayoutDiversity:
    """Test _check_layout_diversity."""

    def test_diverse_layouts(self):
        checker = QualityChecker()
        slides = [
            _make_slide(page=1, layout=LayoutType.TITLE_HERO, subtitle="sub"),
            _make_slide(page=2, layout=LayoutType.BULLET_WITH_ICONS, subtitle="s"),
            _make_slide(page=3, layout=LayoutType.THREE_COLUMNS, subtitle="s"),
        ]
        report = checker.check(slides)
        layout_issues = [i for i in report.issues if i.issue_type == "layout_monotony"]
        assert layout_issues == []

    def test_three_same_layouts(self):
        checker = QualityChecker()
        slides = [
            _make_slide(page=1, layout=LayoutType.BULLET_WITH_ICONS, subtitle="s"),
            _make_slide(page=2, layout=LayoutType.BULLET_WITH_ICONS, subtitle="s"),
            _make_slide(page=3, layout=LayoutType.BULLET_WITH_ICONS, subtitle="s"),
        ]
        report = checker.check(slides)
        layout_issues = [i for i in report.issues if i.issue_type == "layout_monotony"]
        assert len(layout_issues) == 1
        assert layout_issues[0].page_number == 3

    def test_fewer_than_three_slides(self):
        checker = QualityChecker()
        slides = [
            _make_slide(page=1, layout=LayoutType.BULLET_WITH_ICONS, subtitle="s"),
            _make_slide(page=2, layout=LayoutType.BULLET_WITH_ICONS, subtitle="s"),
        ]
        report = checker.check(slides)
        layout_issues = [i for i in report.issues if i.issue_type == "layout_monotony"]
        assert layout_issues == []


class TestEmptyContent:
    """Test _check_empty_content."""

    def test_empty_title(self):
        checker = QualityChecker()
        slide = _make_slide(title="", subtitle="has subtitle")
        report = checker.check([slide])
        empty_title = [i for i in report.issues if i.issue_type == "empty_title"]
        assert len(empty_title) == 1
        assert empty_title[0].severity == "high"
        assert empty_title[0].auto_fixable is True

    def test_whitespace_title(self):
        checker = QualityChecker()
        slide = _make_slide(title="   ", subtitle="has subtitle")
        report = checker.check([slide])
        empty_title = [i for i in report.issues if i.issue_type == "empty_title"]
        assert len(empty_title) == 1

    def test_empty_everything(self):
        checker = QualityChecker()
        slide = _make_slide(title="", bullet_points=[])
        report = checker.check([slide])
        empty_issues = [
            i
            for i in report.issues
            if i.issue_type in ("empty_title", "empty_content")
        ]
        assert len(empty_issues) == 2

    def test_normal_content_no_issue(self):
        checker = QualityChecker()
        slide = _make_slide(title="OK", bullet_points=["point1"])
        report = checker.check([slide])
        empty_issues = [
            i
            for i in report.issues
            if i.issue_type in ("empty_title", "empty_content")
        ]
        assert empty_issues == []


class TestImageMissing:
    """Test _check_image_missing."""

    def test_needs_image_but_missing(self):
        checker = QualityChecker()
        slide = _make_slide(needs_image=True, image_path=None, subtitle="s")
        report = checker.check([slide])
        img_issues = [i for i in report.issues if i.issue_type == "image_missing"]
        assert len(img_issues) == 1
        assert img_issues[0].severity == "low"

    def test_needs_image_and_has_it(self):
        checker = QualityChecker()
        slide = _make_slide(
            needs_image=True, image_path="/path/to/img.png", subtitle="s"
        )
        report = checker.check([slide])
        img_issues = [i for i in report.issues if i.issue_type == "image_missing"]
        assert img_issues == []

    def test_no_image_needed(self):
        checker = QualityChecker()
        slide = _make_slide(needs_image=False, subtitle="s")
        report = checker.check([slide])
        img_issues = [i for i in report.issues if i.issue_type == "image_missing"]
        assert img_issues == []


class TestFix:
    """Test fix() auto-repair."""

    def test_fix_title_overflow(self):
        checker = QualityChecker()
        long_title = "a" * 35
        slide = _make_slide(title=long_title, subtitle="s")
        report = checker.check([slide])
        fixed = checker.fix([slide], report)
        assert len(fixed[0].content.title) == _TITLE_WARN_LEN + 3  # + "..."
        assert fixed[0].content.title.endswith("...")

    def test_fix_bullet_overflow(self):
        checker = QualityChecker()
        long_bp = "x" * 80
        slide = _make_slide(bullet_points=[long_bp, "short"], subtitle="s")
        report = checker.check([slide])
        fixed = checker.fix([slide], report)
        assert len(fixed[0].content.bullet_points[0]) == _BULLET_WARN_LEN + 3
        assert fixed[0].content.bullet_points[1] == "short"

    def test_fix_content_too_dense(self):
        checker = QualityChecker()
        slide = _make_slide(bullet_points=["p"] * 8, subtitle="s")
        report = checker.check([slide])
        fixed = checker.fix([slide], report)
        assert len(fixed[0].content.bullet_points) == _FIX_MAX_BULLETS

    def test_fix_empty_title(self):
        checker = QualityChecker()
        slide = _make_slide(page=3, title="", subtitle="has subtitle")
        report = checker.check([slide])
        fixed = checker.fix([slide], report)
        assert fixed[0].content.title == "第3页"

    def test_fix_does_not_mutate_original(self):
        checker = QualityChecker()
        long_title = "a" * 35
        slide = _make_slide(title=long_title, subtitle="s")
        report = checker.check([slide])
        checker.fix([slide], report)
        assert slide.content.title == long_title  # original unchanged

    def test_fix_skips_non_fixable(self):
        checker = QualityChecker()
        slide = _make_slide(title="OK", needs_image=True, subtitle="s")
        report = checker.check([slide])
        # image_missing is not auto_fixable
        fixed = checker.fix([slide], report)
        assert fixed[0].image_path is None


class TestReport:
    """Test overall report quality."""

    def test_no_issues_perfect_score(self):
        checker = QualityChecker()
        slide = _make_slide(
            title="OK",
            bullet_points=["这是第一条完整的要点", "这是第二条完整的要点", "这是第三条完整的要点"],
            subtitle="sub",
        )
        report = checker.check([slide])
        assert report.score == 10.0
        assert "通过" in report.summary

    def test_issues_reduce_score(self):
        checker = QualityChecker()
        slide = _make_slide(title="a" * 35, subtitle="sub")  # high severity
        report = checker.check([slide])
        assert report.score < 10.0
        assert len(report.issues) > 0

    def test_report_total_pages(self):
        checker = QualityChecker()
        slides = [
            _make_slide(page=1, subtitle="s"),
            _make_slide(page=2, subtitle="s"),
        ]
        report = checker.check(slides)
        assert report.total_pages == 2


class TestInfoTooSparse:
    """Test _check_info_density for sparse content detection."""

    def test_short_bullet_flagged(self):
        checker = QualityChecker()
        slide = _make_slide(
            bullet_points=["太短了", "这条要点信息量足够了"],
            subtitle="s",
        )
        report = checker.check([slide])
        sparse = [i for i in report.issues if i.issue_type == "info_too_sparse"]
        assert len(sparse) == 1
        assert sparse[0].severity == "medium"

    def test_adequate_bullets_no_issue(self):
        checker = QualityChecker()
        slide = _make_slide(
            bullet_points=["这条要点内容足够长了", "这也是一条完整的要点"],
            subtitle="s",
        )
        report = checker.check([slide])
        sparse = [i for i in report.issues if i.issue_type == "info_too_sparse"]
        assert sparse == []

    def test_empty_bullet_not_flagged(self):
        """空字符串不应被标记为 info_too_sparse。"""
        checker = QualityChecker()
        slide = _make_slide(bullet_points=[""], subtitle="s")
        report = checker.check([slide])
        sparse = [i for i in report.issues if i.issue_type == "info_too_sparse"]
        assert sparse == []

    def test_exact_min_length_not_flagged(self):
        checker = QualityChecker()
        bullet = "a" * _MIN_BULLET_LEN
        slide = _make_slide(bullet_points=[bullet], subtitle="s")
        report = checker.check([slide])
        sparse = [i for i in report.issues if i.issue_type == "info_too_sparse"]
        assert sparse == []


class TestRedundantTitle:
    """Test _check_redundant_title."""

    def test_identical_title_and_bullet(self):
        checker = QualityChecker()
        slide = _make_slide(
            title="市场增长",
            bullet_points=["市场增长"],
            subtitle="s",
        )
        report = checker.check([slide])
        redundant = [i for i in report.issues if i.issue_type == "redundant_title"]
        assert len(redundant) == 1

    def test_different_title_and_bullets(self):
        checker = QualityChecker()
        slide = _make_slide(
            title="市场分析",
            bullet_points=["收入同比增长30%", "用户数突破百万"],
            subtitle="s",
        )
        report = checker.check([slide])
        redundant = [i for i in report.issues if i.issue_type == "redundant_title"]
        assert redundant == []

    def test_no_bullets_no_issue(self):
        checker = QualityChecker()
        slide = _make_slide(title="标题", bullet_points=[], subtitle="s")
        report = checker.check([slide])
        redundant = [i for i in report.issues if i.issue_type == "redundant_title"]
        assert redundant == []

    def test_empty_title_no_issue(self):
        checker = QualityChecker()
        slide = _make_slide(title="", bullet_points=["内容"], subtitle="s")
        report = checker.check([slide])
        redundant = [i for i in report.issues if i.issue_type == "redundant_title"]
        assert redundant == []
