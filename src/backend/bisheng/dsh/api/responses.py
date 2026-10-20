"""DSH's frozen real-HTTP error envelope; legacy business codes remain internal."""

from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from loguru import logger
from starlette.responses import Response

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import DshInvalidRequestError


class DshRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def route(request: Request):
            request.state.request_id = str(uuid4())
            try:
                response = await handler(request)
            except RequestValidationError:
                response = self.error(DshInvalidRequestError(), request.state.request_id)
            except BaseErrorCode as error:
                response = self.error(error, request.state.request_id)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Request-ID"] = request.state.request_id
            capture = getattr(request.state, "audit_capture", None)
            if capture is not None:
                response = AuditObservedResponse(response, capture)
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


class AuditObservedResponse(Response):
    """Observe ASGI send facts, not client receipt or model/billing outcome."""

    def __init__(self, response, capture):
        self.response, self.capture = response, capture
        self.raw_headers, self.status_code = response.raw_headers, response.status_code
        self.background = None

    def notify(self, result):
        try:
            self.capture.response(result)
        except Exception as error:
            # Optional audit observation cannot change transport behavior.
            logger.warning("DSH audit response observer failed ({})", type(error).__name__)

    async def __call__(self, scope, receive, send):
        completed = False
        error_frame = self.status_code >= 400

        async def observed_send(message):
            nonlocal completed, error_frame
            if message["type"] == "http.response.body":
                error_frame |= message.get("body", b"").startswith(b"event: error\n")
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True
                self.notify("ERROR" if error_frame else "COMPLETED")

        try:
            await self.response(scope, receive, observed_send)
        finally:
            if not completed:
                self.notify("INTERRUPTED")
