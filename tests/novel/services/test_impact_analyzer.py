"""ImpactAnalyzer 单元测试"""

from __future__ import annotations

import pytest

from src.novel.services.impact_analyzer import (
    ChangeRequest,
    ImpactAnalyzer,
    ImpactResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_novel_data(**overrides) -> dict:
    """构建标准 novel_data fixture。

    模拟 FileManager.load_novel() 返回的 dict 格式。
    包含 2 个角色、10 章大纲（其中 5 章已写）。
    """
    base: dict = {
        "novel_id": "novel_test",
        "title": "测试小说",
        "genre": "玄幻",
        "current_chapter": 5,
        "characters": [
            {
                "character_id": "char_hero",
                "name": "林逸",
                "alias": ["小逸", "逸哥"],
                "gender": "男",
                "age": 18,
                "occupation": "修炼者",
                "status": "active",
                "personality": {
                    "traits": ["勇敢", "坚韧", "善良"],
                    "core_belief": "正义必胜",
                    "motivation": "守护家人",
                    "flaw": "冲动",
                    "speech_style": "直率",
                },
                "appearance": {
                    "height": "180cm",
                    "build": "健硕",
                    "hair": "黑发",
                    "eyes": "黑色",
                    "clothing_style": "青衣",
                },
            },
            {
                "character_id": "char_villain",
                "name": "暗影",
                "alias": [],
                "gender": "男",
                "age": 30,
                "occupation": "魔修",
                "status": "active",
                "personality": {
                    "traits": ["阴险", "狡猾", "残忍"],
                    "core_belief": "力量至上",
                    "motivation": "统治世界",
                    "flaw": "自大",
                    "speech_style": "冷酷",
                },
                "appearance": {
                    "height": "185cm",
                    "build": "魁梧",
                    "hair": "白发",
                    "eyes": "红色",
                    "clothing_style": "黑袍",
                },
            },
        ],
        "world_setting": {
            "era": "古代仙侠",
            "location": "九州大陆",
            "rules": ["灵气充沛", "门派林立", "天道轮回"],
            "terms": {"灵气": "修炼基础能量", "丹田": "储存灵力的器官"},
        },
        "outline": {
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "少年出山",
                    "goal": "介绍主角",
                    "key_events": ["下山"],
                    "involved_characters": ["char_hero"],
                },
                {
                    "chapter_number": 2,
                    "title": "初遇强敌",
                    "goal": "引出反派",
                    "key_events": ["遭遇暗影"],
                    "involved_characters": ["char_hero", "char_villain"],
                },
                {
                    "chapter_number": 3,
                    "title": "修炼突破",
                    "goal": "主角变强",
                    "key_events": ["突破筑基"],
                    "involved_characters": ["char_hero"],
                },
                {
                    "chapter_number": 4,
                    "title": "暗影袭击",
                    "goal": "反派出手",
                    "key_events": ["偷袭门派"],
                    "involved_characters": ["char_hero", "char_villain"],
                },
                {
                    "chapter_number": 5,
                    "title": "绝地反击",
                    "goal": "主角反击",
                    "key_events": ["大战暗影"],
                    "involved_characters": ["char_hero", "char_villain"],
                },
                {
                    "chapter_number": 6,
                    "title": "疗伤恢复",
                    "goal": "过渡",
                    "key_events": ["恢复修为"],
                    "involved_characters": ["char_hero"],
                },
                {
                    "chapter_number": 7,
                    "title": "新的旅程",
                    "goal": "开启新篇",
                    "key_events": ["出发"],
                    "involved_characters": ["char_hero"],
                },
                {
                    "chapter_number": 8,
                    "title": "暗影复出",
                    "goal": "反派回归",
                    "key_events": ["暗影复活"],
                    "involved_characters": ["char_villain"],
                },
                {
                    "chapter_number": 9,
                    "title": "终极对决",
                    "goal": "最终大战",
                    "key_events": ["决战"],
                    "involved_characters": ["char_hero", "char_villain"],
                },
                {
                    "chapter_number": 10,
                    "title": "大结局",
                    "goal": "收尾",
                    "key_events": ["和平"],
                    "involved_characters": ["char_hero"],
                },
            ],
        },
        "chapters": [
            {
                "chapter_number": 1,
                "content": "林逸从小在山上修炼...",
                "summary": "林逸下山历练。",
            },
            {
                "chapter_number": 2,
                "content": "林逸遇到了暗影，暗影实力深不可测...",
                "summary": "林逸初遇暗影。",
            },
            {
                "chapter_number": 3,
                "content": "林逸闭关修炼，突破筑基期...",
                "summary": "林逸突破筑基。",
            },
            {
                "chapter_number": 4,
                "content": "暗影偷袭门派，林逸奋力抵抗...",
                "summary": "暗影偷袭，林逸抵抗。",
            },
            {
                "chapter_number": 5,
                "content": "林逸使出浑身解数与暗影大战...",
                "summary": "林逸与暗影决战。",
            },
        ],
    }
    base.update(overrides)
    return base


