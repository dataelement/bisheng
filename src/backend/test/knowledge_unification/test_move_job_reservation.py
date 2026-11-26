"""T961: actual Plan -> Job acceptance, atomicity, full hash and durable replay."""

import importlib
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.tag import TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt
from bisheng.knowledge.domain.repositories.move_cutover_repository import MoveCutoverRepository
from bisheng.knowledge.domain.repositories.operation_plan_repository import OperationPlanRepository
from bisheng.knowledge.domain.repositories.processing_job_repository import ProcessingJobRepository
from bisheng.knowledge.domain.schemas.processing_job_acceptance import (
    NewProcessingItem,
    ProcessingConfiguration,
    _digest,
    processing_manifest,
    processing_request_facts,
)
from test.knowledge_unification import test_move_scope_repository as fixtures
from test.knowledge_unification.test_processing_actor_subject import reference

store, tenant, moving = fixtures.store, fixtures.tenant, fixtures.moving


def api():
    return importlib.import_module("bisheng.knowledge.domain.repositories.move_job_repository")


def actor(kind="user", ident=7):
    value = reference(subject_type=kind, subject_id=ident)
    value.update(actor_user_id=7, space_id=10)
    return value


@pytest.fixture
async def accepted(moving, monkeypatch):
    # aiosqlite legacy mode does not begin a DB transaction for SELECT/SAVEPOINT.
    # Materialize the caller's native BEGIN so SAVEPOINT release cannot commit it.
    sa.event.listen(moving.engine.sync_engine, "begin", lambda connection: connection.exec_driver_sql("BEGIN"))
    from bisheng.core.database import tenant_filter

    monkeypatch.setattr(
        tenant_filter,
        "_tenant_aware_tables",
        tenant_filter._tenant_aware_tables | {KnowledgeProcessingRetryReceipt.__tablename__},
    )
    async with moving.engine.begin() as connection:
        await connection.run_sync(KnowledgeProcessingRetryReceipt.__table__.create)

    async def prepare(*, zero=None, origin=None):
        origin = origin or actor()
        async with AsyncSession(moving.engine, expire_on_commit=False) as session:
            if zero == "empty":
                for model in (TagLink, KnowledgeDocumentVersion, KnowledgeDocument):
                    await session.execute(sa.delete(model.__table__))
                await session.execute(sa.delete(KnowledgeFile.__table__).where(KnowledgeFile.id.in_((81, 82))))
            elif zero == "skipped":
                await session.execute(sa.update(KnowledgeFile.__table__).where(KnowledgeFile.id == 81).values(status=3))
            await session.commit()
            scope = await fixtures.load(moving, session)
            plan = await OperationPlanRepository().acreate(
                session,
                operation="move",
                space_id=10,
                actor_reference=origin,
                targets=[leaf.target for leaf in scope.leaves],
                target_revisions={"scope_digest": scope.scope_digest},
                source_revisions={"source": scope.source, "destination": scope.destination},
                parameters=scope.to_parameters(),
                impact={"logical_count": len(scope.files)},
                expires_at=datetime.now() + timedelta(hours=1),
            )
            await session.commit()
        return SimpleNamespace(
            scope=scope,
            plan=plan,
            origin=origin,
            args={
                "source_space_id": 10,
                "confirmation_id": plan.confirmation_id,
                "plan_digest": plan.plan_digest,
                "idempotency_key": "move-native",
                "actor_user_id": 7,
                "actor_reference": origin,
            },
        )

    return prepare


def jobs(moving):
    cutover = MoveCutoverRepository(scope_repository=moving.repo)
    return api().MoveJobRepository(cutover=cutover), cutover


async def create(moving, args, repo=None):
    repo = repo or jobs(moving)[0]
    async with AsyncSession(moving.engine, expire_on_commit=False) as session, session.begin():
        return await repo.acreate_move_reserved(session, **args)


