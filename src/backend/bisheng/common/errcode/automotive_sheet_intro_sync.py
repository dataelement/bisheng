from __future__ import annotations

from bisheng.common.errcode.filelib_sync import FilelibSyncError


class AutomotiveSheetIntroSyncDisabledError(FilelibSyncError):
    Code: int = 19907
    Msg: str = "automotive_sheet_intro_sync_disabled"
    HttpStatus: int = 403


class AutomotiveSheetIntroSyncInvalidConfigError(FilelibSyncError):
    Code: int = 19908
    Msg: str = "automotive_sheet_intro_sync_invalid_config"
    HttpStatus: int = 422


class AutomotiveSheetIntroUpstreamError(FilelibSyncError):
    Code: int = 19909
    Msg: str = "automotive_sheet_intro_upstream_error"
    HttpStatus: int = 502
