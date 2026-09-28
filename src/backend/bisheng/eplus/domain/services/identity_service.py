"""Resolve the raw E+ external user identifier to a usable BiSheng user."""

from __future__ import annotations

from dataclasses import dataclass

from bisheng.database.models.tenant import UserTenantDao
from bisheng.user.domain.models.user import UserDao

WECOM_SOURCE = "wecom"


@dataclass(frozen=True, slots=True)
class EPlusIdentity:
    user_id: int
    external_user_id: str


class EPlusIdentityService:
    async def resolve(self, *, tenant_id: int, external_user_id: str) -> EPlusIdentity | None:
        if not external_user_id:
            return None
        user = await UserDao.aget_by_source_external_id(WECOM_SOURCE, external_user_id)
        if user is None or int(user.delete or 0) != 0 or user.user_id is None:
            return None
        membership = await UserTenantDao.aget_active_user_tenant(int(user.user_id))
        if (
            membership is None
            or int(membership.tenant_id) != int(tenant_id)
            or getattr(membership, "status", "active") != "active"
        ):
            return None
        return EPlusIdentity(user_id=int(user.user_id), external_user_id=external_user_id)
