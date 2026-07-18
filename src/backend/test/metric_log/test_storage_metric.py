"""Object-storage metric wiring tests (F042 T006).

Covers ``_classify_storage_exc`` (ok / error / excluded per design 决策 4) and
proves the ``_storage_metric`` aspect is wired into the leaf I/O methods
(put_object_sync / get_object_sync / download_object_sync). Contract: design §6.1.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from loguru import logger
from minio.error import S3Error

from bisheng.core.storage.minio.minio_storage import (
    MinioStorage,
    _classify_storage_exc,
)


@contextmanager
def capture_metric_logs():
    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(str(m).rstrip("\n")), level="INFO", format="{message}")
    try:
        yield messages
    finally:
        logger.remove(sink_id)


def _line_for(messages, domain):
    prefix = f"BS_METRIC domain={domain}"
    for m in messages:
        if m == prefix or m.startswith(prefix + " "):
            return m
    return None


def _s3error(code, status):
    return S3Error(
        code=code,
        message="msg",
        resource="/bucket/key",
        request_id="req",
        host_id="host",
        response=MagicMock(status=status, headers={}),
        bucket_name="bisheng",
        object_name="obj",
    )


def _make_storage():
    storage = MinioStorage.__new__(MinioStorage)
    storage.bucket = "bisheng"
    storage.tmp_bucket = "tmp-dir"
    storage.minio_client_sync = MagicMock()
    return storage


# ---------------------------------------------------------------------------
# _classify_storage_exc
# ---------------------------------------------------------------------------


def test_classify_nosuchkey_is_ok():
    result, status, code = _classify_storage_exc(_s3error("NoSuchKey", 404))
    assert result == "ok" and code == "NoSuchKey"


@pytest.mark.parametrize("code,status", [("AccessDenied", 403), ("SignatureDoesNotMatch", 403), ("ExpiredToken", 401)])
def test_classify_auth_expiry_is_excluded(code, status):
    result, http_status, err_code = _classify_storage_exc(_s3error(code, status))
    assert result == "excluded"
    assert http_status == status and err_code == code


@pytest.mark.parametrize("code,status", [("InternalError", 500), ("SlowDown", 503)])
def test_classify_server_errors_are_error(code, status):
    result, http_status, err_code = _classify_storage_exc(_s3error(code, status))
    assert result == "error" and http_status == status


def test_classify_non_s3_exception_is_error():
    result, http_status, err_code = _classify_storage_exc(TimeoutError("read timed out"))
    assert result == "error" and err_code == "TimeoutError"


def test_classify_fallback_miss_is_ok():
    from bisheng.common.errcode.tenant_sharing import StorageSharingFallbackError

    result, _, _ = _classify_storage_exc(StorageSharingFallbackError())
    assert result == "ok"  # genuine cross-tenant miss: storage worked, object absent


# ---------------------------------------------------------------------------
# Aspect wired into the leaf I/O methods
# ---------------------------------------------------------------------------


def test_put_object_sync_success_emits_ok():
    storage = _make_storage()
    with capture_metric_logs() as messages:
        storage.put_object_sync(object_name="x", file=b"payload")
    line = _line_for(messages, "obj_storage")
    assert line is not None
    assert "op=put" in line and "result=ok" in line and "elapsed_ms=" in line


def test_put_object_sync_server_error_emits_error_and_reraises():
    storage = _make_storage()
    storage.minio_client_sync.put_object.side_effect = _s3error("InternalError", 500)
    with capture_metric_logs() as messages:
        with pytest.raises(S3Error):
            storage.put_object_sync(object_name="x", file=b"payload")
    line = _line_for(messages, "obj_storage")
    assert line is not None
    assert "op=put" in line and "result=error" in line and "http_status=500" in line


def test_get_object_sync_success_emits_ok():
    storage = _make_storage()
    response = MagicMock()
    response.read.return_value = b"data"
    storage.minio_client_sync.get_object.return_value = response
    with capture_metric_logs() as messages:
        storage.get_object_sync(object_name="x")
    line = _line_for(messages, "obj_storage")
    assert line is not None
    assert "op=get" in line and "result=ok" in line


def test_download_object_sync_success_emits_ok():
    storage = _make_storage()
    storage.minio_client_sync.get_object.return_value = MagicMock()
    with capture_metric_logs() as messages:
        storage.download_object_sync(object_name="x")
    line = _line_for(messages, "obj_storage")
    assert line is not None
    assert "op=get" in line and "result=ok" in line
