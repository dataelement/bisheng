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
