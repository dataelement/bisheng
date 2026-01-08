from .base import BaseErrorCode


# RTModel Deployment Module Return error code, business code102
class NotFoundModelError(BaseErrorCode):
    Code: int = 10200
    Msg: str = 'Model does not exist'
