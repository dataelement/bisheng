"""Read-only global account discovery; no credential or membership mutation."""

from dataclasses import dataclass

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.user.domain.models.user import User


@dataclass(frozen=True)
class AccountRow:
    user_id: int
    user_name: str
    deleted: int


class KunlianAccountRepository:
    def __init__(self, session_factory=get_async_db_session):
        self.session_factory = session_factory

    async def exact_accounts(self, user_account: str) -> list[AccountRow]:
        """Stop after two *Python-exact* matches, irrespective of DB collation.

        Stream SQL equality candidates: LIMIT 2 before exact comparison can hide
        a duplicate behind case/accent/space-equivalent names on MySQL or DM8.
        Disabled rows count toward ambiguity and cannot be silently skipped.
        """
        matches = []
        with bypass_tenant_filter():
            async with self.session_factory() as session:
                result = await session.stream(
                    select(User.user_id, User.user_name, User.delete)
                    .where(User.user_name == user_account)
                    .execution_options(yield_per=100)
                )
                try:
                    async for user_id, user_name, deleted in result:
                        if user_name == user_account:
                            matches.append(AccountRow(user_id, user_name, deleted))
                            if len(matches) == 2:
                                break
                finally:
                    await result.close()
        return matches

    async def current_memberships(self, user_id: int) -> list[int]:
        """Only current active memberships into active tenants; no default fallback."""
        with bypass_tenant_filter():
            async with self.session_factory() as session:
                rows = (
                    await session.exec(
                        select(UserTenant.tenant_id)
                        .join(Tenant, Tenant.id == UserTenant.tenant_id)
                        .where(
                            UserTenant.user_id == user_id,
                            UserTenant.is_active == 1,
                            UserTenant.status == "active",
                            Tenant.status == "active",
                        )
                        .limit(2)
                    )
                ).all()
        return list(rows)
