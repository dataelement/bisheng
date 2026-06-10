from .base import BaseErrorCode


class DeveloperTokenMissingError(BaseErrorCode):
    Code: int = 19801
    Msg: str = "developer_token_missing"


class DeveloperTokenInvalidError(BaseErrorCode):
    Code: int = 19802
    Msg: str = "developer_token_invalid"


class DeveloperTokenDisabledError(BaseErrorCode):
    Code: int = 19803
    Msg: str = "developer_token_disabled"


class DeveloperTokenIpForbiddenError(BaseErrorCode):
    Code: int = 19804
    Msg: str = "developer_token_ip_forbidden"


class DeveloperTokenRateLimitedError(BaseErrorCode):
    Code: int = 19805
    Msg: str = "developer_token_rate_limited"


class DeveloperTokenLimiterUnavailableError(BaseErrorCode):
    Code: int = 19806
    Msg: str = "developer_token_limiter_unavailable"


class DeveloperTokenAdminForbiddenError(BaseErrorCode):
    Code: int = 19807
    Msg: str = "developer_token_admin_forbidden"


class DeveloperTokenBindingForbiddenError(BaseErrorCode):
    Code: int = 19808
    Msg: str = "developer_token_binding_forbidden"


class DeveloperTokenInvalidIpRuleError(BaseErrorCode):
    Code: int = 19809
    Msg: str = "developer_token_invalid_ip_rule"


class DeveloperTokenInvalidRateLimitError(BaseErrorCode):
    Code: int = 19810
    Msg: str = "developer_token_invalid_rate_limit"
