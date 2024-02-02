from bisheng.api.errcode.base import BaseErrorCode


# 模型部署模块 返回错误码，业务代码102
class NotFoundModelError(BaseErrorCode):
    Code: int = 10200
    Msg: str = '模型不存在'
