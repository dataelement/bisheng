from .base import BaseErrorCode


# Component Modules Return error code, business code104
class AssistantNotExistsError(BaseErrorCode):
    Code: int = 10400
    Msg: str = 'Assistant does not exist'


class AssistantInitError(BaseErrorCode):
    Code: int = 10401
    Msg: str = 'Assistant onboarding failed: {exception}'


class AssistantNameRepeatError(BaseErrorCode):
    Code: int = 10402
    Msg: str = 'Duplicate assistant name'


class AssistantNotEditError(BaseErrorCode):
    Code: int = 10403
    Msg: str = 'Assistant is live and not editable'


# The assistant has been deleted
class AssistantDeletedError(BaseErrorCode):
    Code: int = 10420
    Msg: str = 'The assistant has been deleted'


# The assistant is currently not online and cannot talk directly
class AssistantNotOnlineError(BaseErrorCode):
    Code: int = 10421
    Msg: str = 'The assistant is currently not online and cannot talk directly'


# Assistant reasoning model list is empty
class AssistantModelEmptyError(BaseErrorCode):
    Code: int = 10422
    Msg: str = 'Assistant reasoning model list is empty'


# No assistant inference model configured
class AssistantModelNotConfigError(BaseErrorCode):
    Code: int = 10423
    Msg: str = 'No assistant inference model configured'


class AssistantAutoLLMError(BaseErrorCode):
    Code: int = 10424
    Msg: str = 'Assistant portrait auto-optimization model is not configured'


# Other errors
class AssistantOtherError(BaseErrorCode):
    Code: int = 10499
    Msg: str = 'Assistant Service Exception'
