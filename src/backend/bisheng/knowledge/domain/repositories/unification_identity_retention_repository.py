"""Read-only original facts for narrowly classified unmounted identities.

No tenant, business row, permission or journal is created/updated here. Large
payloads are fingerprinted one <=200-row page at a time, never retained.
"""

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.audit_log import AuditLog
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant, UserTenant
from bisheng.knowledge.domain.services.unification_fingerprints import canonical, digest
from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionProjectionOperation,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.resource_reference.application.contracts import TransactionIdentity
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType

POLICY = "preserve_unmounted_v1"
FIELDS = ("unmounted_identity_policy", "unmounted_identity_count", "unmounted_identity_digest")


def blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="unmounted_identity_" + reason)


def require(value, reason):
    if not value:
        blocked(reason)


@dataclass(frozen=True, slots=True)
class IdentityRetentionSnapshot:
    tenant_ids: tuple[int, ...]
    checksum: str
    objects: frozenset[str]
    counts: tuple[tuple[str, int], ...]
    grant_identities: tuple[tuple[int, str, str, str], ...]

    def metadata(self):
        return dict(zip(FIELDS, (POLICY, len(self.tenant_ids), self.checksum), strict=True))


class UnificationIdentityRetentionRepository:
    async def acapture(self, session):
        require(
            isinstance(session, AsyncSession)
            and session.in_transaction()
            and type(get_current_tenant_id()) is int
            and get_current_tenant_id() > 0
            and not is_tenant_filter_bypassed(),
            "native_transaction_required",
        )
        transaction = TransactionIdentity.capture(session)
        tenant_id = get_current_tenant_id()
        fingerprint, counts = sha256(), Counter()

        async def read(query):
            transaction.assert_current(session)
            require(
                get_current_tenant_id() == tenant_id and not session.new and not session.dirty and not session.deleted,
                "context_changed",
            )
            with session.no_autoflush, bypass_tenant_filter():
                result = tuple((await session.execute(query)).mappings())
            transaction.assert_current(session)
            return result

        def record(tag, row):
            value = canonical(dict(row))
            fingerprint.update(canonical((tag, len(value))))
            fingerprint.update(value)
            counts[tag] += 1

        async def pages(table, query):
            after = None
            while True:
                current = query.order_by(table.c.id).limit(200)
                if after is not None:
                    current = current.where(table.c.id > after)
                rows = await read(current)
                for row in rows:
                    yield row
                if len(rows) < 200:
                    break
                after = rows[-1]["id"]

        def orphan_query(table):
            actual = Tenant.__table__.alias("retention_actual_tenant")
            return select(*table.c).outerjoin(actual, actual.c.id == table.c.tenant_id).where(actual.c.id.is_(None))

        modes, tenants, objects, operations, owner_by_object = {}, set(), set(), {}, {}
        table = ResourcePermissionMode.__table__
        async for row in pages(table, orphan_query(table)):
            ident = row["tenant_id"]
            key = ident, row["resource_type"], row["resource_id"]
            require(
                type(ident) is int and ident > 0 and row["resource_type"] in {"tool", "assistant"}, "original_scope"
            )
            require(
                row["projection_state"] == "CURRENT"
                and row["version"] > 0
                and row["mode"] == "CUSTOM"
                and row["parent_type"] is None
                and row["parent_id"] is None,
                "mode_not_stable",
            )
            obj = f"{key[1]}:{key[2]}"
            require(key not in modes and obj not in objects, "duplicate_original_scope")
            modes[key] = row["id"]
            owner_by_object[(key[1], key[2])] = ident
            tenants.add(ident)
            objects.add(obj)
            if row["operation_id"] is not None:
                operations[row["operation_id"]] = ident
            record(table.name, row)
        require(bool(modes), "original_modes_required")
        grant_owners, grant_identities = {}, []
        for model in (PermissionGrant, PermissionGrantAssignee, PermissionVisibleSourceProjection):
            table = model.__table__
            async for row in pages(table, orphan_query(table)):
                if model is PermissionGrantAssignee:
                    require(grant_owners.get(row["grant_id"]) == row["tenant_id"], "assignee_parent")
                else:
                    require(
                        (row["tenant_id"], row["resource_type"], row["resource_id"]) in modes, "unclassified_permission"
                    )
                if model is PermissionGrant:
                    require(row["projection_state"] == "CURRENT" and row["version"] > 0, "grant_not_stable")
                    grant_owners[row["id"]] = row["tenant_id"]
                    grant_identities.append(
                        (row["tenant_id"], row["resource_type"], row["resource_id"], row["model_key"])
                    )
                if model is PermissionVisibleSourceProjection and row["operation_id"] is not None:
                    operations[row["operation_id"]] = row["tenant_id"]
                record(table.name, row)
        ordered = tuple(sorted(tenants))
        unmounts = {}
        for start in range(0, len(ordered), 200):
            ids = ordered[start : start + 200]
            table = PermissionProjectionOperation.__table__
            pending = select(table.c.id, table.c.tenant_id, table.c.scope_key).where(
                table.c.tenant_id.in_(ids), table.c.scope_type == "resource", table.c.status != "FINALIZED"
            )
            async for row in pages(table, pending):
                require((row["tenant_id"], *row["scope_key"].split(":", 1)) not in modes, "unfinished_projection")
            for model in (UserTenant, Department):
                table = model.__table__
                condition = table.c.tenant_id.in_(ids)
                if model is Department:
                    condition = or_(condition, table.c.mounted_tenant_id.in_(ids))
                require(not await read(select(table.c.id).where(condition).limit(1)), "identity_still_bound")
            table = AuditLog.__table__
            async for row in pages(
                table, select(*table.c).where(table.c.tenant_id.in_(ids), table.c.action == "tenant.unmount")
            ):
                ident = row["tenant_id"]
                require(
                    row["target_type"] == "tenant"
                    and row["target_id"] == str(ident)
                    and ident not in unmounts
                    and type(row["metadata"]) is dict
                    and type(row["metadata"].get("migrated_counts")) is dict,
                    "unmount_evidence",
                )
                unmounts[ident] = row["metadata"]["migrated_counts"]
                record(table.name, row)
        require(set(unmounts) == tenants, "unmount_evidence_missing")
        tool_ids = {}
        table = GptsToolsType.__table__
        async for row in pages(table, orphan_query(table)):
            key = row["tenant_id"], "tool", str(row["id"])
            require(key in modes and row["is_preset"] == ToolPresetType.PRESET.value, "not_original_preset")
            tool_ids[row["id"]] = row["tenant_id"]
            record(table.name, row)
        require(counts[table.name] == sum(key[1] == "tool" for key in modes), "tool_owner_missing")
        table = GptsTools.__table__
        async for row in pages(table, orphan_query(table)):
            require(
                tool_ids.get(row["type"]) == row["tenant_id"] and row["is_preset"] == ToolPresetType.PRESET.value,
                "tool_child_owner",
            )
            record(table.name, row)
        for kind in ("tool", "assistant"):
            ids = sorted(key[2] for key in modes if key[1] == kind)
            for start in range(0, len(ids), 200):
                batch = ids[start : start + 200]
                mode, actual = ResourcePermissionMode.__table__, Tenant.__table__
                require(
                    not await read(
                        select(mode.c.id)
                        .join(actual, actual.c.id == mode.c.tenant_id)
                        .where(mode.c.resource_type == kind, mode.c.resource_id.in_(batch))
                        .limit(1)
                    ),
                    "live_mode_conflict",
                )
                if kind == "assistant":
                    table = Assistant.__table__
                    rows = await read(
                        select(table.c.id, table.c.tenant_id, actual.c.id.label("actual_tenant"))
                        .outerjoin(actual, actual.c.id == table.c.tenant_id)
                        .where(table.c.id.in_(batch))
                    )
                    require({r["id"] for r in rows} == set(batch), "moved_assistant_missing")
                    for row in rows:
                        old = owner_by_object[(kind, row["id"])]
                        require(
                            row["tenant_id"] == ROOT_TENANT_ID
                            and row["actual_tenant"] == ROOT_TENANT_ID
                            and type(unmounts[old].get("assistant")) is int
                            and unmounts[old]["assistant"] > 0,
                            "moved_assistant_evidence",
                        )
                        record(table.name, row)
        ids = sorted(operations)
        for start in range(0, len(ids), 200):
            table = PermissionProjectionOperation.__table__
            rows = await read(select(*table.c).where(table.c.id.in_(ids[start : start + 200])).order_by(table.c.id))
            require({r["id"] for r in rows} == set(ids[start : start + 200]), "operation_missing")
            for row in rows:
                require(
                    row["tenant_id"] == operations[row["id"]] and row["status"] == "FINALIZED", "operation_not_stable"
                )
                record(table.name, row)
        return IdentityRetentionSnapshot(
            ordered,
            digest((ordered, fingerprint.hexdigest(), sorted(counts.items()))),
            frozenset(objects),
            tuple(sorted(counts.items())),
            tuple(grant_identities),
        )
