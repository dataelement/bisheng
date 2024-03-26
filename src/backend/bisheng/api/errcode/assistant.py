from bisheng.api.errcode.base import BaseErrorCode


# 组件模块 返回错误码，业务代码104
class AssistantNotExistsError(BaseErrorCode):
    Code: int = 10400
    Msg: str = '助手不存在'
