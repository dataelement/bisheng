# Chat Related return error codes 130What/the beginning?
from .base import BaseErrorCode


# This skill has been deleted
class SkillDeletedError(BaseErrorCode):
    Code = 13001
    Msg = "This skill has been deleted"


# The current skill is not online and cannot be spoken to directly
class SkillNotOnlineError(BaseErrorCode):
    Code = 13002
    Msg = "The current skill is not online and cannot be spoken to directly"


# Current compilation failed
class SkillNotBuildError(BaseErrorCode):
    Code = 13003
    Msg = "The current skill has not been compiled and passed, it is not possible to talk directly"


# Backend Service Exception
class ChatServiceError(BaseErrorCode):
    Code = 13004
    Msg = "Backend Service Exception"


# LLM Skill execution error. error={str(e)}
class LLMExecutionError(BaseErrorCode):
    Code = 13005
    Msg = "LLM Skill execution error. error={error}"


# Document parsing failed, click the input upload button to upload again\n\n{str(e)}
class DocumentParseError(BaseErrorCode):
    Code = 13006
    Msg = "Document parsing failed, click the input upload button to upload again\n\n{error}"


# Input data is parsed fail. error={str(e)}
class InputDataParseError(BaseErrorCode):
    Code = 13007
    Msg = "Input data is parsed fail. error={error}"


class WorkflowOfflineError(BaseErrorCode):
    Code = 13010
    Msg = "The current workflow is not online and cannot be chatted directly"
