from bisheng.common.errcode import BaseErrorCode


class DashboardMaxError(BaseErrorCode):
    Code: int = 17000
    Msg: str = '最多允许创建 20 个看板'


class DashBoardShareAuthError(BaseErrorCode):
    Code: int = 17010
    Msg: str = '没有看板分享权限'
