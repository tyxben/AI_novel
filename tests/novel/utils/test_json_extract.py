"""Unit tests for src.novel.utils.json_extract.

Covers both happy paths and edge/error cases:

- direct parse / markdown code block / embedded in prose
- None / empty / garbage / malformed inputs
- nested objects, unicode, escape sequences
- extract_json_array unwrap_keys behaviour (default and custom)
"""

from __future__ import annotations

import pytest

from src.novel.utils.json_extract import extract_json_array, extract_json_obj


# ---------------------------------------------------------------------------
# extract_json_obj
# ---------------------------------------------------------------------------


class TestExtractJsonObjHappyPath:
    def test_direct_object(self):
        assert extract_json_obj('{"a": 1}') == {"a": 1}

    def test_nested_object(self):
        text = '{"outer": {"inner": [1, 2, 3]}, "flag": true}'
        assert extract_json_obj(text) == {
            "outer": {"inner": [1, 2, 3]},
            "flag": True,
        }

    def test_unicode_content(self):
        result = extract_json_obj('{"name": "陈风", "desc": "少年修仙者"}')
        assert result == {"name": "陈风", "desc": "少年修仙者"}

    def test_escape_sequences(self):
        result = extract_json_obj('{"line": "a\\nb", "tab": "x\\ty"}')
        assert result == {"line": "a\nb", "tab": "x\ty"}

    def test_with_surrounding_text(self):
        text = 'Here is the result: {"key": "value"} done.'
        assert extract_json_obj(text) == {"key": "value"}

    def test_markdown_code_block_with_lang(self):
        text = '```json\n{"a": 1, "b": 2}\n```'
        assert extract_json_obj(text) == {"a": 1, "b": 2}

    def test_markdown_code_block_no_lang(self):
        text = '```\n{"a": 1}\n```'
        assert extract_json_obj(text) == {"a": 1}

    def test_markdown_code_block_with_prose_around(self):
        text = 'Here you go:\n```json\n{"status": "ok"}\n```\nAll done.'
        assert extract_json_obj(text) == {"status": "ok"}

    def test_surrounding_whitespace_and_newlines(self):
        assert extract_json_obj('\n\n  {"x": 1}  \n') == {"x": 1}


class TestExtractJsonObjEdgeCases:
    def test_none_input(self):
        assert extract_json_obj(None) is None

    def test_empty_string(self):
        assert extract_json_obj("") is None

    def test_whitespace_only(self):
        assert extract_json_obj("   \n\t  ") is None

    def test_garbage_text(self):
        assert extract_json_obj("this is not json at all") is None

    def test_unclosed_brace(self):
        # A lone { with no closing brace is invalid; must return None.
        assert extract_json_obj('{"a": 1') is None

    def test_top_level_array_returns_none(self):
        # extract_json_obj should reject arrays at the top level
        assert extract_json_obj("[1, 2, 3]") is None

    def test_top_level_scalar_returns_none(self):
        assert extract_json_obj("42") is None
        assert extract_json_obj('"hello"') is None
        assert extract_json_obj("true") is None

    def test_non_string_input(self):
        # Defensive: non-str input must not raise
        assert extract_json_obj(123) is None  # type: ignore[arg-type]
        assert extract_json_obj(["a", "b"]) is None  # type: ignore[arg-type]

    def test_prose_no_braces(self):
        assert extract_json_obj("no braces here") is None

    def test_malformed_braces_only(self):
        # Has { and } but malformed body — should still return None
        assert extract_json_obj("{{not json}}") is None


# ---------------------------------------------------------------------------
# extract_json_array
# ---------------------------------------------------------------------------


class TestExtractJsonArrayHappyPath:
    def test_direct_array(self):
        assert extract_json_array('[1, 2, 3]') == [1, 2, 3]

    def test_array_of_objects(self):
        text = '[{"name": "a"}, {"name": "b"}]'
        assert extract_json_array(text) == [{"name": "a"}, {"name": "b"}]

    def test_empty_array(self):
        assert extract_json_array("[]") == []

    def test_with_surrounding_text(self):
        text = 'Result: [{"name": "a"}] end.'
        assert extract_json_array(text) == [{"name": "a"}]

    def test_markdown_code_block(self):
        text = '```json\n[1, 2, 3]\n```'
        assert extract_json_array(text) == [1, 2, 3]

    def test_markdown_code_block_with_wrapper(self):
        text = '```json\n{"items": [1, 2]}\n```'
        assert extract_json_array(text) == [1, 2]

    def test_unicode_content(self):
        assert extract_json_array('["陈风", "林远"]') == ["陈风", "林远"]


