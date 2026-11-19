"""History helper: initialize a proven empty, unpermissioned NORMAL root closed.

Used only by prepare_f118_history.py. Preview freezes the unchanged business
row and absence of payload/SQL authorization/entire-Store edges. Apply creates
only a CUSTOM mode through the native owner-state port with no Grant, then
executes and checksum-recovers a native DELETE receipt. It never enables a
marker, changes a business row, or guesses an owner Grant. Use the owning CLI's
default preview/apply, or --projection-repairs-only after prior preparation.
"""

from sqlalchemy import String, and_, cast
from sqlmodel import select

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, QAKnowledge
from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionProjectionOperation,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.services.owner_service import OwnerProjectionContext
from bisheng.permission.domain.services.projection_service import restore_projection_plan
from bisheng.permission.domain.services.resource_lifecycle_policy import build_delete_plan


def require(ok, reason):
    if not ok:
        from scripts.prepare_f118_history import blocked

        blocked("empty_root_" + reason)


def mode_for(item):
    row = item["business"]
    return {
        "tenant_id": row["tenant_id"],
        "resource_type": "knowledge_library",
        "resource_id": str(row["id"]),
        "version": 0,
        "parent_type": None,
        "parent_id": None,
    }


def objects(items):
    return {f"{kind}:{item['business']['id']}" for item in items for kind in ("knowledge_library", "knowledge_space")}


async def fact(sessions, item, pin, *, operation=None):
    from scripts.prepare_f118_history import canonical, global_session, read_pin, unfrozen

    row = item["business"]
    ident = row["id"]
    ids = str(ident)
    async with global_session(sessions) as session:
        await unfrozen(session)
        require(await read_pin(session) == pin, "pin_changed")
        business = await session.get(Knowledge, ident)
        require(
            business is not None and canonical(business.model_dump()) == row and row["type"] == 0, "business_changed"
        )
        require(type(row["user_id"]) is int and row["user_id"] > 0, "creator_identity")
        for model in (KnowledgeFile, QAKnowledge, KnowledgeDocument):
            require(
                (await session.exec(select(model.id).where(model.knowledge_id == ident).limit(1))).first() is None,
                "payload_present",
            )
        for model in (ResourcePermissionMode, PermissionGrant, PermissionVisibleSourceProjection):
            rows = (
                await session.exec(
                    select(model)
                    .where(model.resource_type.in_(("knowledge_library", "knowledge_space")), model.resource_id == ids)
                    .limit(2)
                )
            ).all()
            if model is ResourcePermissionMode and operation is not None:
                if not rows and operation.status == "PREPARED":
                    continue
                require(len(rows) == 1, "reserved_mode_missing")
                current = rows[0]
                require(
                    current.tenant_id == row["tenant_id"]
                    and current.resource_type == "knowledge_library"
                    and current.mode == "CUSTOM"
                    and current.parent_type is None
                    and current.parent_id is None
                    and current.operation_id == operation.id
                    and (current.version, current.projection_state)
                    in {(0, "PROJECTING"), (0, "PENDING"), (0, "FAILED_CLOSED"), (1, "CURRENT")},
                    "reserved_fence_changed",
                )
                if operation.status == "FINALIZED":
                    require((current.version, current.projection_state) == (1, "CURRENT"), "final_fence_changed")
            else:
                require(not rows, "authorization_present")
        require(
            (
                await session.exec(
                    select(ResourcePermissionMode.id)
                    .where(
                        ResourcePermissionMode.parent_type.in_(("knowledge_library", "knowledge_space")),
                        ResourcePermissionMode.parent_id == ids,
                    )
                    .limit(1)
                )
            ).first()
            is None,
            "child_mode_present",
        )
        query = select(PermissionProjectionOperation.id).where(
            PermissionProjectionOperation.scope_type == "resource",
            PermissionProjectionOperation.scope_key.in_((f"knowledge_library:{ident}", f"knowledge_space:{ident}")),
        )
        if operation is not None:
            query = query.where(PermissionProjectionOperation.id != operation.id)
        require((await session.exec(query.limit(1))).first() is None, "operation_present")


