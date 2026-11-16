"""F048 visibility for enterprise market plugins and workbenches (F022).

The market owns its records: this module loads them, checks the tenant and
builds the ``VerifiedPermissionTarget``; F048 alone decides (constitution C4).
Business status -- deleted, disabled, no current version -- stays with the
existing repository filters, so authorization is only ever an extra condition.
Records are targeted whatever that status is: a deleted item keeps its grants
for a restoring re-import (spec AC-18), and a deleted plugin keeps appearing in
the sync policies of devices that still run it, as it did before F022.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

from starlette.concurrency import run_in_threadpool

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.permission.application.access import get_f048_runtime
from bisheng.permission.application.business_authorization import batch_check_verified_business_visible
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.permission.application.process_runtime import get_f048_process_runtime
from bisheng.permission.application.system_resource_reconcile import (
    SystemOwnedResourceSpec,
    reconcile_system_owned_resources,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.data_scope import DATA_SCOPE_ALL

PLUGIN_RESOURCE_TYPE = "dsh_market_plugin"
WORKBENCH_RESOURCE_TYPE = "dsh_market_workbench"
MARKET_RESOURCE_TYPES = (PLUGIN_RESOURCE_TYPE, WORKBENCH_RESOURCE_TYPE)
SYSTEM_ACTION_CODES = ("visible",)
MAX_ACCESS_IDS = 500
_RESOURCE_ID = re.compile(r"[a-f0-9]{32}")


@dataclass(frozen=True, slots=True)
class MarketPermissionRecord:
    id: str
    tenant_id: int
    revision: int


@dataclass(frozen=True, slots=True)
class _MarketIdentity:
    """The ``LoginPermissionIdentity`` of a market request."""

    user_id: int
    tenant_id: int
    is_global_super: bool


def _identity(actor) -> _MarketIdentity:
    return _MarketIdentity(
        user_id=int(actor.user_id),
        tenant_id=int(actor.tenant_id),
        is_global_super=bool(getattr(actor, "global_super", False)),
    )


def _record(row) -> MarketPermissionRecord | None:
    if row is None:
        return None
    return MarketPermissionRecord(id=row["id"], tenant_id=int(row["tenant_id"]), revision=int(row["revision"]))


def _valid_id(value) -> bool:
    return isinstance(value, str) and _RESOURCE_ID.fullmatch(value) is not None


def _target(resource_type, record, version, permission_context) -> VerifiedPermissionTarget:
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=record.tenant_id,
        resource_type=resource_type,
        resource_id=record.id,
        resource_version=version,
        context_version=sha256(f"{permission_context}|{record.revision}".encode()).hexdigest(),
    )


class MarketPermissionAdapter:
    """Per-id resolver registered with F048 (permission dialog, single checks)."""

    def __init__(self, runtime, resource_type, load_record):
        self.runtime = runtime
        self.resource_type = resource_type
        self._load_record = load_record

    async def load_permission_record(self, *, resource_id):
        if not _valid_id(resource_id):
            return None
        return _record(await run_in_threadpool(self._load_record, resource_id))

    async def resolve_permission_target(self, *, resource_id, actor, action):
        record = await self.load_permission_record(resource_id=resource_id)
        if record is None or record.tenant_id != actor.current_tenant_id:
            raise PermissionInvalidResourceError()
        version, context = await self.runtime.get_permission_version(
            tenant_id=record.tenant_id,
            resource_type=self.resource_type,
            resource_id=record.id,
        )
        return _target(self.resource_type, record, version, context)


async def _visible_ids(actor, resource_type, records) -> set[str]:
    """Decide a whole candidate set with one snapshot read and batched checks.

    Rows without a decidable permission state -- an import whose registration
    failed -- stay hidden rather than failing the whole list.
    """
    records = [record for record in records if record.tenant_id == int(actor.tenant_id)]
    if not records:
        return set()
    permission_actor = await resolve_permission_actor(_identity(actor))
    if permission_actor.super_admin and permission_actor.data_scope == DATA_SCOPE_ALL:
        # Same short-cut as batch_check_business_actions (skills): an unnarrowed
        # global super admin sees everything. Tenant admins follow the grants.
        return {record.id for record in records}
    runtime = await get_f048_runtime()
    snapshots = await runtime.get_permission_snapshots(
        tuple((record.tenant_id, resource_type, record.id) for record in records)
    )
    targets = []
    for record in records:
        snapshot = snapshots.get((record.tenant_id, resource_type, record.id))
        if snapshot is not None:
            targets.append(_target(resource_type, record, snapshot.version, snapshot.context_version))
    if not targets:
        return set()
    allowed = await batch_check_verified_business_visible(actor=permission_actor, targets=tuple(targets))
    return {resource_id for (_, resource_id), visible in allowed.items() if visible}


async def _employee_page(actor, resource_type, repository, candidates, page, size):
    records = [_record(row) for row in candidates]
    visible = await _visible_ids(actor, resource_type, records)
    ids = [record.id for record in records if record.id in visible]
    start = (page - 1) * size
    data = await run_in_threadpool(repository.employee_views, actor.tenant_id, ids[start : start + size])
    return {"data": data, "total": len(ids)}


async def employee_plugins(actor, repository, query, *, page, size):
    """The employee catalog: authorize every listable row, then paginate."""
    candidates = await run_in_threadpool(repository.employee_candidates, actor.tenant_id, query)
    return await _employee_page(actor, PLUGIN_RESOURCE_TYPE, repository, candidates, page, size)


async def employee_workbenches(actor, repository, *, page, size):
    candidates = await run_in_threadpool(repository.employee_candidates, actor.tenant_id)
    return await _employee_page(actor, WORKBENCH_RESOURCE_TYPE, repository, candidates, page, size)


async def require_visible(actor, resource_type, repository, resource_id) -> None:
    """Refuse a hidden item exactly as a missing one, disclosing nothing."""
    record = (
        _record(await run_in_threadpool(repository.permission_record, resource_id)) if _valid_id(resource_id) else None
    )
    if record is None or record.tenant_id != int(actor.tenant_id):
        raise LookupError("Market item not found")
    if record.id not in await _visible_ids(actor, resource_type, [record]):
        raise LookupError("Market item not found")


async def visible_policies(actor, policies):
    """Keep the sync policies of plugins the caller may see.

    A policy missing from the receipt is what makes Desktop stop and disable an
    installed plugin, so a revoked grant takes effect on the next sync.
    """
    records = [
        MarketPermissionRecord(id=policy["plugin_id"], tenant_id=int(actor.tenant_id), revision=int(policy["revision"]))
        for policy in policies
    ]
    visible = await _visible_ids(actor, PLUGIN_RESOURCE_TYPE, records)
    return [policy for policy in policies if policy["plugin_id"] in visible]


async def workbench_access(actor, repository, workbench_ids) -> dict[str, bool]:
    """Whether each installed workbench is still visible to the caller.

    Missing, foreign and hidden ids all answer ``False``. A failure to decide
    raises instead, so the client keeps its last confirmed state.
    """
    ids = list(dict.fromkeys(workbench_ids))
    if len(ids) > MAX_ACCESS_IDS:
        raise ValueError(f"At most {MAX_ACCESS_IDS} workbenches per request")
    valid = [item for item in ids if _valid_id(item)]
    rows = await run_in_threadpool(repository.permission_records, actor.tenant_id, valid) if valid else []
    visible = await _visible_ids(actor, WORKBENCH_RESOURCE_TYPE, [_record(row) for row in rows])
    return {item: item in visible for item in ids}


def _system_owned(resource_type, tenant_id, resource_id) -> SystemOwnedResourceSpec:
    return SystemOwnedResourceSpec(
        tenant_id=int(tenant_id),
        resource_type=resource_type,
        resource_id=resource_id,
        action_codes=SYSTEM_ACTION_CODES,
        context_version=f"{resource_type}:{resource_id}",
    )


async def ensure_registered(resource_type, *, tenant_id, resource_id, operator_id):
    """Register an item as system-owned and visible to all members, once.

    The reconciler creates only missing registrations; an existing one -- a
    restoring re-import included -- keeps its grants, revocations included.
    """
    runtime = (await get_f048_process_runtime()).components.facade
    return await reconcile_system_owned_resources(
        runtime,
        (_system_owned(resource_type, tenant_id, resource_id),),
        apply=True,
        operator_id=operator_id,
    )


async def ensure_import_registered(resource_type, repository, tenant_id, task, *, operator_id):
    """Register the item behind a completed import task; others need nothing."""
    if task.get("status") != "completed" or not task.get("version_id"):
        return None
    resource_id = await run_in_threadpool(repository.item_for_version, tenant_id, task["version_id"])
    if resource_id is None:
        raise LookupError("Imported market item not found")
    return await ensure_registered(resource_type, tenant_id=tenant_id, resource_id=resource_id, operator_id=operator_id)


async def system_owned_inventory(resource_types, plugin_repository, workbench_repository):
    """Every market item of the selected types, for the explicit upgrade backfill."""
    repositories = {PLUGIN_RESOURCE_TYPE: plugin_repository, WORKBENCH_RESOURCE_TYPE: workbench_repository}
    specs = []
    for resource_type in resource_types:
        with bypass_tenant_filter():
            rows = await run_in_threadpool(repositories[resource_type].all_permission_records)
        specs.extend(_system_owned(resource_type, row["tenant_id"], row["id"]) for row in rows)
    return tuple(specs)
