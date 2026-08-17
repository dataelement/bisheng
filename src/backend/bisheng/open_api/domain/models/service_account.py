"""``service_account`` — companion attributes of a service-account principal (F049 D1).

The principal itself is a ``user`` row (``user_type='service'``,
``source='service_account'``, ``external_id=NULL``, password sentinel) so that
F048 authorization, sessions and audit keep working on ``user_id``. This table
holds what only a service account has: tenant, resource owner, description,
creator and the two lifecycle timestamps.

``disabled_at`` / ``deleted_at`` are the **only state source** (design D1):
``user.delete`` is merely a same-transaction write-through projection that the
service maintains so people-facing ``delete == 0`` filters hide the account.
Readers (validator, list "status" column, detail) look at these two columns
only.

The DAO never opens a session (D1 "single-transaction create") and never issues
bulk UPDATE / DELETE or ``text()`` (K6).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, text
from sqlmodel import Field, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT
from bisheng.database.base import async_get_count
from bisheng.database.models.tenant import UserTenant

# ``user.source`` value for service-account rows. ``external_id`` stays NULL so
# the three login-candidate lookups structurally never match (design D1 / K5).
SERVICE_ACCOUNT_USER_SOURCE = "service_account"


class ServiceAccount(SQLModelSerializable, table=True):
    __tablename__ = "service_account"

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("user.user_id", ondelete="RESTRICT"),
            primary_key=True,
            comment="Principal user row (user.user_type='service')",
        ),
    )
    # ``default=None`` on purpose (guard test_tenant_id_default_guard): the
    # before_flush hook auto-fills from the current tenant context; a Python
    # default would silently write child-tenant rows to Root.
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, index=True, comment="Tenant ID"),
    )
    resource_owner_user_id: int = Field(
        sa_column=Column(
            Integer,
            nullable=False,
            index=True,
            comment="Natural person who owns resources this account creates (AC-23..27)",
        ),
    )
    description: str | None = Field(default=None, sa_column=Column(String(512), nullable=True))
    created_by: int | None = Field(default=None, sa_column=Column(Integer, nullable=True, comment="Creator user id"))
    disabled_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    deleted_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )

    @property
    def is_enabled(self) -> bool:
        """Enabled ⇔ both lifecycle timestamps are NULL (the only state source)."""
        return self.disabled_at is None and self.deleted_at is None


class ServiceAccountDao:
    """Single-row ORM access; every method takes the caller's ``AsyncSession``."""

    @classmethod
    async def acreate_with_user(
        cls,
        session: AsyncSession,
        *,
        user,
        tenant_id: int,
        resource_owner_user_id: int,
        description: str | None,
        created_by: int | None,
    ) -> ServiceAccount:
        """D1 create unit: ``add(user)`` → flush for ``user_id`` → ``add(service_account)`` → ``add(user_tenant)``.

        ``user`` is a fully prepared ``bisheng.user.domain.models.user.User``
        instance (``user_type='service'``, ``source='service_account'``,
        ``external_id=None``, sentinel password) built by the service; the DAO
        stays free of user-domain imports. The caller commits — a failure
        anywhere leaves nothing behind (no orphan user row without companion /
        tenant rows).
        """
        session.add(user)
        await session.flush()
        account = ServiceAccount(
            user_id=user.user_id,
            tenant_id=tenant_id,
            resource_owner_user_id=resource_owner_user_id,
            description=description,
            created_by=created_by,
        )
        session.add(account)
        # Active leaf tenant row — ``is_active=1`` is what F048 subject checks
        # and the credential validator require (design pit 8).
        session.add(UserTenant(user_id=user.user_id, tenant_id=tenant_id, status="active", is_active=1))
        await session.flush()
        return account

    @classmethod
    async def aget(cls, session: AsyncSession, user_id: int, *, include_deleted: bool = False) -> ServiceAccount | None:
        statement = select(ServiceAccount).where(ServiceAccount.user_id == user_id)
        if not include_deleted:
            statement = statement.where(col(ServiceAccount.deleted_at).is_(None))
        result = await session.exec(statement)
        return result.first()

    @classmethod
    async def alist_page(
        cls,
        session: AsyncSession,
        *,
        page: int = 1,
        page_size: int = 20,
        user_ids: list[int] | None = None,
        include_deleted: bool = False,
    ) -> tuple[list[ServiceAccount], int]:
        """Page of companion rows (tenant scoping via the auto filter), newest first.

        ``user_ids`` narrows to a candidate set (e.g. name search resolved on the
        user table by the service). Name / status hydration is the service's job.
        """
        statement = select(ServiceAccount)
        if not include_deleted:
            statement = statement.where(col(ServiceAccount.deleted_at).is_(None))
        if user_ids is not None:
            if not user_ids:
                return [], 0
            statement = statement.where(col(ServiceAccount.user_id).in_(user_ids))
        total = await async_get_count(session, statement)
        statement = statement.order_by(col(ServiceAccount.create_time).desc(), col(ServiceAccount.user_id).desc())
        statement = statement.offset(max(page - 1, 0) * page_size).limit(page_size)
        result = await session.exec(statement)
        return list(result.all()), total

    @classmethod
    async def aupdate_row(cls, session: AsyncSession, row: ServiceAccount) -> ServiceAccount:
        row.update_time = datetime.now()
        session.add(row)
        await session.flush()
        return row

    @classmethod
    async def aset_timestamps(
        cls,
        session: AsyncSession,
        row: ServiceAccount,
        *,
        disabled_at: datetime | None | object = ...,
        deleted_at: datetime | None | object = ...,
    ) -> ServiceAccount:
        """Set lifecycle timestamps on one row (``...`` = leave unchanged). Caller projects ``user.delete``."""
        if disabled_at is not ...:
            row.disabled_at = disabled_at
        if deleted_at is not ...:
            row.deleted_at = deleted_at
        return await cls.aupdate_row(session, row)
