from enum import Enum


class WorkType(Enum):
    GPTS = "assistant"
    WORKFLOW = "workflow"


class IgnoreException(Exception):
    """Exception that does not require traceback logging."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message
