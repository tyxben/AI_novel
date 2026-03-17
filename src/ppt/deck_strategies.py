"""三类 PPT 的生成策略定义

每类 PPT 有完全不同的：
- 叙事骨架（固定页面结构）
- 页型偏好（哪些 PageRole 必须有）
- 内容优先级（什么信息最重要）
- 图片策略（偏好图表 vs 示意图 vs 装饰图）
- 内容增强默认级别
- 文案风格指导
"""

from __future__ import annotations

from src.ppt.models import DeckType, ImageStrategy, PageRole, SlideTask

# =========================================================================
# 汇报材料 — 结论先行、数据可信、进展清楚
# =========================================================================

BUSINESS_REPORT_STRATEGY: dict = {
    "narrative_arc": [
        "结论先行",
        "说明背景",
        "展示进展",
        "核心数据",
        "暴露风险",
        "提出对策",
        "明确下一步",
    ],
    "default_slides": [
        SlideTask(
            page_role=PageRole.COVER,
            page_goal="建立主题",
            must_include=["项目名称", "汇报周期", "汇报人"],
            image_strategy=ImageStrategy.NONE,
            layout_preference="title_hero",
        ),
        SlideTask(
            page_role=PageRole.EXECUTIVE_SUMMARY,
            page_goal="30秒内讲清结论",
            must_include=["进展结论", "关键风险", "下一步"],
            forbidden_content=["背景复述", "细节展开"],
            image_strategy=ImageStrategy.NONE,
            layout_preference="bullet_with_icons",
        ),
        SlideTask(
            page_role=PageRole.BACKGROUND,
            page_goal="快速交代背景",
            must_include=["项目目标", "关键里程碑"],
            forbidden_content=["冗长历史", "无关信息"],
            image_strategy=ImageStrategy.DIAGRAM,
        ),
        SlideTask(
            page_role=PageRole.PROGRESS,
            page_goal="展示当前进展",
            must_include=["已完成事项", "完成率", "关键交付物"],
            image_strategy=ImageStrategy.CHART,
        ),
        SlideTask(
            page_role=PageRole.DATA_EVIDENCE,
            page_goal="用数据说话",
            must_include=["核心指标", "同比/环比", "趋势"],
            image_strategy=ImageStrategy.CHART,
            layout_preference="data_highlight",
        ),
        SlideTask(
            page_role=PageRole.RISK_PROBLEM,
            page_goal="让领导知道当前最大的阻塞点",
            must_include=["风险描述", "影响范围", "责任人", "预计解决时间"],
            forbidden_content=["空话", "背景复述"],
            image_strategy=ImageStrategy.NONE,
        ),
        SlideTask(
            page_role=PageRole.SOLUTION,
            page_goal="提出具体对策",
            must_include=["对策方案", "资源需求", "预期效果"],
            forbidden_content=["空泛建议"],
            image_strategy=ImageStrategy.DIAGRAM,
        ),
        SlideTask(
            page_role=PageRole.NEXT_STEPS,
            page_goal="明确行动项",
            must_include=["具体任务", "负责人", "截止时间"],
            image_strategy=ImageStrategy.NONE,
            layout_preference="timeline",
        ),
        SlideTask(
            page_role=PageRole.CLOSING,
            page_goal="收尾",
            must_include=["联系方式"],
            image_strategy=ImageStrategy.NONE,
            layout_preference="closing",
        ),
    ],
    "required_roles": {
        PageRole.COVER,
        PageRole.EXECUTIVE_SUMMARY,
        PageRole.PROGRESS,
        PageRole.NEXT_STEPS,
        PageRole.CLOSING,
    },
    "preferred_image_strategy": ImageStrategy.CHART,
    "default_enrich_level": "none",  # 汇报材料最怕补错数据
    "writing_style": (
        "汇报文案风格：\n"
        "- 结论优先，用事实句\n"
        "- 少形容词，少空泛套话\n"
        "- 每句话尽量包含：时间、数字、状态、责任人\n"
        "- 正确示范：'本月完成 A/B 两项关键交付'\n"
        "- 正确示范：'当前风险集中在供应商交期延迟'\n"
        "- 错误示范：'项目持续高效推进，取得阶段性成果'\n"
        "- 错误示范：'我们积极推动各项工作落地'"
    ),
    "audience_hint": "管理层/领导",
    "anti_patterns": [
        "持续推进",
        "阶段性成果",
        "高效",
        "积极",
        "稳步",
        "有序",
        "全面",
    ],
}

