from __future__ import annotations

from bisheng.common.errcode import BaseErrorCode


class FilelibSyncError(BaseErrorCode):
    HttpStatus: int = 500

    @property
    def http_status(self) -> int:
        return self.HttpStatus


class FilelibSyncInvalidParamsError(FilelibSyncError):
    Code: int = 19901
    Msg: str = "filelib_sync_invalid_params"
    HttpStatus: int = 400


class FilelibSyncPermissionDeniedError(FilelibSyncError):
    Code: int = 19902
    Msg: str = "filelib_sync_permission_denied"
    HttpStatus: int = 403


class FilelibSyncNotFoundError(FilelibSyncError):
    Code: int = 19903
    Msg: str = "filelib_sync_not_found"
    HttpStatus: int = 404


class FilelibSyncConflictError(FilelibSyncError):
    Code: int = 19904
    Msg: str = "filelib_sync_conflict"
    HttpStatus: int = 409


class FilelibSyncMultipartError(FilelibSyncError):
    Code: int = 19905
    Msg: str = "filelib_sync_multipart_invalid"
    HttpStatus: int = 422
