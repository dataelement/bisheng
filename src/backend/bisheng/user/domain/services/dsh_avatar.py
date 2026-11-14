"""Current user-owned avatar display for the Desktop profile read path."""

from bisheng.common.errcode.dsh import DshUserDisabledError
from bisheng.user.domain.repositories.runtime_identity import current_runtime_person


async def read_dsh_avatar(tenant_id: str, user_id: str) -> str | None:
    """Sign only after revalidating the exact active person and tenant."""
    row = await current_runtime_person(int(user_id))
    if row is None:
        raise DshUserDisabledError()
    user, current_tenant_id = row
    if str(user.user_id) != user_id or str(current_tenant_id) != tenant_id:
        raise DshUserDisabledError()
    # The shared access runtime imports this adapter even for login/logout. Load
    # the full web user service only after the avatar read's identity checks pass.
    from bisheng.user.domain.services.user import UserService

    return await UserService.get_avatar_share_link(user.avatar or None)
