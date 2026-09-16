"""路径规则 —— manager `validate_key` / `validate_prefix` 的逐条镜像（AC-20 / AC-21）。"""

from __future__ import annotations

import pytest

from bisheng_sdk import _paths
from bisheng_sdk.errors import InvalidAttachmentPathError


@pytest.mark.parametrize(
    "path",
    [
        "",
        "../a",
        "a/../b",
        "/abs",
        "a//b",
        "a/./b",
        "a\\b",
        ".",
        "..",
        "a/",
        "a\x00b",
        "a\nb",
        "a\x7fb",
        "x" * 1025,
        "apps/app-1/attachments/a.txt",
        "apps/",
    ],
)
def test_rejected_paths(path: str):
    with pytest.raises(InvalidAttachmentPathError):
        _paths.validate(path)


def test_rejection_is_not_normalisation():
    """`a/../b` 是拒绝，不是"给你 b"——写出它的应用几乎肯定想越界。"""
    with pytest.raises(InvalidAttachmentPathError) as caught:
        _paths.validate("a/../b")
    assert "b" != getattr(caught.value, "path", None) or caught.value.path == "a/../b"


@pytest.mark.parametrize("path", ["a.txt", "报告/2026 年度.pdf", "a/b/c.bin", "x" * 1024])
def test_accepted_paths(path: str):
    assert _paths.validate(path) == path


@pytest.mark.parametrize("prefix", ["", "报告/", "报告", "a/b"])
def test_prefix_allows_empty_and_trailing_slash(prefix: str):
    assert _paths.validate_prefix(prefix) == prefix


@pytest.mark.parametrize("prefix", ["apps/", "/abs/", "../x/"])
def test_prefix_follows_the_same_rules(prefix: str):
    with pytest.raises(InvalidAttachmentPathError):
        _paths.validate_prefix(prefix)


def test_max_key_bytes_is_counted_in_utf8():
    # 1024 字节，不是 1024 个字符：三字节的汉字 342 个就到顶了。
    assert _paths.validate("中" * 341)
    with pytest.raises(InvalidAttachmentPathError):
        _paths.validate("中" * 342)
