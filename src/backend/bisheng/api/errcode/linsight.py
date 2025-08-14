from bisheng.api.errcode.base import BaseErrorCode


class SopFileError(BaseErrorCode):
    Code: int = 11010
    Msg: str = 'SOP文件格式不符合要求'
