from .base import BaseErrorCode


# 组件模块 返回错误码，业务代码104
class AssistantNotExistsError(BaseErrorCode):
    Code: int = 10400
    Msg: str = '助手不存在'


class AssistantInitError(BaseErrorCode):
    Code: int = 10401
    Msg: str = '助手上线失败: {exception}'


class AssistantNameRepeatError(BaseErrorCode):
    Code: int = 10402
    Msg: str = '助手名称重复'


class AssistantNotEditError(BaseErrorCode):
    Code: int = 10403
    Msg: str = '助手已上线，不可编辑'


# 该助手已被删除
class AssistantDeletedError(BaseErrorCode):
    Code: int = 10420
    Msg: str = '该助手已被删除'


# 当前助手未上线，无法直接对话
class AssistantNotOnlineError(BaseErrorCode):
    Code: int = 10421
    Msg: str = '当前助手未上线，无法直接对话'


# 助手推理模型列表为空
class AssistantModelEmptyError(BaseErrorCode):
    Code: int = 10422
    Msg: str = '助手推理模型列表为空'


# 未配置助手推理模型
class AssistantModelNotConfigError(BaseErrorCode):
    Code: int = 10423
    Msg: str = '未配置助手推理模型'


class AssistantAutoLLMError(BaseErrorCode):
    Code: int = 10424
    Msg: str = '未配置助手画像自动优化模型'


# 其它错误
class AssistantOtherError(BaseErrorCode):
    Code: int = 10499
    Msg: str = '助手服务异常'
