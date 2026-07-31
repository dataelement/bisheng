"""Normalize and validate source facts for the formal F048 migration run.

This module is deliberately pure. Business domains export canonical DTOs and
the scripts coordinator passes them here; permission code never queries a
business table to infer tenant, owner, status, or parent facts.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Protocol

MIGRATED_RESOURCE_TYPES = frozenset(
    {
        "knowledge_space",
        "knowledge_library",
        "folder",
        "knowledge_file",
        "workflow",
        "assistant",
        "tool",
        "channel",
        "dashboard",
    }
)
PARENT_REQUIRED_TYPES = frozenset({"folder", "knowledge_file"})
FIXED_CUSTOM_TYPES = MIGRATED_RESOURCE_TYPES - PARENT_REQUIRED_TYPES


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _checksum(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MigrationEnvironmentFacts:
    """D0/D1 facts captured before the formal data migration starts."""

    schema_ready: bool
    services_stopped: bool
    active_heartbeats: int
    expected_store_id: str
    actual_store_id: str
    source_model_id: str
    source_watermark: str
    observed_watermark: str


@dataclass(frozen=True, slots=True)
class MigrationInventoryEnvironment:
    store_id: str
    source_model_id: str
    source_watermark: str


@dataclass(frozen=True, slots=True)
class LegacyConfigSource:
    key: str
    row_version: str
    raw_value: str


@dataclass(frozen=True, slots=True)
class LegacyTupleSource:
    tenant_id: int | None
    user: str
    relation: str
    object: str
    condition: str | None = None

    @property
    def key(self) -> str:
        return "|".join((self.user, self.relation, self.object, self.condition or ""))


@dataclass(frozen=True, slots=True)
class LegacyFailedTupleSource:
    locator: str
    status: str
    tuple_key: str
    resolution: str | None = None
    action: str = "write"
    error_category: str | None = None
    canonical_state: bool | None = None


@dataclass(frozen=True, slots=True)
class PermissionMigrationResourceDTO:
    """Canonical business fact exported by the resource-owning domain."""

    tenant_id: int
    resource_type: str
    resource_id: str
    status: str
    owner_user_id: int | None
    ownership_kind: str
    source_locator: str
    parent_type: str | None = None
    parent_id: str | None = None
    creator_user_ids: tuple[int, ...] = ()
    system_allowlisted: bool = False
    permission_mode: str | None = None
    source_version: str = "1"
    migratable: bool = True
    skip_reason: str | None = None

    @property
    def key(self) -> str:
        return f"{self.resource_type}:{self.resource_id}"


@dataclass(frozen=True, slots=True)
class PermissionMigrationSourcePage:
    items: tuple[PermissionMigrationResourceDTO, ...]
    next_cursor: str | None


class PermissionMigrationSourcePort(Protocol):
    async def aexport(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> PermissionMigrationSourcePage: ...


@dataclass(frozen=True, slots=True)
class SourceInventorySnapshot:
    environment: MigrationEnvironmentFacts
    config_sources: tuple[LegacyConfigSource, ...] = ()
    resources: tuple[PermissionMigrationResourceDTO, ...] = ()
    tuples: tuple[LegacyTupleSource, ...] = ()
    failed_tuples: tuple[LegacyFailedTupleSource, ...] = ()


@dataclass(frozen=True, slots=True)
class MigrationSourceItem:
    source_kind: str
    source_locator: str
    tenant_id: int | None
    source_checksum: str
    status: str
    severity: str
    difference_type: str | None
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class SourceInventory:
    environment: MigrationInventoryEnvironment
    items: tuple[MigrationSourceItem, ...]
    blockers: tuple[str, ...]
    checksum: str

    @property
    def blocker_count(self) -> int:
        return sum(item.severity == "BLOCKER" for item in self.items)


def _source_item(
    *,
    source_kind: str,
    source_locator: str,
    tenant_id: int | None,
    payload: Mapping[str, Any],
    difference_type: str | None = None,
    severity: str = "INFO",
) -> MigrationSourceItem:
    normalized_payload = dict(payload)
    return MigrationSourceItem(
        source_kind=source_kind,
        source_locator=source_locator,
        tenant_id=tenant_id,
        source_checksum=_checksum(normalized_payload),
        status="BLOCKED" if severity == "BLOCKER" else "READY",
        severity=severity,
        difference_type=difference_type,
        payload=normalized_payload,
    )


def _environment_blockers(facts: MigrationEnvironmentFacts) -> tuple[str, ...]:
    blockers: list[str] = []
    if not facts.schema_ready:
        blockers.append("SCHEMA_NOT_READY")
    if not facts.services_stopped or facts.active_heartbeats:
        blockers.append("SERVICES_NOT_STOPPED")
    if not facts.expected_store_id or facts.expected_store_id != facts.actual_store_id:
        blockers.append("STORE_ID_MISMATCH")
    if not facts.source_watermark or facts.source_watermark != facts.observed_watermark:
        blockers.append("SOURCE_WATERMARK_CHANGED")
    return tuple(blockers)


def _config_items(
    sources: tuple[LegacyConfigSource, ...],
) -> list[MigrationSourceItem]:
    items: list[MigrationSourceItem] = []
    seen: set[str] = set()
    for source in sorted(sources, key=lambda row: row.key):
        locator = f"config:{source.key}:{source.row_version}"
        difference_type: str | None = None
        severity = "INFO"
        if source.key in seen:
            parsed: object = source.raw_value
            difference_type = "DUPLICATE_CONFIG_SOURCE"
            severity = "BLOCKER"
        else:
            seen.add(source.key)
            try:
                parsed = json.loads(source.raw_value)
                if not isinstance(parsed, list):
                    raise ValueError("legacy permission config must be a list")
            except (json.JSONDecodeError, TypeError, ValueError):
                parsed = source.raw_value
                difference_type = "CORRUPT_CONFIG_JSON"
                severity = "BLOCKER"
        items.append(
            _source_item(
                source_kind="CONFIG",
                source_locator=locator,
                tenant_id=None,
                payload={
                    "key": source.key,
                    "row_version": source.row_version,
                    "value": parsed,
                },
                difference_type=difference_type,
                severity=severity,
            )
        )
    return items


def _resource_difference(
    resource: PermissionMigrationResourceDTO,
) -> tuple[str | None, str]:
    if not resource.migratable:
        return resource.skip_reason or "BUSINESS_RESOURCE_NOT_MIGRATABLE", "INFO"
    if (
        resource.tenant_id <= 0
        or resource.resource_type not in MIGRATED_RESOURCE_TYPES
        or not resource.resource_id
        or not resource.source_locator
    ):
        return "INVALID_RESOURCE_FACT", "BLOCKER"
    ownership_kind = resource.ownership_kind.upper()
    if ownership_kind not in {"USER", "SYSTEM"}:
        return "INVALID_OWNERSHIP_KIND", "BLOCKER"
    if ownership_kind == "USER" and (resource.owner_user_id is None or resource.owner_user_id <= 0):
        return "INVALID_CANONICAL_OWNER", "BLOCKER"
    if ownership_kind == "SYSTEM" and not resource.system_allowlisted:
        return "SYSTEM_OWNER_NOT_ALLOWLISTED", "BLOCKER"
    if resource.resource_type in PARENT_REQUIRED_TYPES and (not resource.parent_type or not resource.parent_id):
        return "MISSING_CANONICAL_PARENT", "BLOCKER"
    if (resource.parent_type is None) != (resource.parent_id is None):
        return "INVALID_CANONICAL_PARENT", "BLOCKER"
    if resource.parent_type == resource.resource_type and resource.parent_id == resource.resource_id:
        return "CANONICAL_PARENT_CYCLE", "BLOCKER"
    if len(set(resource.creator_user_ids)) != len(resource.creator_user_ids):
        return "DUPLICATE_CREATOR_FACT", "BLOCKER"
    if len(resource.creator_user_ids) > 1:
        return "MULTIPLE_ACTIVE_CREATORS", "BLOCKER"
    return None, "INFO"


def _resource_items(
    resources: tuple[PermissionMigrationResourceDTO, ...],
) -> tuple[list[MigrationSourceItem], dict[str, PermissionMigrationResourceDTO]]:
    items: list[MigrationSourceItem] = []
    by_key: dict[str, PermissionMigrationResourceDTO] = {}
    seen_keys: set[str] = set()
    locators: set[str] = set()
    for resource in sorted(resources, key=lambda row: row.source_locator):
        difference_type, severity = _resource_difference(resource)
        if resource.key in seen_keys or resource.source_locator in locators:
            difference_type = "DUPLICATE_RESOURCE_SOURCE"
            severity = "BLOCKER"
        if resource.migratable:
            by_key.setdefault(resource.key, resource)
        seen_keys.add(resource.key)
        locators.add(resource.source_locator)
        items.append(
            _source_item(
                source_kind="RESOURCE",
                source_locator=resource.source_locator,
                tenant_id=resource.tenant_id,
                payload=asdict(resource),
                difference_type=difference_type,
                severity=severity,
            )
        )
    return items, by_key


def _tuple_items(
    tuples: tuple[LegacyTupleSource, ...],
    resources: Mapping[str, PermissionMigrationResourceDTO],
) -> list[MigrationSourceItem]:
    items: list[MigrationSourceItem] = []
    seen: set[str] = set()
    for source in sorted(tuples, key=lambda row: row.key):
        difference_type: str | None = None
        severity = "INFO"
        object_type, separator, _ = source.object.partition(":")
        resource = resources.get(source.object)
        if source.key in seen:
            difference_type = "DUPLICATE_TUPLE"
        elif separator and object_type in MIGRATED_RESOURCE_TYPES and resource is None:
            # The Store can retain tuples after their canonical business
            # resource has been deleted. They grant no live resource and are
            # retired during the forward migration instead of inventing one.
            difference_type = "STALE_RESOURCE_TUPLE"
        elif resource is not None and source.tenant_id is not None and source.tenant_id != resource.tenant_id:
            difference_type = "CROSS_TENANT_TUPLE"
            severity = "BLOCKER"
        seen.add(source.key)
        items.append(
            _source_item(
                source_kind="TUPLE",
                source_locator=f"tuple:{source.key}",
                tenant_id=source.tenant_id,
                payload=asdict(source),
                difference_type=difference_type,
                severity=severity,
            )
        )
    return items


def _failed_tuple_items(
    rows: tuple[LegacyFailedTupleSource, ...],
) -> list[MigrationSourceItem]:
    items: list[MigrationSourceItem] = []
    unresolved = {"pending", "dead", "failed", "retrying"}
    for source in sorted(rows, key=lambda row: row.locator):
        is_unresolved = source.status.casefold() in unresolved and not (source.resolution and source.resolution.strip())
        items.append(
            _source_item(
                source_kind="FAILED_TUPLE",
                source_locator=source.locator,
                tenant_id=None,
                payload=asdict(source),
                difference_type=("UNRESOLVED_FAILED_TUPLE" if is_unresolved else None),
                severity="BLOCKER" if is_unresolved else "INFO",
            )
        )
    return items


def build_source_inventory(snapshot: SourceInventorySnapshot) -> SourceInventory:
    """Build the source inventory inside a real, frozen migration run."""

    environment = MigrationInventoryEnvironment(
        store_id=snapshot.environment.actual_store_id,
        source_model_id=snapshot.environment.source_model_id,
        source_watermark=snapshot.environment.source_watermark,
    )
    blockers = _environment_blockers(snapshot.environment)
    if blockers:
        payload = {"environment": asdict(environment), "blockers": blockers}
        return SourceInventory(
            environment=environment,
            items=(),
            blockers=blockers,
            checksum=_checksum(payload),
        )

    resource_items, resources = _resource_items(snapshot.resources)
    items = [
        *_config_items(snapshot.config_sources),
        *resource_items,
        *_tuple_items(snapshot.tuples, resources),
        *_failed_tuple_items(snapshot.failed_tuples),
    ]
    ordered = tuple(sorted(items, key=lambda row: (row.source_kind, row.source_locator)))
    inventory_blockers = tuple(
        sorted({item.difference_type for item in ordered if item.severity == "BLOCKER" and item.difference_type})
    )
    payload = {
        "environment": asdict(environment),
        "items": [
            {
                "kind": item.source_kind,
                "locator": item.source_locator,
                "checksum": item.source_checksum,
                "status": item.status,
                "severity": item.severity,
                "difference_type": item.difference_type,
            }
            for item in ordered
        ],
    }
    return SourceInventory(
        environment=environment,
        items=ordered,
        blockers=inventory_blockers,
        checksum=_checksum(payload),
    )
