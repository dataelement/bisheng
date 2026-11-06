"""本地目录后端 —— `bisheng dev` 期的附件空间（AC-20 / 21 / 22 / 23 / 24 / 25）。"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import pytest

from bisheng_sdk import storage
from bisheng_sdk.errors import (
    AttachmentNotFoundError,
    AttachmentTooLargeError,
    InvalidAttachmentPathError,
    StorageHandleMissingError,
)


@pytest.fixture
def local_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`bisheng dev` 今天还没注入 `BISHENG_APP_STORAGE_DIR`，用例自己造句柄。"""
    root = tmp_path / "attachments"
    monkeypatch.setenv("BISHENG_APP_STORAGE_DIR", str(root))
    return root


def test_no_handle_at_all_is_an_error_not_a_temp_dir():
    with pytest.raises(StorageHandleMissingError):
        storage.put("a.txt", b"x")


def test_both_handles_is_refused_rather_than_guessed(local_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BISHENG_APP_STORAGE_ENDPOINT", "http://manager.test/v1/apps/app-1/storage")
    monkeypatch.setenv("BISHENG_APP_STORAGE_TOKEN", "t")
    with pytest.raises(StorageHandleMissingError) as caught:
        storage.put("a.txt", b"x")
    assert "无法判断" in str(caught.value)


def test_roundtrip_put_stat_list_get_delete(local_dir: Path):
    meta = storage.put("报告/2026.pdf", b"hello world")
    assert meta.path == "报告/2026.pdf"
    assert meta.size == 11
    assert meta.content_type == "application/pdf"
    assert isinstance(meta.modified_at, datetime)

    assert storage.stat("报告/2026.pdf").size == 11
    assert storage.get("报告/2026.pdf") == b"hello world"
    with storage.open("报告/2026.pdf") as handle:
        assert handle.read() == b"hello world"

    storage.put("其它/x.txt", b"x")
    rows = storage.list("报告/")
    assert [row.path for row in rows] == ["报告/2026.pdf"]
    assert [row.path for row in storage.list()] == ["其它/x.txt", "报告/2026.pdf"]

    storage.delete("报告/2026.pdf")
    with pytest.raises(AttachmentNotFoundError):
        storage.get("报告/2026.pdf")


@pytest.mark.parametrize("payload", [b"hello world", io.BytesIO(b"hello world"), "hello world"])
def test_put_accepts_bytes_file_objects_and_text(local_dir: Path, payload):
    assert storage.put("a.bin", payload).size == 11


def test_put_accepts_a_pathlike_source(local_dir: Path, tmp_path: Path):
    source = tmp_path / "src.bin"
    source.write_bytes(b"hello world")
    assert storage.put("a.bin", source).size == 11


def test_delete_of_a_missing_attachment_is_an_error(local_dir: Path):
    with pytest.raises(AttachmentNotFoundError):
        storage.delete("nope.txt")


def test_put_is_atomic_and_leaves_no_temp_file(local_dir: Path):
    class Exploding:
        def read(self, size: int = -1) -> bytes:
            raise OSError("disk gone")

    with pytest.raises(OSError):
        storage.put("a.bin", Exploding())
    assert list(local_dir.rglob("*")) == [] or all(not p.name.endswith(".bstmp") for p in local_dir.rglob("*"))
    with pytest.raises(AttachmentNotFoundError):
        storage.stat("a.bin")


def test_real_disk_location_never_reaches_the_app(local_dir: Path):
    meta = storage.put("报告/2026.pdf", b"x")
    assert str(local_dir) not in f"{meta}"
    with pytest.raises(AttachmentNotFoundError) as caught:
        storage.get("报告/missing.pdf")
    assert str(local_dir) not in str(caught.value)


def test_single_file_cap_applies_locally_when_injected(local_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BISHENG_APP_STORAGE_MAX_FILE_MB", "1")
    with pytest.raises(AttachmentTooLargeError) as caught:
        storage.put("big.bin", b"x" * (1024 * 1024 + 1))
    assert caught.value.limit_bytes == 1024 * 1024
    # 拒绝而不是截断：什么都不该落盘。
    with pytest.raises(AttachmentNotFoundError):
        storage.stat("big.bin")


def test_without_the_cap_variable_local_is_unlimited(local_dir: Path):
    assert storage.put("big.bin", b"x" * (2 * 1024 * 1024)).size == 2 * 1024 * 1024


def test_invalid_path_never_touches_the_disk(local_dir: Path):
    with pytest.raises(InvalidAttachmentPathError):
        storage.put("../escape.txt", b"x")
    assert not local_dir.exists() or list(local_dir.rglob("*")) == []


def test_directory_is_created_lazily_on_first_put(local_dir: Path):
    assert not local_dir.exists()
    storage.put("a.txt", b"x")
    assert local_dir.is_dir()


def test_listing_an_empty_space_is_an_empty_list(local_dir: Path):
    assert storage.list() == []


def test_no_clear_or_prefix_delete_api():
    assert {"clear", "delete_prefix", "delete_many", "purge", "url", "presign", "share"}.isdisjoint(set(dir(storage)))
