"""模板层和配置的测试"""

from __future__ import annotations

import json
import textwrap

import pytest

from src.novel.config import NovelConfig, load_novel_config
from src.novel.models.chapter import MoodTag
from src.novel.models.novel import OutlineTemplate
from src.novel.templates.ai_flavor_blacklist import check_ai_flavor, get_blacklist
from src.novel.templates.outline_templates import get_template, list_templates
from src.novel.templates.rhythm_templates import get_rhythm
from src.novel.templates.style_presets import get_style, list_styles
from src.novel.utils import count_words, extract_json_from_llm, truncate_text


# ==========================================================================
# outline_templates
# ==========================================================================


class TestOutlineTemplates:
    """大纲模板测试"""

    def test_get_template_cyclic_upgrade(self) -> None:
        t = get_template("cyclic_upgrade")
        assert isinstance(t, OutlineTemplate)
        assert t.name == "cyclic_upgrade"
        assert t.act_count == 3
        assert t.default_chapters_per_volume == 30
        assert len(t.description) > 0

    def test_get_template_multi_thread(self) -> None:
        t = get_template("multi_thread")
        assert t.name == "multi_thread"
        assert t.act_count == 4
        assert t.default_chapters_per_volume == 25

    def test_get_template_classic_four_act(self) -> None:
        t = get_template("classic_four_act")
        assert t.name == "classic_four_act"
        assert t.act_count == 4
        assert t.default_chapters_per_volume == 20

    def test_get_template_unknown_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="未知模板"):
            get_template("nonexistent_template")

    def test_get_template_returns_copy(self) -> None:
        """修改返回值不应影响内部数据"""
        t1 = get_template("cyclic_upgrade")
        t1.act_count = 999
        t2 = get_template("cyclic_upgrade")
        assert t2.act_count == 3

    def test_get_template_scifi_crisis(self) -> None:
        t = get_template("scifi_crisis")
        assert t.name == "scifi_crisis"
        assert t.act_count == 4
        assert t.default_chapters_per_volume == 15

    def test_list_templates(self) -> None:
        templates = list_templates()
        assert len(templates) == 4
        names = {t.name for t in templates}
        assert names == {"cyclic_upgrade", "multi_thread", "classic_four_act", "scifi_crisis"}

    def test_list_templates_returns_copies(self) -> None:
        t_list = list_templates()
        t_list[0].act_count = 999
        t_list2 = list_templates()
        assert t_list2[0].act_count != 999


# ==========================================================================
# style_presets
# ==========================================================================


class TestStylePresets:
    """风格预设测试"""

    def test_list_styles_has_at_least_8(self) -> None:
        styles = list_styles()
        assert len(styles) >= 8

    def test_list_styles_structure(self) -> None:
        styles = list_styles()
        for s in styles:
            assert "name" in s
            assert "category" in s
            assert "subcategory" in s
            assert "display_name" in s

    def test_get_style_returns_all_fields(self) -> None:
        style = get_style("wuxia.classical")
        assert "system_prompt" in style
        assert "few_shot_examples" in style
        assert "constraints" in style
        assert len(style["system_prompt"]) > 20
        assert len(style["few_shot_examples"]) >= 1

    def test_get_style_unknown_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="未知风格"):
            get_style("nonexistent.style")

    def test_get_style_returns_deep_copy(self) -> None:
        s1 = get_style("webnovel.shuangwen")
        s1["system_prompt"] = "modified"
        s2 = get_style("webnovel.shuangwen")
        assert s2["system_prompt"] != "modified"

    @pytest.mark.parametrize(
        "style_name",
        [
            "wuxia.classical",
            "wuxia.modern",
            "webnovel.shuangwen",
            "webnovel.xuanhuan",
            "webnovel.romance",
            "literary.realism",
            "literary.lyrical",
            "scifi.hardscifi",
            "light_novel.campus",
            "light_novel.fantasy",
        ],
    )
    def test_all_styles_have_chinese_examples(self, style_name: str) -> None:
        style = get_style(style_name)
        for example in style["few_shot_examples"]:
            # 确保示例包含中文
            assert any("\u4e00" <= ch <= "\u9fff" for ch in example), (
                f"风格 {style_name} 的示例不包含中文"
            )

    def test_styles_have_distinct_prompts(self) -> None:
        """各风格的 system_prompt 应当不同"""
        styles = list_styles()
        prompts = set()
        for s in styles:
            full = get_style(s["name"])
            prompts.add(full["system_prompt"])
        assert len(prompts) == len(styles)

    def test_constraints_have_valid_ranges(self) -> None:
        """约束的范围值 [min, max] 中 min <= max"""
        styles = list_styles()
        for s in styles:
            full = get_style(s["name"])
            for key, val in full["constraints"].items():
                if isinstance(val, list) and len(val) == 2:
                    assert val[0] <= val[1], (
                        f"{s['name']}.constraints.{key}: {val[0]} > {val[1]}"
                    )


