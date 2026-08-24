from io import BytesIO

from PIL import Image

from bisheng.qa_expert.domain.watermarked_download import (
    QaWatermarkDownloadError,
    _bytes_to_pdf,
    parse_qa_asset_location,
    resolve_conversion_filename,
)


def test_parse_permanent_qa_object_and_tmp_uuid():
    assert parse_qa_asset_location(
        "https://minio:9000/bisheng/qa-expert/1/question/attachment/a/a.pdf?X-Amz-Signature=1",
        default_bucket="bisheng",
        tmp_bucket="tmp-dir",
    ) == ("bisheng", "qa-expert/1/question/attachment/a/a.pdf")
    assert (
        parse_qa_asset_location(
            "/tmp-dir/abcd1234-ef.png?X-Amz-Expires=1",
            default_bucket="bisheng",
            tmp_bucket="tmp-dir",
        )[0]
        == "tmp-dir"
    )
    assert parse_qa_asset_location(
        "/workspace/bisheng/qa-expert/1/question/image/u/abc.png?X-Amz-Signature=1",
        default_bucket="bisheng",
        tmp_bucket="tmp-dir",
    ) == ("bisheng", "qa-expert/1/question/image/u/abc.png")


def test_parse_rejects_unrelated_paths():
    try:
        parse_qa_asset_location("https://evil.example/etc/passwd", default_bucket="bisheng", tmp_bucket="tmp-dir")
        raise AssertionError("expected error")
    except ValueError:
        pass


def test_resolve_conversion_filename_falls_back_to_object_suffix():
    assert resolve_conversion_filename("问题图片 1", "qa-expert/1/question/image/u/deadbeef.webp") == (
        "问题图片 1.webp"
    )
    assert resolve_conversion_filename("photo.png", "qa-expert/1/question/image/u/deadbeef.webp") == "photo.png"
    assert resolve_conversion_filename("", "qa-expert/1/question/image/u/deadbeef.jpg") == "deadbeef.jpg"


def _image_bytes(fmt: str) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (24, 24), (12, 34, 56)).save(buf, format=fmt)
    return buf.getvalue()


def test_bytes_to_pdf_accepts_display_title_without_extension():
    png = _image_bytes("PNG")
    pdf = _bytes_to_pdf(png, "问题图片 1")
    assert pdf[:5] == b"%PDF-"


def test_bytes_to_pdf_converts_webp_via_pillow_fallback():
    webp = _image_bytes("WEBP")
    pdf = _bytes_to_pdf(webp, "问题图片 1.webp")
    assert pdf[:5] == b"%PDF-"
    # 详情页标题无后缀时，靠 sniff + Pillow
    pdf2 = _bytes_to_pdf(webp, "问题图片 1")
    assert pdf2[:5] == b"%PDF-"


def test_bytes_to_pdf_converts_markdown_without_docx_converter(monkeypatch):
    """`.md` 不得再误走 convert_docx_to_pdf（其只接受 doc/docx，会返回 False 并 500）。"""
    calls: list[str] = []

    def _forbid_docx(*_args, **_kwargs):
        calls.append("docx")
        raise AssertionError("must not call convert_docx_to_pdf for markdown")

    monkeypatch.setattr(
        "bisheng.knowledge.rag.pipeline.loader.utils.libreoffice_converter.convert_docx_to_pdf",
        _forbid_docx,
        raising=False,
    )

    # 强制走纯文本回退，避免单测依赖本机 Playwright/Chromium
    def _fail_registry(*_args, **_kwargs):

        raise QaWatermarkDownloadError("playwright unavailable in unit test")

    monkeypatch.setattr(
        "bisheng.qa_expert.domain.watermarked_download._convert_via_pdf_registry",
        _fail_registry,
    )

    md = "# 标题\n\n工作流与智能体功能清单\n".encode()
    pdf = _bytes_to_pdf(md, "工作流与智能体功能清单-实现方案.md")
    assert pdf[:5] == b"%PDF-"
    assert calls == []


def test_bytes_to_pdf_converts_plain_text_via_fallback(monkeypatch):
    def _fail_registry(*_args, **_kwargs):
        raise QaWatermarkDownloadError("no chromium")

    monkeypatch.setattr(
        "bisheng.qa_expert.domain.watermarked_download._convert_via_pdf_registry",
        _fail_registry,
    )
    pdf = _bytes_to_pdf("hello\n第二行".encode(), "note.txt")
    assert pdf[:5] == b"%PDF-"
