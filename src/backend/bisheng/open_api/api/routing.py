"""Run v2 authentication before FastAPI parses or validates request bodies."""

from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, Request
from fastapi.routing import APIRoute

from bisheng.open_api.api.dependencies import verify_open_api_access


class OpenApiRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def authenticated_handler(request: Request):
            async with asynccontextmanager(verify_open_api_access)(request):
                return await handler(request)

        return authenticated_handler


class OpenApiRouter(APIRouter):
    def add_api_route(self, path: str, endpoint: Callable, **kwargs) -> None:
        # include_router otherwise preserves each child's plain APIRoute.
        kwargs["route_class_override"] = OpenApiRoute
        super().add_api_route(path, endpoint, **kwargs)