# ==========================================================================
# rhythm_templates
# ==========================================================================


class TestRhythmTemplates:
    """节奏模板测试"""

    def test_get_rhythm_exact_length(self) -> None:
        """模板长度 == volume_length 时直接返回"""
        rhythm = get_rhythm("玄幻", 10)
        assert len(rhythm) == 10
        assert all(isinstance(m, MoodTag) for m in rhythm)

    def test_get_rhythm_shorter(self) -> None:
        """volume_length < 模板长度时采样"""
        rhythm = get_rhythm("玄幻", 5)
        assert len(rhythm) == 5
        assert all(isinstance(m, MoodTag) for m in rhythm)

    def test_get_rhythm_longer(self) -> None:
        """volume_length > 模板长度时拉伸"""
        rhythm = get_rhythm("玄幻", 30)
        assert len(rhythm) == 30
        assert all(isinstance(m, MoodTag) for m in rhythm)

    def test_get_rhythm_single_chapter(self) -> None:
        rhythm = get_rhythm("玄幻", 1)
        assert len(rhythm) == 1
        assert isinstance(rhythm[0], MoodTag)

    def test_get_rhythm_invalid_length(self) -> None:
        with pytest.raises(ValueError, match="volume_length 必须 >= 1"):
            get_rhythm("玄幻", 0)
        with pytest.raises(ValueError, match="volume_length 必须 >= 1"):
            get_rhythm("玄幻", -5)

    def test_get_rhythm_unknown_genre_uses_default(self) -> None:
        """未知题材应使用默认节奏模式"""
        rhythm = get_rhythm("未知题材XYZ", 10)
        assert len(rhythm) == 10
        assert all(isinstance(m, MoodTag) for m in rhythm)

    @pytest.mark.parametrize("genre", ["玄幻", "都市", "言情", "悬疑", "仙侠"])
    def test_most_genres_end_with_big_win(self, genre: str) -> None:
        """多数题材的节奏模板最后一个节点应是大爽"""
        rhythm = get_rhythm(genre, 10)
        assert rhythm[-1] == MoodTag.BIG_WIN

    def test_scifi_ends_with_twist(self) -> None:
        """科幻以反转收尾，留下开放式结局"""
        rhythm = get_rhythm("科幻", 10)
        assert rhythm[-1] == MoodTag.TWIST

    def test_wuxia_ends_with_transition(self) -> None:
        """武侠以过渡（余韵）收尾，符合侠义风格"""
        rhythm = get_rhythm("武侠", 10)
        assert rhythm[-1] == MoodTag.TRANSITION

    def test_rhythm_preserves_first_and_last_on_shrink(self) -> None:
        """缩短时应保留首尾"""
        rhythm_full = get_rhythm("玄幻", 10)
        rhythm_short = get_rhythm("玄幻", 3)
        assert rhythm_short[0] == rhythm_full[0]
        assert rhythm_short[-1] == rhythm_full[-1]


# ==========================================================================
# ai_flavor_blacklist
# ==========================================================================


class TestAIFlavorBlacklist:
    """AI 味短语黑名单测试"""

    def test_get_blacklist_has_at_least_50(self) -> None:
        bl = get_blacklist()
        assert len(bl) >= 50

    def test_get_blacklist_all_chinese(self) -> None:
        """所有短语应包含中文"""
        bl = get_blacklist()
        for phrase in bl:
            assert any("\u4e00" <= ch <= "\u9fff" for ch in phrase), (
                f"短语 '{phrase}' 不包含中文"
            )

    def test_get_blacklist_no_duplicates(self) -> None:
        bl = get_blacklist()
        assert len(bl) == len(set(bl))

    def test_check_ai_flavor_hits(self) -> None:
        text = "他心中涌起一股暖流，嘴角勾起一抹微笑，仿佛时间在这一刻静止了。"
        hits = check_ai_flavor(text)
        assert len(hits) >= 2
        # 确认返回的是 (短语, 位置) 格式
        for phrase, pos in hits:
            assert isinstance(phrase, str)
            assert isinstance(pos, int)
            assert text[pos : pos + len(phrase)] == phrase

    def test_check_ai_flavor_no_hits(self) -> None:
        text = "老王蹲在门口抽旱烟，看着远处的麦田发愣。"
        hits = check_ai_flavor(text)
        assert hits == []

    def test_check_ai_flavor_empty_text(self) -> None:
        assert check_ai_flavor("") == []

    def test_check_ai_flavor_sorted_by_position(self) -> None:
        text = "命运的齿轮开始转动，他眼神一凛，内心翻涌。"
        hits = check_ai_flavor(text)
        positions = [pos for _, pos in hits]
        assert positions == sorted(positions)


