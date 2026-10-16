from .base import BaseErrorCode


#  Model management module related return error code, function module code:108
class ServerExistError(BaseErrorCode):
    Code: int = 10800
    Msg: str = "Service provider name is duplicated, please modify"


class ModelNameRepeatError(BaseErrorCode):
    Code: int = 10801
    Msg: str = "Model is not repeatable"


class ServerAddAllError(BaseErrorCode):
    Code: int = 10802
    Msg: str = "Failed to add service provider, failed to initialize all models"


class ServerAddError(BaseErrorCode):
    Code: int = 10803
    Msg: str = "Failed to add service provider, some models failed to initialize"


class WorkbenchEmbeddingError(BaseErrorCode):
    Code: int = 10810
    Msg: str = "Please configure the workbench embedding model."


class WorkbenchChatDefaultModelError(BaseErrorCode):
    Code: int = 10811
    Msg: str = "The daily-chat default model must be one of the configured workbench chat models."


class ModelDiscoveryError(BaseErrorCode):
    Code = 10812
    Msg = "Model discovery failed. Check the connection settings and retry."

    def __init__(self, *, msg: str | None = None, reason: str = "failure"):
        super().__init__(msg=msg or self.Msg, reason=reason)
