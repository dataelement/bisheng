"""T961: bounded accepted typed membership and large real acceptance scopes."""

import math
from copy import deepcopy

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt as Retry
from test.knowledge_unification.test_move_job_reservation import (
    accepted as accepted,
)
from test.knowledge_unification.test_move_job_reservation import (
    actor,
    create,
    jobs,
)
from test.knowledge_unification.test_move_job_reservation import (
    moving as moving,
)
from test.knowledge_unification.test_move_job_reservation import (
    store as store,
)
from test.knowledge_unification.test_move_job_reservation import (
    tenant as tenant,
)


@pytest.mark.parametrize("kind,subject", [("user", 17), ("service_account", 50)])
async def test_initial_subject_comes_from_frozen_actor_never_audit_user(moving, accepted, kind, subject):
    prepared = await accepted(origin=actor(kind, subject))
    result = await create(moving, prepared.args)
    repo, _ = jobs(moving)
    async with AsyncSession(moving.engine) as session, session.begin():
        assert await repo.aoperator_membership(session, job_id=result.job.id, operator_ids=(7, 17, 50)) == frozenset(
            {subject}
        )
    assert result.job.actor_user_id == 7


async def test_all_accepted_early_retries_remain_members_and_only_bounded_references_are_read(moving, accepted):
    prepared = await accepted()
    result = await create(moving, prepared.args)
    async with AsyncSession(moving.engine) as session:
        await session.execute(sa.update(Job.__table__).where(Job.id == result.job.id).values(revision=401))
        await session.execute(
            sa.insert(Retry.__table__),
            [
                {
                    "id": f"retry-{n:08d}",
                    "tenant_id": 101,
                    "job_id": result.job.id,
                    "idempotency_key": f"key-{n}",
                    "request_hash": "f" * 64,
                    "actor_user_id": 7,
                    "actor_subject_type": "user" if n % 2 else "service_account",
                    "actor_subject_id": 17 if n < 401 else 50,
                    "actor_reference": actor("user" if n % 2 else "service_account", 17 if n < 401 else 50),
                    "expected_job_revision": n - 1,
                    "accepted_job_revision": n,
                    "item_count": 1,
                }
                for n in range(1, 402)
            ],
        )
        await session.commit()
    statements = []

    def record(_c, _cu, sql, params, _ctx, _many):
        statements.append((sql, params))

    sa.event.listen(moving.engine.sync_engine, "before_cursor_execute", record)
    repo, _ = jobs(moving)
    async with AsyncSession(moving.engine) as session, session.begin():
        actual = await repo.aoperator_membership(session, job_id=result.job.id, operator_ids=tuple(range(1, 201)))
    assert actual == frozenset({7, 17, 50})
    assert len(statements) <= 8
    for sql, _ in statements:
        assert sql.lstrip().upper() == "BEGIN" or sql.lstrip().upper().startswith("SELECT")
        selected = sql.partition("FROM")[0]
        assert "scope_manifest" not in selected and "processing_snapshot" not in selected
        assert "knowledge_operation_plan.parameters" not in selected
    # Historical expired credential_reference is an accepted fact, not restored here.
    retry_reads = [
        sql for sql, _ in statements if "actor_reference" in sql.partition("FROM")[0] and "retry_receipt" in sql
    ]
    assert len(retry_reads) <= 2 and any("GROUP BY" in sql for sql, _ in statements)


@pytest.mark.parametrize("bad", ["scalar", "reference", "future", "foreign", "null"])
async def test_invalid_retry_facts_cannot_prove_membership(moving, accepted, bad):
    prepared = await accepted()
    job = (await create(moving, prepared.args)).job
    origin = actor("service_account", 50)
    values = {
        "id": "trial",
        "tenant_id": 101,
        "job_id": job.id,
        "idempotency_key": "retry",
        "request_hash": "f" * 64,
        "actor_user_id": 7,
        "actor_subject_type": "service_account",
        "actor_subject_id": 50,
        "actor_reference": origin,
        "expected_job_revision": 0,
        "accepted_job_revision": 1,
        "item_count": 1,
    }
    if bad == "scalar":
        values["actor_subject_id"] = 17
    elif bad == "reference":
        values["actor_reference"] = deepcopy(origin)
        values["actor_reference"]["space_id"] = 11
    elif bad == "future":
        values["accepted_job_revision"] = 999
    elif bad == "foreign":
        values["tenant_id"] = 202
    else:
        values["actor_subject_id"] = values["actor_subject_type"] = None
    async with AsyncSession(moving.engine) as session:
        await session.execute(sa.update(Job.__table__).where(Job.id == job.id).values(revision=1))
        await session.execute(sa.insert(Retry.__table__).values(**values))
        await session.commit()
    repo, _ = jobs(moving)
    async with AsyncSession(moving.engine) as session, session.begin():
        if bad in ("scalar", "reference"):
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.aoperator_membership(session, job_id=job.id, operator_ids=(17, 50))
        else:
            assert await repo.aoperator_membership(session, job_id=job.id, operator_ids=(50,)) == frozenset()


