from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from bisheng.knowledge.pdf.watermark import (
    _CJK_FONT_CANDIDATES,
    PdfWatermarkError,
    PdfWatermarkSpec,
    _calculate_watermark_layout,
    _resolve_cjk_font,
    _tile_positions,
    apply_pdf_watermark,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_source(path: Path) -> None:
    document = fitz.open()
    portrait = document.new_page(width=595, height=842)
    portrait.insert_text((72, 72), "source portrait text")
    landscape = document.new_page(width=842, height=595)
    landscape.insert_text((72, 72), "source landscape text")
    rotated = document.new_page(width=595, height=842)
    rotated.insert_text((72, 72), "source rotated text")
    rotated.set_rotation(90)
    document.set_metadata({"title": "watermark-source"})
    document.save(path)
    document.close()


def _create_zero_page_pdf(path: Path) -> None:
    header = b"%PDF-1.4\n"
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n",
    ]
    offsets: list[int] = []
    body = bytearray(header)
    for item in objects:
        offsets.append(len(body))
        body.extend(item)
    xref_offset = len(body)
    body.extend(b"xref\n0 3\n0000000000 65535 f \n")
    for offset in offsets:
        body.extend(f"{offset:010d} 00000 n \n".encode())
    body.extend(b"trailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n" + str(xref_offset).encode() + b"\n%%EOF\n")
    path.write_bytes(body)


def _spec() -> PdfWatermarkSpec:
    return PdfWatermarkSpec(
        lines=(
            "设备管理部-张三--SG001-2026/07/21",
            "首钢股份内部资料，严禁外传，违者必究",  # noqa: RUF001
        )
    )


