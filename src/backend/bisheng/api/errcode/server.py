from bisheng.api.errcode.base import BaseErrorCode


# RT服务相关的返回错误码，功能模块代码：100
class NotFoundServerError(BaseErrorCode):
    Code: int = 10001
    Msg: str = '未找到RT服务'
