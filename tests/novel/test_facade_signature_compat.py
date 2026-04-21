"""Phase 5 L3 — facade → Agent 签名漂移防护。

背景
----
``NovelToolFacade`` 通过 ``_make_project_architect`` / ``_make_volume_director``
/ ``_make_chapter_planner`` 工厂方法创建 Agent 并调用其 ``propose_*`` /
``regenerate_section``。现有单测常用 ``MagicMock`` class-level patch 替换整
个 Agent，因此**真实 Agent 的方法签名发生漂移（kwarg 改名/删除）时
facade 单测不会失败**，只有真机跑才会炸。

Phase 5 第 5 节方案：每条 facade → Agent 路径加一个 ``inspect.signature``
断言，确认 facade 调用点传的 kwarg 都在 Agent 真实签名里。

覆盖路径
--------
PHASE5.md 5.2 表列的 10 条路径全部纳入：

| facade 方法 | Agent 方法 |
|-------------|-----------|
| propose_project_setup | ProjectArchitect.propose_project_setup |
| propose_synopsis | ProjectArchitect.propose_synopsis |
| propose_main_outline | ProjectArchitect.propose_main_outline |
| propose_characters | ProjectArchitect.propose_main_characters |
| propose_world_setting | ProjectArchitect.propose_world_setting |
| propose_story_arcs | ProjectArchitect.propose_story_arcs |
| propose_volume_breakdown | ProjectArchitect.propose_volume_breakdown |
| regenerate_section | ProjectArchitect.regenerate_section |
| propose_volume_outline | VolumeDirector.propose_volume_outline |
| propose_chapter_brief | ChapterPlanner.propose_chapter_brief |

测试策略
--------
- 用 ``inspect.signature`` 抽参数名集合。
- 断言 facade 调用点实际传的 kwarg 子集被签名覆盖（``subset`` 检查）。
- 不反射 call 真实方法（成本高且 LLM 不可避免）；Phase 4 的业务集成
  测试另行负责"传进去能跑通"，这里只守住"kwarg 名不变"。
- 每个 test case 带 ``@pytest.mark.signature``，秒级跑完。
"""

from __future__ import annotations

import inspect

import pytest

from src.novel.agents.chapter_planner import ChapterPlanner
from src.novel.agents.project_architect import ProjectArchitect
from src.novel.agents.volume_director import VolumeDirector


def _param_names(func) -> set[str]:
    """抽方法的参数名集合，去掉 ``self``。"""
    sig = inspect.signature(func)
    return set(sig.parameters.keys()) - {"self"}


# =========================================================================
# ProjectArchitect 路径（8 条）
# =========================================================================


@pytest.mark.signature
def test_facade_propose_project_setup_signature_compat() -> None:
    """facade.propose_project_setup 调用 ``architect.propose_project_setup(
    inspiration, hints=hints)``，签名必须容纳这两个参数。"""
    params = _param_names(ProjectArchitect.propose_project_setup)
    expected = {"inspiration", "hints"}
    assert expected.issubset(params), (
        f"ProjectArchitect.propose_project_setup 签名变更, 当前: {params}"
    )


@pytest.mark.signature
def test_facade_propose_synopsis_signature_compat() -> None:
    """facade.propose_synopsis 传 ``meta`` 一个位置参数。"""
    params = _param_names(ProjectArchitect.propose_synopsis)
    expected = {"meta"}
    assert expected.issubset(params), (
        f"ProjectArchitect.propose_synopsis 签名变更, 当前: {params}"
    )


@pytest.mark.signature
def test_facade_propose_main_outline_signature_compat() -> None:
    """facade.propose_main_outline 调用时传 6 个 kwarg：
    genre / theme / target_words / template_name / style_name / custom_ideas。"""
    params = _param_names(ProjectArchitect.propose_main_outline)
    expected = {
        "genre",
        "theme",
        "target_words",
        "template_name",
        "style_name",
        "custom_ideas",
    }
    assert expected.issubset(params), (
        f"ProjectArchitect.propose_main_outline 签名变更, 当前: {params}"
    )


