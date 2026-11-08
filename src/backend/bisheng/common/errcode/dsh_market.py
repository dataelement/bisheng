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


class MarketWorkbenchBundleError(BaseErrorCode):
    Code: int = 26205
    Msg: str = "Invalid workbench archive"

    def __init__(self, *, msg=None, validation_error=None):
        super().__init__(msg=msg)
        # Preserve the numeric API code alongside the machine-readable validation code.
        self.kwargs.update(validation_error or {})


class MarketWorkbenchConflictError(BaseErrorCode):
    Code: int = 26206
    Msg: str = "Workbench identity or version conflict"


class MarketWorkbenchNotFoundError(BaseErrorCode):
    Code: int = 26207
    Msg: str = "Workbench or current version not found"


class MarketWorkbenchArtifactError(BaseErrorCode):
    Code: int = 26208
    Msg: str = "Workbench artifact unavailable or invalid"
