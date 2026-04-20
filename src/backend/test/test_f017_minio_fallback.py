"""F017 unit tests — MinIO Root-prefix fallback (T19).

Covers AC-06 Child-side path: when a Child user reads an object that
lives under the Root prefix (because the resource was created by Root),
``get_object_sync`` and friends should automatically translate the
tenant_{code}/ prefix to an empty prefix and retry.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bisheng.core.storage.minio.minio_storage import (
    MinioStorage,
    _is_no_such_key_error,
    _translate_to_root_prefix,
)


# ── Helpers ──────────────────────────────────────────────────────


def _make_storage() -> MinioStorage:
    """Skip __init__ (which builds a real minio client) and attach a mock
    client to the instance — enough for these unit tests."""
    storage = MinioStorage.__new__(MinioStorage)
    storage.bucket = 'bisheng'
    storage.tmp_bucket = 'tmp-dir'
    storage.minio_client_sync = MagicMock()
    return storage


def _ok_response(data: bytes = b'hello'):
    resp = MagicMock()
    resp.read.return_value = data
    return resp


def _nosuchkey_exc():
    """Build a real minio S3Error with code=NoSuchKey; F017 now uses
    ``isinstance(exc, S3Error) and exc.code == 'NoSuchKey'`` rather than
    string-matching, so a plain ``Exception('code: NoSuchKey')`` no longer
    triggers the fallback branch.
    """
    from minio.error import S3Error
    return S3Error(
        code='NoSuchKey',
        message='Object not found',
        resource='/bucket/key',
        request_id='req',
        host_id='host',
        response=MagicMock(status=404, headers={}),
    )


# ── _translate_to_root_prefix ────────────────────────────────────


def test_translate_to_root_prefix_strips_tenant_segment():
    assert _translate_to_root_prefix('tenant_subA/knowledge/1/file.pdf') == 'knowledge/1/file.pdf'


def test_translate_returns_none_when_no_prefix_present():
    # Already a Root-shaped path; fallback would be a no-op.
    assert _translate_to_root_prefix('knowledge/1/file.pdf') is None


def test_translate_returns_none_on_empty():
    assert _translate_to_root_prefix('') is None


def test_is_no_such_key_error_matches_s3_error_code():
    """F017 uses S3Error.code as the stable signal (minio-py contract),
    not string matching on the exception message."""
    assert _is_no_such_key_error(_nosuchkey_exc())
    # Plain Exception with a substring match is NOT treated as NoSuchKey
    # — prevents a user-supplied error message from bypassing the fallback
    # rules. Genuine non-S3 errors surface unchanged.
    assert not _is_no_such_key_error(Exception('code: NoSuchKey'))
    assert not _is_no_such_key_error(Exception('connection refused'))


# ── get_object_sync ──────────────────────────────────────────────


def test_get_object_returns_data_without_fallback_when_leaf_hit():
    storage = _make_storage()
    storage.minio_client_sync.get_object.return_value = _ok_response(b'leaf')
    with patch('bisheng.core.storage.minio.minio_storage._should_fallback_to_root',
               return_value=True):
        data = storage.get_object_sync(object_name='tenant_subA/file.pdf')
    assert data == b'leaf'
    assert storage.minio_client_sync.get_object.call_count == 1


def test_get_object_falls_back_to_root_on_nosuchkey_for_child():
    storage = _make_storage()
    # First call raises NoSuchKey, second call (root prefix) succeeds.
    storage.minio_client_sync.get_object.side_effect = [
        _nosuchkey_exc(),
        _ok_response(b'root-data'),
    ]
    with patch('bisheng.core.storage.minio.minio_storage._should_fallback_to_root',
               return_value=True):
        data = storage.get_object_sync(object_name='tenant_subA/knowledge/1/file.pdf')
    assert data == b'root-data'
    # Confirm second call used the stripped path.
    second_call_args = storage.minio_client_sync.get_object.call_args_list[1]
    assert second_call_args.args[1] == 'knowledge/1/file.pdf'


def test_get_object_no_fallback_when_single_tenant_mode():
    storage = _make_storage()
    storage.minio_client_sync.get_object.side_effect = _nosuchkey_exc()
    with patch('bisheng.core.storage.minio.minio_storage._should_fallback_to_root',
               return_value=False):
        with pytest.raises(Exception) as excinfo:
            storage.get_object_sync(object_name='tenant_subA/file.pdf')
    assert 'NoSuchKey' in str(excinfo.value)
    # Only one call made — no fallback.
    assert storage.minio_client_sync.get_object.call_count == 1


def test_get_object_no_fallback_when_object_has_no_tenant_prefix():
    """Already a Root-shaped path → no translation possible → original
    NoSuchKey surfaces."""
    storage = _make_storage()
    storage.minio_client_sync.get_object.side_effect = _nosuchkey_exc()
    with patch('bisheng.core.storage.minio.minio_storage._should_fallback_to_root',
               return_value=True):
        with pytest.raises(Exception) as excinfo:
            storage.get_object_sync(object_name='knowledge/1/file.pdf')
    assert 'NoSuchKey' in str(excinfo.value)
    assert storage.minio_client_sync.get_object.call_count == 1


def test_get_object_fallback_miss_raises_19503():
    """Fallback attempted but Root path also misses → 19503."""
    from bisheng.common.errcode.tenant_sharing import StorageSharingFallbackError

    storage = _make_storage()
    storage.minio_client_sync.get_object.side_effect = [
        _nosuchkey_exc(),
        _nosuchkey_exc(),
    ]
    with patch('bisheng.core.storage.minio.minio_storage._should_fallback_to_root',
               return_value=True):
        with pytest.raises(StorageSharingFallbackError):
            storage.get_object_sync(object_name='tenant_subA/knowledge/1/file.pdf')


# ── object_exists_sync ───────────────────────────────────────────


def test_object_exists_true_for_leaf_path_directly():
    storage = _make_storage()
    storage.minio_client_sync.stat_object.return_value = MagicMock()
    assert storage.object_exists_sync(object_name='tenant_subA/file.pdf') is True


def test_object_exists_falls_back_to_root_for_child():
    storage = _make_storage()
    storage.minio_client_sync.stat_object.side_effect = [
        _nosuchkey_exc(),
        MagicMock(),  # root hit
    ]
    with patch('bisheng.core.storage.minio.minio_storage._should_fallback_to_root',
               return_value=True):
        assert storage.object_exists_sync(object_name='tenant_subA/file.pdf') is True
    assert storage.minio_client_sync.stat_object.call_count == 2


def test_object_exists_returns_false_when_fallback_disabled_and_missing():
    storage = _make_storage()
    storage.minio_client_sync.stat_object.side_effect = _nosuchkey_exc()
    with patch('bisheng.core.storage.minio.minio_storage._should_fallback_to_root',
               return_value=False):
        assert storage.object_exists_sync(object_name='tenant_subA/file.pdf') is False