@pytest.fixture
def analyzer():
    return ImpactAnalyzer()


@pytest.fixture
def novel_data():
    return _make_novel_data()


# ---------------------------------------------------------------------------
# ChangeRequest / ImpactResult model tests
# ---------------------------------------------------------------------------

class TestModels:
    """Pydantic model 基本检查。"""

    def test_change_request_defaults(self):
        cr = ChangeRequest(
            change_type="add_character",
            entity_type="character",
        )
        assert cr.entity_id is None
        assert cr.effective_from_chapter == 1
        assert cr.details == {}

    def test_change_request_all_fields(self):
        cr = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_1",
            effective_from_chapter=5,
            details={"name": "test"},
        )
        assert cr.change_type == "delete_character"
        assert cr.entity_id == "char_1"
        assert cr.effective_from_chapter == 5
        assert cr.details["name"] == "test"

    def test_impact_result_defaults(self):
        ir = ImpactResult()
        assert ir.affected_chapters == []
        assert ir.severity == "low"
        assert ir.conflicts == []
        assert ir.warnings == []
        assert ir.summary == ""

    def test_impact_result_all_fields(self):
        ir = ImpactResult(
            affected_chapters=[1, 2, 3],
            severity="critical",
            conflicts=["conflict 1"],
            warnings=["warning 1"],
            summary="test summary",
        )
        assert ir.affected_chapters == [1, 2, 3]
        assert ir.severity == "critical"
        assert len(ir.conflicts) == 1
        assert len(ir.warnings) == 1

    def test_change_request_rejects_invalid_effective_from(self):
        with pytest.raises(Exception):
            ChangeRequest(
                change_type="add_character",
                entity_type="character",
                effective_from_chapter=0,  # ge=1 should reject
            )


# ---------------------------------------------------------------------------
# Delete character tests
# ---------------------------------------------------------------------------

