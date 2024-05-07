from bisheng.api.errcode.base import BaseErrorCode


# 组件模块 返回错误码，业务代码104
class AssistantNotExistsError(BaseErrorCode):
    Code: int = 10400
    Msg: str = '助手不存在'


class AssistantInitError(BaseErrorCode):
    Code: int = 10401
    Msg: str = '助手上线失败'


class AssistantNameRepeatError(BaseErrorCode):
    Code: int = 10402
    Msg: str = '助手名称重复'


class AssistantNotEditError(BaseErrorCode):
    Code: int = 10403
    Msg: str = '助手已上线，不可编辑'


class ToolTypeRepeatError(BaseErrorCode):
    Code: int = 10410
    Msg: str = '工具名称已存在'


class ToolTypeEmptyError(BaseErrorCode):
    Code: int = 10411
    Msg: str = '工具下的API不能为空'


class ToolTypeNotExistsError(BaseErrorCode):
    Code: int = 10412
    Msg: str = '工具不存在'


class ToolTypeIsPresetError(BaseErrorCode):
    Code: int = 10413
    Msg: str = '预置工具类别不可删除'
