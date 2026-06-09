"""Unit tests for OfdLoader (T005, covers AC-02 / AC-04).

OfdLoader converts OFD->PDF then delegates to a PDF loader; the converted PDF
becomes the preview file. Conversion + delegate are mocked here (the real
conversion is covered in test_ofd_converter.py).
"""

import pytest
from langchain_core.documents import Document

from bisheng.common.errcode.knowledge import OfdConvertError
from bisheng.knowledge.rag.pipeline.loader import ofd as ofd_module
from bisheng.knowledge.rag.pipeline.loader.ofd import OfdLoader


class _FakeDelegate:
    def __init__(self):
        self.local_image_dir = "staged-images"
        self.bbox_list = ["bbox-1"]

    def load(self):
        return [Document(page_content="hello from pdf delegate")]


def _make_loader(tmp_path, factory):
    return OfdLoader(
        file_path="/somewhere/doc.ofd",
        file_metadata={},
        file_extension="ofd",
        tmp_dir=str(tmp_path),
        pdf_loader_factory=factory,
    )


def test_load_delegates_and_sets_preview(tmp_path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(ofd_module, "convert_ofd_to_pdf", lambda inp, out: str(pdf))

    delegate = _FakeDelegate()
    loader = _make_loader(tmp_path, factory=lambda pdf_path: delegate)

    docs = loader.load()

    assert [d.page_content for d in docs] == ["hello from pdf delegate"]
    # preview is the converted PDF, not the original .ofd
    assert loader.preview_file_path == str(pdf)
    # bbox / image dir propagate from the delegate
    assert loader.local_image_dir == "staged-images"
    assert loader.bbox_list == ["bbox-1"]


def test_convert_failure_propagates(tmp_path, monkeypatch):
    def _boom(inp, out):
        raise OfdConvertError()

    monkeypatch.setattr(ofd_module, "convert_ofd_to_pdf", _boom)
    loader = _make_loader(tmp_path, factory=lambda pdf_path: _FakeDelegate())

    with pytest.raises(OfdConvertError):
        loader.load()
