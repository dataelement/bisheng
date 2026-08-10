import pytest
from pydantic import ValidationError

from bisheng.common.errcode.automotive_sheet_intro_sync import (
    AutomotiveSheetIntroSyncDisabledError,
    AutomotiveSheetIntroSyncInvalidConfigError,
    AutomotiveSheetIntroUpstreamError,
)
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.filelib_sync import FilelibSyncError


def test_automotive_sheet_intro_sync_errcodes_inherit_filelib_sync_error():
    assert issubclass(AutomotiveSheetIntroSyncDisabledError, FilelibSyncError)
    assert issubclass(AutomotiveSheetIntroSyncInvalidConfigError, FilelibSyncError)
    assert issubclass(AutomotiveSheetIntroUpstreamError, FilelibSyncError)
    assert issubclass(AutomotiveSheetIntroSyncDisabledError, BaseErrorCode)


def test_automotive_sheet_intro_sync_errcode_values():
    assert AutomotiveSheetIntroSyncDisabledError.Code == 19907
    assert AutomotiveSheetIntroSyncInvalidConfigError.Code == 19908
    assert AutomotiveSheetIntroUpstreamError.Code == 19909
    assert AutomotiveSheetIntroSyncDisabledError().http_status == 403
    assert AutomotiveSheetIntroSyncInvalidConfigError().http_status == 422
    assert AutomotiveSheetIntroUpstreamError().http_status == 502
