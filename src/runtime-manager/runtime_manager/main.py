"""FastAPI composition root.

Binds ``127.0.0.1:8091`` (design §4.2 ⑧). Never published to the outside: on
114 it is a host systemd unit (``bisheng-runtime-manager.service``), in the
compose form a service on the internal network with no port mapping. Callers
are the platform backend (intent RPC) and the app-proxy (route lookups), both
authenticated with the shared HMAC secret.

``/healthz`` is the deliberate exception to the HMAC rule: systemd / smoke
scripts must be able to answer "is the process up" without holding the secret.
It reports process liveness only and leaks nothing about hosted apps — whether
the *orchestration backend* is reachable is a separate, authenticated answer
(``GET /v1/runtime/status``), because that one is operational intelligence.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from runtime_manager import __version__
from runtime_manager.api import intents, routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [runtime-manager] %(name)s: %(message)s",
)

app = FastAPI(
    title="BiSheng runtime manager",
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(intents.router)
app.include_router(routes.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
