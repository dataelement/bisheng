"""DSH's frozen real-HTTP error envelope; legacy business codes remain internal."""

from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import DshInvalidRequestError


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
