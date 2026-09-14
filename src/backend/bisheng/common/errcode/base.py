import json
from typing import Any

from fastapi import WebSocket
from fastapi.exceptions import HTTPException

from bisheng.common.schemas.api import UnifiedResponseModel


class BaseErrorCode(Exception):
    # The first three digits of the error code represent the specific function module, and the last two digits represent the specific error report inside the module. For example,10001
    Code: int
    Msg: str

    def __init__(self, exception: Exception | None = None, msg: str | None = None, code: int | None = None, **kwargs):
        self.exception = exception
        self.message = msg or self.Msg
        self.code = code or self.Code
        self.kwargs = kwargs
        super().__init__(exception)

    def __str__(self):
        return str(self.exception) if self.exception else self.message

    @classmethod
    def return_resp(cls, msg: str | None = None, data: Any = None) -> UnifiedResponseModel:
        return UnifiedResponseModel(status_code=cls.Code, status_message=msg or cls.Msg, data=data)

    def return_resp_instance(self, data: Any = None) -> UnifiedResponseModel:
        data = data if data is not None else {"exception": str(self), **self.kwargs}

        return UnifiedResponseModel(status_code=self.code, status_message=self.message, data=data)

    @classmethod
    def http_exception(cls, msg: str | None = None) -> HTTPException:
        return BusinessHTTPException(cls, msg=msg)

    @classmethod
    def to_sse_event(cls, msg: str | None = None, data: Any = None, event: str = "error", **kwargs) -> dict:
        data = data if data is not None else {"exception": cls.Msg, **kwargs}
        return {
            "event": event,
            "data": json.dumps({"status_code": cls.Code, "status_message": msg or cls.Msg, "data": data}),
        }

    def to_sse_event_instance(self, event: str = "error", data: Any = None) -> dict:
        data = data if data is not None else {"exception": str(self), **self.kwargs}
        return {
            "event": event,
            "data": json.dumps({"status_code": self.code, "status_message": self.message, "data": data}),
        }

    def to_sse_event_instance_str(self, event: str = "error", data: Any = None) -> str:
        data = data if data is not None else {"exception": str(self), **self.kwargs}
        msg = json.dumps({"status_code": self.code, "status_message": self.message, "data": data}, ensure_ascii=False)
        return f"event: {event}\ndata: {msg}\n\n"

    def to_dict(self, data: Any = None) -> dict:
        data = data if data is not None else {"exception": str(self), **self.kwargs}
        return {"status_code": self.code, "status_message": self.message, "data": data}

    def to_json_str(self, data: Any = None) -> str:
        data = data if data is not None else {"exception": str(self), **self.kwargs}
        return json.dumps({"status_code": self.code, "status_message": self.message, "data": data}, ensure_ascii=False)

    # websocket error message
    async def websocket_close_message(self, websocket: WebSocket, close_ws: bool = True):
        reason = {
            "status_code": self.code,
            "status_message": self.message,
            "data": {"exception": str(self), **self.kwargs},
        }
        await websocket.send_json({"category": "error", "type": "end", "message": reason})
        if close_ws:
            await websocket.close(reason=self.message[:10])


class BusinessHTTPException(HTTPException):
    """Preserve the business error type for transport-specific status mapping."""

    def __init__(self, error_type: type[BaseErrorCode], *, msg: str | None = None):
        self.error_type = error_type
        super().__init__(status_code=error_type.Code, detail=msg or error_type.Msg)
