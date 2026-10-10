from .base import BaseErrorCode


class SandboxUnreachableError(BaseErrorCode):
    Code: int = 28001
    Msg: str = "Isolation environment unreachable"


class SandboxCapacityExceededError(BaseErrorCode):
    Code: int = 28002
    Msg: str = "Isolation environment at capacity"


class SandboxExecTimeoutError(BaseErrorCode):
    Code: int = 28003
    Msg: str = "Execution timed out with no deliverable"


class SandboxCopyInLimitError(BaseErrorCode):
    Code: int = 28004
    Msg: str = "Copy-in skipped an oversized file"


class SandboxCodeNodeOutputError(BaseErrorCode):
    Code: int = 28005
    Msg: str = "Code node output is not serializable"


class SandboxProtocolError(BaseErrorCode):
    Code: int = 28006
    Msg: str = "Isolation environment response is invalid"
