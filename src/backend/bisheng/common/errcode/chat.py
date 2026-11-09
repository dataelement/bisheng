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


class ProjectUnavailableError(BaseErrorCode):
    Code: int = 13011
    Msg = "This project is unavailable"


class ProjectInputError(BaseErrorCode):
    Code: int = 13012
    Msg = "Invalid project operation"


class ProjectSnapshotChangedError(BaseErrorCode):
    Code: int = 13013
    Msg = "Project data changed; reload the snapshot"


class ProjectRequestConflictError(BaseErrorCode):
    Code: int = 13014
    Msg = "This request identifier was already used for different input"


class ProjectConversationError(BaseErrorCode):
    Code: int = 13015
    Msg = "This conversation cannot be added to your project"


class ProjectSyncUnavailableError(BaseErrorCode):
    Code: int = 13016
    Msg = "Project synchronization is temporarily unavailable"


class ProjectImportError(BaseErrorCode):
    Code: int = 13017
    Msg = "Invalid project import batch"


class ProjectSessionExistsError(BaseErrorCode):
    Code: int = 13018
    Msg = "This request already created a conversation; open the existing conversation"
