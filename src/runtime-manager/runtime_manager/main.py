"""FastAPI composition root.

Only protocol v2 and its platform-backed reconciliation loop are registered. Read-only route and egress
projections live on backend, so they do not depend on manager liveness. The
manager API is internal, authenticated with independent platform-control HMAC.
Only /healthz is public liveness; orchestration readiness is authenticated.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from runtime_manager import __version__
from runtime_manager.api import operations, platform_data, platform_observe
from runtime_manager.config import get_config
from runtime_manager.operations import PlatformReconcileLoop
from runtime_manager.reconciler import recovery_budget_seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [runtime-manager] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

_reconcile_loop: PlatformReconcileLoop | None = None


def get_reconcile_loop() -> PlatformReconcileLoop | None:
    """The running loop, for tests and for an operator poking at the process."""
    return _reconcile_loop


@asynccontextmanager
async def lifespan(_: FastAPI, config=None):
    global _reconcile_loop
    config = config or get_config()
    if config.reconcile_enabled:
        from runtime_manager.api.operations import executor

        _reconcile_loop = PlatformReconcileLoop(executor())
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


def create_app(config=None):
    settings = config or get_config()
    if settings.protocol_version != 2:
        raise ValueError("runtime_requires_protocol_v2")

    @asynccontextmanager
    async def configured_lifespan(application):
        async with lifespan(application, config=config):
            yield

    application = FastAPI(
        title="BiSheng runtime manager",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=configured_lifespan,
    )
    application.include_router(operations.router)
    application.include_router(platform_data.router)
    application.include_router(platform_observe.router)

    @application.get("/healthz")
    async def healthz():
        return {"status": "ok", "version": __version__}

    return application


app = create_app()