async def test_full_acceptance_hash_compact_manifest_and_single_item_snapshot(moving, accepted):
    prepared = await accepted()
    job = (await create(moving, prepared.args)).job
    assert job.space_id == 11 and job.actor_reference == prepared.origin
    assert (job.actor_subject_type, job.actor_subject_id) == ("user", 7)
    assert job.state == "accepted" and job.pending_dispatch and job.started_at is job.finished_at is None
    assert job.total_count == job.pending_count == 1 and job.space_config_version == 0
    assert set(job.parameters) == {
        "move_schema",
        "operation_id",
        "confirmation_id",
        "plan_digest",
        "plan_request_hash",
        "source_space_id",
        "destination_space_id",
        "destination_folder_id",
        "scope_digest",
        "changes_digest",
        "logical_file_count",
        "logical_document_count",
        "logical_version_count",
        "index_item_count",
        "configuration",
    }
    assert set(job.parameters["configuration"]) == {
        "source_space_id",
        "destination_space_id",
        "source_model_config_revision",
        "source_index_generation",
        "destination_model_config_revision",
        "destination_index_generation",
        "source_index_digest",
        "destination_index_digest",
    }
    async with AsyncSession(moving.engine) as session:
        plan = await session.get(KnowledgeOperationPlan, prepared.plan.confirmation_id)
        rows = (await session.execute(sa.select(KnowledgeProcessingItem))).scalars().all()
        assert plan.operation_id == job.id and len(rows) == 1
        item = rows[0]
        assert set(item.processing_snapshot) == {
            "move_schema",
            "leaf",
            "file_before",
            "file_after",
            "document_after",
            "version",
            "metadata_policy",
        }
        assert item.processing_snapshot["file_before"]["user_metadata"]["lose"]["field_value"] == 17
        assert "lose" not in item.processing_snapshot["file_after"]["user_metadata"]
        assert item.processing_snapshot["metadata_policy"] == {"retained_fields": ["keep"], "removed_fields": ["lose"]}
        manifest = processing_manifest(
            11,
            [NewProcessingItem(prepared.scope.leaves[0].target, 11, item.expected_parent_id, item.processing_snapshot)],
        )
        facts = processing_request_facts(
            tenant_id=101,
            space_id=11,
            kind="move_index",
            actor_user_id=7,
            actor_reference=prepared.origin,
            parameters=job.parameters,
            manifest=manifest,
            configuration=ProcessingConfiguration(4, "generation-4"),
            space_config_version=0,
        )
        assert job.request_hash == _digest(facts) != _digest({**facts, "scope_manifest": job.scope_manifest})
        assert job.request_hash != plan.request_hash
        assert job.scope_manifest == [
            {
                **{
                    key: manifest[0][key]
                    for key in ("file_id", "document_id", "version_id", "expected_space_id", "expected_parent_id")
                },
                "processing_snapshot_digest": _digest(item.processing_snapshot),
            }
        ]


@pytest.mark.parametrize("zero", ["empty", "skipped"])
async def test_zero_items_remain_accepted_pending_without_dummy_or_implicit_ready(moving, accepted, zero):
    prepared = await accepted(zero=zero)
    job = (await create(moving, prepared.args)).job
    assert job.total_count == job.pending_count == 0 and job.scope_manifest == []
    assert job.state == "accepted" and job.pending_dispatch and job.started_at is job.finished_at is None
    assert job.parameters["logical_file_count"] >= 1
    async with AsyncSession(moving.engine) as session:
        assert not (await session.execute(sa.select(KnowledgeProcessingItem))).all()


async def test_same_and_cross_transaction_replay_survives_business_and_lease_change(moving, accepted, monkeypatch):
    prepared = await accepted()
    repo, cutover = jobs(moving)
    consume, calls = cutover.aconsume_reservation, []

    async def counted(session, receipt):
        assert session.in_nested_transaction()
        calls.append(receipt.job_id)
        return await consume(session, receipt)

    monkeypatch.setattr(cutover, "aconsume_reservation", counted)
    async with AsyncSession(moving.engine, expire_on_commit=False) as session, session.begin():
        assert await repo.aget_move_request(session, **prepared.args) is None
        first = await repo.acreate_move_reserved(session, **prepared.args)
        second = await repo.acreate_move_reserved(session, **prepared.args)
        assert second.reused and second.job.id == first.job.id
    async with AsyncSession(moving.engine) as session:
        await session.execute(
            sa.update(KnowledgeFile.__table__).where(KnowledgeFile.id == 81).values(knowledge_id=11, status=3)
        )
        await session.execute(
            sa.update(Knowledge.__table__).where(Knowledge.id == 10).values(model_config_revision=99, state=2)
        )
        await session.execute(
            sa.update(KnowledgeProcessingJob.__table__)
            .where(KnowledgeProcessingJob.id == first.job.id)
            .values(state="running", revision=8, claim_generation=2)
        )
        await session.commit()
    async with AsyncSession(moving.engine) as session, session.begin():
        replay = await repo.aget_move_request(session, **prepared.args)
        assert replay.reused and replay.job.id == first.job.id and replay.job.state == "running"
        assert (await repo.acreate_move_reserved(session, **prepared.args)).reused
    assert calls == [first.job.id]


