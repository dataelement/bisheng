from .base import BaseErrorCode


#  Model management module related return error code, function module code:108
class ServerExistError(BaseErrorCode):
    Code: int = 10800
    Msg: str = 'Service provider name is duplicated, please modify'


class ModelNameRepeatError(BaseErrorCode):
    Code: int = 10801
    Msg: str = 'Model is not repeatable'


class ServerAddAllError(BaseErrorCode):
    Code: int = 10802
    Msg: str = 'Failed to add service provider, failed to initialize all models'


class ServerAddError(BaseErrorCode):
    Code: int = 10803
    Msg: str = 'Failed to add service provider, some models failed to initialize'
