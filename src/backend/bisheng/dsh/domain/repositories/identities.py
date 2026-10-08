"""Read existing natural-person user and active tenant records without caching."""

from sqlalchemy.exc import SQLAlchemyError

from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError
from bisheng.dsh.domain.schemas.identity import IdentityRecord


class CurrentIdentityRecords:
    async def get(self, tenant_id: str, user_id: str) -> IdentityRecord | None:
        from bisheng.database.models.tenant import TenantDao, UserTenantDao
        from bisheng.user.domain.models.user import UserDao

        try:
            user = await UserDao.aget_user(int(user_id))
            if user is None:
                return None
            membership = await UserTenantDao.aget_active_user_tenant(int(user_id))
            if membership is None or str(membership.tenant_id) != tenant_id:
                return None
            tenant = await TenantDao.aget_by_id(int(tenant_id))
            return IdentityRecord(
                tenant_id=tenant_id,
                user_id=str(user.user_id),
                username=user.user_name or "",
                display_name=getattr(user, "display_name", None),
                tenant_name=tenant.tenant_name if tenant else None,
                profile_version=user.dsh_profile_version,
                active=user.delete == 0,
                tenant_active=bool(tenant and tenant.status == "active" and membership.status == "active"),
                # Service accounts live in their own credential domain, never in this user lookup.
                natural_person=True,
            )
        except SQLAlchemyError:
            raise DshAuthorizationUnavailableError() from None
