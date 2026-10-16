"""DSH's frozen real-HTTP error envelope; legacy business codes remain internal."""

import json
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from loguru import logger

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import DshInternalErrorError, DshInvalidRequestError


class DshRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def route(request: Request):
            try:
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
    def error(error: BaseErrorCode) -> JSONResponse:
        return JSONResponse(
            status_code=getattr(error, "HttpStatus", 500),
            content={
                "error": {
                    "message": error.Msg,
                    "type": getattr(error, "ErrorType", "server_error"),
                    "code": getattr(error, "ClientCode", "internal_error"),
                },
                "request_id": str(uuid4()),
            },
        )


class PublishedToolRoute(DshRoute):
    """Contain unexpected tool failures without logging provider payloads."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def route(request):
            try:
                return await handler(request)
            except Exception as error:
                from starlette.requests import ClientDisconnect

                if isinstance(error, ClientDisconnect):
                    raise
                response = self.error(DshInternalErrorError())
                logger.error(
                    "Published tool internal failure type={} request_id={}",
                    type(error).__name__,
                    json.loads(response.body)["request_id"],
                )
                response.headers["Cache-Control"] = "no-store"
                response.headers["Referrer-Policy"] = "no-referrer"
                return response

        return route
