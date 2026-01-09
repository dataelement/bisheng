import json

from fastapi import WebSocket
from fastapi.exceptions import HTTPException

from bisheng.common.schemas.api import UnifiedResponseModel


class BaseErrorCode(Exception):
    # The first three digits of the error code represent the specific function module, and the last two digits represent the specific error report inside the module. For example,10001
    Code: int
    Msg: str

    def __init__(self, exception: Exception = None, msg: str = None, code: int = None, **kwargs):
        self.exception = exception
        self.message = msg or self.Msg
        self.code = code or self.Code
        self.kwargs = kwargs
        super().__init__(exception)

    def __str__(self):
        return str(self.exception) if self.exception else self.message

    @classmethod
    def return_resp(cls, msg: str = None, data: any = None) -> UnifiedResponseModel:
        return UnifiedResponseModel(status_code=cls.Code, status_message=msg or cls.Msg,
                                    data=data)

    def return_resp_instance(self, data: any = None) -> UnifiedResponseModel:
        data = data if data is not None else {"exception": str(self), **self.kwargs}

        return UnifiedResponseModel(status_code=self.code, status_message=self.message,
                                    data=data)

    @classmethod
    def http_exception(cls, msg: str = None) -> HTTPException:
        return HTTPException(status_code=cls.Code, detail=msg or cls.Msg)

    @classmethod
    def to_sse_event(cls, msg: str = None, data: any = None, event: str = "error", **kwargs) -> dict:
        data = data if data is not None else {"exception": cls.Msg, **kwargs}
        return {
            "event": event,
            "data": json.dumps({
                "status_code": cls.Code,
                "status_message": msg or cls.Msg,
                "data": data
            })
        }

    def to_sse_event_instance(self, event: str = "error", data: any = None) -> dict:
        data = data if data is not None else {"exception": str(self), **self.kwargs}
        return {
            "event": event,
            "data": json.dumps({
                "status_code": self.code,
                "status_message": self.message,
                "data": data
            })
        }

    def to_sse_event_instance_str(self, event: str = "error", data: any = None) -> str:
        data = data if data is not None else {"exception": str(self), **self.kwargs}
        msg = json.dumps({
            "status_code": self.code,
            "status_message": self.message,
            "data": data
        }, ensure_ascii=False)
        return f'event: {event}\ndata: {msg}\n\n'

    def to_dict(self, data: any = None) -> dict:
        data = data if data is not None else {"exception": str(self), **self.kwargs}
        return {
            "status_code": self.code,
            "status_message": self.message,
            "data": data
        }

    def to_json_str(self, data: any = None) -> str:
        data = data if data is not None else {"exception": str(self), **self.kwargs}
        return json.dumps({
            "status_code": self.code,
            "status_message": self.message,
            "data": data
        }, ensure_ascii=False)

    # websocket error message
    async def websocket_close_message(self, websocket: WebSocket, close_ws: bool = True):
        reason = {
            "status_code": self.code,
            "status_message": self.message,
            "data": {"exception": str(self), **self.kwargs}
        }
        await websocket.send_json({"category": "error", "type": "end", "message": reason})
        if close_ws:
            await websocket.close(reason=self.message[:10])
