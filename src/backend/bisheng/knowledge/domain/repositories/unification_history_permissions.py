"""Native permission repairs owned exclusively by prepare_f118_history.

The owning CLI freezes exact evidence before apply. Empty legacy NORMAL-file
permissions inherit their proven original parent; failed mutations retain and
forward-complete their original ledger. Unknown intent is never reconstructed.
"""

from dataclasses import asdict

from sqlmodel import select

from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionProjectionOperation,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.user.domain.models.user import User


async def absent_authorization(session, files):
    """Global object identity, including foreign SQL owners and old operations."""
    occupied = set()
    for start in range(0, len(files), 200):
        ids = [str(row["id"]) for row in files[start : start + 200]]
        for model in (ResourcePermissionMode, PermissionGrant, PermissionVisibleSourceProjection):
            rows = (
                await session.exec(
                    select(model.resource_id).where(
                        model.resource_type.in_(("folder", "knowledge_file")), model.resource_id.in_(ids)
                    )
                )
            ).all()
            occupied.update(int(ident) for ident in rows)
        rows = (
            await session.exec(
                select(PermissionProjectionOperation.scope_key).where(
                    PermissionProjectionOperation.scope_type == "resource",
                    PermissionProjectionOperation.scope_key.in_(
                        [f"{kind}:{ident}" for ident in ids for kind in ("folder", "knowledge_file")]
                    ),
                )
            )
        ).all()
        occupied.update(int(key.partition(":")[2]) for key in rows)
    return occupied


async def initialization_candidates(session, candidates):
    """Only successful old flat NORMAL files, with an existing real creator."""
    occupied = await absent_authorization(session, [item["file"] for item in candidates])
    creators = {}
    ids = sorted({item["file"]["user_id"] for item in candidates if type(item["file"]["user_id"]) is int})
    for start in range(0, len(ids), 200):
        creators.update(
            (
                await session.exec(select(User.user_id, User.delete).where(User.user_id.in_(ids[start : start + 200])))
            ).all()
        )
    accepted, rejected = [], []
    for item in candidates:
        row, root, parent_mode = item["file"], item["root"], item["parent_mode"]
        if (
            row["id"] in occupied
            or row["status"] != 2
            or row["file_type"] != 1
            or row["file_level_path"] not in (None, "")
            or root["type"] != 0
            or (row["tenant_id"], row["knowledge_id"]) != (root["tenant_id"], root["id"])
            or creators.get(row["user_id"]) not in (0, 1)
            or row["user_id"] is None
            or parent_mode is None
            or parent_mode["tenant_id"] != row["tenant_id"]
            or parent_mode["projection_state"] != "CURRENT"
        ):
            rejected.append(row["id"])
        else:
            accepted.append({**item, "creator": {"user_id": row["user_id"], "delete": creators[row["user_id"]]}})
    return accepted, rejected


def ledger_identity(operation):
    return {
        key: getattr(operation, key)
        for key in (
            "id",
            "tenant_id",
            "idempotency_key",
            "request_checksum",
            "operation_type",
            "scope_type",
            "scope_key",
            "expected_version",
            "target_version",
            "store_id",
            "model_id",
            "before_checksum",
            "after_checksum",
            "operator_id",
        )
    }


def inspector(sessions, client):
    from bisheng.permission.application.sql_runtime import FGAProjectionAdapter, SqlProjectionScopeGuard
    from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
    from bisheng.permission.domain.services.projection_service import ProjectionService

    # Read-only preview needs neither a Redis marker nor any bootstrap writer.
    return ProjectionService(
        repository=ProjectionRepository(sessions),
        marker=None,
        scope_guard=SqlProjectionScopeGuard(),
        fga=FGAProjectionAdapter(client),
    )