# =========================================================================
# 课程讲义 — 讲清楚、易理解、有层次
# =========================================================================

COURSE_LECTURE_STRATEGY: dict = {
    "narrative_arc": [
        "引入主题",
        "建立目标",
        "概念引入",
        "逐层深入",
        "举例说明",
        "方法总结",
        "避坑指南",
        "小结练习",
    ],
    "default_slides": [
        SlideTask(
            page_role=PageRole.COVER,
            page_goal="建立课程主题",
            must_include=["课程名称", "讲师"],
            image_strategy=ImageStrategy.ILLUSTRATION,
            layout_preference="title_hero",
        ),
        SlideTask(
            page_role=PageRole.LEARNING_OBJECTIVES,
            page_goal="让学员知道今天学什么",
            must_include=["3-5个学习目标"],
            forbidden_content=["空泛描述"],
            image_strategy=ImageStrategy.NONE,
            layout_preference="bullet_with_icons",
        ),
        SlideTask(
            page_role=PageRole.CONCEPT_INTRO,
            page_goal="引入核心概念",
            must_include=["概念定义", "为什么重要"],
            image_strategy=ImageStrategy.DIAGRAM,
        ),
        SlideTask(
            page_role=PageRole.KNOWLEDGE_POINT,
            page_goal="讲清楚一个知识点",
            must_include=["定义", "关键特征", "与其他概念的关系"],
            forbidden_content=["只下定义不举例"],
            image_strategy=ImageStrategy.DIAGRAM,
        ),
        SlideTask(
            page_role=PageRole.KNOWLEDGE_POINT,
            page_goal="讲清楚第二个知识点",
            must_include=["定义", "关键特征"],
            image_strategy=ImageStrategy.DIAGRAM,
        ),
        SlideTask(
            page_role=PageRole.EXAMPLE_CASE,
            page_goal="用案例帮助理解",
            must_include=["具体案例", "案例分析", "与知识点的对应"],
            image_strategy=ImageStrategy.ILLUSTRATION,
        ),
        SlideTask(
            page_role=PageRole.METHOD_STEPS,
            page_goal="给出可操作的方法",
            must_include=["步骤", "每步要点", "注意事项"],
            image_strategy=ImageStrategy.DIAGRAM,
            layout_preference="timeline",
        ),
        SlideTask(
            page_role=PageRole.COMMON_MISTAKES,
            page_goal="帮学员避坑",
            must_include=["常见错误", "正确做法"],
            image_strategy=ImageStrategy.NONE,
            layout_preference="comparison",
        ),
        SlideTask(
            page_role=PageRole.SUMMARY_REVIEW,
            page_goal="总结回顾",
            must_include=["核心要点回顾", "关键结论"],
            image_strategy=ImageStrategy.NONE,
        ),
        SlideTask(
            page_role=PageRole.EXERCISE,
            page_goal="引导思考/练习",
            must_include=["思考题或练习题"],
            image_strategy=ImageStrategy.NONE,
        ),
        SlideTask(
            page_role=PageRole.CLOSING,
            page_goal="收尾",
            must_include=["联系方式", "参考资料"],
            image_strategy=ImageStrategy.NONE,
            layout_preference="closing",
        ),
    ],
    "required_roles": {
        PageRole.COVER,
        PageRole.LEARNING_OBJECTIVES,
        PageRole.KNOWLEDGE_POINT,
        PageRole.SUMMARY_REVIEW,
        PageRole.CLOSING,
    },
    "preferred_image_strategy": ImageStrategy.DIAGRAM,
    "default_enrich_level": "llm",  # 可以适度补背景解释
    "writing_style": (
        "课程讲义文案风格：\n"
        "- 术语必须解释清楚，不假设学员已知\n"
        "- 例子先于抽象结论\n"
        "- 一页只讲一个知识点\n"
        "- 用'比如...'、'举个例子...'引导\n"
        "- speaker notes 要有'怎么讲'的提示\n"
        "- 正确示范：'缓存是一种将频繁访问的数据暂存在快速存储中的技术，"
        "比如浏览器缓存网页'\n"
        "- 错误示范：'缓存技术是现代计算机系统中的核心组件'"
    ),
    "audience_hint": "学员/学生",
    "anti_patterns": ["众所周知", "不言而喻", "显而易见", "毋庸置疑"],
}

