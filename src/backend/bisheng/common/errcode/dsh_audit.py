"""Browser audit-management errors; separate from the frozen Desktop model envelope."""

from bisheng.common.errcode.base import BaseErrorCode


class DshAuditQueryInvalidError(BaseErrorCode):
    Code: int = 26131
    Msg: str = "Invalid audit query"


class DshAuditRequestUnavailableError(BaseErrorCode):
    Code: int = 26132
    Msg: str = "Audit request unavailable"


class DshAuditOriginalUnavailableError(BaseErrorCode):
    Code: int = 26133
    Msg: str = "Audit original unavailable"


class DshAuditAccessLogUnavailableError(BaseErrorCode):
    Code: int = 26134
    Msg: str = "Audit access logging unavailable"
