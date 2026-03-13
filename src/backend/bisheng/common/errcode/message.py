from .base import BaseErrorCode


# Message module error codes, module code: 140
class MessageNotFoundError(BaseErrorCode):
    Code: int = 14001
    Msg: str = 'Message not found'


class MessagePermissionDeniedError(BaseErrorCode):
    Code: int = 14002
    Msg: str = 'Permission denied for this message operation'


class MessageAlreadyApprovedError(BaseErrorCode):
    Code: int = 14003
    Msg: str = 'Message has already been approved or rejected'
