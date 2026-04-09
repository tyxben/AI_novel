# AI 长篇小说写作模块 - 叙事节奏控制 v2 技术设计文档

## 1. 架构概览

### 1.1 系统定位

叙事节奏控制 v2 是对现有小说生成系统的 **非侵入式增强层**，通过三个并行机制在现有 Agent 流程的关键决策点注入约束和引导信号，无需重写核心 Agent 逻辑。

### 1.2 三机制协同架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    NovelDirector（大纲生成阶段）                   │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐     │
│  │ 生成卷大纲     │  │ 生成系统失效   │  │ 分配策略 Tier  │     │
│  │ + 里程碑       │  │ 排程           │  │ 范围           │     │
│  └───────┬────────┘  └───────┬────────┘  └───────┬────────┘     │
│          │                   │                   │              │
│          └───────────────────┴───────────────────┘              │
│                              │                                  │
│                    写入 novel.json                              │
└──────────────────────────────┼───────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│              每章生成循环（PlotPlanner → Writer → Reviewers）      │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ ContinuityService.generate_brief()                          ││
│  │   - 读取当前卷进度（已完成/逾期里程碑）                       ││
│  │   - 读取系统失效排程（本章是否失效）                          ││
│  │   - 聚合为 continuity_brief                                 ││
│  └────────────────────┬────────────────────────────────────────┘│
│                       │                                         │
│  ┌────────────────────▼────────────────────────────────────────┐│
│  │ PlotPlanner.decompose_chapter()                             ││
│  │   - 读取 volume_progress → 判断是否需要加速里程碑            ││
│  │   - 读取系统状态 → 规划"系统失效"场景                        ││
│  │   - 抽取策略元素 → 注入 required_strategy_elements          ││
│  │   - 生成场景计划（scenes）                                   ││
│  └────────────────────┬────────────────────────────────────────┘│
│                       │                                         │
│  ┌────────────────────▼────────────────────────────────────────┐│
│  │ Writer.write_scene()                                        ││
│  │   - 读取系统状态 → 禁用功能列表注入 prompt                   ││
│  │   - 读取策略元素 → 要求文本体现策略                          ││
│  │   - 生成场景正文                                             ││
│  └────────────────────┬────────────────────────────────────────┘│
│                       │                                         │
│  ┌────────────────────▼────────────────────────────────────────┐│
│  │ ConsistencyChecker / QualityReviewer                        ││
│  │   - 检查系统失效期间是否误用禁用功能                          ││
│  │   - 检查策略元素是否在文本中体现                             ││
│  └────────────────────┬────────────────────────────────────────┘│
│                       │                                         │
│  ┌────────────────────▼────────────────────────────────────────┐│
│  │ 章节生成后勾子                                               ││
│  │   - MilestoneTracker.check_completion()（检查里程碑）        ││
│  │   - SystemStateTracker.advance_state()（推进系统状态）       ││
│  │   - StrategyUsageTracker.record_usage()（记录策略使用）      ││
│  └─────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│                    卷边界勾子（VolumeSettlement）                  │
│  - 生成卷完成度报告（里程碑完成率 / 继承 / 放弃）                  │
│  - 继承未完成里程碑到下一卷                                        │
│  - 生成策略使用统计报告                                            │
└──────────────────────────────────────────────────────────────────┘
```

### 1.3 数据流向

```
大纲阶段（一次性）:
  novel.json 写入:
    - volumes[].narrative_milestones
    - system_failure_schedule
    - volumes[].strategy_tier_range
    - enable_strategy_ladder

每章生成:
  读取:
    novel.json → ContinuityService → continuity_brief
    novel.json → PlotPlanner → chapter_brief (with strategy elements)
    novel.json → Writer → system prompt (with constraints)
  写入:
    chapter.full_text → MilestoneTracker → novel.json (milestone.status)
    chapter.full_text → StrategyUsageTracker → memory.db (strategy_usage table)
    current_chapter → SystemStateTracker → novel.json (system_state.current_mode)

卷边界:
  读取:
    novel.json → VolumeSettlement → 汇总卷完成度
  写入:
    novel.json → volumes[].settlement_report
    novel.json → 下一卷继承里程碑
