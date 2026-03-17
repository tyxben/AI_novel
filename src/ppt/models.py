"""PPT 生成模块数据模型"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------


class DeckType(str, Enum):
    """PPT 类型"""

    BUSINESS_REPORT = "business_report"  # 汇报材料
    COURSE_LECTURE = "course_lecture"  # 课程讲义
    PRODUCT_INTRO = "product_intro"  # 产品介绍


class PageRole(str, Enum):
    """页面角色 — 每页在整套演示中的功能"""

    COVER = "cover"
    EXECUTIVE_SUMMARY = "executive_summary"
    BACKGROUND = "background"
    PROGRESS = "progress"
    DATA_EVIDENCE = "data_evidence"
    RISK_PROBLEM = "risk_problem"
    SOLUTION = "solution"
    NEXT_STEPS = "next_steps"
    LEARNING_OBJECTIVES = "learning_objectives"
    CONCEPT_INTRO = "concept_intro"
    KNOWLEDGE_POINT = "knowledge_point"
    EXAMPLE_CASE = "example_case"
    METHOD_STEPS = "method_steps"
    COMMON_MISTAKES = "common_mistakes"
    SUMMARY_REVIEW = "summary_review"
    EXERCISE = "exercise"
    PAIN_POINT = "pain_point"
    MARKET_OPPORTUNITY = "market_opportunity"
    PRODUCT_OVERVIEW = "product_overview"
    CORE_FEATURES = "core_features"
    USE_CASE = "use_case"
    COMPETITIVE_ADVANTAGE = "competitive_advantage"
    CASE_DATA = "case_data"
    BUSINESS_MODEL = "business_model"
    CTA = "cta"
    SECTION_BREAK = "section_break"
    CLOSING = "closing"


class ImageStrategy(str, Enum):
    """图片策略 — 不再是简单的 needs_image=True/False"""

    CHART = "chart"  # 图表（数据可视化）
    DIAGRAM = "diagram"  # 示意图/流程图/结构图
    UI_MOCK = "ui_mock"  # 产品界面/截图
    ILLUSTRATION = "illustration"  # 情绪化插图/装饰图
    NONE = "none"  # 不需要图片


class DocumentType(str, Enum):
    """文档类型枚举"""

    BUSINESS_REPORT = "business_report"
    PRODUCT_INTRO = "product_intro"
    TECH_SHARE = "tech_share"
    TEACHING = "teaching"
    CREATIVE_PITCH = "creative_pitch"
    OTHER = "other"


class Audience(str, Enum):
    """受众类型"""

    BUSINESS = "business"
    TECHNICAL = "technical"
    EDUCATIONAL = "educational"
    CREATIVE = "creative"
    GENERAL = "general"


class Tone(str, Enum):
    """语言风格"""

    PROFESSIONAL = "professional"
    CASUAL = "casual"
    CREATIVE = "creative"
    TECHNICAL = "technical"
    WARM = "warm"


class LayoutType(str, Enum):
    """布局类型"""

    TITLE_HERO = "title_hero"
    SECTION_DIVIDER = "section_divider"
    TEXT_LEFT_IMAGE_RIGHT = "text_left_image_right"
    IMAGE_LEFT_TEXT_RIGHT = "image_left_text_right"
    FULL_IMAGE_OVERLAY = "full_image_overlay"
    THREE_COLUMNS = "three_columns"
    QUOTE_PAGE = "quote_page"
    DATA_HIGHLIGHT = "data_highlight"
    TIMELINE = "timeline"
    BULLET_WITH_ICONS = "bullet_with_icons"
    COMPARISON = "comparison"
    CLOSING = "closing"


class ThemeStyle(str, Enum):
    """主题风格"""

    MODERN = "modern"
    BUSINESS = "business"
    CREATIVE = "creative"
    TECH = "tech"
    EDUCATION = "education"


class ImageOrientation(str, Enum):
    """图片方向"""

    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    SQUARE = "square"


# ---------------------------------------------------------------------------
# 阶段 1：文档分析结果
# ---------------------------------------------------------------------------


class DocumentAnalysis(BaseModel):
    """阶段1：文档分析结果"""

    theme: str = Field(..., description="核心主题（1-2句话）")
    doc_type: DocumentType
    audience: Audience
    tone: Tone
    key_points: list[str] = Field(..., description="核心要点列表")
    has_sections: bool = Field(False, description="是否有明确章节")
    has_data: bool = Field(False, description="是否包含数据/表格")
    has_quotes: bool = Field(False, description="是否有引用内容")
    estimated_pages: int = Field(..., ge=5, le=50, description="建议页数")


# ---------------------------------------------------------------------------
# 阶段 1.5：深度内容提取
# ---------------------------------------------------------------------------


class ContentBlock(BaseModel):
    """文档中提取的一个内容块"""

    block_id: str = Field(..., description="唯一标识，如 'b1', 'b2'")
    block_type: str = Field(
        ...,
        description="内容类型: thesis | argument | data | quote | example | conclusion",
    )
    title: str = Field(..., description="该内容块的概括标题（10-15字）")
    summary: str = Field(
        ..., description="核心内容摘要（50-100字，保留关键数据和事实）"
    )
    source_text: str = Field(..., description="原文片段（用于内容生成时参考）")
    importance: int = Field(..., ge=1, le=5, description="重要性评分 1-5")
    is_external: bool = Field(
        default=False,
        description="是否为外部增强内容（联网搜索/LLM知识补充）",
    )


class ContentMap(BaseModel):
    """文档结构化内容地图"""

    document_thesis: str = Field(..., description="全文核心论点（一句话）")
    content_blocks: list[ContentBlock] = Field(
        ..., description="提取的所有内容块"
    )
    logical_flow: list[str] = Field(
        ..., description="建议的逻辑展示顺序（block_id 列表）"
    )
    key_data_points: list[str] = Field(
        default_factory=list,
        description="文档中的关键数据/数字（如 '市场规模5.2万亿'）",
    )
    key_quotes: list[str] = Field(
        default_factory=list, description="文档中的金句/引用"
    )


# ---------------------------------------------------------------------------
# 页面任务书 & 演示计划
# ---------------------------------------------------------------------------


class SlideTask(BaseModel):
    """页面任务书 — 每页的生成约束"""

    page_role: PageRole
    page_goal: str  # 这页要达成什么目标（一句话）
    must_include: list[str] = Field(default_factory=list)  # 必须包含的信息
    forbidden_content: list[str] = Field(
        default_factory=list
    )  # 禁止出现的内容
    image_strategy: ImageStrategy = ImageStrategy.NONE
    layout_preference: str | None = None  # 推荐布局，可为 None 让系统选


class PresentationPlan(BaseModel):
    """整套演示计划 — 在逐页生成之前先规划全局"""

    deck_type: DeckType
    audience: str  # 受众描述
    core_message: str  # 核心信息（一句话）
    presentation_goal: str  # 演示目标（要让受众怎样）
    narrative_arc: list[str]  # 叙事弧线（如 ["结论先行","说明背景","展示进展",...])
    slides: list[SlideTask]  # 每页的任务书


# ---------------------------------------------------------------------------
# 阶段 2：单页大纲（轻量）
# ---------------------------------------------------------------------------


class SlideOutline(BaseModel):
    """阶段2：单页大纲（轻量，不含设计细节）"""

    page_number: int = Field(..., ge=1)
    slide_type: str = Field(
        ..., description="页面类型，如 title_hero, content, closing"
    )
    layout: LayoutType
    title: str = Field(..., description="页面标题")
    subtitle: str | None = Field(None, description="副标题（可选）")
    key_points: list[str] = Field(default_factory=list, description="内容要点")
    needs_image: bool = Field(False, description="是否需要配图")
    image_prompt: str | None = Field(None, description="英文图片生成 prompt")
    speaker_notes_hint: str = Field("", description="演讲备注提示")
    content_block_ids: list[str] = Field(
        default_factory=list,
        description="关联的内容块 ID 列表（来自 ContentMap）",
    )
    page_role: PageRole | None = None
    page_goal: str = ""
    must_include: list[str] = Field(default_factory=list)
    forbidden_content: list[str] = Field(default_factory=list)
    image_strategy: ImageStrategy = ImageStrategy.NONE


# ---------------------------------------------------------------------------
# 阶段 3：页面内容
# ---------------------------------------------------------------------------


class ColumnItem(BaseModel):
    """三栏布局的单栏内容"""

    subtitle: str = Field(..., max_length=30, description="栏标题")
    description: str = Field(..., max_length=80, description="栏描述")


class IconItem(BaseModel):
    """图标要点"""

    icon_keyword: str = Field(
        ..., description="图标关键词，如 'chart' / 'team' / 'rocket'"
    )
    text: str = Field(..., max_length=30, description="要点文字")


class TimelineStep(BaseModel):
    """时间线/流程步骤"""

    label: str = Field(
        ..., max_length=20, description="步骤标签，如 '2023 Q1' 或 '第一步'"
    )
    description: str = Field(..., max_length=50, description="步骤描述")


class SlideContent(BaseModel):
    """页面内容（阶段3输出）"""

    title: str = Field(..., max_length=50, description="页面标题")
    subtitle: str | None = Field(None, max_length=100, description="副标题（可选）")
    bullet_points: list[str] = Field(
        default_factory=list, description="要点列表，每条<=30字"
    )
    body_text: str | None = Field(None, description="段落文本（某些布局用）")
    speaker_notes: str = Field("", description="演讲备注")

    # data_highlight 布局
    data_value: str | None = Field(None, description="数据高亮值（如'30%'）")
    data_label: str | None = Field(None, description="数据说明文字")
    data_description: str | None = Field(None, description="数据补充说明")

    # quote_page 布局
    quote: str | None = Field(None, description="引用原文")
    quote_author: str | None = Field(None, description="引用来源/作者")

    # three_columns 布局
    columns: list[ColumnItem] = Field(
        default_factory=list, description="三栏内容（3组）"
    )

    # timeline 布局
    steps: list[TimelineStep] = Field(
        default_factory=list, description="时间线步骤（3-5步）"
    )

    # bullet_with_icons 布局
    icon_items: list[IconItem] = Field(
        default_factory=list, description="图标要点列表"
    )

    # comparison 布局
    left_title: str | None = Field(None, description="对比左栏标题")
    left_items: list[str] = Field(default_factory=list, description="对比左栏要点")
    right_title: str | None = Field(None, description="对比右栏标题")
    right_items: list[str] = Field(default_factory=list, description="对比右栏要点")

    # closing 布局
    contact_info: str | None = Field(None, description="联系信息")


# ---------------------------------------------------------------------------
# 设计相关
# ---------------------------------------------------------------------------


class ColorScheme(BaseModel):
    """配色方案"""

    primary: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    accent: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    text: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    background: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")


class FontSpec(BaseModel):
    """字体规格"""

    size: int = Field(..., ge=10, le=72)
    bold: bool = False
    italic: bool = False
    color: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    family: str = Field(default="微软雅黑")


class DecorationSpec(BaseModel):
    """装饰元素规格"""

    has_divider: bool = False
    divider_color: str | None = None
    divider_width: int = Field(default=2, ge=1, le=5)
    has_background_shape: bool = False
    shape_type: Literal["rectangle", "circle", "gradient"] | None = None
    shape_color: str | None = None
    shape_opacity: float = Field(default=0.2, ge=0.0, le=1.0)


class SlideDesign(BaseModel):
    """页面设计方案（阶段4输出）"""

    layout: LayoutType
    colors: ColorScheme
    title_font: FontSpec
    body_font: FontSpec
    note_font: FontSpec
    decoration: DecorationSpec = Field(default_factory=DecorationSpec)
    padding: dict[str, int] = Field(
        default={"left": 80, "right": 80, "top": 60, "bottom": 60},
        description="页边距（像素）",
    )


# ---------------------------------------------------------------------------
# 图片请求
# ---------------------------------------------------------------------------


class ImageRequest(BaseModel):
    """图片生成请求"""

    page_number: int = Field(..., ge=1)
    prompt: str = Field(..., description="英文 prompt")
    size: ImageOrientation = Field(default=ImageOrientation.LANDSCAPE)
    style: str = Field(..., description="风格标签，如 'abstract_business'")


# ---------------------------------------------------------------------------
# 阶段汇总：完整页面规格
# ---------------------------------------------------------------------------


class SlideSpec(BaseModel):
    """完整页面规格（汇总阶段1-5）"""

    page_number: int = Field(..., ge=1)
    content: SlideContent
    design: SlideDesign
    needs_image: bool = False
    image_request: ImageRequest | None = None
    image_path: str | None = Field(None, description="生成后的图片路径")


# ---------------------------------------------------------------------------
# 阶段 2：PPT 大纲
# ---------------------------------------------------------------------------


class PPTOutline(BaseModel):
    """阶段2：PPT 大纲"""

    total_pages: int = Field(..., ge=5, le=50)
    estimated_duration: str = Field(..., description="预计演讲时长，如'8-10分钟'")
    slides: list[SlideSpec]


# ---------------------------------------------------------------------------
# 项目级模型
# ---------------------------------------------------------------------------


class PPTProject(BaseModel):
    """PPT 项目元数据"""

    project_id: str
    input_text: str
    theme: str = Field("modern", description="主题名称")
    max_pages: int = Field(20, ge=5, le=50)
    brand_template: dict | None = None
    status: Literal[
        "analyzing",
        "outlining",
        "writing",
        "designing",
        "imaging",
        "rendering",
        "completed",
        "failed",
    ] = "analyzing"
    current_stage: str = "文档分析"
    progress: float = Field(0.0, ge=0.0, le=1.0)
    analysis: DocumentAnalysis | None = None
    outline: PPTOutline | None = None
    output_path: str | None = None
    quality_report: dict | None = None
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 主题配置
# ---------------------------------------------------------------------------


class ThemeConfig(BaseModel):
    """主题配置（预设或品牌模板）"""

    name: str
    display_name: str = ""
    description: str = ""
    colors: ColorScheme
    title_font: FontSpec
    body_font: FontSpec
    note_font: FontSpec
    layout_preferences: dict = Field(
        default_factory=lambda: {
            "max_bullet_points": 5,
            "prefer_images": True,
            "allow_full_image": True,
        }
    )
    decoration_defaults: DecorationSpec = Field(default_factory=DecorationSpec)
    brand_logo: str | None = Field(None, description="Logo 图片路径")
    footer_text: str | None = None


# ---------------------------------------------------------------------------
# 质量检查
# ---------------------------------------------------------------------------


class QualityIssue(BaseModel):
    """质量问题"""

    page_number: int = Field(..., ge=1)
    issue_type: str = Field(..., description="问题类型，如 'text_overflow'")
    severity: Literal["low", "medium", "high"] = "medium"
    description: str = Field(..., description="问题描述")
    auto_fixable: bool = Field(False, description="是否可自动修复")


class QualityReport(BaseModel):
    """质量报告"""

    total_pages: int = Field(..., ge=0)
    issues: list[QualityIssue] = Field(default_factory=list)
    score: float = Field(..., ge=0.0, le=10.0, description="总分 0-10")
    summary: str = Field("", description="报告摘要")


# ---------------------------------------------------------------------------
# V2: 叙事结构（从主题生成模式）
# ---------------------------------------------------------------------------


class Scenario(str, Enum):
    """PPT 使用场景"""

    QUARTERLY_REVIEW = "quarterly_review"
    PRODUCT_LAUNCH = "product_launch"
    TECH_SHARE = "tech_share"
    COURSE_LECTURE = "course_lecture"
    PITCH_DECK = "pitch_deck"
    WORKSHOP = "workshop"
    STATUS_UPDATE = "status_update"


class NarrativeSection(BaseModel):
    """叙事结构中的一个章节"""

    role: PageRole
    title_hint: str = Field(..., description="标题提示")
    key_points_hint: list[str] = Field(default_factory=list, description="要点提示")
    speaker_notes_hint: str = Field("", description="演讲稿提示")
    layout_preference: LayoutType | None = Field(None, description="推荐布局")
    image_strategy: ImageStrategy = Field(default=ImageStrategy.NONE)
    required: bool = Field(True, description="是否必须保留")


class NarrativeStructure(BaseModel):
    """叙事结构（从主题生成模式的中间产物）"""

    scenario: str = Field(..., description="场景 ID")
    topic: str = Field("", description="用户主题")
    audience: str = Field("business", description="受众")
    total_pages: int = Field(..., ge=5, le=50)
    sections: list[NarrativeSection] = Field(..., description="章节列表")


# ---------------------------------------------------------------------------
# V2: 可编辑大纲（暂停点）
# ---------------------------------------------------------------------------


class EditableSlide(BaseModel):
    """可编辑的单页大纲"""

    page_number: int = Field(..., ge=1)
    role: str = Field(..., description="PageRole 枚举值（字符串）")
    title: str = Field(..., description="页面标题（可编辑）")
    subtitle: str = Field("", description="副标题（可编辑）")
    key_points: list[str] = Field(default_factory=list, description="要点列表（可编辑）")
    layout: str = Field(..., description="LayoutType 枚举值（可编辑）")
    image_strategy: str = Field("none", description="ImageStrategy 枚举值（可编辑）")
    speaker_notes_hint: str = Field("", description="演讲备注提示（可编辑）")
    editable: bool = Field(True, description="是否可编辑")
    locked: bool = Field(False, description="是否锁定")


class EditableOutline(BaseModel):
    """可编辑大纲（暴露给用户的暂停点数据）"""

    project_id: str = Field(..., description="项目 ID")
    total_pages: int = Field(..., ge=1)
    estimated_duration: str = Field("", description="预计演讲时长")
    narrative_arc: str = Field("", description="叙事弧线描述")
    slides: list[EditableSlide] = Field(..., description="页面列表")
