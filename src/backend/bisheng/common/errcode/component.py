from .base import BaseErrorCode


# Component Modules Return error code, business code103
class ComponentExistError(BaseErrorCode):
    Code: int = 10300
    Msg: str = 'Component Exists'


class ComponentNotExistError(BaseErrorCode):
    Code: int = 10301
    Msg: str = 'Component does not exist'