class TestDeleteCharacter:
    """删除角色影响分析。"""

    def test_delete_character_critical_many_appearances(self, analyzer, novel_data):
        """角色在 >= 3 后续章节出现 -> critical。"""
        # char_hero appears in chapters 1-7, 9, 10 (many chapters)
        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_hero",
            effective_from_chapter=1,
        )
        result = analyzer.analyze(novel_data, change)

        assert result.severity == "critical"
        assert len(result.affected_chapters) >= 3
        assert len(result.conflicts) > 0
        assert "林逸" in result.summary

    def test_delete_character_high_few_appearances(self, analyzer):
        """角色在 1-2 后续章节出现 -> high。"""
        data = _make_novel_data()
        # Create a character that only appears in 2 outline chapters
        data["characters"].append({
            "character_id": "char_minor",
            "name": "路人甲",
            "alias": [],
            "gender": "男",
            "age": 25,
            "occupation": "商人",
            "status": "active",
            "personality": {
                "traits": ["老实", "胆小", "善良"],
                "core_belief": "安全第一",
                "motivation": "赚钱",
                "flaw": "胆怯",
                "speech_style": "卑微",
            },
            "appearance": {
                "height": "170cm",
                "build": "微胖",
                "hair": "棕发",
                "eyes": "棕色",
                "clothing_style": "布衣",
            },
        })
        # Add to exactly 2 outline chapters
        data["outline"]["chapters"][5]["involved_characters"].append("char_minor")  # ch6
        data["outline"]["chapters"][6]["involved_characters"].append("char_minor")  # ch7

        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_minor",
            effective_from_chapter=1,
        )
        result = analyzer.analyze(data, change)

        assert result.severity == "high"
        assert set(result.affected_chapters) == {6, 7}

    def test_delete_unused_character_low(self, analyzer):
        """删除未使用的角色 -> low。"""
        data = _make_novel_data()
        data["characters"].append({
            "character_id": "char_unused",
            "name": "隐居者",
            "alias": [],
            "gender": "男",
            "age": 99,
            "occupation": "隐士",
            "status": "active",
            "personality": {
                "traits": ["沉默", "睿智", "超然"],
                "core_belief": "无为",
                "motivation": "修行",
                "flaw": "冷漠",
                "speech_style": "沉默",
            },
            "appearance": {
                "height": "175cm",
                "build": "清瘦",
                "hair": "灰发",
                "eyes": "灰色",
                "clothing_style": "麻衣",
            },
        })

        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_unused",
            effective_from_chapter=1,
        )
        result = analyzer.analyze(data, change)

        assert result.severity == "low"
        assert result.affected_chapters == []
        assert len(result.conflicts) == 0

    def test_delete_character_nonexistent(self, analyzer, novel_data):
        """删除不存在的角色 -> low + warning。"""
        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_ghost",
            effective_from_chapter=1,
        )
        result = analyzer.analyze(novel_data, change)

        assert result.severity == "low"
        assert len(result.warnings) > 0
        assert "不存在" in result.warnings[0]

    def test_delete_character_no_entity_id(self, analyzer, novel_data):
        """删除角色但未指定 entity_id -> low + warning。"""
        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id=None,
            effective_from_chapter=1,
        )
        result = analyzer.analyze(novel_data, change)

        assert result.severity == "low"
        assert len(result.warnings) > 0

    def test_delete_character_respects_effective_from(self, analyzer, novel_data):
        """effective_from_chapter 限制查找范围。"""
        # char_villain appears in outline chapters: 2, 4, 5, 8, 9
        # With effective_from_chapter=6, only 8, 9 in outline
        # Plus written chapters >= 6: none (current_chapter=5)
        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_villain",
            effective_from_chapter=6,
        )
        result = analyzer.analyze(novel_data, change)

        # Only chapters 8 and 9 in outline from chapter 6 onward
        assert set(result.affected_chapters) == {8, 9}
        assert result.severity == "high"  # 2 chapters -> high

    def test_delete_character_includes_written_chapters(self, analyzer):
        """删除角色检查已写章节正文中的提及。"""
        data = _make_novel_data()
        # Add a character that's NOT in any outline involved_characters
        # but IS mentioned in written chapter text
        data["characters"].append({
            "character_id": "char_cameo",
            "name": "客串角色",
            "alias": ["客串"],
            "gender": "女",
            "age": 20,
            "occupation": "路人",
            "status": "active",
            "personality": {
                "traits": ["活泼", "好奇", "聪明"],
                "core_belief": "探索",
                "motivation": "冒险",
                "flaw": "鲁莽",
                "speech_style": "轻快",
            },
            "appearance": {
                "height": "165cm",
                "build": "纤细",
                "hair": "红发",
                "eyes": "绿色",
                "clothing_style": "长裙",
            },
        })
        # Mention in chapter 3 content
        data["chapters"][2]["content"] = "林逸在路上遇到了客串角色，她正在采药..."

        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_cameo",
            effective_from_chapter=1,
        )
        result = analyzer.analyze(data, change)

        assert 3 in result.affected_chapters
        assert len(result.warnings) > 0

    def test_delete_character_alias_match(self, analyzer):
        """通过别名匹配已写章节中的角色。"""
        data = _make_novel_data()
        # Chapter content mentions alias "小逸" instead of full name "林逸"
        data["chapters"][0]["content"] = "小逸从小在山上修炼..."

        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_hero",
            effective_from_chapter=1,
        )
        result = analyzer.analyze(data, change)

        # Chapter 1 should be found through alias "小逸"
        assert 1 in result.affected_chapters


