"""健康度指标数据模型"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthMetrics(BaseModel):
    """小说项目健康度指标"""

    # 伏笔覆盖
    foreshadowing_total: int = Field(0, ge=0, description="总伏笔数")
    foreshadowing_collected: int = Field(0, ge=0, description="已回收伏笔数")
    foreshadowing_abandoned: int = Field(0, ge=0, description="已废弃伏笔数")
    foreshadowing_forgotten: int = Field(0, ge=0, description="即将遗忘伏笔数")
    foreshadowing_collection_rate: float = Field(
        0.0, ge=0.0, le=1.0, description="回收率"
    )

    # 里程碑进度
    milestone_total: int = Field(0, ge=0)
    milestone_completed: int = Field(0, ge=0)
    milestone_overdue: int = Field(0, ge=0)
    milestone_completion_rate: float = Field(0.0, ge=0.0, le=1.0)

    # 角色覆盖
    character_total: int = Field(0, ge=0)
    character_active: int = Field(0, ge=0, description="有出场记录的角色数")
    character_coverage: float = Field(
        0.0, ge=0.0, le=1.0, description="角色出场覆盖率"
    )

    # 实体一致性
    entity_total: int = Field(0, ge=0)
    entity_conflict_count: int = Field(0, ge=0, description="名称冲突数")
    entity_consistency_score: float = Field(
        1.0, ge=0.0, le=1.0, description="实体一致性得分 (1-冲突率)"
    )

    # 叙事债务
    debt_total: int = Field(0, ge=0)
    debt_overdue: int = Field(0, ge=0)
    debt_health: str = Field("healthy", description="healthy/warning/critical")

    # 综合得分
    overall_health_score: float = Field(
        0.0, ge=0.0, le=100.0, description="综合健康度得分 (0-100)"
    )
