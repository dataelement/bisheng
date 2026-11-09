"""§121 independent selected files and P1 changes, rather than one DIR anchor."""

import math
import time
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Doc
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileMoveReq
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from bisheng.permission.domain.models import ResourcePermissionMode as Mode
from test.knowledge_unification import test_move_processing_admission as stages
from test.knowledge_unification import test_move_processing_items as items
from test.knowledge_unification import test_move_processing_owner as base
from test.knowledge_unification import test_move_projection_repository as native_p1
from test.knowledge_unification.test_processing_identity import request_context

store, tenant, moving, accepted, application = base.store, base.tenant, base.moving, base.accepted, base.application


@pytest.mark.parametrize("count", [401, 10001])
async def test_independent_changes_full_attempt_linear_and_actual_item_ports_constant(application, monkeypatch, count):
    app = application
    await stages.reset_to_before(app)
    ids = tuple(10000 + n for n in range(count))
    async with app.built.sessions() as session, session.begin():
        # Keep original parent Modes intact while reserving native seed's PK range.
        await session.execute(sa.update(Mode.__table__).where(Mode.tenant_id == 101).values(id=Mode.id + 1000000))
        await session.execute(
            sa.insert(base.File.__table__),
            [
                {
                    "id": ident,
                    "tenant_id": 101,
                    "knowledge_id": 10,
                    "user_id": 7,
                    "file_name": f"{ident}.txt",
                    "file_type": 1,
                    "file_level_path": "/50",
                    "level": 1,
                    "status": 2,
                }
                for ident in ids
            ],
        )
        await session.execute(
            sa.insert(Doc.__table__),
            [
                {
                    "id": 40000 + n,
                    "knowledge_id": 10,
                    "primary_version_id": 50000 + n,
                    "file_level_path": "/50",
                    "level": 1,
                }
                for n in range(count)
            ],
        )
        await session.execute(
            sa.insert(Version.__table__),
            [
                {
                    "id": 50000 + n,
                    "document_id": 40000 + n,
                    "knowledge_file_id": ident,
                    "version_no": 1,
                    "is_primary": True,
                }
                for n, ident in enumerate(ids)
            ],
        )
        await session.execute(
            sa.insert(Mode.__table__),
            [
                {
                    "id": 2000000 + n,
                    "tenant_id": 101,
                    "resource_type": "knowledge_file",
                    "resource_id": str(ident),
                    "mode": "INHERIT",
                    "parent_type": "folder",
                    "parent_id": "50",
                    "version": 4,
                    "projection_state": "CURRENT",
                }
                for n, ident in enumerate(ids)
            ],
        )
    await base.refs.seed(
        app.built,
        rows=[base.refs.binding(10 + n, ident, source_id="independent-scale-source") for n, ident in enumerate(ids)],
    )
    phases = {}
    captured = []
    count_costs = []
    batches = []

    def capture(connection, cursor, statement, params, context, many):
        context._owner_started = time.perf_counter()
        arity = len(params[0]) if many and params else len(params)
        if many:
            batches.append((statement.split()[0], len(params), arity))
        captured.append((statement, arity))

    def finished(connection, cursor, statement, params, context, many):
        if "GROUP BY knowledge_processing_item.state" in statement:
            count_costs.append((time.perf_counter() - context._owner_started) * 1000)

    async with app.built.sessions() as session:
        engine = session.bind.sync_engine

    def start():
        captured.clear()
        sa.event.listen(engine, "before_cursor_execute", capture)
        sa.event.listen(engine, "after_cursor_execute", finished)

    def stop(name):
        sa.event.remove(engine, "before_cursor_execute", capture)
        sa.event.remove(engine, "after_cursor_execute", finished)
        phases[name] = tuple(captured)

    def chat(**kwargs):
        assert len(kwargs["source_flow_ids"]) == count
        app.chat.append(kwargs)
        return count

    app.owner.chat_rehome = chat
    request = FileMoveReq(
        items=[{"id": ident, "type": "file"} for ident in ids], target_space_id=11, target_folder_id=51
    )
    start()
    with request_context(app.actor):
        precheck = await app.owner.aprecheck(10, request, identity=app.current, entry_kind="web")
        accepted = await app.owner.aaccept(
            10,
            ProcessingCreateRequest(
                confirmation_id=precheck.confirmation_id,
                plan_digest=precheck.plan_digest,
                idempotency_key="independent-selected-files",
            ),
            identity=app.current,
            entry_kind="web",
        )
    stop("precheck_accept")
    app.built.job_id = accepted.job_id
    async with app.owner._session() as session:
        job, _reference = await app.owner._job(session, accepted.job_id)
        scope = await app.owner._scope_for(session, job)
        expected, _ = await app.owner._materials(session, job, scope.parent_changes, actor_id=7)
    assert len(scope.roots) == len(scope.parent_changes) == len(expected) == count
    # Original plan builders create complete actual ledger/tuple/current Mode facts.
    async with app.built.sessions() as session, session.begin():
        for offset in range(0, count, 200):
            await session.execute(
                sa.delete(Mode.__table__).where(
                    Mode.tenant_id == 101,
                    Mode.resource_type == "knowledge_file",
                    Mode.resource_id.in_(tuple(str(ident) for ident in ids[offset : offset + 200])),
                )
            )
    monkeypatch.setattr(native_p1, "JOB", accepted.job_id)
    async with app.built.sessions() as session:
        async_engine = session.bind
    await native_p1.seed(SimpleNamespace(engine=async_engine), expected)
    start()
    lease = await app.owner.astart_attempt(accepted.job_id, expected_dispatch_revision=job.revision)
    assert lease is not None
    assert await app.owner.aensure_logical(lease) is not None
    stop("attempt_logical")
    # Measure complete ports against N independent operations. No whole-plan/manifest read.
    start()
    item_lease = await app.owner.aclaim_item(lease)
    stop("claim")
    assert item_lease is not None
    start()
    snapshot = await app.owner.aguard_item(item_lease)
    stop("guard")
    assert snapshot.leaf.target.file_id == ids[0]
    value = await items.checkpoint(app, item_lease)
    start()
    assert await app.owner.asave_item_checkpoint(item_lease, step=value.step, checkpoint=items.asdict(value))
    stop("checkpoint")
    start()
    assert await app.owner.acomplete_item(
        item_lease, source_count=0, milvus_count=0, es_count=0, source_digest="1" * 64, target_payload_digest="2" * 64
    )
    stop("ack")
    for name in ("claim", "guard", "checkpoint", "ack"):
        statements = phases[name]
        assert len(statements) < 130
        assert not any(
            "knowledge_operation_plan.parameters" in text or "scope_manifest" in text for text, _ in statements
        )
        assert max(arity for _, arity in statements) < 30
    linear_updates = {
        table: sum(text.startswith("UPDATE " + table + " SET") for text, _ in phases["attempt_logical"])
        for table in ("knowledge_file", "knowledge_document", "knowledge_processing_item")
    }
    assert set(linear_updates.values()) == {count}
    async with app.built.sessions() as session:
        current = await session.get(base.Job, accepted.job_id)
        assert current.total_count == count and current.pending_count == count - 1 and current.succeeded_count == 1
    assert len(phases["attempt_logical"]) < 100 + 150 * math.ceil(count / 200) + 3 * count
    print(
        {
            "independent_changes": count,
            "original_count_aggregate_ms": count_costs,
            "aggregate_matching_items": count,
            "linear_updates": linear_updates,
            "executemany": batches,
            "queries": {name: len(rows) for name, rows in phases.items()},
            "max_params": {name: max(arity for _, arity in rows) for name, rows in phases.items()},
        }
    )
