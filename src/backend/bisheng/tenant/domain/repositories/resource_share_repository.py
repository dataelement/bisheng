"""Exact-ID repository boundary for cross-tenant shared resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bisheng.core.context.tenant import bypass_tenant_filter

MAX_SHARED_RESOURCE_IDS = 100


@dataclass(frozen=True, slots=True)
class SharedResourceRecord:
    owner_tenant_id: int
    resource_type: str
    resource_id: str
    status: str
    shareable: bool
    permission_version: int
    context_version: str


class SharedResourceLoaderPort(Protocol):
    async def load_by_ids(
        self,
        resource_type: str,
        resource_ids: tuple[str, ...],
    ) -> tuple[SharedResourceRecord, ...]: ...


class SharedResourceRepository:
    """Confine tenant-filter bypass to an already-authorized exact ID set."""

    def __init__(self, loader: SharedResourceLoaderPort) -> None:
        self._loader = loader

    async def get_authorized_by_ids(
        self,
        *,
        owner_tenant_id: int,
        resource_type: str,
        resource_ids: tuple[str, ...],
    ) -> tuple[SharedResourceRecord, ...]:
        normalized_ids = tuple(
            dict.fromkeys(resource_id.strip() for resource_id in resource_ids if resource_id.strip())
        )
        if owner_tenant_id <= 0:
            raise ValueError("owner_tenant_id must be positive")
        if not resource_type.strip():
            raise ValueError("resource_type must not be empty")
        if not normalized_ids:
            return ()
        if len(normalized_ids) > MAX_SHARED_RESOURCE_IDS:
            raise ValueError("too many shared resource IDs")

        with bypass_tenant_filter():
            rows = await self._loader.load_by_ids(
                resource_type,
                normalized_ids,
            )

        authorized_ids = set(normalized_ids)
        return tuple(
            row
            for row in rows
            if row.resource_type == resource_type
            and row.resource_id in authorized_ids
            and row.owner_tenant_id == owner_tenant_id
        )
