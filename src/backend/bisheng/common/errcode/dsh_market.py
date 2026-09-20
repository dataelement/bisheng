from .base import BaseErrorCode


class MarketBundleError(BaseErrorCode):
    Code: int = 26201
    Msg: str = "Invalid offline plugin bundle"


class MarketConflictError(BaseErrorCode):
    Code: int = 26202
    Msg: str = "Plugin state changed; refresh and retry"


class MarketNotFoundError(BaseErrorCode):
    Code: int = 26203
    Msg: str = "Plugin or published version not found"


class MarketPermissionError(BaseErrorCode):
    Code: int = 26204
    Msg: str = "Tenant administrator access is required"
