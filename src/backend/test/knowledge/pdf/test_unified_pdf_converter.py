from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PIL import Image

from bisheng.knowledge.pdf.converter import (
    ConversionContext,
    ImagePdfConverter,
    OfficePdfConverter,
    PdfConversionError,
    PdfConverterRegistry,
    TextWebPdfConverter,
    _browser_request_is_allowed,
)
from bisheng.knowledge.pdf.validator import PdfValidationError, validate_pdf


def _write_pdf(path: Path, text: str = "hello") -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_validator_returns_stable_metadata_for_valid_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "valid.pdf"
    _write_pdf(pdf_path)

    result = validate_pdf(pdf_path)

    assert result.page_count == 1
    assert result.artifact_size == pdf_path.stat().st_size
    assert len(result.artifact_sha256) == 64


@pytest.mark.parametrize("content", [b"", b"not-a-pdf"])
def test_validator_rejects_empty_or_invalid_pdf(tmp_path: Path, content: bytes) -> None:
    pdf_path = tmp_path / "invalid.pdf"
    pdf_path.write_bytes(content)

    with pytest.raises(PdfValidationError):
        validate_pdf(pdf_path)


def test_registry_routes_all_portal_extensions() -> None:
    registry = PdfConverterRegistry()

    assert registry.group_for_extension("pdf") == "pdf"
    for extension in ("doc", "docx", "ppt", "pptx", "xls", "xlsx", "csv"):
        assert registry.group_for_extension(extension) == "office"
    for extension in ("txt", "md", "html"):
        assert registry.group_for_extension(extension) == "text_web"
    for extension in ("png", "jpg", "jpeg"):
        assert registry.group_for_extension(extension) == "image"
    with pytest.raises(PdfConversionError):
        registry.group_for_extension("bmp")


def test_text_and_html_are_normalized_without_active_content(tmp_path: Path) -> None:
    converter = TextWebPdfConverter()
    text_path = tmp_path / "source.txt"
    text_path.write_text("第一行\n  <script>alert(1)</script>\n长文本", encoding="utf-8")
    html_path = tmp_path / "source.html"
    html_path.write_text(
        '<script>alert(1)</script><img src="file:///etc/passwd"><p onclick="x()">正文</p>',
        encoding="utf-8",
    )

    text_html = converter.build_html(text_path, "txt")
    sanitized_html = converter.build_html(html_path, "html")

    assert "white-space: pre-wrap" in text_html
    assert "第一行\n  &lt;script&gt;" in text_html
    assert "<script" not in sanitized_html
    assert "file:///etc/passwd" not in sanitized_html
    assert "onclick=" not in sanitized_html
    assert "正文" in sanitized_html


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://example.com/a.png", False),
        ("http://127.0.0.1/private", False),
        ("file:///etc/passwd", False),
        ("data:image/png;base64,AAAA", True),
        ("about:blank", True),
    ],
)
def test_browser_request_policy_blocks_network_and_local_files(url: str, allowed: bool) -> None:
    assert _browser_request_is_allowed(url) is allowed


def test_image_converter_preserves_orientation_and_produces_valid_pdf(
    tmp_path: Path,
) -> None:
    source = tmp_path / "wide.png"
    Image.new("RGB", (800, 400), "red").save(source)

    result = ImagePdfConverter().convert(
        source,
        tmp_path / "out",
        ConversionContext(timeout_seconds=30, max_image_pixels=1_000_000),
    )
    metadata = validate_pdf(result.pdf_path)

    assert result.converter == "pillow"
    assert metadata.page_count == 1
    with fitz.open(result.pdf_path) as document:
        assert document[0].rect.width > document[0].rect.height


def test_image_converter_rejects_pixel_limit(tmp_path: Path) -> None:
    source = tmp_path / "large.jpg"
    Image.new("RGB", (101, 101), "blue").save(source)

    with pytest.raises(PdfConversionError, match="pixel"):
        ImagePdfConverter().convert(
            source,
            tmp_path / "out",
            ConversionContext(timeout_seconds=30, max_image_pixels=10_000),
        )


def test_office_converter_uses_argument_array_and_minimal_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.docx"
    source.write_bytes(b"fake-office")
    captured: dict = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        output_path = Path(command[command.index("--outdir") + 1]) / "source.pdf"
        _write_pdf(output_path)

        class Result:
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("bisheng.knowledge.pdf.converter.get_libreoffice_path", lambda: "/usr/bin/soffice")
    monkeypatch.setattr("bisheng.knowledge.pdf.converter.subprocess.run", fake_run)

    result = OfficePdfConverter().convert(
        source,
        tmp_path / "out",
        ConversionContext(timeout_seconds=45),
    )

    assert result.pdf_path.exists()
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["timeout"] == 45
    assert "--headless" in captured["command"]
    assert "--safe-mode" in captured["command"]
    environment = captured["kwargs"]["env"]
    assert "DATABASE_URL" not in environment
    assert "BS_MINIO_SECRET_KEY" not in environment
    assert set(environment) <= {
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "TMPDIR",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "SAL_USE_VCLPLUGIN",
    }
