"""Inline thinking must never leak, even when tags cross token boundaries."""

import pytest

from bisheng.common.utils.think_tags import ThinkBlockStreamFilter


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("<think>secret</think>Answer", "Answer"),
        ("Before<think>secret</think>After", "BeforeAfter"),
        ("<THINK >secret</THINK >Answer", "Answer"),
        ("<think>unfinished secret", ""),
        ("Answer<thin", "Answer"),
        ("<think>a</think>A<think>b</think>B", "AB"),
        ("Use <b>bold</b> and x < 3", "Use <b>bold</b> and x < 3"),
        ("Plain answer", "Plain answer"),
    ],
)
def test_filter_at_every_split(raw, expected):
    for split in range(len(raw) + 1):
        parser = ThinkBlockStreamFilter()
        actual = parser.feed(raw[:split]) + parser.feed(raw[split:]) + parser.flush()
        assert actual == expected
    parser = ThinkBlockStreamFilter()
    assert "".join(parser.feed(char) for char in raw) + parser.flush() == expected


def test_flush_resets_unclosed_block_for_next_model_round():
    parser = ThinkBlockStreamFilter()
    assert parser.feed("<think>secret") + parser.flush() == ""
    assert parser.feed("Next answer") + parser.flush() == "Next answer"
