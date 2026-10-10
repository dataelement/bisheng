"""Explicitly started diagnostic process; no production startup side effects."""

import asyncio
import os
import sys
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from loguru import logger

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.exceptions.auth import AuthJWTException
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context import FunctionContextManager, close_app_context, initialize_app_context
from bisheng.core.context.manager import app_context
from bisheng.eplus.api.debug_router import create_debug_router
from bisheng.eplus.domain.services.debug_admission import DebugAdmissionService
from bisheng.eplus.infrastructure.debug_adapters import PlatformDebugAuthorization, PlatformDebugReader
from bisheng.eplus.infrastructure.debug_gate import RedisDebugGate
from bisheng.eplus.infrastructure.debug_runtime import DebugAssistantRuntime
from bisheng.user.domain.services.auth import AuthJwt
from bisheng.utils.http_middleware import CustomMiddleware, _extract_http_access_token


def register_permission_context():
    if not settings.openfga.enabled:
        return
    from bisheng.api.services.f048_permission_runtime import initialize_f048_api_runtime
    from bisheng.common.permission_identity import configure_tenant_admin_checker
    from bisheng.department.domain.services.department_projection_scope import (
        get_department_projection_scope,
        register_department_projection_runtime_context,
    )
    from bisheng.permission.application.access import clear_f048_runtime
    from bisheng.permission.application.process_runtime import (
        F048_PERMISSION_RUNTIME_CONTEXT,
        ProcessPermissionRuntime,
        bind_f048_process_runtime,
        run_f048_process_heartbeat,
    )
    from bisheng.permission.application.relation_api import is_tenant_admin

    async def initialize():
        # Unlike the normal API startup, diagnostics must never bootstrap a catalog.
        manager = app_context.get_context("openfga")
        client = await manager.async_get_instance()
        runtime = await initialize_f048_api_runtime(
            client, external_scopes={"department": get_department_projection_scope()}
        )
        await bind_f048_process_runtime(manager, runtime.components.facade)
        return ProcessPermissionRuntime(runtime, asyncio.create_task(run_f048_process_heartbeat(manager)))

    async def cleanup(context):
        context.heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await context.heartbeat_task
        clear_f048_runtime()

    configure_tenant_admin_checker(is_tenant_admin)
    app_context.register_context(
        FunctionContextManager(name=F048_PERMISSION_RUNTIME_CONTEXT, init_func=initialize, cleanup_func=cleanup),
        dependencies=["openfga"],
        lazy=True,
    )
    register_department_projection_runtime_context()


class DebugAuthJwt(AuthJwt):
    def get_subject(self, auth_from="request", token=None, websocket=None):
        if auth_from == "request" and token is None:
            token = _extract_http_access_token(self.req)
        return super().get_subject(auth_from=auth_from, token=token, websocket=websocket)


def debug_auth_jwt(req: Request, res: Response):
    return DebugAuthJwt(req=req, res=res)


def configure_debug_logging():
    # Only request-local, sanitized diagnostics may reach this process's sinks.
    logger.remove()
    logger.add(
        sys.stderr,
        filter=lambda record: record["extra"].get("robot_debug_safe", False),
        diagnose=False,
        backtrace=False,
    )


class DebugBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > 512 * 1024:
                return await JSONResponse(
                    {"status_code": 413, "status_message": "debug request too large"}, status_code=413
                )(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body", False):
                break

        async def replay():
            return chunks.pop(0) if chunks else await receive()

        await self.app(scope, replay, send)


class LazyDebugGate:
    @asynccontextmanager
    async def acquire(self):
        redis = await get_redis_client()
        async with RedisDebugGate(redis.async_connection).acquire():
            yield


def create_app() -> FastAPI:
    if os.getenv("EPLUS_DEBUG_ENABLED", "").lower() != "true":
        raise RuntimeError("set EPLUS_DEBUG_ENABLED=true to start robot debug")
    if os.getenv("BISHENG_RECORD_HISTORY"):
        raise RuntimeError("robot debug refuses local history recording")

    @asynccontextmanager
    async def lifespan(app):
        await initialize_app_context(settings)
        try:
            # Production/model libraries can log bodies or provider exceptions.
            # This isolated process emits only explicitly safe diagnostic records.
            configure_debug_logging()
            register_permission_context()
            yield
        finally:
            await close_app_context()

    async def service_provider(session=Depends(get_db_session)):
        return DebugAdmissionService(PlatformDebugAuthorization(), PlatformDebugReader(session))

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.dependency_overrides[AuthJwt] = debug_auth_jwt
    app.add_middleware(CustomMiddleware)
    app.add_middleware(DebugBodyLimit)
    app.include_router(create_debug_router(service_provider, DebugAssistantRuntime(), LazyDebugGate()))

    @app.exception_handler(AuthJWTException)
    async def auth_error(request, exc):
        return JSONResponse({"status_code": 401, "status_message": "login required"}, status_code=401)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse({"status_code": exc.status_code, "status_message": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(BaseErrorCode)
    async def business_error(request, exc):
        return JSONResponse(
            {"status_code": exc.code, "status_message": "debug authorization or resource unavailable"}, status_code=403
        )

    return app
