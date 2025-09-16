from bisheng.api.errcode.base import BaseErrorCode


class SopFileError(BaseErrorCode):
    Code: int = 11010
    Msg: str = 'SOP文件格式不符合要求'


class SopShowcaseError(BaseErrorCode):
    Code: int = 11011
    Msg: str = 'SOP设置精选案例失败'
