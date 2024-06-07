from bisheng.api.errcode.base import BaseErrorCode


# 用户模块相关的返回错误码，功能模块代码：106
class UserValidateError(BaseErrorCode):
    Code: int = 10600
    Msg: str = '账号或密码错误'


class UserPasswordError(BaseErrorCode):
    Code: int = 10601
    Msg: str = '用户密码长期未修改，需要重新修改账号密码'
