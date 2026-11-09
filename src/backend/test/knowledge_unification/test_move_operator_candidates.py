"""Native, bounded operator locators; acceptance and projection remain separate."""

import importlib
from dataclasses import FrozenInstanceError

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
from test.knowledge_unification import test_move_projection_repository as native

database = native.database
OTHER_JOB = "e0e4b210-560a-4215-b787-9ac61158b6d2"


def api():
    return importlib.import_module("bisheng.permission.application.knowledge_move_projection")


def repository():
    return native.api().MoveProjectionRepository(environment="test")


def row(ident, *, resource_id=None, resource_type="knowledge_file", tenant=101, job_id=native.JOB, operator=7):
    resource_id = str(ident if resource_id is None else resource_id)
    return {
        "id": ident,
        "tenant_id": tenant,
        "idempotency_key": native.api().operation_key(job_id, resource_type, resource_id),
        "operation_type": "RESOURCE_MOVE",
        "scope_type": "resource",
        "scope_key": f"{resource_type}:{resource_id}",
        "operator_id": operator,
        "expected_version": 4,
        "target_version": 5,
        "store_id": "actual-store",
        "model_id": "actual-model",
        "request_checksum": "a" * 64,
        "before_checksum": "b" * 64,
        "after_checksum": "c" * 64,
        "status": "PREPARED",
    }


async def insert(database, rows):
    async with database.engine.begin() as connection:
        await connection.execute(sa.insert(native.Operation), rows)


async def test_native_candidates_follow_input_order_ignore_missing_and_never_scan_other_jobs(database):
    await insert(
        database,
        [
            row(1, resource_type="folder", operator=50),
            row(2, operator=9),
            row(3, operator=7),
            row(4, resource_id=1, resource_type="folder", tenant=202, operator=999),
            row(5, resource_id=2, job_id=OTHER_JOB, operator=888),
            row(6, resource_id=999, operator=777),
        ],
    )
    bridge = api().KnowledgeMoveProjectionApplication(repository=repository())
    async with database.sessions() as session, session.begin():
        database.queries.clear()
        result = await bridge.alist_operator_candidates(
            session, job_id=native.JOB, targets=(("knowledge_file", "3"), ("folder", 1), ("knowledge_file", "99"))
        )
        assert [(r.resource_type, r.resource_id, r.operator_id) for r in result] == [
            ("knowledge_file", "3", 7),
            ("folder", "1", 50),
        ]
        assert all(type(r) is api().MoveOperatorCandidate for r in result)
        assert api().MoveOperatorCandidate is native.api().MoveOperatorCandidate
        assert not hasattr(result[0], "__dict__")
        with pytest.raises(FrozenInstanceError):
            result[0].operator_id = 999
        assert len(database.queries) == 1 and database.queries[0].lstrip().upper().startswith("SELECT")
        assert await bridge.alist_operator_candidates(session, job_id=OTHER_JOB, targets=(("folder", "1"),)) == ()


async def test_empty_and_missing_operations_are_normal_but_still_require_native_context(database):
    repo = repository()
    async with database.sessions() as session:
        with pytest.raises(PermissionPublishNotReadyError):
            await repo.alist_operator_candidates(session, job_id=native.JOB, targets=())
    async with database.sessions() as session, session.begin():
        database.queries.clear()
        assert await repo.alist_operator_candidates(session, job_id=native.JOB, targets=()) == ()
        assert not database.queries
        assert await repo.alist_operator_candidates(session, job_id=native.JOB, targets=(("folder", "1"),)) == ()
        assert len(database.queries) == 1
        with bypass_tenant_filter(), pytest.raises(PermissionPublishNotReadyError):
            await repo.alist_operator_candidates(session, job_id=native.JOB, targets=())
    with pytest.raises(PermissionPublishNotReadyError):
        await repo.alist_operator_candidates(object(), job_id=native.JOB, targets=())


@pytest.mark.parametrize(
    "targets",
    [
        [],
        (("folder", "1"),) * 201,
        (("folder", "1"), ("folder", 1)),
        (("knowledge_space", "1"),),
        (("folder", "01"),),
        (("folder", "+1"),),
        (("folder", "0"),),
        (("folder", True),),
        (("folder", "１"),),
        (("folder", "1"), ("folder", "1")),
        (("folder",),),
        ("folder",),
        (["folder", "1"],),
        (("folder", 1.0),),
    ],
)
async def test_invalid_or_duplicate_targets_reject_before_any_sql(database, targets):
    async with database.sessions() as session, session.begin():
        database.queries.clear()
        with pytest.raises((PermissionPublishNotReadyError, ValueError, TypeError)):
            await repository().alist_operator_candidates(session, job_id=native.JOB, targets=targets)
        assert not database.queries


@pytest.mark.parametrize("job_id", [None, 1, "bad", native.JOB.upper(), native.JOB.replace("-", ""), " " + native.JOB])
async def test_noncanonical_job_rejects_even_for_empty_targets(database, job_id):
    async with database.sessions() as session, session.begin():
        database.queries.clear()
        with pytest.raises((PermissionPublishNotReadyError, ValueError, TypeError)):
            await repository().alist_operator_candidates(session, job_id=job_id, targets=())
        assert not database.queries


