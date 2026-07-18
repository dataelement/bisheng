"""Regression: a missing workspace object must NOT crash the task.

Root cause (114 prod, 2026-06-18): the agent's read_file tool hit a workspace
key that doesn't exist (a URL mistaken for a path, or a prior-turn deliverable
under a different session prefix). MinIO raises ``S3Error: NoSuchKey`` — a
*frozen dataclass* exception — which escaped ``WorkspaceBackend.aread``, failed
the whole task, and on the resume path got masked by langgraph's traceback-trim
(``exc.__traceback__ = tb``) as the cryptic ``cannot assign to field
'__traceback__'``. The fix maps NoSuchKey to a recoverable "file not found".
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from minio.error import S3Error

from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend, _is_missing_key


def _s3(code: str) -> S3Error:
    # S3Error is a frozen dataclass; bypass __init__ and set just the field the
    # classifier reads (object.__setattr__ defeats the frozen __setattr__).
    exc = S3Error.__new__(S3Error)
    object.__setattr__(exc, "code", code)
    return exc


def _backend(tmp_path, *, async_get=None, sync_get=None) -> WorkspaceBackend:
    minio = MagicMock()
    minio.bucket = "bisheng"
    if async_get is not None:
        minio.get_object = async_get
    if sync_get is not None:
        minio.get_object_sync = sync_get
    return WorkspaceBackend(svid="sv-test", minio=minio, file_dir=str(tmp_path))


def test_is_missing_key():
    assert _is_missing_key(_s3("NoSuchKey")) is True
    assert _is_missing_key(_s3("AccessDenied")) is False


async def test_aread_missing_key_returns_not_found(tmp_path):
    be = _backend(tmp_path, async_get=AsyncMock(side_effect=_s3("NoSuchKey")))
    res = await be.aread("/output/europe_grain_report.md")
    assert res.error and "not found" in res.error  # recoverable, not a crash


async def test_aread_other_s3error_reraises(tmp_path):
    be = _backend(tmp_path, async_get=AsyncMock(side_effect=_s3("AccessDenied")))
    with pytest.raises(S3Error):
        await be.aread("/output/x.md")


def test_sync_read_missing_key_returns_not_found(tmp_path):
    be = _backend(tmp_path, sync_get=MagicMock(side_effect=_s3("NoSuchKey")))
    res = be.read("/output/missing.md")
    assert res.error and "not found" in res.error


def test_sync_minio_get_other_error_reraises(tmp_path):
    be = _backend(tmp_path, sync_get=MagicMock(side_effect=_s3("InternalError")))
    with pytest.raises(S3Error):
        be.read("/output/x.md")