# =========================================================================
# 产品介绍 — 让人理解产品、产生兴趣、看到价值
# =========================================================================

PRODUCT_INTRO_STRATEGY: dict = {
    "narrative_arc": [
        "痛点共鸣",
        "机会展示",
        "产品亮相",
        "功能演示",
        "场景应用",
        "优势对比",
        "案例证明",
        "商业合作",
    ],
    "default_slides": [
        SlideTask(
            page_role=PageRole.COVER,
            page_goal="建立品牌印象",
            must_include=["产品名称", "一句话定位"],
            image_strategy=ImageStrategy.ILLUSTRATION,
            layout_preference="title_hero",
        ),
        SlideTask(
            page_role=PageRole.PAIN_POINT,
            page_goal="让受众产生共鸣",
            must_include=["用户痛点", "痛点的代价"],
            forbidden_content=["直接推销产品"],
            image_strategy=ImageStrategy.ILLUSTRATION,
        ),
        SlideTask(
            page_role=PageRole.MARKET_OPPORTUNITY,
            page_goal="展示市场机会",
            must_include=["市场规模", "增长趋势", "未被满足的需求"],
            image_strategy=ImageStrategy.CHART,
        ),
        SlideTask(
            page_role=PageRole.PRODUCT_OVERVIEW,
            page_goal="30秒讲清产品是什么",
            must_include=["产品定义", "核心价值主张"],
            forbidden_content=["技术细节堆砌"],
            image_strategy=ImageStrategy.UI_MOCK,
        ),
        SlideTask(
            page_role=PageRole.CORE_FEATURES,
            page_goal="展示3-4个核心功能",
            must_include=["功能名称", "对应的用户收益"],
            forbidden_content=["参数堆砌", "功能列表"],
            image_strategy=ImageStrategy.UI_MOCK,
            layout_preference="three_columns",
        ),
        SlideTask(
            page_role=PageRole.USE_CASE,
            page_goal="展示使用场景",
            must_include=["具体场景", "使用前后对比"],
            image_strategy=ImageStrategy.ILLUSTRATION,
        ),
        SlideTask(
            page_role=PageRole.COMPETITIVE_ADVANTAGE,
            page_goal="建立差异化",
            must_include=["竞争对比", "独特优势"],
            forbidden_content=["贬低竞品"],
            image_strategy=ImageStrategy.NONE,
            layout_preference="comparison",
        ),
        SlideTask(
            page_role=PageRole.CASE_DATA,
            page_goal="用数据/案例证明价值",
            must_include=["客户案例", "效果数据"],
            image_strategy=ImageStrategy.CHART,
        ),
        SlideTask(
            page_role=PageRole.BUSINESS_MODEL,
            page_goal="展示合作方式",
            must_include=["定价/合作模式", "获取方式"],
            image_strategy=ImageStrategy.NONE,
        ),
        SlideTask(
            page_role=PageRole.CTA,
            page_goal="引导行动",
            must_include=["明确的行动号召", "联系方式"],
            image_strategy=ImageStrategy.NONE,
            layout_preference="closing",
        ),
    ],
    "required_roles": {
        PageRole.COVER,
        PageRole.PAIN_POINT,
        PageRole.PRODUCT_OVERVIEW,
        PageRole.CORE_FEATURES,
        PageRole.CTA,
    },
    "preferred_image_strategy": ImageStrategy.UI_MOCK,
    "default_enrich_level": "llm",  # 可以补市场背景
    "writing_style": (
        "产品介绍文案风格：\n"
        "- 每页围绕用户价值，不是功能堆砌\n"
        "- 功能必须对应场景和收益\n"
        "- 用'你是否遇到过...'、'想象一下...'引导\n"
        "- 避免'我们的产品...'开头，改为'用户可以...'\n"
        "- 正确示范：'3步完成数据分析，原来需要2小时的工作现在只需5分钟'\n"
        "- 错误示范：'本产品采用先进的AI算法，具有强大的数据处理能力'"
    ),
    "audience_hint": "潜在客户/投资人",
    "anti_patterns": [
        "先进的",
        "强大的",
        "业界领先",
        "一站式解决方案",
        "全方位覆盖",
    ],
}

