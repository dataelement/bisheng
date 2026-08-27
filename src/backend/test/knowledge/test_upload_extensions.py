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


def test_resolve_knowledge_upload_extensions_is_fixed_allowlist():
    allowed = resolve_knowledge_upload_extensions(image_parser_enabled=True)
    assert allowed == resolve_knowledge_upload_extensions(image_parser_enabled=False)
    assert allowed == {
        "pdf",
        "txt",
        "docx",
        "ppt",
        "pptx",
        "md",
        "xls",
        "xlsx",
        "doc",
        "html",
        "htm",
    }
    assert "csv" not in allowed
    assert "png" not in allowed
    assert "mp3" not in allowed
    assert "wps" not in allowed


@pytest.mark.parametrize(
    "file_name",
    [
        "安全管理制度.pdf",
        "report.docx",
        "notes.htm",
        "sheet.xlsx",
    ],
)
def test_validate_knowledge_upload_file_extension_accepts_platform_formats(file_name: str):
    validate_knowledge_upload_file_extension(file_name, image_parser_enabled=True)


@pytest.mark.parametrize(
    "file_name",
    [
        "archive.zip",
        "audio.mp3",
        "scan.png",
        "data.csv",
        "doc.wps",
    ],
)
def test_validate_knowledge_upload_file_extension_rejects_removed_formats(file_name: str):
    with pytest.raises(UnsupportedUploadFileExtensionError):
        validate_knowledge_upload_file_extension(file_name, image_parser_enabled=True)
