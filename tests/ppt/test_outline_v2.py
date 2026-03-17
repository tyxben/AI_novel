"""OutlineGenerator V2 扩展测试

测试 from_narrative() 方法 和 serialize/deserialize 序列化往返。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.ppt.models import (
    EditableOutline,
    EditableSlide,
    ImageStrategy,
    LayoutType,
    NarrativeSection,
    NarrativeStructure,
    PageRole,
    SlideOutline,
)
from src.ppt.outline_generator import (
    OutlineGenerator,
    deserialize_edited_outline,
    serialize_outline_for_edit,
)


# ---------------------------------------------------------------------------
# Helper: 创建 OutlineGenerator 实例，跳过真正的 LLM 创建
# ---------------------------------------------------------------------------


def _make_generator() -> OutlineGenerator:
    """创建 OutlineGenerator 并替换 _llm 为 MagicMock。"""
    with patch("src.ppt.outline_generator.create_llm_client"):
        gen = OutlineGenerator({"llm": {}})
    gen._llm = MagicMock()
    return gen


# ===========================================================================
# TestFromNarrative
# ===========================================================================


class TestFromNarrative:
    """测试 from_narrative() 方法"""

    def _make_narrative(self) -> NarrativeStructure:
        return NarrativeStructure(
            scenario="quarterly_review",
            topic="Q1 产品进展",
            audience="business",
            total_pages=5,
            sections=[
                NarrativeSection(role=PageRole.COVER, title_hint="Q1 汇报"),
                NarrativeSection(
                    role=PageRole.EXECUTIVE_SUMMARY,
                    title_hint="核心亮点",
                    key_points_hint=["GMV +30%"],
                ),
                NarrativeSection(role=PageRole.PROGRESS, title_hint="关键进展"),
                NarrativeSection(role=PageRole.DATA_EVIDENCE, title_hint="数据表现"),
                NarrativeSection(role=PageRole.CLOSING, title_hint="谢谢"),
            ],
        )

    def _mock_llm_response(self):
        data = [
            {"title": "Q1 产品进展汇报", "key_points": [], "image_prompt": "blue tech bg"},
            {"title": "核心亮点", "key_points": ["GMV增长30%", "用户满意度提升"], "image_prompt": None},
            {"title": "关键项目进展", "key_points": ["项目A上线", "项目B迭代"], "image_prompt": "project timeline"},
            {"title": "数据说话", "key_points": ["DAU 突破10万"], "image_prompt": "data chart"},
            {"title": "感谢聆听", "key_points": [], "image_prompt": None},
        ]
        return LLMResponse(content=json.dumps(data), model="test")

    def test_from_narrative_success(self):
        gen = _make_generator()
        gen._llm.chat.return_value = self._mock_llm_response()

        narrative = self._make_narrative()
        result = gen.from_narrative(narrative)

        assert len(result) == 5
        assert all(isinstance(s, SlideOutline) for s in result)
        assert result[0].page_number == 1
        assert result[-1].page_number == 5
        # LLM 填充的标题
        assert result[0].title == "Q1 产品进展汇报"

    def test_from_narrative_llm_failure_uses_fallback(self):
        gen = _make_generator()
        gen._llm.chat.side_effect = Exception("timeout")

        narrative = self._make_narrative()
        result = gen.from_narrative(narrative)

        assert len(result) == 5
        # fallback 使用 title_hint
        assert result[0].title == "Q1 汇报"

    def test_from_narrative_page_roles_preserved(self):
        gen = _make_generator()
        gen._llm.chat.return_value = self._mock_llm_response()

        narrative = self._make_narrative()
        result = gen.from_narrative(narrative)

        assert result[0].page_role == PageRole.COVER
        assert result[1].page_role == PageRole.EXECUTIVE_SUMMARY
        assert result[-1].page_role == PageRole.CLOSING

    def test_from_narrative_layout_diversity_enforced(self):
        """from_narrative 会强制首页 TITLE_HERO、末页 CLOSING"""
        gen = _make_generator()
        gen._llm.chat.return_value = self._mock_llm_response()

        narrative = self._make_narrative()
        result = gen.from_narrative(narrative)

        # _ensure_layout_diversity 强制首页 title_hero、末页 closing
        assert result[0].layout == LayoutType.TITLE_HERO
        assert result[-1].layout == LayoutType.CLOSING

    def test_from_narrative_llm_returns_fewer_pages(self):
        """LLM 返回的页数少于叙事结构 -> 多余骨架用 page_goal 填充"""
        gen = _make_generator()
        # 只返回 3 页数据
        short_data = [
            {"title": "封面", "key_points": [], "image_prompt": "bg"},
            {"title": "亮点", "key_points": ["p1"], "image_prompt": None},
            {"title": "进展", "key_points": ["p2"], "image_prompt": None},
        ]
        gen._llm.chat.return_value = LLMResponse(
            content=json.dumps(short_data), model="test"
        )

        narrative = self._make_narrative()
        result = gen.from_narrative(narrative)

        # 仍然返回 5 页（骨架数量由叙事结构决定）
        assert len(result) == 5
        # 第 4、5 页使用 title_hint fallback（_merge_llm_into_skeletons 中 i >= len(raw)）
        assert result[3].title in ("数据表现", "第 4 页")
        assert result[4].title in ("谢谢", "第 5 页")

    def test_from_narrative_with_target_pages(self):
        """传入 target_pages 参数"""
        gen = _make_generator()
        gen._llm.chat.return_value = self._mock_llm_response()

        narrative = self._make_narrative()
        result = gen.from_narrative(narrative, target_pages=10)

        # target_pages 传入但骨架数量仍然由 narrative.sections 决定
        assert len(result) == 5


# ===========================================================================
# TestSerializeDeserialize
# ===========================================================================


class TestSerializeDeserialize:
    """序列化/反序列化测试"""

    def _make_outlines(self) -> list[SlideOutline]:
        return [
            SlideOutline(
                page_number=1,
                slide_type="title_hero",
                layout=LayoutType.TITLE_HERO,
                title="测试标题",
                subtitle="副标题",
                key_points=["要点1", "要点2"],
                needs_image=True,
                image_prompt="test prompt",
                speaker_notes_hint="备注",
                page_role=PageRole.COVER,
                image_strategy=ImageStrategy.ILLUSTRATION,
            ),
            SlideOutline(
                page_number=2,
                slide_type="bullet_with_icons",
                layout=LayoutType.BULLET_WITH_ICONS,
                title="内容页",
                key_points=["点1", "点2", "点3"],
                needs_image=False,
                page_role=PageRole.PROGRESS,
                image_strategy=ImageStrategy.NONE,
            ),
            SlideOutline(
                page_number=3,
                slide_type="closing",
                layout=LayoutType.CLOSING,
                title="谢谢",
                key_points=[],
                needs_image=False,
                page_role=PageRole.CLOSING,
                image_strategy=ImageStrategy.NONE,
            ),
        ]

    def test_serialize_basic(self):
        outlines = self._make_outlines()
        editable = serialize_outline_for_edit(outlines, project_id="test_123")

        assert isinstance(editable, EditableOutline)
        assert editable.project_id == "test_123"
        assert editable.total_pages == 3
        assert len(editable.slides) == 3

    def test_serialize_slide_fields(self):
        outlines = self._make_outlines()
        editable = serialize_outline_for_edit(outlines, project_id="test_123")

        slide0 = editable.slides[0]
        assert slide0.role == "cover"
        assert slide0.title == "测试标题"
        assert slide0.layout == "title_hero"
        assert slide0.image_strategy == "illustration"
        assert slide0.key_points == ["要点1", "要点2"]

    def test_serialize_editable_flags(self):
        outlines = self._make_outlines()
        editable = serialize_outline_for_edit(outlines, project_id="test_123")

        # cover 和 closing 不可编辑
        assert editable.slides[0].editable is False  # cover
        assert editable.slides[1].editable is True  # progress
        assert editable.slides[2].editable is False  # closing

    def test_roundtrip_no_loss(self):
        """序列化 -> 反序列化后数据无损失"""
        original = self._make_outlines()
        editable = serialize_outline_for_edit(original, project_id="test_123")
        restored = deserialize_edited_outline(editable)

        assert len(restored) == len(original)
        for orig, rest in zip(original, restored):
            assert rest.title == orig.title
            assert rest.layout == orig.layout
            assert rest.page_role == orig.page_role
            assert rest.key_points == orig.key_points
            assert rest.image_strategy == orig.image_strategy

    def test_deserialize_invalid_enum_uses_fallback(self):
        """无效枚举值使用 fallback"""
        editable = EditableOutline(
            project_id="test",
            total_pages=1,
            slides=[
                EditableSlide(
                    page_number=1,
                    role="nonexistent_role",
                    title="测试",
                    layout="nonexistent_layout",
                    image_strategy="nonexistent",
                )
            ],
        )

        result = deserialize_edited_outline(editable)
        assert len(result) == 1
        assert result[0].page_role == PageRole.KNOWLEDGE_POINT  # fallback
        assert result[0].layout == LayoutType.BULLET_WITH_ICONS  # fallback
        assert result[0].image_strategy == ImageStrategy.NONE  # fallback

    def test_estimated_duration(self):
        outlines = self._make_outlines()
        editable = serialize_outline_for_edit(outlines, project_id="test_123")
        assert "分钟" in editable.estimated_duration

    def test_serialize_with_narrative_arc(self):
        outlines = self._make_outlines()
        editable = serialize_outline_for_edit(
            outlines, project_id="test_123", narrative_arc="背景->进展->总结"
        )
        assert editable.narrative_arc == "背景->进展->总结"

    def test_deserialize_needs_image_from_strategy(self):
        """反序列化时 needs_image 由 image_strategy 决定"""
        editable = EditableOutline(
            project_id="test",
            total_pages=2,
            slides=[
                EditableSlide(
                    page_number=1,
                    role="cover",
                    title="封面",
                    layout="title_hero",
                    image_strategy="illustration",
                ),
                EditableSlide(
                    page_number=2,
                    role="closing",
                    title="结束",
                    layout="closing",
                    image_strategy="none",
                ),
            ],
        )

        result = deserialize_edited_outline(editable)
        assert result[0].needs_image is True  # illustration != NONE
        assert result[1].needs_image is False  # none == NONE

    def test_serialize_page_numbers_preserved(self):
        """页码在序列化后保持不变"""
        outlines = self._make_outlines()
        editable = serialize_outline_for_edit(outlines, project_id="test_123")

        for i, slide in enumerate(editable.slides):
            assert slide.page_number == i + 1

    def test_roundtrip_subtitle_empty_to_none(self):
        """空字符串 subtitle 在反序列化后变为 None"""
        outlines = [
            SlideOutline(
                page_number=1,
                slide_type="bullet_with_icons",
                layout=LayoutType.BULLET_WITH_ICONS,
                title="测试",
                subtitle=None,
                key_points=[],
                needs_image=False,
                page_role=PageRole.KNOWLEDGE_POINT,
            ),
        ]
        editable = serialize_outline_for_edit(outlines, project_id="test")
        # serialize 将 None -> ""
        assert editable.slides[0].subtitle == ""

        restored = deserialize_edited_outline(editable)
        # deserialize 将 "" -> None（or 保持 ""）
        # 源码: subtitle=es.subtitle or None，所以 "" -> None
        assert restored[0].subtitle is None