# =========================================================================
# 策略注册表 & 辅助函数
# =========================================================================

STRATEGIES: dict[DeckType, dict] = {
    DeckType.BUSINESS_REPORT: BUSINESS_REPORT_STRATEGY,
    DeckType.COURSE_LECTURE: COURSE_LECTURE_STRATEGY,
    DeckType.PRODUCT_INTRO: PRODUCT_INTRO_STRATEGY,
}


def get_strategy(deck_type: DeckType) -> dict:
    """Get the generation strategy for a given DeckType."""
    return STRATEGIES[deck_type]


def get_default_slides(deck_type: DeckType) -> list[SlideTask]:
    """Get the default slide skeleton for a DeckType."""
    return STRATEGIES[deck_type]["default_slides"]


def get_writing_style(deck_type: DeckType) -> str:
    """Get writing style guidance for ContentCreator."""
    return STRATEGIES[deck_type]["writing_style"]


def get_anti_patterns(deck_type: DeckType) -> list[str]:
    """Get anti-patterns (forbidden writing patterns) for a DeckType."""
    return STRATEGIES[deck_type]["anti_patterns"]


# Mapping from DocumentAnalysis fields to DeckType
_DOC_TYPE_MAP: dict[str, DeckType] = {
    "tech_share": DeckType.COURSE_LECTURE,
    "teaching": DeckType.COURSE_LECTURE,
    "academic": DeckType.COURSE_LECTURE,
    "business_report": DeckType.BUSINESS_REPORT,
    "summary": DeckType.BUSINESS_REPORT,
    "marketing": DeckType.PRODUCT_INTRO,
    "product_intro": DeckType.PRODUCT_INTRO,
    "product": DeckType.PRODUCT_INTRO,
}

_TONE_MAP: dict[str, DeckType] = {
    "technical": DeckType.COURSE_LECTURE,
    "creative": DeckType.PRODUCT_INTRO,
}


def detect_deck_type(doc_type: str, tone: str) -> DeckType:
    """Auto-detect DeckType from DocumentAnalysis fields.

    Mapping:
    - tech_share, teaching, academic -> COURSE_LECTURE
    - business_report, summary -> BUSINESS_REPORT
    - marketing, product, product_intro -> PRODUCT_INTRO
    - default -> BUSINESS_REPORT
    """
    # doc_type takes priority
    if doc_type in _DOC_TYPE_MAP:
        return _DOC_TYPE_MAP[doc_type]

    # fall back to tone hint
    if tone in _TONE_MAP:
        return _TONE_MAP[tone]

    # safe default
    return DeckType.BUSINESS_REPORT
