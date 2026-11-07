"""Native ledger evidence, not a transport outcome or caller-owned ready flag."""

import importlib
import math
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionCatalogRelease,
    PermissionProjectionOperation as Operation,
    PermissionProjectionTuple as TupleRow,
    ResourcePermissionMode as Mode,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.projection_plan import (
    build_projection_operation,
    normalize_projection_plan,
    projection_request_checksum,
)
from bisheng.permission.domain.services.resource_lifecycle_policy import build_move_plan

JOB = "ba588a35-4f48-4d46-9a11-a1282c336764"
DIGEST = "d" * 64


def api():
    return importlib.import_module("bisheng.permission.domain.repositories.move_projection_repository")


def expectation(ident=1, *, operator=7):
    before = VerifiedPermissionTarget.from_business_service(
        tenant_id=101,
        resource_type="knowledge_file",
        resource_id=str(ident),
        resource_version=4,
        parent_type="knowledge_space",
        parent_id="11",
        context_version="original-before",
    )
    after = VerifiedPermissionTarget.from_business_service(
        tenant_id=101,
        resource_type="knowledge_file",
        resource_id=str(ident),
        resource_version=4,
        parent_type="knowledge_space",
        parent_id="12",
        context_version="accepted-after",
    )
    return api().MoveProjectionExpectation(
        job_id=JOB,
        tenant_id=101,
        resource_type="knowledge_file",
        resource_id=str(ident),
        before=before,
        after=after,
        mode="CUSTOM",
        expected_permission_version=4,
        changes_digest=DIGEST,
        allowed_operator_ids=(operator,),
    )


def change(item):
    return SimpleNamespace(
        resource_type=item.resource_type,
        resource_id=int(item.resource_id),
        old_parent_type=item.before.parent_type,
        old_parent_id=int(item.before.parent_id),
        new_parent_type=item.after.parent_type,
        new_parent_id=int(item.after.parent_id),
        mode=item.mode,
        expected_permission_version=item.expected_permission_version,
    )


@pytest.fixture
async def database():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    metadata = sa.MetaData()
    models = (AuthorizationModelRelease, PermissionCatalogRelease, Operation, TupleRow, Mode)
    for model in models:
        model.__table__.to_metadata(metadata).c.id.type = sa.Integer()
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            sa.insert(AuthorizationModelRelease),
            dict(
                id=1,
                environment="test",
                store_id="actual-store",
                model_id="actual-model",
                model_version="f048",
                model_checksum="a" * 64,
                required_relations_checksum="b" * 64,
                openfga_version="1",
                status="ACTIVE",
            ),
        )
        await connection.execute(
            sa.insert(PermissionCatalogRelease),
            dict(
                id=1,
                release_key="actual-current",
                version=1,
                status="CURRENT",
                write_fenced=False,
                required_authorization_model_release_id=1,
                draft_owner_id=7,
                idempotency_key="catalog",
                checksum="c" * 64,
            ),
        )
    queries = []
    sa.event.listen(engine.sync_engine, "before_cursor_execute", lambda c, u, sql, p, x, m: queries.append(sql))

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    token = set_current_tenant_id(101)
    try:
        yield SimpleNamespace(engine=engine, sessions=sessions, queries=queries)
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()


