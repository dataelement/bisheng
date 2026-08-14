"""Character-page fallback in WorkspaceBackend.read / .aread.

Line slicing collapses on a file with no line breaks, and the most common such file
is one deepagents produced itself: an offloaded tool result (ToolNode serializes dict
results with ``json.dumps``, so every newline becomes a literal ``\\n``). Before this
fallback, reading one back had two outcomes and both were wrong — ``offset=0`` handed
back the entire file, and ``offset>=1`` returned ``""``, which upstream reports to the
model as *"File exists but has empty contents"*. The tail was unreachable by any call
while the offload notice told the model to page through it with offset/limit.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from bisheng.linsight.domain.services.workspace_backend import (
    _CHAR_PAGE_MIN_CHARS,
    _CHAR_PAGE_SIZE,
    _slice_workspace_text,
)

# One line, comfortably over the threshold — the shape of an offloaded tool result.
_SINGLE_LINE = '{"exitcode": 0, "log": "' + ("x" * 40000) + '", "file_list": ["output/a.png"]}'


def test_single_line_tail_is_reachable():
    """The regression that mattered: page 1+ used to come back empty."""
    page = _slice_workspace_text(_SINGLE_LINE, offset=1, limit=1)
    assert page.strip()
    assert "file_list" not in page  # a middle page, not the head


def test_pages_cover_the_whole_file():
    total_pages = -(-len(_SINGLE_LINE) // _CHAR_PAGE_SIZE)
    seen = "".join(
        _slice_workspace_text(_SINGLE_LINE, offset=i, limit=1).split("]\n", 1)[-1] for i in range(total_pages)
    )
    # Every byte is retrievable; the notice only prefixes partial reads.
    assert _SINGLE_LINE[-200:] in seen
    assert _SINGLE_LINE[:200] in seen


def test_partial_read_is_annotated():
    page = _slice_workspace_text(_SINGLE_LINE, offset=0, limit=1)
    assert "paginated by CHARACTER" in page
    assert "offset counts pages" in page


def test_single_line_below_threshold_is_untouched():
    """A short one-liner (a JSON config, say) must come back byte-identical — no
    prose header, or a caller doing json.loads on it would break."""
    small = '{"a": 1, "b": 2}'
    assert _slice_workspace_text(small, offset=0, limit=100) == small


def test_full_single_line_read_is_not_annotated():
    """Fits in one request => not a partial read => no header."""
    text = "y" * (_CHAR_PAGE_MIN_CHARS + 100)
    out = _slice_workspace_text(text, offset=0, limit=1000)
    assert out == text


def test_multiline_files_keep_line_semantics():
    text = "\n".join(f"line {i}" for i in range(500))
    out = _slice_workspace_text(text, offset=10, limit=3)
    assert out == "line 10\nline 11\nline 12"
    assert "paginated by CHARACTER" not in out


def test_multiline_large_file_is_not_char_paged():
    """Size alone must not trigger the fallback — only the absence of line breaks."""
    text = "\n".join("z" * 100 for _ in range(2000))  # >> threshold, but 2000 lines
    out = _slice_workspace_text(text, offset=0, limit=2)
    assert out == "z" * 100 + "\n" + "z" * 100


def test_limit_none_returns_everything():
    out = _slice_workspace_text(_SINGLE_LINE, offset=0, limit=None)
    assert out.replace("\n", "").endswith('"file_list": ["output/a.png"]}')


def test_offset_past_the_end_is_empty_not_an_error():
    assert _slice_workspace_text(_SINGLE_LINE, offset=10_000, limit=10) == ""
