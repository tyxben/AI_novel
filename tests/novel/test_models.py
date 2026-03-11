"""小说模块数据模型全覆盖测试

覆盖:
- 有效数据创建
- 无效数据抛 ValidationError
- JSON 序列化/反序列化
- 边界条件
- 枚举/Literal 值验证
"""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.novel.models.chapter import Chapter, MoodTag, Scene
from src.novel.models.character import (
    Appearance,
    CharacterArc,
    CharacterProfile,
    CharacterSnapshot,
    Personality,
    Relationship,
    RelationshipEvent,
    TurningPoint,
)
from src.novel.models.foreshadowing import DetailEntry, Foreshadowing
from src.novel.models.memory import (
    ChapterSummary,
    ContextWindow,
    Fact,
    VolumeSnapshot,
)
from src.novel.models.novel import (
    Act,
    ChapterOutline,
    Novel,
    Outline,
    OutlineTemplate,
    Volume,
    VolumeOutline,
)
from src.novel.models.quality import (
    PairwiseResult,
    QualityReport,
    RuleCheckResult,
    StyleMetrics,
)
from src.novel.models.world import PowerLevel, PowerSystem, WorldSetting


# ============================================================
# Fixtures - 可复用的有效数据构造器
# ============================================================


@pytest.fixture
def valid_outline_template():
    return OutlineTemplate(
        name="cyclic_upgrade",
        description="循环升级模板",
        act_count=4,
        default_chapters_per_volume=30,
    )


@pytest.fixture
def valid_act():
    return Act(
        name="第一幕：平凡世界",
        description="主角的日常生活",
        start_chapter=1,
        end_chapter=10,
    )


@pytest.fixture
def valid_volume_outline():
    return VolumeOutline(
        volume_number=1,
        title="第一卷：初入江湖",
        core_conflict="主角被追杀",
        resolution="获得神器逃脱",
        chapters=[1, 2, 3, 4, 5],
    )


@pytest.fixture
def valid_chapter_outline():
    return ChapterOutline(
        chapter_number=1,
        title="第一章：命运开始",
        goal="介绍主角背景",
        key_events=["出场", "遇到师父"],
        mood="蓄力",
    )


@pytest.fixture
def valid_outline(valid_act, valid_volume_outline, valid_chapter_outline):
    return Outline(
        template="cyclic_upgrade",
        acts=[valid_act],
        volumes=[valid_volume_outline],
        chapters=[valid_chapter_outline],
    )


@pytest.fixture
def valid_world_setting():
    return WorldSetting(
        era="古代",
        location="中原大陆",
        rules=["修炼需要灵根"],
    )


@pytest.fixture
def valid_power_level():
    return PowerLevel(
        rank=1,
        name="炼气期",
        description="修炼入门阶段",
        typical_abilities=["感应灵气"],
    )


@pytest.fixture
def valid_power_system(valid_power_level):
    return PowerSystem(name="修炼境界", levels=[valid_power_level])


@pytest.fixture
def valid_appearance():
    return Appearance(
        height="175cm",
        build="匀称",
        hair="黑色短发",
        eyes="深棕色",
        clothing_style="白色长袍",
    )


@pytest.fixture
def valid_personality():
    return Personality(
        traits=["坚毅", "正直", "冲动"],
        core_belief="正义必胜",
        motivation="为父报仇",
        flaw="过于冲动",
        speech_style="江湖豪爽",
    )


@pytest.fixture
def valid_character_profile(valid_appearance, valid_personality):
    return CharacterProfile(
        name="张无忌",
        gender="男",
        age=18,
        occupation="少侠",
        appearance=valid_appearance,
        personality=valid_personality,
    )


@pytest.fixture
def valid_scene():
    return Scene(
        scene_number=1,
        location="客栈大堂",
        time="黄昏时分",
        characters=["char-001"],
        goal="主角初次展露实力",
    )


@pytest.fixture
def valid_chapter(valid_chapter_outline, valid_scene):
    return Chapter(
        chapter_number=1,
        title="第一章：命运开始",
        scenes=[valid_scene],
        full_text="正文内容" * 100,
        word_count=400,
        outline=valid_chapter_outline,
    )


@pytest.fixture
def valid_foreshadowing():
    return Foreshadowing(
        planted_chapter=3,
        content="主角在树下捡到的玉佩上刻着神秘符文",
        target_chapter=15,
        origin="planned",
    )


@pytest.fixture
def valid_detail_entry():
    return DetailEntry(
        chapter=5,
        content="茶馆老板的断指",
        context="前文提到茶馆老板左手少了一根小指，他习惯性地用右手端茶。",
        category="角色动作",
    )


@pytest.fixture
def valid_fact():
    return Fact(
        chapter=3,
        type="character_state",
        content="张无忌修炼九阳神功突破第三层",
        storage_layer="structured",
    )


@pytest.fixture
def valid_chapter_summary():
    return ChapterSummary(
        chapter=1,
        summary="a" * 50,  # min_length=50
        key_events=["主角出场"],
    )


@pytest.fixture
def valid_style_metrics():
    return StyleMetrics(
        avg_sentence_length=15.5,
        dialogue_ratio=0.35,
        exclamation_ratio=0.05,
        paragraph_length=120.0,
    )


@pytest.fixture
def valid_rule_check_result():
    return RuleCheckResult(passed=True)


# ============================================================
# novel.py 测试
# ============================================================


