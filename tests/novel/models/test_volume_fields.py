"""Phase 1-B: Volume 一等公民字段测试。

覆盖 DESIGN.md Part 1：
- volume_goal / volume_outline / settlement / chapter_type_dist 字段存在 + 默认值
- 序列化/反序列化保留新字段
- 老数据（无新字段）能无感加载
"""

from __future__ import annotations

from src.novel.models.novel import Volume


class TestVolumeDefaults:
    def test_volume_goal_defaults_to_empty(self):
        v = Volume(volume_number=1, title="第一卷")
        assert v.volume_goal == ""

    def test_volume_outline_defaults_to_empty_list(self):
        v = Volume(volume_number=1, title="卷X")
        assert v.volume_outline == []
        assert isinstance(v.volume_outline, list)

    def test_settlement_defaults_to_none(self):
        v = Volume(volume_number=1, title="卷X")
        assert v.settlement is None

    def test_chapter_type_dist_defaults_to_empty_dict(self):
        v = Volume(volume_number=1, title="卷X")
        assert v.chapter_type_dist == {}

    def test_two_volumes_do_not_share_default_containers(self):
        """Pydantic default_factory 正确性：避免可变默认被多实例共享。"""
        v1 = Volume(volume_number=1, title="A")
        v2 = Volume(volume_number=2, title="B")
        v1.volume_outline.append(1)
        v1.chapter_type_dist["climax"] = 2
        assert v2.volume_outline == []
        assert v2.chapter_type_dist == {}


class TestVolumeAssignment:
    def test_volume_goal_assignable(self):
        v = Volume(
            volume_number=1,
            title="卷一",
            volume_goal="主角开启修炼之路",
        )
        assert v.volume_goal == "主角开启修炼之路"

    def test_volume_outline_populated(self):
        v = Volume(
            volume_number=1,
            title="卷一",
            volume_outline=[1, 2, 3, 4, 5],
        )
        assert v.volume_outline == [1, 2, 3, 4, 5]

    def test_chapter_type_dist_populated(self):
        dist = {"setup": 2, "buildup": 6, "climax": 2, "resolution": 1}
        v = Volume(
            volume_number=1,
            title="卷一",
            chapter_type_dist=dist,
        )
        assert v.chapter_type_dist == dist

    def test_settlement_is_freeform_dict(self):
        report = {
            "foreshadowings_collected": 3,
            "foreshadowings_total": 5,
            "recovery_rate": 0.6,
            "hooks_for_next": ["师门秘辛未解", "反派身份待明"],
        }
        v = Volume(
            volume_number=1,
            title="卷一",
            settlement=report,
        )
        assert v.settlement == report


class TestVolumeSerialization:
    def test_dump_roundtrip_preserves_new_fields(self):
        v = Volume(
            volume_number=2,
            title="卷二",
            chapters=[11, 12, 13],
            volume_goal="角色关系深化",
            volume_outline=[11, 12, 13],
            chapter_type_dist={"buildup": 2, "climax": 1},
            settlement={"recovery_rate": 0.8},
        )
        data = v.model_dump()
        assert data["volume_goal"] == "角色关系深化"
        assert data["volume_outline"] == [11, 12, 13]
        assert data["chapter_type_dist"] == {"buildup": 2, "climax": 1}
        assert data["settlement"] == {"recovery_rate": 0.8}

        restored = Volume(**data)
        assert restored.volume_goal == v.volume_goal
        assert restored.chapter_type_dist == v.chapter_type_dist
        assert restored.settlement == v.settlement

    def test_legacy_dict_without_new_fields_still_parses(self):
        """v2 时代的 Volume 只有 volume_number/title/chapters/status。"""
        legacy = {
            "volume_number": 1,
            "title": "旧卷",
            "chapters": [1, 2, 3],
            "status": "writing",
        }
        v = Volume(**legacy)
        assert v.volume_goal == ""
        assert v.volume_outline == []
        assert v.settlement is None
        assert v.chapter_type_dist == {}
        # 旧字段仍正确
        assert v.chapters == [1, 2, 3]
        assert v.status == "writing"
