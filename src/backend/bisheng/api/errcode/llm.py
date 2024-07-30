from bisheng.api.errcode.base import BaseErrorCode


#  模型管理模块相关的返回错误码，功能模块代码：108
class ServerExistError(BaseErrorCode):
    Code: int = 10800
    Msg: str = '服务提供方名称不可重复'


class ModelNameRepeatError(BaseErrorCode):
    Code: int = 10801
    Msg: str = '模型不可重复'
