"""Issuing a browser object URL stays on the fixed /object prefix."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bisheng.common.errcode.storage import BrowserObjectBucketError
from bisheng.core.storage.browser_object_path import browser_bucket_allowed
from bisheng.core.storage.minio.minio_storage import MinioStorage


class _Storage:
    bucket = "bisheng"
    tmp_bucket = "tmp-dir"
    get_minio_share_host = MinioStorage.get_minio_share_host
    clear_minio_share_host = MinioStorage.clear_minio_share_host

    def __init__(self):
        self.share_minio_client = MagicMock()
        self.share_minio_client.presigned_get_object.return_value = (
            "http://minio:9000/bisheng/original/4.pdf?X-Amz-Signature=abc"
        )
        self.minio_config = SimpleNamespace(sharepoint="minio:9000", share_schema=False)


def _storage() -> _Storage:
    return _Storage()


def test_empty_bucket_is_not_allowed():
    assert browser_bucket_allowed("", "bisheng", "tmp-dir") is False
    assert browser_bucket_allowed("  ", "bisheng", "tmp-dir") is False
    assert browser_bucket_allowed("bisheng", "bisheng", "tmp-dir") is True
    assert browser_bucket_allowed("other", "bisheng", "tmp-dir") is False


def test_browser_share_link_uses_the_object_prefix():
    storage = _storage()
    url = MinioStorage.get_share_link_sync(storage, "original/4.pdf")
    assert url == "/object/bisheng/original/4.pdf?X-Amz-Signature=abc"


def test_temp_bucket_share_link_uses_the_object_prefix():
    storage = _storage()
    storage.share_minio_client.presigned_get_object.return_value = "http://minio:9000/tmp-dir/a.mp3?X-Amz-Signature=abc"
    url = MinioStorage.get_share_link_sync(storage, "a.mp3", bucket="tmp-dir")
    assert url == "/object/tmp-dir/a.mp3?X-Amz-Signature=abc"


def test_other_bucket_is_not_signed_for_the_browser():
    storage = _storage()
    with pytest.raises(BrowserObjectBucketError):
        MinioStorage.get_share_link_sync(storage, "apps/1/a.pdf", bucket="bisheng-apps")
    storage.share_minio_client.presigned_get_object.assert_not_called()


def test_full_host_link_keeps_the_share_host():
    storage = _storage()
    storage.share_minio_client.presigned_get_object.return_value = (
        "http://minio:9000/bisheng-apps/apps/1/a.pdf?X-Amz-Signature=abc"
    )
    url = MinioStorage.get_share_link_sync(storage, "apps/1/a.pdf", bucket="bisheng-apps", clear_host=False)
    assert url == "http://minio:9000/bisheng-apps/apps/1/a.pdf?X-Amz-Signature=abc"
