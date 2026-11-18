"""Server-side upload format/size policy: the gate every entry re-applies."""

from types import SimpleNamespace

import pytest

from bisheng.common.errcode.knowledge_space import SpaceFileFormatError, SpaceFileSizeLimitError
from bisheng.knowledge.domain import upload_file_size
from bisheng.knowledge.domain.upload_policy import (
    is_supported_upload_filename,
    validate_knowledge_upload_file,
    validate_knowledge_upload_file_format,
)

SETTINGS = {"uploaded_files_maximum_size": 50, "uploaded_media_maximum_size": 1024}


@pytest.fixture
def env_settings(monkeypatch):
    """Patch the module-level settings proxy; the real one is a pydantic model."""
    monkeypatch.setattr(upload_file_size, "settings", SimpleNamespace(get_from_db=lambda key: SETTINGS))


@pytest.mark.parametrize(
    "name",
    [
        "report.pdf",
        "REPORT.PDF",
        "report.docx",
        "report.doc",
        "notes.md",
        "page.html",
        "page.htm",
        "sheet.csv",
        "scan.png",
        "clip.mp4",
        "voice.mp3",
        "legacy.wps",
        "archived.ofd",
        "plain.txt",
    ],
)
def test_supported_extension_is_accepted(name):
    assert is_supported_upload_filename(name)
    validate_knowledge_upload_file_format(name)


@pytest.mark.parametrize(
    "name",
    ["payload.exe", "install.sh", "bundle.zip", "bundle.tar.gz", "README", "trailing.", None, ""],
)
def test_unsupported_extension_is_rejected(name):
    assert not is_supported_upload_filename(name)
    with pytest.raises(SpaceFileFormatError) as caught:
        validate_knowledge_upload_file_format(name)
    assert caught.value.code == 18026


def test_composed_gate_rejects_format_before_size(env_settings):
    with pytest.raises(SpaceFileFormatError):
        validate_knowledge_upload_file("payload.exe", 50 * 1024 * 1024 + 1)
    validate_knowledge_upload_file("report.pdf", 50 * 1024 * 1024)


def test_composed_gate_rejects_supported_format_over_limit(env_settings):
    with pytest.raises(SpaceFileSizeLimitError):
        validate_knowledge_upload_file("report.pdf", 50 * 1024 * 1024 + 1)


def test_unknown_size_still_checks_format():
    """A stream without a declared length must not slip an unsupported name through."""
    with pytest.raises(SpaceFileFormatError):
        validate_knowledge_upload_file("payload.exe", None)
    validate_knowledge_upload_file("report.pdf", None)


def test_media_uses_the_media_limit(env_settings):
    validate_knowledge_upload_file("clip.mp4", 1024 * 1024 * 1024)
    with pytest.raises(SpaceFileSizeLimitError):
        validate_knowledge_upload_file("clip.mp4", 1024 * 1024 * 1024 + 1)
