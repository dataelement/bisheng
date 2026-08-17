"""Open API authentication error codes — module 260 (F049 design D10).

Two sub-ranges share the module: the **open face** (``/api/v2``, 26001-26019,
codes fixed by the PRD appendix; ``26005-26007 / 26010 / 26016`` are reserved
for F050 identity delegation, ``26013 / 26014`` are retired and never reused)
and the **management face** (``/api/v1/service-accounts/**``, 26020+).

``http_status`` is the *real* HTTP status the dedicated ``/api/v2`` exception
handler emits (design K4: the platform-wide handler flattens everything to
HTTP 200 + envelope; on ``/api/v1`` these errors still travel that way and the
front end reads the envelope ``status_code``). Copy for every code lives in
``src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`` (K12).
"""

from bisheng.common.errcode.base import BaseErrorCode


class OpenApiAuthError(BaseErrorCode):
    """Base of the 260xx family; carries the real HTTP status for ``/api/v2``."""

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


# ---------------------------------------------------------------------------
# Open face (/api/v2) — 26001..26019
# ---------------------------------------------------------------------------


class OpenApiCredentialMissingError(OpenApiAuthError):
    """No ``Authorization: Bearer bs-sak-…`` header, or the value is malformed."""

    Code: int = 26001
    Msg: str = "Missing or malformed API credential"
    http_status: int = 401


class OpenApiCredentialInvalidError(OpenApiAuthError):
    """Credential unknown, revoked or expired (also: subject kind without a resolver)."""

    Code: int = 26002
    Msg: str = "Invalid, revoked or expired API credential"
    http_status: int = 401


class OpenApiScopeMissingError(OpenApiAuthError):
    """Credential valid but lacks the endpoint's scope; ``data.required`` names it (AC-04)."""

    Code: int = 26003
    Msg: str = "API credential lacks the required scope"
    http_status: int = 403

    def __init__(self, required: str, **kwargs):
        super().__init__(required=required, **kwargs)


class OpenApiDelegationNotEnabledError(OpenApiAuthError):
    """Any identity-passing header (``X-Bisheng-On-Behalf-Of`` / ``X-Bisheng-End-User``) before F050."""

    Code: int = 26004
    Msg: str = "Identity delegation is not enabled"
    http_status: int = 403


class ServiceAccountLoginForbiddenError(OpenApiAuthError):
    """A service account tried to obtain a session through any login entry (AC-15). Always ``raise``."""

    Code: int = 26012
    Msg: str = "Service accounts cannot log in"
    http_status: int = 403


# ---------------------------------------------------------------------------
# Management face (/api/v1/service-accounts/**) — 26020+
# ---------------------------------------------------------------------------


class ServiceAccountNotFoundError(OpenApiAuthError):
    Code: int = 26020
    Msg: str = "Service account not found"
    http_status: int = 404


class ServiceAccountOwnerInvalidError(OpenApiAuthError):
    """Resource owner must be an enabled natural person of the current tenant (AC-23)."""

    Code: int = 26021
    Msg: str = "Resource owner must be an enabled natural person of this tenant"
    http_status: int = 400


class ServiceAccountOperationForbiddenError(OpenApiAuthError):
    """People-only operations on a service account: password / login toggle / roles / groups / departments / tenant admin (AC-20 / AC-22)."""

    Code: int = 26022
    Msg: str = "This operation is not allowed for a service account"
    http_status: int = 403


class OpenApiExtensionScopeNotDeployedError(OpenApiAuthError):
    """A local-dev-toolkit scope was requested while ``open_platform.enabled`` is false (AC-13)."""

    Code: int = 26023
    Msg: str = "Extension scope is not available: open platform is not deployed"
    http_status: int = 400


class OpenApiDelegateScopeNotEnabledError(OpenApiAuthError):
    """``delegate`` scope requested at issue / edit time — delegation ships with F050 (AC-14)."""

    Code: int = 26024
    Msg: str = "Delegation capability is not enabled yet"
    http_status: int = 400


class OpenApiUnknownScopeError(OpenApiAuthError):
    """Scope code not in ``OPEN_API_SCOPES`` (AC-06)."""

    Code: int = 26025
    Msg: str = "Unknown API scope"
    http_status: int = 400


class ApiCredentialNotFoundError(OpenApiAuthError):
    """Key id unknown or not owned by the addressed service account."""

    Code: int = 26026
    Msg: str = "API key not found or does not belong to this service account"
    http_status: int = 404


class ServiceAccountInactiveError(OpenApiAuthError):
    """Service account is disabled or deleted (management ops and credential validation)."""

    Code: int = 26027
    Msg: str = "Service account is disabled or deleted"
    http_status: int = 401


class ShareLinkInvalidError(OpenApiAuthError):
    """Share token unknown, revoked, expired or bound to another resource (WS + share-link endpoints)."""

    Code: int = 26028
    Msg: str = "Share link is invalid, revoked or expired"
    http_status: int = 401


class ServiceAccountNotGrantSubjectError(OpenApiAuthError):
    """Service accounts are granted only from their own detail page, never from the resource side (AC-16)."""

    Code: int = 26029
    Msg: str = "Service accounts cannot be selected as a resource-side grant subject"
    http_status: int = 403


class OpenApiAuthDependencyUnavailableError(OpenApiAuthError):
    """Redis / DB failure during credential validation — fail closed (design K2)."""

    Code: int = 26030
    Msg: str = "Credential validation service unavailable"
    http_status: int = 503


class OpenApiEndpointUnregisteredError(OpenApiAuthError):
    """A ``/api/v2`` endpoint without ``@open_api_scope`` marker — structural fail-closed (design D3)."""

    Code: int = 26031
    Msg: str = "Endpoint has no registered API scope"
    http_status: int = 500
