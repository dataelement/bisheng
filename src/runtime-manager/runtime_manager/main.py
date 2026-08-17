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

The lifespan owns exactly one background thing: the reconcile loop (D4). It
starts with a full alignment pass, which is what makes a manager restart adopt
whatever is already running instead of disturbing it (AC-22 / AC-50). Startup
never fails on a sick daemon — the apps are up and the loop retries — because a
manager that refuses to boot while dockerd is restarting takes the read side
(status / logs / route) down with it.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from runtime_manager import __version__
from runtime_manager.api import intents, readonly, routes
from runtime_manager.config import get_config
from runtime_manager.reconciler import ReconcileLoop, recovery_budget_seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [runtime-manager] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

_reconcile_loop: ReconcileLoop | None = None


def get_reconcile_loop() -> ReconcileLoop | None:
    """The running loop, for tests and for an operator poking at the process."""
    return _reconcile_loop


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _reconcile_loop
    config = get_config()
    if config.reconcile_enabled:
        _reconcile_loop = ReconcileLoop(config)
        _reconcile_loop.start()
        logger.info(
            "reconcile loop started (every %ss; unattended recovery budget %ss)",
            config.reconcile_interval_seconds,
            recovery_budget_seconds(config),
        )
    try:
        yield
    finally:
        if _reconcile_loop is not None:
            _reconcile_loop.stop()
            _reconcile_loop = None


app = FastAPI(
    title="BiSheng runtime manager",
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.include_router(intents.router)
app.include_router(routes.router)
app.include_router(readonly.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