# ---------------------------------------------------------------------------
# Modify character tests
# ---------------------------------------------------------------------------

class TestModifyCharacter:
    """修改角色影响分析。"""

    def test_modify_core_attribute_with_appearances(self, analyzer, novel_data):
        """修改核心属性 + 后续章节有出现 -> high。"""
        change = ChangeRequest(
            change_type="modify_character",
            entity_type="character",
            entity_id="char_hero",
            effective_from_chapter=1,
            details={"personality": {"traits": ["怯懦"]}},
        )
        result = analyzer.analyze(novel_data, change)

        assert result.severity == "high"
        assert len(result.conflicts) > 0
        assert len(result.affected_chapters) > 0

    def test_modify_non_core_attribute(self, analyzer, novel_data):
        """修改非核心属性 -> medium or low。"""
        change = ChangeRequest(
            change_type="modify_character",
            entity_type="character",
            entity_id="char_hero",
            effective_from_chapter=1,
            details={"age": 20, "appearance": {"hair": "白发"}},
        )
        result = analyzer.analyze(novel_data, change)

        # Non-core changes but character appears in chapters -> medium
        assert result.severity in ("medium", "low")
        assert len(result.warnings) > 0

    def test_modify_core_attribute_no_appearances(self, analyzer):
        """修改核心属性但角色不在任何后续大纲章节 -> medium。"""
        data = _make_novel_data()
        data["characters"].append({
            "character_id": "char_loner",
            "name": "独行者",
            "alias": [],
            "gender": "男",
            "age": 40,
            "occupation": "流浪者",
            "status": "active",
            "personality": {
                "traits": ["孤僻", "坚韧", "冷淡"],
                "core_belief": "自由",
                "motivation": "流浪",
                "flaw": "冷漠",
                "speech_style": "简短",
            },
            "appearance": {
                "height": "175cm",
                "build": "瘦削",
                "hair": "乱发",
                "eyes": "灰色",
                "clothing_style": "破衣",
            },
        })

        change = ChangeRequest(
            change_type="modify_character",
            entity_type="character",
            entity_id="char_loner",
            effective_from_chapter=1,
            details={"name": "新名字"},
        )
        result = analyzer.analyze(data, change)

        # Core change (name) but no appearances -> medium
        assert result.severity == "medium"

    def test_modify_nonexistent_character(self, analyzer, novel_data):
        """修改不存在的角色 -> low + warning。"""
        change = ChangeRequest(
            change_type="modify_character",
            entity_type="character",
            entity_id="char_ghost",
            effective_from_chapter=1,
            details={"age": 99},
        )
        result = analyzer.analyze(novel_data, change)

        assert result.severity == "low"
        assert len(result.warnings) > 0

    def test_modify_character_no_entity_id(self, analyzer, novel_data):
        """修改角色但未指定 entity_id -> low + warning。"""
        change = ChangeRequest(
            change_type="modify_character",
            entity_type="character",
            entity_id=None,
            effective_from_chapter=1,
            details={"age": 25},
        )
        result = analyzer.analyze(novel_data, change)

        assert result.severity == "low"
        assert len(result.warnings) > 0

    def test_modify_character_empty_details(self, analyzer, novel_data):
        """空的 details -> low（无变更字段）。"""
        change = ChangeRequest(
            change_type="modify_character",
            entity_type="character",
            entity_id="char_hero",
            effective_from_chapter=1,
            details={},
        )
        result = analyzer.analyze(novel_data, change)

        # No core or non-core changes, but character has appearances -> medium
        # (appearances exist, but no change fields)
        assert result.severity in ("low", "medium")


