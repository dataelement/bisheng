from __future__ import annotations

import pytest

from bisheng.developer_token.domain.file_sync_folder_path import (
    normalize_file_sync_folder_path,
    split_file_sync_folder_path,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("政策文件/管理制度", "政策文件/管理制度"),
        (" 政策文件 / 管理制度 ", "政策文件/管理制度"),
        ("政策文件\\管理制度", "政策文件/管理制度"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_file_sync_folder_path(raw, expected) -> None:
    assert normalize_file_sync_folder_path(raw) == expected


def test_split_file_sync_folder_path() -> None:
    assert split_file_sync_folder_path("政策文件/管理制度") == ["政策文件", "管理制度"]


def test_normalize_rejects_invalid_segments() -> None:
    with pytest.raises(ValueError):
        normalize_file_sync_folder_path("a/../b")
