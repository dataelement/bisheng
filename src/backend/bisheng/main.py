import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from bisheng.api.router import router, router_rpc
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.exceptions.auth import AuthJWTException
from bisheng.common.init_data import init_default_data
from bisheng.common.middleware.admin_scope import AdminScopeMiddleware
from bisheng.common.services.config_service import settings
from bisheng.core.context import close_app_context, initialize_app_context
from bisheng.core.logger import set_logger_config
from bisheng.utils.http_middleware import CustomMiddleware, WebSocketLoggingMiddleware
from bisheng.utils.threadpool import thread_pool


def handle_http_exception(req: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        msg = {
            "status_code": exc.status_code,
            "status_message": exc.detail["error"] if isinstance(exc.detail, dict) else exc.detail,
        }
    elif isinstance(exc, BaseErrorCode):
        data = {"exception": str(exc), **exc.kwargs} if exc.kwargs else {"exception": str(exc)}
        msg = {"status_code": exc.code, "status_message": exc.message, "data": data}
    else:
        logger.exception("Unhandled exception")
        msg = {"status_code": 500, "status_message": str(exc)}
    logger.error(f"{req.method} {req.url} {exc!s}")
    return JSONResponse(content=msg)


def handle_request_validation_error(req: Request, exc: RequestValidationError) -> JSONResponse:
    msg = {"status_code": status.HTTP_422_UNPROCESSABLE_ENTITY, "status_message": exc.errors()}
    logger.error(f"{req.method} {req.url} {str(exc.errors())[:100]}")
    return JSONResponse(content=msg)


_EXCEPTION_HANDLERS = {
    HTTPException: handle_http_exception,
    RequestValidationError: handle_request_validation_error,
    BaseErrorCode: handle_http_exception,
    Exception: handle_http_exception,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_app_context(config=settings)
    await init_default_data()
    # F034: align frozen system permission tiers with newly-added
    # move_file/move_folder on every boot. Idempotent + non-critical — a failure
    # only leaves the admin permission UI stale, so it must never block startup.
    try:
        from bisheng.permission.domain.relation_model_backfill import (
            backfill_relation_model_move_permissions,
        )

        await backfill_relation_model_move_permissions()
    except Exception:
        logger.exception("relation-model move-permission backfill failed; continuing startup")
    # F035: align legacy linsight data with the deepagents task-mode shape on every
    # boot. Both are idempotent + non-critical — failure only leaves stale menu
    # grants / model config (operators can re-run the standalone scripts), so it
    # must never block startup. The SOP->Skill data migration is intentionally NOT
    # here (it writes object storage and is heavier — stays a manual ops script).
    try:
        from bisheng.permission.domain.linsight_task_mode_menu_backfill import (
            backfill_linsight_task_mode_web_menu,
        )

        await backfill_linsight_task_mode_web_menu()
    except Exception:
        logger.exception("linsight task-mode menu backfill failed; continuing startup")
    try:
        from bisheng.llm.domain.services.linsight_default_model_backfill import (
            backfill_linsight_default_model,
        )

        await backfill_linsight_default_model()
    except Exception:
        logger.exception("linsight default-model backfill failed; continuing startup")
    # LangfuseInstance.update()
    yield
    thread_pool.tear_down()
    await close_app_context()


def create_app():
    """Create the FastAPI app and include the router."""

    app = FastAPI(
        exception_handlers=_EXCEPTION_HANDLERS,
        lifespan=lifespan,
    )

    # 前端 axios 使用 withCredentials=true 时，浏览器禁止 ACAO 为 *。
    # 可通过环境变量 BISHENG_CORS_ORIGINS 覆盖，逗号分隔，例如：
    # BISHENG_CORS_ORIGINS=http://localhost:3001,http://127.0.0.1:3001
    _cors_raw = (os.getenv("BISHENG_CORS_ORIGINS") or "").strip()
    if _cors_raw:
        origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    else:
        origins = [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]

    @app.get("/health")
    def get_health():
        return {"status": "OK"}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Starlette middleware uses LIFO registration — the middleware added
    # latest is the *outermost* on inbound. We want CustomMiddleware (JWT
    # decode + visible_tenant_ids) to run *before* AdminScopeMiddleware on
    # the inbound path, which means AdminScopeMiddleware must be added
    # *first* (inner). See ``common/middleware/admin_scope.py`` docstring.
    app.add_middleware(AdminScopeMiddleware)
    app.add_middleware(CustomMiddleware)
    app.add_middleware(WebSocketLoggingMiddleware)

    @app.exception_handler(AuthJWTException)
    def authjwt_exception_handler(request: Request, exc: AuthJWTException):
        return JSONResponse(status_code=401, content={"detail": str(exc)})

    app.include_router(router)
    app.include_router(router_rpc)
    from bisheng.department.api.endpoints.department_limit import (
        router as department_limit_router,
    )

    app.include_router(
        department_limit_router,
        prefix="/api/department-limit",
        tags=["Department traffic"],
    )
    if settings.debug:
        import tracemalloc

        tracemalloc.start()

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    set_logger_config(settings.logger_conf)

    uvicorn.run(app, host="0.0.0.0", port=7860, workers=1, log_config=None)
