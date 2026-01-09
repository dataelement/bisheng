from .base import BaseErrorCode


class UnAuthorizedError(BaseErrorCode):
    Code: int = 403
    Msg: str = 'No permission to operate'


class NotFoundError(BaseErrorCode):
    Code: int = 404
    Msg: str = 'This role does not exist - '


class ServerError(BaseErrorCode):
    Code: int = 500
    Msg: str = 'Server error'