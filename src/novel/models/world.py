"""世界观设定数据模型"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PowerLevel(BaseModel):
    """单个力量等级"""

    rank: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, description="如'筑基期'")
    description: str = Field(..., min_length=1)
    typical_abilities: list[str] = Field(default_factory=list)


class PowerSystem(BaseModel):
    """力量体系"""

    name: str = Field(..., min_length=1, description="如'修炼境界'")
    levels: list[PowerLevel] = Field(..., min_length=1)


class WorldSetting(BaseModel):
    """世界观设定"""

    era: str = Field(..., min_length=1, description="古代/现代/未来/架空")
    location: str = Field(..., min_length=1, description="地域背景")

    # 力量体系（玄幻/武侠特有）
    power_system: PowerSystem | None = None

    # 专有名词表
    terms: dict[str, str] = Field(
        default_factory=dict, description="专有名词 -> 定义"
    )

    # 关键设定
    rules: list[str] = Field(default_factory=list, description="世界规则")

    # 版本控制（智能编辑系统）
    effective_from_chapter: int | None = Field(
        None, description="生效起始章节（None=从头生效）"
    )
    deprecated_at_chapter: int | None = Field(
        None, description="废弃章节（None=一直生效）"
    )
    version: int = Field(1, ge=1, description="版本号")
