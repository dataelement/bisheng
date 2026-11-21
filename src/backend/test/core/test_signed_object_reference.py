"""Offline signed-object capabilities; no storage/network I/O."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import urlsplit

import pytest
from minio import Minio

from bisheng.core.cache import utils
from bisheng.core.storage import chat_attachment
from bisheng.core.storage.minio.signed_reference import verify_signed_reference


@pytest.fixture
def storage():
    config = SimpleNamespace(access_key="fixture-access", secret_key="fixture-secret")
    return SimpleNamespace(
        bucket="bisheng",
        tmp_bucket="tmp-dir",
        minio_config=config,
        get_minio_share_host=lambda: "https://storage.invalid:9000",
        minio_client_sync=SimpleNamespace(get_object=Mock(return_value=BytesIO(b"fixture"))),
        download_object_sync=Mock(return_value=BytesIO(b"fixture")),
        copy_object=AsyncMock(),
        copy_object_sync=Mock(),
    )


def signed(storage, *, bucket="bisheng", key="original/test document.txt", date=None, expires=600, **kwargs):
    client = Minio(
        "storage.invalid:9000",
        access_key=storage.minio_config.access_key,
        secret_key=storage.minio_config.secret_key,
        secure=True,
        region="us-east-1",
    )
    return client.get_presigned_url(
        "GET", bucket, key, expires=timedelta(seconds=expires), request_date=date or datetime.now(UTC), **kwargs
    )


@pytest.mark.parametrize("prefix", ["", "/object", "/workspace/object"])
@pytest.mark.parametrize("bucket", ["bisheng", "tmp-dir"])
def test_valid_presign_absolute_and_browser_paths(storage, prefix, bucket):
    url = signed(storage, bucket=bucket)
    if prefix:
        parsed = urlsplit(url)
        url = prefix + parsed.path + "?" + parsed.query
    result = verify_signed_reference(url, storage)
    assert (result.bucket, result.object_name) == (bucket, "original/test document.txt")


@pytest.mark.parametrize("key", ["original/报告.pdf", "original/literal%20.txt", "tenant_child/file+name.txt"])
def test_exact_encoded_key_and_signed_response_query(storage, key):
    url = signed(
        storage,
        key=key,
        version_id="version-1",
        response_headers={"response-content-disposition": "attachment; filename=test.txt"},
    )
    reference = verify_signed_reference(url, storage)
    assert reference.object_name == key
    assert reference.version_id == "version-1"
    with pytest.raises(ValueError):
        verify_signed_reference(url.replace("version-1", "version-2"), storage)


@pytest.mark.parametrize(
    "change",
    [
        "unsigned",
        "algorithm",
        "path",
        "host",
        "date",
        "expires",
        "duplicate",
        "extra",
        "headers",
        "credential",
        "expired",
        "future",
    ],
)
def test_tampered_or_stale_presign_denied(storage, change):
    now = datetime.now(UTC)
    url = signed(storage, date=now)
    if change == "unsigned":
        url = url.split("?", 1)[0]
    elif change == "expired":
        url = signed(storage, date=now - timedelta(hours=1), expires=60)
    elif change == "future":
        url = signed(storage, date=now + timedelta(hours=1))
    elif change == "path":
        url = url.replace("test%20document", "other")
    elif change == "host":
        url = url.replace("storage.invalid", "foreign.invalid")
    elif change == "duplicate":
        url += "&X-Amz-Expires=600"
    elif change == "extra":
        url += "&response-content-type=text/plain"
    else:
        tokens = {
            "algorithm": ("AWS4-HMAC-SHA256", "AWS4"),
            "date": (now.strftime("%Y%m%dT%H%M%S"), "20000101T000000"),
            "expires": ("X-Amz-Expires=600", "X-Amz-Expires=601"),
            "headers": ("SignedHeaders=host", "SignedHeaders=host%3Bx-test"),
            "credential": ("fixture-access", "other-access"),
        }
        before, after = tokens[change]
        url = url.replace(before, after)
    with pytest.raises(ValueError):
        verify_signed_reference(url, storage, now=now)


@pytest.mark.parametrize(
    "reference", ["https://storage.invalid:9000/bisheng/foreign.txt", "/bisheng/foreign.txt?X-Amz-Algorithm=fake"]
)
def test_unverified_reference_never_reaches_sdk(monkeypatch, storage, reference):
    monkeypatch.setattr(utils, "get_minio_storage_sync", lambda: storage)
    monkeypatch.setattr(utils, "save_download_file", Mock(return_value="mock-cache"))
    with pytest.raises(ValueError):
        utils.file_download(reference)
    storage.minio_client_sync.get_object.assert_not_called()
    storage.download_object_sync.assert_not_called()


async def test_valid_presign_downloads_exact_signed_key_without_root_fallback(monkeypatch, storage):
    monkeypatch.setattr(utils, "get_minio_storage_sync", lambda: storage)
    monkeypatch.setattr(utils, "save_download_file", Mock(return_value="mock-cache"))
    url = signed(storage, key="tenant_child/original/file.txt")
    assert (await utils.async_file_download(url))[1] == "file.txt"
    storage.minio_client_sync.get_object.assert_called_once_with(
        "bisheng", "tenant_child/original/file.txt", version_id=None
    )
    storage.download_object_sync.assert_not_called()


def test_missing_signed_child_object_never_retries_root(monkeypatch, storage):
    monkeypatch.setattr(utils, "get_minio_storage_sync", lambda: storage)
    storage.minio_client_sync.get_object.side_effect = ValueError("not found")
    with pytest.raises(ValueError, match="not found"):
        utils.file_download(signed(storage, key="tenant_child/original/missing.txt"))
    assert storage.minio_client_sync.get_object.call_count == 1
    storage.download_object_sync.assert_not_called()


async def test_object_name_decoy_does_not_authorize_consumed_filepath(monkeypatch, storage):
    from bisheng.chat_session.domain.session_subject import SessionSubject
    from bisheng.knowledge.domain.services.temp_upload_service import TempUploadService

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.temp_upload_service.get_minio_storage", AsyncMock(return_value=storage)
    )
    subject = SessionSubject.natural_person(tenant_id=1, user_id=7)
    files = [{"object_name": "chat/7/decoy.txt", "filepath": signed(storage, key="original/foreign.txt")}]
    with pytest.raises(Exception) as denied:
        await TempUploadService.assert_owned_references(files, subject)
    assert denied.value.status_code == 404


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_promotion_rejects_unsigned_foreign_source(monkeypatch, storage, asynchronous):
    monkeypatch.setattr(chat_attachment, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(chat_attachment, "get_minio_storage_sync", lambda: storage)
    files = [{"filepath": "/tmp-dir/foreign/file.txt?X-Amz-Algorithm=fake", "filename": "file.txt"}]
    if asynchronous:
        await chat_attachment.promote_chat_attachments(files, 7)
    else:
        chat_attachment.promote_chat_attachments_sync(files, 7)
    storage.copy_object.assert_not_awaited()
    storage.copy_object_sync.assert_not_called()
    assert "object_name" not in files[0]


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_promotion_preserves_valid_source_capability(monkeypatch, storage, asynchronous):
    monkeypatch.setattr(chat_attachment, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(chat_attachment, "get_minio_storage_sync", lambda: storage)
    files = [{"filepath": signed(storage, bucket="tmp-dir", key="uploads/7/file.txt"), "filename": "file.txt"}]
    if asynchronous:
        await chat_attachment.promote_chat_attachments(files, 7)
        assert storage.copy_object.await_args.kwargs["source_object"] == "uploads/7/file.txt"
    else:
        chat_attachment.promote_chat_attachments_sync(files, 7)
        assert storage.copy_object_sync.call_args.kwargs["source_object"] == "uploads/7/file.txt"
    assert files[0]["object_name"].startswith("chat/7/")
