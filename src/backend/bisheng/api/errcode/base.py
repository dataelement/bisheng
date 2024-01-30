from bisheng.api.v1.schemas import UnifiedResponseModel
from pydantic import BaseModel


class BaseErrorCode(BaseModel):
    # 错误码前三位代表具体功能模块，后两位表示模块内部具体的报错。例如10001
    Code: int
    Msg: str

    @classmethod
    def return_resp(cls, data: any = None) -> UnifiedResponseModel:
        return UnifiedResponseModel(status_code=cls.Code, status_msg=cls.Msg, data=data)
