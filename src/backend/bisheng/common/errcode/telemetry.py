from bisheng.common.errcode import BaseErrorCode


class DashboardMaxError(BaseErrorCode):
    Code: int = 17000
    Msg: str = 'Creation is allowed at most 20 kanban boards'


class DashBoardShareAuthError(BaseErrorCode):
    Code: int = 17005
    Msg: str = 'No Kanban sharing permissions'


class QueryDatasetNotFoundError(BaseErrorCode):
    Code: int = 17010
    Msg: str = 'Corresponding dataset configuration not found'


class QueryVirtualMaxError(BaseErrorCode):
    Code: int = 17011
    Msg: str = 'Virtual indicators can only be queried individually'


class QueryMetricNotFoundError(BaseErrorCode):
    Code = 17012
    Msg = 'No corresponding metric configurations found'


class QueryAggregationNotFoundError(BaseErrorCode):
    Code = 17013
    Msg = 'No corresponding summary method found'


class QueryDimensionNotFoundError(BaseErrorCode):
    Code = 17014
    Msg = 'No corresponding dimension configurations found'


class QueryOperatorNotFoundError(BaseErrorCode):
    Code = 17015
    Msg = 'Corresponding operator configuration not found'


class DashboardExportEmptyError(BaseErrorCode):
    Code: int = 17016
    Msg: str = 'No detail rows to export'


class DashboardExportLimitExceededError(BaseErrorCode):
    Code: int = 17017
    Msg: str = 'Detail row count exceeds export limit'


class LoginParticipationFilterError(BaseErrorCode):
    Code: int = 17019
    Msg: str = '登录参与统计仅支持自然日及以上粒度, 以及可确定起止日期的 AND 时间筛选'


class LoginParticipationDataError(BaseErrorCode):
    Code: int = 17020
    Msg: str = '登录参与统计数据读取不完整或格式异常, 请重试并检查统计索引'