@pytest.mark.parametrize("ids", [(True,), (1.0,), (0,), tuple(range(1, 202)), [7]])
async def test_invalid_candidates_are_rejected_before_io(moving, ids):
    repo, _ = jobs(moving)
    statements = []
    sa.event.listen(moving.engine.sync_engine, "before_cursor_execute", lambda *_: statements.append(1))
    async with AsyncSession(moving.engine) as session, session.begin():
        with pytest.raises(ValueError):
            await repo.aoperator_membership(session, job_id="unknown", operator_ids=ids)
    assert statements == []


async def test_empty_membership_is_zero_sql_and_does_not_assert_unknown_job_exists(moving):
    repo, _ = jobs(moving)
    statements = []
    sa.event.listen(moving.engine.sync_engine, "before_cursor_execute", lambda *_: statements.append(1))
    async with AsyncSession(moving.engine) as session:
        assert await repo.aoperator_membership(session, job_id="unknown", operator_ids=()) == frozenset()
    assert statements == []


@pytest.mark.parametrize("count", [401, 10001])
async def test_native_acceptance_and_replay_read_each_scope_linearly_not_per_item(moving, accepted, count):
    async with AsyncSession(moving.engine) as session:
        await session.execute(
            sa.insert(File.__table__),
            [
                {
                    "id": 1000 + n,
                    "tenant_id": 101,
                    "knowledge_id": 10,
                    "file_name": str(n),
                    "file_type": 1,
                    "file_level_path": "/50",
                    "level": 1,
                    "status": 2,
                }
                for n in range(count - 1)
            ],
        )
        await session.execute(
            sa.insert(Version.__table__),
            [
                {
                    "id": 20000 + n,
                    "document_id": 80,
                    "knowledge_file_id": 1000 + n,
                    "version_no": n + 3,
                    "is_primary": False,
                }
                for n in range(count - 1)
            ],
        )
        await session.commit()
    prepared = await accepted()
    statements = []
    sa.event.listen(moving.engine.sync_engine, "before_cursor_execute", lambda _c, _cu, sql, *_: statements.append(sql))
    # Measure the unchanged actual K1 path, then roll its private transaction back.
    # J1 must add only fixed SQL overhead to that same original linear work.
    _, cutover = jobs(moving)
    async with AsyncSession(moving.engine) as session, session.begin():
        transaction = await session.begin_nested()
        receipt = await cutover.aprepare_reservation(
            session,
            scope=prepared.scope,
            confirmation_id=prepared.plan.confirmation_id,
            plan_digest=prepared.plan.plan_digest,
            actor_user_id=7,
            actor_reference=prepared.origin,
        )
        await cutover.aconsume_reservation(session, receipt)
        await transaction.rollback()
    baseline = sum(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    statements.clear()
    repo, _ = jobs(moving)
    job = (await create(moving, prepared.args, repo)).job
    assert job.total_count == count and len(job.scope_manifest) == count
    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    assert baseline <= 70 + 20 * math.ceil(count / 200)
    assert len(selects) <= baseline + 10
    print({"items": count, "original_k1_selects": baseline, "j1_acceptance_selects": len(selects)})
    statements.clear()
    async with AsyncSession(moving.engine) as session, session.begin():
        assert (await repo.aget_move_request(session, **prepared.args)).reused
    assert len(statements) <= 3 and all(
        sql.lstrip().upper() == "BEGIN" or sql.lstrip().upper().startswith("SELECT") for sql in statements
    )