# ---------------------------------------------------------------------------
# Add character tests
# ---------------------------------------------------------------------------

class TestAddCharacter:
    """添加新角色影响分析。"""

    def test_add_character_low(self, analyzer, novel_data):
        """添加新角色 -> low（无冲突）。"""
        change = ChangeRequest(
            change_type="add_character",
            entity_type="character",
            effective_from_chapter=6,
            details={"name": "新角色"},
        )
        result = analyzer.analyze(novel_data, change)

        assert result.severity == "low"
        assert result.affected_chapters == []
        assert len(result.conflicts) == 0
        assert "新角色" in result.summary

    def test_add_character_without_name(self, analyzer, novel_data):
        """添加角色但 details 中没有 name -> 使用默认名称。"""
        change = ChangeRequest(
            change_type="add_character",
            entity_type="character",
            effective_from_chapter=1,
            details={},
        )
        result = analyzer.analyze(novel_data, change)

        assert result.severity == "low"
        assert "新角色" in result.summary


# ---------------------------------------------------------------------------
# Outline modification tests
# ---------------------------------------------------------------------------

class TestModifyOutline:
    """大纲变更影响分析。"""

    def test_modify_written_chapter_outline_high(self, analyzer, novel_data):
        """修改已写章节的大纲 -> high。"""
        change = ChangeRequest(
            change_type="modify_outline",
            entity_type="outline",
            effective_from_chapter=1,
            details={"chapter_number": 3, "goal": "主角被打败"},
        )
        result = analyzer.analyze(novel_data, change)

        assert result.severity == "high"
        assert 3 in result.affected_chapters
        assert len(result.conflicts) > 0
        assert any("已写完" in c for c in result.conflicts)

    def test_modify_unwritten_chapter_outline_low(self, analyzer, novel_data):
        """修改未写章节的大纲 -> low/medium。"""
        change = ChangeRequest(
            change_type="modify_outline",
            entity_type="outline",
            effective_from_chapter=1,
            details={"chapter_number": 8, "goal": "新情节"},
        )
        result = analyzer.analyze(novel_data, change)

        # Chapter 8 not written yet -> low or medium depending on downstream
        assert result.severity in ("low", "medium")
        assert 8 in result.affected_chapters
        assert len(result.warnings) > 0
        assert any("尚未写作" in w for w in result.warnings)

    def test_modify_outline_with_downstream_impact(self, analyzer, novel_data):
        """修改已写章节大纲 + 后续章节共享角色 -> 因果链风险。"""
        change = ChangeRequest(
            change_type="modify_outline",
            entity_type="outline",
            effective_from_chapter=1,
            details={"chapter_number": 2},
        )
        result = analyzer.analyze(novel_data, change)

        # Chapter 2 involves char_hero and char_villain
        # Downstream chapters sharing these characters should be flagged
        assert result.severity == "high"
        assert 2 in result.affected_chapters
        # Downstream chapters that share char_hero or char_villain with ch2
        assert len(result.affected_chapters) > 1

    def test_modify_outline_no_chapter_number(self, analyzer, novel_data):
        """未指定目标章节号 -> 批量修改。"""
        change = ChangeRequest(
            change_type="modify_outline",
            entity_type="outline",
            effective_from_chapter=6,
            details={"template": "new_template"},
        )
        result = analyzer.analyze(novel_data, change)

        # All outline chapters from ch6 onward
        assert all(c >= 6 for c in result.affected_chapters)
        assert len(result.warnings) > 0

    def test_modify_outline_empty_outline(self, analyzer):
        """空大纲。"""
        data = _make_novel_data(outline={"chapters": []}, current_chapter=0)

        change = ChangeRequest(
            change_type="modify_outline",
            entity_type="outline",
            effective_from_chapter=1,
            details={"chapter_number": 1},
        )
        result = analyzer.analyze(data, change)

        assert result.severity == "low"


