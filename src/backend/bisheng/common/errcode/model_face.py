"""Model protocol face errors (module 262, F051).

Every code here is rendered twice: as the platform envelope on non-model-face
paths, and as an OpenAI-shaped error body under ``/api/v2/model/v1`` (design
D4). ``openai_type`` / ``openai_code`` carry the second rendering so the
mapping lives with the code instead of in a table the next person forgets to
extend.

``ModelFaceError`` inherits ``OpenApiAuthError`` for one mechanical reason: the
v2 exception handler resolves a real transport status through
``issubclass(OpenApiAuthError)`` and reads ``http_status`` off the instance
(``open_api/api/exception_handlers.py``). These are not authentication errors.

Sub-bands (design D11):

* ``26200-26209`` protocol face / endpoint / request shape
* ``26210-26229`` callable range and name resolution
* ``26230-26249`` upstream and streaming
* ``26250-26259`` records and ledger (reserved, no outward code this release)
"""

from bisheng.common.errcode.open_api import OpenApiAuthError

OPENAI_TYPE_INVALID_REQUEST = "invalid_request_error"
OPENAI_TYPE_AUTHENTICATION = "authentication_error"
OPENAI_TYPE_PERMISSION = "permission_error"
OPENAI_TYPE_RATE_LIMIT = "rate_limit_error"
OPENAI_TYPE_SERVER = "server_error"


class ModelFaceError(OpenApiAuthError):
    """Base for the 262 band; carries its own OpenAI error rendering."""

    http_status: int = 400
    openai_type: str = OPENAI_TYPE_INVALID_REQUEST
    openai_code: str = "model_face_error"


# --- 26200-26209: protocol face / endpoint / request shape -------------------


class ModelFaceEndpointNotSupportedError(ModelFaceError):
    Code: int = 26201
    Msg: str = "This release does not provide that endpoint; only chat completions and model list are available"
    http_status: int = 404
    openai_code: str = "endpoint_not_supported"


class ModelFaceAnthropicNotSupportedError(ModelFaceError):
    Code: int = 26202
    Msg: str = "This release provides an OpenAI-compatible face only"
    http_status: int = 404
    openai_code: str = "anthropic_protocol_not_supported"


class ModelFaceRequestInvalidError(ModelFaceError):
    Code: int = 26203
    Msg: str = "The request body is not a valid chat completion request"
    http_status: int = 400
    openai_code: str = "invalid_request"


class ModelFaceAccessTokenRefusedError(ModelFaceError):
    """A service-account key carried an access token, or an app's token failed verification."""

    Code: int = 26204
    Msg: str = "This credential does not accept an access token on this face"
    http_status: int = 403
    openai_type: str = OPENAI_TYPE_PERMISSION
    openai_code: str = "access_token_not_accepted"


class ModelFaceIdentityHeaderRefusedError(ModelFaceError):
    """Delegation-style identity headers are refused here, not silently adopted.

    The shared ``/api/v2`` base refuses ``X-On-Behalf-Of`` but adopts a
    well-formed ``X-End-User`` without a word (``identity_service``
    ``resolve_request_identity``). AC-27 requires this face to refuse it, so the
    refusal is ours rather than the base's.
    """

    Code: int = 26205
    Msg: str = "This face carries no delegation; drop the X-End-User / X-On-Behalf-Of header"
    http_status: int = 403
    openai_type: str = OPENAI_TYPE_PERMISSION
    openai_code: str = "identity_header_not_accepted"


# --- 26210-26229: callable range and name resolution -------------------------


class ModelFaceModelNotFoundError(ModelFaceError):
    """Also the answer for another tenant's model — existence is never revealed."""

    Code: int = 26211
    Msg: str = "Model {model} does not exist in this tenant"
    http_status: int = 404
    openai_code: str = "model_not_found"

    def __init__(self, model: str | None = None, **kwargs):
        super().__init__(msg=self.Msg.format(model=model), model=model, **kwargs)


class ModelFaceModelOfflineError(ModelFaceError):
    Code: int = 26212
    Msg: str = "Model {model} is offline; ask a tenant administrator to bring it back online"
    http_status: int = 404
    openai_code: str = "model_offline"

    def __init__(self, model: str | None = None, **kwargs):
        super().__init__(msg=self.Msg.format(model=model), model=model, **kwargs)


class ModelFaceModelRevokedError(ModelFaceError):
    Code: int = 26213
    Msg: str = "Model {model} is no longer available; its provider was removed"
    http_status: int = 404
    openai_code: str = "model_revoked"

    def __init__(self, model: str | None = None, **kwargs):
        super().__init__(msg=self.Msg.format(model=model), model=model, **kwargs)


