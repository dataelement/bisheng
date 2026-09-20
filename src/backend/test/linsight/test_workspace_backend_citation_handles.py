"""F069 T024: the workspace write boundary converts short citation handles.

While a run's ``LinsightCitationScope`` is active, every markdown write / edit
turns the model's ``[S3]`` into the private-use marker the preview, resolve and
export paths already understand. ``.txt`` / ``.html`` never change, a missing
or disabled scope keeps the F047 behaviour (unescape only), unknown handles
stay literal and are reported, and already-converted text is idempotent.
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
@pytest.mark.parametrize("rel", ["scratch/notes.txt", "output/page.html", "scripts/run.py"])
def test_non_markdown_never_converted(fake_minio, file_dir, rel):
    scope = _scope()
    be = _backend(fake_minio, file_dir, scope)
    raw = "结论。[S3] \\ue200x\\ue202"
    be.write("/" + rel, raw)

    assert _stored(fake_minio, rel) == raw.encode()
    scope.note_conversion.assert_not_called()


def test_edit_non_markdown_keeps_verbatim_matching(fake_minio, file_dir):
    be = _backend(fake_minio, file_dir, _scope())
    be.write("/output/page.html", "<p>结论。[S3]</p>")
    res = be.edit("/output/page.html", "[S3]", "[S4]")

    assert res.error is None
    assert _stored(fake_minio, "output/page.html") == "<p>结论。[S4]</p>".encode()


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
