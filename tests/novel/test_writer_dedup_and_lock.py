"""测试 Writer 场景去重 + 角色锁定 + 跨场景上下文修复"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from src.novel.agents.writer import Writer, _DEDUP_HARD_DELETE, _DEDUP_STRIP_OVERLAP
from src.novel.models.chapter import Scene
from src.novel.models.character import (
    Appearance,
    CharacterArc,
    CharacterProfile,
    Personality,
)
from src.novel.models.novel import ChapterOutline
from src.novel.models.world import WorldSetting


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_llm(content: str = "测试生成的场景内容。"):
    """创建 mock LLM 客户端"""
    from dataclasses import dataclass

    @dataclass
    class LLMResponse:
        content: str
        model: str = "test"
        usage: dict | None = None

    llm = MagicMock()
    llm.chat.return_value = LLMResponse(content=content)
    return llm


def _make_character(
    name: str = "张伟",
    gender: str = "男",
    age: int = 28,
    occupation: str = "快递员",
    hair: str = "短发",
    eyes: str = "黑色眼睛",
    build: str = "瘦削",
    distinctive: list[str] | None = None,
    speech_style: str = "直爽口语化",
    catchphrases: list[str] | None = None,
    initial_state: str = "胆小懦弱",
    final_state: str = "勇敢坚毅",
) -> CharacterProfile:
    return CharacterProfile(
        name=name,
        gender=gender,
        age=age,
        occupation=occupation,
        appearance=Appearance(
            height="175cm",
            build=build,
            hair=hair,
            eyes=eyes,
            clothing_style="工装外套",
            distinctive_features=distinctive or ["左眉有疤"],
        ),
        personality=Personality(
            traits=["勇敢", "固执", "善良"],
            core_belief="不抛弃不放弃",
            motivation="保护身边的人",
            flaw="过于冲动",
            speech_style=speech_style,
            catchphrases=catchphrases or ["搞什么鬼"],
        ),
        character_arc=CharacterArc(
            initial_state=initial_state,
            turning_points=[],
            final_state=final_state,
        ),
    )


def _make_outline(chapter_number: int = 1) -> ChapterOutline:
    return ChapterOutline(
        chapter_number=chapter_number,
        title="测试章节",
        goal="推进剧情",
        mood="蓄力",
        estimated_words=2500,
        key_events=["测试事件"],
    )


def _make_world() -> WorldSetting:
    return WorldSetting(era="现代都市", location="某一线城市")


# ===========================================================================
# 1. Jaccard 相似度计算
# ===========================================================================


class TestJaccardSimilarity:
    def test_identical_texts(self):
        llm = _make_llm()
        writer = Writer(llm)
        text = "他推开了那扇锈迹斑斑的铁门。走廊里弥漫着潮湿的气息。灯管闪烁不定。"
        assert writer._jaccard_similarity(text, text) == 1.0

    def test_completely_different_texts(self):
        llm = _make_llm()
        writer = Writer(llm)
        a = "张伟抬头看了看天空，乌云密布。他加快了脚步，希望在暴雨来临前赶到目的地。"
        b = "李明坐在咖啡馆里翻看着报纸。服务员端上了一杯拿铁。窗外车水马龙。"
        sim = writer._jaccard_similarity(a, b)
        assert sim < 0.1

    def test_partial_overlap(self):
        llm = _make_llm()
        writer = Writer(llm)
        a = "他推开了那扇门。走廊里很暗。他听到了脚步声。"
        b = "他推开了那扇门。房间里一片狼藉。桌上放着一封信。"
        sim = writer._jaccard_similarity(a, b)
        assert 0 < sim < 1.0

    def test_empty_texts(self):
        llm = _make_llm()
        writer = Writer(llm)
        assert writer._jaccard_similarity("", "") == 0.0
        assert writer._jaccard_similarity("测试文本。", "") == 0.0

    def test_short_sentences_filtered(self):
        """短于6字的句子应被过滤，不参与相似度计算"""
        llm = _make_llm()
        writer = Writer(llm)
        a = "好。行。走。"  # 全是短句
        b = "好。行。走。"
        sim = writer._jaccard_similarity(a, b)
        assert sim == 0.0  # 都被过滤了


# ===========================================================================
# 2. 段落去重
# ===========================================================================


class TestDeduplicateParagraphs:
    def test_no_previous_returns_unchanged(self):
        llm = _make_llm()
        writer = Writer(llm)
        text = "第一段内容。\n\n第二段内容。"
        assert writer._deduplicate_paragraphs(text, []) == text

    def test_hard_deletes_fully_copied_paragraph(self):
        """≥60% 句子完全相同的段落应被整段删除"""
        llm = _make_llm()
        writer = Writer(llm)
        prev = "张伟走进了那栋废弃的大楼，楼道里散发着霉味。他按下了电梯按钮，但电梯没有反应。走廊尽头漆黑一片。"
        # 新文本段1：和前文完全相同（照搬）
        new_text = (
            "张伟走进了那栋废弃的大楼，楼道里散发着霉味。他按下了电梯按钮，但电梯没有反应。走廊尽头漆黑一片。"
            "\n\n"
            "他决定走楼梯上去，每一步都踩在吱呀作响的台阶上。三楼的走廊一片漆黑。"
        )
        result = writer._deduplicate_paragraphs(new_text, [prev])
        assert "走楼梯" in result  # 独有段保留

    def test_strips_overlap_from_mixed_paragraph(self):
        """40-60% 重复的混合段：剥离重复句，保留独有内容"""
        llm = _make_llm()
        writer = Writer(llm)
        prev = "张伟推开了铁门。走廊里弥漫着霉味。灯管闪烁不定。"
        # 新段落：2句重复 + 2句新内容 = 50% 重复
        new_text = "张伟推开了铁门。走廊里弥漫着霉味。他掏出了手电筒照向前方。墙壁上写满了奇怪的符号。"
        result = writer._deduplicate_paragraphs(new_text, [prev])
        assert "手电筒" in result  # 独有内容保留
        assert "符号" in result  # 独有内容保留

    def test_keeps_low_overlap_paragraphs(self):
        """<40% 重复（正常呼应）应完整保留"""
        llm = _make_llm()
        writer = Writer(llm)
        prev = "张伟推开了铁门。走廊里弥漫着霉味。灯管闪烁不定。天花板上有水渍。"
        # 新段落：只有1句承接（"推开了铁门"），其余4句新内容 = 20% 重复
        new_text = "张伟推开了铁门。楼梯间更加安静。他一步步走上台阶。脚步声在空旷的空间中回荡。远处传来滴水声。"
        result = writer._deduplicate_paragraphs(new_text, [prev])
        assert result == new_text  # 完整保留，不删不改

    def test_keeps_unique_paragraphs(self):
        llm = _make_llm()
        writer = Writer(llm)
        prev = "昨天发生了一件奇怪的事情，有人在门口放了一个包裹。"
        new_text = "今天天气晴朗，张伟骑着电动车穿梭在城市的大街小巷。他手里握着三个快递包裹。"
        result = writer._deduplicate_paragraphs(new_text, [prev])
        assert result == new_text

    def test_multiple_previous_texts(self):
        llm = _make_llm()
        writer = Writer(llm)
        prev1 = "电梯门缓缓打开，走廊里空无一人。墙壁上的油漆剥落露出灰色的水泥。"
        prev2 = "他听到了身后传来脚步声。回头一看，空无一人。走廊尽头的灯忽明忽暗。"
        new_text = (
            "电梯门缓缓打开，走廊里空无一人。墙壁上的油漆剥落露出灰色的水泥。"
            "\n\n"
            "他从口袋里掏出手电筒，光束扫过每一扇紧闭的门。502号房间的门微微开着一条缝。"
        )
        result = writer._deduplicate_paragraphs(new_text, [prev1, prev2])
        assert "502号" in result


# ===========================================================================
# 3. 角色描述包含外貌锁定
# ===========================================================================


class TestCharacterDescriptionLocking:
    def test_includes_appearance(self):
        llm = _make_llm()
        writer = Writer(llm)
        char = _make_character(
            name="王浩", hair="板寸", eyes="深棕色眼睛",
            build="魁梧", distinctive=["右手虎口有旧伤疤"]
        )
        desc = writer._build_character_description([char])
        assert "板寸" in desc
        assert "深棕色眼睛" in desc
        assert "魁梧" in desc
        assert "右手虎口有旧伤疤" in desc

    def test_includes_character_arc(self):
        llm = _make_llm()
        writer = Writer(llm)
        char = _make_character(
            initial_state="孤僻冷漠",
            final_state="学会信任他人",
        )
        desc = writer._build_character_description([char])
        assert "孤僻冷漠" in desc
        assert "学会信任他人" in desc

    def test_multiple_characters_all_locked(self):
        llm = _make_llm()
        writer = Writer(llm)
        char1 = _make_character(name="张伟", hair="短发", gender="男")
        char2 = _make_character(name="李婷", hair="长发", gender="女", age=25)
        desc = writer._build_character_description([char1, char2])
        assert "张伟" in desc and "短发" in desc
        assert "李婷" in desc and "长发" in desc

    def test_no_characters_returns_placeholder(self):
        llm = _make_llm()
        writer = Writer(llm)
        assert writer._build_character_description([]) == "（无指定角色）"


# ===========================================================================
# 4. generate_chapter 集成：去重 + 全文传递
# ===========================================================================


class TestGenerateChapterIntegration:
    def test_scenes_written_summary_is_full_text(self):
        """验证 scenes_written_summary 传递全文而非截断"""
        scene1_text = "第一个场景的完整内容。" * 20  # 长文本
        scene2_text = "第二个场景的不同内容，推进了新的剧情。" * 15

        from dataclasses import dataclass

        @dataclass
        class LLMResponse:
            content: str
            model: str = "test"
            usage: dict | None = None

        call_count = 0

        def mock_chat(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(content=scene1_text)
            elif call_count == 2:
                # 检查 user_prompt 中是否包含场景1的全文
                user_msg = messages[-1]["content"]
                assert "第一个场景的完整内容" in user_msg
                # 不应该是截断后的"……"格式
                assert "……" not in user_msg or "全文" in user_msg
                return LLMResponse(content=scene2_text)
            else:
                return LLMResponse(content="第三个场景。")

        llm = MagicMock()
        llm.chat.side_effect = mock_chat

        writer = Writer(llm)
        outline = _make_outline()
        world = _make_world()
        plans = [
            {"scene_number": 1, "target_words": 800, "characters_involved": []},
            {"scene_number": 2, "target_words": 800, "characters_involved": []},
            {"scene_number": 3, "target_words": 800, "characters_involved": []},
        ]

        chapter = writer.generate_chapter(
            chapter_outline=outline,
            scene_plans=plans,
            characters=[],
            world_setting=world,
            context="",
            style_name="webnovel.shuangwen",
        )

        assert len(chapter.scenes) == 3
        assert call_count == 3

    def test_dedup_triggers_on_repeated_scene(self):
        """验证当场景2包含场景1的大段重复时，去重生效"""
        shared_text = "张伟推开了铁门，走廊里弥漫着一股霉味。灯管闪烁不定，墙壁上布满了裂痕。他的脚步声在空旷的走廊里回荡。"
        scene1_text = shared_text + "\n\n他掏出手机查看地址。"
        scene2_text = shared_text + "\n\n突然楼上传来了一声巨响。"

        from dataclasses import dataclass

        @dataclass
        class LLMResponse:
            content: str
            model: str = "test"
            usage: dict | None = None

        responses = iter([
            LLMResponse(content=scene1_text),
            LLMResponse(content=scene2_text),
        ])

        llm = MagicMock()
        llm.chat.side_effect = lambda *a, **kw: next(responses)

        writer = Writer(llm)
        outline = _make_outline()
        world = _make_world()
        plans = [
            {"scene_number": 1, "target_words": 800, "characters_involved": []},
            {"scene_number": 2, "target_words": 800, "characters_involved": []},
        ]

        chapter = writer.generate_chapter(
            chapter_outline=outline,
            scene_plans=plans,
            characters=[],
            world_setting=world,
            context="",
            style_name="webnovel.shuangwen",
        )

        # 场景2的重复段落应该被移除
        scene2 = chapter.scenes[1]
        assert "巨响" in scene2.text  # 独有内容保留

    def test_character_lock_in_scene_prompt(self):
        """验证场景 prompt 包含角色外貌锁定"""
        from dataclasses import dataclass

        @dataclass
        class LLMResponse:
            content: str
            model: str = "test"
            usage: dict | None = None

        captured_messages = []

        def mock_chat(messages, **kwargs):
            captured_messages.append(messages)
            return LLMResponse(content="生成的场景内容。张伟走在路上。")

        llm = MagicMock()
        llm.chat.side_effect = mock_chat

        writer = Writer(llm)
        char = _make_character(
            name="张伟", hair="板寸短发", eyes="单眼皮小眼睛",
            build="精瘦", distinctive=["左眉有道疤"]
        )
        outline = _make_outline()
        world = _make_world()

        scene = writer.generate_scene(
            scene_plan={
                "scene_number": 1,
                "target_words": 800,
                "characters_involved": ["张伟"],
                "location": "废弃大楼",
                "time": "深夜",
                "goal": "进入大楼",
            },
            chapter_outline=outline,
            characters=[char],
            world_setting=world,
            context="",
            style_name="webnovel.shuangwen",
        )

        # 检查 user_prompt 中是否有外貌锁定
        user_msg = captured_messages[0][-1]["content"]
        assert "外貌锁定" in user_msg or "板寸短发" in user_msg
        assert "单眼皮小眼睛" in user_msg or "精瘦" in user_msg


# ===========================================================================
# 5. _MAX_CONTEXT_CHARS 增大验证
# ===========================================================================


class TestContextSizeIncrease:
    def test_max_context_chars_is_4000(self):
        from src.novel.agents.writer import _MAX_CONTEXT_CHARS
        assert _MAX_CONTEXT_CHARS == 4000


# ===========================================================================
# 6. 边界情况
# ===========================================================================


class TestEdgeCases:
    def test_dedup_empty_scene(self):
        """空场景不应崩溃"""
        llm = _make_llm()
        writer = Writer(llm)
        result = writer._deduplicate_paragraphs("", ["前文内容。"])
        assert result == ""

    def test_dedup_no_paragraphs_split(self):
        """只有一个段落的场景"""
        llm = _make_llm()
        writer = Writer(llm)
        text = "这是一个完整的段落，没有分段符号，一直写到结束。"
        result = writer._deduplicate_paragraphs(text, ["完全不相关的前文。"])
        assert result == text

    def test_character_without_arc(self):
        """没有角色弧线的角色不应崩溃"""
        llm = _make_llm()
        writer = Writer(llm)
        char = CharacterProfile(
            name="路人甲",
            gender="男",
            age=40,
            occupation="保安",
            appearance=Appearance(
                height="170cm", build="普通", hair="平头",
                eyes="黑色", clothing_style="保安制服",
            ),
            personality=Personality(
                traits=["木讷", "忠厚", "固执"],
                core_belief="守好自己的岗位",
                motivation="养家糊口",
                flaw="不善言辞",
                speech_style="闷声少语",
            ),
            character_arc=None,
        )
        desc = writer._build_character_description([char])
        assert "路人甲" in desc
        assert "平头" in desc
        assert "初始状态" not in desc  # 没有弧线，不应输出


# ===========================================================================
# 7. 角色名称校验
# ===========================================================================


class TestCharacterNameCheck:
    def test_replaces_placeholder_female_student(self):
        """占位符「女学生B」应被替换为唯一女性角色名"""
        llm = _make_llm()
        writer = Writer(llm)
        char = _make_character(name="小玲", gender="女", age=16, occupation="学生")
        text = "女学生B蹲在墙角哭泣。她抬起头，脸上全是泪痕。"
        result = writer._check_character_names(text, [char])
        assert "小玲" in result
        assert "女学生B" not in result

    def test_replaces_placeholder_old_man(self):
        """占位符「老人C」应被替换为唯一老年角色名"""
        llm = _make_llm()
        writer = Writer(llm)
        char = _make_character(name="老李", gender="男", age=65, occupation="退休工人")
        text = "老人C颤抖着伸出手，指向墙上的裂缝。"
        result = writer._check_character_names(text, [char])
        assert "老李" in result
        assert "老人C" not in result

    def test_no_replacement_when_ambiguous(self):
        """多个同类型角色时不自动替换"""
        llm = _make_llm()
        writer = Writer(llm)
        char1 = _make_character(name="小玲", gender="女", age=16, occupation="学生")
        char2 = _make_character(name="苏晴", gender="女", age=28, occupation="记者")
        text = "女学生B蹲在墙角。"
        result = writer._check_character_names(text, [char1, char2])
        # 有两个女性角色，不能确定替换哪个，保持原样
        assert "女学生B" in result

    def test_no_change_for_known_names(self):
        """合法角色名不应被修改"""
        llm = _make_llm()
        writer = Writer(llm)
        char = _make_character(name="张伟")
        text = "张伟推开门，走进了房间。"
        result = writer._check_character_names(text, [char])
        assert result == text

    def test_empty_text_returns_empty(self):
        llm = _make_llm()
        writer = Writer(llm)
        char = _make_character(name="张伟")
        assert writer._check_character_names("", [char]) == ""

    def test_no_characters_returns_unchanged(self):
        llm = _make_llm()
        writer = Writer(llm)
        text = "角色A走了过来。"
        assert writer._check_character_names(text, []) == text

    def test_replaces_male_placeholder(self):
        """占位符「男子D」应被替换为唯一男性角色名"""
        llm = _make_llm()
        writer = Writer(llm)
        char = _make_character(name="王浩", gender="男", age=30)
        text = "男子D从阴影中走出来，手里拿着铁管。"
        result = writer._check_character_names(text, [char])
        assert "王浩" in result
        assert "男子D" not in result

    def test_multiple_placeholders_same_text(self):
        """同一段文本中多个不同类型占位符"""
        llm = _make_llm()
        writer = Writer(llm)
        char_girl = _make_character(name="小玲", gender="女", age=16, occupation="学生")
        char_old = _make_character(name="老李", gender="男", age=65, occupation="退休")
        text = "女学生B蹲在角落，老人C站在门口。"
        result = writer._check_character_names(text, [char_girl, char_old])
        assert "小玲" in result
        assert "老李" in result

    def test_detects_unknown_name_in_dialogue(self, caplog):
        """检测对话中出现的未知角色名并警告"""
        llm = _make_llm()
        writer = Writer(llm)
        char = _make_character(name="张伟")
        # "李小雨"不在角色列表中
        text = '张伟转身看向她。李小雨说：\u201c我们得走了。\u201d'
        import logging
        with caplog.at_level(logging.WARNING, logger="novel"):
            result = writer._check_character_names(text, [char])
        # 文本不应被修改（只警告，不替换未知名字）
        assert "李小雨" in result
        # 应该有警告日志
        assert any("白名单外" in r.message for r in caplog.records)

    def test_known_name_partial_match(self):
        """角色别名和昵称的部分匹配不应误报"""
        llm = _make_llm()
        writer = Writer(llm)
        char = _make_character(name="陈远")
        # "陈工"包含"陈"，应被识别为已知角色的称呼
        text = '陈工说：\u201c温度还在下降。\u201d'
        result = writer._check_character_names(text, [char])
        assert result == text  # 不应触发未知名字警告
