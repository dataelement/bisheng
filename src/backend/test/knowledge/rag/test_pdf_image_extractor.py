from io import BytesIO
from pathlib import Path

import fitz
import pytest
from loguru import logger
from PIL import Image

from bisheng.knowledge.rag.pipeline.loader.utils.pdf_image_extractor import PdfImageExtractor


def _image_bytes(image_format: str = "JPEG", size: tuple[int, int] = (640, 360)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color=(40, 120, 200)).save(buffer, format=image_format, quality=95)
    return buffer.getvalue()


def _embedded_image_pdf(
    tmp_path: Path,
    *,
    image_rect: fitz.Rect = fitz.Rect(50, 60, 250, 160),
) -> Path:
    pdf_path = tmp_path / "embedded.pdf"
    document = fitz.open()
    page = document.new_page(width=400, height=300)
    page.insert_image(image_rect, stream=_image_bytes())
    document.save(pdf_path)
    document.close()
    return pdf_path


def test_original_first_preserves_embedded_image_bytes_and_dimensions(tmp_path: Path, monkeypatch):
    pdf_path = _embedded_image_pdf(tmp_path)
    output_dir = tmp_path / "images"

    with fitz.open(pdf_path) as document:
        image_info = document[0].get_image_info(xrefs=True)[0]
        extracted_source = document.extract_image(image_info["xref"])
        monkeypatch.setattr(fitz.Page, "get_pixmap", lambda *args, **kwargs: pytest.fail("unexpected render"))
        result = PdfImageExtractor(
            strategy="original_first",
            fallback_dpi=200,
            max_pixels=16_000_000,
        ).extract(document, 0, [50, 60, 250, 160], "image/with spaces", output_dir)

    output_path = output_dir / result.filename
    assert result.source_type == "embedded"
    assert result.width == 640
    assert result.height == 360
    assert result.matched_xref == image_info["xref"]
    assert result.effective_dpi is None
    assert output_path.read_bytes() == extracted_source["image"]
    assert "/" not in result.filename
    assert " " not in result.filename


def test_render_only_renders_bbox_at_requested_dpi_without_full_page_file(tmp_path: Path):
    pdf_path = tmp_path / "blank.pdf"
    document = fitz.open()
    document.new_page(width=400, height=300)
    document.save(pdf_path)
    document.close()

    output_dir = tmp_path / "images"
    with fitz.open(pdf_path) as document:
        result = PdfImageExtractor(
            strategy="render_only",
            fallback_dpi=200,
            max_pixels=16_000_000,
        ).extract(document, 0, [10, 20, 110, 70], "region", output_dir)

    assert result.source_type == "rendered"
    assert result.width == pytest.approx(100 * 200 / 72, abs=2)
    assert result.height == pytest.approx(50 * 200 / 72, abs=2)
    assert result.effective_dpi == pytest.approx(200, abs=0.1)
    assert list(output_dir.iterdir()) == [output_dir / result.filename]


def test_rendering_reduces_effective_dpi_to_respect_pixel_limit(tmp_path: Path):
    pdf_path = tmp_path / "large-region.pdf"
    document = fitz.open()
    document.new_page(width=500, height=500)
    document.save(pdf_path)
    document.close()

    with fitz.open(pdf_path) as document:
        result = PdfImageExtractor(
            strategy="render_only",
            fallback_dpi=300,
            max_pixels=10_000,
        ).extract(document, 0, [0, 0, 200, 200], "limited", tmp_path / "images")

    assert result.width * result.height <= 10_000
    assert result.effective_dpi < 300


def test_original_first_falls_back_for_partial_scan_page_match(tmp_path: Path):
    pdf_path = tmp_path / "scan.pdf"
    document = fitz.open()
    page = document.new_page(width=400, height=300)
    page.insert_image(page.rect, stream=_image_bytes(size=(1200, 900)))
    document.save(pdf_path)
    document.close()

    with fitz.open(pdf_path) as document:
        result = PdfImageExtractor(
            strategy="original_first",
            fallback_dpi=144,
            max_pixels=16_000_000,
        ).extract(document, 0, [50, 50, 150, 100], "scan-part", tmp_path / "images")

    assert result.source_type == "rendered"
    assert result.matched_xref is None
    assert result.fallback_reason == "no_high_confidence_candidate"
    assert result.width == pytest.approx(200, abs=1)


