from .base import BaseErrorCode


# Dictionary module error codes: 191xx
class DictionaryNotFoundError(BaseErrorCode):
    """字典条目不存在"""

    Code: int = 19100
    Msg: str = "Dictionary entry does not exist"


class DictionaryDuplicateError(BaseErrorCode):
    """同一租户下相同类型的字典取值已存在"""

    Code: int = 19101
    Msg: str = "Dictionary entry already exists"


class DictionaryPermissionDeniedError(BaseErrorCode):
    """仅管理员可维护字典"""

    Code: int = 19102
    Msg: str = "Only administrators can manage dictionary entries"
