"""Read closed original delete receipts; retaining data grants no authority."""

from dataclasses import asdict, dataclass

from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.permission.domain.models import PermissionProjectionOperation, PermissionProjectionTuple
from bisheng.permission.domain.services.projection_plan import build_projection_operation, projection_request_checksum
from bisheng.permission.domain.services.projection_service import restore_projection_plan

REASON = "preserve_original_data_with_finalized_permission_delete"
KINDS = frozenset({"knowledge_library", "knowledge_space", "knowledge_file", "folder"})


def blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="retained_permission_delete_" + reason)


@dataclass(frozen=True, slots=True)
class RetainedPermissionDelete:
    tenant_id: int
    resource_type: str
    resource_id: str
    operation_id: int
    target_version: int
    store_id: str
    model_id: str
    request_checksum: str
    before_checksum: str
    after_checksum: str
    reason: str = REASON


async def load_facts(session, *, candidates):
    """Bounded native reads per <=200 receipts; no SQL/FGA writes."""
    from bisheng.knowledge.domain.repositories.unification_inventory_repository import _scope

    tenant = _scope(session)
    if not candidates or len(candidates) > 200:
        blocked("invalid_batch")
    ids = tuple(sorted({value[0] for value in candidates.values()}))
    if len(ids) != len(candidates) or any(kind not in KINDS for kind, _ in candidates):
        blocked("unsupported_scope")
    with session.no_autoflush, strict_tenant_filter():
        operations = (
            await session.exec(
                select(PermissionProjectionOperation).where(
                    PermissionProjectionOperation.id.in_(ids), PermissionProjectionOperation.tenant_id == tenant
                )
            )
        ).all()
        tuples, cursor = [], None
        while True:
            query = (
                select(PermissionProjectionTuple)
                .where(PermissionProjectionTuple.operation_id.in_(ids), PermissionProjectionTuple.tenant_id == tenant)
                .order_by(PermissionProjectionTuple.id)
                .limit(401)
            )
            if cursor is not None:
                query = query.where(PermissionProjectionTuple.id > cursor)
            page = (await session.exec(query)).all()
            tuples.extend(page[:400])
            if len(tuples) > len(ids) * 90:
                blocked("ledger_scope_limit")
            if len(page) <= 400:
                break
            cursor = page[399].id
    if len(operations) != len(ids):
        blocked("incomplete_ledger")
    by_id = {row.id: row for row in operations}
    groups = {ident: [] for ident in ids}
    for row in tuples:
        groups[row.operation_id].append(row)
    result = []
    for (kind, ident), (operation_id, version) in candidates.items():
        operation, rows = by_id[operation_id], groups[operation_id]
        if (
            operation.status != "FINALIZED"
            or operation.operation_type != "RESOURCE_DELETE"
            or operation.scope_type != "resource"
            or operation.scope_key != f"{kind}:{ident}"
            or operation.target_version != version
            or operation.target_version != operation.expected_version + 1
            or not 1 <= len(rows) <= 90
            # Native checksum-bound forward recovery finalizes the operation
            # without rewriting per-tuple PENDING rows. Its full AFTER graph
            # is checked by frozen inventory and publication, never inferred
            # from those advisory row statuses alone.
            or any(row.status not in {"PENDING", "APPLIED", "VERIFIED"} for row in rows)
        ):
            blocked("original_receipt_changed")
        rows.sort(key=lambda row: row.sequence)
        plan = restore_projection_plan(operation, rows)
        expected, expected_rows = build_projection_operation(plan, request_checksum=projection_request_checksum(plan))
        if (
            plan.change_item_count != 1
            or operation.before_checksum != expected.before_checksum
            or operation.after_checksum != expected.after_checksum
            or not any(delta.relation == "permission_enabled" for delta in plan.deltas)
            or any(
                delta.action != "DELETE"
                or delta.phase != "COMMIT"
                or delta.object != f"{kind}:{ident}"
                or not (
                    (delta.relation == "permission_enabled" and delta.user in {"user:*", "service_account:*"})
                    or (
                        delta.relation == "parent"
                        and delta.user.partition(":")[0] in {"knowledge_library", "knowledge_space", "folder"}
                        and delta.user.partition(":")[2].isascii()
                        and delta.user.partition(":")[2].isdecimal()
                    )
                )
                for delta in plan.deltas
            )
            or len({delta.key for delta in plan.deltas}) != len(rows)
            or any(
                (row.tuple_fingerprint, row.inverse_action) != (want.tuple_fingerprint, want.inverse_action)
                for row, want in zip(rows, expected_rows, strict=True)
            )
        ):
            blocked("not_exact_native_delete")
        result.append(
            RetainedPermissionDelete(
                tenant,
                kind,
                ident,
                operation_id,
                version,
                operation.store_id,
                operation.model_id,
                operation.request_checksum,
                operation.before_checksum,
                operation.after_checksum,
            )
        )
    return tuple(result)


async def validate_facts(session, proofs):
    from bisheng.knowledge.domain.repositories.unification_inventory_repository import UnificationInventoryRepository

    for offset in range(0, len(proofs), 200):
        batch = proofs[offset : offset + 200]
        if any(p["tenant_id"] != get_current_tenant_id() for p in batch):
            blocked("live_tenant_changed")
        candidates = {(p["resource_type"], p["resource_id"]): (p["operation_id"], p["target_version"]) for p in batch}
        actual = {(f.resource_type, f.resource_id): asdict(f) for f in await load_facts(session, candidates=candidates)}
        live = await UnificationInventoryRepository().ainspect_permission_resource_liveness(
            session, resources=tuple(candidates)
        )
        for proof in batch:
            key = proof["resource_type"], proof["resource_id"]
            if actual.get(key) != proof or live[key] is not True:
                blocked("live_proof_changed")
