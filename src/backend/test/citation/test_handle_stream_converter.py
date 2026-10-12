"""F075 — streaming conversion of ``[Sn]`` handles in the daily chat.

The daily chat shows badges while the answer streams, so handles have to be
turned into private-use markers before each delta is sent. The converter holds
back only what could still change meaning. The central promise, pinned by the
chunking tests below: however the model's text is split into deltas, the
concatenated output equals converting the whole text at once.

AC-05, AC-07, AC-08, AC-09, AC-10.
"""

import random

import pytest

from bisheng.citation.domain.services.citation_handle_service import convert_handles_to_markers
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_END_MARKER as E,
)
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_SEPARATOR_MARKER as SEP,
)
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_START_MARKER as S,
)
from bisheng.citation.domain.services.daily_citation_handles import (
    STREAM_HOLD_LIMIT,
    HandleStreamConverter,
    _convert_streaming,
)

HANDLES = {
    "S1": "knowledgesearch_aaaa1111:0",
    "S3": "knowledgesearch_bbbb2222:1",
    "S7": "websearch_cccc3333:0",
    "S12": "knowledgesearch_dddd4444:2",
}
K1, K3, K7, K12 = (HANDLES[h] for h in ("S1", "S3", "S7", "S12"))


def _stream(text: str, sizes) -> str:
    conv = HandleStreamConverter(dict(HANDLES))
    out = []
    pos = 0
    for size in sizes:
        out.append(conv.feed(text[pos : pos + size]))
        pos += size
    out.append(conv.feed(text[pos:]))
    out.append(conv.flush())
    return "".join(out)


def _whole(text: str) -> str:
    return _convert_streaming(text, HANDLES).text


# --------------------------------------------------------------------------- #
# grammar (AC-07, AC-08)
# --------------------------------------------------------------------------- #

CASES = [
    ("结论。[S3]", f"结论。{S}{K3}{E}"),
    ("结论[S3][S7]。", f"结论{S}{K3}{SEP}{K7}{E}。"),
    ("结论[S3, S7]。", f"结论{S}{K3}{SEP}{K7}{E}。"),
    ("结论[S3、S12]。", f"结论{S}{K3}{SEP}{K12}{E}。"),
    ("见 [S3](https://x.y) 链接", "见 [S3](https://x.y) 链接"),
    ("代码 `[S3]` 不转", "代码 `[S3]` 不转"),
    ("```\n[S3]\n```\n", "```\n[S3]\n```\n"),
    ("[S3]: 知识库·规则\n", "[S3]: 知识库·规则\n"),
    ("编号 [3] 与脚注 [^3] 不转", "编号 [3] 与脚注 [^3] 不转"),
    ("未知 [S99] 保留", "未知 [S99] 保留"),
    ("混合 [S3][S99] 部分", f"混合 {S}{K3}{E}[S99] 部分"),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_grammar_whole_text(text, expected):
    assert _whole(text) == expected


@pytest.mark.parametrize("text,expected", CASES)
def test_grammar_one_char_at_a_time(text, expected):
    assert _stream(text, [1] * len(text)) == expected


def test_unknown_handles_are_reported():
    conv = HandleStreamConverter(dict(HANDLES))
    conv.feed("甲[S3]，乙[S99]，丙[S98][S3]。")
    conv.flush()
    assert conv.stats.unknown == ["S99", "S98"]
    assert conv.stats.converted == 2


# --------------------------------------------------------------------------- #
# legacy markers written by the model (AC-10)
# --------------------------------------------------------------------------- #


def test_model_written_legacy_marker_is_dropped_and_counted():
    text = f"旧写法。{S}{K1}{E}新写法。[S3]"
    conv = HandleStreamConverter(dict(HANDLES))
    out = "".join(conv.feed(ch) for ch in text) + conv.flush()
    assert out == f"旧写法。新写法。{S}{K3}{E}"
    assert conv.stats.legacy_markers == 1


def test_escaped_legacy_marker_is_dropped_and_never_leaks_its_key():
    text = "旧写法。\\ue200" + K1 + "\\ue202后文。"
    conv = HandleStreamConverter(dict(HANDLES))
    pieces = [conv.feed(ch) for ch in text]
    out = "".join(pieces) + conv.flush()
    assert out == "旧写法。后文。"
    assert K1 not in "".join(pieces)


# --------------------------------------------------------------------------- #
# chunking invariance (AC-05, AC-09)
# --------------------------------------------------------------------------- #

CORPUS = (
    "## 结论\n\n市占率为 31%。[S3]\n同比增长[S3][S7]，但[S12, S1]口径不同。\n"
    "- 列表项 [S99] 未知\n- 链接 [S3](https://example.com)\n"
    "```python\nprint('[S3]')\n```\n"
    "行内 `code [S7]` 不转，[S7] 要转。\n"
    f"旧的{S}{K1}{E}写法。[S3]: 定义行\n结尾。[S1]"
)


@pytest.mark.parametrize("seed", range(40))
def test_random_chunking_equals_whole_text(seed):
    rng = random.Random(seed)
    sizes = []
    remaining = len(CORPUS)
    while remaining > 0:
        n = rng.randint(1, 9)
        sizes.append(n)
        remaining -= n
    assert _stream(CORPUS, sizes) == _whole(CORPUS)


def test_converted_output_is_idempotent():
    """Re-running the handle conversion on converted text changes nothing. (The
    streaming wrapper itself is fed raw model text only: it drops markers the
    model wrote, so it must never see its own output.)"""
    once = _whole(CORPUS)
    assert convert_handles_to_markers(once, HANDLES).text == once


# --------------------------------------------------------------------------- #
# holding and releasing
# --------------------------------------------------------------------------- #


def test_partial_handle_is_held_until_complete():
    conv = HandleStreamConverter(dict(HANDLES))
    assert conv.feed("结论。[S1") == "结论。"
    assert conv.feed("2]") == ""  # a second group may still follow
    assert conv.feed("，下一句") == f"{S}{K12}{E}，下一句"


def test_plain_text_is_not_delayed():
    conv = HandleStreamConverter(dict(HANDLES))
    assert conv.feed("没有任何编号的一段话。") == "没有任何编号的一段话。"


def test_a_stray_bracket_is_released_past_the_hold_limit():
    conv = HandleStreamConverter(dict(HANDLES))
    first = conv.feed("数组 [")
    assert first == "数组 "
    filler = " " * (STREAM_HOLD_LIMIT + 5)
    out = conv.feed(filler)
    assert out.startswith("[")


def test_handles_allocated_mid_turn_are_used():
    handles: dict[str, str] = {}
    conv = HandleStreamConverter(handles)
    handles["S3"] = K3  # a tool allocated it after the converter was built
    out = conv.feed("结论。[S3]。") + conv.flush()
    assert out == f"结论。{S}{K3}{E}。"


def test_flush_emits_the_held_tail():
    conv = HandleStreamConverter(dict(HANDLES))
    assert conv.feed("最后一句[S3]") == "最后一句"
    assert conv.flush() == f"{S}{K3}{E}"
    assert conv.text == f"最后一句{S}{K3}{E}"