class TestOutlineTemplate:
    def test_valid(self, valid_outline_template):
        assert valid_outline_template.name == "cyclic_upgrade"
        assert valid_outline_template.act_count == 4

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            OutlineTemplate(name="", act_count=3)

    def test_act_count_boundaries(self):
        OutlineTemplate(name="test", act_count=1)
        OutlineTemplate(name="test", act_count=10)
        with pytest.raises(ValidationError):
            OutlineTemplate(name="test", act_count=0)
        with pytest.raises(ValidationError):
            OutlineTemplate(name="test", act_count=11)

    def test_json_roundtrip(self, valid_outline_template):
        json_str = valid_outline_template.model_dump_json()
        restored = OutlineTemplate.model_validate_json(json_str)
        assert restored == valid_outline_template


class TestAct:
    def test_valid(self, valid_act):
        assert valid_act.start_chapter == 1
        assert valid_act.end_chapter == 10

    def test_chapter_ge_1(self):
        with pytest.raises(ValidationError):
            Act(name="X", description="Y", start_chapter=0, end_chapter=5)

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            Act(name="", description="desc", start_chapter=1, end_chapter=5)

    def test_json_roundtrip(self, valid_act):
        restored = Act.model_validate_json(valid_act.model_dump_json())
        assert restored == valid_act


class TestVolumeOutline:
    def test_valid(self, valid_volume_outline):
        assert valid_volume_outline.volume_number == 1
        assert len(valid_volume_outline.chapters) == 5

    def test_empty_chapters_rejected(self):
        with pytest.raises(ValidationError):
            VolumeOutline(
                volume_number=1,
                title="X",
                core_conflict="Y",
                resolution="Z",
                chapters=[],
            )

    def test_json_roundtrip(self, valid_volume_outline):
        restored = VolumeOutline.model_validate_json(
            valid_volume_outline.model_dump_json()
        )
        assert restored == valid_volume_outline


class TestChapterOutline:
    def test_valid(self, valid_chapter_outline):
        assert valid_chapter_outline.mood == "蓄力"
        assert valid_chapter_outline.estimated_words == 2500

    def test_empty_key_events_rejected(self):
        with pytest.raises(ValidationError):
            ChapterOutline(
                chapter_number=1, title="X", goal="Y", key_events=[]
            )

    def test_mood_literal_validation(self):
        co = ChapterOutline(
            chapter_number=1,
            title="X",
            goal="Y",
            key_events=["e"],
            mood="大爽",
        )
        assert co.mood == "大爽"

        with pytest.raises(ValidationError):
            ChapterOutline(
                chapter_number=1,
                title="X",
                goal="Y",
                key_events=["e"],
                mood="invalid_mood",
            )

    def test_estimated_words_boundaries(self):
        ChapterOutline(
            chapter_number=1,
            title="X",
            goal="Y",
            key_events=["e"],
            estimated_words=1000,
        )
        ChapterOutline(
            chapter_number=1,
            title="X",
            goal="Y",
            key_events=["e"],
            estimated_words=10000,
        )
        with pytest.raises(ValidationError):
            ChapterOutline(
                chapter_number=1,
                title="X",
                goal="Y",
                key_events=["e"],
                estimated_words=499,  # min is 500
            )
        with pytest.raises(ValidationError):
            ChapterOutline(
                chapter_number=1,
                title="X",
                goal="Y",
                key_events=["e"],
                estimated_words=10001,
            )

    def test_json_roundtrip(self, valid_chapter_outline):
        restored = ChapterOutline.model_validate_json(
            valid_chapter_outline.model_dump_json()
        )
        assert restored == valid_chapter_outline


class TestOutline:
    def test_valid(self, valid_outline):
        assert valid_outline.template == "cyclic_upgrade"
        assert len(valid_outline.acts) == 1

    def test_invalid_template(self, valid_act):
        with pytest.raises(ValidationError):
            Outline(template="nonexistent", acts=[valid_act])

    def test_all_templates(self):
        for t in ["cyclic_upgrade", "multi_thread", "four_act", "custom"]:
            o = Outline(template=t)
            assert o.template == t

    def test_json_roundtrip(self, valid_outline):
        restored = Outline.model_validate_json(valid_outline.model_dump_json())
        assert restored == valid_outline


class TestVolume:
    def test_valid(self):
        v = Volume(volume_number=1, title="第一卷")
        assert v.status == "planning"

    def test_status_literal(self):
        for s in ["planning", "writing", "completed"]:
            v = Volume(volume_number=1, title="X", status=s)
            assert v.status == s

        with pytest.raises(ValidationError):
            Volume(volume_number=1, title="X", status="invalid")

    def test_json_roundtrip(self):
        v = Volume(volume_number=1, title="X", chapters=[1, 2, 3])
        restored = Volume.model_validate_json(v.model_dump_json())
        assert restored == v


