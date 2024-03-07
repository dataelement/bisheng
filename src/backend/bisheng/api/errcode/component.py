from bisheng.api.errcode.base import BaseErrorCode


# 组件模块 返回错误码，业务代码103
class ComponentExistError(BaseErrorCode):
    Code: int = 10300
    Msg: str = '组件已存在'


class ComponentNotExistError(BaseErrorCode):
    Code: int = 10301
    Msg: str = '组件不存在'