# ---------------------------------------------------------------------------
# World modification tests
# ---------------------------------------------------------------------------

class TestModifyWorld:
    """世界观变更影响分析。"""

    def test_modify_core_world_setting_high(self, analyzer, novel_data):
        """修改核心世界观设定 + 有已写章节 -> high。"""
        change = ChangeRequest(
            change_type="modify_world",
            entity_type="world",
            effective_from_chapter=1,
            details={"rules": ["无灵气", "科技发达"], "era": "未来都市"},
        )
        result = analyzer.analyze(novel_data, change)

        assert result.severity == "high"
        assert len(result.affected_chapters) > 0
        assert len(result.conflicts) > 0

    def test_modify_world_rules_removed(self, analyzer, novel_data):
        """删除已有的世界规则 -> conflict about removed rules。"""
        change = ChangeRequest(
            change_type="modify_world",
            entity_type="world",
            effective_from_chapter=1,
            details={"rules": ["门派林立"]},  # removed "灵气充沛" and "天道轮回"
        )
        result = analyzer.analyze(novel_data, change)

        assert result.severity == "high"
        # Should mention removed rules
        has_removed_rule_conflict = any(
            "删除" in c or "removed" in c.lower() for c in result.conflicts
        )
        assert has_removed_rule_conflict

    def test_modify_non_core_world_setting(self, analyzer, novel_data):
        """修改非核心世界观设定。"""
        change = ChangeRequest(
            change_type="modify_world",
            entity_type="world",
            effective_from_chapter=1,
            details={"terms": {"灵气": "新定义"}},
        )
        result = analyzer.analyze(novel_data, change)

        # Non-core change with written chapters -> medium
        assert result.severity == "medium"
        assert len(result.warnings) > 0

    def test_modify_world_no_written_chapters(self, analyzer):
        """无已写章节时修改世界观 -> low。"""
        data = _make_novel_data(current_chapter=0, chapters=[])

        change = ChangeRequest(
            change_type="modify_world",
            entity_type="world",
            effective_from_chapter=1,
            details={"era": "现代都市"},
        )
        result = analyzer.analyze(data, change)

        assert result.severity == "low"
        assert result.affected_chapters == []

    def test_modify_world_effective_from_limits_scope(self, analyzer, novel_data):
        """effective_from_chapter 限制影响范围。"""
        change = ChangeRequest(
            change_type="modify_world",
            entity_type="world",
            effective_from_chapter=4,
            details={"rules": ["new_rule"]},
        )
        result = analyzer.analyze(novel_data, change)

        # Only chapters 4, 5 should be affected (current_chapter=5)
        assert all(c >= 4 for c in result.affected_chapters)
        assert all(c <= 5 for c in result.affected_chapters)


