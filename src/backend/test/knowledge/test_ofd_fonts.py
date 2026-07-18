"""CJK font handling for the OFD -> PDF converter.

easyofd hard-codes ``setFont("宋体")`` while drawing text and only registers
that name if a system file literally named ``simsun.ttc`` is on reportlab's
search path. On our deploy image (and most Linux hosts) it is not, so the name
is never registered, every glyph falls back to Helvetica, and the converted PDF
comes out with the table borders but **no Chinese text at all** — a blank
invoice preview.

These tests pin the fix: probe the host for a CJK font and register easyofd's
hard-coded font names against it (in the process-global reportlab registry that
easyofd shares), so the conversion renders text without modifying the library.
"""

from pathlib import Path

import fitz
from loguru import logger
from reportlab.pdfbase import pdfmetrics

from bisheng.knowledge.rag.pipeline.loader.utils import ofd_converter
from bisheng.knowledge.rag.pipeline.loader.utils.ofd_converter import (
    convert_ofd_to_pdf,
)

FIXTURES = Path(__file__).parent / "fixtures"
# Anonymized real e-invoice: real OFD structure (TextCode + font refs) with all
# PII scrubbed. It renders Chinese form labels ("电子发票"…) once a CJK font is
# registered, and nothing but borders when one is missing.
CJK_INVOICE = FIXTURES / "invoice_cjk.ofd"


def test_detect_cjk_font_returns_existing_readable_path():
    path = ofd_converter._detect_cjk_font()

    assert path is not None, "host should expose at least one CJK font"
    assert Path(path).is_file()


def test_ensure_cjk_fonts_registers_hardcoded_song_name():
    # easyofd draws with setFont("宋体"); that exact name must end up registered.
    ofd_converter._ensure_cjk_fonts_registered()

    assert "宋体" in pdfmetrics.getRegisteredFontNames()


def test_cjk_invoice_converts_with_selectable_text(tmp_path):
    pdf_path = convert_ofd_to_pdf(str(CJK_INVOICE), str(tmp_path))

    text = fitz.open(pdf_path)[0].get_text().strip()
    assert text, "converted invoice must contain selectable text, not a blank page"
    assert "电子发票" in text


def test_missing_cjk_font_logs_warning_and_still_converts(tmp_path, monkeypatch):
    monkeypatch.setattr(ofd_converter, "_detect_cjk_font", lambda: None)
    # warn-once flag may already be set by an earlier conversion; reset so the
    # missing-font branch is exercised regardless of test order.
    monkeypatch.setattr(ofd_converter, "_warned_missing_font", False)

    messages: list[str] = []
    sink = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    try:
        pdf_path = convert_ofd_to_pdf(str(CJK_INVOICE), str(tmp_path))
    finally:
        logger.remove(sink)

    # Conversion degrades gracefully (still produces a PDF) but is not silent.
    with open(pdf_path, "rb") as f:
        assert f.read(5) == b"%PDF-"
    assert any("CJK" in m or "font" in m.lower() for m in messages)
