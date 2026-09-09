"""Unit tests for the OFD -> PDF converter (T003, covers AC-02 / AC-04).

The fixture ``fixtures/sample.ofd`` is a small valid OFD generated once via
easyofd's ``pdf2ofd``; the converter under test only uses the forward path
(``read`` + ``to_pdf``), which is what production runs.
"""

from pathlib import Path

import pytest

from bisheng.common.errcode.knowledge import OfdConvertError
from bisheng.knowledge.rag.pipeline.loader.utils.ofd_converter import convert_ofd_to_pdf

FIXTURE = Path(__file__).parent / "fixtures" / "sample.ofd"


def test_convert_valid_ofd_returns_pdf(tmp_path):
    out = convert_ofd_to_pdf(str(FIXTURE), str(tmp_path))

    out_path = Path(out)
    assert out_path.exists()
    assert out_path.parent == tmp_path
    with open(out_path, "rb") as f:
        assert f.read(5) == b"%PDF-"


def test_convert_corrupt_raises(tmp_path):
    bad = tmp_path / "fake.ofd"
    bad.write_bytes(b"not an ofd zip at all")

    with pytest.raises(OfdConvertError):
        convert_ofd_to_pdf(str(bad), str(tmp_path))


def test_unknown_annotation_type_does_not_lose_the_document():
    """An annotation type easyofd doesn't know must not abort the whole render.

    easyofd resolves ``@Type`` through ``AnnotationFileParser.AnnoType`` and falls
    back to the *string* ``"unknown"``, while its drawing code calls ``.get("type")``
    on the result. One unrecognised annotation therefore raised AttributeError,
    which ``DrawPDF.__call__`` swallowed by discarding the entire rendered document
    and emitting a one-page placeholder reading "ofd 格式错误,不支持解析" — a real
    customer file (a Suwell-produced doc carrying a ``PreSeal`` seal) lost both of
    its pages that way, and the failure was reported as a successful conversion.
    """
    from bisheng.knowledge.rag.pipeline.loader.utils.ofd_converter import (
        _ensure_easyofd_patched,
    )

    _ensure_easyofd_patched()

    from easyofd.parser_ofd import file_annotation_parser

    table = file_annotation_parser.AnnotationFileParser.AnnoType

    # Known types keep their original mapping.
    assert table.get("Watermark", "unknown")["type"] == "Watermark"

    # Unknown ones resolve to a correctly shaped dict rather than a bare string,
    # so the caller's `.get("type")` works and simply doesn't match the
    # ["Watermark", "Stamp"] filter — the annotation is skipped, the page is kept.
    seal = table.get("PreSeal", "unknown")
    assert isinstance(seal, dict), "must stay subscriptable for draw_annotation"
    assert seal["type"] == "PreSeal"
    assert seal["type"] not in ("Watermark", "Stamp")
