"""Open API authentication and identity errors (module 260)."""

from bisheng.common.errcode.base import BaseErrorCode


class OpenApiAuthError(BaseErrorCode):
    """Base error carrying the real status used by the v2 exception handler."""

    http_status: int = 401

    def __init__(
        self,
        exception: Exception | None = None,
        msg: str | None = None,
        code: int | None = None,
        http_status: int | None = None,
        **kwargs,
    ):
        super().__init__(exception=exception, msg=msg, code=code, **kwargs)
        if http_status is not None:
            self.http_status = http_status


class OpenApiCredentialMissingError(OpenApiAuthError):
    Code = 26001
    Msg = "Missing or malformed API credential"
    http_status = 401


class OpenApiCredentialInvalidError(OpenApiAuthError):
    Code = 26002
    Msg = "Invalid, revoked, or expired API credential"
    http_status = 401


class OpenApiScopeMissingError(OpenApiAuthError):
    Code = 26003
    Msg = "API credential lacks the required scope"
    http_status = 403

    def __init__(self, required: str, **kwargs):
        super().__init__(required=required, **kwargs)


class OpenApiDelegationNotAllowedError(OpenApiAuthError):
    Code = 26004
    Msg = "Delegation is not enabled or the target is outside the allowed scope"
    http_status = 403


class OpenApiDelegationTargetInvalidError(OpenApiAuthError):
    Code = 26005
    Msg = "Delegation target is invalid"
    http_status = 403


class OpenApiDelegationModeUnsupportedError(OpenApiAuthError):
    Code = 26006
    Msg = "This endpoint does not support delegated identity"
    http_status = 403


class OpenApiPrivilegedTargetError(OpenApiAuthError):
    Code = 26007
    Msg = "Privileged users cannot be delegation targets"
    http_status = 403


class OpenApiIdentityHeaderConflictError(OpenApiAuthError):
    Code = 26010
    Msg = "X-On-Behalf-Of and X-End-User cannot be used together"
    http_status = 400


class OpenApiAsyncUnsupportedError(OpenApiAuthError):
    Code = 26015
    Msg = "Asynchronous execution is not available on this endpoint"
    http_status = 400


class OpenApiDelegationHeaderRequiredError(OpenApiAuthError):
    Code = 26016
    Msg = "X-On-Behalf-Of is required for a delegated credential"
    http_status = 400


class OpenApiTaskModeUnsupportedError(OpenApiAuthError):
    Code = 26017
    Msg = "Task mode is not available through the Open API"
    http_status = 400


class OpenApiEndUserInvalidError(OpenApiAuthError):
    Code = 26018
    Msg = "X-End-User must contain at most 128 printable ASCII bytes"
    http_status = 400


class OpenApiRemovedIdentityInputError(OpenApiAuthError):
    Code = 26019
    Msg = "Use X-On-Behalf-Of instead of removed identity inputs"
    http_status = 400


class ServiceAccountNotFoundError(OpenApiAuthError):
    Code = 26020
    Msg = "Service account not found"
    http_status = 404


class ServiceAccountOwnerInvalidError(OpenApiAuthError):
    Code = 26021
    Msg = "Resource owner or delegation target is invalid"
    http_status = 400


class ServiceAccountOperationForbiddenError(OpenApiAuthError):
    Code = 26022
    Msg = "This operation is not allowed for a service account"
    http_status = 403


class OpenApiExtensionScopeNotDeployedError(OpenApiAuthError):
    Code = 26023
    Msg = "The requested extension scope is not deployed"
    http_status = 400


class OpenApiDelegateConfigurationInvalidError(OpenApiAuthError):
    Code = 26024
    Msg = "Delegation configuration is invalid"
    http_status = 400


class OpenApiUnknownScopeError(OpenApiAuthError):
    Code = 26025
    Msg = "Unknown API scope"
    http_status = 400


class ApiCredentialNotFoundError(OpenApiAuthError):
    Code = 26026
    Msg = "API credential not found"
    http_status = 404


class ServiceAccountInactiveError(OpenApiAuthError):
    Code = 26027
    Msg = "Service account is disabled or deleted"
    http_status = 401


class ServiceAccountOwnerForbiddenError(OpenApiAuthError):
    Code = 26029
    Msg = "A service account cannot be a resource owner"
    http_status = 403


class OpenApiAuthDependencyUnavailableError(OpenApiAuthError):
    Code = 26030
    Msg = "Credential validation service unavailable"
    http_status = 503


class OpenApiEndpointUnregisteredError(OpenApiAuthError):
    Code = 26031
    Msg = "Endpoint has no registered API scope"
    http_status = 500


class PersonalTokenDisabledError(OpenApiAuthError):
    Code = 26040
    Msg = "Personal access tokens are not enabled"
    http_status = 403


class PersonalTokenScopeInvalidError(OpenApiAuthError):
    Code = 26041
    Msg = "Personal access token scope is not allowed"
    http_status = 400


class PersonalTokenTtlExceededError(OpenApiAuthError):
    Code = 26042
    Msg = "Personal access token expiry exceeds the allowed maximum"
    http_status = 400


class PersonalTokenHolderInvalidError(OpenApiAuthError):
    Code = 26043
    Msg = "Personal access token holder is no longer active in this tenant"
    http_status = 401