def test_watermark_preserves_source_and_pages_while_tiling_each_page(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "watermarked.pdf"
    _create_source(source)
    source_hash = _sha256(source)

    result = apply_pdf_watermark(source, output, _spec())

    assert _sha256(source) == source_hash
    assert output != source
    assert result.page_count == 3
    assert result.artifact_size == output.stat().st_size
    with fitz.open(source) as original, fitz.open(output) as watermarked:
        assert watermarked.page_count == original.page_count
        assert watermarked.metadata["title"] == "watermark-source"
        for page_number in range(original.page_count):
            original_page = original.load_page(page_number)
            watermarked_page = watermarked.load_page(page_number)
            assert watermarked_page.rect == original_page.rect
            text = watermarked_page.get_text()
            assert original_page.get_text().strip() in text
            assert text.count("设备管理部-张三--SG001-2026/07/21") >= 2
            assert text.count("首钢股份内部资料，严禁外传，违者必究") >= 2  # noqa: RUF001


def test_watermark_uses_chinese_text_opacity_and_arbitrary_angle(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "watermarked.pdf"
    _create_source(source)

    apply_pdf_watermark(source, output, _spec())

    with fitz.open(output) as document:
        page = document.load_page(0)
        traces = page.get_texttrace()
        watermark_traces = [
            trace
            for trace in traces
            if "设备管理部-张三--SG001-2026/07/21" in "".join(chr(char[0]) for char in trace["chars"])
        ]
        assert watermark_traces
        assert all(trace["dir"][0] > 0 and trace["dir"][1] < 0 for trace in watermark_traces)
        assert all(trace["opacity"] == pytest.approx(0.31) for trace in watermark_traces)


def test_watermark_spec_uses_two_lines_and_pdf_visual_baseline() -> None:
    spec = _spec()

    assert len(spec.lines) == 2
    assert spec.rotation == 35.0
    assert spec.opacity == 0.31
    assert spec.font_size == 12.0
    assert spec.horizontal_gap == 180.0
    assert spec.vertical_gap == 135.0
    assert spec.color == (0.45, 0.45, 0.45)
    assert all("songti" not in candidate.lower() for candidate in _CJK_FONT_CANDIDATES)
    assert any("zenhei" in candidate.lower() or "heiti" in candidate.lower() for candidate in _CJK_FONT_CANDIDATES)

    with pytest.raises(PdfWatermarkError, match="two non-empty lines"):
        PdfWatermarkSpec(lines=("identity", "date", "legacy notice"))


def test_watermark_layout_uses_rotated_bounds_clearance_and_staggered_rows() -> None:
    page_rect = fitz.Rect(0, 0, 595, 842)
    font = _resolve_cjk_font()
    legacy_spacing_spec = PdfWatermarkSpec(
        lines=_spec().lines,
        horizontal_gap=120.0,
        vertical_gap=90.0,
    )
    layout = _calculate_watermark_layout(page_rect, legacy_spacing_spec, font)

    assert layout.horizontal_step == pytest.approx(layout.rotated_width + 36.0)
    assert layout.vertical_step == pytest.approx(layout.rotated_height + 27.0)
    assert layout.horizontal_step >= 180.0
    assert layout.vertical_step >= 135.0

    positions = _tile_positions(page_rect, layout)
    rows: dict[float, list[float]] = {}
    for position in positions:
        rows.setdefault(position.y, []).append(position.x)

    assert len(positions) >= 12
    assert len(rows) >= 2
    first_row, second_row = list(rows.values())[:2]
    assert second_row[0] - first_row[0] == pytest.approx(layout.horizontal_step / 2.0)
    assert first_row[1] - first_row[0] == pytest.approx(layout.horizontal_step)


def test_watermark_layout_expands_for_long_identity_without_shrinking_text() -> None:
    page_rect = fitz.Rect(0, 0, 595, 842)
    font = _resolve_cjk_font()
    normal = _calculate_watermark_layout(page_rect, _spec(), font)
    long_spec = PdfWatermarkSpec(
        lines=(
            f"{'超长部门名称' * 8}-张三--{'SG-VERY-LONG-ACCOUNT-' * 5}-2026/07/21",
            "首钢股份内部资料，严禁外传，违者必究",  # noqa: RUF001
        )
    )

    expanded = _calculate_watermark_layout(page_rect, long_spec, font)

    assert expanded.font_size == normal.font_size == 12.0
    assert expanded.horizontal_step > normal.horizontal_step
    assert expanded.vertical_step > normal.vertical_step
    assert expanded.horizontal_step >= expanded.rotated_width + 36.0
    assert expanded.vertical_step >= expanded.rotated_height + 27.0


def test_watermark_uses_bundled_sans_font_and_rejects_unreliable_fallback() -> None:
    bundled_font = next(
        candidate for candidate in _CJK_FONT_CANDIDATES if candidate.endswith("docker/fonts/NotoSansCJKsc-Regular.otf")
    )

    assert Path(bundled_font).is_file()
    assert _resolve_cjk_font(("/missing/watermark-font.ttf", bundled_font)).font_file == bundled_font
    with pytest.raises(PdfWatermarkError, match="font is unavailable"):
        _resolve_cjk_font(("/missing/watermark-font.ttf",))


def test_watermark_rejects_corrupt_encrypted_and_zero_page_sources(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not-a-pdf")
    with pytest.raises(PdfWatermarkError, match="invalid"):
        apply_pdf_watermark(corrupt, tmp_path / "corrupt-output.pdf", _spec())

    plain = tmp_path / "plain.pdf"
    encrypted = tmp_path / "encrypted.pdf"
    _create_source(plain)
    with fitz.open(plain) as document:
        document.save(
            encrypted,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="secret",
        )
    with pytest.raises(PdfWatermarkError, match="encrypted"):
        apply_pdf_watermark(encrypted, tmp_path / "encrypted-output.pdf", _spec())

    zero_page = tmp_path / "zero-page.pdf"
    _create_zero_page_pdf(zero_page)
    with pytest.raises(PdfWatermarkError, match="no pages"):
        apply_pdf_watermark(zero_page, tmp_path / "zero-output.pdf", _spec())


def test_watermark_removes_partial_output_after_failure(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "watermarked.pdf"
    _create_source(source)

    def fail_save(*_args, **_kwargs):
        output.write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(fitz.Document, "save", fail_save)

    with pytest.raises(PdfWatermarkError, match="generation failed"):
        apply_pdf_watermark(source, output, _spec())
    assert not output.exists()
