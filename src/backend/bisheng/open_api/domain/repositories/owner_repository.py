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
    async def get_user_name(cls, user_id: int | None) -> str | None:
        if user_id is None:
            return None
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                user = (await session.exec(select(User).where(User.user_id == user_id))).first()
        return user.user_name if user else None

    @classmethod
    async def get_active_natural_person(cls, user_id: int) -> NaturalPersonRecord | None:
        return (await cls.get_active_natural_people((user_id,))).get(user_id)

    @classmethod
    async def get_active_natural_people(cls, user_ids: tuple[int, ...]) -> dict[int, NaturalPersonRecord]:
        people = {}
        # Read the actual current tenant even when it differs from the caller's.
        # Callers compare it with the service account's tenant before accepting it.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                # Keep IN clauses bounded for both MySQL and DM8.
                for offset in range(0, len(user_ids), 500):
                    rows = await session.exec(
                        select(User, UserTenant.tenant_id)
                        .join(UserTenant, UserTenant.user_id == User.user_id)
                        .where(
                            User.user_id.in_(user_ids[offset : offset + 500]),
                            User.delete == 0,
                            UserTenant.status == "active",
                            UserTenant.is_active == 1,
                        )
                    )
                    for user, tenant_id in rows.all():
                        people[int(user.user_id)] = NaturalPersonRecord(
                            user_id=int(user.user_id), user_name=user.user_name, tenant_id=int(tenant_id)
                        )
        return people
