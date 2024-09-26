from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from bisheng.api import router, router_rpc
from bisheng.database.init_data import init_default_data
from bisheng.interface.utils import setup_llm_caching
from bisheng.restructure.register import register_restructure
from bisheng.services.utils import initialize_services, teardown_services
from bisheng.settings import settings
from bisheng.utils.http_middleware import CustomMiddleware
from bisheng.utils.logger import configure
from bisheng.utils.threadpool import thread_pool
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, ORJSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi_jwt_auth import AuthJWT
from fastapi_jwt_auth.exceptions import AuthJWTException
from loguru import logger


def handle_http_exception(req: Request, exc: Exception) -> ORJSONResponse:
    if isinstance(exc, HTTPException):
        msg = {
            'status_code': exc.status_code,
            'status_message': exc.detail['error'] if isinstance(exc.detail, dict) else exc.detail
        }
    else:
        msg = {'status_code': 500, 'status_message': str(exc)}
    logger.error(f'{req.method} {req.url} {str(exc)}')
    return ORJSONResponse(content=msg)


def handle_request_validation_error(req: Request, exc: RequestValidationError) -> ORJSONResponse:
    msg = {'status_code': status.HTTP_422_UNPROCESSABLE_ENTITY, 'status_message': exc.errors()}
    logger.error(f'{req.method} {req.url} {exc.errors()} {exc.body}')
    return ORJSONResponse(content=msg)


_EXCEPTION_HANDLERS = {
    HTTPException: handle_http_exception,
    RequestValidationError: handle_request_validation_error,
    Exception: handle_http_exception
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_services()
    setup_llm_caching()
    init_default_data()
    # LangfuseInstance.update()
    yield
    teardown_services()
    thread_pool.tear_down()


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

    @AuthJWT.load_config
    def get_config():
        from bisheng.api.JWT import Settings
        return Settings()

    @app.exception_handler(AuthJWTException)
    def authjwt_exception_handler(request: Request, exc: AuthJWTException):
        return JSONResponse(status_code=401, content={'detail': exc.message})

    app.include_router(router)
    app.include_router(router_rpc)
    register_restructure(app)
    return app


def setup_static_files(app: FastAPI, static_files_dir: Path):
    """
    Setup the static files directory.
    Args:
        app (FastAPI): FastAPI app.
        path (str): Path to the static files directory.
    """
    app.mount(
        '/',
        StaticFiles(directory=static_files_dir, html=True),
        name='static',
    )

    @app.exception_handler(404)
    async def custom_404_handler(request, __):
        path = static_files_dir / 'index.html'

        if not path.exists():
            raise RuntimeError(f'File at path {path} does not exist.')
        return FileResponse(path)


# app = create_app()
# setup_static_files(app, static_files_dir)
def setup_app(static_files_dir: Optional[Path] = None) -> FastAPI:
    """Setup the FastAPI app."""
    # get the directory of the current file
    if not static_files_dir:
        frontend_path = Path(__file__).parent
        static_files_dir = frontend_path / 'frontend'

    app = create_app()
    setup_static_files(app, static_files_dir)
    return app


def setup_promethues(app: FastAPI):
    # Add prometheus asgi middleware to route /metrics requests
    from prometheus_client import make_asgi_app
    metrics_app = make_asgi_app()
    app.mount('/metrics', metrics_app)


configure(settings.logger_conf)

app = create_app()

if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host='0.0.0.0', port=7860, workers=1)
