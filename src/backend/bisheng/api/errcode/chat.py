# Chat 相关的返回错误码 130开头
from bisheng.api.errcode.base import BaseErrorCode


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
    code = 13003
    message = "当前技能未编译通过，无法直接对话"


# 后端服务异常
class ChatServiceError(BaseErrorCode):
    code = 13004
    message = "后端服务异常"


# LLM 技能执行错误. error={str(e)}
class LLMExecutionError(BaseErrorCode):
    code = 13005
    message = "LLM 技能执行错误. error={error}"

# 文档解析失败，点击输入框上传按钮重新上传\n\n{str(e)}
class DocumentParseError(BaseErrorCode):
    code = 13006
    message = "文档解析失败，点击输入框上传按钮重新上传\n\n{error}"

# Input data is parsed fail. error={str(e)}
class InputDataParseError(BaseErrorCode):
    code = 13007
    message = "Input data is parsed fail. error={error}"