"""History preparation helper: close residual service-account delete markers.

No business payload is deleted or reassigned. Preview freezes an original native
finalized delete, current mode/mirrors, payload digest and complete object tuples.
Apply uses the normal projection reservation/finalizer and its durable journal.
Use prepare_f118_history.py (optionally --delete-closures-only), not this helper.
"""

from dataclasses import asdict

from sqlalchemy import or_
from sqlmodel import select

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.unification_delete_retention_repository import load_facts
from bisheng.knowledge.domain.repositories.unification_inventory_repository import UnificationInventoryRepository
from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionProjectionOperation,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.services.projection_plan import (
    ProjectionPlan,
    ProjectionTupleDelta,
    normalize_projection_plan,
)
from bisheng.permission.domain.services.projection_service import restore_projection_plan


def require(value, reason):
    if not value:
        from scripts.prepare_f118_history import blocked

        blocked("delete_closure_" + reason)


def ordered(rows):
    import json

    from scripts.prepare_f118_history import canonical

    return sorted((canonical(row) for row in rows), key=lambda row: json.dumps(row, sort_keys=True))


async def selected(sessions, mode):
    from scripts.prepare_f118_history import canonical, checksum, global_session, mirrors, read_pin, unfrozen

    async with global_session(sessions) as session:
        await unfrozen(session)
        pin = await read_pin(session)
        row = await session.get(ResourcePermissionMode, mode["id"])
        require(row is not None, "mode_missing")
        kind, ident, tenant = mode["resource_type"], mode["resource_id"], mode["tenant_id"]
        for model in (ResourcePermissionMode, PermissionGrant, PermissionVisibleSourceProjection):
            foreign = (
                await session.exec(
                    select(model.id)
                    .where(
                        model.resource_type == kind,
                        model.resource_id == ident,
                        or_(model.tenant_id != tenant, model.tenant_id.is_(None)),
                    )
                    .limit(1)
                )
            ).first()
            require(foreign is None, "foreign_scope")
        model = Knowledge if kind in {"knowledge_library", "knowledge_space"} else KnowledgeFile
        business = await session.get(model, int(ident))
        require(business is not None and business.tenant_id == tenant, "payload_identity_changed")
        current = canonical(row.model_dump())
        body = canonical(business.model_dump())
        snapshot, _ = await mirrors(session, current)
        require(all(row["tenant_id"] == tenant for rows in snapshot.values() for row in rows), "foreign_mirror")
        return {
            "pin": pin,
            "mode": current,
            "mirrors": snapshot,
            "business": body,
            "business_digest": checksum({key: value for key, value in body.items() if key != "update_time"}),
        }


