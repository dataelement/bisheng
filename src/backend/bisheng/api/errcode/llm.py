from bisheng.api.errcode.base import BaseErrorCode


#  模型管理模块相关的返回错误码，功能模块代码：108
class ServerExistError(BaseErrorCode):
    Code: int = 10800
    Msg: str = '服务提供方名称重复，请修改'


class ModelNameRepeatError(BaseErrorCode):
    Code: int = 10801
    Msg: str = '模型不可重复'


class ServerAddAllError(BaseErrorCode):
    Code: int = 10802
    Msg: str = '添加服务提供方失败，模型全部初始化失败'


class ServerAddError(BaseErrorCode):
    Code: int = 10803
    Msg: str = '添加服务提供方失败，部分模型初始化失败'
