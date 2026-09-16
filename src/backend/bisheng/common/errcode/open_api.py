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


class PersonalTokenDataScopeError(OpenApiAuthError):
    """F066: the tenant narrowed personal tokens to holder-created knowledge.

    Deliberately separate from 26003 (missing scope): 26003 means "ask an
    admin for the scope", 26044 means "tenant policy — retrying or adding
    scopes will not help".  The payload never names the denied resource
    (anti-enumeration).
    """

    Code = 26044
    Msg = "Personal access token data scope is restricted to holder-created knowledge"
    http_status = 403

    def __init__(self, **kwargs):
        kwargs.setdefault("scope", "personal_only")
        super().__init__(**kwargs)


# 26050+: the `delegate` ⊗ local development toolkit scope policy (伴生 PRD
# §4.2.4), one code per gate — 26050 at issue / edit time (a form the admin can
# fix), 26051 at the channel entrance (a call the developer cannot fix, only
# re-key). They are deliberately not one code: the two gates have different
# audiences, different transports (400 vs 403) and different next actions, and
# `constitution.md` binds one HTTP status per code.
# 26032-26039 and 26045-26049 stay reserved (test/open_api/test_error_codes.py).


class OpenApiDelegateExclusiveScopeError(OpenApiAuthError):
    """``delegate`` combined with a local development toolkit scope.

    A delegated key must send ``X-On-Behalf-Of`` on every call, while the
    toolkit surfaces (``model:invoke`` / ``identity:read`` / ``app:manage``)
    execute as the service account itself — such a key is unusable on both
    sides, so the combination is refused at issue and edit time rather than
    left to fail at runtime.
    """

    Code = 26050
    Msg = "A delegated credential cannot carry local development toolkit scopes; issue a separate key"
    http_status = 400


class OpenApiDelegateLocalDevRefusedError(OpenApiAuthError):
    """A delegated key reached a local development toolkit endpoint.

    The runtime half of INV-31 / 伴生 PRD §4.2.4「运行期兜底」. 26050 keeps such
    a key from being issued, but keys predating that gate still exist, so the
    channel entrance refuses them by scope — before the missing-scope check, or
    a delegated key without ``app:manage`` would get 26003 and send its holder
    to an administrator who then cannot tick the box (26050 refuses the
    combination) — and before delegation resolution, which would otherwise
    answer 26016 「补个身份头」, advice the PRD calls undiagnosable for a local
    agent: the CLI never sends identity headers, so no header is the fix.
    """

    Code = 26051
    Msg = "This credential is delegation-only; issue a separate key without delegate for local development"
    http_status = 403


class OpenApiHostedAppEndpointRefusedError(OpenApiAuthError):
    """A hosted application reached a v2 endpoint that executes as a natural person.

    The legacy ``/api/v2`` business endpoints run as ``get_open_api_operator()``,
    which for this subject resolves to the application's **owner** — with the
    owner's roles. That is fine for a service-account key, whose holder *is* that
    person; it is the exact fall-back F055 AC-52 forbids for an application,
    which may only reach what its capability declaration names.

    The gap is not hypothetical and is not about one endpoint: a declaration that
    names a single knowledge base derives ``knowledge:read``, and that one scope
    also opens ``GET /filelib``, ``GET /filelib/file/list``, ``detail_qa``,
    ``query_qa`` and the citation detail — every one of which would answer with
    the owner's full visibility and no whitelist. So the refusal lives at the
    single place all of them share (``_principal_user_id``) rather than on each
    route, where the next route added would silently miss it.

    An application's own faces never reach here: the model face resolves its
    range through ``model_range_policy`` and ``/filelib/retrieve`` routes this
    subject through ``CapabilityBusService``, which builds the *access user's*
    identity instead.
    """

    Code = 26052
    Msg = "This endpoint is not available to hosted applications; use the declared capability faces"
    http_status = 403