async def capture(sessions, client, *, pin, excluded=frozenset(), parents=(), updates=(), levels=()):
    from scripts.prepare_f118_history import canonical, checksum, global_session, read_pin, unfrozen

    parent_map = {item["mode"]["id"]: item for item in parents}
    repairs, retained, after = [], [], None
    while True:
        async with global_session(sessions) as session:
            await unfrozen(session)
            require(await read_pin(session) == pin, "pin_changed")
            query = (
                select(ResourcePermissionMode)
                .join(
                    PermissionProjectionOperation,
                    PermissionProjectionOperation.id == ResourcePermissionMode.operation_id,
                )
                .where(
                    ResourcePermissionMode.projection_state == "CURRENT",
                    PermissionProjectionOperation.operation_type == "RESOURCE_DELETE",
                    PermissionProjectionOperation.status.in_(("FINALIZED", "FAILED_CLOSED")),
                )
                .order_by(ResourcePermissionMode.id)
                .limit(200)
            )
            if after is not None:
                query = query.where(ResourcePermissionMode.id > after)
            modes = [canonical(row.model_dump()) for row in (await session.exec(query)).all()]
        if not modes:
            break
        for tenant in sorted({row["tenant_id"] for row in modes}):
            batch = [row for row in modes if row["tenant_id"] == tenant]
            with tenant_execution_scope(tenant):
                async with sessions() as session, session.begin():
                    keys = tuple((row["resource_type"], row["resource_id"]) for row in batch)
                    live = await UnificationInventoryRepository().ainspect_permission_resource_liveness(
                        session, resources=keys
                    )
                    candidates = {
                        (row["resource_type"], row["resource_id"]): (row["operation_id"], row["version"])
                        for row in batch
                        if live[row["resource_type"], row["resource_id"]]
                        and (row["resource_type"], row["resource_id"]) not in excluded
                    }
                    operations = (
                        {
                            row.id: row
                            for row in (
                                await session.exec(
                                    select(PermissionProjectionOperation).where(
                                        PermissionProjectionOperation.id.in_(
                                            [value[0] for value in candidates.values()]
                                        ),
                                        PermissionProjectionOperation.tenant_id == tenant,
                                    )
                                )
                            ).all()
                        }
                        if candidates
                        else {}
                    )
                    facts = []
                    for status in ("FINALIZED", "FAILED_CLOSED"):
                        chosen = {}
                        for key, (operation_id, version) in candidates.items():
                            operation = operations[operation_id]
                            if operation.status == status:
                                require(
                                    version
                                    == (
                                        operation.target_version
                                        if status == "FINALIZED"
                                        else operation.expected_version
                                    ),
                                    "original_fence_changed",
                                )
                                chosen[key] = (operation_id, operation.target_version)
                        if chosen:
                            facts.extend(await load_facts(session, candidates=chosen, operation_status=status))
            by_key = {(row["resource_type"], row["resource_id"]): row for row in batch}
            for fact in facts:
                require(fact.store_id == pin["store_id"], "original_store_changed")
                mode = by_key[fact.resource_type, fact.resource_id]
                source_status = "FINALIZED" if mode["version"] == fact.target_version else "FAILED_CLOSED"
                if source_status == "FINALIZED":
                    retained.append(asdict(fact))
                value = await selected(sessions, mode)
                require(value["pin"] == pin and value["mode"] == mode, "capture_changed")
                scope = f"{fact.resource_type}:{fact.resource_id}"
                rows = ordered(await client.read_tuples(object=scope, consistency="HIGHER_CONSISTENCY"))
                require(all(not row.get("condition") for row in rows), "conditional_graph")
                enabled = [row for row in rows if row["relation"] == "permission_enabled"]
                require(
                    all(
                        row["user"]
                        in ({"service_account:*"} if source_status == "FINALIZED" else {"user:*", "service_account:*"})
                        and row["object"] == scope
                        for row in enabled
                    ),
                    "user_access_reappeared",
                )
                parent = parent_map.get(mode["id"])
                if enabled or parent is not None or source_status == "FAILED_CLOSED":
                    require(len(enabled) <= (1 if source_status == "FINALIZED" else 2), "duplicate_marker")
                    parent_deletes = parent["deletes"] if parent else []
                    require(len(parent_deletes) <= 88, "atomic_scope_limit")
                    choices = [value["business"]]
                    table = (
                        "knowledge"
                        if mode["resource_type"] in {"knowledge_library", "knowledge_space"}
                        else "knowledgefile"
                    )
                    for change in updates:
                        if change["table"] == table and change["before"]["id"] == int(mode["resource_id"]):
                            choices += [row | change["values"] for row in choices]
                    for change in levels:
                        if change["table"] == table and change["before"]["id"] == int(mode["resource_id"]):
                            choices += [row | {"level": change["after_level"]} for row in choices]
                    repairs.append(
                        {
                            "mode": mode,
                            "source": asdict(fact),
                            "source_status": source_status,
                            "tuples": rows,
                            "business_digests": sorted(
                                {checksum({k: v for k, v in row.items() if k != "update_time"}) for row in choices}
                            ),
                            "parent_deletes": parent_deletes,
                            "mirrors": value["mirrors"],
                        }
                    )
        if len(modes) < 200:
            break
        after = modes[-1]["id"]
    return repairs, retained


def projection_plan(plan, item, *, identity, operator_id):
    mode = item["mode"]
    scope = f"{mode['resource_type']}:{mode['resource_id']}"
    return normalize_projection_plan(
        ProjectionPlan(
            tenant_id=mode["tenant_id"],
            idempotency_key=f"history-delete-closure:{identity}:{mode['id']}",
            operation_type="RESOURCE_DELETE",
            scope_type="resource",
            scope_key=scope,
            expected_version=mode["version"],
            target_version=mode["version"] + 1,
            store_id=plan["pin"]["store_id"],
            model_id=plan["pin"]["model_id"],
            operator_id=operator_id,
            change_item_count=1,
            deltas=(
                ProjectionTupleDelta("COMMIT", 0, "DELETE", "user:*", "permission_enabled", scope),
                ProjectionTupleDelta("COMMIT", 1, "DELETE", "service_account:*", "permission_enabled", scope),
                *(
                    ProjectionTupleDelta("COMMIT", seq + 2, "DELETE", *key)
                    for seq, key in enumerate(item.get("parent_deletes", ()))
                ),
            ),
        )
    )