async def capture_recoveries(sessions, client, candidates, pin):
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.knowledge.domain.repositories.unification_history_repository import global_session, mirrors

    accepted, rejected = [], []
    service = inspector(sessions, client)
    for item in candidates:
        mode = item["mode"]
        with tenant_execution_scope(mode["tenant_id"]):
            async with global_session(sessions) as session:
                operation = await session.get(PermissionProjectionOperation, mode["operation_id"])
                if (
                    operation is None
                    or operation.status != "FAILED_CLOSED"
                    or operation.operation_type != "GRANT_MUTATION"
                    or operation.scope_type != "resource"
                    or operation.scope_key != f"{mode['resource_type']}:{mode['resource_id']}"
                    or operation.tenant_id != mode["tenant_id"]
                    or operation.expected_version != mode["version"]
                    or operation.target_version != mode["version"] + 1
                    or (operation.store_id, operation.model_id) != (pin["store_id"], pin["model_id"])
                ):
                    rejected.append(item)
                    continue
                ledger = ledger_identity(operation)
                sql, _ = await mirrors(session, mode)
            # Original parser checks the ledger checksums; the scope guard must
            # separately confirm that this same mode still owns its fence.
            preview = await service.inspect_failed_closed_recovery(operation.id)
            _, frozen = await service._load_operation_plan(operation.id)
            if not await service._scope_guard.is_failed_closed_recovery_scope(frozen, operation.id):
                rejected.append(item)
                continue
            accepted.append({**item, "ledger": ledger, "sql": sql, "preview": asdict(preview)})
    return accepted, rejected


async def verify_business(session, item):
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.repositories.unification_history_repository import blocked, canonical, require_chain

    for model, before in ((KnowledgeFile, item["file"]), (Knowledge, item["root"])):
        row = await session.get(model, before["id"])
        current = canonical(row.model_dump()) if row else {}
        if any(current.get(key) != value for key, value in before.items() if key not in {"level", "update_time"}):
            blocked("permission_repair_business_changed")
    await require_chain(session, item["file"])


