"""Real HTTP statuses for the internal app-proxy surface.

The platform's global handler answers every ``HTTPException`` with **HTTP 200**
and puts the status in the body (``bisheng/main.py``). That is right for the
SPA, which reads the envelope, and wrong for a machine peer: app-proxy branches
on the transport status to tell "our shared secret is wrong" (401) from "this
visitor may not enter" (200 + ``decision``). Collapsed into one status, a
mis-configured secret would surface as "the backend answered something we could
not parse" — fail-closed either way, but with a log line pointing at the wrong
component.

Same shape and the same reason as F049's ``register_open_api_exception_handlers``:
a narrower exception class registered *below* ``HTTPException`` in the lookup,
so Starlette's MRO walk picks this one and everything else is untouched.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from bisheng.app_runtime.domain.services.hmac_auth import ProxyHmacRejectedError


def handle_proxy_hmac_rejected(_request: Request, exc: Exception) -> JSONResponse:
    detail = getattr(exc, "detail", "invalid signature")
    return JSONResponse(status_code=401, content={"status_code": 401, "status_message": detail, "data": None})


def register_app_runtime_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProxyHmacRejectedError, handle_proxy_hmac_rejected)