@pytest.mark.signature
def test_facade_propose_characters_signature_compat() -> None:
    """facade.propose_characters 调用 ``architect.propose_main_characters(
    meta, synopsis=syn)``。注意：facade 方法名是 ``propose_characters``，
    但 ProjectArchitect 上真实方法名是 ``propose_main_characters``。"""
    params = _param_names(ProjectArchitect.propose_main_characters)
    expected = {"meta", "synopsis"}
    assert expected.issubset(params), (
        f"ProjectArchitect.propose_main_characters 签名变更, 当前: {params}"
    )


@pytest.mark.signature
def test_facade_propose_world_setting_signature_compat() -> None:
    """facade.propose_world_setting 调用 ``architect.propose_world_setting(
    meta, synopsis=syn)``。"""
    params = _param_names(ProjectArchitect.propose_world_setting)
    expected = {"meta", "synopsis"}
    assert expected.issubset(params), (
        f"ProjectArchitect.propose_world_setting 签名变更, 当前: {params}"
    )


@pytest.mark.signature
def test_facade_propose_story_arcs_signature_compat() -> None:
    """facade.propose_story_arcs 调用 ``architect.propose_story_arcs(
    meta, synopsis, characters=characters, world=world)``。"""
    params = _param_names(ProjectArchitect.propose_story_arcs)
    expected = {"meta", "synopsis", "characters", "world"}
    assert expected.issubset(params), (
        f"ProjectArchitect.propose_story_arcs 签名变更, 当前: {params}"
    )


@pytest.mark.signature
def test_facade_propose_volume_breakdown_signature_compat() -> None:
    """facade.propose_volume_breakdown 调用 ``architect.propose_volume_breakdown(
    meta, synopsis, arcs=arcs)``。"""
    params = _param_names(ProjectArchitect.propose_volume_breakdown)
    expected = {"meta", "synopsis", "arcs"}
    assert expected.issubset(params), (
        f"ProjectArchitect.propose_volume_breakdown 签名变更, 当前: {params}"
    )


@pytest.mark.signature
def test_facade_regenerate_section_signature_compat() -> None:
    """facade.regenerate_section 调用 ``architect.regenerate_section(
    section=pa_section, current_spine=current_spine, hints=hints)``。"""
    params = _param_names(ProjectArchitect.regenerate_section)
    expected = {"section", "current_spine", "hints"}
    assert expected.issubset(params), (
        f"ProjectArchitect.regenerate_section 签名变更, 当前: {params}"
    )


# =========================================================================
# VolumeDirector 路径（1 条）
# =========================================================================


@pytest.mark.signature
def test_facade_propose_volume_outline_signature_compat() -> None:
    """facade.propose_volume_outline + regenerate_section(section='volume_outline')
    都调用 ``director.propose_volume_outline(novel=..., volume_number=...,
    hints=...)``。PHASE5.md 指定 3 个 kwarg 必须存在。实际签名还有
    ``previous_settlement`` 但 facade 不传，不检查。"""
    params = _param_names(VolumeDirector.propose_volume_outline)
    expected = {"novel", "volume_number", "hints"}
    assert expected.issubset(params), (
        f"VolumeDirector.propose_volume_outline 签名变更, 当前: {params}"
    )


# =========================================================================
# ChapterPlanner 路径（1 条）
# =========================================================================


@pytest.mark.signature
def test_facade_propose_chapter_brief_signature_compat() -> None:
    """facade.propose_chapter_brief 调用 ``planner.propose_chapter_brief(
    novel=novel_data, volume_number=volume_number, chapter_number=chapter_number,
    chapter_outline=target_outline)``。4 个 kwarg 必须存在。"""
    params = _param_names(ChapterPlanner.propose_chapter_brief)
    expected = {"novel", "volume_number", "chapter_number", "chapter_outline"}
    assert expected.issubset(params), (
        f"ChapterPlanner.propose_chapter_brief 签名变更, 当前: {params}"
    )
