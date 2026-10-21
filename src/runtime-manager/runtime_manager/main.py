"""FastAPI composition root.

Protocol v2 has one platform-backed reconciliation loop; protocol v1 retains the
legacy local-state loop only for compatibility. Read-only route and egress
projections live on backend, so they do not depend on manager liveness. The
manager API is internal, authenticated with independent platform-control HMAC.
Only /healthz is public liveness; orchestration readiness is authenticated.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from runtime_manager import __version__
from runtime_manager.api import (
    appdb,
    intents,
    operations,
    platform_data,
    platform_observe,
    readonly,
    routes,
    storage,
    upgrade,
)
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
        if config.protocol_version == 2:
            from runtime_manager.api.operations import executor
            from runtime_manager.operations import PlatformReconcileLoop

            _reconcile_loop = PlatformReconcileLoop(executor())
        else:
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

app.include_router(operations.router)
app.include_router(platform_data.router)
app.include_router(platform_observe.router)
app.include_router(upgrade.router)
app.include_router(intents.router)
app.include_router(routes.router)
app.include_router(readonly.router)
app.include_router(storage.router)
app.include_router(appdb.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
