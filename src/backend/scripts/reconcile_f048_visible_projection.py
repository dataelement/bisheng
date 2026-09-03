#!/usr/bin/env python3
"""Audit or repair the F048 flattened visible projection.

The command is safe for production use when run in a maintenance window.  It
uses PermissionGrant/PermissionGrantAssignee as the canonical authorization
source, rebuilds permission_visible_source_projection, idempotently ensures
all expected direct ``visible`` tuples, verifies them at higher consistency,
and can perform the immutable Authorization Model + Catalog forward cutover required after an
older F048 migration. An explicit orphan audit compares Store tuples with all
ACTIVE SQL visible-source contributions. Orphan cleanup is separately gated by
``--cleanup-orphan-tuples`` and the checksum printed by a prior dry-run.

Run from ``src/backend`` with the live ``config`` value::

    PYTHONPATH=./ .venv/bin/python scripts/reconcile_f048_visible_projection.py
    PYTHONPATH=./ .venv/bin/python scripts/reconcile_f048_visible_projection.py --audit-orphan-tuples
    PYTHONPATH=./ .venv/bin/python scripts/reconcile_f048_visible_projection.py --apply --confirm-store-id <store-id> --operator-id <user-id> --allow-model-upgrade
    PYTHONPATH=./ .venv/bin/python scripts/reconcile_f048_visible_projection.py --audit-orphan-tuples --orphan-object folder:97394
    PYTHONPATH=./ .venv/bin/python scripts/reconcile_f048_visible_projection.py --apply --audit-orphan-tuples --orphan-object folder:97394 --cleanup-orphan-tuples --confirm-orphan-checksum <checksum> --confirm-store-id <store-id> --operator-id <user-id>

Dry-run is the default.  Apply refuses active runtime heartbeats or in-flight
permission projection operations. Orphan cleanup deletes only exact direct
``visible`` tuple keys that have no ACTIVE SQL source contribution, and records
each resource-scoped deletion in the durable projection ledger.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import func, update  # noqa: E402
from sqlmodel import col, select  # noqa: E402

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import (  # noqa: E402
    close_app_context,
    initialize_app_context,
)
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.core.openfga.authorization_model_f048 import (  # noqa: E402
    MODEL_VERSION,
    authorization_model_checksum,
    get_authorization_model_f048,
)
from bisheng.core.openfga.client import (  # noqa: E402
    BUSINESS_BATCH_CHECK_LIMIT,
    FGAClient,
)
from bisheng.core.openfga.discovery import discover_openfga_runtime  # noqa: E402
from bisheng.core.openfga.runtime_heartbeat import (  # noqa: E402
    list_runtime_heartbeats,
)
from bisheng.permission.application.catalog_api import (  # noqa: E402
    OpenFGACatalogProjector,
    SqlCatalogImpact,
    SqlCatalogState,
)
from bisheng.permission.application.control_state import (  # noqa: E402
    SqlPermissionControlState,
)
from bisheng.permission.application.sql_runtime import (  # noqa: E402
    RedisConsistencyMarker,
    build_sql_projection_runtime,
)
from bisheng.permission.domain.models import (  # noqa: E402
    AuthorizationModelRelease,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionProjectionOperation,
    PermissionVisibleSourceProjection,
    ProjectionOperationStatus,
    ResourcePermissionMode,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget  # noqa: E402
from bisheng.permission.domain.services.catalog_service import (  # noqa: E402
    CatalogDraftBuildInput,
    CatalogService,
)
from bisheng.permission.domain.services.grant_source_service import (  # noqa: E402
    SOURCE_TYPES,
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceRecord,
)
from bisheng.permission.domain.services.model_policy import (  # noqa: E402
    CustomModelSelection,
)
from bisheng.permission.domain.services.projection_plan import (  # noqa: E402
    MAX_CHANGE_ITEMS,
    ProjectionPlan,
    ProjectionTupleDelta,
)
from bisheng.permission.domain.services.projection_service import (  # noqa: E402
    ProjectionService,
)
from bisheng.permission.domain.services.visibility_projection_service import (  # noqa: E402
    VisibilityProjectionCompiler,
)
from bisheng.permission.migration.f048_runtime_storage import (  # noqa: E402
    OpenFGAMigrationModelPublisher,
)

EXIT_OK = 0
EXIT_BLOCKED = 3
EXIT_RUNTIME_ERROR = 4
HIGHER_CONSISTENCY = "HIGHER_CONSISTENCY"
ACTIVE_OPERATION_STATUSES = ("PREPARED", "STAGING", "COMMIT_UNKNOWN", "COMMITTED")


class VisibleReconcileBlockedError(RuntimeError):
    """A safety or canonical-source invariant blocked reconciliation."""


@dataclass(frozen=True, slots=True)
class CurrentRelease:
    catalog_id: int
    catalog_key: str
    store_id: str
    model_id: str
    model_release_id: int
    model_checksum: str
    write_fenced: bool


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    mode: str
    store_id: str
    source_model_id: str
    target_model_id: str | None
    target_model_checksum: str
    catalog_write_fenced: bool
    grant_count: int
    assignee_count: int
    canonical_source_count: int
    persisted_active_source_count: int
    source_upsert_count: int
    source_retire_count: int
    expected_tuple_count: int
    source_checksum: str
    expected_tuple_checksum: str


@dataclass(frozen=True, slots=True)
class OrphanTupleAudit:
    object_filters: tuple[str, ...]
    live_direct_visible_count: int
    supported_tuple_count: int
    missing_tuple_count: int
    orphan_tuple_count: int
    missing_tuple_checksum: str
    orphan_tuple_checksum: str
    missing_tuples: tuple[tuple[str, str, str], ...]
    orphan_tuples: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True, slots=True)
class OrphanCleanupSelection:
    object_filters: tuple[str, ...]
    tuple_count: int
    tuple_checksum: str
    tuples: tuple[tuple[str, str, str], ...]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Repair SQL source projections, ensure expected tuples, and update the model/Catalog pin",
    )
    parser.add_argument(
        "--confirm-store-id",
        default=None,
        help="Required with --apply; must equal the discovered immutable Store ID",
    )
    parser.add_argument(
        "--operator-id",
        type=int,
        default=0,
        help="Audit operator ID recorded on the no-op Catalog release",
    )
    parser.add_argument(
        "--allow-model-upgrade",
        action="store_true",
        help="Explicitly allow publishing and switching from an older F048 model",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=80,
        help="OpenFGA write batch size, 1..90 (default: 80)",
    )
    parser.add_argument(
        "--audit-orphan-tuples",
        action="store_true",
        help="Scan direct visible Store tuples and report unsupported or missing tuple keys",
    )
    parser.add_argument(
        "--cleanup-orphan-tuples",
        action="store_true",
        help="With --apply, delete audited orphan tuple keys through resource-scoped projection operations",
    )
    parser.add_argument(
        "--orphan-object",
        action="append",
        default=[],
        help="Limit the reported cleanup selection to an exact resource key; repeatable",
    )
    parser.add_argument(
        "--confirm-orphan-checksum",
        default=None,
        help="Required for orphan cleanup; must match the dry-run orphan_tuple_checksum",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 90:
        parser.error("--batch-size must be between 1 and 90")
    if args.operator_id < 0:
        parser.error("--operator-id must not be negative")
    if args.apply and not args.confirm_store_id:
        parser.error("--apply requires --confirm-store-id")
    if args.apply and args.operator_id <= 0:
        parser.error("--apply requires a positive --operator-id")
    if args.cleanup_orphan_tuples and not args.apply:
        parser.error("--cleanup-orphan-tuples requires --apply")
    if args.cleanup_orphan_tuples and not args.audit_orphan_tuples:
        parser.error("--cleanup-orphan-tuples requires --audit-orphan-tuples")
    if args.cleanup_orphan_tuples and not args.confirm_orphan_checksum:
        parser.error("--cleanup-orphan-tuples requires --confirm-orphan-checksum")
    if args.confirm_orphan_checksum and not args.cleanup_orphan_tuples:
        parser.error("--confirm-orphan-checksum requires --cleanup-orphan-tuples")
    if args.orphan_object and not args.audit_orphan_tuples:
        parser.error("--orphan-object requires --audit-orphan-tuples")
    return args


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VisibleReconcileBlockedError(message)


def _checksum(rows: Any) -> str:
    payload = json.dumps(rows, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode()).hexdigest()


def _environment_name(value: str | dict[str, Any]) -> str:
    if isinstance(value, dict):
        value = next(
            (value[key] for key in ("name", "environment", "env", "mode") if value.get(key)),
            "dev",
        )
    return str(value or "dev")[:64]


def _offline_settings(live_settings: Any) -> Any:
    openfga = getattr(live_settings, "openfga", None)
    copy_settings = getattr(live_settings, "model_copy", None)
    copy_openfga = getattr(openfga, "model_copy", None)
    if not callable(copy_settings) or not callable(copy_openfga):
        return live_settings
    return copy_settings(update={"openfga": copy_openfga(update={"enabled": False})})


async def _load_current_release() -> CurrentRelease:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            rows = list(
                (
                    await session.exec(
                        select(PermissionCatalogRelease, AuthorizationModelRelease)
                        .join(
                            AuthorizationModelRelease,
                            AuthorizationModelRelease.id
                            == PermissionCatalogRelease.required_authorization_model_release_id,
                        )
                        .where(PermissionCatalogRelease.status == "CURRENT")
                    )
                ).all()
            )
    _require(len(rows) == 1, "Permission Catalog must have exactly one CURRENT release")
    catalog, model = rows[0]
    _require(model.status == "ACTIVE", "CURRENT Authorization Model release is not ACTIVE")
    _require(catalog.id is not None and model.id is not None, "CURRENT release identity is incomplete")
    return CurrentRelease(
        catalog_id=int(catalog.id),
        catalog_key=catalog.release_key,
        store_id=model.store_id,
        model_id=model.model_id,
        model_release_id=int(model.id),
        model_checksum=model.model_checksum,
        write_fenced=bool(catalog.write_fenced),
    )


async def _assert_maintenance_window(*, apply: bool) -> None:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            active_operations = int(
                (
                    await session.exec(
                        select(func.count(PermissionProjectionOperation.id)).where(
                            PermissionProjectionOperation.status.in_(ACTIVE_OPERATION_STATUSES)
                        )
                    )
                ).one()
            )
    _require(active_operations == 0, f"{active_operations} permission projection operations are active")
    if apply:
        heartbeats = await list_runtime_heartbeats()
        _require(not heartbeats, f"{len(heartbeats)} F048 runtime heartbeats are still active")


async def _load_canonical_grants() -> tuple[tuple[GrantSnapshot, ...], int]:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            grant_rows = list(
                (
                    await session.exec(
                        select(PermissionGrant)
                        .where(PermissionGrant.state == "ACTIVE")
                        .order_by(PermissionGrant.tenant_id, PermissionGrant.id)
                    )
                ).all()
            )
            grant_ids = [int(row.id) for row in grant_rows if row.id is not None]
            assignee_rows = (
                list(
                    (
                        await session.exec(
                            select(PermissionGrantAssignee)
                            .where(
                                col(PermissionGrantAssignee.grant_id).in_(grant_ids),
                                PermissionGrantAssignee.state == "ACTIVE",
                            )
                            .order_by(PermissionGrantAssignee.tenant_id, PermissionGrantAssignee.id)
                        )
                    ).all()
                )
                if grant_ids
                else []
            )
    blockers = [
        f"grant:{row.id}:projection_state={row.projection_state}"
        for row in grant_rows
        if row.projection_state != "CURRENT"
    ]
    unknown_sources = sorted({row.source_type for row in assignee_rows} - set(SOURCE_TYPES))
    if unknown_sources:
        blockers.append(f"unknown assignee source types: {unknown_sources}")
    grant_by_id = {int(row.id): row for row in grant_rows if row.id is not None}
    assignees_by_grant: dict[int, list[PermissionGrantAssignee]] = defaultdict(list)
    for row in assignee_rows:
        grant = grant_by_id.get(int(row.grant_id))
        if grant is None or int(row.tenant_id or 0) != int(grant.tenant_id or 0):
            blockers.append(f"assignee:{row.id}:grant_or_tenant_mismatch")
            continue
        assignees_by_grant[int(row.grant_id)].append(row)
    _require(not blockers, "; ".join(blockers[:20]))

    snapshots: list[GrantSnapshot] = []
    for row in grant_rows:
        tenant_id = int(row.tenant_id or 0)
        _require(tenant_id > 0 and row.id is not None, f"grant {row.id} has invalid identity")
        sources = tuple(
            GrantSourceRecord(
                source_id=int(source.id or 0),
                subject_type=source.subject_type,
                subject_id=source.subject_id,
                userset_relation=source.userset_relation,
                include_children=bool(source.include_children),
                source_type=source.source_type,
                source_ref=source.source_ref,
                source_locator=source.source_locator,
                source_fingerprint=source.source_fingerprint,
                projected_subject=source.projected_subject,
                protected=bool(source.protected),
                active=True,
                version=int(source.version),
            )
            for source in assignees_by_grant.get(int(row.id), ())
        )
        snapshots.append(
            GrantSnapshot(
                grant_id=str(row.id),
                tenant_id=tenant_id,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                model=GrantModelSnapshot(
                    model_key=row.model_key,
                    active=True,
                    action_codes=(),
                ),
                active=bool(sources),
                sources=sources,
                version=int(row.version),
            )
        )
    return tuple(snapshots), len(assignee_rows)


async def _load_persisted_sources() -> tuple[PermissionVisibleSourceProjection, ...]:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            return tuple(
                (
                    await session.exec(
                        select(PermissionVisibleSourceProjection).order_by(
                            PermissionVisibleSourceProjection.tenant_id,
                            PermissionVisibleSourceProjection.id,
                        )
                    )
                ).all()
            )


def _compile_sources(grants: tuple[GrantSnapshot, ...]):
    compiler = VisibilityProjectionCompiler()
    grouped: dict[int, list[GrantSnapshot]] = defaultdict(list)
    for grant in grants:
        grouped[grant.tenant_id].append(grant)
    return tuple(
        source
        for tenant_id in sorted(grouped)
        for source in compiler.compile(
            tenant_id=tenant_id,
            grants=tuple(grouped[tenant_id]),
            existing_sources=(),
        ).active_sources
    )


def _source_key(source: Any) -> str:
    return str(source.contribution_fingerprint)


def _tuple_key(source: Any) -> tuple[str, str, str]:
    return (
        str(source.projected_subject),
        "visible",
        f"{source.resource_type}:{source.resource_id}",
    )


def _build_report(
    *,
    mode: str,
    current: CurrentRelease,
    target_model_id: str | None,
    target_checksum: str,
    grants: tuple[GrantSnapshot, ...],
    assignee_count: int,
    canonical_sources: tuple[Any, ...],
    persisted: tuple[PermissionVisibleSourceProjection, ...],
) -> tuple[ReconcileReport, tuple[Any, ...], tuple[PermissionVisibleSourceProjection, ...], frozenset]:
    desired = {_source_key(row): row for row in canonical_sources}
    persisted_active = {_source_key(row): row for row in persisted if row.state == "ACTIVE"}
    upserts = tuple(
        row
        for key, row in sorted(desired.items())
        if key not in persisted_active
        or persisted_active[key].source_version != row.source_version
        or persisted_active[key].tuple_fingerprint != row.tuple_fingerprint
    )
    retires = tuple(row for key, row in sorted(persisted_active.items()) if key not in desired)
    expected = frozenset(_tuple_key(row) for row in canonical_sources)
    report = ReconcileReport(
        mode=mode,
        store_id=current.store_id,
        source_model_id=current.model_id,
        target_model_id=target_model_id,
        target_model_checksum=target_checksum,
        catalog_write_fenced=current.write_fenced,
        grant_count=len(grants),
        assignee_count=assignee_count,
        canonical_source_count=len(canonical_sources),
        persisted_active_source_count=len(persisted_active),
        source_upsert_count=len(upserts),
        source_retire_count=len(retires),
        expected_tuple_count=len(expected),
        source_checksum=_checksum([row.model_dump(mode="json") for row in sorted(canonical_sources, key=_source_key)]),
        expected_tuple_checksum=_checksum(sorted(expected)),
    )
    return report, upserts, retires, expected


async def _audit_orphan_tuples(
    client: FGAClient,
    *,
    canonical_sources: tuple[Any, ...],
    persisted: tuple[PermissionVisibleSourceProjection, ...],
    object_filters: tuple[str, ...] = (),
) -> OrphanTupleAudit:
    normalized_filters = tuple(sorted(dict.fromkeys(object_filters)))
    invalid = [value for value in normalized_filters if not all(value.partition(":"))]
    _require(not invalid, f"invalid --orphan-object resource keys: {invalid}")
    if normalized_filters:
        rows = [
            row
            for object_key in normalized_filters
            for row in await client.read_tuples(
                relation="visible",
                object=object_key,
                consistency=HIGHER_CONSISTENCY,
            )
        ]
    else:
        rows = await client.read_tuples(consistency=HIGHER_CONSISTENCY)
    live = frozenset(
        (str(row["user"]), "visible", str(row["object"]))
        for row in rows
        if row.get("relation") == "visible" and row.get("user") and row.get("object")
    )
    canonical = frozenset(_tuple_key(row) for row in canonical_sources)
    persisted_active = frozenset(_tuple_key(row) for row in persisted if row.state == "ACTIVE")
    supported = canonical | persisted_active
    if normalized_filters:
        supported = frozenset(row for row in supported if row[2] in normalized_filters)
    missing = tuple(sorted(supported - live))
    orphans = tuple(sorted(live - supported))
    return OrphanTupleAudit(
        object_filters=normalized_filters,
        live_direct_visible_count=len(live),
        supported_tuple_count=len(supported),
        missing_tuple_count=len(missing),
        orphan_tuple_count=len(orphans),
        missing_tuple_checksum=_checksum(missing),
        orphan_tuple_checksum=_checksum(orphans),
        missing_tuples=missing,
        orphan_tuples=orphans,
    )


def _select_orphan_tuples(
    audit: OrphanTupleAudit,
    *,
    object_filters: tuple[str, ...],
) -> OrphanCleanupSelection:
    normalized_filters = tuple(sorted(dict.fromkeys(object_filters)))
    selected = tuple(row for row in audit.orphan_tuples if not normalized_filters or row[2] in normalized_filters)
    return OrphanCleanupSelection(
        object_filters=normalized_filters,
        tuple_count=len(selected),
        tuple_checksum=_checksum(selected),
        tuples=selected,
    )


async def _load_cleanup_scope(object_key: str) -> ResourcePermissionMode:
    resource_type, separator, resource_id = object_key.partition(":")
    _require(
        bool(separator and resource_type and resource_id),
        f"orphan visible tuple has an invalid resource key: {object_key}",
    )
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            rows = list(
                (
                    await session.exec(
                        select(ResourcePermissionMode).where(
                            ResourcePermissionMode.resource_type == resource_type,
                            ResourcePermissionMode.resource_id == resource_id,
                        )
                    )
                ).all()
            )
    _require(
        len(rows) == 1,
        f"orphan visible tuple resource must map to exactly one SQL scope: {object_key}",
    )
    row = rows[0]
    _require(
        row.projection_state == "CURRENT",
        f"orphan visible tuple resource is not CURRENT: {object_key}",
    )
    _require(
        row.tenant_id is not None and int(row.tenant_id) > 0,
        f"orphan visible tuple resource has no tenant: {object_key}",
    )
    return row


def _build_orphan_cleanup_plan(
    *,
    current: CurrentRelease,
    scope: ResourcePermissionMode,
    tuples: tuple[tuple[str, str, str], ...],
    operator_id: int,
) -> ProjectionPlan:
    _require(bool(tuples), "orphan cleanup plan must contain tuple keys")
    _require(
        len(tuples) <= MAX_CHANGE_ITEMS,
        f"one resource has {len(tuples)} orphan tuples; maximum classified cleanup size is {MAX_CHANGE_ITEMS}",
    )
    object_keys = {row[2] for row in tuples}
    scope_key = f"{scope.resource_type}:{scope.resource_id}"
    _require(
        object_keys == {scope_key},
        "orphan cleanup plan cannot mix resource scopes",
    )
    version = int(scope.version)
    digest = _checksum(tuples)
    return ProjectionPlan(
        tenant_id=int(scope.tenant_id or 0),
        idempotency_key=f"f048:visible-orphan:{digest[:40]}:{version}",
        operation_type="VISIBLE_ORPHAN_CLEANUP",
        scope_type="resource",
        scope_key=scope_key,
        expected_version=version,
        target_version=version + 1,
        store_id=current.store_id,
        model_id=current.model_id,
        operator_id=operator_id,
        change_item_count=len(tuples),
        deltas=tuple(
            ProjectionTupleDelta(
                phase="COMMIT",
                sequence=index,
                action="DELETE",
                user=user,
                relation=relation,
                object=object_key,
            )
            for index, (user, relation, object_key) in enumerate(tuples)
        ),
    )


async def _cleanup_orphan_tuples(
    client: FGAClient,
    *,
    current: CurrentRelease,
    selection: OrphanCleanupSelection,
    operator_id: int,
) -> tuple[int, ...]:
    if not selection.tuples:
        return ()
    grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for tuple_key in selection.tuples:
        grouped[tuple_key[2]].append(tuple_key)

    sql_projection = await build_sql_projection_runtime(client)
    projection = ProjectionService(
        repository=sql_projection.repository,
        marker=sql_projection.marker,
        scope_guard=sql_projection.scope_guard,
        fga=sql_projection.fga,
        finalizer=sql_projection.finalizer,
    )
    state = SqlPermissionControlState()
    operation_ids: list[int] = []
    for object_key, tuple_keys in sorted(grouped.items()):
        scope = await _load_cleanup_scope(object_key)
        exact_tuples = tuple(sorted(tuple_keys))
        plan = _build_orphan_cleanup_plan(
            current=current,
            scope=scope,
            tuples=exact_tuples,
            operator_id=operator_id,
        )
        target = VerifiedPermissionTarget.from_business_service(
            tenant_id=plan.tenant_id,
            resource_type=scope.resource_type,
            resource_id=scope.resource_id,
            resource_version=plan.expected_version,
            parent_type=scope.parent_type,
            parent_id=scope.parent_id,
            context_version=f"visible-orphan-{selection.tuple_checksum[:40]}",
        )
        with bypass_tenant_filter():
            operation = await projection.prepare(plan)
            if str(operation.status) == ProjectionOperationStatus.PREPARED.value:
                try:
                    await state.mark_projecting(
                        target=target,
                        operation_id=int(operation.id),
                        expected_catalog_release_id=current.catalog_id,
                    )
                except Exception as exc:
                    await projection.abandon_prepared(plan, exc)
                    raise
            outcome = await projection.execute(plan)
        _require(
            outcome.status == ProjectionOperationStatus.FINALIZED.value,
            f"orphan cleanup did not finalize for {object_key}",
        )
        operation_ids.append(outcome.operation_id)
    return tuple(operation_ids)


async def _apply_source_rows(upserts: tuple[Any, ...]) -> None:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            async with session.begin():
                for source in upserts:
                    existing = (
                        await session.exec(
                            select(PermissionVisibleSourceProjection)
                            .where(
                                PermissionVisibleSourceProjection.tenant_id == source.tenant_id,
                                PermissionVisibleSourceProjection.contribution_fingerprint
                                == source.contribution_fingerprint,
                            )
                            .with_for_update()
                        )
                    ).first()
                    if existing is None:
                        session.add(
                            PermissionVisibleSourceProjection(
                                **source.model_dump(exclude={"operation_id", "migration_item_id"}),
                            )
                        )
                        continue
                    immutable = (
                        "resource_type",
                        "resource_id",
                        "visibility_class",
                        "projected_subject",
                        "source_kind",
                        "source_owner_key",
                        "source_locator",
                        "source_fingerprint",
                        "model_key",
                    )
                    _require(
                        all(getattr(existing, field) == getattr(source, field) for field in immutable),
                        f"visible source fingerprint collision: {source.contribution_fingerprint}",
                    )
                    existing.source_version = source.source_version
                    existing.tuple_fingerprint = source.tuple_fingerprint
                    existing.state = "ACTIVE"


async def _ensure_expected_tuples(
    client: FGAClient,
    expected: frozenset[tuple[str, str, str]],
    *,
    batch_size: int,
) -> None:
    rows = sorted(expected)
    for offset in range(0, len(rows), batch_size):
        batch = rows[offset : offset + batch_size]
        client.validate_business_mutation_size(len(batch))
        await client.write_tuples(
            writes=[{"user": user, "relation": relation, "object": object_key} for user, relation, object_key in batch],
            ignore_duplicate_writes=True,
        )


async def _verify_expected_tuples(
    client: FGAClient,
    expected: frozenset[tuple[str, str, str]],
) -> None:
    rows = sorted(expected)
    for offset in range(0, len(rows), BUSINESS_BATCH_CHECK_LIMIT):
        batch = rows[offset : offset + BUSINESS_BATCH_CHECK_LIMIT]
        allowed = await client.batch_check(
            [{"user": user, "relation": relation, "object": object_key} for user, relation, object_key in batch],
            consistency=HIGHER_CONSISTENCY,
        )
        _require(
            len(allowed) == len(batch) and all(allowed),
            "higher-consistency visible tuple verification failed",
        )


async def _authorization_release_id(store_id: str, model_id: str) -> int:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            row = (
                await session.exec(
                    select(AuthorizationModelRelease).where(
                        AuthorizationModelRelease.store_id == store_id,
                        AuthorizationModelRelease.model_id == model_id,
                    )
                )
            ).first()
    _require(row is not None and row.id is not None, "target Authorization Model release is missing")
    return int(row.id)


async def _is_resumable_upgrade_draft(
    *,
    current_catalog_id: int,
    target_checksum: str,
) -> bool:
    idempotency_key = f"f048-visible-{target_checksum[:32]}"
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            count = int(
                (
                    await session.exec(
                        select(func.count(PermissionCatalogRelease.id)).where(
                            PermissionCatalogRelease.predecessor_id == current_catalog_id,
                            PermissionCatalogRelease.idempotency_key == idempotency_key,
                            PermissionCatalogRelease.status.in_(("DRAFT", "PROJECTING", "COMMITTED")),
                        )
                    )
                ).one()
            )
    return count == 1


async def _activate_model_release(release_id: int) -> None:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            async with session.begin():
                await session.execute(
                    update(AuthorizationModelRelease)
                    .where(AuthorizationModelRelease.id == release_id)
                    .values(status="ACTIVE", activated_at=func.now(), retired_at=None)
                )


async def _publish_noop_catalog_cutover(
    *,
    current: CurrentRelease,
    target_client: FGAClient,
    target_release_id: int,
    operator_id: int,
    target_checksum: str,
) -> int:
    state = SqlCatalogState()
    before = await state.load_snapshot(current.catalog_id)
    _require(
        before.action_release is not None and before.model_release is not None,
        "CURRENT Catalog snapshot is incomplete",
    )
    idempotency_key = f"f048-visible-{target_checksum[:32]}"
    reservation = await state.reserve_draft(
        base_release_id=current.catalog_id,
        operator_id=operator_id,
        idempotency_key=idempotency_key,
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=30),
    )
    impact = SqlCatalogImpact()
    marker = RedisConsistencyMarker()
    await marker.initialize()
    service = CatalogService(
        state=state,
        impact=impact,
        projector=OpenFGACatalogProjector(client=target_client, marker=marker),
    )
    if not reservation.complete:
        customs = tuple(
            CustomModelSelection(
                model_key=model.model_key,
                name=model.name,
                action_codes=model.selected_action_codes,
                active=model.active,
                allow_same_level=model.allow_same_level,
                config_scope=model.config_scope,
            )
            for model in before.model_release.models
            if model.kind == "CUSTOM"
        )
        standard_policy = {
            model.model_key: model.allow_same_level for model in before.model_release.models if model.kind == "STANDARD"
        }
        await service.build_draft(
            CatalogDraftBuildInput(
                release_id=reservation.release_id,
                release_key=reservation.release_key,
                predecessor_release_id=reservation.predecessor_id,
                predecessor_release_key=reservation.predecessor_key,
                before_actions=before.action_release,
                before_models=before.model_release,
                actions=before.action_release.actions,
                custom_models=customs,
                standard_allow_same_level=standard_policy,
                grant_references=await state.grant_references(),
                draft_owner_id=operator_id,
                idempotency_key=idempotency_key,
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=30),
            )
        )
    await state.bind_draft_authorization_release(
        draft_id=reservation.release_id,
        authorization_release_id=target_release_id,
    )
    outcome = await service.publish(
        draft_id=reservation.release_id,
        expected_current_release_id=current.catalog_id,
        idempotency_key=idempotency_key,
    )
    _require(outcome.status == "CURRENT", "Authorization Model Catalog cutover did not finalize")
    return outcome.release_id


async def _retire_other_active_models(current: CurrentRelease) -> None:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            async with session.begin():
                await session.execute(
                    update(AuthorizationModelRelease)
                    .where(
                        AuthorizationModelRelease.store_id == current.store_id,
                        AuthorizationModelRelease.id != current.model_release_id,
                        AuthorizationModelRelease.status == "ACTIVE",
                    )
                    .values(status="RETIRED", retired_at=func.now())
                )


async def execute(args: argparse.Namespace, *, live_settings: Any = settings) -> int:
    await initialize_app_context(config=_offline_settings(live_settings))
    source_client: FGAClient | None = None
    target_client: FGAClient | None = None
    try:
        current = await _load_current_release()
        config = live_settings.openfga
        pin = await discover_openfga_runtime(
            config,
            expected_model=None,
            allow_bootstrap=False,
            required_store_id=current.store_id,
            required_model_id=current.model_id,
        )
        _require(pin.store_id == current.store_id, "OpenFGA Store differs from CURRENT Catalog")
        _require(
            pin.model_checksum == current.model_checksum,
            "OpenFGA model checksum differs from the CURRENT SQL release",
        )
        if args.apply:
            _require(
                args.confirm_store_id == current.store_id,
                "--confirm-store-id does not match the discovered Store",
            )
        await _assert_maintenance_window(apply=args.apply)
        source_client = FGAClient(
            api_url=config.api_url,
            store_id=pin.store_id,
            model_id=pin.model_id,
            timeout=config.timeout,
        )
        target_model = get_authorization_model_f048()
        target_checksum = authorization_model_checksum(target_model)
        target_model_id: str | None = current.model_id if current.model_checksum == target_checksum else None
        target_client = source_client

        grants, assignee_count = await _load_canonical_grants()
        canonical_sources = _compile_sources(grants)
        persisted = await _load_persisted_sources()
        report, upserts, retires, expected = _build_report(
            mode="apply" if args.apply else "dry-run",
            current=current,
            target_model_id=target_model_id,
            target_checksum=target_checksum,
            grants=grants,
            assignee_count=assignee_count,
            canonical_sources=canonical_sources,
            persisted=persisted,
        )
        print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))
        orphan_audit: OrphanTupleAudit | None = None
        cleanup_selection: OrphanCleanupSelection | None = None
        if args.audit_orphan_tuples:
            orphan_audit = await _audit_orphan_tuples(
                source_client,
                canonical_sources=canonical_sources,
                persisted=persisted,
                object_filters=tuple(args.orphan_object),
            )
            print(
                json.dumps(
                    {"event": "orphan_tuple_audit", **asdict(orphan_audit)},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            cleanup_selection = _select_orphan_tuples(
                orphan_audit,
                object_filters=tuple(args.orphan_object),
            )
            print(
                json.dumps(
                    {"event": "orphan_cleanup_selection", **asdict(cleanup_selection)},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        if not args.apply:
            print("[dry-run] no SQL, OpenFGA, Authorization Model, or Catalog mutations were requested")
            return EXIT_OK

        if args.cleanup_orphan_tuples:
            _require(cleanup_selection is not None, "orphan cleanup requires a completed orphan selection")
            _require(not current.write_fenced, "CURRENT Catalog is write fenced")
            _require(
                args.confirm_orphan_checksum == cleanup_selection.tuple_checksum,
                "--confirm-orphan-checksum does not match the selected orphan tuple set",
            )
            cleanup_operation_ids = await _cleanup_orphan_tuples(
                source_client,
                current=current,
                selection=cleanup_selection,
                operator_id=args.operator_id,
            )
            persisted_after = await _load_persisted_sources()
            audit_after = await _audit_orphan_tuples(
                source_client,
                canonical_sources=canonical_sources,
                persisted=persisted_after,
                object_filters=tuple(args.orphan_object),
            )
            remaining_selected = tuple(sorted(set(cleanup_selection.tuples) & set(audit_after.orphan_tuples)))
            _require(
                not remaining_selected,
                f"{len(remaining_selected)} selected orphan visible tuples remain after cleanup",
            )
            print(
                json.dumps(
                    {
                        "event": "orphan_tuple_cleanup",
                        "deleted_tuple_count": cleanup_selection.tuple_count,
                        "operation_ids": cleanup_operation_ids,
                        "orphan_tuple_checksum": cleanup_selection.tuple_checksum,
                        "remaining_audited_orphan_tuple_count": audit_after.orphan_tuple_count,
                        "remaining_selected_orphan_tuple_count": len(remaining_selected),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return EXIT_OK

        _require(
            not retires,
            f"{len(retires)} stale Grant source projections require classified removal; no writes applied",
        )
        if current.write_fenced:
            _require(
                await _is_resumable_upgrade_draft(
                    current_catalog_id=current.catalog_id,
                    target_checksum=target_checksum,
                ),
                "CURRENT Catalog is fenced by an unrelated or non-resumable publication",
            )
        if target_model_id is None:
            _require(
                args.allow_model_upgrade,
                "CURRENT model differs; re-run with --allow-model-upgrade after reviewing dry-run",
            )
            publisher = OpenFGAMigrationModelPublisher(
                source_client=source_client,
                environment=_environment_name(live_settings.environment),
                predecessor_model_id=current.model_id,
            )
            target_model_id = await publisher.aget_or_publish(
                store_id=current.store_id,
                model=target_model,
                checksum=target_checksum,
            )
            target_client = source_client.for_model(target_model_id)
        _require(target_model_id is not None, "target Authorization Model was not published")
        await _ensure_expected_tuples(target_client, expected, batch_size=args.batch_size)
        await _verify_expected_tuples(target_client, expected)
        await _apply_source_rows(upserts)

        new_catalog_id = current.catalog_id
        if current.model_id != target_model_id:
            target_release_id = await _authorization_release_id(
                current.store_id,
                target_model_id,
            )
            await _activate_model_release(target_release_id)
            new_catalog_id = await _publish_noop_catalog_cutover(
                current=current,
                target_client=target_client,
                target_release_id=target_release_id,
                operator_id=args.operator_id,
                target_checksum=target_checksum,
            )

        final = await _load_current_release()
        _require(
            final.catalog_id == new_catalog_id
            and final.store_id == current.store_id
            and final.model_id == target_model_id
            and final.model_checksum == target_checksum,
            "final CURRENT Catalog/model pin verification failed",
        )
        await _retire_other_active_models(final)
        print(
            json.dumps(
                {
                    "event": "reconciled",
                    "catalog_release_id": final.catalog_id,
                    "store_id": final.store_id,
                    "model_id": final.model_id,
                    "model_version": MODEL_VERSION,
                    "source_upserts": len(upserts),
                    "source_retires": len(retires),
                    "visible_tuples_ensured": len(expected),
                    "visible_tuples_verified": len(expected),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return EXIT_OK
    finally:
        if target_client is not None and target_client is not source_client:
            await target_client.close()
        if source_client is not None:
            await source_client.close()
        await close_app_context()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except VisibleReconcileBlockedError as exc:
        print(f"F048 visible reconcile blocked: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    except Exception:
        traceback.print_exc()
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
