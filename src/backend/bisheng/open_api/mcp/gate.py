"""The ASGI gate in front of the MCP transport (design D2).

Why a hand-written gate rather than FastAPI dependencies or ``FastMCP``'s own
``token_verifier``:

* the MCP endpoint is a plain Starlette ``Route``, so ``router_rpc``'s
  router-level dependency never sees it and there is no ``@open_api_scope``
  marker to read;
* the SDK's bearer middleware is an OAuth resource-server shape — it needs an
  issuer URL, answers with ``WWW-Authenticate``, and installs ``request.user``
  but none of the tenant or permission ContextVars the domain services run under.

So the gate reuses ``admit_open_api_principal`` and ``open_api_execution_scope``
— the *same functions* ``/api/v2`` runs, not a second copy that has to be kept
in step. "Revocation takes effect within five seconds" and "editing scopes takes
effect on the next call" are then facts about shared code.

Between the two halves sit the two refusals this face owns (K3). Both are
absolute, and neither may degrade into "carry on as the service account":

* a key carrying ``delegate`` is refused at the door — it is issued for acting
  as somebody else, and a local development face has nobody to act as;
* any identity-passing header is refused outright. ``/api/v2`` *parses* those
  headers; here, accepting and ignoring them would be the worst outcome, because
  the caller would believe the call ran as the named user.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from time import perf_counter
from typing import Any

from fastapi.encoders import jsonable_encoder
from starlette.requests import Request
from starlette.responses import JSONResponse

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.mcp_face import McpIdentityHeaderRefusedError
from bisheng.common.errcode.open_api import (
    OpenApiDelegateLocalDevRefusedError,
)
from bisheng.open_api.api.dependencies import (
    admit_open_api_principal,
    open_api_execution_scope,
)
from bisheng.open_api.api.exception_handlers import open_api_http_status
from bisheng.open_api.domain.scopes import DELEGATE_SCOPE_CODE
from bisheng.open_api.mcp.audit import audit_transport_refusal
from bisheng.open_api.mcp.errors import (
    DEFAULT_LANG,
    SUPPORTED_LANGS,
    reset_current_mcp_lang,
    set_current_mcp_lang,
)

#: Exact header names that carry an identity on ``/api/v2``.
IDENTITY_HEADERS = ("x-on-behalf-of", "x-end-user")
#: Suffixes that catch the vendor-prefixed variants a gateway might add.
IDENTITY_HEADER_SUFFIXES = ("-on-behalf-of", "-end-user")


class McpAccessGate:
    """Authenticate, refuse delegation, install the execution identity, delegate down."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        started = perf_counter()
        lang_token = set_current_mcp_lang(_accept_language(request.headers.get("accept-language")))
        try:
            principal = None
            stack = AsyncExitStack()
            try:
                principal, data_scope = await admit_open_api_principal(request)
                if principal.has_scope(DELEGATE_SCOPE_CODE):
                    raise OpenApiDelegateLocalDevRefusedError()
                _refuse_identity_headers(request.headers.items())
                # Entered explicitly rather than with ``async with`` so that a
                # failure *setting up* the identity still answers in the v2
                # envelope, while anything raised by the transport below is left
                # to the MCP layer — by then the response has usually started
                # and a second one would be a protocol error.
                await stack.enter_async_context(open_api_execution_scope(request, principal, data_scope=data_scope))
            except BaseErrorCode as exc:
                await stack.aclose()
                await self._refuse(exc, principal, request, send, started)
                return

            try:
                await self.app(scope, receive, send)
            finally:
                await stack.aclose()
        finally:
            reset_current_mcp_lang(lang_token)

    @staticmethod
    async def _refuse(exc: BaseErrorCode, principal, request: Request, send, started: float) -> None:
        """Answer in the v2 envelope, with the same status the REST face would use."""

        status = getattr(exc, "http_status", None) or open_api_http_status(exc)
        request.scope["open_api_error_code"] = exc.code
        audit_transport_refusal(
            principal,
            code=exc.code,
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            ip_address=_client_ip(request),
        )
        response = JSONResponse(status_code=int(status), content=jsonable_encoder(exc.to_dict()))
        await response(request.scope, request.receive, send)


def _refuse_identity_headers(headers) -> None:
    for name, _value in headers:
        normalized = name.lower()
        if normalized in IDENTITY_HEADERS or normalized.endswith(IDENTITY_HEADER_SUFFIXES):
            raise McpIdentityHeaderRefusedError(header=normalized)


def _accept_language(raw: str | None) -> str:
    """Pick one of the three languages the ``next_step`` copy exists in."""

    if not raw:
        return DEFAULT_LANG
    for part in raw.split(","):
        tag = part.split(";", 1)[0].strip()
        if not tag:
            continue
        for candidate in SUPPORTED_LANGS:
            if tag.lower() == candidate.lower() or tag.lower().startswith(candidate.lower() + "-"):
                return candidate
        primary = tag.split("-", 1)[0].lower()
        if primary == "zh":
            return "zh-Hans"
        if primary in {"en", "ja"}:
            return primary
    return DEFAULT_LANG


def _client_ip(request: Request) -> str | None:
    client = request.scope.get("client")
    if isinstance(client, (tuple, list)) and client:
        return client[0]
    return None


__all__ = ["IDENTITY_HEADERS", "IDENTITY_HEADER_SUFFIXES", "McpAccessGate"]
