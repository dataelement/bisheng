from .base import BaseErrorCode


class UnAuthorizedError(BaseErrorCode):
    Code: int = 403
    Msg: str = '暂无操作权限'


class NotFoundError(BaseErrorCode):
    Code: int = 404
    Msg: str = '资源不存在'


class ServerError(BaseErrorCode):
    Code: int = 500
    Msg: str = '服务器错误'