```

---

## 2. 数据模型设计

### 2.1 Pydantic 模型定义

新增文件：`src/novel/models/narrative_control.py`

```python
"""叙事控制相关数据模型"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class NarrativeMilestone(BaseModel):
    """卷级叙事里程碑"""
    milestone_id: str = Field(..., description="唯一标识，如 vol1_m1")
    description: str = Field(..., min_length=5, max_length=200, description="中文描述")
    target_chapter_range: tuple[int, int] = Field(..., description="目标完成章节范围 [min, max]")
    verification_type: Literal["auto_keyword", "llm_review"] = Field(
        default="auto_keyword",
        description="验证方式"
    )
    verification_criteria: list[str] | str = Field(
        ...,
        description="关键词列表（auto_keyword）或 LLM prompt（llm_review）"
    )
    priority: Literal["critical", "high", "normal"] = Field(
        default="normal",
        description="优先级"
    )
    status: Literal["pending", "completed", "overdue", "abandoned"] = Field(
        default="pending",
        description="完成状态"
    )
    completed_at_chapter: int | None = Field(
        default=None,
        description="实际完成章节号"
    )
    inherited_from_volume: int | None = Field(
        default=None,
        description="若继承自上一卷，记录来源卷号"
    )


class SystemFailureEvent(BaseModel):
    """系统失效事件排程"""
    chapter: int = Field(..., ge=1, description="失效发生章节")
    mode: Literal["full", "degraded", "offline", "wrong_data", "limited"] = Field(
        ...,
        description="失效模式"
    )
    reason: str = Field(..., min_length=5, max_length=100, description="失效原因（中文）")
    duration_chapters: int = Field(default=1, ge=1, le=10, description="持续章节数")
    affected_capabilities: list[str] = Field(
        default_factory=list,
        description="受影响功能列表（如 ['地图扫描', '战术模拟']）"
    )
    recovery_trigger: str | None = Field(
        default=None,
        description="恢复条件（如 '到达安全区' / 'N 章后自动恢复'）"
    )
    recovery_chapter: int | None = Field(
        default=None,
        description="预期恢复章节号"
    )


class SystemCapabilityState(BaseModel):
    """系统能力当前状态（story-world state，非代码状态）"""
    current_mode: Literal["full", "degraded", "offline", "wrong_data", "limited"] = Field(
        default="full",
        description="当前模式"
    )
    degradation_reason: str | None = Field(
        default=None,
        description="降级/失效原因"
    )
    affected_capabilities: list[str] = Field(
        default_factory=list,
        description="当前受影响功能"
    )
    recovery_trigger: str | None = None
    recovery_chapter: int | None = None
    failure_history: list[dict] = Field(
        default_factory=list,
        description="历史失效记录 [{chapter, mode, reason}, ...]"
    )


class StrategyElement(BaseModel):
    """策略元素（从注册表抽取）"""
    element_id: str = Field(..., description="唯一标识，如 36ji_07")
    name: str = Field(..., min_length=2, max_length=50, description="中文名")
    tier: int = Field(..., ge=1, le=7, description="所属 Tier")
    description: str = Field(..., max_length=300, description="简述")
    usage_constraints: list[str] = Field(
        default_factory=list,
        description="使用约束（如 '需要至少 2 个势力存在'）"
    )
    keywords: list[str] = Field(..., min_items=2, description="关键词列表（用于验证使用）")


class StrategyTier(BaseModel):
    """策略复杂度分级"""
    tier_number: int = Field(..., ge=1, le=7)
    tier_name: str = Field(..., description="中文名，如 '个体战术'")
    description: str = Field(..., max_length=500)
    example_elements: list[str] = Field(..., min_items=10, description="示例策略元素列表")
    applicable_scales: str = Field(..., description="适用叙事尺度，如 '单人/小场景'")


class VolumeProgressReport(BaseModel):
    """卷完成度报告"""
    volume_number: int = Field(..., ge=1)
    milestones_total: int = Field(..., ge=0)
    milestones_completed: int = Field(..., ge=0)
    milestones_overdue: int = Field(..., ge=0)
    milestones_abandoned: int = Field(..., ge=0)
    milestones_inherited_to_next: int = Field(..., ge=0)
    completion_rate: float = Field(..., ge=0.0, le=1.0, description="完成率")
    settlement_timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="收束时间戳"
    )
```

### 2.2 novel.json Schema 扩展

在现有 `novel.json` 基础上增加字段（不破坏现有结构）：

```json
{
  "novel_id": "novel_xxx",
  "title": "...",
  "genre": "...",
  "theme": "...",
  "enable_strategy_ladder": true,  // 新增：是否启用策略阶梯
  "outline": {
    "volumes": [
      {
        "volume_number": 1,
        "title": "...",
        "start_chapter": 1,
        "end_chapter": 30,
        "theme": "...",
        "climax": "...",
        "end_hook": "...",
        "narrative_milestones": [  // 新增：里程碑列表
          {
            "milestone_id": "vol1_m1",
            "description": "主角激活系统并招募第一批追随者",
            "target_chapter_range": [3, 8],
            "verification_type": "auto_keyword",
            "verification_criteria": ["激活系统", "招募", "追随者"],
            "priority": "critical",
            "status": "completed",
            "completed_at_chapter": 5
          },
          {
            "milestone_id": "vol1_m2",
            "description": "攻占第一个宗门据点（青云山门）",
            "target_chapter_range": [15, 20],
            "verification_type": "auto_keyword",
            "verification_criteria": ["青云山门", "攻占", "接管"],
            "priority": "critical",
            "status": "overdue",
            "completed_at_chapter": null
          }
        ],
        "strategy_tier_range": [1, 3],  // 新增：本卷策略 Tier 范围
        "settlement_report": {  // 新增：卷完成度报告（卷结束后生成）
          "milestones_total": 5,
          "milestones_completed": 3,
          "milestones_overdue": 1,
          "milestones_abandoned": 0,
          "milestones_inherited_to_next": 1,
          "completion_rate": 0.6,
          "settlement_timestamp": "2025-03-20T10:30:00Z"
        }
      }
    ]
  },
  "system_failure_schedule": [  // 新增：系统失效排程
    {
      "chapter": 8,
      "mode": "degraded",
      "reason": "进入矿脉深层，灵力紊乱",
      "duration_chapters": 2,
      "affected_capabilities": ["地图扫描", "灵力分析"],
      "recovery_trigger": "离开矿脉深层",
      "recovery_chapter": 10
    },
    {
      "chapter": 23,
      "mode": "wrong_data",
      "reason": "敌方使用干扰阵法",
      "duration_chapters": 1,
      "affected_capabilities": ["敌军数量扫描"],
      "recovery_trigger": "破解阵法",
      "recovery_chapter": 24
    }
  ],
  "system_state": {  // 新增：系统当前状态（动态更新）
    "current_mode": "full",
    "degradation_reason": null,
    "affected_capabilities": [],
    "recovery_trigger": null,
    "recovery_chapter": null,
    "failure_history": [
      {"chapter": 8, "mode": "degraded", "reason": "进入矿脉深层，灵力紊乱"},
      {"chapter": 23, "mode": "wrong_data", "reason": "敌方使用干扰阵法"}
    ]
  }
}
```

### 2.3 SQLite Schema 扩展

新增表：`src/novel/storage/structured_db.py` 扩展

```sql
-- 策略使用记录表
CREATE TABLE IF NOT EXISTS strategy_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_number INTEGER NOT NULL,
    element_id TEXT NOT NULL,  -- 策略元素 ID
    element_name TEXT NOT NULL,
    tier INTEGER NOT NULL,
    matched_keywords TEXT,  -- JSON 数组，匹配到的关键词
    usage_timestamp TEXT NOT NULL,
    FOREIGN KEY (chapter_number) REFERENCES chapters(chapter_number)
);

-- 里程碑完成历史表（可选，novel.json 已存储，此表用于快速查询）
CREATE TABLE IF NOT EXISTS milestone_completion (
    milestone_id TEXT PRIMARY KEY,
    volume_number INTEGER NOT NULL,
    description TEXT NOT NULL,
    target_min INTEGER NOT NULL,
    target_max INTEGER NOT NULL,
    status TEXT NOT NULL,  -- pending/completed/overdue/abandoned
    completed_at_chapter INTEGER,
    verification_method TEXT,  -- keyword/llm
    completion_timestamp TEXT
);
```

### 2.4 模板文件（YAML 数据文件）

#### 2.4.1 `src/novel/templates/strategy_tiers.yaml`

```yaml
# 策略复杂度分级定义
tiers:
  - tier_number: 1
    tier_name: "个体战术"
    description: "单人或小规模行动，依靠个人能力和简单技巧"
    applicable_scales: "单人、小队、单场景"
    example_elements:
      - "肉搏格斗"
      - "隐蔽潜行"
      - "诱骗对话"
      - "观察破绽"
      - "快速逃跑"
      - "单点突破"
      - "伪装身份"
      - "利用地形躲藏"
      - "拖延时间"
      - "示弱诱敌"
      # ... 至少 20 个

  - tier_number: 2
    tier_name: "小队战术"
    description: "小队协同作战，简单战术配合和陷阱设计"
    applicable_scales: "小队（3-20 人）、单一战场"
    example_elements:
      - "声东击西"  # 36计第6计
      - "埋伏圈"
      - "诱敌深入"
      - "火力掩护"
      - "分进合击"
      - "佯攻"
      - "设置陷阱"
      - "前后夹击"
      - "疲敌之计"
      - "打草惊蛇"  # 36计第13计
      # ... 至少 20 个

  - tier_number: 3
    tier_name: "战役战术"
    description: "中等规模战役，涉及情报、后勤、内部分化"
    applicable_scales: "百人级、多战场、区域控制"
    example_elements:
      - "情报渗透"
      - "粮道封锁"
      - "内部分化"
      - "多兵种配合"
      - "地形优势利用"
      - "夜袭"
      - "围点打援"
      - "疲兵之计"
      - "反客为主"  # 36计第30计
      - "欲擒故纵"  # 36计第16计
      # ... 至少 30 个

  - tier_number: 4
    tier_name: "制度建设"
    description: "建立管理体系、法律制度、权力分配机制"
    applicable_scales: "城市、领地、小国"
    example_elements:
      - "分封制"
      - "监察体系"
      - "税收制度"
      - "军功爵位"
      - "法律体系"
      - "户籍管理"
      - "科举选拔"
      - "土地改革"
      - "货币统一"
      - "文字统一"
      # ... 至少 30 个

  - tier_number: 5
    tier_name: "战略战役"
    description: "大规模战争，持久战、心理战、经济战"
    applicable_scales: "国家级、跨区域、数万人规模"
    example_elements:
      - "持久战"
      - "心理战"
      - "舆论战"
      - "经济封锁"
      - "战略防御"
      - "战略反攻"
      - "全面动员"
      - "后方稳定"
      - "敌后游击"
      - "瓦解敌军士气"
      # ... 至少 30 个

  - tier_number: 6
    tier_name: "高级谋略"
    description: "36计级全局谋略、联盟外交、大战略布局"
    applicable_scales: "多国、跨文明、全局博弈"
    example_elements:
      - "远交近攻"  # 36计第23计
      - "合纵连横"
      - "反间计"  # 36计第33计
      - "美人计"  # 36计第31计
      - "围魏救赵"  # 36计第2计
      - "釜底抽薪"  # 36计第19计
      - "借刀杀人"  # 36计第3计
      - "假道伐虢"
      - "笑里藏刀"  # 36计第10计
      - "联盟外交"
      # ... 包含剩余 36 计 + 其他谋略，至少 40 个

  - tier_number: 7
    tier_name: "帝王之术"
    description: "制度设计、文化整合、历史叙事权、文明级统治"
    applicable_scales: "帝国、跨界、文明整合"
    example_elements:
      - "制度设计（三省六部、内阁制）"
      - "文化同化"
      - "宗教统战"
      - "历史叙事权（修史、正统论）"
      - "移民政策"
      - "异族整合"
      - "科技垄断"
      - "教育体系（官学、私学）"
      - "礼法并重"
      - "天命论构建"
      # ... 至少 30 个
```

#### 2.4.2 `src/novel/templates/strategy_registry.yaml`

```yaml
# 策略元素注册表（示例结构，实际由 LLM 生成 + 人工审核）
elements:
  # 36 计完整列表
  - element_id: "36ji_01"
    name: "瞒天过海"
    tier: 2
    description: "佯装常态掩盖真实意图，让对方放松警惕"
    usage_constraints:
      - "需要对方有可利用的认知惯性"
    keywords: ["瞒天过海", "佯装", "掩盖真实意图", "放松警惕"]

  - element_id: "36ji_02"
    name: "围魏救赵"
    tier: 6
    description: "避实击虚,攻击敌方要害迫使其回援"
    usage_constraints:
      - "需要至少 2 个敌对势力存在"
      - "需要主角有能力威胁敌方后方"
    keywords: ["围魏救赵", "避实击虚", "攻其必救", "回援"]

  # ... 剩余 34 计

  # 兵法术语
  - element_id: "sunzi_01"
    name: "知己知彼百战不殆"
    tier: 3
    description: "通过情报收集了解敌我双方实力"
    usage_constraints: []
    keywords: ["知己知彼", "情报", "侦察", "了解敌情"]

  - element_id: "strategy_01"
    name: "持久战"
    tier: 5
    description: "以时间换空间,消耗敌方资源和士气"
    usage_constraints:
      - "主角需有稳定后方支持"
    keywords: ["持久战", "消耗", "拖延", "时间换空间"]

  # 帝王心术
  - element_id: "emperor_01"
    name: "分封制"
    tier: 4
    description: "分封土地和权力给功臣，建立层级管理"
    usage_constraints:
      - "主角需控制至少 3 个区域"
      - "需有至少 3 名可信任的部将"
    keywords: ["分封", "封地", "藩王", "诸侯"]

  - element_id: "emperor_02"
    name: "推恩令"
    tier: 6
    description: "要求诸侯分封领地给所有子嗣，削弱藩王力量"
    usage_constraints:
      - "已实施分封制"
      - "藩王势力过大需削藩"
    keywords: ["推恩令", "削藩", "分封子嗣", "削弱诸侯"]

  # ... 共 150+ 个元素
```

---

## 3. 机制 A：卷进度预算详细设计

### 3.1 里程碑生成

**时机**：`NovelDirector.generate_outline()` 完成卷大纲生成后

**实现**：新增方法 `NovelDirector._generate_milestones_for_volume()`

```python
def _generate_milestones_for_volume(
    self,
    volume: VolumeOutline,
    total_chapters: int,
    genre: str,
    theme: str
) -> list[NarrativeMilestone]:
    """为单个卷生成里程碑"""
    prompt_system = """
