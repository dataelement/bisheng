import struct
import zipfile

import fitz
import pytest
from openpyxl import Workbook

from bisheng.common.errcode.knowledge import KnowledgeSourceFileUnreadableError
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services.knowledge_source_file_validation import validate_sync_original


def sync_file(name):
    return KnowledgeFile(
        knowledge_id=9, file_name=name, user_metadata={"filelib_sync_endpoint": "sync", "developer_token_id": 12}
    )


@pytest.mark.parametrize("encrypted", [False, True])
def test_real_pdf_password_detection(tmp_path, encrypted):
    path = tmp_path / "original.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((40, 40), "original content")
        options = (
            {"encryption": fitz.PDF_ENCRYPT_AES_256, "owner_pw": "owner", "user_pw": "reader"} if encrypted else {}
        )
        document.save(path, **options)
    if encrypted:
        with pytest.raises(KnowledgeSourceFileUnreadableError) as caught:
            validate_sync_original(str(path), sync_file(path.name))
        assert caught.value.kwargs["reason"] == "encrypted"
    else:
        validate_sync_original(str(path), sync_file(path.name))


def encrypted_office_container():
    # 合成标准 OLE 目录与两个加密包装流, 使用真实 xlrd 容器读取。
    header = bytearray(512)
    header[:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<HHHHH", header, 24, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<iiiiiiii", header, 44, 1, 1, 0, 4096, -2, 0, -2, 0)
    struct.pack_into("<109i", header, 76, 0, *([-1] * 108))
    fat = [-1] * 128
    fat[0], fat[1] = -3, -2
    for start in (2, 10):
        for index in range(start, start + 7):
            fat[index] = index + 1
        fat[start + 7] = -2

    def directory(name, kind, child=-1, right=-1, first=-2, size=0):
        entry = bytearray(128)
        encoded = (name + "\0").encode("utf-16le")
        entry[: len(encoded)] = encoded
        struct.pack_into("<HBBiii", entry, 64, len(encoded), kind, 1, -1, right, child)
        struct.pack_into("<iQ", entry, 116, first, size)
        return entry

    entries = directory("Root Entry", 5, child=1)
    entries += directory("EncryptionInfo", 2, right=2, first=2, size=4096)
    entries += directory("EncryptedPackage", 2, first=10, size=4096)
    entries += bytearray(128)
    return bytes(header) + struct.pack("<128i", *fat) + entries + bytes(8192)


@pytest.mark.parametrize("extension", ["docx", "xlsx", "pptx"])
def test_office_encryption_container_is_recognized(tmp_path, extension):
    path = tmp_path / f"protected.{extension}"
    path.write_bytes(encrypted_office_container())
    with pytest.raises(KnowledgeSourceFileUnreadableError) as caught:
        validate_sync_original(str(path), sync_file(path.name))
    assert caught.value.kwargs["reason"] == "encrypted"


@pytest.mark.parametrize("content", [b"broken", b"PK\x03\x04truncated", b""])
def test_broken_office_package_is_not_generic_service_failure(tmp_path, content):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(content)
    with pytest.raises(KnowledgeSourceFileUnreadableError) as caught:
        validate_sync_original(str(path), sync_file(path.name))
    assert caught.value.kwargs["reason"] == "damaged"


def test_workbook_and_missing_file_and_manual_upload(tmp_path):
    path = tmp_path / "readable.xlsx"
    workbook = Workbook()
    workbook.active.append(["original", 1])
    workbook.save(path)
    validate_sync_original(str(path), sync_file(path.name))
    with pytest.raises(OSError):
        validate_sync_original(str(tmp_path / "missing.xlsx"), sync_file("missing.xlsx"))
    broken = tmp_path / "manual.pdf"
    broken.write_bytes(b"unreadable")
    manual = sync_file(broken.name)
    manual.user_metadata = {}
    validate_sync_original(str(broken), manual)


def test_office_xml_damage(tmp_path):
    path = tmp_path / "broken.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document>unterminated")
    with pytest.raises(KnowledgeSourceFileUnreadableError):
        validate_sync_original(str(path), sync_file(path.name))


def test_validation_budget_does_not_mean_file_damage(tmp_path, monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_source_file_validation as module

    path = tmp_path / "large.xlsx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.xml", "x" * 10000)
    monkeypatch.setattr(module, "_MAX_VALIDATION_BYTES", 1000)
    validate_sync_original(str(path), sync_file(path.name))
