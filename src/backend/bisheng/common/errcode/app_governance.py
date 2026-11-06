"""F056 administrator runtime-record read errors (163)."""

from bisheng.common.errcode.base import BaseErrorCode


class RuntimeAuditAccessDeniedError(BaseErrorCode):
    Code: int = 16301
    Msg: str = "Administrator access is required"


class RuntimeAuditFilterInvalidError(BaseErrorCode):
    Code: int = 16302
    Msg: str = "The record filters are invalid"


class RuntimeAuditCursorInvalidError(BaseErrorCode):
    Code: int = 16303
    Msg: str = "The record selection expired or changed. Refresh the list"


class RuntimeAuditExportUnavailableError(BaseErrorCode):
    Code: int = 16304
    Msg: str = "The export is unavailable. Check its status or create a new export"