你是一位专业的叙事结构分析师。你的任务是将卷大纲的主题/高潮/结尾钩子拆解为 3-5 个具体的、可验证的叙事里程碑。

要求：
1. 每个里程碑必须是具体事件（如"主角攻占 X 地点""角色 Y 加入队伍""系统失效导致战术失败"），而非抽象概念
2. 里程碑必须可通过关键词或 LLM 判定是否完成
3. 里程碑的目标章节范围应覆盖卷的不同阶段（开头/发展/高潮/收束）
4. 至少 1 个里程碑为 priority: critical（卷末必须完成）
5. 里程碑之间有依赖关系时，target_chapter_range 不重叠

返回 JSON 数组：
[
  {
    "milestone_id": "vol{volume_number}_m1",
    "description": "里程碑中文描述",
    "target_chapter_range": [min_chapter, max_chapter],
    "verification_type": "auto_keyword",
    "verification_criteria": ["关键词1", "关键词2"],
    "priority": "critical"
  }
]
"""

    prompt_user = f"""
## 卷信息
- 卷号: {volume.volume_number}
- 标题: {volume.title}
- 章节范围: {volume.start_chapter} - {volume.end_chapter}（共 {volume.end_chapter - volume.start_chapter + 1} 章）
- 主题: {volume.theme}
- 高潮: {volume.climax}
- 结尾钩子: {volume.end_hook}

## 小说背景
- 题材: {genre}
- 总主题: {theme}

请生成 3-5 个里程碑，确保覆盖本卷的关键叙事节点。
"""

    response = self.llm.chat(
        messages=[
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": prompt_user}
        ],
        temperature=0.7,
        json_mode=True,
        max_tokens=2048
    )

    milestones_data = extract_json_from_llm(response.content)
    if not milestones_data or not isinstance(milestones_data, list):
        log.warning(f"Failed to generate milestones for volume {volume.volume_number}")
        return []

    milestones = []
    for data in milestones_data:
        try:
            milestone = NarrativeMilestone(**data)
            milestones.append(milestone)
        except Exception as e:
            log.error(f"Invalid milestone data: {e}")
            continue

    return milestones
```

**调用点**：`NovelDirector.generate_outline()` 末尾

```python
# 在 generate_outline() 返回前
for volume in outline.volumes:
    milestones = self._generate_milestones_for_volume(
        volume=volume,
        total_chapters=total_chapters,
        genre=genre,
        theme=theme
    )
    volume.narrative_milestones = milestones  # 扩展 VolumeOutline 模型
```

### 3.2 里程碑追踪服务

**新增模块**：`src/novel/services/milestone_tracker.py`

```python
"""里程碑追踪服务"""
from __future__ import annotations

import logging
import re
from typing import Any

from src.novel.models.narrative_control import NarrativeMilestone

log = logging.getLogger("novel.services.milestone")


class MilestoneTracker:
    """负责里程碑完成度检查和状态更新"""

    def __init__(self, novel_data: dict):
        """
        Args:
            novel_data: novel.json 的 dict 表示
        """
        self.novel_data = novel_data
        self.volumes = novel_data.get("outline", {}).get("volumes", [])

    def get_milestones_for_chapter(self, chapter_num: int) -> list[NarrativeMilestone]:
        """获取当前章节应完成的待办里程碑"""
        current_volume = self._get_volume_by_chapter(chapter_num)
        if not current_volume:
            return []

        milestones = current_volume.get("narrative_milestones", [])
        pending = []
        for m_data in milestones:
            milestone = NarrativeMilestone(**m_data)
            if milestone.status == "pending":
                min_ch, max_ch = milestone.target_chapter_range
                if min_ch <= chapter_num <= max_ch:
                    pending.append(milestone)
        return pending

    def check_milestone_completion(
        self,
        chapter_num: int,
        chapter_text: str,
        chapter_summary: str | None = None,
        llm_client: Any | None = None
    ) -> list[str]:
        """检查本章是否完成了某个待办里程碑
        
        Returns:
            完成的里程碑 ID 列表
        """
        pending = self.get_milestones_for_chapter(chapter_num)
        completed_ids = []

        for milestone in pending:
            is_completed = False

            if milestone.verification_type == "auto_keyword":
                # 关键词检查
                keywords = milestone.verification_criteria
                if isinstance(keywords, str):
                    keywords = [keywords]
                matched = all(
                    self._contains_keyword(chapter_text, kw) for kw in keywords
                )
                is_completed = matched

            elif milestone.verification_type == "llm_review":
                # LLM 判定
                if llm_client is None:
                    log.warning(f"Milestone {milestone.milestone_id} needs LLM but no client provided")
                    continue

                prompt = f"""
判断以下章节是否完成了里程碑：

里程碑描述：{milestone.description}

章节摘要：
{chapter_summary or chapter_text[:1000]}