class TestExtractJsonArrayUnwrapKeys:
    def test_default_unwrap_items(self):
        assert extract_json_array('{"items": [1, 2]}') == [1, 2]

    def test_default_unwrap_list(self):
        assert extract_json_array('{"list": ["a"]}') == ["a"]

    def test_default_unwrap_results(self):
        assert extract_json_array('{"results": [{"r": 1}]}') == [{"r": 1}]

    def test_default_unwrap_data(self):
        assert extract_json_array('{"data": [42]}') == [42]

    def test_default_unwrap_details(self):
        assert extract_json_array('{"details": [{"a": 1}]}') == [{"a": 1}]

    def test_default_unwrap_entries(self):
        assert extract_json_array('{"entries": [{"k": "v"}]}') == [{"k": "v"}]

    def test_default_unwrap_characters(self):
        text = '{"characters": [{"name": "a"}]}'
        assert extract_json_array(text) == [{"name": "a"}]

    def test_default_unwrap_foreshadowings(self):
        text = '{"foreshadowings": [{"title": "x"}]}'
        assert extract_json_array(text) == [{"title": "x"}]

    def test_default_unwrap_facts(self):
        text = '{"facts": [{"type": "time"}]}'
        assert extract_json_array(text) == [{"type": "time"}]

    def test_unknown_key_returns_none(self):
        # dict without any known unwrap key
        assert extract_json_array('{"unknown": [1, 2]}') is None

    def test_custom_unwrap_keys(self):
        assert extract_json_array(
            '{"my_key": [1, 2]}',
            unwrap_keys=["my_key"],
        ) == [1, 2]

    def test_custom_unwrap_keys_priority(self):
        # First matching key wins
        text = '{"b": [2], "a": [1]}'
        assert extract_json_array(text, unwrap_keys=["a", "b"]) == [1]
        assert extract_json_array(text, unwrap_keys=["b", "a"]) == [2]

    def test_custom_unwrap_keys_skip_default(self):
        # If a custom list is provided, defaults should NOT be used
        assert extract_json_array(
            '{"items": [1]}',
            unwrap_keys=["characters"],
        ) is None

    def test_empty_unwrap_keys_skips_dicts(self):
        # Explicit empty iterable disables all unwrapping
        assert extract_json_array('{"items": [1]}', unwrap_keys=[]) is None

    def test_unwrap_ignores_non_list_value(self):
        # items is a dict, not a list -> should fall through to None
        assert extract_json_array('{"items": {"x": 1}}') is None


class TestExtractJsonArrayEdgeCases:
    def test_none_input(self):
        assert extract_json_array(None) is None

    def test_empty_string(self):
        assert extract_json_array("") is None

    def test_whitespace_only(self):
        assert extract_json_array("   \n\t  ") is None

    def test_garbage_text(self):
        assert extract_json_array("not json at all") is None

    def test_unclosed_bracket(self):
        assert extract_json_array('[1, 2') is None

    def test_top_level_scalar(self):
        assert extract_json_array("42") is None
        assert extract_json_array('"x"') is None

    def test_non_string_input(self):
        assert extract_json_array(123) is None  # type: ignore[arg-type]
        assert extract_json_array({"a": 1}) is None  # type: ignore[arg-type]

    def test_array_with_trailing_comma_invalid(self):
        # JSON does not allow trailing commas; parser must reject.
        assert extract_json_array("[1, 2, 3,]") is None

    def test_array_embedded_in_prose(self):
        assert extract_json_array('Here are details:\n[{"a": 1}]\nDone.') == [
            {"a": 1}
        ]

    def test_nested_arrays(self):
        assert extract_json_array("[[1, 2], [3, 4]]") == [[1, 2], [3, 4]]

    def test_prefers_direct_array_over_wrapper_unwrap(self):
        # If top level parses as list, we return it directly and ignore any
        # wrapper keys inside.
        text = '[{"items": "nested"}]'
        assert extract_json_array(text) == [{"items": "nested"}]


# ---------------------------------------------------------------------------
# Cross-function regression: behaviour parity with historical implementations
# ---------------------------------------------------------------------------


class TestHistoricalBehaviourParity:
    """Ensure the unified API covers every caller pattern found in novel/."""

    def test_character_service_pattern(self):
        # character_service.py: '{"characters": [...]}'
        text = '{"characters": [{"name": "陈风", "role": "主角"}]}'
        assert extract_json_array(text) == [
            {"name": "陈风", "role": "主角"}
        ]

    def test_consistency_service_facts_pattern(self):
        # consistency_service.py: '{"facts": [...]}'
        text = '{"facts": [{"type": "time", "value": "晚上"}]}'
        assert extract_json_array(text) == [
            {"type": "time", "value": "晚上"}
        ]

    def test_foreshadowing_service_details_pattern(self):
        # foreshadowing_service.py: '{"details": [...]}' / '{"items": [...]}'
        assert extract_json_array('{"details": [{"a": 1}]}') == [{"a": 1}]
        assert extract_json_array('{"items": [{"x": 2}]}') == [{"x": 2}]
        assert extract_json_array('{"results": [{"r": 1}]}') == [{"r": 1}]

    def test_dual_extraction_same_response(self):
        # Some callers apply both obj and array extraction to the same response.
        text = '{"characters": [{"name": "a"}]}'
        obj = extract_json_obj(text)
        assert obj == {"characters": [{"name": "a"}]}
        arr = extract_json_array(text)
        assert arr == [{"name": "a"}]