class TestNovel:
    def test_valid(self, valid_outline, valid_world_setting):
        novel = Novel(
            title="九州风云录",
            genre="武侠",
            theme="江湖恩怨",
            target_words=500000,
            style_category="武侠",
            style_subcategory="新武侠",
            outline=valid_outline,
            world_setting=valid_world_setting,
        )
        assert novel.status == "draft"
        assert novel.current_chapter == 0
        assert len(novel.novel_id) > 0
        assert novel.created_at  # ISO string generated

    def test_uuid_auto_generated(self, valid_outline, valid_world_setting):
        n1 = Novel(
            title="A",
            genre="武侠",
            theme="T",
            target_words=100,
            style_category="武侠",
            style_subcategory="经典",
            outline=valid_outline,
            world_setting=valid_world_setting,
        )
        n2 = Novel(
            title="B",
            genre="武侠",
            theme="T",
            target_words=100,
            style_category="武侠",
            style_subcategory="经典",
            outline=valid_outline,
            world_setting=valid_world_setting,
        )
        assert n1.novel_id != n2.novel_id

    def test_target_words_must_be_positive(
        self, valid_outline, valid_world_setting
    ):
        with pytest.raises(ValidationError):
            Novel(
                title="X",
                genre="武侠",
                theme="T",
                target_words=0,
                style_category="武侠",
                style_subcategory="经典",
                outline=valid_outline,
                world_setting=valid_world_setting,
            )

    def test_status_literal(self, valid_outline, valid_world_setting):
        for s in ["draft", "writing", "completed"]:
            n = Novel(
                title="X",
                genre="武侠",
                theme="T",
                target_words=100,
                style_category="武侠",
                style_subcategory="经典",
                outline=valid_outline,
                world_setting=valid_world_setting,
                status=s,
            )
            assert n.status == s

        with pytest.raises(ValidationError):
            Novel(
                title="X",
                genre="武侠",
                theme="T",
                target_words=100,
                style_category="武侠",
                style_subcategory="经典",
                outline=valid_outline,
                world_setting=valid_world_setting,
                status="invalid",
            )

    def test_empty_title_rejected(self, valid_outline, valid_world_setting):
        with pytest.raises(ValidationError):
            Novel(
                title="",
                genre="武侠",
                theme="T",
                target_words=100,
                style_category="武侠",
                style_subcategory="经典",
                outline=valid_outline,
                world_setting=valid_world_setting,
            )

    def test_json_roundtrip(self, valid_outline, valid_world_setting):
        novel = Novel(
            title="测试小说",
            genre="武侠",
            theme="复仇",
            target_words=100000,
            style_category="武侠",
            style_subcategory="新武侠",
            outline=valid_outline,
            world_setting=valid_world_setting,
        )
        json_str = novel.model_dump_json()
        data = json.loads(json_str)
        assert data["title"] == "测试小说"
        restored = Novel.model_validate_json(json_str)
        assert restored.title == novel.title
        assert restored.novel_id == novel.novel_id


# ============================================================
# chapter.py 测试
# ============================================================


class TestMoodTag:
    def test_all_values(self):
        assert MoodTag.BUILDUP.value == "蓄力"
        assert MoodTag.SMALL_WIN.value == "小爽"
        assert MoodTag.BIG_WIN.value == "大爽"
        assert MoodTag.TRANSITION.value == "过渡"
        assert MoodTag.HEARTBREAK.value == "虐心"
        assert MoodTag.TWIST.value == "反转"
        assert MoodTag.DAILY.value == "日常"

    def test_from_value(self):
        assert MoodTag("蓄力") == MoodTag.BUILDUP

    def test_invalid_value(self):
        with pytest.raises(ValueError):
            MoodTag("无效")


class TestScene:
    def test_valid(self, valid_scene):
        assert valid_scene.scene_number == 1
        assert valid_scene.location == "客栈大堂"
        assert len(valid_scene.scene_id) > 0

    def test_uuid_auto_generated(self):
        s1 = Scene(
            scene_number=1,
            location="A",
            time="T",
            characters=["c1"],
            goal="G",
        )
        s2 = Scene(
            scene_number=1,
            location="A",
            time="T",
            characters=["c1"],
            goal="G",
        )
        assert s1.scene_id != s2.scene_id

    def test_empty_characters_rejected(self):
        with pytest.raises(ValidationError):
            Scene(
                scene_number=1,
                location="A",
                time="T",
                characters=[],
                goal="G",
            )

    def test_scene_number_ge_1(self):
        with pytest.raises(ValidationError):
            Scene(
                scene_number=0,
                location="A",
                time="T",
                characters=["c1"],
                goal="G",
            )

    def test_text_max_length(self):
        Scene(
            scene_number=1,
            location="A",
            time="T",
            characters=["c1"],
            goal="G",
            text="x" * 15000,
        )
        with pytest.raises(ValidationError):
            Scene(
                scene_number=1,
                location="A",
                time="T",
                characters=["c1"],
                goal="G",
                text="x" * 15001,
            )

    def test_json_roundtrip(self, valid_scene):
        restored = Scene.model_validate_json(valid_scene.model_dump_json())
        assert restored.scene_number == valid_scene.scene_number
        assert restored.location == valid_scene.location


class TestChapter:
    def test_valid(self, valid_chapter):
        assert valid_chapter.chapter_number == 1
        assert valid_chapter.status == "draft"
        assert valid_chapter.revision_count == 0

    def test_status_literal(self, valid_chapter_outline):
        for s in ["draft", "reviewed", "finalized"]:
            c = Chapter(
                chapter_number=1, title="X", outline=valid_chapter_outline, status=s
            )
            assert c.status == s

        with pytest.raises(ValidationError):
            Chapter(
                chapter_number=1,
                title="X",
                outline=valid_chapter_outline,
                status="bad",
            )

    def test_quality_score_boundaries(self, valid_chapter_outline):
        Chapter(
            chapter_number=1,
            title="X",
            outline=valid_chapter_outline,
            quality_score=0.0,
        )
        Chapter(
            chapter_number=1,
            title="X",
            outline=valid_chapter_outline,
            quality_score=10.0,
        )
        with pytest.raises(ValidationError):
            Chapter(
                chapter_number=1,
                title="X",
                outline=valid_chapter_outline,
                quality_score=-0.1,
            )
        with pytest.raises(ValidationError):
            Chapter(
                chapter_number=1,
                title="X",
                outline=valid_chapter_outline,
                quality_score=10.1,
            )

    def test_json_roundtrip(self, valid_chapter):
        json_str = valid_chapter.model_dump_json()
        restored = Chapter.model_validate_json(json_str)
        assert restored.chapter_number == valid_chapter.chapter_number
        assert restored.title == valid_chapter.title
        assert len(restored.scenes) == len(valid_chapter.scenes)


