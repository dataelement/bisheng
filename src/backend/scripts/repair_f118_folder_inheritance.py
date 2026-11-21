"""Explicitly initialize inherited permission modes for selected legacy folders.

Run from src/backend with all writers/consumers stopped, BEFORE M2 freezes.
This requires an operator's explicit decision that these folders inherit their
canonical parent. It never infers creator grants, adds people/roles, edits file
rows, or touches retired PRIVATE libraries. Preview creates a new private plan::

    python scripts/repair_f118_folder_inheritance.py --plan /secure/folders.json \
      --tenant-id 1 --knowledge-id 1509 --folder-id 86 --folder-id 87 --folder-id 88 --operator-id 1
    python scripts/repair_f118_folder_inheritance.py --plan /secure/folders.json --apply --confirm-inherit

Apply and retries use that original plan and the native projection journal.
Keep the original f118-history.json unchanged; this is a separate, selected
repair. After history apply finishes, capture a NEW history plan in a different
file to re-evaluate the original blocked items; never overwrite the old plan.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from scripts import prepare_f118_history as history  # noqa: E402


def require(condition, reason):
    if not condition:
        history.blocked("inherit_repair_" + reason)


async def scoped_rows(session, model, statement, limit):
    """Page the tenant-leading index without imposing a deployment tenant cap."""
    from sqlmodel import select

    rows, cursor = [], None
    while True:
        page = select(model.tenant_id).distinct().order_by(model.tenant_id).limit(200)
        if cursor is not None:
            page = page.where(model.tenant_id > cursor)
        ids = list((await session.exec(page)).all())
        require(all(type(ident) is int for ident in ids), "tenant_scope_identity")
        if not ids:
            return rows
        rows.extend((await session.exec(statement.where(model.tenant_id.in_(ids)).limit(limit - len(rows)))).all())
        if len(rows) >= limit or len(ids) < 200:
            return rows
        cursor = ids[-1]


async def facts(sessions, tenant_id, knowledge_id, folder_ids):
    """Bounded selected-row facts plus tenant-index enumeration, no write locks."""
    from sqlmodel import select

    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.permission.domain.models import (
        PermissionGrant,
        PermissionProjectionOperation,
        PermissionVisibleSourceProjection,
        ResourcePermissionMode,
    )

    require(0 < len(folder_ids) <= 20 and len(set(folder_ids)) == len(folder_ids), "selection")
    async with history.global_session(sessions) as session:
        await history.unfrozen(session)
        pin = await history.read_pin(session)
        root = (
            await session.exec(
                select(Knowledge.id, Knowledge.tenant_id, Knowledge.type).where(Knowledge.id == knowledge_id)
            )
        ).one_or_none()
        require(root is not None and root.tenant_id == tenant_id and root.type in {0, 3}, "active_root")
        selected = (
            await session.exec(
                select(KnowledgeFile.id, KnowledgeFile.file_level_path).where(KnowledgeFile.id.in_(folder_ids))
            )
        ).all()
        require(len(selected) == len(folder_ids), "missing_folder")
        ids = set(folder_ids)
        for row in selected:
            ids.update(history.folder_path(row.file_level_path))
        require(len(ids) <= 200, "ancestor_limit")
        columns = ("id", "tenant_id", "knowledge_id", "file_type", "file_level_path", "level")
        files = (
            await session.exec(
                select(*(getattr(KnowledgeFile, key) for key in columns)).where(KnowledgeFile.id.in_(sorted(ids)))
            )
        ).all()
        rows = {row.id: dict(row._mapping) for row in files}
        for ident in folder_ids:
            row = rows[ident]
            require(row["file_type"] == 0, "not_folder")
            path = history.valid_chain(row, rows, {root.id: dict(root._mapping)})
            require(ident not in path, "self_parent")
        root_kind = "knowledge_space" if root.type == 3 else "knowledge_library"
        scope_keys = {f"folder:{ident}" for ident in ids} | {f"{root_kind}:{root.id}"}
        # Scope IDs are globally unique. Foreign mirror/journal rows cannot be
        # hidden by a tenant filter or mistaken for an uninitialized folder.
        modes = await scoped_rows(
            session,
            ResourcePermissionMode,
            select(ResourcePermissionMode).where(
                (
                    (
                        (ResourcePermissionMode.resource_type == "folder")
                        & ResourcePermissionMode.resource_id.in_([str(i) for i in ids])
                    )
                    | (
                        (ResourcePermissionMode.resource_type == root_kind)
                        & (ResourcePermissionMode.resource_id == str(root.id))
                    )
                ),
            ),
            len(scope_keys) + 1,
        )
        mode_map = {f"{row.resource_type}:{row.resource_id}": history.canonical(row.model_dump()) for row in modes}
        require(len(mode_map) == len(modes) and all(row.tenant_id == tenant_id for row in modes), "foreign_mode")
        external = scope_keys - {f"folder:{ident}" for ident in folder_ids}
        require(
            all(key in mode_map and mode_map[key]["projection_state"] == "CURRENT" for key in external),
            "parent_not_current",
        )
        root_mode = mode_map.get(f"{root_kind}:{root.id}")
        require(
            root_mode is not None
            and root_mode["mode"] == "CUSTOM"
            and root_mode["version"] > 0
            and root_mode["parent_type"] is None
            and root_mode["parent_id"] is None,
            "root_mode",
        )
        for key in external - {f"{root_kind}:{root.id}"}:
            mode = mode_map[key]
            path = history.folder_path(rows[int(key.split(":", 1)[1])]["file_level_path"])
            parent = ("folder", str(path[-1])) if path else (root_kind, str(root.id))
            require(
                mode["mode"] in {"INHERIT", "CUSTOM"}
                and mode["version"] > 0
                and (mode["parent_type"], mode["parent_id"]) == parent,
                "parent_mode",
            )
        journals = await scoped_rows(
            session,
            PermissionProjectionOperation,
            select(PermissionProjectionOperation).where(
                PermissionProjectionOperation.scope_type == "resource",
                PermissionProjectionOperation.scope_key.in_([f"folder:{i}" for i in folder_ids]),
            ),
            len(folder_ids) + 1,
        )
        require(len(journals) <= len(folder_ids), "foreign_journal")
        for model in (PermissionGrant, PermissionVisibleSourceProjection):
            existing = await scoped_rows(
                session,
                model,
                select(model.id).where(
                    model.resource_type == "folder",
                    model.resource_id.in_([str(i) for i in folder_ids]),
                ),
                1,
            )
            require(not existing, "existing_authorization")
        mirrors = {
            ident: ([mode_map[f"folder:{ident}"]] if f"folder:{ident}" in mode_map else []) for ident in folder_ids
        }
    return {
        "pin": pin,
        "root": {"id": root.id, "tenant_id": root.tenant_id, "type": root.type},
        "files": {
            str(i): {
                key: rows[i][key]
                for key in ("id", "tenant_id", "knowledge_id", "file_type", "file_level_path", "level")
            }
            for i in sorted(ids)
        },
        "parents": {key: mode_map[key] for key in sorted(external)},
        "modes": mirrors,
        "journals": journals,
    }


async def tuples(client, obj):
    rows = []
    async for row in client.iter_tuples(object=obj, consistency="HIGHER_CONSISTENCY"):
        rows.append(row)
        require(len(rows) <= 500, "parent_tuple_limit")
    return sorted(history.canonical(rows), key=history.checksum)


def evidence(value):
    return {key: value[key] for key in ("pin", "root", "files", "parents")}


async def capture(*, sessions, client, tenant_id, knowledge_id, folder_ids, operator_id):
    require(tenant_id > 0 and knowledge_id > 0 and operator_id > 0 and all(i > 0 for i in folder_ids), "identity")
    value = await facts(sessions, tenant_id, knowledge_id, folder_ids)
    require(not value["journals"] and not any(value["modes"].values()), "existing_mode_or_journal")
    for ident in folder_ids:
        require(not await tuples(client, f"folder:{ident}"), "existing_folder_tuples")
    parent_tuples = {key: await tuples(client, key) for key in value["parents"]}
    return {
        "schema": 1,
        "purpose": "f118-folder-inherit",
        "tenant_id": tenant_id,
        "knowledge_id": knowledge_id,
        "operator_id": operator_id,
        "folder_ids": sorted(folder_ids),
        **evidence(value),
        "parent_tuples": parent_tuples,
    }


def projection_plan(plan, ident):
    from bisheng.permission.domain.services.resource_lifecycle_policy import build_create_plan

    row = plan["files"][str(ident)]
    path = history.folder_path(row["file_level_path"])
    mode = {
        "tenant_id": plan["tenant_id"],
        "resource_type": "folder",
        "resource_id": str(ident),
        "version": 0,
        "parent_type": "folder" if path else ("knowledge_space" if plan["root"]["type"] == 3 else "knowledge_library"),
        "parent_id": str(path[-1]) if path else str(plan["knowledge_id"]),
    }
    target = history.target_for(mode)
    compiled = build_create_plan(
        target,
        store_id=plan["pin"]["store_id"],
        model_id=plan["pin"]["model_id"],
        operator_id=plan["operator_id"],
        idempotency_key=f"history-inherit:{history.checksum(plan)[:32]}:{ident}",
        protected_deltas=(),
        permission_mode="INHERIT",
    )
    # This restores an explicitly approved legacy inheritance intent. It is not
    # a creator/system bootstrap and must not generate an owner or visible Grant.
    return target, replace(compiled, operation_type="HISTORICAL_INHERIT_REPAIR")


async def verify_folder(plan, folder, modes, journals, *, client, repository):
    from bisheng.permission.domain.services.projection_plan import (
        build_projection_operation,
        normalize_projection_plan,
        projection_request_checksum,
    )
    from bisheng.permission.domain.services.projection_service import restore_projection_plan

    target, expected = projection_plan(plan, folder)
    operation = next((op for op in journals if op.idempotency_key == expected.idempotency_key), None)
    require(not journals if operation is None else journals == [operation], "foreign_journal")
    actual = await tuples(client, expected.scope_key)
    if operation is None:
        require(not modes and not actual, "scope_already_initialized")
        return
    frozen = restore_projection_plan(operation, await repository.aget_operation_tuples(operation.id))
    normalized = normalize_projection_plan(expected)
    compiled, _ = build_projection_operation(normalized, request_checksum=projection_request_checksum(normalized))
    require(
        frozen == normalized
        and operation.before_checksum == compiled.before_checksum
        and operation.after_checksum == compiled.after_checksum,
        "ledger_changed",
    )
    if not modes and operation.status == "PREPARED":
        require(not actual, "unbound_prepared_graph")
        return
    require(
        len(modes) == 1 and modes[0]["operation_id"] == operation.id and modes[0]["version"] in {0, 1},
        "operation_fence_changed",
    )
    mode = modes[0]
    require(
        (mode["mode"], mode["parent_type"], mode["parent_id"]) == ("INHERIT", target.parent_type, target.parent_id),
        "inherit_intent_changed",
    )
    keys = {(row["user"], row["relation"], row["object"]) for row in actual}
    require(
        not keys - {delta.key for delta in expected.deltas} and all(not row.get("condition") for row in actual),
        "folder_graph_changed",
    )
    if operation.status == "FINALIZED":
        require(
            mode["version"] == 1
            and mode["projection_state"] == "CURRENT"
            and keys == {delta.key for delta in expected.deltas},
            "finalized_scope_changed",
        )


async def verify(plan, value, *, sessions, client):
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository

    require(
        value["pin"] == plan["pin"]
        and value["root"] == plan["root"]
        and all(row == plan["files"].get(ident) for ident, row in value["files"].items()),
        "business_or_pin_changed",
    )
    with tenant_execution_scope(plan["tenant_id"]):
        repository = ProjectionRepository(sessions)
        for key, mode in value["parents"].items():
            if key in plan["parents"]:
                require(
                    mode == plan["parents"][key] and await tuples(client, key) == plan["parent_tuples"][key],
                    "parent_graph_changed",
                )
            else:
                kind, ident = key.split(":", 1)
                require(kind == "folder" and int(ident) in plan["folder_ids"], "unplanned_parent")
                _, expected = projection_plan(plan, int(ident))
                operation = await repository.aget_operation_by_idempotency(expected.idempotency_key)
                require(operation is not None and operation.status == "FINALIZED", "parent_repair_incomplete")
                await verify_folder(plan, int(ident), [mode], [operation], client=client, repository=repository)
        for folder, modes in value["modes"].items():
            journals = [op for op in value["journals"] if op.scope_key == f"folder:{folder}"]
            await verify_folder(plan, folder, modes, journals, client=client, repository=repository)


async def apply(plan, *, sessions, client, projection, state):
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.permission.domain.services.owner_service import OwnerProjectionContext

    require(plan.get("purpose") == "f118-folder-inherit", "plan_purpose")
    receipts = []
    selected = plan["folder_ids"]
    ordered = sorted(selected, key=lambda i: (len(history.folder_path(plan["files"][str(i)]["file_level_path"])), i))
    # Full bounded preflight happens once. Each write rechecks only its own
    # folder/ancestor chain, rather than rescanning all selected siblings.
    value = await facts(sessions, plan["tenant_id"], plan["knowledge_id"], selected)
    await verify(plan, value, sessions=sessions, client=client)
    for ident in ordered:
        value = await facts(sessions, plan["tenant_id"], plan["knowledge_id"], [ident])
        await verify(plan, value, sessions=sessions, client=client)
        with tenant_execution_scope(plan["tenant_id"]):
            target, expected = projection_plan(plan, ident)
            operation = await projection.prepare(expected)
            if operation.status == "PREPARED":
                context = OwnerProjectionContext(
                    target=target,
                    owner_grant=None,
                    source_id=1,
                    owner_user_id=None,
                    system_owned=False,
                    system_predicate=False,
                    store_id=expected.store_id,
                    model_id=expected.model_id,
                    operator_id=plan["operator_id"],
                    idempotency_key=expected.idempotency_key,
                    permission_mode="INHERIT",
                    operation_type=expected.operation_type,
                )
                # Native control-state port creates a version-0 PENDING mirror
                # and claims the journal fence; no SQL status is forced CURRENT.
                await state.prepare_owner(context, None, None, None, operation_id=operation.id)
            if operation.status == "FAILED_CLOSED":
                preview = await projection.inspect_failed_closed_recovery(operation.id)
                require(
                    all(
                        delta.action == "WRITE" and delta.key in {row.key for row in expected.deltas}
                        for delta in preview.correction_deltas
                    ),
                    "recovery_changed",
                )
                outcome = await projection.recover_failed_closed_operation(
                    operation.id, confirmation_checksum=preview.confirmation_checksum
                )
            else:
                outcome = await projection.execute(expected)
            require(outcome.status == "FINALIZED", "not_finalized")
            actual = await tuples(client, expected.scope_key)
            require(
                {(row["user"], row["relation"], row["object"]) for row in actual}
                == {delta.key for delta in expected.deltas}
                and all(not row.get("condition") for row in actual),
                "after_state",
            )
            receipts.append(outcome.operation_id)
    return {"folder_ids": ordered, "permission_operation_ids": receipts, "ready": True}


async def arun(args):
    from bisheng.common.services.config_service import settings
    from bisheng.core.database import get_async_db_session
    from bisheng.permission.application.control_state import SqlPermissionControlState
    from scripts import f048_maintenance_runtime as maintenance

    try:
        await maintenance.initialize_maintenance_context(config=settings)
        client = await maintenance.maintenance_client()
        if not args.apply:
            require(all((args.tenant_id, args.knowledge_id, args.folder_id, args.operator_id)), "preview_arguments")
            plan = await capture(
                sessions=get_async_db_session,
                client=client,
                tenant_id=args.tenant_id,
                knowledge_id=args.knowledge_id,
                folder_ids=args.folder_id,
                operator_id=args.operator_id,
            )
            digest = history.save_plan(args.plan, plan)
            return {"apply": False, "sha256": digest, "folder_ids": plan["folder_ids"]}
        require(args.confirm_inherit, "explicit_inherit_confirmation")
        plan = history.load_plan(args.plan)
        for key, supplied in (
            ("tenant_id", args.tenant_id),
            ("knowledge_id", args.knowledge_id),
            ("operator_id", args.operator_id),
        ):
            require(supplied is None or supplied == plan[key], "original_identity_required")
        require(args.folder_id is None or sorted(args.folder_id) == plan["folder_ids"], "original_selection_required")
        runtime = await maintenance.build_maintenance_projection(client)
        return {
            "apply": True,
            **await apply(
                plan,
                sessions=get_async_db_session,
                client=client,
                projection=runtime.projection,
                state=SqlPermissionControlState(),
            ),
        }
    finally:
        await maintenance.close_maintenance_context()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--tenant-id", type=int)
    parser.add_argument("--knowledge-id", type=int)
    parser.add_argument("--folder-id", type=int, action="append")
    parser.add_argument("--operator-id", type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-inherit", action="store_true")
    args = parser.parse_args(argv)
    if args.apply and not args.confirm_inherit:
        parser.error("--apply requires --confirm-inherit after reviewing the saved plan")
    if not args.apply and not all((args.tenant_id, args.knowledge_id, args.folder_id, args.operator_id)):
        parser.error("preview requires --tenant-id, --knowledge-id, --folder-id and --operator-id")
    try:
        result = asyncio.run(arun(args))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "error_type": type(error).__name__,
                    "reason": getattr(error, "kwargs", {}).get("reason") or "inherit_repair_failed",
                    "resume_same_plan": True,
                }
            ),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    sys.exit(main())
