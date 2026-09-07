"""True HTTP status handling for public v3 policy failures."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from bisheng.public_endpoints.domain.services.guest_policy import PublicAccessError


async def handle_public_access_error(_request: Request, exc: PublicAccessError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"status_code": exc.status_code, "status_message": exc.message},
    )


def register_public_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(PublicAccessError, handle_public_access_error)


__all__ = ["register_public_exception_handlers"]
