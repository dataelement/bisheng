from bisheng.common.errcode import BaseErrorCode


class DashboardMaxError(BaseErrorCode):
    Code: int = 17000
    Msg: str = '最多允许创建 20 个看板'