async def verify(plan, item, *, sessions, client, expected, repository):
    from scripts.prepare_f118_history import checksum

    mode = item["mode"]
    value = await selected(sessions, mode)
    require(
        value["pin"] == plan["pin"] and value["business_digest"] in item["business_digests"], "payload_or_pin_changed"
    )
    require(
        {k: v for k, v in value["mirrors"].items() if k != "resource_permission_mode"}
        == {k: v for k, v in item["mirrors"].items() if k != "resource_permission_mode"},
        "sql_grants_changed",
    )
    require(
        {
            k: v
            for k, v in value["mode"].items()
            if k not in {"version", "projection_state", "operation_id", "update_time"}
        }
        == {k: v for k, v in mode.items() if k not in {"version", "projection_state", "operation_id", "update_time"}},
        "mode_intent_changed",
    )
    source = item["source"]
    with tenant_execution_scope(mode["tenant_id"]):
        async with sessions() as session, session.begin():
            facts = await load_facts(
                session,
                candidates={
                    (source["resource_type"], source["resource_id"]): (source["operation_id"], source["target_version"])
                },
                operation_status=item.get("source_status", "FINALIZED"),
            )
    require(len(facts) == 1 and asdict(facts[0]) == source, "original_receipt_changed")
    operation = await repository.aget_operation_by_idempotency(expected.idempotency_key)
    before = item["tuples"]
    keys = {delta.key for delta in expected.deltas}
    after = [row for row in before if (row["user"], row["relation"], row["object"]) not in keys]
    actual = ordered(await client.read_tuples(object=expected.scope_key, consistency="HIGHER_CONSISTENCY"))
    if operation is None or (operation.status == "PREPARED" and value["mode"] == mode):
        require(value["mode"] == mode and actual == before, "before_changed")
    else:
        require(
            restore_projection_plan(operation, await repository.aget_operation_tuples(operation.id)) == expected,
            "closure_ledger_changed",
        )
        require(
            value["mode"]["operation_id"] == operation.id
            and (value["mode"]["version"], value["mode"]["projection_state"])
            in {(mode["version"], "PROJECTING"), (mode["version"], "FAILED_CLOSED"), (mode["version"] + 1, "CURRENT")},
            "fence_changed",
        )
        require(checksum(actual) in {checksum(before), checksum(after)}, "graph_changed")
        if operation.status == "FINALIZED":
            require(
                value["mode"]["version"] == mode["version"] + 1
                and value["mode"]["projection_state"] == "CURRENT"
                and actual == after,
                "after_changed",
            )


async def apply(plan, *, sessions, client, runtime, operator_id):
    from bisheng.common.errcode.permission import PermissionProjectionFailedError
    from scripts.prepare_f118_history import checksum, target_for

    items = plan.get("delete_closures", ())
    if not items:
        return []
    identity = checksum(plan)[:32]
    repository = ProjectionRepository(sessions)
    # Prove the whole selected set before the first mutation, then recheck each
    # scope at its reservation. Each step owns its original durable receipt.
    for item in items:
        with tenant_execution_scope(item["mode"]["tenant_id"]):
            expected = projection_plan(plan, item, identity=identity, operator_id=operator_id)
            await verify(plan, item, sessions=sessions, client=client, expected=expected, repository=repository)
    receipts = []
    for item in items:
        with tenant_execution_scope(item["mode"]["tenant_id"]):
            expected = projection_plan(plan, item, identity=identity, operator_id=operator_id)
            await verify(plan, item, sessions=sessions, client=client, expected=expected, repository=repository)
            operation = await runtime._projection.prepare(expected)
            if operation.status == "PREPARED":
                await runtime._state.mark_projecting(
                    target=target_for(item["mode"]),
                    operation_id=operation.id,
                    expected_catalog_release_id=plan["pin"]["release_id"],
                )
            try:
                if operation.status == "FAILED_CLOSED":
                    raise PermissionProjectionFailedError()
                outcome = await runtime._projection.execute(expected)
            except PermissionProjectionFailedError:
                operation = await repository.aget_operation_by_idempotency(expected.idempotency_key)
                require(operation is not None and operation.status == "FAILED_CLOSED", "not_recoverable")
                await verify(plan, item, sessions=sessions, client=client, expected=expected, repository=repository)
                preview = await runtime._projection.inspect_failed_closed_recovery(operation.id)
                require(
                    all(
                        delta.action == "DELETE" and delta.key in {row.key for row in expected.deltas}
                        for delta in preview.correction_deltas
                    ),
                    "recovery_scope_changed",
                )
                outcome = await runtime._projection.recover_failed_closed_operation(
                    operation.id, confirmation_checksum=preview.confirmation_checksum
                )
            require(outcome.status == "FINALIZED", "not_finalized")
            await verify(plan, item, sessions=sessions, client=client, expected=expected, repository=repository)
            receipts.append(outcome.operation_id)
    return receipts