class ModelFaceModelAmbiguousError(ModelFaceError):
    """Several providers publish this model name; refuse rather than pick one."""

    Code: int = 26214
    Msg: str = "Model name {model} is ambiguous in this tenant; call it by a qualified name such as {hint}"
    http_status: int = 400
    openai_code: str = "model_name_ambiguous"

    def __init__(self, model: str | None = None, candidates: list[str] | None = None, **kwargs):
        ordered = sorted(candidates or [])
        super().__init__(
            msg=self.Msg.format(model=model, hint=ordered[0] if ordered else "provider/model"),
            model=model,
            candidates=ordered,
            **kwargs,
        )
        self.candidates = ordered


class ModelFaceCapabilityUndeclaredError(ModelFaceError):
    """Hosted-app credential: the model exists but is outside the effective declaration."""

    Code: int = 26215
    Msg: str = "Model {model} is not in this application's declared capabilities; declare it and publish again"
    http_status: int = 403
    openai_type: str = OPENAI_TYPE_PERMISSION
    openai_code: str = "capability_undeclared"

    def __init__(self, model: str | None = None, **kwargs):
        super().__init__(msg=self.Msg.format(model=model), model=model, **kwargs)


class ModelFaceCatalogUnavailableError(ModelFaceError):
    """Second gate fail-closed: never fall back to a wider cached set (AC-35)."""

    Code: int = 26216
    Msg: str = "The callable model range cannot be determined right now; the call was refused rather than guessed"
    http_status: int = 503
    openai_type: str = OPENAI_TYPE_SERVER
    openai_code: str = "model_catalog_unavailable"


class ModelFaceProviderLimitExceededError(ModelFaceError):
    Code: int = 26217
    Msg: str = "The provider's daily call limit configured in model management is used up; it resets at midnight"
    http_status: int = 429
    openai_type: str = OPENAI_TYPE_RATE_LIMIT
    openai_code: str = "provider_daily_limit_exceeded"


# --- 26230-26249: upstream and streaming -------------------------------------


class ModelFaceUpstreamError(ModelFaceError):
    Code: int = 26231
    Msg: str = "The upstream model provider failed"
    http_status: int = 502
    openai_type: str = OPENAI_TYPE_SERVER
    openai_code: str = "upstream_error"


class ModelFaceUpstreamRejectedError(ModelFaceError):
    """Upstream 4xx (context too long, unsupported parameter, content filter).

    The transport status is carried on the instance so the caller sees what the
    provider said instead of a repackaged 400.
    """

    Code: int = 26232
    Msg: str = "The upstream model provider rejected the request"
    http_status: int = 400
    openai_type: str = OPENAI_TYPE_INVALID_REQUEST
    openai_code: str = "upstream_rejected"


class ModelFaceUpstreamRateLimitedError(ModelFaceError):
    Code: int = 26233
    Msg: str = "The upstream model provider is rate limiting this request"
    http_status: int = 429
    openai_type: str = OPENAI_TYPE_RATE_LIMIT
    openai_code: str = "upstream_rate_limited"


class ModelFaceStreamInterruptedError(ModelFaceError):
    """Only ever rendered inside an SSE error event — the 200 header is long gone."""

    Code: int = 26234
    Msg: str = "The streaming response was interrupted"
    http_status: int = 500
    openai_type: str = OPENAI_TYPE_SERVER
    openai_code: str = "stream_interrupted"


__all__ = [
    "OPENAI_TYPE_AUTHENTICATION",
    "OPENAI_TYPE_INVALID_REQUEST",
    "OPENAI_TYPE_PERMISSION",
    "OPENAI_TYPE_RATE_LIMIT",
    "OPENAI_TYPE_SERVER",
    "ModelFaceAccessTokenRefusedError",
    "ModelFaceAnthropicNotSupportedError",
    "ModelFaceCapabilityUndeclaredError",
    "ModelFaceCatalogUnavailableError",
    "ModelFaceEndpointNotSupportedError",
    "ModelFaceError",
    "ModelFaceIdentityHeaderRefusedError",
    "ModelFaceModelAmbiguousError",
    "ModelFaceModelNotFoundError",
    "ModelFaceModelOfflineError",
    "ModelFaceModelRevokedError",
    "ModelFaceProviderLimitExceededError",
    "ModelFaceRequestInvalidError",
    "ModelFaceStreamInterruptedError",
    "ModelFaceUpstreamError",
    "ModelFaceUpstreamRateLimitedError",
    "ModelFaceUpstreamRejectedError",
]