# ============================================================
# character.py 测试
# ============================================================


class TestAppearance:
    def test_valid(self, valid_appearance):
        assert valid_appearance.height == "175cm"

    def test_empty_field_rejected(self):
        with pytest.raises(ValidationError):
            Appearance(
                height="", build="匀称", hair="黑", eyes="棕", clothing_style="白"
            )

    def test_json_roundtrip(self, valid_appearance):
        restored = Appearance.model_validate_json(
            valid_appearance.model_dump_json()
        )
        assert restored == valid_appearance


class TestPersonality:
    def test_valid(self, valid_personality):
        assert len(valid_personality.traits) == 3

    def test_traits_min_3(self):
        with pytest.raises(ValidationError):
            Personality(
                traits=["A", "B"],
                core_belief="X",
                motivation="M",
                flaw="F",
                speech_style="S",
            )

    def test_traits_max_7(self):
        with pytest.raises(ValidationError):
            Personality(
                traits=["A", "B", "C", "D", "E", "F", "G", "H"],
                core_belief="X",
                motivation="M",
                flaw="F",
                speech_style="S",
            )

    def test_traits_exactly_3_and_7(self):
        Personality(
            traits=["A", "B", "C"],
            core_belief="X",
            motivation="M",
            flaw="F",
            speech_style="S",
        )
        Personality(
            traits=["A", "B", "C", "D", "E", "F", "G"],
            core_belief="X",
            motivation="M",
            flaw="F",
            speech_style="S",
        )

    def test_json_roundtrip(self, valid_personality):
        restored = Personality.model_validate_json(
            valid_personality.model_dump_json()
        )
        assert restored == valid_personality


class TestRelationship:
    def test_valid(self):
        r = Relationship(
            target_character_id="char-002",
            current_type="友好",
            description="同门师兄弟",
            intensity=7,
        )
        assert r.intensity == 7

    def test_intensity_boundaries(self):
        with pytest.raises(ValidationError):
            Relationship(
                target_character_id="c",
                current_type="友好",
                description="D",
                intensity=0,
            )
        with pytest.raises(ValidationError):
            Relationship(
                target_character_id="c",
                current_type="友好",
                description="D",
                intensity=11,
            )

    def test_json_roundtrip(self):
        r = Relationship(
            target_character_id="c",
            current_type="敌对",
            description="D",
            intensity=5,
            history=[
                RelationshipEvent(
                    chapter=3,
                    from_type="陌生",
                    to_type="敌对",
                    trigger_event="争夺宝物",
                    intensity_change=5,
                )
            ],
        )
        restored = Relationship.model_validate_json(r.model_dump_json())
        assert len(restored.history) == 1
        assert restored.history[0].trigger_event == "争夺宝物"


class TestRelationshipEvent:
    def test_valid(self):
        e = RelationshipEvent(
            chapter=5,
            from_type="友好",
            to_type="敌对",
            trigger_event="背叛事件",
            intensity_change=-8,
        )
        assert e.intensity_change == -8

    def test_intensity_change_boundaries(self):
        RelationshipEvent(
            chapter=1,
            from_type="A",
            to_type="B",
            trigger_event="E",
            intensity_change=-10,
        )
        RelationshipEvent(
            chapter=1,
            from_type="A",
            to_type="B",
            trigger_event="E",
            intensity_change=10,
        )
        with pytest.raises(ValidationError):
            RelationshipEvent(
                chapter=1,
                from_type="A",
                to_type="B",
                trigger_event="E",
                intensity_change=-11,
            )
        with pytest.raises(ValidationError):
            RelationshipEvent(
                chapter=1,
                from_type="A",
                to_type="B",
                trigger_event="E",
                intensity_change=11,
            )


class TestCharacterArc:
    def test_valid(self):
        arc = CharacterArc(
            initial_state="懦弱自卑",
            final_state="自信坚毅",
            turning_points=[
                TurningPoint(chapter=5, event="初战胜利", change="学会勇气")
            ],
        )
        assert arc.initial_state == "懦弱自卑"

    def test_empty_states_rejected(self):
        with pytest.raises(ValidationError):
            CharacterArc(initial_state="", final_state="X")


class TestTurningPoint:
    def test_valid(self):
        tp = TurningPoint(chapter=10, event="师父牺牲", change="觉醒力量")
        assert tp.chapter == 10

    def test_chapter_ge_1(self):
        with pytest.raises(ValidationError):
            TurningPoint(chapter=0, event="E", change="C")


class TestCharacterSnapshot:
    def test_valid(self):
        cs = CharacterSnapshot(
            character_id="c1",
            name="张三",
            location="京城",
            health="健康",
            emotional_state="平静",
        )
        assert cs.current_power_level is None

    def test_with_power_level(self):
        cs = CharacterSnapshot(
            character_id="c1",
            name="张三",
            current_power_level="金丹期",
            location="京城",
            health="健康",
            emotional_state="平静",
        )
        assert cs.current_power_level == "金丹期"

    def test_json_roundtrip(self):
        cs = CharacterSnapshot(
            character_id="c1",
            name="张三",
            location="京城",
            health="健康",
            emotional_state="平静",
            key_relationships_changed=["与李四反目"],
        )
        restored = CharacterSnapshot.model_validate_json(cs.model_dump_json())
        assert restored == cs