# ==========================================================================
# config
# ==========================================================================


class TestNovelConfig:
    """小说模块配置测试"""

    def test_default_config(self) -> None:
        cfg = NovelConfig()
        assert cfg.default_genre == "都市"
        assert cfg.default_target_words == 100000
        assert cfg.default_template == "cyclic_upgrade"

    def test_default_style_config(self) -> None:
        cfg = NovelConfig()
        assert cfg.style.default_category == "网文"
        assert cfg.style.default_subcategory == "爽文"
        assert "网文" in cfg.style.constraints

    def test_default_generation_config(self) -> None:
        cfg = NovelConfig()
        assert cfg.generation.scene_per_chapter == 3
        assert cfg.generation.words_per_scene == [400, 800]
        assert cfg.generation.words_per_chapter == [2000, 3000]

    def test_default_quality_config(self) -> None:
        cfg = NovelConfig()
        assert cfg.quality.max_retries == 2
        assert cfg.quality.auto_approve_threshold == 6.0
        assert "内心翻涌" in cfg.quality.ai_flavor_blacklist

    def test_load_from_dict(self) -> None:
        data = {
            "default_genre": "玄幻",
            "default_target_words": 200000,
            "style": {"default_category": "武侠"},
        }
        cfg = load_novel_config(config_dict=data)
        assert cfg.default_genre == "玄幻"
        assert cfg.default_target_words == 200000
        assert cfg.style.default_category == "武侠"
        # 其他字段保持默认
        assert cfg.style.default_subcategory == "爽文"

    def test_load_from_dict_empty(self) -> None:
        cfg = load_novel_config(config_dict={})
        assert cfg.default_genre == "都市"

    def test_load_from_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_novel_config(config_path="/nonexistent/path.yaml")

    def test_load_no_args_returns_defaults(self) -> None:
        cfg = load_novel_config()
        assert isinstance(cfg, NovelConfig)

    def test_load_from_yaml_file(self, tmp_path: object) -> None:
        """从 YAML 文件加载配置"""
        from pathlib import Path

        p = Path(str(tmp_path)) / "test_config.yaml"
        p.write_text(
            textwrap.dedent("""\
                novel:
                  default_genre: "科幻"
                  default_target_words: 50000
                  quality:
                    max_retries: 5
            """),
            encoding="utf-8",
        )
        cfg = load_novel_config(config_path=p)
        assert cfg.default_genre == "科幻"
        assert cfg.default_target_words == 50000
        assert cfg.quality.max_retries == 5
        # 未指定的保持默认
        assert cfg.default_template == "cyclic_upgrade"

    def test_load_from_yaml_without_novel_section(self, tmp_path: object) -> None:
        """YAML 文件中没有 novel 段时使用全部默认值"""
        from pathlib import Path

        p = Path(str(tmp_path)) / "test_config.yaml"
        p.write_text("other_section:\n  key: value\n", encoding="utf-8")
        cfg = load_novel_config(config_path=p)
        assert cfg.default_genre == "都市"

    def test_import_settings_alias(self) -> None:
        """import 是 Python 关键字，通过 alias 支持"""
        data = {
            "import": {
                "auto_split_chapters": False,
                "chapter_markers": ["卷"],
            }
        }
        cfg = load_novel_config(config_dict=data)
        assert cfg.import_settings.auto_split_chapters is False
        assert cfg.import_settings.chapter_markers == ["卷"]

    def test_config_validation_rejects_bad_values(self) -> None:
        with pytest.raises(Exception):
            NovelConfig(default_target_words=-100)  # type: ignore[arg-type]


# ==========================================================================
# utils
# ==========================================================================


