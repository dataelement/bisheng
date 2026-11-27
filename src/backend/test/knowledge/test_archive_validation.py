import io
from pathlib import Path
import stat
import struct
import threading
import warnings
import zipfile

import pytest

from bisheng.knowledge.domain.services.archive_validation import (
    ArchiveValidationError, expand_archive, normalized_path,
)


def archive(items):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
        for name, payload in items:
            z.writestr(name, payload)
    stream.seek(0)
    return stream


def expand(stream, tmp_path, allowed=None, stop=None):
    return expand_archive(stream, tmp_path, allowed or {"txt", "md", "pdf", "docx"}, 50*1024*1024, stop or threading.Event())


def test_nested_names_are_distinct_and_disk_names_are_generated(tmp_path):
    children, ignored = expand(archive([("空/", b""), ("合同/一.txt", "金额100元".encode()), ("财务/一.txt", "金额200元".encode()), ("合同/附件/说明.md", b"# note"), (".DS_Store", b"meta")]), tmp_path)
    assert [f.relative_path for f in children] == ["合同/一.txt", "财务/一.txt", "合同/附件/说明.md"]
    assert children[0].local_path.read_text() == "金额100元"
    assert len({f.file_id for f in children}) == 3
    assert all(f.local_path.parent == tmp_path and len(f.local_path.stem) == 32 for f in children)
    assert ignored == [".DS_Store"]


@pytest.mark.parametrize("name", ["../a.txt", "a/../../b.txt", "..\\a.txt", "/a.txt", "C:/a.txt", "a//b.txt", "a/./b.txt", "CON.txt", "a./b.txt", "a /b.txt", "a:x.txt", "a\x00b.txt", "a\x01b.txt", "/".join(["d"]*11)+"/a.txt"])
def test_unsafe_paths_are_rejected(name):
    with pytest.raises(ArchiveValidationError):
        normalized_path(name)


@pytest.mark.parametrize("names", [["a.txt", "a.txt"], ["A.txt", "a.txt"], ["é.txt", "e\u0301.txt"], ["a.txt", "a.txt/b.txt"], ["a.txt/b.txt", "a.txt"]])
def test_collisions_fail_before_writing(tmp_path, names):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        stream = archive([(name, b"text") for name in names])
    with pytest.raises(ArchiveValidationError):
        expand(stream, tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name,payload", [("run.exe", b"MZ"), ("inside.zip", b"PK"), ("fake.pdf", b"not pdf"), ("fake.txt", b"MZbinary"), ("fake.docx", b"not zip"), ("empty.txt", b"")])
def test_unsupported_and_disguised_content(tmp_path, name, payload):
    with pytest.raises(ArchiveValidationError):
        expand(archive([(name, payload)]), tmp_path)


def test_image_only_policy_cannot_expand_documents(tmp_path):
    with pytest.raises(ArchiveValidationError):
        expand(archive([("a.pdf", b"%PDF-1.7")]), tmp_path, {"png"})


def test_office_is_a_document_not_a_nested_user_archive(tmp_path):
    docx = archive([("word/document.xml", b"<document/>")]).getvalue()
    children, _ = expand(archive([("合同.docx", docx)]), tmp_path)
    assert children[0].local_path.read_bytes() == docx


def test_symlink(tmp_path):
    info = zipfile.ZipInfo("link.txt")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ArchiveValidationError):
        expand(archive([(info, b"/etc/passwd")]), tmp_path)


def test_high_ratio_small_fixture(tmp_path):
    with pytest.raises(ArchiveValidationError):
        expand(archive([("a.txt", b"0"*1024*1024)]), tmp_path)


def test_file_count_preflight(tmp_path):
    with pytest.raises(ArchiveValidationError):
        expand(archive([(f"{i}.txt", b"x") for i in range(21)]), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_cancelled_expansion_writes_nothing(tmp_path):
    stop = threading.Event()
    stop.set()
    with pytest.raises(ArchiveValidationError):
        expand(archive([("a.txt", b"x")]), tmp_path, stop=stop)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mode", ["crc", "encrypted"])
def test_corrupted_crc_and_encrypted_flag(tmp_path, mode):
    data = bytearray(archive([("a.txt", b"hello")]).getvalue())
    central = data.index(b"PK\x01\x02")
    if mode == "crc":
        struct.pack_into("<I", data, central+16, 1)
    else:
        struct.pack_into("<H", data, central+8, 1)
    with pytest.raises(ArchiveValidationError):
        expand(io.BytesIO(data), tmp_path)


def test_per_file_actual_limit(tmp_path):
    with pytest.raises(ArchiveValidationError):
        expand_archive(archive([("a.txt", b"123456")]), tmp_path, {"txt"}, 5, threading.Event())


def test_empty_zip(tmp_path):
    with pytest.raises(ArchiveValidationError):
        expand(archive([]), tmp_path)
