import json

from fastapi import WebSocket
from fastapi.exceptions import HTTPException

from bisheng.api.v1.schemas import UnifiedResponseModel


class BaseErrorCode(Exception):
    # 错误码前三位代表具体功能模块，后两位表示模块内部具体的报错。例如10001
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

    # websocket error message
    async def websocket_close_message(self, websocket: WebSocket):
        reason = {
            "status_code": self.code,
            "status_message": self.message,
            "data": {"exception": str(self), **self.kwargs}
        }
        await websocket.send_json({"category": "error", "type": "end", "message": reason})

        await websocket.close(reason=self.message[:10])
