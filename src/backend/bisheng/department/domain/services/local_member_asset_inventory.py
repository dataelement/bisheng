"""Inventory transferable and Linsight assets owned by a user."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import ROOT_TENANT_ID, UserTenantDao
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScope,
)
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.linsight.domain.models.linsight_sop import LinsightSOP, LinsightSOPRecord
from bisheng.tenant.domain.services.resource_ownership_service import ResourceOwnershipService, ResourceRow
from bisheng.tenant.domain.services.resource_type_registry import SUPPORTED_TYPES


@dataclass
class AssetBatch:
    tenant_id: int
    resource_type: str
    resource_ids: list[int | str]


@dataclass
class LocalMemberAssetInventory:
    tenant_ids: list[int] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    transfer_batches: list[AssetBatch] = field(default_factory=list)
    linsight_counts: dict[str, int] = field(default_factory=dict)
    personal_knowledge_space_ids: list[int] = field(default_factory=list)

    @property
    def transfer_count(self) -> int:
        return sum(len(batch.resource_ids) for batch in self.transfer_batches)

    @property
    def linsight_delete_count(self) -> int:
        return sum(self.linsight_counts.values())

    @property
    def personal_knowledge_space_count(self) -> int:
        return len(self.personal_knowledge_space_ids)

    @property
    def has_transferable_assets(self) -> bool:
        return self.transfer_count > 0


async def _resolve_user_tenant_ids(user_id: int, fallback_tenant_id: int | None) -> list[int]:
    active = await UserTenantDao.aget_active_user_tenant(user_id)
    if active is not None and active.tenant_id is not None:
        return [int(active.tenant_id)]

    rows = await UserTenantDao.aget_user_tenants(user_id)
    tenant_ids = sorted({int(row.tenant_id) for row in rows if row.tenant_id is not None})
    if tenant_ids:
        return tenant_ids
    if fallback_tenant_id is not None and int(fallback_tenant_id) > 0:
        return [int(fallback_tenant_id)]
    return [ROOT_TENANT_ID]


async def _find_personal_knowledge_space_ids(user_id: int) -> set[int]:
    """System/personal spaces are recycled on delete, not transferred."""
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            owned_space_ids = (
                await session.exec(
                    select(Knowledge.id).where(
                        Knowledge.user_id == user_id,
                        Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                    )
                )
            ).all()
            normalized_ids = sorted(
                {
                    _extract_scalar_int(row)
                    for row in owned_space_ids
                    if row is not None
                }
            )
            if not normalized_ids:
                return set()

            favorite_ids = {
                _extract_scalar_int(row)
                for row in (
                    await session.exec(
                        select(Knowledge.id).where(
                            Knowledge.user_id == user_id,
                            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                            Knowledge.is_favorite == True,  # noqa: E712
                        )
                    )
                ).all()
                if row is not None
            }
            scoped_personal_ids = {
                _extract_scalar_int(row)
                for row in (
                    await session.exec(
                        select(KnowledgeSpaceScope.space_id).where(
                            KnowledgeSpaceScope.space_id.in_(normalized_ids),
                            KnowledgeSpaceScope.level == KnowledgeSpaceLevelEnum.PERSONAL.value,
                        )
                    )
                ).all()
                if row is not None
            }
    return favorite_ids | scoped_personal_ids


async def _filter_resources_in_personal_spaces(
    resources: list[ResourceRow],
    personal_space_ids: set[int],
) -> list[ResourceRow]:
    if not resources or not personal_space_ids:
        return resources

    file_ids = [int(resource.id) for resource in resources]
    files = await KnowledgeFileDao.aget_file_by_ids(file_ids)
    allowed_ids = {
        int(file.id)
        for file in files
        if int(file.knowledge_id) not in personal_space_ids
    }
    return [resource for resource in resources if int(resource.id) in allowed_ids]


async def _count_linsight_assets(user_id: int) -> dict[str, int]:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            session_version_count = int(
                await session.scalar(
                    select(func.count()).select_from(LinsightSessionVersion).where(
                        LinsightSessionVersion.user_id == user_id,
                    ),
                )
                or 0
            )
            sop_count = int(
                await session.scalar(
                    select(func.count()).select_from(LinsightSOP).where(
                        LinsightSOP.user_id == user_id,
                    ),
                )
                or 0
            )
            sop_record_count = int(
                await session.scalar(
                    select(func.count()).select_from(LinsightSOPRecord).where(
                        LinsightSOPRecord.user_id == user_id,
                    ),
                )
                or 0
            )
    return {
        "linsight_session_version": session_version_count,
        "linsight_sop": sop_count,
        "linsight_sop_record": sop_record_count,
    }


def _chunks(values: list[int | str], size: int) -> list[list[int | str]]:
    return [values[start : start + size] for start in range(0, len(values), size)]


def _extract_scalar_int(row: object) -> int:
    """Normalize SQLModel/SQLAlchemy scalar row (int, Row, tuple) to int."""
    if isinstance(row, int):
        return row
    try:
        return int(row)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return int(row[0])  # type: ignore[index]


async def build_local_member_asset_inventory(
    *,
    user_id: int,
    fallback_tenant_id: int | None,
    batch_size: int,
) -> LocalMemberAssetInventory:
    tenant_ids = await _resolve_user_tenant_ids(user_id, fallback_tenant_id)
    personal_space_ids = await _find_personal_knowledge_space_ids(user_id)
    counts: dict[str, int] = defaultdict(int)
    transfer_batches: list[AssetBatch] = []

    for tenant_id in tenant_ids:
        for resource_type in SUPPORTED_TYPES:
            resources = await ResourceOwnershipService._resolve_resources(
                tenant_id=tenant_id,
                from_user_id=user_id,
                resource_types=[resource_type],
                resource_ids=None,
            )
            if not resources:
                continue

            if resource_type == "knowledge_space":
                resources = [
                    resource
                    for resource in resources
                    if int(resource.id) not in personal_space_ids
                ]
            elif resource_type in {"folder", "knowledge_file"}:
                resources = await _filter_resources_in_personal_spaces(
                    resources,
                    personal_space_ids,
                )

            if not resources:
                continue

            counts[resource_type] += len(resources)
            resource_ids = [resource.id for resource in resources]
            for chunk in _chunks(resource_ids, batch_size):
                transfer_batches.append(
                    AssetBatch(
                        tenant_id=tenant_id,
                        resource_type=resource_type,
                        resource_ids=chunk,
                    ),
                )

    if personal_space_ids:
        counts["personal_knowledge_space"] = len(personal_space_ids)

    linsight_counts = await _count_linsight_assets(user_id)
    for key, value in linsight_counts.items():
        counts[key] = value

    return LocalMemberAssetInventory(
        tenant_ids=tenant_ids,
        counts=dict(counts),
        transfer_batches=transfer_batches,
        linsight_counts=linsight_counts,
        personal_knowledge_space_ids=sorted(personal_space_ids),
    )
