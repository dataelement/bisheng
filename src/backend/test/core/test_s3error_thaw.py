"""Storage layer: thaw minio's frozen S3Error so it can't mask the real error.

minio>=7.2 ships ``S3Error`` as a ``@dataclass(frozen=True)``. When such an
exception escapes the storage layer and propagates far enough that a framework
reassigns ``__traceback__`` (anyio's threadpool re-raise on ``run_in_threadpool``,
the ASGI error handler), the frozen ``__setattr__`` raises
``FrozenInstanceError: cannot assign to field '__traceback__'``. That secondary
error replaces the original (e.g. a NoSuchKey miss), so the real stack and the
real S3 code are lost — observed in production on ``POST .../space/{id}/files``.

The fix re-raises a *non-frozen mirror* of the S3Error at the storage boundary:
still ``isinstance(_, S3Error)`` (so every ``except S3Error`` / NoSuchKey check
downstream keeps working) but with a normal ``__setattr__`` so the real error
survives with an intact traceback.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest
from minio.error import S3Error

from bisheng.core.storage.minio.minio_storage import (
    MinioStorage,
    _is_no_such_key_error,
    _thaw_s3_error,
)


def _nosuchkey_exc() -> S3Error:
    return S3Error(
        code="NoSuchKey",
        message="Object not found",
        resource="/bucket/key",
        request_id="req",
        host_id="host",
        response=MagicMock(status=404, headers={}),
        bucket_name="bisheng",
        object_name="569a92bade28471c94dd538bb0a73647.jpg",
    )


def _make_storage() -> MinioStorage:
    storage = MinioStorage.__new__(MinioStorage)
    storage.bucket = "bisheng"
    storage.tmp_bucket = "tmp-dir"
    storage.minio_client_sync = MagicMock()
    return storage


# ── the masking bug, captured ────────────────────────────────────


def test_raw_s3error_masks_traceback_assignment():
    """Document the production failure mode: a raw frozen S3Error rejects the
    ``__traceback__`` reassignment that anyio/ASGI does on re-raise, with the
    exact ``cannot assign to field '__traceback__'`` message seen in the logs."""
    frozen = _nosuchkey_exc()
    with pytest.raises(FrozenInstanceError, match="cannot assign to field '__traceback__'"):
        frozen.__traceback__ = None


# ── _thaw_s3_error ───────────────────────────────────────────────


def test_thaw_allows_traceback_reassignment():
    thawed = _thaw_s3_error(_nosuchkey_exc())
    # Must NOT raise — this is the whole point of the fix.
    thawed.__traceback__ = None


def test_thaw_preserves_s3error_type_and_fields():
    frozen = _nosuchkey_exc()
    thawed = _thaw_s3_error(frozen)
    # Downstream ``except S3Error`` / isinstance checks must still catch it.
    assert isinstance(thawed, S3Error)
    # NoSuchKey detection (F017 fallback, linsight missing-key handling) intact.
    assert _is_no_such_key_error(thawed)
    assert thawed.code == "NoSuchKey"
    assert thawed.message == frozen.message
    assert thawed.object_name == frozen.object_name
    # Message text preserved so logs read identically.
    assert str(thawed) == str(frozen)


def test_thaw_keeps_original_traceback():
    try:
        raise _nosuchkey_exc()
    except S3Error as e:
        original_tb = e.__traceback__
        thawed = _thaw_s3_error(e)
    assert thawed.__traceback__ is original_tb


def test_thaw_passes_through_non_frozen_errors():
    err = ValueError("boom")
    assert _thaw_s3_error(err) is err


# ── storage boundary integration ─────────────────────────────────


def test_download_object_raises_mutable_s3error_on_missing_key():
    """On a genuine NoSuchKey (no multi-tenant fallback), the error that
    escapes ``download_object_sync`` must still be an S3Error but mutable, so
    it can't mask the real miss on its way to the ASGI layer."""
    storage = _make_storage()
    storage.minio_client_sync.get_object.side_effect = _nosuchkey_exc()
    with patch(
        "bisheng.core.storage.minio.minio_storage._should_fallback_to_root",
        return_value=False,
    ):
        with pytest.raises(S3Error) as ei:
            storage.download_object_sync(bucket_name="bisheng", object_name="missing.jpg")
    assert _is_no_such_key_error(ei.value)
    # The escaped error survives a later __traceback__ reassignment.
    ei.value.__traceback__ = None


def test_get_object_raises_mutable_s3error_on_missing_key():
    storage = _make_storage()
    storage.minio_client_sync.get_object.side_effect = _nosuchkey_exc()
    with patch(
        "bisheng.core.storage.minio.minio_storage._should_fallback_to_root",
        return_value=False,
    ):
        with pytest.raises(S3Error) as ei:
            storage.get_object_sync(bucket_name="bisheng", object_name="missing.jpg")
    assert _is_no_such_key_error(ei.value)
    ei.value.__traceback__ = None
