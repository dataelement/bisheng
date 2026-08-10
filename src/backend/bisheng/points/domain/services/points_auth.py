"""积分写操作的统一平台超级管理员校验。"""

from bisheng.common.errcode.points import PointsPermissionDeniedError


def is_platform_super_admin(user) -> bool:
    """平台超管：RBAC AdminRole 或 JWT 已解析的 is_global_super。"""
    if not user:
        return False
    if getattr(user, "is_global_super", False):
        return True
    check = getattr(user, "is_admin", None)
    return bool(check() if callable(check) else check)


def require_platform_admin(user) -> None:
    """不具备平台管理员身份时抛出积分模块错误码。"""
    if not is_platform_super_admin(user):
        raise PointsPermissionDeniedError()