class TestCountWords:
    """字数统计测试"""

    def test_pure_chinese(self) -> None:
        assert count_words("你好世界") == 4

    def test_chinese_with_punctuation(self) -> None:
        # 标点不计入
        assert count_words("你好，世界！") == 4

    def test_english_words(self) -> None:
        assert count_words("hello world") == 2

    def test_mixed(self) -> None:
        # 你好(2 chinese) + 测试(2 chinese) = 4 chinese
        # After removing chinese: " world， 123test" -> words: world, 123, test = 3
        # Total = 4 + 3 = 7
        assert count_words("你好world，测试123test") == 7

    def test_mixed_precise(self) -> None:
        # 你(1) + 好(1) + 世(1) + 界(1) = 4 chinese chars
        # No english/numbers
        assert count_words("你好世界") == 4

        # "Hello 世界 123" -> 世界 = 2 chinese, Hello = 1 word, 123 = 1 number
        assert count_words("Hello 世界 123") == 4

    def test_empty(self) -> None:
        assert count_words("") == 0

    def test_only_punctuation(self) -> None:
        assert count_words("，。！？、；：""''") == 0

    def test_numbers(self) -> None:
        assert count_words("2024年3月") == 4  # 2024(1) + 年(1) + 3(1) + 月(1)


class TestTruncateText:
    """文本截断测试"""

    def test_short_text_no_truncation(self) -> None:
        text = "你好世界"
        assert truncate_text(text, 10) == text

    def test_truncate_at_sentence_boundary(self) -> None:
        text = "第一句话。第二句话。第三句话。"
        result = truncate_text(text, 12)
        assert result.endswith("。")
        assert len(result) <= 12

    def test_truncate_hard_cutoff(self) -> None:
        text = "这是一段没有句号的很长很长的文本内容"
        result = truncate_text(text, 5)
        assert len(result) <= 8  # 5 + "..."

    def test_truncate_empty(self) -> None:
        assert truncate_text("", 10) == ""

    def test_truncate_zero_max(self) -> None:
        assert truncate_text("你好", 0) == ""

    def test_truncate_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="max_chars 必须 >= 0"):
            truncate_text("你好", -1)

    def test_exact_length_no_truncation(self) -> None:
        text = "你好"
        assert truncate_text(text, 2) == text


class TestExtractJsonFromLLM:
    """LLM JSON 提取测试"""

    def test_pure_json(self) -> None:
        response = '{"key": "value", "number": 42}'
        result = extract_json_from_llm(response)
        assert result == {"key": "value", "number": 42}

    def test_markdown_code_block(self) -> None:
        response = '这是分析结果：\n```json\n{"key": "value"}\n```\n以上。'
        result = extract_json_from_llm(response)
        assert result == {"key": "value"}

    def test_markdown_code_block_no_lang(self) -> None:
        response = '```\n{"key": "value"}\n```'
        result = extract_json_from_llm(response)
        assert result == {"key": "value"}

    def test_json_with_surrounding_text(self) -> None:
        response = '分析如下：{"result": "ok", "score": 8.5} 分析完毕。'
        result = extract_json_from_llm(response)
        assert result == {"result": "ok", "score": 8.5}

    def test_empty_response_raises(self) -> None:
        with pytest.raises(ValueError, match="空响应"):
            extract_json_from_llm("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="空响应"):
            extract_json_from_llm("   \n  ")

    def test_no_json_raises(self) -> None:
        with pytest.raises(ValueError, match="无法从响应中提取"):
            extract_json_from_llm("这里没有任何 JSON 内容")

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(ValueError, match="无法从响应中提取"):
            extract_json_from_llm("{invalid json content}")

    def test_nested_json(self) -> None:
        data = {"outer": {"inner": [1, 2, 3]}, "flag": True}
        response = f"结果：{json.dumps(data, ensure_ascii=False)}"
        result = extract_json_from_llm(response)
        assert result == data

    def test_json_with_chinese(self) -> None:
        response = '```json\n{"标题": "测试小说", "字数": 10000}\n```'
        result = extract_json_from_llm(response)
        assert result["标题"] == "测试小说"
        assert result["字数"] == 10000


# ==========================================================================
# templates __init__ 导出测试
# ==========================================================================


class TestTemplatesInit:
    """测试 templates 包的统一导出"""

    def test_imports(self) -> None:
        from src.novel.templates import (
            check_ai_flavor,
            get_blacklist,
            get_rhythm,
            get_style,
            get_template,
            list_styles,
            list_templates,
        )

        assert callable(get_template)
        assert callable(list_templates)
        assert callable(get_style)
        assert callable(list_styles)
        assert callable(get_rhythm)
        assert callable(get_blacklist)
        assert callable(check_ai_flavor)
