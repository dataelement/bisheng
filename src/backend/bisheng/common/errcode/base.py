import json
import re
from typing import Any

from fastapi import WebSocket
from fastapi.exceptions import HTTPException

from bisheng.common.schemas.api import UnifiedResponseModel

# Matches a bare named placeholder such as "{field_name}" in a class Msg.
_MSG_PLACEHOLDER = re.compile(r"\{(\w+)\}")


class BaseErrorCode(Exception):
    # The first three digits of the error code represent the specific function module, and the last two digits represent the specific error report inside the module. For example,10001
    Code: int
    Msg: str

    def __init__(self, exception: Exception | None = None, msg: str | None = None, code: int | None = None, **kwargs):
        self.exception = exception
        self.message = msg or self._format_msg(self.Msg, exception, kwargs)
        self.code = code or self.Code
        self.kwargs = kwargs
        super().__init__(exception)

    @staticmethod
    def _format_msg(template: str, exception: Exception | None, kwargs: dict) -> str:
        """Fill the named placeholders of the class Msg from kwargs and exception.

        A placeholder without a value stays as literal text, so a template that
        shows a pattern (for example a URL shape) is never broken. An explicit
        ``msg`` argument is used as given and does not come through here.
        """
        if not template or "{" not in template:
            return template
        values = {key: value for key, value in kwargs.items() if value is not None}
        if exception is not None:
            values.setdefault("exception", exception)

        def _replace(match: re.Match) -> str:
            key = match.group(1)
            return str(values[key]) if key in values else match.group(0)

        return _MSG_PLACEHOLDER.sub(_replace, template)

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
        error = HTTPException(status_code=cls.Code, detail=msg or cls.Msg)
        # Keep the domain type so version-specific handlers can choose a real
        # HTTP status without losing the legacy response's business code.
        error.error_code_class = cls
        return error

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
