"""Channel-domain source port for the formal F048 data migration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel import Channel, ChannelVisibilityEnum
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.permission.migration.f048_source_inventory import (
    PermissionMigrationResourceDTO,
    PermissionMigrationSourcePage,
)


@dataclass(frozen=True, slots=True)
class ChannelMigrationRow:
    tenant_id: int
    resource_id: str
    status: str
    owner_user_id: int | None
    creator_user_ids: tuple[int, ...] = ()
    migrate_ordinary_grants: bool = True
    source_version: str = "1"


class ChannelMigrationRepositoryPort(Protocol):
    async def aexport_permission_rows(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[ChannelMigrationRow, ...], str | None]: ...


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class SqlChannelMigrationRepository:
    """Cross-tenant, read-only channel exporter with CREATOR evidence."""

    def __init__(
        self,
        session_factory: SessionFactory = get_async_db_session,
    ) -> None:
        self._session_factory = session_factory

    async def aexport_permission_rows(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[ChannelMigrationRow, ...], str | None]:
        after_id = cursor or ""
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                statement = select(Channel).where(col(Channel.id) > after_id).order_by(Channel.id).limit(limit + 1)
                raw_rows = list((await session.execute(statement)).scalars().all())
                selected = raw_rows[:limit]
                channel_ids = [str(row.id) for row in selected]
                creators: dict[str, list[int]] = {}
                if channel_ids:
                    member_statement = select(SpaceChannelMember).where(
                        col(SpaceChannelMember.business_id).in_(channel_ids),
                        SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
                        SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
                        SpaceChannelMember.user_role == UserRoleEnum.CREATOR,
                    )
                    members = list((await session.execute(member_statement)).scalars().all())
                    for member in members:
                        creators.setdefault(
                            str(member.business_id),
                            [],
                        ).append(int(member.user_id))
        rows = tuple(
            ChannelMigrationRow(
                tenant_id=int(row.tenant_id or 0),
                resource_id=str(row.id),
                status="ACTIVE",
                owner_user_id=row.user_id,
                creator_user_ids=tuple(sorted(creators.get(str(row.id), ()))),
                migrate_ordinary_grants=row.visibility != ChannelVisibilityEnum.PRIVATE,
                source_version=(row.update_time.isoformat() if row.update_time is not None else "0"),
            )
            for row in selected
        )
        next_cursor = str(selected[-1].id) if len(raw_rows) > limit and selected else None
        return rows, next_cursor


class ChannelPermissionMigrationSource:
    """Keep membership CREATOR and Channel.user_id as separate facts."""

    def __init__(self, repository: ChannelMigrationRepositoryPort) -> None:
        self._repository = repository

    async def aexport(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> PermissionMigrationSourcePage:
        if not 1 <= limit <= 500:
            raise ValueError("channel migration page size must be 1..500")
        rows, next_cursor = await self._repository.aexport_permission_rows(
            cursor=cursor,
            limit=limit,
        )
        return PermissionMigrationSourcePage(
            items=tuple(
                PermissionMigrationResourceDTO(
                    tenant_id=row.tenant_id,
                    resource_type="channel",
                    resource_id=row.resource_id,
                    status=row.status,
                    owner_user_id=row.owner_user_id,
                    ownership_kind="USER",
                    source_locator=f"channel:{row.resource_id}",
                    creator_user_ids=row.creator_user_ids,
                    migrate_ordinary_grants=row.migrate_ordinary_grants,
                    source_version=row.source_version,
                )
                for row in rows
            ),
            next_cursor=next_cursor,
        )