async def seed(database, items, *, status="FINALIZED", commit="f" * 64):
    operations, tuples, modes = [], [], []
    for offset, item in enumerate(items, 1):
        plan = normalize_projection_plan(
            build_move_plan(
                item.after,
                old_parent=(item.before.parent_type, item.before.parent_id),
                new_parent=(item.after.parent_type, item.after.parent_id),
                mode=item.mode,
                store_id="actual-store",
                model_id="actual-model",
                operator_id=item.allowed_operator_ids[0],
                idempotency_key=f"knowledge-move:{JOB}:{item.resource_type}:{item.resource_id}",
            )
        )
        operation, rows = build_projection_operation(plan, request_checksum=projection_request_checksum(plan))
        operation.id, operation.status, operation.commit_checksum = offset, status, commit
        operations.append(operation.model_dump(exclude={"create_time", "update_time"}))
        for row in rows:
            row.operation_id, row.status = offset, "VERIFIED"
            tuples.append(row.model_dump(exclude={"id", "create_time", "update_time"}))
        modes.append(
            dict(
                id=offset,
                tenant_id=101,
                resource_type=item.resource_type,
                resource_id=item.resource_id,
                mode=item.mode,
                parent_type=item.after.parent_type,
                parent_id=item.after.parent_id,
                version=plan.target_version,
                projection_state="CURRENT",
                operation_id=offset,
            )
        )
    async with database.engine.begin() as connection:
        await connection.execute(sa.insert(Operation), operations)
        await connection.execute(sa.insert(TupleRow), tuples)
        await connection.execute(sa.insert(Mode), modes)


async def test_actual_finalized_current_ledger_is_same_transaction_and_issuer_evidence(database):
    item, repository = expectation(), api().MoveProjectionRepository(environment="test")
    await seed(database, (item,))
    async with database.sessions() as session, session.begin():
        evidence = await repository.arequire_finalized(session, job_id=JOB, expectations=(item,), changes_digest=DIGEST)
        assert evidence.count == 1
        repository.assert_current(
            evidence, session, job_id=JOB, expected_changes=(change(item),), changes_digest=DIGEST
        )
        with pytest.raises(PermissionPublishNotReadyError):
            api().MoveProjectionRepository(environment="test").assert_current(
                evidence, session, job_id=JOB, expected_changes=(change(item),), changes_digest=DIGEST
            )
        with pytest.raises(PermissionPublishNotReadyError):
            repository.assert_current(
                replace(evidence), session, job_id=JOB, expected_changes=(change(item),), changes_digest=DIGEST
            )
    async with database.sessions() as session, session.begin():
        with pytest.raises(PermissionPublishNotReadyError):
            repository.assert_current(
                evidence, session, job_id=JOB, expected_changes=(change(item),), changes_digest=DIGEST
            )


@pytest.mark.parametrize("status", ["PREPARED", "STAGING", "COMMIT_UNKNOWN", "COMMITTED", "FAILED_CLOSED"])
async def test_transport_or_nonterminal_ledger_is_never_ready(database, status):
    item = expectation()
    await seed(database, (item,), status=status)
    async with database.sessions() as session, session.begin():
        with pytest.raises(PermissionPublishNotReadyError):
            await (
                api()
                .MoveProjectionRepository(environment="test")
                .arequire_finalized(session, job_id=JOB, expectations=(item,), changes_digest=DIGEST)
            )


@pytest.mark.parametrize(
    "table,patch",
    [
        (Operation, {"commit_checksum": None}),
        (Operation, {"commit_checksum": "not-an-ack"}),
        (Operation, {"operator_id": 999}),
        (Operation, {"store_id": "foreign-store"}),
        (Operation, {"model_id": "foreign-model"}),
        (Operation, {"before_checksum": "a" * 64}),
        (Operation, {"after_checksum": "b" * 64}),
        (Operation, {"request_checksum": "c" * 64}),
        (Operation, {"target_version": 99}),
        (Operation, {"scope_key": "folder:1"}),
        (Mode, {"version": 99}),
        (Mode, {"projection_state": "PROJECTING"}),
        (Mode, {"parent_id": "999"}),
        (Mode, {"operation_id": None}),
        (Mode, {"mode": "INHERIT"}),
        (PermissionCatalogRelease, {"write_fenced": True}),
        (AuthorizationModelRelease, {"status": "RETIRED"}),
    ],
)
async def test_durable_mismatch_fails_closed(database, table, patch):
    item = expectation()
    await seed(database, (item,))
    async with database.engine.begin() as connection:
        await connection.execute(sa.update(table).values(**patch))
    async with database.sessions() as session, session.begin():
        with pytest.raises(PermissionPublishNotReadyError):
            await (
                api()
                .MoveProjectionRepository(environment="test")
                .arequire_finalized(session, job_id=JOB, expectations=(item,), changes_digest=DIGEST)
            )


