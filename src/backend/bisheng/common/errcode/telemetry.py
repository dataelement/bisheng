from bisheng.common.errcode import BaseErrorCode


class DashboardMaxError(BaseErrorCode):
    Code: int = 17000
    Msg: str = '最多允许创建 20 个看板'


class DashBoardShareAuthError(BaseErrorCode):
    Code: int = 17005
    Msg: str = '没有看板分享权限'


class QueryDatasetNotFoundError(BaseErrorCode):
    Code: int = 17010
    Msg: str = '未找到对应的数据集配置'


class QueryVirtualMaxError(BaseErrorCode):
    Code: int = 17011
    Msg: str = '虚拟指标只能单独查询一个'


class QueryMetricNotFoundError(BaseErrorCode):
    Code = 17012
    Msg = '未找到对应的指标配置'


class QueryAggregationNotFoundError(BaseErrorCode):
    Code = 17013
    Msg = '未找到对应的汇总方式'


class QueryDimensionNotFoundError(BaseErrorCode):
    Code = 17014
    Msg = '未找到对应的维度配置'


class QueryOperatorNotFoundError(BaseErrorCode):
    Code = 17015
    Msg = '未找到对应的操作符配置'
