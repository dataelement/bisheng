"""Error codes for the long-term memory module (F132), module code 121."""

from .base import BaseErrorCode


class MemoryContentTooLongError(BaseErrorCode):
    Code: int = 12100
    Msg: str = "Memory content exceeds 200 characters"


class MemoryContentSensitiveError(BaseErrorCode):
    Code: int = 12101
    Msg: str = "Memory content looks like a password, key, ID number or card number and cannot be saved"


class MemoryContentRelativeTimeError(BaseErrorCode):
    Code: int = 12102
    Msg: str = "Memory content contains a relative time; use a specific date instead"


class MemoryItemNotFoundError(BaseErrorCode):
    Code: int = 12103
    Msg: str = "The memory item does not exist or has already changed"


class MemoryUndoClearedError(BaseErrorCode):
    Code: int = 12104
    Msg: str = "Cannot undo: the memory has been cleared"


class MemoryUndoChangedError(BaseErrorCode):
    Code: int = 12105
    Msg: str = "Cannot undo: the memory item has been changed again"


class MemoryUndoAlreadyDoneError(BaseErrorCode):
    Code: int = 12106
    Msg: str = "This operation has already been undone"


class MemorySearchUnavailableError(BaseErrorCode):
    Code: int = 12107
    Msg: str = "Memory search is temporarily unavailable"


class MemorySearchLimitInvalidError(BaseErrorCode):
    Code: int = 12108
    Msg: str = "Memory retrieval limit must be an integer between 1 and 100"


class MemoryWorkflowSwitchOffError(BaseErrorCode):
    Code: int = 12109
    Msg: str = "The workflow contains a memory retrieval node but memory is turned off in the start node"


class MemoryContentTypeInvalidError(BaseErrorCode):
    Code: int = 12110
    Msg: str = "Memory type must be fact, preference or experience"


class MemoryContentEmptyError(BaseErrorCode):
    Code: int = 12111
    Msg: str = "Memory content cannot be empty"


class MemoryNoModelError(BaseErrorCode):
    Code: int = 12112
    Msg: str = "No model is available for memory consolidation"