class TestCharacterProfile:
    def test_valid(self, valid_character_profile):
        assert valid_character_profile.name == "张无忌"
        assert valid_character_profile.gender == "男"
        assert valid_character_profile.status == "active"

    def test_uuid_auto_generated(self, valid_appearance, valid_personality):
        c1 = CharacterProfile(
            name="A",
            gender="男",
            age=20,
            occupation="O",
            appearance=valid_appearance,
            personality=valid_personality,
        )
        c2 = CharacterProfile(
            name="B",
            gender="女",
            age=20,
            occupation="O",
            appearance=valid_appearance,
            personality=valid_personality,
        )
        assert c1.character_id != c2.character_id

    def test_gender_literal(self, valid_appearance, valid_personality):
        for g in ["男", "女", "其他"]:
            CharacterProfile(
                name="A",
                gender=g,
                age=20,
                occupation="O",
                appearance=valid_appearance,
                personality=valid_personality,
            )
        with pytest.raises(ValidationError):
            CharacterProfile(
                name="A",
                gender="unknown",
                age=20,
                occupation="O",
                appearance=valid_appearance,
                personality=valid_personality,
            )

    def test_age_boundaries(self, valid_appearance, valid_personality):
        CharacterProfile(
            name="A",
            gender="男",
            age=0,
            occupation="O",
            appearance=valid_appearance,
            personality=valid_personality,
        )
        CharacterProfile(
            name="A",
            gender="男",
            age=200,
            occupation="O",
            appearance=valid_appearance,
            personality=valid_personality,
        )
        with pytest.raises(ValidationError):
            CharacterProfile(
                name="A",
                gender="男",
                age=-1,
                occupation="O",
                appearance=valid_appearance,
                personality=valid_personality,
            )
        with pytest.raises(ValidationError):
            CharacterProfile(
                name="A",
                gender="男",
                age=201,
                occupation="O",
                appearance=valid_appearance,
                personality=valid_personality,
            )

    def test_status_literal(self, valid_appearance, valid_personality):
        for s in ["active", "retired", "deceased", "absent"]:
            CharacterProfile(
                name="A",
                gender="男",
                age=20,
                occupation="O",
                appearance=valid_appearance,
                personality=valid_personality,
                status=s,
            )
        with pytest.raises(ValidationError):
            CharacterProfile(
                name="A",
                gender="男",
                age=20,
                occupation="O",
                appearance=valid_appearance,
                personality=valid_personality,
                status="dead",
            )

    def test_json_roundtrip(self, valid_character_profile):
        json_str = valid_character_profile.model_dump_json()
        restored = CharacterProfile.model_validate_json(json_str)
        assert restored.name == valid_character_profile.name
        assert restored.appearance.height == "175cm"
        assert len(restored.personality.traits) == 3


# ============================================================
# world.py 测试
# ============================================================


class TestPowerLevel:
    def test_valid(self, valid_power_level):
        assert valid_power_level.rank == 1
        assert valid_power_level.name == "炼气期"

    def test_rank_ge_1(self):
        with pytest.raises(ValidationError):
            PowerLevel(rank=0, name="X", description="D")

    def test_json_roundtrip(self, valid_power_level):
        restored = PowerLevel.model_validate_json(
            valid_power_level.model_dump_json()
        )
        assert restored == valid_power_level


class TestPowerSystem:
    def test_valid(self, valid_power_system):
        assert valid_power_system.name == "修炼境界"
        assert len(valid_power_system.levels) == 1

    def test_empty_levels_rejected(self):
        with pytest.raises(ValidationError):
            PowerSystem(name="X", levels=[])

    def test_json_roundtrip(self, valid_power_system):
        restored = PowerSystem.model_validate_json(
            valid_power_system.model_dump_json()
        )
        assert restored == valid_power_system


class TestWorldSetting:
    def test_valid(self, valid_world_setting):
        assert valid_world_setting.era == "古代"
        assert valid_world_setting.power_system is None

    def test_with_power_system(self, valid_power_system):
        ws = WorldSetting(
            era="古代",
            location="中原",
            power_system=valid_power_system,
        )
        assert ws.power_system is not None
        assert ws.power_system.name == "修炼境界"

    def test_with_terms(self):
        ws = WorldSetting(
            era="古代",
            location="中原",
            terms={"灵根": "修炼天赋", "丹田": "储存灵力的器官"},
        )
        assert len(ws.terms) == 2

    def test_empty_era_rejected(self):
        with pytest.raises(ValidationError):
            WorldSetting(era="", location="中原")

    def test_json_roundtrip(self, valid_world_setting):
        restored = WorldSetting.model_validate_json(
            valid_world_setting.model_dump_json()
        )
        assert restored == valid_world_setting


# ============================================================
# memory.py 测试
# ============================================================


