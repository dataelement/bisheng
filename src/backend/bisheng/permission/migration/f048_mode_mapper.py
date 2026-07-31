"""Pure canonical-parent and permission-mode mapper for F048."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from bisheng.permission.migration.f048_source_inventory import (
    FIXED_CUSTOM_TYPES,
    PARENT_REQUIRED_TYPES,
    PermissionMigrationResourceDTO,
)
from bisheng.permission.migration.f048_tuple_mapper import MappedGrant

VALID_PARENT_TYPES = frozenset({"knowledge_space", "knowledge_library", "folder"})


def _checksum(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MappedResourceMode:
    tenant_id: int
    resource_type: str
    resource_id: str
    mode: str
    parent_type: str | None
    parent_id: str | None
    ordinary_snapshot_assignee_keys: tuple[str, ...]
    checksum: str

    @property
    def resource_key(self) -> str:
        return f"{self.resource_type}:{self.resource_id}"

    @property
    def parent_key(self) -> str | None:
        if self.parent_type is None or self.parent_id is None:
            return None
        return f"{self.parent_type}:{self.parent_id}"


@dataclass(frozen=True, slots=True)
class ModeMappingDifference:
    resource_key: str
    difference_type: str
    message: str
    severity: str = "BLOCKER"


@dataclass(frozen=True, slots=True)
class ModeMappingResult:
    modes: tuple[MappedResourceMode, ...]
    differences: tuple[ModeMappingDifference, ...]
    blockers: tuple[str, ...]
    checksum: str


def _ordinary_assignee_keys(
    resource: PermissionMigrationResourceDTO,
    grants: tuple[MappedGrant, ...],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                assignee.assignee_key
                for grant in grants
                if grant.tenant_id == resource.tenant_id
                and grant.resource_type == resource.resource_type
                and grant.resource_id == resource.resource_id
                for assignee in grant.assignees
                if not assignee.protected and assignee.source_type not in {"CREATOR", "SYSTEM"}
            }
        )
    )


def _has_parent_cycle(
    start: str,
    resources: dict[str, PermissionMigrationResourceDTO],
) -> bool:
    seen: set[str] = set()
    current = start
    while current in resources:
        if current in seen:
            return True
        seen.add(current)
        resource = resources[current]
        if resource.parent_type is None or resource.parent_id is None:
            return False
        current = f"{resource.parent_type}:{resource.parent_id}"
    return False


def _mode(
    resource: PermissionMigrationResourceDTO,
    ordinary_keys: tuple[str, ...],
) -> MappedResourceMode:
    if resource.resource_type in FIXED_CUSTOM_TYPES:
        mode = "CUSTOM"
    elif resource.resource_type in PARENT_REQUIRED_TYPES:
        mode = "CUSTOM" if ordinary_keys else "INHERIT"
    else:
        raise ValueError("unsupported F048 resource type")
    payload = {
        "mode": mode,
        "ordinary_snapshot_assignee_keys": ordinary_keys,
        "parent_id": resource.parent_id,
        "parent_type": resource.parent_type,
        "resource_id": resource.resource_id,
        "resource_type": resource.resource_type,
        "tenant_id": resource.tenant_id,
    }
    return MappedResourceMode(
        tenant_id=resource.tenant_id,
        resource_type=resource.resource_type,
        resource_id=resource.resource_id,
        mode=mode,
        parent_type=resource.parent_type,
        parent_id=resource.parent_id,
        ordinary_snapshot_assignee_keys=ordinary_keys,
        checksum=_checksum(payload),
    )


def map_resource_modes(
    resources: tuple[PermissionMigrationResourceDTO, ...],
    grants: tuple[MappedGrant, ...],
) -> ModeMappingResult:
    """Map fixed CUSTOM and tree INHERIT/CUSTOM modes without new parent facts."""

    by_key = {resource.key: resource for resource in resources}
    differences: list[ModeMappingDifference] = []
    modes: list[MappedResourceMode] = []
    for resource in sorted(resources, key=lambda row: row.key):
        if resource.resource_type in PARENT_REQUIRED_TYPES:
            parent_key = (
                f"{resource.parent_type}:{resource.parent_id}" if resource.parent_type and resource.parent_id else None
            )
            if parent_key is None or resource.parent_type not in VALID_PARENT_TYPES or parent_key not in by_key:
                differences.append(
                    ModeMappingDifference(
                        resource_key=resource.key,
                        difference_type="MISSING_CANONICAL_PARENT",
                        message="tree resource parent does not exist in source facts",
                    )
                )
                continue
            parent = by_key[parent_key]
            if parent.tenant_id != resource.tenant_id:
                differences.append(
                    ModeMappingDifference(
                        resource_key=resource.key,
                        difference_type="CROSS_TENANT_PARENT",
                        message="tree resource and canonical parent have different tenants",
                    )
                )
                continue
            if _has_parent_cycle(resource.key, by_key):
                differences.append(
                    ModeMappingDifference(
                        resource_key=resource.key,
                        difference_type="CANONICAL_PARENT_CYCLE",
                        message="canonical parent chain contains a cycle",
                    )
                )
                continue
        try:
            modes.append(
                _mode(
                    resource,
                    _ordinary_assignee_keys(resource, grants),
                )
            )
        except ValueError as exc:
            differences.append(
                ModeMappingDifference(
                    resource_key=resource.key,
                    difference_type="UNSUPPORTED_RESOURCE_MODE",
                    message=str(exc),
                )
            )

    ordered_modes = tuple(sorted(modes, key=lambda row: row.resource_key))
    ordered_differences = tuple(
        sorted(
            differences,
            key=lambda row: (row.resource_key, row.difference_type),
        )
    )
    blockers = tuple(sorted({row.difference_type for row in ordered_differences}))
    payload = {
        "modes": [asdict(row) for row in ordered_modes],
        "differences": [asdict(row) for row in ordered_differences],
    }
    return ModeMappingResult(
        modes=ordered_modes,
        differences=ordered_differences,
        blockers=blockers,
        checksum=_checksum(payload),
    )
