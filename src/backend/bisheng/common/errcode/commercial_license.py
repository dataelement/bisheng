from .base import BaseErrorCode


class CommercialLicenseInvalidPayloadError(BaseErrorCode):
    Code: int = 27001
    Msg: str = "Invalid commercial license payload"
