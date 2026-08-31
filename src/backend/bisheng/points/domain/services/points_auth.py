"""积分写操作的统一平台运营资格校验.

require_platform_admin = 超管或平台管理员.
is_platform_super_admin 仍只认超管, 专家问答违规删除不要走前者.
"""

from bisheng.common.errcode.points import PointsPermissionDeniedError
from bisheng.user.domain.services.platform_operator import can_platform_operate


def is_platform_super_admin(user) -> bool:
    """平台超管: RBAC AdminRole 或 JWT 已解析的 is_global_super.

    不得把「平台管理员」算进来.
    """
    if not user:
        return False
    if getattr(user, "is_global_super", False):
        return True
    check = getattr(user, "is_admin", None)
    return bool(check() if callable(check) else check)


def require_platform_admin(user) -> None:
    """不具备运营写资格(超管或平台管理员)时抛出积分模块错误码."""
    if not can_platform_operate(user):
        raise PointsPermissionDeniedError()
