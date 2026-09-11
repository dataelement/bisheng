"""A deliverable whose bytes contradict its name must not be delivered.

Observed on a customer run (session c139f849…): with no code interpreter bound,
the agent could not build a real deck, so it wrote a 310-byte outline — opening
with 「虚拟生成的PPT文件内容」 — into ``output/presentation.pptx`` and signed off with
「已经为你创建了一个简短的PPT…你可以下载」. Selection accepted it (right zone, new file,
non-empty), MinIO stored it, and the user downloaded something PowerPoint cannot
open. Nothing in the run recorded that anything had gone wrong.

This is the sibling of :mod:`test_phantom_deliverable_detection`: that one catches
a file the answer claims but never wrote, this one catches a file that exists but
is not what its name promises. Both are diagnosis — the fake is dropped and
recorded, never repaired into something it isn't.

Only container formats with a FIXED header are checked. A text deliverable
(.md / .csv / .html / .svg) may legitimately begin with any byte, so it has no
signature and is never accused; so is any extension outside the table.
"""

from __future__ import annotations

import os
import zlib

from bisheng.linsight.domain.utils import (
    deliverable_format_error,
    detect_invalid_deliverables,
)

# A real OOXML file is a zip: local file header, then deflate.
PPTX_BYTES = b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + zlib.compress(b"<p:sld/>" * 10)
PDF_BYTES = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02\x03" * 16
# The actual payload from the customer run, shortened.
FAKE_PPTX_BYTES = "虚拟生成的PPT文件内容：\n\n1. 标题幻灯片\n   - 标题：快速演示文稿\n".encode()


def _write(tmp_path, rel_path: str, data: bytes) -> dict:
    path = tmp_path / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "file_name": os.path.basename(rel_path),
        "file_path": str(path),
        "rel_path": rel_path,
        "file_mtime": 0.0,
        "file_md5": "md5-" + rel_path,
        "file_id": "id-" + rel_path,
    }


# ---------------------------------------------------------------------------
# deliverable_format_error
# ---------------------------------------------------------------------------
def test_text_written_under_a_pptx_name_is_rejected(tmp_path):
    info = _write(tmp_path, "output/presentation.pptx", FAKE_PPTX_BYTES)
    reason = deliverable_format_error(info)
    assert reason is not None
    assert "pptx" in reason


def test_a_real_pptx_passes(tmp_path):
    assert deliverable_format_error(_write(tmp_path, "output/deck.pptx", PPTX_BYTES)) is None


def test_a_real_pdf_and_png_pass(tmp_path):
    assert deliverable_format_error(_write(tmp_path, "output/报告.pdf", PDF_BYTES)) is None
    assert deliverable_format_error(_write(tmp_path, "output/chart.png", PNG_BYTES)) is None


def test_markdown_is_never_accused(tmp_path):
    """Text formats have no fixed header — checking one could only produce false
    accusations, and a wrongly dropped real deliverable is worse than a fake one
    getting through."""
    assert deliverable_format_error(_write(tmp_path, "output/报告.md", "# 报告\n正文".encode())) is None
    assert deliverable_format_error(_write(tmp_path, "output/data.csv", b"a,b\n1,2\n")) is None


def test_an_unknown_extension_is_never_accused(tmp_path):
    assert deliverable_format_error(_write(tmp_path, "output/notebook.ipynb", b"{}")) is None


def test_an_empty_file_under_a_binary_name_is_rejected(tmp_path):
    """Zero bytes cannot be a deck. This is the shape a crashed build script
    leaves behind, and it opens no better than the fabricated one."""
    assert deliverable_format_error(_write(tmp_path, "output/deck.pptx", b"")) is not None


def test_an_unreadable_file_is_not_accused(tmp_path):
    """Never accuse a file we could not inspect — the upload will fail on its own
    and report the real error."""
    info = _write(tmp_path, "output/deck.pptx", PPTX_BYTES)
    info["file_path"] = str(tmp_path / "output" / "gone.pptx")
    assert deliverable_format_error(info) is None


def test_a_legacy_ppt_wants_the_ole2_header(tmp_path):
    assert deliverable_format_error(_write(tmp_path, "output/deck.ppt", PPTX_BYTES)) is not None
    ole2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32
    assert deliverable_format_error(_write(tmp_path, "output/deck.ppt", ole2)) is None


# ---------------------------------------------------------------------------
# detect_invalid_deliverables — the diagnostic record
# ---------------------------------------------------------------------------
def test_only_selected_deliverables_are_judged(tmp_path):
    """A stray fake under scratch/ is not a deliverable, so it is not a finding —
    reporting it would bury the real one."""
    details = [
        _write(tmp_path, "output/presentation.pptx", FAKE_PPTX_BYTES),
        _write(tmp_path, "scratch/draft.pptx", FAKE_PPTX_BYTES),
    ]
    invalid = detect_invalid_deliverables(details)
    assert [f["file_name"] for f in invalid] == ["presentation.pptx"]
    assert invalid[0]["reason"]


def test_a_clean_run_reports_nothing(tmp_path):
    details = [_write(tmp_path, "output/deck.pptx", PPTX_BYTES)]
    assert detect_invalid_deliverables(details) == []