@pytest.mark.parametrize(
    "changed", ["actor", "confirmation", "digest", "key", "hash", "compact", "subject", "plan-binding"]
)
async def test_actual_request_plan_hash_compact_and_subject_must_all_match(moving, accepted, changed):
    prepared = await accepted()
    result = await create(moving, prepared.args)
    args = deepcopy(prepared.args)
    if changed in ("actor", "confirmation", "digest", "key"):
        field, value = {
            "actor": ("actor_reference", actor("service_account", 50)),
            "confirmation": ("confirmation_id", "unrelated-plan"),
            "digest": ("plan_digest", "f" * 64),
            "key": ("idempotency_key", "other-key"),
        }[changed]
        args[field] = value
    else:
        async with AsyncSession(moving.engine) as session:
            if changed == "plan-binding":
                await session.execute(
                    sa.update(KnowledgeOperationPlan.__table__)
                    .where(KnowledgeOperationPlan.id == prepared.plan.confirmation_id)
                    .values(operation_id="different-job")
                )
            else:
                values = {
                    "hash": {"request_hash": "f" * 64},
                    "compact": {"scope_manifest": []},
                    "subject": {"actor_subject_id": 50},
                }[changed]
                await session.execute(
                    sa.update(KnowledgeProcessingJob.__table__)
                    .where(KnowledgeProcessingJob.id == result.job.id)
                    .values(**values)
                )
            await session.commit()
    with pytest.raises(Exception) as error:
        await create(moving, args)
    assert type(error.value).__module__.startswith("bisheng.common.errcode")


@pytest.mark.parametrize("failure", ["after-job", "after-consume", "other-issuer", "prior-transaction"])
async def test_private_savepoint_prevents_half_job_or_consume_after_outer_catch_commit(
    moving, accepted, monkeypatch, failure
):
    prepared = await accepted()
    repo, cutover = jobs(moving)
    if failure in ("other-issuer", "prior-transaction"):
        issuer = MoveCutoverRepository(scope_repository=moving.repo) if failure == "other-issuer" else cutover
        async with AsyncSession(moving.engine) as prior, prior.begin():
            receipt = await issuer.aprepare_reservation(
                prior,
                scope=prepared.scope,
                confirmation_id=prepared.plan.confirmation_id,
                plan_digest=prepared.plan.plan_digest,
                actor_user_id=7,
                actor_reference=prepared.origin,
            )

        async def forged(*args, **kwargs):
            return receipt

        monkeypatch.setattr(cutover, "aprepare_reservation", forged)
    else:
        original = cutover.aconsume_reservation

        async def fail(session, receipt):
            if failure == "after-consume":
                await original(session, receipt)
            raise KnowledgeOperationPlanConflictError(reason="probe_failure")

        monkeypatch.setattr(cutover, "aconsume_reservation", fail)
    async with AsyncSession(moving.engine) as session, session.begin():
        with pytest.raises(Exception) as error:
            await repo.acreate_move_reserved(session, **prepared.args)
        assert type(error.value).__module__.startswith("bisheng.common.errcode")
    async with AsyncSession(moving.engine) as session:
        assert not (await session.execute(sa.select(KnowledgeProcessingJob))).all()
        assert not (await session.execute(sa.select(KnowledgeProcessingItem))).all()
        assert (await session.get(KnowledgeOperationPlan, prepared.plan.confirmation_id)).operation_id is None


