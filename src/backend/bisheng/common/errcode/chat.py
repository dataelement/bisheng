# Chat Related return error codes 130What/the beginning?
from .base import BaseErrorCode


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
