"""Dataset capability is separate from model administration."""

from fastapi import Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.permission_identity import check_tenant_admin
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id


async def get_dataset_user(user: UserPayload = Depends(UserPayload.get_login_user)) -> UserPayload:
    # Administrators retain the implicit dataset capability used by navigation.
    tenant_id = get_current_tenant_id()
    if user.is_global_super or (
        tenant_id is not None and tenant_id != DEFAULT_TENANT_ID and await check_tenant_admin(user.user_id, tenant_id)
    ):
        return user
    await UserPayload.assert_effective_web_menu_contains(user.user_id, "dataset")
    return user
