from .base import BaseErrorCode


# Permission module error codes, module code: 190
class PermissionDeniedError(BaseErrorCode):
    Code: int = 19000
    Msg: str = 'Permission denied'


class PermissionCheckFailedError(BaseErrorCode):
    Code: int = 19001
    Msg: str = 'Permission check failed'


class PermissionFGAUnavailableError(BaseErrorCode):
    Code: int = 19002
    Msg: str = 'Authorization service unavailable'


class PermissionInvalidResourceError(BaseErrorCode):
    Code: int = 19003
    Msg: str = 'Invalid resource type or ID'


class PermissionTupleWriteError(BaseErrorCode):
    Code: int = 19004
    Msg: str = 'Failed to write authorization tuple'


class PermissionInvalidRelationError(BaseErrorCode):
    Code: int = 19005
    Msg: str = 'Invalid permission relation'