# ---------------------------------------------------------------------------
# Edge cases / boundary conditions
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """边界条件测试。"""

    def test_empty_novel_data(self, analyzer):
        """完全空的 novel_data。"""
        data: dict = {}
        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_1",
            effective_from_chapter=1,
        )
        result = analyzer.analyze(data, change)

        # Should not crash, character does not exist
        assert isinstance(result, ImpactResult)
        assert result.severity == "low"

    def test_no_chapters_in_outline(self, analyzer):
        """大纲中没有章节。"""
        data = _make_novel_data(
            outline={"chapters": []},
            chapters=[],
            current_chapter=0,
        )
        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_hero",
            effective_from_chapter=1,
        )
        result = analyzer.analyze(data, change)

        assert isinstance(result, ImpactResult)
        # No outline appearances, but character exists and no written chapters
        assert result.affected_chapters == []

    def test_no_characters(self, analyzer):
        """小说没有角色数据。"""
        data = _make_novel_data(characters=[])
        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_hero",
            effective_from_chapter=1,
        )
        result = analyzer.analyze(data, change)

        assert result.severity == "low"
        assert len(result.warnings) > 0

    def test_characters_as_dict(self, analyzer):
        """characters 字段为 dict 格式（兼容旧版）。"""
        data = _make_novel_data()
        # Convert list to dict format
        data["characters"] = {
            "char_hero": {"name": "林逸", "alias": ["小逸"]},
            "char_villain": {"name": "暗影", "alias": []},
        }

        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_hero",
            effective_from_chapter=1,
        )
        result = analyzer.analyze(data, change)

        assert isinstance(result, ImpactResult)
        assert "林逸" in result.summary

    def test_unknown_entity_type(self, analyzer, novel_data):
        """未知的 entity_type。"""
        change = ChangeRequest(
            change_type="modify_magic",
            entity_type="magic_system",
            effective_from_chapter=1,
        )
        result = analyzer.analyze(novel_data, change)

        assert result.severity == "low"
        assert "未知实体类型" in result.summary

    def test_unknown_character_change_type(self, analyzer, novel_data):
        """未知的角色变更类型。"""
        change = ChangeRequest(
            change_type="freeze_character",
            entity_type="character",
            effective_from_chapter=1,
        )
        result = analyzer.analyze(novel_data, change)

        assert result.severity == "low"

    def test_outline_chapter_data_not_dict(self, analyzer):
        """大纲中 chapters 元素不是 dict（容错）。"""
        data = _make_novel_data()
        data["outline"]["chapters"].append("invalid_entry")
        data["outline"]["chapters"].append(42)

        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_hero",
            effective_from_chapter=1,
        )
        # Should not crash
        result = analyzer.analyze(data, change)
        assert isinstance(result, ImpactResult)

    def test_chapter_without_content_or_summary(self, analyzer):
        """已写章节没有 content 和 summary 字段。"""
        data = _make_novel_data()
        data["chapters"] = [
            {"chapter_number": 1},  # No content, no summary
        ]

        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_hero",
            effective_from_chapter=1,
        )
        result = analyzer.analyze(data, change)
        assert isinstance(result, ImpactResult)

    def test_world_setting_key_fallback(self, analyzer):
        """novel_data 用 'world' 而不是 'world_setting'。"""
        data = _make_novel_data()
        data["world"] = data.pop("world_setting")

        change = ChangeRequest(
            change_type="modify_world",
            entity_type="world",
            effective_from_chapter=1,
            details={"rules": []},  # Remove all rules
        )
        result = analyzer.analyze(data, change)

        # Should detect removed rules
        assert isinstance(result, ImpactResult)

    def test_current_chapter_zero(self, analyzer):
        """current_chapter 为 0（没写任何章节）。"""
        data = _make_novel_data(current_chapter=0, chapters=[])

        change = ChangeRequest(
            change_type="modify_world",
            entity_type="world",
            effective_from_chapter=1,
            details={"era": "未来"},
        )
        result = analyzer.analyze(data, change)

        assert result.severity == "low"
        assert result.affected_chapters == []

    def test_chapters_with_full_text_key(self, analyzer):
        """章节使用 full_text 而非 content。"""
        data = _make_novel_data()
        data["chapters"] = [
            {"chapter_number": 1, "full_text": "林逸出山了", "summary": ""},
        ]

        change = ChangeRequest(
            change_type="delete_character",
            entity_type="character",
            entity_id="char_hero",
            effective_from_chapter=1,
        )
        result = analyzer.analyze(data, change)

        # "林逸" should be found in full_text
        assert 1 in result.affected_chapters


