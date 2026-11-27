"""OAuth 2.0 / OIDC Provider error codes (module code: 281)."""

from bisheng.common.errcode.base import BaseErrorCode


class OAuth2InvalidRequestError(BaseErrorCode):
    Code: int = 28101
    Msg: str = "Invalid OAuth2 request"


class OAuth2ClientNotFoundError(BaseErrorCode):
    Code: int = 28102
    Msg: str = "OAuth2 client not found"


class OAuth2ClientDisabledError(BaseErrorCode):
    Code: int = 28103
    Msg: str = "OAuth2 client is disabled"


class OAuth2InvalidClientAuthError(BaseErrorCode):
    Code: int = 28104
    Msg: str = "Invalid OAuth2 client credentials"


class OAuth2InvalidRedirectUriError(BaseErrorCode):
    Code: int = 28105
    Msg: str = "Redirect URI is not allowed for this OAuth2 client"


class OAuth2InvalidScopeError(BaseErrorCode):
    Code: int = 28106
    Msg: str = "Requested OAuth2 scope is not allowed"


class OAuth2InvalidGrantError(BaseErrorCode):
    Code: int = 28107
    Msg: str = "Invalid or expired OAuth2 grant"


class OAuth2AuthorizationExpiredError(BaseErrorCode):
    Code: int = 28108
    Msg: str = "OAuth2 authorization request has expired"


class OAuth2PkceVerificationFailedError(BaseErrorCode):
    Code: int = 28109
    Msg: str = "PKCE code_verifier verification failed"


class OAuth2ClientAlreadyExistsError(BaseErrorCode):
    Code: int = 28110
    Msg: str = "OAuth2 client_id already exists"


class OAuth2BuiltinClientProtectedError(BaseErrorCode):
    Code: int = 28111
    Msg: str = "Built-in OAuth2 client cannot be deleted"


class OAuth2InvalidAccessTokenError(BaseErrorCode):
    Code: int = 28112
    Msg: str = "Invalid or expired OAuth2 access token"


class OAuth2UserInactiveError(BaseErrorCode):
    Code: int = 28113
    Msg: str = "User account or tenant is inactive"


class OAuth2UnsupportedGrantTypeError(BaseErrorCode):
    Code: int = 28114
    Msg: str = "Unsupported OAuth2 grant_type"


class OAuth2InvalidTargetError(BaseErrorCode):
    Code: int = 28115
    Msg: str = "OAuth2 exchange target is not allowed"


class OAuth2UnauthorizedClientError(BaseErrorCode):
    Code: int = 28116
    Msg: str = "OAuth2 client is not allowed to exchange tokens"


class OAuth2TemporarilyUnavailableError(BaseErrorCode):
    Code: int = 28117
    Msg: str = "OAuth2 exchange is temporarily unavailable"


class OAuth2ExchangePolicyConflictError(BaseErrorCode):
    Code: int = 28118
    Msg: str = "OAuth2 exchange policy changed concurrently"