返回 JSON：{{"completed": true/false, "reason": "简要理由"}}
"""
                response = llm_client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    json_mode=True,
                    max_tokens=512
                )
                result = extract_json_from_llm(response.content)
                is_completed = result.get("completed", False) if result else False

            if is_completed:
                self._mark_milestone_completed(milestone.milestone_id, chapter_num)
                completed_ids.append(milestone.milestone_id)
                log.info(f"Milestone {milestone.milestone_id} completed at chapter {chapter_num}")

        return completed_ids

    def mark_overdue_milestones(self, current_chapter: int) -> list[str]:
        """标记已逾期的里程碑
        
        Returns:
            逾期的里程碑 ID 列表
        """
        overdue_ids = []
        for volume in self.volumes:
            milestones = volume.get("narrative_milestones", [])
            for m_data in milestones:
                milestone = NarrativeMilestone(**m_data)
                if milestone.status == "pending":
                    _, max_ch = milestone.target_chapter_range
                    if current_chapter > max_ch:
                        self._mark_milestone_overdue(milestone.milestone_id)
                        overdue_ids.append(milestone.milestone_id)
        return overdue_ids

    def _mark_milestone_completed(self, milestone_id: str, chapter_num: int):
        """更新里程碑状态为已完成"""
        for volume in self.volumes:
            for m in volume.get("narrative_milestones", []):
                if m.get("milestone_id") == milestone_id:
                    m["status"] = "completed"
                    m["completed_at_chapter"] = chapter_num
                    return

    def _mark_milestone_overdue(self, milestone_id: str):
        """更新里程碑状态为逾期"""
        for volume in self.volumes:
            for m in volume.get("narrative_milestones", []):
                if m.get("milestone_id") == milestone_id:
                    m["status"] = "overdue"
                    return

    def _contains_keyword(self, text: str, keyword: str) -> bool:
        """检查文本是否包含关键词（忽略标点和空格）"""
        # 移除标点
        clean_text = re.sub(r'[^\w\s]', '', text)
        clean_keyword = re.sub(r'[^\w\s]', '', keyword)
        return clean_keyword in clean_text

    def _get_volume_by_chapter(self, chapter_num: int) -> dict | None:
        """获取包含指定章节的卷"""
        for vol in self.volumes:
            if vol["start_chapter"] <= chapter_num <= vol["end_chapter"]:
                return vol
        return None
```

**集成点**：`src/novel/pipeline.py` 的章节生成后勾子

```python
# 在 NovelPipeline.generate_chapters() 中，每章生成后
from src.novel.services.milestone_tracker import MilestoneTracker

tracker = MilestoneTracker(novel_data=self.novel.model_dump())
completed = tracker.check_milestone_completion(
    chapter_num=chapter.chapter_number,
    chapter_text=chapter.full_text,
    chapter_summary=None,  # 可选：传入摘要节省 token
    llm_client=self.llm
)
if completed:
    log.info(f"Completed milestones: {completed}")

# 检查逾期
overdue = tracker.mark_overdue_milestones(current_chapter=chapter.chapter_number)
if overdue:
    log.warning(f"Overdue milestones: {overdue}")
```

### 3.3 进度注入到 continuity_brief

**修改点**：`src/novel/services/continuity_service.py`

```python
# 在 ContinuityService.generate_brief() 中增加

def generate_brief(
    self,
    chapter_number: int,
    chapters: list[dict] | None = None,
    chapter_brief: dict | None = None,
    story_arcs: list[dict] | None = None,
    characters: list | None = None,
    protagonist_names: list[str] | None = None,
    novel_data: dict | None = None,  # 新增参数：novel.json 数据
) -> dict[str, Any]:
    """..."""
    brief: dict[str, Any] = {
        "chapter_number": chapter_number,
        "must_continue": [],
        "open_threads": [],
        "character_states": [],
        "active_arcs": [],
        "forbidden_breaks": [],
        "recommended_payoffs": [],
        "volume_progress": {},  # 新增字段
    }

    # ... 现有逻辑 ...

    # 新增：提取卷进度
    if novel_data:
        self._extract_volume_progress(brief, chapter_number, novel_data)

    return brief


def _extract_volume_progress(
    self,
    brief: dict,
    chapter_number: int,
    novel_data: dict
):
    """提取卷进度信息"""
    volumes = novel_data.get("outline", {}).get("volumes", [])
    current_volume = None
    for vol in volumes:
        if vol["start_chapter"] <= chapter_number <= vol["end_chapter"]:
            current_volume = vol
            break

    if not current_volume:
        return

    start = current_volume["start_chapter"]
    end = current_volume["end_chapter"]
    consumed = chapter_number - start
    remaining = end - chapter_number + 1

    milestones = current_volume.get("narrative_milestones", [])
    completed = [m for m in milestones if m.get("status") == "completed"]
    pending = [m for m in milestones if m.get("status") == "pending"]
    overdue = [m for m in milestones if m.get("status") == "overdue"]

    # 计算进度健康度
    total_milestones = len(milestones)
    if total_milestones == 0:
        progress_health = "on_track"
    else:
        completion_rate = len(completed) / total_milestones
        if overdue:
            progress_health = "critical"
        elif completion_rate < 0.5 and consumed / (end - start + 1) > 0.5:
            progress_health = "behind_schedule"
        else:
            progress_health = "on_track"

    brief["volume_progress"] = {
        "current_volume": {
            "number": current_volume["volume_number"],
            "title": current_volume["title"]
        },
        "chapters_consumed": consumed,
        "chapters_remaining": remaining,
        "milestones_completed": [m["description"] for m in completed],
        "milestones_pending": [m["description"] for m in pending],
        "milestones_overdue": [m["description"] for m in overdue],
        "progress_health": progress_health,
    }
```

**格式化为 prompt**：在 `ContinuityService.format_for_prompt()` 中增加

```python
def format_for_prompt(self, brief: dict[str, Any]) -> str:
    """..."""
    sections: list[str] = []

    # ... 现有 sections ...

    # 新增：卷进度
    vp = brief.get("volume_progress", {})
    if vp:
        sections.append("### 当前卷进度摘要")
        vol = vp.get("current_volume", {})
        sections.append(
            f"- 卷：第 {vol.get('number', '?')} 卷「{vol.get('title', '?')}」"
            f"（已用 {vp.get('chapters_consumed', 0)}/{vp.get('chapters_consumed', 0) + vp.get('chapters_remaining', 0)} 章，"
            f"剩余 {vp.get('chapters_remaining', 0)} 章）"
        )

        completed = vp.get("milestones_completed", [])
        if completed:
            sections.append(f"- 已完成里程碑：{'、'.join(completed)}")

        pending = vp.get("milestones_pending", [])
        if pending:
            sections.append(f"- 待完成里程碑：{', '.join(pending[:3])}{'...' if len(pending) > 3 else ''}")

        overdue = vp.get("milestones_overdue", [])
        if overdue:
            sections.append(f"- **逾期里程碑**：{', '.join(overdue)}")

        health = vp.get("progress_health", "")
        health_text = {
            "on_track": "进度正常",
            "behind_schedule": "进度落后，需加速推进",
            "critical": "有逾期里程碑，本章必须推进"
        }.get(health, "")
        if health_text:
            sections.append(f"- 进度状态：{health_text}")

        sections.append("")

    return "\n".join(sections)
```

### 3.4 PlotPlanner 响应进度信号

**修改点**：`src/novel/agents/plot_planner.py`

在 `decompose_chapter()` 方法中，读取 `continuity_brief.volume_progress` 并注入约束 prompt

```python
def decompose_chapter(
    self,
    outline_chapter: ChapterOutline,
    volume_outline: VolumeOutline,
    characters: list[CharacterProfile],
    continuity_brief: dict | None = None,  # 传入 brief
    # ...
) -> dict:
    """..."""

    # 提取卷进度约束
    volume_progress_constraint = ""
    if continuity_brief:
        vp = continuity_brief.get("volume_progress", {})
        health = vp.get("progress_health", "on_track")

        if health == "on_track":
            volume_progress_constraint = "当前卷进度正常，本章可正常推进主线或适度展开支线。"
        elif health == "behind_schedule":
            pending = vp.get("milestones_pending", [])
            volume_progress_constraint = (
                f"**卷进度落后警告**：以下里程碑待完成：{', '.join(pending[:3])}。"
                f"本章必须优先推进以上里程碑，避免引入与里程碑无关的新支线。"
            )
        elif health == "critical":
            overdue = vp.get("milestones_overdue", [])
            volume_progress_constraint = (
                f"**严重警告**：以下里程碑已逾期：{', '.join(overdue)}。"
                f"本章必须有至少 1 个场景直接推进其中一个逾期里程碑，不允许与里程碑无关的场景。"
            )

    # 注入到 user prompt
    user_prompt = _DECOMPOSE_USER.format(
        # ... 现有字段 ...
        volume_progress_constraint=volume_progress_constraint,  # 新增
    )

    # ... 调用 LLM ...
```

在 `_DECOMPOSE_USER` prompt 模板中增加占位符：

```python
_DECOMPOSE_USER = """\
## 章节大纲
...

{volume_progress_constraint}

