"""Native historical F118 facts and repairs, owned by maintenance applications.

The original script remains a compatibility CLI. SQL facts and mutations stay
here; applications consume capture/apply without importing executable scripts.
Original JSON schemas, checksums and idempotency identities remain unchanged.
"""

import json
import os
import re
from contextlib import asynccontextmanager
from hashlib import sha256
from types import SimpleNamespace

from bisheng.knowledge.domain.repositories.unification_history_snapshot import snapshot_scope


def blocked(reason, **details):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

    raise KnowledgeOperationPlanConflictError(reason="history_prepare_" + reason, **details)


def canonical(value):
    return json.loads(json.dumps(value, default=lambda item: item.isoformat(), sort_keys=True, allow_nan=False))


def checksum(value):
    digest = sha256()
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    for fragment in encoder.iterencode(value):
        digest.update(fragment.encode())
    return digest.hexdigest()


def save_private_history_backup(plan, directory):
    """Stream the original rollback evidence, without the shared-page limit."""
    import stat
    import tempfile
    from pathlib import Path

    directory = Path(directory)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        blocked("private_backup_directory_unsafe")
    identity = history_plan_identity(plan)
    target = directory / ("history-" + identity + ".json")
    descriptor, temporary = tempfile.mkstemp(prefix=".history-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            for fragment in json.JSONEncoder(ensure_ascii=False, sort_keys=True).iterencode(
                {"plan": plan, "sha256": identity}
            ):
                output.write(fragment)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(target, flags), "r", encoding="utf-8") as existing:
                info = os.fstat(existing.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                    blocked("private_backup_file_unsafe")
                stored = json.load(existing)
            if (
                set(stored) != {"plan", "sha256"}
                or stored["sha256"] != identity
                or checksum(stored["plan"]) != identity
            ):
                blocked("private_backup_identity_changed")
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return str(target)


class ReplayedHistoryPlan(dict):
    """Owner-issued materialization; its original idempotency identity is fixed."""

    def __init__(self, values, original_checksum):
        super().__init__(values)
        self.original_checksum = original_checksum


def history_plan_identity(plan):
    return plan.original_checksum if isinstance(plan, ReplayedHistoryPlan) else checksum(plan)


def build_replay_plan(plan):
    """Closed replay recipe: row hashes replace private business payloads."""
    if plan.get("business", {}).get("physical"):
        return {
            "schema_version": 1,
            "history_sha256": checksum(plan),
            "executable": False,
            "reason": "physical_replay_adapter_required",
        }
    value = dict(plan)
    for collection in ("levels", "parents", "initializations", "recoveries", "empty_root_initializations"):
        value[collection] = [dict(item) for item in plan.get(collection, ())]
    value["business"] = dict(plan.get("business", {}))
    for collection in ("updates", "deletes", "retained"):
        value["business"][collection] = [dict(item) for item in plan.get("business", {}).get(collection, ())]
    value["retained_evidence"] = []
    changes = {}
    for item in plan.get("business", {}).get("updates", ()):
        allowed = {
            "knowledgefile": {"tenant_id"},
            "flowversion": {"tenant_id"},
            "knowledge": {"model"},
            "tag": {"tenant_id"},
            "taglink": {"tenant_id"},
            "business_resource_reference": {"target_tenant_id"},
        }
        if set(item["values"]) - allowed.get(item["table"], set()):
            blocked("replay_unknown_business_change")
        if item["table"] == "knowledge" and item["values"] != {"model": None}:
            blocked("replay_unknown_model_change")
        changes[item["table"], item["before"]["id"]] = dict(item["values"])
    for item in plan.get("levels", ()):
        changes.setdefault((item["table"], item["before"]["id"]), {})["level"] = item["after_level"]

    def proof(table, row, *, minimal=False, absent=False):
        ignored = ("level", "update_time") if table in {"knowledgefile", "knowledge_document"} else ()

        def digest(record):
            return checksum({key: val for key, val in record.items() if key not in ignored})

        after = {**row, **changes.get((table, row["id"]), {})}
        identity = {key: row[key] for key in ("id", "file_type") if key in row}
        derived = {"tenant_id": row["tenant_id"]} if table == "knowledge_document" and "tenant_id" in row else {}
        return {
            "history_row": {
                "table": table,
                "identity": identity,
                "allowed": sorted({digest(row), digest(after)}),
                "ignore": list(ignored),
                "derived": derived,
                "minimal": minimal,
                "absent": absent,
            }
        }

    business = value.get("business", {})
    for collection in ("updates", "deletes", "retained"):
        for item in business.get(collection, ()):
            item["before"] = proof(item["table"], item["before"], minimal=True, absent=collection == "deletes")
    for item in value.get("levels", ()):
        item["before"] = proof(item["table"], item["before"])
        item["root"] = proof("knowledge", item["root"])
        item["ancestors"] = [proof("knowledgefile", row) for row in item["ancestors"]]
    for item in value.get("parents", ()):
        item["before_file"] = proof("knowledgefile", item["before_file"])
    for collection in ("initializations", "recoveries"):
        for item in value.get(collection, ()):
            item["file"] = proof("knowledgefile", item["file"])
            item["root"] = proof("knowledge", item["root"])
    for item in value.get("empty_root_initializations", ()):
        item["business"] = proof("knowledge", item["business"])
    result = {"schema_version": 1, "history_sha256": checksum(plan), "executable": True, "plan": value}
    result["replay_sha256"] = checksum(result)
    return result


@snapshot_scope
async def restore_replay_plan(replay, *, sessions, for_preview=False):
    from bisheng.knowledge.domain.repositories import unification_history_business as business

    if (
        type(replay) is not dict
        or set(replay) != {"schema_version", "history_sha256", "executable", "plan", "replay_sha256"}
        or replay["schema_version"] != 1
        or replay["executable"] is not True
        or checksum({key: val for key, val in replay.items() if key != "replay_sha256"}) != replay["replay_sha256"]
        or re.fullmatch(r"[0-9a-f]{64}", replay["history_sha256"]) is None
    ):
        blocked("replay_material_invalid")
    plan = replay["plan"]
    async with global_session(sessions) as session:
        snapshot = await business.read(session)
    expected = plan.get("business", {})
    actual = business.state_digest(snapshot)
    if expected and actual not in {expected["before_digest"], expected["after_digest"]}:
        blocked("replay_business_scope_changed")
    complete = bool(expected) and actual == expected["after_digest"]
    indexes = {table: business.row_index(rows) for table, rows in snapshot.items() if not table.startswith("_")}

    def materialize(value, path=()):
        if type(value) is list:
            return [materialize(item, (*path, index)) for index, item in enumerate(value)]
        if type(value) is not dict:
            return value
        if set(value) != {"history_row"}:
            return {key: materialize(item, (*path, key)) for key, item in value.items()}
        proof = value["history_row"]
        if set(proof) != {"table", "identity", "allowed", "ignore", "derived", "minimal", "absent"}:
            blocked("replay_row_proof_invalid")
        table, identity = proof["table"], proof["identity"]
        if table not in indexes or "id" not in identity:
            blocked("replay_row_identity_invalid")
        row = indexes[table].get(identity["id"])
        if row is None:
            if proof["minimal"] and proof["absent"] and complete:
                return identity
            blocked("replay_original_row_missing")
        row = {**row, **proof["derived"]}
        digest = checksum({key: val for key, val in row.items() if key not in proof["ignore"]})
        if digest not in proof["allowed"]:
            blocked("replay_row_changed")
        # Retained orphan rows are hash-validated but never copied into an
        # AFTER delta or a second full payload collection during recovery.
        return identity if proof["minimal"] and (not for_preview or path[:2] == ("business", "retained")) else row

    return ReplayedHistoryPlan(materialize(plan), replay["history_sha256"])


async def assert_history_after_facts(runtime, replay, semantics, operator_id):
    """Materialize only declared new identities and verify the native AFTER."""
    from collections import defaultdict

    from sqlalchemy import select

    from bisheng.knowledge.domain.repositories import unification_history_business as business
    from bisheng.permission.application.migration_history import (
        build_projection_operation,
        projection_request_checksum,
        restore_projection_plan,
    )
    from bisheng.permission.domain.models import (
        PermissionGrant,
        PermissionGrantAssignee,
        PermissionProjectionOperation,
        PermissionProjectionTuple,
        PermissionVisibleSourceProjection,
        ResourcePermissionMode,
    )
    from bisheng.permission.domain.services.projection_plan import (
        ProjectionPlan,
        ProjectionTupleDelta,
        normalize_projection_plan,
    )

    if (
        type(operator_id) is not int
        or operator_id <= 0
        or semantics.get("history_sha256") != replay.get("history_sha256")
    ):
        blocked("after_identity_changed")
    if semantics.get("operator_binding") == "fixed" and semantics["operator_id"] != operator_id:
        blocked("after_operator_changed")
    if replay.get("replay_sha256") != checksum({key: val for key, val in replay.items() if key != "replay_sha256"}):
        blocked("after_replay_changed")
    registry = {
        **business.models(),
        **{
            model.__tablename__: model
            for model in (
                PermissionProjectionOperation,
                PermissionProjectionTuple,
                ResourcePermissionMode,
                PermissionGrant,
                PermissionGrantAssignee,
                PermissionVisibleSourceProjection,
            )
        },
    }
    records = {(item["table"], item["id"]): item for item in semantics["rows"]}
    generated = {(item["table"], item["preview_id"]): item for item in semantics["logical_ids"]}
    mappings, operations, materialized_plans = {}, {}, {}

    async with global_session(runtime.sessions) as session:
        for item in semantics.get("projection_plans", ()):
            values = item["plan"]
            deltas = tuple(ProjectionTupleDelta(**row) for row in values["deltas"])
            key = values["idempotency_key"]
            if key.startswith("resource-purge:"):
                preview_id = int(key.removeprefix("resource-purge:"))
                if (PermissionProjectionOperation.__tablename__, preview_id) not in mappings:
                    blocked("after_operation_dependency_missing")
                key = "resource-purge:" + str(mappings[PermissionProjectionOperation.__tablename__, preview_id])
            expected_plan = normalize_projection_plan(
                ProjectionPlan(
                    **{
                        **values,
                        "deltas": deltas,
                        "idempotency_key": key,
                        "operator_id": operator_id
                        if semantics.get("operator_binding") == "apply_time"
                        else values["operator_id"],
                    }
                )
            )
            rows = tuple(
                (
                    await session.execute(
                        select(PermissionProjectionOperation).where(
                            PermissionProjectionOperation.tenant_id == expected_plan.tenant_id,
                            PermissionProjectionOperation.idempotency_key == key,
                        )
                    )
                ).scalars()
            )
            if len(rows) != 1:
                blocked("after_operation_missing_or_duplicated")
            actual = rows[0]
            tuples = tuple(
                (
                    await session.execute(
                        select(PermissionProjectionTuple)
                        .where(PermissionProjectionTuple.operation_id == actual.id)
                        .order_by(PermissionProjectionTuple.sequence)
                    )
                ).scalars()
            )
            if actual.status != "FINALIZED" or restore_projection_plan(actual, tuples) != expected_plan:
                blocked("after_operation_intent_changed")
            expected_op, _ = build_projection_operation(
                expected_plan, request_checksum=projection_request_checksum(expected_plan)
            )
            if (actual.before_checksum, actual.after_checksum) != (
                expected_op.before_checksum,
                expected_op.after_checksum,
            ):
                blocked("after_operation_checksums_changed")
            preview_id = item["preview_operation_id"]
            mappings[PermissionProjectionOperation.__tablename__, preview_id] = actual.id
            operations[actual.id] = (actual, tuples)
            materialized_plans[preview_id] = expected_op

        for family, preview_id in generated:
            if family == ResourcePermissionMode.__tablename__:
                fact = records[family, preview_id]["after_fact"]
                rows = tuple(
                    (
                        await session.execute(
                            select(ResourcePermissionMode).where(
                                ResourcePermissionMode.tenant_id == fact["tenant_id"],
                                ResourcePermissionMode.resource_type == fact["resource_type"],
                                ResourcePermissionMode.resource_id == fact["resource_id"],
                            )
                        )
                    ).scalars()
                )
                if len(rows) != 1:
                    blocked("after_mode_missing_or_duplicated")
                mappings[family, preview_id] = rows[0].id
            elif family == PermissionProjectionTuple.__tablename__:
                fact = records[family, preview_id]["after_fact"]
                op_id = mappings.get((PermissionProjectionOperation.__tablename__, fact["operation_id"]))
                if op_id not in operations:
                    blocked("after_tuple_operation_missing")
                matches = [
                    row
                    for row in operations[op_id][1]
                    if (row.phase, row.sequence) == (fact["phase"], fact["sequence"])
                ]
                if len(matches) != 1:
                    blocked("after_tuple_identity_changed")
                mappings[family, preview_id] = matches[0].id
            elif family != PermissionProjectionOperation.__tablename__:
                blocked("after_unknown_generated_identity")

        grouped = defaultdict(list)
        for item in semantics["rows"]:
            if item["table"] not in registry:
                blocked("after_unknown_fact_family")
            grouped[item["table"]].append(item)
        verified = 0
        for family, items in grouped.items():
            model = registry[family]
            actual_rows = {}
            ids = tuple(mappings.get((family, item["id"]), item["id"]) for item in items)
            for offset in range(0, len(ids), 200):
                table = model.__table__
                rows = tuple(
                    (
                        await session.execute(select(*table.c).where(table.c.id.in_(ids[offset : offset + 200])))
                    ).mappings()
                )
                actual_rows.update((row["id"], canonical(dict(row))) for row in rows)
            for item in items:
                actual_id = mappings.get((family, item["id"]), item["id"])
                actual = actual_rows.get(actual_id)
                if "after_fact" in item:
                    expected = item["after_fact"]
                    if expected is None:
                        if actual is not None:
                            blocked("after_deleted_mirror_reappeared")
                    else:
                        expected = dict(expected)
                        expected["id"] = actual_id
                        if "operation_id" in expected:
                            expected["operation_id"] = mappings.get(
                                (PermissionProjectionOperation.__tablename__, expected["operation_id"]),
                                expected["operation_id"],
                            )
                        if family == PermissionProjectionOperation.__tablename__ and item["id"] in materialized_plans:
                            native = materialized_plans[item["id"]].model_dump()
                            for field in (
                                "idempotency_key",
                                "operator_id",
                                "request_checksum",
                                "before_checksum",
                                "after_checksum",
                            ):
                                expected[field] = native[field]
                        if actual is None or {key: actual[key] for key in expected} != expected:
                            blocked("after_permission_facts_changed")
                else:
                    selected = (
                        {key: val for key, val in actual.items() if key not in item["ignore_fields"]}
                        if actual is not None
                        else None
                    )
                    if checksum(selected) != item["after"]:
                        blocked(
                            "after_business_facts_changed",
                            table=family,
                            identity=actual_id,
                            expected_checksum=item["after"],
                            actual_checksum=checksum(selected),
                        )
                verified += 1
        # A removed original mode must leave no replacement authorization under
        # the same business identity, even if the old SQL PK is still absent.
        for item in grouped.get(ResourcePermissionMode.__tablename__, ()):
            if item.get("after_fact") is not None:
                continue
            scope = item["before_scope"]
            for model in (ResourcePermissionMode, PermissionGrant, PermissionVisibleSourceProjection):
                table = model.__table__
                if (
                    await session.execute(
                        select(table.c.id)
                        .where(
                            table.c.tenant_id == scope["tenant_id"],
                            table.c.resource_type == scope["resource_type"],
                            table.c.resource_id == scope["resource_id"],
                        )
                        .limit(1)
                    )
                ).first() is not None:
                    blocked("after_purged_scope_reappeared")

    writes = {tuple(row) for row in semantics["graph_writes"]}
    deletes = {tuple(row) for row in semantics["graph_deletes"]}
    if writes or deletes:
        present = set()
        client = getattr(runtime, "history_client", None) or runtime.client
        async for row in client.iter_tuples(consistency="HIGHER_CONSISTENCY"):
            if row.get("condition") is not None:
                blocked("after_conditional_graph")
            key = row["user"], row["relation"], row["object"]
            if key in writes or key in deletes:
                present.add(key)
        if not writes.issubset(present) or deletes.intersection(present):
            blocked("after_graph_changed")
    return {
        "schema_version": 1,
        "history_sha256": replay["history_sha256"],
        "semantic_sha256": checksum(semantics),
        "verified_fact_count": verified,
        "logical_id_map": [
            {"table": table, "preview_id": old, "actual_id": actual}
            for (table, old), actual in sorted(mappings.items())
        ],
        "native_operation_ids": sorted(operations),
        "complete": True,
    }


async def normalized_after_view(runtime, replay, semantics, receipt, operator_id):
    """Normalize declared generated identities only; preserve all other drift."""
    from collections import defaultdict

    from sqlalchemy import select

    from bisheng.knowledge.domain.repositories.unification_history_view_repository import HistoryFactView
    from bisheng.permission.domain.models import (
        PermissionGrant,
        PermissionGrantAssignee,
        PermissionProjectionOperation,
        PermissionProjectionTuple,
        PermissionVisibleSourceProjection,
        ResourcePermissionMode,
    )

    actual_receipt = await assert_history_after_facts(runtime, replay, semantics, operator_id)
    if actual_receipt != receipt:
        blocked("after_receipt_changed")
    registry = {
        model.__tablename__: model
        for model in (
            PermissionProjectionOperation,
            PermissionProjectionTuple,
            ResourcePermissionMode,
            PermissionGrant,
            PermissionGrantAssignee,
            PermissionVisibleSourceProjection,
        )
    }
    mapping = {(row["table"], row["preview_id"]): row["actual_id"] for row in receipt["logical_id_map"]}
    generated_actual = defaultdict(set)
    for (family, _preview), actual in mapping.items():
        generated_actual[family].add(actual)
    view = HistoryFactView()
    try:
        grouped = defaultdict(list)
        for item in semantics["rows"]:
            if item["table"] in registry and item.get("after_fact") is not None:
                grouped[item["table"]].append(item)
        async with global_session(runtime.sessions) as session:
            for family, items in grouped.items():
                table = registry[family].__table__
                requested = tuple(
                    {value for item in items for value in (item["id"], mapping.get((family, item["id"]), item["id"]))}
                )
                rows = {}
                for offset in range(0, len(requested), 200):
                    raw = (
                        await session.execute(select(*table.c).where(table.c.id.in_(requested[offset : offset + 200])))
                    ).mappings()
                    rows.update((row["id"], canonical(dict(row))) for row in raw)
                # Delete actual generated rows first: a permutation of generated
                # identities is legal; an unrelated row collision is not.
                for item in items:
                    preview, actual = item["id"], mapping.get((family, item["id"]), item["id"])
                    if actual != preview:
                        if preview in rows and preview not in generated_actual[family]:
                            blocked("after_logical_identity_collision")
                        view.replace(family, rows[actual], None)
                for item in items:
                    actual = mapping.get((family, item["id"]), item["id"])
                    expected = {**rows[actual], **item["after_fact"]}
                    # after_fact retains the original preview actor/checksums.
                    # Those fields were verified against the real bound actor
                    # above; they are now normalized solely for plan comparison.
                    view.replace(family, rows.get(item["id"]), expected)
        return view
    except BaseException:
        view.close()
        raise


async def replay_preview_view(runtime, replay, semantics, operator_id):
    """Project a bound replay over exact BEFORE/known native journal progress."""
    from collections import defaultdict
    from dataclasses import replace

    from sqlalchemy import select

    from bisheng.knowledge.domain.repositories.unification_history_view_repository import build_history_view
    from bisheng.permission.domain.models import (
        PermissionGrant,
        PermissionGrantAssignee,
        PermissionProjectionOperation,
        PermissionProjectionTuple,
        PermissionVisibleSourceProjection,
        ResourcePermissionMode,
    )
    from bisheng.permission.domain.services.projection_plan import (
        ProjectionPlan,
        ProjectionTupleDelta,
        normalize_projection_plan,
    )
    from bisheng.permission.domain.services.projection_service import restore_projection_plan

    if (
        semantics.get("history_sha256") != replay.get("history_sha256")
        or type(operator_id) is not int
        or operator_id <= 0
    ):
        blocked("replay_preview_identity_changed")
    if semantics.get("operator_binding") == "fixed" and semantics["operator_id"] != operator_id:
        blocked("replay_preview_operator_changed")
    plan = await restore_replay_plan(replay, sessions=runtime.sessions, for_preview=True)
    client = getattr(runtime, "history_client", None) or runtime.client
    view = await build_history_view(
        plan,
        sessions=runtime.sessions,
        client=client,
        operator_id=semantics.get("operator_id") or 0,
        logical_ids=semantics["logical_ids"],
    )
    registry = {
        model.__tablename__: model
        for model in (
            PermissionProjectionOperation,
            PermissionProjectionTuple,
            ResourcePermissionMode,
            PermissionGrant,
            PermissionGrantAssignee,
            PermissionVisibleSourceProjection,
        )
    }
    mappings, scopes, generated_actual = {}, set(), defaultdict(set)
    try:
        if sorted(view.graph_writes) != [tuple(row) for row in semantics["graph_writes"]] or sorted(
            view.graph_deletes
        ) != [tuple(row) for row in semantics["graph_deletes"]]:
            blocked("replay_preview_graph_intent_changed")
        async with global_session(runtime.sessions) as session:
            for item in semantics.get("projection_plans", ()):
                values = item["plan"]
                expected = normalize_projection_plan(
                    ProjectionPlan(
                        **{
                            **values,
                            "deltas": tuple(ProjectionTupleDelta(**row) for row in values["deltas"]),
                            "operator_id": operator_id
                            if semantics.get("operator_binding") == "apply_time"
                            else values["operator_id"],
                        }
                    )
                )
                if expected.idempotency_key.startswith("resource-purge:"):
                    dependency = int(expected.idempotency_key.removeprefix("resource-purge:"))
                    if dependency not in mappings:
                        # Its parent has not started, so this dependent action
                        # cannot have a durable operation yet.
                        continue
                    expected = replace(expected, idempotency_key="resource-purge:" + str(mappings[dependency]))
                rows = (
                    (
                        await session.execute(
                            select(PermissionProjectionOperation).where(
                                PermissionProjectionOperation.tenant_id == expected.tenant_id,
                                PermissionProjectionOperation.idempotency_key == expected.idempotency_key,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(rows) > 1:
                    blocked("replay_preview_duplicate_operation")
                if not rows:
                    continue
                operation = rows[0]
                if operation.status == "COMMIT_UNKNOWN":
                    blocked("replay_preview_commit_unknown")
                tuples = (
                    (
                        await session.execute(
                            select(PermissionProjectionTuple)
                            .where(PermissionProjectionTuple.operation_id == operation.id)
                            .order_by(PermissionProjectionTuple.sequence)
                        )
                    )
                    .scalars()
                    .all()
                )
                if (
                    operation.status not in {"PREPARED", "STAGING", "COMMITTED", "FINALIZED", "FAILED_CLOSED"}
                    or restore_projection_plan(operation, tuples) != expected
                ):
                    blocked("replay_preview_operation_changed")
                scopes.add((expected.tenant_id, *expected.scope_key.split(":", 1)))
                mappings[item["preview_operation_id"]] = operation.id
                generated_actual[operation.__tablename__].add(operation.id)
                if operation.id != item["preview_operation_id"]:
                    view.replace(operation.__tablename__, operation.model_dump(), None)
                for row in tuples:
                    generated_actual[row.__tablename__].add(row.id)
                    logical = f"{values['idempotency_key']}:{row.phase}:{row.sequence}"
                    preview_id = view.logical_ids.get((row.__tablename__, logical))
                    if preview_id is None:
                        blocked("replay_preview_tuple_changed")
                    if row.id != preview_id:
                        view.replace(row.__tablename__, row.model_dump(), None)
            # Original recovery journals are already bound by identity in replay.
            for item in (*plan.get("recoveries", ()), *plan.get("builtin_finalizations", ())):
                scopes.add((item["ledger"]["tenant_id"], *item["ledger"]["scope_key"].split(":", 1)))
            generated_modes = {
                row["preview_id"] for row in semantics["logical_ids"] if row["table"] == "resource_permission_mode"
            }
            for record in semantics["rows"]:
                family, ident = record["table"], record["id"]
                if family not in registry or family in {
                    "permission_projection_operation",
                    "permission_projection_tuple",
                }:
                    continue
                model, fact = registry[family], record.get("after_fact")
                before, _after = view.states(family, (ident,)).get(ident, (None, None))
                if family == "resource_permission_mode" and ident in generated_modes:
                    query = select(model).where(
                        model.tenant_id == fact["tenant_id"],
                        model.resource_type == fact["resource_type"],
                        model.resource_id == fact["resource_id"],
                    )
                else:
                    query = select(model).where(model.id == ident)
                rows = (await session.execute(query)).scalars().all()
                if len(rows) > 1:
                    blocked("replay_preview_duplicate_mirror")
                current = canonical(rows[0].model_dump()) if rows else None
                if current is None:
                    if before is not None and fact is not None:
                        blocked("replay_preview_original_mirror_missing")
                    continue
                closed = set(fact or before or ()) - {"create_time", "update_time"}
                actual = {key: current.get(key) for key in closed}
                original = {key: before.get(key) for key in closed} if before is not None else None
                expected = dict(fact) if fact is not None else None
                if expected is not None:
                    expected["id"] = current["id"]
                    if "operation_id" in expected:
                        expected["operation_id"] = mappings.get(expected["operation_id"], expected["operation_id"])
                if actual != original and actual != expected:
                    scope = (current.get("tenant_id"), current.get("resource_type"), current.get("resource_id"))
                    if family == "permission_grant_assignee":
                        parent = view.states("permission_grant", (current["grant_id"],)).get(
                            current["grant_id"], (None, None)
                        )[1]
                        if parent is not None:
                            scope = (parent["tenant_id"], parent["resource_type"], parent["resource_id"])
                    transient = {"projection_state", "status", "state", "version", "operation_id"}
                    stable = closed - transient - {"id"}
                    if (
                        scope not in scopes
                        or expected is None
                        or any(
                            current.get(key) != expected.get(key)
                            and (original is None or current.get(key) != original.get(key))
                            for key in stable
                        )
                        or (
                            "operation_id" in closed
                            and current["operation_id"]
                            not in {expected.get("operation_id"), (original or {}).get("operation_id")}
                        )
                        or (
                            "projection_state" in closed
                            and current["projection_state"] not in {"PENDING", "PROJECTING", "FAILED_CLOSED", "CURRENT"}
                        )
                        or (
                            "state" in closed
                            and current["state"]
                            not in {expected.get("state"), (original or {}).get("state"), "PENDING", "PENDING_DELETE"}
                        )
                        or (
                            "version" in closed
                            and current["version"]
                            not in {
                                expected.get("version"),
                                (original or {}).get("version"),
                                expected.get("version", 0) - 1,
                            }
                        )
                    ):
                        blocked("replay_preview_mirror_changed")
                if family == "resource_permission_mode" and ident in generated_modes:
                    generated_actual[family].add(current["id"])
                    if current["id"] != ident:
                        view.replace(family, current, None)
            logical_families = defaultdict(list)
            for logical in semantics["logical_ids"]:
                logical_families[logical["table"]].append(logical["preview_id"])
            for family, ids in logical_families.items():
                model = registry[family]
                for offset in range(0, len(ids), 200):
                    existing = set(
                        (
                            await session.execute(select(model.id).where(model.id.in_(ids[offset : offset + 200])))
                        ).scalars()
                    )
                    if existing - generated_actual[family]:
                        blocked("replay_preview_logical_identity_collision")
            # Reinstall the original complete after facts, since removals above
            # may share IDs with another declared generated row.
            for record in semantics["rows"]:
                family, fact = record["table"], record.get("after_fact")
                if family in registry and fact is not None:
                    previous = view.states(family, (record["id"],)).get(record["id"], (None, None))[1]
                    view.replace(family, previous, {**(previous or {}), **fact})
        return plan, view
    except BaseException:
        view.close()
        raise


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
        or payload["plan"].get("schema") not in {1, 2, 3, 4}
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
            from bisheng.permission.domain.services.maintenance_guard import acheck_transaction

            await acheck_transaction(session, global_scope=True)
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


async def hard_missing_batch(session, modes):
    """Global primary-key absence in bounded batches, with no tenant inference."""
    from collections import defaultdict
    from itertools import islice

    from sqlmodel import select

    owners, missing, iterator = business_models(), set(), iter(modes)
    while batch := tuple(islice(iterator, 200)):
        grouped = defaultdict(list)
        for mode in batch:
            owner = owners.get(mode.resource_type)
            if mode.projection_state != "CURRENT" or owner is None:
                continue
            model, parse_id = owner
            if type(mode.resource_id) is not str or not mode.resource_id:
                continue
            try:
                ident = parse_id(mode.resource_id)
            except (TypeError, ValueError):
                continue
            grouped[model].append((mode.id, ident))
        for model, batch in grouped.items():
            # The caller owns the global maintenance transaction. A physically
            # present foreign/type-mismatched row must never be called absent.
            present = set(
                (await session.exec(select(model.id).where(model.id.in_([ident for _, ident in batch])))).all()
            )
            missing.update(mode_id for mode_id, ident in batch if ident not in present)
    return missing


class _ModeRows:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        for row in self.rows:
            yield _ModeFact(**row)


class _ModeFact(SimpleNamespace):
    def model_dump(self):
        return vars(self)


async def downstream(session, target, *, ignored_modes=(), ignored_files=()):
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
            await session.exec(
                select(KnowledgeFile.id)
                .where(KnowledgeFile.knowledge_id == int(ident), KnowledgeFile.id.not_in(tuple(ignored_files)))
                .limit(1)
            )
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


async def mirrors_batch(session, targets):
    """Read exact selected buckets, with bounded predicates/pages, including foreign sources."""
    from collections import defaultdict

    from sqlalchemy import or_
    from sqlmodel import select

    from bisheng.permission.application.sql_runtime import stable_grant_key
    from bisheng.permission.domain.models import (
        PermissionGrant,
        PermissionGrantAssignee,
        PermissionVisibleSourceProjection,
        ResourcePermissionMode,
    )

    if not 1 <= len(targets) <= 50:
        raise ValueError("history mirror batch must contain 1..50 resources")

    def key(row):
        return row["tenant_id"], row["resource_type"], row["resource_id"]

    results = {key(target): {} for target in targets}
    grant_owners = {}
    for model in (ResourcePermissionMode, PermissionGrant, PermissionVisibleSourceProjection):
        grouped = defaultdict(list)
        predicates = [
            (model.tenant_id == tenant) & (model.resource_type == kind) & (model.resource_id == ident)
            for tenant, kind, ident in results
        ]
        after = None
        while True:
            query = select(model).where(or_(*predicates)).order_by(model.id).limit(200)
            if after is not None:
                query = query.where(model.id > after)
            rows = (await session.exec(query)).all()
            for row in rows:
                fact = canonical(row.model_dump())
                owner = key(fact)
                grouped[owner].append(fact)
                if model is PermissionGrant:
                    grant_owners[row.id] = owner
            if len(rows) < 200:
                break
            after = rows[-1].id
        for owner, result in results.items():
            result[model.__tablename__] = grouped[owner]
    sources = defaultdict(list)
    grant_ids = sorted(grant_owners)
    for start in range(0, len(grant_ids), 200):
        after = None
        while True:
            query = (
                select(PermissionGrantAssignee)
                .where(PermissionGrantAssignee.grant_id.in_(grant_ids[start : start + 200]))
                .order_by(PermissionGrantAssignee.id)
                .limit(200)
            )
            if after is not None:
                query = query.where(PermissionGrantAssignee.id > after)
            rows = (await session.exec(query)).all()
            for row in rows:
                # No tenant predicate: a foreign assignee is retained evidence
                # and blocks cleanup, exactly as in the original single reader.
                sources[grant_owners[row.grant_id]].append(canonical(row.model_dump()))
            if len(rows) < 200:
                break
            after = rows[-1].id
    output = []
    for target in targets:
        owner = key(target)
        result = results[owner]
        result[PermissionGrantAssignee.__tablename__] = sorted(sources[owner], key=lambda row: row["id"])
        objects = (
            f"{target['resource_type']}:{target['resource_id']}",
            *(
                "permission_grant:"
                + stable_grant_key(
                    tenant_id=target["tenant_id"],
                    resource_type=target["resource_type"],
                    resource_id=target["resource_id"],
                    model_key=grant["model_key"],
                )
                for grant in result[PermissionGrant.__tablename__]
            ),
        )
        output.append((result, objects))
    return output


async def mirrors(session, target):
    return (await mirrors_batch(session, (target,)))[0]


def fga_blocked_modes(purges, incoming_by_subject, children_by_parent, parent_deletes):
    """Propagate retained downstreams once per edge, including shared objects."""
    from collections import Counter, defaultdict, deque

    by_id = {item["mode"]["id"]: item for item in purges}
    owners = Counter(obj for item in purges for obj in item["objects"])
    object_dependents, mode_dependents = defaultdict(set), defaultdict(set)
    rejected = set()
    for ident, item in by_id.items():
        mode = item["mode"]
        for child in children_by_parent.get((mode["resource_type"], mode["resource_id"]), ()):
            if child not in by_id:
                rejected.add(ident)
            else:
                mode_dependents[child].add(ident)
        for obj in item["objects"]:
            for key in incoming_by_subject.get(obj, ()):
                if key in parent_deletes:
                    continue
                if not owners[key[2]]:
                    rejected.add(ident)
                else:
                    object_dependents[key[2]].add(ident)
    queue = deque(sorted(rejected))
    while queue:
        ident = queue.popleft()
        dependents = set(mode_dependents.get(ident, ()))
        for obj in by_id[ident]["objects"]:
            owners[obj] -= 1
            if not owners[obj]:
                dependents.update(object_dependents.get(obj, ()))
        for dependent in sorted(dependents - rejected):
            rejected.add(dependent)
            queue.append(dependent)
    return rejected


@snapshot_scope
async def capture(sessions, client, *, progress=None):
    from collections import defaultdict
    from heapq import heappop, heappush

    from sqlmodel import select

    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.repositories import unification_history_business as business
    from bisheng.knowledge.domain.repositories import unification_history_permissions as permissions
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
            "initializations": [],
            "recoveries": [],
        }
        snapshot = await business.read(session)
        store = snapshot["knowledge"].store
        after = None
        while True:
            query = select(ResourcePermissionMode).order_by(ResourcePermissionMode.id).limit(200)
            if after is not None:
                query = query.where(ResourcePermissionMode.id > after)
            page = (await session.exec(query)).all()
            store.append("permission_modes", [canonical(row.model_dump()) for row in page])
            if len(page) < 200:
                break
            after = page[-1].id
        mode_rows = store.rows("permission_modes")
        modes = _ModeRows(mode_rows)
        business_plan, virtual = business.build(snapshot, permission_modes=mode_rows)
        result["business"] = business_plan
        result["blocked"].extend(business_plan["blocked"])
        roots = business.row_index(virtual["knowledge"])
        files = business.row_index(virtual["knowledgefile"])
        retiring = {
            (row["before"]["file_type"], str(row["before"]["id"]))
            for row in business_plan["deletes"]
            if row["table"] == "knowledgefile"
        }
        ignored_files = frozenset(int(ident) for _, ident in retiring)
        mode_map = mode_rows.grouped(("resource_type", "resource_id"))
        retained_files = [item["before"] for item in business_plan["retained"]]
        retained_ids = {row["id"] for row in retained_files}
        for ident in sorted(await permissions.absent_authorization(session, retained_files)):
            detail = {"table": "knowledgefile", "id": ident, "reason": "retained_orphan_authorization_exists"}
            result["blocked"].append(detail)
            business_plan["blocked"].append(detail)
        initializations, recoveries = [], []
        parent_buffer = []
        for model, rows in (
            (KnowledgeFile, files.values()),
            (
                KnowledgeDocument,
                virtual["knowledge_document"],
            ),
        ):
            for row in rows:
                if model is KnowledgeFile and row["id"] in retained_ids:
                    continue
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
                # Retired PRIVATE libraries are preserved, not converted or
                # exposed by F118. Their historical files need no new permission
                # mode/parent projection (and must not acquire authorization).
                if roots[row["knowledge_id"]]["type"] == 2:
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
                matched_modes = mode_map.get((kind, str(row["id"])))
                mode = _ModeFact(**matched_modes[-1]) if matched_modes else None
                root_kind = "knowledge_space" if roots[row["knowledge_id"]]["type"] == 3 else "knowledge_library"
                parent = ("folder", str(path[-1])) if path else (root_kind, str(row["knowledge_id"]))
                if mode is None:
                    parent_modes = mode_map.get(parent, ())
                    initializations.append(
                        {
                            "file": row,
                            "root": roots[row["knowledge_id"]],
                            "parent_mode": parent_modes[0] if len(parent_modes) == 1 else None,
                        }
                    )
                    continue
                if (
                    mode.tenant_id == row["tenant_id"]
                    and mode.projection_state == "FAILED_CLOSED"
                    and (mode.parent_type, mode.parent_id) == parent
                    and mode.operation_id is not None
                ):
                    recoveries.append(
                        {"file": row, "root": roots[row["knowledge_id"]], "mode": canonical(mode.model_dump())}
                    )
                    continue
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
                parent_buffer.append(
                    {
                        "id": row["id"],
                        "item": {
                            "before_file": row,
                            "mode": canonical(mode.model_dump()),
                            "correct": correct,
                        },
                    }
                )
                if len(parent_buffer) == 200:
                    store.append("parent_candidates", parent_buffer)
                    parent_buffer.clear()
        store.append("parent_candidates", parent_buffer)
        result["initializations"], rejected_initializations = await permissions.initialization_candidates(
            session, initializations
        )
        result["blocked"].extend(
            {"table": "knowledgefile", "id": ident, "reason": "permission_mode_missing_ambiguous_intent"}
            for ident in rejected_initializations
        )
        parent_rows = store.rows("parent_candidates")
        children_by_parent = defaultdict(set)
        for mode in modes:
            children_by_parent[(mode.parent_type, mode.parent_id)].add(mode.id)
        remaining_spaces = {row["knowledge_id"] for row in snapshot["knowledgefile"] if row["id"] not in ignored_files}
        saved_references = business.group_index(snapshot["business_resource_reference"], ("target_type", "target_id"))
        missing_ids = await hard_missing_batch(session, modes)
        pending = []
        for mode in modes:
            target = canonical(mode.model_dump())
            planned_missing = (
                (0 if mode.resource_type == "folder" else 1, mode.resource_id) in retiring
                if mode.resource_type in {"folder", "knowledge_file"}
                else False
            )
            if mode.projection_state == "CURRENT" and (planned_missing or mode.id in missing_ids):
                pending.append(target)
        candidates = []
        for start in range(0, len(pending), 50):
            batch = pending[start : start + 50]
            facts = await mirrors_batch(session, batch)
            candidates.extend(
                {"mode": target, "sql": sql, "objects": objects}
                for target, (sql, objects) in zip(batch, facts, strict=True)
            )
        pending = candidates
        # All these facts were acquired in this same stopped-service native
        # snapshot. Apply still re-reads live downstreams before each purge.
        pending = {item["mode"]["id"]: item for item in pending}
        for ident, item in tuple(pending.items()):
            if any(row["tenant_id"] != item["mode"]["tenant_id"] for row in item["sql"]["permission_grant_assignee"]):
                result["retained_evidence"].append({"reason": "foreign_assignee", **item})
                result["blocked"].append(
                    {"table": "resource_permission_mode", "id": ident, "reason": "foreign_assignee"}
                )
                del pending[ident]
        parents_by_key = defaultdict(list)
        remaining_children, queue = {}, []
        for ident, item in pending.items():
            mode = item["mode"]
            key = (mode["resource_type"], mode["resource_id"])
            parents_by_key[key].append(ident)
            remaining_children[ident] = set(children_by_parent[key])
            if not remaining_children[ident]:
                heappush(queue, ident)
        while queue:
            ident = heappop(queue)
            item = pending[ident]
            target = item["mode"]
            kind, resource_id = target["resource_type"], target["resource_id"]
            if kind in {"knowledge_space", "knowledge_library"} and int(resource_id) in remaining_spaces:
                continue
            if kind in {"knowledge_space", "knowledge_library", "knowledge_file"} and (
                (kind, resource_id) in saved_references
                or ("knowledge_space" if kind == "knowledge_library" else kind, resource_id) in saved_references
            ):
                continue
            result["purges"].append(item)
            del pending[ident]
            for parent in parents_by_key[(target["parent_type"], target["parent_id"])]:
                if parent in pending:
                    remaining_children[parent].discard(ident)
                    if not remaining_children[parent]:
                        heappush(queue, parent)
        for ident, item in pending.items():
            result["retained_evidence"].append({"reason": "downstream_exists", **item})
            result["blocked"].append({"table": "resource_permission_mode", "id": ident, "reason": "downstream_exists"})
    # One offline Store walk; retain only relevant parent/owned-object keys.
    # External IO never holds a business SQL session.
    parents = {row["item"]["correct"][2] for row in parent_rows}
    owned = {obj for item in (*result["purges"], *result["retained_evidence"]) for obj in item.get("objects", ())}
    orphan_objects = {
        f"{'folder' if item['before']['file_type'] == 0 else 'knowledge_file'}:{item['before']['id']}"
        for item in result["business"]["deletes"]
        if item["table"] == "knowledgefile"
    }
    isolated_objects = {f"{kind}:{row['id']}" for row in retained_files for kind in ("knowledge_file", "folder")}
    isolated_objects.update(
        f"{kind}:{item['file']['id']}" for item in result["initializations"] for kind in ("knowledge_file", "folder")
    )
    from bisheng.knowledge.domain.repositories import unification_history_empty_root as f118_empty_root

    empty_roots = await f118_empty_root.candidates(sessions, result["pin"])
    empty_root_objects = f118_empty_root.objects(empty_roots)
    isolated_objects.update(empty_root_objects)
    keys_by_object, incoming_by_subject = {}, defaultdict(list)
    selected_objects = owned | orphan_objects | isolated_objects
    scanned = 0
    async for row in client.iter_tuples(consistency="HIGHER_CONSISTENCY"):
        scanned += 1
        if progress is not None and scanned % 200 == 0:
            progress("history_capture_fga", processed=scanned, unit="tuple", waiting="read")
        if row["object"] in selected_objects or (row["object"] in parents and row["relation"] == "parent"):
            keys_by_object.setdefault(row["object"], []).append(row)
        subject = row["user"].partition("#")[0]
        if subject in selected_objects:
            incoming_by_subject[subject].append((row["user"], row["relation"], row["object"]))
    for rows in keys_by_object.values():
        rows.sort(key=lambda row: (row["user"], row["relation"], row["object"]))
    for rows in incoming_by_subject.values():
        rows.sort()
    if progress is not None:
        progress("history_capture_fga", processed=scanned, total=scanned, unit="tuple", waiting="complete")
    if any(keys_by_object.get(obj) or incoming_by_subject.get(obj) for obj in empty_root_objects):
        blocked("empty_root_graph_present")
    result["empty_root_initializations"] = empty_roots
    for obj in orphan_objects - owned:
        if keys_by_object.get(obj) or incoming_by_subject.get(obj):
            detail = {
                "table": "knowledgefile",
                "id": int(obj.partition(":")[2]),
                "reason": "orphan_graph_without_permission_owner",
            }
            result["business"]["blocked"].append(detail)
            result["blocked"].append(detail)
    for obj in sorted(isolated_objects):
        if keys_by_object.get(obj) or incoming_by_subject.get(obj):
            detail = {
                "table": "knowledgefile",
                "id": int(obj.partition(":")[2]),
                "reason": "historical_isolation_graph_conflict",
            }
            result["blocked"].append(detail)
    result["recoveries"], rejected_recoveries = await permissions.capture_recoveries(
        sessions, client, recoveries, result["pin"]
    )
    result["blocked"].extend(
        {
            "table": "resource_permission_mode",
            "id": item["mode"]["id"],
            "reason": "failed_closed_original_ledger_not_recoverable",
        }
        for item in rejected_recoveries
    )
    selected = []
    for stored in parent_rows:
        item = stored["item"]
        item["correct"] = tuple(item["correct"])
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
    rejected = fga_blocked_modes(result["purges"], incoming_by_subject, children_by_parent, parent_deletes)
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
        item["incoming"] = [key for obj in item["objects"] for key in incoming_by_subject.get(obj, ())]
    for item in result["retained_evidence"]:
        if "objects" in item:
            item["tuples"] = [row for obj in item["objects"] for row in keys_by_object.get(obj, ())]
            item["incoming"] = [key for obj in item["objects"] for key in incoming_by_subject.get(obj, ())]
    from bisheng.knowledge.domain.repositories import unification_history_delete_closure as f118_delete_closure

    excluded_deletes = {(item["mode"]["resource_type"], item["mode"]["resource_id"]) for item in result["purges"]}
    excluded_deletes.update(
        ("folder" if item["before"]["file_type"] == 0 else "knowledge_file", str(item["before"]["id"]))
        for item in result.get("business", {}).get("deletes", ())
        if item["table"] == "knowledgefile"
    )
    result["delete_closures"], result["permission_delete_retained"] = await f118_delete_closure.capture(
        sessions,
        client,
        pin=result["pin"],
        excluded=excluded_deletes,
        parents=result["parents"],
        updates=result.get("business", {}).get("updates", ()),
        levels=result["levels"],
    )
    folded = {item["mode"]["id"] for item in result["delete_closures"]}
    result["parents"] = [item for item in result["parents"] if item["mode"]["id"] not in folded]
    if result["delete_closures"]:
        result["schema"] = 2  # Older scripts must reject instead of ignoring these repairs.
    result["builtin_finalizations"] = await permissions.capture_builtin_finalizations(sessions, client, result["pin"])
    if result["builtin_finalizations"] or any(
        item.get("source_status") == "FAILED_CLOSED" for item in result["delete_closures"]
    ):
        result["schema"] = 3
    if empty_roots:
        result["schema"] = 4
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


async def project_history_delete(*, plan, item, sessions, client, runtime, repository, actor, target, key):
    """Forward-recover only a frozen history delete with pre-existing missing markers.

    Ordinary permission mutations retain their fail-closed semantics. The native
    recovery service owns correction, fence checks, verification and finalization;
    this maintenance adapter only narrows which failures it may recover.
    """
    from loguru import logger

    from bisheng.common.errcode.permission import PermissionProjectionFailedError
    from bisheng.permission.domain.services.projection_plan import (
        build_projection_operation,
        normalize_projection_plan,
        projection_request_checksum,
    )
    from bisheng.permission.domain.services.projection_service import restore_projection_plan
    from bisheng.permission.domain.services.resource_lifecycle_policy import build_delete_plan

    try:
        return await runtime.project_delete(actor=actor, target=target, idempotency_key=key)
    except PermissionProjectionFailedError as error:
        operation = await repository.aget_operation_by_idempotency(key)
        # Safe diagnostics only: provider messages can contain configuration or SQL.
        error.kwargs.update(reason="history_prepare_delete_projection_failed")
        if operation is None:
            raise
        error.kwargs.update(operation_id=operation.id, projection_status=operation.status)
        if operation.status != "FAILED_CLOSED":
            raise
        details = {"operation_id": operation.id, "projection_status": operation.status}
        expected = normalize_projection_plan(
            build_delete_plan(
                target,
                store_id=plan["pin"]["store_id"],
                model_id=plan["pin"]["model_id"],
                operator_id=actor.user_id,
                idempotency_key=key,
            )
        )
        frozen = restore_projection_plan(operation, await repository.aget_operation_tuples(operation.id))
        expected_operation, _ = build_projection_operation(
            expected, request_checksum=projection_request_checksum(expected)
        )
        if (
            frozen != expected
            or operation.before_checksum != expected_operation.before_checksum
            or operation.after_checksum != expected_operation.after_checksum
        ):
            blocked("delete_recovery_ledger_changed", **details)
        marker_keys = {delta.key for delta in expected.deltas}
        original_keys = {(row["user"], row["relation"], row["object"]) for row in item["tuples"]}
        # A full pair that became MIXED is a different failure. An empty pair
        # already satisfies AFTER and ordinary reconciliation handles it.
        if len(marker_keys & original_keys) != 1:
            raise

        # Recheck after the failed attempt, before any recovery write. The frozen
        # plan must still own a hard-deleted resource and an unchanged inventory.
        async with global_session(sessions) as session:
            await unfrozen(session)
            if await read_pin(session) != plan["pin"]:
                blocked("catalog_pin_changed", **details)
            if not await hard_missing(session, item["mode"]) or await downstream(session, item["mode"]):
                blocked("purge_business_or_downstream_changed", **details)
            current, _ = await mirrors(session, item["mode"])
            if stable_mirrors(current) != stable_mirrors(item["sql"]):
                blocked("purge_mirrors_changed", **details)
        for obj in item["objects"]:
            rows = await client.read_tuples(object=obj, consistency="HIGHER_CONSISTENCY")
            if {(row["user"], row["relation"], row["object"]) for row in rows} - original_keys:
                blocked("purge_graph_changed", **details)
        preview = await runtime._projection.inspect_failed_closed_recovery(operation.id)
        if (
            preview.observed_state not in {"MIXED", "AFTER"}
            or preview.target_tuple_count != len(marker_keys)
            or any(delta.action != "DELETE" or delta.key not in marker_keys for delta in preview.correction_deltas)
        ):
            blocked("delete_recovery_not_marker_only", **details)
        logger.warning("Recovering historical delete projection operation={} scope={}", operation.id, frozen.scope_key)
        try:
            return await runtime._projection.recover_failed_closed_operation(
                operation.id, confirmation_checksum=preview.confirmation_checksum
            )
        except Exception as recovery_error:
            # Preserve the error type and traceback while reporting a safe,
            # actionable reason even when the transport error contains secrets.
            if hasattr(recovery_error, "kwargs"):
                recovery_error.kwargs.update(reason="history_prepare_delete_recovery_failed", **details)
            raise


@snapshot_scope
async def apply(plan, *, sessions, client, runtime, operator_id, physical=None, progress=None):
    from dataclasses import replace

    from sqlmodel import select, update

    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.repositories import unification_history_business as business
    from bisheng.permission.application.deleted_resource_cleanup import DeletedResourceCleanup
    from bisheng.permission.domain.repositories.deleted_resource_repository import DeletedResourceRepository
    from bisheng.permission.domain.services.permission_action_service import PermissionActor
    from bisheng.permission.domain.services.projection_plan import ProjectionTupleDelta
    from bisheng.permission.domain.services.resource_lifecycle_policy import build_delete_plan

    if plan.get("blocked") or plan.get("business", {}).get("blocked"):
        blocked("plan_has_unresolved_candidates")
    if plan.get("purpose") in {"f118-delete-closures", "f118-projection-repairs"} and any(
        plan.get(key) for key in ("levels", "parents", "purges", "initializations", "recoveries", "business")
    ):
        blocked("delete_closure_plan_scope")
    deleted_files = {
        ("folder" if item["before"]["file_type"] == 0 else "knowledge_file", str(item["before"]["id"]))
        for item in plan.get("business", {}).get("deletes", ())
        if item["table"] == "knowledgefile"
    }
    purged = {(item["mode"]["resource_type"], item["mode"]["resource_id"]) for item in plan["purges"]}
    identity = history_plan_identity(plan)[:32]
    async with global_session(sessions) as session:
        await unfrozen(session)
        if await read_pin(session) != plan["pin"]:
            blocked("catalog_pin_changed")
        if plan.get("business") and business.state_digest(await business.read(session)) not in {
            plan["business"]["before_digest"],
            plan["business"]["after_digest"],
        }:
            blocked("business_scope_changed")
        from bisheng.permission.domain.models import ResourcePermissionMode

        for kind in ("folder", "knowledge_file"):
            ids = sorted(ident for resource_type, ident in deleted_files if resource_type == kind)
            for start in range(0, len(ids), 200):
                rows = (
                    await session.exec(
                        select(ResourcePermissionMode.resource_type, ResourcePermissionMode.resource_id).where(
                            ResourcePermissionMode.resource_type == kind,
                            ResourcePermissionMode.resource_id.in_(ids[start : start + 200]),
                        )
                    )
                ).all()
                if any((row.resource_type, row.resource_id) not in purged for row in rows):
                    blocked("orphan_permission_cleanup_not_proven")
        # Physical cleanup cannot precede a changed authorization/downstream
        # scope. Resume may have advanced only the original purge journal.
        for item in plan["purges"]:
            current, _ = await mirrors(session, item["mode"])
            if current["resource_permission_mode"] and stable_mirrors(current) != stable_mirrors(item["sql"]):
                blocked("purge_mirrors_changed")
            if current["resource_permission_mode"] and current != item["sql"]:
                from bisheng.permission.domain.models import PermissionProjectionOperation

                mode = current["resource_permission_mode"][0]
                key = f"history-delete:{identity}:{item['mode']['id']}"
                original = (
                    await session.exec(
                        select(PermissionProjectionOperation).where(
                            PermissionProjectionOperation.idempotency_key == key,
                            PermissionProjectionOperation.tenant_id == item["mode"]["tenant_id"],
                        )
                    )
                ).first()
                operation = (
                    await session.get(PermissionProjectionOperation, mode["operation_id"])
                    if mode["operation_id"]
                    else None
                )
                allowed_key = (
                    key
                    if original and operation and operation.id == original.id
                    else (f"resource-purge:{original.id}" if original else None)
                )
                if (
                    operation is None
                    or operation.idempotency_key != allowed_key
                    or operation.scope_key != f"{item['mode']['resource_type']}:{item['mode']['resource_id']}"
                    or operation.store_id != plan["pin"]["store_id"]
                    or operation.model_id != plan["pin"]["model_id"]
                    or operation.expected_version not in {item["mode"]["version"], item["mode"]["version"] + 1}
                    or mode["version"] not in {operation.expected_version, operation.target_version}
                ):
                    blocked("purge_fence_changed")
    owned = {obj for item in plan["purges"] for obj in item["objects"]}
    expected_incoming = {tuple(key) for item in plan["purges"] for key in item["incoming"]}
    unowned_orphans = {f"{kind}:{ident}" for kind, ident in deleted_files - purged}
    retained_files = [item["before"] for item in plan.get("business", {}).get("retained", ())]
    from bisheng.knowledge.domain.repositories import unification_history_permissions as permissions

    async with global_session(sessions) as session:
        if await permissions.absent_authorization(session, retained_files):
            blocked("retained_orphan_authorization_changed")
    unowned_orphans.update(f"{kind}:{row['id']}" for row in retained_files for kind in ("knowledge_file", "folder"))
    if owned or unowned_orphans:
        async for row in client.iter_tuples(consistency="HIGHER_CONSISTENCY"):
            if row["object"] in unowned_orphans or row["user"].partition("#")[0] in unowned_orphans:
                blocked("orphan_graph_changed")
            if (
                row["user"].partition("#")[0] in owned
                and (row["user"], row["relation"], row["object"]) not in expected_incoming
            ):
                blocked("purge_downstream_graph_changed")
        original_keys = {
            (row["user"], row["relation"], row["object"]) for item in plan["purges"] for row in item["tuples"]
        }
        for obj in owned:
            for row in await client.read_tuples(object=obj, consistency="HIGHER_CONSISTENCY"):
                if (row["user"], row["relation"], row["object"]) not in original_keys:
                    blocked("purge_graph_changed")
    repairs = plan.get("business")
    if repairs:
        if repairs["physical"]:
            if physical is None:
                blocked("orphan_physical_adapter_required")
            await physical.apply(repairs["physical"])
        async with global_session(sessions) as session:
            await unfrozen(session)
            if await read_pin(session) != plan["pin"]:
                blocked("catalog_pin_changed")
            await business.apply(session, repairs)
    owned = {obj for item in plan["purges"] for obj in item["objects"]}
    expected_incoming = {tuple(key) for item in plan["purges"] for key in item["incoming"]}
    if owned:
        async for row in client.iter_tuples(consistency="HIGHER_CONSISTENCY"):
            if (
                row["user"].partition("#")[0] in owned
                and (row["user"], row["relation"], row["object"]) not in expected_incoming
            ):
                blocked("purge_downstream_graph_changed")
    identity = history_plan_identity(plan)[:32]
    receipts = await permissions.apply_repairs(
        plan, sessions=sessions, client=client, runtime=runtime, operator_id=operator_id
    )
    from bisheng.knowledge.domain.repositories import unification_history_delete_closure as f118_delete_closure

    receipts.extend(
        await f118_delete_closure.apply(
            plan, sessions=sessions, client=client, runtime=runtime, operator_id=operator_id
        )
    )
    receipts.extend(await permissions.apply_builtin_finalizations(plan, sessions=sessions, runtime=runtime))
    from bisheng.knowledge.domain.repositories import unification_history_empty_root as f118_empty_root

    receipts.extend(
        await f118_empty_root.apply(plan, sessions=sessions, client=client, runtime=runtime, operator_id=operator_id)
    )
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
    for index, item in enumerate(plan["purges"]):
        if progress is not None:
            progress(
                "history_purge",
                tenant_id=item["mode"]["tenant_id"],
                processed=index,
                total=len(plan["purges"]),
                unit="action",
                committed=index,
                waiting="read",
            )
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
            outcome = await project_history_delete(
                plan=plan,
                item=item,
                sessions=sessions,
                client=client,
                runtime=runtime,
                repository=repository,
                actor=actor,
                target=target,
                key=key,
            )
            receipts.append(outcome.operation_id)
            await DeletedResourceCleanup(runtime, repository=repository).run(
                actor=actor, target=target, delete_idempotency_key=key
            )
            purge = await repository.aget_operation_by_idempotency(f"resource-purge:{outcome.operation_id}")
            if purge is not None:
                receipts.append(purge.id)
        if progress is not None:
            progress(
                "history_purge",
                tenant_id=mode["tenant_id"],
                processed=index + 1,
                total=len(plan["purges"]),
                unit="action",
                committed=index + 1,
                waiting="write",
            )
    tables = {model.__tablename__: model for model in (KnowledgeFile, KnowledgeDocument)}
    for item in plan["levels"]:
        model, before = tables[item["table"]], item["before"]
        with tenant_execution_scope(before["tenant_id"]):
            async with sessions() as session, session.begin():
                from bisheng.permission.domain.services.maintenance_guard import acheck_transaction

                await acheck_transaction(session)
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
                        .values(level=item["after_level"], update_time=model.update_time)
                    )
    return {
        "levels": len(plan["levels"]),
        "parents": len(plan["parents"]),
        "purges": len(plan["purges"]),
        "initializations": len(plan.get("initializations", ())),
        "recoveries": len(plan.get("recoveries", ())),
        "empty_root_initializations": len(plan.get("empty_root_initializations", ())),
        "builtin_finalizations": len(plan.get("builtin_finalizations", ())),
        "delete_closures": len(plan.get("delete_closures", ())),
        "permission_delete_retained": len(plan.get("permission_delete_retained", ())),
        "retained": len(retained_files),
        "warnings": warning_summary(plan),
        "business_deletes": len(plan.get("business", {}).get("deletes", ())),
        "business_updates": len(plan.get("business", {}).get("updates", ())),
        "blocked": plan["blocked"],
        "permission_operation_ids": receipts,
        "preparation_complete": not plan["blocked"],
        "validation_scope": "delete_closures_only"
        if plan.get("purpose") == "f118-delete-closures"
        else ("projection_repairs_only" if plan.get("purpose") == "f118-projection-repairs" else "history_preparation"),
    }


def warning_summary(plan):
    from collections import Counter

    return dict(Counter(item["reason"] for item in plan.get("business", {}).get("warnings", ())))