@pytest.mark.parametrize(
    "patch",
    [
        {"operation_type": "RESOURCE_DELETE"},
        {"scope_type": "tenant"},
        {"scope_key": "folder:1"},
        {"scope_key": "knowledge_file:01"},
        {"operator_id": 0},
        {"operator_id": -1},
        {"operator_id": "invalid"},
    ],
)
async def test_selected_bad_scalar_facts_fail_closed(database, patch):
    await insert(database, [row(1), row(2)])
    async with database.engine.begin() as connection:
        await connection.execute(sa.update(native.Operation).where(native.Operation.id == 2).values(**patch))
    async with database.sessions() as session, session.begin():
        with pytest.raises(PermissionPublishNotReadyError):
            await repository().alist_operator_candidates(
                session, job_id=native.JOB, targets=(("knowledge_file", "1"), ("knowledge_file", "2"))
            )


async def test_duplicate_physical_operations_fail_even_if_deployment_unique_constraint_is_missing(database):
    loose = native.Operation.__table__.to_metadata(sa.MetaData())
    for constraint in tuple(loose.constraints):
        if isinstance(constraint, sa.UniqueConstraint):
            loose.constraints.remove(constraint)
    async with database.engine.begin() as connection:
        await connection.run_sync(native.Operation.__table__.drop)
        await connection.run_sync(loose.create)
    await insert(database, [row(1), row(2, resource_id=1)])
    async with database.sessions() as session, session.begin():
        with pytest.raises(PermissionPublishNotReadyError):
            await repository().alist_operator_candidates(session, job_id=native.JOB, targets=(("knowledge_file", "1"),))


async def test_foreign_operations_are_hidden_and_ambient_scope_is_unchanged(database):
    await insert(database, [row(1, tenant=202)])
    repo = repository()
    async with database.sessions() as session, session.begin():
        assert (
            await repo.alist_operator_candidates(session, job_id=native.JOB, targets=(("knowledge_file", "1"),)) == ()
        )
        token = set_current_tenant_id(202)
        try:
            assert (
                await repo.alist_operator_candidates(session, job_id=native.JOB, targets=(("knowledge_file", "1"),))
            )[0].operator_id == 7
        finally:
            current_tenant_id.reset(token)
        assert current_tenant_id.get() == 101


@pytest.mark.parametrize("related", ["operation", "operation_key_change", "mode", "tuple"])
async def test_relevant_pending_is_rejected_without_flush_or_overwrite(database, related):
    await native.seed(database, (native.expectation(),))
    async with database.sessions() as session, session.begin():
        if related in {"operation", "operation_key_change"}:
            pending = await session.get(native.Operation, 1)
            if related == "operation_key_change":
                pending.idempotency_key = "caller-other-key"
            else:
                pending.operator_id = 99
        elif related == "mode":
            pending = await session.get(native.Mode, 1)
            pending.parent_id = "999"
        else:
            pending = await session.get(native.TupleRow, 1)
            pending.fga_object = "caller-work"
        before = dict(sa.inspect(pending).dict)
        flushes = []
        sa.event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(1))
        database.queries.clear()
        with pytest.raises(PermissionPublishNotReadyError):
            await repository().alist_operator_candidates(session, job_id=native.JOB, targets=(("knowledge_file", "1"),))
        assert not flushes and pending in session.dirty and sa.inspect(pending).dict == before
        assert all(sql.lstrip().upper().startswith("SELECT") for sql in database.queries)
        await session.rollback()


async def test_unrelated_pending_and_identity_map_survive_without_autoflush(database):
    await insert(database, [row(1)])
    async with database.sessions() as session, session.begin():
        existing = await session.get(native.Operation, 1)
        unrelated = native.Mode(tenant_id=101, resource_type="folder", resource_id="999", mode="CUSTOM", version=1)
        session.add(unrelated)
        flushes = []
        sa.event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(1))
        assert (
            await repository().alist_operator_candidates(session, job_id=native.JOB, targets=(("knowledge_file", "1"),))
        )[0].operator_id == 7
        assert not flushes and unrelated in session.new and unrelated.id is None
        assert existing is await session.get(native.Operation, 1) and existing.operator_id == 7
        await session.rollback()


@pytest.mark.parametrize("change", ["tenant", "transaction"])
async def test_context_change_during_sql_never_returns_candidates(database, monkeypatch, change):
    await insert(database, [row(1)])
    token = None
    async with database.sessions() as session:
        await session.begin()
        original = session.execute

        async def changing_execute(*args, **kwargs):
            nonlocal token
            result = await original(*args, **kwargs)
            if change == "tenant":
                token = set_current_tenant_id(202)
            else:
                await session.commit()
                await session.begin()
            return result

        monkeypatch.setattr(session, "execute", changing_execute)
        try:
            with pytest.raises((PermissionPublishNotReadyError, ValueError)):
                await repository().alist_operator_candidates(
                    session, job_id=native.JOB, targets=(("knowledge_file", "1"),)
                )
        finally:
            if token is not None:
                current_tenant_id.reset(token)
            await session.rollback()


async def test_candidate_cannot_replace_actual_pin_tuple_checksum_and_finalized_proof(database):
    item = native.expectation()
    await native.seed(database, (item,))
    async with database.engine.begin() as connection:
        await connection.execute(sa.update(native.Operation).values(store_id="untrusted", status="STAGING"))
        await connection.execute(sa.delete(native.TupleRow))
    async with database.sessions() as session, session.begin():
        repo = repository()
        assert (await repo.alist_operator_candidates(session, job_id=native.JOB, targets=(("knowledge_file", "1"),)))[
            0
        ].operator_id == 7
        with pytest.raises(PermissionPublishNotReadyError):
            await repo.arequire_finalized(
                session, job_id=native.JOB, expectations=(item,), changes_digest=native.DIGEST
            )