## 卷上下文
...
"""
```

### 3.5 卷边界收束

**修改点**：`src/novel/services/volume_settlement.py`

扩展 `get_settlement_brief()` 增加里程碑检查：

```python
def get_settlement_brief(self, chapter_num: int, novel_data: dict) -> dict:
    """..."""
    # ... 现有债务收束逻辑 ...

    # 新增：里程碑完成度检查
    current_volume = self.get_current_volume(chapter_num)
    if current_volume:
        milestones = current_volume.get("narrative_milestones", [])
        critical_incomplete = [
            m for m in milestones
            if m.get("priority") == "critical" and m.get("status") != "completed"
        ]

        if critical_incomplete:
            lines.append("\n【卷级里程碑警告】")
            for m in critical_incomplete:
                lines.append(f"  - 未完成关键里程碑：{m.get('description', '?')}")
            lines.append("请在本卷结束前确保以上里程碑得到解决或明确标记为继承。")

    # ...
```

新增 `settle_volume()` 方法：

```python
def settle_volume(self, volume_number: int, novel_data: dict) -> dict:
    """生成卷完成度报告并处理未完成里程碑
    
    Returns:
        VolumeProgressReport dict
    """
    volumes = novel_data.get("outline", {}).get("volumes", [])
    current_volume = next((v for v in volumes if v["volume_number"] == volume_number), None)
    if not current_volume:
        return {}

    milestones = current_volume.get("narrative_milestones", [])
    completed = [m for m in milestones if m.get("status") == "completed"]
    overdue = [m for m in milestones if m.get("status") == "overdue"]
    pending = [m for m in milestones if m.get("status") == "pending"]

    # 处理未完成的 critical 里程碑
    critical_incomplete = [
        m for m in (pending + overdue) if m.get("priority") == "critical"
    ]

    inherited_count = 0
    abandoned_count = 0

    for m in critical_incomplete:
        # 简单策略：逾期且 critical → 继承到下一卷
        if volume_number < len(volumes):
            next_volume = volumes[volume_number]  # volume_number 从 1 开始，索引从 0 开始
            if "narrative_milestones" not in next_volume:
                next_volume["narrative_milestones"] = []
            m["inherited_from_volume"] = volume_number
            m["status"] = "pending"  # 重置为 pending
            next_volume["narrative_milestones"].insert(0, m)  # 插入到下一卷开头
            inherited_count += 1
            log.info(f"Inherited milestone {m['milestone_id']} to volume {volume_number + 1}")
        else:
            # 最后一卷，标记为 abandoned
            m["status"] = "abandoned"
            abandoned_count += 1
            log.warning(f"Abandoned milestone {m['milestone_id']} at last volume")

    report = {
        "volume_number": volume_number,
        "milestones_total": len(milestones),
        "milestones_completed": len(completed),
        "milestones_overdue": len(overdue),
        "milestones_abandoned": abandoned_count,
        "milestones_inherited_to_next": inherited_count,
        "completion_rate": len(completed) / max(len(milestones), 1),
        "settlement_timestamp": datetime.now().isoformat(),
    }

    current_volume["settlement_report"] = report
    return report
```

**调用点**：`NovelPipeline.generate_chapters()` 在检测到卷结束时

```python
# 在生成某一卷的最后一章后
if chapter.chapter_number == current_volume["end_chapter"]:
    settlement = VolumeSettlement(db=self.memory.db, outline=self.novel.outline)
    report = settlement.settle_volume(
        volume_number=current_volume["volume_number"],
        novel_data=self.novel.model_dump()
    )
    log.info(f"Volume {current_volume['volume_number']} settlement: {report}")
```

---

## 4. 机制 B：系统能力状态机详细设计

### 4.1 失效排程生成

**时机**：`NovelDirector.generate_outline()` 完成后

**新增方法**：`NovelDirector._schedule_system_failures()`

```python
def _schedule_system_failures(
    self,
    total_chapters: int,
    volumes: list[VolumeOutline]
) -> list[SystemFailureEvent]:
    """生成系统失效排程
    
    策略：
    - 密度：每 20 章 1 次（可配置）
    - 优先安排在卷高潮前 2-5 章
    - 避让：第 1-5 章、卷末倒数 2 章、连续 3 章
    """
    import random

    failure_density = 20  # 每 N 章 1 次失效
    target_count = max(1, total_chapters // failure_density)

    # 收集高潮章节范围（假设 climax 在卷的 70%-90% 位置）
    climax_zones = []
    for vol in volumes:
        span = vol.end_chapter - vol.start_chapter + 1
        climax_start = vol.start_chapter + int(span * 0.7)
        climax_end = vol.start_chapter + int(span * 0.9)
        climax_zones.append((climax_start, climax_end))

    # 禁用章节：第 1-5 章、各卷末倒数 2 章
    forbidden_chapters = set(range(1, 6))
    for vol in volumes:
        forbidden_chapters.add(vol.end_chapter)
        forbidden_chapters.add(vol.end_chapter - 1)

    # 候选章节（优先高潮前 2-5 章）
    preferred_chapters = []
    for start, end in climax_zones:
        for offset in range(2, 6):  # 高潮前 2-5 章
            ch = start - offset
            if ch > 0 and ch not in forbidden_chapters:
                preferred_chapters.append(ch)

    # 其他可用章节
    other_chapters = [
        ch for ch in range(6, total_chapters + 1)
        if ch not in forbidden_chapters and ch not in preferred_chapters
    ]

    # 抽取失效章节（60% 从 preferred，40% 从 other）
    pref_count = int(target_count * 0.6)
    other_count = target_count - pref_count

    selected = (
        random.sample(preferred_chapters, min(pref_count, len(preferred_chapters))) +
        random.sample(other_chapters, min(other_count, len(other_chapters)))
    )
    selected = sorted(selected)

    # 避免连续 3 章都失效
    filtered = []
    for ch in selected:
        if not any(abs(ch - prev) < 3 for prev in filtered[-2:]):
            filtered.append(ch)

    # 生成失效事件
    mode_distribution = ["degraded"] * 6 + ["wrong_data"] * 2 + ["offline"] * 1 + ["limited"] * 1
    events = []

    for ch in filtered[:target_count]:
        mode = random.choice(mode_distribution)
        duration = random.randint(1, 3) if mode != "offline" else 1  # offline 不能持续太久

        event = SystemFailureEvent(
            chapter=ch,
            mode=mode,
            reason=self._generate_failure_reason(ch, mode, volumes),
            duration_chapters=duration,
            affected_capabilities=self._select_affected_capabilities(mode),
            recovery_trigger=self._generate_recovery_trigger(mode, duration),
            recovery_chapter=ch + duration
        )
        events.append(event)

    return events


def _generate_failure_reason(self, chapter: int, mode: str, volumes: list) -> str:
    """生成失效原因（简单随机，可改为 LLM 生成）"""
    reasons = {
        "degraded": ["进入灵力紊乱区域", "系统能量不足", "遭遇强干扰源"],
        "offline": ["进入上古禁地", "系统核心受损", "遭遇未知屏蔽"],
        "wrong_data": ["敌方使用干扰阵法", "环境数据污染", "系统误判"],
        "limited": ["系统冷却中", "能量储备不足", "功能过载保护"],
    }
    import random
    return random.choice(reasons.get(mode, ["未知原因"]))


def _select_affected_capabilities(self, mode: str) -> list[str]:
    """根据失效模式选择受影响功能"""
    all_capabilities = ["地图扫描", "战术模拟", "灵力分析", "资源识别", "敌军数量扫描"]
    import random

    if mode == "offline":
        return all_capabilities  # 全失效
    elif mode == "degraded":
        return random.sample(all_capabilities, k=random.randint(2, 3))
    elif mode == "wrong_data":
        return random.sample(all_capabilities, k=1)
    elif mode == "limited":
        return random.sample(all_capabilities, k=random.randint(1, 2))
    return []


def _generate_recovery_trigger(self, mode: str, duration: int) -> str:
    """生成恢复条件"""
    if mode == "offline":
        return "离开禁地"
    elif mode == "degraded":
        return f"{duration} 章后自动恢复"
    elif mode == "wrong_data":
        return "破解干扰源"
    else:
        return f"{duration} 章后冷却完成"
```

**调用点**：`NovelDirector.generate_outline()` 返回前

```python
# 在 generate_outline() 末尾
failure_schedule = self._schedule_system_failures(
    total_chapters=total_chapters,
    volumes=outline.volumes
)

# 存储到 novel.json
state["novel_data"]["system_failure_schedule"] = [
    event.model_dump() for event in failure_schedule
]
state["novel_data"]["system_state"] = SystemCapabilityState().model_dump()
```

### 4.2 系统状态追踪服务

**新增模块**：`src/novel/services/system_state_tracker.py`

```python
"""系统能力状态追踪服务"""
from __future__ import annotations

import logging
from typing import Any

from src.novel.models.narrative_control import SystemCapabilityState, SystemFailureEvent

log = logging.getLogger("novel.services.system_state")


class SystemStateTracker:
    """追踪系统能力状态，管理失效/恢复"""

    def __init__(self, novel_data: dict):
        self.novel_data = novel_data
        self.schedule = [
            SystemFailureEvent(**e) for e in novel_data.get("system_failure_schedule", [])
        ]
        self.current_state = SystemCapabilityState(**novel_data.get("system_state", {}))

    def get_state_for_chapter(self, chapter_num: int) -> SystemCapabilityState:
        """获取指定章节的系统状态"""
        # 检查是否有新失效事件触发
        for event in self.schedule:
            if event.chapter == chapter_num:
                self._activate_failure(event)

        # 检查是否应该恢复
        if self.current_state.recovery_chapter and chapter_num >= self.current_state.recovery_chapter:
            self._recover_system(chapter_num)

        return self.current_state

    def advance_state(self, current_chapter: int):
        """推进系统状态（每章生成后调用）"""
        self.get_state_for_chapter(current_chapter)
        # 更新 novel.json
        self.novel_data["system_state"] = self.current_state.model_dump()

    def _activate_failure(self, event: SystemFailureEvent):
        """激活失效事件"""
        log.warning(f"System failure activated: {event.mode} at chapter {event.chapter}")
        self.current_state.current_mode = event.mode
        self.current_state.degradation_reason = event.reason
        self.current_state.affected_capabilities = event.affected_capabilities
        self.current_state.recovery_trigger = event.recovery_trigger
        self.current_state.recovery_chapter = event.recovery_chapter

        # 记录历史
        self.current_state.failure_history.append({
            "chapter": event.chapter,
            "mode": event.mode,
            "reason": event.reason,
        })

    def _recover_system(self, chapter_num: int):
        """系统恢复"""
        log.info(f"System recovered at chapter {chapter_num}")
        self.current_state.current_mode = "full"
        self.current_state.degradation_reason = None
        self.current_state.affected_capabilities = []
        self.current_state.recovery_trigger = None
        self.current_state.recovery_chapter = None
```

**集成点**：`NovelPipeline.generate_chapters()` 每章生成前后

```python
from src.novel.services.system_state_tracker import SystemStateTracker

# 章节生成前
tracker = SystemStateTracker(novel_data=self.novel.model_dump())
system_state = tracker.get_state_for_chapter(chapter_number)

# 将 system_state 传递给 PlotPlanner 和 Writer
# ...

# 章节生成后
tracker.advance_state(current_chapter=chapter_number)
```

### 4.3 PlotPlanner 读取失效排程

**修改点**：`src/novel/agents/plot_planner.py`

```python
def decompose_chapter(
    self,
    outline_chapter: ChapterOutline,
    volume_outline: VolumeOutline,
    characters: list[CharacterProfile],
    continuity_brief: dict | None = None,
    system_state: SystemCapabilityState | None = None,  # 新增参数
    # ...
) -> dict:
    """..."""

    # 构建系统状态约束 prompt
    system_constraint = ""
    if system_state and system_state.current_mode != "full":
        mode_names = {
            "degraded": "降级",
            "offline": "离线",
            "wrong_data": "数据错误",
            "limited": "功能受限"
        }
        mode_name = mode_names.get(system_state.current_mode, "异常")

        system_constraint = f"""
## 系统状态约束
本章系统状态：**{mode_name}**
原因：{system_state.degradation_reason}
受影响能力：{', '.join(system_state.affected_capabilities)}
恢复条件：{system_state.recovery_trigger}

**重要**：本章主角无法使用以上系统功能。场景必须体现主角在无系统辅助情况下如何应对挑战。
至少 1 个场景必须明确展现系统失效带来的困境或意外。
"""

    # 注入到 prompt
    user_prompt = _DECOMPOSE_USER.format(
        # ...
        system_constraint=system_constraint,
    )
```

### 4.4 Writer 禁止使用失效功能

**修改点**：`src/novel/agents/writer.py`

在 Writer 的系统 prompt 中动态注入系统状态：

```python
def write_scene(
    self,
    scene_plan: dict,
    chapter_context: dict,
    system_state: SystemCapabilityState | None = None,  # 新增
    # ...
) -> str:
    """..."""

    # 构建系统状态约束
    system_constraint = ""
    if system_state and system_state.current_mode != "full":
        forbidden_caps = system_state.affected_capabilities
        system_constraint = f"""