class TestFact:
    def test_valid(self, valid_fact):
        assert valid_fact.type == "character_state"
        assert valid_fact.storage_layer == "structured"
        assert len(valid_fact.fact_id) > 0

    def test_type_literal(self):
        for t in ["time", "character_state", "location", "event", "relationship"]:
            Fact(chapter=1, type=t, content="X", storage_layer="structured")

        with pytest.raises(ValidationError):
            Fact(
                chapter=1,
                type="invalid_type",
                content="X",
                storage_layer="structured",
            )

    def test_storage_layer_literal(self):
        for sl in ["structured", "graph", "vector"]:
            Fact(chapter=1, type="event", content="X", storage_layer=sl)

        with pytest.raises(ValidationError):
            Fact(
                chapter=1,
                type="event",
                content="X",
                storage_layer="invalid",
            )

    def test_with_embedding(self):
        f = Fact(
            chapter=1,
            type="event",
            content="X",
            storage_layer="vector",
            embedding=[0.1, 0.2, 0.3],
        )
        assert f.embedding == [0.1, 0.2, 0.3]

    def test_json_roundtrip(self, valid_fact):
        restored = Fact.model_validate_json(valid_fact.model_dump_json())
        assert restored.type == valid_fact.type
        assert restored.content == valid_fact.content


class TestChapterSummary:
    def test_valid(self, valid_chapter_summary):
        assert valid_chapter_summary.chapter == 1

    def test_summary_min_length(self):
        with pytest.raises(ValidationError):
            ChapterSummary(
                chapter=1, summary="too short", key_events=["E"]
            )

    def test_summary_max_length(self):
        with pytest.raises(ValidationError):
            ChapterSummary(
                chapter=1, summary="x" * 1001, key_events=["E"]
            )

    def test_empty_key_events_rejected(self):
        with pytest.raises(ValidationError):
            ChapterSummary(chapter=1, summary="x" * 50, key_events=[])

    def test_json_roundtrip(self, valid_chapter_summary):
        restored = ChapterSummary.model_validate_json(
            valid_chapter_summary.model_dump_json()
        )
        assert restored == valid_chapter_summary


class TestVolumeSnapshot:
    def test_valid(self):
        vs = VolumeSnapshot(
            volume_number=1,
            main_plot_progress="主角完成第一个任务",
            main_plot_completion=0.1,
            ending_summary="a" * 100,
        )
        assert vs.main_plot_completion == 0.1
        assert len(vs.character_states) == 0

    def test_completion_boundaries(self):
        VolumeSnapshot(
            volume_number=1,
            main_plot_progress="X",
            main_plot_completion=0.0,
            ending_summary="a" * 100,
        )
        VolumeSnapshot(
            volume_number=1,
            main_plot_progress="X",
            main_plot_completion=1.0,
            ending_summary="a" * 100,
        )
        with pytest.raises(ValidationError):
            VolumeSnapshot(
                volume_number=1,
                main_plot_progress="X",
                main_plot_completion=-0.1,
                ending_summary="a" * 100,
            )
        with pytest.raises(ValidationError):
            VolumeSnapshot(
                volume_number=1,
                main_plot_progress="X",
                main_plot_completion=1.1,
                ending_summary="a" * 100,
            )

    def test_ending_summary_min_length(self):
        with pytest.raises(ValidationError):
            VolumeSnapshot(
                volume_number=1,
                main_plot_progress="X",
                main_plot_completion=0.5,
                ending_summary="too short",
            )

    def test_json_roundtrip(self):
        vs = VolumeSnapshot(
            volume_number=2,
            main_plot_progress="进展顺利",
            main_plot_completion=0.5,
            ending_summary="a" * 100,
            cliffhanger="敌人突然出现",
            new_terms={"天劫": "突破时的考验"},
        )
        restored = VolumeSnapshot.model_validate_json(vs.model_dump_json())
        assert restored.cliffhanger == "敌人突然出现"
        assert restored.new_terms["天劫"] == "突破时的考验"


class TestContextWindow:
    def test_valid(self):
        cw = ContextWindow()
        assert cw.recent_chapters_text == ""
        assert cw.max_tokens == 8000

    def test_max_tokens_boundaries(self):
        ContextWindow(max_tokens=1000)
        ContextWindow(max_tokens=128000)
        with pytest.raises(ValidationError):
            ContextWindow(max_tokens=999)
        with pytest.raises(ValidationError):
            ContextWindow(max_tokens=128001)

    def test_with_data(self, valid_fact, valid_chapter_summary):
        cw = ContextWindow(
            recent_chapters_text="最近三章内容...",
            chapter_summaries=[valid_chapter_summary],
            relevant_facts=[valid_fact],
            max_tokens=16000,
        )
        assert len(cw.chapter_summaries) == 1
        assert len(cw.relevant_facts) == 1

    def test_json_roundtrip(self, valid_fact, valid_chapter_summary):
        cw = ContextWindow(
            recent_chapters_text="text",
            chapter_summaries=[valid_chapter_summary],
            relevant_facts=[valid_fact],
        )
        restored = ContextWindow.model_validate_json(cw.model_dump_json())
        assert restored.recent_chapters_text == "text"
        assert len(restored.relevant_facts) == 1


# ============================================================
# quality.py 测试
# ============================================================


