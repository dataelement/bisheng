import pytest

from bisheng.knowledge.domain.upload_extensions import (
    extract_upload_file_extension,
    resolve_knowledge_upload_extensions,
    validate_knowledge_upload_file_extension,
    UnsupportedUploadFileExtensionError,
)


def test_extract_upload_file_extension_normalizes_case():
    assert extract_upload_file_extension("report.PDF") == "pdf"
    assert extract_upload_file_extension(" notes.TXT ") == "txt"


def test_resolve_knowledge_upload_extensions_respects_image_parser_flag():
    with_images = resolve_knowledge_upload_extensions(image_parser_enabled=True)
    without_images = resolve_knowledge_upload_extensions(image_parser_enabled=False)

    assert "pdf" in with_images
    assert "mp3" in with_images
    assert "png" in with_images
    assert "png" not in without_images
    assert "pdf" in without_images
    assert "mp3" in without_images


@pytest.mark.parametrize(
    "file_name",
    [
        "安全管理制度.pdf",
        "report.docx",
        "audio.mp3",
    ],
)
def test_validate_knowledge_upload_file_extension_accepts_platform_formats(file_name: str):
    validate_knowledge_upload_file_extension(file_name, image_parser_enabled=True)


def test_validate_knowledge_upload_file_extension_rejects_unknown_format():
    with pytest.raises(UnsupportedUploadFileExtensionError):
        validate_knowledge_upload_file_extension("archive.zip", image_parser_enabled=True)


def test_validate_knowledge_upload_file_extension_rejects_images_when_parser_disabled():
    with pytest.raises(UnsupportedUploadFileExtensionError):
        validate_knowledge_upload_file_extension("scan.png", image_parser_enabled=False)