async def apply_repairs(plan, *, sessions, client, runtime, operator_id):
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.knowledge.domain.repositories.unification_history_repository import (
        blocked,
        global_session,
        history_plan_identity,
        mirrors,
        read_pin,
        target_for,
        unfrozen,
    )
    from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
    from bisheng.permission.domain.services.owner_service import OwnerProjectionContext
    from bisheng.permission.domain.services.resource_lifecycle_policy import build_create_plan

    receipts = []
    repository = ProjectionRepository(sessions)
    identity = history_plan_identity(plan)[:32] if plan.get("initializations") else None
    for item in plan.get("initializations", ()):
        row = item["file"]
        mode = {
            "tenant_id": row["tenant_id"],
            "resource_type": "knowledge_file",
            "resource_id": str(row["id"]),
            "version": 0,
            "parent_type": "knowledge_library",
            "parent_id": str(row["knowledge_id"]),
        }
        target = target_for(mode)
        key = f"history-initialize:{identity}:{row['id']}"
        with tenant_execution_scope(row["tenant_id"]):
            existing = await repository.aget_operation_by_idempotency(key)
            async with global_session(sessions) as session:
                await unfrozen(session)
                if await read_pin(session) != plan["pin"]:
                    blocked("catalog_pin_changed")
                await verify_business(session, item)
                creator = await session.get(User, item["creator"]["user_id"])
                if creator is None or creator.delete != item["creator"]["delete"]:
                    blocked("initialization_creator_changed")
                parent = await session.get(ResourcePermissionMode, item["parent_mode"]["id"])
                from bisheng.knowledge.domain.repositories.unification_history_repository import canonical

                if parent is None or canonical(parent.model_dump()) != item["parent_mode"]:
                    blocked("initialization_parent_permission_changed")
                if existing is None:
                    accepted, rejected = await initialization_candidates(session, [item])
                    if rejected or not accepted:
                        blocked("initialization_authorization_changed")
                else:
                    current = (
                        await session.exec(
                            select(ResourcePermissionMode).where(
                                ResourcePermissionMode.resource_type.in_(("knowledge_file", "folder")),
                                ResourcePermissionMode.resource_id == str(row["id"]),
                            )
                        )
                    ).all()
                    if current and (
                        len(current) != 1
                        or current[0].tenant_id != row["tenant_id"]
                        or current[0].operation_id != existing.id
                        or current[0].mode != "INHERIT"
                        or current[0].resource_type != "knowledge_file"
                        or (current[0].version, current[0].projection_state)
                        not in {(0, "PROJECTING"), (0, "PENDING"), (1, "CURRENT")}
                        or (current[0].parent_type, current[0].parent_id)
                        != ("knowledge_library", str(row["knowledge_id"]))
                    ):
                        blocked("initialization_fence_changed")
                    if existing.status == "FINALIZED" and (
                        not current or (current[0].version, current[0].projection_state) != (1, "CURRENT")
                    ):
                        blocked("initialization_finalized_scope_changed")
                    for model in (PermissionGrant, PermissionVisibleSourceProjection):
                        if (
                            await session.exec(
                                select(model.id)
                                .where(
                                    model.resource_type.in_(("folder", "knowledge_file")),
                                    model.resource_id == str(row["id"]),
                                )
                                .limit(1)
                            )
                        ).first() is not None:
                            blocked("initialization_new_authorization_exists")
                    if (
                        await session.exec(
                            select(PermissionProjectionOperation.id)
                            .where(
                                PermissionProjectionOperation.scope_type == "resource",
                                PermissionProjectionOperation.scope_key.in_(
                                    (f"knowledge_file:{row['id']}", f"folder:{row['id']}")
                                ),
                                PermissionProjectionOperation.id != existing.id,
                            )
                            .limit(1)
                        )
                    ).first() is not None:
                        blocked("initialization_new_operation_exists")
            frozen = build_create_plan(
                target,
                store_id=plan["pin"]["store_id"],
                model_id=plan["pin"]["model_id"],
                operator_id=operator_id,
                idempotency_key=key,
                protected_deltas=(),
                permission_mode="INHERIT",
            )
            expected = {delta.key for delta in frozen.deltas}
            present = {
                (r["user"], r["relation"], r["object"])
                for r in await client.read_tuples(
                    object=f"knowledge_file:{row['id']}", consistency="HIGHER_CONSISTENCY"
                )
            }
            if present - expected or (existing is None and present):
                blocked("initialization_graph_changed")
            operation = await runtime._projection.prepare(frozen)
            if operation.status == "PREPARED":
                context = OwnerProjectionContext(
                    target=target,
                    owner_grant=None,
                    source_id=0,
                    owner_user_id=row["user_id"],
                    system_owned=False,
                    system_predicate=False,
                    store_id=plan["pin"]["store_id"],
                    model_id=plan["pin"]["model_id"],
                    operator_id=operator_id,
                    idempotency_key=key,
                    permission_mode="INHERIT",
                )
                await runtime._state.prepare_owner(context, None, None, None, operation_id=operation.id)
            outcome = await runtime._projection.execute(frozen)
            if not await runtime._projection._is_after(frozen.deltas):
                blocked("initialization_graph_not_repaired")
            async with global_session(sessions) as session:
                if await read_pin(session) != plan["pin"]:
                    blocked("catalog_pin_changed")
                await verify_business(session, item)
            receipts.append(outcome.operation_id)
    for item in plan.get("recoveries", ()):
        mode, ledger = item["mode"], item["ledger"]
        with tenant_execution_scope(mode["tenant_id"]):
            async with global_session(sessions) as session:
                await unfrozen(session)
                if await read_pin(session) != plan["pin"]:
                    blocked("catalog_pin_changed")
                await verify_business(session, item)
                current = await session.get(ResourcePermissionMode, mode["id"])
                operation = await session.get(PermissionProjectionOperation, ledger["id"])
                if (
                    current is None
                    or operation is None
                    or ledger_identity(operation) != ledger
                    or current.operation_id != ledger["id"]
                    or current.tenant_id != mode["tenant_id"]
                    or (current.mode, current.parent_type, current.parent_id)
                    != (mode["mode"], mode["parent_type"], mode["parent_id"])
                    or (current.version, current.projection_state)
                    not in {(ledger["expected_version"], "FAILED_CLOSED"), (ledger["target_version"], "CURRENT")}
                ):
                    blocked("recovery_ledger_or_fence_changed")
                sql, _ = await mirrors(session, mode)
                if current.projection_state == "FAILED_CLOSED":

                    def original(value):
                        return {
                            name: [{k: v for k, v in row.items() if k != "update_time"} for row in rows]
                            for name, rows in value.items()
                        }

                    if original(sql) != original(item["sql"]):
                        blocked("recovery_original_sql_changed")

                def roster(value):
                    # Native finalization advances only projection/state fields;
                    # business identities and authorization intent stay frozen.
                    return {
                        name: [
                            {
                                k: v
                                for k, v in row.items()
                                if k not in {"state", "projection_state", "version", "operation_id", "update_time"}
                            }
                            for row in rows
                        ]
                        for name, rows in value.items()
                    }

                if roster(sql) != roster(item["sql"]):
                    blocked("recovery_sql_intent_changed")
            if operation.status == "FINALIZED":
                _, frozen = await runtime._projection._load_operation_plan(operation.id)
                if not await runtime._projection._is_after(frozen.deltas):
                    blocked("recovery_finalized_graph_changed")
                receipts.append(operation.id)
                continue
            preview = await runtime._projection.inspect_failed_closed_recovery(operation.id)
            if preview.confirmation_checksum != item["preview"]["confirmation_checksum"]:
                # An interrupted native recovery may have reached AFTER while
                # keeping this exact original fence. Only the native reconciler
                # may finish it; no replacement intent or SQL state override.
                if preview.observed_state != "AFTER":
                    blocked("recovery_graph_changed")
            outcome = await runtime._projection.recover_failed_closed_operation(
                operation.id, confirmation_checksum=preview.confirmation_checksum
            )
            async with global_session(sessions) as session:
                if await read_pin(session) != plan["pin"]:
                    blocked("catalog_pin_changed")
                await verify_business(session, item)
            receipts.append(outcome.operation_id)
    return receipts


