"""测试 Writer._check_character_names 的层 2（未知人名检测）代词前缀剥离修复。

背景：原正则会把 `他低头看向地面` 里的 `他低头`（3 字）误判为未知角色名，
原因是 `_NOT_NAMES` 只列了单字代词 `他/她/它/我/你`，3 字候选漏网。
修复方案：候选以单字代词开头时，整体视为"代词+动词"短语，直接跳过。

本测试不 mock LLM —— `_check_character_names` 是 staticmethod，纯文本处理。
用 caplog 抓 `logging.getLogger("novel")` 的 warning 日志来断言 unknown_names 集合。
"""

from __future__ import annotations

import logging
import re

import pytest

from src.novel.agents.writer import Writer
from src.novel.models.character import (
    Appearance,
    CharacterProfile,
    Personality,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_character(
    name: str, gender: str = "男", *, alias: list[str] | None = None
) -> CharacterProfile:
    """构造最小可用 CharacterProfile。字段全部用默认/伪值，仅 name/gender/alias 语义相关。"""
    return CharacterProfile(
        name=name,
        alias=alias or [],
        gender=gender,  # type: ignore[arg-type]
        age=22,
        occupation="剑客",
        appearance=Appearance(
            height="175cm",
            build="匀称",
            hair="黑色短发",
            eyes="黑眸",
            clothing_style="常服",
        ),
        personality=Personality(
            traits=["冷静", "果敢", "隐忍"],
            core_belief="实力为尊",
            motivation="修炼",
            flaw="自负",
            speech_style="简短",
        ),
    )


# 匹配层 2 警告日志的正则：消息里带 "白名单外的角色名 {...}"
_UNKNOWN_WARN_RE = re.compile(r"白名单外的角色名")


def _extract_unknown_names(caplog) -> set[str]:
    """从 caplog records 里解析出层 2 reported 的 unknown_names 集合。

    层 2 用 `log.warning("角色名校验：检测到白名单外的角色名 %s（合法名单：%s）", unknown_names, known_names)`，
    record.args[0] 即 unknown_names（set）。若没有此类 warning，返回空集合。
    """
    for rec in caplog.records:
        if rec.levelno != logging.WARNING:
            continue
        if "白名单外的角色名" not in rec.getMessage():
            continue
        if rec.args and isinstance(rec.args[0], set):
            return rec.args[0]
    return set()


def _has_unknown_warning(caplog) -> bool:
    return any(
        rec.levelno == logging.WARNING
        and "白名单外的角色名" in rec.getMessage()
        for rec in caplog.records
    )


@pytest.fixture(autouse=True)
def _capture_novel_logger(caplog):
    """确保捕获 logging.getLogger('novel') 的 warning 级别。"""
    caplog.set_level(logging.WARNING, logger="novel")
    yield


# ---------------------------------------------------------------------------
# 正常（真人名）场景 —— 不应误报
# ---------------------------------------------------------------------------


class TestRealNamesNotFlagged:
    def test_known_name_with_action_verb(self, caplog):
        """林炎低头看向地面：林炎在白名单，含部分匹配，不应误报。"""
        text = "林炎低头看向地面，一声不吭。"
        chars = [_make_character("林炎")]
        result = Writer._check_character_names(text, chars)
        assert result == text  # 层 2 不改文本
        assert not _has_unknown_warning(caplog), (
            f"不应产生 unknown warning，但抓到: "
            f"{[r.getMessage() for r in caplog.records]}"
        )

    def test_known_name_with_bare_verb(self, caplog):
        """林炎走：纯"名+单字动词"，回溯后应命中已知名。"""
        text = "林炎走进院子。"
        chars = [_make_character("林炎")]
        Writer._check_character_names(text, chars)
        assert _extract_unknown_names(caplog) == set()


# ---------------------------------------------------------------------------
# 代词前缀场景 —— 核心修复点
# ---------------------------------------------------------------------------


class TestPronounPrefixStripped:
    def test_pronoun_ta_plus_low_head_action(self, caplog):
        """他低头看了看：原 bug 的核心 case，不应再报 {'他低头'}。"""
        text = "他低头看了看脚下的泥土。"
        chars = [_make_character("林炎")]
        Writer._check_character_names(text, chars)
        assert _extract_unknown_names(caplog) == set()
        assert not _has_unknown_warning(caplog)

    def test_pronoun_she_raise_head(self, caplog):
        """她抬头望天：regex 只匹配到单字 '她'，在 _NOT_NAMES 里已被拦，依旧无警告。"""
        text = "她抬头望天。"
        chars = [_make_character("楚云霄")]
        Writer._check_character_names(text, chars)
        assert _extract_unknown_names(caplog) == set()

    def test_pronoun_wo_walk(self, caplog):
        """我走向门口：单字 '我' 在 _NOT_NAMES，不报警。"""
        text = "我走向门口。"
        chars = [_make_character("林炎")]
        Writer._check_character_names(text, chars)
        assert _extract_unknown_names(caplog) == set()

    def test_pronoun_ta_cold_laugh(self, caplog):
        """他冷笑：regex 会回溯到 '他冷' 这种半截候选，也要被代词剥离规则拦下。"""
        text = "他冷笑一声，转身离开。"
        chars = [_make_character("林炎")]
        Writer._check_character_names(text, chars)
        assert _extract_unknown_names(caplog) == set()

    def test_pronoun_it_stand(self, caplog):
        """它站起来：它也是代词前缀。"""
        text = "它站起来，发出低吼。"
        chars = [_make_character("林炎")]
        Writer._check_character_names(text, chars)
        assert _extract_unknown_names(caplog) == set()


# ---------------------------------------------------------------------------
# 真正的未知人名 —— 仍然要被捕获
# ---------------------------------------------------------------------------


class TestGenuinelyUnknownNamesStillCaught:
    def test_unknown_surname_plus_verb(self, caplog):
        """张三走了 + 白名单不含张三 → 应报 {'张三'}。"""
        text = "张三走了，没回头。"
        chars = [_make_character("林炎")]
        Writer._check_character_names(text, chars)
        assert _extract_unknown_names(caplog) == {"张三"}

    def test_mixed_pronoun_and_unknown(self, caplog):
        """混合场景：真·未知名仍报，代词短语不报。

        注：用句号 '。' 作为分隔符以满足正则的 boundary 要求
        （源正则的 boundary 类 `[。！？!?\\n""\\s]` 不含中文逗号 `，`）。
        """
        text = "林炎走过去。他低头看了看。张三站在旁边。"
        chars = [_make_character("林炎")]
        Writer._check_character_names(text, chars)
        # 林炎在白名单；他低头被代词前缀拦；张三才是真正的未知名
        assert _extract_unknown_names(caplog) == {"张三"}


# ---------------------------------------------------------------------------
# 边界场景 —— 不应崩溃
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_text(self, caplog):
        result = Writer._check_character_names("", [_make_character("林炎")])
        assert result == ""
        assert not _has_unknown_warning(caplog)

    def test_empty_characters(self, caplog):
        """characters 为空时直接短路，返回原文。"""
        text = "某人走向另一个人。"
        result = Writer._check_character_names(text, [])
        assert result == text
        assert not _has_unknown_warning(caplog)

    def test_no_matches_at_all(self, caplog):
        """没有动作动词触发 regex，自然也不会报警。"""
        text = "清晨的阳光洒在石板路上，万籁俱寂。"
        Writer._check_character_names(text, [_make_character("林炎")])
        assert _extract_unknown_names(caplog) == set()

    def test_punctuation_stripped_from_candidate(self, caplog):
        """候选前后若含引号字符，strip 后仍应正常处理。"""
        # 这里构造一个以句号开头 + 名 + 动作的场景，确保 boundary 命中
        text = "林炎看向远方。"
        chars = [_make_character("林炎")]
        Writer._check_character_names(text, chars)
        assert _extract_unknown_names(caplog) == set()

    def test_curly_quote_prefix_stripped(self, caplog):
        """Unicode curly quote prefix (U+201D) should be stripped.

        Root cause of chapter_002.txt noise: regex name class did not exclude
        U+201C/U+201D; original strip() only had ASCII quotes, could not remove
        Unicode curly quotes.

        This test uses '走' (in action list) to ensure regex truly captures the candidate.
        """
        # Newline as boundary; right curly quote + 他走 -> regex captures U+201D他 + 走
        text = '林炎抬头。\n\u201d他走了。'  # \u201d = right curly double quote
        chars = [_make_character("林炎")]
        Writer._check_character_names(text, chars)
        # After stripping curly quote, '他' is only 1 char, filtered by len<2; no noise
        assert _extract_unknown_names(caplog) == set()


# ---------------------------------------------------------------------------
# 层 1（占位符）回归 —— 修复不能破坏既有行为
# ---------------------------------------------------------------------------


class TestPlaceholderLayerStillWorks:
    def test_placeholder_replaced_when_unique_match(self, caplog):
        """女学生A说"..."，只有一个女性角色时应被替换为该角色名。"""
        text = '女学生A说"你好"。'
        chars = [
            _make_character("林炎", gender="男"),
            _make_character("楚青禾", gender="女"),
        ]
        result = Writer._check_character_names(text, chars)
        # 占位符被替换为唯一女性角色
        assert "女学生A" not in result
        assert "楚青禾" in result
        # 替换后再走层 2，楚青禾已知，不应报未知
        assert _extract_unknown_names(caplog) == set()
        # 但占位符 warning 必须保留（下游可能有依赖）
        placeholder_warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "占位符称呼" in r.getMessage()
        ]
        assert len(placeholder_warnings) >= 1

    def test_placeholder_warning_fires_when_no_match(self, caplog):
        """没有性别匹配的角色时，占位符 warning 照旧记录，不做替换。"""
        text = '女学生A说"你好"。'
        chars = [_make_character("林炎", gender="男")]
        result = Writer._check_character_names(text, chars)
        # 无女性角色可替换，原文保留
        assert "女学生A" in result
        placeholder_warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "占位符称呼" in r.getMessage()
        ]
        assert len(placeholder_warnings) == 1
