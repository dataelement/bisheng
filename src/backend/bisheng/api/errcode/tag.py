from bisheng.api.errcode.base import BaseErrorCode


# 标签模块相关的返回错误码，功能模块代码：107
class TagExistError(BaseErrorCode):
    Code: int = 10700
    Msg: str = '标签已存在'


class TagNotExistError(BaseErrorCode):
    Code: int = 10701
    Msg: str = '未找到对应的标签'
