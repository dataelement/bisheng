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


class SandboxCodeNodeOutputTooLargeError(BaseErrorCode):
    Code: int = 28007
    Msg: str = "Code node result is {size} bytes, over the {limit}-byte limit"


class SandboxCodeNodeNoResultError(BaseErrorCode):
    Code: int = 28008
    Msg: str = "Code node finished without returning a result from main"


class SandboxConfigurationError(BaseErrorCode):
    Code: int = 28009
    Msg: str = "请为任务模式配置隔离代码执行环境 (container 或 e2b) 后重试"