def test_original_first_falls_back_when_target_contains_multiple_images(tmp_path: Path):
    pdf_path = tmp_path / "multiple.pdf"
    document = fitz.open()
    page = document.new_page(width=400, height=300)
    page.insert_image(fitz.Rect(40, 60, 140, 160), stream=_image_bytes(size=(300, 300)))
    page.insert_image(fitz.Rect(160, 60, 260, 160), stream=_image_bytes(size=(300, 300)))
    document.save(pdf_path)
    document.close()

    with fitz.open(pdf_path) as document:
        result = PdfImageExtractor(
            strategy="original_first",
            fallback_dpi=144,
            max_pixels=16_000_000,
        ).extract(document, 0, [40, 60, 260, 160], "composite", tmp_path / "images")

    assert result.source_type == "rendered"
    assert result.fallback_reason == "no_high_confidence_candidate"


def test_original_first_falls_back_for_rotated_embedded_image(tmp_path: Path):
    pdf_path = tmp_path / "rotated-image.pdf"
    document = fitz.open()
    page = document.new_page(width=400, height=300)
    page.insert_image(
        fitz.Rect(50, 60, 140, 220),
        stream=_image_bytes(size=(640, 360)),
        rotate=90,
    )
    document.save(pdf_path)
    document.close()

    with fitz.open(pdf_path) as document:
        result = PdfImageExtractor(
            strategy="original_first",
            fallback_dpi=144,
            max_pixels=16_000_000,
        ).extract(document, 0, [50, 60, 140, 220], "rotated-image", tmp_path / "images")

    assert result.source_type == "rendered"
    assert result.fallback_reason == "no_high_confidence_candidate"


def test_rendered_image_log_contains_diagnostic_fields(tmp_path: Path):
    pdf_path = tmp_path / "logged.pdf"
    document = fitz.open()
    document.new_page(width=400, height=300)
    document.save(pdf_path)
    document.close()
    messages: list[str] = []
    handler_id = logger.add(lambda message: messages.append(str(message)), format="{message}")

    try:
        with fitz.open(pdf_path) as document:
            PdfImageExtractor(
                strategy="render_only",
                fallback_dpi=200,
                max_pixels=16_000_000,
            ).extract(document, 0, [10, 20, 110, 70], "logged", tmp_path / "images")
    finally:
        logger.remove(handler_id)

    log_text = "\n".join(messages)
    assert "act=etl4lm_extract_image" in log_text
    assert "source_type=rendered" in log_text
    assert "effective_dpi=200" in log_text
    assert "fallback_reason=strategy_render_only" in log_text
    assert "duration_ms=" in log_text


def test_render_only_does_not_try_embedded_image_matching(tmp_path: Path, monkeypatch):
    pdf_path = _embedded_image_pdf(tmp_path)
    monkeypatch.setattr(
        PdfImageExtractor,
        "_find_embedded_image",
        lambda *args, **kwargs: pytest.fail("unexpected embedded image matching"),
    )

    with fitz.open(pdf_path) as document:
        result = PdfImageExtractor(
            strategy="render_only",
            fallback_dpi=144,
            max_pixels=16_000_000,
        ).extract(document, 0, [50, 60, 250, 160], "render-only", tmp_path / "images")

    assert result.source_type == "rendered"


def test_render_region_supports_rotated_pages(tmp_path: Path):
    pdf_path = tmp_path / "rotated.pdf"
    document = fitz.open()
    page = document.new_page(width=400, height=300)
    page.set_rotation(90)
    document.save(pdf_path)
    document.close()

    with fitz.open(pdf_path) as document:
        result = PdfImageExtractor(
            strategy="render_only",
            fallback_dpi=144,
            max_pixels=16_000_000,
        ).extract(document, 0, [10, 20, 110, 70], "rotated", tmp_path / "images")

    assert result.source_type == "rendered"
    assert result.width > 0
    assert result.height > 0


@pytest.mark.parametrize(
    ("page_number", "bbox"),
    [
        (-1, [0, 0, 10, 10]),
        (1, [0, 0, 10, 10]),
        (0, [0, 0, 0, 10]),
        (0, [0, 0, float("nan"), 10]),
        (0, [500, 500, 600, 600]),
    ],
)
def test_invalid_page_or_bbox_fails_explicitly(tmp_path: Path, page_number: int, bbox: list[float]):
    pdf_path = tmp_path / "invalid.pdf"
    document = fitz.open()
    document.new_page(width=400, height=300)
    document.save(pdf_path)
    document.close()

    with fitz.open(pdf_path) as document:
        with pytest.raises(ValueError):
            PdfImageExtractor(
                strategy="render_only",
                fallback_dpi=200,
                max_pixels=16_000_000,
            ).extract(document, page_number, bbox, "invalid", tmp_path / "images")
