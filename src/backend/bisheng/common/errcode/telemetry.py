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
