from bisheng.common.errcode import BaseErrorCode


class DatasetNameExistsError(BaseErrorCode):
    """Raised when a dataset with the given name already exists."""
    Code: int = 16000
    Msg: str = 'Dataset name already exists'