async def candidates(sessions, pin):
    from scripts.prepare_f118_history import canonical, global_session

    result, cursor = [], 0
    while True:
        async with global_session(sessions) as session:
            rows = (
                await session.exec(
                    select(Knowledge)
                    .outerjoin(
                        ResourcePermissionMode,
                        and_(
                            ResourcePermissionMode.tenant_id == Knowledge.tenant_id,
                            ResourcePermissionMode.resource_type == "knowledge_library",
                            ResourcePermissionMode.resource_id == cast(Knowledge.id, String),
                        ),
                    )
                    .where(
                        Knowledge.id > cursor,
                        Knowledge.type == 0,
                        ResourcePermissionMode.id.is_(None),
                        ~select(KnowledgeFile.id).where(KnowledgeFile.knowledge_id == Knowledge.id).exists(),
                        ~select(QAKnowledge.id).where(QAKnowledge.knowledge_id == Knowledge.id).exists(),
                        ~select(KnowledgeDocument.id).where(KnowledgeDocument.knowledge_id == Knowledge.id).exists(),
                    )
                    .order_by(Knowledge.id)
                    .limit(200)
                )
            ).all()
            page = [
                {
                    "business": canonical(row.model_dump()),
                    "reason": "preserve_empty_original_root_with_closed_permissions",
                }
                for row in rows
            ]
        for item in page:
            await fact(sessions, item, pin)
            result.append(item)
        if len(page) < 200:
            return result
        cursor = page[-1]["business"]["id"]


async def no_graph(client, items):
    wanted = objects(items)
    if not wanted:
        return
    async for row in client.iter_tuples(consistency="HIGHER_CONSISTENCY"):
        require(row["object"] not in wanted and row["user"].partition("#")[0] not in wanted, "graph_present")


async def capture(sessions, client, pin):
    items = await candidates(sessions, pin)
    await no_graph(client, items)
    return items


async def apply(plan, *, sessions, client, runtime, operator_id):
    from bisheng.common.errcode.permission import PermissionProjectionFailedError
    from scripts.prepare_f118_history import checksum, target_for

    items = plan.get("empty_root_initializations", ())
    if not items:
        return []
    await no_graph(client, items)
    repository = ProjectionRepository(sessions)
    identity = checksum(plan)[:32]

    def expected(item):
        return build_delete_plan(
            target_for(mode_for(item)),
            store_id=plan["pin"]["store_id"],
            model_id=plan["pin"]["model_id"],
            operator_id=operator_id,
            idempotency_key=f"history-empty-root-closed:{identity}:{item['business']['id']}",
        )

    async def verify(item, projection):
        operation = await repository.aget_operation_by_idempotency(projection.idempotency_key)
        if operation is not None:
            require(
                restore_projection_plan(operation, await repository.aget_operation_tuples(operation.id)) == projection,
                "ledger_changed",
            )
        await fact(sessions, item, plan["pin"], operation=operation)
        return operation

    for item in items:
        with tenant_execution_scope(item["business"]["tenant_id"]):
            await verify(item, expected(item))
    receipts = []
    for item in items:
        with tenant_execution_scope(item["business"]["tenant_id"]):
            projection = expected(item)
            operation = await verify(item, projection)
            operation = await runtime._projection.prepare(projection)
            if operation.status == "PREPARED":
                context = OwnerProjectionContext(
                    target=target_for(mode_for(item)),
                    owner_grant=None,
                    source_id=0,
                    owner_user_id=item["business"]["user_id"],
                    system_owned=False,
                    system_predicate=False,
                    store_id=plan["pin"]["store_id"],
                    model_id=plan["pin"]["model_id"],
                    operator_id=operator_id,
                    idempotency_key=projection.idempotency_key,
                    permission_mode="CUSTOM",
                )
                await runtime._state.prepare_owner(context, None, None, None, operation_id=operation.id)
            try:
                if operation.status == "FAILED_CLOSED":
                    raise PermissionProjectionFailedError()
                outcome = await runtime._projection.execute(projection)
            except PermissionProjectionFailedError:
                operation = await repository.aget_operation_by_idempotency(projection.idempotency_key)
                require(operation.status == "FAILED_CLOSED", "not_recoverable")
                preview = await runtime._projection.inspect_failed_closed_recovery(operation.id)
                require(preview.observed_state == "AFTER" and not preview.correction_deltas, "not_empty_after")
                outcome = await runtime._projection.recover_failed_closed_operation(
                    operation.id, confirmation_checksum=preview.confirmation_checksum
                )
            require(outcome.status == "FINALIZED", "not_finalized")
            await verify(item, projection)
            require(
                not await client.read_tuples(object=projection.scope_key, consistency="HIGHER_CONSISTENCY"),
                "after_graph_changed",
            )
            receipts.append(outcome.operation_id)
    await no_graph(client, items)
    return receipts
