"""F069 T024: the workspace write boundary converts short citation handles.

While a run's ``LinsightCitationScope`` is active, every markdown write / edit
turns the model's ``[S3]`` into the private-use marker the preview, resolve and
export paths already understand. ``.txt`` / ``.py`` never change, a missing
or disabled scope keeps the F047 behaviour (unescape only), unknown handles
stay literal and are reported, and already-converted text is idempotent.

F069 T038 (P2, AC-23, design decision 8): an ``.html`` / ``.htm`` write bakes
the handles instead — ``<sup data-f069-h="Sn">[n]</sup>`` numbered per file by first appearance
plus a references section built from the scope's handle table.
"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bisheng.citation.domain.services.linsight_citation_scope import LinsightCitationScope
from bisheng.linsight.domain.services.workspace_backend import WORKSPACE_PREFIX, WorkspaceBackend
from test.linsight.fixtures.fake_minio import fake_minio  # noqa: F401

KEY = "knowledgesearch_aaaa1111:3"
MARKER = f"{KEY}"


@pytest.fixture()
def file_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _scope(enabled: bool = True, handles: dict | None = None):
    return SimpleNamespace(enabled=enabled, handles={"S3": KEY} if handles is None else handles, note_conversion=Mock())


def _backend(minio, file_dir, scope, svid="sv1"):
    return WorkspaceBackend(svid=svid, minio=minio, file_dir=file_dir, citation_scope=scope)


def _stored(minio, rel, svid="sv1") -> bytes:
    return minio.store[(minio.bucket, f"{WORKSPACE_PREFIX}/{svid}/{rel}")]


# ---------------------------------------------------------------------------
# write / awrite / edit convert [S3] on markdown
# ---------------------------------------------------------------------------
def test_write_markdown_converts_handle(fake_minio, file_dir):
    scope = _scope()
    be = _backend(fake_minio, file_dir, scope)
    be.write("/output/a.md", "结论。[S3]\n")

    assert _stored(fake_minio, "output/a.md") == f"结论。{MARKER}\n".encode()
    assert b"[S3]" not in _stored(fake_minio, "output/a.md")
    scope.note_conversion.assert_called_with(1, [])


async def test_awrite_markdown_converts_handle(fake_minio, file_dir):
    scope = _scope()
    be = _backend(fake_minio, file_dir, scope)
    await be.awrite("/output/a.md", "结论。[S3]\n")

    assert _stored(fake_minio, "output/a.md") == f"结论。{MARKER}\n".encode()
    scope.note_conversion.assert_called_with(1, [])


def test_edit_new_string_converted(fake_minio, file_dir):
    be = _backend(fake_minio, file_dir, _scope())
    be.write("/output/a.md", "第一段。\n")
    res = be.edit("/output/a.md", "第一段。", "第一段。[S3]")

    assert res.error is None
    assert _stored(fake_minio, "output/a.md") == f"第一段。{MARKER}\n".encode()


async def test_aedit_delegates_and_converts(fake_minio, file_dir):
    be = _backend(fake_minio, file_dir, _scope())
    await be.awrite("/output/a.md", "第一段。\n")
    res = await be.aedit("/output/a.md", "第一段。", "第一段。[S3]")

    assert res.error is None
    assert _stored(fake_minio, "output/a.md") == f"第一段。{MARKER}\n".encode()


def test_edit_old_string_with_handle_matches_marker_on_disk(fake_minio, file_dir):
    """AC-14: the model remembers ``[S3]`` while the disk already holds the marker."""
    be = _backend(fake_minio, file_dir, _scope())
    be.write("/output/a.md", "结论。[S3]\n\n次要。\n")
    assert b"[S3]" not in _stored(fake_minio, "output/a.md")

    res = be.edit("/output/a.md", "结论。[S3]", "修订后的结论。[S3]")

    assert res.error is None
    assert res.occurrences == 1
    assert _stored(fake_minio, "output/a.md") == f"修订后的结论。{MARKER}\n\n次要。\n".encode()


def test_edit_old_string_falls_back_to_verbatim(fake_minio, file_dir):
    """A literal ``[S3]`` on disk (e.g. inside a code span) is still editable verbatim."""
    be = _backend(fake_minio, file_dir, _scope())
    be.write("/output/a.md", "见 `[S3]` 处。\n")
    assert b"`[S3]`" in _stored(fake_minio, "output/a.md")

    res = be.edit("/output/a.md", "`[S3]`", "`[S3]`（已核）")

    assert res.error is None
    assert _stored(fake_minio, "output/a.md") == "见 `[S3]`（已核） 处。\n".encode()


def test_edit_replace_all_with_handle(fake_minio, file_dir):
    be = _backend(fake_minio, file_dir, _scope())
    be.write("/output/a.md", "甲。[S3]\n乙。[S3]\n")

    res = be.edit("/output/a.md", "。[S3]", "。 [S3]", replace_all=True)

    assert res.error is None
    assert res.occurrences == 2
    assert _stored(fake_minio, "output/a.md") == f"甲。 {MARKER}\n乙。 {MARKER}\n".encode()


# ---------------------------------------------------------------------------
# non-markdown untouched; scope None / disabled keeps F047 behaviour
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rel", ["scratch/notes.txt", "scripts/run.py"])
def test_non_markdown_never_converted(fake_minio, file_dir, rel):
    """``.html`` is not in this list any more: P2 bakes it (see the html section below)."""
    scope = _scope()
    be = _backend(fake_minio, file_dir, scope)
    raw = "结论。[S3] \\ue200x\\ue202"
    be.write("/" + rel, raw)

    assert _stored(fake_minio, rel) == raw.encode()
    scope.note_conversion.assert_not_called()


def test_edit_non_markdown_keeps_verbatim_matching(fake_minio, file_dir):
    be = _backend(fake_minio, file_dir, _scope())
    be.write("/scratch/notes.txt", "结论。[S3]")
    res = be.edit("/scratch/notes.txt", "[S3]", "[S4]")

    assert res.error is None
    assert _stored(fake_minio, "scratch/notes.txt") == "结论。[S4]".encode()


@pytest.mark.parametrize("scope", [None, _scope(enabled=False), _scope(handles={})])
def test_inactive_scope_only_unescapes(fake_minio, file_dir, scope):
    be = _backend(fake_minio, file_dir, scope)
    be.write("/output/a.md", "结论。[S3] \\ue200knowledgesearch_aaa:1\\ue202")

    stored = _stored(fake_minio, "output/a.md")
    assert stored == "结论。[S3] knowledgesearch_aaa:1".encode()
    if scope is not None:
        scope.note_conversion.assert_not_called()


def test_backend_default_has_no_scope(fake_minio, file_dir):
    be = WorkspaceBackend(svid="sv1", minio=fake_minio, file_dir=file_dir)
    assert be.citation_scope is None
    # the pre-F069 spelling still resolves to the same boundary
    assert be._normalize_markdown_citation_bytes("output/a.md", b"x") == b"x"


# ---------------------------------------------------------------------------
# unknown handles, unescape + convert together, idempotence, robustness
# ---------------------------------------------------------------------------
def test_unknown_handle_stays_literal_and_is_noted(fake_minio, file_dir):
    scope = _scope()
    be = _backend(fake_minio, file_dir, scope)
    be.write("/output/a.md", "甲。[S3][S99]\n乙。[S99]\n")

    stored = _stored(fake_minio, "output/a.md")
    assert stored == f"甲。{MARKER}[S99]\n乙。[S99]\n".encode()
    scope.note_conversion.assert_called_with(1, ["S99"])


def test_unescape_then_convert_in_one_write(fake_minio, file_dir):
    be = _backend(fake_minio, file_dir, _scope())
    be.write("/output/a.md", "甲。\\ue200knowledgesearch_bbb:1\\ue202 乙。[S3]")

    assert _stored(fake_minio, "output/a.md") == f"甲。knowledgesearch_bbb:1 乙。{MARKER}".encode()


def test_second_write_of_converted_text_is_byte_identical(fake_minio, file_dir):
    scope = _scope()
    be = _backend(fake_minio, file_dir, scope)
    be.write("/output/a.md", "结论。[S3] 未知 [S99]\n")
    first = _stored(fake_minio, "output/a.md")

    be.write("/output/a.md", first.decode("utf-8"))

    assert _stored(fake_minio, "output/a.md") == first
    # the re-write converted nothing new; the literal unknown handle is reported again
    assert scope.note_conversion.call_args_list[-1].args == (0, ["S99"])


def test_real_scope_accumulates_counts(fake_minio, file_dir):
    scope = LinsightCitationScope(svid="sv1", session_id="sess1", enabled=True)
    scope.register_handle("S3", KEY, {"type": "rag"})
    be = _backend(fake_minio, file_dir, scope)

    be.write("/output/a.md", "甲。[S3] [S99]\n")
    be.write("/output/b.md", "乙。[S3]\n")

    assert _stored(fake_minio, "output/b.md") == f"乙。{MARKER}\n".encode()
    assert scope.converted_count == 2
    assert scope.unknown_handles == {"S99": 1}


def test_conversion_failure_never_raises(fake_minio, file_dir, monkeypatch):
    """A converter bug must not kill the task: the unescaped text is written as-is."""
    from bisheng.citation.domain.services import citation_handle_service

    def _boom(text, handles):
        raise RuntimeError("converter exploded")

    monkeypatch.setattr(citation_handle_service, "convert_handles_to_markers", _boom)
    be = _backend(fake_minio, file_dir, _scope())

    res = be.write("/output/a.md", "结论。[S3] \\ue200knowledgesearch_aaa:1\\ue202")

    assert res.error is None
    assert _stored(fake_minio, "output/a.md") == "结论。[S3] knowledgesearch_aaa:1".encode()


# ---------------------------------------------------------------------------
# F069 P2 (T038 / AC-23): html deliverables bake handles into <sup>[n]</sup>
# plus a references section built from the scope's handle table
# ---------------------------------------------------------------------------
WEB_KEY = "websearch_bbbb2222:0"
HTML_ENTRIES = [
    {"handle": "S3", "key": KEY, "type": "rag", "title": "规则手册", "loc": "第 3 页"},
    {"handle": "S7", "key": WEB_KEY, "type": "web", "title": "Example page", "loc": ""},
    {"handle": "S8", "key": "temp_cccc3333:1", "type": "temp", "title": "附件.docx", "loc": ""},
]
HTML_HANDLES = {"S3": KEY, "S7": WEB_KEY, "S8": "temp_cccc3333:1"}


def _html_scope(enabled: bool = True, handles: dict | None = None, entries: list | None = None):
    return SimpleNamespace(
        enabled=enabled,
        handles=HTML_HANDLES if handles is None else handles,
        entries=HTML_ENTRIES if entries is None else entries,
        note_conversion=Mock(),
    )


def _page(body: str) -> str:
    return f"<html><head><title>报告</title></head><body>\n{body}\n</body></html>"


def test_html_write_bakes_superscript_and_appendix(fake_minio, file_dir):
    scope = _html_scope()
    be = _backend(fake_minio, file_dir, scope)
    be.write("/output/page.html", _page("<p>结论。[S3]</p>"))

    stored = _stored(fake_minio, "output/page.html").decode("utf-8")
    assert '<p>结论。<sup data-f069-h="S3">[1]</sup></p>' in stored
    assert "[S3]" not in stored
    assert stored.endswith(
        "\n<section data-f069-references><h2>参考资料</h2><ol>\n"
        "<li>《规则手册》 · 第 3 页</li>\n"
        "</ol></section>\n</body></html>"
    )
    scope.note_conversion.assert_called_once_with(1, [])


async def test_html_awrite_bakes(fake_minio, file_dir):
    scope = _html_scope()
    be = _backend(fake_minio, file_dir, scope)
    await be.awrite("/output/page.htm", _page("<p>结论。[S3]</p>"))

    stored = _stored(fake_minio, "output/page.htm").decode("utf-8")
    assert '<sup data-f069-h="S3">[1]</sup>' in stored
    assert "data-f069-references" in stored
    scope.note_conversion.assert_called_once_with(1, [])


def test_html_two_handles_number_by_first_appearance(fake_minio, file_dir):
    scope = _html_scope()
    be = _backend(fake_minio, file_dir, scope)
    be.write("/output/page.html", _page("<p>甲。[S7][S3]</p><p>乙。[S3, S7]</p><p>丙。[S3、S8]</p>"))

    stored = _stored(fake_minio, "output/page.html").decode("utf-8")
    assert '<p>甲。<sup data-f069-h="S7,S3">[1][2]</sup></p>' in stored
    assert '<p>乙。<sup data-f069-h="S3,S7">[2][1]</sup></p>' in stored
    assert '<p>丙。<sup data-f069-h="S3,S8">[2][3]</sup></p>' in stored
    assert (
        "<ol>\n<li>Example page</li>\n<li>《规则手册》 · 第 3 页</li>\n<li>《附件.docx》</li>\n</ol>" in stored
    )
    scope.note_conversion.assert_called_once_with(3, [])


def test_html_second_write_of_baked_content_is_byte_identical(fake_minio, file_dir):
    scope = _html_scope()
    be = _backend(fake_minio, file_dir, scope)
    be.write("/output/page.html", _page("<p>结论。[S3] 未知 [S99]</p>"))
    first = _stored(fake_minio, "output/page.html")
    assert b"data-f069-references" in first

    be.write("/output/page.html", first.decode("utf-8"))

    assert _stored(fake_minio, "output/page.html") == first


def test_html_edit_after_bake_numbers_the_new_handle(fake_minio, file_dir):
    """A later edit that adds a handle to an already-baked page is re-baked:
    the old section goes, the new handle gets the next number."""
    scope = _html_scope()
    be = _backend(fake_minio, file_dir, scope)
    be.write("/output/page.html", _page("<p>结论。[S3]</p>"))
    first = _stored(fake_minio, "output/page.html").decode("utf-8")

    be.write("/output/page.html", first.replace("</p>", "</p><p>补充。[S7]</p>", 1))

    stored = _stored(fake_minio, "output/page.html").decode("utf-8")
    assert '<sup data-f069-h="S3">[1]</sup>' in stored and '<sup data-f069-h="S7">[2]</sup>' in stored
    assert stored.count("data-f069-references") == 1
    assert stored.count("<li>") == 2


def test_html_unknown_handle_left_literal_and_noted(fake_minio, file_dir):
    scope = _html_scope()
    be = _backend(fake_minio, file_dir, scope)
    be.write("/output/page.html", _page("<p>甲。[S3][S99]</p><p>乙。[S3]</p>"))

    stored = _stored(fake_minio, "output/page.html").decode("utf-8")
    # the known handle is baked, the unknown one stays literal after it (same as markdown)
    assert '<p>甲。<sup data-f069-h="S3">[1]</sup>[S99]</p>' in stored
    assert '<p>乙。<sup data-f069-h="S3">[1]</sup></p>' in stored
    assert "<li>《规则手册》 · 第 3 页</li>" in stored
    scope.note_conversion.assert_called_once_with(2, ["S99"])


def test_html_code_script_style_and_attributes_untouched(fake_minio, file_dir):
    scope = _html_scope()
    be = _backend(fake_minio, file_dir, scope)
    body = (
        '<p data-ref="[S3]">正文。[S3]</p>'
        "<code>[S3]</code>"
        "<pre>\n[S3]\n</pre>"
        "<script>var a = '[S3]';</script>"
        "<style>/* [S3] */</style>"
        "<!-- [S3] -->"
    )
    be.write("/output/page.html", _page(body))

    stored = _stored(fake_minio, "output/page.html").decode("utf-8")
    assert '<p data-ref="[S3]">正文。<sup data-f069-h="S3">[1]</sup></p>' in stored
    assert "<code>[S3]</code>" in stored
    assert "<pre>\n[S3]\n</pre>" in stored
    assert "<script>var a = '[S3]';</script>" in stored
    assert "<style>/* [S3] */</style>" in stored
    assert "<!-- [S3] -->" in stored
    scope.note_conversion.assert_called_once_with(1, [])


def test_html_without_numbered_handle_gets_no_section(fake_minio, file_dir):
    scope = _html_scope()
    be = _backend(fake_minio, file_dir, scope)
    raw = _page("<code>[S3]</code><p>[S99]</p><p>[3]</p>")
    be.write("/output/page.html", raw)

    assert _stored(fake_minio, "output/page.html") == raw.encode()
    scope.note_conversion.assert_called_once_with(0, ["S99"])


def test_html_heading_english_without_cjk(fake_minio, file_dir):
    scope = _html_scope(entries=[{"handle": "S7", "key": WEB_KEY, "type": "web", "title": "", "loc": ""}])
    be = _backend(fake_minio, file_dir, scope)
    be.write("/output/page.html", "<html><body><p>Conclusion.[S7]</p></body></html>")

    stored = _stored(fake_minio, "output/page.html").decode("utf-8")
    assert '<p>Conclusion.<sup data-f069-h="S7">[1]</sup></p>' in stored
    # web entry without a title falls back to the key; heading is English
    assert "<h2>References</h2><ol>\n<li>websearch_bbbb2222:0</li>\n</ol>" in stored


def test_html_without_body_appends_section_at_end(fake_minio, file_dir):
    be = _backend(fake_minio, file_dir, _html_scope())
    be.write("/output/fragment.html", "<p>结论。[S3]</p>")

    stored = _stored(fake_minio, "output/fragment.html").decode("utf-8")
    assert stored.startswith('<p>结论。<sup data-f069-h="S3">[1]</sup></p>\n<section data-f069-references>')
    assert stored.endswith("</ol></section>\n")


def test_html_reference_text_is_escaped(fake_minio, file_dir):
    scope = _html_scope(entries=[{"handle": "S3", "key": KEY, "type": "rag", "title": "A<b>&c", "loc": ""}])
    be = _backend(fake_minio, file_dir, scope)
    be.write("/output/page.html", _page("<p>结论。[S3]</p>"))

    assert "<li>《A&lt;b&gt;&amp;c》</li>" in _stored(fake_minio, "output/page.html").decode("utf-8")


@pytest.mark.parametrize("scope", [None, _html_scope(enabled=False), _html_scope(handles={})])
def test_html_inactive_scope_unchanged(fake_minio, file_dir, scope):
    be = _backend(fake_minio, file_dir, scope)
    raw = _page("<p>结论。[S3] \\ue200x\\ue202</p>")
    be.write("/output/page.html", raw)

    assert _stored(fake_minio, "output/page.html") == raw.encode()
    if scope is not None:
        scope.note_conversion.assert_not_called()


def test_html_scope_does_not_touch_txt(fake_minio, file_dir):
    scope = _html_scope()
    be = _backend(fake_minio, file_dir, scope)
    be.write("/scratch/notes.txt", "结论。[S3]")

    assert _stored(fake_minio, "scratch/notes.txt") == "结论。[S3]".encode()
    scope.note_conversion.assert_not_called()


def test_html_non_utf8_bytes_unchanged(fake_minio, file_dir):
    scope = _html_scope()
    be = _backend(fake_minio, file_dir, scope)
    raw = "<p>结论。[S3]</p>".encode("gbk")
    be.write("/output/page.html", raw)

    assert _stored(fake_minio, "output/page.html") == raw
    scope.note_conversion.assert_not_called()


def test_html_bake_failure_never_raises(fake_minio, file_dir, monkeypatch):
    def _boom(self, text):
        raise RuntimeError("baker exploded")

    monkeypatch.setattr(WorkspaceBackend, "_bake_html_citation_handles", _boom)
    be = _backend(fake_minio, file_dir, _html_scope())
    raw = _page("<p>结论。[S3]</p>")

    res = be.write("/output/page.html", raw)

    assert res.error is None
    assert _stored(fake_minio, "output/page.html") == raw.encode()


def test_html_real_scope_entries_feed_the_appendix(fake_minio, file_dir):
    scope = LinsightCitationScope(svid="sv1", session_id="sess1", enabled=True)
    scope.register_handle("S3", KEY, {"type": "rag", "title": "规则手册", "loc": "第 3 页"})
    scope.register_handle("S7", WEB_KEY, {"type": "web", "title": "Example page", "loc": ""})
    be = _backend(fake_minio, file_dir, scope)

    be.write("/output/page.html", _page("<p>甲。[S7]</p><p>乙。[S3] 另见 [S99]</p>"))

    stored = _stored(fake_minio, "output/page.html").decode("utf-8")
    assert '<p>甲。<sup data-f069-h="S7">[1]</sup></p><p>乙。<sup data-f069-h="S3">[2]</sup> 另见 [S99]</p>' in stored
    assert "<ol>\n<li>Example page</li>\n<li>《规则手册》 · 第 3 页</li>\n</ol>" in stored
    assert scope.converted_count == 2
    assert scope.unknown_handles == {"S99": 1}
