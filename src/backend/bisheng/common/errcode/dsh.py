"""F062 error registry (261); client routes use the frozen HTTP/error envelope.

Do not use BaseErrorCode.http_exception for DSH routes: its legacy status is a
business code, not a valid HTTP status. HTTP adapters use HttpStatus/ClientCode.
"""

from .base import BaseErrorCode


class DshInvalidRequestError(BaseErrorCode):
    Code: int = 26101
    Msg: str = "Invalid request"
    HttpStatus: int = 400
    ClientCode: str = "invalid_request"
    ErrorType: str = "invalid_request_error"


class DshUnsupportedParameterError(BaseErrorCode):
    Code: int = 26102
    Msg: str = "Unsupported parameter"
    HttpStatus: int = 400
    ClientCode: str = "unsupported_parameter"
    ErrorType: str = "invalid_request_error"


class DshContextLengthExceededError(BaseErrorCode):
    Code: int = 26103
    Msg: str = "Model context length exceeded"
    HttpStatus: int = 400
    ClientCode: str = "context_length_exceeded"
    ErrorType: str = "invalid_request_error"


class DshInvalidGrantError(BaseErrorCode):
    Code: int = 26104
    Msg: str = "Authorization grant is invalid or already used"
    HttpStatus: int = 400
    ClientCode: str = "invalid_grant"
    ErrorType: str = "authentication_error"


class DshPkceVerificationFailedError(BaseErrorCode):
    Code: int = 26105
    Msg: str = "PKCE verification failed; sign in again"
    HttpStatus: int = 400
    ClientCode: str = "pkce_verification_failed"
    ErrorType: str = "authentication_error"


class DshAuthorizationExpiredError(BaseErrorCode):
    Code: int = 26106
    Msg: str = "Authorization expired"
    HttpStatus: int = 400
    ClientCode: str = "authorization_expired"
    ErrorType: str = "authentication_error"


class DshInvalidAccessTokenError(BaseErrorCode):
    Code: int = 26107
    Msg: str = "Invalid DSH access token"
    HttpStatus: int = 401
    ClientCode: str = "invalid_access_token"
    ErrorType: str = "authentication_error"


class DshInvalidRefreshTokenError(BaseErrorCode):
    Code: int = 26108
    Msg: str = "Invalid refresh token; sign in again"
    HttpStatus: int = 401
    ClientCode: str = "invalid_refresh_token"
    ErrorType: str = "authentication_error"


class DshRefreshTokenReusedError(BaseErrorCode):
    Code: int = 26109
    Msg: str = "Refresh token reuse detected; sign in again"
    HttpStatus: int = 401
    ClientCode: str = "refresh_token_reused"
    ErrorType: str = "authentication_error"


class DshSessionExpiredError(BaseErrorCode):
    Code: int = 26110
    Msg: str = "DSH session expired"
    HttpStatus: int = 401
    ClientCode: str = "session_expired"
    ErrorType: str = "authentication_error"


class DshSessionRevokedError(BaseErrorCode):
    Code: int = 26111
    Msg: str = "DSH session revoked"
    HttpStatus: int = 401
    ClientCode: str = "session_revoked"
    ErrorType: str = "authentication_error"


class DshSeatLimitReachedError(BaseErrorCode):
    Code: int = 26112
    Msg: str = "DSH seat limit reached; contact an administrator"
    HttpStatus: int = 403
    ClientCode: str = "seat_limit_reached"
    ErrorType: str = "permission_error"


class DshSeatRevokedError(BaseErrorCode):
    Code: int = 26113
    Msg: str = "DSH seat revoked"
    HttpStatus: int = 403
    ClientCode: str = "seat_revoked"
    ErrorType: str = "permission_error"


class DshLicenseInvalidError(BaseErrorCode):
    Code: int = 26114
    Msg: str = "Invalid DSH license"
    HttpStatus: int = 403
    ClientCode: str = "license_invalid"
    ErrorType: str = "permission_error"


class DshLicenseExpiredError(BaseErrorCode):
    Code: int = 26115
    Msg: str = "DSH license expired"
    HttpStatus: int = 403
    ClientCode: str = "license_expired"
    ErrorType: str = "permission_error"


class DshDshDisabledError(BaseErrorCode):
    Code: int = 26116
    Msg: str = "DSH access is disabled"
    HttpStatus: int = 403
    ClientCode: str = "dsh_disabled"
    ErrorType: str = "permission_error"


class DshUserDisabledError(BaseErrorCode):
    Code: int = 26117
    Msg: str = "User account unavailable"
    HttpStatus: int = 403
    ClientCode: str = "user_disabled"
    ErrorType: str = "permission_error"


