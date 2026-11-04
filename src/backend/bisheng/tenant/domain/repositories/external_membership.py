"""显式外部成员关联。只创建首个关联。不迁移既有账号。"""

from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import select

from bisheng.common.errcode.sso_sync import (
    KunlianBindingConflictError,
    KunlianDependencyUnavailableError,
    KunlianIdentityUnavailableError,
)
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.user.domain.models.user import User


class ExternalMembershipRepository:
    def __init__(self, session_factory=get_async_db_session):
        self.session_factory = session_factory

    async def validate_external_mapping_target(self, local_tenant_id: int) -> int:
        if type(local_tenant_id) is not int or local_tenant_id <= 0 or get_current_tenant_id() != local_tenant_id:
            raise KunlianIdentityUnavailableError()
        with strict_tenant_filter():
            async with self.session_factory() as session:
                tenant = await session.get(Tenant, local_tenant_id)
                if (
                    tenant is None
                    or tenant.status != "active"
                    or (tenant.parent_tenant_id != (None if local_tenant_id == 1 else 1))
                ):
                    raise KunlianIdentityUnavailableError()
                return tenant.id

    async def find_external_user_ids(self, user_ids: list[int]) -> frozenset[int]:
        if not user_ids:
            return frozenset()
        if len(user_ids) > 500:
            raise KunlianBindingConflictError()
        async with self.session_factory() as session:
            rows = (
                await session.exec(select(User.user_id).where(User.user_id.in_(user_ids), User.source == "kunlian"))
            ).all()
            return frozenset(rows)

    async def read_current_tenant(self, user_id: int, mapping) -> Tenant:
        if get_current_tenant_id() != mapping.local_tenant_id:
            raise KunlianBindingConflictError()
        with strict_tenant_filter():
            async with self.session_factory() as session:
                tenant = await session.get(Tenant, mapping.local_tenant_id)
                membership = (
                    await session.exec(
                        select(UserTenant).where(UserTenant.user_id == user_id, UserTenant.is_active == 1)
                    )
                ).first()
                if (
                    tenant is None
                    or tenant.status != "active"
                    or membership is None
                    or membership.tenant_id != mapping.local_tenant_id
                    or membership.status != "active"
                ):
                    raise KunlianIdentityUnavailableError()
                return tenant

    @asynccontextmanager
    async def membership_scope(self, user_id: int, mapping):
        if type(user_id) is not int or user_id <= 0 or get_current_tenant_id() != mapping.local_tenant_id:
            raise KunlianBindingConflictError()
        with strict_tenant_filter():
            async with self.session_factory() as session:
                try:
                    async with session.begin():
                        tenant = (
                            await session.exec(
                                select(Tenant).where(Tenant.id == mapping.local_tenant_id).with_for_update()
                            )
                        ).first()
                        if tenant is None or tenant.status != "active":
                            raise KunlianIdentityUnavailableError()
                        user = (
                            await session.exec(select(User).where(User.user_id == user_id).with_for_update())
                        ).first()
                        if (
                            user is None
                            or user.source != "kunlian"
                            or not (user.external_id or "").startswith("kunlian:")
                        ):
                            raise KunlianBindingConflictError()
                        # 同一用户的所有关联用于拒绝迁移。不能只看到目标租户内的行。
                        with bypass_tenant_filter():
                            rows = (
                                await session.exec(
                                    select(UserTenant).where(UserTenant.user_id == user_id).with_for_update()
                                )
                            ).all()
                        if any(row.tenant_id != mapping.local_tenant_id for row in rows) or len(rows) > 1:
                            raise KunlianBindingConflictError()
                        if rows:
                            row = rows[0]
                            if row.status != "active" or row.is_active != 1:
                                raise KunlianIdentityUnavailableError()
                        else:
                            row = UserTenant(
                                user_id=user_id,
                                tenant_id=mapping.local_tenant_id,
                                status="active",
                                is_active=1,
                                is_default=1,
                            )
                            session.add(row)
                            await session.flush()
                        # 交给 application 完成持久权限投影。失败则成员 SQL 不提交。
                        yield
                except IntegrityError:
                    raise KunlianBindingConflictError() from None
                except SQLAlchemyError:
                    raise KunlianDependencyUnavailableError() from None