@pytest.mark.parametrize("bad", ["no-tx", "pending", "bypass"])
async def test_native_context_is_checked_before_savepoint_autoflush(moving, accepted, bad):
    from contextlib import nullcontext

    prepared = await accepted()
    repo, _ = jobs(moving)
    async with AsyncSession(moving.engine) as session:
        if bad != "no-tx":
            await session.begin()
        if bad == "pending":
            pending = KnowledgeFile(tenant_id=101, knowledge_id=10, file_name="pending")
            session.add(pending)
        with bypass_tenant_filter() if bad == "bypass" else nullcontext():
            with pytest.raises((ValueError, KnowledgeOperationPlanConflictError)):
                await repo.acreate_move_reserved(session, **prepared.args)
        if bad == "pending":
            assert pending in session.new and pending.id is None
        await session.rollback()


async def test_old_repo_has_only_explicit_thin_move_delegation_and_generic_create_stays_closed(moving, accepted):
    prepared = await accepted()
    move, _ = jobs(moving)
    configured = ProcessingJobRepository(move_jobs=move)
    async with AsyncSession(moving.engine) as session, session.begin():
        for name in ("aget_move_request", "acreate_move_reserved", "aoperator_membership"):
            params = {"job_id": "unknown", "operator_ids": (7,)} if name == "aoperator_membership" else prepared.args
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await getattr(ProcessingJobRepository(), name)(session, **params)
        assert await configured.aget_move_request(session, **prepared.args) is None
        assert (await configured.acreate_move_reserved(session, **prepared.args)).job.kind == "move_index"
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await configured.acreate(
                session,
                space_id=10,
                kind="move_index",
                idempotency_key="bypass",
                actor_user_id=7,
                actor_reference=prepared.origin,
                parameters={},
                configuration=ProcessingConfiguration(4, "generation-4"),
                items=[NewProcessingItem(prepared.scope.leaves[0].target, 10)],
            )


async def test_successful_reservation_is_rolled_back_by_the_external_native_transaction(moving, accepted):
    prepared = await accepted()
    repo, _ = jobs(moving)
    async with AsyncSession(moving.engine) as session:
        transaction = await session.begin()
        result = await repo.acreate_move_reserved(session, **prepared.args)
        job_id = result.job.id
        assert session.in_transaction() and not session.in_nested_transaction()
        await transaction.rollback()
    async with AsyncSession(moving.engine) as session:
        assert await session.get(KnowledgeProcessingJob, job_id) is None
        assert not (await session.execute(sa.select(KnowledgeProcessingItem))).all()
        assert (await session.get(KnowledgeOperationPlan, prepared.plan.confirmation_id)).operation_id is None


async def test_replay_does_not_flush_or_refresh_unrelated_pending_state(moving, accepted):
    prepared = await accepted()
    original = await create(moving, prepared.args)
    repo, _ = jobs(moving)
    async with AsyncSession(moving.engine) as session, session.begin():
        cached = await session.get(KnowledgeFile, 82)
        cached.remark = "caller pending"
        pending = KnowledgeFile(tenant_id=101, knowledge_id=10, file_name="pending")
        session.add(pending)
        statements = []
        sa.event.listen(
            moving.engine.sync_engine, "before_cursor_execute", lambda _c, _cu, sql, *_: statements.append(sql)
        )
        replay = await repo.aget_move_request(session, **prepared.args)
        assert replay.reused and replay.job.id == original.job.id
        assert cached in session.dirty and cached.remark == "caller pending"
        assert pending in session.new and pending.id is None
        assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
        await session.rollback()


async def test_actual_web_snapshot_removal_policy_keeps_original_system_metadata(moving, accepted):
    async with AsyncSession(moving.engine) as session:
        source = await session.get(Knowledge, 10)
        source.metadata_fields = [
            *source.metadata_fields,
            {"field_name": "source_url", "field_type": "string"},
            {"field_name": "html_snapshot_object_name", "field_type": "string"},
        ]
        await session.execute(sa.update(KnowledgeFile.__table__).where(KnowledgeFile.id == 82).values(status=2))
        await session.commit()
    prepared = await accepted()
    job = (await create(moving, prepared.args)).job
    assert job.total_count == 2
    async with AsyncSession(moving.engine) as session:
        rows = (await session.execute(sa.select(KnowledgeProcessingItem))).scalars().all()
        web = next(row.processing_snapshot for row in rows if row.file_id == 82)
        assert web["metadata_policy"]["removed_fields"] == ["lose"]
        assert web["file_after"]["user_metadata"]["source_url"] == "https://private.invalid"
        assert web["file_after"]["user_metadata"]["html_snapshot_object_name"] == "snap/82"
