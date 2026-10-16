"""DSH's frozen real-HTTP error envelope; legacy business codes remain internal."""

from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from loguru import logger
from starlette.requests import ClientDisconnect

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import DshInternalErrorError, DshInvalidRequestError


class DshRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def route(request: Request):
            try:
                if request.method == "POST" and request.url.path.endswith(("/dsh/responses", "/dsh/chat/completions")):
                    # Bound incremental reads, including chunked requests without Content-Length.
                    body = bytearray()
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > 32 * 1024 * 1024:
                            raise DshInvalidRequestError()
                        body.extend(chunk)
                    request._body = bytes(body)
                response = await handler(request)
            except RequestValidationError:
                response = self.error(DshInvalidRequestError())
            except BaseErrorCode as error:
                response = self.error(error)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response

        return route

    @staticmethod
    def error(error: BaseErrorCode, request_id: str | None = None) -> JSONResponse:
        return JSONResponse(
            status_code=getattr(error, "HttpStatus", 500),
            content={
                "error": {
                    "message": error.Msg,
                    "type": getattr(error, "ErrorType", "server_error"),
                    "code": getattr(error, "ClientCode", "internal_error"),
                },
                "request_id": request_id or str(uuid4()),
            },
        )


class ToolInvocationRoute(DshRoute):
    """Contain unexpected tool failures without logging provider payloads."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def route(request):
            try:
                return await handler(request)
            except ClientDisconnect:
                raise
            except Exception as error:
                request_id = str(uuid4())
                # Type only: messages and tracebacks may embed credentials or upstream payloads.
                logger.error("Tool internal failure type={} request_id={}", type(error).__name__, request_id)
                response = self.error(DshInternalErrorError(), request_id)
                response.headers["Cache-Control"] = "no-store"
                response.headers["Referrer-Policy"] = "no-referrer"
                return response

        return route