class TestStyleMetrics:
    def test_valid(self, valid_style_metrics):
        assert valid_style_metrics.avg_sentence_length == 15.5
        assert valid_style_metrics.classical_word_ratio is None

    def test_ratio_boundaries(self):
        StyleMetrics(
            avg_sentence_length=0,
            dialogue_ratio=0.0,
            exclamation_ratio=0.0,
            paragraph_length=0,
        )
        StyleMetrics(
            avg_sentence_length=100,
            dialogue_ratio=1.0,
            exclamation_ratio=1.0,
            paragraph_length=1000,
        )
        with pytest.raises(ValidationError):
            StyleMetrics(
                avg_sentence_length=10,
                dialogue_ratio=-0.1,
                exclamation_ratio=0.0,
                paragraph_length=100,
            )
        with pytest.raises(ValidationError):
            StyleMetrics(
                avg_sentence_length=10,
                dialogue_ratio=1.1,
                exclamation_ratio=0.0,
                paragraph_length=100,
            )

    def test_optional_fields(self):
        sm = StyleMetrics(
            avg_sentence_length=10,
            dialogue_ratio=0.3,
            exclamation_ratio=0.05,
            paragraph_length=80,
            classical_word_ratio=0.15,
            description_ratio=0.4,
            first_person_ratio=0.0,
        )
        assert sm.classical_word_ratio == 0.15

    def test_json_roundtrip(self, valid_style_metrics):
        restored = StyleMetrics.model_validate_json(
            valid_style_metrics.model_dump_json()
        )
        assert restored == valid_style_metrics


class TestRuleCheckResult:
    def test_valid_passed(self, valid_rule_check_result):
        assert valid_rule_check_result.passed is True
        assert valid_rule_check_result.repetition_issues == []

    def test_with_issues(self):
        result = RuleCheckResult(
            passed=False,
            repetition_issues=["第3段连续重复"],
            ai_flavor_issues=["使用了'不禁'"],
        )
        assert not result.passed
        assert len(result.repetition_issues) == 1
        assert len(result.ai_flavor_issues) == 1

    def test_json_roundtrip(self):
        result = RuleCheckResult(
            passed=False, dialogue_tag_issues=["对话标签不一致"]
        )
        restored = RuleCheckResult.model_validate_json(result.model_dump_json())
        assert restored.passed is False
        assert restored.dialogue_tag_issues == ["对话标签不一致"]


class TestPairwiseResult:
    def test_valid(self):
        pr = PairwiseResult(winner="A", reason="版本A情节更紧凑")
        assert pr.winner == "A"

    def test_winner_literal(self):
        for w in ["A", "B", "TIE"]:
            PairwiseResult(winner=w, reason="理由")
        with pytest.raises(ValidationError):
            PairwiseResult(winner="C", reason="理由")

    def test_empty_reason_rejected(self):
        with pytest.raises(ValidationError):
            PairwiseResult(winner="A", reason="")

    def test_json_roundtrip(self):
        pr = PairwiseResult(winner="TIE", reason="两个版本各有优劣")
        restored = PairwiseResult.model_validate_json(pr.model_dump_json())
        assert restored == pr


class TestQualityReport:
    def test_valid(self, valid_rule_check_result):
        qr = QualityReport(
            chapter_number=1,
            rule_check=valid_rule_check_result,
            scores={
                "plot_coherence": 8.0,
                "writing_quality": 7.5,
            },
        )
        assert qr.need_rewrite is False
        assert qr.rewrite_reason is None

    def test_with_rewrite(self, valid_rule_check_result):
        qr = QualityReport(
            chapter_number=5,
            rule_check=valid_rule_check_result,
            need_rewrite=True,
            rewrite_reason="AI味过重",
            suggestions=["减少感叹句", "增加对话"],
        )
        assert qr.need_rewrite is True
        assert len(qr.suggestions) == 2

    def test_json_roundtrip(self, valid_rule_check_result):
        qr = QualityReport(
            chapter_number=1,
            rule_check=valid_rule_check_result,
            scores={"plot_coherence": 9.0},
        )
        restored = QualityReport.model_validate_json(qr.model_dump_json())
        assert restored.scores["plot_coherence"] == 9.0


# ============================================================
# foreshadowing.py 测试
# ============================================================


class TestForeshadowing:
    def test_valid(self, valid_foreshadowing):
        assert valid_foreshadowing.origin == "planned"
        assert valid_foreshadowing.status == "pending"
        assert len(valid_foreshadowing.foreshadowing_id) > 0

    def test_origin_literal(self):
        Foreshadowing(
            planted_chapter=1,
            content="X",
            target_chapter=5,
            origin="planned",
        )
        Foreshadowing(
            planted_chapter=1,
            content="X",
            target_chapter=-1,
            origin="retroactive",
        )
        with pytest.raises(ValidationError):
            Foreshadowing(
                planted_chapter=1,
                content="X",
                target_chapter=5,
                origin="invalid",
            )

    def test_status_literal(self):
        for s in ["pending", "collected", "abandoned"]:
            Foreshadowing(
                planted_chapter=1,
                content="X",
                target_chapter=5,
                origin="planned",
                status=s,
            )
        with pytest.raises(ValidationError):
            Foreshadowing(
                planted_chapter=1,
                content="X",
                target_chapter=5,
                origin="planned",
                status="done",
            )

    def test_target_chapter_allows_negative_one(self):
        f = Foreshadowing(
            planted_chapter=1,
            content="X",
            target_chapter=-1,
            origin="retroactive",
        )
        assert f.target_chapter == -1

    def test_target_chapter_rejects_below_negative_one(self):
        with pytest.raises(ValidationError):
            Foreshadowing(
                planted_chapter=1,
                content="X",
                target_chapter=-2,
                origin="planned",
            )

    def test_retroactive_with_detail_id(self):
        f = Foreshadowing(
            planted_chapter=3,
            content="伏笔内容",
            target_chapter=-1,
            origin="retroactive",
            original_detail_id="detail-001",
            original_context="上下文内容",
        )
        assert f.original_detail_id == "detail-001"

    def test_json_roundtrip(self, valid_foreshadowing):
        restored = Foreshadowing.model_validate_json(
            valid_foreshadowing.model_dump_json()
        )
        assert restored.content == valid_foreshadowing.content
        assert restored.origin == valid_foreshadowing.origin


