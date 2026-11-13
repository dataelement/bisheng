"""Prepare historical depth/permission mirrors before freezing F118 M2.

Run from src/backend with the service's config and ALL writers/consumers stopped.
Preview saves a private, checksummed selected-row backup/plan (no SQL/FGA writes)::

    python scripts/prepare_f118_history.py --plan /secure/f118-history.json
    python scripts/prepare_f118_history.py --plan /secure/f118-history.json --apply --operator-id 1

Apply/resume always reads that same plan. Repairs only valid SQL folder chains'
level counters, removes redundant FGA parents when the correct parent already
exists, and purges derived permissions of hard-deleted resources with no live
downstream. Keeps operation/tuple audit, role data, index bindings, MinIO, ES and
Milvus untouched. Unknown types or ambiguous/missing parents are reported, never
guessed. Run BEFORE a new M2 freeze; an active frozen migration is rejected.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def blocked(reason):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

    raise KnowledgeOperationPlanConflictError(reason="history_prepare_" + reason)


def canonical(value):
    return json.loads(json.dumps(value, default=lambda item: item.isoformat(), sort_keys=True, allow_nan=False))


def checksum(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def save_plan(path, plan):
    payload = {"plan": plan, "sha256": checksum(plan)}
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    saved = load_plan(path)
    if saved != plan:
        blocked("backup_verification_failed")
    return payload["sha256"]


def load_plan(path):
    payload = json.loads(path.read_text())
    if (
        set(payload) != {"plan", "sha256"}
        or checksum(payload["plan"]) != payload["sha256"]
        or payload["plan"].get("schema") != 1
    ):
        blocked("backup_verification_failed")
    return payload["plan"]


def record_event(path, event):
    from datetime import UTC, datetime

    filename = path.with_name(path.name + ".events.jsonl")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW
    with os.fdopen(os.open(filename, flags, 0o600), "a", encoding="utf-8") as file:
        file.write(json.dumps({"time": datetime.now(UTC).isoformat(), **event}, ensure_ascii=False) + "\n")
        file.flush()
        os.fsync(file.fileno())


def folder_path(value):
    if value in (None, ""):
        return ()
    if type(value) is not str or re.fullmatch(r"(?:/[1-9][0-9]*)+", value) is None:
        raise ValueError("noncanonical folder path")
    ids = tuple(map(int, value[1:].split("/")))
    if len(set(ids)) != len(ids):
        raise ValueError("cyclic folder path")
    return ids


@asynccontextmanager
async def global_session(sessions):
    from bisheng.core.context.tenant import bypass_tenant_filter

    with bypass_tenant_filter():
        async with sessions() as session, session.begin():
            yield session


def valid_chain(row, files, spaces):
    path = folder_path(row["file_level_path"])
    root = spaces.get(row["knowledge_id"])
    if (
        root is None
        or type(row["tenant_id"]) is not int
        or row["tenant_id"] <= 0
        or root["tenant_id"] != row["tenant_id"]
    ):
        raise ValueError("missing or foreign knowledge root")
    if root["type"] not in {0, 1, 2, 3} or ("file_type" in row and row["file_type"] not in {0, 1}):
        raise ValueError("unknown knowledge type")
    for index, ident in enumerate(path):
        ancestor = files.get(ident)
        if (
            ancestor is None
            or ancestor["file_type"] != 0
            or ancestor["tenant_id"] != row["tenant_id"]
            or ancestor["knowledge_id"] != row["knowledge_id"]
            or folder_path(ancestor["file_level_path"]) != path[:index]
        ):
            raise ValueError("missing or inconsistent folder ancestor")
    return path


async def read_pin(session):
    from sqlmodel import select

    from bisheng.permission.domain.models import AuthorizationModelRelease, PermissionCatalogRelease

    rows = (
        await session.exec(
            select(PermissionCatalogRelease, AuthorizationModelRelease)
            .join(
                AuthorizationModelRelease,
                AuthorizationModelRelease.id == PermissionCatalogRelease.required_authorization_model_release_id,
            )
            .where(PermissionCatalogRelease.status == "CURRENT")
        )
    ).all()
    if len(rows) != 1:
        blocked("unique_catalog_required")
    catalog, auth = rows[0]
    if catalog.write_fenced or auth.status != "ACTIVE":
        blocked("catalog_not_writable")
    return {
        "release_id": catalog.id,
        "checksum": catalog.checksum,
        "store_id": auth.store_id,
        "model_id": auth.model_id,
        "model_checksum": auth.model_checksum,
    }


async def unfrozen(session):
    from sqlmodel import select

    from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun

    rows = (
        await session.exec(
            select(KnowledgeUnificationRun.baseline_hash, KnowledgeUnificationRun.baseline_ref).where(
                KnowledgeUnificationRun.phase != "completed"
            )
        )
    ).all()
    if any(baseline_hash or baseline_ref for baseline_hash, baseline_ref in rows):
        blocked("active_frozen_run_requires_original_continuation")


def business_models():
    # Composition belongs to scripts. Permission repositories never infer
    # business existence by importing these owners' tables. Keep each owner's
    # ID parser explicit: SQLModel AutoString does not expose python_type.
    from bisheng.channel.domain.models.channel import Channel
    from bisheng.database.models.app import App
    from bisheng.database.models.assistant import Assistant
    from bisheng.database.models.flow import Flow
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.telemetry_search.domain.models.dashboard import Dashboard
    from bisheng.tool.domain.models.gpts_tools import GptsToolsType

    return {
        "knowledge_library": (Knowledge, int),
        "knowledge_space": (Knowledge, int),
        "folder": (KnowledgeFile, int),
        "knowledge_file": (KnowledgeFile, int),
        "workflow": (Flow, str),
        "assistant": (Assistant, str),
        "channel": (Channel, str),
        "tool": (GptsToolsType, int),
        "dashboard": (Dashboard, int),
        "app": (App, str),
    }


async def hard_missing(session, target):
    from sqlmodel import select

    owner = business_models().get(target["resource_type"])
    if owner is None:
        return False
    model, parse_id = owner
    raw_id = target["resource_id"]
    if type(raw_id) is not str or not raw_id:
        return False
    # IDs are global within each owning table. An existing foreign tenant/type
    # or converted knowledge namespace is preserved, never mistaken for absent.
    try:
        ident = parse_id(raw_id)
    except (TypeError, ValueError):
        return False
    return (await session.exec(select(model.id).where(model.id == ident).limit(1))).first() is None


async def downstream(session, target, *, ignored_modes=()):
    from sqlalchemy import or_
    from sqlmodel import select

    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.permission.domain.models import ResourcePermissionMode
    from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference

    kind, ident = target["resource_type"], target["resource_id"]
    # Conservative: even a dangling registered reference/child stops cleanup.
    query = select(ResourcePermissionMode.id).where(
        ResourcePermissionMode.parent_type == kind, ResourcePermissionMode.parent_id == ident
    )
    if ignored_modes:
        query = query.where(ResourcePermissionMode.id.not_in(tuple(ignored_modes)))
    if (await session.exec(query.limit(1))).first() is not None:
        return True
    if kind in {"knowledge_space", "knowledge_library"}:
        if (
            await session.exec(select(KnowledgeFile.id).where(KnowledgeFile.knowledge_id == int(ident)).limit(1))
        ).first() is not None:
            return True
    if kind in {"knowledge_space", "knowledge_library", "knowledge_file"}:
        mapped = "knowledge_space" if kind == "knowledge_library" else kind
        query = (
            select(BusinessResourceReference.id)
            .where(
                or_(BusinessResourceReference.target_type == mapped, BusinessResourceReference.target_type == kind),
                BusinessResourceReference.target_id == ident,
            )
            .limit(1)
        )
        if (await session.exec(query)).first() is not None:
            return True
    return False


async def mirrors(session, target):
    from sqlmodel import select

    from bisheng.permission.application.sql_runtime import stable_grant_key
    from bisheng.permission.domain.models import (
        PermissionGrant,
        PermissionGrantAssignee,
        PermissionVisibleSourceProjection,
        ResourcePermissionMode,
    )

    result, grants = {}, []
    for model in (ResourcePermissionMode, PermissionGrant, PermissionVisibleSourceProjection):
        rows = (
            await session.exec(
                select(model)
                .where(
                    model.tenant_id == target["tenant_id"],
                    model.resource_type == target["resource_type"],
                    model.resource_id == target["resource_id"],
                )
                .order_by(model.id)
            )
        ).all()
        result[model.__tablename__] = [canonical(row.model_dump()) for row in rows]
        if model is PermissionGrant:
            grants = rows
    ids = tuple(grant.id for grant in grants)
    rows = (
        (
            await session.exec(
                select(PermissionGrantAssignee)
                .where(PermissionGrantAssignee.grant_id.in_(ids))
                .order_by(PermissionGrantAssignee.id)
            )
        ).all()
        if ids
        else []
    )
    result[PermissionGrantAssignee.__tablename__] = [canonical(row.model_dump()) for row in rows]
    objects = (
        f"{target['resource_type']}:{target['resource_id']}",
        *(
            "permission_grant:"
            + stable_grant_key(
                tenant_id=target["tenant_id"],
                resource_type=target["resource_type"],
                resource_id=target["resource_id"],
                model_key=grant.model_key,
            )
            for grant in grants
        ),
    )
    return result, objects


async def capture(sessions, client):
    from sqlmodel import select

    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.permission.domain.models import ResourcePermissionMode

    async with global_session(sessions) as session:
        await unfrozen(session)
        result = {
            "schema": 1,
            "pin": await read_pin(session),
            "levels": [],
            "parents": [],
            "purges": [],
            "blocked": [],
            "retained_evidence": [],
        }
        roots = {row.id: canonical(row.model_dump()) for row in (await session.exec(select(Knowledge))).all()}
        files = {row.id: canonical(row.model_dump()) for row in (await session.exec(select(KnowledgeFile))).all()}
        modes = (await session.exec(select(ResourcePermissionMode).order_by(ResourcePermissionMode.id))).all()
        mode_map = {(row.resource_type, row.resource_id): row for row in modes}
        for model, rows in (
            (KnowledgeFile, files.values()),
            (
                KnowledgeDocument,
                (canonical(row.model_dump()) for row in (await session.exec(select(KnowledgeDocument))).all()),
            ),
        ):
            for row in rows:
                if model is KnowledgeDocument:
                    # Ownership comes from Knowledge; documents have no tenant column.
                    row["tenant_id"] = roots.get(row["knowledge_id"], {}).get("tenant_id")
                try:
                    path = valid_chain(row, files, roots)
                    if model is KnowledgeFile and row["id"] in path:
                        raise ValueError("self parent")
                except ValueError:
                    result["retained_evidence"].append(
                        {"reason": "invalid_parent_chain", "table": model.__tablename__, "row": row}
                    )
                    result["blocked"].append(
                        {"table": model.__tablename__, "id": row["id"], "reason": "invalid_parent_chain"}
                    )
                    continue
                if row["level"] != len(path):
                    result["levels"].append(
                        {
                            "table": model.__tablename__,
                            "before": row,
                            "after_level": len(path),
                            "ancestors": [files[ident] for ident in path],
                            "root": roots[row["knowledge_id"]],
                        }
                    )
                if model is not KnowledgeFile:
                    continue
                kind = "folder" if row["file_type"] == 0 else "knowledge_file"
                mode = mode_map.get((kind, str(row["id"])))
                root_kind = "knowledge_space" if roots[row["knowledge_id"]]["type"] == 3 else "knowledge_library"
                parent = ("folder", str(path[-1])) if path else (root_kind, str(row["knowledge_id"]))
                if (
                    mode is None
                    or mode.tenant_id != row["tenant_id"]
                    or mode.projection_state != "CURRENT"
                    or (mode.parent_type, mode.parent_id) != parent
                ):
                    reason = "permission_mode_missing" if mode is None else "permission_mode_parent_or_state_mismatch"
                    result["blocked"].append({"table": model.__tablename__, "id": row["id"], "reason": reason})
                    result["retained_evidence"].append(
                        {"reason": reason, "row": row, "mode": canonical(mode.model_dump()) if mode else None}
                    )
                    continue
                obj = f"{kind}:{row['id']}"
                correct = (f"{parent[0]}:{parent[1]}", "parent", obj)
                result["parents"].append({"before_file": row, "mode": canonical(mode.model_dump()), "correct": correct})
        mode_links = [(mode.id, mode.parent_type, mode.parent_id) for mode in modes]
        pending, ordered = [], set()
        for mode in modes:
            target = canonical(mode.model_dump())
            if mode.projection_state == "CURRENT" and await hard_missing(session, target):
                sql, objects = await mirrors(session, target)
                pending.append({"mode": target, "sql": sql, "objects": objects})
        # Schedule a deleted tree from its leaves. Ignore only children already
        # proven eligible and earlier in this same immutable cleanup plan.
        while pending:
            previous = len(pending)
            for item in tuple(pending):
                target = item["mode"]
                if any(row["tenant_id"] != target["tenant_id"] for row in item["sql"]["permission_grant_assignee"]):
                    result["retained_evidence"].append({"reason": "foreign_assignee", **item})
                    result["blocked"].append(
                        {"table": "resource_permission_mode", "id": target["id"], "reason": "foreign_assignee"}
                    )
                    pending.remove(item)
                elif not await downstream(session, target, ignored_modes=ordered):
                    result["purges"].append(item)
                    ordered.add(target["id"])
                    pending.remove(item)
            if len(pending) == previous:
                for item in pending:
                    result["retained_evidence"].append({"reason": "downstream_exists", **item})
                    result["blocked"].append(
                        {"table": "resource_permission_mode", "id": item["mode"]["id"], "reason": "downstream_exists"}
                    )
                break
    # One offline Store walk; retain only relevant parent/owned-object keys.
    # External IO never holds a business SQL session.
    parents = {item["correct"][2] for item in result["parents"]}
    owned = {obj for item in (*result["purges"], *result["retained_evidence"]) for obj in item.get("objects", ())}
    keys_by_object, incoming = {}, []
    async for row in client.iter_tuples(consistency="HIGHER_CONSISTENCY"):
        if row["object"] in owned or (row["object"] in parents and row["relation"] == "parent"):
            keys_by_object.setdefault(row["object"], []).append(row)
        if row["user"].partition("#")[0] in owned:
            incoming.append((row["user"], row["relation"], row["object"]))
    selected = []
    for item in result["parents"]:
        present = {(raw["user"], raw["relation"], raw["object"]) for raw in keys_by_object.get(item["correct"][2], ())}
        extras = sorted(present - {item["correct"]})
        if extras and item["correct"] in present:
            selected.append({**item, "deletes": extras})
        elif item["correct"] not in present:
            result["retained_evidence"].append(
                {
                    "reason": "canonical_parent_tuple_missing",
                    **item,
                    "tuples": keys_by_object.get(item["correct"][2], []),
                }
            )
            result["blocked"].append(
                {
                    "table": "resource_permission_mode",
                    "id": item["mode"]["id"],
                    "reason": "canonical_parent_tuple_missing",
                }
            )
    result["parents"] = selected
    parent_deletes = {tuple(key) for item in selected for key in item["deletes"]}
    # A graph edge to a live/unknown external object is a real downstream,
    # even when its SQL parent mirror has disappeared. Do not infer it away.
    while True:
        active = {obj for item in result["purges"] for obj in item["objects"]}
        active_ids = {item["mode"]["id"] for item in result["purges"]}
        rejected = {
            item["mode"]["id"]
            for item in result["purges"]
            if any(
                key[0].partition("#")[0] in item["objects"] and key[2] not in active and key not in parent_deletes
                for key in incoming
            )
            or any(
                ident not in active_ids
                and (kind, parent_id) == (item["mode"]["resource_type"], item["mode"]["resource_id"])
                for ident, kind, parent_id in mode_links
            )
        }
        if not rejected:
            break
        result["retained_evidence"].extend(
            {"reason": "fga_downstream_exists", **item} for item in result["purges"] if item["mode"]["id"] in rejected
        )
        result["blocked"].extend(
            {"table": "resource_permission_mode", "id": ident, "reason": "fga_downstream_exists"}
            for ident in sorted(rejected)
        )
        result["purges"] = [item for item in result["purges"] if item["mode"]["id"] not in rejected]
    for item in result["purges"]:
        item["tuples"] = [row for obj in item["objects"] for row in keys_by_object.get(obj, ())]
        item["incoming"] = [key for key in incoming if key[0].partition("#")[0] in item["objects"]]
    for item in result["retained_evidence"]:
        if "objects" in item:
            item["tuples"] = [row for obj in item["objects"] for row in keys_by_object.get(obj, ())]
            item["incoming"] = [key for key in incoming if key[0].partition("#")[0] in item["objects"]]
    return canonical(result)


def target_for(mode, version=None):
    from bisheng.permission.domain.schemas import VerifiedPermissionTarget

    return VerifiedPermissionTarget.from_business_service(
        tenant_id=mode["tenant_id"],
        resource_type=mode["resource_type"],
        resource_id=mode["resource_id"],
        resource_version=mode["version"] if version is None else version,
        parent_type=mode["parent_type"],
        parent_id=mode["parent_id"],
        context_version="f118-history-preparation-v1",
    )


async def require_chain(session, row):
    from sqlmodel import select

    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

    root = (
        await session.exec(
            select(Knowledge).where(Knowledge.id == row["knowledge_id"], Knowledge.tenant_id == row["tenant_id"])
        )
    ).one_or_none()
    path = folder_path(row["file_level_path"])
    rows = (
        (
            await session.exec(
                select(KnowledgeFile).where(KnowledgeFile.id.in_(path), KnowledgeFile.tenant_id == row["tenant_id"])
            )
        ).all()
        if path
        else []
    )
    try:
        valid_chain(
            row,
            {item.id: canonical(item.model_dump()) for item in rows},
            {root.id: canonical(root.model_dump())} if root else {},
        )
    except ValueError:
        blocked("ancestor_or_root_changed")


def stable_mirrors(rows):
    return {
        name: [
            {
                key: value
                for key, value in row.items()
                if key
                not in (
                    {"operation_id", "version", "projection_state", "update_time"}
                    if name == "resource_permission_mode"
                    else {"update_time"}
                )
            }
            for row in values
        ]
        for name, values in rows.items()
    }


def level_scope(model, before):
    from sqlmodel import select

    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

    owner = (
        model.tenant_id == before["tenant_id"]
        if model is KnowledgeFile
        else model.knowledge_id.in_(
            select(Knowledge.id).where(
                Knowledge.id == before["knowledge_id"], Knowledge.tenant_id == before["tenant_id"]
            )
        )
    )
    return (model.id == before["id"], model.knowledge_id == before["knowledge_id"], owner)


async def apply(plan, *, sessions, client, runtime, operator_id):
    from dataclasses import replace

    from sqlmodel import select, update

    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.permission.application.deleted_resource_cleanup import DeletedResourceCleanup
    from bisheng.permission.domain.repositories.deleted_resource_repository import DeletedResourceRepository
    from bisheng.permission.domain.services.permission_action_service import PermissionActor
    from bisheng.permission.domain.services.projection_plan import ProjectionTupleDelta
    from bisheng.permission.domain.services.resource_lifecycle_policy import build_delete_plan

    async with global_session(sessions) as session:
        await unfrozen(session)
        if await read_pin(session) != plan["pin"]:
            blocked("catalog_pin_changed")
    owned = {obj for item in plan["purges"] for obj in item["objects"]}
    expected_incoming = {tuple(key) for item in plan["purges"] for key in item["incoming"]}
    if owned:
        async for row in client.iter_tuples(consistency="HIGHER_CONSISTENCY"):
            if (
                row["user"].partition("#")[0] in owned
                and (row["user"], row["relation"], row["object"]) not in expected_incoming
            ):
                blocked("purge_downstream_graph_changed")
    identity, receipts = checksum(plan)[:32], []
    for item in plan["parents"]:
        mode = item["mode"]
        with tenant_execution_scope(mode["tenant_id"]):
            async with sessions() as session, session.begin():
                current = await session.get(KnowledgeFile, item["before_file"]["id"])
                if current is None or any(
                    getattr(current, key) != item["before_file"][key]
                    for key in ("tenant_id", "knowledge_id", "file_type", "file_level_path")
                ):
                    blocked("parent_business_changed")
                await require_chain(session, item["before_file"])
            keys = await client.read_tuples(
                object=f"{mode['resource_type']}:{mode['resource_id']}",
                relation="parent",
                consistency="HIGHER_CONSISTENCY",
            )
            present = {(row["user"], row["relation"], row["object"]) for row in keys}
            if tuple(item["correct"]) not in present or present - {
                tuple(item["correct"]),
                *(tuple(key) for key in item["deletes"]),
            }:
                blocked("parent_graph_changed")
            target = target_for(mode)
            base = build_delete_plan(
                target,
                store_id=plan["pin"]["store_id"],
                model_id=plan["pin"]["model_id"],
                operator_id=operator_id,
                idempotency_key=f"history-parent:{identity}:{mode['id']}",
            )
            count = len(item["deletes"])
            repair = replace(
                base,
                operation_type="HISTORICAL_PARENT_REPAIR",
                deltas=tuple(
                    ProjectionTupleDelta("STAGE" if index < count - 90 else "COMMIT", index, "DELETE", *key)
                    for index, key in enumerate(item["deletes"])
                ),
            )
            operation = await runtime._projection.prepare(repair)
            if operation.status == "PREPARED":
                await runtime._state.mark_projecting(
                    target=target, operation_id=operation.id, expected_catalog_release_id=plan["pin"]["release_id"]
                )
            outcome = await runtime._projection.execute(repair)
            receipts.append(outcome.operation_id)
            after = await client.read_tuples(
                object=item["correct"][2], relation="parent", consistency="HIGHER_CONSISTENCY"
            )
            if {(row["user"], row["relation"], row["object"]) for row in after} != {tuple(item["correct"])}:
                blocked("parent_graph_not_repaired")
    for item in plan["purges"]:
        mode = item["mode"]
        with tenant_execution_scope(mode["tenant_id"]):
            target, actor = target_for(mode), PermissionActor(user_id=operator_id, current_tenant_id=mode["tenant_id"])
            key = f"history-delete:{identity}:{mode['id']}"
            repository = DeletedResourceRepository(sessions)
            existing = await repository.aget_operation_by_idempotency(key)
            async with global_session(sessions) as session:
                if not await hard_missing(session, mode) or await downstream(session, mode):
                    blocked("purge_business_or_downstream_changed")
                current, _ = await mirrors(session, mode)
                if current["resource_permission_mode"] and stable_mirrors(current) != stable_mirrors(item["sql"]):
                    blocked("purge_mirrors_changed")
                if existing is None and current != item["sql"]:
                    blocked("purge_fence_changed")
            actual = []
            for obj in item["objects"]:
                actual.extend(await client.read_tuples(object=obj, consistency="HIGHER_CONSISTENCY"))

            def keys(rows):
                return {(row["user"], row["relation"], row["object"]) for row in rows}

            if keys(actual) - keys(item["tuples"]) or (existing is None and keys(actual) != keys(item["tuples"])):
                blocked("purge_graph_changed")
            outcome = await runtime.project_delete(actor=actor, target=target, idempotency_key=key)
            receipts.append(outcome.operation_id)
            await DeletedResourceCleanup(runtime, repository=repository).run(
                actor=actor, target=target, delete_idempotency_key=key
            )
            purge = await repository.aget_operation_by_idempotency(f"resource-purge:{outcome.operation_id}")
            if purge is not None:
                receipts.append(purge.id)
    tables = {model.__tablename__: model for model in (KnowledgeFile, KnowledgeDocument)}
    for item in plan["levels"]:
        model, before = tables[item["table"]], item["before"]
        with tenant_execution_scope(before["tenant_id"]):
            async with sessions() as session, session.begin():
                row = (
                    await session.exec(select(model).where(*level_scope(model, before)).with_for_update())
                ).one_or_none()
                if row is None:
                    blocked("level_row_missing")
                await require_chain(session, before)
                current = canonical(row.model_dump())
                if model is KnowledgeDocument:
                    current["tenant_id"] = before["tenant_id"]
                if any(
                    current[key] != value for key, value in before.items() if key not in {"level", "update_time"}
                ) or current["level"] not in {before["level"], item["after_level"]}:
                    blocked("level_row_changed")
                if row.level != item["after_level"]:
                    await session.exec(
                        update(model)
                        .where(*level_scope(model, before), model.level == before["level"])
                        .values(level=item["after_level"])
                    )
    return {
        "levels": len(plan["levels"]),
        "parents": len(plan["parents"]),
        "purges": len(plan["purges"]),
        "blocked": plan["blocked"],
        "permission_operation_ids": receipts,
        "preparation_complete": not plan["blocked"],
    }


async def arun(args):
    from contextlib import AsyncExitStack

    from bisheng.common.services.config_service import settings
    from bisheng.core.cache.redis_manager import RedisManager
    from bisheng.core.context.manager import app_context
    from bisheng.core.database import get_async_db_session
    from bisheng.core.database.manager import DatabaseManager
    from bisheng.core.openfga.client import FGAClient
    from bisheng.core.openfga.discovery import discover_openfga_runtime
    from bisheng.permission.application.control_state import SqlPermissionControlState
    from bisheng.permission.application.runtime import F048PermissionRuntime
    from bisheng.permission.application.sql_runtime import build_sql_projection_runtime
    from bisheng.permission.domain.services.projection_service import ProjectionService

    # Own DB/Redis and a read-pinned FGA transport, like the formal F118 CLI;
    # never initialize storage/RAG clients that could change physical stores.
    async with AsyncExitStack() as stack:
        if (
            not settings.openfga.enabled
            or settings.openfga.force_write_model
            or settings.openfga.dual_model_mode
            or settings.openfga.legacy_model_id
        ):
            blocked("read_pinned_fga_configuration_required")
        database = DatabaseManager(
            database_url=settings.database_url, engine_config=settings.database_pool.as_engine_kwargs()
        )
        app_context.register_context(database)
        stack.push_async_callback(database.async_close)
        await app_context.async_get_instance(DatabaseManager.name)
        async with global_session(get_async_db_session) as session:
            pin = await read_pin(session)
        actual = await discover_openfga_runtime(
            settings.openfga,
            expected_model=None,
            allow_bootstrap=False,
            required_store_id=pin["store_id"],
            required_model_id=pin["model_id"],
        )
        if actual.model_checksum != pin["model_checksum"]:
            blocked("physical_pin_changed")
        client = FGAClient(
            api_url=settings.openfga.api_url,
            store_id=pin["store_id"],
            model_id=pin["model_id"],
            timeout=settings.openfga.timeout,
        )
        stack.push_async_callback(client.close)
        if not args.apply:
            plan = await capture(get_async_db_session, client)
            saved_checksum = save_plan(args.plan, plan)
            return {
                "mode": "preview",
                "plan": str(args.plan),
                "sha256": saved_checksum,
                **{key: len(plan[key]) for key in ("levels", "parents", "purges")},
                "blocked": plan["blocked"],
            }
        plan = load_plan(args.plan)
        if plan["pin"] != pin:
            blocked("backup_or_pin_changed")
        redis = RedisManager(redis_url=settings.redis_url)
        app_context.register_context(redis)
        stack.push_async_callback(redis.async_close)
        await app_context.async_get_instance(RedisManager.name)
        components = await build_sql_projection_runtime(client)

        class MaintenanceState(SqlPermissionControlState):
            async def current_catalog(self):
                async with global_session(get_async_db_session) as session:
                    current = await read_pin(session)
                if current != pin:
                    blocked("catalog_pin_changed")
                # No action/model reinterpretation before the new model is
                # published. This maintenance facade exposes no business check.
                return SimpleNamespace(**current)

        runtime = F048PermissionRuntime(
            client=client,
            state=MaintenanceState(),
            marker=components.marker,
            decision=None,
            projection=ProjectionService(
                **{
                    name: getattr(components, name)
                    for name in ("repository", "marker", "scope_guard", "fga", "finalizer")
                }
            ),
            sources=None,
            owner=None,
            grants=None,
            modes=None,
            explain=None,
        )
        return {
            "mode": "apply",
            "sha256": checksum(plan),
            **await apply(
                plan, sessions=get_async_db_session, client=client, runtime=runtime, operator_id=args.operator_id
            ),
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--operator-id", type=int)
    args = parser.parse_args(argv)
    if args.apply and (args.operator_id is None or args.operator_id <= 0):
        parser.error("--apply requires a positive --operator-id")
    try:
        if args.apply:
            record_event(args.plan, {"event": "apply_start", "operator_id": args.operator_id})
        result = asyncio.run(arun(args))
        if args.apply:
            record_event(args.plan, {"event": "apply_complete", "operator_id": args.operator_id, **result})
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        # Do not expose configuration/provider exception text or backup rows.
        failure = {
            "error_type": type(error).__name__,
            "reason": getattr(error, "kwargs", {}).get("reason"),
            "resume_same_plan": True,
        }
        if args.apply:
            try:
                record_event(args.plan, {"event": "apply_failed", **failure})
            except OSError as journal_error:
                failure["event_journal_error"] = type(journal_error).__name__
        print(json.dumps(failure), file=sys.stderr)
        return 3
    return 2 if args.apply and result["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
