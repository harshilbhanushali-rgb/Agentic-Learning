"""`parse_json_reply` -- the two formatting slips the writer made on the golden set (2026-11-06)."""
import json

import pytest

from shared.gateway import parse_json_reply


def test_valid_json_parses_exactly_as_json_loads_does():
    content = '{"declined": false, "answer": "Line one.\\nLine two.", "quote": "x"}'
    assert parse_json_reply(content) == json.loads(content)


def test_raw_newline_inside_a_string_is_accepted():
    # "Invalid control character at: line 3 column 171" -- a literal newline in the answer.
    content = '{\n  "declined": false,\n  "answer": "First paragraph.\nSecond paragraph."\n}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(content)
    assert parse_json_reply(content)["answer"] == "First paragraph.\nSecond paragraph."


def test_text_after_a_complete_object_is_ignored():
    # "Extra data: line 15 column 2" -- the object closed, then the model kept going.
    content = '{"declined": false, "answer": "Full answer."}\n}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(content)
    assert parse_json_reply(content) == {"declined": False, "answer": "Full answer."}


def test_both_slips_together():
    content = '{"answer": "a\nb"}\n```'
    assert parse_json_reply(content) == {"answer": "a\nb"}


@pytest.mark.parametrize("content", ["not json at all", "Sure! Here is the answer: ...", '{"answer": "cut off'])
def test_something_that_is_not_json_still_raises(content):
    with pytest.raises(json.JSONDecodeError):
        parse_json_reply(content)