**本章系统状态异常**：
- 状态：{system_state.current_mode}（{system_state.degradation_reason}）
- 禁用功能：{', '.join(forbidden_caps)}
- 恢复条件：{system_state.recovery_trigger}

**写作约束**：
- 不允许主角使用以上禁用功能
- 不允许出现"林辰打开系统界面""系统扫描显示"等描述（针对禁用功能）
- 主角必须依靠自身判断、经验、或其他角色辅助来应对挑战
"""

    system_prompt = f"""
{_BASE_SYSTEM_PROMPT}

{system_constraint}

{scene_plan.get('additional_constraints', '')}
"""

    # 调用 LLM
    response = self.llm.chat(
        messages=[{"role": "system", "content": system_prompt}, ...],
        ...
    )
```

### 4.5 ConsistencyChecker 验证系统约束

**修改点**：`src/novel/agents/consistency_checker.py`

在 `check_chapter()` 方法中增加系统约束检查：

```python
def check_chapter(
    self,
    chapter: Chapter,
    system_state: SystemCapabilityState | None = None,  # 新增
    # ...
) -> dict:
    """..."""

    violations = []

    # 新增：系统约束检查
    if system_state and system_state.current_mode != "full":
        forbidden_caps = system_state.affected_capabilities
        for cap in forbidden_caps:
            # 简单关键词检查（可改为更复杂的规则）
            if cap in chapter.full_text:
                # 检查上下文是否是"系统失效"相关描述（允许）
                # 这里简化为：如果出现"系统失效""无法使用"等词，则不算违规
                context_safe = any(
                    keyword in chapter.full_text for keyword in ["系统失效", "无法使用", "失灵", "离线"]
                )
                if not context_safe:
                    violations.append({
                        "type": "system_constraint_violation",
                        "description": f"系统失效期间不应使用功能：{cap}",
                        "severity": "high",
                    })

    # 返回检查结果
    return {
        "violations": violations,
        # ...
    }
```

---

## 5. 机制 C：策略复杂度阶梯详细设计

### 5.1 策略注册表生成

**时机**：项目初始化或首次运行时

**新增脚本**：`src/novel/scripts/generate_strategy_registry.py`（可手动运行或自动运行）

```python
"""生成策略注册表（LLM 辅助 + 人工审核）"""
import yaml
from src.llm.llm_client import create_llm_client


def generate_strategy_registry(output_path: str):
    """生成策略元素注册表"""
    llm = create_llm_client()

    # 生成 36 计
    prompt_36ji = """
生成 36 计的完整列表，每计包含：
- element_id: 如 "36ji_01"
- name: 计名
- tier: 所属复杂度等级（1-7，根据使用场景复杂度判断）
- description: 简要描述
- usage_constraints: 使用约束（如"需要对方有可利用的认知惯性"）
- keywords: 关键词列表（至少 3 个）

返回 JSON 数组。
"""

    response = llm.chat(
        messages=[{"role": "user", "content": prompt_36ji}],
        temperature=0.5,
        json_mode=True,
        max_tokens=8192
    )

    elements_36ji = extract_json_from_llm(response.content)

    # 生成兵法术语（类似流程）
    # ...

    # 生成帝王心术（类似流程）
    # ...

    # 合并所有元素
    all_elements = elements_36ji + elements_sunzi + elements_emperor

    # 写入 YAML
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump({"elements": all_elements}, f, allow_unicode=True)

    print(f"Generated {len(all_elements)} strategy elements to {output_path}")


if __name__ == "__main__":
    generate_strategy_registry("src/novel/templates/strategy_registry.yaml")
```

### 5.2 Tier 范围映射

**修改点**：`src/novel/agents/novel_director.py`

在 `generate_outline()` 中为每个卷分配 Tier 范围：

```python
def generate_outline(...) -> Outline:
    """..."""
    # ... 生成卷大纲 ...

    # 为每个卷分配策略 Tier 范围
    total_volumes = len(outline.volumes)
    for i, vol in enumerate(outline.volumes):
        # 前 1/3: Tier 1-3, 中 1/3: Tier 3-5, 后 1/3: Tier 5-7
        progress = (i + 1) / total_volumes
        if progress <= 0.33:
            tier_range = [1, 3]
        elif progress <= 0.67:
            tier_range = [3, 5]
        else:
            tier_range = [5, 7]

        vol.strategy_tier_range = tier_range

    return outline
```

### 5.3 章节级策略元素分配

**新增模块**：`src/novel/services/strategy_selector.py`

```python
"""策略元素选择服务"""
from __future__ import annotations

import logging
import random
import yaml
from pathlib import Path
from typing import Any

from src.novel.models.narrative_control import StrategyElement

log = logging.getLogger("novel.services.strategy")


class StrategySelector:
    """策略元素选择器"""

    def __init__(self, registry_path: str | None = None):
        if registry_path is None:
            registry_path = Path(__file__).parent.parent / "templates" / "strategy_registry.yaml"

        with open(registry_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self.elements = [StrategyElement(**e) for e in data.get("elements", [])]
        self.recent_usage = []  # 记录近期使用的元素 ID

    def select_elements_for_chapter(
        self,
        tier_range: tuple[int, int],
        recent_chapters_usage: list[str],  # 近 N 章使用的元素 ID
        current_context: dict | None = None,  # 当前章节上下文（可选，用于过滤 usage_constraints）
        count: int = 2
    ) -> list[StrategyElement]:
        """为当前章节选择策略元素
        
        Args:
            tier_range: 当前卷的 Tier 范围 [min, max]
            recent_chapters_usage: 近 5 章已使用的元素 ID
            current_context: 当前章节上下文（可选，用于检查 usage_constraints）
            count: 选择元素数量
        
        Returns:
            选中的策略元素列表
        """
        min_tier, max_tier = tier_range

        # 筛选符合 Tier 的元素
        candidates = [e for e in self.elements if min_tier <= e.tier <= max_tier]

        # 排除近期使用的元素
        candidates = [e for e in candidates if e.element_id not in recent_chapters_usage]

        # 过滤不满足 usage_constraints 的元素（简化实现，可改为 LLM 判定）
        # 这里仅做示例：假设 context 有 "controlled_regions" 字段
        if current_context:
            filtered = []
            for elem in candidates:
                constraints = elem.usage_constraints
                # 简单示例：检查是否包含"需要至少 X 个区域"
                if any("至少 3 个区域" in c for c in constraints):
                    if current_context.get("controlled_regions", 0) < 3:
                        continue
                filtered.append(elem)
            candidates = filtered

        if not candidates:
            log.warning(f"No available strategy elements for tier {tier_range}")
            return []

        # 加权随机选择（中位 Tier 概率更高）
        mid_tier = (min_tier + max_tier) / 2
        weights = [1 / (abs(e.tier - mid_tier) + 1) for e in candidates]

        selected = random.choices(candidates, weights=weights, k=min(count, len(candidates)))
        return selected
```

**集成点**：`PlotPlanner.decompose_chapter()`

```python
from src.novel.services.strategy_selector import StrategySelector

def decompose_chapter(
    self,
    outline_chapter: ChapterOutline,
    volume_outline: VolumeOutline,
    characters: list[CharacterProfile],
    continuity_brief: dict | None = None,
    system_state: SystemCapabilityState | None = None,
    enable_strategy_ladder: bool = True,  # 新增：是否启用策略阶梯
    recent_strategy_usage: list[str] = [],  # 新增：近期策略使用记录
    # ...
) -> dict:
    """..."""

    # 选择策略元素
    required_strategy_elements = []
    if enable_strategy_ladder:
        selector = StrategySelector()
        tier_range = volume_outline.strategy_tier_range or [1, 3]
        selected = selector.select_elements_for_chapter(
            tier_range=tier_range,
            recent_chapters_usage=recent_strategy_usage[-5:],  # 近 5 章
            count=2
        )
        required_strategy_elements = [e.model_dump() for e in selected]

    # 注入到 prompt
    strategy_section = ""
    if required_strategy_elements:
        strategy_section = "## 策略要求\n本章必须体现以下策略手段：\n"
        for elem in required_strategy_elements:
            strategy_section += f"- **{elem['name']}**（Tier {elem['tier']}）：{elem['description']}\n"
        strategy_section += "\n场景设计时，至少 1 个场景必须明确使用以上策略，并在 summary 中体现。\n"

    user_prompt = _DECOMPOSE_USER.format(
        # ...
        strategy_section=strategy_section,
    )

    # 返回结果时附带策略元素
    result = {
        "scenes": scenes,
        "required_strategy_elements": required_strategy_elements,
    }
    return result
```

### 5.4 Writer 强制使用策略元素

**修改点**：`src/novel/agents/writer.py`

```python
def write_scene(
    self,
    scene_plan: dict,
    chapter_context: dict,
    required_strategy_elements: list[dict] | None = None,  # 新增
    # ...
) -> str:
    """..."""

    strategy_constraint = ""
    if required_strategy_elements:
        strategy_constraint = "**本章策略要求**：\n本章必须体现以下策略手段：\n"
        for elem in required_strategy_elements:
            strategy_constraint += f"- **{elem['name']}**：{elem['description']}\n"
            strategy_constraint += f"  - 关键要素：{', '.join(elem['keywords'])}\n"
        strategy_constraint += """