class DshTenantUnavailableError(BaseErrorCode):
    Code: int = 26118
    Msg: str = "Tenant unavailable"
    HttpStatus: int = 403
    ClientCode: str = "tenant_unavailable"
    ErrorType: str = "permission_error"


class DshModelNotAllowedError(BaseErrorCode):
    Code: int = 26119
    Msg: str = "Model is not authorized or unavailable"
    HttpStatus: int = 403
    ClientCode: str = "model_not_allowed"
    ErrorType: str = "permission_error"


class DshAuthorizationConflictError(BaseErrorCode):
    Code: int = 26120
    Msg: str = "Authorization conflict; start a new sign-in"
    HttpStatus: int = 409
    ClientCode: str = "authorization_conflict"
    ErrorType: str = "conflict_error"


class DshMonthlyTokenLimitExceededError(BaseErrorCode):
    Code: int = 26121
    Msg: str = "Monthly token limit reached"
    HttpStatus: int = 429
    ClientCode: str = "monthly_token_limit_exceeded"
    ErrorType: str = "quota_error"


class DshTooManyRequestsError(BaseErrorCode):
    Code: int = 26122
    Msg: str = "Too many requests; try again later"
    HttpStatus: int = 429
    ClientCode: str = "too_many_requests"
    ErrorType: str = "rate_limit_error"


class DshUpstreamErrorError(BaseErrorCode):
    Code: int = 26123
    Msg: str = "Upstream model request failed"
    HttpStatus: int = 502
    ClientCode: str = "upstream_error"
    ErrorType: str = "upstream_error"


class DshUpstreamTimeoutError(BaseErrorCode):
    Code: int = 26124
    Msg: str = "Upstream model request timed out"
    HttpStatus: int = 504
    ClientCode: str = "upstream_timeout"
    ErrorType: str = "upstream_error"


class DshAuthorizationUnavailableError(BaseErrorCode):
    Code: int = 26125
    Msg: str = "DSH authorization is temporarily unavailable"
    HttpStatus: int = 503
    ClientCode: str = "authorization_unavailable"
    ErrorType: str = "service_unavailable_error"


class DshQuotaUnavailableError(BaseErrorCode):
    Code: int = 26126
    Msg: str = "DSH quota state is temporarily unavailable"
    HttpStatus: int = 503
    ClientCode: str = "quota_unavailable"
    ErrorType: str = "service_unavailable_error"


class DshUsageUnavailableError(BaseErrorCode):
    Code: int = 26127
    Msg: str = "Actual request usage could not be confirmed"
    HttpStatus: int = 503
    ClientCode: str = "usage_unavailable"
    ErrorType: str = "service_unavailable_error"


class DshInternalErrorError(BaseErrorCode):
    Code: int = 26128
    Msg: str = "Internal DSH service error"
    HttpStatus: int = 500
    ClientCode: str = "internal_error"
    ErrorType: str = "server_error"


class DshOperationInProgressError(BaseErrorCode):
    Code: int = 26129
    Msg: str = "A management operation is already in progress"
    HttpStatus: int = 409
    ClientCode: str = "operation_in_progress"
    ErrorType: str = "conflict_error"


class DshOperationConflictError(BaseErrorCode):
    Code: int = 26130
    Msg: str = "Management operation version or payload conflict"
    HttpStatus: int = 409
    ClientCode: str = "operation_conflict"
    ErrorType: str = "conflict_error"


DSH_ERROR_TYPES = (
    DshInvalidRequestError,
    DshUnsupportedParameterError,
    DshContextLengthExceededError,
    DshInvalidGrantError,
    DshPkceVerificationFailedError,
    DshAuthorizationExpiredError,
    DshInvalidAccessTokenError,
    DshInvalidRefreshTokenError,
    DshRefreshTokenReusedError,
    DshSessionExpiredError,
    DshSessionRevokedError,
    DshSeatLimitReachedError,
    DshSeatRevokedError,
    DshLicenseInvalidError,
    DshLicenseExpiredError,
    DshDshDisabledError,
    DshUserDisabledError,
    DshTenantUnavailableError,
    DshModelNotAllowedError,
    DshAuthorizationConflictError,
    DshMonthlyTokenLimitExceededError,
    DshTooManyRequestsError,
    DshUpstreamErrorError,
    DshUpstreamTimeoutError,
    DshAuthorizationUnavailableError,
    DshQuotaUnavailableError,
    DshUsageUnavailableError,
    DshInternalErrorError,
    DshOperationInProgressError,
    DshOperationConflictError,
)
ERROR_BY_CLIENT_CODE = {error.ClientCode: error for error in DSH_ERROR_TYPES}