async def builtin_finalization_fact(sessions, service, mode, pin):
    """A native AFTER proof permits SQL finalization, never a tuple correction."""
    from bisheng.knowledge.domain.repositories.unification_history_repository import (
        blocked,
        canonical,
        checksum,
        global_session,
        mirrors,
        read_pin,
        unfrozen,
    )
    from bisheng.linsight.domain.models.linsight_skill import LinsightSkill

    async with global_session(sessions) as session:
        await unfrozen(session)
        if await read_pin(session) != pin:
            blocked("builtin_finalization_pin_changed")
        current = await session.get(ResourcePermissionMode, mode["id"])
        operation = await session.get(PermissionProjectionOperation, mode["operation_id"])
        skill = await session.get(LinsightSkill, int(mode["resource_id"]))
        if (
            current is None
            or operation is None
            or skill is None
            or current.tenant_id != mode["tenant_id"]
            or skill.tenant_id != mode["tenant_id"]
            or current.resource_type != "linsight_skill"
            or current.resource_id != mode["resource_id"]
            or current.operation_id != operation.id
            or (operation.store_id, operation.model_id) != (pin["store_id"], pin["model_id"])
            or operation.scope_type != "resource"
            or operation.scope_key != f"linsight_skill:{skill.id}"
            or operation.operation_type != "RESOURCE_CREATE"
            or operation.tenant_id != mode["tenant_id"]
            or operation.target_version != operation.expected_version + 1
            or skill.source != "builtin"
            or skill.owner_user_id != 0
            or skill.created_by is not None
            or not skill.content_hash
            or not skill.object_path
        ):
            blocked("builtin_finalization_original_intent_changed")
        sql, _ = await mirrors(session, mode)
        fact = {"ledger": ledger_identity(operation), "business_digest": checksum(canonical(skill.model_dump()))}
        if operation.status == "FINALIZED":
            if current.projection_state != "CURRENT" or current.version != operation.target_version:
                blocked("builtin_finalization_completed_fence_changed")
        elif (
            operation.status not in {"FAILED_CLOSED", "COMMITTED"}
            or current.projection_state != "FAILED_CLOSED"
            or current.version != operation.expected_version
            or canonical(current.model_dump()) != mode
            or not sql["permission_visible_source_projection"]
            or any(row["state"] != "PENDING" for row in sql["permission_visible_source_projection"])
        ):
            blocked("builtin_finalization_original_fence_changed")
    _, frozen = await service._load_operation_plan(operation.id)
    if not await service._is_after(frozen.deltas):
        blocked("builtin_finalization_not_after")
    if operation.status != "FINALIZED":
        preview = await service.inspect_failed_closed_recovery(operation.id)
        if preview.observed_state != "AFTER" or preview.correction_deltas:
            blocked("builtin_finalization_requires_graph_mutation")
        fact.update(mode=mode, sql=sql, preview=asdict(preview))
    return operation, canonical(fact)


