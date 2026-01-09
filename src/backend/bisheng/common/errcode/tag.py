from .base import BaseErrorCode


# Label module related return error code, function module code:107
class TagExistError(BaseErrorCode):
    Code: int = 10700
    Msg: str = 'Tag already exist'


class TagNotExistError(BaseErrorCode):
    Code: int = 10701
    Msg: str = 'No tags found'