# ---------------------------------------------------------------------------
# Helper method tests
# ---------------------------------------------------------------------------

class TestHelperMethods:
    """内部辅助方法测试。"""

    def test_find_character_appearances(self, analyzer, novel_data):
        """_find_character_appearances 正确查找。"""
        appearances = analyzer._find_character_appearances(
            novel_data, "char_hero", from_chapter=1
        )
        # char_hero in chapters: 1, 2, 3, 4, 5, 6, 7, 9, 10
        assert 1 in appearances
        assert 8 not in appearances  # ch8 only has char_villain
        assert 9 in appearances

    def test_find_character_appearances_from_chapter(self, analyzer, novel_data):
        """_find_character_appearances 尊重 from_chapter。"""
        appearances = analyzer._find_character_appearances(
            novel_data, "char_hero", from_chapter=6
        )
        # Only chapters >= 6 that include char_hero
        assert all(c >= 6 for c in appearances)

    def test_find_character_appearances_empty_outline(self, analyzer):
        """空大纲返回空列表。"""
        data: dict = {"outline": {"chapters": []}}
        appearances = analyzer._find_character_appearances(
            data, "char_hero", from_chapter=1
        )
        assert appearances == []

    def test_find_downstream_chapters(self, analyzer, novel_data):
        """_find_downstream_chapters 查找共享角色的后续章节。"""
        downstream = analyzer._find_downstream_chapters(novel_data, 2)
        # Chapter 2 has char_hero and char_villain
        # Subsequent chapters with either: 3,4,5,6,7,8,9,10
        assert len(downstream) > 0
        assert all(c > 2 for c in downstream)

    def test_find_downstream_chapters_no_shared(self, analyzer):
        """目标章节无共享角色 -> 空列表。"""
        data = _make_novel_data()
        # Add a chapter with a unique character
        data["outline"]["chapters"].append({
            "chapter_number": 99,
            "title": "孤立章节",
            "goal": "test",
            "key_events": ["test"],
            "involved_characters": ["char_unique_999"],
        })
        downstream = analyzer._find_downstream_chapters(data, 99)
        assert downstream == []

    def test_character_exists_list_format(self, analyzer, novel_data):
        """_character_exists 列表格式。"""
        assert analyzer._character_exists(novel_data, "char_hero") is True
        assert analyzer._character_exists(novel_data, "nonexistent") is False

    def test_character_exists_dict_format(self, analyzer):
        """_character_exists dict 格式。"""
        data = {"characters": {"char_1": {"name": "test"}}}
        assert analyzer._character_exists(data, "char_1") is True
        assert analyzer._character_exists(data, "char_2") is False

    def test_resolve_character_name(self, analyzer, novel_data):
        """_resolve_character_name 正确解析。"""
        assert analyzer._resolve_character_name(novel_data, "char_hero") == "林逸"
        assert analyzer._resolve_character_name(novel_data, "char_villain") == "暗影"
        # Unknown ID returns the ID itself
        assert analyzer._resolve_character_name(novel_data, "unknown") == "unknown"

    def test_resolve_character_aliases(self, analyzer, novel_data):
        """_resolve_character_aliases 正确获取别名。"""
        aliases = analyzer._resolve_character_aliases(novel_data, "char_hero")
        assert "小逸" in aliases
        assert "逸哥" in aliases

        # Character with no aliases
        aliases = analyzer._resolve_character_aliases(novel_data, "char_villain")
        assert aliases == []

    def test_get_outline_chapter_numbers(self, analyzer, novel_data):
        """_get_outline_chapter_numbers 返回所有章节号。"""
        numbers = analyzer._get_outline_chapter_numbers(novel_data)
        assert numbers == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    def test_get_outline_chapter_numbers_empty(self, analyzer):
        """空大纲返回空列表。"""
        data: dict = {"outline": {"chapters": []}}
        numbers = analyzer._get_outline_chapter_numbers(data)
        assert numbers == []
