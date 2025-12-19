from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse
from loguru import logger

from bisheng.api import router, router_rpc
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.exceptions.auth import AuthJWTException
from bisheng.common.init_data import init_default_data
from bisheng.common.services.config_service import settings
from bisheng.core.context import initialize_app_context, close_app_context
from bisheng.core.logger import set_logger_config
from bisheng.services.utils import initialize_services, teardown_services
from bisheng.utils.http_middleware import CustomMiddleware, WebSocketLoggingMiddleware
from bisheng.utils.threadpool import thread_pool


def handle_http_exception(req: Request, exc: Exception) -> ORJSONResponse:
    if isinstance(exc, HTTPException):
        msg = {
            'status_code': exc.status_code,
            'status_message': exc.detail['error'] if isinstance(exc.detail, dict) else exc.detail
        }
    elif isinstance(exc, BaseErrorCode):
        data = {'exception': str(exc), **exc.kwargs} if exc.kwargs else {'exception': str(exc)}
        msg = {'status_code': exc.code, 'status_message': exc.message,
               'data': data}
    else:
        logger.exception('Unhandled exception')
        msg = {'status_code': 500, 'status_message': str(exc)}
    logger.error(f'{req.method} {req.url} {str(exc)}')
    return ORJSONResponse(content=msg)


def handle_request_validation_error(req: Request, exc: RequestValidationError) -> ORJSONResponse:
    msg = {'status_code': status.HTTP_422_UNPROCESSABLE_ENTITY, 'status_message': exc.errors()}
    logger.error(f'{req.method} {req.url} {str(exc.errors())[:100]}')
    return ORJSONResponse(content=msg)


_EXCEPTION_HANDLERS = {
    HTTPException: handle_http_exception,
    RequestValidationError: handle_request_validation_error,
    BaseErrorCode: handle_http_exception,
    Exception: handle_http_exception
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_app_context(config=settings)
    initialize_services()
    await init_default_data()
    # LangfuseInstance.update()
    yield
    teardown_services()
    thread_pool.tear_down()
    await close_app_context()


def create_app():
    """Create the FastAPI app and include the router."""

    app = FastAPI(
        default_response_class=ORJSONResponse,
        exception_handlers=_EXCEPTION_HANDLERS,
        lifespan=lifespan,
    )

    origins = [
        '*',
    ]

    @app.get('/health')
    def get_health():
        return {'status': 'OK'}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    app.add_middleware(CustomMiddleware)
    app.add_middleware(WebSocketLoggingMiddleware)

    @app.exception_handler(AuthJWTException)
    def authjwt_exception_handler(request: Request, exc: AuthJWTException):
        return JSONResponse(status_code=401, content={'detail': str(exc)})

    app.include_router(router)
    app.include_router(router_rpc)
    if settings.debug:
        import tracemalloc
        tracemalloc.start()

    return app


app = create_app()

if __name__ == '__main__':
    import uvicorn

    set_logger_config(settings.logger_conf)

    uvicorn.run(app, host='0.0.0.0', port=7860, workers=1, log_config=None)
