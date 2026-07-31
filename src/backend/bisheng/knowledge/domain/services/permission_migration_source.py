"""Knowledge-domain source port for the formal F048 data migration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import (
    Knowledge,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.permission.migration.f048_source_inventory import (
    PermissionMigrationResourceDTO,
    PermissionMigrationSourcePage,
)

KNOWLEDGE_RESOURCE_TYPES = frozenset(
    {
        "knowledge_space",
        "knowledge_library",
        "folder",
        "knowledge_file",
    }
)


@dataclass(frozen=True, slots=True)
class KnowledgeMigrationRow:
    tenant_id: int
    resource_type: str
    resource_id: str
    status: str
    owner_user_id: int | None
    parent_type: str | None = None
    parent_id: str | None = None
    creator_user_ids: tuple[int, ...] = ()
    source_version: str = "1"
    migratable: bool = True
    skip_reason: str | None = None


class KnowledgeMigrationRepositoryPort(Protocol):
    async def aexport_permission_rows(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[KnowledgeMigrationRow, ...], str | None]: ...


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
_MIGRATED_KNOWLEDGE_TYPES = (
    KnowledgeTypeEnum.NORMAL.value,
    KnowledgeTypeEnum.QA.value,
    KnowledgeTypeEnum.SPACE.value,
)


def _enum_status(enum_type, value: object) -> str:
    try:
        return str(enum_type(value).name)
    except ValueError:
        return f"UNKNOWN:{value}"


def _version(value: object) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else "0"


def _build_file_migration_row(
    file_row: KnowledgeFile,
    *,
    knowledge_type: int,
    knowledge_tenant_id: int | None,
    existing_parent_ids: set[str],
) -> KnowledgeMigrationRow:
    ancestors = [part for part in (file_row.file_level_path or "").split("/") if part]
    parent_type = (
        "folder"
        if ancestors
        else ("knowledge_space" if knowledge_type == KnowledgeTypeEnum.SPACE.value else "knowledge_library")
    )
    parent_id = ancestors[-1] if ancestors else str(file_row.knowledge_id)
    status = _enum_status(KnowledgeFileStatus, file_row.status)
    stale_failed_resource = bool(ancestors) and parent_id not in existing_parent_ids and status == "FAILED"
    return KnowledgeMigrationRow(
        tenant_id=int(knowledge_tenant_id or file_row.tenant_id or 0),
        resource_type=("folder" if file_row.file_type == FileType.DIR.value else "knowledge_file"),
        resource_id=str(file_row.id),
        status=status,
        owner_user_id=file_row.user_id,
        parent_type=parent_type,
        parent_id=parent_id,
        source_version=_version(file_row.update_time),
        migratable=not stale_failed_resource,
        skip_reason=("STALE_FAILED_RESOURCE" if stale_failed_resource else None),
    )


class SqlKnowledgeMigrationRepository:
    """Cross-tenant, read-only exporter owned by the knowledge domain."""

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
    ) -> tuple[tuple[KnowledgeMigrationRow, ...], str | None]:
        phase, after_id = self._parse_cursor(cursor)
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                if phase == "knowledge":
                    rows, next_cursor = await self._knowledge_rows(
                        session,
                        after_id=after_id,
                        limit=limit,
                    )
                    if next_cursor is not None or len(rows) == limit:
                        return tuple(rows), next_cursor
                    file_rows, file_cursor = await self._file_rows(
                        session,
                        after_id=0,
                        limit=limit - len(rows),
                    )
                    return (*rows, *file_rows), file_cursor
                rows, next_cursor = await self._file_rows(
                    session,
                    after_id=after_id,
                    limit=limit,
                )
                return tuple(rows), next_cursor

    @staticmethod
    def _parse_cursor(cursor: str | None) -> tuple[str, int]:
        if cursor is None:
            return "knowledge", 0
        phase, separator, raw_id = cursor.partition(":")
        if not separator or phase not in {"knowledge", "file"} or not raw_id.isdigit():
            raise ValueError("invalid knowledge migration cursor")
        return phase, int(raw_id)

    async def _knowledge_rows(
        self,
        session: AsyncSession,
        *,
        after_id: int,
        limit: int,
    ) -> tuple[list[KnowledgeMigrationRow], str | None]:
        if limit <= 0:
            return [], "file:0"
        statement = (
            select(Knowledge)
            .where(
                col(Knowledge.id) > after_id,
                col(Knowledge.type).in_(_MIGRATED_KNOWLEDGE_TYPES),
            )
            .order_by(Knowledge.id)
            .limit(limit + 1)
        )
        raw_rows = list((await session.execute(statement)).scalars().all())
        selected = raw_rows[:limit]
        space_ids = [str(row.id) for row in selected if row.type == KnowledgeTypeEnum.SPACE.value]
        creators: dict[str, list[int]] = {}
        if space_ids:
            member_statement = select(SpaceChannelMember).where(
                col(SpaceChannelMember.business_id).in_(space_ids),
                SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
                SpaceChannelMember.user_role == UserRoleEnum.CREATOR,
            )
            members = list((await session.execute(member_statement)).scalars().all())
            for member in members:
                creators.setdefault(str(member.business_id), []).append(int(member.user_id))
        rows = [
            KnowledgeMigrationRow(
                tenant_id=int(row.tenant_id or 0),
                resource_type=("knowledge_space" if row.type == KnowledgeTypeEnum.SPACE.value else "knowledge_library"),
                resource_id=str(row.id),
                status=_enum_status(KnowledgeState, row.state),
                owner_user_id=row.user_id,
                creator_user_ids=tuple(sorted(creators.get(str(row.id), ()))),
                source_version=_version(row.update_time),
            )
            for row in selected
        ]
        if len(raw_rows) > limit:
            return rows, f"knowledge:{selected[-1].id}"
        return rows, "file:0"

    async def _file_rows(
        self,
        session: AsyncSession,
        *,
        after_id: int,
        limit: int,
    ) -> tuple[list[KnowledgeMigrationRow], str | None]:
        if limit <= 0:
            return [], "file:0"
        statement = (
            select(KnowledgeFile, Knowledge.type, Knowledge.tenant_id)
            .join(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
            .where(
                col(KnowledgeFile.id) > after_id,
                col(Knowledge.type).in_(_MIGRATED_KNOWLEDGE_TYPES),
            )
            .order_by(KnowledgeFile.id)
            .limit(limit + 1)
        )
        raw_rows = list((await session.execute(statement)).all())
        selected = raw_rows[:limit]
        immediate_parent_ids = {
            ancestors[-1]
            for file_row, _, _ in selected
            if (ancestors := [part for part in (file_row.file_level_path or "").split("/") if part])
        }
        numeric_parent_ids = [int(parent_id) for parent_id in immediate_parent_ids if parent_id.isdigit()]
        existing_parent_ids = (
            {
                str(parent_id)
                for parent_id in (
                    await session.execute(
                        select(KnowledgeFile.id).where(
                            col(KnowledgeFile.id).in_(numeric_parent_ids),
                            KnowledgeFile.file_type == FileType.DIR.value,
                        )
                    )
                ).scalars()
            }
            if numeric_parent_ids
            else set()
        )
        rows = [
            _build_file_migration_row(
                file_row,
                knowledge_type=knowledge_type,
                knowledge_tenant_id=knowledge_tenant_id,
                existing_parent_ids=existing_parent_ids,
            )
            for file_row, knowledge_type, knowledge_tenant_id in selected
        ]
        next_cursor = f"file:{selected[-1][0].id}" if len(raw_rows) > limit and selected else None
        return rows, next_cursor


class KnowledgePermissionMigrationSource:
    """Export canonical container/tree facts through a bounded cursor."""

    def __init__(self, repository: KnowledgeMigrationRepositoryPort) -> None:
        self._repository = repository

    async def aexport(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> PermissionMigrationSourcePage:
        if not 1 <= limit <= 500:
            raise ValueError("knowledge migration page size must be 1..500")
        rows, next_cursor = await self._repository.aexport_permission_rows(
            cursor=cursor,
            limit=limit,
        )
        items: list[PermissionMigrationResourceDTO] = []
        for row in rows:
            if row.resource_type not in KNOWLEDGE_RESOURCE_TYPES:
                raise ValueError(f"unsupported knowledge resource: {row.resource_type}")
            items.append(
                PermissionMigrationResourceDTO(
                    tenant_id=row.tenant_id,
                    resource_type=row.resource_type,
                    resource_id=row.resource_id,
                    status=row.status,
                    owner_user_id=row.owner_user_id,
                    ownership_kind="USER",
                    source_locator=(f"knowledge:{row.resource_type}:{row.resource_id}"),
                    parent_type=row.parent_type,
                    parent_id=row.parent_id,
                    creator_user_ids=row.creator_user_ids,
                    source_version=row.source_version,
                    migratable=row.migratable,
                    skip_reason=row.skip_reason,
                )
            )
        return PermissionMigrationSourcePage(
            items=tuple(items),
            next_cursor=next_cursor,
        )
