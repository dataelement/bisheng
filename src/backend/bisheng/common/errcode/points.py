"""积分模块业务错误码。"""

from bisheng.common.errcode.base import BaseErrorCode


class PointsPermissionDeniedError(BaseErrorCode):
    """当前用户不是平台超级管理员。"""
    Code, Msg = 18201, "无积分管理权限"


class PointsInvalidAdjustError(BaseErrorCode):
    """调分参数不满足产品约束。"""
    Code, Msg = 18202, "积分调整参数不合法"


class PointsRuleConflictError(BaseErrorCode):
    """规则编码重复或受益人配置不匹配。"""
    Code, Msg = 18203, "积分规则配置冲突"


class PointsRuleNotFoundError(BaseErrorCode):
    """扣减时指定的启用规则不存在。"""
    Code, Msg = 18204, "积分规则不存在或未启用"


class PointsCompanyRootConflictError(BaseErrorCode):
    """租户已有其他公司根节点。"""
    Code, Msg = 18205, "公司根节点冲突"


class PointsIdempotentReplayError(BaseErrorCode):
    """调用方显式要求报告的重复记账。"""
    Code, Msg = 18206, "积分操作已处理"
