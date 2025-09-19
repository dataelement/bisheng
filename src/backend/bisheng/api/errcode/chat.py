# Chat 相关的返回错误码 130开头
from .base import BaseErrorCode


# 该技能已被删除
class SkillDeletedError(BaseErrorCode):
    code = 13001
    message = "该技能已被删除"


# 当前技能未上线，无法直接对话
class SkillNotOnlineError(BaseErrorCode):
    code = 13002
    message = "当前技能未上线，无法直接对话"


# 当前编译没通过
class SkillNotBuildError(BaseErrorCode):
    Code = 13003
    Msg = "当前技能未编译通过，无法直接对话"


# 后端服务异常
class ChatServiceError(BaseErrorCode):
    Code = 13004
    Msg = "后端服务异常"


# LLM 技能执行错误. error={str(e)}
class LLMExecutionError(BaseErrorCode):
    Code = 13005
    Msg = "LLM 技能执行错误. error={error}"

# 文档解析失败，点击输入框上传按钮重新上传\n\n{str(e)}
class DocumentParseError(BaseErrorCode):
    Code = 13006
    Msg = "文档解析失败，点击输入框上传按钮重新上传\n\n{error}"

# Input data is parsed fail. error={str(e)}
class InputDataParseError(BaseErrorCode):
    Code = 13007
    Msg = "Input data is parsed fail. error={error}"