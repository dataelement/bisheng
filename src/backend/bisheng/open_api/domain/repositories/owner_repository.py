"""Natural-person lookups used by service-account ownership validation."""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import UserTenant
from bisheng.user.domain.models.user import User


@dataclass(frozen=True, slots=True)
class NaturalPersonRecord:
    user_id: int
    user_name: str
    tenant_id: int


class OwnerRepository:
    @classmethod
    async def get_active_natural_person(cls, user_id: int) -> NaturalPersonRecord | None:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                user = (await session.exec(select(User).where(User.user_id == user_id, User.delete == 0))).first()
                membership = (
                    await session.exec(
                        select(UserTenant).where(
                            UserTenant.user_id == user_id,
                            UserTenant.status == "active",
                            UserTenant.is_active == 1,
                        )
                    )
                ).first()
        if user is None or membership is None:
            return None
        return NaturalPersonRecord(
            user_id=int(user.user_id),
            user_name=user.user_name,
            tenant_id=int(membership.tenant_id),
        )