async def test_tuple_payload_tamper_is_not_hidden_by_matching_outcome_or_commit_checksum(database):
    item = expectation()
    await seed(database, (item,))
    async with database.engine.begin() as connection:
        await connection.execute(sa.update(TupleRow).where(TupleRow.id == 1).values(fga_object="knowledge_file:999"))
    async with database.sessions() as session, session.begin():
        with pytest.raises(PermissionPublishNotReadyError):
            await (
                api()
                .MoveProjectionRepository(environment="test")
                .arequire_finalized(session, job_id=JOB, expectations=(item,), changes_digest=DIGEST)
            )


async def test_all_changes_coverage_cannot_be_replaced_by_one_page_and_a_full_digest(database):
    items, repository = tuple(expectation(i) for i in range(1, 202)), api().MoveProjectionRepository(environment="test")
    await seed(database, items)
    async with database.sessions() as session, session.begin():
        subset = await repository.arequire_finalized(
            session, job_id=JOB, expectations=items[:200], changes_digest=DIGEST
        )
        with pytest.raises(PermissionPublishNotReadyError):
            repository.assert_current(
                subset, session, job_id=JOB, expected_changes=tuple(map(change, items)), changes_digest=DIGEST
            )
        evidence = await repository.arequire_finalized(session, job_id=JOB, expectations=items, changes_digest=DIGEST)
        repository.assert_current(
            evidence, session, job_id=JOB, expected_changes=tuple(map(change, items)), changes_digest=DIGEST
        )
        assert evidence.count == 201


@pytest.mark.parametrize("count", [401, 10001])
async def test_real_large_ledger_uses_bounded_batches_and_linear_sql(database, count):
    items, repository = (
        tuple(expectation(i) for i in range(1, count + 1)),
        api().MoveProjectionRepository(environment="test"),
    )
    await seed(database, items)
    database.queries.clear()
    async with database.sessions() as session, session.begin():
        evidence = await repository.arequire_finalized(session, job_id=JOB, expectations=items, changes_digest=DIGEST)
        assert evidence.count == count
    queries = database.queries
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in queries)
    assert len(queries) <= 4 + math.ceil(count / 200) * 18
    assert not any(" JOIN " in sql.upper() and "permission_projection_tuple" in sql for sql in queries)


async def test_native_reads_do_not_autoflush_unrelated_caller_pending(database):
    item = expectation()
    await seed(database, (item,))
    async with database.sessions() as session, session.begin():
        unrelated = Mode(tenant_id=101, resource_type="folder", resource_id="999", mode="CUSTOM", version=1)
        session.add(unrelated)
        flushes = []
        sa.event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(1))
        await (
            api()
            .MoveProjectionRepository(environment="test")
            .arequire_finalized(session, job_id=JOB, expectations=(item,), changes_digest=DIGEST)
        )
        assert not flushes and unrelated in session.new and unrelated.id is None
        await session.rollback()


async def test_parent_states_are_actual_current_and_empty_has_no_io(database):
    item, repository = expectation(), api().MoveProjectionRepository(environment="test")
    await seed(database, (item,))
    async with database.sessions() as session, session.begin():
        database.queries.clear()
        assert await repository.aread_parent_states(session, targets=()) == () and not database.queries
        (actual,) = await repository.aread_parent_states(session, targets=(("knowledge_file", "1"),))
        assert (actual.mode, actual.version, actual.parent_id, actual.operation_id) == ("CUSTOM", 5, "12", 1)
        with pytest.raises(PermissionPublishNotReadyError):
            await repository.aread_parent_states(session, targets=(("knowledge_file", "2"),))
        with bypass_tenant_filter(), pytest.raises(PermissionPublishNotReadyError):
            await repository.aread_parent_states(session, targets=(("knowledge_file", "1"),))