async def capture_builtin_finalizations(sessions, client, pin):
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.knowledge.domain.repositories.unification_history_repository import canonical, global_session

    result, cursor = [], 0
    service = inspector(sessions, client)
    while True:
        async with global_session(sessions) as session:
            page = (
                await session.exec(
                    select(ResourcePermissionMode)
                    .join(
                        PermissionProjectionOperation,
                        PermissionProjectionOperation.id == ResourcePermissionMode.operation_id,
                    )
                    .where(
                        ResourcePermissionMode.id > cursor,
                        ResourcePermissionMode.resource_type == "linsight_skill",
                        ResourcePermissionMode.projection_state == "FAILED_CLOSED",
                        PermissionProjectionOperation.operation_type == "RESOURCE_CREATE",
                        PermissionProjectionOperation.status.in_(("FAILED_CLOSED", "COMMITTED")),
                    )
                    .order_by(ResourcePermissionMode.id)
                    .limit(200)
                )
            ).all()
            modes = [canonical(row.model_dump()) for row in page]
        for mode in modes:
            with tenant_execution_scope(mode["tenant_id"]):
                _, fact = await builtin_finalization_fact(sessions, service, mode, pin)
                result.append(fact)
        if len(modes) < 200:
            return result
        cursor = modes[-1]["id"]


async def apply_builtin_finalizations(plan, *, sessions, runtime):
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.knowledge.domain.repositories.unification_history_repository import blocked

    receipts = []
    # Validate all selected intents before the first native finalizer.
    for apply in (False, True):
        for item in plan.get("builtin_finalizations", ()):
            with tenant_execution_scope(item["mode"]["tenant_id"]):
                operation, actual = await builtin_finalization_fact(
                    sessions, runtime._projection, item["mode"], plan["pin"]
                )
                if any(actual[key] != item[key] for key in ("ledger", "business_digest")):
                    blocked("builtin_finalization_evidence_changed")
                if operation.status != "FINALIZED" and actual != item:
                    blocked("builtin_finalization_preview_changed")
                if apply:
                    if operation.status != "FINALIZED":
                        await runtime._projection.recover_failed_closed_operation(
                            operation.id, confirmation_checksum=actual["preview"]["confirmation_checksum"]
                        )
                        operation, _ = await builtin_finalization_fact(
                            sessions, runtime._projection, item["mode"], plan["pin"]
                        )
                    if operation.status != "FINALIZED":
                        blocked("builtin_finalization_not_completed")
                    receipts.append(operation.id)
    return receipts