**写作要求**：
- 至少在 1 个场景中明确使用以上策略
- 不要生硬说教（如"林辰想起了三十六计中的 X 计"），而是自然融入情节
- 策略的使用必须有因果：为什么用这个策略？结果如何？
"""

    system_prompt = f"""
{_BASE_SYSTEM_PROMPT}

{strategy_constraint}

{scene_plan.get('additional_constraints', '')}
"""

    # ...
```

### 5.5 策略使用追踪

**新增模块**：`src/novel/services/strategy_usage_tracker.py`

```python
"""策略使用追踪服务"""
from __future__ import annotations

import logging
import json

log = logging.getLogger("novel.services.strategy_usage")


class StrategyUsageTracker:
    """追踪策略元素使用情况"""

    def __init__(self, db: Any):
        self.db = db

    def record_usage(
        self,
        chapter_number: int,
        chapter_text: str,
        required_elements: list[dict]
    ):
        """记录本章策略使用情况（基于关键词匹配）"""
        for elem in required_elements:
            keywords = elem.get("keywords", [])
            matched = [kw for kw in keywords if kw in chapter_text]

            if matched:
                with self.db.transaction() as cur:
                    cur.execute(
                        """
                        INSERT INTO strategy_usage
                        (chapter_number, element_id, element_name, tier, matched_keywords, usage_timestamp)
                        VALUES (?, ?, ?, ?, ?, datetime('now'))
                        """,
                        (
                            chapter_number,
                            elem["element_id"],
                            elem["name"],
                            elem["tier"],
                            json.dumps(matched, ensure_ascii=False)
                        )
                    )
                log.info(f"Recorded strategy usage: {elem['name']} in chapter {chapter_number}")

    def get_recent_usage(self, chapter_number: int, window: int = 5) -> list[str]:
        """获取近 N 章使用的策略元素 ID"""
        with self.db.transaction() as cur:
            cur.execute(
                """
                SELECT DISTINCT element_id FROM strategy_usage
                WHERE chapter_number >= ? AND chapter_number < ?
                """,
                (chapter_number - window, chapter_number)
            )
            rows = cur.fetchall()
        return [row[0] for row in rows]

    def generate_report(self, total_chapters: int) -> dict:
        """生成策略使用统计报告"""
        with self.db.transaction() as cur:
            # Tier 分布
            cur.execute(
                """
                SELECT tier, COUNT(*) FROM strategy_usage GROUP BY tier ORDER BY tier
                """
            )
            tier_distribution = {row[0]: row[1] for row in cur.fetchall()}

            # 36 计覆盖率
            cur.execute(
                """
                SELECT COUNT(DISTINCT element_id) FROM strategy_usage WHERE element_id LIKE '36ji_%'
                """
            )
            jiqi_coverage = cur.fetchone()[0]

            # 重复率
            cur.execute(
                """
                SELECT element_id, COUNT(*) as cnt FROM strategy_usage GROUP BY element_id HAVING cnt > 1
                """
            )
            repeated = cur.fetchall()
            total_usage = sum(tier_distribution.values())
            repeat_count = sum(row[1] - 1 for row in repeated)
            repeat_rate = repeat_count / max(total_usage, 1)

        return {
            "tier_distribution": tier_distribution,
            "jiqi_coverage": jiqi_coverage,
            "jiqi_coverage_rate": jiqi_coverage / 36,
            "repeat_rate": repeat_rate,
            "total_usage": total_usage,
        }
```

**集成点**：`NovelPipeline.generate_chapters()` 每章生成后

```python
from src.novel.services.strategy_usage_tracker import StrategyUsageTracker

tracker = StrategyUsageTracker(db=self.memory.db)
tracker.record_usage(
    chapter_number=chapter.chapter_number,
    chapter_text=chapter.full_text,
    required_elements=chapter_result.get("required_strategy_elements", [])
)

recent_usage = tracker.get_recent_usage(chapter_number=chapter.chapter_number)
# 传递给下一章的 PlotPlanner
```

### 5.6 主题门控

**修改点**：`src/novel/agents/novel_director.py`

在 `analyze_input()` 中增加主题检测：

```python
def analyze_input(
    self,
    genre: str,
    theme: str,
    target_words: int,
    custom_ideas: str | None = None,
) -> dict[str, Any]:
    """..."""
    # ... 现有逻辑 ...

    # 新增：检测是否启用策略阶梯
    enable_strategy_ladder = self._detect_strategy_theme(genre, theme)

    return {
        # ...
        "enable_strategy_ladder": enable_strategy_ladder,
    }


def _detect_strategy_theme(self, genre: str, theme: str) -> bool:
    """检测主题是否需要策略阶梯"""
    strategy_keywords = [
        "战争", "兵法", "谋略", "统一", "争霸", "帝王", "策略", "36计",
        "征战", "战术", "军事", "权谋", "分封", "持久战", "心理战"
    ]

    strategy_genres = ["权谋", "战争", "历史", "玄幻"]  # 玄幻中战争向的也算

    # 关键词匹配
    if any(kw in theme for kw in strategy_keywords):
        return True

    # 题材匹配
    if genre in strategy_genres:
        return True

    # LLM 判定（可选，更精准但消耗 token）
    # ...

    return False
```

---

## 6. 交互合力：三机制协同案例

### 6.1 高潮章节的理想状态

**案例**：第 1 卷高潮（ch24-25）攻占青云山门

**三机制协同**：

1. **卷进度（机制 A）**：
   - 里程碑"攻占青云山门"目标章节 [20, 25]，当前 ch24，接近目标上限
   - `volume_progress.progress_health = "behind_schedule"`（因为其他里程碑也未完成）
   - ContinuityService 注入提示："本章必须推进里程碑：攻占青云山门"
   - PlotPlanner 收到约束，强制生成"攻山门"相关场景

2. **系统失效（机制 B）**：
   - 系统失效排程：ch23 系统进入 `mode: degraded`，地图扫描范围缩小 70%
   - PlotPlanner 生成场景时，明确注入"系统扫描失效，林辰无法提前获知山门内部守军布局"
   - Writer 写作时，禁止使用"系统扫描显示敌军 50 人在 X 位置"，主角必须靠侦察兵 + 推测

3. **策略升级（机制 C）**：
   - 当前卷 Tier 范围 [1, 3]，高潮章节强制使用 Tier 3 策略
   - StrategySelector 抽取："粮道封锁""内部分化""地形优势利用"
   - PlotPlanner 生成场景：第 1 场景 = 切断山门粮道，第 2 场景 = 策反内部守卫，第 3 场景 = 利用山体地形伏击援军
   - Writer 写作时，自然融入"林辰派人绕道后山截断水源，守军三日后内乱"等情节

**效果**：
- 主角在系统受限情况下，必须依靠高级战术（Tier 3）完成关键里程碑，张力最大化
- 读者感受："这章真难！系统失灵了还能赢，主角智商在线！"

### 6.2 日常章节的降级

**案例**：第 2 卷中段（ch35）日常治理章节

**三机制表现**：

1. **卷进度**：
   - 第 2 卷里程碑"建立分封制度"已在 ch32 完成
   - 当前无逾期里程碑，`progress_health = "on_track"`
   - ContinuityService 提示："当前卷进度正常，本章可正常推进主线或适度展开支线"
   - PlotPlanner 有自由度，可生成日常场景

2. **系统失效**：
   - 系统正常（`mode: full`）
   - PlotPlanner 和 Writer 无系统约束

3. **策略升级**：
   - 当前卷 Tier 范围 [2, 4]，但日常章节可回到 Tier 2（允许降级放松节奏）
   - StrategySelector 抽取："小队巡逻""处理民事纠纷"
   - 场景：林辰巡视新占领的村镇，处理两家农户土地纠纷

**效果**：
- 高潮后适度放松，但策略 Tier 仍高于第 1 卷（第 1 卷日常用 Tier 1，第 2 卷日常用 Tier 2）
- 整体升级趋势保持，但有节奏起伏

---

## 7. 边界情况处理

### 7.1 短篇小说（< 50 章）

**问题**：里程碑密度过高，系统失效过于频繁

**策略**：
- 里程碑数量：每卷 2-3 个（而非 3-5 个）
- 系统失效密度：每 30 章 1 次（而非 20 章）
- 策略 Tier 加速升级：第 1 卷 [1, 3]，第 2 卷直接 [3, 5]（跳过中间）

**实现**：在 `NovelDirector.generate_outline()` 中检测 `total_chapters`，调整参数

### 7.2 LangGraph 缺失

**问题**：三机制依赖状态管理，LangGraph 缺失时如何降级

**策略**：
- 所有状态存储在 `novel.json`（文件系统），不依赖 LangGraph 的内存状态
- 每章生成前/后手动调用追踪服务（MilestoneTracker / SystemStateTracker / StrategyUsageTracker）
- 顺序执行模式下，Agent 调用顺序保持不变（PlotPlanner → Writer → Reviewers），只是无并行

**实现**：已在现有 `src/novel/agents/graph.py` 的 fallback 逻辑中支持

### 7.3 非战争题材（言情/日常）

**问题**：策略阶梯污染故事内容（言情小说不需要 36 计）

**策略**：
- 主题门控自动禁用策略阶梯（`enable_strategy_ladder = False`）
- 卷进度和系统失效仍然启用（这两个机制适用所有题材）
- 若言情小说有"系统"设定（如系统流言情），系统失效机制仍适用

**实现**：`_detect_strategy_theme()` 关键词检测 + 题材白名单

### 7.4 迁移现有项目

**问题**：`novel_12e1c974` 已生成 27 章，如何平滑升级

**策略**：
- 运行迁移脚本 `python main.py novel migrate-narrative-arc workspace/novels/novel_12e1c974`
- 迁移步骤：
  1. 为现有卷生成里程碑（LLM 根据 `theme/climax` 生成）
  2. 对已生成的 27 章做回顾检查（批量调用 `MilestoneTracker.check_milestone_completion()`），标记已完成里程碑
  3. 为剩余 173 章重新排程系统失效（避开已生成的 27 章）
  4. 为剩余章节分配策略 Tier 范围
  5. 保存到 `novel.json`
- 迁移后继续生成 ch28+，三机制立即生效

**实现**：新增 CLI 命令 `novel migrate-narrative-arc`

---

## 8. 性能与 Token 优化

### 8.1 Token 消耗分析

**大纲阶段（一次性）**：
- 里程碑生成：每卷 1 次 LLM 调用，约 2k tokens/卷，6 卷 = 12k tokens
- 系统失效排程：纯算法，0 tokens
- 策略注册表生成：一次性，约 10k tokens（可缓存复用）
- **合计**：约 22k tokens（项目级一次性成本）

**每章增量**：
- 里程碑检查：80% 关键词匹配（0 tokens），20% LLM 判定（500 tokens）→ 平均 100 tokens/章
- 系统状态推进：纯算法，0 tokens
- 策略元素抽取：纯随机 + 过滤，0 tokens
- `continuity_brief` 增量：约 500 字（约 250 tokens）
- PlotPlanner prompt 增量：约 300 字（约 150 tokens）
- Writer prompt 增量：约 300 字（约 150 tokens）
- **合计**：约 650 tokens/章

**200 章总增量**：22k（大纲）+ 650 × 200（章节）= 22k + 130k = **152k tokens**

**对比基线**：当前系统 200 章约消耗 3M tokens，增量 152k = **+5% token 消耗**（可接受）

### 8.2 优化策略

1. **里程碑验证**：优先关键词匹配，复杂语义才用 LLM
2. **策略元素库**：预生成并缓存，不重复调用 LLM
3. **系统失效排程**：纯算法，无 LLM 成本
4. **continuity_brief 长度控制**：<500 字，避免过度占用 context

---

## 9. 测试策略

### 9.1 单元测试

**测试文件**：`tests/novel/services/test_milestone_tracker.py`

```python
def test_keyword_milestone_completion():
    """测试关键词匹配里程碑检查"""
    novel_data = {
        "outline": {
            "volumes": [
                {
                    "volume_number": 1,
                    "start_chapter": 1,
                    "end_chapter": 30,
                    "narrative_milestones": [
                        {
                            "milestone_id": "vol1_m1",
                            "description": "攻占青云山门",
                            "target_chapter_range": [15, 20],
                            "verification_type": "auto_keyword",
                            "verification_criteria": ["青云山门", "攻占"],
                            "priority": "critical",
                            "status": "pending",
                        }
                    ]
                }
            ]
        }
    }

    tracker = MilestoneTracker(novel_data)

    # 章节文本包含关键词
    chapter_text = "林辰率军攻占青云山门，守军全军覆没。"
    completed = tracker.check_milestone_completion(
        chapter_num=18,
        chapter_text=chapter_text,
        chapter_summary=None,
        llm_client=None
    )

    assert "vol1_m1" in completed
    assert novel_data["outline"]["volumes"][0]["narrative_milestones"][0]["status"] == "completed"


def test_overdue_milestone():
    """测试逾期里程碑标记"""
    # ...
```

### 9.2 集成测试

**测试文件**：`tests/novel/integration/test_narrative_arc.py`

```python
def test_full_pipeline_with_narrative_arc():
    """测试完整流程（大纲 → 生成 10 章 → 验证三机制）"""
    # 创建项目
    pipeline = NovelPipeline(workspace="workspace_test")
    result = pipeline.create_novel(
        genre="玄幻",
        theme="穿越者统一修仙界，需要战争、兵法、36计",
        target_words=50000  # 约 20 章
    )

    # 验证大纲阶段
    novel_data = result["novel_data"]
    assert "system_failure_schedule" in novel_data
    assert len(novel_data["system_failure_schedule"]) >= 1  # 至少 1 次失效
    volumes = novel_data["outline"]["volumes"]
    assert all("narrative_milestones" in vol for vol in volumes)
    assert all("strategy_tier_range" in vol for vol in volumes)

    # 生成前 10 章
    pipeline.generate_chapters(
        project_path=result["project_path"],
        start_chapter=1,
        end_chapter=10
    )

    # 验证里程碑完成
    tracker = MilestoneTracker(novel_data)
    pending = tracker.get_milestones_for_chapter(11)
    # 至少部分里程碑已完成（不能全是 pending）
    completed_count = sum(
        1 for vol in volumes for m in vol["narrative_milestones"]
        if m["status"] == "completed"
    )
    assert completed_count > 0

    # 验证系统失效执行
    # ...

    # 验证策略使用
    # ...
```

---

## 10. 文件清单

### 10.1 新增文件

```
src/novel/
├── models/
│   └── narrative_control.py  # 新增：NarrativeMilestone, SystemFailureEvent, etc.
├── services/
│   ├── milestone_tracker.py  # 新增：里程碑追踪
│   ├── system_state_tracker.py  # 新增：系统状态追踪
│   ├── strategy_selector.py  # 新增：策略元素选择
│   └── strategy_usage_tracker.py  # 新增：策略使用追踪
├── templates/
│   ├── strategy_tiers.yaml  # 新增：策略分级定义
│   └── strategy_registry.yaml  # 新增：策略元素注册表
└── scripts/
    └── generate_strategy_registry.py  # 新增：注册表生成脚本

tests/novel/
├── services/
│   ├── test_milestone_tracker.py  # 新增
│   ├── test_system_state_tracker.py  # 新增
│   ├── test_strategy_selector.py  # 新增
│   └── test_strategy_usage_tracker.py  # 新增
└── integration/
    └── test_narrative_arc.py  # 新增：端到端集成测试
```

### 10.2 修改文件

```
src/novel/
├── agents/
│   ├── novel_director.py  # 修改：增加里程碑生成、失效排程、Tier 分配、主题门控
│   ├── plot_planner.py  # 修改：读取卷进度/系统状态/策略元素，注入约束 prompt
│   ├── writer.py  # 修改：注入系统状态约束、策略元素约束
│   └── consistency_checker.py  # 修改：增加系统约束检查
├── services/
│   ├── continuity_service.py  # 修改：增加 volume_progress 提取和格式化
│   └── volume_settlement.py  # 修改：增加里程碑完成度检查、settle_volume() 方法
├── models/
│   └── novel.py  # 修改：VolumeOutline 增加 narrative_milestones / strategy_tier_range 字段
├── storage/
│   └── structured_db.py  # 修改：增加 strategy_usage 表
└── pipeline.py  # 修改：集成三机制的追踪服务调用

main.py  # 修改：增加 novel migrate-narrative-arc 命令
```

---

## 11. 实施优先级

**P0（MVP 必须）**：
- 机制 A：R-A-1, R-A-2, R-A-3, R-A-4（卷进度核心功能）
- 机制 B：R-B-1, R-B-2, R-B-3, R-B-4（系统失效核心功能）
- 机制 C：R-C-1, R-C-2, R-C-3, R-C-4, R-C-5（策略阶梯核心功能）
- 集成：R-D-1, R-D-2（协同触发、降级兼容）

**P1（重要）**：
- 机制 A：R-A-5（卷边界收束）
- 机制 B：R-B-5（自动状态转移）
- 机制 C：R-C-6（主题门控）
- 集成：R-D-3, R-D-4（省 token、迁移路径）

**P2（优化）**：
- 机制 C：R-C-7（策略统计报告）

---

## 12. 后续扩展方向

- **动态里程碑调整**：根据读者反馈或剧情变化，LLM 自动调整未完成里程碑的描述/目标章节
- **多主角策略阶梯**：不同主角不同策略风格（如主角 A 擅长战术，主角 B 擅长外交）
- **策略效果评估**：LLM 判定策略使用是否真的导致预期结果（如"声东击西"是否真的骗到敌人）
- **跨卷弧线追踪**：长期伏笔 / 角色成长弧跨多卷自动追踪
- **读者反馈闭环**：根据读者评论自动调整里程碑 / 策略复杂度