class TestDetailEntry:
    def test_valid(self, valid_detail_entry):
        assert valid_detail_entry.category == "角色动作"
        assert valid_detail_entry.status == "available"

    def test_status_literal(self):
        for s in ["available", "promoted", "used"]:
            DetailEntry(
                chapter=1,
                content="X",
                context="C",
                category="道具",
                status=s,
            )
        with pytest.raises(ValidationError):
            DetailEntry(
                chapter=1,
                content="X",
                context="C",
                category="道具",
                status="invalid",
            )

    def test_promoted_with_foreshadowing_id(self):
        de = DetailEntry(
            chapter=5,
            content="断剑",
            context="角色捡起断剑仔细端详",
            category="道具",
            status="promoted",
            promoted_foreshadowing_id="fs-001",
        )
        assert de.promoted_foreshadowing_id == "fs-001"

    def test_empty_content_rejected(self):
        with pytest.raises(ValidationError):
            DetailEntry(
                chapter=1, content="", context="C", category="道具"
            )

    def test_json_roundtrip(self, valid_detail_entry):
        restored = DetailEntry.model_validate_json(
            valid_detail_entry.model_dump_json()
        )
        assert restored.category == valid_detail_entry.category
        assert restored.content == valid_detail_entry.content


# ============================================================
# 跨模型集成测试
# ============================================================


class TestCrossModelIntegration:
    """测试模型之间的组合和嵌套"""

    def test_novel_full_json_roundtrip(
        self,
        valid_outline,
        valid_world_setting,
        valid_character_profile,
        valid_chapter,
    ):
        """完整 Novel 对象的 JSON 序列化/反序列化"""
        novel = Novel(
            title="九州风云录",
            genre="武侠",
            theme="江湖恩怨",
            target_words=500000,
            style_category="武侠",
            style_subcategory="新武侠",
            outline=valid_outline,
            world_setting=valid_world_setting,
            characters=[valid_character_profile],
            chapters=[valid_chapter],
        )
        json_str = novel.model_dump_json()
        data = json.loads(json_str)

        # 验证嵌套结构
        assert data["characters"][0]["name"] == "张无忌"
        assert data["outline"]["template"] == "cyclic_upgrade"
        assert data["world_setting"]["era"] == "古代"

        # 反序列化
        restored = Novel.model_validate_json(json_str)
        assert restored.title == "九州风云录"
        assert len(restored.characters) == 1
        assert restored.characters[0].personality.traits[0] == "坚毅"

    def test_volume_with_snapshot(self, valid_foreshadowing):
        """Volume 包含 VolumeSnapshot 的序列化"""
        snapshot = VolumeSnapshot(
            volume_number=1,
            main_plot_progress="完成第一阶段",
            main_plot_completion=0.25,
            character_states=[
                CharacterSnapshot(
                    character_id="c1",
                    name="张三",
                    location="京城",
                    health="健康",
                    emotional_state="平静",
                )
            ],
            unresolved_foreshadowing=[valid_foreshadowing],
            ending_summary="a" * 100,
        )
        volume = Volume(
            volume_number=1,
            title="第一卷",
            chapters=[1, 2, 3],
            status="completed",
            snapshot=snapshot,
        )
        json_str = volume.model_dump_json()
        restored = Volume.model_validate_json(json_str)
        assert restored.snapshot is not None
        assert restored.snapshot.main_plot_completion == 0.25
        assert len(restored.snapshot.character_states) == 1
        assert len(restored.snapshot.unresolved_foreshadowing) == 1

    def test_model_dump_dict(self, valid_character_profile):
        """model_dump() 返回纯 dict 的验证"""
        data = valid_character_profile.model_dump()
        assert isinstance(data, dict)
        assert isinstance(data["appearance"], dict)
        assert isinstance(data["personality"]["traits"], list)

    def test_all_models_importable_from_init(self):
        """确认所有模型都能从 __init__ 导入"""
        from src.novel.models import (
            Act,
            Appearance,
            Chapter,
            ChapterOutline,
            ChapterSummary,
            CharacterArc,
            CharacterProfile,
            CharacterSnapshot,
            ContextWindow,
            DetailEntry,
            Fact,
            Foreshadowing,
            MoodTag,
            Novel,
            Outline,
            OutlineTemplate,
            PairwiseResult,
            Personality,
            PowerLevel,
            PowerSystem,
            QualityReport,
            Relationship,
            RelationshipEvent,
            RuleCheckResult,
            Scene,
            StyleMetrics,
            TurningPoint,
            Volume,
            VolumeOutline,
            VolumeSnapshot,
            WorldSetting,
        )

        # 确认都是类
        assert all(
            isinstance(cls, type)
            for cls in [
                Novel,
                Outline,
                OutlineTemplate,
                Act,
                VolumeOutline,
                ChapterOutline,
                Volume,
                Chapter,
                Scene,
                CharacterProfile,
                Appearance,
                Personality,
                Relationship,
                RelationshipEvent,
                CharacterArc,
                TurningPoint,
                CharacterSnapshot,
                WorldSetting,
                PowerSystem,
                PowerLevel,
                Fact,
                ChapterSummary,
                VolumeSnapshot,
                ContextWindow,
                StyleMetrics,
                RuleCheckResult,
                PairwiseResult,
                QualityReport,
                Foreshadowing,
                DetailEntry,
                MoodTag,
            ]
        )
